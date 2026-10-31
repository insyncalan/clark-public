"""#47c: the ask clark reply reader and claims check (src/clark/ask.py, commit 3).

Run: python3 dev/run_tests.py test_ask_reply
Fictional data only. Nothing here opens a file, a database or the network.
"""
import ast
import json
import random
import re
import time
import unittest

from _paths import SRC
from clark import ask

CODES = ["ABC", "XYZ"]
ITEMS = {"ABC-A-001": {"title": "Order the test kit", "owner": "Owner One"},
         "ABC-A-009": {"title": "Book the training room", "owner": "Owner Two"},
         "ABC-R-002": {"title": "Supplier delay", "owner": "Owner One"}}
SENT = ("P1", "P2")


def exists(ref):
    return ref in ITEMS


def facts(ref):
    return ITEMS.get(ref)


def read(text, **kw):
    return ask.read_reply(text, kw.get("sent", SENT), CODES, exists, kw.get("facts"))


def kinds(reply):
    return [f.kind for f in reply.flags]


class Form(unittest.TestCase):
    def test_a_plain_answer_parses_with_nothing_to_change(self):
        r = read("The kit is ordered.")
        self.assertEqual((r.answer, r.cites, r.changes, r.parsed, r.flags), ("The kit is ordered.", (), (), True, ()))

    def test_cite_and_change_lines_are_read_and_taken_out_of_the_answer(self):
        r = read('ABC-A-001 is late.\nCITE: P1 P2\nCITE: P2, P1\nCHANGE: {"item": "ABC-A-001", "status": "Done", "n": 3, "ok": true, "x": null}')
        self.assertEqual(r.answer, "ABC-A-001 is late.")
        self.assertEqual(r.cites, ("P1", "P2"))
        self.assertEqual(r.changes, ({"item": "ABC-A-001", "status": "Done", "n": 3, "ok": True, "x": None},))
        self.assertTrue(r.parsed)
        self.assertEqual(r.flags, ())

    def test_a_reply_that_does_not_parse_is_shown_as_text_and_offers_no_change(self):
        bad = [
            "",
            "   \n ",
            "Answer\nCITE: the plan",
            "Answer\nCITE:",
            "Answer\nCITE: P0",
            'Answer\nCHANGE: {"a": }',
            "Answer\nCHANGE: not json",
            "Answer\nCHANGE: []",
            "Answer\nCHANGE: {}",
            'Answer\nCHANGE: {"a": {"b": 1}}',
            'Answer\nCHANGE: {"a": [1]}',
            'Answer\nCHANGE: {"a": 1, "a": 2}',
            'Answer\nCHANGE: {"a": NaN}',
            'Answer\nCHANGE: {"a": Infinity}',
            'Answer\nCHANGE: {"": 1}',
            'Answer\nCHANGE: {"a": 1} trailing',
            "Answer\nCHANGE: " + json.dumps({"a": "x" * (ask.MAX_FIELD_VALUE + 1)}),
            "Answer\nCHANGE: " + json.dumps({"n" * (ask.MAX_FIELD_NAME + 1): 1}),
            "Answer\nCHANGE: " + json.dumps({f"f{i}": i for i in range(ask.MAX_CHANGE_FIELDS + 1)}),
            "Answer\nCHANGE: " + json.dumps({"a": "x" * ask.MAX_CHANGE_CHARS}),
            "\n".join(["Answer"] + ['CHANGE: {"a": 1}'] * (ask.MAX_CHANGES + 1)),
            'Good\nCHANGE: {"a": 1}\nCHANGE: broken',                    # one good line does not rescue a bad one
            "CHANGE: " + "[" * 100000,
        ]
        for text in bad:
            r = read(text)
            self.assertFalse(r.parsed, text[:60])
            self.assertEqual((r.changes, r.cites), ((), ()), text[:60])
            self.assertEqual(r.answer, text[:ask.MAX_REPLY].strip())
            self.assertEqual(r.flags[0].kind, "unreadable")
            self.assertEqual(r.flags[0].message, ask.UNREADABLE)

    def test_the_most_changes_allowed_are_read(self):
        r = read("\n".join(["Answer"] + ['CHANGE: {"a": 1}'] * ask.MAX_CHANGES))
        self.assertEqual((r.parsed, len(r.changes)), (True, ask.MAX_CHANGES))

    def test_a_marker_must_be_plain_capitals_with_a_colon(self):
        r = read('cite: P1\nChange: {"a": 1}\nCHANGE {"a": 1}\nThe CHANGE: {"a": 1}')
        self.assertTrue(r.parsed)
        self.assertEqual((r.cites, r.changes), ((), ()))
        self.assertIn("cite: P1", r.answer)

    def test_a_marker_hidden_behind_invisible_or_look_alike_characters_is_not_acted_on(self):
        for line in ('CHA​NGE: {"a": 1}', 'CHАNGE: {"a": 1}', 'C​ITE: P1', "﻿CITE: P1x".replace("x", "")):
            if line == "﻿CITE: P1":
                continue                                # a leading BOM is a hidden character in front of the word: also caught below
            r = read("Answer\n" + line)
            self.assertFalse(r.parsed, repr(line))
            self.assertEqual(r.changes, ())
            self.assertEqual(r.flags[0].kind, "disguised")
        r = read('Answer\n﻿CHANGE: {"a": 1}')
        self.assertEqual((r.parsed, r.changes), (False, ()))

    def test_odd_input_never_raises(self):
        for value in (None, 5, b"CITE: P1", ["x"], "\x00" * 10, "CITE: " + "P1 " * 5000, "\ud800 CHANGE: {"):
            r = ask.read_reply(value, SENT, CODES, exists)
            self.assertIsInstance(r, ask.Reply)

    def test_a_long_reply_is_cut(self):
        r = read("a " * ask.MAX_REPLY)
        self.assertLessEqual(len(r.answer), ask.MAX_REPLY)


