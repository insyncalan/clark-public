"""#90: python3 -m clark, the plain launcher (src/clark/__main__.py).

Run: python3 tests/test_main.py
The process tests start the real command with subprocess (tests may start programs) on a free port, with fictional demo
data, and stop it with SIGINT. The in-process tests give main() a fake `serve` and a fake `open_url`, so no server starts
and no browser opens. Every folder is a temporary one; HOME is pointed at one, so the real home and OneDrive are never read.
"""
import http.client
import io
import json
import os
import pathlib
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from clark import __main__ as launcher  # noqa: E402
from clark import platform as pl  # noqa: E402
from clark import server  # noqa: E402

WAIT = 30           # seconds to wait for the address line, or for the process to stop


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# The launcher's folders (data folder, OneDrive lookup) are written for the Mac only (platform.py); on another system they raise
# NotBuiltYet. These tests are about the launcher, not the system, so they run as the Mac does: in this process by patching
# platform.system, and in a child process by this small start-up that patches it the same way and then runs `-m clark`.
AS_THE_MAC = ("import runpy, sys; sys.path[:] = [p for p in sys.path if p]; from clark import platform; platform.system = lambda: platform.MAC; "
              "sys.argv[0] = 'clark'; runpy.run_module('clark', run_name='__main__', alter_sys=True)")


