"""#82 (BRD 5.13, FR-120 to FR-124): the Help panel in a real browser, against the real page and routes.

Run: python3 dev/run_tests.py test_help_panel
Headless Chrome through the shared harness (the keychain flags are in it); the page is the real one with fictional demo data.
Only what the page has is shown (src/clark/page/src/help/helpLater.json holds the rest back), so the tabs are checked against
that. Covers: "?" opens Help outside a field and not inside one, Esc returns to the page left, the three tabs, search across all three
tabs, a result opens in place, a link inside Help and a link to a screen, window.clarkPage.help.open to a place (and an unknown
place), and that the published page has no Help. What waits for other items: the profile-menu entry (#64), Publish, Preview and
ask clark links (drawn as plain words until those exist).
"""
import re
import unittest
from pathlib import Path

from _paths import SRC  # noqa: F401  (puts src/ on the path)
from test_report_editor import ALT, Base, Pg  # noqa: F401
from clark import page
from _help_shown import shown_content


def keys_in_help(p):
    return p.js("document.querySelector('#help') ? 1 : 0")


class Panel(Base):
    def in_help(self, cdp):
        p = self.visit(cdp)
        p.key("?", code="Slash", vk=191)
        p.until("!!document.querySelector('#help')", "Help opened on ?")
        return p

    def test_question_mark_opens_and_esc_returns(self):
        from test_server import chrome
        with chrome() as cdp:
            p = self.visit(cdp)
            before = p.js("location.hash")
            self.assertEqual(p.js("document.querySelector('#help') === null"), True)
            p.key("?", code="Slash", vk=191)
            p.until("!!document.querySelector('#help')", "Help opened on ?")
            self.assertEqual(p.js("document.querySelector('#report') === null"), True, "Help is in place of the page")
            self.assertEqual(p.js("location.hash"), before, "opening Help does not move the address")
            p.key("Escape", code="Escape", vk=27)
            p.until("!document.querySelector('#help') && !!document.querySelector('#report')", "Esc returned to the page")

    def test_question_mark_in_a_field_is_just_a_character(self):
        from test_server import chrome
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            p.js("var el=document.querySelector('[data-id] [data-title]'); el.focus()")
            p.key("?", code="Slash", vk=191)
            self.assertEqual(p.js("document.querySelector('#help') === null"), True, "no Help while typing in a title")

    def test_three_tabs_and_what_each_shows_today(self):
        """Only what the page has is shown (helpLater.json): Start here and How do I… say so, Reference has the keys."""
        from test_server import chrome
        with chrome() as cdp:
            p = self.in_help(cdp)
            self.assertEqual(p.js("[...document.querySelectorAll('.hp-tabs [role=tab]')].map(b => b.textContent)"), ["Start here", "How do I…", "Reference"])
            self.assertEqual(p.js("document.querySelectorAll('.hp-job, .hp-steps li, .hp-first li').length"), 0, "no held entry on Start here")
            self.assertTrue(p.js("!!document.querySelector('#hp-later')"))
            p.js("document.querySelector('#hpTab-howto').click()")
            p.until("document.querySelectorAll('.hp-task').length > 0", "How do I… has the two tasks the page can do")
            self.assertEqual(p.js("document.querySelectorAll('.hp-task').length"), 2)
            self.assertEqual(p.js("!!document.querySelector('#hp-later')"), False)
            p.js("document.querySelector('#hpTab-reference').click()")
            p.until("document.querySelectorAll('.hp-ref').length > 0", "Reference drew")
            self.assertEqual(p.js("document.querySelectorAll('.hp-ref').length"), len(shown_content()["reference"]["sections"]))
            self.assertEqual(p.js("document.querySelector('#hp-ref-keys .hp-keys tbody').children.length"), len(shown_content()["reference"]["keys"]))
            self.assertEqual(p.js("document.querySelector('#hp-ref-keys .hp-keys').textContent.indexOf('Sneak peek')"), -1)
            self.assertEqual(p.js("document.querySelector('.hp-idx') && document.querySelectorAll('.hp-idx a').length"), 2)

    def test_search_finds_what_is_shown_and_opens_in_place_and_not_what_is_held(self):
        from test_server import chrome
        with chrome() as cdp:
            p = self.in_help(cdp)
            p.js("var q=document.querySelector('#hpQ'); q.focus()")
            p.type("shortcuts")
            p.until("document.querySelectorAll('#hpRes a.hp-r').length > 0", "results")
            self.assertEqual(p.js("[...document.querySelectorAll('#hpRes .hp-resg h3')].map(h => h.textContent)"), ["Reference"])
            p.js("document.querySelector('#hpRes a.hp-r').click()")
            p.until("!document.querySelector('#hpRes') && !!document.querySelector('.hp-found')", "the result opened in place and flashed")
            for word in ("peek", "publish", "sneak"):
                p.js("var q=document.querySelector('#hpQ'); q.value=''; q.focus()")
                p.type(word)
                p.until("!!document.querySelector('.hp-none')", f"a held word ({word}) finds nothing")
            self.assertIn("Nothing in Help for", p.js("document.querySelector('.hp-none b').textContent"))

    def test_a_contents_link_opens_its_place_and_a_held_place_is_not_one(self):
        from test_server import chrome
        with chrome() as cdp:
            p = self.in_help(cdp)
            p.js("document.querySelector('#hpTab-reference').click()")
            p.until("!!document.querySelector('.hp-idx a')", "the contents list")
            p.js("document.querySelector('.hp-idx a[data-hlink=ref-keys]').click()")
            p.until("!!document.querySelector('#hp-ref-keys.hp-found')", "a contents link opens its place and flashes it")
            self.assertEqual(p.js("document.querySelector('[data-hlink=ref-peek], [data-hlink=howto-use-the-board], [data-hgo]')"), None)
            self.assertTrue(p.js("location.hash.indexOf('#dashboard') === 0"), "the page left is the Dashboard")

    def test_focus_goes_back_to_what_had_it_when_help_closes(self):                     # MEDIUM
        from test_server import chrome
        with chrome() as cdp:
            p = self.visit(cdp)
            p.edit()
            p.js("var h=document.querySelector('.secs .sec[data-id] [data-drag]'); window.__id=h.closest('.sec').dataset.id; h.focus()")
            p.key("?", code="Slash", vk=191)
            p.until("!!document.querySelector('#help')", "Help opened from a section's handle")
            p.key("Escape", code="Escape", vk=27)
            p.until("!document.querySelector('#help') && document.activeElement && document.activeElement.hasAttribute('data-drag')", "Esc put focus back on the handle")
            self.assertEqual(p.js("document.activeElement.closest('.sec').dataset.id"), p.js("window.__id"))
            # the Close button does the same, and a part of the top bar is the same element still
            p.js("document.querySelector('.mode[data-mode=view]').focus()")
            p.key("?", code="Slash", vk=191)
            p.until("!!document.querySelector('#help')", "Help opened from the View button")
            p.js("document.querySelector('#hpClose').click()")
            p.until("!document.querySelector('#help') && document.activeElement && document.activeElement.dataset.mode === 'view'", "Close put focus back on View")

    def test_esc_clears_the_search_from_a_result_or_a_tab_then_closes(self):            # MEDIUM
        from test_server import chrome
        with chrome() as cdp:
            p = self.in_help(cdp)
            for where in ("result", "tab"):
                p.js("var q=document.querySelector('#hpQ'); q.focus()")
                p.type("keys")
                p.until("document.querySelectorAll('#hpRes a.hp-r').length > 0", "results")
                p.js("(%s).focus()" % ("document.querySelector('#hpRes a.hp-r')" if where == "result" else "document.querySelector('#hpTab-start')"))
                self.assertNotEqual(p.js("document.activeElement.id"), "hpQ")
                p.key("Escape", code="Escape", vk=27)
                p.until("!document.querySelector('#hpRes') && document.querySelector('#hpQ').value === ''", f"Esc on a {where} cleared the search")
                self.assertTrue(p.js("!!document.querySelector('#help')"), "and Help stayed open")
            p.key("Escape", code="Escape", vk=27)
            p.until("!document.querySelector('#help')", "a second Esc closes Help")

    def test_open_help_at_a_place(self):
        from test_server import chrome
        with chrome() as cdp:
            p = self.visit(cdp)
            p.js("window.clarkPage.help.open('ref-keys')")
            p.until("!!document.querySelector('#hp-ref-keys.hp-found')", "opened at the keys")
            self.assertEqual(p.js("document.querySelector('#hpTab-reference').getAttribute('aria-selected')"), "true")
            p.js("window.clarkPage.help.close()")
            p.until("!document.querySelector('#help')", "closed")
            p.js("window.clarkPage.help.open('howto-nothing-here')")
            p.until("!!document.querySelector('#help')", "an unknown place still opens Help")
            self.assertEqual(p.js("document.querySelector('.hp-found')"), None, "and flashes nothing")

    def test_the_tab_used_last_is_remembered_and_a_new_page_closes_help(self):
        from test_server import chrome
        with chrome() as cdp:
            p = self.in_help(cdp)
            p.js("document.querySelector('#hpTab-howto').click()")
            p.js("window.clarkPage.help.close()")
            p.js("window.clarkPage.help.open()")
            p.until("document.querySelector('#hpTab-howto') && document.querySelector('#hpTab-howto').getAttribute('aria-selected') === 'true'", "opened on the tab used last")
            p.js("location.reload()")
            p.until("!!window.clarkPage && !!document.querySelector('#report')", "reloaded")
            p.key("?", code="Slash", vk=191)
            p.until("!!document.querySelector('#hpTab-howto') && document.querySelector('#hpTab-howto').getAttribute('aria-selected') === 'true'", "a reload still opens on the tab used last")
            p.js("window.clarkPage.show('work')")
            p.until("!document.querySelector('#help')", "going to another page closes Help")


class Published(unittest.TestCase):
    def test_the_published_page_has_no_help(self):
        text = (Path(page.__file__).parent / "page-view.html").read_text(encoding="utf-8")
        text = re.sub(r"data:[a-z0-9/+.-]+;base64,[A-Za-z0-9+/=]+", "data:", text)          # a short word can turn up by chance inside the fonts' base64 data
        for word in ("Twelve jobs", "clark.helpTab", "Search Help", "hpQ", "Your first ten minutes"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
