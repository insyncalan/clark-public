"""#82 (the lead): Help shows only what is on the page, says Archive for records, and spells "ask clark" in lower case.

Run: python3 dev/run_tests.py test_help_shown
Quick tier: reads files, starts no browser.

THE HELD LIST. helpContent.json is the whole Help (the prototype's, in plain words). src/clark/page/src/help/helpLater.json lists
the entries held back because the part of clark they describe is not on the page yet: they are hidden from the three tabs, the
search, the contents lists and "open at a place". HOW TO RELEASE ONE when its item merges: remove its line in helpLater.json,
then run this file. The tests below read the page's own source (every file under src/clark/page/src except Help's own words)
and fail with the names that the page does not have yet: a bold button name, a screen, or a feature word (peek, board, ask
clark, Publish ...). Fix the wording or hold the entry again. If the item adds the feature word for the first time, add its
proof to FEATURES below.
"""
import json
import re
import unittest

from _help_shown import HELP, LATER, RAW, shown_content
from _paths import ROOT

PAGE_SRC = ROOT / "src" / "clark" / "page" / "src"
SKIP = {"helpContent.json", "helpLater.json", "helpHeld.json"}
SHOWN = shown_content()
# The one place a record is really deleted today: a text section's menu (edit/Gutter.jsx). The owner has not ruled on it, so Help
# describes the button exactly as the page labels it. FOR THE RULING (the owner / the review): archive it too, or keep Delete.
SECTION_DELETE = "Delete section"
# A feature word in shown text needs proof that the page has it: a pattern that must match the page's own code (outside Help).
FEATURES = [
    ("the peek", r"\bpeek\b", r"<Peek\b"),
    ("Sneak peek", r"Sneak peek", r"Sneak peek"),
    ("the board", r"\bboard\b", r'"Board"|>Board<'),
    ("ask clark", r"ask clark", r"ask clark"),
    ("Import and Export", r"\b(Import|Export|Excel)\b", r"\b(Import|Export)\b|Excel"),
    ("Publish", r"\b(Publish|Preview|Word document)\b", r'"Publish|>Publish|"Preview|>Preview'),
    ("the profile circle", r"profile circle", r"profile"),
    ("the AI menu", r"\bAI\b", r"\bAI\b"),
    ("use cases", r"\buse cases?\b", r"[Uu]se case"),
    ("filters and grouping", r"\b(Filter by|Group by)\b", r"Filter by|Group by"),
]


def strip_comments(code):
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    return re.sub(r"(?m)(^|\s)//.*$", r"\1", code)


def page_code(include_help=False):
    out = []
    for f in sorted(PAGE_SRC.rglob("*")):
        if not f.is_file() or f.suffix not in (".js", ".jsx") or f.name in SKIP:
            continue
        if f.parent == HELP and not include_help:
            continue
        out.append(strip_comments(f.read_text(encoding="utf-8")))
    return "\n".join(out)


def strings(o):
    """Every word a person reads in a piece of the source (ids, groups, addresses and the lists' bookkeeping are not words)."""
    if isinstance(o, str):
        yield o
    elif isinstance(o, list):
        for x in o:
            yield from strings(x)
    elif isinstance(o, dict):
        for k, v in o.items():
            if k not in ("id", "g", "go", "parts", "ic", "tabs", "groups"):
                yield from strings(v)


def shown_texts():
    s = SHOWN
    out = list(strings(s["start"]) if s["start"]["parts"] else [])
    out += list(strings(s["howto"]["tasks"])) + list(strings(s["reference"]["sections"]))
    return out


