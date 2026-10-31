"""#63: Back and Forward with something still open on the page, and in the published file.

Run: python3 dev/run_tests.py test_back_forward
The router and the pages, project and peek it steps through are tests/test_router.py. This file is what was left on #63:
- The editor (a real server over a real store, fictional data) with something open when Back or Forward comes: a section's title
  being typed is saved first, to the project it belongs to, and the message says so with Undo; a menu (the Add menu, a section's
  gutter menu) or a filter's box closes and nothing is chosen, also when the page stays drawn; opening any of them adds no entry.
- The published file (the real publish of the fixture), from file:// at 1400 and 900 px and from a sandboxed frame: each tab
  adds one entry, Back and Forward step through them, and nothing is blocked or thrown. From file://, an address typed for a tab
  the file has not opens its first tab, and one for another project keeps the file's own. The file has no detail panel yet
  (#42): Back closing one is for when it does.
Needs Google Chrome and is required: the tests fail, never skip, without it. Not covered: the trackpad swipe itself, Safari and
Edge (hand checks); history.back() and history.forward() are what the swipe, the mouse buttons and the keys call.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _demo import USER, DemoStore
import _testpage as testpage
import _publish_fixture as fx

from clark import changes, order, publish, server as sv
from clark.store import open_store
from test_page import navigate
from test_server import Running, _Pipe, chrome, wait

EMPTY_BRANDING = tempfile.mkdtemp(prefix="clark-no-brand-")        # so a brand on this laptop never changes a test
WATCH = ("window.errs = []; window.violations = [];"
         "addEventListener('error', function (e) { window.errs.push(String(e.message)); });"
         "addEventListener('unhandledrejection', function (e) { window.errs.push(String(e.reason)); });"
         "document.addEventListener('securitypolicyviolation', function (e) { window.violations.push(e.violatedDirective); });")


def tearDownModule():
    shutil.rmtree(EMPTY_BRANDING, ignore_errors=True)


class Editor(unittest.TestCase):
    """The page clark serves, with Edit: project ABC (the demo) and a second fictional project, XYZ."""

    def setUp(self):
        self.demo = DemoStore()
        self.addCleanup(self.demo.close)
        self.store = self.demo.store
        with self.store.step("dashboard", USER) as st:
            st.create("projects", {"code": "XYZ", "name": "Second Programme", "health": "On track"})
        self.demo.action(description="Agree the cut-over plan", owner="Sam Rivers")
        self.sent = []
        real_change = changes.make_change(self.store.path, [], USER)
        real_undo = changes.make_undo(self.store.path, [], USER)

        def seam(real, which):
            def call(req):
                self.sent.append(which)
                return real(req)
            return call
        self.s = Running(data_for=self.store.data_for, page_html=lambda: testpage.html(),
                         change=seam(real_change, "change"), undo=seam(real_undo, "undo"))
        self.addCleanup(self.s.close)
        quiet = mock.patch.object(sv.LOG, "disabled", True)
        quiet.start()
        self.addCleanup(quiet.stop)

    # ---- helpers ----
    def visit(self, cdp, hash_):
        self.cdp = cdp
        self.sid = navigate(cdp, self.s.port, hash_)
        self.until("document.documentElement.dataset.ready === '1' && !!document.querySelector('h1') && "
                   "document.querySelector('h1').textContent !== 'Loading'", "the page drew")
        self.js(WATCH)

    def js(self, expr):
        return self.cdp.js(expr, self.sid)

    def until(self, expr, what, seconds=10):
        self.assertTrue(wait(lambda: self.js(expr), seconds), what)

    def key(self, key, code, vk):
        for kind in ("keyDown", "keyUp"):
            self.cdp.call("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": code, "windowsVirtualKeyCode": vk}, self.sid)

    def edit(self):
        self.js("document.querySelector('[data-mode=edit]').click()")
        self.until("document.querySelector('#report') && document.querySelector('#report').dataset.mode === 'edit'", "Edit")

    def tab(self):
        return self.js("document.querySelector('.tab[aria-selected=true]').dataset.view")

    def titles(self, code):
        return [r["title"] for r in order.in_order(self.store.read("report_sections", code))]

    def page_titles(self):
        return self.js("[...document.querySelectorAll('.secs > .sec .sec-h')].map(e => e.textContent)")

    def type_title(self, ref, text):
        """Put the caret in section `ref`'s title, select it all and type `text`, and leave it there: not yet saved."""
        self.js(f"(function(){{var el=document.querySelector('[data-id=\"{ref}\"] [data-title]'); el.focus();"
                "var r=document.createRange(); r.selectNodeContents(el); var s=getSelection(); s.removeAllRanges(); s.addRange(r);})()")
        self.cdp.call("Input.insertText", {"text": text}, self.sid)
        self.assertEqual(self.js("document.activeElement.dataset.title"), "", "the title still has the caret")

    def no_errors(self):
        self.assertEqual(self.js("window.errs"), [])

    # ---- a title being typed ----
    def test_back_with_a_title_being_typed_saves_it_first_and_says_so(self):
        with chrome() as cdp:
            self.visit(cdp, "#work&p=ABC")
            self.js("document.querySelector('[data-view=dashboard]').click()")
            self.until("!!document.querySelector('.sec')", "the report drew")
            self.edit()
            n = self.js("history.length")
            first = self.js("document.querySelector('.secs > .sec').dataset.id")
            self.type_title(first, "Where we are now")
            self.assertEqual(self.js("history.length"), n, "typing adds no entry")
            self.assertEqual(self.sent, [], "nothing is saved while it is being typed")
            self.js("history.back()")
            self.until("location.hash === '#work&p=ABC' && !!document.querySelector('#work')", "Back went to Work items")
            self.until("!!document.querySelector('[data-undo]')", "the message says the title was saved, with Undo")
            self.assertEqual(self.js("document.querySelector('.toast-text').textContent"), "Title changed.")
            self.assertEqual(self.titles("ABC")[0], "Where we are now", "the title was kept, not lost")
            self.assertEqual(self.sent, ["change"], "saved once")
            self.js("history.forward()")
            self.until("!!document.querySelector('.secs > .sec')", "Forward to the report")
            self.assertEqual(self.page_titles()[0], "Where we are now")
            self.no_errors()

    def test_back_to_another_project_saves_the_title_in_its_own_project_and_undo_stays_there(self):
        with chrome() as cdp:
            self.visit(cdp, "#dashboard&p=XYZ")
            xyz = self.page_titles()
            abc_before = self.titles("ABC")
            self.js("clarkPage.setProject('ABC')")
            self.until("document.getElementById('project-name').textContent === 'Example Programme' && !!document.querySelector('.sec')",
                       "ABC drew")
            self.edit()
            first = self.js("document.querySelector('.secs > .sec').dataset.id")
            self.type_title(first, "Where we are now")
            self.js("history.back()")
            self.until("document.getElementById('project-name').textContent === 'Second Programme'", "Back went to XYZ")
            self.until("!!document.querySelector('[data-undo]')", "the message says the title was saved")
            self.assertEqual(self.titles("ABC")[0], "Where we are now", "saved in ABC, where it was typed")
            self.assertEqual(self.titles("XYZ"), xyz, "XYZ's report is untouched")
            self.assertEqual(self.page_titles(), xyz, "XYZ's page shows XYZ's sections, not the ones ABC's reply carried")
            self.js("document.querySelector('[data-undo]').click()")
            self.until("!!document.querySelector('.toast') && document.querySelector('.toast-text').textContent === 'Undone.'", "undone")
            self.assertEqual(self.titles("ABC"), abc_before, "Undo undid it in ABC")
            self.assertEqual(self.page_titles(), xyz, "and XYZ's page still shows XYZ's sections")
            self.assertEqual(self.sent, ["change", "undo"])
            self.no_errors()

    # ---- menus and a filter's box ----
    def test_back_with_a_section_menu_open_closes_it_and_chooses_nothing(self):
        with chrome() as cdp:
            self.visit(cdp, "#work&p=ABC")
            self.js("document.querySelector('[data-view=dashboard]').click()")
            self.until("!!document.querySelector('.sec')", "the report drew")
            self.edit()
            n = self.js("history.length")
            self.js("document.querySelector('.secs > .sec [data-options]').click()")
            self.until("!!document.querySelector('.secs .menu')", "the menu opened")
            self.assertEqual(self.js("history.length"), n, "opening a menu adds no entry")
            self.js("history.back()")
            self.until("!!document.querySelector('#work')", "Back went to Work items")
            self.js("history.forward()")
            self.until("!!document.querySelector('.secs > .sec')", "Forward to the report")
            self.assertEqual(self.js("document.querySelectorAll('.secs .menu').length"), 0, "the menu is not open again")
            self.assertEqual(self.sent, [], "nothing in it was chosen")
            self.no_errors()

    def test_back_and_forward_on_the_same_report_close_the_gutter_menu_and_choose_nothing(self):
        """The section control in the gutter (#101): its menu closes on Back and Forward even when the report stays drawn (the
        sections are not drawn again, so only the Back can have closed it), and a typed address closes it too."""
        with chrome() as cdp:
            self.visit(cdp, "#dashboard&p=ABC")
            self.until("!!document.querySelector('.sec')", "the report drew")
            self.edit()
            titles = self.titles("ABC")
            grip = "document.querySelector('.secs > .sec .sec-ctl [data-options]')"
            self.js("document.querySelector('.secs > .sec').clarkMark = 1")                  # the same section, never drawn again
            closed = (f"document.querySelectorAll('.secs .sec-ctl .menu').length === 0 && {grip}.getAttribute('aria-expanded') === 'false'"
                      " && !document.querySelector('.secs .sec-ctl.open')")

            def open_menu():
                self.js(f"{grip}.click()")
                self.until("!!document.querySelector('.secs .sec-ctl.open .menu[role=menu]')", "the gutter menu opened")

            n = self.js("history.length")
            open_menu()
            self.assertEqual(self.js("history.length"), n, "opening the menu adds no entry")
            self.js("location.hash = '#dashboard&p=ABC&f=any'")                              # a typed address
            self.until(closed, "a typed address closed the menu")
            open_menu()
            self.js("history.back()")
            self.until("location.hash === '#dashboard&p=ABC'", "Back")
            self.until(closed, "Back closed the menu")
            open_menu()
            self.js("history.forward()")
            self.until("location.hash === '#dashboard&p=ABC&f=any'", "Forward")
            self.until(closed, "Forward closed the menu")
            self.assertEqual(self.js("document.querySelector('.secs > .sec').clarkMark"), 1, "the report stayed drawn throughout")
            self.assertEqual(self.js("document.querySelector('#report').dataset.mode"), "edit", "still in Edit")
            self.assertEqual(self.sent, [], "nothing in it was chosen")
            self.assertEqual(self.titles("ABC"), titles, "no section moved, was added or was left out")
            self.assertEqual(self.js("document.querySelectorAll('.toast').length"), 0, "and nothing was said")
            self.no_errors()

    def test_a_gutter_menu_opened_in_its_first_frame_stays_open(self):
        """The first draw is not a Back: a menu opened the moment its control appears stays open."""
        with chrome() as cdp:
            self.visit(cdp, "#dashboard&p=ABC")
            self.until("!!document.querySelector('.sec')", "the report drew")
            self.js("window.quick = new MutationObserver(function () {"
                    "  var g = document.querySelector('.secs > .sec .sec-ctl [data-options]');"
                    "  if (g) { window.quick.disconnect(); g.click(); window.quickAt = !!document.querySelector('.secs .sec-ctl'); } });"
                    "window.quick.observe(document.body, { childList: true, subtree: true });")
            self.js("document.querySelector('[data-mode=edit]').click()")
            self.until("window.quickAt === true", "the grip was clicked as soon as it was drawn")
            self.until("!!document.querySelector('.secs .sec-ctl.open .menu')", "the menu opened")
            self.js("window.later = false; setTimeout(function () { window.later = true; }, 400)")
            self.until("window.later", "a moment later")
            self.assertEqual(self.js("document.querySelectorAll('.secs .sec-ctl.open .menu').length"), 1, "the menu is still open")
            self.no_errors()

    def test_a_menu_opened_straight_after_a_move_stays_open(self):
        """Only a menu that was open before the move closes. The close comes a frame or more after the move, so a menu opened in
        that time (a click or a key straight after Back or a typed address) was opened on the new page and stays open: the
        profile menu and a section's gutter menu, each opened in the same moment as a typed address."""
        with chrome() as cdp:
            self.visit(cdp, "#dashboard&p=ABC")
            self.until("!!document.querySelector('.sec')", "the report drew")
            self.edit()
            later = "window.later = false; setTimeout(function () { window.later = true; }, 400)"
            self.js("location.hash = '#dashboard&p=ABC&f=any'; document.querySelector('#profile-btn').click()")
            self.until("!!document.querySelector('#profile-menu')", "the profile menu opened")
            self.js(later)
            self.until("window.later", "a moment later")
            self.assertTrue(self.js("!!document.querySelector('#profile-menu')"), "the profile menu is still open")
            self.assertEqual(self.js("document.querySelector('#profile-btn').getAttribute('aria-expanded')"), "true")
            self.js("document.querySelector('#profile-menu').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
            self.until("!document.querySelector('#profile-menu')", "Esc closed it")
            grip = "document.querySelector('.secs > .sec .sec-ctl [data-options]')"
            self.js(f"location.hash = '#dashboard&p=ABC'; {grip}.click()")
            self.until("!!document.querySelector('.secs .sec-ctl.open .menu[role=menu]')", "the gutter menu opened")
            self.js(later)
            self.until("window.later", "a moment later")
            self.assertEqual(self.js("document.querySelectorAll('.secs .sec-ctl.open .menu').length"), 1, "the gutter menu is still open")
            self.js("history.back()")                                         # and a menu that was open before a move still closes
            self.until("location.hash === '#dashboard&p=ABC&f=any'", "Back")
            self.until("document.querySelectorAll('.secs .sec-ctl .menu').length === 0", "Back closed the gutter menu")
            self.assertEqual(self.sent, [], "nothing was chosen")
            self.no_errors()

    def test_back_closing_a_peek_also_closes_the_add_menu_and_a_filter_box_and_keeps_the_filters(self):
        with chrome() as cdp:
            self.visit(cdp, "#work&p=ABC")
            self.js("document.querySelector('[data-show=all]').click()")
            self.until("location.hash.indexOf('&f=') > 0", "a filter is in the address")
            hash_ = self.js("location.hash")
            row = self.js("document.querySelector('tr[data-id]').dataset.id")
            n = self.js("history.length")
            self.js(f"clarkPage.openPeek('{row}')")
            self.until("!!clarkPage.peek()", "the peek opened")
            peek_hash = self.js("location.hash")
            self.js("document.querySelector('#newBtn').click()")
            self.until("!!document.querySelector('#newBtnMenu')", "the Add menu opened")
            self.assertEqual(self.js("history.length"), n + 1, "the peek added one entry and the menu none")
            self.js("history.back()")
            self.until("clarkPage.peek() === null", "Back closed the peek")
            self.assertEqual(self.js("location.hash"), hash_, "and kept the page and its filters")
            self.until("!document.querySelector('#newBtnMenu')", "the Add menu closed too")
            self.assertEqual(self.js("document.querySelector('#newBtn').getAttribute('aria-expanded')"), "false")
            self.assertEqual(self.js("document.querySelector('#work-note').textContent"), "", "nothing in it was chosen")
            self.js("history.forward()")
            self.until(f"location.hash === {json.dumps(peek_hash)}", "Forward reopened the peek")
            self.js("document.querySelector('[data-fb]').click()")
            self.until("!!document.querySelector('.fbox')", "a filter's box opened")
            self.assertEqual(self.js("history.length"), n + 1, "opening a filter's box adds no entry")
            self.js("history.back()")
            self.until("clarkPage.peek() === null", "Back closed the peek")
            self.until("!document.querySelector('.fbox')", "and the filter's box")
            self.assertEqual(self.js("location.hash"), hash_, "with the filters as they were")
            self.assertEqual(self.tab(), "work")
            self.assertEqual(self.sent, [])
            self.no_errors()


class PublishedFile(unittest.TestCase):
    """The real published file of the fixture (project PUB), opened from file:// with nothing listening."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        db = fx.build_db(Path(cls.tmp.name) / "clark.db")
        cls.store = open_store(db, onedrive_roots=[])
        cls.addClassCleanup(cls.store.close)
        done = publish.publish(cls.store, "PUB", cls.tmp.name, by_user="Demo User", now="2026-10-28", branding=EMPTY_BRANDING)
        cls.path = Path(done["path"])
        cls.name = 'Bridge & "Harbour" <Programme>'

    def attach(self, cdp, url, width):
        self.cdp = cdp
        tid = next(t["targetId"] for t in cdp.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
        self.sid = cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
        cdp.call("Page.enable", {}, self.sid)
        cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": WATCH}, self.sid)
        cdp.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False}, self.sid)
        cdp.call("Page.navigate", {"url": url}, self.sid)

    def js(self, expr):
        return self.cdp.js(expr, self.sid)

    def until(self, expr, what, seconds=10):
        self.assertTrue(wait(lambda: self.js(expr), seconds), f"{what}: {expr}")

    def steps(self, doc, frame, typed=True):
        """Tabs push one entry each and Back and Forward step through them; with `typed`, an address typed for a tab the file
        has not opens its first tab and one for another project keeps the file's own. A sandboxed frame has no address to type
        in (and setting location.hash there does nothing), so it is checked without."""
        sel = f"{doc}.querySelector('.tab[aria-selected=true]').dataset.view"
        h1 = f"{doc}.querySelector('h1').textContent"
        where = f"{frame}.location.hash"
        self.until(f"{doc} && {doc}.documentElement.dataset.ready === '1' && !!{doc}.querySelector('h1')", "the file drew")
        self.assertEqual(self.js(sel), "dashboard")
        n = self.js("history.length")
        for view in ("work", "milestones"):
            self.js(f"{doc}.querySelector('[data-view={view}]').click()")
            self.until(f"{sel} === '{view}'", view)
        self.assertEqual(self.js("history.length"), n + 2, "each tab added one entry")
        self.assertEqual(self.js(where), "#milestones&p=PUB")
        for view, heading in (("work", "Work items"), ("dashboard", self.name)):
            self.js(f"{frame}.history.back()")
            self.until(f"{sel} === '{view}' && {h1} === {json.dumps(heading)}", f"Back to {view}")
        for view in ("work", "milestones"):
            self.js(f"{frame}.history.forward()")
            self.until(f"{sel} === '{view}'", f"Forward to {view}")
        self.assertEqual(self.js("history.length"), n + 2, "Back and Forward add nothing")
        if not typed:
            return
        self.js(f"{frame}.location.hash = '#settings&p=PUB'")                                # typed: a tab the file has not
        self.until(f"{sel} === 'dashboard' && {h1} === {json.dumps(self.name)}", "no Settings in a file: the first tab")
        self.js(f"{frame}.location.hash = '#work&p=QRS'")                                    # typed: another project
        self.until(f"{sel} === 'work'", "the tab it names")
        self.assertEqual(self.js(f"{doc}.getElementById('project-name').textContent"), self.name, "the file's own project")
        self.js(f"{frame}.history.back()")
        self.until(f"{sel} === 'dashboard'", "Back from a typed address")

    def test_back_and_forward_step_through_the_tabs_from_file_url_at_1400_and_900(self):
        for width in (1400, 900):
            with self.subTest(width=width), chrome() as cdp:
                self.attach(cdp, self.path.as_uri(), width)
                self.until("document.documentElement.dataset.ready === '1'", "the file drew")
                self.assertEqual(self.js("location.protocol"), "file:")
                self.steps("document", "window")
                self.assertEqual(self.js("window.errs"), [])
                self.assertEqual(self.js("window.violations"), [], "the file's policy blocked nothing")

    def test_back_and_forward_work_in_a_sandboxed_frame(self):
        wrapper = Path(self.tmp.name) / "wrapper.html"
        wrapper.write_text("<!doctype html><meta charset=utf-8><body>"
                           f'<iframe sandbox="allow-scripts" width="1200" height="800" src="{self.path.as_uri()}"></iframe></body>',
                           encoding="utf-8")
        with chrome() as cdp:
            cdp.__class__ = Watching
            cdp.events = []
            self.cdp = cdp
            tid = next(t["targetId"] for t in cdp.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
            top = cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
            cdp.call("Page.enable", {}, top)
            # The sandboxed frame is a target of its own: it waits at its start until the watch is in it, then runs.
            cdp.call("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True}, top)
            cdp.call("Page.navigate", {"url": wrapper.as_uri()}, top)
            self.sid = self.frame_session(cdp)
            cdp.call("Page.enable", {}, self.sid)
            cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": WATCH}, self.sid)
            cdp.call("Runtime.runIfWaitingForDebugger", {}, self.sid)
            self.until("document.documentElement.dataset.ready === '1'", "the frame drew the file")
            self.assertEqual(self.js("String(origin)"), "null", "an opaque origin: the frame is sandboxed")
            self.assertEqual(self.js("location.protocol"), "file:")
            self.steps("document", "window", typed=False)
            self.assertEqual(self.js("window.errs"), [], "nothing thrown in the frame")
            self.assertEqual(self.js("window.violations"), [], "the file's policy blocked nothing in the frame")

    def frame_session(self, cdp):
        """The session of the sandboxed frame, once Chrome has attached to it (it is then waiting to run)."""
        def find():
            cdp.call("Target.getTargets")                                    # reads the events Chrome has sent meanwhile
            got = [e["params"]["sessionId"] for e in cdp.events if e.get("method") == "Target.attachedToTarget"
                   and e["params"]["targetInfo"]["type"] == "iframe"]
            return got[0] if got else None
        found = {}
        self.assertTrue(wait(lambda: found.setdefault("id", find()) or found.pop("id"), 15), "Chrome attached to the frame")
        return found["id"]


class Watching(_Pipe):
    """The harness's pipe, keeping the events Chrome sends (the harness drops them), as tests/test_publish.py has it."""

    def call(self, method, params=None, session=None):
        self.n += 1
        msg = {"id": self.n, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        os.write(self.w, json.dumps(msg).encode() + b"\0")
        while True:
            while b"\0" not in self.buf:
                chunk = os.read(self.r, 1 << 16)
                if not chunk:
                    raise RuntimeError("Chrome closed the pipe")
                self.buf += chunk
            raw, self.buf = self.buf.split(b"\0", 1)
            m = json.loads(raw)
            if m.get("id") == self.n:
                if "error" in m:
                    raise RuntimeError(m["error"])
                return m["result"]
            if "method" in m:
                self.events.append(m)

if __name__ == "__main__":
    unittest.main()
