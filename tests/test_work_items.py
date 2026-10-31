"""#36: the Work items list (read only). Spec: docs/handoff/design-36-work-items-list.md; cases: tests/fixtures/work-items-list-cases.json.

Run: python3 dev/run_tests.py test_work_items
Part 1 runs the page's own pure functions (src/clark/page/src/workItems.js, bundled by the pinned esbuild) in headless Chrome
against every fixture case: Python can not run JavaScript, and the browser is the page's real engine. Part 2 starts the real
server on a demo database (dev/demo_data.py at a fixed CLARK_NOW), loads the committed page at 1400 and 900 px and finds every
row. The browser parts are required: they fail, never skip, without Chrome (set CLARK_CHROME to its path).
"""
import importlib.util
import json
import logging
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _paths import ROOT, SRC, TOOLS

import esbuild  # noqa: E402  (dev/tools)
from clark import page, server as sv  # noqa: E402
from clark.store import open_store  # noqa: E402
from test_page import navigate  # noqa: E402  (not used for the width: this file sets its own)
from test_server import CHROME, Running, _Collect, chrome, wait  # noqa: E402  (the #33 browser harness, shared)

CASES = json.loads((ROOT / "tests" / "fixtures" / "work-items-list-cases.json").read_text(encoding="utf-8"))
TODAY = CASES["today"]                        # 2026-10-28, also the demo database's CLARK_NOW
MODULE = SRC / "clark" / "page" / "src" / "workItems.js"
FIXED_DATE = ("(() => { const R = Date, F = new R(2026, 9, 28, 12, 0, 0).getTime();"
              " function D(...a) { return this instanceof D ? (a.length ? new R(...a) : new R(F)) : new R(F).toString(); }"
              " D.prototype = R.prototype; D.now = () => F; D.UTC = R.UTC; D.parse = R.parse; window.Date = D; })();")


def bundled(module=MODULE, name="WI"):
    """A pure module (default: the Work items rules) as one script that sets a global (`WI`). #64a's filter tests reuse it."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "wi.js"
        done = esbuild.run(["--bundle", "--format=iife", f"--global-name={name}", str(module), f"--outfile={out}"],
                           capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        return out.read_text(encoding="utf-8")


def page_target(cdp):
    tid = next(t["targetId"] for t in cdp.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
    return cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]


class Rules(unittest.TestCase):
    """The fixtures, case by case, through the page's own functions in Chrome."""

    @classmethod
    def setUpClass(cls):
        assert Path(CHROME).is_file(), f"Chrome is needed for the required browser tests: set CLARK_CHROME, or put google-chrome or chromium on the PATH ({CHROME!r})"
        script = (bundled() + ";\n(" + """(c) => ({
            due: c.due_and_pill.map((x) => ({ due: WI.dueCell(x.row, x.today || c.today), pill: WI.pillOf(x.row, x.today || c.today) })),
            colour: c.priority_colour.map((x) => WI.colourOf(x.priority)),
            owner: c.owner.map((x) => WI.ownerOf(x.owner)),
            sort: WI.sortRows(c.sort.rows, c.today).map((r) => r.id),
            count: c.count_line.map((x) => WI.countOf(x.total, x.open)),
            useCase: WI.metaOf(WI.rowsOf(c.use_case_label.data)[0]),
            kinds: WI.rowsOf({ actions: [{ id: "A", description: "a", client_visible: 1 }],
                raid: [{ id: "R", type: "Dependency", description: "r" }], decisions: [{ id: "D", decision: "d", made_by: "Q" }],
                use_cases: [], milestones: [] }).map((r) => [r.id, r.kind, r.title, r.owner, r.client]),
        })""" + ")(" + json.dumps(CASES) + ")")
        with chrome() as cdp:
            sid = page_target(cdp)
            res = cdp.call("Runtime.evaluate", {"expression": script, "returnByValue": True}, sid)
            assert "exceptionDetails" not in res, res
            cls.out = res["result"]["value"]

    def test_due_date_in_words_and_the_status_pill(self):
        for case, got in zip(CASES["due_and_pill"], self.out["due"]):
            with self.subTest(case["name"]):
                self.assertEqual(got, case["expect"])

    def test_every_priority_has_its_colour_and_the_priority_word_stays(self):
        for case, got in zip(CASES["priority_colour"], self.out["colour"]):
            with self.subTest(str(case["priority"])):
                self.assertEqual(got, {k: case[k] for k in ("colour", "word", "class")})

    def test_owner_text_and_initials(self):
        for case, got in zip(CASES["owner"], self.out["owner"]):
            with self.subTest(repr(case["owner"])):
                self.assertEqual(got, case["expect"])

    def test_the_sort_order(self):
        self.assertEqual(self.out["sort"], CASES["sort"]["expected_order"])

    def test_each_list_becomes_rows_of_its_kind_and_a_decision_s_owner_is_who_made_it(self):
        self.assertEqual(self.out["kinds"], [["A", "action", "a", None, True], ["R", "dependency", "r", None, False],
                                             ["D", "decision", "d", "Q", False]])

    def test_the_count_line_has_one_work_item_and_many_work_items(self):
        for case, got in zip(CASES["count_line"], self.out["count"]):
            with self.subTest(f"{case['total']} total, {case['open']} open"):
                self.assertEqual(got, case["expect"])

    def test_a_use_case_is_written_out_not_as_UC(self):
        self.assertEqual(self.out["useCase"], "A · " + CASES["use_case_label"]["expect"])

    def test_the_cases_cover_what_the_spec_counts(self):
        self.assertEqual((len(CASES["due_and_pill"]), len(CASES["priority_colour"]), len(CASES["owner"])), (37, 5, 8))

    def test_only_one_place_reads_the_clock(self):
        reads = [str(p.relative_to(SRC)) for p in (SRC / "clark" / "page" / "src").rglob("*.js*")
                 if re.search(r"new Date\(\)|Date\.now", p.read_text(encoding="utf-8"))]
        self.assertEqual(reads, [str(MODULE.relative_to(SRC))])