class Held(unittest.TestCase):
    def test_every_held_id_is_a_real_entry_and_nothing_else_is(self):
        self.assertEqual(sorted(set(LATER["howto"]) - {t["id"] for t in RAW["howto"]["tasks"]}), [])
        self.assertEqual(sorted(set(LATER["reference"]) - {t["id"] for t in RAW["reference"]["sections"]}), [])
        self.assertEqual(sorted(set(LATER["start"]) - {"top", "loop", "first", "jobs", "where", "rules", "foot"}), [])
        for k in LATER["keys"]:
            self.assertEqual(RAW["reference"]["keys"][k["at"]][0], k["keys"], "a held key row moved: fix its position")
        for part in ("start", "howto", "reference"):
            for why in LATER[part].values():
                self.assertTrue(why.strip())

    def test_the_shown_help_is_what_is_left(self):
        s = SHOWN
        self.assertEqual([x["id"] for x in s["howto"]["tasks"]], ["use-the-board"])
        self.assertEqual([x["id"] for x in s["reference"]["sections"]], ["keys"])
        self.assertEqual(s["start"]["parts"], [])
        self.assertEqual(len(s["reference"]["keys"]), 21 - len(LATER["keys"]))
        self.assertEqual(s["howto"]["groups"], ["Work items"])
        self.assertEqual(s["reference"]["groups"], ["Keys and icons"])
        self.assertEqual(len(LATER["howto"]) + len(s["howto"]["tasks"]), len(RAW["howto"]["tasks"]))
        self.assertEqual(len(LATER["reference"]) + len(s["reference"]["sections"]), len(RAW["reference"]["sections"]))

    def test_the_source_itself_is_whole(self):
        self.assertEqual((len(RAW["howto"]["tasks"]), len(RAW["reference"]["sections"]), len(RAW["reference"]["keys"])), (26, 30, 21))


class AgainstThePage(unittest.TestCase):
    """HIGH 1: what Help shows must exist on the page as it is today."""
    CODE = page_code()
    HELPCODE = page_code(include_help=True)

    def test_every_bold_name_shown_is_on_the_page(self):
        norm = lambda t: re.sub(r"[‘’]", "'", t)
        code = norm(self.HELPCODE)
        missing = sorted({b for t in shown_texts() for b in re.findall(r"\*\*(.+?)\*\*", t) if norm(b).strip(" .,:;…") not in code})
        self.assertEqual(missing, [], "Help names buttons the page does not have: hold the entry in helpLater.json, or reword it")

    def test_every_screen_shown_is_a_tab_of_the_page(self):
        screens = set(re.findall(r'(\w+): "[A-Z]\w+"', re.search(r"export const TITLES = \{(.*?)\}", (PAGE_SRC / "stores" / "report.js").read_text(encoding="utf-8")).group(1)))
        text = " ".join(shown_texts())
        gos = {m.split("#")[0].split("+")[0] for m in re.findall(r"\]\(go:([^)]+)\)", text)}
        self.assertEqual(sorted(gos - screens), [])

    def test_no_feature_word_is_shown_before_the_page_has_the_feature(self):
        text = "\n".join(shown_texts())
        for name, shown, proof in FEATURES:
            if re.search(shown, text):
                self.assertRegex(self.CODE, proof, f"Help talks about {name}, which the page does not have yet")

    def test_the_check_has_teeth_on_the_whole_source(self):
        """On the whole source (nothing held) the same checks fail: ask clark is not on the page (the board is, from #68). Publish left this list when its button and box reached the page (#43), Import and Export when Export did (#147), and the peek when Sneak peek did (#42); a feature that has arrived can no longer be absent, and the entries still listed prove the check bites."""
        everything = " ".join(list(strings(RAW["howto"]["tasks"])) + list(strings(RAW["start"])))
        absent = [n for n, shown, proof in FEATURES if re.search(shown, everything) and not re.search(proof, self.CODE)]
        for want in ("ask clark", "Sneak peek"):
            self.assertIn(want, absent)
        names = {b for b in re.findall(r"\*\*(.+?)\*\*", everything) if b not in self.HELPCODE}
        # the count falls as features reach the page: 190 bold names, 99 still absent at #147's merge with main, 83 with the section
        # gutter (#101), whose words Help names (Add a section, the grip ...), 80 with the peek's Activity tab (#42: Help now names
        # Activity and no longer All, Updates and Source); lower this only when a feature lands, never to hide a missing one
        self.assertGreaterEqual(len(names), 80)

    def test_the_shown_keys_are_ones_the_page_answers(self):
        rows = [r[0] for r in SHOWN["reference"]["keys"]]
        self.assertEqual(rows, ["[[?]]", "[[Up]] [[Down]] [[Enter]]", "[[V]]", "[[E]]", "[[Alt+Up]] [[Alt+Down]]", "[[Home]] [[End]]"])