class Process:
    """`python3 -m clark ...` as a process, with its output read by threads so a wait can never hang the test."""

    def __init__(self, *args, home=None, env=None):
        full = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
        full.pop("CLARK_PORT", None)
        full.pop("CLARK_NOW", None)
        if home:
            full["HOME"] = str(home)
        full.update(env or {})
        self.proc = subprocess.Popen([sys.executable, "-c", AS_THE_MAC, *args], cwd=str(ROOT), env=full, text=True,
                                     encoding="utf-8", stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
        self.lines, self.errors = queue.Queue(), []
        self.seen = []
        threading.Thread(target=self._read, args=(self.proc.stdout, self.lines), daemon=True).start()
        self.err_thread = threading.Thread(target=self._read_all, args=(self.proc.stderr,), daemon=True)
        self.err_thread.start()

    @staticmethod
    def _read(stream, q):
        for line in stream:
            q.put(line.rstrip("\n"))
        q.put(None)

    def _read_all(self, stream):
        for line in stream:
            self.errors.append(line.rstrip("\n"))

    def address_line(self):
        """The line that gives the address, or fail with what the process said."""
        while True:
            try:
                line = self.lines.get(timeout=WAIT)
            except queue.Empty:
                self.kill()
                raise AssertionError(f"no address line in {WAIT} s; output {self.seen}, errors {self.errors}")
            if line is None:
                raise AssertionError(f"it stopped before listening; output {self.seen}, errors {self.errors}")
            self.seen.append(line)
            if line.startswith("Open http://"):
                return line

    def finish(self):
        """Wait for it to end on its own: (exit code, stdout lines, stderr lines)."""
        try:
            code = self.proc.wait(timeout=WAIT)
        except subprocess.TimeoutExpired:
            self.kill()
            raise AssertionError("it did not stop")
        self.err_thread.join(5)
        while True:
            line = self.lines.get(timeout=5)
            if line is None:
                break
            self.seen.append(line)
        return code, self.seen, self.errors

    def stop(self):
        """Ctrl+C: SIGINT, then wait. The exit code."""
        self.proc.send_signal(signal.SIGINT)
        return self.finish()[0]

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()

    def close(self):
        self.kill()
        for stream in (self.proc.stdout, self.proc.stderr):
            stream.close()


def post(port, path, body, headers=None):
    con = http.client.HTTPConnection("127.0.0.1", port, timeout=WAIT)
    try:
        data = json.dumps(body).encode("utf-8")
        con.putrequest("POST", path, skip_host=True)
        con.putheader("Host", f"127.0.0.1:{port}")
        con.putheader("Content-Type", "application/json")
        con.putheader("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            con.putheader(k, v)
        con.endheaders(data)
        r = con.getresponse()
        return r.status, json.loads(r.read().decode("utf-8"))
    finally:
        con.close()


def get(port, path, host=None, headers=None):
    con = http.client.HTTPConnection("127.0.0.1", port, timeout=WAIT)
    try:
        con.putrequest("GET", path, skip_host=True)
        con.putheader("Host", host or f"127.0.0.1:{port}")
        for k, v in (headers or {}).items():
            con.putheader(k, v)
        con.endheaders()
        r = con.getresponse()
        return r.status, r.read().decode("utf-8")
    finally:
        con.close()


def port_of(line):
    return int(re.search(r"http://127\.0\.0\.1:(\d+)/", line).group(1))


class TempFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="clark-main-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patch = mock.patch.object(pl, "system", return_value=pl.MAC)      # see AS_THE_MAC
        patch.start()
        self.addCleanup(patch.stop)


class RunsAsAProcess(TempFolder):
    def start(self, *args, **kw):
        p = Process(*args, **kw)
        self.addCleanup(p.close)
        return p

    def test_demo_serves_the_real_page_and_stops_cleanly_on_ctrl_c(self):
        port = free_port()
        p = self.start("--demo", "--port", str(port), home=self.tmp)
        line = p.address_line()
        self.assertEqual(port_of(line), port)
        self.assertEqual(line, f"Open http://127.0.0.1:{port}/#dashboard&p=TUL to use clark. Leave this window open. "
                               f"Press Ctrl+C to stop.")
        self.assertEqual(get(port, "/health"), (200, '{"ok": true}'))
        status, page = get(port, "/")
        self.assertEqual(status, 200)
        self.assertIn('id="app"', page)                     # the real page (#35), not the server's placeholder
        self.assertNotIn("The report editor is starting", page)
        token = json.loads(re.search(r'<script type="application/json" id="clark-boot">(.*?)</script>', page).group(1))["token"]
        self.assertTrue(token)
        status, body = get(port, "/api/data?project=TUL", headers={"X-Clark-Token": token})     # the store's own read, in the server's thread
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["data"]["project"]["code"], "TUL")
        status, body = get(port, "/api/projects", headers={"X-Clark-Token": token})       # the project list: its own connection
        self.assertEqual(status, 200, body)
        listed = json.loads(body)["projects"]
        self.assertEqual([x["code"] for x in listed], ["MOSS", "TUL"])
        self.assertTrue(listed[0]["name"])
        self.assertEqual(get(port, "/api/projects")[0], 403, "the list needs the token like everything under /api/")
        sent = {"X-Clark-Token": token}                                    # #65: saving and Undo, each call on its own store
        sections = json.loads(get(port, "/api/data?project=TUL", headers=sent)[1])["data"]["report_sections"]
        self.assertEqual(len(sections), 11)
        first = sections[4]["id"]
        status, made = post(port, "/api/change", {"project": "TUL", "kind": "report_sections", "op": "update", "id": first,
                                                  "changes": {"title": "Renamed in the demo"}}, sent)
        self.assertEqual((status, made["ok"]), (200, True), made)
        status, back = post(port, "/api/undo", {"project": "TUL", "apply_id": made["apply_id"]}, sent)
        self.assertEqual((status, back["skipped"], back["sections"][4]["title"]), (200, [], sections[4]["title"]))
        self.assertEqual(post(port, "/api/change", {"project": "TUL"}, {"X-Clark-Token": "wrong"})[0], 403)
        self.assertEqual(get(port, "/", host="evil.example")[0], 403)      # a wrong Host is refused
        self.assertEqual(p.stop(), 0)
        self.assertEqual(p.errors, [])
        self.assertEqual(p.seen[-1], "Stopped.")
        self.assertNotIn("report editor", "\n".join(p.seen))
        self.assertFalse([f for f in self.tmp.iterdir()])                 # it wrote nothing into HOME

    def test_the_demo_folder_is_removed_when_it_stops(self):
        scratch = self.tmp / "scratch"
        scratch.mkdir()
        port = free_port()
        p = self.start("--demo", "--port", str(port), env={"TMPDIR": str(scratch)}, home=self.tmp)
        p.address_line()
        self.assertEqual([x.name.split("-")[0] for x in scratch.iterdir()], ["clark"])
        self.assertEqual(p.stop(), 0)
        self.assertEqual(list(scratch.iterdir()), [])

    def test_a_port_in_use_is_one_plain_line_and_exit_1_before_anything_starts(self):
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen(1)
            port = busy.getsockname()[1]
            code, out, err = self.start("--demo", "--port", str(port), home=self.tmp).finish()
        self.assertEqual(code, 1)
        self.assertEqual(err, [launcher.server.PORT_TAKEN])
        self.assertFalse([l for l in out if l.startswith("Open http://")])
        self.assertNotIn("Using", "\n".join(out))                 # it stopped before it opened any data

    def test_clark_port_sets_the_port_and_the_option_wins(self):
        port, other = free_port(), free_port()
        p = self.start("--demo", home=self.tmp, env={"CLARK_PORT": str(port)})
        self.assertEqual(port_of(p.address_line()), port)
        self.assertEqual(p.stop(), 0)
        p = self.start("--demo", "--port", str(other), home=self.tmp, env={"CLARK_PORT": str(port)})
        self.assertEqual(port_of(p.address_line()), other)
        self.assertEqual(p.stop(), 0)

    def test_data_makes_the_database_there_and_a_second_start_reuses_it(self):
        folder = self.tmp / "new" / "place"
        p = self.start("--data", str(folder), "--port", str(free_port()), home=self.tmp)
        p.address_line()
        self.assertEqual(p.stop(), 0)
        db = folder / "clark.db"
        self.assertTrue(db.is_file())
        marker = db.stat().st_size, db.read_bytes()[:16]
        p = self.start("--data", str(folder), "--port", str(free_port()), home=self.tmp)
        port = port_of(p.address_line())
        self.assertEqual(get(port, "/health")[0], 200)
        self.assertEqual(get(port, "/api/data?project=TUL", headers={"X-Clark-Token": "wrong"})[0], 403)
        self.assertEqual(p.stop(), 0)
        self.assertEqual((db.stat().st_size, db.read_bytes()[:16]), marker)       # opened again, not made again
        self.assertEqual([x.name for x in folder.iterdir() if not x.name.startswith("clark.db")], [])

    def test_a_data_folder_inside_onedrive_is_refused_and_nothing_is_made(self):
        cloud = self.tmp / "Library" / "CloudStorage" / "OneDrive-DemoOrg"
        cloud.mkdir(parents=True)
        inside = cloud / "clark-data"
        code, out, err = self.start("--data", str(inside), "--port", str(free_port()), home=self.tmp).finish()
        self.assertEqual(code, 1)
        self.assertEqual(len(err), 1)
        self.assertRegex(err[0], r"^Your data can't be kept in .* because it is inside OneDrive \(OneDrive-DemoOrg\)")
        self.assertFalse(inside.exists())
        self.assertNotIn("Traceback", "\n".join(err))

    def test_the_default_folder_is_clarks_own_under_home(self):
        p = self.start("--port", str(free_port()), home=self.tmp)
        p.address_line()
        self.assertEqual(p.stop(), 0)
        self.assertTrue((pl.data_dir(self.tmp, on=pl.MAC) / "clark.db").is_file())

    def test_argument_errors_are_plain(self):
        for args, text in ((["--port", "abc"], "The port setting (--port) must be a whole number from 1 to 65535."),
                           (["--port", "70000"], "The port setting (--port) must be a whole number from 1 to 65535."),
                           (["--demo", "--data", str(self.tmp)], "--demo makes its own temporary folder. Use --data or "
                                                                 "--demo, not both."),
                           (["--foo"], "The option --foo isn't recognised."),
                           (["--foo", "--bar"], "These options aren't recognised: --foo, --bar."),
                           (["--data"], "--data needs a value after it.")):
            code, out, err = self.start(*args, home=self.tmp).finish()
            self.assertEqual(code, 2, args)
            self.assertEqual(err, [text, "Run python3 -m clark --help to see the options."], args)
            self.assertNotIn("Traceback", "\n".join(err))
        code, out, err = self.start("--demo", home=self.tmp, env={"CLARK_PORT": "x"}).finish()
        self.assertEqual(code, 2)
        self.assertEqual(err[0], "The port setting (CLARK_PORT) must be a whole number from 1 to 65535.")

    def test_the_help_text_is_plain(self):
        code, out, err = self.start("--help", home=self.tmp).finish()
        text = " ".join("\n".join(out).split())          # argparse wraps lines to the terminal's width
        self.assertEqual(code, 0)
        self.assertIn("Start clark on this computer. Only this computer can reach it.", text)
        self.assertIn("the port clark listens on (default: the CLARK_PORT setting, or 8766)", text)
        self.assertNotIn("report editor", text)


class AStoppedRestoreIsNotCalledUnreadable(TempFolder):
    """F1: a restore that stopped and cannot be finished is shown with its own words (where the database you had is), not as
    'clark can't read the data'."""

    def test_the_launcher_shows_where_the_database_is(self):
        data = self.tmp / "data"
        aside = data / "backups" / "replaced-20300101T000000Z"
        aside.mkdir(parents=True)
        (aside / "clark.db").write_bytes(b"the database you had")
        (data / "clark.db.restoring.json").write_text(json.dumps({"aside": aside.name}), encoding="utf-8")
        (data / "clark.db.restoring").write_bytes(b"damaged")
        with self.assertRaises(launcher.Quiet) as ctx:
            launcher.open_data(data, [])
        text = str(ctx.exception)
        self.assertTrue(text.startswith(f"clark.db is missing from {pl.shown(data)}. Your database is in "), text)
        self.assertIn("replaced-20300101T000000Z", text)
        self.assertNotIn("can't read the data", text)
        self.assertFalse((data / "clark.db").exists(), "no new empty database was made")


class RunsFromTheTopFolder(TempFolder):
    """Plain `python3 -m clark` from the repo's top folder: no PYTHONPATH, no install step (the root clark/ stand-in)."""

    def test_plain_python_m_clark_starts_and_serves_with_no_pythonpath(self):
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "CLARK_PORT", "CLARK_NOW")}
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1", HOME=str(self.tmp))
        port = free_port()
        proc = subprocess.Popen([sys.executable, "-m", "clark", "--demo", "--port", str(port)], cwd=str(ROOT), env=env,
                                text=True, encoding="utf-8", stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        self.addCleanup(lambda: (proc.poll() is None and proc.kill(), proc.wait(), proc.stdout.close(), proc.stderr.close()))
        lines = queue.Queue()
        threading.Thread(target=Process._read, args=(proc.stdout, lines), daemon=True).start()
        while True:
            line = lines.get(timeout=WAIT)
            self.assertIsNotNone(line, proc.stderr.read() if proc.poll() is not None else "it stopped")
            if line.startswith("Open http://"):
                break
        self.assertEqual(get(port, "/health"), (200, '{"ok": true}'))
        proc.send_signal(signal.SIGINT)
        self.assertEqual(proc.wait(timeout=WAIT), 0)

    def test_the_stand_in_hands_over_to_the_real_package_under_src(self):
        code = ("import clark; print(clark.__file__)\n"
                "import clark.__main__ as shim\n"
                "shim.prepare()\n"
                "import clark; print(clark.__file__)\n"
                "import clark.__main__ as real; print(real.__file__)\n")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        done = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env, text=True, encoding="utf-8",
                              capture_output=True, timeout=WAIT)
        first, second, third = [Path(x).resolve() for x in done.stdout.split()]
        self.assertEqual(first, (ROOT / "clark" / "__init__.py").resolve(), done.stderr)
        self.assertEqual(second, (ROOT / "src" / "clark" / "__init__.py").resolve())
        self.assertEqual(third, (ROOT / "src" / "clark" / "__main__.py").resolve())

    def test_the_stand_in_puts_vendor_on_the_path_just_after_src(self):
        code = ("import sys, json\n"
                "import clark.__main__ as shim\n"
                "shim.prepare(); shim.prepare()\n"                        # twice: no folder is added twice
                "import openpyxl\n"
                "print(json.dumps({'path': sys.path[:2], 'src': sys.path.count(shim.SRC),"
                " 'vendor': sys.path.count(shim.VENDOR), 'openpyxl': openpyxl.__file__}))\n")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        done = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env, text=True, encoding="utf-8",
                              capture_output=True, timeout=WAIT)
        self.assertEqual(done.returncode, 0, done.stderr)
        seen = json.loads(done.stdout)
        self.assertEqual([Path(x) for x in seen["path"]], [(ROOT / "src").resolve(), (ROOT / "vendor").resolve()])
        self.assertEqual((seen["src"], seen["vendor"]), (1, 1))
        self.assertEqual(Path(seen["openpyxl"]).resolve(), (ROOT / "vendor" / "openpyxl" / "__init__.py").resolve())

    def test_starting_from_the_top_folder_writes_no_bytecode(self):
        top = self.tmp / "clark folder"                                     # a space, as in a OneDrive path
        shutil.copytree(str(ROOT / "clark"), str(top / "clark"), ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(str(ROOT / "src"), str(top / "src"), ignore=shutil.ignore_patterns("__pycache__"))
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONDONTWRITEBYTECODE",
                                                                 "PYTHONPYCACHEPREFIX")}
        env["HOME"] = str(self.tmp)
        for module in ("clark", "clark.launch"):
            done = subprocess.run([sys.executable, "-m", module, "--help"], cwd=str(top), env=env, text=True,
                                  encoding="utf-8", capture_output=True, timeout=WAIT)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("clark", done.stdout)
        cached = sorted(str(p.relative_to(top)) for p in top.rglob("*.pyc"))
        # Python writes the stand-in's own __init__ cache before that file can say no; nothing else is written.
        self.assertEqual([p for p in cached if not Path(p).name.startswith("__init__.")], [])
        self.assertFalse(list((top / "src").rglob("__pycache__")))

    def test_in_the_tests_clark_is_the_one_under_src(self):
        self.assertEqual(Path(launcher.__file__).resolve(), (ROOT / "src" / "clark" / "__main__.py").resolve())
        self.assertNotIn(str(ROOT), [str(Path(x).resolve()) for x in sys.path if x])      # the top folder is not on the path


