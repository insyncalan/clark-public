"""#47c: the Claude command provider (src/clark/ask_claude.py, guarded-derived), against a FAKE command. Nothing here runs the real
`claude` (it would spend the person's plan); the fake is a small Python script written into a temporary folder that records what it
was given (its arguments, its environment, its working folder, its temporary folder, standard input, its open descriptors and its
umask) and answers as each test asks.

Run: python3 dev/run_tests.py test_ask_claude
These tests pin the arguments, standard input, the fixed places, the native-program rule, the sign-in check, the scrubbed
environment, the hints and the process handling. They cannot prove that the real command honours --safe-mode; that is the smoke
test (dev/tools/ask_claude_smoke.py, and the opt-in class in tests/test_ask_claude_smoke.py), run by hand on a Mac.
"""
import json
import os
import pwd
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from _paths import SRC  # noqa: F401

from clark import ask, ask_claude as ac, platform

HELP = "\n".join(f"  {f} <x>   something" for f in ac.NEEDED_FLAGS)
SIGNED_IN = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty"})
ANSWER = "The plan is on track.\nCITE: P1"

FAKE = r'''#!@PYTHON@ -B
import json, os, stat, sys, time
here = os.path.dirname(os.path.abspath(__file__))
def rd(name, default=""):
    try:
        with open(os.path.join(here, name), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return default
mode = rd("mode").strip()
args = sys.argv[1:]
if mode == "escape" and "--print" in args:        # a helper that leaves the group and holds standard input without reading it
    import subprocess
    p = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(30)"], start_new_session=True,
                         stdout=subprocess.DEVNULL)
    with open(os.path.join(here, "escaped.pid"), "w", encoding="utf-8") as f:
        f.write(str(p.pid))
    sys.exit(0)
data = sys.stdin.buffer.read()                    # waits for the end of standard input, as the real command does
again = sys.stdin.buffer.read()
with open(os.path.join(here, "calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"args": args, "eof": again == b"", "env": dict(os.environ)}) + "\n")
if args == ["--version"]:
    print("not a version" if mode == "badversion" else "2.1.312 (Claude Code)")
    sys.exit(0)
if args == ["--help"]:
    print(rd("help"))
    sys.exit(0)
if args == ["--setting-sources", "", "auth", "status"]:
    sys.stdout.write(rd("auth"))
    sys.exit(int(rd("authcode", "0") or "0"))
tmp = os.environ.get("TMPDIR", "")
tmp_st = os.stat(tmp) if tmp and os.path.isdir(tmp) else None
start_cwd, start_tmp = os.listdir("."), (os.listdir(tmp) if tmp_st else None)
FDS, INO, SOCK = [], {}, set()
for name in os.listdir("/dev/fd"):
    n = int(name)
    try:
        st = os.fstat(n)
    except OSError:
        continue                                  # the descriptor that listed the folder is already closed
    FDS.append(n)
    INO[n] = st.st_ino
    if stat.S_ISSOCK(st.st_mode):
        SOCK.add(n)
FDS.sort()
mask = os.umask(0)
os.umask(mask)
with open(os.path.join(here, "seen.json"), "w", encoding="utf-8") as f:
    json.dump({"args": args, "env": dict(os.environ), "cwd": os.getcwd(), "stdin": data.decode("utf-8", "surrogateescape"),
               "stdin_len": len(data), "eof": again == b"", "pid": os.getpid(), "pgid": os.getpgid(0), "fds": FDS,
               "inodes": {str(n): INO[n] for n in FDS if n > 2 and n in INO}, "sockets": [n for n in FDS if n in SOCK],
               "umask": mask, "tmp": tmp, "tmp_mode": (tmp_st.st_mode & 0o777) if tmp_st else None,
               "tmp_uid": tmp_st.st_uid if tmp_st else None, "start_cwd": start_cwd, "start_tmp": start_tmp}, f)
if mode == "slow":
    time.sleep(60)
if mode == "helper":
    import subprocess
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    with open(os.path.join(here, "helper.pid"), "w", encoding="utf-8") as f:
        f.write(str(p.pid))
    time.sleep(60)
if mode == "flood":
    sys.stdout.write("x" * 10000000)
    sys.stdout.flush()
    time.sleep(60)
if mode == "fail":
    sys.stderr.write("secret request text in an error " + "sk" + "-ant-api03-canary\n")    # built here, so no key shape is in this file
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "half an answer"}))
    sys.exit(1)
if mode == "empty":
    sys.exit(0)
if mode == "litter":
    for folder in (".", tmp):
        with open(os.path.join(folder, "left-behind.txt"), "w", encoding="utf-8") as f:
            f.write("x")
if mode == "raw":
    sys.stdout.buffer.write(bytes.fromhex(rd("raw").strip()))
    sys.exit(0)
sys.stdout.write(rd("reply"))
'''


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:                                   # a zombie that has not been reaped yet counts as gone
        with os.popen(f"ps -o stat= -p {pid}") as p:
            return not p.read().strip().startswith("Z")
    except OSError:
        return True


def result(text, **extra):
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text, **extra})


def tree(root):
    return sorted(str(p.relative_to(root)) for p in Path(root).rglob("*"))