class NeverDelete(unittest.TestCase):
    """HIGH 2 (the owner: we never delete, we archive): a record is archived, never deleted, in everything a person reads."""
    def user_text(self):
        return [s for s in strings(RAW)] + [s for s in strings(LATER)]

    def test_no_delete_in_the_words_except_the_section_button_as_the_page_labels_it(self):
        found = []
        for s in self.user_text():
            rest = s.replace(SECTION_DELETE, "")
            found += re.findall(r"(?i)\b(delet\w*)\b", rest)
        self.assertEqual(found, [])

    def test_the_section_button_is_named_as_the_page_names_it(self):
        self.assertIn(f"**{SECTION_DELETE}**", json.dumps(RAW, ensure_ascii=False))
        self.assertIn(f'text: "{SECTION_DELETE}"', (PAGE_SRC / "edit" / "Gutter.jsx").read_text(encoding="utf-8"))
        self.assertEqual(sum(s.count(SECTION_DELETE) for s in self.user_text()), 1)

    def test_archive_says_what_it_does(self):
        text = " ".join(self.user_text())
        for part in ("Archive hides the project and everything in it from the usual lists, the counts and the published page",
                     "**Show archived** finds it", "**Restore** and **Undo** bring it back"):
            self.assertIn(part, text)
        self.assertIn("Archive use case", text)
        self.assertIn("Archive milestone", text)


class AskClark(unittest.TestCase):
    """MEDIUM: ask clark is written in lower case, wherever it is, at the start of a sentence too."""
    def test_every_spelling_in_the_help_source_is_lower_case(self):
        bad = []
        for f in sorted(HELP.iterdir()):
            if f.suffix in (".json", ".js", ".jsx"):
                bad += [(f.name, m) for m in re.findall(r"(?i)\bask clark\b", f.read_text(encoding="utf-8")) if m != "ask clark"]
        self.assertEqual(bad, [])

    def test_the_whole_page_source_too(self):
        bad = []
        for f in PAGE_SRC.rglob("*"):
            if f.is_file() and f.suffix in (".js", ".jsx", ".json"):
                bad += [(f.name, m) for m in re.findall(r"(?i)\bask clark\b", f.read_text(encoding="utf-8")) if m != "ask clark"]
        self.assertEqual(bad, [])

    def test_the_first_step_no_longer_starts_with_it(self):
        self.assertNotIn("Ask clark", json.dumps(RAW, ensure_ascii=False))
        self.assertIn("Use ask clark to **Check this report**", json.dumps(RAW, ensure_ascii=False))


class Wording(unittest.TestCase):
    """The page test stays strict (team names, dd-mm-20yy dates). Help's real example dates and the template name Headline band are in
    held entries, and a held entry is left out of the built page, so the page test passes without an exception."""
    def test_the_page_test_has_no_exception_for_help(self):
        page_test = (ROOT / "tests" / "test_page.py").read_text(encoding="utf-8")
        self.assertNotIn("Help (#82) may carry", page_test)
        self.assertNotRegex(page_test, r"for allowed in")

    def test_a_held_entry_is_not_in_the_built_page(self):
        import sys
        sys.path.insert(0, str(ROOT / "dev" / "tools"))
        import build_page
        html = build_page.build()
        self.assertNotIn("Open the report with a message", html)
        self.assertNotIn("12-12-2026", html)


if __name__ == "__main__":
    unittest.main()
