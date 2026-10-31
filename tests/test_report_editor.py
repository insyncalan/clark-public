"""#65 part B: the page's View and Edit modes and the sections editor, in a real browser against the real routes.

Run: python3 dev/run_tests.py test_report_editor
Each browser test starts headless Chrome through the harness (tests/test_server.py chrome(): the keychain flags are in it) and a
real server whose `change` and `undo` are the real clark.changes over a real store in a temporary folder (fictional data), so the
page, the two routes and the writer are exercised end to end. A few tests wrap the seams to make a failure on purpose: the
page must say the plain words for it and never the server's own text. The non-browser checks (the two built pages are current,
the published build names no route that changes anything) need no browser.
"""
import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from _demo import USER, DemoStore
from _editor_checks import edit_elements
from _paths import SRC, TOOLS

sys.path.insert(0, str(TOOLS))
import build_page  # noqa: E402
import esbuild  # noqa: E402

from clark import changes, order, page, publish, server as sv  # noqa: E402
from test_page import DATA, navigate  # noqa: E402
from test_server import Running, chrome, wait  # noqa: E402

EMPTY_BRANDING = tempfile.mkdtemp(prefix="clark-no-brand-")        # so a brand on this laptop never changes a test
PAGE_SRC = SRC / "clark" / "page" / "src"
TITLES = ["Current state", "At a glance", "Use case summary", "Milestones", "Summary", "This week", "Next week",
          "Risks and issues", "Open actions", "Decisions", "Supporting documents"]
IDS = [f"ABC-S-{n:03d}" for n in range(1, 12)]
SECRET = "Server text that a person must never read"
QUIET = "Not shown on this page yet."                    # the page clark serves, for every type (#74)
ALT = 1                                                            # Input.dispatchKeyEvent modifiers: Alt


def tearDownModule():
    shutil.rmtree(EMPTY_BRANDING, ignore_errors=True)


class Pg:
    """The page under test, with the few things every test does."""

    def __init__(self, test, cdp, sid):
        self.t, self.cdp, self.sid = test, cdp, sid

    @classmethod
    def at(cls, test, cdp, port, hash_="#dashboard&p=ABC"):
        return cls(test, cdp, navigate(cdp, port, hash_))

    def js(self, expr):
        return self.cdp.js(expr, self.sid)

    def until(self, expr, what, seconds=10):
        self.t.assertTrue(wait(lambda: self.js(expr), seconds), what)

    def ready(self):
        self.until("document.querySelectorAll('.sec').length > 0 || !!document.querySelector('#no-sections')", "the report drew")

    def reload(self):
        """Reload and wait for the NEW document: location.reload() returns while the old one is still up, so a bare ready()
        sees the old sections (or none, mid-teardown). A token set on the old window is gone in the new one."""
        self.js("window.__old_document = true")
        self.js("location.reload()")
        self.until("window.__old_document === undefined && document.readyState === 'complete'", "the page reloaded")
        self.ready()

    def edit(self):
        self.js("document.querySelector('[data-mode=edit]').click()")
        self.until("document.querySelector('#report').dataset.mode === 'edit'", "Edit mode")

    def view(self):
        self.js("document.querySelector('[data-mode=view]').click()")
        self.until("document.querySelector('#report').dataset.mode === 'view'", "View mode")

    def ids(self):
        return self.js("[...document.querySelectorAll('.secs > .sec')].map(e => e.dataset.id)")

    def titles(self):
        return self.js("[...document.querySelectorAll('.secs > .sec .sec-h')].map(e => e.textContent)")

    def order_is(self, ids, what="the order"):
        self.t.assertTrue(wait(lambda: self.ids() == ids, 10), f"{what}: wanted {ids}, the page has {self.ids()}")

    def clear_toast(self):
        self.js("(document.querySelector('[data-dismiss]') || {click(){}}).click()")
        self.until("!document.querySelector('.toast')", "no message")

    def saved(self):
        """Wait for the toast that says a change was made (it carries Undo): the change has reached the store."""
        self.until("!!document.querySelector('[data-undo]')", "the change was saved")

    def toast(self):
        return self.js("(document.querySelector('.toast-text') || {}).textContent || ''")

    def key(self, key, modifiers=0, code=None, vk=0):
        for kind in ("keyDown", "keyUp"):
            self.cdp.call("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": code or key, "windowsVirtualKeyCode": vk,
                                                      "modifiers": modifiers}, self.sid)

    def type(self, text):
        self.cdp.call("Input.insertText", {"text": text}, self.sid)

    def mouse(self, kind, x, y, buttons=0):
        self.cdp.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "buttons": buttons,
                                                    "clickCount": 0 if kind == "mouseMoved" else 1}, self.sid)

    def box(self, selector):
        """[centre x, centre y, bottom] of the first element that matches."""
        return self.js(f"(function(){{var r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();"
                       "return [r.left + r.width / 2, r.top + r.height / 2, r.bottom];})()")

    def tall(self, cdp, width=1400):
        """A window tall enough for every section, so a drag never needs the page to scroll."""
        cdp.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 2400, "deviceScaleFactor": 1, "mobile": False}, self.sid)

    def rect(self, ref):
        """{left, top, right, bottom} of section `ref`."""
        return self.js(f"(function(){{var r=document.querySelector('[data-id=\"{ref}\"]').getBoundingClientRect();"
                       "return {left:r.left, top:r.top, right:r.right, bottom:r.bottom};})()")

    def drag(self, ref, x, y, release=True):
        """Press the handle of `ref`, move to (x, y) in steps and (by default) let go there."""
        hx, hy, _ = self.box(f'[data-id="{ref}"] [data-drag]')
        self.mouse("mousePressed", hx, hy, 1)
        for step in range(1, 9):
            self.mouse("mouseMoved", hx + (x - hx) * step / 8, hy + (y - hy) * step / 8, 1)
        if release:
            self.mouse("mouseReleased", x, y, 0)

    def menu(self, ref, act):
        self.js(f"document.querySelector('[data-id=\"{ref}\"] [data-options]').click()")
        self.until(f"!!document.querySelector('[data-id=\"{ref}\"] .menu')", "the menu opened")
        self.js(f"document.querySelector('[data-id=\"{ref}\"] [data-act={act}]').click()")

    def replace_title(self, ref, text, ending="Enter"):
        """Select the whole title of section `ref` and type `text` in its place; leave with Enter, Esc or by clicking away."""
        self.js(f"(function(){{var el=document.querySelector('[data-id=\"{ref}\"] [data-title]'); el.focus();"
                "if (el.select) { el.select(); } else { var r=document.createRange(); r.selectNodeContents(el); var s=getSelection();"
                "s.removeAllRanges(); s.addRange(r); }})()")
        if text:
            self.type(text)
        else:
            self.key("Backspace", code="Backspace", vk=8)
        if ending == "Enter":
            self.key("Enter", code="Enter", vk=13)
        elif ending == "Escape":
            self.key("Escape", code="Escape", vk=27)
        else:
            self.js("document.activeElement.blur()")


class Base(unittest.TestCase):
    def setUp(self):
        self.demo = DemoStore()
        self.addCleanup(self.demo.close)
        self.store = self.demo.store
        self.real_change = changes.make_change(self.store.path, [], USER)
        self.real_undo = changes.make_undo(self.store.path, [], USER)
        self.sent = []                       # every request the page made that reached the seams: (which, request)
        self.failure = None                     # a function (req) -> (status, body) or an exception to raise
        self.s = Running(data_for=self.store.data_for, page_html=lambda: page.page_html(EMPTY_BRANDING),
                         change=self.seam(self.real_change, "change"), undo=self.seam(self.real_undo, "undo"))
        self.addCleanup(self.s.close)
        quiet = mock.patch.object(sv.LOG, "disabled", True)               # a fault on purpose is logged by the server
        quiet.start()
        self.addCleanup(quiet.stop)

    def seam(self, real, which):
        def call(req):
            self.sent.append((which, req))
            if self.failure is not None:
                got = self.failure(req)
                if isinstance(got, BaseException):
                    raise got
                return got
            return real(req)
        return call

    def ids_in_store(self):
        return [r["id"] for r in order.in_order(self.store.read("report_sections", "ABC"))]

    def beside_flags(self):
        return {r["id"]: r["beside"] for r in order.in_order(self.store.read("report_sections", "ABC"))}

    def titles_in_store(self):
        return [r["title"] for r in order.in_order(self.store.read("report_sections", "ABC"))]

    def visit(self, cdp, hash_="#dashboard&p=ABC"):
        p = Pg.at(self, cdp, self.s.port, hash_)
        p.ready()
        return p


class Modes(Base):
    def test_editor_modes(self):
        """View and Edit switch with no reload and no navigation; Edit is in memory only (no address, no history entry)."""
        with chrome() as cdp:
            p = self.visit(cdp)
            p.js("window.marker = 'same page'; window.lengthBefore = history.length")
            hash_before = p.js("location.hash")
            self.assertEqual(p.js("document.querySelector('#report').dataset.mode"), "view", "a page opens in View")
            pressed = "[...document.querySelectorAll('.mode')].map(b => b.textContent + ':' + b.getAttribute('aria-pressed'))"
            self.assertEqual(p.js(pressed), ["View:true", "Edit:false"])
            for w in (1400, 900):
                cdp.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": 900, "deviceScaleFactor": 1, "mobile": False}, p.sid)
                p.edit()
                self.assertEqual(p.js(pressed), ["View:false", "Edit:true"])
                p.view()
                self.assertEqual(p.js(pressed), ["View:true", "Edit:false"])
            p.edit()
            self.assertEqual(p.js("window.marker"), "same page", "no reload")
            self.assertEqual(p.js("history.length"), p.js("window.lengthBefore"), "Back never stops on a mode change")
            self.assertEqual(p.js("location.hash"), hash_before, "the mode is not in the address")
            self.assertEqual(p.js("document.querySelector('.mode[data-mode=edit]').tagName"), "BUTTON")
            self.assertEqual(self.sent, [], "switching mode asks the server for nothing")
            p.reload()
            p.until("document.querySelector('#report').dataset.mode === 'view' && window.marker === undefined",
                    "a reload is View")
            self.assertNotIn("edit", p.js("location.hash"))

    def test_view_is_read_only(self):
        """View has none of the finder's elements (absent, not hidden); typing changes nothing; Edit has them all."""
        with chrome() as cdp:
            p = self.visit(cdp)
            self.assertEqual(edit_elements(cdp, p.sid), [], "View removes the Edit parts")
            before = p.js("document.querySelector('main').innerHTML")
            p.key("a", code="KeyA", vk=65)
            p.type("typed in View")
            p.js("document.querySelector('.sec-h').click()")
            p.type("again")
            p.key("ArrowDown", ALT, code="ArrowDown", vk=40)
            self.assertEqual(p.js("document.querySelector('main').innerHTML"), before, "typing in View changes nothing")
            self.assertEqual(edit_elements(cdp, p.sid), [])
            self.assertEqual(self.sent, [])
            # At a glance, the use case summary (#45) and the milestones section (#44, its own block and its own words when empty)
            # are drawn; every type still not drawn says the one plain line
            sec = "[...document.querySelectorAll('.secs > .sec')].filter(s => !['milestones', 'glance', 'usecases'].includes(s.dataset.type))"
            quiet = sec + ".map(s => s.dataset.type + ':' + s.querySelector('.quiet').textContent)"
            kinds = p.js(sec + ".map(s => s.dataset.type)")
            self.assertEqual(p.js(quiet), [f"{k}:{QUIET}" for k in kinds], "View: one plain line, the same for every type")
            self.assertTrue(p.js("!!document.querySelector('.secs > .sec[data-type=milestones] .msv, .secs > .sec[data-type=milestones] [data-no-milestones]')"),
                            "View: the milestones section is drawn, not the plain line")
            p.edit()
            found = edit_elements(cdp, p.sid)
            for what in ("[data-drag]", "[data-options]", "[data-add]", "[contenteditable=plaintext-only]"):
                self.assertEqual(len([f for f in found if what in f]), 11, what)
            self.assertEqual(p.js(quiet), [f"{k}:{QUIET}" for k in kinds], "Edit: the same line")
            self.assertNotIn("is not shown", p.js("document.querySelector('main').textContent"))
            p.view()
            self.assertEqual(edit_elements(cdp, p.sid), [], "and gone again in View")

    def test_a_report_with_no_sections_shows_none_and_does_not_crash(self):
        s = Running(data_for=DATA.get, page_html=lambda: page.page_html(EMPTY_BRANDING))
        self.addCleanup(s.close)
        with chrome() as cdp:
            p = Pg.at(self, cdp, s.port)
            p.ready()
            self.assertEqual(p.js("document.querySelectorAll('.sec').length"), 0)
            self.assertEqual(p.js("document.querySelector('#no-sections').textContent"), "This report has no sections yet. Switch to Edit to add one.")
            self.assertEqual(p.js("document.querySelector('h1').textContent"), "Example Programme")
            p.edit()
            self.assertEqual(p.js("document.querySelectorAll('[data-add]').length"), 1, "an empty report can still get its first section")
            p.js("window.posts = []; var f = window.fetch; window.fetch = function (u, o) { window.posts.push(String(o && o.body)); return f.apply(this, arguments); };")
            p.js("document.querySelector('[data-add]').click()")
            self.assertTrue(wait(lambda: len(p.js("window.posts")) == 1, 5), "with nothing claiming the request, the button asks for a plain text section")
            sent = json.loads(p.js("window.posts[0]"))
            self.assertEqual(sent.get("values"), {"type": "text"})
            self.assertIsNone(sent.get("after"), "at the end")


