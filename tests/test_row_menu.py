"""#97, the right-click menu on a work item: in the table, on the board and in full screen, by mouse and by keys, each entry doing
what its button elsewhere does (the cells' own words and requests, the board's cards, clark's archive step), with Undo.

Run: python3 dev/run_tests.py test_row_menu
Part 1 runs the menu's rules (src/clark/page/src/logic/rowMenu.js, bundled by the pinned esbuild) in headless Chrome. Part 2 drives
the committed page against the real server, whose change and undo routes are changes.make_change and make_undo over a demo
database, with real mouse and key events, and checks each step in the database. Desktop (1400) and 900 px. The browser parts are
required: they fail, never skip, without Chrome (set CLARK_CHROME to its path).
"""
import contextlib
import json
import unittest

from _paths import ROOT, SRC

from test_server import chrome, wait  # noqa: E402
from test_work_filters import click, need_chrome  # noqa: E402
from test_work_items import bundled, page_target  # noqa: E402
import test_work_board_page as board  # noqa: E402

PAGE_SRC = SRC / "clark" / "page" / "src"
TODAY = board.TODAY                        # Thursday 29-10-2026

KEYS = {"Enter": (13, "\r"), " ": (32, " "), "Escape": (27, ""), "ArrowDown": (40, ""), "ArrowUp": (38, ""), "ArrowLeft": (37, ""),
        "ArrowRight": (39, ""), "Home": (36, ""), "End": (35, ""), "Tab": (9, ""), "F10": (121, ""), "ContextMenu": (93, "")}


def key(cdp, sid, name, shift=False):
    vk, text = KEYS[name]
    common = {"key": name, "code": {" ": "Space"}.get(name, name), "windowsVirtualKeyCode": vk, **({"modifiers": 8} if shift else {})}
    cdp.call("Input.dispatchKeyEvent", {"type": "rawKeyDown" if not text else "keyDown", **common, **({"text": text} if text else {})}, sid)
    cdp.call("Input.dispatchKeyEvent", {"type": "keyUp", **common}, sid)


def right_click(cdp, sid, selector):
    cdp.js(f"document.querySelector({json.dumps(selector)}).scrollIntoView({{block: 'center'}})", sid)
    x, y = cdp.js(f"(() => {{ const b = document.querySelector({json.dumps(selector)}).getBoundingClientRect(); return [b.x + Math.min(b.width / 2, 120), b.y + b.height / 2]; }})()", sid)
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y}, sid)
    cdp.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "right", "buttons": 2, "clickCount": 1}, sid)
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "right", "buttons": 0, "clickCount": 1}, sid)


