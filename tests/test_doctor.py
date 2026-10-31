"""#57: the doctor (src/clark/doctor.py, python3 -m clark.doctor).

Run: python3 dev/run_tests.py test_doctor
Everything it looks at is a fake or a temporary folder: a temporary home folder (so "OneDrive" is a folder made there), a fake
browser finder, a fake Claude finder and a fake answer for what is on the port. No real OneDrive, no browser is opened, and
nothing is asked over the network. Each check's ready and fix words are checked, and the exit code.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _paths import ROOT

from clark import doctor, launch, platform as pl


class DoctorCase(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="clark-home-")).resolve()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.app = self.home / "Documents" / "clark"
        self.app.mkdir(parents=True)

    def seams(self, **over):
        """A Mac where everything is ready, unless `over` says otherwise."""
        seams = dict(on=pl.MAC, home=self.home, environ={}, app=self.app, version=(3, 9, 6), sqlite_version="3.37.0",
                     find_chrome=lambda: "/fictional/chrome", find_claude=lambda: "/fictional/bin/claude",
                     health=lambda port, mark: launch.NOTHING, free=lambda port: False)
        seams.update(over)
        return seams

    def run_doctor(self, argv=(), **over):
        lines = []
        code = doctor.main(list(argv), say=lines.append, **self.seams(**over))
        return code, lines

    def line(self, lines, start):
        found = [line for line in lines if line.startswith(start)]
        self.assertEqual(len(found), 1, lines)
        return found[0]

    def onedrive(self, name="OneDrive-Fictional Ltd"):
        root = self.home / "Library" / "CloudStorage" / name
        root.mkdir(parents=True)
        return root


class AllReady(DoctorCase):
    def test_every_check_ready_exit_0(self):
        code, lines = self.run_doctor()
        self.assertEqual(code, 0, lines)
        self.assertEqual(lines[0], "Checking what clark needs on this computer...")
        self.assertEqual(lines[-1], "Everything clark needs is ready.")
        self.assertEqual(len(lines), 2 + len(doctor.CHECKS))
        self.assertTrue(all(line.startswith("Ready: ") for line in lines[1:-1]), lines)
        self.assertIn("Ready: Python 3.9.6 is ready.", lines)
        self.assertIn("Ready: Your clark data can be saved in ~/Library/Application Support/clark.", lines)
        self.assertIn("Ready: Your clark data isn't inside OneDrive.", lines)
        self.assertIn("Ready: Your clark folder isn't in OneDrive.", lines)
        self.assertIn("Ready: Chrome is there, so clark opens in its own window.", lines)
        self.assertIn("Ready: Nothing else on this computer is in the way of clark starting.", lines)
        self.assertIn("Ready: Claude Code is installed, so you can ask clark for help.", lines)

    def test_it_makes_no_data_folder(self):
        self.run_doctor()
        self.assertFalse((self.home / "Library" / "Application Support").exists())

    def test_no_account_folder_is_shown(self):
        code, lines = self.run_doctor()
        self.assertNotIn(str(self.home), "\n".join(lines))


class Python(DoctorCase):
    def test_too_old_on_the_mac(self):
        code, lines = self.run_doctor(version=(3, 8, 9))
        self.assertEqual(code, 1)
        self.assertEqual(self.line(lines, "To fix: This Mac's"),
                         "To fix: This Mac's Python (3.8.9) is too old for clark. Type xcode-select --install in Terminal, "
                         "then start clark again.")
        self.assertEqual(lines[-1], "1 thing to fix before clark can start. Fix it, then run python3 -m clark.doctor again.")

    def test_too_old_on_windows_says_download_again(self):
        code, lines = self.run_doctor(version=(3, 8, 0), on=pl.WINDOWS)
        self.assertEqual(code, 1)
        self.line(lines, "To fix: The Python inside clark's folder is missing or too old. Download clark again.")

    def test_no_sqlite(self):
        code, lines = self.run_doctor(sqlite_version="")
        self.assertEqual(code, 1)
        self.assertEqual(self.line(lines, "To fix: This Python"),
                         "To fix: This Python can't keep clark's data. Install a full copy of Python from python.org, then start clark again.")

    def test_no_sqlite_on_windows_says_download_again(self):
        code, lines = self.run_doctor(sqlite_version="", on=pl.WINDOWS, find_chrome=None)
        self.assertEqual(code, 1)
        self.line(lines, "To fix: The Python inside clark's folder can't keep clark's data. Download clark again.")
        self.assertNotIn("SQLite", "\n".join(lines))

    def test_the_real_python_is_ready(self):
        line = doctor.check_python(doctor.Seen(on=pl.MAC))
        self.assertEqual(line.kind, doctor.READY, line)


class DataFolder(DoctorCase):
    def test_a_folder_that_exists_and_can_be_saved_in(self):
        data = self.home / "data"
        data.mkdir()
        code, lines = self.run_doctor(["--data", str(data)])
        self.assertEqual(code, 0, lines)
        self.line(lines, "Ready: Your clark data can be saved in ~/data.")
        self.assertEqual(os.listdir(data), [], "the test file is removed")

    def test_a_file_where_the_folder_should_be(self):
        (self.home / "data").write_bytes(b"")
        code, lines = self.run_doctor(["--data", str(self.home / "data")])
        self.assertEqual(code, 1)
        self.assertEqual(self.line(lines, "To fix: Your clark data"),
                         "To fix: Your clark data can't be saved in ~/data. Check you can save files there, then start "
                         "clark again.")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can save anywhere")
    def test_a_folder_that_cant_be_saved_in(self):
        locked = self.home / "locked"
        locked.mkdir()
        locked.chmod(0o500)
        self.addCleanup(locked.chmod, 0o700)
        code, lines = self.run_doctor(["--data", str(locked / "clark")])
        self.assertEqual(code, 1)
        self.line(lines, "To fix: Your clark data can't be saved in ~/locked/clark.")

    def test_a_data_folder_inside_onedrive(self):
        root = self.onedrive()
        code, lines = self.run_doctor(["--data", str(root / "clark")])
        self.assertEqual(code, 1)
        self.assertEqual(self.line(lines, "To fix: Your clark data is set to go"),
                         "To fix: Your clark data is set to go in ~/Library/CloudStorage/OneDrive-Fictional Ltd/clark, which "
                         "is inside OneDrive. OneDrive copies files while they are being written, which damages the data. "
                         "Choose a folder on this computer that OneDrive doesn't sync. Then, in the Terminal window that "
                         "START-HERE.txt describes, type python3 -m clark --data and that folder's name, and press Return. "
                         "Backups can still go to OneDrive.")
        self.assertNotIn("(OneDrive-Fictional Ltd)", "\n".join(lines), "the OneDrive folder's own name isn't said")


class AppFolder(DoctorCase):
    def test_windows_says_file_explorer(self):
        with mock.patch.object(pl, "onedrive_roots", return_value=[self.onedrive()]):
            line = doctor.check_app_folder(doctor.Seen(on=pl.WINDOWS, home=self.home, app=self.home / "Library" / "CloudStorage"
                                                       / "OneDrive-Fictional Ltd" / "clark"))
        self.assertEqual(line.words, "Your clark folder is in OneDrive. In File Explorer, set it to 'Always keep on this "
                                     "device' so its files are always there.")

    def test_in_onedrive_is_advice_not_a_fault(self):
        app = self.onedrive() / "clark"
        app.mkdir()
        code, lines = self.run_doctor(app=app)
        self.assertEqual(code, 0, lines)
        self.assertEqual(self.line(lines, "Worth knowing: Your clark folder"),
                         "Worth knowing: Your clark folder is in OneDrive. In Finder, set it to 'Always keep on this "
                         "device' so its files are always there.")
        self.assertEqual(lines[-1], "Everything clark needs is ready.")


class Browser(DoctorCase):
    def test_no_chrome_is_advice(self):
        code, lines = self.run_doctor(find_chrome=lambda: None)
        self.assertEqual(code, 0, lines)
        self.assertEqual(self.line(lines, "Worth knowing: Chrome"),
                         "Worth knowing: Chrome wasn't found, so clark will open in your usual browser. Install Chrome to "
                         "give clark its own window.")

    def test_the_named_browser_is_used_on_the_mac(self):
        stub = self.home / "browser"
        stub.write_bytes(b"")
        code, lines = self.run_doctor(find_chrome=None, environ={"CLARK_BROWSER": str(stub)})
        self.line(lines, "Ready: Chrome is there")


class Port(DoctorCase):
    def test_another_program(self):
        asked = []
        with mock.patch.object(pl, "launcher_name", return_value="clark.command"):
            code, lines = self.run_doctor(["--port", "8799"], health=lambda port, mark: asked.append((port, mark)) or launch.NOT_CLARK)
        self.assertEqual(code, 1)
        self.assertEqual(asked[0][0], 8799)
        self.line(lines, "To fix: "
                         "Nothing was started: clark is already open in another Terminal window, or another program is using the connection it needs. Close that Terminal window or program, then double-click clark.command again. If that does not help, restart your Mac.")

    def test_another_copy_with_other_data(self):
        with mock.patch.object(Path, "home", return_value=self.home):        # launch.report writes ~ for the real home
            code, lines = self.run_doctor(health=lambda port, mark: launch.OTHER_DATA)
        self.assertEqual(code, 1)
        self.line(lines, "To fix: Another copy of clark is already open with different data (this one uses "
                         "~/Library/Application Support/clark). Close that copy, then start clark again.")

    def test_the_try_another_line_stays_on_the_same_line(self):
        with mock.patch.object(pl, "launcher_name", return_value="clark.command"):
            code, lines = self.run_doctor(health=lambda port, mark: launch.NOT_CLARK, free=lambda port: True)
        line = self.line(lines, "To fix: Nothing was started")
        self.assertIn(" If you can't close it, open Terminal in the clark folder and type: ./clark.command --port ", line)
        self.assertNotIn("\n", line)

    def test_ours_already_running_is_ready(self):
        code, lines = self.run_doctor(health=lambda port, mark: launch.OURS)
        self.assertEqual(code, 0, lines)
        self.line(lines, "Ready: Your clark is already running with this data.")

    def test_the_mark_is_this_data_folders(self):
        from clark import appfiles
        asked = []
        self.run_doctor(health=lambda port, mark: asked.append(mark) or launch.NOTHING)
        self.assertEqual(asked, [appfiles.data_mark(self.home / "Library" / "Application Support" / "clark")])

    def test_the_port_setting_is_used_and_a_bad_one_said_plainly(self):
        asked = []
        self.run_doctor(environ={"CLARK_PORT": "8801"}, health=lambda port, mark: asked.append(port) or launch.NOTHING)
        self.assertEqual(asked, [8801])
        code, lines = self.run_doctor(["--port", "abc"])
        self.assertEqual(code, 1)
        self.assertEqual(self.line(lines, "To fix: The start-up number"),
                         "To fix: The start-up number (set with --port) must be a whole number from 1 to 65535. Change it, "
                         "then run python3 -m clark.doctor again.")
        code, lines = self.run_doctor(environ={"CLARK_PORT": "70000"})
        self.assertEqual(code, 1)
        self.line(lines, "To fix: The start-up number (set with CLARK_PORT) must be a whole number from 1 to 65535.")


class Claude(DoctorCase):
    def test_not_found_is_advice(self):
        code, lines = self.run_doctor(find_claude=lambda: None)
        self.assertEqual(code, 0, lines)
        self.assertEqual(self.line(lines, "Worth knowing: Claude Code"),
                         "Worth knowing: Claude Code wasn't found, so ask clark can't run. The rest of clark works without "
                         "it. To use ask clark, install Claude Code, then start clark again.")

    def test_a_cmd_file_is_refused_as_advice(self):
        code, lines = self.run_doctor(find_claude=lambda: pl.find_claude(lambda name: "C:/Tools/claude.cmd"))
        self.assertEqual(code, 0, lines)
        self.assertEqual(self.line(lines, "Worth knowing: The copy of Claude Code"),
                         "Worth knowing: The copy of Claude Code on this computer can't be used safely by ask clark. Install "
                         "Claude Code's own app (claude.exe), then start clark again.")
        self.assertNotIn("C:/Tools", "\n".join(lines))


class NotBuiltYet(DoctorCase):
    """A system whose platform branch isn't written: it says so, never crashes, and the exit code is 1."""

    def test_windows_says_each_check_isnt_available_yet(self):
        code, lines = self.run_doctor(on=pl.WINDOWS, find_chrome=None)
        self.assertEqual(code, 1)
        for start in ("The data folder check", "The OneDrive check for your data", "The OneDrive check for the clark folder",
                      "The browser check"):
            self.line(lines, f"Not checked: {start} can't run on this computer yet.")
        self.assertEqual(lines[-1], "Some checks can't run on this computer yet, so we can't say whether clark will start. "
                                    "Try starting it; if it won't, tell the clark team.")

    def test_only_onedrive_unknown_with_a_given_folder(self):
        data = self.home / "data"
        code, lines = self.run_doctor(["--data", str(data)], on=pl.WINDOWS, find_chrome=None)
        self.line(lines, "Ready: Your clark data can be saved in ~/data.")
        self.line(lines, "Not checked: The OneDrive check for your data can't run on this computer yet.")
        self.assertEqual(code, 1)

    def test_a_check_that_stops_is_said_plainly(self):
        def broken():
            raise ValueError("fictional failure in ~/secret-folder")
        code, lines = self.run_doctor(find_claude=broken)
        self.assertEqual(self.line(lines, "Not checked: The Claude Code check"),
                         "Not checked: The Claude Code check couldn't finish. Run python3 -m clark.doctor again.")
        self.assertNotIn("fictional", "\n".join(lines))
        self.assertNotIn("ValueError", "\n".join(lines))
        self.assertEqual(code, 0, "an advice check that stops doesn't fail the doctor")

    def test_a_required_check_that_stops_fails_it(self):
        def broken(port, mark):
            raise OSError("fictional")
        code, lines = self.run_doctor(health=broken)
        self.assertEqual(code, 1)
        self.line(lines, "Not checked: The check that nothing is in the way couldn't finish. Run python3 -m clark.doctor again.")
        self.assertNotIn("fictional", "\n".join(lines))

    def test_the_whole_doctor_failing_is_one_line(self):
        with mock.patch.object(doctor, "doctor", side_effect=RuntimeError("fictional failure in ~/secret-folder")):
            lines = []
            code = doctor.main([], say=lines.append)
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["The checks stopped before the end. Run python3 -m clark.doctor again; if it keeps happening, tell the clark "
                                 "team."])
        self.assertNotIn("Traceback", lines[0])


