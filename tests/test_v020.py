"""clark 0.2's hand checks as tests. Each release gets a test_vNNN file, so the walk-through keeps only the judgement and
live-only checks.

Run: python3 dev/run_tests.py test_v020

What a person would check by eye in the v0.2 items, and where each check is covered:
  COVERED       already covered by a test elsewhere. Not tested again here: test_every_covering_test_named_here_exists checks
                that each one is still there.
                after that, the same existence check runs for them.
  NEW           covered here, in a real browser at 1400 and 900 px, light and dark (the classes below).
  WAITING       the feature is not on main yet; its check is written when it lands (the open PR or item is named).
  WALK_THROUGH  judgement or live only, with the reason. These stay in the walk-through.

The browser tests drive the real server and the committed page in headless Chrome over the demo store at CLARK_NOW=2026-10-28
(tests/test_server.py chrome(), as test_glance_tiles does). Required: they fail, never skip, without Chrome (set CLARK_CHROME).
"""
import ast
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from _paths import ROOT

from clark import page  # noqa: E402
from test_server import Running, chrome, wait  # noqa: E402
from test_work_filters import need_chrome  # noqa: E402
from test_work_items import FIXED_DATE, load_demo, page_target  # noqa: E402

TESTS = ROOT / "tests"
WIDTHS = (1400, 900)
THEMES = ("light", "dark")
PAGES = ("dashboard", "work", "milestones", "settings")
DRAWN = {"dashboard": "#report", "work": "#work", "milestones": "#milestones", "settings": ".frame"}   # each page, once drawn
EMPTY_BRANDING = tempfile.mkdtemp(prefix="clark-no-brand-")        # so a brand on this laptop never changes a test