# ---- part 1: the rules ----
class Rules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        need_chrome()
        cls.stack = contextlib.ExitStack()
        cls.cdp = cls.stack.enter_context(chrome())
        cls.sid = page_target(cls.cdp)
        res = cls.cdp.call("Runtime.evaluate", {"expression": bundled(PAGE_SRC / "logic" / "rowMenu.js", "RM") + "; true", "returnByValue": True}, cls.sid)
        assert "exceptionDetails" not in res, res

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def js(self, expr):
        res = self.cdp.call("Runtime.evaluate", {"expression": expr, "returnByValue": True}, self.sid)
        self.assertNotIn("exceptionDetails", res, (expr, res))
        return res["result"].get("value")

    ACTION = {"id": "ABC-A-001", "kind": "action", "owner": "Ada Quillfeather", "status": "Open", "priority": "High", "due_date": "2026-11-02"}

    def test_draft_email_names_the_owner_and_is_greyed_with_a_reason_when_there_is_no_address(self):
        row = json.dumps(self.ACTION)
        self.assertEqual(self.js(f"RM.draftEntry({row}, {{}})"),
                         {"name": "Draft email to Ada Quillfeather", "reason": "No email address for Ada Quillfeather yet.", "to": ""})
        people = json.dumps({"people": [{"name": "ada quillfeather", "email": " ada@example.com "}]})
        self.assertEqual(self.js(f"RM.draftEntry({row}, {people})"), {"name": "Draft email to Ada Quillfeather", "reason": "", "to": "ada@example.com"})
        for owner in ("TBC", None, ""):
            none = json.dumps({**self.ACTION, "owner": owner})
            got = self.js(f"RM.draftEntry({none}, {people})")
            self.assertEqual((got["name"], got["to"]), ("Draft email to the owner", ""))
            self.assertIn("no owner", got["reason"])

    def test_the_lists_offer_what_the_cells_offer_without_what_the_item_has(self):
        row = json.dumps(self.ACTION)
        self.assertEqual(self.js(f"RM.statusList({row})"), ["Delayed", "Closed", "Cancelled"])
        made = json.dumps({"id": "ABC-D-002", "kind": "decision", "owner": "X Y", "status": "Made"})
        self.assertEqual(self.js(f"RM.statusList({made})"), ["Withdrawn"], "a made decision never goes back to Pending")
        self.assertEqual(self.js(f"RM.ownerList(['Ada Quillfeather', 'Zelda Quince'], {row})"), ["Zelda Quince"])
        self.assertEqual(self.js(f"RM.dueList({json.dumps(TODAY)})"),
                         [{"id": "friday", "name": "Friday", "day": "2026-10-30", "line": "30-10-2026"},
                          {"id": "week", "name": "A week on", "day": "2026-11-05", "line": "05-11-2026"}])

    def test_a_pick_is_the_cells_own_change_and_an_unchanged_value_is_nothing(self):
        row = json.dumps(self.ACTION)
        got = self.js(f"RM.pickChange({row}, 'status', 'Closed', {json.dumps(TODAY)})")
        self.assertEqual(got, {"table": "actions", "id": "ABC-A-001", "changes": {"status": "Closed"}, "words": "Status of ABC-A-001 changed to Closed.",
                               "back": "Status of ABC-A-001 is back to Open."})
        self.assertIsNone(self.js(f"RM.pickChange({row}, 'status', 'Open', {json.dumps(TODAY)})"))
        self.assertIn("error", self.js(f"RM.pickChange({row}, 'status', 'Made', {json.dumps(TODAY)})"))

    def test_duplicate_copies_the_fields_the_server_takes_and_says_it_is_a_copy(self):
        raw = json.dumps({"id": "ABC-A-001", "description": "Order the laptops", "owner": "Ada Quillfeather", "priority": "High", "due_date": None,
                          "workstream": "Data", "milestone": None, "status": "Closed", "closed": "2026-10-10", "client_visible": 0})
        self.assertEqual(self.js(f"RM.duplicateRequest({raw}, 'actions')"),
                         {"kind": "actions", "op": "new", "place": "menu",
                          "values": {"owner": "Ada Quillfeather", "priority": "High", "workstream": "Data", "description": "Copy of Order the laptops"}})
        long = json.dumps({"decision": "x" * 300, "made_by": "A B", "needed_by": "2026-11-20", "status": "Made"})
        got = self.js(f"RM.duplicateRequest({long}, 'decisions')")
        self.assertEqual(len(got["values"]["decision"]), 200)
        self.assertEqual(sorted(got["values"]), ["decision", "made_by", "needed_by"], "a copy of a made decision starts as a new one: no status")

    def test_the_link_is_the_items_peek_address(self):
        row = json.dumps(self.ACTION)
        self.assertEqual(self.js(f"RM.linkFor({row}, 'ABC', 'http://127.0.0.1:1/', (s) => '#' + s.view + '&p=' + s.project + '&item=' + s.item)"),
                         "http://127.0.0.1:1/#work&p=ABC&item=ABC-A-001")