class Fake(unittest.TestCase):
    """A fake command at a fixed place, on a Mac (the tests also run on Linux), with the native-program rule passed: the fake is
    a script. The rule itself is tested on its own (NativeProgram)."""
    native = True

    def setUp(self):
        self.d = Path(os.path.realpath(tempfile.mkdtemp(prefix="clark-fake-")))
        self.addCleanup(shutil.rmtree, self.d, True)
        self.bin = self.d / "bin"
        self.bin.mkdir()
        self.home = self.d / "home"
        self.home.mkdir()
        self.cmd = self.bin / "claude"
        self.cmd.write_text(FAKE.replace("@PYTHON@", sys.executable), encoding="utf-8")
        self.cmd.chmod(0o755)
        self.mode("ok")
        self.put("help", HELP)
        self.put("auth", SIGNED_IN)
        self.put("reply", result(ANSWER))
        patches = [mock.patch.object(platform, "system", return_value=platform.MAC)]
        if self.native:
            patches.append(mock.patch.object(ac, "native_problem", return_value=None))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.provider = self.make()

    def make(self, **kw):
        kw.setdefault("places", (str(self.cmd),))
        kw.setdefault("env", ac.child_env(home=str(self.home), user="tester"))
        kw.setdefault("limit", 10)
        kw.setdefault("roots", (str(self.d),))
        return ac.ClaudeCommand(**kw)

    def put(self, name, text):
        (self.bin / name).write_text(text, encoding="utf-8")

    def mode(self, m):
        self.put("mode", m)

    def seen(self):
        p = self.bin / "seen.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def calls(self):
        p = self.bin / "calls.jsonl"
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []

    def request(self, question="How is the plan?"):
        return ask.build_request(question, [ask.Passage("report: actions", "ABC-A-001 Send the plan | owner: Sam Lee")])


class Arguments(Fake):
    def test_the_command_line_is_exactly_the_fixed_flags(self):
        self.assertEqual(ac.arguments("/x/claude"), [
            "/x/claude", "--print", "--safe-mode", "--disable-slash-commands", "--tools", "", "--strict-mcp-config",
            "--setting-sources", "", "--no-session-persistence", "--max-turns", "1", "--output-format", "json",
            "--max-budget-usd", "1.00", "--system-prompt", ask.RULES])

    def test_every_flag_the_run_uses_is_checked_in_the_help_except_the_documented_unlisted_one(self):
        used = {a for a in ac.arguments("/x/claude")[1:] if a.startswith("--") and a != ask.RULES}
        self.assertEqual(used, set(ac.NEEDED_FLAGS) | {"--max-turns"})
        self.assertEqual(ac.UNLISTED_FLAGS, ("--max-turns",))
        self.assertNotIn("--max-turns", ac.NEEDED_FLAGS, "a version whose --help leaves it out is still usable")

    def test_the_sign_in_check_reads_no_settings_file(self):
        self.assertEqual(ac.AUTH_ARGS, ("--setting-sources", "", "auth", "status"))
        self.provider.status()
        self.assertIn(["--setting-sources", "", "auth", "status"], [c["args"] for c in self.calls()])

    def test_the_run_is_started_with_the_isolating_flags_and_the_request_on_standard_input(self):
        req = self.request()
        self.assertEqual(self.provider.ask(req), ANSWER)
        seen = self.seen()
        self.assertEqual(seen["args"], ac.arguments(self.cmd)[1:], "the program got exactly the fixed flags")
        for flag in ac.NEVER_FLAGS:
            self.assertNotIn(flag, seen["args"])
        self.assertEqual(seen["stdin"], req.text, "the request arrives on standard input")
        self.assertFalse(any(req.question in a for a in seen["args"]), "the question is never in the arguments")
        self.assertFalse(any("Send the plan" in a for a in seen["args"]), "no passage is in the arguments")

    def test_hostile_question_text_only_ever_reaches_standard_input(self):
        hostile = ("--dangerously-skip-permissions --add-dir / ; rm -rf ~ `id` $(id) | cat ~/.ssh/id_rsa && \x00 '\" \\\n"
                   "--settings {\"apiKeyHelper\": \"/bin/sh\"}\n" + "x" * 2_000_000)
        got = self.provider.ask(ask.Request(text=hostile, question=hostile))
        self.assertEqual(got, ANSWER)
        seen = self.seen()
        self.assertEqual(seen["args"], ac.arguments(self.cmd)[1:], "an argument list, never a shell: nothing the person typed is a flag")
        self.assertEqual(seen["stdin"], hostile)
        self.assertTrue(seen["eof"])

    def test_it_runs_in_an_empty_folder_of_its_own_that_is_removed_afterwards(self):
        self.provider.ask(self.request())
        seen = self.seen()
        self.assertTrue(Path(seen["cwd"]).name.startswith("clark-ask-"))
        self.assertEqual(seen["start_cwd"], [], "the working folder is empty when the program starts")
        self.assertNotEqual(Path(seen["cwd"]).resolve(), Path.cwd().resolve())
        self.assertFalse(Path(seen["cwd"]).exists(), "the folder is removed after the run")

    def test_its_own_process_group(self):
        self.provider.ask(self.request())
        seen = self.seen()
        self.assertEqual(seen["pid"], seen["pgid"], "started in a new session, so Stop can end the whole group")


