"""#64a: the Work items filters, the Add button (creaite's NewTile) and the dark-mode tokens.

Run: python3 dev/run_tests.py test_work_filters
Part 1 runs the page's own pure filter module (src/clark/page/src/filters.js, bundled by the pinned esbuild) in headless Chrome over
fixtures built from the demo store at CLARK_NOW=2026-10-28 and checks it against a second, plain-Python version of the rules.
Part 2 renders NewTile on its own. Part 3 starts the real server, loads the committed page at 1400 and 900 px and drives it with
real mouse and key events over the DevTools pipe (the harness is test_work_items's and test_server's). The browser parts are
required: they fail, never skip, without Chrome (set CLARK_CHROME to its path).
"""
import contextlib
import copy
import json
import logging
import re
import tempfile
import unittest
import urllib.parse
from datetime import date
from pathlib import Path
from unittest import mock

from _paths import ROOT, SRC
import _testpage as testpage

import build_page  # noqa: E402  (dev/tools)
import esbuild  # noqa: E402
from clark import page, server as sv  # noqa: E402
from test_server import CHROME, Running, _Collect, chrome, wait  # noqa: E402
from test_work_items import FIXED_DATE, TODAY, bundled, load_demo, page_target  # noqa: E402

PAGE_SRC = SRC / "clark" / "page" / "src"
FIELDS = ["workstream", "status", "due", "owner", "priority", "use_case", "milestone", "client"]
CLOSED = {"Closed", "Cancelled", "Made", "Withdrawn"}
NONE = "(none)"


# ---- the same rules again, in plain Python, as the oracle ----
def is_open(r):
    return r["status"] not in CLOSED


def due_of(r):
    return (r.get("needed_by") if r["status"] == "Pending" else r.get("date")) if r["kind"] == "decision" else r.get("due_date")


def bucket(r, today=TODAY):
    try:
        n = (date.fromisoformat(due_of(r) or "") - date.fromisoformat(today)).days
    except ValueError:
        return "none"
    if not is_open(r):
        return ""
    return "overdue" if n < 0 else "soon" if n <= 7 else "later"


def value(r, f):
    return {"workstream": lambda: r["workstream"] or NONE, "status": lambda: r["status"], "due": lambda: bucket(r),
            "owner": lambda: (r["owner"] or "").strip() or NONE, "priority": lambda: r["priority"] or NONE,
            "use_case": lambda: r["uc"] or NONE, "milestone": lambda: r["milestone"] or NONE,
            "client": lambda: "yes" if r["client"] else "no"}[f]()


def expect(rows, mode="open", type_="all", filters=None, nots=()):
    out = []
    for r in rows:
        if type_ == "risk" and r["kind"] not in ("risk", "issue", "assumption", "dependency"):
            continue
        if type_ in ("action", "decision") and r["kind"] != type_:
            continue
        if mode == "open" and not is_open(r) or mode == "closed" and is_open(r):
            continue
        if all((value(r, f) in vs) != (f in nots) for f, vs in (filters or {}).items() if vs):
            out.append(r["id"])
    return sorted(out)


# ---- real mouse and keys over the pipe ----
KEYS = {"Enter": (13, "\r"), " ": (32, " "), "Escape": (27, ""), "ArrowDown": (40, ""), "ArrowUp": (38, ""), "Home": (36, ""),
        "End": (35, ""), "Tab": (9, "")}


def key(cdp, sid, name):
    vk, text = KEYS[name]
    common = {"key": name, "code": {" ": "Space"}.get(name, name), "windowsVirtualKeyCode": vk}
    cdp.call("Input.dispatchKeyEvent", {"type": "keyDown", **common, **({"text": text} if text else {})}, sid)
    cdp.call("Input.dispatchKeyEvent", {"type": "keyUp", **common}, sid)


def where(cdp, sid, selector):
    # Measure only once the element has stopped changing size: a box measured mid-transition (the Add button shrinking
    # back to its "+" after it loses focus) is gone by the time the mouse gets there, and the click lands beside it.
    still = f"(e => !e || e.getAnimations({{subtree: true}}).every(a => a.playState !== 'running'))(document.querySelector({json.dumps(selector)}))"
    assert wait(lambda: cdp.js(still, sid)), f"{selector} is still moving"
    cdp.js(f"document.querySelector({json.dumps(selector)}).scrollIntoView({{block: 'center'}})", sid)
    box = cdp.js(f"(() => {{ const b = document.querySelector({json.dumps(selector)}).getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; }})()", sid)
    assert box, f"{selector} is not on the page"
    return box


def hover(cdp, sid, selector):
    x, y = where(cdp, sid, selector)
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y}, sid)


def click(cdp, sid, selector):
    x, y = where(cdp, sid, selector)
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y}, sid)
    cdp.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1}, sid)
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "buttons": 0, "clickCount": 1}, sid)


def need_chrome():
    assert Path(CHROME).is_file(), f"Google Chrome is needed for the required browser tests ({CHROME}); set CLARK_CHROME"


