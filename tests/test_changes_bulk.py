"""#196 stage 1: a bulk change, the same field change to several work items in one step with one Undo (clark.changes, op "bulk").

Run: python3 dev/run_tests.py test_changes_bulk
Pure Python over a real demo store (fictional data): one step and one Undo for every item, all or none, each item's history
written as a single edit writes it, items that can't take the change left out and named, the confirm above 25, and hostile
requests refused with nothing written.
"""
import json
import sqlite3
import unittest
from unittest import mock

from _demo import USER, DemoStore
from clark import changes, server as sv
from clark import store as clark_store


class Bulk(unittest.TestCase):
    def setUp(self):
        self.demo = DemoStore()
        self.addCleanup(self.demo.close)
        self.s = self.demo.store
        self.change = changes.make_change(self.s.path, [], USER)
        self.undo = changes.make_undo(self.s.path, [], USER)
        self.actions = [self.demo.action(owner="Ada Quillfeather", priority="High", status="Open") for _ in range(3)]
        with self.s.step("dashboard", USER) as st:
            self.risks = [st.create("raid", {"project": "ABC", "type": "Risk", "description": "Supplier late", "impact": "Low",
                                             "likelihood": "Low", "raised": "2026-10-01", "source": "demo"}) for _ in range(2)]
            self.decisions = [st.create("decisions", {"project": "ABC", "decision": "Go", "made_by": "Board", "status": "Pending",
                                                      "source": "demo"}) for _ in range(2)]
            st.create("projects", {"code": "XYZ", "name": "Other Programme", "health": "On track"})

    # ---- helpers ----
    def send(self, kind, ids, changes_, **more):
        return self.change({"project": "ABC", "kind": kind, "op": "bulk", "ids": ids, "changes": changes_, **more})

    def counts(self):
        con = sqlite3.connect(str(self.s.path))
        try:
            return con.execute("SELECT (SELECT count(*) FROM applies), (SELECT count(*) FROM change_log), "
                               "(SELECT count(*) FROM item_events)").fetchone()
        finally:
            con.close()

    def value(self, table, ref, field):
        return self.s.read(table, ref=ref)[field]

    def refused(self, kind, ids, changes_, words, status=400, **more):
        before = self.counts()
        got, body = self.send(kind, ids, changes_, **more)
        self.assertEqual((got, body["ok"], body["message"]), (status, False, words), body)
        self.assertEqual(self.counts(), before, "nothing was written")
        return body

    def steps(self):
        return self.counts()[0]

    # ---- one step, one undo ----
    def test_one_change_to_three_actions_is_one_step_with_a_history_line_per_item(self):
        before = self.steps()
        status, body = self.send("actions", self.actions, {"owner": "Zelda Quince"})
        self.assertEqual((status, body["ok"], body["changed"], body["left_out"], body["unchanged"]), (200, True, self.actions, [], []), body)
        self.assertEqual(self.steps(), before + 1, "one step for every item")
        self.assertTrue(body["undoable"])
        self.assertEqual(body["words"], "Changed 3 items.")
        for ref in self.actions:
            self.assertEqual(self.value("actions", ref, "owner"), "Zelda Quince")
            owner = [e for e in self.s.history(ref) if e["field"] == "owner" and e["step"] == body["apply_id"]]
            self.assertEqual(len(owner), 1, ref)
            self.assertEqual((owner[0]["before"], owner[0]["after"], owner[0]["route"], owner[0]["place"], owner[0]["by_user"]),
                             ("Ada Quillfeather", "Zelda Quince", "dashboard", "bulk", USER))
        self.assertEqual({i["id"]: i["owner"] for i in body["items"]}, {r: "Zelda Quince" for r in self.actions})
        self.assertNotIn("description", body["items"][0], "a title is never said back")

    def test_one_undo_puts_every_item_back_and_says_so(self):
        _, body = self.send("actions", self.actions, {"owner": "Zelda Quince", "priority": "Low"})
        status, undone = self.undo({"project": "ABC", "apply_id": body["apply_id"]})
        self.assertEqual((status, undone["ok"], undone["skipped"]), (200, True, []), undone)
        for ref in self.actions:
            self.assertEqual((self.value("actions", ref, "owner"), self.value("actions", ref, "priority")), ("Ada Quillfeather", "High"))
        self.assertEqual(undone["words"], "Put back: 6 changes to the work items.")
        again = self.undo({"project": "ABC", "apply_id": body["apply_id"]})
        self.assertEqual((again[0], again[1]["code"]), (409, "undone"))

    def test_the_undo_of_the_undo_puts_the_whole_batch_back_in_one_step(self):
        _, body = self.send("actions", self.actions, {"owner": "Zelda Quince"})
        _, undone = self.undo({"project": "ABC", "apply_id": body["apply_id"]})
        refused = self.undo({"project": "ABC", "apply_id": undone["apply_id"]})
        self.assertEqual((refused[0], refused[1]["message"]), (400, changes.NO_UNDO), "the page never undoes an undo, as for one edit")
        before = self.steps()
        redo = self.s.undo(undone["apply_id"], USER)
        self.assertEqual((len(redo["reversed"]), redo["skipped"], self.steps()), (3, [], before + 1))
        for ref in self.actions:
            self.assertEqual(self.value("actions", ref, "owner"), "Zelda Quince")

    def test_close_and_reopen_set_and_clear_the_closing_date_and_undo_together(self):
        _, body = self.send("actions", self.actions, {"status": "Closed"})
        for ref in self.actions:
            self.assertEqual(self.value("actions", ref, "status"), "Closed")
            self.assertEqual(self.value("actions", ref, "closed"), clark_store.today())
        _, reopened = self.send("actions", self.actions, {"status": "Open"})
        self.assertEqual(reopened["changed"], self.actions)
        self.assertIsNone(self.value("actions", self.actions[0], "closed"))
        self.undo({"project": "ABC", "apply_id": reopened["apply_id"]})
        self.undo({"project": "ABC", "apply_id": body["apply_id"]})
        self.assertEqual([self.value("actions", r, "status") for r in self.actions], ["Open"] * 3)
        self.assertIsNone(self.value("actions", self.actions[0], "closed"))

    def test_a_risks_impact_works_out_its_priority_and_undo_puts_both_back(self):
        was = [self.value("raid", r, "priority") for r in self.risks]
        _, body = self.send("raid", self.risks, {"impact": "High", "likelihood": "High"})
        self.assertEqual(body["changed"], self.risks, body)
        self.assertEqual({i["priority"] for i in body["items"]}, {clark_store.priority("High", "High")})
        _, undone = self.undo({"project": "ABC", "apply_id": body["apply_id"]})
        self.assertTrue(undone["ok"], undone)
        self.assertEqual([self.value("raid", r, "priority") for r in self.risks], was)
        self.assertEqual([self.value("raid", r, "impact") for r in self.risks], ["Low", "Low"])

    def test_a_decision_takes_only_who_makes_it(self):
        _, body = self.send("decisions", self.decisions, {"made_by": "Steering group"})
        self.assertEqual(body["changed"], self.decisions, body)
        for field, words in (("workstream", changes.NO_DECISION_FIELD["workstream"]), ("priority", changes.NO_DECISION_FIELD["priority"]),
                             ("status", "The field 'status' can't be set here."), ("owner", "The field 'owner' can't be set here.")):
            with self.subTest(field=field):
                self.refused("decisions", self.decisions, {field: "Made"}, words)

    def test_a_made_or_withdrawn_decision_keeps_who_made_it(self):
        with self.s.step("dashboard", USER) as st:
            made = st.create("decisions", {"project": "ABC", "decision": "Go", "made_by": "Board", "status": "Made", "date": "2026-10-01", "source": "demo"})
            withdrawn = st.create("decisions", {"project": "ABC", "decision": "Stop", "made_by": "Board", "status": "Withdrawn", "source": "demo"})
        pending = self.decisions[0]
        status, body = self.send("decisions", [made, pending, withdrawn], {"made_by": "Steering group"})
        self.assertEqual((status, body["changed"]), (200, [pending]), body)
        self.assertEqual(body["left_out"], [{"id": made, "why": changes.BULK_DECIDED}, {"id": withdrawn, "why": changes.BULK_DECIDED}])
        self.assertEqual([self.value("decisions", r, "made_by") for r in (made, pending, withdrawn)], ["Board", "Steering group", "Board"])
        body = self.refused("decisions", [made, withdrawn], {"made_by": "Someone else"}, changes.BULK_DECIDED)
        self.assertEqual((body["code"], len(body["left_out"])), ("none_can", 2))
        self.assertEqual([self.value("decisions", r, "made_by") for r in (made, withdrawn)], ["Board", "Board"])

    def test_reopen_of_a_closed_item_still_works(self):
        self.send("actions", self.actions, {"status": "Closed"})
        _, body = self.send("actions", self.actions, {"status": "Open"})
        self.assertEqual(body["changed"], self.actions, body)
        self.assertEqual([self.value("actions", r, "status") for r in self.actions], ["Open"] * 3)

    def test_workstream_and_milestone_reach_every_item(self):
        _, body = self.send("actions", self.actions, {"workstream": "Build", "milestone": self.demo.milestone, "due_date": "2030-01-15"})
        self.assertEqual(body["changed"], self.actions, body)
        self.assertEqual({self.value("actions", r, "milestone") for r in self.actions}, {self.demo.milestone})

    def test_one_safety_copy_at_most(self):
        folder = self.s.path.parent / "backups"
        had = len(list(folder.glob("*"))) if folder.is_dir() else 0
        self.send("actions", self.actions, {"owner": "Zelda Quince"})
        now = len(list(folder.glob("*"))) if folder.is_dir() else 0
        self.assertLessEqual(now - had, 1)

    # ---- all or none ----
    def test_a_refusal_while_writing_leaves_every_item_as_it_was(self):
        real = clark_store.Step.update
        calls = []

        def failing(st, kind, ref, changes_, **kw):
            calls.append(ref)
            if len(calls) == len(self.actions) + 2:                  # the second item of the real step, after the trial of all three
                raise clark_store.Invalid("owner must be one of nobody")
            return real(st, kind, ref, changes_, **kw)
        before = self.counts()
        with mock.patch.object(clark_store.Step, "update", failing):
            status, body = self.send("actions", self.actions, {"owner": "Zelda Quince"})
        self.assertEqual((status, body["message"]), (400, changes.STALE), body)
        self.assertEqual(self.counts(), before)
        self.assertEqual([self.value("actions", r, "owner") for r in self.actions], ["Ada Quillfeather"] * 3)

    def test_a_fault_while_writing_rolls_the_whole_step_back(self):
        real = clark_store.Step.update
        calls = []

        def broken(st, kind, ref, changes_, **kw):
            calls.append(ref)
            out = real(st, kind, ref, changes_, **kw)
            if len(calls) == len(self.actions) * 2:                  # after the last item of the real step was written
                raise RuntimeError("disk gone")
            return out
        before = self.counts()
        with mock.patch.object(clark_store.Step, "update", broken), self.assertRaises(RuntimeError):
            self.send("actions", self.actions, {"owner": "Zelda Quince"})
        self.assertEqual(self.counts(), before)
        self.assertEqual([self.value("actions", r, "owner") for r in self.actions], ["Ada Quillfeather"] * 3)

    def test_an_item_that_has_the_value_by_the_write_is_not_said_to_have_changed(self):
        real = clark_store.Step.update
        calls = []

        def same_by_then(st, kind, ref, changes_, **kw):
            calls.append(ref)
            if len(calls) == len(self.actions) + 1:                  # the first item of the real step: it has the value by now, so nothing is written
                return ref
            return real(st, kind, ref, changes_, **kw)
        with mock.patch.object(clark_store.Step, "update", same_by_then):
            status, body = self.send("actions", self.actions, {"owner": "Zelda Quince"})
        self.assertEqual((status, body["changed"], body["unchanged"]), (200, self.actions[1:], self.actions[:1]), body)
        self.assertEqual(body["words"], "Changed 2 items. 1 already had that.")
        self.assertEqual([i["id"] for i in body["items"]], self.actions[1:])

    def test_the_trial_never_writes(self):
        before = self.counts()
        self.send("actions", self.actions + ["ABC-A-901"], {"owner": "Ada Quillfeather"})
        self.assertEqual(self.counts(), before)

    # ---- left out and named ----
    def test_items_that_cannot_take_it_are_left_out_and_named(self):
        archived, late = self.demo.action(), self.demo.action(raised="2099-01-01")
        with self.s.step("dashboard", USER) as st:
            st.archive("actions", archived)
        gone = "ABC-A-900"
        status, body = self.send("actions", self.actions + [archived, late, gone], {"status": "Closed"})
        self.assertEqual((status, body["changed"]), (200, self.actions), body)
        self.assertEqual(body["left_out"], [{"id": archived, "why": changes.BULK_ARCHIVED}, {"id": late, "why": changes.BEFORE_RAISED},
                                            {"id": gone, "why": changes.BULK_GONE}])
        self.assertEqual(body["words"], f"Changed 3 items. Left out {archived}: {changes.BULK_ARCHIVED} Left out {late}: "
                                        f"{changes.BEFORE_RAISED} Left out {gone}: {changes.BULK_GONE}")
        self.assertEqual((self.value("actions", archived, "status"), self.value("actions", late, "status")), ("Open", "Open"))

    def test_more_than_three_left_out_are_counted(self):
        self.assertEqual(changes._bulk_words(["a"], [], [{"id": f"ABC-A-90{i}", "why": "Gone."} for i in range(5)]),
                         "Changed 1 item. Left out ABC-A-900: Gone. Left out ABC-A-901: Gone. Left out ABC-A-902: Gone. 2 more were left out.")

    def test_nothing_saves_when_none_can_take_it(self):
        body = self.refused("actions", self.actions, {"workstream": "No such stream"}, changes.NO_WORKSTREAM)
        self.assertEqual((body["code"], [e["id"] for e in body["left_out"]]), ("none_can", self.actions))
        archived = self.demo.action()
        with self.s.step("dashboard", USER) as st:
            st.archive("actions", archived)
        body = self.refused("actions", [archived, "ABC-A-901"], {"owner": "Zelda Quince"}, changes.BULK_NONE_CAN)
        self.assertEqual(len(body["left_out"]), 2)

    def test_nothing_changed_when_they_already_have_it(self):
        before = self.counts()
        status, body = self.send("actions", self.actions, {"owner": "Ada Quillfeather"})
        self.assertEqual((status, body["ok"], body["apply_id"], body["undoable"], body["words"]),
                         (200, True, None, False, changes.BULK_ALREADY), body)
        self.assertEqual(body["unchanged"], self.actions)
        self.assertEqual(self.counts(), before)
        status, body = self.send("actions", self.actions + ["ABC-A-901"], {"owner": "Ada Quillfeather"})
        self.assertEqual(body["words"], f"{changes.BULK_ALREADY} Left out ABC-A-901: {changes.BULK_GONE}")

    def test_some_already_have_it(self):
        self.demo.update("actions", self.actions[0], {"owner": "Zelda Quince"})
        _, body = self.send("actions", self.actions, {"owner": "Zelda Quince"})
        self.assertEqual((body["changed"], body["unchanged"], body["words"]),
                         (self.actions[1:], self.actions[:1], "Changed 2 items. 1 already had that."))

    # ---- refused whole ----
    def test_mixed_kinds_and_projects_are_refused_in_the_issues_words(self):
        self.refused("actions", self.actions + self.risks[:1], {"owner": "Zelda Quince"}, changes.BULK_KINDS)
        self.refused("actions", self.actions + [self.decisions[0]], {"owner": "Zelda Quince"}, changes.BULK_KINDS)
        self.refused("actions", self.actions + ["XYZ-A-001"], {"owner": "Zelda Quince"}, changes.BULK_PROJECTS)
        self.refused("actions", self.actions + [self.demo.milestone], {"owner": "Zelda Quince"}, changes.BULK_KINDS)
        self.assertEqual(changes.BULK_KINDS, "These items are of different kinds.")
        self.assertEqual(changes.BULK_PROJECTS, "These items are in different projects.")

    def test_an_archived_project_changes_nothing(self):
        with self.s.step("dashboard", USER) as st:
            st.archive("projects", "ABC")
        self.refused("actions", self.actions, {"owner": "Zelda Quince"}, changes.PROJECT_NOT_ACTIVE)

    def test_hostile_requests_write_nothing(self):
        many = [f"ABC-A-{i % 999 + 1:03d}" for i in range(changes.MAX_BULK + 1)]
        for ids, words in (([], changes.BULK_NOTHING), ("ABC-A-001", changes.BULK_NOTHING), (None, changes.BULK_NOTHING),
                           (many, changes.BULK_TOO_MANY), ([1, 2], changes.ITEM_NOT_MINE), ([["ABC-A-001"]], changes.ITEM_NOT_MINE),
                           (["ABC-A-001; DROP TABLE actions"], changes.ITEM_NOT_MINE), (["ABC-A-١٢٣"], changes.ITEM_NOT_MINE),
                           (["abc-a-001"], changes.ITEM_NOT_MINE), (["ABC-A-001\ud800"], changes.ITEM_NOT_MINE),
                           (["ABC-A-001", "ABC-W-001"], changes.BULK_KINDS)):
            with self.subTest(ids=str(ids)[:40]):
                self.refused("actions", ids, {"owner": "Zelda Quince"}, words)
        for changes_, words in (({}, "Say what to change."), (None, "Say what to change."), (["owner"], "Send the changes as an object."),
                                ({"owner": None}, changes.ITEM_VALUE_WORDS), ({"owner": "A\nB"}, changes.ITEM_TEXT_WORDS),
                                ({"owner": "x" * 201}, changes.ITEM_VALUE_WORDS), ({"owner": 3}, changes.ITEM_VALUE_WORDS),
                                ({"status": "Done"}, changes.NOT_A_STATUS), ({"priority": "Huge"}, changes.NOT_A_CHOICE),
                                ({"archived": 1}, changes.NO_ARCHIVE), ({"description": "New"}, "The field 'description' can't be set here."),
                                ({"use_case": self.demo.use_case}, "The field 'use_case' can't be set here."),
                                ({"project": "XYZ"}, "The field 'project' can't be set here."), ({"type": "Risk"}, changes.ITEM_KEEPS_TYPE)):
            with self.subTest(changes=str(changes_)[:40]):
                self.refused("actions", self.actions, changes_, words)
        self.refused("raid", self.risks, {"priority": "High"}, changes.NO_RAID_PRIORITY)
        self.refused("actions", self.actions, {"owner": "Zelda Quince"}, changes.BULK_CONFIRM, confirm="yes")
        self.refused("actions", self.actions, {"owner": "Zelda Quince"}, changes.BAD_PLACE, place="attic")
        before = self.counts()
        status, body = self.change({"project": "ABC", "kind": "actions", "op": "bulk", "ids": self.actions, "changes": {"owner": "Z"}, "id": "x"})
        self.assertEqual((status, body["message"]), (400, "That change doesn't take 'id'."))
        for kind in ("milestones", "use_cases", "report_sections", "projects"):
            with self.subTest(kind=kind):
                status, body = self.change({"project": "ABC", "kind": kind, "op": "bulk", "ids": self.actions, "changes": {"owner": "Z"}})
                self.assertEqual((status, body["message"]), (400, changes.BAD_OP))
        self.assertEqual(self.counts(), before)

    def test_duplicate_ids_count_once(self):
        _, body = self.send("actions", self.actions + self.actions[::-1], {"owner": "Zelda Quince"})
        self.assertEqual((body["changed"], body["unchanged"], body["words"]), (self.actions, [], "Changed 3 items."))
        own =[e for e in self.s.history(self.actions[0]) if e["field"] == "owner" and e["step"] == body["apply_id"]]
        self.assertEqual(len(own), 1)

    def test_the_place_is_kept_as_sent_or_bulk(self):
        _, body = self.send("actions", self.actions, {"owner": "Zelda Quince"}, place="board")
        self.assertEqual({e["place"] for e in self.s.history(self.actions[0]) if e["step"] == body["apply_id"]}, {"board"})

    # ---- the confirm above 25 ----
    def test_the_confirm_counts_the_whole_request_at_25_and_26(self):
        more = self.actions + [self.demo.action(owner="Ada Quillfeather") for _ in range(22)]
        self.assertEqual(len(more), 25)
        status, body = self.send("actions", more, {"owner": "Zelda Quince"})
        self.assertEqual((status, len(body["changed"])), (200, 25), "25 needs no confirm")
        archived = self.demo.action()
        with self.s.step("dashboard", USER) as st:
            st.archive("actions", archived)
        body = self.refused("actions", more + [archived], {"owner": "Ada Quillfeather"}, "Change 26 items?", status=409)
        self.assertEqual((body["code"], body["count"]), ("confirm", 26), "an item that will be left out still counts")
        status, body = self.send("actions", more + [archived], {"owner": "Ada Quillfeather"}, confirm=True)
        self.assertEqual((status, len(body["changed"]), len(body["left_out"])), (200, 25, 1), body)
        self.assertEqual(changes.BULK_CONFIRM_ABOVE, 25)

    def test_the_largest_request_fits_the_routes_body_limit(self):
        req = {"project": "ABCDEFG", "kind": "actions", "op": "bulk", "ids": ["ABCDEFG-A-999"] * changes.MAX_BULK,
               "changes": {"owner": "x" * 200}, "confirm": True, "place": "bulk"}
        self.assertLess(len(json.dumps(req).encode()), sv.ROUTE_BODY_LIMITS["/api/change"])


if __name__ == "__main__":
    unittest.main()
