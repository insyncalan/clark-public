"""#42: the peek (read only in View, the words box in Edit) and Sneak peek's reader. Run: python3 dev/run_tests.py test_peek

Part 1 is the reader in plain Python (clark/sneak.py): from → to, no store, no process, no network, nothing written. Part 2 is the
route (POST /api/sneak/read) against a real demo database: it reads only (change_log, item_events and applies are the same
after). Part 3 is the page in a real browser at 1400 and 900 px with the test build (the hook is not in the served page): a click
opens the peek, Previous and Next, Esc and focus, the width, View shows fields only, the words box opens with two slashes, shows
from → to, and Enter applies through #68's change (place peek) with a toast and Undo; Shift+Enter keeps the box; a confirm line; a refusal in words.
"""
import json
import sys
import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from _paths import ROOT
import _testpage as testpage

from clark import changes, page, server as sv, sneak  # noqa: E402
from test_server import Running, chrome, wait  # noqa: E402
from test_work_items import FIXED_DATE, load_demo, page_target  # noqa: E402
from test_work_filters import click, key as basic_key  # noqa: E402

EXTRA = {"/": (191, "/"), "ArrowLeft": (37, "")}


def key(cdp, sid, name):
    """test_work_filters' key, with the two it lacks."""
    if name not in EXTRA:
        return basic_key(cdp, sid, name)
    vk, text = EXTRA[name]
    common = {"key": name, "code": {"/": "Slash"}.get(name, name), "windowsVirtualKeyCode": vk}
    cdp.call("Input.dispatchKeyEvent", {"type": "keyDown", **common, **({"text": text} if text else {})}, sid)
    cdp.call("Input.dispatchKeyEvent", {"type": "keyUp", **common}, sid)

NOW = date(2026, 10, 28)
DATA = {"actions": [{"id": "A-1", "owner": "Sam Reed", "priority": "Low", "status": "Open", "due_date": "2026-10-29"}],
        "raid": [{"id": "R-1", "type": "Risk", "owner": "Sam Reed", "priority": "High", "status": "Open", "due_date": None}],
        "decisions": [{"id": "D-1", "status": "Pending", "needed_by": "2026-11-02", "made_by": "Sam Reed"}]}


