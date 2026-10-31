"""#47c slice 3: the smoke-test script for the real Claude command (dev/tools/ask_claude_smoke.py), tested with fake commands.
Run: python3 dev/run_tests.py test_ask_claude_smoke

The script is run for real by hand once on a Mac with the real command (the report goes in the PR); these tests show that it can tell the
cases apart: a command that honours the isolating flags passes; one that still runs the person's hooks, helper, MCP server or CLAUDE.md
fails, naming the canary; one whose checks run a canary fails; one whose sign-in check would accept a key fails; and one whose canaries
were never armed (it ran none even without the flags) is INCONCLUSIVE, never a pass. Nothing here starts the real command or touches the
real ~/.claude, except the opt-in class RealCommand at the end.

RealCommand (skipped unless CLARK_SMOKE_REAL_CLAUDE=1, and only on a Mac) runs the whole smoke test against the real `claude` in its
fixed places, with the person's own sign-in: it spends two or three one-word questions of their plan. Run it by hand:
    CLARK_SMOKE_REAL_CLAUDE=1 python3 dev/run_tests.py test_ask_claude_smoke
and paste the printed report into the PR.
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _paths  # noqa: F401
from _paths import TOOLS

sys.path.insert(0, str(TOOLS))
import ask_claude_smoke as smoke  # noqa: E402
from clark import ask_claude, platform  # noqa: E402

FAKE = '''#!/usr/bin/env python3
import json, os, subprocess, sys
mode = %r
args = sys.argv[1:]
sys.stdin.read()
home = os.environ.get("HOME", "")
def canaries(cfg_only=False):
    cfg = json.load(open(os.path.join(home, ".claude", "settings.json"), encoding="utf-8"))
    if cfg_only:
        subprocess.run([cfg["apiKeyHelper"]], stdout=subprocess.DEVNULL)
        return
    for event, groups in cfg.get("hooks", {}).items():
        for g in groups:
            for h in g["hooks"]:
                subprocess.run([h["command"]], stdout=subprocess.DEVNULL)
    subprocess.run([cfg["apiKeyHelper"]], stdout=subprocess.DEVNULL)
    os.makedirs(os.path.join(cfg["env"]["CLAUDE_CODE_TMPDIR"], "claude-501"), exist_ok=True)
    mcp = json.load(open(os.path.join(home, ".claude.json"), encoding="utf-8"))["mcpServers"]["canary"]["command"]
    subprocess.run([mcp], stdout=subprocess.DEVNULL)
if args == ["--version"]:
    print("2.1.0 (fake)"); sys.exit(0)
if args == ["--help"]:
    print("\\n".join("  " + f for f in %r)); sys.exit(0)
if args == ["--setting-sources", "", "auth", "status"]:
    if mode == "checkfires":
        canaries(cfg_only=True)
    if mode == "lax":
        print(json.dumps({"loggedIn": True, "authMethod": "claude.ai"})); sys.exit(0)
    print(json.dumps({"loggedIn": False, "authMethod": "api_key_helper"})); sys.exit(1)
isolated = "--safe-mode" in args
armed = mode in ("honours", "ignores", "writes", "checkfires", "lax") and (not isolated or mode in ("ignores", "writes"))
text = "OK"
if armed:
    canaries()
    text = open(os.path.join(home, ".claude", "CLAUDE.md"), encoding="utf-8").read().split()[-1].rstrip(".") + " OK"
if mode == "writes" and isolated:
    open(os.path.join(home, ".claude", "session.jsonl"), "w", encoding="utf-8").write("saved")
    open(os.path.join(home, ".claude.json"), "a", encoding="utf-8").write(" ")
if "json" in args:
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text}))
else:
    print(text)
'''


def fake(folder, mode):
    path = Path(folder) / f"claude-{mode}"
    path.write_text(FAKE % (mode, list(ask_claude.NEEDED_FLAGS)), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


CANARY_CHECKS = [f"hook-{e}" for e in smoke.HOOK_EVENTS] + ["apiKeyHelper", "mcp-server", "settings-env"]


class Smoke(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.was, smoke.SETTLE = smoke.SETTLE, 0.3                      # the real run waits 2 s for a late helper; a fake needs no wait
        self.addCleanup(setattr, smoke, "SETTLE", self.was)
        for patch in (mock.patch.object(platform, "system", return_value=platform.MAC),      # the fakes are scripts, and CI is Linux
                      mock.patch.object(ask_claude, "native_problem", return_value=None)):
            patch.start()
            self.addCleanup(patch.stop)

    def states(self, mode):
        report = smoke.smoke(fake(self.tmp.name, mode), real=False)
        return {name: state for name, state, _ in report}, report

    def test_a_command_that_honours_the_flags_passes_every_check(self):
        states, report = self.states("honours")
        self.assertEqual({s for s in states.values()} - {smoke.PASS, smoke.NOTE}, set(), report)
        self.assertEqual(states["control: the canaries run when nothing isolates the command"], smoke.PASS)
        self.assertIn("isolated: the answer is not shaped by the CLAUDE.md canary", states)
        for label in ("checks", "isolated"):
            self.assertEqual(sorted(n for n in states if n.startswith(label + ": ") and n.endswith("did not run")),
                             sorted(f"{label}: {c} did not run" for c in CANARY_CHECKS))
            self.assertEqual(states[f"{label}: settings-env did not run"], smoke.PASS, "the settings env canary was armed by the control")
        self.assertEqual(states["the sign-in check refuses a home with no sign-in and an apiKeyHelper"], smoke.PASS)
        self.assertEqual(smoke.text_report("fake", report).splitlines()[-1], "RESULT: PASS")

    def test_a_command_that_still_runs_the_canaries_fails_and_names_each(self):
        states, report = self.states("ignores")
        for name in CANARY_CHECKS:
            self.assertEqual(states[f"isolated: {name} did not run"], smoke.FAIL, name)
        self.assertEqual(states["isolated: the answer is not shaped by the CLAUDE.md canary"], smoke.FAIL)
        self.assertIn("must not merge", smoke.text_report("fake", report))

    def test_a_check_that_runs_the_helper_fails(self):
        states, _ = self.states("checkfires")
        self.assertEqual(states["checks: apiKeyHelper did not run"], smoke.FAIL)
        self.assertEqual(states["isolated: apiKeyHelper did not run"], smoke.PASS)

    def test_a_sign_in_check_that_would_accept_the_throw_away_home_fails(self):
        states, _ = self.states("lax")
        self.assertEqual(states["the sign-in check refuses a home with no sign-in and an apiKeyHelper"], smoke.FAIL)

    def test_a_command_that_writes_under_the_home_fails(self):
        states, _ = self.states("writes")
        self.assertEqual(states["isolated: no new file under the throw-away ~/.claude"], smoke.FAIL)
        self.assertEqual(states["isolated: ~/.claude.json is byte for byte as it was"], smoke.FAIL)

    def test_canaries_that_were_never_armed_are_inconclusive_never_a_pass(self):
        states, report = self.states("quiet")
        self.assertEqual(states["control: the canaries run when nothing isolates the command"], smoke.INCONCLUSIVE)
        for name, state in states.items():
            if name.startswith(("isolated: hook-", "checks: hook-")) or name in ("isolated: apiKeyHelper did not run", "isolated: mcp-server did not run"):
                self.assertEqual(state, smoke.INCONCLUSIVE, name)
        self.assertEqual(states["isolated: settings-env did not run"], smoke.NOTE, "an unarmed optional canary is a note")
        self.assertNotEqual(smoke.text_report("fake", report).splitlines()[-1], "RESULT: PASS")

    def test_an_isolated_run_with_no_answer_never_passes_a_canary_check(self):
        path = Path(self.tmp.name) / "claude-silent"
        path.write_text(FAKE.replace('if "json" in args:', 'if "json" in args:\n    sys.exit(1)\nif False:') % ("honours", list(ask_claude.NEEDED_FLAGS)), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        report = smoke.smoke(path, real=False)
        states = {n: s for n, s, _ in report}
        self.assertEqual(states["checks: apiKeyHelper did not run"], smoke.PASS, "the checks ran through, so they are judged")
        for name in CANARY_CHECKS:
            self.assertEqual(states[f"isolated: {name} did not run"], smoke.INCONCLUSIVE, name)
        self.assertEqual(states["isolated: the CLAUDE.md canary could not be tested"], smoke.INCONCLUSIVE)
        self.assertEqual(states["isolated: no new file under the throw-away ~/.claude"], smoke.PASS, "the run started and ended")
        self.assertNotEqual(smoke.text_report("fake", report).splitlines()[-1], "RESULT: PASS")

    def test_each_canary_is_judged_against_its_own_arming(self):
        path = Path(self.tmp.name) / "claude-partial"
        path.write_text(FAKE.replace('    subprocess.run([mcp], stdout=subprocess.DEVNULL)',
                                     '    if mode != "partial":\n        subprocess.run([mcp], stdout=subprocess.DEVNULL)')
                        .replace('armed = mode in ("honours",', 'armed = mode in ("honours", "partial",') % ("partial", list(ask_claude.NEEDED_FLAGS)),
                        encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        report = smoke.smoke(path, real=False)
        states = {n: s for n, s, _ in report}
        self.assertEqual(states["control: the canaries run when nothing isolates the command"], smoke.INCONCLUSIVE)
        self.assertEqual(states["isolated: mcp-server did not run"], smoke.INCONCLUSIVE, "never armed, so its silence shows nothing")
        self.assertEqual(states["checks: mcp-server did not run"], smoke.INCONCLUSIVE)
        self.assertEqual(states["isolated: apiKeyHelper did not run"], smoke.PASS)
        self.assertNotEqual(smoke.text_report("fake", report).splitlines()[-1], "RESULT: PASS")

    def test_a_command_the_check_refuses_fails_the_check(self):
        path = Path(self.tmp.name) / "claude-old"
        path.write_text("#!/bin/sh\necho 1.0.0\n", encoding="utf-8")        # a version, but --help lists none of the flags
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        states = {n: s for n, s, _ in smoke.smoke(path, real=False)}
        self.assertEqual(states["the native-program, version and flag checks accept this command"], smoke.FAIL)

    def test_a_refused_command_never_passes_an_isolated_check(self):
        for flag in ("--setting-sources", ask_claude.NEEDED_FLAGS[-1]):      # each missing flag is pinned in test_ask_claude
            path = Path(self.tmp.name) / "claude-short"
            path.write_text(FAKE % ("honours", [f for f in ask_claude.NEEDED_FLAGS if f != flag]), encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
            report = smoke.smoke(path, real=False)
            states = {n: s for n, s, _ in report}
            self.assertEqual(states["control: the canaries run when nothing isolates the command"], smoke.PASS, flag)
            self.assertEqual(states["the native-program, version and flag checks accept this command"], smoke.FAIL, flag)
            isolated = {n: s for n, s in states.items() if n.startswith("isolated: ")}
            self.assertEqual(sorted(isolated), sorted([f"isolated: {c} did not run" for c in CANARY_CHECKS] + [
                "isolated: the CLAUDE.md canary could not be tested", "isolated: no new file under the throw-away ~/.claude",
                "isolated: ~/.claude.json is byte for byte as it was"]), flag)
            self.assertEqual(set(isolated.values()), {smoke.INCONCLUSIVE}, flag)
            self.assertNotEqual(smoke.text_report("fake", report).splitlines()[-1], "RESULT: PASS", flag)

    def test_the_canaries_are_planted_in_a_throw_away_home_and_markers_start_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, markers = Path(tmp) / "h", Path(tmp) / "m"
            home.mkdir()
            marks = smoke.plant(home, markers)
            self.assertEqual(len(marks), len(smoke.HOOK_EVENTS) + 3)
            self.assertFalse(any(p.exists() for p in marks.values()))
            cfg = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(cfg["hooks"]), sorted(smoke.HOOK_EVENTS))
            self.assertEqual(cfg["env"]["CLAUDE_CODE_TMPDIR"], str(marks["settings-env"]))
            self.assertIn(smoke.CANARY_WORD, (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8"))
            self.assertNotEqual(str(home), os.path.expanduser("~"))

    def test_the_script_never_writes_under_the_real_claude_folder(self):
        text = (TOOLS / "ask_claude_smoke.py").read_text(encoding="utf-8")
        self.assertNotIn('expanduser("~/.claude")', text)
        self.assertNotIn("Path.home()", text)
        real_part = text.split("    if real:")[1].split("def text_report")[0]
        for writer in ("write_text", "write_bytes", "open(", "unlink", "rmtree", "mkdir"):
            self.assertNotIn(writer, real_part, "the real home's folder is only listed, by file name")


@unittest.skipUnless(os.environ.get("CLARK_SMOKE_REAL_CLAUDE") == "1" and sys.platform == "darwin",
                     "the real-command smoke test runs only by hand on a Mac: CLARK_SMOKE_REAL_CLAUDE=1")
class RealCommand(unittest.TestCase):
    """The merge blocker: the whole smoke test against the real command, with its report printed for the PR."""

    def test_the_real_command_passes_every_check(self):
        command, why = ask_claude.find_command()
        self.assertIsNotNone(command, why)
        report = smoke.smoke(command, real=True)
        text = smoke.text_report(command, report)
        print("\n" + text)
        self.assertEqual(text.splitlines()[-1], "RESULT: PASS", text)


if __name__ == "__main__":
    unittest.main()