# ---- part 1: the rules ----
class Rules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        need_chrome()
        cls.store, cls.folder, cls.ids = load_demo()
        cls.data = {p["code"]: cls.store.data_for(p["code"]) for p in cls.store.read("projects")}
        cls.stack = contextlib.ExitStack()
        cls.cdp = cls.stack.enter_context(chrome())
        cls.sid = page_target(cls.cdp)
        entry = Path(tempfile.mkdtemp()) / "entry.js"
        entry.write_text(f'export * from "{PAGE_SRC / "filters.js"}"; export {{ rowsOf }} from "{PAGE_SRC / "workItems.js"}";\n', encoding="utf-8")
        script = bundled(entry, "F") + f";\nwindow.TODAY = {json.dumps(TODAY)}; window.DATA = {json.dumps(cls.data)};" \
            " window.ROWS = Object.fromEntries(Object.entries(DATA).map(([k, d]) => [k, F.rowsOf(d)])); true"
        res = cls.cdp.call("Runtime.evaluate", {"expression": script, "returnByValue": True}, cls.sid)
        assert "exceptionDetails" not in res, res
        cls.rows = cls.js("ROWS")

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        cls.store.close()
        import shutil
        shutil.rmtree(str(cls.folder), ignore_errors=True)

    @classmethod
    def js(cls, expr):
        res = cls.cdp.call("Runtime.evaluate", {"expression": expr, "returnByValue": True}, cls.sid)
        assert "exceptionDetails" not in res, (expr, res)
        return res["result"].get("value")

    def state(self, mode="open", type_="all", filters=None, nots=()):
        s = f"F.setType(F.setMode(F.initial(), {json.dumps(mode)}), {json.dumps(type_)})"
        for f, vs in (filters or {}).items():
            s = f"F.setFilter({s}, {json.dumps(f)}, {json.dumps(list(vs))}, {json.dumps(f in nots)})"
        return s

    def got(self, code, **kw):
        return sorted(self.js(f"F.applyFilters(ROWS[{json.dumps(code)}], {self.state(**kw)}, TODAY).map(r => r.id)"))

    def test_the_demo_has_the_rows_the_oracle_expects(self):
        for code, rows in self.rows.items():
            self.assertGreaterEqual(len(rows), 16)
            self.assertEqual(sorted(r["id"] for r in rows), self.ids_all(code))

    def ids_all(self, code):
        return sorted(r["id"] for r in self.rows[code])

    def test_open_is_the_start_and_the_counts_match_the_list(self):
        for code, rows in self.rows.items():
            with self.subTest(code):
                self.assertEqual(self.js("F.initial().mode"), "open")
                c = self.js(f"F.counts(ROWS[{json.dumps(code)}], F.initial(), TODAY)")
                self.assertEqual(c, {"open": len(expect(rows)), "closed": len(expect(rows, "closed")), "all": len(rows)})
                self.assertGreater(c["closed"], 0)
                self.assertEqual(self.got(code), expect(rows))
                self.assertEqual(self.got(code, mode="closed"), expect(rows, "closed"))
                self.assertEqual(self.got(code, mode="all"), sorted(r["id"] for r in rows))

    def test_each_filter_gives_the_rows_the_oracle_gives_one_value_at_a_time(self):
        for code, rows in self.rows.items():
            for f in FIELDS:
                values = sorted({value(r, f) for r in rows if value(r, f)})
                self.assertGreaterEqual(len(values), 1, f)
                for v in values:
                    for mode in ("open", "all"):
                        with self.subTest(code=code, field=f, value=v, mode=mode):
                            self.assertEqual(self.got(code, mode=mode, filters={f: [v]}), expect(rows, mode, filters={f: [v]}))

    def test_is_not_is_the_other_rows(self):
        for code, rows in self.rows.items():
            for f in ("owner", "priority", "due", "client", "status"):
                v = sorted({value(r, f) for r in rows if value(r, f)})[0]
                with self.subTest(code=code, field=f):
                    got = self.got(code, mode="all", filters={f: [v]}, nots=[f])
                    self.assertEqual(got, expect(rows, "all", filters={f: [v]}, nots=[f]))
                    self.assertEqual(sorted(got + self.got(code, mode="all", filters={f: [v]})), self.ids_all(code))

    def test_several_values_in_one_filter_are_any_of_and_several_filters_are_all_of(self):
        for code, rows in self.rows.items():
            owners = sorted({value(r, "owner") for r in rows})[:2]
            combos = [{"owner": owners}, {"owner": owners, "priority": ["High", "Urgent"]},
                      {"due": ["overdue", "soon"], "client": ["yes"]}, {"priority": ["High"], "status": ["Open", "Delayed"], "client": ["no"]}]
            for filters in combos:
                for mode in ("open", "all"):
                    with self.subTest(code=code, filters=filters, mode=mode):
                        self.assertEqual(self.got(code, mode=mode, filters=filters), expect(rows, mode, filters=filters))

    def test_type_and_mode_and_filters_together(self):
        for code, rows in self.rows.items():
            for type_ in ("action", "risk", "decision"):
                for mode in ("open", "closed", "all"):
                    with self.subTest(code=code, type=type_, mode=mode):
                        self.assertEqual(self.got(code, mode=mode, type_=type_), expect(rows, mode, type_))
                        self.assertEqual(self.got(code, mode=mode, type_=type_, filters={"client": ["yes"]}), expect(rows, mode, type_, {"client": ["yes"]}))
            self.assertEqual({r["kind"] for r in rows if r["kind"] not in ("action", "decision")} - {"risk", "issue", "assumption", "dependency"}, set())

    def test_the_switch_counts_follow_the_other_filters_so_the_mode_that_is_on_equals_the_list(self):
        for code, rows in self.rows.items():
            for filters, type_ in (({}, "all"), ({"owner": [value(rows[0], "owner")]}, "all"), ({"due": ["overdue"]}, "action"),
                                   ({"client": ["yes"], "priority": ["High", "Medium"]}, "all"), ({"status": ["Closed"]}, "risk")):
                with self.subTest(code=code, filters=filters, type=type_):
                    c = self.js(f"F.counts(ROWS[{json.dumps(code)}], {self.state(type_=type_, filters=filters)}, TODAY)")
                    for mode in ("open", "closed", "all"):
                        self.assertEqual(c[mode], len(expect(rows, mode, type_, filters)), mode)
                    self.assertEqual(c["open"] + c["closed"], c["all"])
                    t = self.js(f"F.typeCounts(ROWS[{json.dumps(code)}], {self.state(type_=type_, filters=filters)}, TODAY)")
                    self.assertEqual(t[type_], len(expect(rows, "open", type_, filters)))

    def test_an_option_list_has_each_value_with_the_count_it_would_give(self):
        for code, rows in self.rows.items():
            for f in FIELDS:
                for mode in ("open", "all"):
                    with self.subTest(code=code, field=f, mode=mode):
                        opts = self.js(f"F.options(ROWS[{json.dumps(code)}], {json.dumps(f)}, {self.state(mode=mode)}, TODAY)")
                        self.assertEqual(len({o["value"] for o in opts}), len(opts), "no value twice")
                        for o in opts:
                            self.assertEqual(o["count"], len(expect(rows, mode, filters={f: [o["value"]]})), o)
                            self.assertTrue(o["label"])
                            self.assertFalse(o["chosen"])
        opts = self.js(f"F.options(ROWS.TUL, 'due', F.initial(), TODAY)")
        self.assertEqual([o["label"] for o in opts], ["Overdue", "Due in 7 days", "No date", "Later"])
        self.assertEqual([o["label"] for o in self.js("F.options(ROWS.TUL, 'priority', F.initial(), TODAY)")][:4], ["Urgent", "High", "Medium", "Low"])
        self.assertEqual([o["label"] for o in self.js("F.options(ROWS.TUL, 'client', F.initial(), TODAY)")], ["Shown to the client", "Internal only"])
        mine = self.js("F.options(ROWS.TUL, 'owner', F.setFilter(F.initial(), 'owner', ['Nobody Here'], false), TODAY)")
        self.assertIn(("Nobody Here", 0, True), [(o["value"], o["count"], o["chosen"]) for o in mine], "a chosen value stays listed, so it can be un-ticked")

    def test_plain_names_for_every_filter_and_value(self):
        self.assertEqual(self.js("F.FIELDS.map(f => F.NAMES[f])"), ["Workstream", "Status", "Due", "Owner", "Priority", "Use case", "Milestone", "Client", "Freshness"])
        self.assertEqual(self.js("F.NAMES.use_case + '|' + F.labelOf('owner', F.NONE) + '|' + F.labelOf('use_case', F.NONE) + '|' + F.labelOf('milestone', F.NONE)"),
                         "Use case|No owner|No use case|No milestone")
        for code in self.rows:
            for f in FIELDS:
                for o in self.js(f"F.options(ROWS[{json.dumps(code)}], {json.dumps(f)}, F.initial(), TODAY)"):
                    self.assertNotIn(o["label"], ("yes", "no", "overdue", "soon", "later", "none", "(none)", ""), f"{f}: {o}")

    def test_review_is_not_offered_until_a_row_carries_dates(self):
        # Nobody can pick a filter that can never match; an address that already carries it still decodes and still lists it.
        names = lambda expr: self.js(f"F.offeredFields({expr}).map(f => F.NAMES[f])")
        for code in self.rows:
            self.assertNotIn("Freshness", names(f"ROWS[{json.dumps(code)}], F.initial()"), code)
        self.assertEqual(names("ROWS.TUL, F.initial()"), ["Workstream", "Status", "Due", "Owner", "Priority", "Use case", "Milestone", "Client"])
        for extra in ("{raised: '2026-10-01'}", "{last_reviewed: '2026-10-01'}", "{not_reviewed: false}"):
            self.assertIn("Freshness", names(f"[{extra}], F.initial()"), extra)
        st = "F.decode('reviewed:stale')"
        self.assertEqual(self.js(f"{st}.filters.reviewed"), ["stale"])
        self.assertIn("Freshness", names(f"ROWS.TUL, {st}"), "a filter already on stays listed so it can be removed")

    def test_a_none_status_reads_in_plain_words(self):
        self.assertEqual(self.js("F.labelOf('status', F.NONE)"), "No status")

    def test_due_buckets_at_the_boundaries(self):
        mk = lambda kind, status, **kw: {"id": f"{kind}-{status}-{len(kw)}{kw.get('due_date', kw.get('needed_by', kw.get('date', 'x')))}", "kind": kind, "status": status, "workstream": "", "owner": "", "priority": "", "uc": "", "milestone": "", "client": False, **kw}
        cases = [("2026-10-27", "overdue"), ("2026-10-28", "soon"), ("2026-11-04", "soon"), ("2026-11-05", "later"), (None, "none"), ("", "none"),
                 ("2026-02-30", "none"), ("not a date", "none")]
        rows = [mk("action", "Open", due_date=d) for d, _ in cases]
        got = self.js(f"F.applyFilters({json.dumps(rows)}, F.setMode(F.initial(), 'all'), TODAY).map(r => F.dueBucket(r, TODAY))")
        self.assertEqual(got, [b for _, b in cases])
        # the day changes with the clock handed in, never with this computer's
        self.assertEqual(self.js(f"F.dueBucket({json.dumps(rows[1])}, '2026-10-29')"), "overdue")
        self.assertEqual(self.js(f"F.dueBucket({json.dumps(rows[1])}, '2026-10-21')"), "soon")
        self.assertEqual(self.js(f"F.dueBucket({json.dumps(rows[1])}, '2026-10-20')"), "later")
        # work that is done is in no bucket (Overdue never lists it); a pending decision counts its needed-by date, a made one has none
        self.assertEqual(self.js(f"F.dueBucket({json.dumps(mk('action', 'Closed', due_date='2026-10-01'))}, TODAY)"), "")
        self.assertEqual(self.js(f"F.dueBucket({json.dumps(mk('decision', 'Pending', needed_by='2026-10-20', date='2026-12-01'))}, TODAY)"), "overdue")
        self.assertEqual(self.js(f"F.dueBucket({json.dumps(mk('decision', 'Made', needed_by='2026-10-20', date='2026-12-01'))}, TODAY)"), "")
        self.assertEqual(self.js(f"F.dueBucket({json.dumps(mk('decision', 'Made'))}, TODAY)"), "none")
        for code, rows_ in self.rows.items():
            self.assertTrue(all(bucket(r) == self.js(f"F.dueBucket({json.dumps(r)}, TODAY)") for r in rows_))

    def test_chips_beside_the_count_and_clear_all(self):
        s = self.state(mode="closed", type_="action", filters={"due": ["overdue", "none"], "owner": ["Sam Rivers"], "client": ["yes"]}, nots=["owner"])
        chips = self.js(f"F.chips({s}).map(c => c.text)")
        self.assertEqual(chips, ["Due: Overdue, No date", "Owner is not: Sam Rivers", "Client: Shown to the client"])
        self.assertEqual(self.js(f"F.chips({s}).map(c => c.field)"), ["due", "owner", "client"])
        self.assertEqual(self.js(f"[F.isActive({s}, 'due'), F.isActive({s}, 'owner'), F.isActive({s}, 'status'), F.isActive({s}, 'client')]"), [True, True, False, True])
        self.assertTrue(self.js(f"F.canClear({s})"))
        self.assertEqual(self.js(f"F.clearAll({s})"), self.js("F.initial()"))
        self.assertEqual(self.js("F.chips(F.clearAll(" + s + "))"), [])
        self.assertFalse(self.js("F.canClear(F.initial())"))
        self.assertTrue(self.js("F.canClear(F.setMode(F.initial(), 'all'))"))
        self.assertTrue(self.js("F.canClear(F.setType(F.initial(), 'risk'))"))
        # one chip off, the others stay; un-ticking the last value takes the filter (and its "is not") away
        self.assertEqual(self.js(f"F.chips(F.removeFilter({s}, 'owner')).map(c => c.field)"), ["due", "client"])
        self.assertEqual(self.js("F.chips(F.toggleValue(F.toggleValue(F.initial(), 'owner', 'A'), 'owner', 'A'))"), [])
        # Clear all brings back the count: the list is the start list again
        for code, rows in self.rows.items():
            self.assertEqual(sorted(self.js(f"F.applyFilters(ROWS[{json.dumps(code)}], F.clearAll({s}), TODAY).map(r => r.id)")), expect(rows))
        self.assertEqual(self.js("[F.countText(1, 'open'), F.countText(15, 'open'), F.countText(0, 'closed'), F.countText(17, 'all')]"),
                         ["1 open item", "15 open items", "0 closed items", "17 items"])

    def test_a_change_returns_a_new_state_and_leaves_the_old_one_alone(self):
        got = self.js("""(() => { const a = F.setFilter(F.initial(), 'owner', ['A'], false), before = JSON.stringify(a);
            const b = F.toggleValue(a, 'owner', 'B'), c = F.setNot(b, 'owner', true), d = F.setMode(c, 'all'), e = F.removeFilter(d, 'owner');
            return [JSON.stringify(a) === before, a !== b, b.filters.owner, c.not.owner === true, b.not.owner === undefined, d.mode, F.initial().mode, e.filters.owner === undefined, F.setFilter(a, 'nonsense', ['x']) === a]; })()""")
        self.assertEqual(got, [True, True, ["A", "B"], True, True, "all", "open", True, True])
        self.assertTrue(self.js("(() => { const s = F.setFilter(F.initial(), 'owner', ['A'], false); return [F.initial(), s, F.decode('owner:a')].every(x => Object.getPrototypeOf(x.filters) === Object.prototype && Object.getPrototypeOf(x.not) === Object.prototype); })()"),
                        "the filters are a plain object, never a Map")

    # What the router accepts in `f` as it stands (router.js F_TEXT, MAX_F), copied here so a change on either side fails a test.
    F_TEXT = re.compile(r"^(?:[A-Za-z0-9\-._~!$'()*+,;:@/?]|%[0-9A-Fa-f]{2})*$")

    def encoded(self, s):
        """[the text, whether decode(text) gives back the state s, the length]."""
        return self.js(f"(() => {{ const k = (o) => JSON.stringify(o, (_, v) => (v && v.constructor === Object ? Object.fromEntries(Object.entries(v).sort()) : v)); const s = {s}, t = F.encode(s); return [t, k(F.decode(t)) === k(s), t.length]; }})()")

    def test_encode_and_decode_round_trip(self):
        cases = [self.state(), self.state(mode="closed"), self.state(mode="all", type_="risk"),
                 self.state(filters={"owner": ["Sam Rivers", "Zoë O'Neil"], "due": ["overdue"]}, nots=["owner"]),
                 self.state(mode="closed", type_="decision", filters={f: ["a, b", "c&d", "e=f", "50%", "#x", NONE, "ü ñ 日本"] for f in FIELDS[:4]}, nots=["status", "workstream"])]
        for s in cases:
            with self.subTest(s[:80]):
                text, same, _ = self.encoded(s)
                self.assertTrue(same, "decode(encode(state)) is the state")
                self.assertRegex(text, self.F_TEXT, "only characters the router carries as they stand")
        self.assertEqual(self.js("F.encode(F.initial())"), "", "the start state adds nothing to the address")
        self.assertEqual(self.js("F.encode(F.setMode(F.initial(), 'closed'))"), "mode:closed")
        self.assertEqual(self.js("F.encode(F.setFilter(F.initial(), 'owner', ['Sam Rivers'], true))"), "not:owner;owner:Sam%20Rivers")

    def test_encode_writes_percent_signs_ampersands_equals_and_unicode_as_escapes_that_come_back(self):
        # '%26' is an ampersand, '%3D' an equals sign: the value "a%26b" (a percent sign in the name) must not be read as "a&b".
        for v, want in (("a&b", "owner:a%26b"), ("a=b", "owner:a%3Db"), ("a%26b", "owner:a%2526b"), ("a%3Db", "owner:a%253Db"),
                        ("50%", "owner:50%25"), ("日本 ü", "owner:%E6%97%A5%E6%9C%AC%20%C3%BC"), ("a,b;c:d", "owner:a%2Cb%3Bc%3Ad")):
            with self.subTest(v):
                s = f"F.setFilter(F.initial(), 'owner', [{json.dumps(v)}], false)"
                text, same, _ = self.encoded(s)
                self.assertEqual(text, want)
                self.assertTrue(same)
                self.assertNotRegex(text, r"[=&#]")
                self.assertRegex(text, self.F_TEXT)
        self.assertEqual(self.js("F.decode('owner:a%26b,c%3Dd').filters.owner"), ["a&b", "c=d"])
        self.assertEqual(self.js("F.decode('owner:a%2526b').filters.owner"), ["a%26b"], "one decoding only, never two")

    def test_decode_is_total_garbage_gives_no_filters_and_it_never_throws(self):
        junk = ["", None, 5, {}, [], "mode:sideways", "type:;owner:", "owner:%E0%A4%A", "owner:%", "owner:%zz", "owner:%ED%A0%80", "owner:%00",
                "nonsense:1;;:;a", "#work&p=TUL", "not:owner", "due:overdue,,", "mode=closed", "__proto__:x;constructor:y;owner:__proto__",
                ";" * 2000, "owner:" + "%41" * 5000, "mode:closed;mode:all;mode:open", "\u0000\ud800", "owner:a;owner:b"]
        for j in junk:
            with self.subTest(str(j)[:30]):
                got = self.js(f"(() => {{ try {{ const s = F.decode({json.dumps(j)}); return [s.mode, s.type, Object.keys(s).sort().join(), Object.keys(s.filters).join(), Object.keys(Object.prototype).length, ({{}}).x]; }} catch (e) {{ return 'threw ' + e; }} }})()")
                self.assertNotIsInstance(got, str, got)
                self.assertEqual(got[2], "filters,mode,not,type", "decode reads only the filters, never the view or the project")
                self.assertEqual(got[4:], [0, None], "nothing on Object.prototype")
        for j in ["", None, 5, "mode:sideways", "owner:%E0%A4%A", "owner:%", "nonsense:1;;:;a", "#work&p=TUL", "mode=closed", "__proto__:x", "owner:%00"]:
            with self.subTest("none " + str(j)):
                self.assertEqual(self.js(f"F.decode({json.dumps(j)})"), self.js("F.initial()"), "garbage gives no filters at all")
        self.assertEqual(self.js("F.decode('due:overdue,,soon;not:owner').filters"), {"due": ["overdue", "soon"]})
        self.assertEqual(self.js("F.decode('mode:closed;owner:a;owner:b').filters"), {"owner": ["a"]}, "the first of a repeated key wins")

    def test_over_length_is_refused_by_fits_and_cut_by_encode_and_never_beyond_the_routers_limit(self):
        many = [f"Person number {n:03d} with a longish name" for n in range(60)]
        big = f"F.setFilter(F.initial(), 'owner', {json.dumps(many)}, false)"
        self.assertEqual(self.js(f"F.fits({big})"), False, "too many values for the address: fits() says no")
        text, _, n = self.encoded(big)
        self.assertLessEqual(n, 600)
        self.assertRegex(text, self.F_TEXT)
        self.assertEqual(self.js(f"F.decode(F.encode({big})).filters.owner")[0], many[0], "encode keeps the first values and cuts the last")
        self.assertEqual(self.js("F.MAX_F"), 600)
        one = self.js("F.encode(F.setFilter(F.initial(), 'owner', ['x'.repeat(700)], false))")
        self.assertEqual(one, "", "one value that can never fit gives nothing, not a half value")
        self.assertEqual(self.js("F.fits(F.setFilter(F.initial(), 'owner', ['Sam Rivers'], false))"), True)
        # exactly at the limit still fits; one more does not
        for n_, ok in ((600 - len("owner:"), True), (600 - len("owner:") + 1, False)):
            self.assertEqual(self.js(f"F.fits(F.setFilter(F.initial(), 'owner', ['x'.repeat({n_})], false))"), ok)
        # a value the router would drop the whole `f` for (a control character, a lone surrogate) is left out, never written
        for bad in ("a\\u0000b", "a\\ud800b", "a\\nb"):
            with self.subTest(bad):
                s = f"F.setFilter(F.initial(), 'owner', ['ok', '{bad}'], false)"
                self.assertEqual(self.js(f"F.encode({s})"), "owner:ok")
                self.assertEqual(self.js(f"F.fits({s})"), False)

    def test_the_add_words_follow_the_type_switch(self):
        plan = lambda t: self.js(f"F.addPlan({json.dumps(t)})")
        self.assertEqual(plan("action"), {"word": "Add action", "kind": "action", "menu": None})
        self.assertEqual(plan("decision"), {"word": "Add decision", "kind": "decision", "menu": None})
        self.assertEqual(plan("risk"), {"word": "Add risk or issue", "kind": None, "menu": [{"kind": "risk", "word": "Add risk"}, {"kind": "issue", "word": "Add issue"}]})
        self.assertEqual(plan("all")["word"], "Add item")
        self.assertEqual([m["word"] for m in plan("all")["menu"]], ["Add action", "Add risk", "Add issue", "Add decision"], "on All, a menu of every type")