# (item, the check a person would make by eye, the test that covers it: file::Class::test)
COVERED = [
    ("#65", "View and Edit switch without a reload", "test_report_editor::Modes::test_editor_modes"),
    ("#65", "In View nothing on the page can be edited", "test_report_editor::Modes::test_view_is_read_only"),
    ("#65", "A text section can be added, with Undo",
     "test_report_editor::Gutter::test_the_fallback_adds_below_the_whole_row_and_a_pair_stays_whole"),
    ("#65", "A section can be renamed in place", "test_report_editor::Sections::test_rename_in_place_as_plain_text"),
    ("#65", "A section moves up or down, with Undo, and a reload keeps the order",
     "test_report_editor::Sections::test_move_by_the_menu_ends_disabled_undo_and_a_reload_keeps_the_order"),
    ("#65", "A hidden section is gone in View, dimmed in Edit, and Undo shows it again",
     "test_report_editor::Sections::test_hide_is_dropped_in_view_dimmed_in_edit_and_undo_shows_it"),
    ("#65", "The report has no sideways scroll at 1400 and 900",
     "test_report_editor::Look::test_no_sideways_scroll_targets_and_text_size_at_1400_and_900"),
    ("#74", "Summary, This week and Next week show in the published file, view-only, at 1400 and 900",
     "test_report_editor::Published::test_the_published_file_draws_the_three_bodies_read_only_at_1400_and_900"),
    ("#74", "A hidden section is not in the published file",
     "test_report_editor::Published::test_the_published_file_has_no_edit_part_and_not_a_hidden_section"),
    ("#63", "Each page has its own address, and Back and Forward step through them",
     "test_router::BuiltPage::test_each_tab_pushes_one_entry_and_back_and_forward_step_through_them"),
    ("#63", "Back with a peek open closes the peek first",
     "test_router::BuiltPage::test_back_with_a_peek_open_closes_it_first_and_forward_reopens_it"),
    ("#63", "A filter change adds no history entry",
     "test_work_filters::RealBrowser::test_a_filter_click_changes_f_in_the_address_by_replace_and_adds_no_history_entry"),
    ("#63", "Scrolling adds no history entry", "test_router::BuiltPage::test_scroll_resize_escape_and_repeated_calls_add_no_entry"),
    ("#63", "A reload opens the same page, project and peek", "test_router::BuiltPage::test_a_reload_keeps_the_page_the_project_and_the_peek"),
    ("#63", "Back from the first page leaves clark as normal", "test_router::BuiltPage::test_back_from_the_first_entry_leaves_clark_as_normal"),
    ("#63", "The published file's tabs step with Back and Forward too",
     "test_router::FileUrl::test_the_built_page_pushes_hash_only_entries_from_a_file_url"),
    ("#64", "Open, Closed and All show counts that match the list at 1400 and 900",
     "test_work_filters::RealBrowser::test_the_switch_counts_equal_the_list_after_each_filter_at_1400_and_900_px"),
    ("#64", "A second filter opens with one click, and a second click on it closes it",
     "test_work_filters::RealBrowser::test_a_second_filter_opens_with_one_click_and_a_second_click_on_it_closes_it"),
    ("#64", "Active filters show as chips, and Clear all brings the rows back",
     "test_work_filters::RealBrowser::test_nothing_matching_says_so_and_clear_all_brings_the_rows_back"),
    ("#64", "The Add button grows to its words on hover and on focus",
     "test_work_filters::RealBrowser::test_the_add_button_grows_to_its_words_on_hover_and_on_keyboard_focus"),
    ("#64", "The Add button's word follows the type switch",
     "test_work_filters::RealBrowser::test_the_add_button_follows_the_type_switch_and_offers_menus"),
    ("#64", "The profile circle's menu opens Settings", "test_profile_menu::ProfileMenu::test_C_the_settings_entry_opens_settings"),
    ("#64", "Every colour the page uses has a dark value",
     "test_work_filters::RealBrowser::test_dark_tokens_are_there_and_differ_from_light_and_the_profile_tokens_are_neutral"),
    ("#64", "Button text is readable in dark mode", "test_dark_contrast::DarkBrandBlue::test_button_text_on_the_brand_colour_passes_aa"),
    ("#43", "The Publish dialog shows Local always on and To client unticked", "test_publish_dialog::Dialog::test_C_dialog_defaults"),
    ("#43", "To client is unticked again every time the dialog opens",
     "test_publish_dialog::Dialog::test_C_reopen_is_unticked_after_a_client_publish"),
    ("#43", "To client is disabled, with its words, until a client folder is set",
     "test_publish_dialog::NoFolder::test_C_to_client_is_disabled_with_the_exact_words_until_a_folder_is_set"),
    ("#43", "The dialog fits at 900", "test_publish_dialog::Dialog::test_C_fits_at_900"),
    ("#43", "After a publish the message and the report bar say what happened",
     "test_publish_dialog::Dialog::test_C_result_message_and_report_bar"),
    ("#43", "Settings has the client folder field, and it fits at 900", "test_publish_dialog::Settings::test_C_settings_folder_field"),
    ("#45", "Project health takes the room the other tiles leave, and they sit at the right",
     "test_glance_tiles::Tiles::test_project_health_is_two_tile_widths_and_the_tiles_follow_it_from_the_left"),
    ("#45", "Each tile's number matches the demo data and opens that list",
     "test_glance_tiles::Tiles::test_each_tile_number_is_the_list_it_opens_and_the_chips_say_what_it_counts"),
    ("#45", "Each tile says its state in words, never only a colour",
     "test_glance_tiles::Words::test_the_words_are_plain_and_never_a_colour_name"),
    ("#127", "Each Excel sheet has a dropdown on every fixed-value column", "test_excel_lists::Lists::test_actions"),
    ("#127", "Risks and issues has its dropdowns", "test_excel_lists::Lists::test_risks_and_issues"),
    ("#127", "Decisions has its dropdowns", "test_excel_lists::Lists::test_decisions"),
    ("#127", "Milestones has its dropdowns", "test_excel_lists::Lists::test_milestones"),
    ("#127", "Use cases has its dropdowns", "test_excel_lists::Lists::test_use_cases"),
    ("#127", "A value changed in Excel takes its colour",
     "test_excel_format::Formatting::test_a_changed_value_gets_the_matching_colour"),
    ("#127", "An overdue date turns red", "test_excel_format::Formatting::test_overdue_is_a_formula_rule_on_the_due_column"),
    ("#128", "The ID column is shaded and nothing is locked (the ruling on #128)",
     "test_excel::ExcelTests::test_the_id_column_is_shaded_and_nothing_is_locked_or_protected"),
    ("#133", "The brand mark is on the Excel Cover", "test_excel_picture::InTheWorkbook::test_a_generated_logo_is_embedded_byte_for_byte_on_the_cover"),
    ("#133", "The brand mark sits at the right of the Cover's band",
     "test_excel_picture::InTheWorkbook::test_the_drawing_anchors_at_the_right_of_the_band_scaled_to_the_row"),
    ("#143", "The sheets and headers have the new names", "test_excel::ExcelTests::test_each_sheet_and_its_headers"),
    ("#129", "The import plan names the ID a new row gets",
     "test_excel_import_ids::IdsAndPlan::test_an_empty_id_gets_the_next_free_id_and_the_plan_line_names_it"),
    ("#129", "A changed ID is refused for that row, in words, and the others apply",
     "test_excel_import_ids::NewItems::test_a_changed_id_is_refused_for_that_row_and_the_others_apply"),
    ("#135", "Closing an item raised in the future is refused in plain words",
     "test_changes::Items::test_closing_or_cancelling_an_item_raised_in_the_future_says_so_in_plain_words_and_writes_nothing"),
]

