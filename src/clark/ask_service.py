"""ask: the logic of POST /api/ask, GET /api/ask/status, POST /api/ask/stop and POST /api/ask/change/dry and /apply (#47c, #47d,
#47e). Unguarded; server.py only routes to it. It never opens the database for writing: a change the answer suggests comes back as
data, and is saved only by the person's Apply, through ask_apply.AskApply and changes.make_ask_change (the one save path).

A SUGGESTED CHANGE IS HELD HERE, NOT TAKEN FROM THE PAGE (#47e). When an answer suggests changes, the server keeps them in memory
under a random `reply` ID for REPLY_MINUTES, with the project and whether passages from the project's saved folders were sent with
the question (`from_source`). The dry run takes only {project, reply}: the page can't send a change of its own, and has no field
that could clear the mark. A change from an answer that read the person's files always needs the separate Confirm, whether the
answer cited the file or not (a file it was given can steer it without being cited). Each reply's dry run is made once; Apply
takes the offer the dry run gave, used once (ask_apply.py). Neither route ever asks the provider.

THE SWITCH IS HONOURED HERE, ON THE SERVER (review note). Before anything is read for a question, and again just
before the request goes to the provider, the store's switch is read (`store.ask_enabled()`, which reads as off when it cannot
say). While it is off the provider is never asked, so "nothing is sent while asking is off" holds for any caller: the page, a
stale tab or anything else that can reach the route.

WHAT IS SENT. The question, the chat's earlier turns as the page holds them (they are kept nowhere else), and passages built only
from what the published file would carry (ask_data.py, through publish.select), and passages from the project's own saved
folders (ask_passages.py, every file opened again through reach.read_bytes; PDF is not supported yet and is counted). The
folders are read for the open project only. The reply carries how many files were left out for safety.

READ ONLY. The database is only ever opened read-only here (`connect(path, readonly=True)`), so nothing in this module can write
it, even by mistake: a source test in tests/test_ask_route.py fails if an ask module opens it any other way.

Every answer is (status, {ok, ...}) with plain words; a refusal also has a stable `code`. No question, passage, reply or path is
logged or kept.
"""
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from clark import ask, ask_apply, ask_data, ask_passages, platform, publish, secret_screen
from clark.store import Store, connect

PROJECT_CODE = re.compile(r"[A-Z][A-Z0-9]{2,6}")
MESSAGES = {
    "bad_request": "That question could not be read. Nothing was sent. Reload the page and ask again.",
    "bad_project_code": "That isn't a project here. Nothing was sent.",
    "project_not_found": "That project isn't here. Nothing was sent.",
    "project_archived": "That project is archived. Restore it before asking about it. Nothing was sent.",
    "asking_off": "Asking is off, so nothing was sent. Turn it on in Settings to ask questions.",
    "busy": "The saved data could not be opened just now. Wait a moment and try again. Nothing was sent.",
    "not_running": "No question is being answered just now.",
    "stopping": "Stopping.",
    "change_bad_request": "That change could not be read. Nothing was changed. Reload the page and ask again.",
    "no_reply": "That answer's changes are no longer waiting. Nothing was changed. Ask again.",
    "shown_already": "Those changes were shown already. Nothing was changed. Ask again to see them afresh.",
    "folders_unreadable": "Your folders couldn't be read just now, so nothing was sent. Try again, or remove a folder in Settings.",
}
FIELDS = {"project", "question", "earlier"}
DRY_FIELDS = {"project", "reply"}
APPLY_FIELDS = {"project", "offer", "confirm"}
REPLY_MINUTES = ask_apply.OFFER_MINUTES
MAX_REPLIES = 20
PASSAGE_SHOWN = 600        # characters of a source passage shown beside a change that came from it
PROJECT_SHARE = 25000      # characters of the budget the project's own data may take; the folders get the rest


