"""#197: Cmd or Ctrl+Z undoes the last change, the same step as the toast's Undo, on the Dashboard, Work items and Milestones.

Run: python3 dev/run_tests.py test_undo_key
A real server whose `change` and `undo` are the real clark.changes over a real demo store (fictional data), and the committed page
in headless Chrome at 1400 and 900 px, light and dark, with real key events. The key never acts while typing in a box or a
rich-text field, inside a dialog or a menu, in View, or with Shift; with nothing to undo it says so.
The browser parts are required: they fail, never skip, without Chrome (set CLARK_CHROME to its path).
"""
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from _demo import USER
from clark import changes, page, server as sv
from clark.store import open_store
from test_server import CHROME, Running, chrome, wait
from test_work_items import FIXED_DATE, load_demo, page_target

EMPTY_BRANDING = tempfile.mkdtemp(prefix="clark-no-brand-")
META, CTRL, SHIFT = 4, 2, 8
NOTHING = "Nothing to undo."
CELL = "[data-cell='TUL-A-001:priority']"


def tearDownModule():
    shutil.rmtree(EMPTY_BRANDING, ignore_errors=True)


def press_z(cdp, sid, modifiers):
    common = {"key": "z", "code": "KeyZ", "windowsVirtualKeyCode": 90, "modifiers": modifiers}
    cdp.call("Input.dispatchKeyEvent", {"type": "keyDown", **common}, sid)
    cdp.call("Input.dispatchKeyEvent", {"type": "keyUp", **common}, sid)


def click(cdp, sid, selector):
    cdp.js(f"document.querySelector({json.dumps(selector)}).scrollIntoView({{block: 'center'}})", sid)
    box = cdp.js(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) return null; const b = e.getBoundingClientRect(); return [b.x + Math.min(b.width / 2, 20), b.y + b.height / 2]; }})()", sid)
    assert box, f"{selector} is not on the page"
    x, y = box
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y}, sid)
    cdp.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1}, sid)
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "buttons": 0, "clickCount": 1}, sid)


