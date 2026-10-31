"""Publish and To client as the server runs them (#43; BRD FR-80 to FR-83, BR-8). The routes in server.py call this and nothing else.

One class, Publisher, with three public methods (each returns (status, body) for the server to send):
- publish(body): POST /api/publish {project, to_client, on_clash?, new_name?, confirmed?}. The report is built once
  (publish.build). With To client ticked, everything that could stop the copy is decided first and nothing is written until it
  is all clear (the saved folder is still there and allowed, a taken name has been answered, the finished bytes hold nothing
  that was meant to be left out). Then the system's Save dialog chooses the Local file, Local is written and read back, the same
  bytes are copied into the client folder and read back (to_client.copy_to_client), and one `publications` row records it.
  The request never names a folder or a file: the client folder is the one saved in Settings (projects.publish_client).
- client_folder(body): POST /api/client-folder {project, action: "choose" | "clear"}. Saves or clears that folder as an
  ordinary step (so it is in history and can be undone). It never writes into the folder.
- latest(code): GET /api/publication?project=. The date and kind of the latest publication, for the report bar; no path.

This is the only module besides to_client.py that may reach a client-folder writer (a test pins it). It opens its own short-lived
store for each call (the server answers from several threads), takes no network address, and sends nothing anywhere: OneDrive's
own sync does the upload.

Standard library only, Python 3.9.
"""
import getpass
import hashlib
import re
import secrets
import shutil
import tempfile
import threading
import time
from pathlib import Path

from clark import milestones, page, platform, publish, to_client
from clark.store import Invalid, open_store

PROJECT_CODE = re.compile(r"[A-Z][A-Z0-9]{2,6}")
MIN_MARKER = 8                       # a shorter piece of text can't be searched for without finding it everywhere
TEXT_FIELDS = {"milestones": ("name", "description"), "actions": ("description",), "raid": ("description",),
               "decisions": ("decision",), "use_cases": ("title", "headline")}
NOTE_FIELDS = ("internal_note", "movement", "reasoning", "options", "response_action")      # working notes: never in a report
PICK_PROMPT = "Choose the folder OneDrive syncs for the client"
SAVE_PROMPT = "Save the report"
PREVIEW_KEEP = 4                     # previews waiting to be opened; the oldest goes first
PREVIEW_SECONDS = 120                # a preview that is not opened in this time is dropped

# What the route says, by stable `code`. The words are the product's (RULES.md): plain, "clark" in lower case. The messages of
# to_client.MESSAGES (the catalogue of the spec) are used as they are for everything that module decides.
MESSAGES = {
    "bad_project_code": "Give the project's code (3 to 7 capital letters or digits).",
    "project_not_found": "There is no project with that code.",
    "busy": "A publish is already running. Wait for it to finish, then try again.",
    "cancelled": to_client.MESSAGES["cancelled"],
    "dialog_failed": "{reason} Nothing was published.",
    "same_folder": "That is the client's folder. Save the local copy somewhere else. Nothing was published.",
    "local_not_html": "The local copy's name must end in .html. Nothing was published.",
    "local_clark_files": "That place is where clark keeps its own files. Save the local copy somewhere else. Nothing was published.",
    "local_failed": "{name} could not be saved. Check you can edit that folder and that the disk has room, then try again. Nothing was published.",
    "local_differs": "{name} was not saved as it was made (the folder may be syncing). Nothing was published. Try again.",
    "not_made": "{reason} Nothing was published.",
    "not_recorded": "Published, but clark could not record it. The files are fine; publish again to record it.",
    "done_local": "Published. Saved locally as “{name}”.",
    "look_at": " Look at: {items}.",
    "brand_link": " The web link comes from the brand's styling file, not from anything you wrote: ask whoever looks after the brand to remove it.",
    "folder_saved": "The client folder is saved.",
    "folder_cleared": "The client folder is cleared.",
    "folder_unchanged": "That is already the client folder.",
    "bad_action": "Say whether to choose a folder or clear it.",
    "client_folder_refused": "{reason}",
    "settings_failed": "The client folder could not be saved. Nothing was changed. Try again.",
    "brand_styling": "The brand's styling file has a web link in it, so the report can't go out. Ask whoever looks after the brand to remove it.",
    "page_shape": "Something is wrong inside clark. Nothing was published. Tell the clark team, and say what you were doing.",
    "db_unreadable": "The records could not be read. Restart clark and try again.",
    "preview_not_made": "The preview could not be made. {reason}",
    "preview_ready": "The preview is ready. This is the version kept on this computer, not the client's copy. It is not published.",
    "export_failed": "The workbook could not be made. Nothing was changed. Try again.",
}


