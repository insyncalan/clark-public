"""#123: what the Activity tab is given (word diff, filter words, closing line) and the rules answered on 29-10-2026 that the
history rows do not already pin: the published page never says who last changed something."""
import re
import time
import unittest
from unittest import mock
from pathlib import Path

from _demo import USER, DemoStore
from clark import history, store as store_module

SRC = Path(__file__).resolve().parent.parent / "src" / "clark"


class WordDiff(unittest.TestCase):
    def test_same_text_has_no_pieces(self):
        self.assertEqual(history.word_diff("one two", "one two"), [])
        self.assertEqual(history.word_diff("<p>one</p>", "one"), [])

    def test_a_replaced_word_is_removed_then_added(self):
        d = history.word_diff("Order the laptops now", "Order the tablets now")
        self.assertEqual([(p["op"], p["text"]) for p in d],
                         [("same", "Order the "), ("removed", "laptops"), ("added", "tablets"), ("same", " now")])

    def test_pieces_put_back_together_read_as_the_two_texts(self):
        a, b = "Plan the move in March and tell the team", "Plan the move in April and tell all the team today"
        d = history.word_diff(a, b)
        self.assertEqual("".join(p["text"] for p in d if p["op"] != "added"), a)
        self.assertEqual("".join(p["text"] for p in d if p["op"] != "removed"), b)

    def test_markup_is_read_as_words_and_never_kept(self):
        d = history.word_diff("<p>Go <b>live</b> soon</p>", "<p>Go <script>x()</script>live later</p>")
        for p in d:
            self.assertNotIn("<", p["text"])
        self.assertIn("later", "".join(p["text"] for p in d if p["op"] == "added"))

    def test_an_empty_side_is_all_added_or_removed(self):
        self.assertEqual(history.word_diff("", "new words"), [{"op": "added", "text": "new words"}])
        self.assertEqual(history.word_diff("old words", ""), [{"op": "removed", "text": "old words"}])