class Environment(Fake):
    CANARIES = {"ANTHROPIC_API_KEY": "sk-ant-canary", "ANTHROPIC_BASE_URL": "https://example.test", "ANTHROPIC_AUTH_TOKEN": "c",
                "ANTHROPIC_MODEL": "c", "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CODE_USE_VERTEX": "1", "CLAUDE_CODE_OAUTH_TOKEN": "c",
                "CLAUDE_CODE_SIMPLE": "1", "CLAUDE_CONFIG_DIR": "/tmp/elsewhere", "CLAUDE_CODE_TMPDIR": "/tmp/shared",
                "AWS_SECRET_ACCESS_KEY": "c", "AWS_PROFILE": "c", "AWS_BEARER_TOKEN_BEDROCK": "c", "GITHUB_TOKEN": "c",
                "OPENAI_API_KEY": "c", "CLARK_SECRET_CANARY": "c", "PYTHONPATH": "/tmp/evil", "PYTHONSTARTUP": "/tmp/evil.py",
                "DYLD_INSERT_LIBRARIES": "/tmp/evil.dylib", "DYLD_LIBRARY_PATH": "/tmp", "LD_PRELOAD": "/tmp/evil.so",
                "NODE_OPTIONS": "--require /tmp/evil.js", "NODE_EXTRA_CA_CERTS": "/tmp/ca.pem", "HTTPS_PROXY": "http://example.test",
                "HTTP_PROXY": "http://example.test", "ALL_PROXY": "socks5://example.test", "NO_PROXY": "*", "TMPDIR": "/tmp/shared",
                "DISABLE_TELEMETRY": "", "DISABLE_AUTOUPDATER": "0", "HOME": "/tmp/not-my-home", "USER": "someone-else"}
    PINNED = {"DISABLE_TELEMETRY": "1", "DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
              "DISABLE_ERROR_REPORTING": "1", "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1"}

    def test_the_child_inherits_nothing_but_the_allow_list(self):
        with mock.patch.dict(os.environ, self.CANARIES):
            provider = self.make(env=None)                    # the real child_env(), from this process
            self.assertEqual(provider.ask(self.request()), ANSWER)
        env = self.seen()["env"]
        for name, value in self.CANARIES.items():
            self.assertNotEqual(env.get(name), value, name)
        allowed = {"PATH", "LANG", "HOME", "USER", "LOGNAME", "TMPDIR", "CLAUDE_CODE_TMPDIR", *self.PINNED,
                   "__CF_USER_TEXT_ENCODING", "PWD", "SHLVL", "_",
                   "LC_CTYPE"}      # the last five are added by the system or by Python's own locale set-up in the fake program (Linux sets LC_CTYPE)
        self.assertLessEqual(set(env), allowed, sorted(set(env) - allowed))
        self.assertEqual(env["PATH"], "/usr/bin:/bin:/usr/sbin:/sbin")
        self.assertEqual(env["HOME"], pwd.getpwuid(os.getuid()).pw_dir, "the home folder comes from the system's record, never $HOME")

    def test_the_telemetry_and_update_switches_are_pinned_in_the_child_whatever_clark_was_given(self):
        with mock.patch.dict(os.environ, self.CANARIES):
            env = ac.child_env(home=str(self.home), user="tester")
        self.assertEqual(env, {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_GB.UTF-8", "HOME": str(self.home),
                               "USER": "tester", "LOGNAME": "tester", **self.PINNED})
        self.provider = self.make(env=env)
        self.provider.ask(self.request())
        seen = self.seen()["env"]
        self.assertEqual({k: seen.get(k) for k in self.PINNED}, self.PINNED)

    def test_an_odd_user_name_or_a_relative_home_is_left_out(self):
        self.assertNotIn("USER", ac.child_env(home="/h", user="bad user;rm"))
        self.assertNotIn("HOME", ac.child_env(home="relative/home", user="tester"))

    def test_the_version_help_and_sign_in_checks_are_scrubbed_too(self):
        with mock.patch.dict(os.environ, self.CANARIES):
            self.assertTrue(self.make(env=None).status()["connected"])
        calls = self.calls()
        self.assertEqual([c["args"] for c in calls], [["--version"], ["--help"], ["--setting-sources", "", "auth", "status"]])
        for call in calls:
            self.assertFalse({k for k, v in self.CANARIES.items() if call["env"].get(k) == v}, call["args"])


