"""#180: Settings › Personal › About you (Your name, Your email) and the profile menu's top line, in a real browser at 1400 and 900 px.
Run: python3 dev/run_tests.py test_about_you

Both are kept by clark in the data folder's settings.json (not in the browser). What is asserted: the two boxes and their words; saving
when a box is left, a reload keeps them (read from clark, not the browser); the menu's top line shows the name in bold with the email
under it, only the name when there is no email, and with neither the link "Add your name in Settings", which opens Settings and puts
the cursor in the name box; emptying the name brings the link back at once; a fresh store has no "@" anywhere in the menu; a 60
character name and email are cut with an ellipsis on one line each, never widen the menu, and carry the whole text as the tooltip;
a refusal says why in its words, ends "Nothing was saved.", writes nothing and leaves the typed text in its box.
Chrome is required: these tests fail, never skip, without it.
"""
import json
import time
import unittest

from _paths import SRC
from test_publish_dialog import Base, PAGE_SRC
from test_server import chrome

WIDTHS = (1400, 900)
NAME_LINE = "Shown at the top of your menu, and as the name on each change you make. Optional."
EMAIL_LINE = "Optional. Used only to tell which email addresses are your own. clark does not send email."


class AboutYou(Base):
    def saved(self):
        f = self.rig.data_dir / "settings.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

    def open_menu(self, p):
        p.js("document.querySelector('#profile-btn').click()")
        p.until("!!document.querySelector('#profile-menu')", "the menu opened")

    def close_menu(self, p):
        p.js("document.querySelector('#profile-menu').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
        p.until("!document.querySelector('#profile-menu')", "the menu closed")

    def open_settings(self, p):
        self.open_menu(p)
        p.js("document.querySelector('#profile-menu [data-kind=settings]').click()")
        p.until("!!document.querySelector('#about-name')", "About you drew")

    def type_into(self, p, field, text, leave="enter"):
        """Type `text` into the box and leave it: Enter, or a blur (headless Chrome's page has no focus, so a real blur never fires and
        is dispatched)."""
        p.js(f"(() => {{ const el = document.querySelector('#about-{field}'); el.value = {json.dumps(text)}; "
             "el.dispatchEvent(new Event('input', {bubbles: true})); "
             + ("el.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true}));" if leave == "enter"
                else "el.dispatchEvent(new FocusEvent('blur'));") + " })()")

    def wait_saved(self, key, value, seconds=6):
        end = time.time() + seconds
        while time.time() < end:
            if self.saved().get(key) == value:
                return True
            time.sleep(0.1)
        return False

    def top(self, p):
        return p.js("(() => { const w = document.querySelector('#profile-menu .who'); if (w) return {name: w.querySelector('b').textContent, "
                    "email: (w.querySelector('small') || {}).textContent || '', title: w.title}; "
                    "const l = document.querySelector('#profile-menu .who-link'); return l ? {link: l.textContent} : null; })()")

    def test_C_the_two_boxes_and_their_words_start_empty_and_the_fresh_menu_has_no_at_sign(self):
        for w in WIDTHS:
            with self.subTest(width=w), chrome() as cdp:
                p = self.page(cdp)
                p.width(w)
                self.open_menu(p)
                self.assertEqual(self.top(p), {"link": "Add your name in Settings"})
                self.assertNotIn("@", p.js("document.querySelector('#profile-menu').innerText"))
                self.close_menu(p)
                self.open_settings(p)
                self.assertEqual(p.js("document.querySelector('[data-about-you] legend').textContent"), "About you")
                self.assertEqual(p.js("[...document.querySelectorAll('[data-about-you] label')].map(l => l.textContent)"), ["Your name", "Your email"])
                self.assertEqual(p.js("[...document.querySelectorAll('[data-about-you] small')].map(l => l.textContent)"), [NAME_LINE, EMAIL_LINE])
                self.assertEqual(p.js("[document.querySelector('#about-name').value, document.querySelector('#about-email').value]"), ["", ""])
                self.assertEqual(self.saved(), {})
                self.assertEqual(p.js("Object.keys(localStorage).filter(k => /name|email|profile/i.test(k))"), [], "nothing is kept in the browser")

    def test_C_a_name_and_an_email_are_saved_by_clark_shown_at_once_and_kept_over_a_reload(self):
        with chrome() as cdp:
            p = self.page(cdp)
            self.open_settings(p)
            self.type_into(p, "name", "Sam Lee")
            self.type_into(p, "email", "sam@example.test")
            p.until("document.querySelector('#about-name').value === 'Sam Lee'", "the box holds it")
            self.assertTrue(self.wait_saved("profile_email", "sam@example.test"), "saved by clark")
            self.assertEqual(self.saved(), {"profile_email": "sam@example.test", "profile_name": "Sam Lee"})
            self.open_menu(p)
            self.assertEqual(self.top(p), {"name": "Sam Lee", "email": "sam@example.test", "title": "Sam Lee\nsam@example.test"})
            self.assertEqual(p.js("getComputedStyle(document.querySelector('#profile-menu .who b')).fontWeight >= 500"), True)
            self.close_menu(p)
            p.js("location.reload()")
            p.until("!!document.querySelector('#profile-btn')", "the page again")
            self.open_menu(p)
            p.until("!!document.querySelector('#profile-menu .who')", "the menu shows who you are after a reload (read from clark)")
            self.assertEqual(self.top(p)["name"], "Sam Lee")

    def test_C_a_name_alone_shows_only_the_name_and_emptying_it_brings_the_link_back_at_once(self):
        with chrome() as cdp:
            p = self.page(cdp)
            self.open_settings(p)
            self.type_into(p, "name", "Sam Lee", leave="blur")
            self.assertTrue(self.wait_saved("profile_name", "Sam Lee"), "leaving the box saves it")
            self.open_menu(p)
            p.until("!!document.querySelector('#profile-menu .who')", "the name shows")
            self.assertEqual(self.top(p), {"name": "Sam Lee", "email": "", "title": "Sam Lee"})
            self.close_menu(p)
            self.type_into(p, "name", "")
            self.assertTrue(self.wait_saved("profile_name", ""))
            self.open_menu(p)
            p.until("!!document.querySelector('#profile-menu .who-link')", "the link is back")
            self.assertEqual(self.top(p), {"link": "Add your name in Settings"})

    def test_C_the_link_opens_settings_and_puts_the_cursor_in_the_name_box(self):
        with chrome() as cdp:
            p = self.page(cdp)
            self.open_menu(p)
            p.js("document.querySelector('#profile-menu .who-link').click()")
            p.until("!!document.querySelector('#about-name')", "Settings › Personal drew")
            p.until("document.activeElement && document.activeElement.id === 'about-name'", "the name box has the cursor")

    def test_C_long_values_are_cut_on_one_line_each_and_never_widen_the_menu(self):
        name, email = "N" * 60, ("e" * 48) + "@example.test"
        self.assertEqual((len(name), len(email)), (60, 61))
        email = ("e" * 47) + "@example.test"
        self.assertEqual(len(email), 60)
        with chrome() as cdp:
            p = self.page(cdp)
            p.width(900)
            self.open_settings(p)
            self.type_into(p, "name", name)
            self.type_into(p, "email", email)
            self.assertTrue(self.wait_saved("profile_email", email))
            self.open_menu(p)
            p.until("!!document.querySelector('#profile-menu .who small')", "both lines show")
            box = "document.querySelector('#profile-menu')"
            b, sm = "document.querySelector('#profile-menu .who b')", "document.querySelector('#profile-menu .who small')"
            shape = {"menu": p.js(f"Math.round({box}.getBoundingClientRect().width)"),
                     "cutName": p.js(f"{b}.scrollWidth > {b}.clientWidth"), "cutEmail": p.js(f"{sm}.scrollWidth > {sm}.clientWidth"),
                     "oneName": p.js(f"{b}.getBoundingClientRect().height < 26"), "oneEmail": p.js(f"{sm}.getBoundingClientRect().height < 26"),
                     "tip": p.js("document.querySelector('#profile-menu .who').title"),
                     "side": p.js("document.documentElement.scrollWidth <= window.innerWidth")}
            self.assertLessEqual(shape["menu"], 282, "the menu stays within 280 px")
            self.assertTrue(shape["cutName"] and shape["cutEmail"], "both are cut")
            self.assertTrue(shape["oneName"] and shape["oneEmail"], "one line each")
            self.assertEqual(shape["tip"], name + "\n" + email, "the whole text is the tooltip")
            self.assertTrue(shape["side"], "no sideways scroll")

    def test_C_a_refusal_says_why_ends_nothing_was_saved_writes_nothing_and_keeps_what_was_typed(self):
        with chrome() as cdp:
            p = self.page(cdp)
            self.open_settings(p)
            self.type_into(p, "name", "Sam Lee")
            self.assertTrue(self.wait_saved("profile_name", "Sam Lee"))
            before = self.saved()
            self.type_into(p, "name", "N" * 61)
            p.until("document.querySelector('#about-name-line').parentElement.querySelector('.fld-bad').textContent !== ''", "the refusal shows")
            self.assertEqual(p.js("document.querySelector('#about-name').closest('.fld').querySelector('.fld-bad').textContent"),
                             "Your name is too long. Use 60 characters or fewer. Nothing was saved.")
            self.assertEqual(p.js("document.querySelector('#about-name').value"), "N" * 61, "what was typed stays in the box")
            self.assertEqual(self.saved(), before, "nothing was written")
            self.type_into(p, "name", "Sam Lee")
            self.type_into(p, "email", "nope")
            p.until("document.querySelector('#about-email').closest('.fld').querySelector('.fld-bad').textContent !== ''", "the email refusal shows")
            self.assertEqual(p.js("document.querySelector('#about-email').closest('.fld').querySelector('.fld-bad').textContent"),
                             "That email address is not complete. Check it, or leave it empty. Nothing was saved.")
            self.assertEqual(self.saved(), before)
            self.assertEqual(p.js("document.querySelector('#about-email').getAttribute('aria-invalid')"), "true")


class Source(unittest.TestCase):
    def test_the_words_are_pinned(self):
        text = (PAGE_SRC / "edit" / "Personal.jsx").read_text(encoding="utf-8")
        for words in ("<legend>About you</legend>", '"Your name"', '"Your email"', NAME_LINE, EMAIL_LINE):
            self.assertIn(words, text)
        self.assertIn("Add your name in Settings", (PAGE_SRC / "edit" / "ProfileMenu.jsx").read_text(encoding="utf-8"))

    def test_a_published_file_has_none_of_it(self):
        from clark import page
        view = page.VIEW_PAGE.read_text(encoding="utf-8")
        for word in ("About you", "Your email", "/api/profile", "Add your name in Settings"):
            self.assertNotIn(word, view)


if __name__ == "__main__":
    unittest.main()