class Reader(unittest.TestCase):
    def read(self, item, words):
        return sneak.read(DATA, item, words, NOW)

    def test_the_example_from_the_issue(self):
        r = self.read("A-1", "move to Friday, owner Jo Ellis, high priority")
        self.assertTrue(r["ok"])
        got = {c["field"]: (c["from_text"], c["to_text"]) for c in r["changes"]}
        self.assertEqual(got, {"due_date": ("29-10-2026", "30-10-2026"), "owner": ("Sam Reed", "Jo Ellis"), "priority": ("Low", "High")})
        self.assertTrue(next(c for c in r["changes"] if c["field"] == "owner")["new_name"], "a name in no item yet is labelled")
        self.assertFalse(r["confirm"])

    def test_a_known_owner_is_not_a_new_name(self):
        r = self.read("A-1", "owner Sam Reed, due 2026-11-03")
        self.assertEqual([c["field"] for c in r["changes"]], ["due_date"], "the owner is already Sam Reed")

    def test_a_date_that_is_not_a_day_is_refused(self):
        for w in ("due 31-02-2026", "due 2026-02-31", "by 99-99-2026"):
            r = self.read("A-1", w)
            self.assertFalse(r["ok"])
            self.assertIn("isn't a real day", r["message"])

    def test_the_changes_that_need_a_confirm_are_marked(self):
        self.assertTrue(self.read("A-1", "cancel it")["confirm"])
        self.assertTrue(self.read("D-1", "made on 2026-11-01")["confirm"])
        self.assertTrue(self.read("D-1", "withdrawn")["confirm"])
        self.assertTrue(self.read("A-1", "mark it done")["confirm"], "closing is as deliberate as cancelling")
        self.assertTrue(self.read("A-1", "we will close this call, owner Jo")["confirm"], "a free word read as Closed is always confirmed")
        self.assertFalse(self.read("A-1", "delayed")["confirm"])

    def test_things_that_do_not_apply_are_left_out_in_words(self):
        r = self.read("R-1", "high priority, owner Jo Ellis")
        self.assertEqual([c["field"] for c in r["changes"]], ["owner"])
        self.assertIn("impact and likelihood", r["note"])
        self.assertFalse(self.read("A-1", "hello there")["ok"])
        self.assertFalse(self.read("Z-9", "owner Jo")["ok"])
        self.assertFalse(self.read("A-1", "x " * 400)["ok"])
        self.assertFalse(self.read("A-1", "")["ok"])
        self.assertFalse(self.read("A-1", None)["ok"])

    def test_a_typed_owner_loses_hidden_characters_and_an_empty_one_is_refused(self):
        r = self.read("A-1", "owner Jo\u202eEllis\x00\x1b[31m, high priority")
        owner = next(c for c in r["changes"] if c["field"] == "owner")
        for text in (owner["to"], owner["to_text"]):
            self.assertFalse([ch for ch in text if ord(ch) < 32 or ch in "\u202e\u200b\u2028"], text)
        for words in ("owner \u200b", "owner \u202e\u2028", "owner is ", "owner TBC", "owner 🙂", "owner \"", "owner A-1"):
            r = self.read("A-1", words)
            self.assertFalse(r["ok"], words)
            self.assertIn("name", r["message"])

    def test_a_name_loses_quotes_symbols_and_emoji_around_it_and_may_not_hold_an_item_id(self):
        for words, name in (("owner \u201cJo Ellis", "Jo Ellis"), ("owner \U0001F642 Jo", "Jo"), ("owner Jo Ellis \u201d", "Jo Ellis"), ("owner O'Brien", "O'Brien")):
            r = self.read("A-1", words)
            self.assertEqual(r["changes"][0]["to"], name, words)
        for words in ("owner A-1 Jo", "owner Jo A-1"):
            self.assertIn("name", self.read("A-1", words)["message"], words)

    def test_the_owner_stops_before_a_priority_word_and_a_new_name_counts_decision_and_milestone_owners(self):
        r = self.read("A-1", "owner Jo Ellis high priority")
        self.assertEqual({c["field"]: c["to"] for c in r["changes"]}, {"owner": "Jo Ellis", "priority": "High"})
        data = {**DATA, "milestones": [{"id": "M-1", "owner": "Mo Hale"}], "decisions": DATA["decisions"] + [{"id": "D-2", "status": "Made", "made_by": "Ida Park"}]}
        for name in ("Ida Park", "Mo Hale"):
            owner = sneak.read(data, "A-1", f"owner {name}", NOW)["changes"][0]
            self.assertFalse(owner["new_name"], name)
        self.assertTrue(sneak.read(data, "A-1", "owner Zed Quin", NOW)["changes"][0]["new_name"])

    def test_a_negation_or_two_statuses_are_not_guessed(self):
        for words in ("not done", "don't cancel this", "this is not delayed", "done and cancel"):
            r = self.read("A-1", words)
            self.assertFalse(r["ok"], words)
            self.assertIn("can't tell which status", r["message"])
        self.assertFalse(self.read("D-1", "made and pending")["ok"])

    def test_more_negation_forms_are_not_read_as_the_action(self):
        for words in ("mustn't cancel", "couldn't be done", "hadn't finished", "ain't done", "unless done", "nothing is done", "weren't delayed",
                      "mustn\u2019t cancel", "neither done nor cancelled", "dont close it"):
            r = self.read("A-1", words)
            self.assertFalse(r["ok"], words)
            self.assertIn("can't tell which status", r["message"], words)
        for words in ("I want to close this", "it is present, done", "event done"):          # "want", "present" and "event" are not negations
            self.assertTrue(self.read("A-1", words)["ok"], words)

    def test_the_owners_name_is_not_scanned_for_a_status_a_date_or_a_priority(self):
        for words, name in (("owner Dan Done", "Dan Done"), ("owner Will Friday", "Will Friday"), ("assign to Cal Cancel", "Cal Cancel"),
                            ("owner Hi Low", "Hi Low")):
            r = self.read("A-1", words)
            self.assertTrue(r["ok"], words)
            self.assertEqual({c["field"]: c["to"] for c in r["changes"]}, {"owner": name}, words)
        r = self.read("A-1", "owner Dan Done, done")
        self.assertEqual({c["field"]: c["to"] for c in r["changes"]}, {"owner": "Dan Done", "status": "Closed"}, "a real status after the name still counts")

    def test_a_decision_made_needs_its_date_and_a_date_with_it_is_the_day_it_was_made(self):
        r = self.read("D-1", "made")
        self.assertFalse(r["ok"])
        self.assertIn("needs the day it was made", r["message"])
        r = self.read("D-1", "made on 2026-11-01")
        self.assertEqual({c["field"]: c["to"] for c in r["changes"]}, {"date": "2026-11-01", "status": "Made"})

    def test_a_register_item_never_gets_a_priority(self):
        data = {**DATA, "raid": DATA["raid"] + [{"id": "R-2", "type": "Assumption", "owner": "Sam Reed", "status": "Open"}]}
        for item in ("R-1", "R-2"):
            r = sneak.read(data, item, "high priority", NOW)
            self.assertFalse(r["ok"], item)
            self.assertIn("impact and likelihood", r["message"])
            self.assertNotIn("couldn't find a change", r["message"], "a note that explains replaces the generic words")

    def test_a_refusal_says_why_and_what_can_change(self):
        closed = {**DATA, "actions": [{"id": "A-9", "owner": "Sam Reed", "status": "Closed", "priority": "Low"}]}
        self.assertIn("already Closed", sneak.read(closed, "A-9", "done", NOW)["message"])
        self.assertIn("already Sam Reed", self.read("A-1", "owner Sam Reed")["message"])
        self.assertIn("Only an action can be delayed", self.read("R-1", "delayed")["message"])
        self.assertIn("milestone", sneak.read({**DATA, "milestones": [{"id": "M-1"}]}, "M-1", "done", NOW)["message"])
        self.assertIn("due date, the owner, the priority and the status", self.read("A-1", "gibberish")["message"])

    def test_archive_or_delete_in_the_words_says_so_plainly(self):
        self.assertEqual(self.read("A-1", "please delete this")["message"], "Nothing is removed here. Nothing was changed.")
        for words in ("archive it",):
            m = self.read("A-1", words)["message"]
            self.assertFalse(self.read("A-1", words)["ok"])
            self.assertIn("An item can't be archived from here.", m)
            self.assertNotIn("delete", m)
            self.assertIn("Archiving isn't available from the page yet. Nothing was changed.", m)
            self.assertNotIn("Archive option", m)
            self.assertNotIn("due date, the owner", m, "it does not list the four changeable fields")
        r = self.read("A-1", "owner Jo Ellis and archive it")
        self.assertTrue(r["ok"])
        self.assertNotIn("delete", r["note"])
        self.assertIn("Archiving isn't available from the page yet.", r["note"])

    def test_it_says_which_date_it_understood_and_refuses_a_silly_year(self):
        self.assertIn("Read as 30-10-2026", self.read("A-1", "Friday")["note"])
        self.assertIn("in the past", self.read("A-1", "due 2026-10-01")["note"])
        for words in ("due 0001-01-01", "due 9999-12-31"):
            self.assertIn("year looks wrong", self.read("A-1", words)["message"])

    def test_two_different_days_are_refused_and_a_decision_is_not_made_in_the_future(self):
        for words in ("friday 2026-11-05", "due 2026-11-03 or 2026-11-05", "monday not friday", "due today not tomorrow"):
            r = self.read("A-1", words)
            self.assertFalse(r["ok"], words)
            self.assertIn("which day you mean", r["message"], words)
        self.assertTrue(self.read("A-1", "friday, 30-10-2026")["ok"], "the same day twice is one day")
        r = self.read("D-1", "made tomorrow")
        self.assertIn("hasn't come yet", r["note"], "a made day in the future is said, and still confirmed")
        self.assertTrue(r["confirm"])
        r = self.read("D-1", "made yesterday")
        self.assertEqual({c["field"]: c["to"] for c in r["changes"]}, {"date": "2026-10-27", "status": "Made"})
        self.assertNotIn("past", r["note"])

    def test_it_uses_no_network_and_starts_no_process(self):
        with mock.patch("socket.socket", side_effect=AssertionError("network")), mock.patch("subprocess.Popen", side_effect=AssertionError("process")):
            self.assertTrue(self.read("A-1", "move to Friday")["ok"])
        src = (ROOT / "src" / "clark" / "sneak.py").read_text(encoding="utf-8")
        for word in ("import subprocess", "import socket", "import urllib", "import sqlite3", "clark.store", "claude"):
            self.assertNotIn(word, src)


