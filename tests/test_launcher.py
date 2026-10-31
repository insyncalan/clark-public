"""#71: the launcher (src/clark/launch.py, clark.command) and the system calls it makes (platform.py).

Run: python3 dev/run_tests.py test_launcher
Nothing real is started or opened. The port check talks to fake servers on 127.0.0.1 (clark with this data folder, clark with
another, creaite's plain {"ok": true}, a page of HTML, a 403, one that never answers, and no server at all). The rest of the
launcher runs with fakes for starting clark and opening a window. The data folder is always a temporary one; the real home
folder, its clark data and any real Chrome are never touched. clark.command runs against a fake python3 on a PATH of its own.
"""
import http.server
import json
import os
import socket
import stat
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from _paths import ROOT, SRC

from clark import appfiles, launch, platform as pl

BASH = "/bin/bash"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Fake:
    """A fake server on a free port, for one test. `mode` says what /health answers: ours (the same data folder as the mark the
    test gives), other (clark, another folder), creaite ({"ok": true}), html, forbidden, silent (accepts, never answers), big,
    notjson. `seen` holds each request's path, Host and mark header."""

    def __init__(self, mode, mark=None, port=0):
        fake = self
        self.seen, self.mode, self.mark, self.release = [], mode, mark, threading.Event()

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                fake.seen.append((self.path, self.headers.get("Host"), self.headers.get(appfiles.MARK_HEADER)))
                m = fake.mode
                if m == "silent":
                    fake.release.wait(5)
                    return
                body, code = {
                    "ours": (appfiles.health_answer(self.headers.get(appfiles.MARK_HEADER), fake.mark), 200),
                    "other": (appfiles.health_answer(self.headers.get(appfiles.MARK_HEADER), "another folder's mark"), 200),
                    "creaite": ({"ok": True}, 200),
                    "html": (b"<html>hello</html>", 200),
                    "forbidden": ({"ok": False}, 403),
                    "notjson": (b"ok", 200),
                    "big": (b'{"ok": true, "this_data": true, "x": "' + b"a" * 9000 + b'"}', 200),
                    "stringly": ({"ok": True, "this_data": "yes"}, 200),
                    "notok": ({"ok": False, "this_data": True}, 200),
                }[m]
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_port
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def close(self):
        self.release.set()
        self.httpd.shutdown()
        self.httpd.server_close()


class PortCheck(unittest.TestCase):
    """The Done-when's "port check (a fake server on the port)"."""

    MARK = "0123456789abcdef"

    def fake(self, mode):
        f = Fake(mode, self.MARK)
        self.addCleanup(f.close)
        return f

    def check(self, mode, **kw):
        return launch.ask_health(self.fake(mode).port, self.MARK, **kw)

    def test_nothing_on_the_port(self):
        self.assertEqual(launch.ask_health(free_port(), self.MARK), launch.NOTHING)

    def test_clark_with_this_data_folder_is_ours(self):
        f = self.fake("ours")
        self.assertEqual(launch.ask_health(f.port, self.MARK), launch.OURS)
        self.assertEqual(f.seen, [("/health", f"127.0.0.1:{f.port}", self.MARK)], "one request, to /health, with the mark")

    def test_clark_with_another_data_folder_is_not_taken_over(self):
        self.assertEqual(self.check("other"), launch.OTHER_DATA)

    def test_anything_that_answers_without_the_mark_is_not_clark(self):
        """creaite answers {"ok": true} to /health: without this_data it is not ours."""
        for mode in ("creaite", "html", "forbidden", "notjson", "stringly", "notok"):
            self.assertEqual(self.check(mode), launch.NOT_CLARK, mode)

    def test_an_answer_that_is_too_big_is_not_clark(self):
        self.assertEqual(self.check("big"), launch.NOT_CLARK)

    def test_a_program_that_holds_the_port_and_never_answers_is_not_clark_and_does_not_hang_the_launcher(self):
        self.assertEqual(self.check("silent", timeout=0.3), launch.NOT_CLARK)

    def test_something_that_is_not_a_web_server_is_not_clark(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)

            def say_nonsense():
                conn, _ = s.accept()
                conn.sendall(b"\x00\x01 not http at all\r\n\r\n")
                conn.close()
            threading.Thread(target=say_nonsense, daemon=True).start()
            self.assertEqual(launch.ask_health(s.getsockname()[1], self.MARK, timeout=2), launch.NOT_CLARK)


