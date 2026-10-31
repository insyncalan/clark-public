"""#195: selecting several work items on the table and the board: click, Cmd or Ctrl+click, Shift ranges in the order drawn,
Cmd or Ctrl with Shift, double click to open; Shift+Up and Shift+Down, Space, Cmd or Ctrl+A; the group tick boxes; Select all N
matching; the rules that end or narrow a selection; what a screen reader is told; both widths, light and dark, reduced motion.

Run: python3 dev/run_tests.py test_multi_select
Part 1 runs the pure rules (src/clark/page/src/logic/selection.js, bundled by the pinned esbuild) in headless Chrome. Part 2 loads
the real page against the real server over a demo database, with real DevTools mouse and key events. The selection lives in
memory only: these tests also check that nothing is sent to the server and nothing is kept in the browser.
"""
import json
import sys
import unittest

from _paths import SRC

from test_server import CHROME, Running, chrome, wait  # noqa: E402
from test_sizes import DATA, published_page  # noqa: E402
from test_page import navigate  # noqa: E402
from test_work_board_page import Base, FIXED  # noqa: E402
from test_work_filters import click, where  # noqa: E402
from test_work_items import bundled  # noqa: E402

LOGIC = SRC / "clark" / "page" / "src" / "logic" / "selection.js"
ALT, CTRL, META, SHIFT = 1, 2, 4, 8
MOD = META if sys.platform == "darwin" else CTRL       # Cmd on a Mac (where Ctrl and a click is the right-click menu), Ctrl elsewhere
KEYS = {"Enter": (13, "\r", "Enter"), " ": (32, " ", "Space"), "Escape": (27, "", "Escape"), "ArrowDown": (40, "", "ArrowDown"),
        "ArrowUp": (38, "", "ArrowUp"), "a": (65, "a", "KeyA"), "Tab": (9, "", "Tab")}


def press(cdp, sid, name, mods=0):
    vk, text, code = KEYS[name]
    common = {"key": name, "code": code, "windowsVirtualKeyCode": vk, "modifiers": mods}
    typed = {"text": text} if text and not mods & (CTRL | META) else {}
    cdp.call("Input.dispatchKeyEvent", {"type": "keyDown", **common, **typed}, sid)
    cdp.call("Input.dispatchKeyEvent", {"type": "keyUp", **common}, sid)


