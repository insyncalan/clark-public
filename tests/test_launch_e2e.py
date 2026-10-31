"""#71: the launcher against the REAL server, end to end (no fake /health).

Run: python3 dev/run_tests.py test_launch_e2e
launch.main() starts `python3 -m clark` in a temporary data folder on a free port and asks its real /health with the data
folder's mark. The only seam is the window: CLARK_BROWSER names a small script that writes the address it was given to a log,
so no browser opens. Other programs on the port are small stand-ins that answer /health badly. Every server this test starts
is stopped, and the process list is checked at the end of each test.
"""
import http.server
import json
import os
import socket
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import _paths  # noqa: F401  (puts src/ on the path)
from clark import launch, platform as pl

NOT_CLARK_LINE = "Nothing was started: clark is already open in another Terminal window, or another program is using the connection it needs. Close that Terminal window or program, then double-click clark.command again. If that does not help, restart your Mac."


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until(check, seconds=10.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.05)
    return check()


class Stand(http.server.BaseHTTPRequestHandler):
    """A program that is not clark, answering /health in one of the ways a stranger might."""
    def log_message(self, *a):
        pass

    def do_GET(self):
        how = self.server.how
        if how == "slow":
            time.sleep(3)
        body, status, ctype = {
            "ok-only": (b'{"ok": true}', 200, "application/json"),
            "html": (b"<html><body>hello</body></html>", 200, "text/html"),
            "404": (b"not found", 404, "text/plain"),
            "big": (b'{"ok": true, "this_data": true, "pad": "' + b"x" * 100_000 + b'"}', 200, "application/json"),
            "slow": (b'{"ok": true, "this_data": true}', 200, "application/json"),
            "string": (b'{"ok": true, "this_data": "true"}', 200, "application/json"),
        }[how]
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass


@unittest.skipUnless(sys.platform == 'darwin', 'the launcher runs on macOS only')
class LaunchEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.addCleanup(self.tmp.cleanup)
        self.log = self.root / "windows.log"
        self.stub = self.root / "browser"
        self.stub.write_text(f'#!/bin/sh\necho "$@" >> "{self.log}"\n', encoding="utf-8")
        self.stub.chmod(self.stub.stat().st_mode | stat.S_IXUSR)
        self.environ = {**os.environ, "CLARK_BROWSER": str(self.stub)}
        self.processes, self.listeners = [], []
        self.addCleanup(self.stop_everything)
        self.port = free_port()

    def stop_everything(self):
        for p in self.processes:
            if p.poll() is None:
                p.terminate()
        for p in self.processes:
            try:
                p.wait(timeout=10)
            except Exception:
                p.kill()
                p.wait(timeout=5)
        for s in self.listeners:
            if isinstance(s, socket.socket):
                s.close()
            else:
                s.shutdown()
                s.server_close()
        self.assertTrue(all(p.poll() is not None for p in self.processes), "a server is left running")

    def folder(self, name):
        return self.root / name

    def run_launcher(self, folder, port=None):
        """launch.main() with the real health check and the real start; the start is only watched so it can be stopped."""
        said = []

        def start(*args, **kw):
            p = pl.start_detached(*args, **kw)
            self.processes.append(p)
            return p
        code = launch.main(["--data", str(folder), "--port", str(port or self.port)], say=said.append,
                           environ=self.environ, start=start)
        return code, said

    def windows(self):
        wait_until(lambda: self.log.exists(), 2.0)
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def stand_in(self, how):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), Stand)
        server.how = how
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.listeners.append(server)

    def assert_not_clark(self):
        code, said = self.run_launcher(self.folder("data"))
        self.assertEqual(code, 1)
        self.assertEqual(len(said), 1)
        self.assertTrue(said[0].startswith(NOT_CLARK_LINE), said)
        self.assertEqual(self.windows(), [])
        self.assertEqual(self.processes, [])

    def test_first_run_starts_clark_and_opens_one_window(self):
        code, said = self.run_launcher(self.folder("data"))
        self.assertEqual(code, 0, said)
        self.assertEqual(said[0], "Starting clark...")
        self.assertEqual(said[-1], "Opened clark in its own window.")
        self.assertEqual(len(self.processes), 1)
        self.assertEqual(self.windows(), [f"--app=http://127.0.0.1:{self.port}/"])

    def test_second_run_on_the_same_data_folder_opens_one_more_window_and_starts_nothing(self):
        data = self.folder("data")
        self.assertEqual(self.run_launcher(data)[0], 0)
        code, said = self.run_launcher(data)
        self.assertEqual(code, 0, said)
        self.assertEqual(said, ["It is already running. Opening its window.", "Opened clark in its own window."])
        self.assertEqual(len(self.processes), 1)
        self.assertTrue(wait_until(lambda: len(self.windows()) == 2))
        self.assertEqual(len(self.windows()), 2)

    def test_another_data_folder_on_the_same_port_is_refused_with_no_window(self):
        self.assertEqual(self.run_launcher(self.folder("one"))[0], 0)
        before = self.windows()
        code, said = self.run_launcher(self.folder("two"))
        self.assertEqual(code, 1)
        self.assertEqual(len(said), 1)
        self.assertTrue(said[0].startswith("Another copy of clark is already open with different data"), said)
        self.assertEqual(self.windows(), before)
        self.assertEqual(len(self.processes), 1)

    def test_a_program_that_is_not_clark_is_never_taken_over(self):
        for how in ("ok-only", "html", "404", "big", "slow", "string"):
            with self.subTest(how=how):
                self.stand_in(how)
                self.assert_not_clark()
                s = self.listeners.pop()
                s.shutdown()
                s.server_close()

    def test_a_program_that_accepts_and_never_answers_is_not_clark(self):
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", self.port))
        s.listen(5)
        self.listeners.append(s)
        self.assert_not_clark()


if __name__ == "__main__":
    unittest.main()