class FakeServe:
    """Stands in for server.serve: records what it was given, prints the address line, and returns `code`."""

    def __init__(self, code=0, raises=None):
        self.calls, self.code, self.raises = [], code, raises

    def __call__(self, **kw):
        self.calls.append(kw)
        # the guarded server's own line, in its old words: the launcher must say it its own way
        print("Open http://127.0.0.1:%d/ to use the report editor. Leave this window open; press Ctrl+C to stop."
              % kw["port"], file=kw["out"], flush=True)
        if self.raises:
            raise self.raises
        return self.code


class InProcess(TempFolder):
    def run_main(self, *argv, serve=None, **kw):
        out, err = io.StringIO(), io.StringIO()
        serve = serve or FakeServe()
        kw.setdefault("home", self.tmp)
        kw.setdefault("environ", {})
        kw.setdefault("is_free", lambda port: True)            # no real port is probed in these tests
        code = launcher.main(list(argv), out=out, err=err, serve=serve, **kw)
        return code, out.getvalue(), err.getvalue(), serve

    def test_the_server_gets_the_stores_data_and_the_built_page_and_the_change_and_undo_handlers(self):
        code, out, err, serve = self.run_main("--port", "8123")
        self.assertEqual((code, err), (0, ""))
        (call,) = serve.calls
        self.assertEqual(sorted(call), ["change", "data_for", "err", "movement", "out", "page_html", "port", "profile", "projects", "publisher", "safety", "undo", "use_cases"])
        self.assertTrue(callable(call["change"]) and callable(call["undo"]))
        self.assertTrue(callable(call["safety"].listing) and callable(call["safety"].preview) and callable(call["safety"].restore))
        self.assertTrue(callable(call["projects"]))
        self.assertEqual(call["port"], 8123)
        self.assertEqual(call["data_for"].__name__, "data_for")
        self.assertIs(call["page_html"], launcher.page.page_html)
        self.assertEqual(out.splitlines()[-2:], [f"Open http://127.0.0.1:8123/ to use clark. Leave this window open. "
                                                  f"Press Ctrl+C to stop.", "Stopped."])      # no project yet: no hash
        self.assertNotIn("report editor", out)

    def test_the_launchers_own_store_is_closed_before_serving_so_a_restore_can_take_the_file(self):
        """#111: an open connection would make Restore say another program has the data open; data_for opens its own each time."""
        import sqlite3
        seen = []

        def serve(**kw):
            held = kw["data_for"].__self__
            with self.assertRaises(sqlite3.ProgrammingError):
                held.con.execute("SELECT 1")                     # closed
            seen.append(kw["safety"].path)
            self.assertIsNone(kw["data_for"]("ABC"))             # and the page's reads still work (no such project here)
            return 0
        self.assertEqual(self.run_main(serve=serve)[0], 0)
        self.assertEqual(len(seen), 1)

    def test_the_projects_function_uses_its_own_connection_in_any_thread(self):
        """The server answers from several threads and a SQLite connection belongs to the thread that made it, so the list must
        not come from the launcher's own store: it opens a short-lived one per call, here from another thread, and it leaves
        archived projects out and orders by code."""
        import threading
        from clark.store import open_store
        folder = self.tmp / "data"
        folder.mkdir()
        store = open_store(folder / "clark.db", onedrive_roots=[])
        self.addCleanup(store.close)
        with store.step("dashboard", "Demo User") as st:
            for code, name in (("ZZZ", "Last programme"), ("AAA", "First programme"), ("MMM", "Middle programme")):
                st.create("projects", {"code": code, "name": name})
        store.con.execute("UPDATE projects SET archived = 1, active = 0 WHERE code = 'MMM'")
        projects = launcher.projects_of(store.path, [])
        found, errors = [], []

        def from_another_thread():
            try:
                found.extend(projects())
            except BaseException as e:           # noqa: BLE001  (the test says what went wrong)
                errors.append(repr(e))
        t = threading.Thread(target=from_another_thread)
        t.start()
        t.join(10)
        self.assertEqual(errors, [])
        self.assertEqual(found, [{"code": "AAA", "name": "First programme"}, {"code": "ZZZ", "name": "Last programme"}])
        self.assertEqual(projects(), found, "and again in this thread, after the other")

    def test_the_projects_function_is_not_the_stores_own_read(self):
        code, out, err, serve = self.run_main("--port", "8123")
        projects = serve.calls[0]["projects"]
        self.assertNotEqual(getattr(projects, "__name__", ""), "read")
        self.assertIsNot(projects, getattr(serve.calls[0]["data_for"], "__self__", object()).read)

    def test_change_and_undo_go_through_when_given(self):
        def change(*a):
            return None

        def undo(*a):
            return None
        _, _, _, serve = self.run_main(change=change, undo=undo)
        self.assertIs(serve.calls[0]["change"], change)
        self.assertIs(serve.calls[0]["undo"], undo)
        _, _, _, serve = self.run_main(undo=undo)
        self.assertIs(serve.calls[0]["undo"], undo)
        self.assertEqual(serve.calls[0]["change"].__name__, "change")        # not given: built from clark.changes

    def test_change_and_undo_are_built_for_the_data_file_each_call_on_a_store_of_its_own(self):
        """The handlers are made from the file, not from the launcher's own store (a connection belongs to its thread), and they
        work from another thread."""
        _, _, _, serve = self.run_main("--data", str(self.tmp / "data"), onedrive_roots=[])
        call = serve.calls[0]
        from clark.store import open_store
        store = open_store(self.tmp / "data" / "clark.db", onedrive_roots=[])
        self.addCleanup(store.close)
        with store.step("dashboard", "Demo User") as st:
            st.create("projects", {"code": "ABC", "name": "Example Programme"})
        found = []
        t = threading.Thread(target=lambda: found.append(call["change"](
            {"project": "ABC", "kind": "report_sections", "op": "new", "values": {"title": "From a thread"}})))
        t.start()
        t.join(30)
        self.assertEqual(found[0][0], 200, found)
        self.assertEqual(store.read("report_sections", "ABC")[-1]["title"], "From a thread")
        done = call["undo"]({"project": "ABC", "apply_id": found[0][1]["apply_id"]})
        self.assertEqual((done[0], done[1]["skipped"]), (200, []))

    def test_the_default_port_is_8766_or_clark_port(self):
        self.assertEqual(self.run_main()[3].calls[0]["port"], 8766)
        self.assertEqual(self.run_main(environ={"CLARK_PORT": "9001"})[3].calls[0]["port"], 9001)
        self.assertEqual(self.run_main("--port", "9002", environ={"CLARK_PORT": "9001"})[3].calls[0]["port"], 9002)

    def test_the_default_data_folder_comes_from_the_platform_layer_and_is_made_on_first_run(self):
        folder = pl.data_dir(self.tmp, on=pl.MAC)
        self.assertFalse(folder.exists())
        self.run_main()
        self.assertTrue((folder / "clark.db").is_file())

    def test_open_opens_the_address_once_and_only_when_asked(self):
        opened = []
        self.run_main("--port", "8124", open_url=opened.append)
        self.assertEqual(opened, [])
        self.run_main("--port", "8124", "--open", open_url=opened.append)
        self.assertEqual(opened, ["http://127.0.0.1:8124/"])

    def test_a_browser_that_will_not_open_gives_one_next_step_only(self):
        def refuse(url):
            raise pl.PlatformError(f"The browser could not be opened. {pl.TRY_AGAIN}")
        code, out, err, serve = self.run_main("--open", open_url=refuse)
        self.assertEqual(err, "The browser could not be opened. Open http://127.0.0.1:8766/ yourself.\n")
        self.assertNotIn("Try again", err)

    def test_a_browser_that_will_not_open_is_said_plainly_and_the_server_still_runs(self):
        def refuse(url):
            raise pl.PlatformError("The browser could not be opened.")
        code, out, err, serve = self.run_main("--open", open_url=refuse)
        self.assertEqual(code, 0)
        self.assertEqual(err, "The browser could not be opened. Open http://127.0.0.1:8766/ yourself.\n")

    def test_one_project_gives_the_address_with_its_code_and_open_opens_that(self):
        opened = []
        data = self.tmp / "data"
        store = launcher.clark_store.open_store(data / "clark.db", onedrive_roots=[]) if data.mkdir() is None else None
        with store.step("dashboard", "tester") as st:
            st.create("projects", dict(code="ABC", name="Test project", sponsor="A. Sponsor", phase="Build", health="On track"))
        store.close()
        code, out, err, _ = self.run_main("--data", str(data), "--port", "8125", "--open", open_url=opened.append)
        self.assertIn("Open http://127.0.0.1:8125/#dashboard&p=ABC to use clark. Leave this window open. "
                      "Press Ctrl+C to stop.", out)
        self.assertEqual(opened, ["http://127.0.0.1:8125/#dashboard&p=ABC"])

    def test_the_demo_gives_the_demo_projects_real_code(self):
        sys.path.insert(0, str(launcher.DEV))
        self.addCleanup(sys.path.remove, str(launcher.DEV))
        import demo_data
        self.assertEqual(launcher.DEMO_CODE, demo_data.CODES[0])
        _, out, _, _ = self.run_main("--demo", "--port", "8126")
        self.assertIn(f"Open http://127.0.0.1:8126/#dashboard&p={demo_data.CODES[0]} to use clark.", out)

    def test_a_port_in_use_is_checked_before_anything_is_made_or_started(self):
        taken = []

        def busy(port):
            taken.append(port)
            return port != 8766
        code, out, err, serve = self.run_main("--demo", is_free=busy)
        self.assertEqual(code, 1)
        self.assertEqual(err, launcher.server.PORT_TAKEN + "\n")
        self.assertEqual((serve.calls, out), ([], ""))

    def test_the_servers_own_port_line_and_the_launchers_are_the_same_line(self):
        """A port taken after the launcher's check (a race) is reported by the server in the same words, passed on as they are."""
        def losing(**kw):
            print(launcher.server.PORT_TAKEN, file=kw["err"])
            return 1
        code, out, err, _ = self.run_main(serve=losing)
        self.assertEqual(code, 1)
        self.assertEqual(err, launcher.server.PORT_TAKEN + "\n")

    def test_the_servers_exit_code_is_passed_on(self):
        self.assertEqual(self.run_main(serve=FakeServe(code=1))[0], 1)

    def test_ctrl_c_before_or_during_serving_exits_0_and_closes_the_store_and_removes_the_demo_folder(self):
        scratch = self.tmp / "scratch"
        scratch.mkdir()
        old = tempfile.tempdir
        tempfile.tempdir = str(scratch)
        self.addCleanup(setattr, tempfile, "tempdir", old)
        seen = []
        real = launcher.clark_store.Store.close
        launcher.clark_store.Store.close = lambda s: (seen.append(s.path), real(s))
        self.addCleanup(setattr, launcher.clark_store.Store, "close", real)
        code, out, err, _ = self.run_main("--demo", serve=FakeServe(raises=KeyboardInterrupt()))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines()[-1], "Stopped.")
        self.assertEqual(seen[-1].name, "clark.db")             # the demo build closes its own store first; the last is the served one
        self.assertEqual(seen[-1].parent.parent, scratch)
        self.assertEqual(list(scratch.iterdir()), [])

    def test_a_folder_inside_onedrive_is_refused_before_anything_is_made(self):
        root = self.tmp / "OneDrive-DemoOrg"
        root.mkdir()
        code, out, err, serve = self.run_main("--data", str(root / "clark"), onedrive_roots=[root])
        self.assertEqual(code, 1)
        self.assertEqual(serve.calls, [])
        self.assertIn("inside OneDrive", err)
        self.assertFalse((root / "clark").exists())

    def test_a_file_where_the_folder_should_be_is_said_plainly(self):
        f = self.tmp / "afile"
        f.write_text("x", encoding="utf-8")
        code, out, err, serve = self.run_main("--data", str(f / "inner"))
        self.assertEqual(code, 1)
        self.assertRegex(err, r"^The data folder .*inner can't be made \(it is a file, not a folder\)\. Check you may write there, or choose "
                              r"another folder with --data\.\n$")
        self.assertNotIn("clark: ", err)

    def test_something_that_is_not_a_clark_database_is_refused_plainly(self):
        (self.tmp / "clark.db").write_bytes(b"this is not a database at all, just some text\n" * 20)
        code, out, err, serve = self.run_main("--data", str(self.tmp))
        self.assertEqual(code, 1)
        self.assertEqual(err, "The data in clark.db can't be read. Start clark with --data to use another folder, or "
                              "restore a backup.\n")
        self.assertNotIn("Traceback", err)
        self.assertNotIn("file is not a database", err)             # the store's raw error is never shown