# The start of each PublishError that is about clark's own page or the brand's styling, and the fixed words that stand for it.
_FAULTS = (("The brand's tokens.css", "brand_styling"), ("The page clark builds", "page_shape"),
           ("The page has a server token", "page_shape"))


def made_words(error):
    """What a PublishError says to a person. The database's own wording (it can carry a system error) and the wording about
    the brand's styling file or the shape of clark's page (internal names) are never shown: each has a fixed sentence."""
    text = str(error).rstrip()
    if text.startswith("The database could not be read"):
        return MESSAGES["db_unreadable"]
    for start, key in _FAULTS:
        if text.startswith(start):
            return MESSAGES[key]
    return text


def code_of(message):
    """The stable code for a to_client message: the name of its entry in to_client.MESSAGES (or "bad_request")."""
    for key, text in to_client.MESSAGES.items():
        if text == message:
            return key
    return "bad_request"


def _text(value):
    return value if isinstance(value, str) else None


class Markers(list):
    """The texts that must be absent, with `where`: for each, the ID of the item it came from (to name it in a refusal)."""
    where = None


def markers_for(store, code, published, template=""):
    """Text that must NOT be in the finished file, read from what the store holds and select() dropped or never carries: the ID
    and main text of every row that was left out (archived, the client flag off, hidden, a Sensitive or other excluded label),
    and every row's internal note, Movement and working notes. Texts shorter than MIN_MARKER are not used (they would be found
    anywhere); an ID always is. A note that is also in `template` (the bare page, which every file holds whatever the data)
    is not a marker either: it cannot tell a leak from the page's own words. A left-out row's text that is also part of something published (the same words in a kept
    row) is not a marker, because it may rightly be in the file. check_copy looks for each in its plain, lower-case, HTML-escaped
    and JSON-escaped spellings."""
    data = published["data"]
    kept_ids = {r["id"] for kind in publish.KINDS for r in data.get(kind, ()) if isinstance(r, dict) and "id" in r}
    kept_text = [v for kind in ("projects",) + publish.KINDS + ("workstreams",)
                 for r in ([data["project"]] if kind == "projects" else data.get(kind, ())) if isinstance(r, dict)
                 for v in r.values() if isinstance(v, str)]
    kept_text += [s.get("body") or "" for s in published.get("sections", ()) if isinstance(s, dict)]
    found, where = [], {}
    bare = to_client._key(template)

    def add(text, item):
        found.append(text)
        where.setdefault(text, item)
    for kind in publish.KINDS:
        for row in store.read(kind, project=code):
            for field in NOTE_FIELDS:
                if _text(row.get(field)) and len(row[field].strip()) >= MIN_MARKER and to_client._key(row[field].strip()) not in bare:
                    add(row[field].strip(), row.get("id"))
            if row.get("id") in kept_ids:
                continue
            add(row["id"], row["id"])
            for field in TEXT_FIELDS[kind]:
                value = (_text(row.get(field)) or "").strip()
                if len(value) >= MIN_MARKER and not any(value in text for text in kept_text):
                    add(value, row["id"])
    out = Markers(dict.fromkeys(found))
    out.where = where
    return out