class Fakes:
    """What launch() does with the system, recorded."""

    def __init__(self, healths, chrome="/stub/browser", fail_start=None, process_exits=False):
        self.healths, self.chrome, self.fail_start, self.process_exits = list(healths), chrome, fail_start, process_exits
        self.started, self.windows, self.browser, self.said, self.asked = [], [], [], [], []

    def health(self, port, mark):
        self.asked.append((port, mark))
        return self.healths.pop(0) if len(self.healths) > 1 else self.healths[0]

    def start(self, argv, env, log, cwd=None):
        if self.fail_start:
            raise pl.PlatformError(self.fail_start)
        self.started.append((argv, env, log, cwd))
        return type("Process", (), {"poll": lambda s: 1 if self.process_exits else None})()

    def wait(self, port, mark, process, health=None):
        return launch.wait_for_clark(port, mark, process, seconds=0.0, health=health, sleep=lambda s: None)

    def kw(self):
        return dict(say=self.said.append, environ={"HOME": "/nowhere", "PATH": "/bin"}, start=self.start, health=self.health,
                    wait=self.wait, find_chrome=lambda env: self.chrome, open_window=lambda u, c: self.windows.append((u, c)),
                    open_browser=self.browser.append, free=lambda p: p == 8801)


def as_the_mac(case):
    """#100: these tests are about the launcher, not the system; the Mac-only folder and OneDrive lookups raise NotBuiltYet on
    another system, so they run as the Mac does (platform.system patched for the test)."""
    patch = mock.patch.object(pl, "system", return_value=pl.MAC)
    patch.start()
    case.addCleanup(patch.stop)