def tap(cdp, sid, selector, mods=0, count=1):
    """A real mouse click (with Shift, Ctrl or Cmd held when `mods` says so); `count` 2 is a double click."""
    x, y = where(cdp, sid, selector)
    m = lambda kind, n, **kw: cdp.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "modifiers": mods, "clickCount": n, **kw}, sid)
    m("mouseMoved", 0)
    for n in range(1, count + 1):
        m("mousePressed", n, button="left", buttons=1)
        m("mouseReleased", n, button="left", buttons=0)


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
        cls.cdp.js(bundled(LOGIC, "SEL"), cls.sid)

    @classmethod
    def tearDownClass(cls):
        cls.server.close()
        cls.stack.__exit__(None, None, None)

    def js(self, expr):
        return self.cdp.js(f"JSON.stringify((() => {{ const E = SEL.EMPTY; {expr} }})())", self.sid)

    def run_(self, expr):
        return json.loads(self.js(expr))

    ORDER = "const O = ['C', 'A', 'E', 'B', 'D'];"           # the drawn order is not the order of the ids

    def test_a_plain_click_picks_only_that_one(self):
        got = self.run_(self.ORDER + "let s = SEL.click(E, 'A', {}, O); s = SEL.click(s, 'B', {}, O); return s;")
        self.assertEqual(got, {"ids": ["B"], "anchor": "B", "cursor": "B", "all": False})

    def test_cmd_or_ctrl_click_adds_and_removes_one(self):
        got = self.run_(self.ORDER + "let s = SEL.click(E, 'A', {}, O); s = SEL.click(s, 'B', {add: true}, O); const two = s.ids;"
                        " s = SEL.click(s, 'A', {add: true}, O); return [two, s.ids];")
        self.assertEqual(got, [["A", "B"], ["B"]], "a second Cmd or Ctrl click on one takes it out; it never replaces the rest")

    def test_shift_click_is_the_range_in_the_drawn_order(self):
        got = self.run_(self.ORDER + "let s = SEL.click(E, 'A', {}, O); s = SEL.click(s, 'D', {range: true}, O); const down = s.ids;"
                        " s = SEL.click(s, 'C', {range: true}, O); return [down, s.ids, s.anchor];")
        self.assertEqual(got[0], ["A", "E", "B", "D"], "from A to D as drawn, not A, B, C, D")
        self.assertEqual(got[1], ["C", "A"], "the anchor stays: a second Shift click is a new range from it")
        self.assertEqual(got[2], "A")

    def test_cmd_or_ctrl_with_shift_adds_the_range(self):
        got = self.run_(self.ORDER + "let s = SEL.click(E, 'C', {}, O); s = SEL.click(s, 'B', {add: true}, O);"
                        " s = SEL.click(s, 'D', {add: true, range: true}, O); return s.ids;")
        self.assertEqual(got, ["C", "B", "D"], "the range B to D is added to C")

    def test_shift_with_no_anchor_picks_that_one(self):
        self.assertEqual(self.run_(self.ORDER + "return SEL.click(E, 'E', {range: true}, O).ids;"), ["E"])

    def test_shift_up_and_down_extend_from_the_cursor(self):
        got = self.run_(self.ORDER + "let s = SEL.click(E, 'A', {}, O); s = SEL.extend(s, 1, O); const a = [s.ids, s.cursor];"
                        " s = SEL.extend(s, 1, O); const b = [s.ids, s.cursor]; s = SEL.extend(s, -1, O); s = SEL.extend(s, -1, O); s = SEL.extend(s, -1, O);"
                        " const c = [s.ids, s.cursor]; s = SEL.extend(s, -1, O); return [a, b, c, [s.ids, s.cursor]];")
        self.assertEqual(got, [[["A", "E"], "E"], [["A", "E", "B"], "B"], [["C", "A"], "C"], [["C", "A"], "C"]],
                         "down twice, then up past the anchor; at the top it stays")

    def test_space_toggles_and_select_all_takes_every_drawn_row(self):
        got = self.run_(self.ORDER + "let s = SEL.toggle(E, 'B'); s = SEL.toggle(s, 'D'); const a = s.ids; s = SEL.toggle(s, 'B');"
                        " return [a, s.ids, SEL.selectAll(s, O).ids];")
        self.assertEqual(got, [["B", "D"], ["D"], ["C", "A", "E", "B", "D"]])

    def test_a_group_tick_is_checked_unchecked_or_part_checked(self):
        got = self.run_("const g = ['A', 'B', 'C']; const st = (ids) => SEL.groupState({...E, ids}, g);"
                        " return [st([]), st(['A']), st(['A', 'B', 'C', 'X']), SEL.groupState(E, [])];")
        self.assertEqual(got, ["unchecked", "mixed", "checked", "unchecked"])

    def test_a_group_tick_picks_the_whole_group_or_clears_it(self):
        got = self.run_("const g = ['A', 'B']; let s = {...E, ids: ['X', 'A']}; s = SEL.toggleGroup(s, g); const a = s.ids;"
                        " s = SEL.toggleGroup(s, g); return [a, s.ids];")
        self.assertEqual(got, [["X", "A", "B"], ["X"]], "part-checked picks the rest; checked clears only that group")

    def test_select_all_matching_is_offered_for_two_or_more_and_fewer_than_match(self):
        got = self.run_("const m = ['A', 'B', 'C']; const o = (ids) => SEL.offersAllMatching({...E, ids}, m);"
                        " return [o(['A']), o(['A', 'B']), o(['A', 'B', 'C'])];")
        self.assertEqual(got, [False, True, False])

    def test_all_matching_counts_every_match_and_follows_the_filters(self):
        got = self.run_("let s = SEL.selectMatching({...E, ids: ['A', 'B']}, ['A', 'B', 'C', 'H']);"
                        " const a = [s.ids, s.all];"
                        " let r = SEL.sync(s, ['A', 'B'], ['A', 'B', 'C', 'H']); const b = r.sel.ids;"      # C and H are in a collapsed group
                        " r = SEL.sync(r.sel, ['B', 'Q'], ['B', 'Q']); const c = [r.sel.ids, r.left];"     # the filters changed
                        " r = SEL.sync(r.sel, [], []); return [a, b, c, [r.sel.ids, r.sel.all, r.left]];")
        self.assertEqual(got[0], [["A", "B", "C", "H"], True], "every match, drawn or not")
        self.assertEqual(got[1], ["A", "B", "C", "H"], "a collapsed group's matches stay picked")
        self.assertEqual(got[2], [["B", "Q"], 0], "it keeps working as the filters change")
        self.assertEqual(got[3], [[], False, 2], "and ends when nothing matches")

    def test_rows_no_longer_drawn_leave_and_are_counted(self):
        got = self.run_("let s = {...E, ids: ['A', 'B', 'C'], anchor: 'B'}; const r = SEL.sync(s, ['A', 'X'], ['A', 'B', 'C', 'X']);"
                        " const same = SEL.sync(r.sel, ['A'], ['A']); return [r.sel.ids, r.sel.anchor, r.left, same.left, same.sel === r.sel];")
        self.assertEqual(got, [["A"], None, 2, 0, True])

    def test_all_matching_keeps_the_same_selection_when_nothing_changed(self):
        got = self.run_("let s = SEL.selectMatching({...E, ids: ['A', 'B']}, ['A', 'B', 'C']); const r = SEL.sync(s, ['A'], ['A', 'B', 'C']);"
                        " return [r.sel === s, r.left];")
        self.assertEqual(got, [True, 0], "a redraw with the same matches hands back the same selection, so nothing redraws again")

    def test_the_words(self):
        got = self.run_("return [SEL.countWords(0), SEL.countWords(1), SEL.countWords(3), SEL.leftWords(1), SEL.leftWords(3), SEL.matchingWords(12)];")
        self.assertEqual(got, ["Nothing selected", "1 selected", "3 selected", "1 left the selection", "3 left the selection", "Select all 12 matching"])