class Route(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store, cls.folder, cls.ids = load_demo()
        cls.code = next(iter(cls.ids))
        cls.item = cls.store.data_for(cls.code)["actions"][0]["id"]

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        import shutil
        shutil.rmtree(str(cls.folder), ignore_errors=True)

    def counts(self):
        return [self.store.con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("change_log", "item_events", "applies")]

    def test_it_reads_and_writes_nothing(self):
        s = Running(data_for=self.store.data_for, sneak=sneak.make_read(self.store.data_for))
        self.addCleanup(s.close)
        before = self.counts()
        body = json.dumps({"project": self.code, "id": self.item, "text": "move to Friday, high priority"}).encode()
        status, _, raw = s.api("POST", "/api/sneak/read", body)
        reply = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(self.counts(), before)
        for bad in (b"[]", json.dumps({"project": "no", "id": "A", "text": "x"}).encode(), json.dumps({"project": self.code, "id": 1, "text": "x"}).encode(),
                    json.dumps({"project": self.code, "id": "A", "text": "x", "extra": 1}).encode()):
            self.assertEqual(s.api("POST", "/api/sneak/read", bad)[0], 400)
        self.assertNotEqual(s.api("POST", "/api/sneak/read", body, token="wrong")[0], 200, "the token is checked")
        self.assertEqual(self.counts(), before)

    def test_the_change_route_takes_the_peek_as_a_place_and_not_a_made_up_one(self):
        s = Running(data_for=self.store.data_for, change=changes.make_change(self.store.path, [], "Demo User"))
        self.addCleanup(s.close)
        row = next(r for r in self.store.data_for(self.code)["actions"] if r["status"] == "Open")
        def go(place):
            body = {"project": self.code, "kind": "actions", "op": "update", "id": row["id"], "changes": {"owner": "Zed Quinn"}, "place": place}
            return s.api("POST", "/api/change", json.dumps(body).encode())[0]
        self.assertEqual(go("peeks"), 400)
        self.assertEqual(go("peek"), 200)

    def test_no_seam_is_503_and_an_unknown_project_is_404(self):
        s = Running(data_for=self.store.data_for)
        self.addCleanup(s.close)
        body = json.dumps({"project": self.code, "id": self.item, "text": "x"}).encode()
        status, _, raw = s.api("POST", "/api/sneak/read", body)
        self.assertEqual((status, json.loads(raw)["code"]), (503, "reading_off"))
        self.assertNotIn("change was not kept", json.loads(raw)["message"], "a read keeps nothing")
        s2 = Running(data_for=self.store.data_for, sneak=sneak.make_read(self.store.data_for))
        self.addCleanup(s2.close)
        self.assertEqual(s2.api("POST", "/api/sneak/read", json.dumps({"project": "ZZZ", "id": "A", "text": "x"}).encode())[0], 404)


class Browser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store, cls.folder, cls.ids = load_demo()
        cls.code = next(iter(cls.ids))
        cls.data = cls.store.data_for(cls.code)

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        import shutil
        shutil.rmtree(str(cls.folder), ignore_errors=True)

    def load_page(self, cdp, width, hash_=None, change=None):
        s = Running(data_for=self.store.data_for, projects=lambda: self.store.read("projects"), page_html=lambda: testpage.html(), sneak=sneak.make_read(self.store.data_for),
                    change=change or changes.make_change(self.store.path, [], "Demo User"), undo=changes.make_undo(self.store.path, [], "Demo User"))
        self.addCleanup(s.close)
        sid = page_target(cdp)
        cdp.call("Page.enable", {}, sid)
        cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": FIXED_DATE}, sid)
        cdp.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False}, sid)
        cdp.call("Emulation.setFocusEmulationEnabled", {"enabled": True}, sid)
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{s.port}/{hash_ or '#work&p=' + self.code}"}, sid)
        self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('#work tbody tr[data-id]').length", sid) > 0))
        return s, sid

    def edit_mode(self, cdp, sid):
        """Edit is a switch on the Dashboard (kept in memory): go there, switch, come back to Work items."""
        cdp.js("document.querySelector('[data-view=dashboard]').click()", sid)
        self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('[data-mode=edit]')", sid)))
        cdp.js("document.querySelector('[data-mode=edit]').click()", sid)
        cdp.js("document.querySelector('[data-view=work]').click()", sid)
        self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('#work tbody tr[data-id]').length", sid) > 0))

    def ids_on_page(self, cdp, sid):
        return cdp.js("[...document.querySelectorAll('#work tbody tr[data-id]')].map(r => r.dataset.id)", sid)

    def test_a_click_opens_the_peek_with_fields_and_prev_next_esc_and_focus(self):
        for width in (1400, 900):
            with self.subTest(width=width), chrome() as cdp:
                s, sid = self.load_page(cdp, width)
                ids = self.ids_on_page(cdp, sid)
                self.assertTrue(len(ids) > 3)
                click(cdp, sid, f"#work tbody tr[data-id='{ids[1]}'] .c-item")
                self.assertTrue(wait(lambda: cdp.js("clarkPage.peek() && clarkPage.peek().id", sid) == ids[1]))
                self.assertEqual(cdp.js("document.querySelector('#peek').dataset.peek", sid), ids[1])
                labels = cdp.js("[...document.querySelectorAll('#peek dt')].map(d => d.textContent)", sid)
                self.assertIn("Owner", labels)
                self.assertIn("Status", labels)
                self.assertNotIn("Shown to client", labels, "an internal field is not in View or a published file")
                self.assertEqual(cdp.js("document.querySelector('#peek').getBoundingClientRect().right", sid), cdp.js("document.documentElement.clientWidth", sid))
                self.assertEqual(cdp.js("!!document.querySelector('[data-sneak-open],[data-sneak]')", sid), False, "no words box in View")
                # Previous and Next replace the entry (they add none) and follow the list that opened it
                length = cdp.js("history.length", sid)
                click(cdp, sid, "[data-pk-next]")
                self.assertTrue(wait(lambda: cdp.js("clarkPage.peek().id", sid) == ids[2]))
                click(cdp, sid, "[data-pk-prev]")
                click(cdp, sid, "[data-pk-prev]")
                self.assertTrue(wait(lambda: cdp.js("clarkPage.peek().id", sid) == ids[0]))
                self.assertTrue(cdp.js("document.querySelector('[data-pk-prev]').disabled", sid), "disabled at the start")
                self.assertEqual(cdp.js("history.length", sid), length)
                # Esc closes it and focus goes back to where it was
                key(cdp, sid, "Escape")
                self.assertTrue(wait(lambda: cdp.js("clarkPage.peek()", sid) is None))
                self.assertEqual(cdp.js("!!document.querySelector('#peek')", sid), False)

    def test_the_icon_buttons_have_a_tooltip_and_a_name_and_a_pending_decision_says_decision_by(self):
        pending = next(d["id"] for d in self.data["decisions"] if d["status"] == "Pending")
        made = next(d["id"] for d in self.data["decisions"] if d["status"] == "Made")
        with chrome() as cdp:
            s, sid = self.load_page(cdp, 1400, f"#work&p={self.code}&item={pending}")
            self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('#peek dt')", sid)))
            labels = cdp.js("[...document.querySelectorAll('#peek dt')].map(d => d.textContent)", sid)
            self.assertIn("Decision by", labels)
            self.assertNotIn("Made by", labels, "a decision still to be made is not 'made by' anyone")
            self.assertNotIn("Owner", labels)
            for attr in ("data-pk-prev", "data-pk-next", "data-pk-wide", "data-pk-close"):
                got = cdp.js(f"(b => [b.title, b.getAttribute('aria-label')])(document.querySelector('[{attr}]'))", sid)
                self.assertTrue(got[0] and got[0] == got[1], (attr, got))
            self.assertEqual(cdp.js("document.querySelector('[data-pk-close]').title", sid), "Close this panel")
            self.assertEqual(cdp.js("document.querySelector('[data-pk-wide]').title", sid), "Make this panel fill the screen")
            cdp.js(f"location.hash = '#work&p={self.code}&item={made}'", sid)
            self.assertTrue(wait(lambda: cdp.js("clarkPage.peek() && clarkPage.peek().id", sid) == made))
            self.assertIn("Decision by", cdp.js("[...document.querySelectorAll('#peek dt')].map(d => d.textContent)", sid), "the prototype says Decision by for every decision")

    def test_the_width_drags_resets_and_is_kept_and_never_passes_the_window(self):
        for width in (1400, 900):
            with self.subTest(width=width), chrome() as cdp:
                s, sid = self.load_page(cdp, width)
                cdp.js("clarkPage.openPeek(document.querySelector('#work tbody tr[data-id]').dataset.id)", sid)
                self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('#peek')", sid)))
                w = lambda: cdp.js("document.querySelector('#peek').getBoundingClientRect().width", sid)
                default = w()
                client = cdp.js("document.documentElement.clientWidth", sid)
                self.assertLessEqual(default, cdp.js("document.documentElement.clientWidth", sid))
                edge = cdp.js("(() => { const b = document.querySelector('.pk-edge').getBoundingClientRect(); return [b.x + 3, b.y + 200]; })()", sid)
                for kind, x in (("mousePressed", edge[0]), ("mouseMoved", client - 700), ("mouseReleased", client - 700)):
                    cdp.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": edge[1], "button": "left", "buttons": 1 if kind != "mouseReleased" else 0, "clickCount": 1}, sid)
                self.assertTrue(wait(lambda: abs(w() - min(700, client)) <= 2), f"dragged to {w()}")
                cdp.call("Page.reload", {}, sid)
                self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('#peek')", sid)))
                self.assertLessEqual(abs(w() - min(700, client)), 2, "kept after a reload")
                cdp.js("document.querySelector('.pk-edge').focus()", sid)
                for _ in range(40):
                    key(cdp, sid, "ArrowLeft")
                self.assertTrue(wait(lambda: w() == client), "never wider than the window")
                cdp.js("document.querySelector('.pk-edge').dispatchEvent(new MouseEvent('dblclick', {bubbles: true}))", sid)
                self.assertTrue(wait(lambda: w() == default), "double-click resets")
                click(cdp, sid, "[data-pk-wide]")
                self.assertTrue(wait(lambda: w() == client), "across the whole screen")

    def test_edit_opens_the_words_box_with_two_slashes_and_reads_without_writing(self):
        for width in (1400, 900):
            with self.subTest(width=width), chrome() as cdp:
                s, sid = self.load_page(cdp, width)
                self.edit_mode(cdp, sid)
                target = next(r["id"] for r in self.data["actions"] if r["status"] == "Open")
                cdp.js(f"clarkPage.openPeek({json.dumps(target)})", sid)
                self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('[data-sneak-open]')", sid)), "the sparkle is in the top bar")
                self.assertTrue(wait(lambda: cdp.js("document.activeElement.hasAttribute('data-pk-close')", sid)), "focus went into the peek, so its keys are set")
                cdp.js("document.activeElement.blur()", sid)
                key(cdp, sid, "/")
                key(cdp, sid, "/")
                self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('[data-sneak]')", sid)), "two slashes open it")
                self.assertTrue(wait(lambda: cdp.js("document.activeElement.className", sid) == "sn-in"), "focus is in the box")
                self.assertIn("Change an item with words", cdp.js("document.querySelector('[data-sneak]').textContent", sid))
                cdp.js("(() => { const i = document.querySelector('.sn-in'); i.value = 'move to Friday, owner Jo Ellis, high priority'; i.dispatchEvent(new Event('input', {bubbles: true})); })()", sid)
                self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('.sn-list li').length", sid) >= 2))
                fields = cdp.js("[...document.querySelectorAll('.sn-list li')].map(l => l.dataset.field)", sid)
                self.assertIn("owner", fields)
                self.assertIn("due_date", fields)
                # Esc closes the words box only; the peek stays
                key(cdp, sid, "Escape")
                self.assertTrue(wait(lambda: cdp.js("!document.querySelector('[data-sneak]')", sid)))
                self.assertEqual(cdp.js("!!document.querySelector('#peek')", sid), True)
                self.assertTrue(wait(lambda: cdp.js("document.activeElement.hasAttribute('data-sneak-open')", sid)), "focus returns to the sparkle")
                self.assertIn("Shown to client", cdp.js("[...document.querySelectorAll('#peek dt')].map(d => d.textContent)", sid), "Edit shows it")
                # a date that is not a day is refused in plain words
                cdp.js("document.querySelector('[data-sneak-open]').click()", sid)
                self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('.sn-in')", sid)))
                cdp.js("(() => { const i = document.querySelector('.sn-in'); i.value = 'due 31-02-2026'; i.dispatchEvent(new Event('input', {bubbles: true})); })()", sid)
                self.assertTrue(wait(lambda: "isn't a real day" in cdp.js("(document.querySelector('[data-sneak-message]') || {textContent: ''}).textContent", sid)))

    def words(self, cdp, sid, target, text):
        """Open the peek on `target` in Edit, open the words box and type `text`; waits for a reading."""
        cdp.js(f"clarkPage.openPeek({json.dumps(target)})", sid)
        self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('[data-sneak-open]')", sid)))
        cdp.js("document.querySelector('[data-sneak-open]').click()", sid)
        self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('.sn-in')", sid)))
        cdp.js(f"(() => {{ const i = document.querySelector('.sn-in'); i.value = {json.dumps(text)}; i.dispatchEvent(new Event('input', {{bubbles: true}})); }})()", sid)
        self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('.sn-list li').length", sid) >= 1))

    def open_actions(self):
        return [r["id"] for r in self.data["actions"] if r["status"] == "Open"]

    def row_text(self, cdp, sid, which):
        return cdp.js(f"(() => {{ const d = document.querySelector('#peek [data-row={which}] dd'); if (!d) return ''; const c = d.cloneNode(true); c.querySelectorAll('.chg').forEach((x) => x.remove()); return c.textContent.trim(); }})()", sid)

    def test_enter_applies_with_a_toast_flash_and_undo_and_the_box_closes(self):
        for width in (1400, 900):
            with self.subTest(width=width), chrome() as cdp:
                sent = []
                real = changes.make_change(self.store.path, [], "Demo User")
                s, sid = self.load_page(cdp, width, change=lambda req: (sent.append(req), real(req))[1])
                self.edit_mode(cdp, sid)
                target = self.open_actions()[0]
                self.words(cdp, sid, target, "owner Jo Ellis, high priority")
                before = self.row_text(cdp, sid, "owner")
                key(cdp, sid, "Enter")
                self.assertTrue(wait(lambda: self.row_text(cdp, sid, "owner") == "Jo Ellis"), "the peek shows what was saved")
                self.assertEqual(self.row_text(cdp, sid, "priority"), "High")
                self.assertEqual(len(sent), 1, "one request, one step")
                self.assertEqual((sent[0]["place"], sent[0]["kind"], sent[0]["op"], sent[0]["id"]), ("peek", "actions", "update", target))
                self.assertEqual(sent[0]["changes"], {"owner": "Jo Ellis", "priority": "High"})
                self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('#peek [data-row=owner][data-flash]')", sid)), "the changed field flashes")
                self.assertFalse(cdp.js("!!document.querySelector('#peek [data-row=status][data-flash]')", sid), "a field that did not change does not")
                self.assertTrue(cdp.js("!document.querySelector('[data-sneak]')", sid), "Enter closes the words box")
                self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('.toast [data-undo]')", sid)), "the toast offers Undo")
                cdp.js("document.querySelector('.toast [data-undo]').click()", sid)
                self.assertTrue(wait(lambda: self.row_text(cdp, sid, "owner") == before), "Undo puts the owner back")
                self.assertNotEqual(self.row_text(cdp, sid, "priority"), "High", "and the priority, in the same step")
                self.assertTrue(wait(lambda: "Undone" in cdp.js("(document.querySelector('.toast') || {textContent: ''}).textContent", sid)))

    def test_shift_enter_applies_and_keeps_the_box_open(self):
        with chrome() as cdp:
            s, sid = self.load_page(cdp, 1400)
            self.edit_mode(cdp, sid)
            target = self.open_actions()[1]
            self.words(cdp, sid, target, "owner Pat Moss")
            cdp.js("document.querySelector('.sn-in').dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', shiftKey: true, bubbles: true, cancelable: true}))", sid)
            self.assertTrue(wait(lambda: self.row_text(cdp, sid, "owner") == "Pat Moss"))
            self.assertTrue(cdp.js("!!document.querySelector('[data-sneak]')", sid), "the box stays open")
            self.assertEqual(cdp.js("document.querySelector('.sn-in').value", sid), "", "and is empty for the next words")

    def test_a_reading_that_needs_a_confirm_is_not_applied_by_enter(self):
        with chrome() as cdp:
            s, sid = self.load_page(cdp, 1400)
            self.edit_mode(cdp, sid)
            target = next(r["id"] for r in self.data["actions"] if r["status"] == "Open")
            cdp.js(f"clarkPage.openPeek({json.dumps(target)})", sid)
            self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('[data-sneak-open]')", sid)))
            cdp.js("document.querySelector('[data-sneak-open]').click()", sid)
            self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('.sn-in')", sid)))
            cdp.js("(() => { const i = document.querySelector('.sn-in'); i.value = 'cancel it'; i.dispatchEvent(new Event('input', {bubbles: true})); })()", sid)
            self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('[data-sneak-confirm]')", sid)))
            key(cdp, sid, "Enter")
            self.assertTrue(wait(lambda: cdp.js("document.querySelector('[data-sneak-confirm]').classList.contains('flash')", sid)), "the line flashes")
            self.assertEqual(cdp.js("!!document.querySelector('.toast')", sid), False, "nothing was sent")
            self.assertNotEqual(self.row_text(cdp, sid, "status"), "Cancelled")
            cdp.js("document.querySelector('[data-sneak-confirm-btn]').click()", sid)
            self.assertTrue(wait(lambda: self.row_text(cdp, sid, "status") == "Cancelled"), "the confirm button applies it")
            self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('.toast [data-undo]')", sid)))
            cdp.js("document.querySelector('.toast [data-undo]').click()", sid)
            self.assertTrue(wait(lambda: self.row_text(cdp, sid, "status") != "Cancelled"), "Undo reopens it")

    def test_reduced_motion_gets_a_still_tint_and_a_changed_marker(self):
        with chrome() as cdp:
            s, sid = self.load_page(cdp, 1400)
            cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]}, sid)
            self.edit_mode(cdp, sid)
            self.words(cdp, sid, self.open_actions()[0], "owner Rae Quill")
            key(cdp, sid, "Enter")
            self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('#peek [data-row=owner][data-flash]')", sid)))
            self.assertEqual(cdp.js("getComputedStyle(document.querySelector('#peek [data-row=owner][data-flash]')).animationName", sid), "none")
            self.assertEqual(cdp.js("document.querySelector('#peek [data-row=owner] .tag.chg').textContent", sid), "Changed")
            self.assertFalse(cdp.js("!!document.querySelector('#peek [data-row=status] .tag.chg')", sid), "only the changed field is marked")

    def test_an_old_confirm_is_not_applied_after_the_item_changed_and_typing_clears_the_reading(self):
        with chrome() as cdp:
            sent = []
            real = changes.make_change(self.store.path, [], "Demo User")
            s, sid = self.load_page(cdp, 1400, change=lambda req: (sent.append(req), real(req))[1])
            self.edit_mode(cdp, sid)
            target = self.open_actions()[-1]
            self.words(cdp, sid, target, "done")
            self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('[data-sneak-confirm]')", sid)))
            old = self.store.con.execute("SELECT status FROM actions WHERE id = ?", (target,)).fetchone()[0]
            self.store.con.execute("UPDATE actions SET status = 'Cancelled' WHERE id = ?", (target,))
            self.store.con.commit()
            self.addCleanup(lambda: (self.store.con.execute("UPDATE actions SET status = ? WHERE id = ?", (old, target)), self.store.con.commit()))
            cdp.js("document.querySelector('[data-sneak-confirm-btn]').click()", sid)
            self.assertTrue(wait(lambda: "This item changed" in cdp.js("(document.querySelector('.toast.problem') || {textContent: ''}).textContent", sid)))
            self.assertEqual(sent, [], "nothing was sent")
            # typing clears the reading at once, so Enter cannot apply an older list
            cdp.js("(() => { const i = document.querySelector('.sn-in'); i.value = 'owner Zed Quin'; i.dispatchEvent(new Event('input', {bubbles: true})); })()", sid)
            self.assertEqual(cdp.js("document.querySelectorAll('.sn-list li').length", sid), 0)
            key(cdp, sid, "Enter")
            time.sleep(0.1)
            self.assertEqual(sent, [], "Enter did nothing before the new reading arrived")

    def test_a_change_the_route_refuses_says_why_in_plain_words_and_changes_nothing(self):
        with chrome() as cdp:
            s, sid = self.load_page(cdp, 1400, change=lambda req: (400, {"ok": False, "message": changes.ITEM_NOT_MINE, "code": "refused"}))
            self.edit_mode(cdp, sid)
            target = self.open_actions()[2]
            self.words(cdp, sid, target, "owner Ann Fox")
            before = self.row_text(cdp, sid, "owner")
            key(cdp, sid, "Enter")
            self.assertTrue(wait(lambda: changes.ITEM_NOT_MINE in cdp.js("(document.querySelector('.toast.problem') || {textContent: ''}).textContent", sid)))
            self.assertEqual(self.row_text(cdp, sid, "owner"), before)
            self.assertFalse(cdp.js("!!document.querySelector('.toast [data-undo]')", sid))
            self.assertTrue(cdp.js("!!document.querySelector('[data-sneak]')", sid), "the box stays so the words can be changed")

    def test_the_published_page_has_no_peek_extras_and_the_served_page_no_hook(self):
        view = page.VIEW_PAGE.read_text(encoding="utf-8")
        for word in ("/api/sneak", "/api/change", "sneak", "Sneak peek", "clarkPage"):
            self.assertNotIn(word, view)
        served = page.PAGE.read_text(encoding="utf-8")
        self.assertNotIn("clarkPage", served, "the test hook is not in a client file")
        self.assertIn("clarkPage", testpage.html())


