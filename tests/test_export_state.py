"""#181: the Excel export's record file (excel-export-state.json) stays small. A record made by the same bytes is not written
again; no project keeps more than KEEP_NEWEST bytes-keyed records (the newest by export time) and the age rule still applies; a
record under a path (what an import leaves) is never removed here. Fictional data. Run: python3 dev/run_tests.py test_export_state"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _paths  # noqa: F401
from clark import excel, platform


def record(project, exported, tag="x"):
    return {"exported_at": f"{exported} 09:00:00", "hash": tag, "imported_hash": None, "project": project, "rows": {"actions": {"A-1": {"x": tag}}}}


class State(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.state = Path(self.dir.name) / excel.STATE_FILE

    def books(self):
        return json.loads(self.state.read_text(encoding="utf-8"))["workbooks"]

    def sha(self, project):
        return sorted(k for k, v in self.books().items() if k.startswith("sha256:") and v["project"] == project)

    def test_the_same_record_again_writes_nothing(self):
        excel.save_state(self.state, "sha256:aa", record("ABC", "2026-10-28"))
        with mock.patch.object(platform, "write_file") as write:
            excel.save_state(self.state, "sha256:aa", record("ABC", "2026-10-28"))
            write.assert_not_called()
            excel.save_state(self.state, "sha256:aa", record("ABC", "2026-10-29"))           # another export time: it is written
            write.assert_called_once()

    def test_a_project_keeps_only_its_newest_records_and_another_projects_are_not_touched(self):
        for n in range(15):
            excel.save_state(self.state, f"sha256:a{n:02d}", record("ABC", f"2026-10-{10 + n:02d}", f"a{n}"))
        for n in range(3):
            excel.save_state(self.state, f"sha256:b{n:02d}", record("XYZ", f"2026-10-0{1 + n}", f"b{n}"))
        excel.prune_hash_records(self.state, "2026-10-28")
        self.assertEqual(len(self.sha("ABC")), excel.KEEP_NEWEST)
        self.assertEqual(self.sha("ABC"), [f"sha256:a{n:02d}" for n in range(5, 15)], "the newest ten")
        self.assertEqual(len(self.sha("XYZ")), 3)

    def test_the_age_rule_still_applies_and_a_path_record_is_never_removed(self):
        excel.save_state(self.state, "sha256:old", record("ABC", "2026-08-01"))
        excel.save_state(self.state, "sha256:new", record("ABC", "2026-10-27"))
        excel.save_state(self.state, "/folder/mine.xlsx", {**record("ABC", "2026-01-01"), "imported_hash": "z"})
        excel.prune_hash_records(self.state, "2026-10-28")
        self.assertEqual(self.sha("ABC"), ["sha256:new"])
        self.assertIn("/folder/mine.xlsx", self.books())

    def test_a_smaller_cap_keeps_that_many_and_never_none(self):
        for n in range(4):
            excel.save_state(self.state, f"sha256:{n}", record("ABC", f"2026-10-2{n}", str(n)))
        excel.prune_hash_records(self.state, "2026-10-28", keep_newest=2)
        self.assertEqual(self.sha("ABC"), ["sha256:2", "sha256:3"])
        excel.prune_hash_records(self.state, "2026-10-28", keep_newest=0)
        self.assertEqual(len(self.sha("ABC")), 1, "the newest is always kept")

    def test_two_records_made_in_the_same_second_are_cut_by_the_order_they_were_saved_in(self):
        for n in (5, 3, 9, 0, 7, 1, 8, 2, 11, 4, 10, 6):
            excel.save_state(self.state, f"sha256:{n:02d}", record("ABC", "2026-10-27", str(n)))
        excel.prune_hash_records(self.state, "2026-10-28")
        self.assertEqual(self.sha("ABC"), [f"sha256:{n:02d}" for n in sorted((9, 0, 7, 1, 8, 2, 11, 4, 10, 6))], "the first two saved are the ones that go")

    def test_the_record_just_written_is_kept_even_when_the_total_cap_would_cut_it(self):
        for n in range(31):
            excel.save_state(self.state, f"sha256:p{n}a", record(f"P{n:02d}", "2026-10-27", f"p{n}a"))
            excel.save_state(self.state, f"sha256:p{n}b", record(f"P{n:02d}", "2026-10-26", f"p{n}b"))
        excel.save_state(self.state, "sha256:mine", record("ABC", "2026-10-01", "mine"))
        excel.save_state(self.state, "sha256:abc", record("ABC", "2026-10-27", "abc"))
        excel.prune_hash_records(self.state, "2026-10-28")
        self.assertNotIn("sha256:mine", self.books(), "without keep it is the oldest and the total cap takes it")
        excel.save_state(self.state, "sha256:mine2", record("ABC", "2026-10-02", "mine2"))
        excel.prune_hash_records(self.state, "2026-10-28", keep="sha256:mine2")
        self.assertIn("sha256:mine2", self.books())
        self.assertIn("sha256:abc", self.books(), "each project's newest is exempt from the total cap")

    def test_ten_future_dated_records_rank_below_the_real_exports_made_today(self):
        for n in range(10):
            excel.save_state(self.state, f"sha256:f{n}", record("ABC", f"2027-01-0{n + 1}", f"f{n}"))
        excel.save_state(self.state, "sha256:r1", record("ABC", "2026-10-28", "r1"))
        excel.save_state(self.state, "sha256:r2", record("ABC", "2026-10-28", "r2"))
        excel.prune_hash_records(self.state, "2026-10-28", keep="sha256:r2")
        self.assertIn("sha256:r1", self.books(), "the earlier real export of today survives")
        self.assertIn("sha256:r2", self.books())
        self.assertEqual(len(self.sha("ABC")), excel.KEEP_NEWEST)

    def test_nothing_is_written_when_nothing_is_cut(self):
        excel.save_state(self.state, "sha256:aa", record("ABC", "2026-10-27"))
        with mock.patch.object(platform, "write_file") as write:
            excel.prune_hash_records(self.state, "2026-10-28")
            write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