class TheRunsEdges(Fake):
    """What the program inherits and where it runs. Each is recorded by the fake."""

    def test_only_standard_in_out_and_error_reach_the_program_an_open_file_and_socket_of_clarks_do_not(self):
        planted = open(self.d / "held-open.txt", "w", encoding="utf-8")
        sock = socket.socket()
        self.addCleanup(planted.close)
        self.addCleanup(sock.close)
        for fd in (planted.fileno(), sock.fileno()):
            os.set_inheritable(fd, True)               # inheritable on purpose: only close_fds stands between them and the program
        self.assertEqual(self.provider.ask(self.request()), ANSWER)
        seen = self.seen()
        self.assertTrue({0, 1, 2} <= set(seen["fds"]))
        self.assertNotIn(os.fstat(planted.fileno()).st_ino, set(seen["inodes"].values()), "clark's open file did not reach the program")
        self.assertNotIn(planted.fileno(), seen["fds"])
        self.assertNotIn(sock.fileno(), seen["fds"])
        self.assertEqual(seen["sockets"], [], "no socket of clark's reached the program")
        self.assertLessEqual(len([fd for fd in seen["fds"] if fd > 2]), 1, "nothing but the descriptor that listed /dev/fd")

    def test_what_the_program_writes_is_the_persons_alone_umask_077(self):
        self.provider.ask(self.request())
        self.assertEqual(self.seen()["umask"], 0o077)

    def test_standard_input_reaches_its_end_on_every_call_so_the_program_can_never_wait_for_more(self):
        self.provider = self.make(limit=5, check_limit=5)
        began = time.monotonic()
        self.assertEqual(self.provider.ask(self.request()), ANSWER)
        self.assertLess(time.monotonic() - began, 5)
        calls = self.calls()
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(c["eof"] for c in calls), "a second read of standard input found its end at once")

    def test_the_whole_request_arrives_and_its_end_comes_even_when_it_is_larger_than_a_pipe(self):
        big = ask.Request(text="x" * 3_000_000, question="q")
        self.assertEqual(self.provider.ask(big), ANSWER, "the program saw the end of its input and finished")
        self.assertEqual(self.seen()["stdin_len"], 3_000_000)

    def test_each_run_has_a_private_temporary_folder_of_its_own_that_is_removed_afterwards(self):
        self.provider.ask(self.request())
        first = self.seen()
        self.provider.ask(self.request())
        second = self.seen()
        for seen in (first, second):
            self.assertTrue(seen["tmp"])
            self.assertEqual(seen["env"]["CLAUDE_CODE_TMPDIR"], seen["tmp"], "the command's own temporary folder is the same one")
            self.assertEqual(seen["tmp_mode"], 0o700)
            self.assertEqual(seen["tmp_uid"], os.getuid())
            self.assertEqual(seen["start_tmp"], [], "empty when the program starts")
            self.assertNotEqual(Path(seen["tmp"]), Path(seen["cwd"]))
            self.assertFalse(Path(seen["tmp"]).exists(), "removed after the run")
            self.assertNotEqual(seen["tmp"], os.environ.get("TMPDIR"), "never clark's own temporary folder")
        self.assertNotEqual(first["tmp"], second["tmp"], "never shared between runs")

    def test_files_the_program_leaves_behind_go_with_its_folders_and_nothing_new_appears_in_the_home_folder(self):
        before = tree(self.home)
        self.mode("litter")
        self.assertEqual(self.provider.ask(self.request()), ANSWER)
        seen = self.seen()
        self.assertFalse(Path(seen["cwd"]).exists())
        self.assertFalse(Path(seen["tmp"]).exists())
        self.provider.status()
        self.assertEqual(tree(self.home), before, "clark's provider writes nothing under the home folder")
        self.assertEqual(sorted(os.listdir(self.bin)), sorted(["claude", "mode", "help", "auth", "reply", "seen.json", "calls.jsonl"]))

    def test_the_working_folder_is_never_inside_clarks_data_folder_even_when_tmpdir_says_so(self):
        data = self.d / "Library" / "Application Support" / "clark"
        data.mkdir(parents=True)
        inside = data / "tmp"
        inside.mkdir()
        with mock.patch.object(platform, "data_dir", return_value=data), mock.patch.object(platform.tempfile, "gettempdir", return_value=str(inside)):
            self.assertEqual(platform._scratch_parent(), "/tmp")
        with mock.patch.object(platform, "data_dir", return_value=data), mock.patch.object(platform.tempfile, "gettempdir", return_value=str(self.d)):
            self.assertEqual(platform._scratch_parent(), "/tmp", "a temporary folder that holds the data folder is no good either")
        elsewhere = Path(tempfile.mkdtemp(prefix="clark-else-"))
        self.addCleanup(shutil.rmtree, elsewhere, True)
        with mock.patch.object(platform, "data_dir", return_value=data), mock.patch.object(platform.tempfile, "gettempdir", return_value=str(elsewhere)):
            self.assertEqual(platform._scratch_parent(), str(elsewhere.resolve()))
        self.provider.ask(self.request())
        self.assertNotIn(str(data), self.seen()["cwd"])
        self.assertNotIn(str(data), self.seen()["tmp"])


