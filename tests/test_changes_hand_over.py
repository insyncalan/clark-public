"""#199: Hand over, a change of owner for work items of all three kinds together, in one step with one Undo (clark.changes, op "handover").

Run: python3 dev/run_tests.py test_changes_hand_over
Pure Python over a real demo store (fictional data): one step and one Undo for actions, risks and decisions together, one history
line per item, items that can't take it left out and named, the confirm above 25, and hostile requests refused with nothing
written.
"""
import json
import sqlite3
import unittest

from _demo import USER, DemoStore
from clark import changes, server as sv
from clark import store as clark_store


class HandOver(unittest.TestCase):
    def setUp(self):
        self.demo = DemoStore()
        self.addCleanup(self.demo.close)
        self.s = self.demo.store
        self.change = changes.make_change(self.s.path, [], USER)
        self.undo = changes.make_undo(self.s.path, [], USER)
        self.actions = [self.demo.action(owner="Ada Quillfeather") for _ in range(2)]
        with self.s.step("dashboard", USER) as st:
            self.risks = [st.create("raid", {"project": "ABC", "type": "Risk", "description": "Supplier late", "impact": "Low",
                                             "likelihood": "Low", "raised": "2026-10-01", "owner": "Ada Quillfeather", "source": "demo"})]
            self.decisions = [st.create("decisions", {"project": "ABC", "decision": "Go", "made_by": "Ada Quillfeather",
                                                      "status": "Pending", "source": "demo"})]
            st.create("projects", {"code": "XYZ", "name": "Other Programme", "health": "On track"})
        self.all = self.actions + self.risks + self.decisions

    def send(self, ids, to="Zelda Quince", **more):
        return self.change({"project": "ABC", "kind": "actions", "op": "handover", "ids": ids, "to": to, **more})

    def counts(self):
        con = sqlite3.connect(str(self.s.path))
        try:
            return con.execute("SELECT (SELECT count(*) FROM applies), (SELECT count(*) FROM change_log), "
                               "(SELECT count(*) FROM item_events)").fetchone()
        finally:
            con.close()

    def who(self, ref):
        table = clark_store.item_table(ref)
        return self.s.read(table, ref=ref)[changes.HAND_OVER_FIELD[table]]

    def refused(self, ids, words, status=400, to="Zelda Quince", **more):
        before = self.counts()
        got, body = self.send(ids, to, **more)
        self.assertEqual((got, body["ok"], body["message"]), (status, False, words), body)
        self.assertEqual(self.counts(), before, "nothing was written")
        return body

    def test_actions_a_risk_and_a_decision_move_in_one_step_with_one_history_line_each(self):
        before = self.counts()[0]
        status, body = self.send(self.all)
        self.assertEqual((status, body["ok"], body["changed"], body["left_out"], body["unchanged"]), (200, True, self.all, [], []), body)
        self.assertEqual((self.counts()[0], body["undoable"], body["words"]), (before + 1, True, "Changed 4 items."))
        for ref in self.all:
            self.assertEqual(self.who(ref), "Zelda Quince", ref)
            line = [e for e in self.s.history(ref) if e["step"] == body["apply_id"]]
            self.assertEqual(len(line), 1, ref)
            self.assertEqual((line[0]["before"], line[0]["after"], line[0]["place"], line[0]["by_user"]), ("Ada Quillfeather", "Zelda Quince", "bulk", USER))
        self.assertEqual({i["id"] for i in body["items"]}, set(self.all))

    def test_one_undo_puts_every_owner_back(self):
        _, body = self.send(self.all)
        status, undone = self.undo({"project": "ABC", "apply_id": body["apply_id"]})
        self.assertEqual((status, undone["ok"], undone["skipped"]), (200, True, []), undone)
        self.assertEqual({self.who(r) for r in self.all}, {"Ada Quillfeather"})

    def test_only_the_owner_changes(self):
        row = self.s.read("actions", ref=self.actions[0])
        self.send(self.all)
        now = self.s.read("actions", ref=self.actions[0])
        skip = ("owner", "updated_at")
        self.assertEqual({k: v for k, v in now.items() if k not in skip}, {k: v for k, v in row.items() if k not in skip})

    def test_items_that_cannot_take_it_are_left_out_and_named(self):
        archived = self.demo.action()
        with self.s.step("dashboard", USER) as st:
            st.archive("actions", archived)
        gone = "ABC-A-900"
        status, body = self.send(self.all + [archived, gone])
        self.assertEqual((status, body["changed"]), (200, self.all), body)
        self.assertEqual(body["left_out"], [{"id": archived, "why": changes.BULK_ARCHIVED}, {"id": gone, "why": changes.BULK_GONE}])
        self.assertIn(f"Left out {archived}: {changes.BULK_ARCHIVED}", body["words"])
        self.assertEqual(self.s.read("actions", ref=archived)["owner"], "TBC")

    def test_nothing_saves_when_none_can_take_it_or_they_have_it_already(self):
        self.refused(["ABC-A-900"], changes.BULK_GONE)
        self.send(self.all)
        before = self.counts()
        status, body = self.send(self.all)
        self.assertEqual((status, body["apply_id"], body["changed"], body["unchanged"], body["words"]), (200, None, [], self.all, changes.BULK_ALREADY))
        self.assertEqual(self.counts(), before)

    def test_hostile_requests_write_nothing(self):
        many = [f"ABC-A-{i % 999 + 1:03d}" for i in range(changes.MAX_BULK + 1)]
        for ids, words in (([], changes.BULK_NOTHING), ("ABC-A-001", changes.BULK_NOTHING), (None, changes.BULK_NOTHING),
                           (many, changes.BULK_TOO_MANY), ([1], changes.ITEM_NOT_MINE), (["ABC-A-001; DROP TABLE actions"], changes.ITEM_NOT_MINE),
                           (["ABC-W-001"], changes.ITEM_NOT_MINE), (["XYZ-A-001"], changes.BULK_PROJECTS)):
            with self.subTest(ids=str(ids)[:40]):
                self.refused(ids, words)
        for to, words in ((None, changes.ITEM_VALUE_WORDS), ("", changes.ITEM_VALUE_WORDS), ("  ", changes.ITEM_VALUE_WORDS),
                          ("A\nB", changes.ITEM_TEXT_WORDS), ("x" * 201, changes.ITEM_VALUE_WORDS), (3, changes.ITEM_VALUE_WORDS)):
            with self.subTest(to=str(to)[:20]):
                self.refused(self.all, words, to=to)
        self.refused(self.all, changes.BULK_CONFIRM, confirm="yes")
        before = self.counts()
        status, body = self.change({"project": "ABC", "kind": "actions", "op": "handover", "ids": self.all, "to": "Z", "changes": {"status": "Closed"}})
        self.assertEqual((status, body["message"]), (400, "That change doesn't take 'changes'."))
        for kind in ("milestones", "use_cases", "report_sections", "projects"):
            with self.subTest(kind=kind):
                status, body = self.change({"project": "ABC", "kind": kind, "op": "handover", "ids": self.all, "to": "Z"})
                self.assertEqual((status, body["message"]), (400, changes.BAD_OP))
        self.assertEqual(self.counts(), before)

    def test_an_archived_project_changes_nothing(self):
        with self.s.step("dashboard", USER) as st:
            st.archive("projects", "ABC")
        self.refused(self.all, changes.PROJECT_NOT_ACTIVE)

    def test_the_confirm_counts_the_whole_request_at_25_and_26(self):
        more = self.actions + [self.demo.action(owner="Ada Quillfeather") for _ in range(23)]
        self.assertEqual(len(more), 25)
        status, body = self.send(more)
        self.assertEqual((status, len(body["changed"])), (200, 25), "25 needs no confirm")
        more.append(self.risks[0])
        body = self.refused(more, "Change 26 items?", status=409, to="Ada Quillfeather")
        self.assertEqual((body["code"], body["count"]), ("confirm", 26))
        status, body = self.send(more, "Ada Quillfeather", confirm=True)
        self.assertEqual((status, len(body["changed"]), body["unchanged"]), (200, 25, self.risks), body)     # the risk had that owner already

    def test_the_largest_request_fits_the_routes_body_limit(self):
        req = {"project": "ABCDEFG", "kind": "actions", "op": "handover", "ids": ["ABCDEFG-A-999"] * changes.MAX_BULK,
               "to": "x" * 200, "confirm": True, "place": "bulk"}
        self.assertLess(len(json.dumps(req).encode()), sv.ROUTE_BODY_LIMITS["/api/change"])


if __name__ == "__main__":
    unittest.main()