class Publisher:
    """The publish routes' logic. `db_path` is the database; `onedrive_roots` as the launcher's. Seams for tests: `fs` (the disk
    the client folder is on; to_client.RealFs), `choose_save_file` and `choose_folder` (the system's dialogs), `today` (a
    function giving YYYY-MM-DD), `by_user` (who is publishing) and `data_dir` (clark's own folder, which a client folder may
    never be in)."""

    def __init__(self, db_path, onedrive_roots=None, *, fs=None, choose_save_file=None, choose_folder=None, today=None,
                 by_user=None, data_dir=None, branding=None, backups_dir=None):
        self.db_path = Path(db_path)
        self.onedrive_roots = list(platform.onedrive_roots() if onedrive_roots is None else onedrive_roots)
        self.fs = fs or to_client.RealFs()
        self.choose_save_file = choose_save_file or platform.choose_save_file
        self.choose_folder = choose_folder or platform.choose_folder
        self.today = today or milestones.today
        self.by_user = by_user or getpass.getuser
        self.data_dir = Path(data_dir) if data_dir else platform.data_dir()
        self.branding, self.backups_dir = branding, backups_dir
        self.lock = threading.Lock()          # one publish at a time
        self.previews, self.preview_lock = {}, threading.Lock()      # {nonce: (bytes, time made)}: in memory only

    def store(self):
        return open_store(self.db_path, onedrive_roots=self.onedrive_roots)

    # ----- publish -----
    def publish(self, body):
        if not self.lock.acquire(blocking=False):
            return 409, self.fail("busy")
        try:
            store = self.store()
            try:
                return self._publish(store, body if isinstance(body, dict) else {})
            finally:
                store.close()
        finally:
            self.lock.release()

    def fail(self, code, status_message=None, **extra):
        return {"ok": False, "code": code, "message": status_message or MESSAGES[code], **extra}

    def _publish(self, store, body):
        code = body.get("project")
        if not isinstance(code, str) or not PROJECT_CODE.fullmatch(code):
            return 400, self.fail("bad_project_code")
        row = store.read("projects", ref=code)
        if row is None:
            return 404, self.fail("project_not_found")
        saved = row.get("publish_client") or None
        asked = to_client.validate_request(body, saved)
        if asked["status"] != 200:
            return 400, self.fail(code_of(asked["message"]), asked["message"])
        want_client, confirmed = asked["to_client"], asked["confirmed"]
        today = str(self.today())
        try:
            built = publish.build(store, code, today, self.branding)
        except publish.PublishError as e:
            return 409, self.fail("not_made", MESSAGES["not_made"].format(reason=made_words(e)))
        week = built["project"]["week_ending"]
        body_bytes, digest = built["body"], built["sha256"]
        last = store.last_publish_folder(code)
        plan, same, markers = None, None, []
        self.folder_warning = None
        if want_client:
            early, plan, same, markers = self.client_plan(store, code, built, saved, last, today, week, body)
            if early is not None:
                return early
        # Nothing has been written. The system's own Save dialog chooses the Local file; Cancel cancels everything.
        default = publish.file_name(code, week, today)
        try:
            chosen = self.choose_save_file(SAVE_PROMPT, default, start=last)
        except platform.PlatformError as e:
            return 409, self.fail("dialog_failed", MESSAGES["dialog_failed"].format(reason=str(e).rstrip()))
        if chosen is None:
            return 200, self.fail("cancelled")
        if "\x00" in str(chosen):         # a file name cannot hold a NUL; said in words, not a fault
            return 409, self.fail("local_failed", MESSAGES["local_failed"].format(name="The file"))
        dest = Path(chosen)
        if want_client:
            # The Save window may have been open a while. What the client is to get is made again now, so a flag turned off
            # meanwhile is honoured; if anything differs, every check before the copy runs again on the new file.
            try:
                again = publish.build(store, code, today, self.branding)
            except publish.PublishError as e:
                return 409, self.fail("not_made", MESSAGES["not_made"].format(reason=made_words(e)))
            # The client folder is checked again whether or not the file changed: it may have been swapped for a link (or
            # another folder) while the window was open, and the copy goes only to the real place this check finds.
            if again["sha256"] != digest:
                built = again
                body_bytes, digest = built["body"], built["sha256"]
                week = built["project"]["week_ending"]
            early, plan, same, markers = self.client_plan(store, code, built, saved, last, today, week, body)
            if early is not None:
                return early
        if saved and self.inside_folder(dest.parent, saved):
            return 409, self.fail("same_folder")
        if dest.suffix.lower() != ".html":
            return 409, self.fail("local_not_html")
        if any(self.inside_folder(dest, own) for own in (self.data_dir, self.backups_dir) if own):
            return 409, self.fail("local_clark_files")
        written = self.write_local(dest, body_bytes, digest)
        if written is not None:
            return 409, written
        # Local is saved. The copy comes next; whatever happens to it, Local stays and the publish is logged.
        client = None
        if plan is not None:
            try:
                client = to_client.copy_to_client(
                    self.fs, plan["folder"], plan["name"], body_bytes, project=code, at=today, markers=markers,
                    replaces=plan["replaces"], confirmed=confirmed, asked=plan["asked"], local_sha256=digest,
                    guard={"data_dir": self.data_dir, "backups_dir": self.backups_dir, "identity": plan.get("identity")})
            except Exception:         # the copy was taken back by copy_to_client; Local stays and is recorded
                client = to_client.ClientResult(False, "failed", to_client.MESSAGES["copy_failed_local_kept"].format(
                    reason="something went wrong while checking it."), nothing_written=True)
        elif same is not None:
            client = same
        if client is not None and client.action in ("ask", "confirm_overwrite", "cancel"):
            # The name needed asking about after all (something appeared meanwhile): Local is saved, the copy is not made.
            client = to_client.ClientResult(False, "failed", to_client.MESSAGES["copy_failed_local_kept"].format(
                reason=client.message), nothing_written=True)
        client_path = client.path if client is not None and client.ok else None
        try:
            store.log_publication(code, dest, week, digest, self.by_user(), client_path=client_path)
        except (Invalid, OSError) as e:
            return 409, self.fail("not_recorded", MESSAGES["not_recorded"],
                                  local_saved=True, local_name=dest.name)
        if client is None:
            return 200, {"ok": True, "code": "done", "action": "done", "message": MESSAGES["done_local"].format(name=dest.name),
                         "local_name": dest.name, "to_client": False}
        status, out = self.reply(client)
        out.update(local_saved=True, local_name=dest.name, to_client=True)
        if self.folder_warning:
            out["warning"] = self.folder_warning
            out["message"] += " " + self.folder_warning
        return status, out

    def client_plan(self, store, code, built, saved, last, today, week, body):
        """Every check that stands before the copy, on the finished bytes. (early reply or None, plan, same, markers)."""
        body_bytes = built["body"]
        pre = to_client.preflight(self.fs, saved, data_dir=self.data_dir, onedrive_roots=self.onedrive_roots, local_folder=last,
                                  backups_dir=self.backups_dir)
        if not pre["ok"]:             # the folder's own message comes first, whatever the file holds
            kind, got = to_client.plan_client_copy(
                self.fs, saved_folder=saved, data=body_bytes, project=code, today=today, week_ending=week,
                data_dir=self.data_dir, onedrive_roots=self.onedrive_roots, local_folder=last, backups_dir=self.backups_dir,
                choice=body.get("on_clash"), new_name=body.get("new_name"), at=today)
            return self.reply(got), None, None, []
        self.folder_warning = pre.get("warning")
        markers = markers_for(store, code, built["published"], page.page_html(self.branding, view=True))
        problems = to_client.check_copy(body_bytes, markers=markers, folder=saved)
        if problems:
            held = to_client.MESSAGES["held_back"].format(what=to_client.held_words(problems))
            if "text that was meant to be left out" in problems:
                held += self.which_items(body_bytes, markers)
            return (409, self.result(False, "refused", held + (MESSAGES["brand_link"] if "a <link> tag" in problems else ""))), \
                None, None, markers
        kind, got = to_client.plan_client_copy(
            self.fs, saved_folder=saved, data=body_bytes, project=code, today=today, week_ending=week,
            data_dir=self.data_dir, onedrive_roots=self.onedrive_roots, local_folder=last, backups_dir=self.backups_dir,
            choice=body.get("on_clash"), new_name=body.get("new_name"), at=today)
        if kind == "stop":
            return self.reply(got), None, None, markers
        return (None, got, None, markers) if kind == "copy" else (None, None, got, markers)

    def which_items(self, body, markers):
        """" Look at: ID, ID." for the items whose left-out text is in the file (so the person can fix them), or ""."""
        where = getattr(markers, "where", None) or {}
        ids = []
        for m in to_client.markers_found(body, markers):      # one pass over the file, then a look-up for each marker
            if where.get(m) and where[m] not in ids:
                ids.append(where[m])
        return MESSAGES["look_at"].format(items=", ".join(ids[:10])) if ids else ""

    def inside_folder(self, a, b):
        """Whether folder `a` is `b` or below it (as written and with links followed; case and accent form ignored)."""
        try:
            return to_client._inside(a, b) or to_client._inside(self.fs.realpath(a), self.fs.realpath(b))
        except (OSError, ValueError):
            return False

    def write_local(self, dest, data, digest):
        """Write the Local file and read it back; None when it is good, else the failure to send."""
        try:
            platform.write_file(dest, data)
            if hashlib.sha256(dest.read_bytes()).hexdigest() != digest:
                return self.fail("local_differs", MESSAGES["local_differs"].format(name=dest.name))
        except (OSError, platform.PlatformError) as e:
            return self.fail("local_failed", MESSAGES["local_failed"].format(name=dest.name))
        return None

    def result(self, ok, action, message, **extra):
        return {"ok": ok, "code": action, "action": action, "message": message, **extra}

    def reply(self, r):
        """A ClientResult as (status, body). A question is 200 with `clash`; a refusal or failure is 409; success is 200."""
        out = self.result(r.ok, r.action, r.message)
        if r.name:
            out["name"] = r.name
        if r.action == "ask" and r.clash:
            c = r.clash
            out.update(clash=True, numbered=c.get("numbered"), can_overwrite=c.get("can_overwrite", True), note=c.get("note"))
            return 200, out
        if r.action == "cancel":
            return 200, out
        if r.ok:
            out["replaced"] = r.replaced
            return 200, out
        return 409, out

    # ----- the client folder setting -----
    def client_folder(self, body):
        body = body if isinstance(body, dict) else {}
        code, action = body.get("project"), body.get("action")
        if not isinstance(code, str) or not PROJECT_CODE.fullmatch(code):
            return 400, self.fail("bad_project_code")
        if set(body) - {"project", "action"} or action not in ("choose", "clear"):
            return 400, self.fail("bad_action")
        with self.lock:
            store = self.store()
            try:
                row = store.read("projects", ref=code)
                if row is None:
                    return 404, self.fail("project_not_found")
                saved = row.get("publish_client") or None
                if action == "clear":
                    return self.save_folder(store, code, saved, None)
                try:
                    start = saved or next(iter(self.onedrive_roots), None)
                    picked = self.choose_folder(PICK_PROMPT, start=start)
                except platform.PlatformError as e:
                    return 409, self.fail("dialog_failed", MESSAGES["dialog_failed"].format(reason=str(e).rstrip()).replace(
                        " Nothing was published.", ""))
                if picked is None:
                    return 200, {"ok": True, "changed": False, "folder": saved}
                checked = to_client.preflight(self.fs, str(picked), data_dir=self.data_dir, onedrive_roots=self.onedrive_roots,
                                              local_folder=store.last_publish_folder(code) or row.get("publish_local"),
                                              backups_dir=self.backups_dir)
                if not checked["ok"]:
                    return 409, self.fail("client_folder_refused", checked["message"])
                return self.save_folder(store, code, saved, checked["folder"], checked.get("warning"))
            finally:
                store.close()

    def save_folder(self, store, code, saved, folder, warning=None):
        if folder == saved:
            return 200, {"ok": True, "changed": False, "folder": saved, "message": MESSAGES["folder_unchanged" if folder else "folder_cleared"]}
        try:
            with store.step("dashboard", self.by_user(), place="menu") as st:
                st.update("projects", code, {"publish_client": folder})
        except Invalid as e:
            return 409, self.fail("settings_failed", MESSAGES["settings_failed"])
        return 200, {"ok": True, "changed": True, "folder": folder, "folder_name": to_client.folder_name(folder),
                     "warning": warning, "message": MESSAGES["folder_saved" if folder else "folder_cleared"]}

    # ----- preview and export (#147) -----
    def preview(self, body):
        """POST /api/preview {project}: the published page as publish would make it (publish.build), kept in memory for one visit
        to the address in `url`. No publication is logged, no number is taken, and nothing is written to any folder."""
        code = body.get("project") if isinstance(body, dict) else None
        if not isinstance(code, str) or not PROJECT_CODE.fullmatch(code):
            return 400, self.fail("bad_project_code")
        store = self.store()
        try:
            if store.read("projects", ref=code) is None:
                return 404, self.fail("project_not_found")
            try:
                built = publish.build(store, code, str(self.today()), self.branding)
            except publish.PublishError as e:
                return 409, self.fail("preview_not_made", MESSAGES["preview_not_made"].format(reason=made_words(e)))
        finally:
            store.close()
        nonce, now = secrets.token_urlsafe(24), time.monotonic()
        with self.preview_lock:
            for k in [k for k, v in self.previews.items() if now - v[1] > PREVIEW_SECONDS]:
                del self.previews[k]
            while len(self.previews) >= PREVIEW_KEEP:
                del self.previews[next(iter(self.previews))]
            self.previews[nonce] = (built["body"], now)
        return 200, {"ok": True, "code": "preview_ready", "message": MESSAGES["preview_ready"], "url": "/preview?id=" + nonce}

    def take_preview(self, nonce):
        """The page's bytes for an address from preview(), once; None when it is unknown, used or too old."""
        with self.preview_lock:
            got = self.previews.pop(nonce, None)
        return got[0] if got and time.monotonic() - got[1] <= PREVIEW_SECONDS else None

    def export(self, code):
        """GET /api/export?project=: the project's workbook (excel.export_project), made in a temporary folder that is removed
        afterwards. On success (200, {"name": "<CODE>-<date>.xlsx", "data": bytes}); a refusal is a plain sentence."""
        if not isinstance(code, str) or not PROJECT_CODE.fullmatch(code):
            return 400, self.fail("bad_project_code")
        from clark import excel         # here, not at the top: the launcher imports this module before the vendored openpyxl is reachable
        store = self.store()
        folder = None
        try:
            if store.read("projects", ref=code) is None:
                return 404, self.fail("project_not_found")
            today = str(self.today())
            folder = Path(tempfile.mkdtemp(prefix="clark-export-"))
            name, warnings = f"{code}-{today}.xlsx", []
            here = Path(self.db_path).parent                                      # beside clark.db, where the record is kept
            try:
                # The record of the export (what the import later compares with) is kept beside clark.db under the workbook's
                # SHA-256 (the browser saves the download where clark can't see, and the import finds the record by the bytes,
                # so only while the file is exactly what clark wrote: a re-save or an edit loses it, until #169 puts an id in the workbook);
                # the workbook itself stays in the temporary folder, which is removed. Two exports differ, so neither replaces the other,
                # and save_state and prune_hash_records hold excel.STATE_LOCK, so two exports at once both keep their record.
                made = excel.export_project(store, code, folder / name, folder / "state.json", on=today, warnings=warnings,
                                       exported_by=self.by_user())      # the name publish records; the owner has no source yet (projects has none), so the Cover says "the person who sent it to you"
                data = Path(made).read_bytes()
                record = excel.load_state(folder / "state.json", made)
                key = excel.hash_key(record.get("hash") or excel.file_hash(made))
                excel.save_state(here / excel.STATE_FILE, key, record)
                live = {r["code"] for r in store.read("projects") if not r.get("archived")}
                excel.prune_hash_records(here / excel.STATE_FILE, self.today(), live=live, keep=key)       # older than 30 days, over the cap, or an archived project's: gone (#181)
            except (excel.Refused, OSError, ValueError, platform.PlatformError):          # excel.TooBig is a Refused too
                return 409, self.fail("export_failed")
            return 200, {"name": name, "data": data, "warnings": warnings}
        finally:
            store.close()
            if folder is not None:
                shutil.rmtree(folder, ignore_errors=True)

    # ----- the report bar -----
    def latest(self, code):
        """The latest publication of the project, for the report bar: {"at", "to_client"} or {} (no paths, no hash)."""
        if not isinstance(code, str) or not PROJECT_CODE.fullmatch(code):
            return 400, self.fail("bad_project_code")
        store = self.store()
        try:
            if store.read("projects", ref=code) is None:
                return 404, self.fail("project_not_found")
            last = store.latest_publication(code)
        finally:
            store.close()
        return 200, {"ok": True, "latest": {"at": last["at"][:10], "to_client": last["to_client"]} if last else None}
