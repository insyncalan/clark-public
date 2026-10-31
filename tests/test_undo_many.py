"""#197: Undo several changes at once (stage one: the store and the request behind it). A preview lists each change that will
be undone and each that will be left, with a plain reason; one new step then undoes them all, newest first, and is itself
undone by one Undo. Hostile requests are refused with nothing written.

Run: python3 dev/run_tests.py test_undo_many
Each test makes a real store in a temporary folder with fictional data.
"""
import json
import sqlite3
import unittest
from unittest import mock

from _demo import USER, DemoStore
from clark import changes, store as store_module
from clark.store import BATCH_UNDO, MAX_UNDO_MANY, Invalid, reverted_rowids


def dump(path):
    """Every row of the database, as text: two equal dumps mean nothing at all was written."""
    con = sqlite3.connect(str(path))
    try:
        return "\n".join(con.iterdump())
    finally:
        con.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.demo = DemoStore()
        self.addCleanup(self.demo.close)
        self.s = self.demo.store
        self.undo = changes.make_undo(self.s.path, [], USER)
        self.change = changes.make_change(self.s.path, [], USER)

    def edit(self, ref, kind="actions", project="ABC", **fields):
        """One change from the page: one step, as the table makes it."""
        status, body = self.change({"project": project, "kind": kind, "op": "update", "id": ref, "changes": fields,
                                    "place": "cell"})
        self.assertEqual(status, 200, body)
        return body["apply_id"]

    def add(self, description="Draft the cut-over plan"):
        """A new action from the page: one step."""
        status, body = self.change({"project": "ABC", "kind": "actions", "op": "new", "values": {"description": description},
                                    "place": "report"})
        self.assertEqual(status, 200, body)
        return body["ref"], body["apply_id"]

    def many(self, steps, **more):
        return self.undo({"project": "ABC", "steps": steps, **more})

    def action(self, ref):
        return self.s.read("actions", ref=ref)