class Words(DoctorCase):
    """Every line a person reads follows the product rules."""

    def every_line(self):
        out = []
        root = self.onedrive()
        for over in ({}, dict(version=(3, 8, 0)), dict(sqlite_version=""), dict(find_chrome=lambda: None),
                     dict(find_claude=lambda: None), dict(health=lambda p, m: launch.NOT_CLARK),
                     dict(health=lambda p, m: launch.OTHER_DATA), dict(app=root), dict(on=pl.WINDOWS, find_chrome=None)):
            out += self.run_doctor(**over)[1]
        out += self.run_doctor(["--data", str(root / "x")])[1]
        out += self.run_doctor(["--port", "0"])[1]
        out += self.run_doctor(find_claude=lambda: pl.find_claude(lambda name: "C:/Tools/claude.cmd"))[1]
        out += self.run_doctor(health=lambda p, m: 1 / 0)[1]
        return out

    def test_clark_is_lower_case_and_never_starts_a_line(self):
        lines = self.every_line()
        for line in lines:
            words = line.split(": ", 1)[-1] if line.split(":", 1)[0] + ":" in doctor.LABELS.values() else line
            self.assertFalse(line.lower().startswith("clark") or words.lower().startswith("clark"), line)
            self.assertNotIn("Clark", line)
            self.assertNotIn("Ask clark", line)

    def test_no_exclamation_marks_and_no_system_words(self):
        for line in self.every_line():
            self.assertNotIn("!", line)
            for word in ("SQLite", "port setting", "this system", "Traceback", "Error"):
                self.assertNotIn(word, line)

    def test_two_failures_are_counted(self):
        with mock.patch.object(pl, "launcher_name", return_value="clark.command"):
            code, lines = self.run_doctor(version=(3, 8, 0), health=lambda p, m: launch.NOT_CLARK)
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1], "2 things to fix before clark can start. Fix each one, then run python3 -m clark.doctor again.")


class FromTheTopFolder(unittest.TestCase):
    """`python3 -m clark.doctor` from the repo's top folder reaches src/clark/doctor.py through the clark/ stand-in."""

    def test_help(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "CLARK_PORT")}
            env.update(HOME=tmp, PYTHONDONTWRITEBYTECODE="1")
            done = subprocess.run([sys.executable, "-m", "clark.doctor", "--help"], cwd=str(ROOT), env=env,
                                  capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("Check what clark needs on this computer, and say what to do.", done.stdout)
            self.assertEqual(" ".join(done.stdout.split()).count("can include the names of folders"), 1, done.stdout)
            self.assertEqual(os.listdir(tmp), [])


if __name__ == "__main__":
    unittest.main()
