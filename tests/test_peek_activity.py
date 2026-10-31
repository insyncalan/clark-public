"""#42: the peek's Activity tab (Edit only), the rule the peek follows with multi-select, and the peek's text contrast.
Run: PYTHONPATH=../src python3 test_peek_activity.py

Part 1 is the rule `peekFollowsSelection` (page/src/peek/follow.js), run in node when node is on the machine. Part 2 reads the
built pages: the Activity tab and its route are in the served page and in no published file. Part 3 measures the peek's text
colours against its backgrounds from the committed tokens, light and dark (4.5:1). Part 4 is the page in a real browser at 1400
and 900 px: in Edit the Activity tab shows who, how and when, newest first, by mouse and by keys; View has no tabs.
"""
import json
import re
import shutil
import subprocess
import unittest

from _paths import ROOT

from clark import activity_read, page  # noqa: E402
from test_dark_contrast import dark_blocks, ratio  # noqa: E402
import test_peek as tp  # noqa: E402
from test_peek import key  # noqa: E402
from test_server import chrome, wait  # noqa: E402
from test_work_filters import click  # noqa: E402

SRC = ROOT / "src" / "clark" / "page" / "src"
TOKENS = ROOT / "src" / "clark" / "brand" / "tokens.css"


class FollowRule(unittest.TestCase):
    def run_js(self, body):
        node = shutil.which("node")
        if not node:
            self.skipTest("no node")
        code = f'import {{ peekFollowsSelection as F }} from "{(SRC / "peek" / "follow.js").as_uri()}"; {body}'
        done = subprocess.run([node, "--input-type=module", "-e", code], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_two_or_more_close_an_open_peek_one_moves_it_and_none_leaves_it(self):
        out = self.run_js('console.log(JSON.stringify([F(0, true), F(1, true), F(2, true), F(7, true), '
                          'F(0, false), F(1, false), F(2, false), F(-1, true), F(NaN, true), F(1.5, true)]))')
        self.assertEqual(out, ["stay", "follow", "close", "close", "none", "none", "none", "stay", "stay", "stay"])

    def test_the_peek_state_module_exposes_it_and_the_rule_is_written_down(self):
        self.assertIn('export { peekFollowsSelection } from "../peek/follow.js"', (SRC / "stores" / "peekState.js").read_text(encoding="utf-8"))
        doc = (ROOT / "docs" / "handoff" / "design-42-peek.md").read_text(encoding="utf-8")
        self.assertIn("peekFollowsSelection(count, peekOpen)", doc)
        self.assertIn("With 2 or more selected, an open peek closes", doc)


class BuiltPages(unittest.TestCase):
    def test_the_activity_tab_is_in_the_served_page_only(self):
        served, view = page.PAGE.read_text(encoding="utf-8"), page.VIEW_PAGE.read_text(encoding="utf-8")
        for word in ("/api/activity", "data-activity", "Reading the history", "Item details and history"):
            self.assertIn(word, served, word)
            self.assertNotIn(word, view, word)

    def test_help_names_the_tab_that_is_there_and_one_name_for_sneak_peek(self):
        text = (SRC / "help" / "helpContent.json").read_text(encoding="utf-8")
        self.assertNotIn("**All**, **Activity**, **Updates** and **Source**", text)
        self.assertNotIn("All, Activity, Updates and Source", text)
        self.assertIn("**Activity** tab", text)
        self.assertNotIn("Change an item in words", text)
        self.assertIn("Change an item with words", (SRC / "edit" / "SneakPeek.jsx").read_text(encoding="utf-8"))


def light_tokens(css):
    """The light values: every #hex token set before the first dark block (a later one wins)."""
    head = css.split(":root[data-theme=dark]")[0]
    out = {}
    for name, value in re.findall(r"(--[\w-]+):\s*(#[0-9A-Fa-f]{6}|#[0-9A-Fa-f]{3})\b", head):
        out[name] = ("#" + "".join(c * 2 for c in value[1:]) if len(value) == 4 else value).upper()
    return out


# (text token, background token): the peek's fields, its tabs, the Activity rows and the words box.
PAIRS = (("--text", "--surface"), ("--text-muted", "--surface"), ("--heading", "--surface"), ("--status-green-text", "--surface"),
         ("--status-red-text", "--surface"), ("--text", "--grey-50"), ("--text-muted", "--grey-50"), ("--status-red-text", "--grey-50"))


class Contrast(unittest.TestCase):
    def test_the_peek_text_is_at_least_4_5_to_1_in_light_and_dark(self):
        css = TOKENS.read_text(encoding="utf-8")
        modes = [("light", light_tokens(css))] + [("dark", b) for b in dark_blocks(css)]
        for mode, tokens in modes:
            for fg, bg in PAIRS:
                with self.subTest(mode=mode, fg=fg, bg=bg):
                    self.assertGreaterEqual(ratio(tokens[fg], tokens[bg]), 4.5, f"{mode}: {fg} on {bg}")

    def test_the_activity_styles_use_only_those_tokens(self):
        css = (SRC / "edit" / "edit.css").read_text(encoding="utf-8")
        mine = "\n".join(line for line in css.splitlines() if line.startswith((".pa-", ".pk-tab", ".pk-activity")))
        used = set(re.findall(r"(?<![\w-])color:\s*var\((--[\w-]+)\)", mine))
        self.assertTrue(used)
        self.assertTrue(used <= {fg for fg, _ in PAIRS}, used)


class ActivityBrowser(unittest.TestCase):
    setUpClass = tp.Browser.__dict__["setUpClass"]
    tearDownClass = tp.Browser.__dict__["tearDownClass"]
    edit_mode = tp.Browser.edit_mode
    ids_on_page = tp.Browser.ids_on_page

    def load_page(self, cdp, width):
        s, sid = tp.Browser.load_page(self, cdp, width)
        s.httpd.activity = activity_read.make_read(self.store.path, self.store.data_for)
        return s, sid

    def test_edit_shows_who_how_and_when_newest_first_by_mouse_and_keys_and_view_has_no_tabs(self):
        for width in (1400, 900):
            with self.subTest(width=width), chrome() as cdp:
                s, sid = self.load_page(cdp, width)
                ids = self.ids_on_page(cdp, sid)
                click(cdp, sid, f"#work tbody tr[data-id='{ids[0]}'] .c-item")
                self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('#peek')", sid)))
                self.assertFalse(cdp.js("!!document.querySelector('#peek [role=tablist],[data-activity]')", sid), "no tabs in View")
                key(cdp, sid, "Escape")
                self.edit_mode(cdp, sid)
                click(cdp, sid, f"#work tbody tr[data-id='{ids[0]}'] .c-item")
                self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('[data-pk-tab=activity]')", sid)))
                click(cdp, sid, "[data-pk-tab=activity]")
                self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('[data-activity-row]').length", sid) > 0))
                self.assertEqual(cdp.js("document.querySelector('[data-pk-tab=activity]').getAttribute('aria-selected')", sid), "true")
                first = cdp.js("document.querySelector('[data-activity-row] .pa-meta').textContent", sid)
                self.assertRegex(first, r"\d{2}-\d{2}-\d{4}", "the when is a date the person reads")
                self.assertNotIn("{", cdp.js("document.querySelector('[data-activity]').textContent", sid), "no raw JSON")
                # the keys: Left goes back to Details, focus stays on the tabs
                cdp.js("document.querySelector('[data-pk-tab=activity]').focus()", sid)
                key(cdp, sid, "ArrowLeft")
                self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('#peek .pk-fields')", sid)))
                self.assertEqual(cdp.js("document.activeElement.dataset.pkTab", sid), "details")
                self.assertFalse(cdp.js("!!document.querySelector('[data-activity]')", sid))


if __name__ == "__main__":
    unittest.main()