class WidthSource(unittest.TestCase):
    def test_no_peek_file_sizes_the_width_from_window_inner_width(self):
        """A classic scroll bar makes innerWidth wider than the page, so the peek is sized from the client width."""
        for name in ("components/Peek.jsx", "stores/peekState.js"):
            text = (ROOT / "src/clark/page/src" / name).read_text(encoding="utf-8")
            self.assertNotIn("innerWidth", text, name)
            self.assertIn("documentElement.clientWidth", text, name)

    def test_the_fill_screen_rule_is_a_hundred_percent_not_a_hundred_vw(self):
        """100vw counts a classic scroll bar (15 px on Linux), so a peek that fills the screen would be too wide; 100% does not."""
        css = (ROOT / "src/clark/page/shell.css").read_text(encoding="utf-8")
        rule = next(line for line in css.splitlines() if line.startswith(".peek.wide"))
        self.assertIn("width: 100%", rule)
        self.assertNotIn("100vw", rule)

    def test_every_browser_test_that_uses_the_page_hook_loads_the_test_page(self):
        """The served page carries no window.clarkPage (#42), so a browser test that calls it must load testpage.html(), not page.page_html()."""
        for path in sorted((ROOT / "tests").glob("test_*.py")):
            text = path.read_text(encoding="utf-8")
            if "clarkPage." in text and path.name != "test_peek.py":
                self.assertNotIn("page.page_html(", text, f"{path.name} uses clarkPage, so it must serve testpage.html()")


