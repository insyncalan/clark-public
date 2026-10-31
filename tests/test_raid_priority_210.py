"""#210: a risk's or an issue's Priority cell changes its impact or its likelihood (the two the priority is worked out from), one
step with Undo, through the same change route as every other cell (src/clark/changes.py). The priority itself is still never
set by hand, and a decision still has none.

Run: cd tests && PYTHONPATH=../src python3 test_raid_priority_210.py
Each test makes a real store in a temporary folder (fictional data) and calls the same functions the server calls.
"""
import sqlite3
import unittest

from _demo import USER
from clark import changes, history
from test_changes import Api


class RaidPriority(Api):
    def setUp(self):
        super().setUp()
        self.a = self.demo.action(owner="Sam Reed")
        with self.s.step("dashboard", USER) as st:
            self.r = st.create("raid", {"project": "ABC", "type": "Risk", "description": "Supplier slips", "impact": "High",
                                        "likelihood": "Medium", "raised": "2026-10-01", "source": "demo"})
            self.i = st.create("raid", {"project": "ABC", "type": "Issue", "description": "Test kit late", "impact": "Low",
                                        "likelihood": "Low", "raised": "2026-10-01", "source": "demo"})
            self.d = st.create("decisions", {"project": "ABC", "decision": "Use the new tool", "status": "Pending",
                                             "needed_by": "2030-01-05", "source": "demo"})
            st.create("projects", {"code": "XYZ", "name": "Other Programme", "health": "On track"})
            self.xr = st.create("raid", {"project": "XYZ", "type": "Risk", "description": "Theirs", "impact": "Low",
                                         "likelihood": "Low", "raised": "2026-10-01", "source": "demo"})

    def item(self, kind, ref, project="ABC", **changes_):
        return {"project": project, "kind": kind, "op": changes.UPDATE, "id": ref, "changes": changes_, "place": "cell"}

    def go(self, kind, ref, **changes_):
        status, body = self.change(self.item(kind, ref, **changes_))
        self.assertEqual((status, body.get("message")), (200, None), body)
        return body

    def snap(self):
        con = sqlite3.connect(str(self.path))
        try:
            return (con.execute("SELECT group_concat(id || impact || likelihood || priority || updated_at) FROM raid").fetchone()[0],
                    con.execute("SELECT count(*) FROM applies").fetchone()[0], con.execute("SELECT count(*) FROM change_log").fetchone()[0])
        finally:
            con.close()

    def no(self, request, words):
        before = self.snap()
        got = self.change(request)
        self.assertEqual((got[0], got[1]["ok"], got[1]["message"]), (400, False, words), request)
        self.assertEqual(self.snap(), before, "nothing was written")

    def raid(self, ref):
        r = self.s.read("raid", ref=ref)
        return r["impact"], r["likelihood"], r["priority"]

    def test_impact_is_one_step_and_the_reply_carries_the_new_worked_out_priority(self):
        self.assertEqual(self.raid(self.r), ("High", "Medium", "High"))
        steps = self.snap()[1]
        body = self.go("raid", self.r, impact="Low")
        self.assertTrue(body["undoable"])
        self.assertEqual(self.snap()[1], steps + 1, "one change is one step")
        self.assertEqual(self.raid(self.r), ("Low", "Medium", "Medium"), "the store works the priority out again")
        self.assertEqual({k: body["item"][k] for k in ("id", "impact", "likelihood", "priority")},
                         {"id": self.r, "impact": "Low", "likelihood": "Medium", "priority": "Medium"}, "the cell redraws from the reply")

    def test_likelihood_on_an_issue_too(self):
        body = self.go("raid", self.i, likelihood="High")
        self.assertEqual(self.raid(self.i), ("Low", "High", "High"))
        self.assertEqual(body["item"]["priority"], "High")

    def test_undo_puts_back_the_field_and_the_priority_it_gave(self):
        step = self.go("raid", self.r, likelihood="High")["apply_id"]
        self.assertEqual(self.raid(self.r), ("High", "High", "Urgent"))
        status, back = self.undone(step)
        self.assertEqual(status, 200, back)
        self.assertEqual(self.raid(self.r), ("High", "Medium", "High"), "impact, likelihood and priority are as they were")
        self.assertIn(f"the likelihood of {self.r} is back to Medium", back["words"])
        step = self.go("raid", self.r, impact="Medium")["apply_id"]
        self.assertEqual(self.raid(self.r), ("Medium", "Medium", "Medium"))
        self.assertEqual(self.undone(step)[0], 200)
        self.assertEqual(self.raid(self.r), ("High", "Medium", "High"))

    def test_a_value_that_isnt_high_medium_or_low_is_refused(self):
        for bad in ("Critical", "high", "Urgent", " "):
            with self.subTest(bad=bad):
                self.no(self.item("raid", self.r, impact=bad), changes.ITEM_VALUE_WORDS if not bad.strip() else changes.NOT_A_CHOICE)
                self.no(self.item("raid", self.r, likelihood=bad), changes.ITEM_VALUE_WORDS if not bad.strip() else changes.NOT_A_CHOICE)
        for bad in (None, 3, True, ["High"]):
            with self.subTest(bad=bad):
                self.no(self.item("raid", self.r, impact=bad), changes.ITEM_VALUE_WORDS)
                self.no(self.item("raid", self.r, likelihood=bad), changes.ITEM_VALUE_WORDS)

    def test_another_projects_risk_is_refused(self):
        self.no(self.item("raid", self.xr, impact="High"), changes.ITEM_NOT_MINE)
        self.assertEqual(self.raid(self.xr), ("Low", "Low", "Low"))

    def test_the_wrong_kind_is_refused_and_the_priority_still_cant_be_set_by_hand(self):
        self.no(self.item("actions", self.a, impact="High"), "The field 'impact' can't be set here.")
        self.no(self.item("actions", self.a, likelihood="High"), "The field 'likelihood' can't be set here.")
        self.no(self.item("decisions", self.d, impact="High"), "The field 'impact' can't be set here.")
        self.no(self.item("raid", self.r, priority="Low"), changes.NO_RAID_PRIORITY)
        self.no(self.item("raid", self.r, impact="Low", priority="Low"), changes.NO_RAID_PRIORITY)
        self.no(self.item("decisions", self.d, priority="High"), "A decision has no priority.")
        self.no(self.item("actions", self.r, impact="Low"), "The field 'impact' can't be set here.")

    def test_the_history_says_who_how_and_when(self):
        self.go("raid", self.r, impact="Low")
        rows = [r for r in history.rows_for_item(self.s.con, self.r) if r["kind"] == "Changed" and r["field"] == "Impact"]
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual((row["who"], row["how"]), (USER, "In the table"))
        self.assertTrue(row["when"], "when it was made")
        self.assertEqual((row["from"], row["to"]), ("High", "Low"))
        pri = [r for r in history.rows_for_item(self.s.con, self.r) if r["kind"] == "Changed" and r["field"] == "Priority"]
        self.assertEqual([(r["from"], r["to"]) for r in pri], [("High", "Medium")], "the worked-out priority is in the history too")


if __name__ == "__main__":
    unittest.main()
