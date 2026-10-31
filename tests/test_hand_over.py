"""#199: Hand over, on the page: pick mode, All, the count, the person field, one step, one Undo, items left out and named, the question
above 25, and the keys that are off while it is on.

Run: python3 dev/run_tests.py test_hand_over
Part 1 runs the page's own rules (src/clark/page/src/logic/handOver.js, bundled by the pinned esbuild) in headless Chrome. Part 2 loads
the real page against the real server, whose change and undo routes are clark.changes over a demo database (fictional data), with real
DevTools mouse and key events, so every change is checked in the database. Desktop (1400) and 900 px, light and dark.
"""
import json
import unittest

from _paths import SRC

from test_bulk_bar import letter, special  # noqa: E402
from test_multi_select import CTRL, MOD, SHIFT, press, tap  # noqa: E402
from test_server import Running, chrome, wait  # noqa: E402
from test_work_board_page import Base  # noqa: E402
from test_work_filters import click  # noqa: E402
from test_work_items import bundled  # noqa: E402

LOGIC = SRC / "clark" / "page" / "src" / "logic" / "handOver.js"
SARA = "#work&p=ABC&f=mode:all;owner:Sara%20Khan"        # the Owner filter on one person, closed items shown too
PRIYA = "#work&p=ABC&f=mode:all;owner:Priya%20Nair"


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
        cls.cdp.js(bundled(LOGIC, "H"), cls.sid)

    @classmethod
    def tearDownClass(cls):
        cls.server.close()
        cls.stack.__exit__(None, None, None)

    def run_(self, expr):
        return json.loads(self.cdp.js(f"JSON.stringify((() => {{ {expr} }})())", self.sid))

    def test_only_open_items_are_offered(self):
        got = self.run_("const r = (id, status, kind) => ({id, status, kind: kind || 'action'});"
                        "return H.offered([r('a','Open'), r('b','Closed'), r('c','Cancelled'), r('d','Delayed'), r('e','Made','decision'), r('f','Pending','decision'), r('g','Withdrawn','decision')]).map(x => x.id);")
        self.assertEqual(got, ["a", "d", "f"])

    def test_the_words_and_what_stops_the_button(self):
        self.assertEqual(self.run_("return [H.countWords(3, 12), H.why(0, 'Zelda'), H.why(2, '  '), H.why(2, 'Zelda'), H.why(501, 'Zelda')];"),
                         ["3 of 12 selected", "Tick at least one item.", "Say who to hand over to.", "", "Tick at most 500 items at a time."])

    def test_what_is_sent(self):
        got = self.run_("const rows = [{id: 'ABC-006', kind: 'risk', table: 'raid'}, {id: 'ABC-A-001', kind: 'action', table: 'actions'}];"
                        "return [H.requestFor(rows, ['ABC-006', 'ABC-A-001'], '  Zelda   Quince '), H.requestFor(rows, ['ABC-A-001'], 'Z', {confirm: true})];")
        self.assertEqual(got[0], {"kind": "raid", "op": "handover", "ids": ["ABC-006", "ABC-A-001"], "to": "Zelda Quince", "place": "bulk"})
        self.assertEqual((got[1]["kind"], got[1]["confirm"]), ("actions", True))

    def test_the_question_is_asked_above_25(self):
        self.assertEqual(self.run_("return [H.needsConfirm(25), H.needsConfirm(26), H.confirmWords(26, ' Zelda  Quince')];"),
                         [False, True, "Hand over 26 items to Zelda Quince?"])

    def test_the_button_needs_an_owner_filter_that_picks_people(self):
        self.assertEqual(self.run_("return [H.ownerFilterOn({filters: {owner: ['A']}, not: {}}), H.ownerFilterOn({filters: {owner: []}, not: {}}),"
                                   " H.ownerFilterOn({filters: {owner: ['A']}, not: {owner: true}}), H.ownerFilterOn({filters: {}, not: {}}), H.ownerFilterOn(null)];"),
                         [True, False, False, False, False])

    def test_the_words_after_an_undo(self):
        self.assertEqual(self.run_("return [H.backWords(1), H.backWords(4)];"),
                         ["Undone: 1 item is back with its owner.", "Undone: 4 items are back with their owner."])