class FoundAndChecked(Fake):
    def test_only_the_fixed_places_are_used_never_the_path(self):
        self.assertTrue(all(Path(os.path.expanduser(p)).is_absolute() for p in ac.PLACES))
        with mock.patch.dict(os.environ, {"PATH": str(self.bin)}):
            provider = self.make(places=(str(self.d / "nowhere" / "claude"),))
            self.assertEqual(provider.status()["connected"], False)
            self.assertTrue(provider.status()["why"].startswith(ac.NOT_INSTALLED))
            got = provider.ask(self.request())
        self.assertEqual(got, ask.Failure(ac.NOT_INSTALLED))
        self.assertEqual(self.calls(), [], "a command on PATH is never run")

    def test_a_relative_place_is_never_used(self):
        self.assertEqual(ac.find_command(("claude", "bin/claude"), roots=(str(self.d),)), (None, ac.NOT_INSTALLED))

    def test_ready_with_a_good_version_every_flag_and_a_claude_sign_in(self):
        with mock.patch.object(ac, "hints", return_value=[]):
            self.assertEqual(self.provider.status(), {"connected": True, "why": ac.READY})

    def test_a_missing_flag_sends_nothing(self):
        for flag in ac.NEEDED_FLAGS:
            self.put("help", "\n".join(f"  {f}" for f in ac.NEEDED_FLAGS if f != flag))
            provider = self.make()
            self.assertEqual(provider.usable(), (None, ac.CANT_USE), flag)
            self.assertEqual(provider.ask(self.request()), ask.Failure(ac.CANT_USE), flag)
            self.assertIsNone(self.seen(), f"nothing was sent without {flag}")

    def test_a_flag_named_only_in_another_options_description_does_not_count(self):
        help_text = "\n".join(f"  {f} <x>   something" for f in ac.NEEDED_FLAGS if f != "--safe-mode")
        help_text += "\n  --troubleshoot   like --safe-mode, but louder"
        self.put("help", help_text)
        self.assertFalse(self.make().status()["connected"])
        self.assertEqual(ac.listed_flags("  -p, --print   Print\n  --allowed-tools, --allowedTools <t...>  Tools: --tools\n"
                                         "Use --safe-mode to troubleshoot\n  --max-budget-usd=<n>  cap"),
                         {"-p", "--print", "--allowed-tools", "--allowedTools", "--max-budget-usd"})

    def test_a_flag_named_only_inside_a_longer_one_does_not_count(self):
        self.put("help", HELP.replace("--safe-mode ", "--safe-modes ").replace("--tools ", "--toolset "))
        self.assertEqual(self.provider.status()["connected"], False)

    def test_an_unreadable_version_sends_nothing(self):
        self.mode("badversion")
        self.assertEqual(self.provider.usable(), (None, ac.CANT_USE))
        self.mode("ok")
        self.assertEqual(self.provider.ask(self.request()), ask.Failure(ac.CANT_USE), "the check is kept for the same file")
        self.assertIsNone(self.seen())

    def test_a_changed_command_is_checked_again(self):
        self.assertTrue(self.provider.status()["connected"])
        self.put("help", "nothing useful")
        self.cmd.write_text(self.cmd.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        self.assertFalse(self.provider.status()["connected"])

    def test_the_exact_file_the_place_names_is_the_one_checked_and_run(self):
        link = self.d / "place" / "claude"
        link.parent.mkdir()
        link.symlink_to(self.cmd)
        provider = self.make(places=(str(link),))
        self.assertEqual(provider.ask(self.request()), ANSWER)
        self.assertEqual(self.calls()[-1]["args"], ac.arguments(self.cmd)[1:])
        self.assertEqual(ac.find_command((str(link),), roots=(str(self.d),)), (self.cmd, None), "the run starts the resolved file")


class NativeProgram(Fake):
    """The native-program rule (native_problem and find_command), on files made for each case."""
    native = False

    def program(self, name="claude", head=b"\xcf\xfa\xed\xfe", mode=0o755, folder=None):
        folder = folder or (self.d / "app")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_bytes(head + b"\x00" * 64)
        path.chmod(mode)
        return path

    def found(self, path, roots=None):
        return ac.find_command((str(path),), roots=roots or (str(self.d),))

    def test_a_mac_program_owned_by_this_user_is_accepted(self):
        for head in ac.MACH_O:
            path = self.program(head=head)
            self.assertEqual(self.found(path), (path, None), head)

    def test_a_script_is_refused_and_nothing_runs(self):
        self.assertEqual(self.found(self.cmd), (None, ac.NOT_NATIVE))
        self.assertEqual(self.make().usable(), (None, ac.NOT_NATIVE))
        self.assertEqual(self.make().ask(self.request()), ask.Failure(ac.NOT_NATIVE))
        self.assertEqual(self.calls(), [], "a shim or shell script is never started")
        self.assertEqual(self.found(self.program(head=b"#!/u")), (None, ac.NOT_NATIVE))

    def test_a_file_others_can_change_is_refused(self):
        self.assertEqual(self.found(self.program(mode=0o775)), (None, ac.NOT_NATIVE))
        self.assertEqual(self.found(self.program(mode=0o757)), (None, ac.NOT_NATIVE))

    def test_a_folder_others_can_change_is_refused(self):
        folder = self.d / "shared"
        path = self.program(folder=folder)
        folder.chmod(0o777)
        self.addCleanup(folder.chmod, 0o755)
        self.assertEqual(self.found(path), (None, ac.NOT_NATIVE))

    def test_a_file_that_is_not_executable_or_not_a_plain_file_is_refused(self):
        self.assertEqual(self.found(self.program(mode=0o644)), (None, ac.NOT_NATIVE))
        fifo = self.d / "app" / "pipe"
        os.mkfifo(str(fifo))
        self.assertEqual(self.found(fifo), (None, ac.NOT_NATIVE), "refused without opening it, so it cannot hang")

    def test_a_file_owned_by_someone_else_is_refused(self):
        path = self.program()
        with mock.patch.object(ac.os, "getuid", return_value=os.getuid() + 1):
            self.assertEqual(self.found(path), (None, ac.NOT_NATIVE))

    def test_a_link_out_of_the_home_and_homebrew_folders_is_refused(self):
        outside = Path(os.path.realpath(tempfile.mkdtemp(prefix="clark-out-")))
        self.addCleanup(shutil.rmtree, outside, True)
        target = self.program(folder=outside)
        link = self.d / "bin2" / "claude"
        link.parent.mkdir()
        link.symlink_to(target)
        self.assertEqual(self.found(link, roots=(str(self.d),)), (None, ac.NOT_NATIVE))
        self.assertEqual(self.found(link, roots=(str(outside),)), (target, None))

    def test_the_first_place_that_holds_anything_decides(self):
        good = self.program()
        self.assertEqual(ac.find_command((str(self.cmd), str(good)), roots=(str(self.d),)), (None, ac.NOT_NATIVE),
                         "a refused command is never passed over for another one")
        self.assertEqual(ac.find_command((str(self.d / "none"), str(good)), roots=(str(self.d),)), (good, None))
        broken = self.d / "broken"
        broken.symlink_to(self.d / "gone")
        self.assertEqual(ac.find_command((str(broken), str(good)), roots=(str(self.d),)), (None, ac.NOT_NATIVE))

    def test_a_folder_further_up_that_others_can_change_is_refused_unless_it_is_sticky(self):
        up = self.d / "up"
        path = self.program(folder=up / "inner")
        self.assertEqual(self.found(path), (path, None))
        up.chmod(0o777)
        self.addCleanup(up.chmod, 0o755)
        self.assertEqual(self.found(path), (None, ac.NOT_NATIVE), "anyone could rename the folder and put another program there")
        up.chmod(0o1777)
        self.assertEqual(self.found(path), (path, None), "a sticky folder lets others add names, never move ours")
        up.chmod(0o775)
        self.assertEqual(self.found(path), (None, ac.NOT_NATIVE))

    def test_a_folder_further_up_owned_by_someone_else_is_refused(self):
        path = self.program(folder=self.d / "up2" / "inner")
        real_stat = os.stat
        other = self.d / "up2"

        def stat_as_someone_else(p, *a, **k):
            st = real_stat(p, *a, **k)
            if str(p) == str(other):
                return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, os.getuid() + 1, st.st_gid, st.st_size,
                                       st.st_atime, st.st_mtime, st.st_ctime))
            return st
        with mock.patch.object(ac.os, "stat", side_effect=stat_as_someone_else):
            self.assertEqual(self.found(path), (None, ac.NOT_NATIVE))

    def test_the_default_roots_are_the_home_folder_and_homebrews(self):
        roots = ac.roots_for()
        self.assertEqual(roots[0], str(Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()))
        self.assertEqual(roots[1:], tuple(str(Path(r).resolve()) for r in ("/opt/homebrew", "/usr/local")))


