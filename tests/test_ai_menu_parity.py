"""#72 round 3: the AI menu keeps creaite's lists and gives creaite's verdicts. Two parity pins, both read from fixture files copied
from creaite v2.6.11 (no creaite path is read at test time):
- the option list and the place lists (OPTIONS, PLACES, GROUPS, FORMATS) match creaite's, except the listed deliberate differences;
- the client message check gives the same verdict as creaite's on a hostile list (all blocked) and an ordinary list (none blocked)."""
import json
import unittest
from pathlib import Path

from _paths import SRC  # noqa: F401  (puts src/ on the path)
from clark import ai_menu as am

FIX = Path(__file__).parent / "fixtures"
CREAITE = json.loads((FIX / "creaite-ai-menu-v2.6.11.json").read_text(encoding="utf-8"))
CORPUS = json.loads((FIX / "ai-client-parity.json").read_text(encoding="utf-8"))

# Every deliberate difference from creaite, each recorded in docs/REUSE-FROM-CREAITE.md.
DELIBERATE_OPTION_TEXT = {
    ("custom", "name"): "Ask…",                       # clark's name for the free-text option (the prototype and the decisions file)
    ("executive", "instruction"): CREAITE["options"]["executive"]["instruction"].replace("voice below", "voice"),   # no style guide
    ("notes", "instruction"): CREAITE["options"]["notes"]["instruction"].replace(" (a Working session note's template)", ""),
}
CUT_PLACES = {"line", "report", "minutes", "client", "readonly"}      # places clark does not have
KEPT_PLACES = ("notes", "current", "plain", "email", "client_message")


def reply(text):
    return "<<<SUGGESTION\n" + text + "\nSUGGESTION>>>"


class ListsMatchCreaite(unittest.TestCase):
    def test_every_option_matches_but_the_listed_differences(self):
        self.assertEqual(set(am.OPTIONS), set(CREAITE["options"]))
        for key, theirs in CREAITE["options"].items():
            for i, field in enumerate(("name", "line", "instruction")):
                want = DELIBERATE_OPTION_TEXT.get((key, field), theirs[field])
                self.assertEqual(am.OPTIONS[key][i], want, (key, field))

    def test_the_deliberate_differences_are_real(self):
        """No listed difference is a no-op: each one differs from creaite's text, so the list cannot go stale."""
        for (key, field), text in DELIBERATE_OPTION_TEXT.items():
            self.assertNotEqual(text, CREAITE["options"][key][field], (key, field))

    def test_each_kept_place_lists_the_same_options_in_the_same_order(self):
        for place in KEPT_PLACES:
            self.assertEqual(am.PLACES[place], CREAITE["places"][place], place)

    def test_each_kept_place_groups_the_same_options(self):
        for place in KEPT_PLACES:
            self.assertEqual([[g, ids] for g, ids in am.GROUPS[place]], CREAITE["groups"][place], place)

    def test_each_kept_place_has_the_same_format(self):
        for place in KEPT_PLACES:
            self.assertEqual(am.FORMATS[place], CREAITE["formats"][place], place)

    def test_clark_has_no_place_creaite_lacks_and_leaves_out_only_the_listed_ones(self):
        self.assertEqual(set(am.PLACES), set(KEPT_PLACES))
        self.assertEqual(set(CREAITE["places"]) - set(am.PLACES), CUT_PLACES)

    def test_every_group_option_is_in_its_place_list(self):
        for place, groups in am.GROUPS.items():
            for _, ids in groups:
                self.assertTrue(set(ids) <= set(am.PLACES[place]), place)


class ClientVerdictsMatchCreaite(unittest.TestCase):
    def verdict(self, item, people=()):
        return am.check_reply(reply(item["reply"]), item["original"], "rewrite", "client_message", people)

    def test_the_hostile_list_is_all_blocked(self):
        self.assertGreaterEqual(len(CORPUS["hostile"]), 15)
        for item in CORPUS["hostile"]:
            r = self.verdict(item, CORPUS["people"])
            self.assertFalse(r["ok"], item["id"])

    def test_the_hostile_list_is_blocked_without_the_people_list_too_except_a_known_name(self):
        for item in CORPUS["hostile"]:
            self.assertFalse(self.verdict(item)["ok"], item["id"])

    def test_the_ordinary_list_is_all_shown(self):
        self.assertGreaterEqual(len(CORPUS["ordinary"]), 90)
        for item in CORPUS["ordinary"]:
            r = self.verdict(item, CORPUS["people"])
            self.assertTrue(r["ok"], (item["id"], r["message"]))

    def test_a_known_person_is_blocked_and_unknown_is_not(self):
        k = CORPUS["known_person"]
        self.assertFalse(self.verdict(k, CORPUS["people"])["ok"])
        self.assertTrue(self.verdict(k)["ok"])


if __name__ == "__main__":
    unittest.main()
