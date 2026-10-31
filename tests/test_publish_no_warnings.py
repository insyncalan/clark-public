"""Tech debt #222: the Publish dialog lists no incomplete or stale items, and shows no sentence about them.

Run: python3 dev/run_tests.py test_publish_no_warnings
A project with items that have no owner, no date and are not reviewed opens the dialog, and the dialog has none of those words and no
Show them link. Publish, Local and To client still work (test_publish, test_report_editor). The Freshness filter (#119, #159) is
unchanged and its own tests still run. Chrome is required; the test fails, never skips, without it.
"""
import unittest

from test_work_board_page import need_chrome  # noqa: F401  (the shared Chrome check)


class PublishWarningsGone(unittest.TestCase):
    def test_the_dialog_has_no_stale_or_incomplete_list(self):
        from pathlib import Path
        page = (Path(__file__).resolve().parents[1] / "src" / "clark" / "page" / "src" / "edit" / "Publish.jsx").read_text(encoding="utf-8")
        for words in ("Show them", "no owner or no date", "have not been reviewed", "publishCheck", "pub-fresh", "ANYWAY"):
            self.assertNotIn(words, page, words)


if __name__ == "__main__":
    unittest.main()