class WordDiffBounds(unittest.TestCase):
    """A long edited text must not hang the Activity tab: the work is bounded whatever the size."""

    @staticmethod
    def texts(chars):
        words = ["w%d" % ((i * 7919) % 401) for i in range(chars // 4)]
        a = " ".join(words)[:chars]
        b = " ".join(("x%d" % i if i % 7 == 0 else t) for i, t in enumerate(words))[:chars]
        return a, b

    def test_a_20000_character_edit_returns_quickly(self):
        a, b = self.texts(20000)
        t = time.monotonic()
        pieces = history.word_diff(a, b)
        self.assertLess(time.monotonic() - t, 5)                # a hang guard, not a speed claim (the old code took minutes)
        self.assertTrue(pieces)

    def test_a_long_changed_stretch_is_one_removed_and_one_added_piece_whole(self):
        a, b = self.texts(20000)
        pieces = history.word_diff(a, b)
        self.assertEqual([p["op"] for p in pieces], ["removed", "added"])
        self.assertEqual(pieces[0]["text"], a.strip())
        self.assertEqual(pieces[1]["text"], b.strip())

    def test_a_small_edit_in_a_long_text_is_still_compared_word_by_word(self):
        base = " ".join("word%d" % i for i in range(3000))
        t = time.monotonic()
        pieces = history.word_diff(base, base.replace("word1500", "other"))
        self.assertLess(time.monotonic() - t, 5)                # the old code took about two minutes here
        self.assertEqual([p["op"] for p in pieces], ["same", "removed", "added", "same"])
        self.assertEqual((pieces[1]["text"], pieces[2]["text"]), ("word1500", "other"))

    def test_the_row_says_plainly_when_it_was_not_compared_word_by_word(self):
        a, b = self.texts(15000)
        row = history._with_diff({"kind": "Changed", "from": a, "to": b})
        self.assertEqual(row["diff_note"], history.NOT_COMPARED)
        self.assertIn("word by word", row["diff_note"])
        self.assertEqual([p["op"] for p in row["diff"]], ["removed", "added"])
        small = history._with_diff({"kind": "Changed", "from": "one two three", "to": "one 2 three"})
        self.assertNotIn("diff_note", small)

    def test_a_request_has_a_total_budget(self):
        a = " ".join("w%d" % i for i in range(150))
        b = " ".join("x%d" % i for i in range(150))             # about 300 tokens a side: compared alone
        budget = [history.DIFF_BUDGET]
        spent = []                                              # the budget is words, not seconds: count the words compared
        real = history.difflib.SequenceMatcher

        def counting(isjunk, x, y, autojunk=True):
            spent.append(max(len(x), len(y)))
            return real(isjunk, x, y, autojunk=autojunk)

        with mock.patch.object(history.difflib, "SequenceMatcher", counting):
            rows = [history._with_diff({"kind": "Changed", "from": a, "to": b}, budget) for _ in range(200)]
        self.assertLessEqual(sum(spent), history.DIFF_BUDGET)   # the request never compared more than its budget
        self.assertGreater(sum(spent), history.DIFF_BUDGET - max(spent))   # and used it up before it stopped comparing
        self.assertLess(len(spent), 200)
        compared = [r for r in rows if "diff_note" not in r]
        self.assertTrue(0 < len(compared) < 200)
        self.assertTrue(all(r["diff_note"] == history.NOT_COMPARED for r in rows if "diff_note" in r))

    def test_a_typed_ampersand_entity_is_not_decoded_twice(self):
        self.assertTrue(history.word_diff("a &amp;lt; b c d", "a &lt; b c d"))

class PlainAndRichFields(unittest.TestCase):
    """Review of #189: a plain-text field is compared as typed; a rich field reaches the rows as words, never markup."""
    def setUp(self):
        self.demo = DemoStore()
        self.addCleanup(self.demo.close)
        self.con = self.demo.store.con

    def rows(self, field):
        return [r for r in history.activity_for_project(self.con, "ABC")["rows"] if r["field"] == field]

    def test_a_change_inside_angle_brackets_in_a_plain_field_still_shows(self):
        a = self.demo.action(description="Keep cost < 5k and > 2k for the pilot")
        self.demo.update("actions", a, {"description": "Keep cost < 9k and > 2k for the pilot"})
        row = [r for r in self.rows("Action") if r["kind"] == "Changed"][0]
        self.assertEqual((row["from"], row["to"]), ("Keep cost < 5k and > 2k for the pilot", "Keep cost < 9k and > 2k for the pilot"))
        self.assertNotEqual(row["diff"], [])
        self.assertEqual([(p["op"], p["text"]) for p in row["diff"] if p["op"] != "same"], [("removed", "5k"), ("added", "9k")])
        created = [r for r in self.rows("Action") if r["kind"] == "Created"][0]
        self.assertEqual(created["to"], "Keep cost < 5k and > 2k for the pilot")

    def test_a_typed_entity_in_a_plain_field_is_not_decoded(self):
        self.assertTrue(history.word_diff("cost &lt; 5k now", "cost < 5k now", rich=False))
        self.assertEqual(history.word_diff("cost &lt; 5k now", "cost < 5k now"), [])      # as HTML they read the same

    def test_a_rich_field_reaches_the_rows_as_plain_words(self):
        self.demo.update("projects", "ABC", {"current_state": "<p>Build is <strong>on track</strong> &amp; tested</p>"})
        self.demo.update("projects", "ABC", {"current_state": "<p>Build is <strong>late</strong> &amp; tested</p>"})
        changed = [r for r in self.rows("Where things stand") if r["kind"] == "Changed"]
        self.assertEqual(len(changed), 2)
        newest, first = changed[0], changed[1]
        self.assertEqual((newest["from"], newest["to"]), ("Build is on track & tested", "Build is late & tested"))
        self.assertEqual((first["from"], first["to"]), ("", "Build is on track & tested"))     # a first fill from empty reads as words
        self.assertIsNone(first["diff"])
        for r in changed:
            for text in (r["from"], r["to"]):
                self.assertNotIn("<", text)
                self.assertNotIn("&amp;", text)
        self.assertEqual([(p["op"], p["text"]) for p in newest["diff"] if p["op"] != "same"], [("removed", "on track"), ("added", "late")])


class Activity(unittest.TestCase):
    def setUp(self):
        self.demo = DemoStore()
        self.addCleanup(self.demo.close)
        self.con = self.demo.store.con
        self.action = self.demo.action()

    def change(self, **c):
        with self.demo.store.step("dashboard", USER, place="peek") as st:
            st.update("actions", self.action, c)

    def test_filter_words_are_in_the_order_shown(self):
        v = history.activity_for_project(self.con, "ABC")
        self.assertEqual([f["label"] for f in v["filters"]], ["All", "Changes", "Comments and updates"])
        self.assertEqual(v["kind"], "all")
        self.assertEqual(history.activity_for_project(self.con, "ABC", "comments")["empty"], "No comments or updates yet.")

    def test_a_long_text_change_carries_a_diff_and_a_short_one_does_not(self):
        self.change(description="Draft the cut-over plan for the north office")
        self.change(description="Draft the cut-over plan for the south office")
        self.change(owner="Sam Example")
        rows = {}
        for r in history.activity_for_project(self.con, "ABC")["rows"]:
            if r["kind"] == "Changed":
                rows.setdefault(r["field"], r)                  # newest first: the north-to-south change
        ops = [p["op"] for p in rows["Action"]["diff"]]
        self.assertIn("removed", ops)
        self.assertIn("added", ops)
        owner = [r for r in history.activity_for_project(self.con, "ABC")["rows"] if r["field"] == "Owner"]
        self.assertTrue(owner and all(r["diff"] is None for r in owner))

    def test_rows_are_the_same_rows_the_sheet_reads_plus_the_diff(self):
        self.change(owner="Sam Example")
        plain = history.view_for_project(self.con, "ABC", "all", history.ROW_LIMIT)
        tab = history.activity_for_project(self.con, "ABC")
        self.assertEqual([{k: v for k, v in r.items() if k != "diff"} for r in tab["rows"]], plain["rows"])
        self.assertEqual((tab["footnote"], tab["empty"], tab["closing"]), (plain["footnote"], plain["empty"], plain["closing"]))

    def test_cut_rows_end_with_the_closing_line(self):
        for n in range(3):
            self.change(owner="Owner %d" % n)
        v = history.activity_for_project(self.con, "ABC", limit=2)
        self.assertEqual((len(v["rows"]), v["closing"]), (2, history.CLOSING_LINE))
        i = history.activity_for_item(self.con, self.action, limit=2)
        self.assertEqual((len(i["rows"]), i["closing"]), (2, history.CLOSING_LINE))
        self.assertEqual(history.activity_for_item(self.con, self.action)["closing"], "")

    def test_one_item_shows_only_its_rows(self):
        other = self.demo.action()
        self.change(owner="Sam Example")
        with self.demo.store.step("dashboard", USER, place="peek") as st:
            st.update("actions", other, {"owner": "Pat Other"})
        ids = {r["item_id"] for r in history.activity_for_item(self.con, self.action)["rows"]}
        self.assertEqual(ids, {self.action})

    def test_reading_changes_nothing(self):
        self.change(description="Draft the cut-over plan for the north office")
        before, changes = list(self.con.iterdump()), self.con.total_changes
        history.activity_for_project(self.con, "ABC")
        history.activity_for_item(self.con, self.action, "changes")
        self.assertEqual((list(self.con.iterdump()), self.con.total_changes), (before, changes))


class NeverShowsWhoLastChanged(unittest.TestCase):
    """Answered 29-10-2026: the published page never shows 'last changed by'."""

    def test_the_names_of_who_and_which_computer_never_reach_a_published_page(self):
        self.assertTrue({"by_user", "device"} <= store_module.NEVER_PUBLISH)

    def test_no_text_the_page_or_a_published_file_is_built_from_says_last_changed_by(self):
        pat = re.compile(r"last\s+(changed|edited|updated|modified)\s+by", re.I)
        hits = []
        for f in SRC.rglob("*"):
            if f.is_file() and f.suffix in (".py", ".js", ".jsx", ".css", ".json", ".md", ".txt") and "node_modules" not in f.parts:
                if pat.search(f.read_text(encoding="utf-8", errors="replace")):
                    hits.append(str(f.relative_to(SRC)))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
