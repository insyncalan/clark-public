"""

Run: python3 dev/run_tests.py test_page_words
The real page runs in headless Chrome against a real server whose data_for is a fake that fails on demand (a KeyError, no
answer for the project, a connection that drops), or whose token check is made to refuse (a wrong token). Each case shows the
exact plain wording and never a Python class name, "JSON", "Not allowed", "Bad request" or "report editor"; "Try again" brings
the page back when the fake does. The server's own messages are #33's file: the page must be safe whatever they say.
"""
import re
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from _paths import SRC

from clark import page, server as sv  # noqa: E402
from test_page import DATA, navigate  # noqa: E402
from test_server import Running, chrome, wait  # noqa: E402

READ_FAILED = "This project could not be read. Reload the page. If it happens again, restart clark."
HIT_PROBLEM = "A problem came up reading this project. Reload the page. If it happens again, restart clark."
NOT_ACCEPTED = "That request was not accepted. Reload the page."
STALE = "This page is out of date: clark was restarted after you opened it. Reload the page and try again."
NOT_ANSWERING = "Nothing is running behind this page: clark stops by itself after a while with nothing open. Start it again from clark.command."
WENT_WRONG = "Something went wrong"
NEVER = re.compile(r"\w*(Error|Exception)\b|Traceback|JSON|Not allowed|Bad request|[Rr]eport editor|\bClark\b|\bUC\b|!")
PAGE_SRC = Path(page.PAGE).parent / "src"
WAIT = 30     # seconds to poll for what the page should show: a busy machine can take far longer than a quiet one


class Fake:
    """A data_for that can be told to fail: ok, keyerror, none, drop (the connection ends without a reply), wait."""

    def __init__(self):
        self.mode = "ok"
        self.release = threading.Event()

    def __call__(self, code):
        if self.mode == "keyerror":
            raise KeyError("secret/path/name")
        if self.mode == "none":
            return None
        if self.mode == "drop":
            raise ConnectionResetError()
        if self.mode == "wait":
            self.release.wait(WAIT)
        return DATA.get(code)


def lines(cdp, sid):
    """The visible text of the page's main area, as its non-empty lines."""
    text = cdp.js("document.querySelector('main').innerText", sid) or ""
    return [x.strip() for x in text.splitlines() if x.strip()]