class Restore(InProcess):
    """#86: `python3 -m clark restore [NAME] [--data FOLDER]` is a sub-command of the launcher; plain `python3 -m clark` is unchanged."""

    def make(self):
        import _demo
        demo = _demo.DemoStore()
        self.addCleanup(demo.close)
        with demo.store.step("undo", "Demo User") as st:             # it writes something: a step that writes nothing keeps no copy
            st.create("actions", {"project": "ABC", "description": "x", "raised": "2026-10-01", "source": "demo"})
        demo.store.close()
        return demo

    def restore(self, *argv, **kw):
        out, err = io.StringIO(), io.StringIO()
        kw.setdefault("home", self.tmp)
        kw.setdefault("onedrive_roots", [])
        code = launcher.main(["restore", *argv], out=out, err=err, **kw)
        return code, out.getvalue(), err.getvalue()

    def test_with_no_name_it_lists_the_copies_in_local_time_and_changes_nothing(self):
        demo = self.make()
        before = sorted(p.name for p in demo.dir.rglob("*"))
        code, out, err = self.restore("--data", str(demo.dir))
        self.assertEqual((code, err), (0, ""))
        self.assertRegex(out, r"Backups in .*backups, newest first \(times are your local time\):")
        self.assertRegex(out, r"  \d\d-\d\d-\d{4} \d\d:\d\d  before an undo +clark-\d{8}T\d{6}Z-undo\.db")
        self.assertIn("daily", out)
        self.assertIn("python3 -m clark restore NAME", out)
        self.assertIn("a folder called replaced-DATE", " ".join(out.split()))
        self.assertEqual(sorted(p.name for p in demo.dir.rglob("*")), before)

    def test_a_folder_with_no_backups_says_so(self):
        code, out, err = self.restore("--data", str(self.tmp / "nothing-here"))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("There are no backups in", out)

    def test_with_a_name_it_puts_that_copy_back_and_says_where_the_old_database_went(self):
        demo = self.make()
        name = [p.name for p in (demo.dir / "backups").iterdir() if p.name.endswith("-daily.db")][0]
        code, out, err = self.restore(name, "--data", str(demo.dir))
        self.assertEqual((code, err), (0, ""))
        self.assertRegex(out, rf"^Put {name} back as your clark data\. The database you had before is kept in .*replaced-\d{{8}}T\d{{6}}Z, "
                              r"and clark made a backup of it first\. Start clark again to use it\.\n$")
        self.assertEqual(len([p for p in (demo.dir / "backups").iterdir() if p.name.startswith("replaced-")]), 1)

    def test_l4_the_words_say_a_backup_was_made_only_when_one_was(self):
        """L4: the success text claimed "clark made a backup of it first" for a database that was too damaged or empty to copy."""
        import sqlite3

        def damaged_page(folder):
            folded = sqlite3.connect(folder / "clark.db")
            folded.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            folded.close()
            with open(folder / "clark.db", "r+b") as f:
                f.seek(10 * 4096)
                f.write(b"\xff" * 4096)

        cases = (("garbage", lambda folder: (folder / "clark.db").write_bytes(b"this is not a database" * 100)),
                 ("zero bytes", lambda folder: (folder / "clark.db").write_bytes(b"")),
                 ("a damaged page", damaged_page))
        for label, spoil in cases:
            with self.subTest(label):
                demo = self.make()
                name = [p.name for p in (demo.dir / "backups").iterdir() if p.name.endswith("-daily.db")][0]
                for side in ("-wal", "-shm"):
                    (demo.dir / f"clark.db{side}").unlink(missing_ok=True)
                spoil(demo.dir)
                code, out, err = self.restore(name, "--data", str(demo.dir))
                self.assertEqual((code, err), (0, ""))
                self.assertNotIn("made a backup of it first", out)
                self.assertIn("could not make a backup of it first, because it was empty or damaged, so that folder holds the only copy", out)
                self.assertRegex(out, r"is kept in .*replaced-\d{8}T\d{6}Z\.")
        demo = self.make()                                              # and a good database really is copied first
        name = [p.name for p in (demo.dir / "backups").iterdir() if p.name.endswith("-daily.db")][0]
        code, out, err = self.restore(name, "--data", str(demo.dir))
        self.assertIn("and clark made a backup of it first.", out)
        self.assertEqual(len([p for p in (demo.dir / "backups").iterdir() if p.name.endswith("-restore.db")]), 1)

    def test_l5_a_backups_path_that_is_a_file_or_unreadable_is_a_plain_message(self):
        """L5: these gave a Python traceback with the whole path (and so the user name) in it."""
        import stat
        for label, name in (("a file", ""), ("a file", "clark-20300102T030405Z-undo.db"), ("unreadable", ""),
                            ("unreadable", "clark-20300102T030405Z-undo.db")):
            with self.subTest(f"{label} {name or 'listing'}"):
                demo = self.make()
                backups = demo.dir / "backups"
                shutil.rmtree(backups)
                if label == "a file":
                    backups.write_text("not a folder", encoding="utf-8")
                else:
                    backups.mkdir()
                    (backups / "clark-20300102T030405Z-undo.db").write_bytes(b"x")
                    os.chmod(backups, 0)
                    self.addCleanup(os.chmod, backups, stat.S_IRWXU)
                argv = ([name] if name else []) + ["--data", str(demo.dir)]
                with mock.patch.object(pathlib.Path, "home", return_value=demo.dir.resolve().parent):
                    code, out, err = self.restore(*argv)
                os.chmod(backups, stat.S_IRWXU) if label == "unreadable" else None
                self.assertEqual((code, out), (1, ""))
                self.assertNotIn("Traceback", err)
                for real in (str(demo.dir), str(demo.dir.resolve())):
                    self.assertNotIn(real, err, "the real path (and so the user name) is not in the message")
                self.assertIn("~/", err)
                self.assertTrue(err.endswith("\n") and err.count("\n") == 1, err)

    def test_l7_ctrl_c_during_the_move_prints_a_hint_not_a_traceback_and_starting_clark_finishes_it(self):
        """L7: Ctrl+C in the move window gave a traceback and no "start clark again" hint."""
        from clark import backup
        from clark.store import open_store
        for label, hook_name in (("before anything moved", "_move_aside"), ("after the old database moved", "replace_file")):
            with self.subTest(label):
                demo = self.make()
                name = [p.name for p in (demo.dir / "backups").iterdir() if p.name.endswith("-daily.db")][0]
                if hook_name == "_move_aside":
                    hook = mock.patch.object(backup, "_move_aside", side_effect=KeyboardInterrupt)
                else:
                    real = pl.replace_file

                    def stop_at_the_last_step(source, dest, *a, **kw):
                        if Path(dest).name == "clark.db":
                            raise KeyboardInterrupt
                        return real(source, dest, *a, **kw)
                    hook = mock.patch.object(pl, "replace_file", stop_at_the_last_step)
                with hook:
                    code, out, err = self.restore(name, "--data", str(demo.dir))
                self.assertEqual((code, out), (130, ""))
                self.assertNotIn("Traceback", err)
                self.assertIn("Start clark again to finish the restore", err)
                self.assertEqual(err.count("\n"), 1)
                started = open_store(demo.dir / "clark.db", onedrive_roots=[])           # "start clark again"
                self.addCleanup(started.close)
                self.assertTrue((demo.dir / "clark.db").exists())
                self.assertFalse((demo.dir / "clark.db.restoring.json").exists(), "nothing is left waiting")

    def test_a_name_that_is_not_a_backup_and_a_database_in_use_are_refused_plainly(self):
        demo = self.make()
        code, out, err = self.restore("../clark.db", "--data", str(demo.dir))
        self.assertEqual((code, out), (1, ""))
        self.assertRegex(err, r"^No backup called \.\./clark\.db is in .*\. To see the backups, run:\n    python3 -m clark restore\n$")
        import sqlite3
        name = [p.name for p in (demo.dir / "backups").iterdir() if p.name.endswith("-daily.db")][0]
        holder = sqlite3.connect(demo.dir / "clark.db")
        holder.execute("SELECT count(*) FROM sqlite_master").fetchone()
        try:
            code, out, err = self.restore(name, "--data", str(demo.dir))
        finally:
            holder.close()
        self.assertEqual(code, 1)
        self.assertRegex(err, r"^Another window or program has clark's data open")

    def test_a_damaged_database_can_still_be_restored(self):
        demo = self.make()
        name = [p.name for p in (demo.dir / "backups").iterdir() if p.name.endswith("-daily.db")][0]
        for side in ("-wal", "-shm"):
            (demo.dir / f"clark.db{side}").unlink(missing_ok=True)
        (demo.dir / "clark.db").write_bytes(b"this is not a database" * 100)
        code, out, err = self.restore(name, "--data", str(demo.dir))
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.startswith(f"Put {name} back"))

    def test_a_database_with_a_damaged_page_can_be_restored_from_the_command(self):
        demo = self.make()
        name = [p.name for p in (demo.dir / "backups").iterdir() if p.name.endswith("-daily.db")][0]
        import sqlite3
        folded = sqlite3.connect(demo.dir / "clark.db")
        folded.execute("PRAGMA wal_checkpoint(TRUNCATE)")             # Python 3.9's SQLite leaves frames in the -wal after a close
        folded.close()
        with open(demo.dir / "clark.db", "r+b") as f:
            f.seek(10 * 4096)                       # the root page of one table; the page with the database's identity is untouched
            f.write(b"\xff" * 4096)
        code, out, err = self.restore(name, "--data", str(demo.dir))
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.startswith(f"Put {name} back"))

    def test_a_zero_byte_clark_db_is_restored_and_no_new_database_is_built_in_it(self):
        demo = self.make()
        name = [p.name for p in (demo.dir / "backups").iterdir() if p.name.endswith("-daily.db")][0]
        for side in ("-wal", "-shm"):
            (demo.dir / f"clark.db{side}").unlink(missing_ok=True)
        (demo.dir / "clark.db").write_bytes(b"")
        code, out, err = self.restore(name, "--data", str(demo.dir))
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.startswith(f"Put {name} back"))
        aside = [p for p in (demo.dir / "backups").iterdir() if p.name.startswith("replaced-")]
        self.assertEqual([(p / "clark.db").stat().st_size for p in aside], [0], "the empty file was moved aside as it was")
        self.assertGreater((demo.dir / "clark.db").stat().st_size, 0)

    def test_a_clark_db_made_new_with_nothing_in_it_can_be_restored_over(self):
        from clark.store import open_store
        demo = self.make()
        name = [p.name for p in (demo.dir / "backups").iterdir() if p.name.endswith("-daily.db")][0]
        for side in ("", "-wal", "-shm"):
            (demo.dir / f"clark.db{side}").unlink(missing_ok=True)
        fresh = open_store(demo.dir / "clark.db", onedrive_roots=[])       # what starting clark again would have made
        fresh.close()
        code, out, err = self.restore(name, "--data", str(demo.dir))
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.startswith(f"Put {name} back"))

    def test_the_options_errors_are_plain(self):
        for argv, text in ((["a", "b"], "Restore takes one backup name at most. You gave: b."),
                           (["--data"], "--data needs a value after it."),
                           (["--port", "1"], "Restore has no option --port.")):
            out, err = io.StringIO(), io.StringIO()
            real = sys.stderr
            sys.stderr = err
            try:
                with self.assertRaises(SystemExit) as ctx:
                    launcher.main(["restore", *argv], out=out, err=err, home=self.tmp)
            finally:
                sys.stderr = real
            self.assertEqual(ctx.exception.code, 2, argv)
            self.assertIn(text.split(" (")[0], err.getvalue())
            self.assertIn("Run python3 -m clark restore --help to see the options.", err.getvalue())

    def test_the_plain_launcher_and_its_help_are_unchanged_and_point_to_restore(self):
        code, out, err, serve = self.run_main("--port", "8123")
        self.assertEqual((code, err, len(serve.calls)), (0, "", 1))
        text = " ".join(launcher.parser().format_help().split())
        self.assertIn("python3 -m clark restore --help", text)
        self.assertIn("--data FOLDER", text)