# ---- part 2: NewTile on its own ----
class NewTile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        need_chrome()
        entry = Path(tempfile.mkdtemp()) / "entry.jsx"
        entry.write_text(f'import {{ render }} from "preact"; import {{ NewTile }} from "{PAGE_SRC / "components" / "NewTile.jsx"}";\n'
                         "window.draw = (props) => render(<NewTile {...props} onAdd={(k) => (window.CALLS = (window.CALLS || []).concat([k]))} />, document.getElementById('host'));\n", encoding="utf-8")
        out = entry.parent / "tile.js"
        done = esbuild.run(["--bundle", "--format=iife", "--tsconfig-raw={}", *build_page.preact_flags(), str(entry), f"--outfile={out}"], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        cls.script = out.read_text(encoding="utf-8")
        cls.stack = contextlib.ExitStack()
        cls.cdp = cls.stack.enter_context(chrome())
        cls.sid = page_target(cls.cdp)
        cls.cdp.call("Page.enable", {}, cls.sid)
        cls.cdp.call("Emulation.setFocusEmulationEnabled", {"enabled": True}, cls.sid)

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def mount(self, **props):
        self.cdp.call("Page.navigate", {"url": "about:blank"}, self.sid)
        wait(lambda: self.cdp.js("document.readyState", self.sid) == "complete")
        self.cdp.js("document.body.innerHTML = '<div id=host></div>'; window.CALLS = []", self.sid)
        res = self.cdp.call("Runtime.evaluate", {"expression": self.script + f";draw({json.dumps(props)}); true", "returnByValue": True}, self.sid)
        self.assertNotIn("exceptionDetails", res, res)

    def listening_for_a_click_away(self):
        doc = self.cdp.call("Runtime.evaluate", {"expression": "document"}, self.sid)["result"]["objectId"]
        return any(h["type"] == "pointerdown" for h in self.cdp.call("DOMDebugger.getEventListeners", {"objectId": doc}, self.sid)["listeners"])

    def test_every_add_word_is_the_label_and_the_tooltip_and_a_click_says_what_was_added(self):
        for word, kind in (("Add action", "action"), ("Add milestone", "milestone"), ("Add project", "project"), ("Add use case", "use_case")):
            with self.subTest(word):
                self.mount(word=word, kind=kind)
                self.assertEqual(self.cdp.js("(() => { const b = document.querySelector('#newBtn'); return [b.getAttribute('aria-label'), b.title, b.dataset.tip, b.textContent, b.hasAttribute('aria-haspopup')]; })()", self.sid),
                                 [word, word, word, word, False])
                click(self.cdp, self.sid, "#newBtn")
                self.assertEqual(self.cdp.js("CALLS", self.sid), [kind])

    def test_a_plain_tile_works_from_the_keyboard(self):
        self.mount(word="Add milestone", kind="milestone")
        self.cdp.js("document.querySelector('#newBtn').focus()", self.sid)
        key(self.cdp, self.sid, "Enter")
        key(self.cdp, self.sid, " ")
        self.assertEqual(self.cdp.js("CALLS", self.sid), ["milestone", "milestone"])

    def test_a_menu_of_kinds_opens_with_the_keys_and_closes_with_escape(self):
        self.mount(word="Add item", items=[{"kind": "action", "word": "Add action"}, {"kind": "risk", "word": "Add risk"}, {"kind": "decision", "word": "Add decision"}])
        js = lambda e: self.cdp.js(e, self.sid)
        self.assertEqual(js("[document.querySelector('#newBtn').getAttribute('aria-haspopup'), document.querySelector('#newBtn').getAttribute('aria-expanded')]"), ["menu", "false"])
        js("document.querySelector('#newBtn').focus()")
        key(self.cdp, self.sid, "ArrowDown")
        self.assertTrue(wait(lambda: js("!!document.querySelector('[role=menu]')")))
        self.assertEqual(js("[...document.querySelectorAll('[role=menuitem]')].map(b => b.textContent)"), ["Add action", "Add risk", "Add decision"])
        self.assertEqual(js("document.querySelector('#newBtn').getAttribute('aria-expanded')"), "true")
        self.assertEqual(js("document.activeElement.textContent"), "Add action", "focus goes to the first item")
        key(self.cdp, self.sid, "ArrowDown")
        self.assertEqual(js("document.activeElement.textContent"), "Add risk")
        key(self.cdp, self.sid, "End")
        self.assertEqual(js("document.activeElement.textContent"), "Add decision")
        key(self.cdp, self.sid, "ArrowDown")
        self.assertEqual(js("document.activeElement.textContent"), "Add action", "the arrows wrap")
        key(self.cdp, self.sid, "ArrowUp")
        self.assertEqual(js("document.activeElement.textContent"), "Add decision")
        key(self.cdp, self.sid, "Escape")
        self.assertTrue(wait(lambda: js("!document.querySelector('[role=menu]')")))
        self.assertTrue(wait(lambda: js("document.activeElement.id") == "newBtn"), "Esc puts focus back on the button")
        key(self.cdp, self.sid, "Enter")
        self.assertTrue(wait(lambda: js("!!document.querySelector('[role=menu]')")))
        key(self.cdp, self.sid, "ArrowDown")
        key(self.cdp, self.sid, "Enter")                                 # Enter on "Add risk"
        self.assertTrue(wait(lambda: js("!document.querySelector('[role=menu]')")))
        self.assertEqual(js("CALLS"), ["risk"])
        self.assertTrue(wait(lambda: js("document.activeElement.id") == "newBtn"), "a pick puts focus back on the button")
        key(self.cdp, self.sid, "Enter")
        self.assertTrue(wait(lambda: js("document.activeElement.textContent") == "Add action"))
        key(self.cdp, self.sid, " ")                                     # Space on the first item
        self.assertEqual(js("CALLS"), ["risk", "action"])

    def test_a_click_away_closes_the_menu(self):
        self.mount(word="Add risk or issue", items=[{"kind": "risk", "word": "Add risk"}, {"kind": "issue", "word": "Add issue"}])
        click(self.cdp, self.sid, "#newBtn")
        self.assertTrue(wait(lambda: self.cdp.js("!!document.querySelector('[role=menu]')", self.sid)))
        # The menu is drawn at once, but its click-away listener is added in a useEffect, which Preact runs after the next
        # frame: under load a click sent straight away lands before anything is listening. Wait for the listener itself.
        self.assertTrue(wait(self.listening_for_a_click_away), "the open menu listens for a click away")
        self.cdp.js("document.body.insertAdjacentHTML('beforeend', '<p id=away style=\"margin-top:300px\">away</p>')", self.sid)
        click(self.cdp, self.sid, "#away")
        self.assertTrue(wait(lambda: self.cdp.js("!document.querySelector('[role=menu]')", self.sid)))
        self.assertEqual(self.cdp.js("CALLS", self.sid), [])


# ---- part 3: the real page ----
class RealBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        need_chrome()
        cls.store, cls.folder, cls.ids = load_demo()
        cls.projects = cls.store.read("projects")
        cls.data = {p["code"]: cls.store.data_for(p["code"]) for p in cls.projects}

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        import shutil
        shutil.rmtree(str(cls.folder), ignore_errors=True)

    def serve(self):
        s = Running(data_for=lambda code: copy.deepcopy(self.data.get(code)), projects=lambda: self.projects,
                    page_html=lambda: testpage.html())
        self.addCleanup(s.close)
        return s

    def load_page(self, cdp, port, width, hash_):
        sid = page_target(cdp)
        cdp.call("Page.enable", {}, sid)
        cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": FIXED_DATE + "window.__push = 0; const P = history.pushState; history.pushState = function () { window.__push++; return P.apply(this, arguments); };"}, sid)
        cdp.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False}, sid)
        cdp.call("Emulation.setFocusEmulationEnabled", {"enabled": True}, sid)
        cdp.call("Page.navigate", {"url": "about:blank"}, sid)
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{port}/{hash_}"}, sid)
        self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('#work tbody tr[data-id]').length", sid) > 0), f"{hash_} drew its list")
        return sid

    def shown(self, cdp, sid):
        return sorted(cdp.js("[...document.querySelectorAll('#work tbody tr[data-id]')].map(r => r.dataset.id)", sid))

    def switch(self, cdp, sid):
        return cdp.js("Object.fromEntries([...document.querySelectorAll('[data-show]')].map(b => [b.dataset.show, +b.querySelector('em').textContent]))", sid)

    def pressed(self, cdp, sid, sel):
        return cdp.js(f"document.querySelector({json.dumps(sel)}).getAttribute('aria-pressed')", sid)

    def tick(self, cdp, sid, field, nth):
        """Open a filter's box with the mouse, tick its nth choice, leave the box open."""
        if cdp.js(f"document.querySelector('[data-fb={field}]').getAttribute('aria-expanded')", sid) != "true":
            click(cdp, sid, f"[data-fb={field}]")
        self.assertTrue(wait(lambda: cdp.js(f"!!document.querySelector('#fbox-{field}')", sid)))
        label = cdp.js(f"document.querySelectorAll('#fbox-{field} label')[{nth}].textContent", sid)
        click(cdp, sid, f"#fbox-{field} label:nth-of-type({nth + 1}) input")
        return label

    def test_the_switch_counts_equal_the_list_after_each_filter_at_1400_and_900_px(self):
        s = self.serve()
        blocked = []
        handler = _Collect(blocked)
        sv.LOG.addHandler(handler)
        sv.LOG.setLevel(logging.INFO)
        self.addCleanup(sv.LOG.removeHandler, handler)
        with mock.patch.dict(sv.CSP_REPORTS, since=__import__("time").time(), n=0, dropped=0):
            for code, ids in self.ids.items():
                for width in (1400, 900):
                    with self.subTest(project=code, width=width), chrome() as cdp:
                        sid = self.load_page(cdp, s.port, width, f"#work&p={code}")
                        flat = [r for k in ("actions", "raid", "decisions") for r in self.data[code][k]]
                        all_rows = self.rows_of(cdp, sid)
                        # Open is the start; the switch counts are the project's numbers and the Open count is the list
                        self.assertEqual(self.pressed(cdp, sid, "[data-show=open]"), "true")
                        self.assertEqual(self.shown(cdp, sid), expect(all_rows))
                        self.assertEqual(self.switch(cdp, sid), {"open": len(expect(all_rows)), "closed": len(expect(all_rows, "closed")), "all": len(ids)})
                        self.assertEqual(self.switch(cdp, sid)["open"], len(self.shown(cdp, sid)))
                        self.assertEqual(cdp.js("document.querySelector('#work-count').textContent", sid), f"{len(expect(all_rows))} open items")
                        self.assertGreater(len(flat), 15)
                        # All: every demo row, once each
                        click(cdp, sid, "[data-show=all]")
                        self.assertEqual(self.shown(cdp, sid), ids)
                        self.assertEqual(cdp.js("document.querySelector('#work-count').textContent", sid), f"{len(ids)} items")
                        # a series of filters: after each, the count of the mode that is on is the number of visible rows, and the other counts follow
                        filters, nots = {}, ()
                        for field, nth in (("owner", 0), ("priority", 1), ("due", 0), ("client", 0)):
                            label = self.tick(cdp, sid, field, nth)
                            self.assertTrue(label)
                            value_ = self.chosen_value(cdp, sid, field)
                            filters.setdefault(field, []).append(value_)
                            want = expect(all_rows, "all", filters=filters)
                            self.assertTrue(wait(lambda: self.shown(cdp, sid) == want), f"{field} {value_}: {self.shown(cdp, sid)} != {want}")
                            sw = self.switch(cdp, sid)
                            self.assertEqual(sw["all"], len(self.shown(cdp, sid)))
                            self.assertEqual((sw["open"], sw["closed"]), (len(expect(all_rows, "open", filters=filters)), len(expect(all_rows, "closed", filters=filters))))
                            self.assertEqual(cdp.js("!!document.querySelector(\"[data-fb=%s]\").classList.contains('on')" % field, sid), True, "a dot on an active filter")
                            self.assertEqual(cdp.js("document.querySelectorAll('.fchip').length", sid), len(filters))
                        for mode in ("open", "closed"):
                            click(cdp, sid, f"[data-show={mode}]")
                            want = expect(all_rows, mode, filters=filters)
                            self.assertTrue(wait(lambda: self.shown(cdp, sid) == want))
                            self.assertEqual(self.switch(cdp, sid)[mode], len(want))
                        # Clear all removes the chips and the dots and restores the count
                        click(cdp, sid, "#clearAll")
                        self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('.fchip').length", sid) == 0))
                        self.assertEqual(self.shown(cdp, sid), expect(all_rows))
                        self.assertEqual(cdp.js("document.querySelectorAll('.fbtn.on').length", sid), 0)
                        self.assertEqual(cdp.js("!!document.querySelector('#clearAll')", sid), False)
                        self.assertEqual(self.pressed(cdp, sid, "[data-show=open]"), "true")
                        # layout
                        self.assertEqual(cdp.js("document.documentElement.scrollWidth <= window.innerWidth", sid), True, "no sideways scroll")
                        self.assertEqual(cdp.js("[...document.querySelectorAll('#work *')].filter(e => e.scrollWidth > e.clientWidth + 1 && /auto|scroll/.test(getComputedStyle(e).overflowX) && !e.closest('.fbox')).length", sid), 0)
                        self.assertEqual(cdp.js("window.__push", sid), 0, "no filter pushed a browser-history entry")
                        self.assertEqual(cdp.js("history.length", sid), 2, "about:blank and the page, nothing more")
            self.assertEqual(blocked, [], f"the policy blocked nothing: {blocked}")

    def rows_of(self, cdp, sid):
        """The page's own rows (rowsOf) are in no global, so read what the table shows: id, status and the oracle's fields from the data."""
        code = cdp.js("location.hash.match(/p=([A-Z0-9]+)/)[1]", sid)
        d = self.data[code]
        ucs = {u["id"]: u["ref"] for u in d["use_cases"]}
        ms = {m["id"]: m["name"] for m in d["milestones"]}
        out = []
        common = lambda r: {"id": r["id"], "status": r["status"], "client": bool(r["client_visible"]), "workstream": r.get("workstream") or "",
                            "uc": f"UC {ucs[r['use_case']]}" if r.get("use_case") in ucs else "", "milestone": ms.get(r.get("milestone")) or ""}
        for r in d["actions"]:
            out.append({**common(r), "kind": "action", "owner": r["owner"], "priority": r["priority"], "due_date": r["due_date"]})
        for r in d["raid"]:
            out.append({**common(r), "kind": r["type"].lower(), "owner": r["owner"], "priority": r["priority"], "due_date": r["due_date"]})
        for r in d["decisions"]:
            out.append({**common(r), "kind": "decision", "owner": r["made_by"], "priority": None, "needed_by": r.get("needed_by"), "date": r.get("date"), "workstream": "", "milestone": ""})
        return out

    def chosen_value(self, cdp, sid, field):
        return cdp.js(f"[...document.querySelectorAll('#fbox-{field} input')].filter(i => i.checked).map(i => i.value).pop()", sid)

    def test_the_chosen_filter_and_the_view_edit_toggle_look_different_from_the_others(self):
        # The highlight rules in shell.css must match the aria-pressed the buttons set (a rename of the attribute once lost them).
        s = self.serve()
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#work&p=TUL")
            bg = lambda sel: cdp.js(f"getComputedStyle(document.querySelector({json.dumps(sel)})).backgroundColor", sid)
            for on, off in (("[data-type][aria-pressed=true]", "[data-type][aria-pressed=false]"),
                            ("[data-show][aria-pressed=true]", "[data-show][aria-pressed=false]"),
                            (".mode[aria-pressed=true]", ".mode[aria-pressed=false]")):
                with self.subTest(on=on):
                    self.assertTrue(cdp.js(f"!!document.querySelector({json.dumps(on)}) && !!document.querySelector({json.dumps(off)})", sid), "one of each is drawn")
                    self.assertNotEqual(bg(on), bg(off), "the pressed button has its own background")
            self.tick(cdp, sid, "owner", 0)      # "is not" counts only once a value is chosen
            click(cdp, sid, "#fbox-owner .isnot [data-not='1']")
            self.assertTrue(wait(lambda: cdp.js("document.querySelector('#fbox-owner .isnot [data-not=\"1\"]').getAttribute('aria-pressed')", sid) == "true"))
            self.assertNotEqual(bg("#fbox-owner .isnot [data-not='1']"), bg("#fbox-owner .isnot [data-not='0']"))

    def test_a_second_filter_opens_with_one_click_and_a_second_click_on_it_closes_it(self):
        s = self.serve()
        for width in (1400, 900):
            with self.subTest(width=width), chrome() as cdp:
                sid = self.load_page(cdp, s.port, width, "#work&p=TUL")
                cdp.js("window.__a = document.querySelector('[data-fb=owner]'); window.__b = document.querySelector('[data-fb=priority]'); window.__bar = document.querySelector('.fbar')", sid)
                is_open = lambda f: cdp.js(f"!!document.querySelector('#fbox-{f}') && document.querySelector('[data-fb={f}]').getAttribute('aria-expanded') === 'true'", sid)
                click(cdp, sid, "[data-fb=owner]")
                self.assertTrue(wait(lambda: is_open("owner")), "the first click opens A")
                # a change inside A redraws the list; the buttons stay the same elements, so the next click lands
                click(cdp, sid, "#fbox-owner label:nth-of-type(1) input")
                self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('.fchip').length", sid) == 1))
                self.assertTrue(is_open("owner"))
                click(cdp, sid, "[data-fb=priority]")
                self.assertTrue(wait(lambda: is_open("priority")), "ONE click on B opens B")
                self.assertFalse(is_open("owner"), "and A closes")
                self.assertEqual(cdp.js("[window.__a === document.querySelector('[data-fb=owner]'), window.__b === document.querySelector('[data-fb=priority]'), window.__bar === document.querySelector('.fbar')]", sid),
                                 [True, True, True], "the filter buttons were not re-created")
                click(cdp, sid, "[data-fb=priority]")
                self.assertTrue(wait(lambda: not is_open("priority")), "a second click on B closes it")
                self.assertEqual(cdp.js("document.querySelectorAll('.fbox').length", sid), 0)
                # open A, tick in A, then B opens first time (the prototype's lost second click)
                click(cdp, sid, "[data-fb=status]")
                self.assertTrue(wait(lambda: is_open("status")))
                click(cdp, sid, "[data-fb=client]")
                self.assertTrue(wait(lambda: is_open("client")) and not is_open("status"))
                # a click on the page elsewhere closes it; Esc closes it with focus back on its button
                click(cdp, sid, "h1")
                self.assertTrue(wait(lambda: not is_open("client")))
                click(cdp, sid, "[data-fb=due]")
                self.assertTrue(wait(lambda: is_open("due")))
                key(cdp, sid, "Escape")
                self.assertTrue(wait(lambda: not is_open("due")))
                self.assertEqual(cdp.js("document.activeElement.dataset.fb", sid), "due")

    def test_a_filter_change_redraws_only_the_list(self):
        s = self.serve()
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#work&p=TUL")
            cdp.js("window.__keep = ['h1', '.crumbs', '.head', '.wbar', '.seg', '[data-type=action]', '[data-show=closed]', '.fbar', '#newBtn', '#work-list'].map(q => document.querySelector(q))", sid)
            cdp.js("window.__tbody = document.querySelector('#work tbody')", sid)
            click(cdp, sid, "[data-show=closed]")
            self.assertTrue(wait(lambda: self.pressed(cdp, sid, "[data-show=closed]") == "true"))
            click(cdp, sid, "[data-type=action]")
            self.assertTrue(wait(lambda: self.pressed(cdp, sid, "[data-type=action]") == "true"))
            self.assertEqual(cdp.js("window.__keep.map((e, i) => e === document.querySelector(['h1', '.crumbs', '.head', '.wbar', '.seg', '[data-type=action]', '[data-show=closed]', '.fbar', '#newBtn', '#work-list'][i]))", sid),
                             [True] * 10, "the heading, the switches, the filter row, Add and the list's own box are the same elements")
            self.assertEqual(cdp.js("window.__tbody === document.querySelector('#work tbody')", sid), True)
            self.assertEqual(sorted({k for k in cdp.js("[...document.querySelectorAll('#work tbody tr[data-id]')].map(r => r.dataset.kind)", sid)}), ["action"])

    def test_the_address_carries_the_filters_by_replace_and_a_reload_restores_them(self):
        s = self.serve()
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#work&p=TUL")
            click(cdp, sid, "[data-show=all]")
            click(cdp, sid, "[data-type=risk]")
            label = self.tick(cdp, sid, "priority", 0)
            self.assertTrue(wait(lambda: "priority:" in cdp.js("location.hash", sid)))
            h = cdp.js("location.hash", sid)
            self.assertRegex(h, r"^#work&p=TUL&f=mode:all;type:risk;priority:")
            self.assertEqual(cdp.js("history.length", sid), 2)
            self.assertEqual(cdp.js("window.__push", sid), 0)
            want = self.shown(cdp, sid)
            cdp.call("Page.reload", {}, sid)
            self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('#work tbody tr[data-id]').length", sid) > 0))
            self.assertEqual(cdp.js("location.hash", sid), h)
            self.assertEqual(self.shown(cdp, sid), want)
            self.assertEqual(self.pressed(cdp, sid, "[data-show=all]"), "true")
            self.assertEqual(self.pressed(cdp, sid, "[data-type=risk]"), "true")
            self.assertEqual(cdp.js("document.querySelectorAll('.fchip').length", sid), 1)
            # leaving Work items drops the filters from the address (they belong to that page; Back brings them back, see the Back test)
            click(cdp, sid, "[data-view=milestones]")
            self.assertEqual(cdp.js("location.hash", sid), "#milestones&p=TUL")
            click(cdp, sid, "[data-view=work]")
            self.assertEqual(cdp.js("location.hash", sid), "#work&p=TUL")
            self.assertEqual(self.pressed(cdp, sid, "[data-show=open]"), "true")
            click(cdp, sid, "[data-show=closed]")
            click(cdp, sid, "#clearAll")
            self.assertTrue(wait(lambda: cdp.js("location.hash", sid) == "#work&p=TUL"))
            self.assertEqual(cdp.js("window.__push", sid), 2, "only the two page changes pushed an entry; no filter did")

    def test_a_filter_click_changes_f_in_the_address_by_replace_and_adds_no_history_entry(self):
        s = self.serve()
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#work&p=TUL")
            cdp.js("window.__replace = 0; const R = history.replaceState; history.replaceState = function () { window.__replace++; return R.apply(this, arguments); };", sid)
            before = cdp.js("history.length", sid)
            self.assertNotIn("f=", cdp.js("location.hash", sid), "the start state adds nothing")
            click(cdp, sid, "[data-show=closed]")
            self.assertTrue(wait(lambda: cdp.js("location.hash", sid) == "#work&p=TUL&f=mode:closed"))
            self.tick(cdp, sid, "owner", 0)
            self.assertTrue(wait(lambda: ";owner:" in cdp.js("location.hash", sid)))
            h = cdp.js("location.hash", sid)
            self.assertRegex(h, r"^#work&p=TUL&f=mode:closed;owner:[^&=;]+$")
            self.assertEqual(cdp.js("history.length", sid), before, "a filter change adds no entry")
            self.assertEqual(cdp.js("window.__push", sid), 0)
            self.assertGreaterEqual(cdp.js("window.__replace", sid), 2, "each change rewrote the entry")
            self.assertEqual(cdp.js("clarkPage.filters()", sid), h.split("&f=")[1], "the page reads the same text")
            click(cdp, sid, "#clearAll")
            self.assertTrue(wait(lambda: cdp.js("location.hash", sid) == "#work&p=TUL"))
            self.assertEqual(cdp.js("history.length", sid), before)

    def test_loading_an_address_with_f_shows_the_filters_and_a_bad_f_shows_none_and_changes_nothing_else(self):
        s = self.serve()
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#work&p=TUL&f=mode:closed;type:action")
            self.assertEqual(self.pressed(cdp, sid, "[data-show=closed]"), "true")
            self.assertEqual(self.pressed(cdp, sid, "[data-type=action]"), "true")
            self.assertEqual(self.shown(cdp, sid), expect(self.rows_of(cdp, sid), "closed", "action"))
            self.assertEqual(cdp.js("location.hash", sid), "#work&p=TUL&f=mode:closed;type:action", "kept exactly as given")
            sid = self.load_page(cdp, s.port, 1400, "#work&p=TUL&f=owner:Sam%20Rivers;not:owner")
            self.assertEqual(cdp.js("[...document.querySelectorAll('.fchip')].map(c => c.textContent.replace('\\u00d7', ''))", sid), ["Owner is not: Sam Rivers"])
            self.assertEqual(cdp.js("document.querySelector('[data-fb=owner]').classList.contains('on')", sid), True)
            # a hostile value is shown as plain text: nothing runs, no markup is made, and the page still works
            hostile = '<img src=x onerror="window.__pwn=1">'
            sid = self.load_page(cdp, s.port, 1400, "#work&p=TUL&f=owner:" + urllib.parse.quote(hostile, safe="") + ";not:owner")
            self.assertEqual(cdp.js("[...document.querySelectorAll('.fchip')].map(c => c.textContent.replace('\\u00d7', ''))", sid), ["Owner is not: " + hostile])
            self.assertEqual(cdp.js("document.querySelectorAll('.fchip img, #work img[onerror]').length", sid), 0, "no element was made from the value")
            self.assertEqual(cdp.js("typeof window.__pwn", sid), "undefined", "nothing ran")
            self.assertEqual(cdp.js("clarkPage.project()", sid), "TUL")
            self.assertEqual(cdp.js("document.querySelector('[data-show=all]').click(), document.querySelectorAll('.fchip').length", sid), 1, "the page still answers")
        # an `f` the router will not trust is dropped: no filters, and the page and the project are as the rest of the address says
        for bad in ("f=mode:closed;owner:%zz", "f=owner:%", "f=mode=closed", "f=" + "a" * 601, "f=owner:%00", "f=owner:%ED%A0%80",
                    "f=mode:closed&p=XYZ", "f=mode:closed&item=A-12&view=milestones"):
            with self.subTest(bad), chrome() as cdp:
                sid = self.load_page(cdp, s.port, 1400, "#work&p=TUL&" + bad)
                self.assertEqual(cdp.js("document.querySelectorAll('.fchip').length", sid), 0)
                self.assertEqual(cdp.js("clarkPage.project()", sid), "TUL")
                self.assertEqual(cdp.js("location.hash.startsWith('#work&p=TUL')", sid), True)
                if "mode:closed&" in bad:       # a raw "&" ends the value; what is before it is still a good `f`, and "p=XYZ" is a second p, ignored
                    self.assertEqual(self.pressed(cdp, sid, "[data-show=closed]"), "true")
                else:
                    self.assertEqual(self.pressed(cdp, sid, "[data-show=open]"), "true")

    def test_back_and_forward_bring_the_filters_back_with_the_page_and_a_filter_change_is_never_a_stop(self):
        s = self.serve()
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#work&p=TUL")
            click(cdp, sid, "[data-show=all]")
            click(cdp, sid, "[data-type=risk]")
            self.assertTrue(wait(lambda: cdp.js("location.hash", sid) == "#work&p=TUL&f=mode:all;type:risk"))
            want = self.shown(cdp, sid)
            click(cdp, sid, "[data-view=milestones]")                       # a page change is one entry
            self.assertTrue(wait(lambda: cdp.js("location.hash", sid) == "#milestones&p=TUL"))
            self.assertEqual(cdp.js("history.length", sid), 3)
            cdp.js("history.back()", sid)                                   # Back goes to Work items WITH its filters, not to an earlier filter
            self.assertTrue(wait(lambda: cdp.js("location.hash", sid) == "#work&p=TUL&f=mode:all;type:risk"))
            self.assertTrue(wait(lambda: self.shown(cdp, sid) == want))
            self.assertEqual(self.pressed(cdp, sid, "[data-type=risk]"), "true")
            cdp.js("history.forward()", sid)
            self.assertTrue(wait(lambda: cdp.js("location.hash", sid) == "#milestones&p=TUL"))
            cdp.js("history.back()", sid)
            self.assertTrue(wait(lambda: self.shown(cdp, sid) == want))
            hist = cdp.call("Page.getNavigationHistory", {}, sid)           # the filters were never entries: blank, Work items (rewritten twice), Milestones
            self.assertEqual(len(hist["entries"]), 3)
            self.assertEqual(hist["entries"][0]["url"], "about:blank")
            self.assertTrue(hist["entries"][1]["url"].endswith("#work&p=TUL&f=mode:all;type:risk"))

    def test_a_peek_and_the_filters_share_the_address_and_neither_loses_the_other(self):
        s = self.serve()
        item = self.data["TUL"]["actions"][0]["id"]
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#work&p=TUL")
            click(cdp, sid, "[data-show=all]")
            cdp.js(f"clarkPage.openPeek({json.dumps(item)})", sid)
            self.assertTrue(wait(lambda: cdp.js("location.hash", sid) == f"#work&p=TUL&item={item}&f=mode:all"))
            click(cdp, sid, "[data-type=action]")                           # a filter change with a peek open keeps the peek
            self.assertTrue(wait(lambda: cdp.js("location.hash", sid) == f"#work&p=TUL&item={item}&f=mode:all;type:action"))
            self.assertEqual(cdp.js("clarkPage.peek().id", sid), item)
            h = cdp.js("location.hash", sid)
            cdp.call("Page.reload", {}, sid)                                # a reload brings back both
            self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('#work tbody tr[data-id]').length", sid) > 0))
            self.assertEqual(cdp.js("location.hash", sid), h)
            self.assertEqual(cdp.js("clarkPage.peek().id", sid), item)
            self.assertEqual(self.pressed(cdp, sid, "[data-type=action]"), "true")
            self.assertEqual(self.pressed(cdp, sid, "[data-show=all]"), "true")
            cdp.js("clarkPage.closePeek()", sid)                            # a filter was changed while it was open, so closing rewrites the entry (#42): the filter stays
            self.assertTrue(wait(lambda: cdp.js("clarkPage.peek()", sid) is None))
            self.assertTrue(wait(lambda: cdp.js("clarkPage.filters()", sid) == "mode:all;type:action"))

    def test_too_many_filters_for_the_address_is_refused_with_a_plain_line_and_changes_nothing(self):
        s = self.serve()
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#work&p=TUL")
            click(cdp, sid, "[data-show=all]")
            # fill `f` to 598 characters with one hand-made filter (the router's limit is 600), then try a real one
            text = "mode:all;owner:" + ",".join(f"P%20{n:03d}" for n in range(70))
            text = text[:585] if len(text) > 585 else text
            text = text[:text.rfind(",")] + "," + "Q" * (598 - len(text[:text.rfind(",")]) - 1)
            self.assertEqual(len(text), 598)
            cdp.js(f"clarkPage.setFilters({json.dumps(text)})", sid)
            self.assertTrue(wait(lambda: len(cdp.js("clarkPage.filters()", sid)) == 598))
            self.tick(cdp, sid, "workstream", 0)
            self.tick(cdp, sid, "status", 0)
            self.tick(cdp, sid, "priority", 0)
            self.assertTrue(wait(lambda: "not fit" in cdp.js("document.querySelector('#work-note').textContent", sid)))
            self.assertEqual(cdp.js("document.querySelector('#work-note').getAttribute('role')", sid), "status")
            self.assertEqual(len(cdp.js("clarkPage.filters()", sid)), 598, "nothing changed")
            self.assertEqual(cdp.js("document.querySelectorAll('#fbox-priority input:checked').length", sid), 0, "a tick that was not kept is not left ticked")
            self.assertEqual(cdp.js("history.length", sid), 2)
            click(cdp, sid, "#clearAll")                                    # Clear all always fits, and the line goes
            self.assertTrue(wait(lambda: cdp.js("location.hash", sid) == "#work&p=TUL"))
            self.assertEqual(cdp.js("document.querySelector('#work-note').textContent", sid), "")

    def test_the_filter_boxes_rows_are_big_enough_to_hit_and_aria_controls_exists_only_while_open(self):
        s = self.serve()
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#work&p=TUL")
            self.assertEqual(cdp.js("document.querySelectorAll('[data-fb][aria-controls]').length", sid), 0, "closed: no aria-controls to a box that is not there")
            click(cdp, sid, "[data-fb=owner]")
            self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('#fbox-owner')", sid)))
            self.assertEqual(cdp.js("document.querySelector('[data-fb=owner]').getAttribute('aria-controls')", sid), "fbox-owner")
            self.assertEqual(cdp.js("document.querySelectorAll('[data-fb][aria-controls]').length", sid), 1)
            self.assertGreaterEqual(cdp.js("Math.min(...[...document.querySelectorAll('#fbox-owner label')].map(l => l.getBoundingClientRect().height))", sid), 24,
                                    "the whole label row is the target, at least 24 px high")
            click(cdp, sid, "[data-fb=owner]")
            self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('[data-fb][aria-controls]').length", sid) == 0))

    def test_nothing_matching_says_so_and_clear_all_brings_the_rows_back(self):
        s = self.serve()
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#work&p=TUL")
            cdp.js("location.hash = '#work&p=TUL&f=mode:closed;type:decision;client:no;priority:Urgent'", sid)     # a hand-made address
            cdp.call("Page.reload", {}, sid)
            self.assertTrue(wait(lambda: "No items match these filters." in (cdp.js("document.querySelector('#work-list').innerText", sid) or "")))
            self.assertEqual(cdp.js("document.querySelectorAll('#work tbody tr[data-id]').length", sid), 0)
            click(cdp, sid, "#clearAll2")
            self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('#work tbody tr[data-id]').length", sid) > 0))

    def test_the_add_button_follows_the_type_switch_and_offers_menus(self):
        s = self.serve()
        for width in (1400, 900):
            with self.subTest(width=width), chrome() as cdp:
                sid = self.load_page(cdp, s.port, width, "#work&p=TUL")
                js = lambda e: cdp.js(e, sid)
                tile = lambda: js("(() => { const b = document.querySelector('#newBtn'); return [b.getAttribute('aria-label'), b.title, b.textContent, b.getAttribute('aria-haspopup')]; })()")
                self.assertEqual(tile(), ["Add item", "Add item", "Add item", "menu"])
                click(cdp, sid, "#newBtn")                                                    # All: a menu of every type
                self.assertTrue(wait(lambda: js("!!document.querySelector('#newBtnMenu')")))
                self.assertEqual(js("[...document.querySelectorAll('#newBtnMenu [role=menuitem]')].map(b => b.textContent)"), ["Add action", "Add risk", "Add issue", "Add decision"])
                click(cdp, sid, "#newBtnMenu [data-kind=issue]")                              # the stub says what it did, and adds nothing
                self.assertTrue(wait(lambda: "Add issue" in js("document.querySelector('#work-note').textContent")))
                self.assertEqual(js("document.querySelectorAll('#work tbody tr[data-id]').length"), len(expect(self.rows_of(cdp, sid))))
                for type_, words in (("action", "Add action"), ("decision", "Add decision"), ("risk", "Add risk or issue"), ("all", "Add item")):
                    click(cdp, sid, f"[data-type={type_}]")
                    self.assertTrue(wait(lambda: tile()[0] == words), f"the word follows the {type_} switch")
                    self.assertEqual(tile()[:3], [words, words, words], "label, tooltip and text are the full words")
                click(cdp, sid, "[data-type=risk]")                                           # Risks and issues: Add risk, Add issue
                click(cdp, sid, "#newBtn")
                self.assertTrue(wait(lambda: js("!!document.querySelector('#newBtnMenu')")))
                self.assertEqual(js("[...document.querySelectorAll('#newBtnMenu [role=menuitem]')].map(b => b.textContent)"), ["Add risk", "Add issue"])
                key(cdp, sid, "Escape")
                self.assertTrue(wait(lambda: js("!document.querySelector('#newBtnMenu')")))
                click(cdp, sid, "[data-type=action]")                                         # Actions: no menu, one click
                self.assertTrue(wait(lambda: tile()[3] is None))
                click(cdp, sid, "#newBtn")
                self.assertTrue(wait(lambda: "Add action" in js("document.querySelector('#work-note').textContent")))
                self.assertEqual(js("document.documentElement.scrollWidth <= window.innerWidth"), True)

    def test_the_add_button_grows_to_its_words_on_hover_and_on_keyboard_focus(self):
        s = self.serve()
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#work&p=TUL")
            click(cdp, sid, "[data-type=action]")
            self.assertTrue(wait(lambda: cdp.js("document.querySelector('#newBtn').getAttribute('aria-label')", sid) == "Add action"))
            width = lambda: cdp.js("document.querySelector('#newBtn').getBoundingClientRect().width", sid)
            cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 5, "y": 5}, sid)
            cdp.js("document.activeElement.blur()", sid)
            self.assertTrue(wait(lambda: width() < 40), "a plus on its own")
            small = width()
            hover(cdp, sid, "#newBtn")
            self.assertTrue(wait(lambda: width() > small + 40), "grown to its words on hover")
            cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 5, "y": 5}, sid)
            self.assertTrue(wait(lambda: width() < 40))
            cdp.js("document.querySelector('#newBtn').focus()", sid)
            key(cdp, sid, "Tab")                                                              # a key press makes the focus a keyboard one
            cdp.js("document.querySelector('#newBtn').focus()", sid)
            self.assertTrue(wait(lambda: width() > small + 40), "and on keyboard focus")
            self.assertEqual(cdp.js("getComputedStyle(document.querySelector('#newBtn .w')).opacity", sid), "1")

    def test_the_filter_boxes_work_with_the_keyboard(self):
        s = self.serve()
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#work&p=TUL")
            cdp.js("document.querySelector('[data-fb=owner]').focus()", sid)
            key(cdp, sid, "Enter")
            self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('#fbox-owner')", sid)))
            self.assertTrue(wait(lambda: cdp.js("document.activeElement.type", sid) == "checkbox"), "focus goes into the box")
            key(cdp, sid, " ")
            self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('.fchip').length", sid) == 1))
            self.assertEqual(cdp.js("document.querySelector('[data-fb=owner]').getAttribute('aria-label')", sid), "Owner: filtered")
            key(cdp, sid, "Escape")
            self.assertTrue(wait(lambda: cdp.js("!document.querySelector('#fbox-owner')", sid)))
            self.assertEqual(cdp.js("document.activeElement.dataset.fb", sid), "owner")
            cdp.js("document.querySelector('[data-fx=owner]').focus()", sid)
            key(cdp, sid, "Enter")
            self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('.fchip').length", sid) == 0))

    def test_dark_tokens_are_there_and_differ_from_light_and_the_profile_tokens_are_neutral(self):
        s = self.serve()
        with chrome() as cdp:
            sid = self.load_page(cdp, s.port, 1400, "#work&p=TUL")
            tok = lambda n: cdp.js(f"getComputedStyle(document.documentElement).getPropertyValue({json.dumps(n)}).trim()", sid)
            names = ["--surface", "--grey-50", "--grey-100", "--grey-200", "--grey-300", "--grey-500", "--grey-700", "--brand-ink", "--heading", "--brand-blue",
                     "--brand-blue-tint", "--status-green", "--status-amber", "--status-red", "--status-green-tint", "--status-amber-tint", "--status-red-tint",
                     "--status-green-text", "--status-amber-text", "--status-red-text", "--status-blue-text", "--data-1", "--data-6", "--flash", "--shadow"]
            light = {n: tok(n) for n in names}
            self.assertTrue(all(light.values()))
            frame = lambda: cdp.js("getComputedStyle(document.querySelector('#work')).backgroundColor + '|' + getComputedStyle(document.body).backgroundColor + '|' + getComputedStyle(document.querySelector('.t')).color", sid)
            frame_light = frame()
            cdp.js("document.documentElement.dataset.theme = 'dark'", sid)
            dark = {n: tok(n) for n in names}
            self.assertEqual([n for n in names if dark[n] == light[n]], [], "every colour token the page uses has a dark value")
            self.assertNotEqual(frame(), frame_light, "the page, the frame and the text are redrawn")
            self.assertEqual(cdp.js("getComputedStyle(document.documentElement).colorScheme", sid), "dark")
            # the computer's own setting: followed only when asked for (data-theme=auto); with none the page stays light
            cdp.js("document.documentElement.dataset.theme = 'auto'", sid)
            cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": "dark"}]}, sid)
            self.assertEqual({n: tok(n) for n in names}, dark, "auto on a dark computer is the dark values")
            cdp.js("delete document.documentElement.dataset.theme", sid)
            self.assertEqual({n: tok(n) for n in names}, light, "no data-theme: light until the user chooses")
            cdp.js("document.documentElement.dataset.theme = 'light'", sid)
            self.assertEqual({n: tok(n) for n in names}, light)
            cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": "light"}]}, sid)
            cdp.js("document.documentElement.dataset.theme = 'auto'", sid)
            self.assertEqual({n: tok(n) for n in names}, light, "auto on a light computer is light")
            for n in ("--profile-bg", "--profile-fg", "--profile-ring", "--profile-size"):
                self.assertTrue(tok(n), n)
            self.assertEqual(tok("--profile-size"), "32px")
            # the filter boxes and the Add menu take the dark values too (colours come from the tokens only)
            cdp.js("document.documentElement.dataset.theme = 'dark'", sid)
            click(cdp, sid, "[data-fb=owner]")
            self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('#fbox-owner')", sid)))
            self.assertEqual(cdp.js("getComputedStyle(document.querySelector('#fbox-owner')).backgroundColor", sid), "rgb(14, 45, 56)")


if __name__ == "__main__":
    unittest.main()
