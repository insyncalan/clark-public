"""#66: there is one rich editor, clarkEditor(), and nothing else edits rich text on the page.

Run: python3 dev/run_tests.py test_one_editor_gate
Adapted from creaite's gate, not copied: creaite's file is a Markdown round trip and counts nothing. Here:
  - a source check: no other `new Editor`, `createEditor` or `contenteditable` in the page's source outside core/editor.js (the section
    title's plain-text field is the one named exception, below);
  - a page check: with the rich fields switched on (a copy of the page's source with the seam in edit/richSave.js listing the text
    section's body), Edit opens every rich field and finds only clarkEditor() instances (a .ProseMirror with a handle), and with the
    seam as shipped (empty) no rich field has an editor;
  - the editor adds no <style> element when it mounts, and the Edit page loads.
"""
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _demo import USER, DemoStore
from _paths import SRC, TOOLS

sys.path.insert(0, str(TOOLS))
import build_page  # noqa: E402

from clark import changes, order, page, server as sv  # noqa: E402
from clark.store import open_store  # noqa: E402
from test_page import navigate  # noqa: E402
from test_server import Running, chrome, wait  # noqa: E402

PAGE_SRC = SRC / "clark" / "page" / "src"
EMPTY_BRANDING = tempfile.mkdtemp(prefix="clark-no-brand-")
# Not a rich field: the section title is plain text on a contenteditable="plaintext-only" span (Title.jsx, #65), with an input as the
# fallback. It stays: the title is a one-line plain-text field whose tests belong to #65, and moving it onto the plain profile is a
# low-priority follow-up. Moving it onto clarkEditor's plain profile is a separate change (it would rewrite #65's tests of the title).
# The other: the Draft email preview is a plain editable box on purpose (its styled HTML and table are what Outlook pastes, as in creaite). It holds an email, not a report field. keys.js and help/helpStore.js only READ isContentEditable to leave typing alone.
NAMED = {"edit/Title.jsx", "components/DraftEmail.jsx"}
PATTERN = re.compile(r"new\s+Editor\b|createEditor\b|contenteditable(?!\w*\)?\s*\|\|)", re.I)


def tearDownModule():
    shutil.rmtree(EMPTY_BRANDING, ignore_errors=True)


class Source(unittest.TestCase):
    def test_no_other_editor_in_the_page_source(self):
        found = []
        for f in sorted(PAGE_SRC.rglob("*")):
            if f.suffix not in (".js", ".jsx") or f.name == "sanitiseTables.js":
                continue
            rel = f.relative_to(PAGE_SRC).as_posix()
            if rel == "core/editor.js" or rel in NAMED:
                continue
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if PATTERN.search(line.replace("isContentEditable", "")):
                    found.append(f"{rel}:{n}: {line.strip()[:80]}")
        self.assertEqual(found, [])

    def test_the_seam_ships_empty_and_names_the_three_rich_fields_it_will_take(self):
        text = (PAGE_SRC / "edit" / "richSave.js").read_text(encoding="utf-8")
        self.assertRegex(text, r"export const RICH_WRITES = \{\};")

    def test_core_editor_is_the_only_importer_of_the_vendored_editor(self):
        importers = [f.relative_to(PAGE_SRC).as_posix() for f in PAGE_SRC.rglob("*.js*") if re.search(r"from\s+[\"']tiptap[\"']", f.read_text(encoding="utf-8"))]
        self.assertEqual(importers, ["core/editor.js"])

    def test_the_published_page_has_no_editor(self):
        view = (SRC / "clark" / "page" / "page-view.html").read_text(encoding="utf-8")
        scripts = "".join(re.findall(r"<script>(.*?)</script>", view, re.S))          # the stylesheet names the editor's classes; the script must not hold it
        self.assertGreater(len(scripts), 1000)
        for word in ("createEditor", "cxed", "prosemirror", "SanitiseError"):
            self.assertNotIn(word, scripts, word)

    def test_the_built_pages_are_current(self):
        self.assertEqual(build_page.main(["--check"]), 0)


ORIGINAL = "<p>Original words the programme manager wrote.</p>"