WITH_165 = [
    ("#67", "In View there are no pickers, and a double click on a row opens the peek (a single click selects it since #195)",
     "test_inline_edits::Live::test_view_has_no_pickers_and_a_row_double_click_opens_the_peek"),
    ("#67", "Status changes in place by click and by keyboard, one step with Undo", "test_inline_edits::Live::test_status_by_click_and_keyboard"),
    ("#67", "Priority changes in place, one step with Undo",
     "test_inline_edits::Live::test_priority_by_click_and_by_keyboard_one_step_with_undo_and_esc_leaves_it"),
    ("#67", "Owner changes in place", "test_inline_edits::Live::test_owner_by_typing_by_choosing_and_by_keyboard_and_esc_leaves_it"),
    ("#67", "Due changes in place", "test_inline_edits::Live::test_due_by_quick_choice_by_the_month_and_by_keyboard_in_one_panel"),
    ("#135", "The page shows the refusal in its own words", "test_inline_edits::Live::test_a_refusal_is_said_in_the_pages_words"),
]

# Covered here (the classes below).
NEW = [
    ("#67", "The top bar stays in view when a long page is scrolled, at 1400 and 900, light and dark",
     "test_v020::StickyBar::test_the_top_bar_stays_in_view_when_a_long_page_is_scrolled"),
    ("#64", "In dark mode every page is dark, with no light patch left and no sideways scroll, at 1400 and 900",
     "test_v020::DarkMode::test_every_page_is_dark_with_no_light_patch_and_no_sideways_scroll"),
]