class Store(Base):
    """The writer: Store.undo_many."""

    def test_the_preview_is_the_same_run_and_writes_nothing(self):
        a, made = self.add()
        b = self.edit(a, owner="Sam Example")
        c = self.edit(a, priority="High")
        before = dump(self.s.path)
        preview = self.s.undo_many([made, b, c], USER, dry=True)
        self.assertEqual(dump(self.s.path), before)
        self.assertIsNone(preview["step_id"])
        real = self.s.undo_many([made, b, c], USER)
        strip = lambda out: [(e["step"], e["ref"], e["field"], e.get("change")) for e in out["reversed"]]      # noqa: E731
        self.assertEqual(strip(preview), strip(real))
        self.assertEqual(preview["skipped"], real["skipped"])

    def test_one_new_step_undoes_them_all_newest_first(self):
        a = self.demo.action()
        b = self.edit(a, owner="Sam Example")
        c = self.edit(a, owner="Kim Example")                       # the same field twice: undone in turn, newest first
        d = self.edit(a, priority="High")
        steps_before = self.s.con.execute("SELECT count(*) FROM applies").fetchone()[0]
        out = self.s.undo_many([b, d, c], USER)
        self.assertEqual(self.s.con.execute("SELECT count(*) FROM applies").fetchone()[0], steps_before + 1, "one history entry")
        self.assertEqual([e["step"] for e in out["reversed"]], sorted([e["step"] for e in out["reversed"]], reverse=True))
        self.assertEqual((self.action(a)["owner"], self.action(a)["priority"]), ("TBC", "Medium"))
        rows = self.s.con.execute("SELECT via FROM change_log WHERE apply_id = ?", (out["step_id"],)).fetchall()
        self.assertTrue(rows and all(r[0].startswith("revert:") for r in rows))
        refs = {r[0] for r in self.s.con.execute("SELECT DISTINCT src_ref FROM item_events WHERE apply_id = ?", (out["step_id"],))}
        self.assertEqual(refs, {BATCH_UNDO})
        self.assertEqual(self.s.batch_undo_steps(out["step_id"]), [b, c, d])

    def test_a_creation_and_the_changes_after_it_go_back_together_and_come_back_together(self):
        a, made = self.add()
        b = self.edit(a, owner="Sam Example")
        c = self.edit(a, due_date="2030-01-02")
        out = self.s.undo_many([made, b, c], USER)
        self.assertEqual(out["skipped"], [])
        self.assertIsNone(self.action(a))
        back = self.s.undo(out["step_id"], USER)                    # the toast's Undo of the batch
        self.assertEqual(back["skipped"], [])
        row = self.action(a)
        self.assertEqual((row["owner"], row["due_date"]), ("Sam Example", "2030-01-02"), "every change is back, not just the row")
        self.assertIsNotNone(self.s.con.execute("SELECT undone_at FROM applies WHERE apply_id = ?", (out["step_id"],)).fetchone()[0])
        self.assertFalse({r for r in reverted_rowids(self.s.con)} & {r[0] for r in self.s.con.execute(
            "SELECT rowid FROM change_log WHERE apply_id IN (?, ?, ?)", (made, b, c))})
        with self.assertRaises(Invalid):
            self.s.undo(back["step_id"], USER)                      # an undo of the undo of the undo: never

    def test_one_at_a_time_a_creation_can_be_undone_after_its_changes_are(self):
        a, made = self.add()
        b = self.edit(a, owner="Sam Example")
        self.s.undo(b, USER)
        out = self.s.undo(made, USER)
        self.assertEqual(out["skipped"], [], "the change's own time stamp does not block it")
        self.assertIsNone(self.action(a))

    def test_a_later_change_not_chosen_leaves_its_item_as_it_is(self):
        a = self.demo.action()
        b = self.edit(a, owner="Sam Example")
        self.edit(a, owner="Kim Example")                           # later, not chosen
        out = self.s.undo_many([b], USER)
        self.assertIsNone(out["step_id"])
        self.assertEqual(self.action(a)["owner"], "Kim Example")
        self.assertTrue(out["skipped"] and out["skipped"][0]["by_step"])

    def test_already_undone_an_undo_and_an_archived_item_are_skipped_not_refused(self):
        a = self.demo.action()
        x = self.demo.action(description="Book the venue")
        b = self.edit(a, owner="Sam Example")
        u = self.s.undo(b, USER)["step_id"]
        c = self.edit(x, owner="Sam Example")
        with self.s.step("dashboard", USER) as st:
            st.archive("actions", x)
        d = self.edit(a, priority="High")
        out = self.s.undo_many([b, u, c, d], USER)
        whys = {e["step"]: e["why"] for e in out["skipped"]}
        self.assertEqual(whys[b], "already undone")
        self.assertEqual(whys[u], "is an undo")
        self.assertIn("is archived", whys[c])
        self.assertEqual([e["step"] for e in out["reversed"]], [d])
        self.assertEqual(self.action(x)["owner"], "Sam Example")

    def test_an_unknown_step_refuses_the_whole_batch_and_nothing_is_written(self):
        a = self.demo.action()
        b = self.edit(a, owner="Sam Example")
        before = dump(self.s.path)
        with self.assertRaises(Invalid):
            self.s.undo_many([b, 999999], USER)                     # the unknown one is the newest: b is never reached
        self.assertEqual(dump(self.s.path), before)

    def test_a_fault_part_way_leaves_nothing_changed(self):
        a = self.demo.action()
        b = self.edit(a, owner="Sam Example")
        c = self.edit(a, priority="High")
        before = dump(self.s.path)
        real, calls = store_module.revert_plan, []

        def second_fails(*args, **kw):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("disk gone")
            return real(*args, **kw)
        with mock.patch.object(store_module, "revert_plan", second_fails):
            with self.assertRaises(RuntimeError):
                self.s.undo_many([b, c], USER)
        self.assertEqual(len(calls), 2)
        self.assertEqual(dump(self.s.path), before)

    def test_the_limit(self):
        with self.assertRaises(Invalid):
            self.s.undo_many([], USER)
        with self.assertRaisesRegex(Invalid, f"Choose 1 to {MAX_UNDO_MANY} "):
            self.s.undo_many(range(1, MAX_UNDO_MANY + 2), USER)

    def test_a_step_that_wrote_nothing_is_not_there_to_undo(self):
        a = self.demo.action()
        b = self.edit(a, owner="Sam Example")
        self.s.con.execute("INSERT INTO applies (at, proposals, by_user, device) VALUES ('2026-10-01 09:00:00.000', '[]', 'x', 'y')")
        empty = self.demo.last_step()
        before = dump(self.s.path)
        with self.assertRaisesRegex(Invalid, "no step"):
            self.s.undo_many([b, empty], USER)
        self.assertEqual(dump(self.s.path), before)


