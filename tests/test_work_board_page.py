"""#68 and #81, the Work items board on the page: layout switch, Group by, cards, swimlanes, moving a card (drag and Move to...)
against the real change route with Undo, refusals, Due's date picker, collapse, full screen. Spec: docs/handoff/design-68-81-board.md.

Run: python3 dev/run_tests.py test_work_board_page
The real page runs in headless Chrome (required: these fail, never skip, without it) against the real server, whose change and
undo routes are changes.make_change and make_undo over a demo database, so each move is checked in the database. Mouse and keys
are real DevTools input events. Desktop (1400) and 900 px only. The pure rules are tested in test_board.
"""
import json
import re
import sqlite3
import unittest
from unittest import mock

from _demo import USER
from _paths import ROOT, SRC

from clark import changes, page, server as sv  # noqa: E402
from test_board import make_data  # noqa: E402
from test_server import Running, chrome, wait  # noqa: E402
from test_work_filters import click, dblclick, hover, key, need_chrome, where  # noqa: E402
from test_work_items import page_target  # noqa: E402

PAGE_SRC = SRC / "clark" / "page" / "src"
TODAY = "2026-10-29"
FIXED = ("(() => { const R = Date, F = new R(2026, 9, 29, 12, 0, 0).getTime();"
         " function D(...a) { return this instanceof D ? (a.length ? new R(...a) : new R(F)) : new R(F).toString(); }"
         " D.prototype = R.prototype; D.now = () => F; D.UTC = R.UTC; D.parse = R.parse; window.Date = D; })();")


class Base(unittest.TestCase):
    def setUp(self):
        need_chrome()
        self.demo, self.data = make_data()
        self.store = self.demo.store
        with self.store.step("dashboard", USER) as st:               # one card the client sees
            st.update("actions", self.id_of("Send the invitations"), {"client_visible": 1})
            st.update("actions", self.id_of("Book the training room"), {"client_visible": 0})     # on by default (#24)
        self.sent = []
        change, undo = changes.make_change(self.store.path, [], USER), changes.make_undo(self.store.path, [], USER)

        def seam(real, which):
            def call(req):
                self.sent.append((which, req))
                return real(req)
            return call
        self.s = Running(data_for=self.store.data_for, page_html=lambda: page.page_html(__import__("tempfile").mkdtemp()),
                         change=seam(change, "change"), undo=seam(undo, "undo"))
        self.addCleanup(self.s.close)
        self.addCleanup(self.demo.close)
        quiet = mock.patch.object(sv.LOG, "disabled", True)
        quiet.start()
        self.addCleanup(quiet.stop)

    # ---- the data ----
    def id_of(self, text):
        for k, f in (("actions", "description"), ("raid", "description"), ("decisions", "decision")):
            for r in self.data[k]:
                if text in r[f]:
                    return r["id"]
        raise KeyError(text)

    def query(self, sql, *args):
        """A read on a connection of its own: the store's one is busy serving the page, and would show an old snapshot."""
        con = sqlite3.connect(str(self.store.path))
        con.row_factory = sqlite3.Row
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()

    def row(self, ref):
        for t in ("actions", "raid", "decisions"):
            r = self.query(f"SELECT * FROM {t} WHERE id = ?", ref)
            if r:
                return dict(r[0])
        raise KeyError(ref)

    def steps(self):
        return self.query("SELECT COALESCE(max(apply_id), 0) FROM applies")[0][0]

    # ---- the browser ----
    def visit(self, cdp, width=1400, height=900, hash_="#work&p=ABC", edit=True, preset=None, wait_for="#work-list"):
        sid = page_target(cdp)
        cdp.call("Page.enable", {}, sid)
        pre = FIXED
        if preset:
            pre += f"try {{ if (!localStorage.getItem('clark.work.v1')) localStorage.setItem('clark.work.v1', JSON.stringify({{ABC: {json.dumps(preset)}}})); }} catch (e) {{}}"
        cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": pre}, sid)
        cdp.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False}, sid)
        cdp.call("Emulation.setFocusEmulationEnabled", {"enabled": True}, sid)
        cdp.call("Page.navigate", {"url": "about:blank"}, sid)
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{self.s.port}/{hash_}"}, sid)
        self.until(cdp, sid, f"!!document.querySelector({json.dumps(wait_for)})", "the work items page")
        if edit:
            cdp.js("document.querySelector('[data-mode=edit]').click()", sid)
            self.until(cdp, sid, "document.querySelector('[data-mode=edit]').getAttribute('aria-pressed') === 'true'", "Edit")
        return sid

    def until(self, cdp, sid, expr, what="", secs=30):
        self.assertTrue(wait(lambda: bool(cdp.js(f"!!({expr})", sid)), secs), f"timed out waiting for {what or expr}")

    def reload(self, cdp, sid):
        cdp.call("Page.reload", {}, sid)
        self.until(cdp, sid, "document.documentElement.dataset.ready === '1' && !!document.querySelector('#work-list')", "the page after a reload")

    def board(self, cdp, sid, group="status", lane=None, mode="all"):
        """Remember the layout (as the person would by clicking), then reload so it is drawn."""
        cdp.js(f"localStorage.setItem('clark.work.v1', JSON.stringify({{ABC: {{view: 'board', group: {json.dumps(group)}, lane: {json.dumps(lane)}, collapsed: []}}}}))", sid)
        self.reload(cdp, sid)
        cdp.js("document.querySelector('[data-mode=edit]').click()", sid)
        if mode != "open":
            click(cdp, sid, f"[data-show={mode}]")
        self.until(cdp, sid, "!!document.querySelector('#work-board .bcard')", "the board")

    def drag(self, cdp, sid, card, cell, steps=8):
        """Pick a card up with the mouse and drop it in a column cell, like a person: the board scrolls itself when the pointer
        is held at its edge, so the pointer waits there until the cell shows."""
        x0, y0 = where(cdp, sid, f"article[data-id='{card}'] .bc-main")
        mouse = lambda kind, x, y, **kw: cdp.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, **kw}, sid)
        mouse("mouseMoved", x0, y0)
        mouse("mousePressed", x0, y0, button="left", buttons=1, clickCount=1)
        for i in (1, 2, 3):
            mouse("mouseMoved", x0 + 6 * i, y0 + 6 * i, buttons=1)
        sel = json.dumps(cell)
        find = ("(() => { const t = document.querySelector(" + sel + ").getBoundingClientRect(); const full = document.body.classList.contains('board-full');"
                " const s = (full ? document.querySelector('main') : document.querySelector('.boardbox')).getBoundingClientRect();"
                " const l = Math.max(t.left, s.left, 0), r = Math.min(t.right, s.right, innerWidth), tp = Math.max(t.top, s.top + 100, 0), b = Math.min(t.bottom, s.bottom - 60, innerHeight);"
                " return [l, r, tp, b, t.left + t.width / 2 < s.left + 80 ? 'left' : t.left + t.width / 2 > s.right - 80 ? 'right' : '', s.left, s.right]; })()")
        at = (x0, y0)
        for _ in range(200):
            l, r, tp, b, side, sl, sr = cdp.js(find, sid)
            if r - l >= 20 and b - tp >= 20 and not side:
                at = ((l + r) / 2, (tp + b) / 2)
                break
            at = (sr - 10, y0) if side == "right" else (sl + 10, y0) if side == "left" else (x0, min(max(tp, 0) + 10, 700))
            mouse("mouseMoved", at[0], at[1], buttons=1)
            __import__("time").sleep(0.03)
        else:
            self.fail(f"could not bring {cell} into view")
        tx, ty = at
        px, py = x0 + 18, y0 + 18
        for i in range(1, steps + 1):
            mouse("mouseMoved", px + (tx - px) * i / steps, py + (ty - py) * i / steps, buttons=1)
        mouse("mouseReleased", tx, ty, button="left", buttons=0, clickCount=1)

    @staticmethod
    def cell(col, lane=""):
        return f"section.col[data-col='{col}'][data-lane='{lane}']"

    def toast(self, cdp, sid):
        return cdp.js("(() => { const t = document.querySelector('.toast'); return t ? {text: t.querySelector('.toast-text').textContent, kind: t.dataset.kind, undo: !!t.querySelector('[data-undo]')} : null; })()", sid)

    def wait_toast(self, cdp, sid, kind=None):
        self.until(cdp, sid, f"!!document.querySelector('.toast{'[data-kind=' + kind + ']' if kind else ''}')", "a toast")
        return self.toast(cdp, sid)

    def cards_in(self, cdp, sid, col, lane=""):
        return cdp.js(f"[...document.querySelectorAll(\"{self.cell(col, lane)} .bcard\")].map(c => c.dataset.id)", sid)