class Words(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self.s = Running(data_for=self.fake, page_html=lambda: page.page_html(tempfile.mkdtemp()))
        self.addCleanup(self.s.close)
        quiet = mock.patch.object(sv.LOG, "disabled", True)   # the server logs a fault on purpose
        quiet.start()
        self.addCleanup(quiet.stop)

    def visit(self, cdp, hash_="#dashboard&p=ABC"):
        return navigate(cdp, self.s.port, hash_)

    def shown(self, cdp, sid, expected):
        self.assertTrue(wait(lambda: lines(cdp, sid) == expected, WAIT), f"wanted {expected}, the page shows {lines(cdp, sid)}")
        self.assertIsNone(NEVER.search(" ".join(lines(cdp, sid))), lines(cdp, sid))

    def recovers(self, cdp, sid):
        self.fake.mode = "ok"
        cdp.js("document.querySelector('.again').click()", sid)
        self.assertTrue(wait(lambda: cdp.js("document.querySelector('h1') && document.querySelector('h1').textContent", sid)
                             == "Example Programme", WAIT), "Try again brought the report back")

    def test_a_fault_in_the_data_shows_no_error_name_and_try_again_recovers(self):
        self.fake.mode = "keyerror"
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.shown(cdp, sid, [WENT_WRONG, HIT_PROBLEM, "Try again"])
            self.recovers(cdp, sid)

    def test_a_project_that_is_not_there_says_so_and_what_to_check(self):
        self.fake.mode = "none"
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.shown(cdp, sid, ["That project isn't here", "There is no project with that code. Check the code in the address, or choose a project from the list."])

    def test_a_connection_that_ends_without_a_reply_says_clark_is_not_answering(self):
        self.fake.mode = "drop"
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.shown(cdp, sid, [WENT_WRONG, NOT_ANSWERING, "Try again"])
            self.recovers(cdp, sid)

    def test_a_server_that_is_stopped_says_clark_is_not_answering_and_try_again_works_when_it_is_back(self):
        port = self.s.port

        def page_then_stop():
            """Serves the page, then clark's window closes: the page's own request for the data finds nobody."""
            threading.Thread(target=lambda: (self.s.httpd.shutdown(), self.s.httpd.server_close()), daemon=True).start()
            time.sleep(0.5)
            return page.page_html(tempfile.mkdtemp())
        self.s.httpd.page_html = page_then_stop
        with chrome() as cdp:
            sid = navigate(cdp, port, "#dashboard&p=ABC")
            self.shown(cdp, sid, [WENT_WRONG, NOT_ANSWERING, "Try again"])
            back = sv.LocalServer((sv.HOST, port), data_for=self.fake)       # clark is opened again, on the same port
            threading.Thread(target=back.serve_forever, daemon=True).start()
            self.addCleanup(lambda: (back.shutdown(), back.server_close()))
            self.recovers(cdp, sid)

    def test_a_wrong_token_says_the_page_is_old_and_try_again_reloads_the_page(self):
        with chrome() as cdp:
            with mock.patch.object(sv, "token_ok", return_value=False):
                sid = self.visit(cdp)
                self.shown(cdp, sid, [WENT_WRONG, STALE, "Try again"])
            cdp.js("document.querySelector('.again').click()", sid)
            self.assertTrue(wait(lambda: cdp.js("document.querySelector('h1') && document.querySelector('h1').textContent", sid)
                                 == "Example Programme", WAIT), "Try again reloaded the page with this run's token")

    def test_a_refusal_with_the_servers_old_words_shows_clark_did_not_accept_that_request(self):
        def refuse(handler):
            handler.send(403, {"ok": False, "message": "Not allowed"})
            return False
        with chrome() as cdp:
            with mock.patch.object(sv.Handler, "authorised", refuse):
                sid = self.visit(cdp)
                self.shown(cdp, sid, [WENT_WRONG, NOT_ACCEPTED, "Try again"])
            cdp.js("document.querySelector('.again').click()", sid)
            self.assertTrue(wait(lambda: cdp.js("document.querySelector('h1') && document.querySelector('h1').textContent", sid)
                                 == "Example Programme", WAIT), "Try again reloaded the page")

    def test_a_message_the_page_does_not_know_is_never_shown(self):
        odd = "ValueError: bad JSON in /Users/someone/file.py"
        cases = {500: HIT_PROBLEM, 400: "That request could not be read. Reload the page.", 403: NOT_ACCEPTED, 409: READ_FAILED}
        for code, wanted in cases.items():
            def route(handler, code=code):
                handler.send(code, {"ok": False, "message": odd})
            with self.subTest(status=code), mock.patch.dict(sv.GET_ROUTES, {"/api/data": route}), chrome() as cdp:
                sid = self.visit(cdp)
                self.shown(cdp, sid, [WENT_WRONG, wanted, "Try again"])
        def missing(handler):
            handler.send(404, {"ok": False, "message": odd})
        with mock.patch.dict(sv.GET_ROUTES, {"/api/data": missing}), chrome() as cdp:
            sid = self.visit(cdp)
            self.shown(cdp, sid, ["That project isn't here", "Check the project's code."])

    def test_the_empty_pages_say_what_is_happening_or_coming(self):
        none = Running(data_for=self.fake, page_html=lambda: page.page_html(tempfile.mkdtemp()), projects=lambda: [])   # #36: no projects yet
        self.addCleanup(none.close)
        with chrome() as cdp:
            sid = navigate(cdp, none.port, "#dashboard")
            self.shown(cdp, sid, ["No project open", "There are no projects yet.",
                                  "To look around with made-up projects, close clark and start it again with python3 -m clark --demo."])
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('#report')", sid), WAIT))
            cdp.js("document.querySelector('[data-view=settings]').click()", sid)
            self.shown(cdp, sid, ["Settings", "Settings are not ready yet.",
                                  "Client folder",      # #43: the one setting built so far; the rest of Settings is FR-1
                                  "This must be a folder OneDrive syncs to the client's SharePoint. Publish copies the finished page "
                                  "into it when you tick To client; OneDrive then uploads it.",
                                  "No client folder yet.", "Choose folder",
                                  "Personal",    # #45: Settings › Personal, the section styles
                                  "These are for you, on this computer. This changes the page you edit. The published page uses Slim gaps for now.",
                                  "Section style", "Slim gaps", "Sections close together, divided by a thin line.",
                                  "Roomy gaps", "More space between sections.", "Grey headers", "Each section's title sits on a grey band.",
                                  "One card", "All the sections inside a single card.",
                                  "Keys", "Single-key shortcuts",            # #193
                                  "Letter keys such as V and E work alone on the page. Turn them off if you type by voice or hit keys by accident. Arrows, Enter, Esc and Ctrl or Cmd combinations still work.",
                                  "Backups",            # #111: the backups card; this server has no backups to list
                                  "A copy of your data is kept each day, and before an undo or an import. Choose one to look at, or to put back.",
                                  "Backups can't be shown right now. Restart clark the usual way and try again. Try again"])
        self.fake.mode = "wait"
        with chrome() as cdp:
            sid = self.visit(cdp)
            self.shown(cdp, sid, ["Loading", "Opening ABC."])
            self.fake.release.set()

    def test_a_count_and_its_noun_agree_through_one_helper(self):
        """#130 point 7: "1 day", never "1 days"; the helper is workItems.js `plural`, and no source joins a count to a noun by hand."""
        from test_work_items import CHROME, bundled  # noqa: E402
        script = bundled() + ";JSON.stringify([WI.plural(0, 'day'), WI.plural(1, 'day'), WI.plural(2, 'day'), WI.plural(1, 'open action'), WI.plural(3, 'open action'), WI.plural(2, 'entry', 'entries')])"
        with chrome() as cdp:
            tid = next(t["targetId"] for t in cdp.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
            sid = cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
            got = cdp.call("Runtime.evaluate", {"expression": script, "returnByValue": True}, sid)["result"]["value"]
        self.assertEqual(got, '["0 days","1 day","2 days","1 open action","3 open actions","2 entries"]')
        for name in ("workItems.js", "filters.js", "glanceTiles.js"):
            text = (PAGE_SRC / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\$\{[^}]*\}\s+(days|items|actions|risks|decisions)\b|item\$\{", text), name)

    def test_the_empty_pages_say_why_and_name_one_control(self):
        empty = {"project": {"code": "EMP", "name": "Empty Project"}, "milestones": [], "workstreams": [], "actions": [], "raid": [],
                 "decisions": [], "use_cases": [], "links": [], "labels": {}, "report_sections": []}
        s = Running(data_for=lambda code: empty, page_html=lambda: page.page_html(tempfile.mkdtemp()))
        self.addCleanup(s.close)
        want = {"#dashboard&p=EMP": "This report has no sections yet. Switch to Edit to add one.",
                "#work&p=EMP": "This project has no work items yet. Use Add item to add the first.",
                "#milestones&p=EMP": "No milestones are shown yet."}
        with chrome() as cdp:
            sid = navigate(cdp, s.port, "#dashboard&p=EMP")
            for hash_, words in want.items():
                cdp.js("location.hash = %r" % hash_, sid)
                self.assertTrue(wait(lambda: words in " ".join(lines(cdp, sid)), WAIT), f"{hash_}: {lines(cdp, sid)}")
        self.assertIsNone(NEVER.search(" ".join(want.values())))

    def test_the_export_says_only_what_is_known_about_where_the_file_went(self):
        """#147: the browser chooses the folder, so the page names the file and says the browser saved it, never a folder."""
        src = (PAGE_SRC / "edit" / "ProfileMenu.jsx").read_text(encoding="utf-8")
        self.assertIn("Your browser has saved \u201c${a.download}\u201d.", src)
        self.assertNotIn("Downloads folder", src)
        self.assertNotRegex(src, r"(?m)^\s*say\([^\n]*[`\"]clark")

    def test_no_text_the_page_shows_names_a_file_path_or_a_file_type(self):
        """#130 point 7: body copy names a folder by its name, never a path (the one command in the no-projects help is typed, not a path)."""
        path = re.compile(r"(?<![\w.])(~/|/Users/|[A-Za-z]:\\|\w+/\w+\.\w+)|\.(html|xlsx|json|db|md)\b")
        for f in [f for f in PAGE_SRC.rglob("*.jsx")]:
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                shown = re.findall(r">([^<>{}]{8,})<|\"([A-Z][^\"]{20,})\"", line)
                for a, b in shown:
                    self.assertIsNone(path.search(a or b), f"{f.name}:{n}: {line.strip()}")
        for name in ("publish.py", "to_client.py"):
            text = (Path(page.PAGE).parents[1] / name).read_text(encoding="utf-8")
            self.assertNotIn("The folder {folder} isn't there", text)
            self.assertNotIn("was saved in {folder},", text)

    def test_no_text_in_the_page_source_says_report_editor_or_capital_clark(self):
        files = [f for f in PAGE_SRC.rglob("*") if f.is_file()] + [PAGE_SRC.parent / "shell.css"]
        self.assertTrue(files)
        for f in files:
            text = f.read_text(encoding="utf-8").replace("X-Clark-Token", "")     # the header's name is the server's, not text
            self.assertNotIn("report editor", text.lower(), f.name)
            self.assertNotIn("Clark", text, f.name)
            self.assertIsNone(re.search(r"\bJSON\b(?!\.)", re.sub(r"//.*", "", text)) if f.suffix == ".jsx" else None, f.name)

    def test_no_sentence_on_the_page_starts_with_the_product_name(self):
        """A screen sentence does not start with the product name (the rule set in #170): every string in the page's code, at the
        start of a string and after a full stop inside one."""
        starts = re.compile(r"""(?:[`"'>]|[.!?]\s)\s*clark\s+[a-z]""", re.I)   # a word after it: an event name like "clark:open" is not a sentence
        files = sorted(PAGE_SRC.rglob("*.js")) + sorted(PAGE_SRC.rglob("*.jsx"))
        self.assertTrue(files)
        for f in files:
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("//"):
                    continue
                self.assertIsNone(starts.search(line), f"{f.name}:{n}: a sentence starts with the product name")

    def test_help_names_no_version_that_may_not_exist(self):
        """#209: the Update entry shows the button as Review X.Y.Z, not a real-looking version."""
        for path in (PAGE_SRC / "help" / "helpContent.json", PAGE_SRC.parents[3] / "system" / "prototype" / "help.js"):
            text = path.read_text(encoding="utf-8")
            self.assertIn("**Review X.Y.Z**", text, path.name)
            self.assertNotRegex(text, r"Review \d+\.\d+\.\d+", path.name)

    def test_every_publish_message_a_person_can_see_is_plain_words(self):
        """#43: the publish routes' messages hold no system text slot, no jargon and no request talk."""
        from clark import publish_flow, to_client
        jargon = re.compile(r"(?i)\(\{reason\}\)|\bpath\b|\brequest\b|true or false|\btag\b|"
                            r"\battribute\b|\bstylesheet\b|\bcss\b|tokens\.css|\bkey of this session|permission denied|errno|oserror|!")
        for module in (to_client, publish_flow):
            for key, value in module.MESSAGES.items():
                for text in (value if isinstance(value, list) else [value]):
                    self.assertIsNone(jargon.search(text), f"{module.__name__}.{key}: {text}")
                    self.assertFalse(text.lower().startswith("clark"), f"{module.__name__}.{key}: starts with the product name")
                    self.assertLessEqual(text.count("client folder"), 1, f"{module.__name__}.{key}: says 'client folder' more than once")
        for key in ("local_failed", "not_recorded", "settings_failed"):
            self.assertNotIn("{reason}", publish_flow.MESSAGES[key], key)
            self.assertNotIn("(", publish_flow.MESSAGES[key], key)

    def test_a_publish_error_about_the_brand_or_the_page_is_a_fixed_sentence(self):
        """#43 (Head): PublishError text with internal names (tokens.css, @import, build_page.py, a server token) never reaches
        a person; each real error is raised by publish and read through made_words."""
        from clark import publish, publish_flow
        page_text = "<html lang=\"en-GB\"><head><style>%s</style></head><body></body></html>"
        faults = {
            "brand_styling": [page_text % "@import url(x.css);", page_text % "a{background:url(https://x.test/a.png)}"],
            "page_shape": ['<html><body id="clark-boot"></body></html>', "<p>no html element here</p>",
                           "<html lang=\"en-GB\"><head><title>t</title></head>"],
        }
        for key, pages in faults.items():
            for html in pages:
                with self.subTest(key=key, page=html[:40]):
                    with self.assertRaises(publish.PublishError) as caught:
                        publish.render({"data": {}}, html, "2026-10-28", "t")
                    said = publish_flow.made_words(caught.exception)
                    self.assertEqual(said, publish_flow.MESSAGES[key])
                    self.assertIsNone(re.search(r"(?i)tokens\.css|@import|build_page|\btoken\b|\bbody\b|\bcss\b|python", said), said)
        for key in ("brand_styling", "page_shape"):
            self.assertRegex(publish_flow.MESSAGES[key], r"(?i)(ask |tell )")     # each says what to do next

    def test_what_is_said_about_the_export_record_claims_no_more_than_the_file_being_exactly_what_clark_wrote(self):
        """#147: the record is found only while the workbook is exactly what clark wrote (until #169). The words about an unrecorded
        workbook say so, start with no product name and promise no folder."""
        import tempfile
        from clark import excel_import
        src = (SRC / "clark" / "excel_import.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("recorded only while it is exactly what clark wrote"), 2)
        self.assertNotIn("whichever folder", src)
        for line in re.findall(r'f"(There is no record of exporting[^"]*)"', src):
            self.assertFalse(line.lower().startswith("clark"), line)
        toast = (PAGE_SRC / "edit" / "ProfileMenu.jsx").read_text(encoding="utf-8")
        self.assertNotRegex(toast, r"(?i)say\(\"done\".*(record|import)")

    def test_a_brand_link_refusal_does_not_contradict_itself(self):
        """#43: the refusal joins the held-back reason and the brand sentence; it must not say the report has something
        in it and then that the report is fine, and each brand sentence says where the link is from and what to do."""
        from clark import publish_flow, to_client
        held = to_client.MESSAGES["held_back"].format(what="a web link built into the page")
        joined = held + publish_flow.MESSAGES["brand_link"]
        self.assertNotIn("is fine", joined)
        self.assertIn("not from anything you wrote: ask whoever looks after the brand to remove it.", joined)
        self.assertNotIn("is fine", publish_flow.MESSAGES["brand_styling"])
        self.assertEqual(publish_flow.MESSAGES["brand_styling"],
                         "The brand's styling file has a web link in it, so the report can't go out. Ask whoever looks after the brand to remove it.")

    def test_the_two_low_wording_points_are_fixed_sentences(self):
        """#43: page_shape names no one 'itself' and says nothing was published; local_not_html names the ending."""
        from clark import publish_flow
        self.assertEqual(publish_flow.MESSAGES["page_shape"],
                         "Something is wrong inside clark. Nothing was published. Tell the clark team, and say what you were doing.")
        self.assertEqual(publish_flow.MESSAGES["local_not_html"], "The local copy's name must end in .html. Nothing was published.")


if __name__ == "__main__":
    unittest.main()