class Request(Base):
    """POST /api/undo with `steps`: what the page sends, and what a hostile request gets."""

    def setUp(self):
        super().setUp()
        with self.s.step("dashboard", USER) as st:
            st.create("projects", {"code": "XYZ", "name": "Other Programme", "health": "On track"})
            self.theirs = st.create("actions", {"project": "XYZ", "description": "Theirs", "raised": "2026-10-01", "source": "demo"})
        self.a = self.demo.action()

    def refused(self, request, words, status=400):
        before = dump(self.s.path)
        got = self.undo(request)
        self.assertEqual((got[0], got[1]["ok"], got[1]["message"]), (status, False, words), request)
        self.assertEqual(dump(self.s.path), before, "nothing was written")
        return got[1]

    def test_preview_then_undo_then_undo_the_undo(self):
        b = self.edit(self.a, owner="Sam Example")
        c = self.edit(self.a, priority="High")
        before = dump(self.s.path)
        status, preview = self.many([b, c], preview=True)
        self.assertEqual((status, preview["preview"], preview["apply_id"]), (200, True, None), preview)
        self.assertEqual(dump(self.s.path), before, "a preview writes nothing")
        self.assertEqual([(e["step"], e["field"]) for e in preview["undo"]], [(c, "priority"), (b, "owner")])
        self.assertEqual(preview["words"], "2 changes will be undone.")
        status, done = self.many([b, c])
        self.assertEqual((status, done["preview"]), (200, False), done)
        self.assertEqual((self.action(self.a)["owner"], self.action(self.a)["priority"]), ("TBC", "Medium"))
        self.assertEqual(done["words"], "Undone: 2 changes.")
        status, back = self.undo({"project": "ABC", "apply_id": done["apply_id"]})      # the toast's Undo
        self.assertEqual(status, 200, back)
        self.assertEqual((self.action(self.a)["owner"], self.action(self.a)["priority"]), ("Sam Example", "High"))
        status, again = self.undo({"project": "ABC", "apply_id": back["apply_id"]})
        self.assertEqual((status, again["message"]), (400, changes.NO_UNDO))
        self.assertEqual(self.action(self.a)["owner"], "Sam Example")

    def test_skipped_changes_say_why_in_plain_words(self):
        x = self.demo.action(description="Book the venue")
        y = self.demo.action(description="Order the badges")
        later = self.edit(self.a, owner="Sam Example")
        self.edit(self.a, owner="Kim Example")                      # later, not chosen
        undone = self.edit(y, owner="Sam Example")
        single = self.undo({"project": "ABC", "apply_id": undone})[1]["apply_id"]
        archived = self.edit(x, owner="Sam Example")
        self.assertEqual(self.change({"project": "ABC", "kind": "actions", "op": "archive", "id": x})[0], 200)
        elsewhere = self.demo.update("actions", y, {"priority": "High"})
        con = sqlite3.connect(str(self.s.path))
        con.execute("UPDATE change_log SET via = 'minutes' WHERE apply_id = ?", (elsewhere,))       # not a step of the page's
        con.commit()
        con.close()
        good = self.edit(y, due_date="2030-01-02")
        status, preview = self.many([later, undone, single, archived, elsewhere, good], preview=True)
        self.assertEqual(status, 200, preview)
        whys = {e["step"]: e["why"] for e in preview["skipped"]}
        self.assertEqual(whys, {later: changes.CHANGED_SINCE, undone: changes.UNDONE_ALREADY, single: changes.IS_AN_UNDO,
                                archived: changes.ARCHIVED_NOW, elsewhere: changes.NOT_FROM_HERE})
        self.assertEqual([e["step"] for e in preview["undo"]], [good])
        self.assertEqual(preview["words"], "1 change will be undone. 5 will be left as they are.")
        for line in preview["skipped"] + preview["undo"]:
            self.assertNotIn("_", line["field"], line)              # a field as a person reads it, never its stored name

    def test_a_decision_that_is_made_is_left_with_its_reason(self):
        with self.s.step("dashboard", USER) as st:
            d = st.create("decisions", {"project": "ABC", "decision": "Use the new tool", "status": "Pending",
                                        "needed_by": "2030-01-05", "source": "demo"})
        self.edit(d, kind="decisions", status="Made", date="2026-10-02")    # the page offers no Undo for it
        made = self.demo.last_step()
        b = self.edit(self.a, owner="Sam Example")
        status, preview = self.many([made, b], preview=True)
        self.assertEqual(status, 200, preview)
        self.assertEqual({e["step"]: e["why"] for e in preview["skipped"]}, {made: changes.MADE_CANT_BE_PUT_BACK})

    def test_a_creation_and_its_changes_from_the_page(self):
        ref, made = self.add()
        b = self.edit(ref, owner="Sam Example")
        status, done = self.many([made, b])
        self.assertEqual(status, 200, done)
        self.assertIsNone(self.action(ref))
        self.assertIn({"step": made, "ref": ref, "field": "", "change": "removed"}, done["undo"])
        self.assertEqual(len([e for e in done["undo"] if e["step"] == made]), 1, "one line for the item made, not one per column")

    def test_a_change_to_several_items_in_one_step_is_one_change_and_one_undo(self):
        x = self.demo.action(description="Book the venue")
        with self.s.step("dashboard", USER, place="bulk") as st:      # as a bulk change writes it: one step for every item
            st.update("actions", self.a, {"owner": "Sam Example"})
            st.update("actions", x, {"owner": "Sam Example"})
        bulk = self.demo.last_step()
        b = self.edit(self.a, priority="High")
        status, done = self.many([bulk, b])
        self.assertEqual((status, done["count"]), (200, 2), done)
        self.assertEqual(sorted(e["ref"] for e in done["undo"] if e["step"] == bulk), sorted([self.a, x]))
        self.assertEqual([self.action(r)["owner"] for r in (self.a, x)], ["TBC", "TBC"])
        status, back = self.undo({"project": "ABC", "apply_id": done["apply_id"]})
        self.assertEqual(status, 200, back)
        self.assertEqual([self.action(r)["owner"] for r in (self.a, x)], ["Sam Example", "Sam Example"])
        self.assertEqual(self.action(self.a)["priority"], "High")

    def test_a_step_left_out_whole_is_named_by_this_projects_row_and_never_anothers(self):
        with self.s.step("dashboard", USER) as st:
            st.create("projects", {"code": "DEF", "name": "Third Programme", "health": "On track"})
        with self.s.step("excel", USER) as st:                          # another project's row first, then this one's
            st.create("actions", {"project": "DEF", "description": "Theirs", "raised": "2026-10-01", "source": "demo"})
            mine = st.create("actions", {"project": "ABC", "description": "Ours", "raised": "2026-10-01", "source": "demo"})
        mixed = self.demo.last_step()
        b = self.edit(self.a, owner="Sam Example")
        for preview in (True, False):
            with self.subTest(preview=preview):
                status, body = self.many([mixed, b], preview=preview)
                self.assertEqual(status, 200, body)
                self.assertEqual(body["skipped"], [{"step": mixed, "ref": mine, "field": "", "why": changes.NOT_FROM_HERE}])
                text = json.dumps(body)
                for other in ("DEF", "XYZ", '"field": "id"'):
                    self.assertNotIn(other, text, "nothing of another project, and no stored field name")
                self.assertEqual([e["step"] for e in body["undo"]], [b])

    def test_duplicates_count_once(self):
        b = self.edit(self.a, owner="Sam Example")
        status, done = self.many([b, b, b])
        self.assertEqual((status, done["count"], len(done["undo"])), (200, 1, 1), done)

    def test_hostile_requests_are_refused_and_write_nothing(self):
        b = self.edit(self.a, owner="Sam Example")
        theirs = self.edit(self.theirs, project="XYZ", owner="Sam Example")
        cases = (
            ({"project": "ABC", "steps": []}, changes.MANY_NONE),
            ({"project": "ABC", "steps": "1,2"}, changes.MANY_NONE),
            ({"project": "ABC", "steps": None}, changes.MANY_NONE),
            ({"project": "ABC", "steps": [b, 999999]}, changes.MANY_NOT_MINE),
            ({"project": "ABC", "steps": [b, theirs]}, changes.MANY_NOT_MINE),      # another project's: the same words
            ({"project": "ABC", "steps": [b, True]}, changes.MANY_NOT_MINE),
            ({"project": "ABC", "steps": [b, "2"]}, changes.MANY_NOT_MINE),
            ({"project": "ABC", "steps": [b, -1]}, changes.MANY_NOT_MINE),
            ({"project": "ABC", "steps": [b, 0]}, changes.MANY_NOT_MINE),
            ({"project": "ABC", "steps": [b, 2 ** 63]}, changes.MANY_NOT_MINE),
            ({"project": "ABC", "steps": [b, 1.0]}, changes.MANY_NOT_MINE),
            ({"project": "ABC", "steps": list(range(1, MAX_UNDO_MANY + 2))}, changes.MANY_TOO_MANY),
            ({"project": "ABC", "steps": [b] * (MAX_UNDO_MANY * 2 + 1)}, changes.MANY_TOO_MANY),
            ({"project": "ABC", "steps": [b], "preview": "yes"}, changes.MANY_BAD_FLAG),
            ({"project": "ABC", "steps": [b], "confirm": 1}, changes.MANY_BAD_FLAG),
            ({"project": "ABC", "steps": [b], "table": "actions"}, "clark doesn't know 'table' in that request."),
            ({"project": "abc", "steps": [b]}, changes.BAD_PROJECT),
            ({"project": "XYZ", "steps": [b]}, changes.MANY_NOT_MINE),
        )
        for request, words in cases:
            with self.subTest(request=str(request)[:80]):
                self.refused(request, words)
        self.refused({"project": "QRS", "steps": [b]}, changes.NO_PROJECT, 404)
        self.assertEqual(self.action(self.a)["owner"], "Sam Example")

    def test_the_second_confirm_above_twenty_five(self):
        steps = [self.edit(self.a, owner=f"Person {n}") for n in range(26)]
        status, preview = self.many(steps[1:], preview=True)
        self.assertEqual((status, preview["count"], preview["needs_confirm"]), (200, 25, False))
        status, preview = self.many(steps, preview=True)
        self.assertEqual((status, preview["count"], preview["needs_confirm"]), (200, 26, True))
        self.refused({"project": "ABC", "steps": steps}, changes.MANY_CONFIRM.format(n=26), 409)
        self.refused({"project": "ABC", "steps": steps, "confirm": False}, changes.MANY_CONFIRM.format(n=26), 409)
        status, done = self.many(steps, confirm=True)
        self.assertEqual((status, len(done["undo"])), (200, 26), done)
        self.assertEqual(self.action(self.a)["owner"], "TBC")

    def test_twenty_five_need_no_confirm(self):
        steps = [self.edit(self.a, owner=f"Person {n}") for n in range(25)]
        status, done = self.many(steps)
        self.assertEqual(status, 200, done)
        self.assertEqual(self.action(self.a)["owner"], "TBC")

    def test_nothing_to_undo_is_said_plainly(self):
        b = self.edit(self.a, owner="Sam Example")
        self.edit(self.a, owner="Kim Example")
        self.refused({"project": "ABC", "steps": [b]}, changes.MANY_NOTHING, 409)
        status, preview = self.many([b], preview=True)
        self.assertEqual((status, preview["undo"], len(preview["skipped"])), (200, [], 1))

    def test_a_batch_of_another_project_is_not_undone_from_here(self):
        theirs = self.edit(self.theirs, project="XYZ", owner="Sam Example")
        status, done = self.undo({"project": "XYZ", "steps": [theirs]})
        self.assertEqual(status, 200, done)
        status, body = self.undo({"project": "ABC", "apply_id": done["apply_id"]})
        self.assertEqual((status, body["message"]), (400, changes.NO_UNDO))
        self.assertEqual(self.s.read("actions", ref=self.theirs)["owner"], "TBC")

    def test_a_single_undo_is_still_not_undone_from_here(self):
        b = self.edit(self.a, owner="Sam Example")
        single = self.undo({"project": "ABC", "apply_id": b})[1]["apply_id"]
        status, body = self.undo({"project": "ABC", "apply_id": single})
        self.assertEqual((status, body["message"]), (400, changes.NO_UNDO))

    def test_plain_words(self):
        for name in ("MANY_NONE", "MANY_TOO_MANY", "MANY_NOT_MINE", "MANY_CONFIRM", "MANY_NOTHING", "MANY_BAD_FLAG", "IS_AN_UNDO",
                     "UNDONE_ALREADY", "NOT_FROM_HERE", "ARCHIVED_NOW", "CHANGED_SINCE"):
            words = getattr(changes, name)
            with self.subTest(name=name):
                self.assertTrue(words[0].isupper() and words.endswith("."), words)
                for jargon in ("step", "apply", "id ", "rowid", "revert", "batch", "_", "!"):
                    self.assertNotIn(jargon, words.lower())


if __name__ == "__main__":
    unittest.main()