class SignIn(Fake):
    def auth(self, method, logged_in=True, code=0):
        self.put("auth", json.dumps({"loggedIn": logged_in, "authMethod": method}))
        self.put("authcode", str(code))

    def test_only_a_claude_sign_in_is_used(self):
        self.auth("claude.ai")
        self.assertEqual(self.provider.ask(self.request()), ANSWER)

    def test_an_api_key_login_sends_nothing_and_says_connect_claude_in_settings(self):
        for method in ("api_key", "api_key_helper"):
            self.auth(method)
            self.assertEqual(self.provider.usable(), (None, ac.API_KEY_LOGIN), method)
            self.assertFalse(self.provider.status()["connected"])
            self.assertEqual(self.provider.ask(self.request()), ask.Failure(ac.API_KEY_LOGIN), method)
        self.assertIsNone(self.seen(), "no question was sent")
        self.assertTrue(ac.API_KEY_LOGIN.endswith("Connect Claude in Settings to use this."))

    def test_a_token_another_provider_or_an_unknown_way_sends_nothing(self):
        for method in ("oauth_token", "third_party", "something_new", None):
            self.auth(method)
            self.assertEqual(self.provider.ask(self.request()), ask.Failure(ac.OTHER_LOGIN), method)
        self.assertIsNone(self.seen())

    def test_not_signed_in_sends_nothing(self):
        for logged_in, method, code in ((False, "none", 1), (True, "none", 0), (False, "claude.ai", 0), (True, "claude.ai", 1)):
            self.auth(method, logged_in, code)
            self.assertEqual(self.provider.ask(self.request()), ask.Failure(ac.NOT_SIGNED_IN), (logged_in, method, code))
        self.assertIsNone(self.seen())

    def test_an_answer_that_cannot_be_read_sends_nothing(self):
        for text in ("Logged in as someone", "", "[1, 2]", "\"claude.ai\"", "[" * 100000,
                     "{\"loggedIn\": true, \"authMethod\": \"claude.ai\"} x"):
            self.put("auth", text)
            self.assertEqual(self.provider.ask(self.request()), ask.Failure(ac.CANT_USE), text[:30])
        self.assertIsNone(self.seen())

    def test_one_sign_in_check_for_each_question(self):
        self.assertEqual(ask.ask_provider(self.provider, self.request(), codes=("ABC",)).answer, "The plan is on track.")
        auth = [c for c in self.calls() if c["args"][-2:] == ["auth", "status"]]
        self.assertEqual(len(auth), 1, "status() before the question and the question itself share one check")
        self.assertEqual(self.provider.ask(self.request()), ANSWER)
        auth = [c for c in self.calls() if c["args"][-2:] == ["auth", "status"]]
        self.assertEqual(len(auth), 2, "a check is used once: the next question asks again")

    def test_a_status_check_older_than_the_reuse_window_is_asked_again(self):
        self.provider.status()
        with mock.patch.object(ac, "LOGIN_REUSE", 0.0):
            self.assertEqual(self.provider.ask(self.request()), ANSWER)
        self.assertEqual(len([c for c in self.calls() if c["args"][-2:] == ["auth", "status"]]), 2)

    def test_the_sign_in_is_asked_before_every_question(self):
        self.assertEqual(self.provider.ask(self.request()), ANSWER)
        (self.bin / "seen.json").unlink()
        self.auth("api_key")
        self.assertEqual(self.provider.ask(self.request()), ask.Failure(ac.API_KEY_LOGIN), "a change of sign-in is seen at once")
        self.assertIsNone(self.seen())


