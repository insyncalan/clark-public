"""#82 (BRD 5.13, FR-120 to FR-124): Help's source, src/clark/page/src/help/helpContent.json, is complete and in plain words.

Run: python3 dev/run_tests.py test_help_content
Quick tier: reads the JSON and the prototype's files, starts no browser. The logic that works on the source (tab lists, search,
places) is tested in test_help_logic.py. Counts are the prototype's, which has grown past the issue's first numbers (26 tasks
and 30 sections, not 24 and 28, after the section templates were added). Text taken out because it describes the prototype
or names creaite is in helpHeld.json, which the page never loads, and none of it may be in the shipped source.
"""
import json
import re
import unittest

from _paths import ROOT

HELP = ROOT / "src" / "clark" / "page" / "src" / "help"
SRC = json.loads((HELP / "helpContent.json").read_text(encoding="utf-8"))
HELD = json.loads((HELP / "helpHeld.json").read_text(encoding="utf-8"))
LOGIC = (HELP / "helpLogic.js").read_text(encoding="utf-8")
PROTO = ROOT / "system" / "prototype"
BASE = {"start": "start-", "howto": "howto-", "reference": "ref-"}
UI_NAMES = {"clark version and updates"}     # the name of a Settings section (BRD FR-8a), shown as a name, not as the start of a sentence
# 'Archive', 'Archive use case' and 'Show archived' are the owner's rule (we archive, never delete) and are not in the prototype, which still
# says Delete; 'Delete section' is the label the page has today (edit/Gutter.jsx), kept as it is for the ruling.
# 'Source folders for ask clark' is the name the product's Settings card still has; the prototype's card is now "Asking" (#170),
# and the product build renames it (#47).
CHECKED_BY_HAND = set(['Archive use case', '+ Add use case', 'How do I…', 'Install clark X.Y.Z', 'Movement › What changed', 'Personal › Appearance', 'Personal › Dashboard sections', 'Review X.Y.Z', 'See all work items', 'Source folders for ask clark', 'Start here', 'The line above the title', 'The project name', '⋯'])
STEPS = SRC["howto"]["tasks"]
SECTIONS = SRC["reference"]["sections"]
START = SRC["start"]


def texts(o, path=""):
    """Every string a person reads, with where it is: ids, groups, links' targets and icon names are addresses, not words."""
    skip = {"id", "g", "go"}
    if isinstance(o, str):
        yield path, o
    elif isinstance(o, list):
        for i, x in enumerate(o):
            yield from texts(x, f"{path}[{i}]")
    elif isinstance(o, dict):
        for k, v in o.items():
            if k not in skip and k != "about":
                yield from texts(v, f"{path}.{k}")


def words():
    """The strings to read as words. A job's first item is its id and its last its screen; an icon's first is its picture's name."""
    out = list(texts({"howto": SRC["howto"], "start": {k: v for k, v in START.items() if k not in ("jobs", "where")}}))
    out += [(f"job {j[0]}", s) for j in START["jobs"] for s in j[1:3]]
    out += [(f"where {w[0]}", s) for w in START["where"] for s in w[:2]]
    out += list(texts({"groups": SRC["reference"]["groups"], "sections": [{k: v for k, v in s.items() if k != "b"} for s in SECTIONS]}))
    for s in SECTIONS:
        for n, b in enumerate(s["b"]):
            out += list(texts(b[1:], f"ref {s['id']} block {n}"))
    out += [("key", s) for r in SRC["reference"]["keys"] for s in r]
    out += [("icon", s) for r in SRC["reference"]["icons"] for s in r[1:]]
    out += [("mark", s) for r in SRC["reference"]["milestone_states"] + SRC["reference"]["milestone_extra"] for s in r]
    return out


