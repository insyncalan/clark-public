"""#201: the words a person reads when clark cannot start because its address is taken. Each message names the cause and one next
step in plain words; the server's line, the launcher's line and START-HERE agree on the cause; none starts with the product name
and none sends a person to restart the Mac. Run: python3 dev/run_tests.py test_launcher_words"""
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

import _paths  # noqa: F401
from _paths import ROOT, TOOLS
from clark import launch, platform, server

sys.path.insert(0, str(TOOLS))
import package  # noqa: E402

LAUNCHER = mock.patch.object(platform, "launcher_name", return_value="clark.command")      # the launcher's name is only known on a Mac


def setUpModule():
    LAUNCHER.start()


def tearDownModule():
    LAUNCHER.stop()


CAUSE = "clark is already open in another"
CAUSE_TAIL = "or another program is using the connection it needs"


class TheServersLine(unittest.TestCase):
    def test_words(self):
        self.assertEqual(server.PORT_TAKEN, "Nothing was started: clark is already open in another window, or another program is using the "
                                            "connection it needs. Close the other window or program, then start clark again.")


class TheLaunchersLine(unittest.TestCase):
    def say(self, free):
        return launch.report(launch.NOT_CLARK, 8800, Path("/tmp/clark-data"), free=free)

    def test_the_cause_and_the_one_next_step(self):
        text = self.say(lambda p: False)
        self.assertEqual(text, "Nothing was started: clark is already open in another Terminal window, or another program is using the "
                               f"connection it needs. Close that Terminal window or program, then double-click {platform.launcher_name()} again. If that does not help, restart your Mac.")

    def test_off_a_mac_the_line_still_reads_and_names_the_launcher_in_general_words(self):
        with mock.patch.object(platform, "launcher_name", side_effect=platform.NotBuiltYet("not built")):
            text = self.say(lambda p: False)
        self.assertIn("then double-click the clark launcher again.", text)

    def test_off_a_mac_a_free_port_nearby_and_either_kind_of_port_still_read_and_do_not_raise(self):
        with mock.patch.object(platform, "launcher_name", side_effect=platform.NotBuiltYet("not built")):
            for kind in (launch.NOT_CLARK, launch.OTHER_DATA):
                text = launch.report(kind, 8800, Path("/tmp/clark-data"), free=lambda p: p == 8801)
                self.assertTrue(text)
                self.assertNotIn("--port", text, "no command to type off a Mac")

    def test_the_step_covers_another_program_as_well_as_a_window(self):
        self.assertIn("Close that Terminal window or program, then double-click", self.say(lambda p: False))

    def test_a_free_port_is_only_a_second_line_for_a_person_who_cannot_close_the_other(self):
        text = self.say(lambda p: p == 8801)
        first, second = text.split("\n")
        self.assertEqual(first, self.say(lambda p: False))
        self.assertEqual(second, f"If you can't close it, open Terminal in the clark folder and type: ./{platform.launcher_name()} --port 8801")


class StartHere(unittest.TestCase):
    def test_the_paragraph(self):
        self.assertIn("If it says nothing was started because clark is already open in another\nTerminal window, or another program is using the "
                      "connection it needs, close\nthat Terminal window or program, then double-click clark.command again. If that\ndoes not help, restart your Mac.\n", package.START_HERE_MAC)


class TheyAgree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.LINES = (server.PORT_TAKEN, launch.report(launch.NOT_CLARK, 8800, Path("/tmp/clark-data"), free=lambda p: False),
                     " ".join(package.START_HERE_MAC.split()))

    def test_every_line_gives_the_same_cause(self):
        for text in self.LINES:
            flat = " ".join(text.split())
            self.assertIn(CAUSE, flat)
            self.assertIn(CAUSE_TAIL, flat)

    def test_none_starts_with_the_product_name_and_restart_your_mac_is_only_the_last_resort_of_the_two_double_click_lines(self):
        for text in self.LINES[:2]:
            self.assertFalse(text.lower().startswith("clark"), text)
        launcher_line = self.LINES[1]
        self.assertTrue(launcher_line.endswith("If that does not help, restart your Mac."), launcher_line)
        self.assertEqual(launcher_line.count("restart your Mac"), 1)
        self.assertNotIn("restart your Mac", server.PORT_TAKEN, "a person who runs clark from Terminal does not need it")
        start = " ".join(package.START_HERE_MAC.split())
        self.assertTrue(start.count("restart your Mac") == 1 and "If that does not help, restart your Mac." in start)
        for path in list((ROOT / "src").rglob("*.py")) + [TOOLS / "package.py"]:
            n = path.read_text(encoding="utf-8").count("restart your Mac")
            self.assertEqual(n, {"launch.py": 1, "package.py": 1}.get(path.name, 0), f"{path.name}: the last-resort line is in the launcher's line and START-HERE only")

    def test_the_old_vague_wording_is_gone(self):
        for path in list((ROOT / "src" / "clark").glob("*.py")) + [TOOLS / "package.py"]:
            text = path.read_text(encoding="utf-8")
            self.assertFalse(re.search(r"using what clark needs to start", text), path.name)


if __name__ == "__main__":
    unittest.main()
