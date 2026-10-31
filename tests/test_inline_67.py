"""#67 (wiring, first part): the contents minimap on the report, the sticky bar, a click on a Work items row opening that item's
peek, and the history an inline edit leaves. Spec: docs/handoff/design-67-inline-editing.md (what is built here and what waits on
a guarded change or on #66).

Run: python3 dev/run_tests.py test_inline_67
Browser tests start headless Chrome through the harness against a real server whose change and undo are the real clark.changes
over a real store in a temporary folder (fictional data), at 1400 and 900 px.
"""
import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from _demo import USER, DemoStore
from _editor_checks import edit_elements
from clark import changes, history, publish
from test_page import navigate
from test_report_editor import EMPTY_BRANDING, IDS, Base, Pg
from test_server import chrome, wait

SIZES = (1400, 900)
TOP = "document.querySelector('.top').getBoundingClientRect()"


def size(cdp, p, width, height=600):
    cdp.call("Emulation.setFocusEmulationEnabled", {"enabled": True}, p.sid)      # headless Chrome fires focus events only with this
    cdp.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False}, p.sid)


class Minimap(Base):
    LISTED = "[...document.querySelectorAll('.toc li button')].map(b => b.dataset.id)"

    def listed(self, p):
        return p.js(self.LISTED)

    def test_it_lists_every_visible_section_and_no_hidden_one_and_follows_hide_and_add(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            self.assertEqual(self.listed(p), IDS, "View lists every section")
            p.edit()
            self.assertEqual(self.listed(p), IDS)
            p.menu("ABC-S-002", "hide")
            p.until("!!document.querySelector('[data-id=\"ABC-S-002\"].is-hidden')", "the section is hidden")
            self.assertEqual(self.listed(p), [i for i in IDS if i != "ABC-S-002"], "a hidden section is not listed, though Edit still draws it")
            self.assertTrue(p.js("!!document.querySelector('[data-id=\"ABC-S-002\"]')"))
            p.js("document.querySelector('[data-id=\"ABC-S-001\"] [data-add]').click()")
            p.until("document.querySelectorAll('.secs > .sec').length === 12", "a section was added")
            listed = self.listed(p)
            self.assertEqual(len(listed), 11)
            self.assertNotIn("ABC-S-002", listed)
            self.assertEqual(listed[1], p.ids()[1], "the new section is listed in its place")
            p.view()
            self.assertEqual(self.listed(p), listed, "View lists the same sections")
            p.edit()
            p.js("document.querySelector('[data-id=\"ABC-S-002\"] [data-options]').click()")
            p.until("!!document.querySelector('[data-id=\"ABC-S-002\"] .menu')", "the menu opened")
            p.js("document.querySelector('[data-id=\"ABC-S-002\"] [data-act=show]').click()")
            p.until("!document.querySelector('[data-id=\"ABC-S-002\"].is-hidden')", "shown again")
            self.assertIn("ABC-S-002", self.listed(p), "showing it lists it again")

    def test_a_click_scrolls_to_the_section_under_the_sticky_bar_and_leaves_the_address(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            for w in SIZES:
                size(cdp, p, w)
                p.js("window.scrollTo(0, 0)")
                before = p.js("[location.hash, history.length]")
                p.js("document.querySelector('.toc-lines').focus()")
                p.until("document.querySelector('.toc').classList.contains('open')", "the list opened on focus")
                for ref in ("ABC-S-008", "ABC-S-011", "ABC-S-004"):
                    p.js(f"document.querySelector('.toc li button[data-id=\"{ref}\"]').click()")
                    p.until(f"(function(){{var t=document.querySelector('[data-id=\"{ref}\"]').getBoundingClientRect().top;"
                            f"return t >= {TOP}.bottom - 1 && t < window.innerHeight;}})()", f"{ref} is in view at {w}")
                    p.js("document.querySelector('.toc-lines').focus()")
                self.assertEqual(p.js("[location.hash, history.length]"), before, "the address and history are left alone")

    def test_keys_open_and_close_it_and_a_hidden_list_cannot_be_tabbed_into(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            size(cdp, p, 1400)
            self.assertFalse(p.js("document.querySelector('.toc').classList.contains('open')"))
            p.js("document.querySelector('.toc-lines').focus()")
            p.until("document.querySelector('.toc').classList.contains('open')", "focus opens it")
            p.key("ArrowDown", code="ArrowDown", vk=40)
            p.until("document.activeElement.matches('.toc li button')", "Arrow moves into the list")
            p.key("Escape", code="Escape", vk=27)
            p.until("!document.querySelector('.toc').classList.contains('open')", "Esc closes it")
            self.assertTrue(p.js("document.activeElement.matches('.toc-lines')"), "focus is back on the button")
            p.key("Tab", code="Tab", vk=9)
            self.assertFalse(p.js("!!document.activeElement.closest('.toc-card')"), "Tab does not move into the closed list")
            self.assertFalse(p.js("document.querySelector('.toc').classList.contains('open')"), "and does not reopen it")

    def test_it_marks_the_current_section_as_the_page_scrolls(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            size(cdp, p, 1400)
            p.js("window.scrollTo(0, document.documentElement.scrollHeight)")
            p.until("document.querySelector('.toc-lines i.on') && document.querySelector('.toc-lines i.on').dataset.tl === 'ABC-S-011'",
                    "the last section is current at the bottom")
            p.js("window.scrollTo(0, 0)")
            p.until("document.querySelector('.toc-lines i.on').dataset.tl === 'ABC-S-001'", "the first is current at the top")

    def test_it_fits_at_1400_and_900_in_both_colour_schemes(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            for scheme in ("light", "dark"):
                p.js(f"document.documentElement.dataset.theme = '{scheme}'")      # the page follows data-theme, not the emulated media
                for w in SIZES:
                    size(cdp, p, w)
                    p.js("document.querySelector('.toc-lines').focus()")
                    p.until("document.querySelector('.toc').classList.contains('open') && getComputedStyle(document.querySelector('.toc-card')).opacity === '1'", "open")
                    box = p.js("(function(){var r=document.querySelector('.toc-card').getBoundingClientRect();"
                               "return [r.left >= 0, r.right <= window.innerWidth, r.top >= 0, r.bottom <= window.innerHeight,"
                               "document.documentElement.scrollWidth <= window.innerWidth];})()")
                    self.assertEqual(box, [True] * 5, f"{scheme} {w}")

    def test_the_current_section_mark_can_be_seen_against_the_page_in_both_colours(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            size(cdp, p, 1400)
            p.until("!!document.querySelector('.toc-lines i.on')", "a section is current")
            for scheme, floor in (("light", 3.0), ("dark", 3.0)):
                p.js(f"document.documentElement.dataset.theme = '{scheme}'")
                self.assertEqual(p.js("document.documentElement.dataset.theme"), scheme)
                time.sleep(0.4)                                            # the mark's colour eases over a short transition
                ratio = p.js("""(function(){
                    function rgb(c){ var m = c.match(/[\\d.]+/g).map(Number); return m.slice(0, 3); }
                    function lum(c){ var v = rgb(c).map(function(x){ x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }); return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; }
                    var mark = getComputedStyle(document.querySelector('.toc-lines i.on')).backgroundColor;
                    var page = getComputedStyle(document.body).backgroundColor;
                    var a = lum(mark), b = lum(page);
                    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
                })()""")
                self.assertGreaterEqual(ratio, floor, f"{scheme}: the current-section mark against the page is {ratio:.2f}:1")


class Sticky(Base):
    def test_the_top_bar_stays_in_view_after_scrolling_at_1400_and_900(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            for mode in ("view", "edit"):
                if mode == "edit":
                    p.edit()
                for w in SIZES:
                    size(cdp, p, w)
                    p.js("window.scrollTo(0, document.documentElement.scrollHeight)")
                    p.until("window.scrollY > 300", "the page scrolled")
                    got = p.js(f"(function(){{var r={TOP}, e=document.elementFromPoint(r.left + 40, r.top + r.height / 2);"
                               "return [r.top, r.height > 0, !!(e && e.closest('.top')), document.querySelectorAll('.top [data-mode]').length];})()")
                    self.assertEqual(got[:3], [0, True, True], f"{mode} {w}: the bar is at the top and on top")
                    p.js("window.scrollTo(0, 0)")


class View(Base):
    def test_view_has_the_minimap_and_nothing_to_edit_no_eye_and_no_picker(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            self.assertEqual(edit_elements(cdp, p.sid), [])
            self.assertEqual(p.js("document.querySelectorAll('.toc').length"), 1)
            self.assertEqual(p.js("document.querySelectorAll('[data-eye], [data-picker], [role=dialog]').length"), 0)
            size(cdp, p, 1400)
            p.js("document.querySelector('.toc-lines').focus()")
            p.until("document.querySelector('.toc').classList.contains('open')", "open")
            self.assertEqual(edit_elements(cdp, p.sid), [], "opening the minimap adds no field")


class Published(unittest.TestCase):
    def test_the_published_file_has_the_minimap_without_a_hidden_section_and_no_editing(self):
        demo = DemoStore()
        self.addCleanup(demo.close)
        store = demo.store
        change = changes.make_change(store.path, [], USER)
        for ref, edit in (("ABC-S-005", {"title": "Hidden secret plan", "hidden": 1}), ("ABC-S-006", {"title": "Shown plan"})):
            status, body = change({"project": "ABC", "kind": "report_sections", "op": "update", "id": ref, "changes": edit})
            self.assertEqual(status, 200, body)
        with store.step("dashboard", USER) as st:
            for ref in ("ABC-S-006", "ABC-S-007"):
                st.update("report_sections", ref, {"body": "<p>Some words</p>"})
        folder = tempfile.mkdtemp(prefix="clark-pub-")
        self.addCleanup(shutil.rmtree, folder, True)
        done = publish.publish(store, "ABC", folder, by_user=USER, now="2026-10-28", branding=EMPTY_BRANDING)
        text = Path(done["path"]).read_text(encoding="utf-8")
        self.assertNotIn("Hidden secret plan", text)
        with chrome() as cdp:
            tid = next(t["targetId"] for t in cdp.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
            sid = cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
            cdp.call("Page.navigate", {"url": Path(done["path"]).as_uri()}, sid)
            self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('.sec')", sid)), "the file drew its sections")
            self.assertEqual(cdp.js("[...document.querySelectorAll('.toc li button')].map(b => b.textContent)", sid), ["At a glance", "Use case summary", "Shown plan", "Next week"],
                             "the minimap lists what the file shows, and not the hidden section")
            self.assertEqual(cdp.js("[...document.querySelectorAll('.toc li button')].every(b => (function(e){ return !!e && e.classList.contains('sec') && e.dataset.id === b.dataset.id; })(document.getElementById('sec-' + b.dataset.id)))", sid), True,
                             "each entry's anchor is a section of the file")
            self.assertEqual(edit_elements(cdp, sid), [])
            cdp.call("Emulation.setFocusEmulationEnabled", {"enabled": True}, sid)
            cdp.call("Emulation.setDeviceMetricsOverride", {"width": 900, "height": 400, "deviceScaleFactor": 1, "mobile": False}, sid)
            cdp.js("document.querySelector('.toc-lines').focus()", sid)
            self.assertTrue(wait(lambda: cdp.js("document.querySelector('.toc').classList.contains('open')", sid)), "it opens in a file")
            cdp.js("document.querySelector('.toc li button:last-child, .toc li:last-child button').click()", sid)
            self.assertTrue(wait(lambda: cdp.js("window.scrollY > 0", sid)), "the file scrolled to the section")
            self.assertEqual(cdp.js("location.hash", sid), "", "no address change in a file")


class RowClick(Base):
    def setUp(self):
        super().setUp()
        self.a = self.demo.action(workstream="Build", owner="Sara Khan")
        self.b = self.demo.action(workstream="Build", owner="Sam Example")

    def work(self, cdp, w=1400):
        p = Pg.at(self, cdp, self.s.port, "#work&p=ABC&f=mode:all")
        size(cdp, p, w, 900)
        p.until("document.querySelectorAll('#work tbody tr').length >= 2", "the rows drew")
        return p

    def peek(self, p):
        return p.js("(window.clarkPage.peek() || {}).id || ''")

    def test_a_double_click_on_a_row_opens_its_peek_and_one_in_a_field_or_button_does_not(self):
        # #195: a single click selects the row; a double click opens the peek
        dbl = "(function(el){el.dispatchEvent(new MouseEvent('click',{bubbles:true,detail:1})); el.dispatchEvent(new MouseEvent('dblclick',{bubbles:true,detail:2}));})"
        with chrome() as cdp:
            for w in SIZES:
                p = self.work(cdp, w)
                p.js(f"document.querySelector('tr[data-id=\"{self.a}\"] .c-owner').click()")
                self.assertEqual(self.peek(p), "", "a single click selects, it does not open")
                p.js(f"{dbl}(document.querySelector('tr[data-id=\"{self.a}\"] .c-owner'))")
                p.until(f"window.clarkPage.peek() && window.clarkPage.peek().id === '{self.a}'", f"the row's peek opened at {w}")
                p.js("window.clarkPage.closePeek()")
                p.until("!window.clarkPage.peek()", "closed")
                p.js(f"(function(){{var td=document.querySelector('tr[data-id=\"{self.b}\"] .c-owner');"
                     "var i=document.createElement('input'); i.id='probe-in'; td.appendChild(i);"
                     "var b=document.createElement('button'); b.id='probe-btn'; td.appendChild(b);"
                     "var c=document.createElement('span'); c.id='probe-ce'; c.setAttribute('contenteditable','true'); td.appendChild(c);})()")
                for probe in ("probe-in", "probe-btn", "probe-ce"):
                    p.js(f"{dbl}(document.getElementById('{probe}'))")
                self.assertEqual(self.peek(p), "", "a double click inside a field or on a button opens nothing")

    def test_enter_on_a_focused_row_opens_it_and_a_selection_does_not(self):
        with chrome() as cdp:
            p = self.work(cdp)
            p.js(f"document.querySelector('tr[data-id=\"{self.b}\"]').focus()")
            p.key("Enter", code="Enter", vk=13)
            p.until(f"window.clarkPage.peek() && window.clarkPage.peek().id === '{self.b}'", "Enter opened it")
            p.js("window.clarkPage.closePeek()")
            p.until("!window.clarkPage.peek()", "closed")
            p.js(f"(function(){{var el=document.querySelector('tr[data-id=\"{self.a}\"] .t'); var r=document.createRange(); r.selectNodeContents(el);"
                 "var s=getSelection(); s.removeAllRanges(); s.addRange(r); el.click();})()")
            self.assertEqual(self.peek(p), "", "ending a text selection opens nothing")


    def test_a_focused_row_has_the_one_blue_ring_and_the_one_hover_colour(self):
        with chrome() as cdp:
            for scheme in ("light", "dark"):
                p = self.work(cdp)
                p.js(f"document.documentElement.dataset.theme = '{scheme}'")
                p.js(f"document.querySelector('tr[data-id=\"{self.a}\"]').focus()")
                p.key("ArrowDown", code="ArrowDown", vk=40)                     # a key press makes the focus ring show
                p.until(f"document.activeElement.dataset.id === '{self.b}'", "the arrow moved to the next row")
                got = p.js("(function(){var r=document.activeElement, c=getComputedStyle(r), root=getComputedStyle(document.documentElement);"
                           "return [c.outlineColor === (function(){var d=document.createElement('i'); d.style.color=root.getPropertyValue('--brand-blue'); document.body.appendChild(d); var v=getComputedStyle(d).color; d.remove(); return v;})(),"
                           "c.outlineStyle, getComputedStyle(r.querySelector('td')).backgroundColor === 'rgba(0, 0, 0, 0)'];})()")
                self.assertEqual(got, [True, "solid", True], f"{scheme}: the row's ring is --brand-blue and the hover paints the row, not its cells")


class EditHistory(unittest.TestCase):
    """Done-when 1: an inline edit made through /api/change is read back from change_log and item_events, newest first."""

    def setUp(self):
        self.demo = DemoStore()
        self.addCleanup(self.demo.close)
        self.a = self.demo.action(workstream="Build", owner="Sara Khan")
        self.change = changes.make_change(self.demo.store.path, [], USER)
        self.undo = changes.make_undo(self.demo.store.path, [], USER)

    def con(self):
        con = sqlite3.connect(str(self.demo.store.path))
        con.row_factory = sqlite3.Row
        self.addCleanup(con.close)
        return con

    def edit(self, **fields):
        status, body = self.change({"project": "ABC", "kind": "actions", "op": "update", "id": self.a, "changes": fields, "place": "cell"})
        self.assertEqual((status, body.get("message")), (200, None), body)
        return body

    def test_the_edits_are_in_the_items_history_newest_first(self):
        self.edit(owner="Sam Example")
        second = self.edit(owner="Alex Example")
        events = [e for e in history.history(self.con(), self.a) if e["field"] == "owner"]
        self.assertEqual([(e["before"], e["after"]) for e in events][:2], [("Sam Example", "Alex Example"), ("Sara Khan", "Sam Example")])   # the third is the action's creation
        self.assertEqual(events[0]["after"], "Alex Example", "newest first")
        self.assertEqual((events[0]["route"], events[0]["place"], events[0]["by_user"]), ("dashboard", "cell", USER))
        self.assertEqual(events[0]["step"], second["apply_id"])
        self.assertTrue(events[0]["in_force"])

    def test_an_undo_is_in_the_history_and_the_edit_it_reversed_is_no_longer_in_force(self):
        body = self.edit(owner="Sam Example")
        status, reply = self.undo({"project": "ABC", "apply_id": body["apply_id"]})
        self.assertEqual(status, 200, reply)
        events = [e for e in history.history(self.con(), self.a) if e["field"] == "owner"]
        self.assertTrue(events[0]["is_undo"], "the undo is the newest event")
        self.assertEqual(events[0]["after"], "Sara Khan")
        edit = next(e for e in events if e["after"] == "Sam Example" and not e["is_undo"])
        self.assertFalse(edit["in_force"])
        self.assertEqual(edit["undone_by"], events[0]["event_id"])

    def test_a_section_edit_never_appears_in_a_work_items_history(self):
        before = history.history(self.con(), self.a)
        status, body = self.change({"project": "ABC", "kind": "report_sections", "op": "update", "id": "ABC-S-002", "changes": {"hidden": 1}})
        self.assertEqual(status, 200, body)
        self.assertEqual(history.history(self.con(), self.a), before)


if __name__ == "__main__":
    unittest.main()