class AskService:
    """`db_path` is the database; `provider` an ask.Provider (the one provider module's in clark; a stub in tests); `onedrive_roots` as
    the launcher's."""

    def __init__(self, db_path, provider, onedrive_roots=None, *, data_dir=None, home=None, applier=None, clock=time.monotonic):
        self.db_path = Path(db_path)
        self.data_dir = Path(data_dir) if data_dir else self.db_path.parent
        self.home = home
        self.provider = provider
        self.onedrive_roots = list(platform.onedrive_roots() if onedrive_roots is None else onedrive_roots)
        self.lock = threading.Lock()                 # the store is opened by one question at a time
        self.applier = applier or ask_apply.AskApply(self.db_path, self.onedrive_roots)
        self.clock = clock
        self.replies = {}                            # reply ID -> Held: the changes an answer suggested, kept on the server
        self.replies_lock = threading.Lock()

    def fail(self, code, message=None):
        return {"ok": False, "code": code, "message": message or MESSAGES[code]}

    def reader(self):
        """The store, opened read-only (a write through it fails in SQLite itself)."""
        return Store(connect(self.db_path, readonly=True), self.db_path, self.onedrive_roots)

    def enabled(self):
        """The switch, read now from the store; off when the store can't be opened or can't say (never fails open)."""
        try:
            store = self.reader()
        except (sqlite3.Error, OSError, TypeError):
            return False
        try:
            return store.ask_enabled() is True
        except Exception:  # noqa: BLE001  a switch that can't be read is off
            return False
        finally:
            store.close()

    # ----- GET /api/ask/status -----
    def status(self, *_ignored):
        on = self.enabled()
        st = ask.answer_status(self.provider) if on else {"connected": False, "why": MESSAGES["asking_off"]}
        return 200, {"ok": True, "ask_enabled": on, "connected": st["connected"], "why": st["why"]}

    # ----- POST /api/ask/stop -----
    def stop(self, body=None):
        if body not in (None, {}):
            return 400, self.fail("bad_request")
        stop = getattr(self.provider, "stop", None)
        running = bool(stop()) if callable(stop) else False
        return 200, {"ok": True, "stopped": running, "message": MESSAGES["stopping" if running else "not_running"]}

    # ----- POST /api/ask -----
    def read_body(self, body):
        """(project, question, earlier) or None for a body of the wrong shape."""
        if not isinstance(body, dict) or not set(body) <= FIELDS or not {"project", "question"} <= set(body):
            return None
        code, question, earlier = body["project"], body["question"], body.get("earlier", [])
        if not isinstance(question, str) or not isinstance(earlier, list):
            return None
        turns = []
        for t in earlier:
            if not (isinstance(t, dict) and set(t) == {"role", "text"} and t["role"] in ask.ROLES and isinstance(t["text"], str)):
                return None
            turns.append((t["role"], t["text"]))
        return code, question, turns

    def ask(self, body):
        got = self.read_body(body)
        if got is None:
            return 400, self.fail("bad_request")
        code, question, earlier = got
        if not isinstance(code, str) or not PROJECT_CODE.fullmatch(code):
            return 400, self.fail("bad_project_code")
        if not self.enabled():                       # the gate: nothing is read for the question, nothing is sent
            return 409, self.fail("asking_off")
        with self.lock:
            try:
                store = self.reader()
            except (sqlite3.Error, OSError, TypeError):
                return 409, self.fail("busy")
            try:
                row = store.read("projects", ref=code)
                if row is None:
                    return 404, self.fail("project_not_found")
                if row.get("archived"):
                    return 409, self.fail("project_archived")
                try:
                    data = ask_data.project_data(store, code, question, PROJECT_SHARE)
                except publish.PublishError:
                    return 404, self.fail("project_not_found")
                folders = [r["path"] for r in store.read("source_folders", code) if r.get("project", code) == code]
            finally:
                store.close()
        used = sum(len(p.text) for p in data.passages)         # the folders get what the project's own data left of the budget
        try:
            found = ask_passages.folder_data(folders, self.data_dir, question, ask.BUDGET - used, self.home,
                                             ask.MAX_PASSAGES - len(data.passages))
        except Exception:                            # noqa: BLE001 a folder that fails in a way not foreseen sends nothing
            return 200, self.fail("folders_unreadable")
        try:
            request = ask.build_request(question, tuple(data.passages) + tuple(found.passages), earlier)
        except ask.AskRefused as e:
            return 400, self.fail("refused", str(e))
        facts = data.facts
        if not self.enabled():                       # the gate again, just before anything leaves: a switch turned off meanwhile wins
            return 409, self.fail("asking_off")
        reply = ask.ask_provider(self.provider, request, codes=(code,), exists=lambda ref: ref in facts,
                                 facts=lambda ref: facts.get(ref))
        if isinstance(reply, ask.Failure):
            out = {"ok": False, "code": "no_answer", "message": reply.message}
            offer = getattr(reply, "offer", ())       # #54: a limit offers other models; the person chooses, nothing switches
            if offer:
                out["code"], out["offer"] = "limit", [dict(o) for o in offer]
            return 200, out
        notes = [n for n in (ask.dropped_note(request.dropped_turns),
                             left_out_note(data.left_out + found.left_out), *folder_notes(found)) if n]
        folder_ids = {pid for pid, _label in request.passages[len(data.passages):]}
        texts = {pid: p.text for (pid, _label), p in zip(request.passages, tuple(data.passages) + tuple(found.passages))}
        held = self.hold(code, reply, request, folder_ids, texts) if reply.changes else None
        return 200, {"ok": True, "answer": reply.answer, "parsed": reply.parsed, "cites": list(reply.cites),
                     "sources": [{"id": pid, "label": label} for pid, label in request.passages if pid in reply.cites],
                     "flags": [{"kind": f.kind, "ref": f.ref, "message": f.message} for f in reply.flags],
                     "changes": [dict(c) for c in reply.changes], "notes": notes, "reply": held,
                     "left_out_for_safety": found.safety}

    # ----- the changes an answer suggested, held on the server (#47e) -----
    def hold(self, code, reply, request, folder_ids, texts):
        """Keep a reply's changes under a new reply ID, marked from_source when any folder passage was sent. The passages shown
        beside a change are the folder passages it names or the answer cites (their labels and the start of their text)."""
        labels = dict(request.passages)
        shown = [pid for pid in dict.fromkeys([c.get("source") for c in reply.changes] + list(reply.cites))
                 if isinstance(pid, str) and pid in folder_ids]
        passages = tuple({"id": pid, "label": labels[pid], "text": texts.get(pid, "")[:PASSAGE_SHOWN]} for pid in shown)
        entry = Held(code, tuple(dict(c) for c in reply.changes), bool(folder_ids), passages, self.clock())
        with self.replies_lock:
            now = self.clock()
            for k in [k for k, h in self.replies.items() if now - h.at > REPLY_MINUTES * 60]:
                del self.replies[k]
            while len(self.replies) >= MAX_REPLIES:
                del self.replies[next(iter(self.replies))]
            key = secrets.token_urlsafe(16)
            self.replies[key] = entry
            return key

    # ----- POST /api/ask/change/dry -----
    def change_dry(self, body):
        """{project, reply} -> the dry run of each change that answer suggested: {ok, plans: [...], from_source, passages}. Each
        plan is an offer (before and after from the data) or a plain refusal. Made once per reply; the provider is never asked."""
        if not isinstance(body, dict) or set(body) != DRY_FIELDS or not all(isinstance(body[k], str) for k in DRY_FIELDS):
            return 400, self.fail("change_bad_request")
        code = body["project"]
        if not PROJECT_CODE.fullmatch(code):
            return 400, self.fail("bad_project_code", ask_apply.NO_PROJECT)
        if not self.enabled():                       # fails closed: nothing is read for a change while asking is off
            return 409, self.fail("asking_off", ask_apply.ASKING_OFF)
        with self.replies_lock:
            held = self.replies.get(body["reply"])
            if held is None or held.project != code or self.clock() - held.at > REPLY_MINUTES * 60:
                return 409, self.fail("no_reply")
            if held.shown:
                return 409, self.fail("shown_already")
            held.shown = True
        status, out = self.applier.plan_all(code, list(held.changes), held.from_source)
        if status != 200:
            return status, out
        return 200, {"ok": True, "plans": out["plans"], "from_source": held.from_source, "passages": list(held.passages)}

    # ----- POST /api/ask/change/apply -----
    def change_apply(self, body):
        """{project, offer, confirm?} -> the change saved as one undoable step: {ok, kind, ref, apply_id, undoable, before, after}.
        `confirm` must be exactly true for a change the server marked from_source; the provider is never asked."""
        if not isinstance(body, dict) or not {"project", "offer"} <= set(body) or not set(body) <= APPLY_FIELDS:
            return 400, self.fail("change_bad_request")
        code, offer, confirm = body["project"], body["offer"], body.get("confirm", False)
        if not isinstance(code, str) or not isinstance(offer, str) or not isinstance(confirm, bool):
            return 400, self.fail("change_bad_request")
        if not PROJECT_CODE.fullmatch(code):
            return 400, self.fail("bad_project_code", ask_apply.NO_PROJECT)
        if not self.enabled():                       # and the save path reads the switch again inside its step
            return 409, self.fail("asking_off", ask_apply.ASKING_OFF)
        return self.applier.apply(offer, code, confirm=confirm)