# ---- part 2: the real page ----
class Menu(board.Base):
    TABLE = "tr[data-id='%s']"
    CARD = "article[data-id='%s'] .bc-main"

    def open_menu(self, cdp, sid, selector):
        right_click(cdp, sid, selector)
        self.until(cdp, sid, "!!document.querySelector('.rowmenu [role=menu]')", "the menu")

    def entries(self, cdp, sid):
        return cdp.js("[...document.querySelectorAll('.rowmenu [role=menuitem]')].map(b => [b.dataset.rm, b.querySelector('b').textContent, b.getAttribute('aria-disabled') === 'true', (b.querySelector('small') || {}).textContent || ''])", sid)

    def shut(self, cdp, sid):
        self.until(cdp, sid, "!document.querySelector('.rowmenu')", "the menu to close")

    def test_a_right_click_on_a_row_opens_the_menu_with_every_entry(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            a, before = self.id_of("Order the laptops"), self.steps()
            self.open_menu(cdp, sid, self.TABLE % a)
            self.assertEqual(cdp.js("document.querySelector('.rowmenu [role=menu]').getAttribute('aria-label')", sid), f"Actions for {a}")
            got = self.entries(cdp, sid)
            self.assertEqual([e[1] for e in got], ["Draft email to Sara Khan", "Open the peek", "Change status", "Move due date", "Change owner",
                                                   "Hide from the client", "Copy link to this item", "Copy ID", "Duplicate", "Archive"])
            by = {e[0]: e for e in got}
            self.assertEqual(by["draft"][2:], [True, "No email address for Sara Khan yet."], "greyed, with the reason in words")
            self.assertTrue(by["eye"][2] and by["eye"][3], "the eye says why it is greyed")
            self.assertFalse(any(by[k][2] for k in ("peek", "status", "due", "owner", "link", "copyid", "dup", "archive")))
            self.assertEqual(cdp.js("document.activeElement.dataset.rm", sid), "peek", "focus is on the first entry that can be used")
            box = cdp.js("(() => { const b = document.querySelector('.rowmenu').getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom]; })()", sid)
            self.assertTrue(box[0] >= 0 and box[1] >= 0 and box[2] <= 1400 and box[3] <= 900, box)
            self.assertFalse(cdp.js("!!document.querySelector('.cpop')", sid))
            self.assertEqual(self.steps(), before)

    def test_the_eye_entry_follows_the_item_and_a_menu_closes_with_escape_and_a_click_away(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            shown, hidden = self.id_of("Send the invitations"), self.id_of("Book the training room")
            self.open_menu(cdp, sid, self.TABLE % shown)
            self.assertIn("Hide from the client", [e[1] for e in self.entries(cdp, sid)])
            key(cdp, sid, "Escape")
            self.shut(cdp, sid)
            self.assertEqual(cdp.js("document.activeElement.dataset.id", sid), shown, "focus is back on the row")
            self.open_menu(cdp, sid, self.TABLE % hidden)
            self.assertIn("Show to the client", [e[1] for e in self.entries(cdp, sid)])
            cdp.js("document.body.insertAdjacentHTML('beforeend', '<div id=away style=\"position:fixed;left:0;top:0;width:30px;height:30px;z-index:60\"></div>')", sid)
            hit = cdp.js("(() => { const a = document.querySelector('#away').getBoundingClientRect(); const e = document.elementFromPoint(a.x + 15, a.y + 15); return e && (e.id || e.outerHTML.slice(0, 60)); })()", sid)
            self.assertEqual(hit, "away", f"the click-away spot is covered by {hit}")      # say so, instead of waiting out a timeout
            click(cdp, sid, "#away")
            self.shut(cdp, sid)
            right_click(cdp, sid, ".head h1")
            self.assertFalse(cdp.js("!!document.querySelector('.rowmenu')", sid), "off a row the menu stays out of the way")

    def test_change_status_from_the_menu_is_one_step_with_undo(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            a = self.id_of("Order the laptops")
            before = self.steps()
            self.open_menu(cdp, sid, self.TABLE % a)
            click(cdp, sid, "[data-rm=status]")
            self.until(cdp, sid, "document.querySelector('.rowmenu [role=menu]').getAttribute('aria-label').startsWith('Change status')", "the list")
            self.assertEqual([e[1] for e in self.entries(cdp, sid)], ["Delayed", "Closed", "Cancelled", "‹ Back"])
            click(cdp, sid, "[data-rm='s:Closed']")
            t = self.wait_toast(cdp, sid, "done")
            self.assertEqual((t["text"], t["undo"]), (f"Status of {a} changed to Closed.", True), "the cell's own words")
            self.assertEqual((self.row(a)["status"], self.steps()), ("Closed", before + 1))
            self.shut(cdp, sid)
            click(cdp, sid, "[data-undo]")
            self.until(cdp, sid, f"document.querySelector('.toast-text').textContent === 'Status of {a} is back to Open.'")
            self.assertEqual(self.row(a)["status"], "Open")

    def test_the_keys_open_the_menu_walk_it_and_run_an_entry(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            a = self.id_of("Order the laptops")
            cdp.js(f"document.querySelector(\"{self.TABLE % a}\").focus()", sid)
            key(cdp, sid, "F10", shift=True)
            self.until(cdp, sid, "!!document.querySelector('.rowmenu [role=menu]')", "Shift+F10 opens it")
            key(cdp, sid, "Escape")
            self.shut(cdp, sid)
            self.assertEqual(cdp.js("document.activeElement.dataset.id", sid), a)
            key(cdp, sid, "ContextMenu")
            self.until(cdp, sid, "!!document.querySelector('.rowmenu [role=menu]')", "the menu key opens it")
            first = cdp.js("document.activeElement.dataset.rm", sid)
            key(cdp, sid, "ArrowDown")
            self.assertEqual((first, cdp.js("document.activeElement.dataset.rm", sid)), ("peek", "status"))
            key(cdp, sid, "End")
            self.assertEqual(cdp.js("document.activeElement.dataset.rm", sid), "archive")
            key(cdp, sid, "Home")
            self.assertEqual(cdp.js("document.activeElement.dataset.rm", sid), "peek")
            key(cdp, sid, "ArrowDown")                                  # Change status
            key(cdp, sid, "ArrowRight")                                 # opens its list
            self.until(cdp, sid, "document.querySelector('.rowmenu [role=menu]').getAttribute('aria-label').startsWith('Change status')")
            self.assertEqual(cdp.js("document.activeElement.dataset.rm", sid), "s:Delayed")
            key(cdp, sid, "ArrowLeft")                                  # back to the menu
            self.until(cdp, sid, "document.querySelector('.rowmenu [role=menu]').getAttribute('aria-label').startsWith('Actions')")
            key(cdp, sid, "ArrowRight")                                 # (focus starts on the first entry again)
            key(cdp, sid, "End")
            self.assertEqual(cdp.js("document.activeElement.dataset.rm", sid), "archive")
            key(cdp, sid, "Home")
            key(cdp, sid, "Enter")                                      # Open the peek
            self.until(cdp, sid, f"location.hash.includes('item={a}')", "Enter on Open the peek")
            self.shut(cdp, sid)

    def test_move_due_date_offers_friday_and_a_week_on_and_a_date_to_pick(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            a = self.id_of("Order the laptops")
            self.open_menu(cdp, sid, self.TABLE % a)
            click(cdp, sid, "[data-rm=due]")
            self.until(cdp, sid, "!!document.querySelector('[data-rm=pick]')", "the list")
            self.assertEqual([e[1:2] + e[3:] for e in self.entries(cdp, sid)], [["Friday", "30-10-2026"], ["A week on", "05-11-2026"], ["Pick a date", ""], ["No date", ""], ["‹ Back", ""]])
            click(cdp, sid, "[data-rm='d:2026-10-30']")
            self.wait_toast(cdp, sid, "done")
            self.assertEqual(self.row(a)["due_date"], "2026-10-30")
            self.open_menu(cdp, sid, self.TABLE % a)
            click(cdp, sid, "[data-rm=due]")
            click(cdp, sid, "[data-rm=pick]")
            self.until(cdp, sid, "!!document.querySelector('.cpop.cdate')", "the date picker")
            self.assertFalse(cdp.js("!!document.querySelector('.rowmenu [role=menu]')", sid), "the picker replaces the list")
            key(cdp, sid, "Escape")
            self.until(cdp, sid, "!document.querySelector('.cpop')")
            self.assertEqual(cdp.js("document.activeElement.dataset.id", sid), a)
            self.assertEqual(self.row(a)["due_date"], "2026-10-30")

    def test_change_owner_lists_the_people_of_the_project(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            a = self.id_of("Order the laptops")
            self.open_menu(cdp, sid, self.TABLE % a)
            click(cdp, sid, "[data-rm=owner]")
            self.until(cdp, sid, "!!document.querySelector('[data-rm=back]')", "the list")
            names = [e[1] for e in self.entries(cdp, sid)]
            self.assertNotIn("Sara Khan", names, "not the current owner")
            self.assertIn("Priya Nair", names)
            click(cdp, sid, "[data-rm='o:Priya Nair']")
            self.assertEqual(self.wait_toast(cdp, sid, "done")["text"], f"Owner of {a} changed to Priya Nair.")
            self.assertEqual(self.row(a)["owner"], "Priya Nair")
            self.open_menu(cdp, sid, self.TABLE % a)
            self.assertEqual(self.entries(cdp, sid)[0][1], "Draft email to Priya Nair", "the draft entry follows the owner")

    def test_archive_hides_the_item_and_undo_brings_it_back_nothing_is_deleted(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            a = self.id_of("Order the laptops")
            before = self.steps()
            self.open_menu(cdp, sid, self.TABLE % a)
            click(cdp, sid, "[data-rm=archive]")
            t = self.wait_toast(cdp, sid, "done")
            self.assertEqual((t["text"], t["undo"]), (f"{a} archived. It is out of the lists and the published page.", True))
            self.until(cdp, sid, f"!document.querySelector(\"{self.TABLE % a}\")", "the row to leave the list")
            self.assertEqual((self.row(a)["archived"], self.steps()), (1, before + 1))
            self.assertEqual(len(self.query("SELECT 1 FROM actions WHERE id = ?", a)), 1, "the record is still in the database")
            click(cdp, sid, "[data-undo]")
            self.until(cdp, sid, f"!!document.querySelector(\"{self.TABLE % a}\")", "the row to come back")
            self.assertEqual(self.row(a)["archived"], 0)
            self.assertEqual(cdp.js("document.querySelector('.toast-text').textContent", sid), f"{a} is back.")

    def test_duplicate_adds_a_copy_in_one_step_with_undo(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            a = self.id_of("Order the laptops")
            old = self.row(a)
            n, before = len(self.query("SELECT id FROM actions")), self.steps()
            self.open_menu(cdp, sid, self.TABLE % a)
            click(cdp, sid, "[data-rm=dup]")
            self.assertEqual(self.wait_toast(cdp, sid, "done")["text"], f"Copy of {a} added.")
            now = self.query("SELECT * FROM actions WHERE description = 'Copy of Order the laptops'")
            self.assertEqual((len(now), len(self.query("SELECT id FROM actions")), self.steps()), (1, n + 1, before + 1))
            copy = now[0]
            self.assertEqual((copy["owner"], copy["priority"], copy["due_date"], copy["workstream"], copy["milestone"], copy["status"]),
                             (old["owner"], old["priority"], old["due_date"], old["workstream"], old["milestone"], "Open"))
            self.until(cdp, sid, f"!!document.querySelector(\"{self.TABLE % copy['id']}\")", "the copy in the list")
            click(cdp, sid, "[data-undo]")
            self.until(cdp, sid, f"!document.querySelector(\"{self.TABLE % copy['id']}\")", "the copy to go again")

    def test_duplicate_works_for_a_risk_and_a_decision_too(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            for text, table, col in (("Supplier slips", "raid", "description"), ("Use the new tool", "decisions", "decision")):
                ref = self.id_of(text)
                self.open_menu(cdp, sid, self.TABLE % ref)
                click(cdp, sid, "[data-rm=dup]")
                self.assertTrue(wait(lambda: len(self.query(f"SELECT id FROM {table} WHERE {col} = ?", "Copy of " + text)) == 1), table)

    def test_copy_id_and_copy_link_put_text_on_the_clipboard_and_say_so(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            before = self.steps()
            cdp.js("window.__clip = []; Object.defineProperty(navigator, 'clipboard', {value: {writeText: (t) => { window.__clip.push(t); return Promise.resolve(); }}, configurable: true})", sid)
            a = self.id_of("Order the laptops")
            self.open_menu(cdp, sid, self.TABLE % a)
            click(cdp, sid, "[data-rm=copyid]")
            self.until(cdp, sid, "window.__clip.length === 1")
            self.assertEqual(cdp.js("window.__clip[0]", sid), a)
            self.assertEqual(self.wait_toast(cdp, sid)["text"], f"{a} copied.")
            self.assertEqual(cdp.js("document.querySelector('#work-live').textContent", sid), f"{a} copied.")
            self.open_menu(cdp, sid, self.TABLE % a)
            click(cdp, sid, "[data-rm=link]")
            self.until(cdp, sid, "window.__clip.length === 2")
            self.assertTrue(cdp.js("window.__clip[1]", sid).endswith(f"#work&p=ABC&item={a}"), cdp.js("window.__clip[1]", sid))
            self.assertEqual(self.steps(), before)

    def test_in_view_the_changes_are_greyed_and_the_rest_still_works(self):
        with chrome() as cdp:
            sid = self.visit(cdp, edit=False)
            a, before = self.id_of("Order the laptops"), self.steps()
            self.open_menu(cdp, sid, self.TABLE % a)
            by = {e[0]: e for e in self.entries(cdp, sid)}
            for k in ("status", "due", "owner", "dup", "archive"):
                self.assertTrue(by[k][2], k)
            for k in ("peek", "link", "copyid"):
                self.assertFalse(by[k][2], k)
            self.assertIn("Switch to Edit to change this.", cdp.js("document.querySelector('.rowmenu').textContent", sid))
            click(cdp, sid, "[data-rm=archive]")
            self.assertTrue(cdp.js("!!document.querySelector('.rowmenu')", sid), "a greyed entry does nothing")
            self.assertEqual(self.steps(), before)
            click(cdp, sid, "[data-rm=peek]")
            self.until(cdp, sid, f"location.hash.includes('item={a}')")
            self.shut(cdp, sid)

    def test_on_the_board_and_in_full_screen(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            a, b = self.id_of("Order the laptops"), self.id_of("Send the invitations")
            self.open_menu(cdp, sid, self.CARD % a)
            self.assertEqual(cdp.js("document.querySelector('.rowmenu [role=menu]').getAttribute('aria-label')", sid), f"Actions for {a}")
            self.assertEqual(self.entries(cdp, sid)[0][1], "Draft email to Sara Khan")
            key(cdp, sid, "Escape")
            self.shut(cdp, sid)
            self.assertEqual(cdp.js("document.activeElement.closest('article').dataset.id", sid), a, "focus is back on the card")
            before = self.steps()
            click(cdp, sid, "#board-full")
            self.until(cdp, sid, "document.body.classList.contains('board-full')")
            self.open_menu(cdp, sid, self.CARD % b)
            click(cdp, sid, "[data-rm=status]")
            click(cdp, sid, "[data-rm='s:Closed']")
            self.wait_toast(cdp, sid, "done")
            self.assertEqual((self.row(b)["status"], self.steps()), ("Closed", before + 1))
            self.assertTrue(cdp.js("document.body.classList.contains('board-full')", sid), "full screen stays")
            self.until(cdp, sid, f"!document.querySelector(\"{self.CARD % b}\") || document.querySelector(\"{self.CARD % b}\").closest('section').dataset.col === 'Closed'", "the card in its new column")
            cdp.js(f"document.querySelector(\"article[data-id='{a}'] .bc-main\").focus()", sid)
            key(cdp, sid, "F10", shift=True)
            self.until(cdp, sid, "!!document.querySelector('.rowmenu [role=menu]')", "the keys open it on a card too")
            key(cdp, sid, "Escape")
            self.shut(cdp, sid)
            self.assertTrue(cdp.js("document.body.classList.contains('board-full')", sid), "Esc closed the menu only, not full screen")

    def test_at_900_px_the_menu_stays_inside_the_window(self):
        with chrome() as cdp:
            sid = self.visit(cdp, width=900, height=500)
            rows = cdp.js("[...document.querySelectorAll('tr[data-id]')].map(r => r.dataset.id)", sid)
            self.open_menu(cdp, sid, self.TABLE % rows[-1])
            box = cdp.js("(() => { const b = document.querySelector('.rowmenu').getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom]; })()", sid)
            self.assertTrue(box[0] >= 0 and box[1] >= 0 and box[2] <= 900 and box[3] <= 500, box)

    def test_the_published_page_has_no_menu(self):
        view = (ROOT / "src" / "clark" / "page" / "page-view.html").read_text(encoding="utf-8")
        for word in ("data-rowmenu", "clark:draft-email", "Copy link to this item"):
            self.assertNotIn(word, view)


if __name__ == "__main__":
    unittest.main()