def load_demo():
    """A demo database built at the fixed date; (store, {code: expected ids}, {code: name})."""
    spec = importlib.util.spec_from_file_location("demo_data", str(ROOT / "dev" / "demo_data.py"))
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    folder = Path(tempfile.mkdtemp(prefix="clark-wi-"))
    demo.build(folder / "clark.db", demo.parse_now(TODAY), onedrive_roots=[])
    store = open_store(folder / "clark.db", onedrive_roots=[])
    ids = {}
    for p in store.read("projects"):
        d = store.data_for(p["code"])
        ids[p["code"]] = sorted(r["id"] for k in ("actions", "raid", "decisions") for r in d[k])
    return store, folder, ids


class RealBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store, cls.folder, cls.ids = load_demo()
        cls.projects = cls.store.read("projects")          # read here: the store's own connection is for this thread only

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        import shutil
        shutil.rmtree(str(cls.folder), ignore_errors=True)

    def serve(self, data_for=None, projects=None):
        s = Running(data_for=data_for or self.store.data_for, projects=projects or (lambda: self.projects),
                    page_html=lambda: page.page_html(tempfile.mkdtemp()))
        self.addCleanup(s.close)
        return s

    def load_page(self, cdp, port, width, hash_):
        sid = page_target(cdp)
        cdp.call("Page.enable", {}, sid)
        cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": FIXED_DATE}, sid)
        cdp.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False}, sid)
        cdp.call("Page.navigate", {"url": "about:blank"}, sid)       # a hash-only change would not reload the page
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{port}/{hash_}"}, sid)
        return sid

    def rows(self, cdp, sid):
        return cdp.js("[...document.querySelectorAll('#work tbody tr[data-id]')].map(r => ({id: r.dataset.id, kind: r.dataset.kind,"
                      " text: r.innerText, late: !!r.querySelector('.due-l.late'), words: (r.querySelector('.due-l') || {}).textContent,"
                      " pill: r.querySelector('.pill').textContent, pillClass: r.querySelector('.pill').className}))", sid)

    def test_every_demo_row_is_listed_at_1400_and_900_px(self):
        s = self.serve()
        blocked = []
        handler = _Collect(blocked)
        sv.LOG.addHandler(handler)
        sv.LOG.setLevel(logging.INFO)
        self.addCleanup(sv.LOG.removeHandler, handler)
        self.assertEqual(set(self.ids), {"TUL", "MOSS"})
        with mock.patch.dict(sv.CSP_REPORTS, since=__import__("time").time(), n=0, dropped=0):
            for code, ids in self.ids.items():
                for width in (1400, 900):
                    with self.subTest(project=code, width=width), chrome() as cdp:
                        sid = self.load_page(cdp, s.port, width, f"#work&p={code}&f=mode:all")      # the list starts on Open (#64a); All shows every row
                        self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('#work tbody tr[data-id]').length", sid) > 0),
                                        f"{code} at {width}px drew its list")
                        rows = self.rows(cdp, sid)
                        self.assertEqual(sorted(r["id"] for r in rows), ids, f"every row of {code}, once each")
                        self.assertGreaterEqual(len(rows), 16)
                        self.assertEqual(cdp.js("document.documentElement.scrollWidth <= window.innerWidth", sid), True,
                                         f"{code} at {width}px has no sideways scroll")
                        self.assertEqual(cdp.js("[...document.querySelectorAll('#work, #work *')].filter(e => e.scrollWidth > e.clientWidth + 1"
                                                " && /auto|scroll/.test(getComputedStyle(e).overflowX)).length", sid), 0,
                                         "nothing inside the list scrolls sideways")
                        text = cdp.js("document.querySelector('#work').innerText", sid)
                        self.assertNotRegex(text, r"\d{4}-\d{2}-\d{2}", "dates read DD-MM-YYYY")
                        self.assertEqual(cdp.js("document.querySelectorAll('#work table input, #work table button:not(.grp-b), #work table select,"
                                                " #work table textarea, #work table [contenteditable]').length", sid), 0, "nothing in the list edits data (a group heading only opens and shuts its rows)")
                        self.assertIn(f"{len(ids)} items", text)
            self.assertEqual(blocked, [], f"the policy blocked nothing: {blocked}")

    def test_work_items_on_a_phone_at_390_px(self):
        """#130 point 5: nothing sideways, compact controls, Status, Due and Priority in each row, targets 24 px, text 12 px."""
        s = self.serve()
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 390, "#work&p=TUL&f=mode:all")
            self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('#work tbody tr[data-id]').length", sid) > 0))
            wide = cdp.js("[...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > window.innerWidth + 0.5).map(e => e.tagName + '.' + e.className).slice(0, 8)", sid)
            self.assertEqual(cdp.js("document.documentElement.scrollWidth <= window.innerWidth", sid), True, f"no sideways page scroll: {wide}")
            self.assertEqual(cdp.js("[...document.querySelectorAll('#work, #work *')].filter(e => e.scrollWidth > e.clientWidth + 1"
                                    " && /auto|scroll/.test(getComputedStyle(e).overflowX)).length", sid), 0, "no inner sideways scroll")
            bad = cdp.js("[...document.querySelectorAll('#work tbody tr, #work .seg, #work .fbar, #work .wbar, #work .head')]"
                         ".filter(e => { const r = e.getBoundingClientRect(); return r.left < -0.5 || r.right > window.innerWidth + 0.5 "
                         "|| e.scrollWidth > e.clientWidth + 1; }).map(e => e.className || e.tagName)", sid)
            self.assertEqual(bad, [], "every row and control sits inside the window")
            rows = cdp.js("[...document.querySelectorAll('#work tbody tr[data-id]')].map(r => ({id: r.dataset.id, cells: ['.c-status', '.c-due', '.c-prio']"
                          ".map(c => { const b = r.querySelector(c).getBoundingClientRect(); return [b.left, b.right, b.top, b.bottom, "
                          "getComputedStyle(r.querySelector(c), '::before').content]; }), item: r.querySelector('.c-item').getBoundingClientRect().bottom}))", sid)
            self.assertGreaterEqual(len(rows), 16)
            for r in rows:
                (s1, d1, p1) = r["cells"]
                self.assertEqual([s1[4], d1[4], p1[4]], ['"Status"', '"Due"', '"Priority"'], "the three labels are shown")
                for c in (s1, d1, p1):
                    self.assertGreaterEqual(c[0], 0)
                    self.assertLessEqual(c[1], 390)
                    self.assertGreaterEqual(c[2], r["item"] - 1, f"{r['id']}: under the item")
                self.assertLessEqual(s1[1], d1[0] + 1)
                self.assertLessEqual(d1[1], p1[0] + 1)
            small = cdp.js("[...document.querySelectorAll('#work, #work *')].filter(e => e.childNodes.length && [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())"
                           " && parseFloat(getComputedStyle(e).fontSize) < 12).map(e => e.className)", sid)
            self.assertEqual(small, [], "text is at least 12 px")
            cdp.js("document.querySelector('[data-fb=owner]').click()", sid)
            self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('#fbox-owner')", sid)))
            targets = cdp.js("[...document.querySelectorAll('#work .seg button, #work .fbtn, #work .newb, #fbox-owner button, #fbox-owner label')]"
                             ".filter(e => { const r = e.getBoundingClientRect(); return r.height < 24 || r.width < 24; }).map(e => e.className || e.textContent)", sid)
            self.assertEqual(targets, [], "targets are at least 24 px")
            self.assertEqual(cdp.js("(() => { const r = document.querySelector('#fbox-owner').getBoundingClientRect(); return r.left >= 0 && r.right <= window.innerWidth; })()", sid), True)
            self.assertEqual(cdp.js("document.documentElement.scrollWidth <= window.innerWidth", sid), True)

    def test_the_card_cells_never_overlap_in_a_wide_or_a_narrow_font_at_390_px(self):
        """#130 point 5: with a much wider (or narrower) font than the page's own, no two cells in a card overlap, nothing leaves its card or the window."""
        s = self.serve()
        fonts = {
            "wide": "#work, #work *, #work *::before { font-family: 'Courier New', 'DejaVu Sans Mono', monospace !important; letter-spacing: 0.12em !important; }",
            "narrow": "#work, #work *, #work *::before { font-family: 'Arial Narrow', 'Liberation Sans Narrow', sans-serif !important; letter-spacing: -0.03em !important; }",
        }
        for name, css in fonts.items():
            with chrome() as cdp:
                sid = self.load_page(cdp, s.port, 390, "#work&p=TUL&f=mode:all")
                self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('#work tbody tr[data-id]').length", sid) > 0))
                cdp.js("(() => { const sh = new CSSStyleSheet(); sh.replaceSync(%s); document.adoptedStyleSheets = [...document.adoptedStyleSheets, sh]; })()" % json.dumps(css), sid)
                res = cdp.js("(() => { const bad = []; const eps = 1;"
                             " for (const r of document.querySelectorAll('#work tbody tr[data-id]')) {"
                             "  const rb = r.getBoundingClientRect(); const cells = [...r.children].map(c => [c, c.getBoundingClientRect()]);"
                             "  if (rb.left < -eps || rb.right > window.innerWidth + eps) bad.push(r.dataset.id + ' row outside the window');"
                             "  for (const [c, b] of cells) {"
                             "   if (b.left < rb.left - eps || b.right > rb.right + eps) bad.push(r.dataset.id + ' ' + c.className + ' outside the card');"
                             "   if (c.scrollWidth > c.clientWidth + eps) bad.push(r.dataset.id + ' ' + c.className + ' wider than its box ' + c.scrollWidth + '/' + c.clientWidth);"
                             "   for (const k of c.querySelectorAll('*')) { const kb = k.getBoundingClientRect(); if (kb.right > b.right + eps) bad.push(r.dataset.id + ' ' + c.className + ' child ' + k.className + ' leaves its cell'); } }"
                             "  for (let i = 0; i < cells.length; i++) for (let j = i + 1; j < cells.length; j++) { const a = cells[i][1], b = cells[j][1];"
                             "   if (a.left < b.right - eps && b.left < a.right - eps && a.top < b.bottom - eps && b.top < a.bottom - eps) bad.push(r.dataset.id + ' ' + cells[i][0].className + ' overlaps ' + cells[j][0].className); } }"
                             " if (document.documentElement.scrollWidth > window.innerWidth) bad.push('page scrolls sideways: ' + [...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > window.innerWidth + 0.5).map(e => e.tagName + '.' + e.className).slice(0, 6).join(', '));"
                             " return bad.slice(0, 10); })()", sid)
                self.assertEqual(res, [], f"{name} font")
                self.assertGreaterEqual(cdp.js("document.querySelectorAll('#work tbody tr[data-id]').length", sid), 16)

    def test_a_group_header_and_the_labels_at_390_px(self):
        """#130 point 5: a group header row is a block as wide as the cards, and only the five td cells carry a label, in order, at 13 px."""
        s = self.serve()
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 390, "#work&p=TUL&f=mode:all")
            self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('#work tbody tr[data-id]').length", sid) > 0))
            cdp.js("(() => { const tb = document.querySelector('#work tbody'); const tr = document.createElement('tr'); tr.className = 'grp';"
                   " const th = document.createElement('th'); th.colSpan = 6; th.textContent = 'A group with a rather long name to wrap'; tr.appendChild(th);"
                   " tb.insertBefore(tr, tb.firstChild); })()", sid)
            g = cdp.js("(() => { const tr = document.querySelector('#work tr.grp'), th = tr.firstChild, row = document.querySelector('#work tbody tr[data-id]');"
                       " const a = tr.getBoundingClientRect(), b = th.getBoundingClientRect(), c = row.getBoundingClientRect();"
                       " return [getComputedStyle(tr).display, getComputedStyle(th).display, a.left, a.right, b.left, b.right, c.left, c.right]; })()", sid)
            self.assertEqual(g[:2], ["block", "block"], "the group header is a block, not a table row")
            self.assertGreaterEqual(g[2], 0)
            self.assertLessEqual(g[3], 390)
            self.assertAlmostEqual(g[2], g[6], delta=1)
            self.assertAlmostEqual(g[3], g[7], delta=1)
            self.assertLessEqual(g[5], g[3] + 0.5)
            self.assertEqual(cdp.js("document.documentElement.scrollWidth <= window.innerWidth", sid), True)
            labelled = cdp.js("[...document.querySelectorAll('#work th, #work td, #work tr')].filter(e => getComputedStyle(e, '::before').content !== 'none'"
                              " && getComputedStyle(e, '::before').content !== 'normal').map(e => e.tagName + '.' + e.className)", sid)
            self.assertTrue(labelled)
            self.assertEqual({x.split('.')[0] for x in labelled}, {"TD"}, "only cells carry a label")
            self.assertEqual({x.split('.')[1] for x in labelled}, {"c-type", "c-owner", "c-status", "c-due", "c-prio"})
            texts = cdp.js("(() => { const tr = document.querySelector('#work tbody tr[data-id]'); return [...tr.children].map(td => { const r = td.getBoundingClientRect(); return [td.className.split(' ')[0], getComputedStyle(td, '::before').content, getComputedStyle(td, '::before').fontSize, Math.round(r.top), r.left]; })"
                           ".filter(x => x[1] !== 'none' && x[1] !== 'normal').sort((p, q) => p[3] - q[3] || p[4] - q[4]).map(x => x.slice(0, 3)); })()", sid)
            self.assertEqual([(a, b) for a, b, _ in texts], [("c-type", '"Type"'), ("c-owner", '"Owner"'), ("c-status", '"Status"'), ("c-due", '"Due"'), ("c-prio", '"Priority"')])
            self.assertTrue(all(c == "13px" for _, _, c in texts), "labels are 13 px")

    def test_the_phone_rules_leave_900_and_1400_px_as_a_table(self):
        s = self.serve()
        for width in (1400, 900):
            with chrome() as cdp:
                sid = self.load_page(cdp, s.port, width, "#work&p=TUL&f=mode:all")
                self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('#work tbody tr[data-id]').length", sid) > 0))
                self.assertEqual(cdp.js("getComputedStyle(document.querySelector('#work table.items')).display", sid), "table")
                self.assertEqual(cdp.js("getComputedStyle(document.querySelector('#work tbody tr[data-id]')).display", sid), "table-row")

    def test_spot_checks_on_the_screen(self):
        s = self.serve()
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#work&p=TUL&f=mode:all")
            self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('#work tbody tr[data-id]').length", sid) > 0))
            cdp.js("document.querySelector('#group-by').click()", sid)                 # the one flat list, whose order this checks (#68's default is grouped)
            cdp.js("document.querySelector('.ddmenu [data-kind=nothing]').click()", sid)
            self.assertTrue(wait(lambda: cdp.js("!document.querySelector('tr.grp')", sid)))
            rows = {r["id"]: r for r in self.rows(cdp, sid)}
            data = self.store.data_for("TUL")
            order = [r["id"] for r in self.rows(cdp, sid)]
            self.assertEqual(order[0], "TUL-A-002", "the oldest open date comes first")
            late = rows["TUL-010"]                                    # an open Urgent issue due 25-10-2026
            self.assertEqual((late["words"], late["late"], late["pill"]), ("3 days late", True, "Red"))
            self.assertIn("25-10-2026", late["text"])
            self.assertEqual(rows["TUL-A-002"]["pill"], "Overdue")    # Delayed, but overdue wins
            closed = rows["TUL-A-003"]                                # closed: its date, no words
            self.assertIsNone(closed.get("words"))
            self.assertIn("13-10-2026", closed["text"])
            self.assertEqual(closed["pill"], "Closed")
            self.assertEqual(rows["TUL-007"]["words"], "In 7 days")
            self.assertIn("Dependency", rows["TUL-011"]["text"])      # all four RAID types are listed, by word
            self.assertIn("Assumption", rows["TUL-009"]["text"])
            self.assertEqual(rows["TUL-D-016"]["pill"], "Pending")
            self.assertEqual(rows["TUL-D-013"]["pill"], "Made")
            self.assertIn("19-08-2026", rows["TUL-D-013"]["text"])    # a made decision shows the date it was made
            self.assertIn("Use case 1.1", rows["TUL-A-001"]["text"])
            self.assertNotIn("UC ", rows["TUL-A-001"]["text"])
            self.assertIn("Shown to client", rows["TUL-A-001"]["text"])
            self.assertNotIn("Shown to client", rows["TUL-A-004"]["text"])
            self.assertEqual(cdp.js("getComputedStyle(document.querySelector('tr[data-id=TUL-010] .due-l')).color", sid),
                             "rgb(163, 48, 31)", "late words are in the red text colour")
            self.assertEqual(len(data["actions"]) + len(data["raid"]) + len(data["decisions"]), len(rows))

    def test_choosing_a_project_when_the_address_has_none(self):
        s = self.serve()
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#work")
            self.assertTrue(wait(lambda: "Choose a project." in (cdp.js("document.querySelector('main').innerText", sid) or "")))
            self.assertNotIn("work items", cdp.js("document.querySelector('main p').innerText", sid))
            self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('main li button').length", sid) == 2))
            cdp.js("document.querySelector('main li button').click()", sid)
            self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('#work tbody tr[data-id]').length", sid) > 0))

    def test_no_projects_says_so_and_how_to_look_around(self):
        s = self.serve(projects=lambda: [])
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#work")
            self.assertTrue(wait(lambda: "There are no projects yet." in (cdp.js("document.querySelector('main').innerText", sid) or "")))
            text = cdp.js("document.querySelector('main').innerText", sid)
            self.assertIn("To look around with made-up projects, close clark and start it again with python3 -m clark --demo.", text)
            self.assertNotIn("demo_data.py", text)
            self.assertNotIn("Choose a project", text)

    def test_a_project_list_that_cannot_be_read_is_not_called_empty(self):
        def broken():
            raise RuntimeError("the store is not there")
        s = self.serve(projects=broken)
        with chrome() as cdp, self.assertLogs(sv.LOG, "ERROR"):
            sid = self.load_page(cdp, s.port, 1400, "#work")
            self.assertTrue(wait(lambda: "The list of projects could not be read. Reload the page. If it happens again, restart clark." in (cdp.js("document.querySelector('main').innerText", sid) or "")))
            text = cdp.js("document.querySelector('main').innerText", sid)
            self.assertNotIn("There are no projects yet.", text)
            self.assertNotIn("the store is not there", text)

    def test_the_other_screens_say_loading_and_not_ready_in_plain_words(self):
        s = self.serve()
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#settings&p=TUL")
            self.assertTrue(wait(lambda: "Settings are not ready yet." in (cdp.js("document.querySelector('main').innerText", sid) or "")))
        gate = (SRC / "clark" / "page" / "src" / "components" / "Views.jsx").read_text(encoding="utf-8")
        self.assertIn("Opening {project.value}.", gate)
        self.assertNotIn("Loading work items", gate)

    def test_the_page_words_follow_the_rules_in_every_source_file(self):
        """User text says clark in lower case, never "UC", never "report editor" (the X-Clark-Token header is not user text)."""
        for path in (SRC / "clark" / "page" / "src").rglob("*.js*"):
            text = path.read_text(encoding="utf-8").replace("X-Clark-Token", "")
            with self.subTest(path.name):
                self.assertNotRegex(text, r"\bClark\b")
                self.assertNotIn("report editor", text.lower())
                self.assertNotIn('"UC ', text)
                self.assertNotIn("`UC ", text)

    def test_the_words_when_it_goes_wrong(self):
        s = self.serve()
        with chrome() as cdp:                                                       # no such project
            sid = self.load_page(cdp, s.port, 1400, "#work&p=NOPE")
            self.assertTrue(wait(lambda: "There is no project with that code. Check the code in the address, or choose a project from the list." in (cdp.js("document.querySelector('main').innerText", sid) or "")))
        real = sv.with_boot
        with mock.patch.object(sv, "with_boot", lambda html: real(html).replace(sv.TOKEN, "an-old-token")):
            with chrome() as cdp:                                                   # a page from before a restart
                sid = self.load_page(cdp, s.port, 1400, "#work&p=TUL")
                self.assertTrue(wait(lambda: "This page is out of date: clark was restarted after you opened it. Reload the page and try again." in
                                     (cdp.js("document.querySelector('main').innerText", sid) or "")), "the page's own words, not the server's")
                self.assertNotIn(sv.STALE_PAGE, cdp.js("document.querySelector('main').innerText", sid))
                self.assertEqual(cdp.js("document.querySelectorAll('main button').length", sid), 1, "Try again")
        broken = [True]

        def data_for(code):
            if broken[0]:
                raise RuntimeError("the store is not there")
            return self.store.data_for(code)

        s2 = self.serve(data_for=data_for)
        with chrome() as cdp, self.assertLogs(sv.LOG, "ERROR"):                     # a fault, then Try again
            sid = self.load_page(cdp, s2.port, 1400, "#work&p=TUL")
            self.assertTrue(wait(lambda: cdp.js("document.querySelector('main h1') && document.querySelector('main h1').textContent", sid) == "Something went wrong"))
            self.assertNotIn("the store is not there", cdp.js("document.querySelector('main').innerText", sid))
            self.assertIn("A problem came up reading this project. Reload the page. If it happens again, restart clark.",
                          cdp.js("document.querySelector('main').innerText", sid))
            broken[0] = False
            cdp.js("[...document.querySelectorAll('main button')].find(b => b.textContent === 'Try again').click()", sid)
            self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('#work tbody tr[data-id]').length", sid) > 0))

    def test_the_words_when_clark_does_not_answer(self):
        s = self.serve()
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#work")
            self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('main li button').length", sid) == 2))
            s.close()                                                               # clark goes away; then a project is chosen
            cdp.js("document.querySelector('main li button').click()", sid)
            self.assertTrue(wait(lambda: "Nothing is running behind this page: clark stops by itself after a while with nothing open. Start it again from clark.command." in
                                 (cdp.js("document.querySelector('main').innerText", sid) or "")))

    def test_a_project_with_no_work_items_says_so(self):
        s = self.serve(data_for=lambda code: {"project": {"code": code, "name": "Empty Project"}, "milestones": [], "workstreams": [],
                                              "actions": [], "raid": [], "decisions": [], "use_cases": [], "links": [], "labels": {}})
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#work&p=EMPTY")
            self.assertTrue(wait(lambda: "This project has no work items yet. Use Add item to add the first." in (cdp.js("document.querySelector('main').innerText", sid) or "")))


if __name__ == "__main__":
    unittest.main()