class Shape(unittest.TestCase):
    def test_three_tabs_from_one_source(self):
        self.assertEqual(SRC["tabs"], [["start", "Start here"], ["howto", "How do I…"], ["reference", "Reference"]])

    def test_the_counts(self):
        """Start here: five loop steps, five first-ten-minutes steps, twelve jobs, six places, four rules. The prototype's counts."""
        self.assertEqual((len(START["loop"]), len(START["first"]), len(START["jobs"]), len(START["where"]), len(START["rules"])),
                         (5, 5, 12, 6, 4))
        self.assertEqual((len(STEPS), len(SECTIONS)), (26, 30))
        self.assertEqual((len(SRC["reference"]["keys"]), len(SRC["reference"]["icons"])), (30, 31))

    def test_ids_are_unique_plain_and_listed_in_a_group(self):
        for kind, rows, groups in (("task", STEPS, SRC["howto"]["groups"]), ("section", SECTIONS, SRC["reference"]["groups"])):
            ids = [r["id"] for r in rows]
            self.assertEqual(len(ids), len(set(ids)), kind)
            for r in rows:
                self.assertRegex(r["id"], r"^[a-z0-9]+(-[a-z0-9]+)*$", r["id"])
                self.assertIn(r["g"], groups, r["id"])
            for g in groups:
                self.assertTrue([r for r in rows if r["g"] == g], f"the {kind} group {g} is empty")

    def test_every_entry_has_a_title_and_a_body(self):
        for t in STEPS:
            self.assertTrue(t["t"].strip() and t["w"].strip(), t["id"])
            self.assertTrue(t["s"] and all(s.strip() for s in t["s"]), t["id"])
        for s in SECTIONS:
            self.assertTrue(s["t"].strip(), s["id"])
            self.assertTrue(s["b"], s["id"])
            for kind, *rest in s["b"]:
                self.assertIn(kind, {"p", "ul", "tbl", "keys", "icons", "marks", "types", "ai"}, s["id"])
                if kind in ("p", "ul", "tbl"):
                    self.assertTrue(rest[0] and (rest[1] if kind == "tbl" else True), s["id"])
        for j in START["jobs"]:
            self.assertTrue(all(str(x).strip() for x in j), j)
        for x in START["loop"] + START["first"]:
            self.assertTrue(x["t"].strip() and x["d"].strip())
        for r in START["rules"] + START["where"]:
            self.assertTrue(r[0].strip() and r[1].strip())

    def test_every_job_is_a_task_and_every_task_goes_somewhere_real(self):
        ids = {t["id"] for t in STEPS}
        for j in START["jobs"]:
            self.assertIn(j[0], ids)
        screens = set(re.search(r"export const SCREENS = \[(.*?)\]", LOGIC).group(1).replace('"', "").replace(" ", "").split(","))
        for t in STEPS:
            self.assertIn(t["go"].split("#")[0], screens, t["id"])


class KeysVE(unittest.TestCase):
    def rows(self):
        return {r[0]: r[1] for r in SRC["reference"]["keys"]}

    def test_v_and_e_are_one_row_each_in_plain_words(self):
        rows = self.rows()
        self.assertEqual(len([r for r in SRC["reference"]["keys"] if r[0] in ("[[V]]", "[[E]]")]), 2)
        self.assertNotIn("[[V]] [[E]]", rows)
        self.assertIn("Switches to View", rows["[[V]]"])
        self.assertIn("Switches to Edit", rows["[[E]]"])
        for key in ("[[V]]", "[[E]]"):
            self.assertIn("Dashboard", rows[key])
            self.assertIn("only", rows[key])
            self.assertIn("typing in a box", rows[key])


class Places(unittest.TestCase):
    ids = {"start-" + p for p in ("top", "loop", "first", "jobs", "where", "rules", "foot")} | \
          {"howto-" + t["id"] for t in STEPS} | {"ref-" + s["id"] for s in SECTIONS}

    def all_strings(self):
        return [s for _, s in texts({"s": START, "h": SRC["howto"], "r": SRC["reference"]})]

    def test_every_link_inside_help_finds_its_place(self):
        links = {m for s in self.all_strings() for m in re.findall(r"\]\(#([^)]+)\)", s)}
        links |= {"howto-" + j[0] for j in START["jobs"]} | {"ref-keys"}
        self.assertGreater(len(links), 20)
        self.assertEqual(sorted(links - self.ids), [])

    def test_every_screen_help_sends_you_to_exists(self):
        screens = set(re.search(r"export const SCREENS = \[(.*?)\]", LOGIC).group(1).replace('"', "").replace(" ", "").split(","))
        protos = (PROTO / "views.js").read_text(encoding="utf-8")
        gos = {m for s in self.all_strings() for m in re.findall(r"\]\(go:([^)]+)\)", s)} | {j[3] for j in START["jobs"]} | \
              {w[2] for w in START["where"] if w[2]}
        self.assertGreater(len(gos), 3)
        for g in gos:
            view, _, anchor = g.partition("#")
            self.assertIn(view, screens, g)
            if anchor:
                self.assertIn(f'id="{anchor}"', protos, g)

    def test_every_place_the_prototype_opens_help_at_exists(self):
        """C.help.open('x') anywhere in the prototype or the page: x is a place or a tab."""
        used = set()
        for f in list(PROTO.glob("*.js")) + list((ROOT / "src" / "clark" / "page" / "src").rglob("*.js*")):
            used |= set(re.findall(r"help\.open\('([^']+)'\)", f.read_text(encoding="utf-8")))
        self.assertGreaterEqual(len(used), 4)
        self.assertEqual(sorted(u for u in used if u not in self.ids and u not in BASE), [])