class Hints(Fake):
    CLEAN = {k: v for k, v in os.environ.items() if k not in ac.PROXY_NAMES + ac.KEY_NAMES + ("CLAUDE_CONFIG_DIR",)}

    def status_with(self, environ):
        with mock.patch.dict(os.environ, {**self.CLEAN, **environ}, clear=True):
            return self.provider.status()

    def test_no_hint_on_an_ordinary_computer(self):
        self.assertEqual(self.status_with({}), {"connected": True, "why": ac.READY})

    def test_a_proxy_or_its_own_certificates_get_a_plain_hint_in_the_status_and_in_a_failure(self):
        for name in ("HTTPS_PROXY", "http_proxy", "ALL_PROXY", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE"):
            st = self.status_with({name: "/somewhere"})
            self.assertTrue(st["connected"], name)
            self.assertEqual(st["why"], ac.READY + " " + ac.PROXY_HINT, name)
        self.mode("fail")
        with mock.patch.dict(os.environ, {**self.CLEAN, "HTTPS_PROXY": "http://proxy.example.test"}, clear=True):
            self.assertEqual(self.provider.ask(self.request()), ask.Failure(ac.NO_ANSWER + " " + ac.PROXY_HINT))

    def test_a_custom_config_folder_gets_a_plain_hint(self):
        self.assertEqual(self.status_with({"CLAUDE_CONFIG_DIR": "/Users/tester/.claude-work"})["why"], ac.READY + " " + ac.CONFIG_HINT)

    def test_an_api_key_in_clarks_environment_gets_the_connect_hint(self):
        st = self.status_with({"ANTHROPIC_API_KEY": "sk-ant-canary"})
        self.assertEqual(st["why"], ac.READY + " " + ac.KEY_HINT)
        self.assertTrue(ac.KEY_HINT.endswith("Connect Claude in Settings to use this."))
        self.assertNotIn("sk-ant-canary", st["why"])

    def test_no_sentence_starts_with_the_product_name(self):
        for name in ("MAC_ONLY", "NOT_INSTALLED", "NOT_NATIVE", "CANT_USE", "NOT_SIGNED_IN", "API_KEY_LOGIN", "OTHER_LOGIN", "READY",
                     "NO_ANSWER", "TOO_SLOW", "TOO_LONG_REPLY", "BUSY", "PROXY_HINT", "CONFIG_HINT", "KEY_HINT"):
            self.assertFalse(getattr(ac, name).lower().startswith(("clark", "ask clark")), name)

    def test_any_other_system_gets_one_fixed_sentence_and_nothing_starts(self):
        for other in ("linux", "win32", "freebsd"):
            with mock.patch.object(platform, "system", return_value=other):
                self.assertEqual(self.provider.ask(self.request()), ask.Failure(ac.MAC_ONLY))
                self.assertEqual(self.status_with({}), {"connected": False, "why": ac.MAC_ONLY})
        self.assertEqual(self.calls(), [], "the command was not started")
        self.assertEqual(ac.MAC_ONLY, "Questions work on a Mac for now. Everything else in the report works as before, and a later "
                                      "version will cover this computer.")


class Replies(Fake):
    """What comes back is untrusted: only one successful result object holding text is an answer."""

    def reply(self, text):
        self.put("reply", text)
        return self.provider.ask(self.request())

    def test_anything_but_one_successful_result_object_is_no_answer(self):
        bad = ["The plan is on track.", "", "null", "[1]", json.dumps({"result": "x"}),
               json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": "x"}),
               json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": False, "result": "x"}),
               json.dumps({"type": "result", "subtype": "success", "is_error": 0, "result": "x"}),
               json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": ["x"]}),
               json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "   "}),
               result("x") + "\n" + result("y"), "[" * 200000]
        with mock.patch.object(ac, "hints", return_value=[]):
            for text in bad:
                self.assertEqual(self.reply(text), ask.Failure(ac.NO_ANSWER), text[:40])

    def test_bytes_that_are_not_utf8_are_no_answer(self):
        self.mode("raw")
        self.put("raw", (b'{"type": "result", "subtype": "success", "is_error": false, "result": "\xff\xfe"}').hex())
        with mock.patch.object(ac, "hints", return_value=[]):
            self.assertEqual(self.provider.ask(self.request()), ask.Failure(ac.NO_ANSWER))

    def test_odd_but_valid_text_comes_back_as_text_for_the_reply_reader(self):
        text = "line one\x00 NUL ‮ reversed \U0001F600"
        self.assertEqual(self.reply(result(text, total_cost_usd=0.01, extra={"a": 1})), text)

    def test_a_failing_command_gives_a_fixed_sentence_and_none_of_its_output_or_error_text(self):
        self.mode("fail")
        with mock.patch.object(ac, "hints", return_value=[]):
            got = self.provider.ask(self.request())
            self.assertEqual(got, ask.Failure(ac.NO_ANSWER))
            self.assertNotIn("secret", got.message)
            self.assertNotIn("half an answer", got.message)
            self.mode("empty")
            self.assertEqual(self.provider.ask(self.request()), ask.Failure(ac.NO_ANSWER))

    def test_the_reply_goes_through_the_reply_reader_and_claims_check(self):
        self.put("reply", result("ABC-A-001 is late. ABC-A-999 is done.\nCITE: P1 P7"))
        got = ask.ask_provider(self.provider, self.request(), codes=("ABC",), exists=lambda ref: ref == "ABC-A-001")
        self.assertIsInstance(got, ask.Reply)
        self.assertTrue(got.flags, "the made-up ID and the source that was not sent are flagged")
        self.assertNotIn("CITE", got.answer)
        self.assertEqual(got.cites, ("P1", "P7"))

    def test_a_reply_over_the_cap_is_stopped(self):
        self.mode("flood")
        provider = self.make(limit=20, max_out=100000)
        began = time.monotonic()
        self.assertEqual(provider.ask(self.request()), ask.Failure(ac.TOO_LONG_REPLY))
        self.assertLess(time.monotonic() - began, 10)


