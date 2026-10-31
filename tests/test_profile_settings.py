"""#180: your name and your email (settings.profile, settings.set_profile, profile_settings.Profile and GET and POST /api/profile).
Fictional data only. Run: python3 dev/run_tests.py test_profile_settings

What is asserted: a fresh folder has neither (never an invented email); both are saved in settings.json beside the backups number,
which is kept; a name of 60 characters is kept and 61 is refused, each refusal in the words Settings shows and ending "Nothing was
saved.", writing nothing; spaces are made one; a control or invisible character is refused; an email must be shaped like an address or
empty; a settings file that can't be read is never replaced; the seam answers and refuses by shape; the route has the server's checks,
a 2 KiB limit and no effect when refused; the name is the name on each change (by_user), with the login name when none was typed, and
the email's domain is the person's own domain.
"""
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path

import _paths  # noqa: F401
from _demo import DemoStore
from clark import changes, platform, profile_settings, server as sv, settings


class Folder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def disk(self):
        f = self.dir / settings.FILE
        return f.read_bytes() if f.exists() else None


class Settings(Folder):
    def test_a_fresh_folder_has_neither(self):
        self.assertEqual(settings.profile(self.dir), {"name": "", "email": ""})

    def test_both_are_saved_beside_the_backups_number_which_is_kept(self):
        settings.set_backups_kept(self.dir, 21)
        saved = settings.set_profile(self.dir, "Sam Lee", "sam@example.test")
        self.assertEqual(saved, {"name": "Sam Lee", "email": "sam@example.test"})
        self.assertEqual(settings.profile(self.dir), saved)
        self.assertEqual(settings.backups_kept(self.dir), 21)
        self.assertEqual(json.loads(self.disk()), {"backups_kept": 21, "profile_email": "sam@example.test", "profile_name": "Sam Lee"})
        settings.set_backups_kept(self.dir, 9)
        self.assertEqual(settings.profile(self.dir), saved, "the backups number does not touch them")

    def test_each_may_be_empty_and_emptying_clears_it(self):
        settings.set_profile(self.dir, "Sam Lee", "sam@example.test")
        self.assertEqual(settings.set_profile(self.dir, "", "sam@example.test"), {"name": "", "email": "sam@example.test"})
        self.assertEqual(settings.set_profile(self.dir, "Sam", ""), {"name": "Sam", "email": ""})
        self.assertEqual(settings.set_profile(self.dir, "  ", None), {"name": "", "email": ""})

    def test_sixty_characters_are_kept_and_sixty_one_are_refused_in_the_words_settings_shows(self):
        self.assertEqual(settings.set_profile(self.dir, "N" * 60, "")["name"], "N" * 60)
        before = self.disk()
        with self.assertRaises(ValueError) as caught:
            settings.set_profile(self.dir, "N" * 61, "sam@example.test")
        self.assertEqual(str(caught.exception), "Your name is too long. Use 60 characters or fewer. Nothing was saved.")
        self.assertEqual(self.disk(), before, "nothing was written")

    def test_a_bad_email_is_refused_in_its_words_and_nothing_is_written(self):
        settings.set_profile(self.dir, "Sam", "sam@example.test")
        before = self.disk()
        for bad in ("sam", "sam@", "@example.test", "sam@example", "a b@example.test", "<sam@example.test>", "sam@example.test?bcc=x@y.test",
                    "sam@example.test‮", "sam@exa​mple.test", "x" * 250 + "@example.test", "sam@example.test;lee@example.test"):
            with self.assertRaises(ValueError, msg=repr(bad)) as caught:
                settings.set_profile(self.dir, "Sam", bad)
            self.assertEqual(str(caught.exception), "That email address is not complete. Check it, or leave it empty. Nothing was saved.", repr(bad))
        self.assertEqual(self.disk(), before)
        self.assertEqual(settings.set_profile(self.dir, "Sam", "dana.o'hart+uat@partner.example.test")["email"], "dana.o'hart+uat@partner.example.test")

    def test_spaces_are_made_one_and_an_unkeepable_character_is_refused(self):
        self.assertEqual(settings.set_profile(self.dir, "  Sam    Lee ", "")["name"], "Sam Lee")
        before = self.disk()
        for bad in ("Sam\nLee", "Sam\u0000Lee", "Sam‮Lee", "Sam​Lee", "Sam\tLee", "Sam Lee"):
            with self.assertRaises(ValueError, msg=repr(bad)) as caught:
                settings.set_profile(self.dir, bad, "")
            self.assertTrue(str(caught.exception).endswith("Nothing was saved."), repr(bad))
        self.assertEqual(self.disk(), before)

    def test_a_non_text_value_is_refused(self):
        with self.assertRaises(ValueError):
            settings.set_profile(self.dir, 5, "")
        with self.assertRaises(ValueError):
            settings.set_profile(self.dir, "", ["a@b.test"])

    def test_a_settings_file_that_cannot_be_read_is_never_replaced(self):
        (self.dir / settings.FILE).write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            settings.set_profile(self.dir, "Sam", "")
        self.assertIn("Nothing was saved", str(caught.exception))
        self.assertEqual(self.disk(), b"{not json")

    def test_a_value_in_the_file_that_is_not_plain_is_read_as_empty(self):
        (self.dir / settings.FILE).write_text(json.dumps({"profile_name": "N" * 80, "profile_email": "not an address"}), encoding="utf-8")
        self.assertEqual(settings.profile(self.dir), {"name": "", "email": ""})
        (self.dir / settings.FILE).write_text(json.dumps({"profile_name": 7, "profile_email": None}), encoding="utf-8")
        self.assertEqual(settings.profile(self.dir), {"name": "", "email": ""})