class OpenUrl(unittest.TestCase):
    """platform.open_url, with a fake runner like the other platform functions."""

    def test_it_uses_open_with_an_argument_list(self):
        calls = []

        def run(args, **kw):
            calls.append((args, kw))
            return subprocess.CompletedProcess(args, 0, "", "")
        pl.open_url("http://127.0.0.1:8766/", run=run, on=pl.MAC)
        self.assertEqual([c[0] for c in calls], [["open", "http://127.0.0.1:8766/"]])
        self.assertNotIn("shell", calls[0][1])

    def test_only_web_addresses_are_opened(self):
        for bad in ("-a Calculator", "file:///etc/passwd", "http://x y", "", "javascript:alert(1)"):
            with self.assertRaisesRegex(pl.PlatformError, "Only web addresses"):
                pl.open_url(bad, run=lambda *a, **k: self.fail("started a program"), on=pl.MAC)

    def test_a_refusal_is_said_plainly(self):
        with self.assertRaises(pl.PlatformError) as ctx:
            pl.open_url("http://127.0.0.1:1/", run=lambda a, **k: subprocess.CompletedProcess(a, 1, "", "no browser"),
                        on=pl.MAC)
        self.assertEqual(str(ctx.exception), "The browser could not be opened. " + pl.TRY_AGAIN)
        self.assertNotIn("no browser", str(ctx.exception))
        self.assertNotIn("(", str(ctx.exception))

    def test_a_refusal_with_no_reason_does_not_say_so(self):
        with self.assertRaises(pl.PlatformError) as ctx:
            pl.open_url("http://127.0.0.1:1/", run=lambda a, **k: subprocess.CompletedProcess(a, 1, "", ""), on=pl.MAC)
        self.assertEqual(str(ctx.exception), "The browser could not be opened. " + pl.TRY_AGAIN)

    def test_windows_is_not_built_yet(self):
        with self.assertRaisesRegex(pl.NotBuiltYet, "on Windows is not built yet"):
            pl.open_url("http://127.0.0.1:1/", run=lambda *a, **k: None, on=pl.WINDOWS)


