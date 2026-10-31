"""#179: Appearance (System, Light, Dark) in Settings › Personal and as the same Appearance group in the profile menu, in a real browser at 1400 and
900 px. Run: python3 dev/run_tests.py test_appearance

The choice is one setting for this person on this computer, remembered in the browser as the section style is and applied as
`data-theme` on the page (Light none, Dark "dark", System "auto", which the page's own colour-scheme rule answers). What is asserted:
the group and its words; System is the default and follows the computer both ways with no reload while Light and Dark do not; the
menu has the same three choices, in the same order, below the separator, the one in use marked; a change in either place shows in
the other at once; a reload keeps it; every page is dark when Dark is chosen, with no sideways scroll; a published file never has it.
Chrome is required: these tests fail, never skip, without it.
"""
import re
import unittest

from _paths import SRC
from test_publish_dialog import Base, PAGE_SRC
from test_server import chrome

from clark import page

WIDTHS = (1400, 900)
ORDER = ["System", "Light", "Dark"]


def scheme(p, value):
    p.cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": value}]}, p.sid)


class Appearance(Base):
    def open_settings(self, p):
        p.js("document.querySelector('#profile-btn').click()")
        p.until("!!document.querySelector('#profile-menu')", "the menu opened")
        p.js("document.querySelector('#profile-menu [data-kind=settings]').click()")
        p.until("!!document.querySelector('#personal')", "Settings › Personal drew")

    def open_menu(self, p):
        p.js("document.querySelector('#profile-btn').click()")
        p.until("!!document.querySelector('#profile-menu')", "the menu opened")

    def in_settings(self, p):
        return p.js("[...document.querySelectorAll('#personal [data-appearance] input')].filter(i => i.checked).map(i => i.value)")

    def in_menu(self, p):
        return p.js("[...document.querySelectorAll('#profile-menu [role=menuitemradio]')].filter(i => i.getAttribute('aria-checked') === 'true').map(i => i.textContent.replace('✓', ''))")

    def paper(self, p):
        """The page's own background, as it is drawn now."""
        return p.js("getComputedStyle(document.body).backgroundColor")

    def lightness(self, p):
        rgb = [int(x) for x in re.findall(r"\d+", self.paper(p))[:3]]
        return sum(rgb) / 3

    def test_C_settings_has_the_appearance_group_with_system_as_the_default(self):
        for w in WIDTHS:
            with self.subTest(width=w), chrome() as cdp:
                p = self.page(cdp)
                p.width(w)
                self.open_settings(p)
                self.assertEqual(p.js("document.querySelector('#personal [data-appearance] legend').textContent"), "Appearance")
                self.assertEqual(p.js("[...document.querySelectorAll('#personal [data-appearance] b')].map(b => b.textContent)"), ORDER)
                self.assertEqual(self.in_settings(p), ["system"])
                self.assertEqual(p.js("document.querySelector('#personal [data-appearance] input[value=system]').closest('label').textContent"),
                                 "SystemFollows your Mac's setting.")
                self.assertEqual(p.js("document.documentElement.dataset.theme"), "auto")
                self.assertTrue(p.js("document.documentElement.scrollWidth <= window.innerWidth"), "no sideways scroll")

    def test_C_system_follows_the_computer_both_ways_with_no_reload_and_light_and_dark_do_not(self):
        with chrome() as cdp:
            p = self.page(cdp)
            self.open_settings(p)
            p.js("window.__same = 1")
            scheme(p, "dark")
            p.until("window.__same === 1", "no reload")
            dark = self.lightness(p)
            scheme(p, "light")
            light = self.lightness(p)
            self.assertLess(dark, 90, "System: dark when the computer is dark")
            self.assertGreater(light, 200, "System: light when the computer is light")
            self.assertEqual(p.js("window.__same"), 1, "the same page throughout: no reload")
            for choice, want in (("light", "light"), ("dark", "dark")):
                p.js(f"document.querySelector('#personal [data-appearance] input[value={choice}]').click()")
                for computer in ("dark", "light"):
                    scheme(p, computer)
                    self.assertEqual("dark" if self.lightness(p) < 90 else "light", want, f"{choice} chosen, computer {computer}")

    def test_C_the_menu_has_dark_mode_with_the_same_three_in_the_same_order_below_the_separator(self):
        for w in WIDTHS:
            with self.subTest(width=w), chrome() as cdp:
                p = self.page(cdp)
                p.width(w)
                self.open_menu(p)
                roles = p.js("[].map.call(document.querySelector('#profile-menu').children, function(e){return e.getAttribute('role')})")
                self.assertEqual(roles[:8], ["menuitem", "menuitem", "menuitem", "menuitem", "separator", "presentation", "menuitemradio", "menuitemradio"])
                self.assertEqual(p.js("document.querySelectorAll('#profile-menu .lab')[0].textContent"), "Appearance", "the group has the same name in the menu as in Settings")
                self.assertEqual(p.js("[...document.querySelectorAll('#profile-menu [role=menuitemradio]')].map(i => i.textContent.replace('✓', ''))"), ORDER)
                self.assertEqual(self.in_menu(p), ["System"], "the one in use is marked")

    def test_C_one_setting_two_places_both_ways_with_no_reload(self):
        with chrome() as cdp:
            p = self.page(cdp)
            self.open_settings(p)
            p.js("window.__same = 1")
            p.js("document.querySelector('#personal [data-appearance] input[value=dark]').click()")
            self.open_menu(p)
            self.assertEqual(self.in_menu(p), ["Dark"], "a change in Settings shows in the menu")
            p.js("document.querySelector('#profile-menu [data-kind=look-light]').click()")
            p.until("!document.querySelector('#profile-menu')", "picking closed the menu")
            self.assertEqual(self.in_settings(p), ["light"], "a change in the menu shows in Settings")
            self.assertEqual(p.js("document.documentElement.dataset.theme || 'none'"), "none", "Light sets no attribute")
            self.assertEqual(p.js("window.__same"), 1)

    def test_C_the_choice_is_remembered_across_a_reload(self):
        with chrome() as cdp:
            p = self.page(cdp)
            self.open_menu(p)
            p.js("document.querySelector('#profile-menu [data-kind=look-dark]').click()")
            p.until("document.documentElement.dataset.theme === 'dark'", "Dark applied")
            self.assertEqual(p.js("localStorage.getItem('clark.appearance')"), "dark")
            p.js("location.reload()")
            p.until("!!document.querySelector('#profile-btn') && document.documentElement.dataset.theme === 'dark'", "Dark again after a reload")
            self.open_menu(p)
            self.assertEqual(self.in_menu(p), ["Dark"])

    def test_C_with_dark_chosen_every_page_is_dark_and_does_not_scroll_sideways(self):
        for w in WIDTHS:
            with self.subTest(width=w), chrome() as cdp:
                p = self.page(cdp)
                p.width(w)
                scheme(p, "light")                                   # the computer is light: only the choice can make it dark
                self.open_menu(p)
                p.js("document.querySelector('#profile-menu [data-kind=look-dark]').click()")
                p.until("document.documentElement.dataset.theme === 'dark'", "Dark applied")
                for view in ("dashboard", "work", "milestones"):
                    p.js(f"document.querySelector('[data-view={view}]').click()")
                    p.until(f"!!document.querySelector('#{ 'report' if view == 'dashboard' else view }')", f"{view} drew")
                    self.assertLess(self.lightness(p), 90, f"{view} is dark")
                    self.assertTrue(p.js("document.documentElement.scrollWidth <= window.innerWidth"), f"{view}: no sideways scroll")
                self.open_settings(p)
                self.assertLess(self.lightness(p), 90, "Settings is dark")
                self.assertTrue(p.js("document.documentElement.scrollWidth <= window.innerWidth"), "Settings: no sideways scroll")


class Source(unittest.TestCase):
    def test_a_published_file_has_no_appearance_setting(self):
        view = page.VIEW_PAGE.read_text(encoding="utf-8")
        self.assertNotIn("clark.appearance", view)
        self.assertNotIn("data-appearance", view)
        for path in PAGE_SRC.rglob("*.js*"):
            if path.name == "appearance.js":
                continue
            text = path.read_text(encoding="utf-8")
            if "stores/appearance.js" in text:
                self.assertIn("/edit/", path.as_posix(), f"{path.name} is not an Edit part but imports the appearance setting")

    def test_the_words_are_pinned(self):
        text = (PAGE_SRC / "edit" / "Personal.jsx").read_text(encoding="utf-8")
        for words in ('["system", "System", "Follows your Mac\'s setting."]', '["light", "Light", "Always light."]', '["dark", "Dark", "Always dark."]',
                      "<legend>Appearance</legend>"):
            self.assertIn(words, text)
        self.assertIn('lab: "Appearance"', (PAGE_SRC / "edit" / "ProfileMenu.jsx").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