class Words(unittest.TestCase):
    JARGON = re.compile(r"\b(sweeps?|proposals?|stag(?:e|ed|ing)|vault|live server|extract(?:s|ed|ion)?|refus(?:e|ed|al)|valid|invalid|"
                        r"tracker|prototype|demo|creaite|Claude|Tiptap|schema|database|SQLite|JSON|token|hook|script|payload)\b", re.I)
    # "close the list to apply it" is ordinary English for a filter; nothing here means creaite's apply
    PATH = re.compile(r"(?:\w+/){2,}|\.py\b|\.js\b|\.json\b|\.md\b|~/|\\")
    AMERICAN = re.compile(r"\b(color|colors|colored|organize|organized|center|behavior|favorite|gray|customize|license|canceled)\b", re.I)

    def test_no_internal_jargon_or_paths_or_creaite(self):
        found = [(p, s) for p, s in words() if self.JARGON.search(s) or self.PATH.search(s)]
        self.assertEqual(found, [])

    def test_no_line_starts_with_the_product_name_and_the_name_is_lower_case(self):
        starts = [(p, s) for p, s in words() if re.match(r"\s*(\*\*)?clark\b", s, re.I) and s not in UI_NAMES]
        self.assertEqual(starts, [])
        self.assertEqual([(p, s) for p, s in words() if re.search(r"\bClark\b", s)], [])

    def test_british_english_and_dates(self):
        self.assertEqual([(p, s) for p, s in words() if self.AMERICAN.search(s)], [])
        self.assertEqual([(p, s) for p, s in words() if re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", s)], [])
        # a date shown to a person is DD-MM-YYYY or written out; YYYY-MM-DD is allowed only inside a file name
        shown = [s for _, s in words() if re.search(r"\b\d{4}-\d{2}-\d{2}\b", s) and ".html" not in s]
        self.assertEqual(shown, [])

    def test_no_real_looking_email_or_address(self):
        self.assertEqual([(p, s) for p, s in words() if re.search(r"[\w.]+@[\w.]+|https?://", s)], [])

    def test_nothing_is_named_that_clark_does_not_have(self):
        """creaite's mail, calendar and meeting features are not clark's, nor are the report layouts that are only in the backlog (FR-4)."""
        absent = re.compile(r"\b(Outlook|transcripts?|VIP|steerco|Steerco|people register|Teams chat|sweep|meeting minutes|Cover-led|Health spine|health spine)\b")
        found = [(p, s) for p, s in words() if absent.search(s)]
        self.assertEqual(found, [])

    def test_every_button_and_label_in_bold_is_in_the_prototype(self):
        """A **bold** name is a button or label on a screen. It must be written in the prototype's other files (or be a word Help
        itself defines), so Help never names something the product does not have."""
        corpus = "\n".join(p.read_text(encoding="utf-8") for p in list(PROTO.glob("*.js")) + [PROTO / "index.html"] if p.name != "help.js")
        corpus = re.sub(r"[‘’]", "'", corpus).lower()
        missing = set()
        for p, s in words():
            for b in re.findall(r"\*\*(.+?)\*\*", s):
                name = re.sub(r"[‘’]", "'", b).strip(" .,:;…").lower()
                if name and name not in corpus:
                    missing.add(b)
        self.maxDiff = None
        # a ratchet: these were read by hand (a path through Settings, a button made of words and a number, a part of a screen
        # described in words); a NEW bold name that the prototype lacks fails here, and the review or the builder checks it
        self.assertEqual(sorted(missing - CHECKED_BY_HAND), [], "bold names that the prototype does not have: add them there, or reword Help")
        self.assertEqual(sorted(CHECKED_BY_HAND - missing), [], "no longer needed in the hand-checked list: take it out")


class Held(unittest.TestCase):
    def test_taken_out_text_is_not_in_the_shipped_source(self):
        shipped = json.dumps(SRC, ensure_ascii=False)
        self.assertGreaterEqual(len(HELD["held"]), 15)
        for h in HELD["held"]:
            self.assertTrue(h["where"] and h["text"] and h["why"])
            if len(h["text"]) > 40:
                self.assertNotIn(h["text"], shipped, h["where"])

    def test_the_page_never_loads_the_held_file(self):
        for f in (ROOT / "src" / "clark" / "page" / "src").rglob("*.js*"):
            self.assertNotIn("helpHeld", f.read_text(encoding="utf-8"), f.name)



class WordingRound(unittest.TestCase):
    """The plain-words review of the Help: each fix is pinned here so the old wording cannot come back."""
    ALL = " \n".join(s for _, s in words())

    def test_the_template_list_names_the_headline_band(self):          # HIGH (the product's own word; the held entry never reaches the built page)
        self.assertIn('"Headline band"', json.dumps(SRC["reference"]["sections"]))
        self.assertNotIn("Headline message", json.dumps(SRC))
        self.assertNotIn("Notice bar", json.dumps(SRC))

    def test_the_panel_header_does_not_say_question_mark_comes_back_from_help(self):       # HIGH
        jsx = (HELP / "Help.jsx").read_text(encoding="utf-8")
        self.assertNotIn("to come back", jsx)
        self.assertRegex(jsx, r"to open Help\. Esc or Close takes you back")

    def test_examples_are_real_dates(self):                                                  # MEDIUM
        self.assertIn("by 12-12-2026", self.ALL)
        self.assertIn("forecast 12-12-2026", self.ALL)
        self.assertNotRegex(self.ALL, r"such as DD-MM-YYYY|forecast DD-MM-YYYY")

    def test_no_report_layout_choice_is_mentioned(self):                                     # MEDIUM
        self.assertNotRegex(self.ALL, r"(?i)report layout|layout and section style|Cover-led|Editing the layout|one layout")
        self.assertIn("the report in the section style you chose", self.ALL)

    def test_no_leftover_from_the_prototype(self):                                           # MEDIUM
        self.assertNotIn("The real clark", self.ALL)
        self.assertIn("clark keeps one file a day", self.ALL)

    def test_published_line_is_plainer(self):                                                # LOW
        self.assertIn("“Published” on its date, to the client (or locally)", self.ALL)

    def test_no_results_does_not_offer_ask_clark_yet(self):                                  # MEDIUM
        self.assertNotRegex(re.search(r"export const noResults.*?\}\);", LOGIC, re.S).group(0), r'hint: "[^"]*ask clark')

class PublishFileName(unittest.TestCase):
    def test_example_file_name_is_what_publish_really_names_the_file(self):
        from clark import publish
        task = next(t for t in STEPS if t["id"] == "publish-the-report")
        example = re.search(r"for example “([^”]+)”", task["n"]).group(1)
        code, week = re.fullmatch(r"([A-Z0-9]+)-report-(\d{4}-\d{2}-\d{2})\.html", example).groups()
        self.assertEqual(publish.file_name(code, week, "2026-11-02"), example)


class LowWordsRound(unittest.TestCase):
    """The five low-priority fixes from the review."""
    ALL = " \n".join(s for _, s in words())

    def test_nothing_here_yet_is_plainer(self):
        jsx = (HELP / "Help.jsx").read_text(encoding="utf-8")
        self.assertIn("Nothing here yet. This appears when the part of clark it describes is ready.", jsx)
        self.assertNotIn("This part of Help appears", jsx)

    def test_usual_lists_not_default_views(self):
        self.assertNotIn("default views", self.ALL)
        self.assertEqual(self.ALL.count("the usual lists, the counts and the published page"), 2)

    def test_editing_line_says_what_it_does(self):
        self.assertIn("while you edit, that each change saves on its own", self.ALL)
        self.assertNotIn("“Editing", self.ALL)       # the page has no such label to quote

    def test_the_report_has_no_look_to_choose(self):
        self.assertNotIn("one look", self.ALL)
        self.assertIn("The report is the cover, then the sections in cards", self.ALL)

    def test_no_line_starts_with_ask_clark(self):
        self.assertIn("The check in ask clark warns you when", self.ALL)
        self.assertFalse([s for _, s in words() if re.match(r"(?i)ask clark[’']s\b", s.strip())])


if __name__ == "__main__":
    unittest.main()