class Seam(Folder):
    def setUp(self):
        super().setUp()
        self.p = profile_settings.Profile(self.dir)

    def test_get_and_save(self):
        self.assertEqual(self.p.get(), (200, {"ok": True, "name": "", "email": ""}))
        self.assertEqual(self.p.save({"name": "Sam Lee", "email": "sam@example.test"}), (200, {"ok": True, "name": "Sam Lee", "email": "sam@example.test"}))
        self.assertEqual(self.p.get()[1]["name"], "Sam Lee")

    def test_a_wrong_shape_is_refused_and_writes_nothing(self):
        for req in ({}, {"name": "x"}, {"email": "x"}, {"name": "x", "email": "", "by_user": "y"}, {"name": 1, "email": ""}, {"name": "x", "email": None}, [], "x", None):
            status, body = self.p.save(req)
            self.assertEqual((status, body["ok"], body["code"]), (400, False, "bad_request"), req)
            self.assertTrue(body["message"].endswith("Nothing was saved."))
        self.assertIsNone(self.disk())

    def test_a_refusal_is_400_in_the_words_and_nothing_changes(self):
        self.p.save({"name": "Sam", "email": "sam@example.test"})
        before = self.disk()
        status, body = self.p.save({"name": "N" * 61, "email": ""})
        self.assertEqual((status, body["code"], body["message"]), (400, "refused", settings.NAME_TOO_LONG))
        self.assertEqual(self.disk(), before)

    def test_who_is_the_name_else_the_login_name_and_the_domain_is_the_emails(self):
        self.assertEqual(self.p.who(), platform.login_name())
        self.assertEqual(self.p.own_domains(), [])
        self.p.save({"name": "Sam Lee", "email": "Sam@Example.TEST"})
        self.assertEqual(self.p.who(), "Sam Lee")
        self.assertEqual(self.p.own_domains(), ["example.test"])

    def test_two_saves_at_once_both_finish_with_a_whole_file(self):
        def go(n):
            for i in range(20):
                self.p.save({"name": f"Name {n} {i}", "email": ""})
        threads = [threading.Thread(target=go, args=(n,)) for n in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertRegex(settings.profile(self.dir)["name"], r"^Name \d \d+$")
        json.loads(self.disk())


class Route(Folder):
    def setUp(self):
        super().setUp()
        self.p = profile_settings.Profile(self.dir)
        self.httpd = sv.LocalServer((sv.HOST, 0), profile=self.p)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.httpd.shutdown(), self.httpd.server_close()))
        import http.client
        self.http = http.client

    def ask(self, method, body=None, token=True, host=True, ctype="application/json", extra=None):
        conn = self.http.HTTPConnection(sv.HOST, self.httpd.server_port, timeout=10)
        try:
            conn.putrequest(method, "/api/profile", skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", f"127.0.0.1:{self.httpd.server_port}" if host is True else host)
            if token:
                conn.putheader(sv.TOKEN_HEADER, sv.TOKEN if token is True else token)
            for k, v in (extra or {}).items():
                conn.putheader(k, v)
            raw = json.dumps(body).encode() if body is not None and not isinstance(body, bytes) else body
            if raw is not None:
                conn.putheader("Content-Type", ctype)
                conn.putheader("Content-Length", str(len(raw)))
            conn.endheaders(raw)
            r = conn.getresponse()
            data = r.read()
            return r.status, (json.loads(data) if data else None)
        finally:
            conn.close()

    def test_get_and_post(self):
        self.assertEqual(self.ask("GET"), (200, {"ok": True, "name": "", "email": ""}))
        status, body = self.ask("POST", {"name": "Sam Lee", "email": "sam@example.test"})
        self.assertEqual((status, body["name"], body["email"]), (200, "Sam Lee", "sam@example.test"))
        self.assertEqual(self.ask("GET")[1]["email"], "sam@example.test")

    def test_the_servers_checks_come_first_and_nothing_is_written(self):
        good = {"name": "Sam", "email": ""}
        for kw, want in (({"token": False}, 403), ({"token": "wrong"}, 403), ({"host": "evil.example"}, 403),
                         ({"extra": {"Origin": "http://evil.example"}}, 403), ({"ctype": "text/plain"}, 415)):
            self.assertEqual(self.ask("POST", good, **kw)[0], want, kw)
        self.assertEqual(self.ask("GET", token=False)[0], 403)
        self.assertEqual(self.ask("POST", {"name": "x" * 3000, "email": ""})[0], 400, "over 2 KiB is refused before it is read")
        self.assertIsNone(self.disk())

    def test_a_refusal_is_the_400_in_words_and_nothing_is_written(self):
        status, body = self.ask("POST", {"name": "N" * 61, "email": ""})
        self.assertEqual((status, body["message"]), (400, settings.NAME_TOO_LONG))
        status, body = self.ask("POST", {"name": "Sam", "email": "nope"})
        self.assertEqual((status, body["message"]), (400, settings.EMAIL_BAD))
        self.assertIsNone(self.disk())

    def test_no_seam_is_404(self):
        bare = sv.LocalServer((sv.HOST, 0))
        threading.Thread(target=bare.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (bare.shutdown(), bare.server_close()))
        conn = self.http.HTTPConnection(sv.HOST, bare.server_port, timeout=10)
        conn.request("GET", "/api/profile", headers={"Host": f"127.0.0.1:{bare.server_port}", sv.TOKEN_HEADER: sv.TOKEN})
        self.assertEqual(conn.getresponse().status, 404)
        conn.close()


class ByUser(unittest.TestCase):
    def test_the_name_is_the_name_on_each_change_and_the_login_name_when_none_was_typed(self):
        demo = DemoStore()
        self.addCleanup(demo.close)
        who = profile_settings.Profile(demo.store.path.parent)
        change = changes.make_change(demo.store.path, [], who.who)
        sections = demo.store.read("report_sections", "ABC")
        target = sections[0]["id"]
        req = {"project": "ABC", "kind": "report_sections", "op": "update", "id": target, "changes": {"title": "Where we are"}, "place": "report"}
        self.assertEqual(change(req)[0], 200)
        by = lambda: [r[0] for r in demo.store.con.execute("SELECT by_user FROM applies ORDER BY apply_id DESC LIMIT 1")]
        self.assertEqual(by(), [platform.login_name()])
        who.save({"name": "Sam Lee", "email": ""})
        req["changes"] = {"title": "Where we are now"}
        self.assertEqual(change(req)[0], 200)
        self.assertEqual(by(), ["Sam Lee"])


if __name__ == "__main__":
    unittest.main()