class Launch(unittest.TestCase):
    def setUp(self):
        as_the_mac(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "clark-data"
        self.folder.mkdir()

    def run_launch(self, fakes, port=8800):
        return launch.launch(port, self.folder, **fakes.kw())

    def test_nothing_there_starts_clark_marked_launched_waits_and_opens_its_window(self):
        f = Fakes([launch.NOTHING, launch.OURS])
        self.assertEqual(self.run_launch(f), 0)
        (argv, env, log, cwd), = f.started
        self.assertEqual(argv[1:], ["-m", "clark", "--data", str(self.folder), "--port", "8800"])
        self.assertEqual((env["CLARK_LAUNCHED"], env["CLARK_PORT"], env["PYTHONPATH"]), ("1", "8800", str(SRC)))
        self.assertEqual(env["HOME"], "/nowhere", "the rest of the environment is passed on")
        self.assertEqual((log, cwd), (self.folder / "server.log", str(self.folder)))
        self.assertEqual(f.windows, [("http://127.0.0.1:8800/", "/stub/browser")])
        self.assertEqual(f.browser, [])
        self.assertEqual(f.said, ["Starting clark...", "A minute after the last window closes, clark stops by itself.",
                                  "Opened clark in its own window."])

    def test_it_asks_with_this_data_folders_mark(self):
        f = Fakes([launch.OURS])
        self.run_launch(f)
        self.assertEqual(f.asked, [(8800, appfiles.data_mark(self.folder))])

    def test_ours_already_running_starts_nothing_and_only_opens_the_window(self):
        f = Fakes([launch.OURS])
        self.assertEqual(self.run_launch(f), 0)
        self.assertEqual(f.started, [])
        self.assertEqual(f.said[0], "It is already running. Opening its window.")
        self.assertEqual(len(f.windows), 1)

    def test_another_clarks_data_folder_is_reported_and_nothing_starts_or_opens(self):
        f = Fakes([launch.OTHER_DATA])
        self.assertEqual(self.run_launch(f), 1)
        self.assertEqual((f.started, f.windows, f.browser), ([], [], []))
        self.assertEqual(f.said, [f"Another copy of clark is already open with different data (this one uses {self.folder}). "
                                  "Close that copy, then start clark again.\n"
                                  "If you can't close it, open Terminal in the clark folder and type: ./clark.command --port 8801"])

    def test_another_program_is_reported_the_same_way(self):
        f = Fakes([launch.NOT_CLARK])
        self.assertEqual(self.run_launch(f), 1)
        self.assertEqual((f.started, f.windows, f.browser), ([], [], []))
        self.assertEqual(f.said, ["Nothing was started: clark is already open in another Terminal window, or another program is using the connection it needs. Close that Terminal window or program, then double-click clark.command again. If that does not help, restart your Mac.\nIf you can't close it, open Terminal in the clark folder and type: "
                                  "./clark.command --port 8801"])

    def test_a_port_with_no_easy_free_port_near_it_still_gives_a_way_out(self):
        text = launch.report(launch.NOT_CLARK, 8800, self.folder, free=lambda p: False)
        self.assertEqual(text, "Nothing was started: clark is already open in another Terminal window, or another program is using the connection it needs. Close that Terminal window or program, then double-click clark.command again. If that does not help, restart your Mac.")
        text = launch.report(launch.NOT_CLARK, 8800, self.folder, free=lambda p: p == 8801)
        self.assertEqual(text, "Nothing was started: clark is already open in another Terminal window, or another program is using the connection it needs. Close that Terminal window or program, then double-click clark.command again. If that does not help, restart your Mac.\n"
                               "If you can't close it, open Terminal in the clark folder and type: ./clark.command --port 8801")
        self.assertNotIn("port 8800", text.lower().replace("--port", ""))

    def test_a_clark_that_does_not_start_never_shows_raw_log_text_and_says_what_to_do(self):
        (self.folder / "server.log").write_text("Using the data in x\nclark can't read the data in clark.db. Start clark with "
                                                "--data to use another folder.\n", encoding="utf-8")
        f = Fakes([launch.NOTHING], process_exits=True)
        self.assertEqual(self.run_launch(f), 1)
        self.assertEqual(f.windows, [])
        self.assertEqual(f.said[-1], "It didn't start. Close this window and try again. If it still doesn't start, send the file "
                                     f"{self.folder / 'server.log'} to the clark team.")
        self.assertNotIn("clark.db", f.said[-1])

    def test_a_clark_that_does_not_start_and_leaves_no_log_still_says_where_to_look(self):
        f = Fakes([launch.NOTHING])
        self.assertEqual(self.run_launch(f), 1)
        self.assertEqual(f.said[-1], "It didn't start. Close this window and try again. If it still doesn't start, send the file "
                                     f"{self.folder / 'server.log'} to the clark team.")

    def test_someone_else_taking_the_port_while_it_starts_is_reported_not_opened(self):
        f = Fakes([launch.NOTHING, launch.NOT_CLARK])
        self.assertEqual(self.run_launch(f), 1)
        self.assertEqual(f.windows, [])
        self.assertIn("is using the connection it needs", f.said[-1])

    def test_a_start_the_system_refuses_is_said_in_the_systems_plain_words(self):
        f = Fakes([launch.NOTHING], fail_start="The app could not start. Try again; if it keeps happening, send the file ~/x to the clark team.")
        self.assertEqual(self.run_launch(f), 1)
        self.assertEqual(f.said[-1], "The app could not start. Try again; if it keeps happening, send the file ~/x to the clark team.")

    def test_no_chrome_opens_the_default_browser_and_says_so(self):
        f = Fakes([launch.OURS], chrome=None)
        self.assertEqual(self.run_launch(f), 0)
        self.assertEqual((f.windows, f.browser), ([], ["http://127.0.0.1:8800/"]))
        self.assertEqual(f.said[-1], "Chrome wasn't found, so clark opened in your default browser. "
                                     "Install Chrome to give clark its own window.")

    def test_a_window_the_system_cannot_open_says_the_address(self):
        f = Fakes([launch.OURS])
        kw = f.kw()
        kw["open_window"] = lambda u, c: (_ for _ in ()).throw(pl.PlatformError("The window could not be opened."))
        self.assertEqual(launch.launch(8800, self.folder, **kw), 1)
        self.assertEqual(f.said[-1], "The window could not be opened. Open this address in your browser: http://127.0.0.1:8800/")

    def test_the_address_is_always_127_0_0_1(self):
        self.assertEqual(launch.address(8766), "http://127.0.0.1:8766/")


class Wait(unittest.TestCase):
    class Clock:
        def __init__(self):
            self.now = 0.0

        def __call__(self):
            return self.now

        def sleep(self, s):
            self.now += s

    def run_wait(self, answers, exits_at=None, seconds=15.0):
        clock, calls = self.Clock(), []
        proc = type("P", (), {"poll": lambda s: 1 if exits_at is not None and clock.now >= exits_at else None})()

        def health(port, mark):
            calls.append(clock.now)
            return answers(clock.now)
        return launch.wait_for_clark(1, "m", proc, seconds, health, clock.sleep, clock), calls

    def test_it_waits_until_clark_answers(self):
        seen, calls = self.run_wait(lambda t: launch.OURS if t >= 2 else launch.NOTHING)
        self.assertEqual(seen, launch.OURS)
        self.assertAlmostEqual(calls[-1], 2.0, delta=0.15)

    def test_it_gives_up_after_the_time_and_says_nothing_answered(self):
        seen, calls = self.run_wait(lambda t: launch.NOTHING, seconds=3)
        self.assertEqual(seen, launch.NOTHING)
        self.assertGreaterEqual(calls[-1], 3)

    def test_a_process_that_has_gone_is_not_waited_for_and_a_second_launch_that_won_the_port_counts(self):
        seen, calls = self.run_wait(lambda t: launch.OURS if t >= 1 else launch.NOTHING, exits_at=1)
        self.assertEqual(seen, launch.OURS)
        seen, calls = self.run_wait(lambda t: launch.NOTHING, exits_at=1)
        self.assertEqual(seen, launch.NOTHING)
        self.assertLess(calls[-1], 2, "it did not wait the whole time")

    def test_someone_taking_the_port_ends_the_wait_at_once(self):
        seen, calls = self.run_wait(lambda t: launch.NOT_CLARK)
        self.assertEqual((seen, calls), (launch.NOT_CLARK, [0.0]))


class AgainstAFakeServer(unittest.TestCase):
    """launch() with the real port check and a fake "start" that brings up a fake server on the port, as clark would."""

    def test_start_then_the_real_check_sees_our_clark_and_a_second_launch_only_opens_a_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, port = Path(tmp), free_port()
            mark = appfiles.data_mark(folder)

            def start(argv, env, log, cwd=None):
                self.addCleanup(Fake("ours", mark, port).close)
                return type("P", (), {"poll": lambda s: None})()

            said, windows, started = [], [], []
            kw = dict(say=said.append, environ={}, start=start, find_chrome=lambda env: "/stub", free=lambda p: False,
                      open_window=lambda u, c: windows.append(u), open_browser=lambda u: windows.append("browser"))
            self.assertEqual(launch.launch(port, folder, **kw), 0)
            self.assertEqual(windows, [f"http://127.0.0.1:{port}/"])
            kw["start"] = lambda *a, **k: started.append(a)
            self.assertEqual(launch.launch(port, folder, **kw), 0, "the second launch finds our clark")
            self.assertEqual((started, len(windows)), ([], 2))
            self.assertEqual(said[-2], "It is already running. Opening its window.")

    def test_a_clark_with_another_data_folder_on_the_port_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = Fake("ours", appfiles.data_mark(Path(tmp) / "elsewhere"))
            self.addCleanup(other.close)
            said, started, windows = [], [], []
            code = launch.launch(other.port, Path(tmp), say=said.append, environ={}, start=lambda *a, **k: started.append(a),
                                 open_window=lambda u, c: windows.append(u), find_chrome=lambda env: "/stub", free=lambda p: False)
            self.assertEqual((code, started, windows), (1, [], []))
            self.assertIn("already open with different data", said[0])


class Main(unittest.TestCase):
    def setUp(self):
        as_the_mac(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.said = []

    def main(self, argv, environ=None, **seams):
        f = Fakes([launch.OURS])
        kw = f.kw()
        kw.update(seams)
        for k in ("say", "environ", "free"):
            kw.pop(k)
        self.fakes = f
        return launch.main(argv, say=self.said.append, environ=environ or {}, home=self.home, onedrive_roots=[], **kw)

    def test_the_default_data_folder_is_clarks_own_one_in_the_home_folder_and_is_made(self):
        self.assertEqual(self.main([]), 0)
        folder = self.home / "Library" / "Application Support" / "clark"
        self.assertTrue(folder.is_dir())
        self.assertEqual(self.fakes.asked, [(8766, appfiles.data_mark(folder))])

    def test_the_port_comes_from_the_option_then_the_setting_then_8766(self):
        self.main(["--port", "8811"], {"CLARK_PORT": "8812"})
        self.main([], {"CLARK_PORT": "8812"})
        self.assertEqual([p for p, _ in self.fakes.asked], [8812])
        self.main(["--data", str(self.home / "d"), "--port", "8811"], {"CLARK_PORT": "8812"})
        self.assertEqual([p for p, _ in self.fakes.asked], [8811])

    def test_a_port_that_is_not_a_number_is_one_plain_line_and_exit_2(self):
        self.assertEqual(self.main(["--port", "abc"]), 2)
        self.assertEqual(self.said, ["The port setting (--port) must be a whole number from 1 to 65535."])
        self.said.clear()
        self.assertEqual(self.main([], {"CLARK_PORT": "70000"}), 2)
        self.assertEqual(self.said, ["The port setting (CLARK_PORT) must be a whole number from 1 to 65535."])

    def test_a_data_folder_inside_onedrive_is_refused_before_anything_starts(self):
        root = self.home / "OneDrive-Fictional"
        root.mkdir()
        f = Fakes([launch.NOTHING])
        kw = f.kw()
        for k in ("say", "environ", "free"):
            kw.pop(k)
        code = launch.main(["--data", str(root / "clark")], say=self.said.append, environ={}, home=self.home,
                           onedrive_roots=[root], **kw)
        self.assertEqual(code, 1)
        self.assertIn("is inside OneDrive", self.said[0])
        self.assertEqual((f.started, f.asked, (root / "clark").exists()), ([], [], False))

    def test_a_data_folder_that_cannot_be_made_says_so_plainly(self):
        blocker = self.home / "file"
        blocker.write_text("x", encoding="utf-8")
        self.assertEqual(self.main(["--data", str(blocker / "inside")]), 1)
        self.assertRegex(self.said[0], r"^The data folder can't be made \(.+\)\. Check you can save files there, then try again\.$")


class Command(unittest.TestCase):
    """clark.command: what a double-click runs, with a fake python3 on a PATH of its own."""

    SCRIPT = ROOT / "clark.command"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        self.out = Path(self.tmp.name) / "ran.txt"

    def python3(self, version_ok=True, status=0):
        py = self.bin / "python3"
        py.write_text(f'#!/bin/sh\nif [ "$1" = "-c" ]; then exit {0 if version_ok else 1}; fi\n'
                      f'{{ pwd; echo "$@"; }} > "{self.out}"\nexit {status}\n', encoding="utf-8")
        py.chmod(0o755)

    def run_script(self, *args, cwd=None):
        return subprocess.run([BASH, str(self.SCRIPT), *args], cwd=cwd or self.tmp.name, env={"PATH": str(self.bin), "HOME": self.tmp.name},
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)

    def test_it_is_a_file_a_double_click_can_run(self):
        self.assertTrue(self.SCRIPT.stat().st_mode & stat.S_IXUSR, "clark.command is not executable")
        self.assertTrue(self.SCRIPT.read_text(encoding="utf-8").startswith("#!/bin/bash\n"))
        self.assertEqual(subprocess.run([BASH, "-n", str(self.SCRIPT)], capture_output=True).returncode, 0)

    def test_it_runs_the_launcher_from_its_own_folder_and_passes_the_options_on(self):
        self.python3()
        done = self.run_script("--port", "8801", cwd=self.tmp.name)       # started from somewhere else, as a double-click is
        self.assertEqual(done.returncode, 0, done.stderr)
        pwd, args = self.out.read_text(encoding="utf-8").splitlines()
        self.assertEqual(Path(pwd).resolve(), ROOT.resolve())
        self.assertEqual(args, "-m clark.launch --port 8801")

    def test_the_launchers_exit_code_is_kept_and_nothing_is_said_when_it_went_well(self):
        self.python3(status=3)
        done = self.run_script()
        self.assertEqual(done.returncode, 3)
        self.python3(status=0)
        self.assertEqual((self.run_script().stdout, self.run_script().stderr), ("", ""))

    def test_without_python_it_says_what_to_do_in_plain_words_and_runs_nothing(self):
        done = self.run_script()          # no python3 on the PATH at all
        self.assertEqual(done.returncode, 1)
        self.assertFalse(self.out.exists())
        self.assertIn("This Mac needs Python 3.9 or newer to run clark, and doesn't have it yet.", done.stdout)
        self.assertIn("Otherwise type this in this window: xcode-select --install", done.stdout)
        self.assertNotIn("open Terminal", done.stdout)
        self.assertIn("double-click clark.command again", done.stdout)

    def test_a_python_that_is_too_old_or_only_a_stub_gets_the_same_words(self):
        self.python3(version_ok=False)
        done = self.run_script()
        self.assertEqual(done.returncode, 1)
        self.assertFalse(self.out.exists())
        self.assertIn("xcode-select --install", done.stdout)

    def test_it_installs_and_downloads_nothing(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        for word in ("curl", "wget", "pip", "brew", "sudo", "http"):
            self.assertNotIn(word, text)


class RunsFromTheTopFolder(unittest.TestCase):
    """The real python3, with no PYTHONPATH, as a download is run: the root clark/ stand-in must reach src/clark/launch.py.
    Only --help and a mistake in the options are used, so nothing is started and no data folder is touched."""

    def env(self, tmp):
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "CLARK_PORT")}
        env.update(HOME=tmp, PYTHONDONTWRITEBYTECODE="1")
        return env

    def test_python_m_clark_launch_finds_the_launcher_from_the_top_folder(self):
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            done = subprocess.run([sys.executable, "-m", "clark.launch", "--help"], cwd=str(ROOT), env=self.env(tmp), capture_output=True,
                                  text=True, encoding="utf-8", timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("Start clark if it isn't running, and open its window.", done.stdout)
            self.assertEqual(os.listdir(tmp), [], "nothing was made in the home folder")

    def test_clark_command_runs_it_and_a_mistake_in_the_options_is_one_plain_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = subprocess.run([BASH, str(ROOT / "clark.command"), "--port", "abc"], cwd=tmp, env=self.env(tmp), stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(done.returncode, 2, done.stderr)
            self.assertIn("The port setting (--port) must be a whole number from 1 to 65535.", done.stdout)
            self.assertEqual(os.listdir(tmp), [], "no data folder was made")


class PlatformCalls(unittest.TestCase):
    """platform.py's launcher functions, with fakes for the system."""

    def test_the_launcher_file_name(self):
        self.assertEqual(pl.launcher_name(on=pl.MAC), "clark.command")

    def test_find_chrome_prefers_the_named_browser_then_the_app_in_applications_then_the_one_in_the_home_folder(self):
        have = lambda *found: (lambda p: p in found)
        home = "/Users/fictional"
        mine = home + "/Applications/" + pl.CHROME_MAC.split("/Applications/", 1)[1]
        self.assertEqual(pl.find_chrome({"CLARK_BROWSER": "/stub/b"}, home, have("/stub/b", pl.CHROME_MAC), pl.MAC), "/stub/b")
        self.assertIsNone(pl.find_chrome({"CLARK_BROWSER": "/stub/b"}, home, have(pl.CHROME_MAC), pl.MAC),
                          "a named browser that isn't there: the default browser is used, not Chrome")
        self.assertEqual(pl.find_chrome({}, home, have(pl.CHROME_MAC, mine), pl.MAC), pl.CHROME_MAC)
        self.assertEqual(pl.find_chrome({}, home, have(mine), pl.MAC), mine)
        self.assertIsNone(pl.find_chrome({}, home, have(), pl.MAC))

    def test_start_detached_uses_an_argument_list_a_session_of_its_own_and_the_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, calls = Path(tmp) / "server.log", []
            log.write_bytes(b"earlier\n")

            def popen(argv, **kw):
                calls.append((argv, kw))
                return "process"
            got = pl.start_detached(("a", "b"), {"X": "1"}, log, cwd=tmp, popen=popen, on=pl.MAC)
            self.assertEqual(got, "process")
            (argv, kw), = calls
            self.assertEqual((argv, kw["cwd"], kw["env"], kw["start_new_session"], kw["stdin"]), (["a", "b"], tmp, {"X": "1"}, True, subprocess.DEVNULL))
            self.assertIsNot(kw.get("shell"), True)
            self.assertEqual(kw["stdout"].name, str(log))
            self.assertTrue(kw["stdout"].closed, "this program does not keep the log open")
            self.assertEqual(log.read_bytes(), b"earlier\n", "added to, not replaced")

    def test_a_log_that_has_grown_too_big_is_started_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "server.log"
            log.write_bytes(b"x" * 50)
            original = pl.LOG_LIMIT
            pl.LOG_LIMIT = 10
            self.addCleanup(setattr, pl, "LOG_LIMIT", original)
            pl.start_detached(["a"], {}, log, popen=lambda argv, **kw: None, on=pl.MAC)
            self.assertEqual(log.read_bytes(), b"")

    def test_a_program_that_cannot_start_is_a_plain_error_naming_the_log(self):
        def popen(argv, **kw):
            raise FileNotFoundError(2, "No such file or directory")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(pl.PlatformError, r"^The app could not start\. Try again; if it keeps happening, send the file .*server\.log to the clark team\.$"):
                pl.start_detached(["a"], {}, Path(tmp) / "server.log", popen=popen, on=pl.MAC)

    def test_the_app_window_is_chrome_with_app_equals_the_address(self):
        calls = []
        pl.open_app_window("http://127.0.0.1:8766/", "/stub/browser", popen=lambda a, **kw: calls.append((a, kw)), on=pl.MAC)
        (argv, kw), = calls
        self.assertEqual(argv, ["/stub/browser", "--app=http://127.0.0.1:8766/"])
        self.assertTrue(kw["start_new_session"])
        self.assertIsNot(kw.get("shell"), True)

    def test_only_a_web_address_is_opened_and_a_failure_is_plain(self):
        for bad in ("file:///etc/passwd", "--user-data-dir=/x", "javascript:1", "http://a b"):
            with self.assertRaisesRegex(pl.PlatformError, "Only web addresses"):
                pl.open_app_window(bad, "/stub", popen=lambda *a, **k: None, on=pl.MAC)

        def popen(argv, **kw):
            raise PermissionError(13, "Permission denied")
        with self.assertRaisesRegex(pl.PlatformError, r"^The window could not be opened\.$"):
            pl.open_app_window("http://127.0.0.1:1/", "/stub", popen=popen, on=pl.MAC)

    def test_every_windows_branch_is_not_built_yet(self):
        calls = (lambda: pl.launcher_name(on=pl.WINDOWS), lambda: pl.find_chrome({}, on=pl.WINDOWS),
                 lambda: pl.start_detached(["a"], {}, "x.log", popen=lambda *a, **k: None, on=pl.WINDOWS),
                 lambda: pl.open_app_window("http://127.0.0.1:1/", "c", popen=lambda *a, **k: None, on=pl.WINDOWS))
        for call in calls:
            with self.assertRaisesRegex(pl.NotBuiltYet, "on Windows is not built yet"):
                call()


if __name__ == "__main__":
    unittest.main()