class Keys(Base):
    """#103: the plain keys V and E switch the Dashboard to View and Edit, as the two buttons do, and only there."""

    def mode(self, p):
        return p.js("document.querySelector('#report') ? document.querySelector('#report').dataset.mode : 'none'")

    def press(self, p, key, modifiers=0):
        p.key(key, modifiers, code="Key" + key.upper(), vk=ord(key.upper()))

    def test_v_and_e_switch_the_dashboard_and_the_buttons_say_so(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            self.assertEqual(p.js("[...document.querySelectorAll('.mode')].map(b => b.title + '|' + b.getAttribute('aria-keyshortcuts'))"),
                             ["View (V)|V", "Edit (E)|E"])
            p.js("window.marker = 'same page'; window.lengthBefore = history.length; document.activeElement.blur()")
            self.press(p, "e")
            p.until("document.querySelector('#report').dataset.mode === 'edit'", "E switches to Edit")
            self.assertEqual(p.js("document.querySelector('.mode[data-mode=edit]').getAttribute('aria-pressed')"), "true", "the buttons follow")
            self.press(p, "e")
            self.assertEqual(self.mode(p), "edit", "E again leaves it as it is")
            self.press(p, "v")
            p.until("document.querySelector('#report').dataset.mode === 'view'", "V switches to View")
            self.assertEqual(p.js("document.querySelector('.mode[data-mode=view]').getAttribute('aria-pressed')"), "true")
            self.press(p, "E")                                                     # a capital (Caps Lock) is the same key
            p.until("document.querySelector('#report').dataset.mode === 'edit'", "a capital E switches too")
            self.assertEqual(p.js("window.marker"), "same page", "no reload")
            self.assertEqual(p.js("history.length"), p.js("window.lengthBefore"), "no history entry")
            self.assertEqual(self.sent, [], "the keys ask the server for nothing")
            p.js("document.querySelector('.mode[data-mode=view]').focus()")      # a focused button still lets the key through
            self.press(p, "v")
            p.until("document.querySelector('#report').dataset.mode === 'view'", "V with a button focused")

    def test_a_modifier_or_a_held_key_does_nothing(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            for mod in (1, 2, 4, 8):                                              # Alt, Ctrl, Meta, Shift
                self.press(p, "e", mod)
            self.assertEqual(self.mode(p), "view")
            p.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'e', repeat: true, bubbles: true, cancelable: true}))")
            p.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'e', isComposing: true, bubbles: true, cancelable: true}))")
            self.assertEqual(self.mode(p), "view", "neither a held key nor a composing input method")
            self.press(p, "e")
            p.until("document.querySelector('#report').dataset.mode === 'edit'", "and the plain key still works")

    def test_they_do_nothing_where_the_key_belongs_to_something_else(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            item = self.store.data_for("ABC")["milestones"][0]["id"]
            p.edit()
            # the title of a section: editable text
            p.js("document.querySelector('[data-title]').focus()")
            self.press(p, "v")
            self.assertEqual(self.mode(p), "edit", "V in a title")
            p.js("document.activeElement.blur()")
            # a text field
            p.js("var i = document.createElement('input'); i.id = 'probe'; document.body.appendChild(i); i.focus()")
            self.press(p, "v")
            self.assertEqual(self.mode(p), "edit", "V in a field")
            p.js("document.querySelector('#probe').remove()")
            # an open options menu
            p.js("document.querySelector('[data-options]').click()")
            p.until("!!document.querySelector('.menu')", "the menu opened")
            self.press(p, "v")
            self.assertEqual(self.mode(p), "edit", "V with a menu open")
            p.js("document.querySelector('[data-options]').click()")
            p.until("!document.querySelector('.menu')", "the menu closed")
            # a dialog, with focus on the page behind it
            p.js("var d = document.createElement('dialog'); d.id = 'probe'; d.setAttribute('open', ''); document.body.appendChild(d); document.activeElement.blur()")
            self.press(p, "v")
            self.assertEqual(self.mode(p), "edit", "V with a dialog open")
            p.js("document.querySelector('#probe').remove()")
            # the peek
            p.js(f"clarkPage.openPeek('{item}')")
            p.until("!!clarkPage.peek()", "the peek opened")
            p.js("document.activeElement.blur()")
            self.press(p, "v")
            self.assertEqual(self.mode(p), "edit", "V with a peek open")
            p.js("clarkPage.closePeek()")
            p.until("!clarkPage.peek()", "the peek closed")
            self.press(p, "v")
            p.until("document.querySelector('#report').dataset.mode === 'view'", "with all of them closed, V works again")
            self.assertEqual(self.sent, [])

    def test_only_on_the_dashboard(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            for page_ in ("work", "milestones", "settings"):
                p.js(f"clarkPage.show('{page_}')")
                p.until(f"location.hash.indexOf('#{page_}') === 0", f"{page_} opened")
                self.press(p, "e")
                p.js("clarkPage.show('dashboard')")
                p.until("!!document.querySelector('#report')", "back on the Dashboard")
                self.assertEqual(self.mode(p), "view", f"E on {page_} changed nothing")
            self.press(p, "e")
            p.until("document.querySelector('#report').dataset.mode === 'edit'", "and on the Dashboard it does")


class Sections(Base):
    def test_hide_is_dropped_in_view_dimmed_in_edit_and_undo_shows_it(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            p.menu("ABC-S-002", "hide")
            hidden = "document.querySelector('[data-id=\"ABC-S-002\"]').classList.contains('is-hidden')"
            p.until(hidden, "dimmed in Edit")
            self.assertEqual(p.ids(), IDS, "still drawn in Edit")
            self.assertIn("Left out of the published page", p.js("document.querySelector('[data-id=\"ABC-S-002\"]').textContent"))
            self.assertLess(float(p.js("getComputedStyle(document.querySelector('[data-id=\"ABC-S-002\"] .sec-head')).opacity")), 1, "its words are dimmed")
            self.assertEqual(self.sent[-1][1]["changes"], {"hidden": 1}, "0 or 1, never true")
            self.assertEqual(p.toast(), "Section left out of the published page.")
            p.view()
            self.assertEqual(p.ids(), [i for i in IDS if i != "ABC-S-002"], "gone in View")
            self.assertNotIn("At a glance", p.js("document.querySelector('main').innerText"))
            p.edit()
            p.clear_toast()
            p.menu("ABC-S-003", "hide")
            p.saved()
            p.js("document.querySelector('[data-undo]').click()")
            p.until("!document.querySelector('[data-id=\"ABC-S-003\"]').classList.contains('is-hidden')", "Undo showed it again")
            self.assertEqual(self.sent[-1][0], "undo")
            self.assertEqual(self.sent[-1][1], {"project": "ABC", "apply_id": self.demo.last_step() - 1})
            self.assertTrue(p.js(hidden), "only the step that was undone")
            p.menu("ABC-S-002", "show")
            p.until("!" + hidden, "Show brings it back")
            self.assertEqual(p.toast(), "Section included in the published page.")

    def test_rename_in_place_as_plain_text(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            first = "document.querySelector('.sec-h').textContent"
            p.replace_title("ABC-S-001", "Where we are")
            p.saved()
            self.assertEqual(p.js(first), "Where we are")
            self.assertEqual(self.titles_in_store()[0], "Where we are")
            self.assertEqual(self.sent[-1][1]["changes"], {"title": "Where we are"})
            self.assertEqual(p.toast(), "Title changed.")
            p.js("document.querySelector('[data-undo]').click()")
            p.until(f"{first} === 'Current state' && document.querySelector('.toast-text').textContent === 'Undone.'", "Undo put the title back")
            self.assertEqual(self.titles_in_store()[0], "Current state")
            n = len(self.sent)
            p.replace_title("ABC-S-001", "Never saved", ending="Escape")           # Esc puts it back and sends nothing
            self.assertEqual(p.js(first), "Current state")
            self.assertEqual(len(self.sent), n)
            p.replace_title("ABC-S-001", "")                                       # blank: refused in plain words
            p.until("!!document.querySelector('.toast.problem')", "a message")
            self.assertEqual(p.toast(), "A title can't be blank. The old title was kept. Type a new title to change it.")
            self.assertEqual(p.js(first), "Current state")
            self.assertEqual(len(self.sent), n)
            p.replace_title("ABC-S-001", "x" * 121)                                # 121 characters: refused
            p.until("document.querySelector('.toast-text').textContent.indexOf('121') > 0", "a message")
            self.assertEqual(p.toast(), "A title can be 120 characters at most, and this one has 121. "
                                        "The old title was kept. Shorten it and try again.")
            self.assertEqual(p.js(first), "Current state")
            self.assertEqual(len(self.sent), n, "refused on the page, nothing sent")
            p.clear_toast()
            p.replace_title("ABC-S-001", "y" * 120)                                # 120 is allowed
            p.saved()
            self.assertEqual(self.titles_in_store()[0], "y" * 120)
            p.clear_toast()
            p.replace_title("ABC-S-002", "<b>x</b>", ending="blur")                # markup is text; saved on leaving the field
            p.saved()
            self.assertEqual(p.js("document.querySelectorAll('.sec-h')[1].querySelector('b')"), None, "text, not markup")
            self.assertEqual(self.titles_in_store()[1], "<b>x</b>")
            p.view()
            self.assertEqual(p.js("document.querySelectorAll('.sec-h')[1].textContent"), "<b>x</b>")
            self.assertEqual(p.js("document.querySelectorAll('.sec-h b').length"), 0)

    def test_rename_falls_back_to_a_plain_input_where_plaintext_only_is_missing(self):
        with chrome() as cdp:
            tid = next(t["targetId"] for t in cdp.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
            sid = cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
            cdp.call("Emulation.setDeviceMetricsOverride", {"width": 1400, "height": 900, "deviceScaleFactor": 1, "mobile": False}, sid)
            cdp.call("Page.enable", {}, sid)
            cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source":
                     "Object.defineProperty(HTMLElement.prototype, 'contentEditable', {configurable: true, "
                     "get: function () { return 'inherit'; }, set: function () {}});"}, sid)
            cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{self.s.port}/#dashboard&p=ABC"}, sid)
            p = Pg(self, cdp, sid)
            p.until("!!document.querySelector('.sec')", "drew")
            p.edit()
            self.assertEqual(p.js("document.querySelectorAll('input[data-title]').length"), 11)
            self.assertEqual(p.js("document.querySelectorAll('[contenteditable]').length"), 0)
            p.replace_title("ABC-S-001", "Typed in a field")
            p.saved()
            self.assertEqual(self.titles_in_store()[0], "Typed in a field")
            p.clear_toast()
            p.replace_title("ABC-S-001", "", ending="Enter")
            p.until("!!document.querySelector('.toast.problem')", "blank refused")
            self.assertEqual(p.js("document.querySelector('[data-title]').value"), "Typed in a field")
            p.view()
            self.assertEqual(edit_elements(cdp, p.sid), [])

    def test_move_by_the_menu_ends_disabled_undo_and_a_reload_keeps_the_order(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            for ref, act, other in (("ABC-S-001", "up", "down"), ("ABC-S-011", "down", "up")):
                p.js(f"document.querySelector('[data-id=\"{ref}\"] [data-options]').click()")
                p.until(f"!!document.querySelector('[data-id=\"{ref}\"] .menu')", "menu")
                item = f"document.querySelector('[data-id=\"{ref}\"] [data-act={{}}]')"
                self.assertEqual(p.js(item.format(act) + ".getAttribute('aria-disabled')"), "true")
                self.assertIsNone(p.js(item.format(other) + ".getAttribute('aria-disabled')"))
                p.until("document.activeElement.matches('[role=menuitem]')", "focus went into the menu")
                n = len(self.sent)
                p.js(item.format(act) + ".click()")
                self.assertEqual(len(self.sent), n, "a disabled item sends nothing")
                p.key("Escape", code="Escape", vk=27)
                p.until(f"!document.querySelector('[data-id=\"{ref}\"] .menu')", "Esc closed the menu")
                self.assertTrue(p.js("document.activeElement.matches('[data-options]')"), "focus went back to the button")
            p.menu("ABC-S-003", "up")
            want = ["ABC-S-001", "ABC-S-003", "ABC-S-002"] + IDS[3:]
            p.order_is(want, "Move up")
            self.assertEqual(self.ids_in_store(), want)
            self.assertEqual(self.sent[-1][1], {"project": "ABC", "kind": "report_sections", "op": "move", "id": "ABC-S-003",
                                                "before": "ABC-S-002", "place": "menu"})
            p.menu("ABC-S-001", "down")
            want = ["ABC-S-003", "ABC-S-001", "ABC-S-002"] + IDS[3:]
            p.order_is(want, "Move down")
            p.menu("ABC-S-011", "up")
            p.order_is(want[:-2] + ["ABC-S-011", "ABC-S-010"], "the last moves up")
            p.js("document.querySelector('[data-undo]').click()")
            p.order_is(want, "Undo of that move")
            p.reload()
            p.order_is(want, "a reload keeps the order")
            self.assertEqual(self.ids_in_store(), want)

    def test_move_by_alt_arrows_on_the_handle_keeps_focus_there(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            on_handle = "document.activeElement.matches('[data-drag]') && document.activeElement.closest('.sec').dataset.id === 'ABC-S-004'"
            p.js("document.querySelector('[data-id=\"ABC-S-004\"] [data-drag]').focus()")
            p.key("ArrowUp", ALT, code="ArrowUp", vk=38)
            p.order_is(IDS[:2] + ["ABC-S-004", "ABC-S-003"] + IDS[4:], "Alt+Up")
            self.assertTrue(wait(lambda: p.js(on_handle), 5), "focus stays on the handle")
            self.assertEqual(self.sent[-1][1]["place"], "report")
            p.key("ArrowDown", ALT, code="ArrowDown", vk=40)
            p.order_is(IDS[:3] + ["ABC-S-004"] + IDS[3:3] + IDS[4:], "Alt+Down")
            self.assertTrue(wait(lambda: p.js(on_handle), 5))
            p.key("ArrowDown", ALT, code="ArrowDown", vk=40)
            p.order_is(IDS[:3] + ["ABC-S-005", "ABC-S-004"] + IDS[5:], "Alt+Down again")
            self.assertTrue(wait(lambda: p.js(on_handle), 5))
            n = len(self.sent)
            p.key("ArrowDown", 0, code="ArrowDown", vk=40)
            self.assertEqual(len(self.sent), n, "an arrow without Alt does nothing")
            p.js("document.querySelector('[data-id=\"ABC-S-004\"] [data-drag]').focus()")
            p.js("document.querySelector('[data-id=\"ABC-S-001\"] [data-drag]').focus()")      # the first, and the last
            p.key("ArrowUp", ALT, code="ArrowUp", vk=38)
            p.until("!!document.querySelector('.toast.note')", "a note at the top")
            self.assertEqual(p.toast(), "This section is already first.")
            self.assertEqual(len(self.sent), n)
            self.assertEqual(self.ids_in_store()[0], "ABC-S-001")

    def test_move_by_dragging_the_handle(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            hx, hy, _ = p.box('[data-id="ABC-S-001"] [data-drag]')
            _, _, bottom = p.box('[data-id="ABC-S-003"]')
            ty = bottom - 3                                  # in the lower half of the third section: it lands before the fourth
            p.mouse("mousePressed", hx, hy, 1)
            for step in range(1, 9):
                p.mouse("mouseMoved", hx, hy + (ty - hy) * step / 8, 1)
            p.until("!!document.querySelector('.sec.drop-before')", "a drop line while dragging")
            self.assertEqual(p.js("document.querySelector('.sec.drop-before').dataset.id"), "ABC-S-004")
            p.mouse("mouseReleased", hx, ty, 0)
            want = ["ABC-S-002", "ABC-S-003", "ABC-S-001"] + IDS[3:]
            p.order_is(want, "dragged")
            self.assertEqual(self.ids_in_store(), want)
            self.assertEqual(self.sent[-1][1], {"project": "ABC", "kind": "report_sections", "op": "move", "id": "ABC-S-001",
                                                "before": "ABC-S-004", "place": "report"})
            self.assertEqual(p.js("document.querySelector('.drop-before')"), None, "the drop line goes")
            self.assertTrue(wait(lambda: p.js("document.activeElement.matches('[data-drag]') && "
                                              "document.activeElement.closest('.sec').dataset.id === 'ABC-S-001'"), 5),
                            "the handle keeps focus")
            n = len(self.sent)                               # a small movement is a click, not a move
            hx, hy, _ = p.box('[data-id="ABC-S-001"] [data-drag]')
            p.mouse("mousePressed", hx, hy, 1)
            p.mouse("mouseMoved", hx, hy + 2, 1)
            p.mouse("mouseReleased", hx, hy + 2, 0)
            self.assertEqual(len(self.sent), n)
            p.js("document.querySelector('[data-undo]').click()")
            p.order_is(IDS, "Undo of the drag")

    def test_drag_onto_half_of_a_section_that_is_not_text_and_undo(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.tall(cdp)
            p.edit()
            r = p.rect("ABC-S-002")                          # At a glance, on its own: any type can be paired
            mid_y = (r["top"] + r["bottom"]) / 2
            p.drag("ABC-S-008", r["left"] + (r["right"] - r["left"]) * 0.75, mid_y, release=False)
            p.until("!!document.querySelector('.sec.drop-right')", "the right half is outlined while dragging")
            self.assertEqual(p.js("document.querySelector('.sec.drop-right').dataset.id"), "ABC-S-002")
            self.assertIsNone(p.js("document.querySelector('.drop-left')"))
            p.mouse("mouseReleased", r["left"] + (r["right"] - r["left"]) * 0.75, mid_y, 0)
            p.order_is(IDS[:2] + ["ABC-S-008"] + IDS[2:7] + IDS[8:], "dropped beside")
            self.assertEqual(self.sent[-1][1], {"project": "ABC", "kind": "report_sections", "op": "move", "id": "ABC-S-008",
                                                "before": "ABC-S-003", "flags": {"ABC-S-002": 1}, "place": "report"})
            self.assertEqual(p.toast(), "Moved Risks and issues beside At a glance, on the right.")
            p.until("document.querySelector('[data-id=\"ABC-S-002\"]').classList.contains('slot-left') && "
                    "document.querySelector('[data-id=\"ABC-S-008\"]').classList.contains('slot-right')", "two columns")
            self.assertIsNone(p.js("document.querySelector('.drop-right')"), "the outline goes")
            n = len(self.sent)
            r8 = p.rect("ABC-S-008")                         # dropped on itself: nothing is sent and nothing is said
            p.drag("ABC-S-008", (r8["left"] + r8["right"]) / 2, (r8["top"] + r8["bottom"]) / 2)
            self.assertEqual(len(self.sent), n)
            p.js("document.querySelector('[data-undo]').click()")
            p.order_is(IDS, "one Undo puts the order back")
            self.assertEqual(self.beside_flags()["ABC-S-002"], 0)
            r = p.rect("ABC-S-002")                          # again, then a reload: the layout is in the store
            p.drag("ABC-S-008", r["left"] + (r["right"] - r["left"]) * 0.25, (r["top"] + r["bottom"]) / 2)
            p.until("document.querySelector('[data-id=\"ABC-S-008\"]').classList.contains('slot-left')", "beside, on the left")
            p.reload()
            self.assertTrue(p.js("document.querySelector('[data-id=\"ABC-S-008\"]').classList.contains('slot-left')"))
            self.assertEqual(self.ids_in_store()[1:3], ["ABC-S-008", "ABC-S-002"])

    def test_one_undo_puts_a_dragged_half_back(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.tall(cdp)
            p.edit()
            hx, hy, _ = p.box('[data-id="ABC-S-010"]')
            r = p.rect("ABC-S-010")
            p.drag("ABC-S-006", hx, r["bottom"] - 2)         # the bottom edge of Decisions: a row of its own after it
            p.order_is([i for i in IDS if i != "ABC-S-006"][:9] + ["ABC-S-006", "ABC-S-011"], "left the pair")
            self.assertEqual(self.sent[-1][1]["flags"], {"ABC-S-006": 0})
            self.assertEqual(self.sent[-1][1]["before"], "ABC-S-011")
            self.assertEqual(sum(self.beside_flags().values()), 0, "the partner is on its own, full width")
            p.until("document.querySelector('[data-id=\"ABC-S-007\"]').classList.contains('slot-full')", "partner full width")
            self.assertEqual(self.sent[-1][0], "change")
            n = len(self.sent)
            p.js("document.querySelector('[data-undo]').click()")
            p.order_is(IDS, "one Undo puts the order back")
            self.assertEqual(self.beside_flags()["ABC-S-006"], 1, "and the pair")
            self.assertEqual(len([w for w, _ in self.sent[n:] if w == "undo"]), 1)

    def test_esc_cancels_a_drag_and_releasing_drops_nothing(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.tall(cdp)
            p.edit()
            r = p.rect("ABC-S-002")
            n = len(self.sent)
            p.drag("ABC-S-008", r["left"] + (r["right"] - r["left"]) * 0.75, (r["top"] + r["bottom"]) / 2, release=False)
            p.until("!!document.querySelector('.sec.drop-right')", "the half is outlined while dragging")
            p.key("Escape", code="Escape", vk=27)
            p.until("!document.querySelector('.sec.drop-right')", "Esc clears the indicator")
            x, y = r["left"] + (r["right"] - r["left"]) * 0.75, (r["top"] + r["bottom"]) / 2
            p.mouse("mouseMoved", x + 1, y + 1, 1)                      # 1 px of jitter after Esc: still cancelled
            p.mouse("mouseMoved", x, y, 1)
            self.assertFalse(p.js("!!document.querySelector('.sec.drop-right, .sec.drop-left, .sec.drop-before, .secs.drop-end')"), "no indicator comes back")
            p.mouse("mouseReleased", x, y, 0)
            self.assertEqual(len(self.sent), n, "nothing was sent")
            p.order_is(IDS, "the order is as it was")
            p.drag("ABC-S-008", r["left"] + (r["right"] - r["left"]) * 0.75, (r["top"] + r["bottom"]) / 2)      # the next drag works again
            p.order_is(IDS[:2] + ["ABC-S-008"] + IDS[2:7] + IDS[8:], "a later drag still drops")

    def test_one_undo_puts_back_a_drop_where_a_half_is_hidden(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.tall(cdp)
            p.edit()
            p.menu("ABC-S-007", "hide")
            p.until("!!document.querySelector('[data-id=\"ABC-S-007\"].is-hidden')", "the partner is hidden")
            hx, hy, _ = p.box('[data-id="ABC-S-010"]')
            r = p.rect("ABC-S-010")
            p.drag("ABC-S-006", hx, r["bottom"] - 2)
            p.order_is([i for i in IDS if i != "ABC-S-006"][:9] + ["ABC-S-006", "ABC-S-011"], "left the pair")
            self.assertEqual(self.sent[-1][1]["flags"], {"ABC-S-006": 0})
            p.saved()
            p.js("document.querySelector('[data-undo]').click()")
            p.order_is(IDS, "Undo of the drop")
            self.assertEqual(self.beside_flags()["ABC-S-006"], 1, "the pair is back")
            hidden = {r["id"]: r["hidden"] for r in self.store.read("report_sections", "ABC")}
            self.assertEqual(hidden["ABC-S-007"], 1, "and the partner is still hidden")

    def test_a_drop_on_the_middle_of_a_pair_is_a_line_and_a_small_move_sends_nothing(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.tall(cdp)
            p.edit()
            r = p.rect("ABC-S-006")
            p.drag("ABC-S-001", (r["left"] + r["right"]) / 2 - 20, r["top"] + 3, release=False)       # the top of the pair
            p.until("document.querySelectorAll('.sec.drop-before').length === 2", "a line across the whole pair")
            self.assertEqual(p.js("[...document.querySelectorAll('.sec.drop-before')].map(e => e.dataset.id)"), ["ABC-S-006", "ABC-S-007"])
            p.mouse("mouseReleased", r["left"], r["top"] + 3, 0)
            p.order_is(IDS[1:5] + ["ABC-S-001"] + IDS[5:], "above the pair")
            self.assertNotIn("flags", self.sent[-1][1])
            n = len(self.sent)
            hx, hy, _ = p.box('[data-id="ABC-S-001"] [data-drag]')
            p.drag("ABC-S-001", hx, hy + 2)                  # under 4 px: a click
            self.assertEqual(len(self.sent), n)
            self.assertIsNone(p.js("document.querySelector('.drop-before')"))

    def test_the_menu_works_for_every_type_and_says_why_it_cannot(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            p.menu("ABC-S-002", "beside")                    # At a glance beside Use case summary: neither is text
            p.until("document.querySelector('[data-id=\"ABC-S-002\"]').classList.contains('slot-left')", "beside")
            self.assertEqual(self.sent[-1][1]["flags"], {"ABC-S-002": 1})
            self.assertEqual(p.toast(), "Moved At a glance beside Use case summary, on the left.")
            self.assertTrue(wait(lambda: p.js("document.activeElement.matches('[data-options]')"), 5), "focus returns to the menu button")
            p.menu("ABC-S-003", "full")                      # either half is offered Full width
            p.until("document.querySelector('[data-id=\"ABC-S-002\"]').classList.contains('slot-full')", "full width from the second half")
            self.assertEqual(self.sent[-1][1]["flags"], {"ABC-S-002": 0})
            n = len(self.sent)
            p.js("document.querySelector('[data-id=\"ABC-S-005\"] [data-options]').click()")      # the next row is a pair
            p.until("!!document.querySelector('[data-id=\"ABC-S-005\"] .menu')", "menu")
            item = "document.querySelector('[data-id=\"ABC-S-005\"] [data-act=beside]')"
            self.assertEqual(p.js(item + ".getAttribute('aria-disabled')"), "true")
            self.assertEqual(p.js(item + ".hasAttribute('title')"), False, "the reason is on screen once, not repeated in a tooltip")
            self.assertEqual(p.js("document.getElementById(" + item + ".getAttribute('aria-describedby')).textContent"),
                             "The next row already has two sections. Move one of them first, or move this section between rows.")
            p.js(item + ".click()")
            self.assertEqual(len(self.sent), n)

    def test_keyboard_moves_go_by_rows_with_words_and_a_half_steps_out_of_its_pair(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            on = lambda ref: p.js(f"document.activeElement.matches('[data-drag]') && document.activeElement.closest('.sec').dataset.id === '{ref}'")
            p.js("document.querySelector('[data-id=\"ABC-S-005\"] [data-drag]').focus()")
            p.key("ArrowDown", ALT, code="ArrowDown", vk=40)           # a section on its own passes the whole pair
            p.order_is(IDS[:4] + ["ABC-S-006", "ABC-S-007", "ABC-S-005"] + IDS[7:], "past the pair")
            self.assertEqual(p.toast(), "Moved Summary down.")
            self.assertTrue(wait(lambda: on("ABC-S-005"), 5))
            p.js("document.querySelector('[data-undo]').click()")
            p.order_is(IDS, "undone")
            p.js("document.querySelector('[data-id=\"ABC-S-007\"] [data-drag]').focus()")
            p.key("ArrowUp", ALT, code="ArrowUp", vk=38)               # the second half goes just above the pair; the first is alone
            p.until("document.querySelector('[data-id=\"ABC-S-006\"]').classList.contains('slot-full')", "stepped out")
            self.assertEqual(self.sent[-1][1]["flags"], {"ABC-S-006": 0})
            self.assertEqual(p.toast(), "Moved Next week up.")
            self.assertTrue(wait(lambda: on("ABC-S-007"), 5))
            p.js("document.querySelector('[data-id=\"ABC-S-011\"] [data-drag]').focus()")
            n = len(self.sent)
            p.key("ArrowDown", ALT, code="ArrowDown", vk=40)
            p.until("!!document.querySelector('.toast.note')", "a note")
            self.assertEqual(p.toast(), "This section is already last.")
            self.assertEqual(len(self.sent), n)

    def test_a_pair_stacks_at_900_and_a_hidden_half_leaves_the_other_full_width(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            tops = "[document.querySelector('[data-id=\"ABC-S-006\"]').getBoundingClientRect().top, document.querySelector('[data-id=\"ABC-S-007\"]').getBoundingClientRect().top]"
            cdp.call("Emulation.setDeviceMetricsOverride", {"width": 900, "height": 900, "deviceScaleFactor": 1, "mobile": False}, p.sid)
            t = p.js(tops)
            self.assertLess(t[0], t[1], "stacked at 900 px")
            cdp.call("Emulation.setDeviceMetricsOverride", {"width": 1400, "height": 900, "deviceScaleFactor": 1, "mobile": False}, p.sid)
            t = p.js(tops)
            self.assertAlmostEqual(t[0], t[1], delta=2)
            p.edit()
            p.menu("ABC-S-007", "hide")
            p.until("!!document.querySelector('[data-id=\"ABC-S-007\"].is-hidden')", "hidden")
            p.view()
            self.assertIsNone(p.js("document.querySelector('[data-id=\"ABC-S-007\"]')"))
            for ref in ("ABC-S-006", "ABC-S-008"):
                self.assertTrue(p.js(f"document.querySelector('[data-id=\"{ref}\"]').classList.contains('slot-full')"), ref)

    def test_delete_a_text_section_only_and_undo_brings_it_back(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            for ref in ("ABC-S-001", "ABC-S-002", "ABC-S-004", "ABC-S-008"):
                p.js(f"document.querySelector('[data-id=\"{ref}\"] [data-options]').click()")
                p.until(f"!!document.querySelector('[data-id=\"{ref}\"] .menu')", "menu")
                self.assertIsNone(p.js(f"document.querySelector('[data-id=\"{ref}\"] [data-act=delete]')"), f"{ref} is not a text section")
                p.key("Escape", code="Escape", vk=27)
            p.menu("ABC-S-005", "delete")
            p.order_is([i for i in IDS if i != "ABC-S-005"], "deleted")
            self.assertNotIn("ABC-S-005", self.ids_in_store())
            self.assertEqual(p.toast(), "Section deleted.")
            self.assertTrue(wait(lambda: p.js("document.activeElement.matches('[data-drag]')"), 5), "focus goes to a neighbour's handle")
            p.js("document.querySelector('[data-undo]').click()")
            p.order_is(IDS, "Undo brought it back in its place")
            self.assertEqual(self.titles_in_store(), TITLES)

    def test_beside_puts_two_sections_in_one_row_and_full_width_undoes_it(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            row = ("(function(){var a=document.querySelector('[data-id=\"ABC-S-006\"]').getBoundingClientRect(),"
                   "b=document.querySelector('[data-id=\"ABC-S-007\"]').getBoundingClientRect();"
                   "return [Math.abs(a.top-b.top)<2, a.right<=b.left+1];})()")
            self.assertEqual(p.js(row), [True, True], "This week sits beside Next week to start with")
            p.edit()
            p.menu("ABC-S-006", "full")
            p.until("!document.querySelector('[data-id=\"ABC-S-006\"]').classList.contains('slot-left')", "full width")
            self.assertFalse(p.js(row)[0])
            self.assertEqual(self.sent[-1][1], {"project": "ABC", "kind": "report_sections", "op": "move", "id": "ABC-S-006",
                                                "before": "ABC-S-007", "flags": {"ABC-S-006": 0}, "place": "menu"})
            self.assertEqual(p.toast(), "This week is now full width.")
            p.menu("ABC-S-006", "beside")
            p.until("document.querySelector('[data-id=\"ABC-S-006\"]').classList.contains('slot-left')", "beside again")
            self.assertEqual(self.sent[-1][1]["flags"], {"ABC-S-006": 1})

    def test_the_undo_says_so_when_a_later_change_was_left_as_it_is(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            p.replace_title("ABC-S-001", "First name")
            p.until("document.querySelector('.sec-h').textContent === 'First name'", "renamed")
            p.until("!!document.querySelector('[data-undo]')", "toast")
            with self.store.step("dashboard", USER) as st:                       # another change to the same title, made elsewhere
                st.update("report_sections", "ABC-S-001", {"title": "Changed elsewhere"})
            p.js("document.querySelector('[data-undo]').click()")
            p.until("document.querySelector('.toast-text').textContent.indexOf('left as it is') > 0", "the toast names what was left")
            self.assertIn("“Changed elsewhere” was changed later (step", p.toast())
            self.assertEqual(p.js("document.querySelector('.sec-h').textContent"), "Changed elsewhere")


class Failures(Base):
    """Every failure says plain words and nothing the server said; nothing is drawn that was not saved."""
    STALE = "This page is out of date: clark was restarted after you opened it. Reload the page and try again."

    def shown_problem(self, p, words):
        p.until(f"!!document.querySelector('.toast.problem') && document.querySelector('.toast-text').textContent === {json.dumps(words)}",
                f"the plain words: {words}")
        self.assertEqual(p.js("document.querySelector('.toast.problem').getAttribute('role')"), "alert")
        self.assertNotRegex(words, r"(?i:Error|Exception|Traceback|JSON|Not allowed|Bad request|sqlite)|\bClark\b|!")
        self.assertNotIn(SECRET, p.js("document.body.innerHTML"))

    def test_a_stale_token(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            p.js("document.getElementById('clark-boot').textContent = JSON.stringify({token: 'from an earlier run'})")
            p.menu("ABC-S-002", "up")
            self.shown_problem(p, self.STALE)
            self.assertEqual(p.ids(), IDS, "nothing was redrawn")
            self.assertEqual(self.sent, [], "the server refused before the seam")
            self.assertEqual(self.ids_in_store(), IDS)

    def test_a_400_never_shows_the_servers_words_but_known_ones_get_clark_words(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            self.failure = lambda req: (400, {"ok": False, "message": SECRET, "code": "refused"})
            p.menu("ABC-S-002", "up")
            self.shown_problem(p, "That change could not be made, and nothing was changed. Reload the page and try again.")
            self.assertEqual(p.ids(), IDS)
            self.failure = lambda req: (400, {"ok": False, "message": "Your page is out of date. Reload it, then try again.", "code": "refused"})
            p.menu("ABC-S-002", "up")
            self.shown_problem(p, "The report has changed since you opened it, and nothing was changed. Reload the page and try again.")

    def test_a_500_and_a_fault(self):
        words = "A problem came up saving that, and nothing was changed. Try again. If it happens again, restart clark."
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            self.failure = lambda req: RuntimeError(SECRET)                        # the route faults: the server answers 500
            p.menu("ABC-S-002", "up")
            self.shown_problem(p, words)
            self.failure = lambda req: (500, {"ok": False, "message": SECRET})
            p.js("document.querySelector('[data-dismiss]').click()")
            p.menu("ABC-S-003", "up")
            self.shown_problem(p, words)
            self.assertEqual(p.ids(), IDS)
            self.failure = None
            p.menu("ABC-S-003", "up")                                              # and it works once the fault is over
            p.order_is(["ABC-S-001", "ABC-S-003", "ABC-S-002"] + IDS[3:])
            self.assertIsNone(p.js("document.querySelector('.toast.problem')"), "the next change replaced the message")

    def test_busy_and_already_undone(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            self.failure = lambda req: (503, {"ok": False, "message": SECRET})
            p.menu("ABC-S-002", "up")
            self.shown_problem(p, "That could not be saved just now, and nothing was changed. Wait a moment and try again. "
                                  "If it keeps happening, restart clark.")
            self.failure = lambda req: (409, {"ok": False, "message": "That step has been undone already."})
            p.js("document.querySelector('[data-dismiss]').click()")
            p.menu("ABC-S-002", "up")
            self.shown_problem(p, "That change has been undone already. Reload the page to see how the report is now.")

    def test_no_answer_at_all(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            self.s.close()                                                        # clark's window was closed
            self.addCleanup(lambda: None)
            p.menu("ABC-S-002", "up")
            self.shown_problem(p, "Nothing is running behind this page: clark stops by itself after a while with nothing open. Start it again from clark.command.")
            self.assertEqual(p.ids(), IDS)

    def test_changes_go_out_one_at_a_time(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            gate = {"in": 0, "max": 0}

            def slow(req):
                gate["in"] += 1
                gate["max"] = max(gate["max"], gate["in"])
                time.sleep(0.3)
                try:
                    return self.real_change(req)
                finally:
                    gate["in"] -= 1
            self.s.httpd.change = slow
            for ref in ("ABC-S-002", "ABC-S-003", "ABC-S-004"):                 # made faster than the 0.3 s each one takes
                p.menu(ref, "hide")
            p.until("document.querySelectorAll('.is-hidden').length === 3", "all three were made", 20)
            self.assertEqual(gate["max"], 1, "never two at once")


class Gutter(Base):
    """#101: one quiet control in each section's left margin: a grip with a + under it, and its menu."""

    CTL = "document.querySelector('[data-id=\"%s\"] .sec-ctl')"
    MENU_TEXTS = "[...document.querySelectorAll('[data-id=\"%s\"] .menu-item')].map(e => e.textContent)"
    # A capture listener on window sees the request before any dialog on the document; when it is "not claimed" it stops the event there,
    # so the fallback toast is tested whether or not an Add a section dialog is built in (#96).
    LISTEN = ("window.asked = []; window.openers = []; window.addEventListener('clark:add-section', e => { window.asked.push(e.detail.after); "
              "var o = e.detail.opener; window.openers.push(o && o.hasAttribute('data-add') ? 'plus' : (o && o.hasAttribute('data-drag') ? 'grip' : String(o))); "
              "window.cancelable = e.cancelable; if (window.claim) e.preventDefault(); else e.stopPropagation(); }, true);")

    def opacity(self, p, ref):
        return p.js(f"parseFloat(getComputedStyle({self.CTL % ref}).opacity)")

    def open_menu(self, p, ref):
        p.js(f"document.querySelector('[data-id=\"{ref}\"] [data-options]').click()")
        p.until(f"!!document.querySelector('[data-id=\"{ref}\"] .menu')", "the menu opened")
        p.until("document.activeElement.matches('[role=menuitem]')", "focus went into the menu")

    def test_one_control_in_the_margin_and_the_old_add_lines_are_gone(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            self.assertEqual(p.js("document.querySelectorAll('.sec-ctl').length"), 11, "one control for each section")
            self.assertEqual(p.js("document.querySelectorAll('.sec-ctl > [data-drag]').length"), 11)
            self.assertEqual(p.js("document.querySelectorAll('.sec-ctl > [data-add]').length"), 11, "a + under each grip")
            self.assertEqual(p.js("document.querySelectorAll('.sec-add, .opts, .opts-btn').length"), 0,
                             "no Add line between sections and no separate options button")
            self.assertNotIn("Add a text section", p.js("document.querySelector('main').textContent"))
            self.assertNotIn("Add a text section", p.js("document.documentElement.outerHTML"))
            for ref in ("ABC-S-001", "ABC-S-005"):
                self.open_menu(p, ref)
                self.assertFalse([t for t in p.js(self.MENU_TEXTS % ref) if "text section" in t.lower()], "no text-section entry")
                p.key("Escape", code="Escape", vk=27)
            # the grip and the + are in the margin, left of the section's own box
            for ref in ("ABC-S-001", "ABC-S-006"):
                box = p.js(f"(function(){{var s=document.querySelector('[data-id=\"{ref}\"]').getBoundingClientRect(),"
                           f"c=document.querySelector('[data-id=\"{ref}\"] .sec-ctl').getBoundingClientRect();"
                           "return [c.right <= s.left, c.top >= s.top, c.bottom <= s.bottom];})()")
                self.assertEqual(box, [True, True, True], ref)

    def test_faint_at_rest_clear_on_hover_and_focus_and_while_open(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            p.js("document.activeElement.blur()")
            p.mouse("mouseMoved", 5, 5)
            p.until("Math.abs(getComputedStyle(%s).opacity - 0.3) < 0.01" % (self.CTL % "ABC-S-004"), "faint at rest")
            self.assertAlmostEqual(self.opacity(p, "ABC-S-004"), 0.3, places=2)
            x, y, _ = p.box('[data-id="ABC-S-004"] .sec-head')
            p.mouse("mouseMoved", x, y)
            p.until("parseFloat(getComputedStyle(%s).opacity) === 1" % (self.CTL % "ABC-S-004"), "clear on hover")
            self.assertAlmostEqual(self.opacity(p, "ABC-S-003"), 0.3, places=2, msg="only the section being pointed at")
            p.mouse("mouseMoved", 5, 5)
            p.until("parseFloat(getComputedStyle(%s).opacity) < 1" % (self.CTL % "ABC-S-004"), "faint again")
            p.js("document.querySelector('[data-id=\"ABC-S-004\"] [data-drag]').focus()")
            p.until("parseFloat(getComputedStyle(%s).opacity) === 1" % (self.CTL % "ABC-S-004"), "clear on focus")
            p.js("document.activeElement.blur()")
            p.until("parseFloat(getComputedStyle(%s).opacity) < 1" % (self.CTL % "ABC-S-004"), "faint once focus has gone")
            self.open_menu(p, "ABC-S-004")
            p.mouse("mouseMoved", 5, 5)
            p.until("parseFloat(getComputedStyle(%s).opacity) === 1" % (self.CTL % "ABC-S-004"), "clear while the menu is open")

    def test_rest_strength_follows_the_theme_dark_clearer_than_light(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            p.js("document.activeElement.blur()")
            p.mouse("mouseMoved", 5, 5)
            p.until("Math.abs(getComputedStyle(%s).opacity - 0.3) < 0.01" % (self.CTL % "ABC-S-004"), "light: .3")
            p.js("document.documentElement.dataset.theme = 'dark'")
            p.until("Math.abs(getComputedStyle(%s).opacity - 0.75) < 0.01" % (self.CTL % "ABC-S-004"), "dark: .75")
            p.js("document.documentElement.dataset.theme = 'auto'")
            cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": "dark"}]}, p.sid)
            p.until("Math.abs(getComputedStyle(%s).opacity - 0.75) < 0.01" % (self.CTL % "ABC-S-004"), "following a dark computer: .75")
            cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": "light"}]}, p.sid)
            p.until("Math.abs(getComputedStyle(%s).opacity - 0.3) < 0.01" % (self.CTL % "ABC-S-004"), "following a light computer: .3")

    def test_a_hidden_section_dims_its_words_not_its_control(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            p.menu("ABC-S-002", "hide")
            p.saved()
            p.js("document.activeElement.blur()")
            p.mouse("mouseMoved", 5, 5)
            p.until("document.querySelector('[data-id=\"ABC-S-002\"]').classList.contains('is-hidden')", "hidden")
            p.until("Math.abs(getComputedStyle(%s).opacity - 0.3) < 0.01" % (self.CTL % "ABC-S-002"), "the control is at the same rest strength as any other")

    def test_the_fade_stops_for_reduced_motion_and_the_rings_and_menu_fit(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            ctl = self.CTL % "ABC-S-004"
            # a computer set to reduce motion (a macOS runner is) would report 0s here, so ask for the normal case
            cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "no-preference"}]}, p.sid)
            p.until(f"getComputedStyle({ctl}).transitionDuration !== '0s'", "it fades normally")
            cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]}, p.sid)
            p.until(f"getComputedStyle({ctl}).transitionDuration === '0s'", "no fade when the person asked for less motion")
            cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "no-preference"}]}, p.sid)
            p.js("document.querySelector('[data-id=\"ABC-S-004\"] [data-drag]').focus()")
            # the rings of the grip and the + sit inside each, so they do not overlap
            p.key("Tab", code="Tab", vk=9)
            for sel in ("[data-drag]", "[data-add]"):
                p.js("document.querySelector('[data-id=\"ABC-S-004\"] %s').focus()" % sel)
                self.assertEqual(p.js("getComputedStyle(document.activeElement).outlineOffset"), "-2px", sel)
            cdp.call("Emulation.setDeviceMetricsOverride", {"width": 900, "height": 900, "deviceScaleFactor": 1, "mobile": False}, p.sid)
            self.open_menu(p, "ABC-S-004")
            self.assertTrue(p.js("(function(){var r=document.querySelector('.menu').getBoundingClientRect();return r.right <= innerWidth && document.documentElement.scrollWidth <= innerWidth;})()"),
                            "the menu stays inside the window")
            self.assertEqual(p.js("getComputedStyle(document.querySelector('.menu')).maxWidth"), "860px", "and is capped to the window's width less 40 px")

    def test_a_section_left_out_shows_an_eye_off_mark_with_a_label(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            self.assertEqual(p.js("document.querySelectorAll('.sec-ctl .eye').length"), 0, "none on a section that is on the page")
            p.menu("ABC-S-002", "hide")
            p.saved()
            p.until("!!document.querySelector('[data-id=\"ABC-S-002\"] .sec-ctl .eye')", "the mark appeared")
            eye = "document.querySelector('[data-id=\"ABC-S-002\"] .sec-ctl .eye')"
            self.assertEqual(p.js(f"{eye}.getAttribute('aria-label')"), "Left out of the published page")
            self.assertEqual(p.js(f"{eye}.getAttribute('role')"), "img")
            self.assertEqual(p.js("document.querySelectorAll('.sec-ctl .eye').length"), 1, "only on that section")
            self.assertTrue(p.js(f"(function(){{var e={eye}.getBoundingClientRect(),c=document.querySelector('[data-id=\"ABC-S-002\"] [data-add]').getBoundingClientRect();return e.top >= c.bottom - 1 && Math.abs(e.left - c.left) < 2;}})()"), "under the +")
            p.js("document.querySelector('[data-undo]').click()")
            p.until(f"!{eye}", "Undo took the mark away")

    def test_an_unavailable_item_can_be_reached_and_says_why_on_screen(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            n = len(self.sent)
            self.open_menu(p, "ABC-S-001")           # the first section: Move up cannot apply
            item = "document.querySelector('[data-id=\"ABC-S-001\"] [data-act=up]')"
            self.assertEqual(p.js(f"{item}.getAttribute('aria-disabled')"), "true")
            p.key("ArrowDown", code="ArrowDown", vk=40)
            self.assertEqual(p.js("document.activeElement.dataset.act"), "up", "the arrow keys stop on it")
            why = p.js(f"document.getElementById({item}.getAttribute('aria-describedby')).textContent")
            self.assertTrue(why and why.strip(), "its reason is in the menu, not only in a tooltip")
            self.assertTrue(p.js(f"(function(){{var r=document.getElementById({item}.getAttribute('aria-describedby')).getBoundingClientRect();return r.height > 0 && r.width > 0;}})()"), "and it can be seen")
            p.cdp.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"}, p.sid)
            p.cdp.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13}, p.sid)
            p.until("!!document.querySelector('.toast.note')", "a note appeared")
            self.assertEqual(p.toast(), why.strip(), "Enter says it again")
            self.assertEqual(len(self.sent), n, "and changes nothing")

    def test_the_control_never_moves_or_narrows_a_section(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            rects = lambda: p.js("Object.fromEntries([...document.querySelectorAll('.secs > .sec')].map(e => "
                                 "[e.dataset.id, [e.getBoundingClientRect().left, e.getBoundingClientRect().width]]))")
            p.edit()
            # (This week and Next week are already a pair in the demo report.)
            for w in (1400, 900):
                cdp.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": 900, "deviceScaleFactor": 1, "mobile": False}, p.sid)
                p.view()
                in_view = rects()
                p.edit()
                self.assertEqual(rects(), in_view, f"the same left edge and width in View and Edit at {w}")
            cdp.call("Emulation.setDeviceMetricsOverride", {"width": 1400, "height": 900, "deviceScaleFactor": 1, "mobile": False}, p.sid)
            # the right half: its control sits in the gap between the two columns and covers no content
            gap = p.js("(function(){var l=document.querySelector('[data-id=\"ABC-S-006\"]').getBoundingClientRect(),"
                       "r=document.querySelector('[data-id=\"ABC-S-007\"]').getBoundingClientRect(),"
                       "c=document.querySelector('[data-id=\"ABC-S-007\"] .sec-ctl').getBoundingClientRect();"
                       "return [c.left >= l.right, c.right <= r.left];})()")
            self.assertEqual(gap, [True, True], "in the gap")
            # opening the menu or hovering moves nothing either
            before = rects()
            self.open_menu(p, "ABC-S-007")
            self.assertEqual(rects(), before, "an open menu moves nothing")

    MEASURE = ("(function(){var out=[];document.querySelectorAll('.secs > .sec').forEach(function(s){var c=s.querySelector('.sec-ctl').getBoundingClientRect(),"
               "worst=1e9,sb=s.getBoundingClientRect();[...s.children].forEach(function(k){if(k.classList.contains('sec-ctl'))return;"
               "var r=k.getBoundingClientRect();if(r.width&&r.height)worst=Math.min(worst,r.left);});"
               "var h=s.querySelector('.sec-title, .sec-h');out.push([s.dataset.id,Math.round(c.right),Math.round(h.getBoundingClientRect().left),Math.round(worst),Math.round(c.left),Math.round(sb.left)]);});return out;})()")

    def test_at_900_the_control_has_room_inside_the_card_and_covers_no_heading_or_content(self):
        """#139: at 900 px in Edit the control sits in the section's own padding, so it is at or before the left edge of the
        heading (or the Title field) and of everything else in the section; 1400 px keeps it in the margin."""
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            for scheme in ("light", "dark"):
                cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]}, p.sid)
                for w in (900, 1400):
                    cdp.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": 900, "deviceScaleFactor": 1, "mobile": False}, p.sid)
                    p.until(f"window.innerWidth === {w}", "resized")
                    rows = p.js(self.MEASURE)
                    self.assertEqual(len(rows), 11)
                    for ref, ctl_right, head_left, content_left, ctl_left, sec_left in rows:
                        self.assertLessEqual(ctl_right, head_left, f"{ref} at {w} in {scheme}: the control ends before the heading")
                        self.assertLessEqual(ctl_right, content_left, f"{ref} at {w} in {scheme}: and before all content")
                        if w == 900:
                            self.assertGreaterEqual(ctl_left, sec_left, f"{ref}: inside the card at 900")
                        else:
                            self.assertLessEqual(ctl_right, sec_left, f"{ref}: in the margin at 1400")
                    self.assertLessEqual(p.js("document.documentElement.scrollWidth"), w, f"no sideways scroll at {w} in {scheme}")
            cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": "light"}]}, p.sid)
            # a left-out section too
            cdp.call("Emulation.setDeviceMetricsOverride", {"width": 900, "height": 900, "deviceScaleFactor": 1, "mobile": False}, p.sid)
            p.js("document.querySelector('[data-id=\"ABC-S-002\"]').classList.add('is-hidden')")
            self.assertLessEqual(p.js(self.MEASURE + "[1][1]"), p.js(self.MEASURE + "[1][2]"), "a left-out section too")
            p.view()
            self.assertEqual(p.js("getComputedStyle(document.querySelector('.secs > .sec')).paddingLeft"), "0px", "View is unchanged")

    def test_the_menu_entries_and_their_order(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            self.open_menu(p, "ABC-S-005")
            self.assertEqual(p.js(self.MENU_TEXTS % "ABC-S-005"),
                             ["Add a template below…", "Move up", "Move down", "Place beside the next section",
                              "Leave out of the published page", "Delete section"])
            self.assertEqual(p.js("[...document.querySelectorAll('.menu-item')].map(e => e.dataset.act)"),
                             ["add", "up", "down", "beside", "hide", "delete"])
            p.key("Escape", code="Escape", vk=27)
            self.open_menu(p, "ABC-S-002")           # not a text section: no Delete
            self.assertEqual(p.js(self.MENU_TEXTS % "ABC-S-002")[-1], "Leave out of the published page")
            p.key("Escape", code="Escape", vk=27)
            p.menu("ABC-S-002", "hide")
            p.saved()
            p.clear_toast()
            self.open_menu(p, "ABC-S-002")
            self.assertIn("Include in the published page", p.js(self.MENU_TEXTS % "ABC-S-002"))
            self.assertNotIn("Leave out of the published page", p.js(self.MENU_TEXTS % "ABC-S-002"))
            p.key("Escape", code="Escape", vk=27)
            self.open_menu(p, "ABC-S-007")      # half of a pair
            self.assertEqual(p.js(self.MENU_TEXTS % "ABC-S-007")[3], "Full width")
            self.assertEqual(p.js("document.querySelector('.menu').getAttribute('role')"), "menu")

    def test_the_plus_and_the_menu_entry_ask_for_a_section_below(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            p.js(self.LISTEN)
            n = len(self.sent)
            p.js("window.claim = false")
            p.js("document.querySelector('[data-id=\"ABC-S-003\"] [data-add]').click()")
            self.assertEqual(p.js("window.asked"), ["ABC-S-003"], "the + announces a request below this section")
            self.assertEqual(p.js("window.openers"), ["plus"], "and hands over the button that was pressed")
            self.assertTrue(p.js("window.cancelable"), "so a dialog can claim it with preventDefault")
            p.until("document.querySelectorAll('.sec').length === 12", "nobody claimed it, so a plain text section was added below, as before")
            self.assertEqual(self.sent[-1][1]["after"], "ABC-S-003", "below the section whose + was pressed")
            self.assertEqual(self.sent[-1][1]["values"], {"type": "text"})
            self.assertEqual(p.toast(), "Section added.")
            self.assertTrue(p.js("!!document.querySelector('.toast .toast-btn')"), "with its Undo")
            self.assertEqual(len(self.sent), n + 1)
            p.clear_toast()
            p.js("window.claim = true")
            p.menu("ABC-S-011", "add")
            self.assertEqual(p.js("window.asked"), ["ABC-S-003", "ABC-S-011"], "the menu entry makes the same request")
            self.assertEqual(p.js("window.openers"), ["plus", "grip"], "with the section's grip as the opener")
            self.assertIsNone(p.js("document.querySelector('.toast')"), "a dialog that claims it says nothing itself")
            self.assertEqual(len(self.sent), n + 1, "and nothing more was added")
            self.assertEqual(p.js("document.querySelectorAll('.sec').length"), 12)

    def test_the_fallback_adds_below_the_whole_row_and_a_pair_stays_whole(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            self.assertEqual(self.beside_flags()["ABC-S-006"], 1, "006 and 007 are a pair")
            p.js("document.querySelector('[data-id=\"ABC-S-006\"] [data-add]').click()")      # the + of the pair's first half
            p.until("document.querySelectorAll('.sec').length === 12", "a plain text section was added")
            new = [i for i in p.ids() if i not in IDS][0]
            ids = p.ids()
            self.assertEqual(ids[ids.index("ABC-S-006") + 1], "ABC-S-007", "the pair is still side by side")
            self.assertEqual(ids[ids.index("ABC-S-007") + 1], new, "the new section is below the whole row")
            self.assertEqual(self.sent[-1][1]["after"], "ABC-S-007", "after the second half")
            self.assertEqual(self.beside_flags()["ABC-S-006"], 1)
            self.assertEqual(self.beside_flags()[new], 0, "on its own, full width")
            self.assertTrue(p.js("document.querySelector('[data-id=\"ABC-S-006\"]').classList.contains('slot-left') && "
                                 "document.querySelector('[data-id=\"ABC-S-007\"]').classList.contains('slot-right')"))
            p.js("document.querySelector('[data-undo]').click()")
            p.until("document.querySelectorAll('.sec').length === 11", "one Undo takes it away")
            self.assertEqual(self.beside_flags()["ABC-S-006"], 1, "and the pair is as it was")
            self.assertEqual(len(self.ids_in_store()), 11)

    def test_keyboard_enter_and_space_open_the_menu_escape_closes_and_returns(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            grip = "document.querySelector('[data-id=\"ABC-S-004\"] [data-drag]')"
            for key, code, vk in (("Enter", "Enter", 13), (" ", "Space", 32)):
                p.js(f"{grip}.focus()")
                p.cdp.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": key, "code": code, "windowsVirtualKeyCode": vk,
                                                      "text": "\r" if key == "Enter" else " "}, p.sid)
                p.cdp.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "code": code, "windowsVirtualKeyCode": vk}, p.sid)
                p.until("!!document.querySelector('[data-id=\"ABC-S-004\"] .menu')", f"{code} opened the menu")
                self.assertEqual(p.js(f"{grip}.getAttribute('aria-expanded')"), "true")
                p.until("document.activeElement.matches('[role=menuitem]')", "focus went into the menu")
                self.assertEqual(p.js("document.activeElement.dataset.act"), "add", "the first entry has focus")
                p.key("ArrowDown", code="ArrowDown", vk=40)
                self.assertEqual(p.js("document.activeElement.dataset.act"), "up", "arrow keys step through the entries")
                p.key("Escape", code="Escape", vk=27)
                p.until("!document.querySelector('.menu')", "Esc closed it")
                self.assertTrue(p.js(f"document.activeElement === {grip}"), "focus came back to the grip")
                self.assertEqual(p.js(f"{grip}.getAttribute('aria-expanded')"), "false")
            # Alt+Up on the grip still moves by rows and keeps focus there
            p.key("ArrowUp", ALT, code="ArrowUp", vk=38)
            p.order_is(IDS[:2] + ["ABC-S-004", "ABC-S-003"] + IDS[4:], "Alt+Up")
            self.assertTrue(wait(lambda: p.js(f"document.activeElement === {grip}"), 5))

    def test_the_words_for_a_screen_reader_and_the_tooltip(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            g = "document.querySelector('[data-id=\"ABC-S-004\"] %s')"
            self.assertEqual(p.js(g % "[data-drag]" + ".getAttribute('aria-label')"), "Move or change Summary".replace("Summary", self.titles_in_store()[3]))
            self.assertEqual(p.js(g % "[data-drag]" + ".title"), "Drag to move · click for options")
            self.assertEqual(p.js(g % "[data-drag]" + ".getAttribute('aria-haspopup')"), "menu")
            self.assertEqual(p.js(g % "[data-drag]" + ".getAttribute('aria-keyshortcuts')"), "Alt+ArrowUp Alt+ArrowDown")
            self.assertEqual(p.js(g % "[data-add]" + ".getAttribute('aria-label')"), "Add a template below " + self.titles_in_store()[3])
            self.assertEqual(p.js(g % "[data-add]" + ".title"), "Add a template below")

    def test_a_drag_does_not_open_the_menu_but_a_click_does(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.tall(cdp)
            p.edit()
            bx, by, bottom = p.box('[data-id="ABC-S-004"]')
            p.drag("ABC-S-002", bx, bottom - 4)
            p.saved()
            self.assertEqual(p.js("document.querySelectorAll('.menu').length"), 0, "letting go after a drag opens nothing")
            hx, hy, _ = p.box('[data-id="ABC-S-008"] [data-drag]')
            p.mouse("mousePressed", hx, hy, 1)
            p.mouse("mouseReleased", hx, hy, 0)
            p.until("!!document.querySelector('[data-id=\"ABC-S-008\"] .menu')", "a click opens the menu")

    def test_the_styles_use_tokens_only_and_text_stays_at_13_px(self):
        css = (PAGE_SRC.parent / "shell.css").read_text(encoding="utf-8")
        lines = [l for l in css.splitlines() if l.startswith((".sec-ctl", ".sec.slot-right > .sec-ctl", ".sec:hover > .sec-ctl", ".handle", ".plus"))]
        self.assertGreaterEqual(len(lines), 6)
        for l in lines:
            self.assertNotRegex(l, r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", l)
        self.assertNotRegex("\n".join(lines), r"font-size:\s*(?:[0-9]|1[0-2])px")


class Look(Base):
    def test_no_sideways_scroll_targets_and_text_size_at_1400_and_900(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            p.menu("ABC-S-002", "hide")
            p.until("!!document.querySelector('.toast')", "a toast")
            p.js("document.querySelector('[data-id=\"ABC-S-004\"] [data-options]').click()")
            p.until("!!document.querySelector('.menu')", "a menu")
            for w in (1400, 900):
                cdp.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": 900, "deviceScaleFactor": 1, "mobile": False}, p.sid)
                p.until("document.documentElement.scrollWidth <= window.innerWidth", f"no sideways scroll at {w}")
                small = p.js("""[...document.querySelectorAll('[data-drag], [data-options], [data-add], .mode, .menu-item, .toast-btn')]
                    .map(e => [e.className || e.tagName, e.getBoundingClientRect().width, e.getBoundingClientRect().height])
                    .filter(x => x[1] < 24 || x[2] < 24)""")
                self.assertEqual(small, [], f"every target is at least 24 px at {w}")
                tiny = p.js("""[...document.querySelectorAll('#app *, .toasts *')].filter(e => [...e.childNodes].some(n => n.nodeType === 3
                    && n.textContent.trim()) && e.getBoundingClientRect().width > 0 && parseFloat(getComputedStyle(e).fontSize) < 13)
                    .map(e => e.className || e.tagName)""")
                self.assertEqual(tiny, [], f"no text under 13 px at {w}")
                menu = p.js("(function(){var m=document.querySelector('.menu').getBoundingClientRect();return [m.left>=0, m.right<=window.innerWidth];})()")
                self.assertEqual(menu, [True, True], "the menu is inside the window")
            for view in ("work", "milestones", "dashboard"):
                p.js(f"document.querySelector('[data-view={view}]').click()")
                p.until("document.documentElement.scrollWidth <= window.innerWidth", f"{view} has no sideways scroll at 900")


class Published(unittest.TestCase):
    def test_the_two_built_pages_are_current(self):
        self.assertEqual(page.PAGE.read_text(encoding="utf-8"), build_page.build(build_page.ENTRY),
                         "src/clark/page/page.html is out of date: run python3 dev/tools/build_page.py")
        self.assertEqual(page.VIEW_PAGE.read_text(encoding="utf-8"), build_page.build(build_page.ENTRY_VIEW),
                         "src/clark/page/page-view.html is out of date: run python3 dev/tools/build_page.py")
        self.assertEqual(build_page.main(["--check"]), 0)

    def test_only_api_js_names_the_two_routes(self):
        for f in PAGE_SRC.rglob("*"):
            if f.is_file() and f.name != "api.js":
                text = f.read_text(encoding="utf-8")
                self.assertNotIn("/api/change", text, f.name)
                self.assertNotIn("/api/undo", text, f.name)
        api = (PAGE_SRC / "api.js").read_text(encoding="utf-8")
        for need in ("/api/change", "/api/undo", "X-Clark-Token", "application/json"):
            self.assertIn(need, api)

    def test_the_published_build_has_no_route_no_edit_control_and_no_edit_button(self):
        text = page.VIEW_PAGE.read_text(encoding="utf-8")
        for never in ("/api/change", "/api/undo", "plaintext-only", "data-edit-only", "data-drag", "contenteditable",
                      "Add a text section", "Add a section below", "Add a template below", "View (V)", "Edit (E)", "aria-keyshortcuts"):
            self.assertNotIn(never, text, never)
        self.assertIn("/api/change", page.PAGE.read_text(encoding="utf-8"), "the served page does have it")
        with tempfile.TemporaryDirectory() as tmp:
            done = esbuild.run(["--bundle", "--format=iife", "--tsconfig-raw={}", *build_page.preact_flags(), "view.jsx",
                                f"--outfile={Path(tmp) / 'p.js'}", f"--metafile={Path(tmp) / 'm.json'}"],
                               cwd=build_page.SRC, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            inputs = json.loads((Path(tmp) / "m.json").read_text(encoding="utf-8"))["inputs"]
        self.assertEqual([i for i in inputs if i.startswith("edit/") or i in ("api.js", "stores/changes.js")], [])

    def test_the_published_file_has_no_edit_part_and_not_a_hidden_section(self):
        demo = DemoStore()
        self.addCleanup(demo.close)
        store = demo.store
        change = changes.make_change(store.path, [], USER)
        for ref, edit in (("ABC-S-005", {"title": "Hidden secret plan", "hidden": 1}), ("ABC-S-006", {"title": "Shown <b>plan</b>"})):
            status, body = change({"project": "ABC", "kind": "report_sections", "op": "update", "id": ref, "changes": edit})
            self.assertEqual(status, 200, body)
        with store.step("dashboard", USER) as st:              # words in This week and Next week: an empty text section is left out
            for ref in ("ABC-S-006", "ABC-S-007"):
                st.update("report_sections", ref, {"body": "<p>Some words</p>"})
        folder = tempfile.mkdtemp(prefix="clark-pub-")
        self.addCleanup(shutil.rmtree, folder, True)
        done = publish.publish(store, "ABC", folder, by_user=USER, now="2026-10-28", branding=EMPTY_BRANDING)
        text = Path(done["path"]).read_text(encoding="utf-8")
        for never in ("Hidden secret plan", "/api/change", "plaintext-only"):
            self.assertNotIn(never, text)
        self.assertIn("Shown \\u003cb\\u003eplan", text)
        with chrome() as cdp:
            tid = next(t["targetId"] for t in cdp.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
            sid = cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
            cdp.call("Page.navigate", {"url": Path(done["path"]).as_uri()}, sid)
            self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('.sec')", sid)), "the file drew its sections")
            titles = cdp.js("[...document.querySelectorAll('.sec-h')].map(e => e.textContent)", sid)
            self.assertNotIn("Hidden secret plan", titles)
            self.assertIn("Shown <b>plan</b>", titles)
            self.assertEqual(titles, ["At a glance", "Use case summary", "Shown <b>plan</b>", "Next week"],
                             "At a glance and the use case summary (#45) and the two text sections with words: Summary is hidden, and no other type is drawn in a file yet")
            self.assertEqual(edit_elements(cdp, sid), [])
            self.assertEqual(cdp.js("document.querySelectorAll('.mode, [aria-pressed]').length", sid), 0, "no Edit button")
            for key in ("e", "E", "v"):                                           # V and E do nothing in a published file (#103)
                for kind in ("keyDown", "keyUp"):
                    cdp.call("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": "Key" + key.upper(),
                                                         "windowsVirtualKeyCode": ord(key.upper())}, sid)
            time.sleep(0.3)
            self.assertEqual(cdp.js("document.querySelector('#report').dataset.mode", sid), "view", "E in a file stays View")
            self.assertEqual(edit_elements(cdp, sid), [])
            self.assertIsNone(cdp.js("document.querySelector('.sec-h b')", sid))

    def test_the_published_file_draws_the_three_bodies_read_only_at_1400_and_900(self):
        """#74: Summary, This week and Next week show their words in the file, view-only; a hostile part planted past the editor
        and a hidden section's body are not there; with This week hidden, Next week takes the whole row."""
        demo = DemoStore()
        self.addCleanup(demo.close)
        store = demo.store
        long_word = "Z" * 400
        bodies = {"ABC-S-005": f"<p>Summary ZQ-SUMMARY <strong>bold</strong></p><ul><li>one</li></ul><p>{long_word}</p>"
                               '<script>window.ZQ_RAN=1</script><img src="x" onerror="window.ZQ_RAN=1">'
                               '<a href="javascript:window.ZQ_RAN=1">ZQ-BAD-LINK</a>'
                               '<a href="&#106;avascript:window.ZQ_RAN=1">ZQ-ENC-LINK</a>'      # an address hidden in an entity
                               "<p>Write to ann&#64;example.com ZQ-AT</p>"                       # an entity in plain words
                               '<p style="color:red;background:url(https://evil.example/x)">ZQ-STYLED</p>'
                               '<a href="https://example.com/notes">ZQ-SAFE-LINK</a>',          # the one link that stays
                  "ABC-S-006": "<p>ZQ-HIDDEN-THIS-WEEK</p>",
                  "ABC-S-007": "<p>Next week ZQ-NEXT</p>"}
        with store.step("dashboard", USER) as st:                         # past the editor: the store takes a text body
            for ref, body in bodies.items():
                st.update("report_sections", ref, {"body": body})
            st.update("report_sections", "ABC-S-006", {"hidden": 1})
        folder = tempfile.mkdtemp(prefix="clark-pub-")
        self.addCleanup(shutil.rmtree, folder, True)
        done = publish.publish(store, "ABC", folder, by_user=USER, now="2026-10-28", branding=EMPTY_BRANDING)
        text = Path(done["path"]).read_text(encoding="utf-8")
        for never in ("ZQ-HIDDEN-THIS-WEEK", "ZQ_RAN", "onerror", "javascript:", "avascript:", "evil.example", "color:red"):
            self.assertNotIn(never, text, never)
        self.assertEqual(publish.outside_addresses(text), [], "with the bodies in it, nothing in the file reaches outside")
        with chrome() as cdp:
            tid = next(t["targetId"] for t in cdp.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
            sid = cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
            cdp.call("Page.navigate", {"url": Path(done["path"]).as_uri()}, sid)
            self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('.sec-body')", sid)), "the file drew a body")

            def body(ref):
                return cdp.js(f"(document.querySelector('[data-id=\"{ref}\"] .sec-body') || {{}}).textContent || null", sid)
            self.assertIn("Summary ZQ-SUMMARY bold", body("ABC-S-005"))
            self.assertIn("ZQ-BAD-LINK", body("ABC-S-005"), "an unsafe link keeps its words")
            self.assertIn("ZQ-ENC-LINK", body("ABC-S-005"), "a link hidden in an entity keeps its words")
            self.assertIn("Write to ann@example.com ZQ-AT", body("ABC-S-005"), "an entity in the words reads as its letter")
            self.assertIn("ZQ-STYLED", body("ABC-S-005"), "a styled paragraph keeps its words")
            links = cdp.js("[...document.querySelectorAll('[data-id=\"ABC-S-005\"] .sec-body a[href]')].map(a => a.getAttribute('href'))", sid)
            self.assertEqual(links, ["https://example.com/notes"], "only the safe link has an address")
            self.assertEqual(cdp.js("document.querySelectorAll('.sec-body [style]').length", sid), 0, "no style attribute is left")
            self.assertEqual(body("ABC-S-007"), "Next week ZQ-NEXT")
            self.assertIsNone(cdp.js("document.querySelector('[data-id=\"ABC-S-006\"]')", sid), "a hidden section is not drawn")
            self.assertEqual(cdp.js("document.querySelector('[data-id=\"ABC-S-005\"] .sec-body strong').textContent", sid), "bold")
            self.assertIsNone(cdp.js("window.ZQ_RAN || null", sid), "nothing planted ran")
            self.assertEqual(cdp.js("[...document.querySelectorAll('.sec')].filter(s => s.dataset.type !== 'text')"
                                    ".filter(s => s.querySelector('.sec-body')).length", sid), 0, "only a text section has a body")
            for w in (1400, 900):
                cdp.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": 900, "deviceScaleFactor": 1, "mobile": False}, sid)
                self.assertTrue(wait(lambda: cdp.js("document.documentElement.scrollWidth <= window.innerWidth", sid)),
                                f"no sideways scroll at {w}, even with a 400-letter word")
                self.assertEqual(edit_elements(cdp, sid), [], f"nothing to type in at {w}")
                full = cdp.js("(function(){var s=document.querySelector('[data-id=\"ABC-S-007\"]').getBoundingClientRect(),"
                              "r=document.querySelector('.secs').getBoundingClientRect();return Math.abs(s.width - r.width) < 2;})()", sid)
                self.assertTrue(full, f"with This week hidden, Next week takes the whole row at {w}")

    def test_an_empty_text_body_leaves_its_section_out_of_the_file_at_1400_and_900(self):
        """
        paragraphs, line breaks, non-breaking spaces) is not drawn in the file, so its heading never stands alone; This week is
        beside Next week, so with This week empty Next week takes the whole row. A body that is only a picture still shows."""
        demo = DemoStore()
        self.addCleanup(demo.close)
        store = demo.store
        picture = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        with store.step("dashboard", USER) as st:
            st.update("report_sections", "ABC-S-005", {"body": f'<p><img src="{picture}" alt=""></p>'})
            st.update("report_sections", "ABC-S-006", {"body": "<p></p><p> \n </p><br><p>&nbsp;<br></p><div><span> </span></div>",
                                                            "beside": 1})
            st.update("report_sections", "ABC-S-007", {"body": "<p>Next week ZQ-NEXT</p>"})
        folder = tempfile.mkdtemp(prefix="clark-pub-")
        self.addCleanup(shutil.rmtree, folder, True)
        done = publish.publish(store, "ABC", folder, by_user=USER, now="2026-10-28", branding=EMPTY_BRANDING)
        with chrome() as cdp:
            tid = next(t["targetId"] for t in cdp.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
            sid = cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
            cdp.call("Page.navigate", {"url": Path(done["path"]).as_uri()}, sid)
            self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('[data-id=\"ABC-S-007\"] .sec-body')", sid)), "the file drew")
            self.assertIsNone(cdp.js("document.querySelector('[data-id=\"ABC-S-006\"]')", sid), "an empty This week is not drawn")
            self.assertEqual(cdp.js("[...document.querySelectorAll('.sec-h')].filter(h => h.textContent === 'This week').length", sid), 0)
            self.assertTrue(cdp.js("!!document.querySelector('[data-id=\"ABC-S-005\"] .sec-body img')", sid), "a picture alone is not empty")
            self.assertTrue(cdp.js("document.querySelector('[data-id=\"ABC-S-007\"]').classList.contains('slot-full')", sid),
                            "the rows are worked out again without This week")
            for w in (1400, 900):
                cdp.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": 900, "deviceScaleFactor": 1, "mobile": False}, sid)
                full = ("(function(){var s=document.querySelector('[data-id=\"ABC-S-007\"]').getBoundingClientRect(),"
                        "r=document.querySelector('.secs').getBoundingClientRect();return Math.abs(s.width - r.width) < 2;})()")
                self.assertTrue(wait(lambda: cdp.js(full, sid)), f"with This week empty, Next week takes the whole row at {w}")

    def test_a_type_the_file_does_not_draw_yet_is_left_out_and_its_neighbour_takes_the_row_at_1400_and_900(self):
        """
        does not draw yet (all but text) is left out of the file, heading and all, for every type in the demo; Next week is set
        beside Risks and issues (This week no longer beside it), so with Risks and issues left out Next week takes the row."""
        demo = DemoStore()
        self.addCleanup(demo.close)
        store = demo.store
        sections = order.in_order(store.read("report_sections", "ABC"))
        kinds = {s["type"] for s in sections}
        self.assertTrue({"current", "glance", "usecases", "milestones", "text", "raid", "actions", "decisions", "docs"} <= kinds,
                        kinds)
        with store.step("dashboard", USER) as st:
            for s in sections:
                if s["type"] == "text":
                    st.update("report_sections", s["id"], {"body": f"<p>Words ZQ-{s['id']}</p>"})
            st.update("report_sections", "ABC-S-006", {"beside": 0})          # This week full width
            st.update("report_sections", "ABC-S-007", {"beside": 1})          # Next week beside Risks and issues
        folder = tempfile.mkdtemp(prefix="clark-pub-")
        self.addCleanup(shutil.rmtree, folder, True)
        done = publish.publish(store, "ABC", folder, by_user=USER, now="2026-10-28", branding=EMPTY_BRANDING)
        text = Path(done["path"]).read_text(encoding="utf-8")
        for never in ("is not shown on this page", "Its content is not shown"):     # the served line is in the code, never drawn
            self.assertNotIn(never, text, never)
        with chrome() as cdp:
            tid = next(t["targetId"] for t in cdp.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
            sid = cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
            cdp.call("Page.navigate", {"url": Path(done["path"]).as_uri()}, sid)
            self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('[data-id=\"ABC-S-005\"] .sec-body')", sid)), "the file drew")
            drawn = cdp.js("[...document.querySelectorAll('.sec')].map(s => s.dataset.type)", sid)
            self.assertEqual(drawn, ["glance", "usecases"] + ["text"] * len([s for s in sections if s["type"] == "text"]),
                             "only text sections, At a glance and the use case summary (#45) are drawn")
            for s in sections:
                if s["type"] not in ("text", "glance", "usecases"):
                    self.assertIsNone(cdp.js(f"document.querySelector('[data-id=\"{s['id']}\"]')", sid), s["type"])
            page_text = cdp.js("document.body.innerText", sid)
            self.assertNotIn("is not shown", page_text)
            self.assertNotIn(QUIET, page_text)
            self.assertEqual(cdp.js("document.querySelectorAll('.quiet').length", sid), 0, "no quiet line in a file")
            self.assertTrue(cdp.js("document.querySelector('[data-id=\"ABC-S-007\"]').classList.contains('slot-full')", sid),
                            "the rows are worked out again without Risks and issues")
            for w in (1400, 900):
                cdp.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": 900, "deviceScaleFactor": 1, "mobile": False}, sid)
                full = ("(function(){var s=document.querySelector('[data-id=\"ABC-S-007\"]').getBoundingClientRect(),"
                        "r=document.querySelector('.secs').getBoundingClientRect();return Math.abs(s.width - r.width) < 2;})()")
                self.assertTrue(wait(lambda: cdp.js(full, sid)), f"with Risks and issues left out, Next week takes the whole row at {w}")


if __name__ == "__main__":
    unittest.main()