class TheLaunchersWordsArePlain(unittest.TestCase):
    def test_no_string_in_the_launcher_says_report_editor_or_capital_clark(self):
        import ast
        tree = ast.parse((ROOT / "src" / "clark" / "__main__.py").read_text(encoding="utf-8"))
        words = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        self.assertTrue(words)
        for w in words:
            self.assertNotIn("report editor", w.lower())
            self.assertNotIn("Clark", w)
            self.assertNotIn("!", w)


class NoLineStartsWithTheProductName(unittest.TestCase):
    """"""
    START = re.compile(r"clark(?:\s|'|\u2019)", re.I)

    def lines_that_start_with_it(self, source):
        import ast
        tree = ast.parse(source)
        docstrings = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
        parts = {id(v): i for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for i, v in enumerate(n.values)}
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                for i, line in enumerate(node.value.split("\n")):
                    # a piece of an f-string that follows a placeholder starts a line only after a line break
                    if (i > 0 or parts.get(id(node), 0) == 0) and self.START.match(line):
                        found.append(line)
        return found

    def test_no_message_in_the_launcher_or_the_backup_module_starts_with_the_product_name(self):
        for name in ("__main__.py", "backup.py"):
            with self.subTest(file=name):
                text = (ROOT / "src" / "clark" / name).read_text(encoding="utf-8")
                self.assertEqual(self.lines_that_start_with_it(text), [])

    def test_the_scan_sees_a_sentence_that_starts_with_it(self):
        self.assertEqual(self.lines_that_start_with_it("x = \"clark can't make it\""), ["clark can't make it"])
        self.assertEqual(self.lines_that_start_with_it('x = f"clark knows {a}."'), ["clark knows "])
        self.assertEqual(self.lines_that_start_with_it('x = f"{a} clark is"'), [])
        self.assertEqual(self.lines_that_start_with_it('x = "first\\nclark is"'), ["clark is"])
        self.assertEqual(self.lines_that_start_with_it('x = "clark.db"'), [])

    def test_the_options_errors_do_not_start_with_it(self):
        for argv in (["--nope"], ["--nope", "--nada"], ["--port"]):
            with self.subTest(argv=argv):
                err = io.StringIO()
                with mock.patch.object(sys, "stderr", err), self.assertRaises(SystemExit):
                    launcher.main(argv)
                self.assertFalse(self.START.match(err.getvalue()), err.getvalue())


class TheSourceUsesTheRealServer(unittest.TestCase):
    def test_serve_still_takes_the_arguments_the_launcher_passes(self):
        import inspect
        names = inspect.signature(server.serve).parameters
        for name in ("port", "data_for", "page_html", "out", "err"):
            self.assertIn(name, names)


if __name__ == "__main__":
    unittest.main()