class Page(Base):
    """The real page in Edit (and in View where it says so), table first."""

    ROWS = "[...document.querySelectorAll('#work-list tr[data-id]')].map(r => r.dataset.id)"
    PICKED = "clarkPage.selected()"

    def load(self, cdp, width=1400, edit=True, mode="all"):
        sid = self.visit(cdp, width=width, edit=edit)
        if mode != "open":
            click(cdp, sid, f"[data-show={mode}]")
            self.until(cdp, sid, f"document.querySelector('[data-show={mode}]').getAttribute('aria-pressed') === 'true'", "the switch")
        self.until(cdp, sid, "document.querySelectorAll('#work-list tr[data-id]').length > 5", "the rows")
        return sid

    def picked(self, cdp, sid):
        return cdp.js(self.PICKED, sid)

    def rsel(self, rid):
        return f"#work-list tr[data-id='{rid}'] .c-item .t"

    def test_click_cmd_and_ctrl_click_shift_ranges_in_the_drawn_order(self):
        for width in (1400, 900):
            with self.subTest(width=width), chrome() as cdp:
                sid = self.load(cdp, width)
                rows = cdp.js(self.ROWS, sid)
                self.assertNotEqual(rows, sorted(rows), "the test needs a drawn order that is not the order of the ids")
                tap(cdp, sid, self.rsel(rows[1]))
                self.assertEqual(self.picked(cdp, sid), [rows[1]], "a click selects only that row")
                self.assertNotIn("item=", cdp.js("location.hash", sid), "a single click does not open the peek")
                tap(cdp, sid, self.rsel(rows[3]), MOD)
                tap(cdp, sid, self.rsel(rows[5]), MOD)
                self.assertEqual(self.picked(cdp, sid), [rows[1], rows[3], rows[5]], "Cmd or Ctrl adds one each")
                tap(cdp, sid, self.rsel(rows[3]), MOD)
                self.assertEqual(self.picked(cdp, sid), [rows[1], rows[5]], "a second Cmd click takes it out")
                tap(cdp, sid, self.rsel(rows[2]))
                tap(cdp, sid, self.rsel(rows[6]), SHIFT)
                self.assertEqual(self.picked(cdp, sid), rows[2:7], "Shift selects the range as drawn")
                self.assertEqual(cdp.js("String(getSelection())", sid), "", "a Shift click selects no text")
                tap(cdp, sid, self.rsel(rows[0]), MOD | SHIFT)
                self.assertEqual(sorted(self.picked(cdp, sid)), sorted(rows[0:7]), "Ctrl with Shift adds the range 0 to 2 to the range 2 to 6")
                tap(cdp, sid, self.rsel(rows[4]))
                self.assertEqual(self.picked(cdp, sid), [rows[4]], "a plain click starts again")
                self.assertEqual(self.sent, [], "selecting sends nothing")

    def test_a_double_click_opens_the_peek_and_links_buttons_and_boxes_keep_their_job(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = cdp.js(self.ROWS, sid)
            tap(cdp, sid, self.rsel(rows[2]), count=2)
            self.until(cdp, sid, f"location.hash.includes('item={rows[2]}')", "a double click opens the peek")
            self.assertEqual(self.picked(cdp, sid), [rows[2]])
            tap(cdp, sid, self.rsel(rows[4]))
            self.until(cdp, sid, f"location.hash.includes('item={rows[4]}')", "with the peek open on one, a click moves it")
            cdp.js("clarkPage.closePeek()", sid)
            self.until(cdp, sid, "!location.hash.includes('item=')", "closed")
            before = self.picked(cdp, sid)
            tap(cdp, sid, f"#work-list tr[data-id='{rows[0]}'] [data-cell$=':owner']")
            self.until(cdp, sid, "!!document.querySelector('.pop, .ddmenu, [role=dialog]')", "the owner picker opened")
            self.assertEqual(self.picked(cdp, sid), before, "a cell's button keeps its job and leaves the selection")
            press(cdp, sid, "Escape")

    def test_keys_shift_arrows_space_and_select_all(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = cdp.js(self.ROWS, sid)
            cdp.js(f"document.querySelector(\"tr[data-id='{rows[1]}']\").focus()", sid)
            press(cdp, sid, " ")
            self.assertEqual(self.picked(cdp, sid), [rows[1]], "Space adds the cursor row")
            press(cdp, sid, "ArrowDown", SHIFT)
            press(cdp, sid, "ArrowDown", SHIFT)
            self.assertEqual(self.picked(cdp, sid), rows[1:4], "Shift+Down extends from the cursor")
            self.assertEqual(cdp.js("document.activeElement.dataset.id", sid), rows[3], "the cursor moved with it")
            press(cdp, sid, "ArrowUp", SHIFT)
            self.assertEqual(self.picked(cdp, sid), rows[1:3], "Shift+Up takes one back")
            press(cdp, sid, " ")
            self.assertEqual(self.picked(cdp, sid), [rows[1]], "Space takes the cursor row out")
            for mods in (CTRL, META):
                cdp.js("clarkPage.closePeek()", sid)
                press(cdp, sid, "Escape")
                press(cdp, sid, "a", mods)
                self.assertEqual(self.picked(cdp, sid), rows, "Cmd or Ctrl+A selects every row shown")
            self.assertEqual(cdp.js("String(getSelection())", sid), "", "and no page text")
            press(cdp, sid, "Escape")
            self.assertEqual(self.picked(cdp, sid), [], "Esc clears it")

    def test_select_all_keys_in_a_box_are_the_box_s_own(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            click(cdp, sid, "[data-fb]")
            self.until(cdp, sid, "!!document.querySelector('.fbox')", "a filter's box")
            cdp.js("(document.querySelector('.fbox input') || document.querySelector('.fbox button')).focus()", sid)
            press(cdp, sid, "a", CTRL)
            self.assertEqual(self.picked(cdp, sid), [], "Ctrl+A in a filter box is the browser's")

    def test_group_ticks_checked_part_checked_and_off_when_collapsed(self):
        for width in (1400, 900):
            with self.subTest(width=width), chrome() as cdp:
                sid = self.load(cdp, width)
                groups = cdp.js("[...document.querySelectorAll('tbody[data-group]')].map(t => [t.dataset.group, [...t.querySelectorAll('tr[data-id]')].map(r => r.dataset.id)])", sid)
                g, ids = next((k, v) for k, v in groups if len(v) >= 2)
                box = f"tbody[data-group='{g}'] .gtick"
                state = f"(b => b.checked ? 'checked' : b.indeterminate ? 'mixed' : 'unchecked')(document.querySelector(\"{box}\"))"
                self.assertEqual(cdp.js(state, sid), "unchecked")
                self.assertTrue(cdp.js(f"document.querySelector(\"{box}\").getAttribute('aria-label').startsWith('Select ')", sid))
                tap(cdp, sid, self.rsel(ids[0]))
                self.assertEqual(cdp.js(state, sid), "mixed", "one of the group's rows: part-checked")
                tap(cdp, sid, box)
                self.assertEqual(sorted(self.picked(cdp, sid)), sorted(ids), "the tick picks the whole group")
                self.assertEqual(cdp.js(state, sid), "checked")
                tap(cdp, sid, box)
                self.assertEqual(self.picked(cdp, sid), [], "and clears it")
                tap(cdp, sid, f"tbody[data-group='{g}'] .grp-b")
                self.until(cdp, sid, f"document.querySelector(\"{box}\").disabled", "a collapsed group's tick is off")
                cdp.js(f"document.querySelector(\"{box}\").click()", sid)
                self.assertEqual(self.picked(cdp, sid), [], "and does nothing")

    def test_collapsing_a_group_drops_its_rows_and_says_how_many(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            groups = cdp.js("[...document.querySelectorAll('tbody[data-group]')].map(t => [t.dataset.group, [...t.querySelectorAll('tr[data-id]')].map(r => r.dataset.id)])", sid)
            (g, ids), (_, other) = [x for x in groups if len(x[1]) >= 2][:2]
            tap(cdp, sid, f"tbody[data-group='{g}'] .gtick")
            tap(cdp, sid, self.rsel(other[0]), MOD)
            tap(cdp, sid, f"tbody[data-group='{g}'] .grp-b")
            self.until(cdp, sid, f"document.querySelector('#sel-note') && document.querySelector('#sel-note').textContent === '{len(ids)} left the selection'", "the note")
            self.assertEqual(self.picked(cdp, sid), [other[0]])
            self.assertEqual(cdp.js("document.querySelector('#sel-live').textContent.trim()", sid), f"{len(ids)} left the selection. 1 selected")

    def test_select_all_matching_takes_collapsed_groups_and_follows_the_filters(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            groups = cdp.js("[...document.querySelectorAll('tbody[data-group]')].map(t => [t.dataset.group, [...t.querySelectorAll('tr[data-id]')].map(r => r.dataset.id)])", sid)
            every = [i for _, v in groups for i in v]
            shut, hidden = groups[-1]
            tap(cdp, sid, f"tbody[data-group='{shut}'] .grp-b")
            self.until(cdp, sid, f"!document.querySelector(\"tbody[data-group='{shut}'] tr[data-id]\")", "a group collapsed")
            shown = cdp.js(self.ROWS, sid)
            tap(cdp, sid, self.rsel(shown[0]))
            self.assertFalse(cdp.js("!!document.querySelector('#sel-all')", sid), "not offered for one")
            tap(cdp, sid, self.rsel(shown[1]), SHIFT)
            self.assertEqual(cdp.js("document.querySelector('#sel-all').textContent", sid), f"Select all {len(every)} matching")
            tap(cdp, sid, "#sel-all")
            self.assertEqual(sorted(self.picked(cdp, sid)), sorted(every), "every match, the collapsed group's too")
            self.assertTrue(set(hidden) <= set(self.picked(cdp, sid)))
            self.assertFalse(cdp.js("!!document.querySelector('#sel-all')", sid), "no offer once all are picked")
            self.assertEqual(cdp.js("document.querySelector('#sel-count').textContent", sid), f"{len(every)} selected")
            tap(cdp, sid, "[data-type=action]")
            self.until(cdp, sid, "document.querySelector('[data-type=action]').getAttribute('aria-pressed') === 'true'", "only actions")
            actions = [r["id"] for r in self.data["actions"]]
            self.until(cdp, sid, f"JSON.stringify(clarkPage.selected().slice().sort()) === {json.dumps(json.dumps(sorted(actions)).replace(' ', ''))}",
                       "the selection followed the filters to the actions")
            tap(cdp, sid, "[data-type=all]")
            self.until(cdp, sid, f"clarkPage.selected().length === {len(every)}", "and back")

    def test_filtering_drops_rows_no_longer_shown(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = cdp.js(self.ROWS, sid)
            kinds = cdp.js("Object.fromEntries([...document.querySelectorAll('#work-list tr[data-id]')].map(r => [r.dataset.id, r.dataset.kind]))", sid)
            act = [r for r in rows if kinds[r] == "action"][:1]
            dec = [r for r in rows if kinds[r] == "decision"][:2]
            tap(cdp, sid, self.rsel(act[0]))
            for d in dec:
                tap(cdp, sid, self.rsel(d), MOD)
            tap(cdp, sid, "[data-type=decision]")
            self.until(cdp, sid, f"clarkPage.selected().length === {len(dec)}", "the action left")
            self.assertEqual(sorted(self.picked(cdp, sid)), sorted(dec))
            self.assertEqual(cdp.js("document.querySelector('#sel-note').textContent", sid), "1 left the selection")

    def test_two_or_more_close_the_peek(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = cdp.js(self.ROWS, sid)
            tap(cdp, sid, self.rsel(rows[0]), count=2)
            self.until(cdp, sid, "!!clarkPage.peek()", "the peek opened")
            tap(cdp, sid, self.rsel(rows[1]), MOD)
            self.until(cdp, sid, "clarkPage.peek() === null", "selecting a second closes the peek")
            self.assertEqual(self.picked(cdp, sid), rows[:2])

    def test_the_ways_a_selection_ends(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = cdp.js(self.ROWS, sid)
            pick2 = lambda: (tap(cdp, sid, self.rsel(rows[0])), tap(cdp, sid, self.rsel(rows[2]), MOD))
            pick2()
            tap(cdp, sid, "#sel-clear")
            self.assertEqual(self.picked(cdp, sid), [], "the X on the bar")
            self.assertFalse(cdp.js("!!document.querySelector('#sel-bar')", sid))
            pick2()
            press(cdp, sid, "Escape")
            self.assertEqual(self.picked(cdp, sid), [], "Esc")
            pick2()
            tap(cdp, sid, ".top")
            self.assertEqual(self.picked(cdp, sid), [], "a click outside")
            pick2()
            tap(cdp, sid, "#work h1")
            self.assertEqual(len(self.picked(cdp, sid)), 2, "a click on the page itself, inside Work items, keeps it")
            cdp.js("clarkPage.show('milestones')", sid)
            self.until(cdp, sid, "location.hash.startsWith('#milestones')")
            cdp.js("history.back()", sid)
            self.until(cdp, sid, "!!document.querySelector('#work-list tr[data-id]')", "back on Work items")
            self.assertEqual(self.picked(cdp, sid), [], "a change of tab")
            self.assertEqual(cdp.js("Object.keys(localStorage).filter(k => /sel/i.test(k) || /sel/i.test(localStorage.getItem(k)))", sid), [],
                             "nothing about the selection is kept")
            self.assertEqual(self.sent, [])

    def test_esc_leaves_an_open_menu_its_own(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = cdp.js(self.ROWS, sid)
            tap(cdp, sid, self.rsel(rows[0]))
            tap(cdp, sid, self.rsel(rows[1]), MOD)
            click(cdp, sid, "#group-by")
            self.until(cdp, sid, "!!document.querySelector('.ddmenu')", "the menu")
            press(cdp, sid, "Escape")
            self.until(cdp, sid, "!document.querySelector('.ddmenu')", "Esc closed the menu")
            self.assertEqual(len(self.picked(cdp, sid)), 2, "and left the selection")

    def test_shown_not_only_by_colour_and_told_to_a_screen_reader(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = cdp.js(self.ROWS, sid)
            self.assertEqual(cdp.js("[...document.querySelectorAll('#work table.items')].map(t => [t.getAttribute('role'), t.getAttribute('aria-multiselectable')])", sid), [["grid", "true"]])
            self.assertTrue(cdp.js("[...document.querySelectorAll('#work-list tr[data-id]')].every(r => r.getAttribute('aria-selected') === 'false')", sid))
            tap(cdp, sid, self.rsel(rows[0]))
            tap(cdp, sid, self.rsel(rows[1]), MOD)
            on = f"document.querySelector(\"tr[data-id='{rows[0]}']\")"
            self.assertEqual(cdp.js(f"{on}.getAttribute('aria-selected')", sid), "true")
            self.assertTrue(cdp.js(f"!!{on}.querySelector('.c-item .tick + .t')", sid), "a tick mark before the title")
            self.assertTrue(cdp.js(f"getComputedStyle({on}).boxShadow.includes('inset')", sid), "a border")
            self.assertTrue(cdp.js(f"{on}.querySelector('.tick').getAttribute('aria-hidden') === 'true'", sid), "the tick is not read twice")
            live = "document.querySelector('#sel-live')"
            self.assertEqual(cdp.js(f"[{live}.getAttribute('role'), {live}.getAttribute('aria-live'), {live}.textContent.trim()]", sid), ["status", "polite", "2 selected"])
            self.assertEqual(cdp.js("document.querySelector('#sel-clear').getAttribute('aria-label')", sid), "Clear the selection")

    def test_the_same_count_twice_is_still_told(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = cdp.js(self.ROWS, sid)
            live = "document.querySelector('#sel-live').textContent"
            tap(cdp, sid, self.rsel(rows[0]))
            first = cdp.js(live, sid)
            tap(cdp, sid, self.rsel(rows[1]))
            second = cdp.js(live, sid)
            self.assertEqual((first.strip(), second.strip()), ("1 selected", "1 selected"))
            self.assertNotEqual(first, second, "the polite region's text changes, so a screen reader reads it again")
            self.assertEqual(cdp.js(f"document.querySelector(\"tr[data-id='{rows[0]}']\").getAttribute('aria-label')", sid), f"Select or open {rows[0]}")

    def test_focus_order_the_bar_comes_before_the_table_and_the_table_is_still_one_stop(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = cdp.js(self.ROWS, sid)
            tap(cdp, sid, self.rsel(rows[0]))
            tap(cdp, sid, self.rsel(rows[3]), SHIFT)
            order = cdp.js("[...document.querySelectorAll('#work-list a, #work-list button, #work-list input, #work-list [tabindex]')]"
                           ".filter(e => e.tabIndex >= 0 && !e.disabled && !e.closest('tr.grp')).map(e => e.id || (e.matches('tr') ? 'row' : e.className))", sid)
            self.assertEqual(order[:2], ["sel-all", "sel-clear"], order)
            self.assertLess(order.index("sel-clear"), order.index("row"), "the bar comes before the table")
            self.assertEqual(order.count("row"), 1, "the table is one tab stop")

    def test_reduced_motion_has_no_movement(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]}, sid)
            self.assertEqual(cdp.js("getComputedStyle(document.querySelector('#work-list tr[data-id]')).transitionDuration", sid), "0s")
            cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "no-preference"}]}, sid)
            self.assertNotEqual(cdp.js("getComputedStyle(document.querySelector('#work-list tr[data-id]')).transitionDuration", sid), "0s")

    def test_the_bar_fits_at_both_widths_in_light_and_dark(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = cdp.js(self.ROWS, sid)
            tap(cdp, sid, self.rsel(rows[0]))
            tap(cdp, sid, self.rsel(rows[2]), SHIFT)
            for theme in ("light", "dark"):
                cdp.js(f"document.documentElement.dataset.theme = '{theme}'", sid)
                for width in (1400, 900):
                    cdp.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False}, sid)
                    got = cdp.js("(() => { const b = document.querySelector('#sel-bar').getBoundingClientRect(), x = document.querySelector('#sel-clear').getBoundingClientRect();"
                                 " return [b.left >= 0, b.right <= innerWidth, x.right <= b.right, document.documentElement.scrollWidth <= innerWidth]; })()", sid)
                    self.assertEqual(got, [True] * 4, f"{theme} {width}")
                    # the tick and the bar's words can be read: the words are the heading colour on the tinted bar
                    fg, bg = cdp.js("(() => { const s = getComputedStyle(document.querySelector('#sel-count')), b = getComputedStyle(document.querySelector('#sel-bar')); return [s.color, b.backgroundColor]; })()", sid)
                    self.assertGreaterEqual(contrast(fg, bg), 4.5, f"{theme} {width}: {fg} on {bg}")

    def test_view_mode_selects_too(self):
        with chrome() as cdp:
            sid = self.load(cdp, edit=False)
            rows = cdp.js(self.ROWS, sid)
            tap(cdp, sid, self.rsel(rows[0]))
            tap(cdp, sid, self.rsel(rows[1]), MOD)
            self.assertEqual(self.picked(cdp, sid), rows[:2])


class PublishedFile(unittest.TestCase):
    """A published file is read only: nothing to do with several, so no selection; Shift with an arrow still moves the row."""

    def test_no_selection_and_shift_arrows_still_move(self):
        s = Running(data_for=DATA.get, page_html=published_page)
        self.addCleanup(s.close)
        with chrome() as cdp:
            sid = navigate(cdp, s.port, "#work&p=ABC")
            self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('#work tr[data-id]').length > 1", sid)), "the rows drew")
            cdp.call("Emulation.setFocusEmulationEnabled", {"enabled": True}, sid)
            rows = cdp.js("[...document.querySelectorAll('#work tr[data-id]')].map(r => r.dataset.id)", sid)
            self.assertEqual(cdp.js("[document.querySelector('#work table').getAttribute('aria-multiselectable'), !!document.querySelector('#sel-live, .gtick'),"
                                    " document.querySelector('#work tr[data-id]').getAttribute('aria-label')]", sid), [None, False, f"Open {rows[0]}"])
            cdp.js("document.querySelector('#work tr[data-id]').focus()", sid)
            press(cdp, sid, "ArrowDown", SHIFT)
            self.assertTrue(wait(lambda: cdp.js("document.activeElement.dataset.id", sid) == rows[1]), "Shift+Down moved to the next row")
            self.assertEqual(cdp.js("clarkPage.selected()", sid), [], "and selected nothing")


class OnTheBoard(Base):
    CARDS = "[...document.querySelectorAll('#work-board article.bcard[data-id]')].map(c => c.dataset.id)"

    def card(self, cid):
        return f"article[data-id='{cid}'] .bc-title"

    def test_cards_select_like_rows(self):
        for width in (1400, 900):
            with self.subTest(width=width), chrome() as cdp:
                sid = self.visit(cdp, width=width)
                self.board(cdp, sid, "status")
                cards = cdp.js(self.CARDS, sid)
                tap(cdp, sid, self.card(cards[0]))
                self.assertEqual(cdp.js("clarkPage.selected()", sid), [cards[0]])
                self.assertNotIn("item=", cdp.js("location.hash", sid), "a click selects; it does not open")
                tap(cdp, sid, self.card(cards[3]), SHIFT)
                self.assertEqual(cdp.js("clarkPage.selected()", sid), cards[0:4], "a range in reading order")
                tap(cdp, sid, self.card(cards[1]), MOD)
                self.assertEqual(cdp.js("clarkPage.selected()", sid), [cards[0], cards[2], cards[3]])
                self.assertTrue(cdp.js(f"document.querySelector(\"article[data-id='{cards[0]}']\").classList.contains('picked')", sid))
                self.assertTrue(cdp.js(f"!!document.querySelector(\"article[data-id='{cards[0]}'] .bc-title .tick\")", sid), "a tick before the title")
                self.assertIn(", selected", cdp.js(f"document.querySelector(\"article[data-id='{cards[0]}'] .bc-main\").getAttribute('aria-label')", sid))
                self.assertEqual(cdp.js("document.querySelector('#sel-count').textContent", sid), "3 selected")
                tap(cdp, sid, self.card(cards[2]), count=2)
                self.until(cdp, sid, f"location.hash.includes('item={cards[2]}')", "a double click opens the peek")
                self.assertEqual(self.sent, [], "no card moved")

    def test_card_keys_and_column_ticks(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            cards = cdp.js(self.CARDS, sid)
            cdp.js(f"document.querySelector(\"article[data-id='{cards[0]}'] .bc-main\").focus()", sid)
            press(cdp, sid, " ")
            self.assertEqual(cdp.js("clarkPage.selected()", sid), [cards[0]], "Space adds the card")
            self.assertNotIn("item=", cdp.js("location.hash", sid), "and does not open it")
            press(cdp, sid, "ArrowDown", SHIFT)
            self.assertEqual(cdp.js("clarkPage.selected()", sid), cards[0:2])
            press(cdp, sid, "a", CTRL)
            self.assertEqual(cdp.js("clarkPage.selected()", sid), cards, "every card shown")
            press(cdp, sid, "Escape")
            self.assertEqual(cdp.js("clarkPage.selected()", sid), [])
            press(cdp, sid, "Enter")
            self.until(cdp, sid, "location.hash.includes('item=')", "Enter still opens the card")
            cdp.js("clarkPage.closePeek()", sid)
            col = cdp.js("[...document.querySelectorAll('#work-board section.col')].find(c => c.querySelectorAll('.bcard').length >= 2).dataset.col", sid)
            ids = cdp.js(f"[...document.querySelectorAll(\"section.col[data-col='{col}'] .bcard\")].map(c => c.dataset.id)", sid)
            tap(cdp, sid, f"section.col[data-col='{col}'] .gtick")
            self.assertEqual(sorted(cdp.js("clarkPage.selected()", sid)), sorted(ids), "a column's tick picks its cards")
            tap(cdp, sid, f"section.col[data-col='{col}'] .col-b")
            self.until(cdp, sid, f"document.querySelector(\"section.col[data-col='{col}'] .gtick\").disabled", "off while collapsed")
            self.assertEqual(cdp.js("clarkPage.selected()", sid), [], "collapsing dropped them")
            self.assertEqual(cdp.js("document.querySelector('#sel-note').textContent", sid), f"{len(ids)} left the selection")

    def test_the_board_fits_with_the_ticks_in_light_and_dark(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            for theme in ("light", "dark"):
                cdp.js(f"document.documentElement.dataset.theme = '{theme}'", sid)
                for width in (1400, 900):
                    cdp.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False}, sid)
                    got = cdp.js("(() => [...document.querySelectorAll('#work-board .col-h')].every(h => { const t = h.querySelector('.gtick').getBoundingClientRect(), r = h.getBoundingClientRect();"
                                 " return t.width > 0 && t.left >= r.left && t.right <= r.right; }) && document.documentElement.scrollWidth <= innerWidth)()", sid)
                    self.assertTrue(got, f"{theme} {width}")


def _lum(rgb):
    import re
    nums = [float(x) for x in re.findall(r"[\d.]+", rgb)[:3]]
    r, g, b = nums if rgb.startswith("color(") else [x / 255 for x in nums]
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    x, y = sorted((_lum(a), _lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


if __name__ == "__main__":
    unittest.main()