class NeverRun(unittest.TestCase):
    def test_a_change_line_is_data_only(self):
        bad = {"item": "ABC-A-001", "status": "__import__('os').system('echo hi')", "sql": "DROP TABLE actions", "path": "/etc/passwd"}
        r = read("Done\nCHANGE: " + json.dumps(bad))
        self.assertEqual(r.changes, (bad,))                 # carried as the text it is, never run, never checked against a store
        self.assertTrue(r.parsed)

    def test_a_change_names_no_store_and_the_module_runs_nothing(self):
        text = (SRC / "clark" / "ask.py").read_text(encoding="utf-8")
        called = {n.func.id for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertEqual(called & {"eval", "exec", "compile", "open", "__import__", "getattr_static"}, set())
        for word in ("__import__", "importlib", "pickle", "marshal", "yaml", "sqlite3", "subprocess", "os.system"):
            self.assertNotIn(word, text)


class Claims(unittest.TestCase):
    def test_an_unknown_id_is_flagged_in_plain_words(self):
        r = read("ABC-A-001 is late and so is ABC-A-777.")
        self.assertEqual(kinds(r), ["unknown_id"])
        self.assertEqual(r.flags[0].ref, "ABC-A-777")
        self.assertEqual(r.flags[0].message, "The answer mentioned ABC-A-777, which isn't in this project. Ignore that part.")

    def test_another_projects_id_is_unknown(self):
        self.assertEqual([f.ref for f in read("See XYZ-A-001.").flags], ["XYZ-A-001"])

    def test_known_ids_are_not_flagged_and_each_unknown_is_flagged_once(self):
        self.assertEqual(read("ABC-A-001, ABC-R-002 and ABC-A-009.").flags, ())
        self.assertEqual(kinds(read("ABC-A-777 then ABC-A-777 again")), ["unknown_id"])

    def test_disguised_ids_are_caught(self):
        for text in ("ABC​-A-777", "ABC‑A‑777", "АBC-A-777", "ABC-А-777", "ＡＢＣ-A-777",
                     "ABC\U000E0041-A-777", "ÁBC-A-777"):
            self.assertEqual([f.ref for f in read("It is " + text + " now").flags], ["ABC-A-777"], repr(text))

    def test_a_loosely_written_real_id_is_counted_and_a_loosely_written_unknown_one_is_not_invented(self):
        r = read("See abc a 9 and ABC (A) 001 and ABC 100 users.")
        self.assertEqual(r.flags, ())                       # abc a 9 = ABC-A-009 and ABC (A) 001 are real; "ABC 100 users" is no item

    def test_an_exists_that_raises_flags_the_id(self):
        def boom(_ref):
            raise RuntimeError("no store")
        r = ask.read_reply("See ABC-A-001.", SENT, CODES, boom)
        self.assertEqual(kinds(r), ["unknown_id"])

    def test_a_title_that_does_not_match_is_flagged(self):
        r = read('ABC-A-001 is "Book the training room".', facts=facts)
        self.assertEqual(kinds(r), ["wrong_title"])
        self.assertEqual(r.flags[0].expected, "Order the test kit")
        self.assertEqual(read('ABC-A-001 is "order the test kit".', facts=facts).flags, ())
        self.assertEqual(read("ABC-A-001 is “Order the test kit”.", facts=facts).flags, ())

    def test_an_owner_that_does_not_match_is_flagged(self):
        r = read("ABC-A-009 is owned by Owner One and due soon.", facts=facts)
        self.assertEqual(kinds(r), ["wrong_owner"])
        self.assertEqual(r.flags[0].message, "The answer gave the wrong owner for ABC-A-009. The report says: Owner Two.")
        self.assertEqual(read("ABC-A-009 owner: Owner Two", facts=facts).flags, ())
        self.assertEqual(read("ABC-A-009 is assigned to Owner Two.", facts=facts).flags, ())

    def test_a_line_with_two_items_is_not_matched_against_either(self):
        self.assertEqual(read('ABC-A-001 and ABC-A-009 are "Something else", owner Owner Nine', facts=facts).flags, ())

    def test_facts_are_optional_and_a_failing_facts_is_ignored(self):
        self.assertEqual(read('ABC-A-001 is "Wrong title".').flags, ())

        def boom(_ref):
            raise RuntimeError("x")
        self.assertEqual(ask.read_reply('ABC-A-001 is "Wrong title".', SENT, CODES, exists, boom).flags, ())

    def test_a_cited_passage_that_was_not_sent_is_flagged(self):
        r = read("Yes.\nCITE: P1 P7")
        self.assertEqual(kinds(r), ["unsent_passage"])
        self.assertEqual((r.flags[0].ref, r.flags[0].message), ("P7", ask.NOT_SENT))
        self.assertEqual(r.cites, ("P1", "P7"))
        self.assertEqual(kinds(read("Yes, see [P5].")), ["unsent_passage"])
        self.assertEqual(read("Yes.\nCITE: P1 P2").flags, ())

    def test_sent_can_be_a_request(self):
        req = ask.build_request("Q?", [ask.Passage("a.md", "text")])
        self.assertEqual(kinds(ask.read_reply("CITE: P1 P2", req, CODES, exists)), ["unsent_passage"])

    def test_a_change_that_names_an_unknown_item_is_left_out_and_flagged(self):
        r = read('Done\nCHANGE: {"item": "ABC-A-001", "status": "Done"}\nCHANGE: {"item": "ABC-A-777", "status": "Done"}')
        self.assertEqual(r.changes, ({"item": "ABC-A-001", "status": "Done"},))
        self.assertEqual(sorted(kinds(r)), ["change_left_out", "unknown_id"])

    def test_claims_are_checked_on_a_reply_that_did_not_parse_too(self):
        r = read("ABC-A-777\nCITE: nonsense")
        self.assertFalse(r.parsed)
        self.assertIn("unknown_id", kinds(r))

    def test_flags_come_in_a_fixed_order(self):
        text = "ABC-A-888 and ABC-A-777 and ABC-A-001.\nCITE: P9 P8"
        self.assertEqual(read(text).flags, read(text).flags)
        self.assertEqual([f.ref for f in read(text).flags], ["ABC-A-777", "ABC-A-888", "P8", "P9"])


class Caps(unittest.TestCase):
    def test_hundreds_of_unknown_ids_give_a_few_flags_and_an_and_more_line(self):
        text = " ".join(f"ABC-A-{n:03d}" for n in range(100, 1000))
        r = read(text)
        self.assertLessEqual(len(r.flags), ask.MAX_FLAGS + 1)
        self.assertEqual(r.flags[-1].kind, "more")
        self.assertRegex(r.flags[-1].message, r"^and \d+ more\.$")
        shown = sum(1 for f in r.flags if f.kind == "unknown_id")
        self.assertEqual(shown + int(re.search(r"\d+", r.flags[-1].message).group()), 900)

    def test_a_few_flags_get_no_and_more_line(self):
        self.assertNotIn("more", kinds(read("ABC-A-777 and ABC-A-778")))

    def test_the_cap_holds_on_a_reply_that_did_not_parse(self):
        r = read("CITE: nonsense\n" + " ".join(f"ABC-A-{n:03d}" for n in range(100, 900)))
        self.assertFalse(r.parsed)
        self.assertLessEqual(len(r.flags), ask.MAX_FLAGS + 2)


class Keys(unittest.TestCase):
    def test_an_unknown_id_in_a_change_name_is_left_out_and_flagged(self):
        r = read("Done.\nCHANGE: " + json.dumps({"ABC-A-777": "x"}))
        self.assertEqual(r.changes, ())
        self.assertEqual(kinds(r).count("change_left_out"), 1)

    def test_a_known_id_in_a_change_name_is_kept(self):
        r = read("Done.\nCHANGE: " + json.dumps({"ABC-A-001": "x"}))
        self.assertEqual(r.changes, ({"ABC-A-001": "x"},))


class Speed(unittest.TestCase):
    """No line of a reply can make the claims check slow (the owner pattern once backtracked on a long run of spaces)."""

    OLD_OWNER = (r"\b(?:owner|owned by|assigned to)\b\s*(?:is\b|:|-)?\s*"
                 r"([A-Z][\w'\u2019.-]*(?:\s+[A-Z][\w'\u2019.-]*){0,2})")

    def timed(self, text):
        t = time.perf_counter()
        read(text, facts=facts)
        return time.perf_counter() - t

    def test_a_long_run_of_spaces_after_owner_is_quick(self):
        self.assertLess(self.timed("ABC-A-001 owner" + " " * 59000 + "x"), 1.0)

    def test_adversarial_lines_of_sixty_thousand_characters_are_quick(self):
        n = 60000
        for text in ("ABC-A-001 owner is" + " " * n, "ABC-A-001 owner -" + " \t" * 29000, "ABC-A-001 " + "owner " * 9000,
                     "ABC-A-001 owner " + "A " * 29000, "ABC-A-001 owner A" + "." * n, "ABC-A-001 " + '"' * n,
                     "ABC-A-001 " + '"a' * 29000, "ABC-A-001 " * 6000, "[P1" * 20000, "CITE: " + "P1 " * 20000,
                     "ABC-A-001\n" * 6000):
            with self.subTest(text=text[:30]):
                self.assertLess(self.timed(text[:n]), 1.0)

    def test_the_secret_check_is_quick_on_adversarial_text(self):
        n = 60000
        for text in ("password" + " " * n, "password is " * 5000, "Bearer " * 8000, "http://a:" * 7000, "aA1" * 20000,
                     "api key " * 7000, "-----BEGIN " + "A " * 29000):
            with self.subTest(text=text[:20]):
                t = time.perf_counter()
                ask.looks_like_secret(text[:n])
                self.assertLess(time.perf_counter() - t, 1.0)

    def test_a_line_over_the_limit_is_not_checked_for_title_or_owner(self):
        wrong = "ABC-A-001 owner is Somebody Else"
        self.assertEqual(kinds(read(wrong, facts=facts)), ["wrong_owner"])
        long_line = wrong + " " + "x" * ask.MAX_CHECKED_LINE
        self.assertEqual(kinds(read(long_line, facts=facts)), [])
        self.assertEqual(kinds(read('ABC-A-001 "Some other title" ' + "x" * ask.MAX_CHECKED_LINE, facts=facts)), [])
        # the other checks still run on it
        self.assertEqual(kinds(read(long_line + " ABC-A-777")), ["unknown_id"])

    def test_the_owner_pattern_matches_what_the_old_one_did(self):
        old = re.compile(self.OLD_OWNER)
        pieces = ["owner", "owned by", "assigned to", "Owner", " ", "  ", "\t", "is", "is ", ":", "-", ": ", " - ", "Sam", "Poe",
                  "O'Neil", "Ann-Marie", "J.", "sam", "x", ",", ".", "\u2019", "ABC-A-001", "was", "\u00e9"]
        rng = random.Random(4747)
        for _ in range(200000):
            text = "".join(rng.choice(pieces) for _ in range(rng.randint(1, 9)))
            a, b = old.search(text), ask._OWNER.search(text)
            self.assertEqual((a and (a.span(), a.group(1))), (b and (b.span(), b.group(1))), text)


class Messages(unittest.TestCase):
    def test_the_sentences_are_pinned(self):
        self.assertEqual(ask.UNREADABLE, "The answer came back in a form that couldn't be checked, so it is shown as text and nothing is "
                                         "offered to change. Ask again, or check it against the report yourself.")
        self.assertEqual(ask.NOT_SENT, "The answer named a source that was not sent. Ignore that part.")
        r = read("CHANGE: " + json.dumps({"item": "ABC-A-777"}))
        self.assertEqual([f.message for f in r.flags if f.kind == "change_left_out"],
                         ["A change the answer suggested named ABC-A-777, which isn't in this project, so it was left out."])

    def test_the_words_for_a_wrong_title_and_a_wrong_owner_are_kept(self):
        r = read('ABC-A-001 "Some other title" owner is Somebody Else', facts=facts)
        self.assertEqual(sorted(f.message for f in r.flags),
                         ["The answer gave the wrong owner for ABC-A-001. The report says: Owner One.",
                          "The answer gave the wrong title for ABC-A-001. The report says: Order the test kit."])

    def test_no_message_starts_with_the_product_name_or_a_write_verb(self):
        for flag_text in (ask.UNREADABLE, ask.NOT_SENT):
            self.assertFalse(flag_text.lower().startswith(("clark", "ask clark")))


if __name__ == "__main__":
    unittest.main()