class Page(Base):
    """The real page, in Edit unless it says View."""

    TICKS = "[...document.querySelectorAll('#work-list tr.picked')].map(r => r.dataset.id)"
    ROWS = "[...document.querySelectorAll('#work-list tr[data-id]')].map(r => r.dataset.id)"

    def load(self, cdp, hash_=SARA, width=1400, edit=True):
        sid = self.visit(cdp, width=width, hash_=hash_, edit=edit)
        self.until(cdp, sid, "document.querySelectorAll('#work-list tr[data-id]').length >= 2", "the rows")
        return sid

    def start(self, cdp, sid):
        click(cdp, sid, "#hand-over")
        self.until(cdp, sid, "!!document.querySelector('#hand-bar')", "pick mode")

    def sent_hand(self):
        return [r for w, r in self.sent if w == "change" and r.get("op") == "handover"]

    def toast(self, cdp, sid):
        self.until(cdp, sid, "!!document.querySelector('.toast .toast-text')", "the toast")
        return cdp.js("document.querySelector('.toast .toast-text').textContent", sid)

    def name(self, cdp, sid, text):
        tap(cdp, sid, "#hand-to")
        cdp.js(f"document.execCommand('insertText', false, {json.dumps(text)})", sid)

    def owner(self, ref):
        r = self.row(ref)
        return r["made_by"] if "made_by" in r else r["owner"]

    def count(self, cdp, sid):
        return cdp.js("document.querySelector('#hand-count').textContent", sid)

    def rtap(self, cdp, sid, ref, mods=0):
        tap(cdp, sid, f"#work-list tr[data-id='{ref}'] .c-item .t", mods)

    # ---- the way in ----
    def test_the_button_is_in_edit_with_the_owner_filter_on_and_nowhere_else(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            self.assertTrue(cdp.js("!!document.querySelector('#hand-over')", sid))
            self.assertEqual(cdp.js("document.querySelector('#hand-over').textContent", sid), "Hand over")
        with chrome() as cdp:
            sid = self.load(cdp, "#work&p=ABC&f=mode:all")
            self.assertFalse(cdp.js("!!document.querySelector('#hand-over')", sid), "no owner filter")
        with chrome() as cdp:
            sid = self.load(cdp, SARA, edit=False)
            self.assertFalse(cdp.js("!!document.querySelector('#hand-over')", sid), "not in View")

    # ---- pick mode ----
    def test_pick_mode_ticks_open_items_only_and_counts_them(self):
        with chrome() as cdp:
            sid = self.load(cdp, PRIYA)
            self.start(cdp, sid)
            shown = cdp.js(self.ROWS, sid)
            open_ = [r for r in shown if self.row(r)["status"] not in ("Closed", "Cancelled", "Made", "Withdrawn")]
            self.assertTrue(len(open_) < len(shown), "the demo has closed items for this person")
            self.assertEqual(cdp.js("[...document.querySelectorAll('#work-list input.rtick')].map(i => i.dataset.tick)", sid), open_, "a tick box on each open item only")
            self.assertEqual(self.count(cdp, sid), f"0 of {len(open_)} selected")
            self.rtap(cdp, sid, open_[0])
            self.assertEqual((self.count(cdp, sid), cdp.js(self.TICKS, sid)), (f"1 of {len(open_)} selected", [open_[0]]))
            self.rtap(cdp, sid, open_[0])
            self.assertEqual(cdp.js(self.TICKS, sid), [], "a click toggles the row")
            closed = next(r for r in shown if r not in open_)
            self.rtap(cdp, sid, closed)
            self.assertEqual(cdp.js(self.TICKS, sid), [], "a closed item is never offered")
            click(cdp, sid, "#hand-all")
            self.assertEqual((cdp.js(self.TICKS, sid), self.count(cdp, sid)), (open_, f"{len(open_)} of {len(open_)} selected"))
            click(cdp, sid, "#hand-none")
            self.assertEqual(cdp.js(self.TICKS, sid), [])
            self.assertFalse(cdp.js("!!document.querySelector('#hand-none')", sid), "None is offered only with something ticked")

    def test_a_click_only_ticks_and_the_row_keys_are_off(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            rows = cdp.js(self.ROWS, sid)
            self.start(cdp, sid)
            self.rtap(cdp, sid, rows[0])
            self.assertFalse(cdp.js("!!document.querySelector('[data-peek]')", sid), "a click does not open the item")
            self.assertEqual(cdp.js("document.querySelectorAll('#work-list [data-cell]').length", sid), 0, "no cell opens a picker")
            tap(cdp, sid, f"#work-list tr[data-id='{rows[1]}'] .c-item .t", count=2)
            self.assertFalse(cdp.js("!!document.querySelector('[data-peek]')", sid), "nor does a double click")
            cdp.js(f"document.querySelector(\"tr[data-id='{rows[0]}']\").focus()", sid)
            before = cdp.js(self.TICKS, sid)
            press(cdp, sid, "ArrowDown", SHIFT)
            press(cdp, sid, "a", CTRL)
            press(cdp, sid, "Enter")
            for k in "ospct":
                letter(cdp, sid, k)
            self.assertEqual(cdp.js(self.TICKS, sid), before, "Shift with an arrow, Ctrl+A and the letters tick nothing")
            self.assertFalse(cdp.js("!!document.querySelector('[data-peek], .cpop, .bmenu, .bask')", sid), "and open nothing")
            special(cdp, sid, "F10", "F10", 121, SHIFT)
            self.assertFalse(cdp.js("!!document.querySelector('.bmenu')", sid), "the row menu is off")
            press(cdp, sid, " ")
            self.assertEqual(cdp.js(self.TICKS, sid), [r for r in before if r != rows[0]] if rows[0] in before else before + [rows[0]], "Space ticks")
            self.assertEqual(cdp.js("document.querySelectorAll('#sel-bar').length", sid), 0, "the usual selection bar is not shown")

    def test_the_button_says_why_it_waits(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            self.start(cdp, sid)
            self.assertEqual(cdp.js("document.querySelector('#hand-why').textContent", sid), "Tick at least one item.")
            self.assertEqual(cdp.js("document.querySelector('#hand-go').getAttribute('aria-disabled')", sid), "true")
            self.rtap(cdp, sid, cdp.js(self.ROWS, sid)[0])
            self.assertEqual(cdp.js("document.querySelector('#hand-why').textContent", sid), "Say who to hand over to.")
            click(cdp, sid, "#hand-go")
            self.assertEqual(self.sent_hand(), [], "nothing is sent while it waits")
            self.name(cdp, sid, "Zelda Quince")
            self.assertFalse(cdp.js("!!document.querySelector('#hand-why')", sid))
            self.assertIsNone(cdp.js("document.querySelector('#hand-go').getAttribute('aria-disabled')", sid))

    def test_the_person_box_suggests_the_names_on_the_project(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            self.start(cdp, sid)
            names = cdp.js("[...document.querySelectorAll('#hand-people option')].map(o => o.value)", sid)
            self.assertIn("Priya Nair", names)
            self.assertIn("Sara Khan", names)
            self.assertNotIn("TBC", names)
            self.assertEqual(cdp.js("document.querySelector('#hand-to').getAttribute('list')", sid), "hand-people")

    # ---- the hand over ----
    def test_hand_over_changes_every_owner_in_one_step_and_one_undo(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            shown = cdp.js(self.ROWS, sid)
            self.assertEqual(len(shown), 4, "Sara Khan has an action pair, a risk and a decision open")
            was = {r: self.owner(r) for r in shown}
            self.start(cdp, sid)
            click(cdp, sid, "#hand-all")
            self.name(cdp, sid, "Zelda Quince")
            steps = self.steps()
            click(cdp, sid, "#hand-go")
            self.assertIn("Changed 4 items.", self.toast(cdp, sid))
            self.assertEqual([(r["kind"] if False else r["op"], sorted(r["ids"]), r["to"]) for r in self.sent_hand()], [("handover", sorted(shown), "Zelda Quince")])
            self.assertEqual(self.steps(), steps + 1, "one step for actions, a risk and a decision")
            self.assertEqual({r: self.owner(r) for r in shown}, {r: "Zelda Quince" for r in shown})
            self.until(cdp, sid, "!document.querySelector('#hand-bar')", "pick mode ends")
            click(cdp, sid, ".toast [data-undo]")
            self.until(cdp, sid, "document.querySelector('.toast .toast-text') && document.querySelector('.toast .toast-text').textContent.startsWith('Undone')", "the undo")
            self.assertEqual(cdp.js("document.querySelector('.toast .toast-text').textContent", sid), "Undone: 4 items are back with their owner.")
            self.assertEqual({r: self.owner(r) for r in shown}, was, "one Undo restores every owner")
            self.assertEqual(len([1 for w, _ in self.sent if w == "undo"]), 1)

    def test_only_what_is_ticked_is_handed_over(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            shown = cdp.js(self.ROWS, sid)
            self.start(cdp, sid)
            self.rtap(cdp, sid, shown[0])
            self.rtap(cdp, sid, shown[2])
            self.name(cdp, sid, "Zelda Quince")
            press(cdp, sid, "Enter")                                  # Enter in the box does it too
            self.assertIn("Changed 2 items.", self.toast(cdp, sid))
            self.assertEqual({r: self.owner(r) for r in shown}, {r: ("Zelda Quince" if r in (shown[0], shown[2]) else "Sara Khan") for r in shown})

    def test_items_that_cannot_take_it_are_left_out_and_named(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            shown = cdp.js(self.ROWS, sid)
            self.start(cdp, sid)
            click(cdp, sid, "#hand-all")
            self.name(cdp, sid, "Zelda Quince")
            with self.store.step("dashboard", "Demo User") as st:      # archived while the page still shows it
                st.archive("actions", shown[0])
            click(cdp, sid, "#hand-go")
            text = self.toast(cdp, sid)
            self.assertIn("Changed 3 items.", text)
            self.assertIn(f"Left out {shown[0]}: It is archived. Restore it first.", text)
            self.assertEqual(self.owner(shown[0]), "Sara Khan")

    def test_cancel_and_esc_leave_pick_mode_and_change_nothing(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            shown = cdp.js(self.ROWS, sid)
            for how in ("cancel", "esc"):
                self.start(cdp, sid)
                click(cdp, sid, "#hand-all")
                if how == "cancel":
                    click(cdp, sid, "#hand-cancel")
                else:
                    cdp.js(f"document.querySelector(\"tr[data-id='{shown[0]}']\").focus()", sid)
                    press(cdp, sid, "Escape")
                self.until(cdp, sid, "!document.querySelector('#hand-bar')", how)
                self.assertEqual(cdp.js("document.querySelectorAll('#work-list input.rtick').length", sid), 0)
                self.assertTrue(cdp.js("!!document.querySelector('#hand-over')", sid), "the button is back")
                self.assertEqual(cdp.js("document.activeElement && document.activeElement.id", sid), "hand-over") if how == "cancel" else None
            self.assertEqual(self.sent_hand(), [])
            self.assertEqual({self.owner(r) for r in shown}, {"Sara Khan"})
            self.rtap(cdp, sid, shown[0])
            self.assertEqual(cdp.js("document.querySelectorAll('#sel-bar, tr.picked').length", sid), 1, "the usual selection works again")

    def test_a_filter_that_hides_a_ticked_item_unticks_it(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            shown = cdp.js(self.ROWS, sid)
            self.start(cdp, sid)
            click(cdp, sid, "#hand-all")
            click(cdp, sid, "[data-type=action]")
            self.until(cdp, sid, "document.querySelectorAll('#work-list tr[data-id]').length < 4", "the filter")
            now = cdp.js(self.ROWS, sid)
            self.assertEqual((cdp.js(self.TICKS, sid), self.count(cdp, sid)), (now, f"{len(now)} of {len(now)} selected"))
            self.assertIn("left the selection", cdp.js("document.querySelector('#hand-note').textContent", sid))

    # ---- the question above 25 ----
    def test_the_question_at_25_and_26(self):
        with self.store.step("dashboard", "Demo User") as st:
            for n in range(22):                                        # 26 open actions and more for Sara Khan, with her four
                st.create("actions", {"project": "ABC", "description": f"Extra task {n + 1}", "owner": "Sara Khan", "raised": "2026-10-01", "source": "demo"})
        with chrome() as cdp:
            sid = self.load(cdp)
            shown = cdp.js(self.ROWS, sid)
            self.assertEqual(len(shown), 26)
            self.start(cdp, sid)
            click(cdp, sid, "#hand-all")
            self.name(cdp, sid, "Zelda Quince")
            self.assertEqual(self.count(cdp, sid), "26 of 26 selected")
            self.rtap(cdp, sid, shown[0])                              # untick one: 25
            click(cdp, sid, "#hand-go")
            self.assertIn("Changed 25 items.", self.toast(cdp, sid))
            self.assertFalse(cdp.js("!!document.querySelector('.bask')", sid), "25 asks nothing")
            self.assertEqual(len(self.sent_hand()[-1]["ids"]), 25)
            click(cdp, sid, ".toast [data-undo]")
            self.until(cdp, sid, "document.querySelector('.toast .toast-text').textContent.startsWith('Undone')", "the undo")
            self.start(cdp, sid)
            click(cdp, sid, "#hand-all")
            self.name(cdp, sid, "Zelda Quince")
            sent = len(self.sent_hand())
            click(cdp, sid, "#hand-go")
            self.until(cdp, sid, "!!document.querySelector('.bask')", "the question")
            self.assertEqual(cdp.js("document.querySelector('.bask-q').textContent", sid), "Hand over 26 items to Zelda Quince?")
            self.assertEqual(len(self.sent_hand()), sent, "nothing is sent before the answer")
            press(cdp, sid, "Escape")
            self.until(cdp, sid, "!document.querySelector('.bask')", "Esc says no")
            self.assertTrue(cdp.js("!!document.querySelector('#hand-bar')", sid), "Esc on the question keeps pick mode")
            self.assertEqual(len(self.sent_hand()), sent)
            click(cdp, sid, "#hand-go")
            self.until(cdp, sid, "!!document.querySelector('.bask')", "the question again")
            click(cdp, sid, "[data-bask=yes]")
            self.assertTrue(wait(lambda: len(self.sent_hand()) == sent + 1), "sent after the answer")
            last = self.sent_hand()[-1]
            self.assertEqual((len(last["ids"]), last.get("confirm")), (26, True))
            self.assertTrue(wait(lambda: self.owner(shown[0]) == "Zelda Quince"), "saved once the answer was sent")

    def test_nothing_offers_to_delete_or_archive(self):
        with chrome() as cdp:
            sid = self.load(cdp)
            self.start(cdp, sid)
            words = cdp.js("[...document.querySelectorAll('#hand-bar button, #hand-bar a')].map(b => b.textContent.toLowerCase()).join(' ')", sid)
            for bad in ("delete", "archive", "remove"):
                self.assertNotIn(bad, words)

    # ---- both widths, light and dark ----
    def test_the_bar_and_the_ticks_fit_at_both_widths_in_light_and_dark(self):
        for width in (1400, 900):
            with self.subTest(width=width), chrome() as cdp:
                sid = self.load(cdp, width=width)
                self.start(cdp, sid)
                self.rtap(cdp, sid, cdp.js(self.ROWS, sid)[0])
                for dark in (False, True):
                    cdp.js(f"document.documentElement.dataset.theme = '{'dark' if dark else 'light'}'", sid)
                    box = cdp.js("(() => { const r = [...document.querySelectorAll('#hand-bar, #hand-bar button, #hand-bar input, #work-list input.rtick')].map(e => e.getBoundingClientRect());"
                                 " return [Math.min(...r.map(x => x.left)), Math.max(...r.map(x => x.right)), innerWidth, document.documentElement.scrollWidth]; })()", sid)
                    self.assertGreaterEqual(box[0], 0)
                    self.assertLessEqual(box[1], box[2], f"inside the window at {width}, dark={dark}")
                    self.assertLessEqual(box[3], box[2], "no page scroll sideways")
                    colours = cdp.js("(() => { const b = document.querySelector('#hand-to'); const s = getComputedStyle(b); return [s.color, s.backgroundColor]; })()", sid)
                    self.assertNotEqual(colours[0], colours[1], "the box can be read")
                    pri = cdp.js("(() => { const s = getComputedStyle(document.querySelector('#hand-go')); return [s.color, s.backgroundColor]; })()", sid)
                    self.assertNotEqual(pri[0], pri[1])
                    self.assertTrue(cdp.js("document.querySelector('tr.picked') !== null", sid))


if __name__ == "__main__":
    unittest.main()
