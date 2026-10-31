"""#215: text read from a saved folder is screened for secrets before it is sent.

Run: python3 dev/run_tests.py test_secret_screen
Every fake secret is built from pieces at run time, so this file holds nothing a secrets scan would find.
"""
import json
import logging
import re
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from _paths import SRC  # noqa: F401

import test_ask_passages as tp
import test_ask_route as tr
import test_docx_read as tdx
from clark import ask, ask_passages, ask_service, secret_screen, store as st

PW = "Hunt" + "er2-Zq-99x"
FAMILIES = {
    "private key": "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIE" + "A" * 40 + "\n-----END " + "RSA PRIVATE KEY-----",
    "aws key": "id AK" + "IAIOSFODNN7EXAMPLE here",
    "github token": "use gh" + "p_" + "A1b2C3d4" * 5,
    "slack token": "xo" + "xb-" + "1234567890-abcdefghij",
    "bearer header": "Authorization: " + "Bear" + "er " + "abcDEF123456" * 3,
    "web token": "ey" + "J" + "a" * 12 + ".ey" + "J" + "b" * 12 + "." + "c" * 12,
    "api key": "sk-" + "ant-" + "a1B2c3D4e5F6",
    "address with password": "postgres://admin:" + PW + "@db.example.org/main",
    "password line": "pass" + "word = " + PW,
    "secret line": "client_" + "secret: " + "a1b2c3d4e5f6a7b8",
    "env line": "DB_PASS" + "WORD=" + PW,
    "env key line": "AWS_SECRET" + "_ACCESS_KEY=" + "wJalr" + "XUtnFEMI9K7MDENG",
    "long token near a word": "the api " + "key is " + "Xk9" + "Qm2Lp7" * 5 + "Zt4Rw8Vb1Nc",
}