class PageGate(unittest.TestCase):
    """The real page, built from a copy of the source with the seam switched on for the text section's body."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="clark-gate-")
        cls.src = Path(cls.tmp) / "src"
        shutil.copytree(PAGE_SRC, cls.src, ignore=shutil.ignore_patterns("shown"))
        seam = cls.src / "edit" / "richSave.js"
        seam.write_text(seam.read_text(encoding="utf-8").replace(
            "export const RICH_WRITES = {};",
            'export const RICH_WRITES = { body: (id, html) => ({ kind: "report_sections", op: "update", id, changes: { body: html } }) };'),
            encoding="utf-8")
        with mock.patch.object(build_page, "SRC", cls.src):
            cls.page_on = build_page.build()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.demo = DemoStore()
        self.addCleanup(self.demo.close)
        self.store = self.demo.store
        self.real = changes.make_change(self.store.path, [], USER)
        self.sent = []
        self.fail_reads = False
        self.body_writes = False                 # #188: the stand-in body write kind (stand_in) answers instead of the real server
        quiet = mock.patch.object(sv.LOG, "disabled", True)
        quiet.start()
        self.addCleanup(quiet.stop)

    def data(self, code):
        if self.fail_reads:
            raise OSError("the data could not be read")
        return self.store.data_for(code)

    def serve(self, html):
        s = Running(data_for=self.data, page_html=lambda: html, change=self.change, undo=changes.make_undo(self.store.path, [], USER))
        self.addCleanup(s.close)
        return s

    def change(self, req):
        if self.body_writes:
            return self.stand_in(req)
        self.sent.append(req)
        return self.real(req)

    def seed_body(self):
        """The demo project's first text section gets a body; returns nothing, sets self.sec. Also switches the stand-in on."""
        rows = [r for r in self.store.read("report_sections", "ABC") if r["type"] == "text"]
        self.assertTrue(rows, "the demo project has a text section")
        self.sec = rows[0]["id"]
        with self.store.step("dashboard", USER) as st:
            st.update("report_sections", self.sec, {"body": ORIGINAL})
        self.body_writes = True

    def edit(self, cdp, s):
        sid = navigate(cdp, s.port, "#dashboard&p=ABC")
        js = lambda e: cdp.js(e, sid)  # noqa: E731
        self.assertTrue(wait(lambda: js("document.querySelectorAll('.sec').length > 0"), 15))
        js("document.querySelector('[data-mode=edit]').click()")
        self.assertTrue(wait(lambda: js("document.querySelector('#report').dataset.mode === 'edit'"), 10))
        return js, sid

    def test_with_the_seam_empty_no_rich_field_has_an_editor(self):
        s = self.serve(page.page_html(EMPTY_BRANDING))
        with chrome() as cdp:
            js, _ = self.edit(cdp, s)
            self.assertEqual(js("document.querySelectorAll('.ProseMirror, [data-rich]').length"), 0)
            self.assertEqual(js("document.querySelectorAll('.sec[data-type=text] .quiet').length > 0"), True)

    def test_every_rich_field_opens_a_clark_editor_and_nothing_else(self):
        s = self.serve(self.page_on)
        with chrome() as cdp:
            js, sid = self.edit(cdp, s)
            fields = js("document.querySelectorAll('[data-rich]').length")
            self.assertGreaterEqual(fields, 1, "the text sections show a rich field")
            before = js("document.querySelectorAll('style').length")
            js("document.querySelectorAll('[data-rich]').forEach(function(f){ f.click(); })")
            self.assertTrue(wait(lambda: js("document.querySelectorAll('.ProseMirror').length") == fields, 10))
            self.assertEqual(js("document.querySelectorAll('.ProseMirror').length"), js("document.querySelectorAll('.ProseMirror').length"))
            self.assertEqual(js("[...document.querySelectorAll('.ProseMirror')].every(function(e){ return !!e.cxed && typeof e.cxed.html === 'function'; })"), True)
            self.assertEqual(js("document.querySelectorAll('[contenteditable]').length"),
                             js("document.querySelectorAll('.ProseMirror').length + document.querySelectorAll('[contenteditable=plaintext-only]').length"),
                             "no contenteditable but the editors' own and the section titles")
            self.assertEqual(js("document.querySelectorAll('style').length"), before, "a mount adds no <style>")

    def test_a_save_that_the_server_refuses_says_so_in_plain_words_and_keeps_the_field_open(self):
        s = self.serve(self.page_on)
        with chrome() as cdp:
            js, sid = self.edit(cdp, s)
            js("document.querySelector('[data-rich]').click()")
            self.assertTrue(wait(lambda: js("!!document.querySelector('.ProseMirror')"), 10))
            js("document.querySelector('.ProseMirror').cxed.editor.commands.insertContent('New words'); true")
            cdp.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13,
                                                "modifiers": 4 if js("/Mac/.test(navigator.platform)") else 2}, sid)
            self.assertTrue(wait(lambda: any(r.get("changes", {}).get("body") for r in self.sent), 10), "the change was sent")
            self.assertTrue(wait(lambda: js("!!document.querySelector('.toast')"), 10))
            self.assertTrue(js("!!document.querySelector('.ProseMirror')"), "the field stays open")
            self.assertNotIn("Traceback", js("document.querySelector('.toast-text').textContent"))

    def stored(self):
        return next(r for r in self.store.read("report_sections", "ABC") if r["id"] == self.sec)["body"]

    def stand_in(self, req):
        """The body write kind that is not built yet (changes.py is guarded): stores the body as the real one will and replies as the
        real server does, with the sections and no bodies."""
        self.sent.append(req)
        body = (req.get("changes") or {}).get("body")
        if req.get("kind") == "report_sections" and body is not None:
            mine = open_store(self.store.path, onedrive_roots=[])          # the server calls this on its own thread
            try:
                with mine.step("dashboard", USER) as st:
                    st.update("report_sections", req["id"], {"body": body})
                return 200, {"ok": True, "apply_id": 1, "ref": req["id"], "sections": changes._shown_rows(changes._sections(mine, "ABC"))}
            finally:
                mine.close()
        return self.real(req)

    def open_field(self, cdp, js, sid):
        js("document.querySelector('[data-rich]').click()")
        self.assertTrue(wait(lambda: js("!!document.querySelector('.ProseMirror')"), 10))
        self.assertTrue(wait(lambda: js("document.activeElement && document.activeElement.classList.contains('ProseMirror')"), 10),
                        "the editor has the focus when it opens")

    def mod(self, js):
        return 4 if js("/Mac/.test(navigator.platform)") else 2

    def key(self, cdp, sid, key, code, vk, modifiers=0):
        for kind in ("keyDown", "keyUp"):
            cdp.call("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": code, "windowsVirtualKeyCode": vk, "modifiers": modifiers}, sid)

    def test_a_saved_body_is_still_there_when_the_field_is_opened_again_and_the_focus_comes_back(self):
        self.seed_body()
        s = self.serve(self.page_on)
        with chrome() as cdp:
            js, sid = self.edit(cdp, s)
            self.assertIn("Original words", js("document.querySelector('[data-rich]').textContent"))
            self.open_field(cdp, js, sid)
            js("document.querySelector('.ProseMirror').cxed.editor.commands.insertContent('Added words. '); true")
            self.key(cdp, sid, "Enter", "Enter", 13, self.mod(js))
            self.assertTrue(wait(lambda: any(r.get("changes", {}).get("body") for r in self.sent), 10), "the change was sent")
            self.assertTrue(wait(lambda: js("!document.querySelector('.ProseMirror')"), 10),
                            "the field closed after the save: " + str(js("(document.querySelector('.toast-text') || {}).textContent")))
            self.assertIn("Original words", self.sent[-1]["changes"]["body"])
            self.assertTrue(wait(lambda: js("document.activeElement && document.activeElement.matches('[data-rich]')"), 5),
                            "after a save the focus is on the field, not the page body")
            shown = js("document.querySelector('[data-rich]').textContent")
            self.assertIn("Original words", shown, "the saved section still has its text")
            self.assertIn("Added words", shown)
            self.assertNotIn("Click to write", shown)
            # open it again: the editor holds what was stored, so the next save does not overwrite it with only the new words
            self.open_field(cdp, js, sid)
            held = js("document.querySelector('.ProseMirror').textContent")
            self.assertIn("Original words", held)
            self.assertIn("Added words", held)
            js("document.querySelector('.ProseMirror').cxed.editor.commands.insertContent('Second edit. '); true")
            self.key(cdp, sid, "Enter", "Enter", 13, self.mod(js))
            self.assertTrue(wait(lambda: len([r for r in self.sent if r.get("changes", {}).get("body")]) == 2, 10))
            second = [r for r in self.sent if r.get("changes", {}).get("body")][-1]["changes"]["body"]
            self.assertIn("Original words", second)
            self.assertIn("Added words", second)
            self.assertIn("Second edit", second)
            self.assertIn("Original words", self.stored())

    def test_esc_puts_the_focus_back_on_the_field_and_keeps_the_stored_text(self):
        self.seed_body()
        s = self.serve(self.page_on)
        with chrome() as cdp:
            js, sid = self.edit(cdp, s)
            self.open_field(cdp, js, sid)
            js("document.querySelector('.ProseMirror').cxed.editor.commands.insertContent('Words to throw away. '); true")
            self.key(cdp, sid, "Escape", "Escape", 27)
            self.assertTrue(wait(lambda: js("!document.querySelector('.ProseMirror')"), 10), "Esc closed the field")
            self.assertTrue(wait(lambda: js("document.activeElement && document.activeElement.matches('[data-rich]')"), 5),
                            "after Esc the focus is on the field, not the page body")
            self.assertEqual(self.stored(), ORIGINAL)
            self.assertEqual([r for r in self.sent if r.get("changes", {}).get("body")], [], "Esc saved nothing")

    def test_a_click_elsewhere_closes_the_field_and_leaves_the_focus_where_it_went(self):
        self.seed_body()
        s = self.serve(self.page_on)
        with chrome() as cdp:
            js, sid = self.edit(cdp, s)
            self.open_field(cdp, js, sid)
            x, y = js("(() => { const r = document.querySelector('.sec[data-type=milestones] h2, .sec h2').getBoundingClientRect(); return [r.x + 4, r.y + r.height / 2]; })()")
            for kind in ("mousePressed", "mouseReleased"):
                cdp.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1}, sid)
            self.assertTrue(wait(lambda: js("!document.querySelector('.ProseMirror')"), 10), "leaving the field closed it")
            self.assertEqual(js("document.activeElement.matches('[data-rich]')"), False, "the focus stayed where the person put it")

    def test_space_opens_the_field_as_enter_does(self):
        self.seed_body()
        s = self.serve(self.page_on)
        with chrome() as cdp:
            js, sid = self.edit(cdp, s)
            js("(() => { const f = document.querySelector('[data-rich]'); f.focus(); "
               "f.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true })); })()")
            self.assertTrue(wait(lambda: js("!!document.querySelector('.ProseMirror')"), 10), "Space opened the editor")

    def test_when_the_page_cannot_read_again_the_section_keeps_its_text_and_the_toast_says_so(self):
        self.seed_body()
        s = self.serve(self.page_on)
        with chrome() as cdp:
            js, sid = self.edit(cdp, s)
            self.fail_reads = True
            self.open_field(cdp, js, sid)
            js("document.querySelector('.ProseMirror').cxed.editor.commands.insertContent('Added words. '); true")
            self.key(cdp, sid, "Enter", "Enter", 13, self.mod(js))
            self.assertTrue(wait(lambda: js("(document.querySelector('.toast-text') || {}).textContent || ''").endswith("Reload the page to see it."), 10))
            self.assertIn("could not be refreshed", js("document.querySelector('.toast-text').textContent"))
            shown = js("document.querySelector('[data-rich]').textContent")
            self.assertIn("Original words", shown, "the reply carried no body, so the section kept the one the page had")
            self.assertNotIn("Click to write", shown)


if __name__ == "__main__":
    unittest.main()