class Switch(Base):
    def test_layout_icon_switch_has_tooltips_and_is_remembered(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.assertEqual(cdp.js("[...document.querySelectorAll('[aria-label=Layout] button')].map(b => [b.dataset.layout, b.getAttribute('aria-label'), b.dataset.tip, b.getAttribute('aria-pressed')])", sid),
                             [["table", "Table", "Table", "true"], ["board", "Board", "Board", "false"]])
            self.assertTrue(cdp.js("!!document.querySelector('table.items') && !document.querySelector('#work-board')", sid), "a table to start")
            hover(cdp, sid, "[data-layout=board]")
            self.assertEqual(cdp.js("getComputedStyle(document.querySelector('[data-layout=board]'), '::after').content", sid), '"Board"', "a tooltip")
            click(cdp, sid, "[data-layout=board]")
            self.until(cdp, sid, "!!document.querySelector('#work-board')", "the board")
            self.assertEqual(cdp.js("document.querySelector('#work-live').textContent", sid), "Showing the board, grouped by Workstream.")
            self.reload(cdp, sid)
            self.assertTrue(cdp.js("!!document.querySelector('#work-board')", sid), "the board is remembered")
            self.assertEqual(cdp.js("document.querySelector('[data-layout=board]').getAttribute('aria-pressed')", sid), "true")
            click(cdp, sid, "[data-layout=table]")
            self.reload(cdp, sid)
            self.assertTrue(cdp.js("!!document.querySelector('table.items') && !document.querySelector('#work-board')", sid), "the table is remembered")

    def test_a_switch_adds_no_history_entry_and_nothing_in_the_address(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            before = cdp.js("[history.length, location.hash]", sid)
            click(cdp, sid, "[data-layout=board]")
            self.until(cdp, sid, "!!document.querySelector('#work-board')")
            self.assertEqual(cdp.js("[history.length, location.hash]", sid), before)

    def test_a_browser_that_refuses_storage_still_switches(self):
        with chrome() as cdp:
            sid = page_target(cdp)
            cdp.call("Page.enable", {}, sid)
            cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": FIXED + "Storage.prototype.setItem = function () { throw new Error('blocked'); };"}, sid)
            cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{self.s.port}/#work&p=ABC"}, sid)
            self.until(cdp, sid, "!!document.querySelector('[data-layout=board]')")
            click(cdp, sid, "[data-layout=board]")
            self.until(cdp, sid, "!!document.querySelector('#work-board')", "the board, though nothing could be kept")

    def test_the_published_page_has_no_board(self):
        view = (ROOT / "src" / "clark" / "page" / "page-view.html").read_text(encoding="utf-8")
        for word in ("clark:open-peek", "work-board", "/api/change"):
            self.assertNotIn(word, view)
        self.assertNotIn("data-layout", view)


class GroupBy(Base):
    def test_group_by_menu_and_the_table_groups(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.assertEqual(cdp.js("document.querySelector('#group-by').textContent", sid), "Group by: Workstream")
            self.assertEqual(cdp.js("document.querySelector('#group-by').getAttribute('aria-haspopup')", sid), "menu")
            click(cdp, sid, "#group-by")
            names = cdp.js("[...document.querySelectorAll('.ddmenu [role=menuitem]')].map(b => b.textContent)", sid)
            self.assertEqual(names, ["Workstream", "Status", "Due", "Owner", "Priority", "Milestone", "Type", "Nothing"])
            click(cdp, sid, ".ddmenu [data-kind=status]")
            self.until(cdp, sid, "document.querySelector('#group-by').textContent === 'Group by: Status'")
            groups = cdp.js("[...document.querySelectorAll('tbody[data-group]')].map(t => [t.dataset.group, t.querySelectorAll('tr[data-id]').length, +t.querySelector('.gc').textContent])", sid)
            self.assertTrue(groups and all(n == c for _, n, c in groups), groups)
            self.assertEqual(sum(n for _, n, _ in groups), cdp.js("document.querySelectorAll('#work tr[data-id]').length", sid))
            click(cdp, sid, "#group-by")
            click(cdp, sid, ".ddmenu [data-kind=nothing]")
            self.until(cdp, sid, "!document.querySelector('tr.grp')", "a flat table")
            self.reload(cdp, sid)
            self.assertEqual(cdp.js("document.querySelector('#group-by').textContent", sid), "Group by: Nothing", "remembered")

    def test_a_table_group_opens_and_shuts_and_is_remembered(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            n = cdp.js("document.querySelectorAll('#work tr[data-id]').length", sid)
            click(cdp, sid, "tbody[data-group] .grp-b")
            shut = cdp.js("document.querySelector('tbody[data-group] .grp-b').getAttribute('aria-expanded')", sid)
            self.assertEqual(shut, "false")
            self.assertLess(cdp.js("document.querySelectorAll('#work tr[data-id]').length", sid), n)
            self.reload(cdp, sid)
            self.assertEqual(cdp.js("document.querySelector('tbody[data-group] .grp-b').getAttribute('aria-expanded')", sid), "false")

    def test_the_board_columns_follow_group_by_and_nothing_is_not_offered(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            cols = cdp.js("[...document.querySelectorAll('#work-board section.col')].map(c => c.dataset.col)", sid)
            self.assertEqual(cols, ["Open", "Delayed", "Pending", "Closed", "Made", "Cancelled", "Withdrawn"])
            click(cdp, sid, "#group-by")
            names = cdp.js("[...document.querySelectorAll('.ddmenu [role=menuitem]')].map(b => b.textContent)", sid)
            self.assertNotIn("Nothing", names)
            click(cdp, sid, ".ddmenu [data-kind=owner]")
            self.until(cdp, sid, "document.querySelector('#group-by').textContent === 'Group by: Owner'")
            labels = cdp.js("[...document.querySelectorAll('#work-board .col-b .cl')].map(c => c.textContent)", sid)
            self.assertEqual(labels[-1], "No owner")
            self.assertIn("Priya Nair", labels)
            # every card is in exactly one column, and the counts add up to the list
            total = cdp.js("document.querySelectorAll('#work-board .bcard').length", sid)
            self.assertEqual(total, cdp.js("[...document.querySelectorAll('#work-board section.col')].reduce((a, c) => a + +c.dataset.count, 0)", sid))
            self.assertRegex(cdp.js("document.querySelector('#work-count').textContent", sid), rf"^{total} (?:open )?items?$")

    def test_a_column_nothing_can_be_dropped_on_says_so(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "due")
            said = cdp.js("(() => { const c = document.querySelector(\"section.col[data-col='overdue']\"); const p = c.querySelector('.nd'); return [c.classList.contains('nodrop'), p ? p.textContent : null]; })()", sid)
            self.assertEqual(said, [True, "Can't drop here. Use This week, Next week or Later."], "the Overdue column says what to do instead")
            self.assertFalse(cdp.js("!!document.querySelector(\"section.col[data-col='later'] .nd\")", sid), "a column that takes cards does not say it")

    def test_the_toast_area_is_a_polite_live_region_and_a_refusal_lands_in_it(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            self.assertEqual(cdp.js("(() => { const r = document.querySelector('.toasts'); return r ? [r.getAttribute('role'), r.getAttribute('aria-live')] : null; })()", sid), ["status", "polite"],
                             "the region is there before any message, so a screen reader hears the first one")
            self.drag(cdp, sid, self.id_of("Supplier slips"), self.cell("Delayed"))
            self.wait_toast(cdp, sid, "note")
            self.assertTrue(cdp.js("!!document.querySelector('.toasts[aria-live=polite] > .toast[data-kind=note]')", sid), "the refusal is inside the live region")
            self.assertEqual(cdp.js("document.querySelectorAll('.toasts').length", sid), 1)

    def test_leaving_the_board_mid_drag_leaves_no_listener_behind(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            cdp.js("(() => { window.__open = 0; const a = document.addEventListener, r = document.removeEventListener, key = (t, c) => t === 'pointermove' && c === true;"
                   " document.addEventListener = function (t, f, c) { if (key(t, c)) window.__open++; return a.apply(this, arguments); };"
                   " document.removeEventListener = function (t, f, c) { if (key(t, c)) window.__open--; return r.apply(this, arguments); }; })()", sid)
            x, y = where(cdp, sid, "article.bcard .bc-main")
            cdp.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1}, sid)
            self.assertEqual(cdp.js("window.__open", sid), 1, "a press listens")
            cdp.js("document.querySelector('[data-layout=table]').click()", sid)
            self.until(cdp, sid, "!document.querySelector('#work-board')", "the table")
            self.assertEqual(cdp.js("window.__open", sid), 0)
            cdp.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "buttons": 0, "clickCount": 1}, sid)

    def test_workstream_is_a_filter_and_the_filters_narrow_the_board(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            all_ = cdp.js("document.querySelectorAll('#work-board .bcard').length", sid)
            click(cdp, sid, "[data-type=action]")
            self.until(cdp, sid, "[...document.querySelectorAll('#work-board .bcard')].every(c => c.dataset.kind === 'action')")
            acts = cdp.js("document.querySelectorAll('#work-board .bcard').length", sid)
            self.assertLess(acts, all_)
            self.assertEqual(cdp.js("[...document.querySelectorAll('#work-board section.col')].map(c => c.dataset.col)", sid), ["Open", "Delayed", "Closed", "Cancelled"], "the status columns follow the type")
            click(cdp, sid, "[data-fb=workstream]")
            self.assertTrue(cdp.js("!!document.querySelector('#fbox-workstream')", sid), "Workstream is a filter")
            click(cdp, sid, "#fbox-workstream label:nth-of-type(1) input")
            self.until(cdp, sid, f"document.querySelectorAll('#work-board .bcard').length < {acts}")
            n = cdp.js("document.querySelectorAll('#work-board .bcard').length", sid)
            self.assertRegex(cdp.js("document.querySelector('#work-count').textContent", sid), rf"^{n} (?:open )?items?$")


class Cards(Base):
    def test_a_card_shows_its_parts_and_a_client_eye_only_when_shown_to_the_client(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            a = self.id_of("Send the invitations")
            card = cdp.js(f"(() => {{ const c = document.querySelector(\"article[data-id='{a}']\"); return {{type: c.querySelector('.type').textContent, id: c.querySelector('.bc-id').textContent, title: c.querySelector('.bc-title').textContent, initials: c.querySelector('.av').textContent, owner: c.querySelector('.av').title, due: c.querySelector('.due-l').textContent, pill: c.querySelector('.pill').textContent, eye: !!c.querySelector('.eye'), eyeWords: c.querySelector('.eye .sr').textContent, label: c.querySelector('.bc-main').getAttribute('aria-label'), role: c.querySelector('.bc-main').getAttribute('role')}}; }})()", sid)
            self.assertEqual((card["type"], card["id"], card["title"], card["initials"], card["owner"], card["pill"]), ("Action", a, "Send the invitations", "PN", "Priya Nair", "Delayed"))
            self.assertRegex(card["due"], r"^In \d+ days$|^\d+ days late$|Today|Tomorrow")
            self.assertTrue(card["eye"])
            self.assertEqual(card["eyeWords"], "Shown to the client")
            self.assertEqual(card["role"], "button")
            self.assertTrue(card["label"].startswith(f"{a} Send the invitations, Delayed"), card["label"])
            self.assertEqual(cdp.js(f"!!document.querySelector(\"article[data-id='{self.id_of('Book the training room')}'] .eye\")", sid), False)
            self.assertEqual(cdp.js(f"document.querySelector(\"article[data-id='{self.id_of('Book the training room')}'] .av\")", sid), None, "no initials for an item with no owner")

    def test_one_level_of_swimlanes_by_workstream_or_type(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status", lane="workstream")
            lanes = cdp.js("[...document.querySelectorAll('#work-board .lane')].map(l => [l.querySelector('.ll').textContent, +l.querySelector('.lc').textContent, l.querySelectorAll('.bcard').length])", sid)
            self.assertTrue(lanes and all(c == n for _, c, n in lanes), lanes)
            self.assertEqual([x[0] for x in lanes][:2], ["Build", "Data"])
            self.assertEqual(lanes[-1][0], "No workstream")
            click(cdp, sid, "#swimlanes")
            self.assertEqual(cdp.js("[...document.querySelectorAll('.ddmenu [role=menuitem]')].map(b => b.textContent)", sid), ["None", "Workstream", "Type"])
            click(cdp, sid, ".ddmenu [data-kind=type]")
            self.until(cdp, sid, "document.querySelector('#swimlanes').textContent === 'Swimlanes: Type'")
            self.assertEqual(cdp.js("[...document.querySelectorAll('#work-board .lane .ll')].map(c => c.textContent)", sid), ["Actions", "Risks and issues", "Decisions"])
            click(cdp, sid, "#group-by")                       # the group chosen is not offered as a lane
            click(cdp, sid, ".ddmenu [data-kind=type]")
            self.until(cdp, sid, "!document.querySelector('#work-board .lane-h')", "no lanes when Group by takes the lane's place")


class Moves(Base):
    def test_dragging_a_card_is_one_step_with_undo(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            a = self.id_of("Order the laptops")
            before = self.steps()
            self.drag(cdp, sid, a, self.cell("Delayed"))
            t = self.wait_toast(cdp, sid, "done")
            self.assertEqual(t["text"], f"{a} is now Delayed.")
            self.assertTrue(t["undo"])
            self.assertEqual(self.row(a)["status"], "Delayed")
            self.assertEqual(self.steps(), before + 1, "one step")
            self.assertEqual(self.sent[-1][1]["changes"], {"status": "Delayed"})
            self.assertIn(a, self.cards_in(cdp, sid, "Delayed"), "the card is drawn in its new column")
            click(cdp, sid, "[data-undo]")
            self.until(cdp, sid, f"document.querySelector(\"{self.cell('Open')} article[data-id='{a}']\")", "the card back in Open")
            self.assertEqual(self.row(a)["status"], "Open")

    def test_a_drag_closes_an_item_and_a_reopen_clears_the_date(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            a = self.id_of("Book the training room")
            self.drag(cdp, sid, a, self.cell("Closed"))
            self.wait_toast(cdp, sid, "done")
            self.assertEqual(self.row(a)["status"], "Closed")
            self.assertTrue(self.row(a)["closed"])
            self.drag(cdp, sid, a, self.cell("Open"))
            self.until(cdp, sid, f"document.querySelector(\"{self.cell('Open')} article[data-id='{a}']\")")
            self.assertFalse(self.row(a)["closed"])

    def test_the_move_to_menu_is_the_keyboard_path_and_makes_the_same_step(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            a = self.id_of("Order the laptops")
            before = self.steps()
            cdp.js(f"document.querySelector(\"[data-move='{a}']\").focus()", sid)
            key(cdp, sid, "Enter")
            self.until(cdp, sid, "!!document.querySelector('.ddmenu')", "the menu")
            self.assertEqual(cdp.js("document.querySelector('[data-move]').closest('article') && document.querySelector('.ddmenu').getAttribute('aria-label')", sid), f"Move {a} to")
            items = cdp.js("[...document.querySelectorAll('.ddmenu [role=menuitem]')].map(b => b.textContent)", sid)
            self.assertEqual(items, ["Delayed", "Closed", "Cancelled"], "only where an action can go, not where it is")
            self.assertEqual(cdp.js("document.querySelector('.ddmenu .mh').textContent", sid), "Move to Status")
            key(cdp, sid, "ArrowDown")
            key(cdp, sid, "Enter")                                   # Closed
            t = self.wait_toast(cdp, sid, "done")
            self.assertEqual(t["text"], f"{a} is now Closed.")
            self.assertEqual((self.row(a)["status"], self.steps()), ("Closed", before + 1))
            click(cdp, sid, "[data-undo]")
            self.until(cdp, sid, "document.querySelector('.toast-text').textContent === 'Undone.'")
            self.assertEqual(self.row(a)["status"], "Open")

    def test_the_menu_closes_with_escape_and_gives_focus_back(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            a = self.id_of("Order the laptops")
            before = self.steps()
            click(cdp, sid, f"[data-move='{a}']")
            self.until(cdp, sid, "!!document.querySelector('.ddmenu')")
            key(cdp, sid, "Escape")
            self.until(cdp, sid, "!document.querySelector('.ddmenu')")
            self.assertEqual(cdp.js("document.activeElement.dataset.move", sid), a)
            self.assertEqual(self.steps(), before)

    def test_a_lane_and_a_column_in_one_step(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status", lane="workstream")
            a = self.id_of("Order the laptops")                       # Data, Open
            before = self.steps()
            self.drag(cdp, sid, a, self.cell("Delayed", "Build"))
            t = self.wait_toast(cdp, sid, "done")
            self.assertEqual(t["text"], f"{a} is now Delayed, in the Build workstream.")
            self.assertEqual((self.row(a)["status"], self.row(a)["workstream"]), ("Delayed", "Build"))
            self.assertEqual(self.steps(), before + 1, "both changes are one step")
            self.assertEqual(self.sent[-1][1]["changes"], {"status": "Delayed", "workstream": "Build"})
            click(cdp, sid, "[data-undo]")
            self.until(cdp, sid, f"document.querySelector(\"{self.cell('Open', 'Data')} article[data-id='{a}']\")", "both put back")
            self.assertEqual((self.row(a)["status"], self.row(a)["workstream"]), ("Open", "Data"))

    def test_the_menu_offers_lanes_too(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status", lane="workstream")
            a = self.id_of("Order the laptops")
            click(cdp, sid, f"[data-move='{a}']")
            heads = cdp.js("[...document.querySelectorAll('.ddmenu .mh')].map(h => h.textContent)", sid)
            self.assertEqual(heads, ["Move to Status", "Move to Workstream"])
            click(cdp, sid, ".ddmenu [data-lane='1'][data-to='Build']")
            self.wait_toast(cdp, sid, "done")
            self.assertEqual(self.row(a)["workstream"], "Build")

    def test_refusals_say_why_and_change_nothing(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            risk, issue, action = self.id_of("Supplier slips"), self.id_of("Test system is down"), self.id_of("Order the laptops")
            decided, made = self.id_of("Use the new tool"), self.id_of("shared calendar")
            before = self.steps()
            sent = len(self.sent)
            for card, cell, words in [
                (risk, self.cell("Delayed"), "A risk can't be Delayed. It can be Open, Closed or Cancelled."),
                (decided, self.cell("Delayed"), "A decision can't be Delayed. It can be Pending, Made or Withdrawn."),
                (made, self.cell("Pending"), "A decision that has been made can't go back to Pending. Record a new decision that replaces it."),
                (action, self.cell("Withdrawn"), "An action can't be Withdrawn. It can be Open, Delayed, Closed or Cancelled."),
            ]:
                with self.subTest(card=card, cell=cell):
                    cdp.js("document.querySelector('.toast') && document.querySelector('[data-dismiss]').click()", sid)
                    self.drag(cdp, sid, card, cell)
                    t = self.wait_toast(cdp, sid, "note")
                    self.assertEqual(t["text"], words)
                    self.assertFalse(t["undo"], "nothing to undo")
            self.assertEqual((self.steps(), len(self.sent)), (before, sent), "nothing reached the server")
            self.assertEqual(self.row(risk)["status"], "Open")
            del issue

    def test_refusals_by_group(self):
        cases = [
            ("workstream", "Use the new tool", "Data", "A decision isn't part of a workstream."),
            ("priority", "Supplier slips", "Low", "A risk or issue's priority comes from its impact and likelihood. Change those in its details."),
            ("priority", "Use the new tool", "Low", "A decision has no priority."),
            ("type", "Order the laptops", "decisions", "An action can't change its type."),
            ("milestone", "Use the new tool", None, "A decision isn't tied to a milestone."),
            ("due", "Order the laptops", "overdue", "Overdue is worked out from the due date. Drop the card on This week, Next week or Later and choose a date."),
        ]
        with chrome() as cdp:
            sid = self.visit(cdp)
            before = self.steps()
            for group, card, col, words in cases:
                with self.subTest(group=group, card=card):
                    self.board(cdp, sid, group)
                    if col is None:
                        col = next(c.get("id") for c in self.data["milestones"])
                    cdp.js("document.querySelector('.toast') && document.querySelector('[data-dismiss]').click()", sid)
                    self.drag(cdp, sid, self.id_of(card), self.cell(col))
                    self.assertEqual(self.wait_toast(cdp, sid, "note")["text"], words)
            self.assertEqual(self.steps(), before)

    def test_overdue_is_not_a_drop_target_or_a_menu_item(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "due")
            self.assertEqual(cdp.js("document.querySelector(\"section.col[data-col=overdue]\").getAttribute('aria-disabled')", sid), "true")
            a = self.id_of("Order the laptops")
            click(cdp, sid, f"[data-move='{a}']")
            items = cdp.js("[...document.querySelectorAll('.ddmenu [role=menuitem]')].map(b => b.textContent)", sid)
            self.assertNotIn("Overdue", items)
            self.assertIn("No date", items)

    def test_due_asks_for_a_date_never_in_the_past(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "due")
            a = self.id_of("Order the laptops")                       # due 2026-12-01 (Later)
            before = self.steps()
            self.drag(cdp, sid, a, self.cell("next_week"))
            self.until(cdp, sid, "!!document.querySelector('.dpick')", "the date picker")
            self.assertEqual(cdp.js("document.querySelector('.dpick').getAttribute('role')", sid), "dialog")
            self.assertEqual(cdp.js("document.querySelector('.dpick input').min", sid), TODAY, "the earliest day is today")
            self.until(cdp, sid, "document.activeElement === document.querySelector('.dpick input')", "focus in the date box")
            cdp.js("(() => { const i = document.querySelector('.dpick input'); i.value = '2026-10-01'; i.dispatchEvent(new Event('input', {bubbles: true})); })()", sid)
            click(cdp, sid, "[data-set]")
            self.until(cdp, sid, "!!document.querySelector('.dp-err')")
            self.assertEqual(cdp.js("document.querySelector('.dp-err').textContent", sid), "Pick today or a later date.")
            self.assertEqual(self.steps(), before, "a past date is never sent")
            cdp.js("(() => { const i = document.querySelector('.dpick input'); i.value = '2026-11-06'; i.dispatchEvent(new Event('input', {bubbles: true})); })()", sid)
            click(cdp, sid, "[data-set]")
            t = self.wait_toast(cdp, sid, "done")
            self.assertEqual(t["text"], f"{a} is now due 06-11-2026.")
            self.assertEqual(self.row(a)["due_date"], "2026-11-06")
            self.assertEqual(self.steps(), before + 1)
            click(cdp, sid, "[data-undo]")
            self.until(cdp, sid, "document.querySelector('.toast-text').textContent === 'Undone.'")
            self.assertEqual(self.row(a)["due_date"], "2026-12-01")

    def test_the_suggested_date_is_that_weeks_friday_and_escape_closes_only_the_picker(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "due")
            a = self.id_of("Order the laptops")
            before = self.steps()
            self.drag(cdp, sid, a, self.cell("this_week"))
            self.until(cdp, sid, "!!document.querySelector('.dpick')")
            self.assertEqual(cdp.js("document.querySelector('.dpick input').value", sid), "2026-10-30")
            self.until(cdp, sid, "document.activeElement === document.querySelector('.dpick input')", "focus in the date box")
            cdp.js("document.activeElement && document.activeElement.blur()", sid)       # Esc works from wherever focus is
            key(cdp, sid, "Escape")
            self.until(cdp, sid, "!document.querySelector('.dpick')")
            self.assertEqual(self.steps(), before)

    def test_no_date_clears_the_date(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "due")
            a = self.id_of("Order the laptops")
            self.drag(cdp, sid, a, self.cell("__none"))
            self.wait_toast(cdp, sid, "done")
            self.assertIsNone(self.row(a)["due_date"])
            self.assertEqual(self.sent[-1][1]["changes"], {"due_date": None})

    def test_a_pending_decision_dragged_to_made_asks_first_and_has_no_undo(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            d = self.id_of("Use the new tool")
            before = self.steps()
            self.drag(cdp, sid, d, self.cell("Made"))
            self.until(cdp, sid, "!!document.querySelector('.dpick')")
            self.assertEqual(cdp.js("document.querySelector('.dpick').getAttribute('aria-label')", sid), "Record this decision")
            click(cdp, sid, "[data-cancel]")
            self.assertEqual(self.steps(), before, "Cancel changes nothing")
            self.drag(cdp, sid, d, self.cell("Made"))
            self.until(cdp, sid, "!!document.querySelector('[data-yes]')")
            self.assertEqual(cdp.js("document.querySelector('[data-yes]').closest('[role=dialog], .dpick, .confirm, div').parentElement.textContent.includes(\"A made decision can't go back to Pending. If it changes, record a new one.\")", sid), True, "the confirm and the refusal use the same phrase")
            click(cdp, sid, "[data-yes]")
            t = self.wait_toast(cdp, sid, "done")
            self.assertEqual(t["text"], f"{d} is now Made, dated today. This can't be undone. Record a new decision to change it.")
            self.assertFalse(t["undo"], "a made decision can't be put back, so there is no Undo")
            self.assertEqual((self.row(d)["status"], self.row(d)["date"]), ("Made", TODAY))

    def test_a_card_with_nowhere_to_go_says_so_and_what_to_do(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            made = cdp.js("(() => { const c = document.querySelector(\"section.col[data-col='Made'] article\"); return c ? c.dataset.id : null; })()", sid)
            self.assertTrue(made, "the demo has a made decision")
            click(cdp, sid, f"[data-move='{made}']")
            self.until(cdp, sid, "!!document.querySelector('.ddmenu')", "the menu")
            items = cdp.js("[...document.querySelectorAll('.ddmenu [role=menuitem]')].map(b => b.textContent)", sid)
            self.assertEqual(items, ["This card can't move on this board. Record a new decision to change it."], "a made decision is changed by a new one, not by opening it")
            self.assertNotIn("Open it", items[0])

    def test_a_card_that_is_not_a_decision_keeps_the_general_sentence_when_it_cannot_move(self):
        src = (ROOT / "src/clark/page/src/edit/Board.jsx").read_text(encoding="utf-8")
        self.assertIn("This card can't move on this board. Open it to change its details.", src)
        self.assertIn("This card can't move on this board. Record a new decision to change it.", src)

    def test_a_move_to_where_the_card_is_does_nothing(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            a = self.id_of("Order the laptops")
            before = (self.steps(), len(self.sent))
            self.drag(cdp, sid, a, self.cell("Open"))
            self.assertIsNone(self.toast(cdp, sid))
            self.assertEqual((self.steps(), len(self.sent)), before)
            self.assertEqual(cdp.js("location.hash.includes('item=')", sid), False, "a drag never opens the peek")

    def test_in_view_nothing_moves(self):
        with chrome() as cdp:
            sid = self.visit(cdp, edit=False)
            self.board(cdp, sid, "status", mode="open")
            cdp.js("document.querySelector('[data-mode=view]').click()", sid)
            self.assertEqual(cdp.js("document.querySelectorAll('[data-move]').length", sid), 0)
            a = self.id_of("Order the laptops")
            before = len(self.sent)
            self.drag(cdp, sid, a, self.cell("Delayed"))
            self.assertEqual(len(self.sent), before)
            self.assertIn("Switch to Edit to move cards.", cdp.js("document.querySelector('.lanebar').textContent", sid))


class Collapse(Base):
    def test_columns_collapse_in_every_lane_and_are_remembered(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status", lane="workstream")
            n = cdp.js("document.querySelectorAll(\"section.col[data-col='Closed']\").length", sid)
            self.assertGreater(n, 1)
            click(cdp, sid, "section.col[data-col='Closed'] .col-b")
            self.until(cdp, sid, "document.querySelectorAll(\"section.col.shut[data-col='Closed']\").length === " + str(n), "every lane's column shut")
            self.assertEqual(cdp.js("document.querySelector(\"section.col[data-col='Closed'] .col-b\").getAttribute('aria-expanded')", sid), "false")
            self.assertEqual(cdp.js("getComputedStyle(document.querySelector(\"section.col.shut\")).width", sid), "44px")
            self.reload(cdp, sid)
            self.until(cdp, sid, "!!document.querySelector('#work-board')")
            self.assertEqual(cdp.js("document.querySelectorAll(\"section.col.shut[data-col='Closed']\").length", sid), n, "still shut after a reload")
            self.assertEqual(cdp.js("document.querySelectorAll('section.col.shut').length", sid), n, "and only those")
            click(cdp, sid, "section.col[data-col='Closed'] .col-b")
            self.until(cdp, sid, "document.querySelectorAll('section.col.shut').length === 0")

    def test_every_column_has_a_count_and_an_empty_one_says_so(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            cols = cdp.js("[...document.querySelectorAll('section.col')].map(c => [c.dataset.col, +c.dataset.count, +c.querySelector('.cn').textContent, c.querySelectorAll('.bcard').length, !!c.querySelector('.none')])", sid)
            for col, count, shown, cards, empty in cols:
                self.assertEqual((count, shown), (cards, cards), col)
                self.assertEqual(empty, cards == 0, col)


class Peek(Base):
    def test_a_double_click_opens_the_peek_hook_and_a_click_on_another_card_moves_it_without_a_new_entry(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            cdp.js("window.__peeks = []; window.addEventListener('clark:open-peek', (e) => window.__peeks.push(e.detail.id))", sid)
            a, b = self.id_of("Order the laptops"), self.id_of("Send the invitations")
            n = cdp.js("history.length", sid)
            dblclick(cdp, sid, f"article[data-id='{a}'] .bc-main")      # #195: one click selects the card, a double click opens it
            self.until(cdp, sid, f"location.hash.includes('item={a}')", "the address")
            self.assertEqual(cdp.js("window.__peeks", sid), [a])
            self.until(cdp, sid, f"document.querySelector(\"article[data-id='{a}']\").classList.contains('sel')", "the selected look")
            m = cdp.js("history.length", sid)
            click(cdp, sid, f"article[data-id='{b}'] .bc-main")
            self.until(cdp, sid, f"location.hash.includes('item={b}')")
            self.assertEqual(cdp.js("history.length", sid), m, "another card replaces the peek, it adds no entry")
            self.assertEqual(m, n + 1)
            cdp.js(f"document.querySelector(\"article[data-id='{a}'] .bc-main\").focus()", sid)
            key(cdp, sid, "Enter")
            self.until(cdp, sid, f"location.hash.includes('item={a}')", "Enter opens it too")


class FullScreen(Base):
    def test_full_screen_icon_scrolls_headings_and_keys(self):
        with chrome() as cdp:
            sid = self.visit(cdp, height=420)
            self.board(cdp, sid, "status", lane="workstream")
            self.assertTrue(cdp.js("!!document.querySelector('.lanebar #board-full')", sid), "the icon is on the swimlane row")
            self.assertEqual(cdp.js("document.querySelector('#board-full').getAttribute('aria-label')", sid), "View full screen")
            bg = cdp.js("getComputedStyle(document.body).backgroundColor", sid)
            click(cdp, sid, "#board-full")
            self.until(cdp, sid, "document.body.classList.contains('board-full')")
            self.assertEqual(cdp.js("document.querySelector('#board-full').getAttribute('aria-label')", sid), "Leave full screen")
            self.assertEqual(cdp.js("document.querySelector('#work-live').textContent", sid), "Full screen on.")
            self.assertEqual(cdp.js("getComputedStyle(document.querySelector('.top')).display", sid), "none", "the top bar goes")
            self.assertEqual(cdp.js("getComputedStyle(document.body).backgroundColor", sid), bg, "the brand background stays")
            self.assertTrue(cdp.js("document.querySelector('.fbar').getBoundingClientRect().height > 0", sid), "the filters stay")
            self.assertEqual(cdp.js("document.documentElement.scrollWidth <= innerWidth", sid), True)
            # scroll: the filters scroll away, the headings stay
            cdp.js("document.querySelector('main').scrollTop = 260", sid)
            self.until(cdp, sid, "document.querySelector('main').scrollTop > 100", "the window scrolled")
            self.assertLess(cdp.js("document.querySelector('.fbar').getBoundingClientRect().bottom", sid), 0, "the filters scrolled away")
            lane_top = cdp.js("document.querySelector('.lane-h').getBoundingClientRect().top", sid)
            col_top = cdp.js("document.querySelector('.lane .col-h').getBoundingClientRect().top", sid)
            self.assertEqual((lane_top, col_top), (0, 40), "lane and column headings stay at the top")
            # at the bottom there is room under the last card
            cdp.js("document.querySelector('main').scrollTop = 1e6", sid)
            gap = cdp.js("(() => { const m = document.querySelector('main'); const cs = [...document.querySelectorAll('.bcard')]; const last = Math.max(...cs.map(c => c.getBoundingClientRect().bottom)); return m.getBoundingClientRect().bottom - last; })()", sid)
            self.assertGreaterEqual(gap, 48, "at least 48 px under the last card")
            # Esc with a peek open leaves full screen alone; with none open it leaves
            cdp.js("document.body.insertAdjacentHTML('beforeend', '<div data-peek></div>')", sid)
            key(cdp, sid, "Escape")
            self.assertTrue(cdp.js("document.body.classList.contains('board-full')", sid), "the peek takes the first Esc")
            cdp.js("document.querySelector('[data-peek]').remove()", sid)
            key(cdp, sid, "Escape")
            self.until(cdp, sid, "!document.body.classList.contains('board-full')", "Esc leaves")
            self.assertEqual(cdp.js("document.activeElement.id", sid), "board-full", "focus returns to the icon")
            self.assertEqual(cdp.js("document.querySelector('#work-live').textContent", sid), "Full screen off.")
            click(cdp, sid, "#board-full")
            self.until(cdp, sid, "document.body.classList.contains('board-full')")
            click(cdp, sid, "#board-full")
            self.until(cdp, sid, "!document.body.classList.contains('board-full')", "the icon leaves too")

    def test_a_card_double_click_in_full_screen_opens_the_peek_and_a_move_keeps_full_screen(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            click(cdp, sid, "#board-full")
            self.until(cdp, sid, "document.body.classList.contains('board-full')")
            a = self.id_of("Order the laptops")
            self.drag(cdp, sid, a, self.cell("Delayed"))
            self.wait_toast(cdp, sid, "done")
            self.assertTrue(cdp.js("document.body.classList.contains('board-full')", sid), "a move redraws the board but keeps full screen")
            dblclick(cdp, sid, f"article[data-id='{a}'] .bc-main")
            self.until(cdp, sid, f"location.hash.includes('item={a}')")

    def test_full_screen_ends_when_the_table_comes_back(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.board(cdp, sid, "status")
            click(cdp, sid, "#board-full")
            self.until(cdp, sid, "document.body.classList.contains('board-full')")
            cdp.js("window.scrollTo(0, 0)", sid)
            cdp.js("document.querySelector('[data-layout=table]').click()", sid)
            self.until(cdp, sid, "!document.body.classList.contains('board-full')", "the table, with the top bar")

    def test_board_view_pins_only_the_column_headings_under_the_top_bar(self):
        """#134: the toolbar rows scroll away and the column headings stay at the foot of the top bar; back at 0 the rows return."""
        rows = "['.head', '.wbar', '.fbar', '.factive', '.lanebar']"
        for width in (1400, 900):
            for full in (False, True):
                with self.subTest(width=width, full=full), chrome() as cdp:
                    sid = self.visit(cdp, width=width, height=700)
                    self.board(cdp, sid, "status")
                    if full:
                        click(cdp, sid, "#board-full")
                        self.until(cdp, sid, "document.body.classList.contains('board-full')")
                    scroller = "document.querySelector('main')" if full else "document.scrollingElement"
                    self.assertTrue(cdp.js(f"{rows}.filter(s => document.querySelector(s)).every(s => document.querySelector(s).getBoundingClientRect().bottom > 0 || {str(full).lower()})", sid), "at the top the rows show")
                    cdp.js(f"{scroller}.scrollTop = 600", sid)
                    self.until(cdp, sid, f"{scroller}.scrollTop > 100", "scrolled")
                    got = cdp.js(
                        "(() => { const top = document.querySelector('.top'), bar = top && getComputedStyle(top).display !== 'none' ? top.getBoundingClientRect().bottom : 0;"
                        f" const rows = {rows}.map(s => document.querySelector(s)).filter(e => e && e.getBoundingClientRect().height > 0);"
                        " const h = document.querySelector('.col-h').getBoundingClientRect().top;"
                        " return {bar, h, rows: rows.map(e => Math.round(e.getBoundingClientRect().bottom)), n: rows.length}; })()", sid)
                    self.assertGreaterEqual(got["n"], 3, got)
                    self.assertTrue(all(b <= got["bar"] + 1 for b in got["rows"]), f"the toolbar rows are above the top bar's foot: {got}")
                    self.assertLessEqual(abs(got["h"] - got["bar"]), 2, f"the column headings sit at the top bar's foot: {got}")
                    cdp.js(f"{scroller}.scrollTop = 0", sid)
                    self.until(cdp, sid, f"{scroller}.scrollTop === 0", "back at the top")
                    self.assertTrue(cdp.js("['.wbar', '.fbar', '.factive', '.lanebar'].every(s => document.querySelector(s).getBoundingClientRect().top >= (document.querySelector('.top') && getComputedStyle(document.querySelector('.top')).display !== 'none' ? document.querySelector('.top').getBoundingClientRect().bottom - 1 : -1))", sid), "back at the top the toolbar shows again")

    def test_pinned_headings_dark_wheel_no_overlap_and_focus(self):
        """#134 (more): in light and dark, at 1400 and 900 px, the toolbar's top moves away with the page, the headings pin at the top
        bar's foot, the wheel moves the page first, no card sits under a heading, and tabbing to a card brings it clear of the headings."""
        for theme in ("light", "dark"):
            for width in (1400, 900):
                with self.subTest(theme=theme, width=width), chrome() as cdp:
                    sid = self.visit(cdp, width=width, height=700)
                    cdp.js(f"document.documentElement.dataset.theme = '{theme}'", sid)
                    self.board(cdp, sid, "status")
                    top0 = cdp.js("document.querySelector('.wbar').getBoundingClientRect().top", sid)
                    cdp.js("window.scrollTo(0, 0)", sid)
                    # the wheel over the board moves the page first, up to the gap, and never past it
                    cdp.call("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": 700, "y": 400, "deltaX": 0, "deltaY": 120}, sid)
                    self.until(cdp, sid, "window.scrollY > 0", "the page took the wheel")
                    cdp.js("window.scrollTo(0, 100000)", sid)
                    self.until(cdp, sid, "window.scrollY > 100", "scrolled to the end")
                    got = cdp.js(
                        "(() => { const bar = document.querySelector('.top').getBoundingClientRect().bottom, r = s => document.querySelector(s).getBoundingClientRect();"
                        " const h = [...document.querySelectorAll('.col-h')].map(e => e.getBoundingClientRect()), hb = Math.max(...h.map(x => x.bottom));"
                        " const box = r('.boardbox');"
                        " return {bar, wbar: r('.wbar').bottom, ht: Math.min(...h.map(x => x.top)), hb, box: box.top}; })()", sid)
                    self.assertLessEqual(got["wbar"], got["bar"] + 1, got)
                    self.assertLessEqual(abs(got["ht"] - got["bar"]), 2, got)
                    self.assertLessEqual(abs(got["box"] - got["bar"]), 2, got)
                    self.assertGreater(top0, 0)
                    # no card is drawn over a heading: each card's top is at or below the headings' foot, or it is wholly clear of them
                    self.assertEqual(cdp.js("(() => { const hb = Math.max(...[...document.querySelectorAll('.col-h')].map(e => e.getBoundingClientRect().bottom));"
                                            " return [...document.querySelectorAll('.bcard')].filter(e => { const x = e.getBoundingClientRect(); const z = x => +getComputedStyle(x).zIndex || 0;"
                                            " return x.top < hb - 1 && x.bottom > hb && z(e) >= 3; }).length; })()", sid), 0, "no card sits above a heading")
                    # keyboard: focus the last card; it must not end under the headings
                    cdp.js("window.scrollTo(0, 0); document.querySelector('.boardbox').scrollTop = 0; [...document.querySelectorAll('.bcard .bc-main')].pop().focus()", sid)
                    self.until(cdp, sid, "document.activeElement && document.activeElement.classList.contains('bc-main')", "focus on a card")
                    self.assertTrue(cdp.js("(() => { const hb = Math.max(...[...document.querySelectorAll('.col-h')].map(e => e.getBoundingClientRect().bottom)), a = document.activeElement.getBoundingClientRect();"
                                           " return a.top >= hb - 1 && a.bottom <= innerHeight + 1; })()", sid), "the focused card is clear of the headings and on screen")

    def test_the_table_view_is_not_pinned(self):
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.assertFalse(cdp.js("document.body.classList.contains('board-view')", sid), "no board class in the table")
            self.board(cdp, sid, "status")
            self.assertTrue(cdp.js("document.body.classList.contains('board-view')", sid))
            cdp.js("document.querySelector('[data-layout=table]').click()", sid)
            self.until(cdp, sid, "!document.body.classList.contains('board-view') && !!document.querySelector('table.items')", "the table")

    def test_no_sideways_scroll_of_the_page_at_900_and_1400(self):
        for width in (1400, 900):
            with self.subTest(width=width), chrome() as cdp:
                sid = self.visit(cdp, width=width)
                self.board(cdp, sid, "status", lane="workstream")
                self.assertTrue(cdp.js("document.documentElement.scrollWidth <= innerWidth", sid), "the page does not scroll sideways")
                self.assertTrue(cdp.js("document.querySelector('.boardbox').scrollWidth > document.querySelector('.boardbox').clientWidth", sid), "the board scrolls inside itself")


class Source(unittest.TestCase):
    def test_no_way_to_delete_anything_and_no_hard_coded_colour(self):
        board = (PAGE_SRC / "edit" / "Board.jsx").read_text(encoding="utf-8")
        for name in ("Board.jsx",):
            text = (PAGE_SRC / "edit" / name).read_text(encoding="utf-8").replace("classList.remove(", "")     # a style class, not an item
            self.assertIsNone(re.search(r"\b(?:delete|remove|archive)\b", text, re.I), f"{name} has no way to take an item away")
        self.assertNotRegex(board, r"op: \"?(?:delete|new|move)")
        css = (ROOT / "src" / "clark" / "page" / "shell.css").read_text(encoding="utf-8")
        mine = css[css.index("Work items: Group by"):]
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(", mine.replace("rgba(255,255,255", "")), "tokens only")

    def test_the_event_for_the_peek_is_named(self):
        self.assertIn("clark:open-peek", (PAGE_SRC / "edit" / "Board.jsx").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