# Not on main yet: (item, check, where it is being built).
WAITING = [
    ("#42", "The peek opens on a row at once, with its fields and Activity", "PR #78"),
    ("#42", "The peek's width can be dragged and is remembered", "PR #78"),
    ("#42", "Sneak peek opens with //, the sparkle and the foot line; Esc returns focus", "PR #78"),
    ("#42", "Apply shows a toast with Undo, and the changed fields flash", "PR #78"),
    ("#42", "In View and in the published file the peek shows fields only", "PR #78"),
    ("#44", "The timeline shows each milestone at its date; zoom; the six state colours", "PR #75"),
    ("#44", "The rail list shows 5 milestones, then Show all", "PR #75"),
    ("#44", "A slipped milestone shows its slip marker with the days", "PR #75"),
    ("#44", "Timeline and Calendar switch, with the Legend under both", "PR #75"),
    ("#136", "Movement lists each date change in plain words", "no PR yet"),
    ("#45", "The health pill cycles or picks the health, with Undo; the reason is edited in place", "PR #186"),
    ("#45", "The use case strip's status words line up in one column at both widths", "PR #186"),
    ("#45", "A use case row opens its standing and linked items in place", "PR #186"),
    ("#45", "Tiles can be reordered and hidden in Edit, with Undo", "PR #186"),
    ("#45", "The tiles and the use case summary appear in the published page, view-only", "PR #186"),
    ("#66", "Every rich field uses the one editor (toolbar, bubble, / menu)", "PR #53 (the cleaner); the editor has no PR yet"),
    ("#67", "The eye hides a row from the published page, with Undo", "no PR yet"),
    ("#67", "The minimap and the picker on the report itself (their parts are tested alone by test_picker_minimap)", "no PR yet"),
    ("#74", "Supporting Documents: add, edit, hide and move a link", "no PR yet"),
    ("#74", "The Summary, This week and Next week bodies are edited in place", "waits for #66"),
    ("#64", "The profile circle shows the user's initials", "no PR yet"),
    ("#64", "Dark mode is in the profile menu", "no PR yet"),
    ("#64", "Import and export as icons with a tooltip", "no PR yet"),
    ("#64", "With the peek open, a click on another item moves it there", "PR #78"),
    ("#64", "The published page's detail closes on an outside click", "no PR yet"),
    ("#64", "The eye on Work items rows, with Undo", "no PR yet"),
    ("#126", "Archive and Restore, and Show archived, on the page", "no PR yet (the prototype is PR #181)"),
    ("#63", "Back and Forward with a menu or a picker open", "PR #108"),
]

# Judgement or live only: (item, check, kind, why it stays with a person).
WALK_THROUGH = [
    ("#63", "A two-finger swipe on the trackpad goes Back and Forward", "live only",
     "the browser turns the swipe into Back; headless Chrome has no trackpad. What the page does on Back is tested (test_router)"),
    ("#63", "The mouse's back and forward buttons, and the keyboard's Back and Forward", "live only",
     "these are the browser's own controls, not the page's; the page's side of them is the same Back and Forward as above"),
    ("#43", "A To client publish arrives in the real client folder and syncs to the client", "live only",
     "needs the real OneDrive-synced folder; the copy and its SHA-256 are tested in test_to_client"),
    ("#43", "The published file reads well and looks right to a client", "judgement", "only a person can say it reads well"),
    ("#127", "In Excel, the dropdown arrows show and a wrong value gets the plain error box", "live only",
     "openpyxl reads the rules in the file; only Excel draws them"),
    ("#127", "In Excel, a value changed by hand recolours itself", "live only", "the same: the rules are tested, Excel draws them"),
    ("#128", "In Excel, the ID column is shaded and its note reads well", "live only", "the same"),
    ("#133", "The brand mark on the Cover looks right", "judgement", "its bytes and place are tested; how it looks is a person's call"),
    ("#129", "The import plan's lines read well", "judgement", "the words are pinned by tests; whether they read well is a person's call"),
    ("#64", "Dark mode is pleasant to read", "judgement",
     "contrast is measured (test_dark_contrast) and light patches are found (test_v020); taste is a person's"),
    ("#65", "Dragging a section feels right", "judgement", "the drop places are tested; the feel is a person's"),
    ("#86", "The restore steps can be followed once, as written", "live only",
     "a restore into a fresh folder is tested (test_backup); following the words on a real laptop is not"),
]

TABLES = {"COVERED": COVERED, "WITH_165": WITH_165, "NEW": NEW}


