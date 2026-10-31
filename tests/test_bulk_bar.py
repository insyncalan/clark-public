"""#196 stage 2: changing several work items at once on the page: the bar, the right-click menu (and Shift+F10 and the Menu key),
the keys O S P T C, a cell of a selected row, the question above 25, one Undo, and Help.

Run: python3 dev/run_tests.py test_bulk_bar
Part 1 runs the page's own rules (src/clark/page/src/edit/bulkLogic.js, bundled by the pinned esbuild) in headless Chrome. Part 2
loads the real page against the real server, whose change and undo routes are clark.changes over a demo database (fictional data),
with real DevTools mouse and key events, so every change is checked in the database. Desktop (1400) and 900 px only.
"""
import json
import sys
import unittest

from _paths import SRC

from test_multi_select import CTRL, META, MOD, SHIFT, press, tap  # noqa: E402
from test_server import Running, chrome, wait  # noqa: E402
from test_work_board_page import Base  # noqa: E402
from test_work_filters import click  # noqa: E402
from test_work_items import bundled  # noqa: E402

LOGIC = SRC / "clark" / "page" / "src" / "edit" / "bulkLogic.js"
LETTERS = {k: (ord(k.upper()), k, "Key" + k.upper()) for k in "ospctvz"}


def letter(cdp, sid, k, mods=0):
    vk, text, code = LETTERS[k]
    common = {"key": k, "code": code, "windowsVirtualKeyCode": vk, "modifiers": mods}
    cdp.call("Input.dispatchKeyEvent", {"type": "keyDown", **common, **({} if mods & (CTRL | META) else {"text": text})}, sid)
    cdp.call("Input.dispatchKeyEvent", {"type": "keyUp", **common}, sid)


def special(cdp, sid, key, code, vk, mods=0):
    common = {"key": key, "code": code, "windowsVirtualKeyCode": vk, "modifiers": mods}
    cdp.call("Input.dispatchKeyEvent", {"type": "rawKeyDown", **common}, sid)
    cdp.call("Input.dispatchKeyEvent", {"type": "keyUp", **common}, sid)