class Screen(unittest.TestCase):
    def test_each_family_is_caught(self):
        for name, text in FAMILIES.items():
            with self.subTest(name):
                self.assertTrue(secret_screen.looks_like_secret("Notes before.\n" + text + "\nNotes after."))

    def test_ordinary_technical_text_is_not(self):
        text = "\n".join((
            "Release 2.5.1 ships on Friday; run git commit -m fix and open https://example.org/docs/plan?page=2.",
            "The token: 2026 plan covers three workstreams. The password policy is reviewed each year.",
            "Set the ticket id to ABC-A-003 and the build to 20261031-final-report-v2.",
            "Uses AES and SHA256 for the file checks; the key owner is the security lead.",
        ))
        self.assertFalse(secret_screen.looks_like_secret(text))

    def test_a_break_inside_the_secret_does_not_hide_it(self):
        token = "gh" + "p_" + "A1b2C3d4" * 5
        self.assertTrue(secret_screen.looks_like_secret(token[:20] + "\n" + token[20:]))
        self.assertTrue(secret_screen.looks_like_secret("pass" + "word:\r\n" + PW))

    def test_not_text_counts_as_a_hit(self):
        self.assertTrue(secret_screen.looks_like_secret(b"bytes"))

    def test_the_lists_are_the_publish_scans(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dev" / "tools"))
        try:
            import publish_public as pp
        finally:
            sys.path.pop(0)
        self.assertEqual([(k, rx.pattern.decode()) for k, rx in pp.SECRET_PATTERNS], list(secret_screen.SECRET_PATTERNS))
        self.assertEqual(pp.GENERIC_SECRET.pattern.decode(), secret_screen.GENERIC_SECRET)
        self.assertEqual(pp.UNQUOTED_SECRET.pattern.decode(), secret_screen.UNQUOTED_SECRET)
        self.assertEqual(pp.BASE64_RUN.pattern.decode(), secret_screen.BASE64_RUN)

    def test_base64_hidden_key_is_caught(self):
        import base64
        text = "data: " + base64.b64encode(("-----BEGIN " + "PRIVATE KEY-----").encode()).decode()
        self.assertTrue(secret_screen.looks_like_secret(text))

    def test_a_very_large_text_is_screened_quickly(self):
        start = time.monotonic()
        for text in ("a" * 1_000_000, ("word " * 200_000), "x1" * 500_000, "password=" + "a" * 900_000,
                     "-----BEGIN " * 80_000, ("A1" * 40 + " ") * 12_000, "a://" * 250_000, "http://" + "a" * 1_000_000,
                     "x://a:" + "b" * 1_000_000, "authorization: " + " " * 1_000_000):
            secret_screen.looks_like_secret(text)
        self.assertLess(time.monotonic() - start, 30)

    def test_the_address_shape_still_finds_an_address(self):
        self.assertTrue(secret_screen.looks_like_secret("see s3://user:" + PW + "@host/x"))


class FromFolders(tp.Folders):
    def test_each_family_in_a_file_is_left_out_whole_and_counted(self):
        for i, (name, text) in enumerate(FAMILIES.items()):
            self.put(self.box, f"f{i}.txt", "ZQ-PLAN the plan is fine\n" + text)
        self.put(self.box, "ok.txt", "ZQ-OK the plan is fine")
        got = self.run_it()
        self.assertEqual(self.labels(got), ["saved/ok.txt"])
        self.assertEqual(got.safety, len(FAMILIES))
        self.assertEqual(len(got.secret_labels), len(FAMILIES))
        self.assertNotIn("ZQ-PLAN", self.text_of(got))                      # the whole file, not just the line

    def test_a_secret_in_a_word_file_is_left_out(self):
        self.put(self.box, "w.docx", tdx.docx(tdx.P("ZQ-WORD budget") + tdx.P("pass" + "word: " + PW)), binary=True)
        self.put(self.box, "split.docx", tdx.docx(tdx.P("gh" + "p_" + "A1b2C3d4" * 2) + tdx.P("A1b2C3d4" * 3)), binary=True)
        got = self.run_it()
        self.assertEqual(got.passages, ())
        self.assertEqual(sorted(got.secret_labels), ["saved/split.docx", "saved/w.docx"])

    def test_a_normal_file_is_unchanged(self):
        self.put(self.box, "a.md", "ZQ-A Release 2.5.1 on 31-10-2026; token: 2026 plan.")
        got = self.run_it()
        self.assertIn("ZQ-A Release 2.5.1 on 31-10-2026; token: 2026 plan.", self.text_of(got))
        self.assertEqual((got.safety, got.secret_labels), (0, ()))

    def test_a_secret_far_down_a_long_file_is_still_found_and_it_is_fast(self):
        self.put(self.box, "long.txt", "plain words here\n" * 40000 + "pass" + "word=" + PW)
        start = time.monotonic()
        got = self.run_it()
        self.assertLess(time.monotonic() - start, 30)
        self.assertEqual(got.passages, ())
        self.assertEqual(got.secret_labels, ("saved/long.txt",))

    def test_removing_the_screen_lets_the_secret_through(self):
        self.put(self.box, "s.txt", "ZQ-S pass" + "word=" + PW)
        with mock.patch.object(secret_screen, "looks_like_secret", return_value=False):
            got = self.run_it()
        self.assertIn(PW, self.text_of(got))                                # so the tests above depend on the screen
        self.assertEqual(self.run_it().passages, ())


class OnTheRoute(tp.OnTheRoute):
    def test_the_person_is_told_the_file_and_the_next_step_and_the_secret_goes_nowhere(self):
        (self.mine / "creds.txt").write_text("ZQ-CREDS pass" + "word=" + PW, encoding="utf-8")
        with self.assertLogs(level="DEBUG") as logs:
            logging.getLogger().debug("start")
            status, got = self.question("What is the cutover plan?")
        self.assertEqual(status, 200, got)
        (text,) = self.provider.sent
        self.assertIn("ZQ-MINE", text)
        self.assertNotIn(PW, text)
        self.assertNotIn("ZQ-CREDS", text)
        note = [n for n in got["notes"] if "creds.txt" in n]
        self.assertEqual(len(note), 1, got["notes"])
        self.assertIn("looks like it holds a secret", note[0])
        self.assertIn("Remove the secret from the file or move it out of the saved folder.", note[0])
        self.assertGreaterEqual(got["left_out_for_safety"], 2)
        for blob in (json.dumps(got), "\n".join(logs.output)):
            self.assertNotIn(PW, blob)


if __name__ == "__main__":
    unittest.main()