def tearDownModule():
    shutil.rmtree(EMPTY_BRANDING, ignore_errors=True)


def names_in(path):
    """{class name: {test method names}} in a test file, read without importing it."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {c.name: {f.name for f in c.body if isinstance(f, ast.FunctionDef)} for c in tree.body if isinstance(c, ast.ClassDef)}


class Tables(unittest.TestCase):
    """The lists above are the release's hand checks: each pointer must name a real test, so a renamed or removed test shows."""

    def missing(self, rows):
        out = []
        for item, check, where in rows:
            name, cls, test = where.split("::")
            path = TESTS / (name + ".py")
            found = names_in(path) if path.is_file() else {}
            if test not in found.get(cls, ()):
                out.append(f"{item} {check}: {where}")
        return out

    def test_every_covering_test_named_here_exists(self):
        self.assertEqual(self.missing(COVERED + NEW), [])

    def test_the_checks_that_land_with_pr_165_are_tested_there(self):
        if not (TESTS / "test_inline_edits.py").is_file():
            self.skipTest("lands with #165: tests/test_inline_edits.py (the Work items cells that change in place) is only in "
                          "PR #165, so these checks are not on this tree yet")
        self.assertEqual(self.missing(WITH_165), [])

    def test_each_check_is_in_one_list_only_and_each_walk_through_check_says_why(self):
        checks = [c for rows in (COVERED, WITH_165, NEW, WAITING) for _, c, _ in rows] + [c for _, c, _, _ in WALK_THROUGH]
        self.assertEqual(sorted(c for c in set(checks) if checks.count(c) > 1), [])
        for item, check, kind, why in WALK_THROUGH:
            self.assertIn(kind, ("judgement", "live only"), check)
            self.assertTrue(why.strip(), check)


class Browser(unittest.TestCase):
    """The real server over the demo store, and the committed page in headless Chrome."""

    @classmethod
    def setUpClass(cls):
        need_chrome()
        cls.store, cls.folder, ids = load_demo()
        cls.projects = cls.store.read("projects")
        cls.data = {p["code"]: cls.store.data_for(p["code"]) for p in cls.projects}
        cls.code = max(ids, key=lambda c: len(ids[c]))              # the project with the most work items: the longest list

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        shutil.rmtree(str(cls.folder), ignore_errors=True)

    def serve(self):
        s = Running(data_for=lambda code: copy.deepcopy(self.data.get(code)), projects=lambda: self.projects,
                    page_html=lambda: page.page_html(EMPTY_BRANDING))
        self.addCleanup(s.close)
        return s

    def load(self, cdp, port, view, width, theme, height=900):
        sid = page_target(cdp)
        cdp.call("Page.enable", {}, sid)
        cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": FIXED_DATE}, sid)
        cdp.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False}, sid)
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{port}/#{view}&p={self.code}"}, sid)
        drawn = "!!document.querySelector('header.top') && !!document.querySelector(%s)" % json.dumps(DRAWN[view])
        self.assertTrue(wait(lambda: cdp.js(drawn, sid)), f"{view} drew")
        if theme == "dark":
            cdp.js("document.documentElement.dataset.theme = 'dark'", sid)
            self.assertEqual(cdp.js("getComputedStyle(document.documentElement).colorScheme", sid), "dark", "dark mode is on")
        return sid


# The top bar's place and what is drawn at its middle, after the page is scrolled to its end.
TOP_BAR = """(() => {
  window.scrollTo(0, document.documentElement.scrollHeight);
  const bar = document.querySelector('header.top'), b = bar.getBoundingClientRect();
  const at = document.elementFromPoint(Math.round(b.left + b.width / 2), Math.round(b.top + b.height / 2));
  return { scrolled: Math.round(window.scrollY), top: Math.round(b.top), height: Math.round(b.height),
           onTop: !!(at && bar.contains(at)), page: document.documentElement.scrollHeight, view: window.innerHeight };
})()"""