class PublishedList(unittest.TestCase):
    def test_a_published_file_never_tags_a_row_shown_to_client_even_if_its_data_says_so(self):
        """Every row of a client's file is for the client, so the tag says nothing there; it is an Edit-mode tag (#42 review)."""
        import tempfile
        import test_publish as tp
        _plant, pub, text = tp.made()
        data = tp.block(text)
        for table in ("actions", "raid", "decisions"):
            for row in data["data"].get(table, []):
                row["client_visible"] = 1
        rebuilt = text.replace(tp.re.search(r'<script type="application/json" id="clark-data">.*?</script>', text, tp.re.S).group(0),
                               pub_block(data), 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            path.write_text(rebuilt, encoding="utf-8")
            with chrome() as cdp:
                sid = tp.opened(cdp, path.as_uri())
                self.assertTrue(wait(lambda: cdp.js("document.querySelector('h1') && document.documentElement.dataset.ready", sid) == "1"))
                cdp.js("document.querySelector('[data-view=work]').click()", sid)
                self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('#work tbody tr[data-id]').length", sid) > 0))
                self.assertEqual(cdp.js("document.querySelector('#work').textContent.includes('Shown to client')", sid), False)


def pub_block(data):
    from clark import publish
    return publish.data_block({"data": data["data"], "sections": data["sections"], "tabs": data["tabs"]}, data["as_at"])


class PlainLabels(unittest.TestCase):
    """The peek's button names and the confirm line, pinned in the source and in the built page."""
    SRC = ROOT / "src" / "clark" / "page"

    def texts(self):
        return [(self.SRC / "src" / "edit" / "SneakPeek.jsx").read_text(encoding="utf-8"),
                (self.SRC / "src" / "components" / "Peek.jsx").read_text(encoding="utf-8"),
                (self.SRC / "page.html").read_text(encoding="utf-8")]

    def test_the_sparkle_has_a_title_and_a_matching_label(self):
        jsx = self.texts()[0]
        self.assertIn('title="Change an item with words" aria-label="Change an item with words"', jsx)

    def test_the_width_button_follows_the_state(self):
        peek = self.texts()[1]
        for kind in ("title", "aria-label"):
            self.assertIn(kind + '={wide.value ? "Return the panel to its usual width" : "Make this panel fill the screen"}', peek)
        self.assertIn("aria-pressed={wide.value}", peek)

    def test_the_confirm_line_names_the_button(self):
        jsx = self.texts()[0]
        self.assertIn("This change needs your OK. Press ", jsx)
        self.assertIn("to make it, or change your words.", jsx)
        self.assertNotIn("This needs a confirm", jsx)


class ToastWords(unittest.TestCase):
    """The three toast lines of Applying a reading are plain and say what to do next (pinned in the source and the built page)."""
    LINES = ("There was nothing to change, so nothing was changed. Type what you want to change and try again.",
             "This item changed while you were reading, so nothing was changed. Type your change again to see the new details, then apply.",
             "A decision that is made can't be undone from here. To change it, record a new decision that replaces it.")

    def test_each_line_is_in_the_source_and_the_built_page(self):
        src = (ROOT / "src/clark/page/src/edit/sneakApply.js").read_text(encoding="utf-8")
        built = (ROOT / "src/clark/page/page.html").read_text(encoding="utf-8")
        for line in self.LINES:
            self.assertIn(line, src)
            self.assertIn(line, built)
        for old in ("There is nothing to change. Nothing was changed.", "Check the new words.", "put back from here"):
            self.assertNotIn(old, src)


if __name__ == "__main__":
    unittest.main()