class Rules(unittest.TestCase):
    """The rules on their own, through the page's own module in Chrome."""

    @classmethod
    def setUpClass(cls):
        cls.stack = chrome()
        cls.cdp = cls.stack.__enter__()
        cls.server = Running(page_html=lambda: "<!doctype html><title>t</title>")
        tid = next(t["targetId"] for t in cls.cdp.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
        cls.sid = cls.cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
        cls.cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{cls.server.port}/"}, cls.sid)
        assert wait(lambda: cls.cdp.js("document.readyState === 'complete'", cls.sid))
        cls.cdp.js(bundled(LOGIC, "B"), cls.sid)

    @classmethod
    def tearDownClass(cls):
        cls.server.close()
        cls.stack.__exit__(None, None, None)

    def run_(self, expr):
        return json.loads(self.cdp.js(f"JSON.stringify((() => {{ {expr} }})())", self.sid))

    A = "const a = (id) => ({id, kind: 'action', table: 'actions'}), r = (id) => ({id, kind: 'risk', table: 'raid'}), d = (id) => ({id, kind: 'decision', table: 'decisions'});"

    def controls(self, rows, editing=True):
        return self.run_(self.A + f"return B.controls(B.summary([{rows}]), {{editing: {json.dumps(editing)}}}).map(c => [c.id, c.on, c.why]);")

    def test_each_kind_has_its_own_controls(self):
        self.assertEqual([c[0] for c in self.controls("a('ABC-A-001'), a('ABC-A-002')")],
                         ["close", "reopen", "status", "owner", "due", "priority", "workstream", "milestone"])
        self.assertEqual([c[0] for c in self.controls("r('ABC-001'), r('ABC-002')")],
                         ["close", "reopen", "status", "owner", "due", "impact", "likelihood", "workstream", "milestone"])
        self.assertEqual(self.controls("d('ABC-D-001'), d('ABC-D-002')"), [["made_by", True, ""]], "a decision offers only Made by")
        self.assertTrue(all(c[1] for c in self.controls("a('ABC-A-001'), a('ABC-A-002')")))

    def test_mixed_kinds_turn_every_field_off_with_the_reason(self):
        got = self.controls("a('ABC-A-001'), r('ABC-002')")
        self.assertTrue(got and all(not on and why == "These items are of different kinds" for _, on, why in got), got)

    def test_other_projects_turn_off_workstream_and_milestone_only(self):
        got = {c[0]: c for c in self.controls("a('ABC-A-001'), a('XYZ-A-002')")}
        self.assertEqual((got["workstream"][1:], got["milestone"][1:]), ([False, "These items are in different projects"],) * 2)
        self.assertTrue(got["owner"][1] and got["close"][1])

    def test_view_says_to_switch_to_edit(self):
        self.assertEqual({c[2] for c in self.controls("a('ABC-A-001'), a('ABC-A-002')", editing=False)}, {"Switch to Edit to change these"})

    def test_what_is_sent(self):
        got = self.run_("return [B.changesFor('actions', 'close'), B.changesFor('raid', 'reopen'), B.changesFor('decisions', 'made_by', '  Zelda   Quince '),"
                        " B.changesFor('actions', 'owner', ''), B.changesFor('actions', 'due', ''), B.changesFor('actions', 'milestone', ''),"
                        " B.changesFor('raid', 'impact', 'High'), B.requestFor('actions', ['ABC-A-001'], {status: 'Closed'}),"
                        " B.requestFor('actions', ['ABC-A-001'], {status: 'Closed'}, {confirm: true, place: 'menu'})];")
        self.assertEqual(got, [{"status": "Closed"}, {"status": "Open"}, {"made_by": "Zelda Quince"}, None, {"due_date": None}, {"milestone": None},
                               {"impact": "High"}, {"kind": "actions", "op": "bulk", "ids": ["ABC-A-001"], "changes": {"status": "Closed"}, "place": "bulk"},
                               {"kind": "actions", "op": "bulk", "ids": ["ABC-A-001"], "changes": {"status": "Closed"}, "place": "menu", "confirm": True}])

    def test_the_question_is_asked_above_25(self):
        self.assertEqual(self.run_("return [B.needsConfirm(25), B.needsConfirm(26), B.confirmWords(26)];"), [False, True, "Change 26 items?"])

    def test_a_cell_of_a_selected_row(self):
        got = self.run_(self.A + "const s = [a('ABC-A-001'), a('ABC-A-002'), a('ABC-A-003')];"
                        " return [B.cellPlan('ABC-A-002', 'owner', s), B.cellPlan('ABC-A-009', 'owner', s), B.cellPlan('ABC-A-001', 'owner', s.slice(0, 1)),"
                        " B.cellPlan('ABC-A-001', 'owner', [a('ABC-A-001'), r('ABC-002')]).why, B.cellPlan('ABC-D-001', 'due', [d('ABC-D-001'), d('ABC-D-002')]).why,"
                        " B.cellPlan('ABC-001', 'priority', [r('ABC-001'), r('ABC-002')]).why, B.cellPlan('ABC-D-001', 'owner', [d('ABC-D-001'), d('ABC-D-002')]).question];")
        self.assertEqual(got[0], {"id": "owner", "question": "Change the owner of all 3 selected items?", "n": 3, "table": "actions",
                                  "ids": ["ABC-A-001", "ABC-A-002", "ABC-A-003"]})
        self.assertEqual(got[1:3], [None, None], "a row that is not selected, or a selection of one, changes only that row")
        self.assertEqual(got[3], "These items are of different kinds, so the owner can't be changed for all of them. Clear the selection to change only this one.")
        self.assertEqual(got[4], "A decision takes only who makes it. Clear the selection to change only this one.")
        self.assertEqual(got[5], "A risk's or issue's priority comes from its impact and likelihood. Clear the selection to change only this one.")
        self.assertEqual(got[6], "Change the decider of all 2 selected items?")

    def test_the_keys(self):
        got = self.run_(self.A + "return [['o', 's', 'p', 't', 'c', 'v', 'x'].map(k => B.keyControl(k, 'actions')), B.keyControl('O', 'decisions'),"
                        " B.keyWhy('priority', B.summary([r('ABC-001')])), B.keyWhy('status', B.summary([d('ABC-D-001')])),"
                        " B.keyWhy('owner', B.summary([a('ABC-A-001'), r('ABC-001')])), B.keyWhy('owner', B.summary([a('ABC-A-001')]), false), B.keyWhy('close', B.summary([a('ABC-A-001')]))];")
        self.assertEqual(got[0], ["owner", "status", "priority", "due", "close", None, None])
        self.assertEqual(got[1], "made_by")
        self.assertEqual(got[2:], ["A risk's or issue's priority comes from its impact and likelihood. Change its impact or likelihood instead.",
                                   "A decision takes only who makes it.", "These items are of different kinds.", "Switch to Edit to change these.", ""])

    def test_words(self):
        self.assertEqual(self.run_("return [B.itemsWords(1), B.itemsWords(3), B.pickerLabel('status', 3), B.backWords(1), B.backWords(4), B.copyText(['ABC-A-001', 'ABC-002'])];"),
                         ["1 item", "3 items", "Status of 3 items", "Undone: 1 item is back as it was.", "Undone: 4 items are back as they were.", "ABC-A-001, ABC-002"])


class Page(Base):
    """The real page, in Edit unless it says View."""

    ROWS = "[...document.querySelectorAll('#work-list tr[data-id]')].map(r => r.dataset.id)"

    def load(self, cdp, width=1400, edit=True, kind="action", mode="all"):
        sid = self.visit(cdp, width=width, edit=edit)
        click(cdp, sid, f"[data-show={mode}]")
        if kind:
            click(cdp, sid, f"[data-type={kind}]")
            self.until(cdp, sid, f"document.querySelector('[data-type={kind}]').getAttribute('aria-pressed') === 'true'", "the type")
        self.until(cdp, sid, "document.querySelectorAll('#work-list tr[data-id]').length >= 2", "the rows")
        return sid

    def rsel(self, rid):
        return f"#work-list tr[data-id='{rid}'] .c-item .t"

    def pick(self, cdp, sid, ids):
        tap(cdp, sid, self.rsel(ids[0]))
        for rid in ids[1:]:
            tap(cdp, sid, self.rsel(rid), MOD)
        self.assertEqual(cdp.js("clarkPage.selected()", sid), ids)

    def bulk_sent(self):
        return [r for w, r in self.sent if w == "change" and r.get("op") == "bulk"]

    def toast(self, cdp, sid):
        self.until(cdp, sid, "!!document.querySelector('.toast .toast-text')", "the toast")
        return cdp.js("document.querySelector('.toast .toast-text').textContent", sid)

    def field(self, ref, f):
        return self.row(ref)[f]

    # ---- the bar ----
    def test_the_bar_changes_the_owner_of_every_selected_row_in_one_step_and_one_undo(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = cdp.js(self.ROWS, sid)[:3]
            was = {r: self.field(r, "owner") for r in rows}
            self.pick(cdp, sid, rows)
            bar = cdp.js("[...document.querySelectorAll('#sel-bar [data-bulk]')].map(b => b.textContent)", sid)
            self.assertEqual(bar, ["Close", "Reopen", "Status", "Owner", "Due date", "Priority", "Workstream", "Milestone"])
            steps = self.steps()
            click(cdp, sid, "#sel-bar [data-bulk=owner]")
            self.until(cdp, sid, "document.activeElement && document.activeElement.classList.contains('cp-in')", "the owner box")
            self.assertEqual(cdp.js("document.querySelector('.cpop').getAttribute('aria-label')", sid), "Owner of 3 items")
            cdp.js("document.execCommand('insertText', false, 'Zelda Quince')", sid)
            press(cdp, sid, "Enter")
            self.assertIn("Changed 3 items.", self.toast(cdp, sid))
            self.assertEqual([r["ids"] for r in self.bulk_sent()], [rows])
            self.assertEqual(self.steps(), steps + 1, "one step")
            self.assertEqual({r: self.field(r, "owner") for r in rows}, {r: "Zelda Quince" for r in rows})
            self.until(cdp, sid, "clarkPage.selected().length === 0", "the selection clears after the change")
            click(cdp, sid, ".toast [data-undo]")
            self.until(cdp, sid, "document.querySelector('.toast .toast-text') && document.querySelector('.toast .toast-text').textContent.startsWith('Undone')", "the undo")
            self.assertEqual(cdp.js("document.querySelector('.toast .toast-text').textContent", sid), "Undone: 3 items are back as they were.")
            self.assertEqual({r: self.field(r, "owner") for r in rows}, was, "one Undo puts every item back")
            self.assertEqual(len([1 for w, _ in self.sent if w == "undo"]), 1)

    def test_close_and_reopen_from_the_bar(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = [r for r in cdp.js(self.ROWS, sid) if self.field(r, "status") != "Closed"][:2]
            self.pick(cdp, sid, rows)
            click(cdp, sid, "#sel-bar [data-bulk=close]")
            self.assertIn("Changed 2 items.", self.toast(cdp, sid))
            self.assertEqual([self.field(r, "status") for r in rows], ["Closed", "Closed"])
            self.pick(cdp, sid, rows)
            click(cdp, sid, "#sel-bar [data-bulk=reopen]")
            self.assertTrue(wait(lambda: [self.field(r, "status") for r in rows] == ["Open", "Open"]), "reopened")
            self.assertEqual([q["changes"] for q in self.bulk_sent()], [{"status": "Closed"}, {"status": "Open"}])

    def test_a_status_from_the_bar_and_nothing_changed_when_they_have_it(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = [r for r in cdp.js(self.ROWS, sid) if self.field(r, "status") == "Open"][:2]
            self.pick(cdp, sid, rows)
            click(cdp, sid, "#sel-bar [data-bulk=status]")
            self.until(cdp, sid, "!!document.querySelector('.cpop [data-value=Open]')", "the status menu")
            click(cdp, sid, ".cpop [data-value=Open]")
            self.assertEqual(self.toast(cdp, sid), "Nothing changed: they already have that.")
            self.assertFalse(cdp.js("!!document.querySelector('.toast [data-undo]')", sid), "no Undo when nothing changed")
            self.assertEqual(cdp.js("clarkPage.selected()", sid), rows, "nothing saved: the selection stays")

    def test_mixed_kinds_turn_every_field_off_and_say_why(self):
        with chrome() as cdp:
            sid = self.load(cdp, kind=None)
            a, r = self.id_of("Book the training room"), self.id_of("Supplier slips")
            self.pick(cdp, sid, [a, r])
            offs = cdp.js("[...document.querySelectorAll('#sel-bar [data-bulk]')].map(b => b.getAttribute('aria-disabled'))", sid)
            self.assertTrue(offs and set(offs) == {"true"}, offs)
            self.assertEqual(cdp.js("document.querySelector('#sel-why').textContent", sid), "These items are of different kinds")
            click(cdp, sid, "#sel-bar [data-bulk=owner]")
            self.assertEqual(self.bulk_sent(), [], "an off control sends nothing")

    def test_decisions_offer_only_made_by(self):
        with chrome() as cdp:
            sid = self.load(cdp, kind="decision")
            rows = cdp.js(self.ROWS, sid)[:2]
            self.pick(cdp, sid, rows)
            self.assertEqual(cdp.js("[...document.querySelectorAll('#sel-bar [data-bulk]')].map(b => b.textContent)", sid), ["Made by"])
            click(cdp, sid, "#sel-bar [data-bulk=made_by]")
            self.until(cdp, sid, "document.activeElement && document.activeElement.classList.contains('cp-in')", "the box")
            cdp.js("document.execCommand('insertText', false, 'Steering group')", sid)
            press(cdp, sid, "Enter")
            self.assertIn("Changed 2 items.", self.toast(cdp, sid))
            self.assertEqual([self.field(x, "made_by") for x in rows], ["Steering group"] * 2)

    def test_left_out_items_are_named(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = [r for r in cdp.js(self.ROWS, sid) if self.field(r, "status") != "Closed"][:3]
            self.pick(cdp, sid, rows)
            with self.store.step("dashboard", "Demo User") as st:     # archived while the page still shows it
                st.archive("actions", rows[2])
            click(cdp, sid, "#sel-bar [data-bulk=close]")
            text = self.toast(cdp, sid)
            self.assertIn("Changed 2 items.", text)
            self.assertIn(f"Left out {rows[2]}: It is archived. Restore it first.", text)

    # ---- the question above 25 ----
    def test_the_question_at_25_and_26(self):
        with self.store.step("dashboard", "Demo User") as st:
            for n in range(21):                                        # 26 actions with the five of the demo
                st.create("actions", {"project": "ABC", "description": f"Extra task {n + 1}", "owner": "TBC", "raised": "2026-10-01", "source": "demo"})
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = cdp.js(self.ROWS, sid)
            self.assertEqual(len(rows), 26)
            tap(cdp, sid, self.rsel(rows[0]))
            tap(cdp, sid, self.rsel(rows[24]), SHIFT)
            click(cdp, sid, "#sel-bar [data-bulk=owner]")
            self.until(cdp, sid, "document.activeElement && document.activeElement.classList.contains('cp-in')", "the box")
            cdp.js("document.execCommand('insertText', false, 'Zelda Quince')", sid)
            press(cdp, sid, "Enter")
            self.assertIn("Changed", self.toast(cdp, sid))
            self.assertFalse(cdp.js("!!document.querySelector('.bask')", sid), "25 asks nothing")
            self.assertEqual(len(self.bulk_sent()[-1]["ids"]), 25)
            press(cdp, sid, "Escape")
            cdp.js(f"document.querySelector(\"tr[data-id='{rows[0]}']\").focus()", sid)
            press(cdp, sid, "a", MOD)
            self.assertEqual(len(cdp.js("clarkPage.selected()", sid)), 26)
            sent = len(self.bulk_sent())
            click(cdp, sid, "#sel-bar [data-bulk=owner]")
            self.until(cdp, sid, "document.activeElement && document.activeElement.classList.contains('cp-in')", "the box")
            cdp.js("document.execCommand('insertText', false, 'Ada Quillfeather')", sid)
            press(cdp, sid, "Enter")
            self.until(cdp, sid, "!!document.querySelector('.bask')", "the question")
            self.assertEqual(cdp.js("document.querySelector('.bask-q').textContent", sid), "Change 26 items?")
            self.assertEqual(len(self.bulk_sent()), sent, "nothing is sent before the answer")
            press(cdp, sid, "Escape")
            self.until(cdp, sid, "!document.querySelector('.bask')", "Esc says no")
            self.assertEqual(len(self.bulk_sent()), sent)
            click(cdp, sid, "#sel-bar [data-bulk=close]")
            self.until(cdp, sid, "!!document.querySelector('.bask')", "the question again")
            click(cdp, sid, "[data-bask=yes]")
            self.assertTrue(wait(lambda: len(self.bulk_sent()) == sent + 1), "sent after the answer")
            last = self.bulk_sent()[-1]
            self.assertEqual((len(last["ids"]), last.get("confirm")), (26, True))

    # ---- the right-click menu, Shift+F10 and the Menu key ----
    def menu_items(self, cdp, sid):
        self.until(cdp, sid, "!!document.querySelector('.bmenu')", "the menu")
        return cdp.js("[...document.querySelectorAll('.bmenu [data-bulk-menu]')].map(b => [b.dataset.bulkMenu, b.getAttribute('aria-disabled') !== 'true'])", sid)

    def right_click(self, cdp, sid, selector):
        x, y = __import__("test_work_filters").where(cdp, sid, selector)
        cdp.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "right", "buttons": 2, "clickCount": 1}, sid)
        cdp.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "right", "buttons": 0, "clickCount": 1}, sid)

    def test_the_right_click_menu_on_a_selection_and_on_a_lone_row(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = [r for r in cdp.js(self.ROWS, sid) if self.field(r, "status") != "Closed"]
            self.pick(cdp, sid, rows[:2])
            self.right_click(cdp, sid, self.rsel(rows[1]))
            got = self.menu_items(cdp, sid)
            self.assertEqual(cdp.js("document.querySelector('.bmenu .bm-h').textContent", sid), "2 items")
            self.assertEqual([g[0] for g in got], ["close", "reopen", "status", "owner", "due", "priority", "workstream", "milestone", "copy"])
            click(cdp, sid, ".bmenu [data-bulk-menu=close]")
            self.assertIn("Changed 2 items.", self.toast(cdp, sid))
            self.assertEqual(self.bulk_sent()[-1]["place"], "menu")
            self.right_click(cdp, sid, self.rsel(rows[3]))
            self.menu_items(cdp, sid)
            self.assertEqual(cdp.js("document.querySelector('.bmenu .bm-h').textContent", sid), "1 item", "a row that is not selected is selected on its own")
            self.assertEqual(cdp.js("clarkPage.selected()", sid), [rows[3]])
            press(cdp, sid, "Escape")
            self.until(cdp, sid, "!document.querySelector('.bmenu')", "Esc closes the menu")

    def test_shift_f10_and_the_menu_key_open_it_and_mixed_kinds_offer_only_copy_ids(self):
        with chrome() as cdp:
            sid = self.load(cdp, kind=None)
            a, r = self.id_of("Book the training room"), self.id_of("Supplier slips")
            self.pick(cdp, sid, [a, r])
            cdp.js(f"document.querySelector(\"tr[data-id='{a}']\").focus()", sid)
            special(cdp, sid, "F10", "F10", 121, SHIFT)
            self.assertEqual(self.menu_items(cdp, sid), [["copy", True]])
            self.assertEqual(cdp.js("document.querySelector('.bmenu .bm-why').textContent", sid), "These items are of different kinds")
            cdp.js("window.copied = null; navigator.clipboard.writeText = (t) => { window.copied = t; return Promise.resolve(); }", sid)
            click(cdp, sid, ".bmenu [data-bulk-menu=copy]")
            self.until(cdp, sid, "window.copied !== null", "Copy IDs")
            self.assertEqual(cdp.js("window.copied", sid), f"{a}, {r}")
            cdp.js(f"document.querySelector(\"tr[data-id='{a}']\").focus()", sid)
            special(cdp, sid, "ContextMenu", "ContextMenu", 93)
            self.menu_items(cdp, sid)
            press(cdp, sid, "Escape")
            self.assertEqual(self.bulk_sent(), [])

    def test_the_menu_on_a_card(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            self.board(cdp, sid)
            cards = cdp.js("[...document.querySelectorAll('#work-board article.bcard')].map(c => c.dataset.id)", sid)
            self.right_click(cdp, sid, f"article.bcard[data-id='{cards[0]}'] .bc-title")
            self.assertTrue(self.menu_items(cdp, sid))
            click(cdp, sid, ".bmenu [data-bulk-menu=owner]")
            self.until(cdp, sid, "document.activeElement && document.activeElement.classList.contains('cp-in')", "the box")
            cdp.js("document.execCommand('insertText', false, 'Zelda Quince')", sid)
            press(cdp, sid, "Enter")
            self.assertIn("Changed 1 item.", self.toast(cdp, sid))
            self.assertEqual((self.field(cards[0], "owner"), self.bulk_sent()[-1]["place"]), ("Zelda Quince", "board"))

    # ---- the keys ----
    def focus(self, cdp, sid, rid):
        cdp.js(f"document.querySelector(\"tr[data-id='{rid}']\").focus()", sid)

    def test_o_s_t_and_c_on_a_row_and_on_a_selection(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = [r for r in cdp.js(self.ROWS, sid) if self.field(r, "status") != "Closed"]
            self.focus(cdp, sid, rows[0])
            letter(cdp, sid, "o")
            self.until(cdp, sid, "document.activeElement && document.activeElement.classList.contains('cp-in')", "O opens the owner box")
            self.assertEqual(cdp.js("document.querySelector('.cpop').getAttribute('aria-label')", sid), "Owner of 1 item")
            press(cdp, sid, "Escape")
            self.until(cdp, sid, "!document.querySelector('.cpop')", "Esc closes it")
            self.focus(cdp, sid, rows[0])
            letter(cdp, sid, "s")
            self.until(cdp, sid, "!!document.querySelector('.cpop [data-value=Delayed]')", "S opens the status menu")
            press(cdp, sid, "Escape")
            self.focus(cdp, sid, rows[0])
            letter(cdp, sid, "t")
            self.until(cdp, sid, "!!document.querySelector('.cpop.cdate')", "T opens the date picker")
            press(cdp, sid, "Escape")
            self.focus(cdp, sid, rows[0])
            letter(cdp, sid, "p")
            self.until(cdp, sid, "!!document.querySelector('.cpop [data-value=Urgent]')", "P opens the priority menu")
            press(cdp, sid, "Escape")
            self.assertEqual(self.bulk_sent(), [], "opening and closing sends nothing")
            self.pick(cdp, sid, rows[:2])
            self.focus(cdp, sid, rows[1])
            letter(cdp, sid, "c")
            self.assertIn("Changed 2 items.", self.toast(cdp, sid))
            self.assertEqual(self.bulk_sent()[-1]["ids"], rows[:2], "C closes the whole selection")

    def test_p_on_a_risk_says_why_and_the_keys_are_silent_where_they_must_be(self):
        with chrome() as cdp:
            sid = self.load(cdp, kind="risk")
            risk = cdp.js(self.ROWS, sid)[0]
            self.focus(cdp, sid, risk)
            letter(cdp, sid, "p")
            self.assertIn("priority comes from its impact and likelihood", self.toast(cdp, sid))
            click(cdp, sid, "[data-mode=view]")
            self.until(cdp, sid, "document.querySelector('[data-mode=view]').getAttribute('aria-pressed') === 'true'", "View")
            self.focus(cdp, sid, risk)
            for k in "ospct":
                letter(cdp, sid, k)
            self.assertFalse(cdp.js("!!document.querySelector('.cpop, .bask')", sid), "no key acts in View")
            self.assertNotIn("Switch to Edit", cdp.js("document.querySelector('#work-live').textContent", sid), "in View a letter is not even answered")
            click(cdp, sid, "[data-mode=edit]")
            cdp.js("document.activeElement.blur()", sid)
            letter(cdp, sid, "c")
            letter(cdp, sid, "o")
            self.assertFalse(cdp.js("!!document.querySelector('.cpop, .bask')", sid), "nothing acts when the table has no keyboard")
            self.focus(cdp, sid, risk)
            for mods in (CTRL, META):
                letter(cdp, sid, "z", mods)
                letter(cdp, sid, "c", mods)
            self.assertFalse(cdp.js("!!document.querySelector('.cpop, .bask')", sid), "Cmd or Ctrl with a letter is never taken")
            cdp.js("localStorage.setItem('clark.single-keys', 'off')", sid)
            self.reload(cdp, sid)
            cdp.js("document.querySelector('[data-mode=edit]').click()", sid)
            self.until(cdp, sid, f"!!document.querySelector(\"tr[data-id='{risk}']\")", "the row")
            self.focus(cdp, sid, risk)
            letter(cdp, sid, "c")
            letter(cdp, sid, "o")
            self.assertFalse(cdp.js("!!document.querySelector('.cpop, .bask')", sid), "off with the Single-key switch")
            self.assertEqual(self.bulk_sent(), [])

    def test_keys_on_the_item_open_in_the_peek(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rid = [r for r in cdp.js(self.ROWS, sid) if self.field(r, "status") != "Closed"][0]
            cdp.js(f"clarkPage.openPeek('{rid}', 'item')", sid)
            self.until(cdp, sid, f"clarkPage.peek() && clarkPage.peek().id === '{rid}'", "the item is open")
            # The peek itself is #42's, not on the page yet: a stand-in root with the same mark, holding a button with the keyboard.
            cdp.js("(() => { const p = document.createElement('aside'); p.setAttribute('data-peek', ''); p.setAttribute('role', 'dialog');"
                   " p.innerHTML = '<button type=button>Details</button>'; document.body.append(p); p.querySelector('button').focus(); })()", sid)
            letter(cdp, sid, "c")
            self.assertIn("Changed 1 item.", self.toast(cdp, sid))
            self.assertEqual(self.bulk_sent()[-1]["ids"], [rid])

    # ---- a cell of a selected row ----
    def test_a_cell_of_a_selected_row_changes_every_selected_row_after_saying_so(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = cdp.js(self.ROWS, sid)[:3]
            self.pick(cdp, sid, rows)
            click(cdp, sid, f"#work-list tr[data-id='{rows[1]}'] [data-cell$=':priority']")
            self.until(cdp, sid, "!!document.querySelector('.cpop [data-value=Low]')", "the priority menu")
            click(cdp, sid, ".cpop [data-value=Low]")
            self.until(cdp, sid, "!!document.querySelector('.bask')", "the question")
            self.assertEqual(cdp.js("document.querySelector('.bask-q').textContent", sid), "Change the priority of all 3 selected items?")
            self.assertEqual(self.bulk_sent(), [], "it says so before it does")
            click(cdp, sid, "[data-bask=yes]")
            self.assertTrue(wait(lambda: [self.field(r, "priority") for r in rows] == ["Low"] * 3), "every selected row changed")
            self.assertEqual(self.bulk_sent()[-1]["place"], "cell")

    def test_cancel_on_the_question_changes_nothing(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = cdp.js(self.ROWS, sid)[:2]
            was = [self.field(r, "priority") for r in rows]
            self.pick(cdp, sid, rows)
            click(cdp, sid, f"#work-list tr[data-id='{rows[0]}'] [data-cell$=':priority']")
            self.until(cdp, sid, "!!document.querySelector('.cpop [data-value=Urgent]')", "the menu")
            click(cdp, sid, ".cpop [data-value=Urgent]")
            self.until(cdp, sid, "!!document.querySelector('.bask')", "the question")
            click(cdp, sid, "[data-bask=no]")
            self.until(cdp, sid, "!document.querySelector('.bask')", "closed")
            self.assertEqual(([self.field(r, "priority") for r in rows], self.bulk_sent(), [w for w, q in self.sent if w == "change"]), (was, [], []))

    # ---- never deletes; Help; both widths, light and dark ----
    def test_nothing_offers_to_delete_or_archive(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = cdp.js(self.ROWS, sid)[:2]
            self.pick(cdp, sid, rows)
            self.right_click(cdp, sid, self.rsel(rows[0]))
            self.menu_items(cdp, sid)
            words = cdp.js("document.querySelector('#sel-bar').textContent + ' ' + document.querySelector('.bmenu').textContent", sid).lower()
            for never in ("delete", "archive", "remove"):
                self.assertNotIn(never, words)

    def test_help_says_what_each_key_does(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            cdp.js("window.clarkPage.help.open('ref-keys')", sid)
            self.until(cdp, sid, "!!document.querySelector('#help')", "Help")
            text = cdp.js("document.querySelector('#help').textContent", sid)
            for words in ("change the owner (O), status (S), priority (P) or due date (T), or close it (C)", "one step with one Undo",
                          "open the menu of changes for it, or for the selection", "The Menu key and a right-click open it too"):
                self.assertIn(words, text)

    def test_the_bar_menu_and_question_fit_at_both_widths_in_light_and_dark(self):
        for width in (1400, 900):
            with self.subTest(width=width), chrome() as cdp:
                sid = self.load(cdp, width=width, kind="risk")
                rows = cdp.js(self.ROWS, sid)[:2]
                self.pick(cdp, sid, rows)
                for dark in (False, True):
                    cdp.js(f"document.documentElement.dataset.theme = '{'dark' if dark else 'light'}'", sid)
                    box = cdp.js("(() => { const r = [...document.querySelectorAll('#sel-bar, #sel-bar [data-bulk]')].map(e => e.getBoundingClientRect());"
                                 " return [Math.min(...r.map(x => x.left)), Math.max(...r.map(x => x.right)), innerWidth, document.documentElement.scrollWidth]; })()", sid)
                    self.assertGreaterEqual(box[0], 0)
                    self.assertLessEqual(box[1], box[2], f"the bar is inside the window at {width}, dark={dark}")
                    self.assertLessEqual(box[3], box[2], "no page scroll sideways")
                    colours = cdp.js("(() => { const b = document.querySelector('#sel-bar [data-bulk]'); const s = getComputedStyle(b); return [s.color, s.backgroundColor]; })()", sid)
                    self.assertNotEqual(colours[0], colours[1])
                    self.right_click(cdp, sid, self.rsel(rows[0]))
                    self.menu_items(cdp, sid)
                    m = cdp.js("(() => { const r = document.querySelector('.bmenu').getBoundingClientRect(); return [r.left, r.right, r.top, r.bottom, innerWidth, innerHeight]; })()", sid)
                    self.assertTrue(m[0] >= 0 and m[1] <= m[4] and m[2] >= 0 and m[3] <= m[5], m)
                    press(cdp, sid, "Escape")
                    self.until(cdp, sid, "!document.querySelector('.bmenu')", "closed")


if __name__ == "__main__":
    unittest.main()
