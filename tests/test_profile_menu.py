"""#77: the profile circle's menu in the top bar, in a real browser. Publish is in the menu and not in the bar; the keys are the
menu's (arrows, Home, End, Esc back to the circle); the tooltip is the spec's words.

Run: python3 dev/run_tests.py test_profile_menu
Preview and Export (#147) ask the server's routes (tests/test_preview_export_route.py); here they are tested as the page uses them.
Dark mode and the name-and-email line are not in the menu: the page has no dark-mode setting and holds no profile. Chrome is required.
"""
import json
import re
import unittest
from unittest import mock

from test_publish_dialog import Base, PAGE_SRC
from test_server import chrome
from clark import excel, server as sv

# The tooltip is built from the entries that carry a short word, so it follows them; the test below pins the two together.
TIP = "Your menu: Publish, Preview, Export, Settings"
NAME = "Your menu"
ITEMS = ["Publish…", "Preview the page in a new tab", "Export to Excel", "Settings", "Help"]


class ProfileMenu(Base):
    def open_menu(self, p):
        p.js("document.querySelector('#profile-btn').focus(); document.querySelector('#profile-btn').click()")
        p.until("!!document.querySelector('#profile-menu')", "the menu opened")

    def labels(self, p):
        return p.js("[].map.call(document.querySelectorAll('#profile-menu [role=menuitem]'), function(e){return e.textContent})")

    def active(self, p):
        return p.js("document.activeElement.textContent")

    def test_C_the_tooltip_lists_the_items_and_the_name_is_short(self):
        with chrome() as cdp:
            p = self.page(cdp)
            self.assertEqual(p.js("document.querySelector('#profile-btn').title"), TIP)
            self.assertEqual(p.js("document.querySelector('#profile-btn').getAttribute('aria-label')"), NAME)
            self.assertEqual(p.js("document.querySelector('#profile-btn').getAttribute('aria-haspopup')"), "menu")

    def test_C_publish_is_in_the_menu_and_not_in_the_bar(self):
        with chrome() as cdp:
            p = self.page(cdp)
            self.assertFalse(p.js("!![].find.call(document.querySelectorAll('header.top button'), function(b){return /^(Publish|Preview|Export|Help|Dark)/.test(b.textContent.trim())})"))
            self.assertFalse(p.js("!!document.querySelector('[data-publish],[data-preview],[data-export]')"))
            self.assertEqual(p.js("document.querySelectorAll('header.top [data-kind]').length"), 0, "no entry is in the bar")
            self.open_menu(p)
            self.assertEqual(self.labels(p), ITEMS, "the items and their order")

    def test_C_the_menu_has_a_separator_before_settings(self):
        with chrome() as cdp:
            p = self.page(cdp)
            self.open_menu(p)
            self.assertEqual(p.js("[].map.call(document.querySelector('#profile-menu').children, function(e){return e.getAttribute('role')}).join()"),
                             "menuitem,menuitem,menuitem,separator,menuitem,menuitem")

    def test_C_the_last_published_note_is_reachable_when_narrow(self):
        for w in (390, 900):
            with self.subTest(width=w), chrome() as cdp:
                p = self.page(cdp)
                p.width(w, 700)
                p.js("document.querySelector('#profile-btn').click()")
                p.until("!!document.querySelector('#profile-menu')", "the menu opened")
                p.js("document.querySelector('#profile-btn').click()")
                p.until("!document.querySelector('#profile-menu')", "the menu closed")
                p.open_publish()
                p.go()
                p.until("document.querySelector('[data-go]').innerText === 'Close'", "published")
                p.until("!!document.querySelector('#pub-note')", "the bar says when")
                p.go()
                p.until("!document.querySelector('#publish-dialog')", "closed")
                p.js("document.querySelector('#profile-btn').click()")
                p.until("!!document.querySelector('#profile-menu .lab')", "the note is in the menu")
                self.assertRegex(p.js("document.querySelector('#profile-menu .lab').textContent"), r"^Published \d\d-\d\d-\d{4} locally$")
                self.assertTrue(p.js("(function(){var r=document.querySelector('#profile-menu').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth})()"), "inside the window")

    def test_C_the_publish_entry_opens_the_dialog(self):
        with chrome() as cdp:
            p = self.page(cdp)
            p.open_publish()
            self.assertIn("Publish the report", p.dialog_text())
            self.assertEqual((self.rig.everything_written(), self.rig.rows()), ([], []), "opening writes nothing")

    def test_C_the_tooltip_is_pinned_to_the_entries(self):
        words = re.findall(r'tip: "([A-Za-z]+)"', (PAGE_SRC / "edit" / "ProfileMenu.jsx").read_text(encoding="utf-8"))
        self.assertEqual("Your menu: " + ", ".join(words), TIP, "the words in the source")
        with chrome() as cdp:
            p = self.page(cdp)
            self.open_menu(p)
            tip = p.js("document.querySelector('#profile-btn').title")
            self.assertEqual(tip, TIP)
            shown = self.labels(p)
            for word in tip[len(NAME) + 2:].split(", "):
                self.assertTrue(any(l.startswith(word) for l in shown), word + " is an entry")
            self.assertEqual([l for l in shown if not any(l.startswith(w) for w in words)], ["Help"], "only Help has no word in the tip")

    def toast(self, p):
        p.until("!!document.querySelector('.toast .toast-text')", "a message appeared")
        return p.js("document.querySelector('.toast .toast-text').textContent")

    def pick(self, p, kind):
        self.open_menu(p)
        p.js("document.querySelector('#profile-menu [data-kind=%s]').click()" % kind)

    def test_C_the_preview_entry_opens_the_page_in_a_new_tab_and_publishes_nothing(self):
        with chrome() as cdp:
            p = self.page(cdp)
            before = self.rig.everything_written()
            p.js("window.__tabs = []; window.open = function(){ var t = {location: '', opener: window, close: function(){ this.closed = true; }}; window.__tabs.push(t); return t; }")
            self.pick(p, "preview")
            p.until("window.__tabs.length === 1 && /^\\/preview\\?id=/.test(window.__tabs[0].location)", "the tab was pointed at the preview")
            self.assertTrue(p.js("window.__tabs[0].opener === null"), "the preview tab has no link back to the editor (opener)")
            self.assertIn("not published", self.toast(p))
            self.assertEqual(p.js("document.querySelectorAll('.toasts').length"), 1, "one live region: the note is in the change toast's")
            p.js("window.__page = null; fetch(window.__tabs[0].location).then(function(r){return r.text()}).then(function(t){window.__page = t})")
            p.until("window.__page !== null", "the address served the page")
            self.assertTrue(p.js("window.__page.indexOf('id=\"clark-data\"') > 0 && window.__page.indexOf('data-mode=\"view\"') > 0"), "the page as published")
            self.assertFalse(p.js("window.__page.indexOf(%s) >= 0" % json.dumps(sv.TOKEN)), "this run's token is not in it")
            self.assertEqual((self.rig.everything_written(), self.rig.rows(), self.rig.saves), (before, [], []), "nothing published, nothing written")

    def test_C_a_blocked_new_tab_is_said_in_words(self):
        with chrome() as cdp:
            p = self.page(cdp)
            p.js("window.open = function(){ return null; }")
            self.pick(p, "preview")
            self.assertIn("Allow pop-ups", self.toast(p))

    def test_C_the_export_entry_downloads_the_workbook_named_with_the_code_and_the_day(self):
        with chrome() as cdp:
            p = self.page(cdp)
            before = self.rig.everything_written()
            p.js("window.__dl = []; window.__blob = null; URL.createObjectURL = function(b){ window.__blob = {size: b.size}; return 'blob:none'; };"
                 " HTMLAnchorElement.prototype.click = function(){ window.__dl.push(this.download); }")
            self.pick(p, "export")
            p.until("window.__dl.length === 1", "a download was started")
            self.assertEqual(p.js("window.__dl[0]"), "PUB-2026-10-28.xlsx")
            self.assertGreater(p.js("window.__blob.size"), 1000)
            self.assertIn("PUB-2026-10-28.xlsx", self.toast(p))
            self.assertEqual((self.rig.everything_written(), self.rig.rows()), (before + ["clark-data/excel-export-state.json"], []),
                             "no workbook in any folder; only the export's record, beside the database")

    def test_C_a_second_click_while_an_export_runs_does_nothing(self):
        with chrome() as cdp:
            p = self.page(cdp)
            p.js("window.__dl = []; window.__asked = 0; URL.createObjectURL = function(b){ return 'blob:none'; };"
                 " HTMLAnchorElement.prototype.click = function(){ window.__dl.push(this.download); };"
                 " var real = window.fetch; window.fetch = function(u, o){ if (String(u).indexOf('/api/export') >= 0) { window.__asked++;"
                 " return new Promise(function(done){ setTimeout(function(){ done(real(u, o)); }, 700); }); } return real(u, o); }")
            self.pick(p, "export")
            self.pick(p, "export")
            self.pick(p, "export")
            p.until("window.__dl.length >= 1", "the export finished")
            p.js("window.__later = false; setTimeout(function(){ window.__later = true; }, 600)")
            p.until("window.__later", "a moment later")
            self.assertEqual((p.js("window.__asked"), p.js("window.__dl.length")), (1, 1), "one export, one download")
            self.pick(p, "export")                                                      # and after it finished, the next click works
            p.until("window.__dl.length === 2", "a second export after the first")

    def test_C_an_export_that_is_refused_says_what_to_do(self):
        with chrome() as cdp:
            p = self.page(cdp)
            p.js("window.__dl = []; HTMLAnchorElement.prototype.click = function(){ window.__dl.push(this.download); }")
            with mock.patch.object(excel, "export_project", side_effect=excel.Refused("x.xlsx is open in Excel. Close it.")):
                self.pick(p, "export")
                self.assertEqual(self.toast(p), "The workbook could not be made. Nothing was changed. Try again.")
            self.assertEqual(p.js("window.__dl.length"), 0)

    def test_C_the_help_entry_opens_help(self):
        with chrome() as cdp:
            p = self.page(cdp)
            self.assertFalse(p.js("!!document.querySelector('.hp-tabs')"))
            self.pick(p, "help")
            p.until("!!document.querySelector('.hp-tabs')", "Help opened")

    def test_C_the_settings_entry_opens_settings(self):
        with chrome() as cdp:
            p = self.page(cdp)
            self.open_menu(p)
            p.js("document.querySelector('#profile-menu [data-kind=settings]').click()")
            p.until("location.hash.indexOf('#settings') === 0", "Settings opened")

    def test_C_the_keys(self):
        with chrome() as cdp:
            p = self.page(cdp)
            self.open_menu(p)
            self.assertEqual(self.active(p), "Publish…", "focus is on the first item")
            for want in ITEMS[1:]:
                p.key("ArrowDown", vk=40)
                self.assertEqual(self.active(p), want)
            p.key("ArrowDown", vk=40)
            self.assertEqual(self.active(p), "Publish…", "it wraps")
            p.key("End", vk=35)
            self.assertEqual(self.active(p), "Help")
            p.key("Home", vk=36)
            self.assertEqual(self.active(p), "Publish…")
            p.key("ArrowUp", vk=38)
            self.assertEqual(self.active(p), "Help")
            p.key("Escape", code="Escape", vk=27)
            p.until("!document.querySelector('#profile-menu')", "Esc closed it")
            p.until("document.activeElement.id === 'profile-btn'", "focus is back on the circle")


class Published(unittest.TestCase):
    def test_the_page_has_no_menu_of_its_own_in_a_published_file(self):
        from clark import page
        self.assertNotIn("profile-btn", page.VIEW_PAGE.read_text(encoding="utf-8"))
        self.assertIn("menuTip(items)", (PAGE_SRC / "edit" / "ProfileMenu.jsx").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