@dataclass
class Held:
    """One answer's suggested changes, on the server: the project, the changes as the model wrote them, whether the answer was
    given passages from the person's files (the page can't clear this), those passages to show, when, and whether shown."""
    project: str
    changes: tuple
    from_source: bool
    passages: tuple
    at: float
    shown: bool = field(default=False)


def left_out_note(count):
    """The plain line for passages of the project's data that did not fit what can be sent."""
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        return ""
    return ("Some of the report was too long to send in full, so only the parts closest to your question were used.")


def folder_notes(found):
    """Plain lines about the saved folders: what was left out for safety, and the types not read."""
    out = []
    if found.safety:
        out.append(f"{found.safety} {'file was' if found.safety == 1 else 'files were'} left out for safety.")
    for label in getattr(found, "secret_labels", ()):         # #215: the file's label only, never what matched
        out.append(f"{label} was left out because it {secret_screen.REASON}. {secret_screen.NEXT_STEP}")
    if found.pdf:
        out.append(f"{found.pdf} PDF {'file was' if found.pdf == 1 else 'files were'} not read: PDF is not supported yet.")
    if found.other:
        out.append(f"{found.other} {'file was' if found.other == 1 else 'files were'} not read because of its type.")
    if found.stopped:
        out.append("Not every file in your folders was looked at.")
    return out