# Every box of a real size whose own background is opaque and light, in dark mode; the page's own background; the heading's colour.
LIGHT_PATCHES = """(() => {
  const lum = (c) => {
    const m = /rgba?\\(([^)]+)\\)/.exec(c || ''); if (!m) return null;
    const p = m[1].split(/[\\s,\\/]+/).filter(Boolean).map(Number), a = p.length > 3 ? p[3] : 1;
    if (a < 0.9) return null;
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(p[0]) + 0.7152 * f(p[1]) + 0.0722 * f(p[2]);
  };
  const patches = [];
  for (const e of document.querySelectorAll('body *')) {
    const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
    if (r.width * r.height < 4000 || cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
    const l = lum(cs.backgroundColor);
    if (l !== null && l > 0.3) patches.push(e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') +
      (typeof e.className === 'string' && e.className ? '.' + e.className.trim().split(/\\s+/).join('.') : '') + ' ' + cs.backgroundColor);
  }
  const html = document.documentElement, body = document.body;
  const ground = lum(getComputedStyle(body).backgroundColor) ?? lum(getComputedStyle(html).backgroundColor);
  const h1 = document.querySelector('h1');
  return { patches, ground, heading: h1 ? lum(getComputedStyle(h1).color) : null,
           sideways: html.scrollWidth > window.innerWidth };
})()"""


class StickyBar(Browser):
    def test_the_top_bar_stays_in_view_when_a_long_page_is_scrolled(self):
        """#67: the sticky bar stays visible at both widths. The bar is clark's top bar (the report's own bar comes with the
        minimap, see WAITING). The window is 600 px high so the Work items list and the report are longer than it."""
        s = self.serve()
        for view in ("work", "dashboard"):
            for width in WIDTHS:
                for theme in THEMES:
                    with self.subTest(page=view, width=width, theme=theme), chrome() as cdp:
                        sid = self.load(cdp, s.port, view, width, theme, height=600)
                        got = cdp.js(TOP_BAR, sid)
                        self.assertGreater(got["page"], got["view"] + 100, "the page is longer than the window, so it scrolls")
                        self.assertGreater(got["scrolled"], 0, "the page scrolled")
                        self.assertEqual(got["top"], 0, "the top bar is still at the top of the window")
                        self.assertGreater(got["height"], 30, "and has its height")
                        self.assertTrue(got["onTop"], "and nothing is drawn over it")


class DarkMode(Browser):
    def test_every_page_is_dark_with_no_light_patch_and_no_sideways_scroll(self):
        """#64: dark mode for the whole editor. In dark mode no box of a real size keeps a light background, the page's
        ground is dark and the heading is light; and nothing scrolls sideways. In light mode the same pages have a light ground,
        so the check is not passing by accident."""
        s = self.serve()
        for view in PAGES:
            for width in WIDTHS:
                with self.subTest(page=view, width=width), chrome() as cdp:
                    sid = self.load(cdp, s.port, view, width, "light")
                    light = cdp.js(LIGHT_PATCHES, sid)
                    self.assertGreater(light["ground"], 0.5, "in light mode the page is light")
                    self.assertFalse(light["sideways"], "no sideways scroll in light mode")
                    cdp.js("document.documentElement.dataset.theme = 'dark'", sid)
                    self.assertTrue(wait(lambda: (cdp.js(LIGHT_PATCHES, sid)["ground"] or 1) < 0.1), "the page's ground turns dark")
                    dark = cdp.js(LIGHT_PATCHES, sid)
                    self.assertEqual(dark["patches"], [], "no light patch is left in dark mode")
                    self.assertGreater(dark["heading"], 0.4, "the heading is light on the dark page")
                    self.assertFalse(dark["sideways"], "no sideways scroll in dark mode")


if __name__ == "__main__":
    unittest.main()
