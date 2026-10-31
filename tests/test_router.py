"""#63: standard browser navigation, Back and Forward (src/clark/page/src/router.js and its use in stores/report.js).

Run: python3 dev/run_tests.py test_router
Also #63's `f` key (the Work items filters' text, opaque to the router): see the tests named test_f_*.
Rules: the readiness check on the planning repo #63. Addresses are hashes ("#work&p=PDF&item=A-12"), never a path or a query; every change
of page, project or peek goes through router.navigate(); Back closes a peek first; Previous/Next and another row replace the entry;
a project switch pushes one; filters, scroll and the like add none; a reload keeps page, project and peek; anything unknown falls
back with no error. Data is fictional: project PDF (items A-12, A-13, milestone M-3) and project QRS.
Needs Google Chrome and is required: the tests fail, never skip, without it. The router's own functions run in a plain page (the
router bundled alone) from file:// and from a sandboxed frame; the built page runs against the harness's server (the page's data
needs the server's token), and once from file:// with no server, where its tabs and addresses work and its data can't load.
Not covered: the published file's own script (#39's publish.py is not on this branch), the trackpad swipe, Safari and Edge.
"""
import json
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

from _paths import ROOT, SRC, TOOLS
import _testpage as testpage

sys.path.insert(0, str(TOOLS))
import build_page  # noqa: E402
import esbuild  # noqa: E402

from clark import page  # noqa: E402
from test_server import Running, chrome, wait  # noqa: E402  (the #33 browser harness, shared)

PAGE_SRC = SRC / "clark" / "page" / "src"


def project(code, name, items, milestones):
    return {"project": {"code": code, "name": name, "health": "On track", "client_name": None},
            "milestones": [{"id": m, "name": "Pilot live"} for m in milestones], "workstreams": [], "use_cases": [], "links": [],
            "actions": [{"id": i, "description": "Agree the cut-over plan"} for i in items], "raid": [], "decisions": [], "labels": {}}


DATA = {"PDF": project("PDF", "Example Programme", ["A-12", "A-13"], ["M-3"]),
        "QRS": project("QRS", "Second Programme", ["A-1"], [])}

# Fed to parse and format: none may throw, and each result must be a stable, hash-only address.
HOSTILE = ["", "#", "#&&&&", "#work&p=PDF&item=A-12", "#work&p=PDF&p=QRS&item=A-12&item=A-13", "#<script>alert(1)</script>",
           "#work&p=PDF&item=<script>alert(1)</script>", "#work&item=" + "A" * 100000, "#" + "&p=PDF" * 5000, "#work&item=%E0%A4%A",
           "#work&item=%00%0a", "#%77ork&p=PDF", "#__proto__=1&constructor=x&toString", "#work&p=pdf", "#work&p=PDF%26item%3DA-1",
           "#work&item=A-12%26p%3DQRS", "#settings&p=PDF&item=A-12", "#work&item=A-1&ms=M-3", "#milestones&ms=../../x?y#z",
           "#work&item=A-12&", "#work&&item=A-12", "#work&item", "#work&item=", "\u0000‮#work", "#work&p=PDF\n&item=A-12",
           "javascript:alert(1)", "#%", "#%ff&p=%ff", None, 7, {}, [], ["#work"], True]
HOSTILE_STATES = [None, 3, "work", {"view": "<x>", "project": "a/b", "item": "../x?y", "ms": "?q=1"}, {"view": "work", "project": "PDF",
                  "item": {"toString": 1}}, {"view": "work", "item": "A" * 100000}, {"view": "work", "item": "A-12", "ms": "M-3"}]
SENTINELS = ("<?", "?", "/", " ", "<", ">", "\n")