class UndoKey(unittest.TestCase):
    def setUp(self):
        assert Path(CHROME).is_file(), f"Google Chrome is needed for the required browser tests ({CHROME}); set CLARK_CHROME"
        self.store, self.folder, _ = load_demo()
        self.addCleanup(shutil.rmtree, str(self.folder), True)
        self.addCleanup(self.store.close)
        self.path = self.folder / "clark.db"
        self.sent = []
        real_change, real_undo = changes.make_change(self.path, [], USER), changes.make_undo(self.path, [], USER)

        def seam(real, which):
            def call(req):
                self.sent.append((which, req))
                return real(req)
            return call
        self.s = Running(data_for=self.read, projects=lambda: [{"code": "TUL", "name": "Tulip"}],
                         page_html=lambda: page.page_html(EMPTY_BRANDING), change=seam(real_change, "change"), undo=seam(real_undo, "undo"))
        self.addCleanup(self.s.close)
        quiet = mock.patch.object(sv.LOG, "disabled", True)
        quiet.start()
        self.addCleanup(quiet.stop)

    def read(self, code):
        st = open_store(self.path, onedrive_roots=[])
        try:
            return st.data_for(code)
        finally:
            st.close()

    def priority(self):
        st = open_store(self.path, onedrive_roots=[])
        try:
            return st.read("actions", ref="TUL-A-001")["priority"]
        finally:
            st.close()

    def steps(self):
        st = open_store(self.path, onedrive_roots=[])
        try:
            return st.con.execute("SELECT count(*) FROM applies").fetchone()[0]
        finally:
            st.close()

    def undos_sent(self):
        return len([s for s in self.sent if s[0] == "undo"])

    def open_page(self, cdp, width, scheme="light", edit=True):
        sid = page_target(cdp)
        cdp.call("Page.enable", {}, sid)
        cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": FIXED_DATE}, sid)
        cdp.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False}, sid)
        cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]}, sid)
        cdp.call("Emulation.setFocusEmulationEnabled", {"enabled": True}, sid)
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{self.s.port}/#work&p=TUL&f=mode:all"}, sid)
        self.until(cdp, sid, "document.querySelectorAll('#work tbody tr').length > 0", "the list drew")
        if edit:
            cdp.js("document.querySelector('[data-mode=edit]').click()", sid)
            self.until(cdp, sid, "!!document.querySelector('[data-cell]')", "Edit shows the cells' pickers")
        return sid

    def until(self, cdp, sid, expr, what, seconds=10):
        self.assertTrue(wait(lambda: cdp.js(expr, sid), seconds), what)

    def toast(self, cdp, sid):
        return cdp.js("(document.querySelector('.toast-text') || {}).textContent || ''", sid)

    def pick(self, cdp, sid, value):
        """Change TUL-A-001's priority in the table, as a person does, and close the toast that offers Undo."""
        click(cdp, sid, CELL)
        self.until(cdp, sid, "!!document.querySelector('[data-pop][role=menu]')", "the priority menu opened")
        click(cdp, sid, f"[data-pop] [data-value={value}]")
        self.until(cdp, sid, "!!document.querySelector('[data-undo]')", "the toast offers Undo")
        self.assertEqual(self.priority(), value)
        click(cdp, sid, "[data-dismiss]")
        self.until(cdp, sid, "!document.querySelector('.toast-text')", "the toast closed")
        cdp.js("document.activeElement && document.activeElement.blur && document.activeElement.blur()", sid)

    def test_the_key_undoes_the_last_change_then_says_nothing_to_undo(self):
        for width in (1400, 900):
            for scheme in ("light", "dark"):
                with self.subTest(width=width, scheme=scheme), chrome() as cdp:
                    sid = self.open_page(cdp, width, scheme)
                    self.pick(cdp, sid, "Low")
                    before = self.steps()
                    press_z(cdp, sid, CTRL)                     # the toast has gone: the key still knows the last change
                    self.until(cdp, sid, "(document.querySelector('.toast-text') || {}).textContent === 'Priority of TUL-A-001 is back to Urgent.'",
                               "the key undid the change and said what went back")
                    self.assertEqual((self.priority(), self.steps()), ("Urgent", before + 1), "one undo, one step")
                    self.until(cdp, sid, f"document.querySelector(\"{CELL}\").textContent === 'Urgent'", "the row shows it")
                    look = cdp.js("(() => { const t = getComputedStyle(document.querySelector('.toast')); return [t.color, t.backgroundColor]; })()", sid)
                    self.assertNotEqual(look[0], look[1], "the message can be read")
                    n = self.undos_sent()
                    press_z(cdp, sid, META)                     # Cmd on a Mac works too
                    self.until(cdp, sid, f"(document.querySelector('.toast-text') || {{}}).textContent === {json.dumps(NOTHING)}", "nothing is left to undo")
                    self.assertEqual((self.undos_sent(), self.steps()), (n, before + 1), "nothing was sent")
                    self.assertEqual(cdp.js("document.documentElement.scrollWidth <= window.innerWidth", sid), True, "no sideways scroll")

    def test_two_changes_go_back_newest_first_and_the_dashboard_and_milestones_take_the_key(self):
        with chrome() as cdp:
            sid = self.open_page(cdp, 1400)
            self.pick(cdp, sid, "Low")
            self.pick(cdp, sid, "High")
            cdp.js("location.hash = '#dashboard&p=TUL'", sid)
            self.until(cdp, sid, "location.hash.startsWith('#dashboard')", "the Dashboard opened")
            press_z(cdp, sid, CTRL)
            self.until(cdp, sid, "/back to Low\\.$/.test((document.querySelector('.toast-text') || {}).textContent || '')", "the newest went back first")
            self.assertEqual(self.priority(), "Low")
            cdp.js("location.hash = '#milestones&p=TUL'", sid)
            self.until(cdp, sid, "location.hash.startsWith('#milestones')", "Milestones opened")
            cdp.js("document.activeElement && document.activeElement.blur && document.activeElement.blur()", sid)
            press_z(cdp, sid, CTRL)
            self.until(cdp, sid, "/back to Urgent\\.$/.test((document.querySelector('.toast-text') || {}).textContent || '')", "then the one before")
            self.assertEqual(self.priority(), "Urgent")
            press_z(cdp, sid, CTRL)
            self.until(cdp, sid, f"(document.querySelector('.toast-text') || {{}}).textContent === {json.dumps(NOTHING)}", "and then nothing")

    def test_the_toasts_undo_and_the_key_never_undo_one_change_twice(self):
        with chrome() as cdp:
            sid = self.open_page(cdp, 1400)
            click(cdp, sid, CELL)
            self.until(cdp, sid, "!!document.querySelector('[data-pop][role=menu]')", "the priority menu opened")
            click(cdp, sid, "[data-pop] [data-value=Low]")
            self.until(cdp, sid, "!!document.querySelector('[data-undo]')", "the toast offers Undo")
            click(cdp, sid, "[data-undo]")
            self.until(cdp, sid, "/back to Urgent\\.$/.test((document.querySelector('.toast-text') || {}).textContent || '')", "the button undid it")
            n = self.undos_sent()
            press_z(cdp, sid, CTRL)
            self.until(cdp, sid, f"(document.querySelector('.toast-text') || {{}}).textContent === {json.dumps(NOTHING)}", "the key has nothing left")
            self.assertEqual(self.undos_sent(), n)

    def test_never_in_a_box_a_rich_text_field_a_menu_a_dialog_in_view_or_with_shift(self):
        with chrome() as cdp:
            sid = self.open_page(cdp, 1400)
            self.pick(cdp, sid, "Low")
            n, before = self.undos_sent(), self.steps()
            places = {
                "a box": "(() => { const i = document.createElement('input'); i.id = 'probe'; document.body.appendChild(i); i.focus(); })()",
                "a rich-text field": "(() => { const d = document.createElement('div'); d.id = 'probe'; d.contentEditable = 'true'; document.body.appendChild(d); d.focus(); })()",
                "a dialog": "(() => { const d = document.createElement('div'); d.id = 'probe'; d.setAttribute('role', 'dialog'); d.tabIndex = -1; document.body.appendChild(d); d.focus(); })()",
                "a menu": "(() => { const d = document.createElement('div'); d.id = 'probe'; d.setAttribute('role', 'menu'); document.body.appendChild(d); })()",
            }
            for where, make in places.items():
                with self.subTest(where=where):
                    cdp.js(make, sid)
                    press_z(cdp, sid, CTRL)
                    press_z(cdp, sid, META)
                    time.sleep(0.3)
                    cdp.js("document.getElementById('probe').remove()", sid)
                    self.assertEqual(self.toast(cdp, sid), "", f"{where}: the page said nothing")
            click(cdp, sid, CELL)                               # the page's own menu
            self.until(cdp, sid, "!!document.querySelector('[data-pop][role=menu]')", "the priority menu opened")
            press_z(cdp, sid, CTRL)
            self.assertEqual(self.priority(), "Low", "the key left the open menu alone")
            click(cdp, sid, "h1")
            self.until(cdp, sid, "document.querySelectorAll('[data-pop]').length === 0", "the menu closed")
            cdp.js("document.activeElement && document.activeElement.blur && document.activeElement.blur()", sid)
            press_z(cdp, sid, CTRL | SHIFT)                     # redo is not this key
            cdp.js("document.querySelector('[data-mode=view]').click()", sid)
            press_z(cdp, sid, CTRL)                             # View changes nothing, so it undoes nothing
            self.assertEqual((self.undos_sent(), self.steps(), self.priority()), (n, before, "Low"), "nothing was undone")
            cdp.js("document.querySelector('[data-mode=edit]').click()", sid)
            self.until(cdp, sid, "!!document.querySelector('[data-cell]')", "back in Edit")
            cdp.js("location.hash = '#settings&p=TUL'", sid)
            self.until(cdp, sid, "location.hash.startsWith('#settings')", "Settings opened")
            cdp.js("document.activeElement && document.activeElement.blur && document.activeElement.blur()", sid)
            self.assertEqual(cdp.js("[document.activeElement.tagName, !!document.querySelector('dialog[open],[role=dialog],[role=menu],[role=listbox]')]", sid), ["BODY", False])
            press_z(cdp, sid, CTRL)
            time.sleep(0.6)                                     # time for a message to draw, if one were said
            self.assertEqual(self.undos_sent(), n, "not on Settings")
            self.assertEqual(self.toast(cdp, sid), "", "Settings leaves the key alone: not even Nothing to undo")
            cdp.js("location.hash = '#work&p=TUL&f=mode:all'", sid)
            self.until(cdp, sid, "!!document.querySelector('[data-cell]')", "Work items again")
            cdp.js("document.activeElement && document.activeElement.blur && document.activeElement.blur()", sid)
            press_z(cdp, sid, CTRL)
            self.until(cdp, sid, "/back to Urgent\\.$/.test((document.querySelector('.toast-text') || {}).textContent || '')", "still there to undo")
            self.assertEqual(self.undos_sent(), n + 1)


if __name__ == "__main__":
    unittest.main()