class Limits(Fake):
    def test_a_helper_that_leaves_the_group_and_holds_standard_input_cannot_hold_the_run_up(self):
        self.mode("escape")
        provider = self.make(limit=2)
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("got", provider.ask(ask.Request(text="x" * 3_000_000, question="q"))),
                             daemon=True)
        t.start()
        t.join(20)
        pid_file = self.bin / "escaped.pid"
        if pid_file.exists():
            pid = int(pid_file.read_text(encoding="utf-8"))
            self.addCleanup(lambda: os.kill(pid, 9) if alive(pid) else None)
        self.assertFalse(t.is_alive(), "the run came back although a helper still holds standard input")
        self.assertIsInstance(out["got"], ask.Failure)

    def test_too_slow_is_stopped_with_its_whole_group(self):
        self.mode("slow")
        provider = self.make(limit=1.5)
        began = time.monotonic()
        self.assertEqual(provider.ask(self.request()), ask.Failure(ac.TOO_SLOW))
        self.assertLess(time.monotonic() - began, 10)
        self.assertFalse(alive(self.seen()["pid"]))

    def test_a_helper_in_its_group_is_ended_too(self):
        self.mode("helper")
        provider = self.make(limit=2)
        self.assertEqual(provider.ask(self.request()), ask.Failure(ac.TOO_SLOW))
        helper = int((self.bin / "helper.pid").read_text(encoding="utf-8"))
        deadline = time.monotonic() + 5
        while alive(helper) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertFalse(alive(helper), "the command's helper went with it")

    def test_stop_ends_the_answer_and_its_group(self):
        self.mode("slow")
        provider = self.make(limit=30)
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("got", provider.ask(self.request())))
        t.start()
        deadline = time.monotonic() + 10
        while self.seen() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(provider.stop())
        t.join(10)
        self.assertEqual(out["got"], ask.Failure(ask.STOPPED))
        self.assertFalse(alive(self.seen()["pid"]))
        self.assertFalse(provider.stop(), "nothing left to stop")

    def test_one_question_at_a_time(self):
        self.mode("slow")
        provider = self.make(limit=30)
        t = threading.Thread(target=lambda: provider.ask(self.request()))
        t.start()
        deadline = time.monotonic() + 10
        while self.seen() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(provider.ask(self.request()), ask.Failure(ac.BUSY))
        provider.stop()
        t.join(10)


class Source(unittest.TestCase):
    TEXT = Path(ac.__file__).read_text(encoding="utf-8")
    RUN = Path(platform.__file__).read_text(encoding="utf-8").split("def run_stoppable")[1]

    def test_never_a_shell_and_never_bare(self):
        self.assertNotIn("shell=True", self.TEXT)
        self.assertNotIn("os.system", self.TEXT)
        self.assertNotIn("subprocess", self.TEXT)
        self.assertNotIn("\"--bare\"", self.TEXT.split("NEVER_FLAGS")[0])
        self.assertNotIn("shell=True", self.RUN)
        self.assertIn("shell=False", self.RUN)


if __name__ == "__main__":
    unittest.main()