def bundle_router(tmp):
    """router.js alone, as one script exposing R, in a plain page written to `tmp`; returns the page's path."""
    out = Path(tmp) / "router.js"
    done = esbuild.run(["--bundle", "--format=iife", "--global-name=R", "--target=es2020", "--tsconfig-raw={}",
                        str(PAGE_SRC / "router.js"), f"--outfile={out}"], cwd=build_page.SRC, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return out.read_text(encoding="utf-8")


WATCH = """window.errs = []; window.urls = [];
addEventListener('error', function (e) { window.errs.push(String(e.message)); });
addEventListener('unhandledrejection', function (e) { window.errs.push(String(e.reason)); });
['pushState', 'replaceState'].forEach(function (m) { var o = history[m];
  history[m] = function (s, t, u) { window.urls.push(m + ' ' + u); return o.apply(this, arguments); }; });"""


def opened(cdp, url, extra=""):
    """Attach to the page, watch errors and every history call from the first byte, and open `url` at 1400 px."""
    cdp.call("Target.getTargets")
    tid = next(t["targetId"] for t in cdp.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
    sid = cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
    cdp.call("Page.enable", {}, sid)
    cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": WATCH + extra}, sid)
    cdp.call("Emulation.setDeviceMetricsOverride", {"width": 1400, "height": 900, "deviceScaleFactor": 1, "mobile": False}, sid)
    cdp.call("Page.navigate", {"url": url}, sid)
    return sid


class Browser(unittest.TestCase):
    """Helpers for a test that drives one Chrome page."""

    def ev(self, expr):
        return self.cdp.js(expr, self.sid)

    def until(self, expr, want, what=""):
        ok = wait(lambda: self.ev(expr) == want, 10)
        self.assertTrue(ok, f"{what}: wanted {want!r}, got {self.ev(expr)!r}")

    def at(self):
        return self.ev("[location.hash, history.length]")

    def no_errors(self):
        self.assertEqual(self.ev("window.errs"), [])


class Pure(Browser):
    """parse and format, run in the browser (there is no Node here): round trips and hostile input."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.script = bundle_router(cls.tmp.name)
        cls.file = Path(cls.tmp.name) / "plain.html"
        cls.file.write_text(f"<!doctype html><meta charset=utf-8><body><script>{cls.script}</script></body>", encoding="utf-8")

    def run_in_page(self, expr):
        with chrome() as cdp:
            self.cdp = cdp
            self.sid = opened(cdp, self.file.as_uri())
            self.assertTrue(wait(lambda: cdp.js("typeof R", self.sid) == "object"))
            return cdp.js(expr, self.sid)

    def test_parse_reads_the_documented_addresses(self):
        got = self.run_in_page("""JSON.stringify([R.parse('#work&p=PDF&item=A-12'), R.parse('#milestones&p=PDF&ms=M-3'),
            R.parse('settings'), R.parse(''), R.parse('#nope&p=PDF'), R.parse('#work&p=PDF&p=QRS&item=A-12&item=A-13'),
            R.parse('#settings&p=PDF&item=A-12'), R.parse('#work&item=A-1&ms=M-3'), R.parse('#work&p=pdf')])""")
        e = lambda v, p="", i="", m="": {"view": v, "project": p, "item": i, "ms": m, "f": ""}  # noqa: E731
        self.assertEqual(json.loads(got), [e("work", "PDF", "A-12"), e("milestones", "PDF", "", "M-3"), e("settings"), e("dashboard"),
                                           e("dashboard", "PDF"), e("work", "PDF", "A-12"), e("settings", "PDF"), e("work", "", "A-1"),
                                           e("work")])

    def test_format_gives_one_hash_only_form(self):
        got = self.run_in_page("""JSON.stringify([R.format({view:'work',project:'PDF',item:'A-12'}),
            R.format({view:'milestones',project:'PDF',ms:'M-3'}), R.format({view:'settings'}), R.format({}),
            R.format({view:'settings',project:'PDF',item:'A-12'})])""")
        self.assertEqual(json.loads(got), ["#work&p=PDF&item=A-12", "#milestones&p=PDF&ms=M-3", "#settings", "#dashboard",
                                           "#settings&p=PDF"])

    def test_hostile_hashes_never_throw_and_round_trip_to_a_stable_hash_only_address(self):
        hostile = json.dumps(HOSTILE + ["#work&item=" + "%41" * 70, "#work&item=A-" + "9" * 70])
        states = json.dumps(HOSTILE_STATES)
        got = self.run_in_page(f"""(function () {{ var bad = [];
            JSON.parse({json.dumps(hostile)}).concat([undefined]).forEach(function (h, n) {{ try {{
              var s = R.parse(h), f = R.format(s), again = R.parse(f);
              if (JSON.stringify(s) !== JSON.stringify(again) || R.format(again) !== f) bad.push('round trip ' + n);
              if (!/^#[a-z]+(&p=[A-Z][A-Z0-9]{{2,6}})?(&(item|ms)=[A-Za-z0-9._-]{{1,64}})?$/.test(f)) bad.push('shape ' + n + ' ' + f.slice(0, 40));
              if (f.length > 120) bad.push('long ' + n);
            }} catch (e) {{ bad.push('threw ' + n + ' ' + e); }} }});
            JSON.parse({json.dumps(states)}).concat([undefined]).forEach(function (s, n) {{ try {{ var f = R.format(s);
              if (!/^#[a-z]+/.test(f) || f.length > 120) bad.push('state ' + n + ' ' + f.slice(0, 40)); }}
              catch (e) {{ bad.push('state threw ' + n + ' ' + e); }} }});
            return bad; }})()""")
        self.assertEqual(got, [])

    def test_a_script_text_or_a_path_in_a_hash_never_reaches_the_address(self):
        got = self.run_in_page("""JSON.stringify([R.format(R.parse('#work&p=PDF&item=<script>alert(1)</script>')),
            R.format(R.parse('#milestones&ms=../../x?y#z')), R.format(R.parse('#work&item=A-12%26p%3DQRS')),
            R.format(R.parse('#work&item=' + 'A'.repeat(100000)))])""")
        self.assertEqual(json.loads(got), ["#work&p=PDF", "#milestones", "#work", "#work"])

    # ---- `f`: one opaque key for the Work items filters (#64a). The router carries it as given and never reads it. ----

    def js_json(self, expr):
        return json.loads(self.run_in_page(f"JSON.stringify({expr})"))

    def test_f_is_empty_when_absent_and_carried_as_given_when_present(self):
        got = self.js_json("""[R.parse('#work&p=PDF'), R.parse('#work&p=PDF&f=overdue'), R.parse('#work&p=PDF&item=A-12&f=a%20b'),
            R.parse('#work&f=x&p=PDF'), R.parse('#work&p=PDF&f='), R.parse('#work&p=PDF&f'), R.parse('f=x'),
            R.format({view:'work', project:'PDF'}), R.format({view:'work', project:'PDF', f:'overdue'}),
            R.format({view:'work', project:'PDF', item:'A-12', f:'a%20b'}), R.format({view:'dashboard', f:'x'})]""")
        e = lambda v, p="", i="", f="": {"view": v, "project": p, "item": i, "ms": "", "f": f}  # noqa: E731
        self.assertEqual(got, [e("work", "PDF"), e("work", "PDF", f="overdue"), e("work", "PDF", "A-12", "a%20b"),
                               e("work", "PDF", f="x"), e("work", "PDF"), e("work", "PDF"), e("dashboard"),
                               "#work&p=PDF", "#work&p=PDF&f=overdue", "#work&p=PDF&item=A-12&f=a%20b", "#dashboard&f=x"])

    def test_f_of_600_characters_is_kept_and_601_is_dropped(self):
        got = self.js_json("""(function () { var out = {}; var of = function (unit, n) { return unit.repeat(Math.ceil(n / unit.length)).slice(0, n); };
            [['a', 600], ['a', 601], ['a', 1], ['%41', 600], ['%41', 603], ['%41', 597], ['a%26', 600], ['a%26', 601]].forEach(function (c) {
              var f = of(c[0], c[1]); if (f.length !== c[1]) throw new Error('setup');
              out[c[0] + ' x ' + c[1]] = [R.parse('#work&p=PDF&item=A-12&f=' + f).f === f, R.format({view:'work', project:'PDF', f: f}) === '#work&p=PDF&f=' + f,
                                          R.parse('#work&p=PDF&item=A-12&f=' + f).item]; });
            return out; })()""")
        for key, (parsed, formatted, item) in got.items():
            n = int(key.split(" x ")[1])
            self.assertEqual((parsed, formatted), (n <= 600, n <= 600), key)
            self.assertEqual(item, "A-12", key)
        self.assertEqual(len(got), 8)

    # Each of these is malformed: `f` is dropped (''), and the other keys are what the address says without it.
    MALFORMED = {"a control character": "a%00b", "a newline": "a%0Ab", "a tab": "a%09b", "unit separator": "%1F", "DEL": "%7f",
                 "a C1 control": "a%C2%85b", "a raw newline": "a\nb", "a raw tab": "a\tb", "a raw NUL": "a\u0000b",
                 "a lone surrogate as UTF-8": "%ED%A0%80", "a lone low surrogate as UTF-8": "a%ED%B0%80b",
                 "a raw lone surrogate": "a\ud800b", "a raw lone low surrogate": "\udc00", "%zz": "%zz", "a lone %": "%",
                 "a short escape": "a%4", "a truncated sequence": "%E0%A4%A", "an overlong sequence": "%C0%AF",
                 "an unencoded =": "a=b", "an unencoded = after a key": "status=open", "a space": "a b", "a raw non-ASCII letter": "café",
                 "an angle bracket": "<script>alert(1)</script>", "a backslash": "a\\b", "a quote": 'a"b'}

    def test_f_that_is_malformed_is_dropped_and_never_changes_the_other_keys(self):
        cases = json.dumps(self.MALFORMED)
        got = self.js_json(f"""(function () {{ var out = {{}}; var cases = {cases};
            Object.keys(cases).forEach(function (k) {{ var v = cases[k];
              out[k] = [R.parse('#work&p=PDF&item=A-12&f=' + v), R.parse('#work&f=' + v + '&p=PDF&item=A-12'),
                        R.format({{view:'work', project:'PDF', item:'A-12', f: v}})]; }});
            return out; }})()""")
        want = {"view": "work", "project": "PDF", "item": "A-12", "ms": "", "f": ""}
        for name, (tail, head, formatted) in got.items():
            self.assertEqual(tail, want, name)
            self.assertEqual(head, want, name)
            self.assertEqual(formatted, "#work&p=PDF&item=A-12", name)

    def test_an_unencoded_ampersand_or_equals_in_f_cannot_inject_or_change_another_key(self):
        # "=" inside f's value: malformed, f dropped. "&": it ends the value as it ends every value, so what follows is ordinary
        # keys, and the first of a repeated key wins: an earlier p, item or ms can never be overridden by anything after f.
        got = self.js_json("""[R.parse('#work&p=PDF&item=A-12&f=x&p=QRS&item=A-13&ms=M-3'), R.parse('#work&p=PDF&f=a=b&p=QRS'),
            R.parse('#work&p=PDF&item=A-12&f=a%26p%3DQRS%26item%3DA-13'), R.parse('#work&p=PDF&item=A-12&f=a%3Db'),
            R.parse('#milestones&p=PDF&ms=M-3&f=a&ms=M-4&view=work'), R.parse('#work&p=PDF&f=a&f=b'),
            R.format({view:'work', project:'PDF', item:'A-12', f:'a&p=QRS'}), R.format({view:'work', project:'PDF', item:'A-12', f:'a&item=A-13'}),
            R.format({view:'work', project:'PDF', ms:'M-3', f:'a=b'}), R.format({view:'work', project:'PDF', f:'a#b'})]""")
        e = lambda v, p, i, m, f: {"view": v, "project": p, "item": i, "ms": m, "f": f}  # noqa: E731
        self.assertEqual(got, [e("work", "PDF", "A-12", "", "x"), e("work", "PDF", "", "", ""),
                               e("work", "PDF", "A-12", "", "a%26p%3DQRS%26item%3DA-13"), e("work", "PDF", "A-12", "", "a%3Db"),
                               e("milestones", "PDF", "", "M-3", "a"), e("work", "PDF", "", "", "a"),
                               "#work&p=PDF&item=A-12", "#work&p=PDF&item=A-12", "#work&p=PDF&ms=M-3", "#work&p=PDF"])

    HOSTILE_F = ["", "%", "%%", "%25", "%2", "%G0", "%zz", "%00", "%ED%A0%80", "%F0%90%80", "%F4%90%80%80", "%FF", "\ud800", "\udc00\ud800",
                 "a" * 600, "a" * 601, "%41" * 300, "%41" * 201, "&", "&&&&", "=", "==", "&p=QRS", "&item=A-13&ms=M-3",
                 "a&f=b", "__proto__", "constructor", "toString", "../../x?y#z", "<script>alert(1)</script>", "javascript:alert(1)",
                 "‮", " ", "\u0000", "\n", " ", "﻿", "%E2%80%AE", "%C2%80", "%2f%2e%2e", "😀", "%F0%9F%98%80", "a%26b%3Dc", "x" * 100000]

    def test_about_forty_hostile_f_values_never_throw_and_never_move_another_key(self):
        values = json.dumps(self.HOSTILE_F)
        got = self.js_json(f"""(function () {{ var bad = [], kept = 0, base = {{view:'work', project:'PDF', item:'A-12', ms:'', f:''}};
            var others = function (s) {{ return JSON.stringify([s.view, s.project, s.item, s.ms]); }};
            var ok = /^(?:[A-Za-z0-9\\-._~!$'()*+,;:@\\/?]|%[0-9A-Fa-f]{{2}})*$/;
            JSON.parse({json.dumps(values)}).concat([undefined, null, 7, true, {{}}, [], ['a'], {{toString: 1}}]).forEach(function (v, n) {{ try {{
              var hashes = typeof v === 'string' ? ['#work&p=PDF&item=A-12&f=' + v, '#work&f=' + v + '&p=PDF&item=A-12', '#work&p=PDF&item=A-12&f=' + v + '&f=ok'] : [];
              hashes.forEach(function (h) {{ var s = R.parse(h), g = R.format(s);
                // the other keys are those of the address with f taken out, or (a raw "&") the keys that follow it, never more
                if (typeof s.f !== 'string' || s.f.length > 600 || (s.f && !ok.test(s.f))) bad.push('f ' + n);
                if (R.format(R.parse(g)) !== g || JSON.stringify(R.parse(g)) !== JSON.stringify(s)) bad.push('round trip ' + n);
                if (!(typeof v === 'string' && v.indexOf('&') >= 0) && others(s) !== others(base)) bad.push('moved ' + n + ' ' + h.slice(0, 60));
                if (s.f) kept++; }});
              var t = R.format({{view:'work', project:'PDF', item:'A-12', f: v}});
              if (t.indexOf('&f=') >= 0 && t.slice(t.indexOf('&f=') + 3) !== v) bad.push('changed ' + n);
              if (!(typeof v === 'string' && v.indexOf('&') >= 0) && others(R.parse(t)) !== others(base)) bad.push('format moved ' + n);
              if (t.length > 700) bad.push('long ' + n);
            }} catch (e) {{ bad.push('threw ' + n + ' ' + e); }} }});
            return {{bad: bad, kept: kept}}; }})()""")
        self.assertEqual(got["bad"], [])
        self.assertGreater(got["kept"], 0, "some of them are fine and are kept")
        self.assertGreaterEqual(len(self.HOSTILE_F), 30)

    def test_f_round_trips_with_its_percent_escapes_untouched(self):
        fs = ["", "overdue", "a%26b%3Dc", "%25", "%2526", "x%20y", "status%3Dopen%26owner%3DAB", "%E2%9C%93", "%F0%9F%98%80", "a%2Bb", "%23",
              "a-b_c.d~e!f$g'h(i)j*k+l,m;n:o@p/q?r", "a" * 600]
        states = []
        for view in ("dashboard", "work", "milestones", "settings"):
            for proj in ("", "PDF"):
                for item, ms in (("", ""), ("A-12", ""), ("", "M-3")):
                    for f in fs:
                        states.append({"view": view, "project": proj, "item": item if view != "settings" else "",
                                       "ms": ms if view != "settings" else "", "f": f})
        got = self.js_json(f"""(function () {{ var bad = [];
            JSON.parse({json.dumps(json.dumps(states))}).forEach(function (s, n) {{
              var h = R.format(s), back = R.parse(h);
              if (JSON.stringify(back) !== JSON.stringify(s)) bad.push([h.slice(0, 80), back]);
              if (s.f && h.slice(h.indexOf('&f=') + 3) !== s.f) bad.push(['changed', h.slice(0, 80)]);
              if (R.format(back) !== h) bad.push(['unstable', h.slice(0, 80)]); }});
            return bad; }})()""")
        self.assertEqual(got, [])
        self.assertEqual(self.js_json("R.format({view:'work', project:'PDF', f:'a%26b%3Dc'})"), "#work&p=PDF&f=a%26b%3Dc",
                         "%26 and %3D stay as they are: not decoded, not encoded again")


class Navigate(Browser):
    """navigate(), onPop() and back() in a plain page: hash-only, push or replace, no repeat, and the fallbacks."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.file = Path(cls.tmp.name) / "plain.html"
        script = bundle_router(cls.tmp.name)
        cls.file.write_text(f"<!doctype html><meta charset=utf-8><body><script>{script}\n"
                            "window.popped = []; R.onPop(function (s) { window.popped.push(R.format(s)); });</script></body>",
                            encoding="utf-8")

    def visit(self, cdp, hash_="", extra=""):
        self.cdp = cdp
        self.sid = opened(cdp, self.file.as_uri() + hash_, extra)
        self.assertTrue(wait(lambda: cdp.js("typeof R", self.sid) == "object"))

    def test_push_replace_and_the_same_address_never_pushes_twice(self):
        with chrome() as cdp:
            self.visit(cdp)
            start = self.at()[1]
            self.assertIs(self.ev("R.navigate({view:'work', project:'PDF'})"), True)
            self.assertIs(self.ev("R.navigate({view:'work', project:'PDF'})"), False, "the same state again")
            self.assertIs(self.ev("R.navigate({view:'work', project:'PDF', junk: 1})"), False)
            self.assertEqual(self.at(), ["#work&p=PDF", start + 1])
            self.assertIs(self.ev("R.navigate({view:'work', project:'PDF', item:'A-12'})"), True)
            self.assertIs(self.ev("R.navigate({view:'work', project:'PDF', item:'A-13'}, {replace: true})"), True)
            self.assertEqual(self.at(), ["#work&p=PDF&item=A-13", start + 2], "replace keeps the count")
            self.assertEqual(self.ev("window.urls"), ["pushState #work&p=PDF", "pushState #work&p=PDF&item=A-12",
                                                      "replaceState #work&p=PDF&item=A-13"])
            self.assertEqual(self.ev("history.scrollRestoration"), "manual")
            self.no_errors()

    def test_back_and_forward_step_through_and_onpop_draws_each_move_once(self):
        with chrome() as cdp:
            self.visit(cdp)
            for state in ("{view:'work', project:'PDF'}", "{view:'milestones', project:'PDF'}", "{view:'settings', project:'PDF'}"):
                self.ev(f"R.navigate({state})")
            self.assertEqual(self.ev("window.popped"), [], "a move the page made itself is not a pop")
            for want in ("#milestones&p=PDF", "#work&p=PDF"):
                self.ev("history.back()")
                self.until("location.hash", want, "back")
            self.ev("history.forward()")
            self.until("location.hash", "#milestones&p=PDF", "forward")
            self.assertEqual(self.ev("window.popped"), ["#milestones&p=PDF", "#work&p=PDF", "#milestones&p=PDF"],
                             "popstate and hashchange together are one draw")

    def test_a_peek_pushed_by_a_click_is_marked_so_it_closes_with_back(self):
        with chrome() as cdp:
            self.visit(cdp)
            self.ev("R.navigate({view:'work', project:'PDF'})")
            self.assertIs(self.ev("R.peekWasPushed()"), False)
            self.ev("R.navigate({view:'work', project:'PDF', item:'A-12'})")
            self.assertIs(self.ev("R.peekWasPushed()"), True)
            self.ev("R.navigate({view:'work', project:'PDF', item:'A-13'}, {replace: true})")
            self.assertIs(self.ev("R.peekWasPushed()"), True, "Next keeps the mark")
            self.ev("R.back()")
            self.until("location.hash", "#work&p=PDF", "back closed the peek")
            self.assertIs(self.ev("R.peekWasPushed()"), False)

    def test_the_address_is_hash_only_and_the_path_and_query_never_change(self):
        with chrome() as cdp:
            self.visit(cdp, "")
            before = self.ev("location.href.split('#')[0]")
            for state in ("{view:'work', project:'PDF', item:'A-12'}", "{view:'x/../y?z=1', project:'PDF/../x', item:'/a?b'}",
                          "{view:'milestones', ms:'M-3'}", "{view:'settings'}"):
                self.ev(f"R.navigate({state})")
            self.ev("R.navigate({view:'work', project:'QRS'}, {replace: true})")
            self.assertEqual(self.ev("location.href.split('#')[0]"), before)
            urls = self.ev("window.urls")
            self.assertTrue(urls and all(re.fullmatch(r"(push|replace)State #[a-z]+(&p=[A-Z0-9]+)?(&(item|ms)=[A-Za-z0-9._-]+)?", u) for u in urls), urls)
            self.assertEqual(self.ev("location.search"), "")
            self.no_errors()

    def test_when_pushstate_throws_the_hash_is_set_and_when_replacestate_throws_the_entry_is_replaced(self):
        throw = ("history.pushState = function () { throw new DOMException('no', 'SecurityError'); };"
                 "history.replaceState = function () { throw new DOMException('no', 'SecurityError'); };")
        with chrome() as cdp:
            self.visit(cdp, "", throw)
            start = self.at()[1]
            self.ev("R.navigate({view:'work', project:'PDF'})")
            self.ev("R.navigate({view:'work', project:'PDF', item:'A-12'})")
            self.assertEqual(self.at(), ["#work&p=PDF&item=A-12", start + 2], "location.hash added the entries")
            self.ev("R.navigate({view:'work', project:'PDF', item:'A-13'}, {replace: true})")
            self.assertEqual(self.at(), ["#work&p=PDF&item=A-13", start + 2], "location.replace kept the count")
            self.ev("history.back()")
            self.until("location.hash", "#work&p=PDF", "back works over the fallback")
            self.assertEqual(self.ev("window.popped"), ["#work&p=PDF"], "and draws once")
            self.assertIs(self.ev("R.peekWasPushed()"), False, "no mark can be set there, so closing replaces")
            self.no_errors()

    def test_when_every_call_throws_the_page_still_works(self):
        throw = ("history.pushState = history.replaceState = function () { throw new Error('no'); };"
                 "Object.defineProperty(Location.prototype, 'hash', {get: function () { return ''; }, set: function () { throw new Error('no'); }});"
                 "Location.prototype.replace = function () { throw new Error('no'); };")
        with chrome() as cdp:
            self.visit(cdp, "", throw)
            self.assertIn(self.ev("R.navigate({view:'work', project:'PDF'})"), (True, False))
            self.assertEqual(self.ev("R.back() === true || R.back() === false"), True)
            self.no_errors()

    def test_file_url_and_a_sandboxed_frame_work_with_hash_only_addresses(self):
        framed = Path(self.tmp.name) / "framed.html"
        framed.write_text(f"<!doctype html><meta charset=utf-8><body><script>{bundle_router(self.tmp.name)}\n"
                          "var out = {errs: []}; addEventListener('error', function (e) { out.errs.push(String(e.message)); });\n"
                          "R.onPop(function (s) { (out.popped = out.popped || []).push(R.format(s)); });\n"
                          "R.navigate({view:'work', project:'PDF'}); R.navigate({view:'work', project:'PDF', item:'A-12'});\n"
                          "out.after = [location.hash, history.length]; history.back();\n"
                          "setTimeout(function () { out.back = location.hash; out.origin = String(origin);\n"
                          "  parent.postMessage(JSON.stringify(out), '*'); }, 400);</script></body>", encoding="utf-8")
        wrapper = Path(self.tmp.name) / "wrapper.html"
        wrapper.write_text("<!doctype html><meta charset=utf-8><body><script>window.heard = [];"
                           "addEventListener('message', function (e) { window.heard.push(e.data); });</script>"
                           f'<iframe sandbox="allow-scripts" src="{framed.as_uri()}"></iframe></body>', encoding="utf-8")
        with chrome() as cdp:
            self.cdp = cdp
            self.sid = opened(cdp, wrapper.as_uri())
            self.assertTrue(wait(lambda: cdp.js("window.heard && window.heard.length", self.sid) == 1), "the frame reported")
            heard = json.loads(self.ev("window.heard[0]"))
        self.assertEqual(heard["errs"], [])
        self.assertEqual(heard["origin"], "null", "an opaque origin: the frame is sandboxed")
        self.assertEqual(heard["after"][0], "#work&p=PDF&item=A-12")
        self.assertEqual(heard["back"], "#work&p=PDF")
        self.assertEqual(heard["popped"], ["#work&p=PDF"])
        with chrome() as cdp:                                          # and the same page straight from file://
            self.visit(cdp, "#work&p=PDF&item=A-12")
            self.assertEqual(self.ev("location.protocol"), "file:")
            self.ev("R.navigate({view:'milestones', project:'PDF'})")
            self.ev("history.back()")
            self.until("location.hash", "#work&p=PDF&item=A-12", "back from file://")
            self.assertEqual(self.ev("R.current()"), {"view": "work", "project": "PDF", "item": "A-12", "ms": "", "f": ""})
            self.no_errors()

    # ---- `f`: a filter change rewrites the entry (#64a) ----

    def test_f_current_gives_the_starting_value_on_load_from_file_url(self):
        with chrome() as cdp:
            self.visit(cdp, "#work&p=PDF&item=A-12&f=a%26b%3Dc")
            self.assertEqual(self.ev("location.protocol"), "file:")
            self.assertEqual(self.ev("R.current()"), {"view": "work", "project": "PDF", "item": "A-12", "ms": "", "f": "a%26b%3Dc"})
            self.no_errors()
        with chrome() as cdp:
            self.visit(cdp, "#work&p=PDF&f=%zz")
            self.assertEqual(self.ev("R.current().f"), "", "a malformed f on load is dropped")
            self.assertEqual(self.ev("R.current().project"), "PDF")
            self.no_errors()

    def test_f_changes_replace_the_entry_and_never_push(self):
        with chrome() as cdp:
            self.visit(cdp)
            self.ev("R.navigate({view:'work', project:'PDF'})")
            n = self.at()[1]
            self.assertIs(self.ev("R.navigate({view:'work', project:'PDF', f:'a'}, {replace: true})"), True)
            self.assertEqual(self.at(), ["#work&p=PDF&f=a", n], "history.length did not change and the entry was replaced")
            self.assertIs(self.ev("R.navigate({view:'work', project:'PDF', f:'a%26b%3Dc'}, {replace: true})"), True)
            self.assertEqual(self.at(), ["#work&p=PDF&f=a%26b%3Dc", n])
            self.assertIs(self.ev("R.navigate({view:'work', project:'PDF', f:'a%26b%3Dc'}, {replace: true})"), False, "the same f: nothing")
            self.assertEqual(self.ev("window.urls"), ["pushState #work&p=PDF", "replaceState #work&p=PDF&f=a",
                                                      "replaceState #work&p=PDF&f=a%26b%3Dc"])
            self.ev("history.back()")                       # Back leaves for the entry before the filter, not for an earlier filter
            self.until("location.hash", "", "Back did not stop on a filter")
            self.no_errors()

    def test_an_f_only_change_is_replaced_even_when_the_caller_forgets_replace(self):
        with chrome() as cdp:
            self.visit(cdp)
            self.ev("R.navigate({view:'work', project:'PDF', item:'A-12'})")
            n = self.at()[1]
            self.assertIs(self.ev("R.peekWasPushed()"), True)
            self.assertIs(self.ev("R.navigate({view:'work', project:'PDF', item:'A-12', f:'x'})"), True, "no {replace: true}")
            self.assertEqual(self.at(), ["#work&p=PDF&item=A-12&f=x", n])
            self.assertIs(self.ev("R.navigate({view:'work', project:'PDF', item:'A-12', f:'y'})"), True)
            self.assertIs(self.ev("R.navigate({view:'work', project:'PDF', item:'A-12', f:''})"), True, "clearing it is also only f")
            self.assertIs(self.ev("R.navigate({view:'work', project:'PDF', item:'A-12', f:'%zz'})"), False, "a dropped f is no change")
            self.assertEqual(self.at(), ["#work&p=PDF&item=A-12", n])
            self.assertEqual(self.ev("window.urls"), ["pushState #work&p=PDF&item=A-12", "replaceState #work&p=PDF&item=A-12&f=x",
                                                      "replaceState #work&p=PDF&item=A-12&f=y", "replaceState #work&p=PDF&item=A-12"])
            self.assertIs(self.ev("R.peekWasPushed()"), True, "the peek's mark survived, so closing it still steps Back")
            self.no_errors()

    def test_a_page_or_project_change_that_also_changes_f_pushes_one_entry(self):
        with chrome() as cdp:
            self.visit(cdp)
            self.ev("R.navigate({view:'work', project:'PDF'})")
            self.ev("R.navigate({view:'work', project:'PDF', f:'a'}, {replace: true})")
            n = self.at()[1]
            self.assertIs(self.ev("R.navigate({view:'milestones', project:'PDF', f:'b'})"), True)
            self.assertEqual(self.at(), ["#milestones&p=PDF&f=b", n + 1])
            self.assertIs(self.ev("R.navigate({view:'milestones', project:'QRS', f:'c'})"), True)
            self.assertEqual(self.at(), ["#milestones&p=QRS&f=c", n + 2])
            self.assertIs(self.ev("R.navigate({view:'work', project:'QRS', item:'A-1', f:''})"), True, "a page and a peek and f")
            self.assertEqual(self.at(), ["#work&p=QRS&item=A-1", n + 3])
            self.assertEqual(self.ev("window.urls[window.urls.length - 3]"), "pushState #milestones&p=PDF&f=b")
            self.no_errors()

    def test_back_and_forward_restore_f_and_onpop_delivers_it_once(self):
        with chrome() as cdp:
            self.visit(cdp)
            self.ev("R.navigate({view:'work', project:'PDF'})")
            self.ev("R.navigate({view:'work', project:'PDF', f:'a%26b'}, {replace: true})")
            self.ev("R.navigate({view:'work', project:'PDF', f:'a%26b%3Dc'}, {replace: true})")
            self.ev("R.navigate({view:'milestones', project:'PDF'})")
            self.ev("R.navigate({view:'work', project:'PDF', f:'z'})")
            self.assertEqual(self.ev("window.popped"), [])
            self.ev("history.back()")
            self.until("location.hash", "#milestones&p=PDF", "back")
            self.ev("history.back()")
            self.until("location.hash", "#work&p=PDF&f=a%26b%3Dc", "back to the page with its last f")
            self.assertEqual(self.ev("R.current().f"), "a%26b%3Dc")
            self.ev("history.forward()")
            self.ev("history.forward()")
            self.until("location.hash", "#work&p=PDF&f=z", "forward")
            self.assertEqual(self.ev("window.popped"), ["#milestones&p=PDF", "#work&p=PDF&f=a%26b%3Dc", "#milestones&p=PDF", "#work&p=PDF&f=z"])
            self.no_errors()

    def test_a_typed_hash_with_f_reaches_listeners_and_a_malformed_one_arrives_without_it(self):
        with chrome() as cdp:
            self.visit(cdp)
            self.ev("R.navigate({view:'work', project:'PDF'})")
            self.ev("location.hash = '#work&p=PDF&f=q%26r'")
            self.until("window.popped.length", 1, "hashchange")
            self.ev("location.hash = '#work&p=PDF&item=A-12&f=%25zz%zz'")
            self.until("window.popped.length", 2, "hashchange")
            self.ev("location.hash = '#work&p=PDF&f=a=b'")
            self.until("window.popped.length", 3, "hashchange")
            self.assertEqual(self.ev("window.popped"), ["#work&p=PDF&f=q%26r", "#work&p=PDF&item=A-12", "#work&p=PDF"])
            self.no_errors()


class Source(unittest.TestCase):
    def test_only_the_router_touches_history_or_the_address(self):
        touching = re.compile(r"pushState|replaceState|history\.(back|forward|go)\b|location\s*\.\s*(hash|href|assign|replace)\b|"
                              r"location\s*=|window\.open|hashchange|popstate")
        found = [str(p.relative_to(ROOT)) for p in sorted(PAGE_SRC.rglob("*")) if p.suffix in (".js", ".jsx") and p.name != "router.js"
                 and touching.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(found, [], "every change of page, project or peek goes through router.navigate()")
    def test_the_report_store_exposes_f_read_only_and_changes_it_only_through_setfilters(self):
        store = (PAGE_SRC / "stores" / "report.js").read_text(encoding="utf-8")
        self.assertRegex(store, r"export const f = computed\(")
        self.assertRegex(store, r"export function setFilters\(text\)")
        self.assertRegex(store, r"go\(\{ \.\.\.where\(\), f: text \}, \{ replace: true \}\)")
        self.assertNotRegex(store, r"export const filterText|export \{[^}]*filterText")

    def test_the_built_page_carries_the_router_and_no_other_address_code(self):
        html = page.PAGE.read_text(encoding="utf-8")
        self.assertIn("clarkPeek", html)
        self.assertIn("scrollRestoration", html)


class BuiltPage(Browser):
    """The real bundle in a real browser against the harness's server."""

    def serve(self):
        s = Running(data_for=DATA.get, page_html=lambda: testpage.html())
        self.addCleanup(s.close)
        return s

    def draw(self, cdp, hash_, expect=None, extra=""):
        """Open the page at `hash_` and wait until it has drawn: `expect` as the heading, else the project's name arrived."""
        s = self.serve()
        self.base = f"http://127.0.0.1:{s.port}/"
        self.cdp = cdp
        self.sid = opened(cdp, self.base + hash_, extra)
        self.assertTrue(wait(lambda: cdp.js("document.documentElement.dataset.ready", self.sid) == "1"), "the bundle ran")
        if expect:
            self.until("document.querySelector('h1') && document.querySelector('h1').textContent", expect, "the page drew")
        else:
            code = re.search(r"p=([A-Z]+)", hash_).group(1)
            self.until("document.getElementById('project-name').textContent", DATA[code]["project"]["name"], "the data arrived")

    def leave(self):
        try:
            self.ev("history.back()")
        except RuntimeError:                                           # the page went away under the call: that is the point
            pass
        self.leaves()

    def leaves(self):
        """The tab went back to about:blank: the page it was on is gone (a call into it now fails, so ask the browser)."""
        def url():
            return next(t["url"] for t in self.cdp.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
        self.assertTrue(wait(lambda: url() == "about:blank", 10), f"Back from the first entry leaves clark: {url()}")

    def click_tab(self, view):
        self.ev(f"document.querySelector('[data-view={view}]').click()")

    def tab(self):
        return self.ev("document.querySelector('.tab[aria-selected=true]').dataset.view")

    def peek(self):
        return self.ev("clarkPage.peek()")

    def test_each_tab_pushes_one_entry_and_back_and_forward_step_through_them(self):
        with chrome() as cdp:
            self.draw(cdp, "#dashboard&p=PDF")
            start = self.at()[1]
            for view in ("work", "milestones", "settings"):
                self.click_tab(view)
            self.assertEqual(self.at(), ["#settings&p=PDF", start + 3])
            self.assertEqual(self.tab(), "settings")
            for view in ("milestones", "work", "dashboard"):
                self.ev("history.back()")
                self.until("document.querySelector('.tab[aria-selected=true]').dataset.view", view, "back")
            self.assertEqual(self.at(), ["#dashboard&p=PDF", start + 3])
            for view in ("work", "milestones", "settings"):
                self.ev("history.forward()")
                self.until("document.querySelector('.tab[aria-selected=true]').dataset.view", view, "forward")
            self.assertEqual(self.ev("document.querySelector('h1').textContent"), "Settings")
            self.click_tab("settings")
            self.assertEqual(self.at()[1], start + 3, "the same tab again adds nothing")
            self.no_errors()

    def test_back_with_a_peek_open_closes_it_first_and_forward_reopens_it(self):
        with chrome() as cdp:
            self.draw(cdp, "#dashboard&p=PDF")
            self.click_tab("work")
            before = self.at()
            self.ev("clarkPage.openPeek('A-12')")
            self.assertEqual(self.at(), ["#work&p=PDF&item=A-12", before[1] + 1])
            self.assertEqual(self.peek(), {"kind": "item", "id": "A-12"})
            self.ev("history.back()")
            self.until("location.hash", "#work&p=PDF", "back")
            self.assertIsNone(self.peek(), "Back closed the peek")
            self.assertEqual(self.tab(), "work", "and stayed on the page")
            self.ev("history.forward()")
            self.until("clarkPage.peek() && clarkPage.peek().id", "A-12", "forward reopened it")
            self.assertEqual(self.tab(), "work")

    def test_back_closes_the_peek_in_one_step_whatever_cards_were_opened_and_a_card_replaces_the_entry(self):
        # #42 contract (kept by the closePeek rule): Back closes the peek, another card replaces the entry and adds none.
        with chrome() as cdp:
            self.draw(cdp, "#work&p=PDF")
            before = self.at()
            self.ev("clarkPage.openPeek('A-12')")
            self.ev("clarkPage.openPeek('A-13')")
            self.assertEqual(self.at(), ["#work&p=PDF&item=A-13", before[1] + 1], "another card replaced the entry")
            self.ev("history.back()")
            self.until("location.hash", "#work&p=PDF", "one Back closed the peek")
            self.assertIsNone(self.peek())
            self.no_errors()

    def test_closing_a_peek_that_a_click_opened_steps_back_and_leaves_no_entry(self):
        with chrome() as cdp:
            self.draw(cdp, "#work&p=PDF")
            before = self.at()
            self.ev("clarkPage.openPeek('A-12')")
            self.ev("clarkPage.closePeek()")
            self.until("location.hash", "#work&p=PDF", "close")
            self.assertEqual(self.at()[1], before[1] + 1, "the entry is still there to go Forward to, and none was added")
            self.ev("history.forward()")
            self.until("location.hash", "#work&p=PDF&item=A-12", "forward")
            self.ev("history.back()")
            self.leave()                                               # one more Back leaves the page's first entry, as normal

    def test_closing_a_peek_when_back_goes_nowhere_rewrites_the_entry(self):
        # A restored or duplicated tab: the entry still carries the peek mark but the stack behind it is gone, so Back does nothing.
        with chrome() as cdp:
            self.draw(cdp, "#work&p=PDF&item=A-12")
            self.until("clarkPage.peek() && clarkPage.peek().id", "A-12", "restored")
            self.ev("history.replaceState({clarkPeek: 1}, '', location.hash)")
            cdp.call("Page.resetNavigationHistory", {}, self.sid)
            self.until("history.length", 1, "no earlier entry")
            self.ev("window.urls = []")
            self.ev("clarkPage.closePeek()")
            self.until("location.hash", "#work&p=PDF", "the fallback rewrote the entry")
            self.until("clarkPage.peek()", None, "and the page drew without the peek")
            self.assertEqual(self.at()[1], 1)
            self.assertEqual(self.ev("window.urls"), ["replaceState #work&p=PDF"], "one rewrite, no entry added")
            self.assertEqual(self.tab(), "work")
            self.no_errors()

    def test_closing_a_peek_that_back_can_close_does_not_also_rewrite(self):
        with chrome() as cdp:
            self.draw(cdp, "#work&p=PDF")
            self.ev("clarkPage.openPeek('A-12')")
            n = self.at()[1]
            self.ev("window.urls = []")
            self.ev("clarkPage.closePeek()")
            self.until("location.hash", "#work&p=PDF", "back closed it")
            time.sleep(0.7)                                            # past the router's wait for Back to move the address
            self.assertEqual(self.ev("window.urls"), [], "Back moved, so the fallback never ran")
            self.assertEqual(self.at()[1], n, "the opened entry is still there to go Forward to")
            self.no_errors()

    def test_a_peek_for_an_id_the_data_does_not_have_does_nothing(self):
        with chrome() as cdp:
            self.draw(cdp, "#work&p=PDF")
            before = self.at()
            for args in ("'Z-99'", "'Z-99', 'milestone'", "'Z-99', 'item'", "'M-3', 'item'", "'A-12', 'milestone'", "''", "'../x'"):
                self.ev(f"clarkPage.openPeek({args})")
            self.assertEqual(self.at(), before, "no entry pushed, none rewritten")
            self.assertIsNone(self.peek())
            self.ev("clarkPage.openPeek('A-12')")
            opened_at = self.at()
            self.ev("clarkPage.openPeek('Z-99')")
            self.assertEqual(self.at(), opened_at, "with a peek open, an unknown id leaves it as it was")
            self.assertEqual(self.peek(), {"kind": "item", "id": "A-12"})
            self.assertEqual(self.ev("window.urls"), ["pushState #work&p=PDF&item=A-12"], "the one real open, nothing else")
            self.no_errors()

    def test_when_the_address_cannot_be_set_at_all_the_page_still_changes(self):
        # location.hash cannot be stubbed in Chrome, so the address is held still instead: a cancelled navigate event makes pushState
        # throw and leaves a set hash unmoved, the router's two ways in. The page must draw the state it was asked for.
        hold = "navigation.addEventListener('navigate', function (e) { if (window.hold) e.preventDefault(); });"
        with chrome() as cdp:
            self.draw(cdp, "#dashboard&p=PDF", extra=hold)
            self.ev("window.hold = true")
            self.click_tab("work")
            self.assertEqual(self.tab(), "work", "the page changed")
            self.assertEqual(self.ev("location.hash"), "#dashboard&p=PDF", "though the address could not")
            self.ev("clarkPage.openPeek('A-12')")
            self.assertEqual(self.peek(), {"kind": "item", "id": "A-12"})
            self.ev("clarkPage.closePeek()")
            self.until("clarkPage.peek()", None, "the peek closed too")
            self.ev("clarkPage.setProject('QRS')")
            self.until("document.getElementById('project-name').textContent", "Second Programme", "and the project changed")
            self.assertEqual(self.ev("location.hash"), "#dashboard&p=PDF")
            self.no_errors()

    def test_previous_next_and_another_row_replace_the_entry(self):
        with chrome() as cdp:
            self.draw(cdp, "#work&p=PDF")
            self.ev("clarkPage.openPeek('A-12')")
            opened_at = self.at()
            self.ev("clarkPage.openPeek('A-13')")
            self.ev("clarkPage.openPeek('A-12')")
            self.ev("clarkPage.openPeek('M-3')")
            self.assertEqual(self.at(), ["#work&p=PDF&ms=M-3", opened_at[1]], "item to item to milestone: the count did not move")
            self.assertEqual(self.peek(), {"kind": "milestone", "id": "M-3"})
            self.ev("clarkPage.closePeek()")                           # one step closes it, the replaced entries having kept the mark
            self.until("location.hash", "#work&p=PDF", "one Back closed it")
            self.assertIsNone(self.peek())

    def test_closing_a_peek_that_a_reload_opened_rewrites_the_entry(self):
        with chrome() as cdp:
            self.draw(cdp, "#work&p=PDF&item=A-12")
            self.until("clarkPage.peek() && clarkPage.peek().id", "A-12", "restored")
            n = self.at()[1]
            self.ev("clarkPage.closePeek()")
            self.until("location.hash", "#work&p=PDF", "closed in place")
            self.assertEqual(self.at()[1], n)

    def test_a_project_switch_pushes_one_entry_closes_the_peek_and_back_returns(self):
        with chrome() as cdp:
            self.draw(cdp, "#work&p=PDF")
            self.ev("clarkPage.openPeek('A-12')")
            n = self.at()[1]
            self.ev("clarkPage.setProject('QRS')")
            self.assertEqual(self.at(), ["#work&p=QRS", n + 1])
            self.assertIsNone(self.peek(), "the peek closed")
            self.until("document.getElementById('project-name').textContent", "Second Programme", "the new project's data")
            self.ev("clarkPage.setProject('QRS')")
            self.assertEqual(self.at()[1], n + 1, "the same project adds nothing")
            self.ev("history.back()")
            self.until("document.getElementById('project-name').textContent", "Example Programme", "back to the first project")
            self.assertEqual(self.peek(), {"kind": "item", "id": "A-12"}, "and its peek")
            self.ev("history.forward()")
            self.until("document.getElementById('project-name').textContent", "Second Programme", "forward")
            self.ev("clarkPage.setProject('not a code')")
            self.assertEqual(self.at(), ["#work&p=QRS", n + 1], "a bad code changes nothing")
            self.no_errors()

    def test_scroll_resize_escape_and_repeated_calls_add_no_entry(self):
        # The real "history.length unchanged" check for filters, search, sort, Edit and the calendar waits for #64a and #42.
        with chrome() as cdp:
            self.draw(cdp, "#work&p=PDF")
            before = self.at()
            self.ev("document.body.style.minHeight = '5000px'; window.scrollTo(0, 800); window.scrollTo(0, 0)")
            for w in (900, 1400):
                cdp.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": 900, "deviceScaleFactor": 1, "mobile": False}, self.sid)
            self.ev("document.querySelector('.tab').focus()")
            self.ev("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))")
            self.ev("clarkPage.show('work'); clarkPage.setProject('PDF'); clarkPage.closePeek()")       # nothing to do: no entry
            self.assertEqual(self.at(), before)
            self.assertEqual(self.ev("window.urls"), [])
            self.no_errors()

    def test_every_history_call_the_page_makes_is_hash_only(self):
        with chrome() as cdp:
            self.draw(cdp, "#dashboard&p=PDF")
            before = self.ev("location.href.split('#')[0]")
            for view in ("work", "milestones", "settings"):
                self.click_tab(view)
            self.ev("clarkPage.show('work'); clarkPage.openPeek('A-12'); clarkPage.openPeek('A-13'); clarkPage.closePeek()")
            self.until("location.hash", "#work&p=PDF", "closed")
            self.ev("clarkPage.setProject('QRS')")
            urls = self.ev("window.urls")
            self.assertGreaterEqual(len(urls), 6)
            for u in urls:
                self.assertRegex(u, r"^(push|replace)State #(dashboard|work|milestones|settings)(&p=[A-Z0-9]+)?(&(item|ms)=[A-Za-z0-9._-]+)?$")
            self.assertEqual(self.ev("location.href.split('#')[0]"), before)
            self.assertEqual(self.ev("location.search"), "")

    def test_a_reload_keeps_the_page_the_project_and_the_peek(self):
        for want in ("#work&p=PDF&item=A-13", "#milestones&p=PDF&ms=M-3", "#settings&p=PDF", "#dashboard&p=QRS"):
            with chrome() as cdp:
                self.draw(cdp, "#dashboard&p=PDF")
                state = route = None
                self.ev("clarkPage.show('dashboard')")
                self.cdp.call("Page.navigate", {"url": self.base + want}, self.sid)              # a bookmark
                self.until("document.documentElement.dataset.ready", "1", "reopened")
                self.cdp.call("Page.reload", {}, self.sid)
                self.until("document.documentElement.dataset.ready", "1", "reloaded")
                name = DATA[re.search(r"p=([A-Z]+)", want).group(1)]["project"]["name"]
                self.until("document.getElementById('project-name').textContent", name, f"the project after reload of {want}")
                self.assertEqual(self.ev("location.hash"), want)
                view = want[1:].split("&")[0]
                self.assertEqual(self.tab(), view)
                peek = self.peek()
                if "item=" in want:
                    self.assertEqual(peek, {"kind": "item", "id": "A-13"})
                elif "ms=" in want:
                    self.assertEqual(peek, {"kind": "milestone", "id": "M-3"})
                else:
                    self.assertIsNone(peek)
                self.no_errors()

    def test_unknown_things_fall_back_without_an_error(self):
        with chrome() as cdp:
            self.draw(cdp, "#nope&p=PDF")
            self.assertEqual(self.tab(), "dashboard", "an unknown page opens the Dashboard")
            self.no_errors()
        with chrome() as cdp:
            self.draw(cdp, "#work&p=PDF&item=Z-99")
            self.until("clarkPage.peek()", None, "an unknown item opens the page with no peek")
            self.until("location.hash", "#work&p=PDF", "and the address is rewritten")
            self.assertEqual(self.tab(), "work")
            self.assertEqual(self.ev("window.urls"), ["replaceState #work&p=PDF"], "rewritten, not added")
            self.no_errors()
        with chrome() as cdp:
            self.draw(cdp, "#milestones&p=PDF&ms=M-99")
            self.until("clarkPage.peek()", None, "an unknown milestone")
            self.no_errors()
        with chrome() as cdp:
            self.draw(cdp, "#work&p=ZZZ", expect="That project isn't here")                       # well-formed, not there
            self.no_errors()
        with chrome() as cdp:
            self.draw(cdp, "#work&p=<script>alert(1)</script>&item=%E0%A4%A", expect="No project open")
            self.assertEqual(self.tab(), "work")
            self.assertIsNone(self.peek() if self.ev("!!window.clarkPage") else None)
            self.no_errors()

    def test_back_from_the_first_entry_leaves_clark_as_normal(self):
        with chrome() as cdp:
            self.draw(cdp, "#dashboard&p=PDF")
            self.click_tab("work")
            self.ev("history.back()")
            self.until("location.hash", "#dashboard&p=PDF", "back to the first page")
            self.leave()

    # ---- `f` in the built page: the store's f signal and setFilters (#64a binds to them) ----

    def test_f_is_read_on_load_and_kept_by_a_reload(self):
        with chrome() as cdp:
            self.draw(cdp, "#work&p=PDF&item=A-12&f=a%26b%3Dc")
            self.assertEqual(self.ev("clarkPage.filters()"), "a%26b%3Dc")
            self.assertEqual(self.peek(), {"kind": "item", "id": "A-12"}, "the peek is untouched by f")
            self.cdp.call("Page.reload", {}, self.sid)
            self.until("document.documentElement.dataset.ready", "1", "reloaded")
            self.until("document.getElementById('project-name').textContent", "Example Programme", "the data")
            self.assertEqual(self.ev("location.hash"), "#work&p=PDF&item=A-12&f=a%26b%3Dc")
            self.assertEqual(self.ev("clarkPage.filters()"), "a%26b%3Dc")
            self.no_errors()
        with chrome() as cdp:
            self.draw(cdp, "#work&p=PDF&f=%zz")
            self.assertEqual(self.ev("clarkPage.filters()"), "")
            self.no_errors()

    def test_setfilters_rewrites_the_entry_so_back_never_stops_on_a_filter(self):
        with chrome() as cdp:
            self.draw(cdp, "#dashboard&p=PDF")
            self.click_tab("work")
            before = self.at()
            for text in ("a", "ab", "ab%26c%3Dd", ""):
                self.ev(f"clarkPage.setFilters({json.dumps(text)})")
                self.assertEqual(self.ev("clarkPage.filters()"), text)
            self.ev("clarkPage.setFilters('a')")
            self.assertEqual(self.at(), ["#work&p=PDF&f=a", before[1]], "length unchanged, entry replaced")
            self.assertEqual(self.ev("window.urls.slice(1)"), ["replaceState #work&p=PDF&f=a", "replaceState #work&p=PDF&f=ab",
                                                              "replaceState #work&p=PDF&f=ab%26c%3Dd", "replaceState #work&p=PDF",
                                                              "replaceState #work&p=PDF&f=a"])
            self.ev("clarkPage.setFilters('a')")
            self.assertEqual(self.ev("window.urls.length"), 6, "the same text again: no call")
            self.ev("history.back()")
            self.until("document.querySelector('.tab[aria-selected=true]').dataset.view", "dashboard", "one Back left the filtered page")
            self.assertEqual(self.ev("clarkPage.filters()"), "")
            self.ev("history.forward()")
            self.until("clarkPage.filters()", "a", "Forward brings f back")
            self.assertEqual(self.tab(), "work")
            self.no_errors()

    def test_f_survives_a_peek_and_comes_back_with_back_and_forward(self):
        with chrome() as cdp:
            self.draw(cdp, "#work&p=PDF")
            self.ev("clarkPage.setFilters('x%26y')")
            n = self.at()[1]
            self.ev("clarkPage.openPeek('A-12')")
            self.assertEqual(self.at(), ["#work&p=PDF&item=A-12&f=x%26y", n + 1], "the peek keeps f")
            self.ev("clarkPage.setFilters('z')")
            self.assertEqual(self.at(), ["#work&p=PDF&item=A-12&f=z", n + 1], "a filter change with a peek open still rewrites")
            self.ev("clarkPage.closePeek()")
            self.until("location.hash", "#work&p=PDF&f=z", "a filter changed while it was open stays: the entry is rewritten, not stepped back (#42)")
            self.assertEqual(self.at()[1], n + 1, "no entry added or lost")
            self.ev("history.back()")
            self.until("location.hash", "#work&p=PDF&f=x%26y", "Back goes to the entry before the peek, which has its own f")
            self.assertIsNone(self.peek())
            self.no_errors()

    def test_a_page_or_project_change_pushes_one_entry_and_back_restores_f(self):
        with chrome() as cdp:
            self.draw(cdp, "#work&p=PDF")
            self.ev("clarkPage.setFilters('keep')")
            n = self.at()[1]
            self.click_tab("milestones")
            self.assertEqual(self.at(), ["#milestones&p=PDF", n + 1])
            self.assertEqual(self.ev("clarkPage.filters()"), "", "the filters belong to one page")
            self.ev("history.back()")
            self.until("clarkPage.filters()", "keep", "back")
            self.ev("clarkPage.setProject('QRS')")
            self.assertEqual(self.at(), ["#work&p=QRS", n + 1])
            self.assertEqual(self.ev("clarkPage.filters()"), "")
            self.until("document.getElementById('project-name').textContent", "Second Programme", "the new project")
            self.ev("history.back()")
            self.until("document.getElementById('project-name').textContent", "Example Programme", "back to the first project")
            self.assertEqual(self.ev("[location.hash, clarkPage.filters()]"), ["#work&p=PDF&f=keep", "keep"])
            self.no_errors()

    def test_every_history_call_with_f_is_still_hash_only(self):
        with chrome() as cdp:
            self.draw(cdp, "#work&p=PDF")
            before = self.ev("location.href.split('#')[0]")
            self.ev("clarkPage.setFilters('a%26b'); clarkPage.openPeek('A-12'); clarkPage.setFilters('c'); clarkPage.closePeek()")
            urls = self.ev("window.urls")
            self.assertGreaterEqual(len(urls), 3)       # closePeek steps Back, so makes no call
            for u in urls:
                self.assertRegex(u, r"^(push|replace)State #[a-z]+(&p=[A-Z0-9]+)?(&(item|ms)=[A-Za-z0-9._-]+)?(&f=[A-Za-z0-9%._~-]+)?$")
            self.assertEqual(self.ev("location.href.split('#')[0]"), before)
            self.assertEqual(self.ev("location.search"), "")
            self.no_errors()


class FileUrl(Browser):
    """The built page opened from file:// with no server: its tabs and addresses work (its data needs the server, so it says so)."""

    def test_the_built_page_pushes_hash_only_entries_from_a_file_url(self):
        with tempfile.TemporaryDirectory() as tmp, chrome() as cdp:
            f = Path(tmp) / "page.html"
            f.write_text(testpage.html(), encoding="utf-8")
            self.cdp = cdp
            self.sid = opened(cdp, f.as_uri() + "#work&p=PDF&item=A-12")
            self.assertTrue(wait(lambda: cdp.js("document.documentElement.dataset.ready", self.sid) == "1"))
            self.assertEqual(self.ev("location.protocol"), "file:")
            n = self.at()[1]
            for view in ("milestones", "settings"):
                self.ev(f"document.querySelector('[data-view={view}]').click()")
            self.assertEqual(self.at(), ["#settings&p=PDF", n + 2])
            self.ev("history.back()")
            self.until("document.querySelector('.tab[aria-selected=true]').dataset.view", "milestones", "back")
            self.ev("clarkPage.openPeek('M-3', 'milestone')")
            self.assertEqual(self.at(), ["#milestones&p=PDF&ms=M-3", n + 2], "no data to check it against, so it stays")
            self.ev("history.back()")
            self.until("location.hash", "#milestones&p=PDF", "back closed the peek")
            self.assertTrue(all(u.split(" ", 1)[1].startswith("#") for u in self.ev("window.urls")))
            self.no_errors()

    def test_f_works_from_a_file_url_too(self):
        with tempfile.TemporaryDirectory() as tmp, chrome() as cdp:
            f = Path(tmp) / "page.html"
            f.write_text(testpage.html(), encoding="utf-8")
            self.cdp = cdp
            self.sid = opened(cdp, f.as_uri() + "#work&p=PDF&f=a%26b")
            self.assertTrue(wait(lambda: cdp.js("document.documentElement.dataset.ready", self.sid) == "1"))
            self.assertEqual(self.ev("location.protocol"), "file:")
            self.assertEqual(self.ev("clarkPage.filters()"), "a%26b")
            n = self.at()[1]
            self.ev("clarkPage.setFilters('c%3Dd')")
            self.assertEqual(self.at(), ["#work&p=PDF&f=c%3Dd", n])
            self.assertTrue(all(u.split(" ", 1)[1].startswith("#") for u in self.ev("window.urls")))
            self.no_errors()


if __name__ == "__main__":
    unittest.main()
