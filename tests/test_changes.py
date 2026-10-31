"""#65: what the page may change and undo (src/clark/changes.py; guarded): the allow-list, every refusal in plain words, each
kind of step with Undo and Undo of the Undo, and the checks that keep one project's request from touching another's.

Run: python3 dev/run_tests.py test_changes
Each test makes a real store in a temporary folder (fictional data) and calls the same functions the server calls.
"""
import ast
import json
import os
import sqlite3
import threading
import unittest
from unittest import mock

from _demo import USER, DemoStore
from _paths import SRC
from clark import backup, changes, default_sections, order, publish, store as store_module

KIND = "report_sections"
BODY = "SECRET-BODY-TEXT <p>not in a reply</p>"


class Api(unittest.TestCase):
    def setUp(self):
        self.demo = DemoStore()
        self.addCleanup(self.demo.close)
        self.s = self.demo.store
        self.path = self.s.path
        self.change = changes.make_change(self.path, [], USER)
        self.undo = changes.make_undo(self.path, [], USER)

    def req(self, op, **more):
        return {"project": "ABC", "kind": KIND, "op": op, **more}

    def ok(self, op, **more):
        status, body = self.change(self.req(op, **more))
        self.assertEqual((status, body.get("message")), (200, None), body)
        return body

    def refused(self, request, words, status=400):
        before = self.snapshot()
        got = self.change(request)
        self.assertEqual((got[0], got[1]["ok"], got[1]["message"]), (status, False, words), request)
        self.assertEqual(self.snapshot(), before, "nothing was written")
        return got[1]

    def snapshot(self):
        con = sqlite3.connect(str(self.path))
        try:
            return (con.execute("SELECT count(*) FROM applies").fetchone()[0], con.execute("SELECT count(*) FROM change_log").fetchone()[0],
                    con.execute("SELECT group_concat(id || title || sort_order || beside || hidden) FROM report_sections").fetchone()[0])
        finally:
            con.close()

    def rows(self):
        return order.in_order(self.s.read(KIND, "ABC"))

    def ids_now(self):
        return [r["id"] for r in self.rows()]

    def titles(self):
        return [r["title"] for r in self.rows()]

    def undone(self, apply_id, **more):
        status, body = self.undo({"project": "ABC", "apply_id": apply_id, **more})
        return status, body


class Allowed(Api):
    def test_allowed_fields_are_columns(self):
        for kind, ops in changes.CHANGE_KINDS.items():
            self.assertIn(kind, store_module.TABLES)
            columns = set(store_module.columns(self.s.con, kind))
            for op, fields in ops.items():
                self.assertTrue(set(fields) <= columns, (kind, op))
        sections = set(store_module.columns(self.s.con, KIND))
        self.assertTrue(set(changes.SHOWN) <= sections - {"body"} | {"id"})
        self.assertNotIn("body", changes.SHOWN)
        for never in ("project", "id", "sort_order", "body"):
            self.assertFalse(any(never in fields for ops in changes.CHANGE_KINDS.values() for fields in ops.values()), never)
        self.assertEqual(set(changes.OP_KEYS), {"new", "update", "move", "delete", "archive", "restore", "pick", "bulk", "handover"})      # #196: + bulk; #199: + handover

    def test_the_route_admits_only_the_approved_kinds(self):
        """#45 (Full tier, approved) added glance_tiles and projects (test_changes_tiles holds their tests) and #67 the eye,
        report_hidden (test_changes_hidden). The records can be archived and restored (#126), and the work items also updated
        (#68), and so are a project's health, an existing use case's fields (#164) and the milestones (#136), never given other ops."""
        self.assertEqual(set(changes.CHANGE_KINDS), {"report_sections", "glance_tiles", "report_hidden", *changes.ARCHIVABLE})
        for kind in changes.ARCHIVABLE:
            ops = set(changes.CHANGE_KINDS[kind])
            want = {"archive", "restore"} | ({"update"} if kind in changes.ITEM_KINDS or kind in ("projects", "milestones", "use_cases") else set())
            self.assertEqual(ops, want | ({"new"} if kind in changes.NEWABLE else set())      # #67: a row can be added to four kinds, never a use case
                             | ({"bulk", "handover"} if kind in changes.ITEM_KINDS else set()))           # #196: only the work items take a bulk change; #199: and a hand over
            self.assertEqual(set(changes.CHANGE_KINDS[kind]["archive"]) | set(changes.CHANGE_KINDS[kind]["restore"]), set())
        for kind in ("workstreams", "labels", "links", "report_sections ", "",
                     "REPORT_SECTIONS", "report_sections; DROP TABLE x"):
            with self.subTest(kind=kind):
                self.refused({"project": "ABC", "kind": kind, "op": "new", "values": {"project": "ABC", "tile": "health"}},
                             changes.BAD_KIND)
        self.assertEqual(self.s.read("glance_tiles", "ABC"), [])
        self.assertEqual(self.s.read("report_hidden", "ABC"), [])


class Refusals(Api):
    def test_unknown_kind_op_field_type_are_400(self):
        self.refused([], changes.NOT_JSON_OBJECT)
        self.refused("text", changes.NOT_JSON_OBJECT)
        self.refused(None, changes.NOT_JSON_OBJECT)
        self.refused({**self.req("new"), "colour": "red"}, "clark doesn't know 'colour' in that request.")
        self.refused({"kind": KIND, "op": "new"}, changes.BAD_PROJECT)
        self.refused({**self.req("new"), "project": "abc"}, changes.BAD_PROJECT)
        self.refused({**self.req("new"), "project": "ABC; DROP"}, changes.BAD_PROJECT)
        self.refused({"project": "ABC", "op": "new"}, changes.BAD_KIND)
        self.refused(self.req("copy"), changes.BAD_OP)
        self.refused(self.req(""), changes.BAD_OP)
        self.refused({"project": "ABC", "kind": KIND}, changes.BAD_OP)
        self.refused(self.req("new", values={"colour": "red"}), "The field 'colour' can't be set here.")
        self.refused(self.req("new", values={"sort_order": 5}), "The field 'sort_order' can't be set here.")
        self.refused(self.req("new", values={"project": "XYZ"}), "The field 'project' can't be set here.")
        self.refused(self.req("new", values={"id": "ABC-S-099"}), "The field 'id' can't be set here.")
        self.refused(self.req("new", values={"hidden": 1}), "The field 'hidden' can't be set here.")
        self.refused(self.req("new", values={"body": "x"}), "The field 'body' can't be set here.")
        self.refused(self.req("new", values={"type": "raid"}), changes.ONLY_TEXT)
        self.refused(self.req("new", values={"type": "docs", "title": "x"}), changes.ONLY_TEXT)
        self.refused(self.req("new", values={"type": ["text"]}), changes.ONLY_TEXT)
        self.refused(self.req("new", id="ABC-S-001"), "That change doesn't take 'id'.")
        self.refused(self.req("new", changes={"title": "x"}), "That change doesn't take 'changes'.")
        self.refused(self.req("new", before="ABC-S-001"), "That change doesn't take 'before'.")
        self.refused(self.req("update", id="ABC-S-005", values={"title": "x"}), "That change doesn't take 'values'.")
        self.refused(self.req("update", id="ABC-S-005", changes={"sort_order": 1}), "The field 'sort_order' can't be set here.")
        self.refused(self.req("update", id="ABC-S-005", changes={"body": "x"}), "The field 'body' can't be set here.")
        self.refused(self.req("update", id="ABC-S-005", changes={"project": "XYZ"}), "The field 'project' can't be set here.")
        self.refused(self.req("update", id="ABC-S-005", changes={}), "Say what to change.")
        self.refused(self.req("update", id="ABC-S-005"), "Say what to change.")
        self.refused(self.req("update", id="ABC-S-005", changes=["title"]), "Send the changes as an object.")
        self.refused(self.req("move", id="ABC-S-005"), "Say where to move it.")
        self.refused(self.req("delete", id="ABC-S-005", before="ABC-S-001"), "That change doesn't take 'before'.")
        self.refused(self.req("new", place="elsewhere"), changes.BAD_PLACE)
        self.refused(self.req("new", place=["menu"]), changes.BAD_PLACE)

    def test_a_changed_type_is_refused(self):
        for value in ("raid", "text", None, 5):
            with self.subTest(value=value):
                self.refused(self.req("update", id="ABC-S-005", changes={"type": value}), changes.KEEPS_TYPE)
        self.refused(self.req("update", id="ABC-S-005", changes={"type": "raid", "title": "x"}), changes.KEEPS_TYPE)

    def test_request_typing_never_reaches_the_store_as_a_fault(self):
        """Unhashable, non-string, bool, float and huge values are refused in words, never a 500."""
        weird = ([], {}, [1], {"a": 1}, True, False, 0, 1, -1, 1.5, 2 ** 70, "", None, "x" * 5000, "ABC-S-001\x00", "ABC|x")
        for v in weird:
            for request in (
                    {"project": v, "kind": KIND, "op": "new"}, {"project": "ABC", "kind": v, "op": "new"},
                    {"project": "ABC", "kind": KIND, "op": v}, self.req("update", id=v, changes={"title": "x"}),
                    self.req("update", id="ABC-S-005", changes=v), self.req("update", id="ABC-S-005", changes={"title": v}),
                    self.req("update", id="ABC-S-005", changes={"hidden": v}), self.req("update", id="ABC-S-005", changes={"beside": v}),
                    self.req("move", id=v, before=None), self.req("move", id="ABC-S-005", before=v),
                    self.req("delete", id=v), self.req("new", after=v), self.req("new", values=v), self.req("new", values={"title": v}),
                    self.req("new", values={"type": v}), self.req("new", place=v)):
                with self.subTest(v=repr(v)[:30], op=request.get("op")):
                    got = self.change(request)
                    if got[0] == 200:       # only the harmless ones: nothing given, an empty object, or a real 0 or 1 flag
                        fine = isinstance(v, str) and v.strip() and len(v) <= 120 and "\x00" not in v        # a title that is simply a title
                        self.assertTrue(v is None or v == {} or (type(v) is int and v in (0, 1)) or fine, request)
                        continue
                    self.assertIn(got[0], (400, 404), request)
                    self.assertFalse(got[1]["ok"])
                    self.assertNotRegex(got[1]["message"], r"Traceback|Error|sqlite|TypeError|Exception", got[1]["message"])
        for v in ([], {}, True, 0, -1, 1.5, 2 ** 70, 2 ** 63, "1", None, "", "x" * 5000, [1]):
            with self.subTest(apply_id=repr(v)[:30]):
                got = self.undone(v)
                self.assertEqual((got[0], got[1]["message"]), (400, changes.NO_UNDO))

    def test_flags_are_0_or_1_and_nothing_else(self):
        for field in ("hidden", "beside"):
            for bad in (True, False, 2, -1, 1.0, 0.0, "1", "0", "", None, [1], {"a": 1}):
                with self.subTest(field=field, value=repr(bad)):
                    self.refused(self.req("update", id="ABC-S-005", changes={field: bad}), changes.FLAG_WORDS)
        self.assertEqual(self.rows()[4]["hidden"], 0)

    def test_hide_with_1_then_undo_puts_it_back_and_the_log_says_1(self):
        for field in ("hidden", "beside"):
            with self.subTest(field=field):
                body = self.ok("update", id="ABC-S-005", changes={field: 1})
                self.assertEqual(self.s.read(KIND, ref="ABC-S-005")[field], 1)
                row = self.s.con.execute("SELECT old_value, new_value FROM change_log WHERE apply_id = ? AND field = ?",
                                         (body["apply_id"], field)).fetchone()
                self.assertEqual((row[0], row[1]), ("0", "1"))
                status, out = self.undone(body["apply_id"])
                self.assertEqual((status, out["skipped"]), (200, []))
                self.assertEqual(self.s.read(KIND, ref="ABC-S-005")[field], 0)

    def test_beside_on_a_section_that_is_not_text_is_accepted(self):
        body = self.ok("update", id="ABC-S-008", changes={"beside": 1})
        self.assertEqual(self.s.read(KIND, ref="ABC-S-008")["beside"], 1)
        self.assertEqual(self.undone(body["apply_id"])[1]["skipped"], [])
        self.assertEqual(self.s.read(KIND, ref="ABC-S-008")["beside"], 0)

    def test_hostile_titles(self):
        for title, words in (("", "A title can't be blank."), ("   ", "A title can't be blank."),
                             ("\u00a0\t", "A title can't be blank."), ("x" * 121, "A title can be at most 120 characters."),
                             ("Plan\u202eevil", "A title can't hold control or invisible characters."),
                             ("Plan\u200b", "A title can't hold control or invisible characters."),
                             ("\ufeff", "A title can't hold control or invisible characters."),
                             ("a\nb", "A title can't hold control or invisible characters."),
                             ("a\u2029b", "A title can't hold control or invisible characters."),
                             ("lone \ud800", "A title can't hold control or invisible characters."),
                             ("\x00", "A title can't hold control or invisible characters."),
                             ("\u2800", "A title needs at least one visible letter, number or symbol."),
                             (" \u3164\uffa0 ", "A title needs at least one visible letter, number or symbol."),
                             ("\ufe0f", "A title needs at least one visible letter, number or symbol."), (5, "A title must be text."),
                             (["x"], "A title must be text."), (None, "A title must be text.")):
            with self.subTest(title=repr(title)[:30]):
                self.refused(self.req("update", id="ABC-S-005", changes={"title": title}), words)
                self.refused(self.req("new", values={"title": title}), words)
        self.assertEqual(self.titles()[4], "Summary")

    def test_a_title_is_plain_text_trimmed_and_nfc_and_markup_stays_text(self):
        body = self.ok("update", id="ABC-S-005", changes={"title": "  <b>x</b> & Cafe\u0301  "})
        self.assertEqual(self.s.read(KIND, ref="ABC-S-005")["title"], "<b>x</b> & Caf\u00e9")
        shown = {r["id"]: r["title"] for r in body["sections"]}
        self.assertEqual(shown["ABC-S-005"], "<b>x</b> & Caf\u00e9")        # the page shows it with textContent, never as markup
        self.ok("update", id="ABC-S-005", changes={"title": "x" * 120})
        self.ok("new", values={"title": "\U0001F600" * 120})

    def test_another_projects_section_is_refused(self):
        with self.s.step("dashboard", USER) as st:
            st.create("projects", {"code": "XYZ", "name": "Second Programme"})
        theirs = "XYZ-S-001"
        words = changes.NOT_MINE
        for request in (self.req("update", id=theirs, changes={"title": "Mine now"}), self.req("update", id="ABC-S-999",
                        changes={"title": "Mine now"}), self.req("move", id=theirs, before=None), self.req("move", id="ABC-S-999", before=None),
                        self.req("delete", id=theirs), self.req("delete", id="ABC-S-999")):
            with self.subTest(request=request):
                self.refused(request, words)            # another project's and a missing one: the same words
        self.assertEqual(self.s.read(KIND, ref=theirs)["title"], "Current state")
        for op, key in (("move", "before"), ("new", "after")):
            for ref in (theirs, "ABC-S-999", "nonsense"):
                with self.subTest(op=op, ref=ref):
                    extra = {"id": "ABC-S-005"} if op == "move" else {}
                    self.refused(self.req(op, **{key: ref}, **extra), changes.STALE)       # a stale position: reload

    def test_a_section_cant_go_before_itself(self):
        self.refused(self.req("move", id="ABC-S-005", before="ABC-S-005"), "A section can't be moved before itself.")

    def test_an_unknown_project_is_404_in_the_servers_words(self):
        from clark import server
        got = self.change({**self.req("new"), "project": "NOP"})
        self.assertEqual((got[0], got[1]["message"], got[1]["code"]), (404, server.MESSAGES["project_not_found"], "project_not_found"))
        self.assertEqual(changes.BAD_PROJECT, server.MESSAGES["bad_project_code"])
        self.assertEqual(self.undo({"project": "NOP", "apply_id": 1})[0], 404)

    def test_a_missing_database_is_refused_and_no_empty_one_is_made(self):
        self.s.close()
        for suffix in ("", "-wal", "-shm"):
            self.path.with_name(self.path.name + suffix).unlink(missing_ok=True)
        for call in (self.change(self.req("new")), self.undo({"project": "ABC", "apply_id": 1})):
            self.assertEqual((call[0], call[1]["message"], call[1]["ok"]), (503, "clark's data can't be found.", False))
        self.assertFalse(self.path.exists(), "open_store would have made an empty one")

    def test_a_change_while_a_restore_has_moved_the_database_aside_gets_the_restore_sentence(self):
        self.s.close()
        aside = self.path.with_name(self.path.name + ".aside")
        self.path.rename(aside)
        self.addCleanup(lambda: aside.exists() and aside.rename(self.path))
        key = os.path.abspath(self.path)
        with backup._UNDER_WAY_LOCK:
            backup._UNDER_WAY.add(key)
        self.addCleanup(backup._UNDER_WAY.discard, key)
        for call in (self.change(self.req("new")), self.undo({"project": "ABC", "apply_id": 1})):
            self.assertEqual((call[0], call[1]["message"], call[1]["ok"]), (503, backup.RESTORE_BUSY, False))
        self.assertFalse(self.path.exists())

    @unittest.skipIf(not hasattr(os, "geteuid") or os.geteuid() == 0, "root can write to a folder marked read-only")
    def test_a_data_folder_that_cant_be_written_is_503_in_clarks_words_and_never_sqlites(self):
        self.s.close()
        for suffix in ("-wal", "-shm"):                                 # none left (an older SQLite leaves them): opening for
            self.path.with_name(self.path.name + suffix).unlink(missing_ok=True)      # writing has to make them, and can't
        self.addCleanup(os.chmod, self.path.parent, 0o700)
        os.chmod(self.path.parent, 0o500)                               # a real read-only folder
        for call in (self.change(self.req("new")), self.undo({"project": "ABC", "apply_id": 1})):
            self.assertEqual((call[0], call[1]["message"], call[1]["ok"]), (503, changes.CANT_SAVE, False))
            self.assertEqual(changes.CANT_SAVE, "clark can't save to its data. Check the folder is writable, then try again.")
            self.assertNotRegex(json.dumps(call[1]).lower(), "readonly|attempt|sqlite|operationalerror|database")

    def test_the_stores_could_not_be_opened_refusal_is_503_wherever_it_comes_from_and_hides_sqlites_words(self):
        said = store_module._busy(sqlite3.OperationalError("attempt to write a readonly database"))
        self.assertNotIn("readonly", said)
        self.assertTrue(said.startswith(changes.NOT_OPENED))
        for work in (changes._do_change, changes._do_undo):               # the refusal raised after the store is open
            def broken(store, who, req, work=work):
                raise store_module.Invalid(said)
            status, body = changes._call(self.path, [], USER, broken, {})
            self.assertEqual((status, body["message"]), (503, changes.CANT_SAVE))
        self.assertEqual(self.change(self.req("new"))[0], 200, "and a folder that can be written is not refused")


class Steps(Api):
    """Each kind of step through the route: it does what it says, one step, the reply, then Undo and Undo of the Undo."""

    def test_new_is_one_step_and_goes_after_the_named_section(self):
        count = self.snapshot()[0]
        body = self.ok("new", values={"title": "Plan"}, after="ABC-S-005", place="menu")
        self.assertEqual((body["ref"], body["apply_id"]), ("ABC-S-012", count + 1))
        self.assertEqual(self.titles()[4:7], ["Summary", "Plan", "This week"])
        row = self.s.read(KIND, ref="ABC-S-012")
        self.assertEqual((row["type"], row["project"], row["hidden"], row["beside"]), ("text", "ABC", 0, 0))
        rows = self.s.con.execute("SELECT DISTINCT item_id FROM change_log WHERE apply_id = ?", (body["apply_id"],)).fetchall()
        self.assertEqual([r[0] for r in rows], ["ABC-S-012"], "one new row and no other")
        event = self.s.con.execute("SELECT route, place, actor FROM item_events WHERE apply_id = ? LIMIT 1", (body["apply_id"],)).fetchone()
        self.assertEqual(tuple(event), ("dashboard", "menu", "you"))
        self.assertEqual(self.s.con.execute("SELECT by_user FROM applies WHERE apply_id = ?", (body["apply_id"],)).fetchone()[0], USER)

    def test_new_with_no_title_is_called_new_section_and_no_after_means_the_end(self):
        body = self.ok("new")
        self.assertEqual(self.titles()[-1], "New section")
        self.assertEqual(body["ref"], self.rows()[-1]["id"])
        self.ok("new", values={"type": "text"}, after=None)
        self.ok("new", after=self.rows()[-1]["id"])
        self.assertEqual(self.titles()[-3:], ["New section"] * 3)

    def test_new_renumbers_when_there_is_no_gap(self):
        for n, ref in enumerate(("ABC-S-001", "ABC-S-002", "ABC-S-003")):
            self.ok("update", id=ref, changes={"title": f"T{n}"})
            with self.s.step("dashboard", USER) as st:
                st.update(KIND, ref, {"sort_order": 10 + n})             # one apart: nothing fits between
        body = self.ok("new", values={"title": "Between"}, after="ABC-S-001")
        self.assertEqual(self.titles()[:3], ["T0", "Between", "T1"])
        rows = {r["item_id"] for r in self.s.con.execute("SELECT item_id FROM change_log WHERE apply_id = ?", (body["apply_id"],))}
        self.assertGreater(len(rows), 2, "the others were renumbered in the same step")
        status, out = self.undone(body["apply_id"])
        self.assertEqual((status, out["skipped"]), (200, []))
        self.assertEqual(self.titles()[:3], ["T0", "T1", "T2"])

    def test_update_move_delete_each_with_undo_and_undo_of_the_undo(self):
        cases = (
            ("update", lambda ref: {"id": ref, "changes": {"title": "Renamed"}}, lambda ref: self.s.read(KIND, ref=ref)["title"]),
            ("update", lambda ref: {"id": ref, "changes": {"hidden": 1}}, lambda ref: self.s.read(KIND, ref=ref)["hidden"]),
            ("update", lambda ref: {"id": ref, "changes": {"beside": 1}}, lambda ref: self.s.read(KIND, ref=ref)["beside"]),
            ("move", lambda ref: {"id": ref, "before": "ABC-S-002"}, lambda ref: [r["id"] for r in self.rows()].index(ref)),
            ("delete", lambda ref: {"id": ref}, lambda ref: self.s.read(KIND, ref=ref) is not None),
        )
        for op, args, get in cases:
            added = self.ok("new", values={"title": "Plan"})["ref"]         # a fresh text section for each case
            with self.subTest(op=op, args=args(added)):
                before = get(added)
                body = self.ok(op, **args(added))
                self.assertIsNotNone(body["apply_id"])
                after = get(added)
                self.assertNotEqual(before, after)
                status, out = self.undone(body["apply_id"])
                self.assertEqual((status, out["skipped"]), (200, []), out)
                self.assertEqual(get(added), before)
                self.assertTrue(out["words"].startswith("Put back: "), out["words"])
                self.assertEqual([r["id"] for r in out["sections"]], [r["id"] for r in self.rows()])
                again = self.s.undo(out["apply_id"], USER)               # Undo of the Undo, in the store (the route refuses it)
                self.assertEqual(again["skipped"], [])
                self.assertEqual(get(added), after)

    def test_move_changes_only_the_moved_row_and_before_none_is_the_end(self):
        body = self.ok("move", id="ABC-S-009", before="ABC-S-002")
        self.assertEqual([r["id"] for r in self.rows()][:3], ["ABC-S-001", "ABC-S-009", "ABC-S-002"])
        rows = self.s.con.execute("SELECT DISTINCT item_id FROM change_log WHERE apply_id = ?", (body["apply_id"],)).fetchall()
        self.assertEqual([r[0] for r in rows], ["ABC-S-009"])
        self.ok("move", id="ABC-S-001", before=None)
        self.assertEqual(self.rows()[-1]["id"], "ABC-S-001")

    def test_a_move_with_flags_is_one_step_and_one_undo(self):
        before = {r["id"]: r["beside"] for r in self.rows()}
        body = self.ok("move", id="ABC-S-009", before="ABC-S-002", flags={"ABC-S-001": 1, "ABC-S-009": 0}, place="report")
        ids = [r["id"] for r in self.rows()]
        self.assertEqual(ids[:3], ["ABC-S-001", "ABC-S-009", "ABC-S-002"])
        now = {r["id"]: r["beside"] for r in self.rows()}
        self.assertEqual((now["ABC-S-001"], now["ABC-S-009"]), (1, 0))      # the right half of the first section, for a raid section: any type
        steps = {r[0] for r in self.s.con.execute("SELECT DISTINCT apply_id FROM change_log WHERE apply_id >= ?", (body["apply_id"],))}
        self.assertEqual(steps, {body["apply_id"]})
        self.assertEqual({r[0] for r in self.s.con.execute("SELECT item_id FROM change_log WHERE apply_id = ?", (body["apply_id"],))},
                         {"ABC-S-009", "ABC-S-001"})
        status, out = self.undone(body["apply_id"])
        self.assertEqual((status, out["skipped"]), (200, []))
        self.assertEqual([r["id"] for r in self.rows()], sorted(ids, key=lambda i: int(i[-3:])))
        self.assertEqual({r["id"]: r["beside"] for r in self.rows()}, before)

    def test_a_plain_move_and_a_move_with_flags_that_change_nothing(self):
        body = self.ok("move", id="ABC-S-009", before="ABC-S-002", flags={})
        self.assertIsNotNone(body["apply_id"])
        count = self.snapshot()
        for request in (self.req("move", id="ABC-S-005", before="ABC-S-006", flags={"ABC-S-005": 0}),
                        self.req("move", id="ABC-S-005", before="ABC-S-006", flags={})):
            got = self.change(request)[1]
            self.assertTrue(got["ok"])
            self.assertIsNone(got["apply_id"], request)
        self.assertEqual(self.snapshot(), count)

    def test_a_move_with_flags_sets_beside_and_nothing_else(self):
        self.assertEqual(changes.CHANGE_KINDS[KIND]["move"], ("beside",))
        for bad in ("hidden", "sort_order", "title"):
            self.refused(self.req("move", id="ABC-S-005", before=None, flags={bad: 1}), changes.STALE)   # not a section: refused as a stale id
        self.refused(self.req("update", id="ABC-S-005", changes={"title": "Q"}, flags={"ABC-S-005": 1}), changes.INVALID_LAYOUT)

    def test_a_beside_drop_from_a_page_that_is_out_of_date_is_refused(self):
        """The page saw S3 to S8 only; another tab then added a section after S7. A drop meant "beside S7" must not become a pair
        with the new section."""
        new = self.ok("new", values={"title": "Added elsewhere"}, after="ABC-S-007")["ref"]
        self.assertEqual(self.ids_now().index(new), self.ids_now().index("ABC-S-007") + 1)
        self.refused(self.req("move", id="ABC-S-003", before="ABC-S-008", flags={"ABC-S-007": 1, "ABC-S-003": 0}, place="report"), changes.STALE)
        self.refused(self.req("move", id="ABC-S-003", before=new, flags={"ABC-S-001": 1}), changes.STALE)   # not the one before the landing place
        ok = self.ok("move", id="ABC-S-003", before="ABC-S-008", flags={new: 1, "ABC-S-003": 0}, place="report")    # the page that saw it
        self.assertEqual({r["id"]: r["beside"] for r in self.rows()}[new], 1)
        self.assertIsNotNone(ok["apply_id"])

    def test_a_beside_drop_onto_the_second_half_of_a_pair_is_refused(self):
        rows = {r["id"]: r["beside"] for r in self.rows()}
        first = next(i for i, r in enumerate(self.rows()) if r["beside"] == 1)
        second = self.rows()[first + 1]["id"]
        mover = next(r["id"] for r in self.rows() if r["id"] not in (second, self.rows()[first]["id"]))
        after = self.rows()[first + 2]["id"] if first + 2 < len(self.rows()) else None
        self.refused(self.req("move", id=mover, before=after, flags={second: 1}), changes.STALE)
        self.assertEqual({r["id"]: r["beside"] for r in self.rows()}, rows)

    def test_a_page_that_missed_a_new_pair_can_neither_break_it_nor_join_it(self):
        """Another tab made S2 and S3 a pair after this page drew the report: A (beside S2, which now has a partner), B (beside S2
        from the left) and C (into S3, the second half) are all refused, and nothing is written."""
        self.ok("update", id="ABC-S-002", changes={"beside": 1})
        for flags, before in (({"ABC-S-002": 1, "ABC-S-008": 0}, "ABC-S-003"), ({"ABC-S-008": 1}, "ABC-S-002"), ({"ABC-S-008": 1}, "ABC-S-003")):
            with self.subTest(flags=flags, before=before):
                self.refused(self.req("move", id="ABC-S-008", before=before, flags=flags, place="report"), changes.STALE)

    def test_a_stray_flag_on_a_second_half_does_not_block_a_drop_the_page_allows(self):
        """S3 and S4 are a pair and S4 also carries a 1 the page ignores; S6 is on its own. Dropping S5 beside S6 is fine."""
        for ref, value in (("ABC-S-003", 1), ("ABC-S-004", 1), ("ABC-S-005", 0), ("ABC-S-006", 0)):
            self.ok("update", id=ref, changes={"beside": value})
        got = self.ok("move", id="ABC-S-005", before="ABC-S-007", flags={"ABC-S-006": 1, "ABC-S-005": 0}, place="report")
        self.assertIsNotNone(got["apply_id"])
        self.assertEqual({r["id"]: r["beside"] for r in self.rows()}["ABC-S-006"], 1)

    def test_flags_may_only_name_the_moved_section_its_neighbours_and_the_one_before_the_landing_place(self):
        before = {r["id"]: r["beside"] for r in self.rows()}
        for other in ("ABC-S-004", "ABC-S-005", "ABC-S-011"):                    # S9 moves to before S2: none of these is near
            for value in (0, 1):
                with self.subTest(other=other, value=value):
                    self.refused(self.req("move", id="ABC-S-009", before="ABC-S-002", flags={other: value}, place="report"), changes.STALE)
        self.assertEqual({r["id"]: r["beside"] for r in self.rows()}, before)
        for named in ("ABC-S-009", "ABC-S-002", "ABC-S-001", "ABC-S-008", "ABC-S-010"):   # the moved, before, the one above, both old neighbours
            with self.subTest(named=named):
                got = self.change(self.req("move", id="ABC-S-009", before="ABC-S-002", flags={named: 0}))
                self.assertTrue(got[1]["ok"], named)
                self.undone(got[1]["apply_id"])                       # back to the start for the next one

    def test_bad_flags_are_refused_in_words_and_change_nothing(self):
        theirs = "XYZ-S-001"
        with self.s.step("dashboard", USER) as st:
            st.create("projects", {"code": "XYZ", "name": "Second Programme"})
        too_many = {f"ABC-S-00{i}": 1 for i in range(1, 6)}
        for flags, words in (({"ABC-S-005": 2}, "That must be 0 or 1."), ({"ABC-S-005": True}, "That must be 0 or 1."),
                             ({"ABC-S-005": "1"}, "That must be 0 or 1."), ({"ABC-S-005": None}, "That must be 0 or 1."),
                             ({"ABC-S-999": 1}, changes.STALE), ({theirs: 1}, changes.STALE),
                             (too_many, changes.INVALID_LAYOUT), ([1], changes.INVALID_LAYOUT),
                             ("ABC-S-005", changes.INVALID_LAYOUT)):
            with self.subTest(flags=flags):
                self.refused(self.req("move", id="ABC-S-009", before="ABC-S-002", flags=flags), words)

    def test_a_change_that_changes_nothing_has_no_step_and_no_undo(self):
        count = self.snapshot()
        for request in (self.req("update", id="ABC-S-005", changes={"title": "Summary"}),
                        self.req("update", id="ABC-S-005", changes={"hidden": 0}),
                        self.req("move", id="ABC-S-005", before="ABC-S-006"),        # it is already just before This week
                        self.req("move", id="ABC-S-011", before=None)):
            body = self.change(request)[1]
            self.assertTrue(body["ok"])
            self.assertIsNone(body["apply_id"], request)
        self.assertEqual(self.snapshot(), count)

    def test_ties_in_sort_order_keep_a_stable_order_and_move_still_works(self):
        a = self.ok("new", values={"title": "Tie A"})["ref"]
        b = self.ok("new", values={"title": "Tie B"})["ref"]
        with self.s.step("dashboard", USER) as st:
            st.update(KIND, b, {"sort_order": self.s.read(KIND, ref=a)["sort_order"]})
        self.assertEqual([r["id"] for r in self.rows()][-2:], [a, b])
        body = self.ok("move", id=b, before=a)                  # two tied neighbours: nothing fits, everything is renumbered
        self.assertEqual([r["id"] for r in self.rows()][-2:], [b, a])
        self.assertEqual(len({r["sort_order"] for r in self.rows()}), len(self.rows()))
        self.assertEqual(self.undone(body["apply_id"])[0], 200)

    def test_section_numbers_running_out_at_999_is_said_in_everyday_words(self):
        con = sqlite3.connect(str(self.path))
        try:
            con.execute("INSERT INTO report_sections (project, id, type, title, sort_order) VALUES ('ABC', 'ABC-S-999', 'text', 'Last', 9999999)")
            con.commit()                                                 # the counter is at 999 without making 999 sections
        finally:
            con.close()
        words = "ABC's report has used up all the section numbers clark has (999), so no more sections can be added."
        self.refused(self.req("new", values={"title": "One too many"}), words)
        self.assertNotRegex(words, "item|kind of")                       # not the work items' words
        self.assertEqual(len(self.rows()), 12)
        self.ok("update", id="ABC-S-005", changes={"title": "Other changes still work"})

    def test_100_sections_is_the_most(self):
        with self.s.step("dashboard", USER) as st:
            for n in range(89):
                st.create(KIND, {"project": "ABC", "type": "text", "title": f"S{n}", "sort_order": 100000 + n})
        self.refused(self.req("new"), "A report can have at most 100 sections.")

    def test_delete_only_a_text_section(self):
        self.refused(self.req("delete", id="ABC-S-001"), "Only a text section can be deleted; hide the others.")
        self.assertEqual(self.ok("delete", id="ABC-S-005")["ref"], "ABC-S-005")
        self.assertNotIn("Summary", self.titles())

    def beside_now(self):
        return {r["id"]: r["beside"] for r in self.rows()}

    def test_deleting_the_second_half_of_a_final_pair_clears_the_first_half_in_one_step(self):
        last = self.ids_now()[-1]
        added = self.ok("new", values={"title": "Plan"})["ref"]
        self.ok("update", id=last, changes={"beside": 1})                   # the new last section is its second half
        before = self.beside_now()
        self.assertEqual(before[last], 1)
        body = self.ok("delete", id=added)
        self.assertEqual(self.beside_now()[last], 0, "no stray flag on the last section")
        self.assertNotIn(added, self.ids_now())
        status, out = self.undone(body["apply_id"])
        self.assertEqual((status, out["skipped"]), (200, []), out)
        self.assertEqual(self.beside_now(), before, "one Undo puts the section and the flag back")
        self.assertIn(added, self.ids_now())

    def test_deleting_the_first_half_of_a_pair_clears_a_stray_flag_on_the_second_half(self):
        a = self.ok("new", values={"title": "First"})["ref"]
        b = self.ok("new", values={"title": "Second"})["ref"]
        self.ok("update", id=a, changes={"beside": 1})
        self.ok("update", id=b, changes={"beside": 1})                      # a stray flag on the second half (ignored by the page)
        before = self.beside_now()
        body = self.ok("delete", id=a)
        self.assertEqual(self.beside_now()[b], 0, "it must not become the first half of a new pair")
        self.assertEqual(self.undone(body["apply_id"])[1]["skipped"], [])
        self.assertEqual(self.beside_now(), before)

    def test_a_delete_the_store_refuses_leaves_every_flag_as_it_was(self):
        self.ok("update", id="ABC-S-001", changes={"beside": 1})           # S-002 is the second half of S-001; it is not a text section
        before, snap = self.beside_now(), self.snapshot()
        self.assertEqual(before["ABC-S-001"], 1)
        self.refused(self.req("delete", id="ABC-S-002"), "Only a text section can be deleted; hide the others.")
        self.assertEqual(self.beside_now(), before, "the partner's flag was written inside the step, so the refusal rolled it back")
        self.assertEqual(self.snapshot(), snap, "no step, no change_log row")

    def test_guard_deleting_a_lone_section_changes_nothing_else(self):
        a = self.ok("new", values={"title": "Alone"})["ref"]
        before = {k: v for k, v in self.beside_now().items() if k != a}
        body = self.ok("delete", id=a)
        self.assertEqual(self.beside_now(), before)
        ids = {r["item_id"] for r in self.s.con.execute("SELECT item_id FROM change_log WHERE apply_id = ?", (body["apply_id"],)).fetchall()}
        self.assertEqual(ids, {a})

    def test_replies_carry_no_body(self):
        with self.s.step("dashboard", USER) as st:
            st.update(KIND, "ABC-S-005", {"body": BODY})
        for body in (self.ok("update", id="ABC-S-005", changes={"title": "Renamed"}), self.ok("move", id="ABC-S-005", before="ABC-S-001"),
                     self.ok("new"), self.ok("delete", id="ABC-S-012")):
            self.assertNotIn("SECRET-BODY-TEXT", json.dumps(body))
            for row in body["sections"]:
                self.assertEqual(sorted(row), sorted(("id", "type", "title", "beside", "hidden", "sort_order")))
        status, out = self.undone(self.ok("update", id="ABC-S-005", changes={"hidden": 1})["apply_id"])
        self.assertEqual(status, 200)
        self.assertNotIn("SECRET-BODY-TEXT", json.dumps(out))
        self.assertEqual(set(out), {"ok", "apply_id", "reversed", "skipped", "words", "sections"})
        self.assertEqual(self.s.read(KIND, ref="ABC-S-005")["body"], BODY, "the body itself is untouched")


class Undoing(Api):
    def test_undo_only_this_pages_steps(self):
        a = self.demo.action()
        with self.s.step("excel", USER) as st:                          # #68: an item step is ours only via the dashboard route
            st.update("actions", a, {"owner": "Via Excel"})
        action_step = self.demo.last_step()
        project_step = self.s.con.execute("SELECT min(apply_id) FROM applies").fetchone()[0]       # creates the project and its sections
        with self.s.step("excel", USER) as st:
            st.create(KIND, {"project": "ABC", "type": "text", "title": "From a workbook", "sort_order": 1})
        excel_step = self.demo.last_step()
        mine = self.ok("update", id="ABC-S-005", changes={"title": "Mine"})["apply_id"]
        with self.s.step("dashboard", USER) as st:
            st.create("projects", {"code": "XYZ", "name": "Second Programme"})
        with self.s.step("dashboard", USER) as st:
            st.update(KIND, "XYZ-S-001", {"title": "Theirs"})
        theirs = self.demo.last_step()
        with self.s.step("dashboard", USER) as st:                      # a step that touches both a section and an action
            st.update(KIND, "ABC-S-006", {"title": "Mixed"})
            st.update("actions", a, {"owner": "Sam Example"})
        mixed = self.demo.last_step()
        undo_step = self.s.undo(mine, USER)["step_id"]                  # an undo's own step: made by revert, not the dashboard
        for step in (action_step, project_step, excel_step, theirs, mixed, undo_step, 99999, 0, -3):
            with self.subTest(step=step):
                status, body = self.undone(step)
                self.assertEqual((status, body["message"]), (400, changes.NO_UNDO))    # no step tells which of these exist
        self.assertEqual(self.s.read(KIND, ref="XYZ-S-001")["title"], "Theirs")
        self.assertEqual(self.s.read("actions", ref=a)["owner"], "Sam Example")   # the mixed step was not undone (nor one of the sections and an item)
        self.assertEqual(self.s.read(KIND, ref="ABC-S-006")["title"], "Mixed")
        self.assertEqual(self.undo({"project": "XYZ", "apply_id": theirs})[0], 200)   # its own project can
        self.assertEqual(self.undo({"project": "ABC", "apply_id": theirs})[0], 400)

    def test_an_undo_twice_is_409(self):
        step = self.ok("update", id="ABC-S-005", changes={"title": "Once"})["apply_id"]
        self.assertEqual(self.undone(step)[0], 200)
        status, body = self.undone(step)
        self.assertEqual((status, body["message"]), (409, changes.UNDONE))

    def test_a_later_change_is_skipped_and_named_in_the_words(self):
        first = self.ok("update", id="ABC-S-005", changes={"title": "Second name"})["apply_id"]
        later = self.ok("update", id="ABC-S-005", changes={"title": "Third name"})["apply_id"]
        status, body = self.undone(first)
        self.assertEqual(status, 200)
        self.assertEqual(self.s.read(KIND, ref="ABC-S-005")["title"], "Third name")
        self.assertEqual([(s["ref"], s["field"], s["by_step"]) for s in body["skipped"]], [("ABC-S-005", "title", later)])
        self.assertEqual(body["words"], f"Nothing was put back. \u201cThird name\u201d was changed later (step {later}), so it was left as it is.")
        self.assertIsNone(body["apply_id"])

    def test_one_field_changed_twice_in_a_step_goes_back_to_its_first_value(self):
        with self.s.step("dashboard", USER) as st:
            st.update(KIND, "ABC-S-005", {"title": "Middle"})
            st.update(KIND, "ABC-S-005", {"title": "Last"})
        status, body = self.undone(self.demo.last_step())
        self.assertEqual((status, body["skipped"]), (200, []))
        self.assertEqual(self.s.read(KIND, ref="ABC-S-005")["title"], "Summary")

    def test_an_added_section_that_was_renamed_is_kept_and_the_later_step_named(self):
        added = self.ok("new", values={"title": "Plan"})
        later = self.ok("update", id=added["ref"], changes={"title": "Renamed"})["apply_id"]
        status, body = self.undone(added["apply_id"])
        self.assertEqual(status, 200)
        self.assertIsNotNone(self.s.read(KIND, ref=added["ref"]))
        self.assertEqual([s["by_step"] for s in body["skipped"]], [later])
        self.assertIn(f"step {later}", body["words"])

    def test_an_add_can_be_undone_after_a_later_change_was_itself_undone_but_not_after_a_change_that_stays(self):
        added = self.ok("new", values={"title": "Plan"})
        renamed = self.ok("update", id=added["ref"], changes={"title": "Renamed"})
        self.assertEqual(self.undone(renamed["apply_id"])[0], 200)             # the rename is undone: only an undo is later now
        status, body = self.undone(added["apply_id"])
        self.assertEqual((status, body["skipped"], body["words"]), (200, [], "Put back: the new section \u201cPlan\u201d was removed."))
        self.assertIsNone(self.s.read(KIND, ref=added["ref"]))
        again = self.ok("new", values={"title": "Again"})                      # a change that stays still blocks the undo,
        self.ok("update", id=again["ref"], changes={"title": "Kept"})          # and the step named is that person's, not an undo
        later = self.ok("update", id=again["ref"], changes={"title": "Kept too"})["apply_id"]
        status, body = self.undone(again["apply_id"])
        self.assertEqual((status, [s["by_step"] for s in body["skipped"]]), (200, [later]))
        self.assertEqual(self.s.read(KIND, ref=again["ref"])["title"], "Kept too")
        third = self.ok("new", values={"title": "Third"})
        first = self.ok("update", id=third["ref"], changes={"title": "Renamed"})["apply_id"]
        self.assertEqual(self.undone(first)[0], 200)
        last = self.ok("update", id=third["ref"], changes={"title": "Renamed again"})["apply_id"]     # a real change after the undo
        status, body = self.undone(third["apply_id"])
        self.assertEqual([s["by_step"] for s in body["skipped"]], [last])
        self.assertIn(f"(step {last})", body["words"])
        undo_steps = {r[0] for r in self.s.con.execute("SELECT DISTINCT apply_id FROM change_log WHERE via LIKE 'revert:%'")}
        self.assertNotIn(last, undo_steps)

    def test_a_section_with_no_title_to_hand_is_a_section_and_never_an_id(self):
        gone = {"ref": "ABC-S-012", "field": None, "why": "has changed since: left as it is", "by_step": 7}
        for skipped in (gone, {**gone, "by_step": None}, {**gone, "why": "no longer exists"}, {**gone, "why": "is back already: x"},
                        {**gone, "why": "other data depends on it"}):
            said = changes.words([], [skipped], {})
            self.assertNotIn("ABC-S-012", said)
            self.assertNotIn("-S-", said)
            self.assertTrue(said.startswith("Nothing was put back. A section "), said)
        self.assertIn("(step 7)", changes.words([], [gone], {}), "a step number is said on purpose")
        said = changes.words([{"ref": "ABC-S-012", "field": "title", "change": "set", "to": "x"}], [], {})
        self.assertEqual(said, "Put back: the title of a section.")
        self.assertIn("\u201cPlan\u201d", changes.words([], [gone], {"ABC-S-012": "Plan"}))

    def test_the_words_for_each_kind_of_undo(self):
        added = self.ok("new", values={"title": "Plan"})
        self.assertEqual(self.undone(added["apply_id"])[1]["words"], "Put back: the new section \u201cPlan\u201d was removed.")
        deleted = self.ok("delete", id="ABC-S-005")
        self.assertEqual(self.undone(deleted["apply_id"])[1]["words"], "Put back: the section \u201cSummary\u201d is back.")
        hidden = self.ok("update", id="ABC-S-005", changes={"hidden": 1})
        self.assertEqual(self.undone(hidden["apply_id"])[1]["words"], "Put back: \u201cSummary\u201d is shown again.")
        moved = self.ok("move", id="ABC-S-009", before="ABC-S-002")
        self.assertEqual(self.undone(moved["apply_id"])[1]["words"], "Put back: the place of \u201cOpen actions\u201d.")

    def test_the_undo_of_an_undo_is_refused_by_the_route_and_works_in_the_store(self):
        step = self.ok("update", id="ABC-S-005", changes={"title": "Once"})["apply_id"]
        undo_step = self.undone(step)[1]["apply_id"]
        self.assertEqual(self.undone(undo_step), (400, {"ok": False, "message": changes.NO_UNDO, "code": "refused"}))
        self.assertEqual(self.s.undo(undo_step, USER)["skipped"], [])
        self.assertEqual(self.s.read(KIND, ref="ABC-S-005")["title"], "Once")

    def test_two_undos_of_one_step_at_once_make_one_undo_and_one_409(self):
        step = self.ok("update", id="ABC-S-005", changes={"title": "Once"})["apply_id"]
        results, gate = [], threading.Barrier(4)

        def go():
            gate.wait(10)
            results.append(self.undone(step)[0])
        threads = [threading.Thread(target=go) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(sorted(results), [200, 409, 409, 409])
        self.assertEqual(self.s.read(KIND, ref="ABC-S-005")["title"], "Summary")

    def test_the_check_and_the_undo_sit_under_one_lock(self):
        """The step's rows are checked and the undo made inside one critical section of changes.py (no gap for another request)."""
        calls = []
        real_step_rows, real_undo = store_module.Store.step_rows, store_module.Store.undo

        def step_rows(me, apply_id):
            calls.append(("check", changes.LOCK.locked()))
            return real_step_rows(me, apply_id)

        def undo(me, *a, **k):
            calls.append(("undo", changes.LOCK.locked()))
            return real_undo(me, *a, **k)
        step = self.ok("update", id="ABC-S-005", changes={"title": "Once"})["apply_id"]
        store_module.Store.step_rows, store_module.Store.undo = step_rows, undo
        try:
            self.assertEqual(self.undone(step)[0], 200)
        finally:
            store_module.Store.step_rows, store_module.Store.undo = real_step_rows, real_undo
        self.assertEqual(calls, [("check", True), ("undo", True)])

    def test_unknown_keys_in_an_undo_are_refused(self):
        self.assertEqual(self.undo([])[1]["message"], changes.NOT_JSON_OBJECT)
        self.assertEqual(self.undo({"project": "ABC", "apply_id": 1, "kind": KIND})[1]["message"],
                         "clark doesn't know 'kind' in that request.")
        self.assertEqual(self.undo({"apply_id": 1})[1]["message"], changes.BAD_PROJECT)


class OlderProject(Api):
    """A project made before #65 has no report_sections rows (the editor shows none and publish falls back to its seven
    defaults). Its first change makes the default sections first, in the same step (the Head's option b). Undo takes back only
    the person's change: the starting sections are protected like a new project's (SEED_VIA), so they stay."""
    code = "OLD"

    def old(self, code="OLD"):
        """A project made the way a pre-#65 one was: no seed, so no section row and no section in change_log."""
        with mock.patch.dict(store_module.AFTER_NEW, clear=True):
            with self.s.step("dashboard", USER) as st:
                st.create("projects", {"code": code, "name": "Older Programme"})
        self.code = code

    def setUp(self):
        super().setUp()
        self.old()

    def sections(self):
        return order.in_order(self.s.read(KIND, self.code))

    def published(self):
        return [(s["id"], s["title"]) for s in publish.select(publish.read_inputs(self.s, self.code, "2026-10-28"))["sections"]]

    def go(self, op, **more):
        return self.ok(op, project=self.code, **more)

    def test_each_first_change_seeds_the_defaults_in_its_own_step_and_undo_takes_back_only_the_change_and_the_seed_stays(self):
        defaults = [s["title"] for s in default_sections.DEFAULT_SECTIONS if s["type"] != "docs"]    # publish leaves "docs" out
        no_summary = [t for t in defaults if t != "Summary"]
        cases = (                                   # op, what it asks (S-005 is Summary, S-009 Open actions), sections and published after
            ("new", {"values": {"title": "Only me"}}, 12, defaults + ["Only me"]),
            ("update", {"id": "S-005", "changes": {"title": "Renamed"}}, 11, ["Renamed" if t == "Summary" else t for t in defaults]),
            ("move", {"id": "S-009", "before": "S-002"}, 11, defaults[:1] + ["Open actions"] + defaults[1:8] + defaults[9:]),
            ("update", {"id": "S-005", "changes": {"hidden": 1}}, 11, no_summary),
            ("update", {"id": "S-007", "changes": {"beside": 1}}, 11, defaults),
            ("delete", {"id": "S-005"}, 10, no_summary),
        )
        shape = lambda rows: [(r["id"], r["type"], r["title"], r["beside"], r["hidden"], r["sort_order"]) for r in rows]
        for n, (op, args, count, titles) in enumerate(cases):
            self.old(f"OL{n}")
            args = {k: (f"{self.code}-{v}" if k in ("id", "before") else v) for k, v in args.items()}
            with self.subTest(op=op, args=args):
                before = self.published()
                self.assertEqual(self.sections(), [])
                self.assertEqual([t for _, t in before], ["Current state", "At a glance", "Use cases", "Milestones", "Risks and issues",
                                                          "Actions", "Decisions"])            # publish's fallback: the seven
                steps = self.snapshot()[0]
                body = self.go(op, **args)
                self.assertEqual(body["apply_id"], steps + 1, "one step")
                self.assertEqual(len(self.sections()), count)
                self.assertEqual(sorted(r["id"] for r in self.sections())[:2], [f"{self.code}-S-001", f"{self.code}-S-002"])  # a new project's ids
                self.assertEqual([t for _, t in self.published()], titles)
                changed = shape(self.sections())
                status, out = self.undo({"project": self.code, "apply_id": body["apply_id"]})
                self.assertEqual((status, out["skipped"]), (200, []), out)
                kept = self.sections()
                self.assertEqual(len(kept), 11, "the eleven starting sections stay")
                self.assertEqual([r["title"] for r in kept], [s["title"] for s in default_sections.DEFAULT_SECTIONS])
                self.assertEqual([t for _, t in self.published()], defaults, "published: the defaults, not none and not the seven")
                self.assertEqual(shape(kept) == changed, False, "the person's change went back")
                self.assertEqual([r["sort_order"] for r in kept], [order.GAP * k for k in range(1, 12)])

    def test_a_later_change_to_a_starting_section_loses_no_seed_and_still_blocks_an_undo_of_that_section(self):
        added = self.go("new", values={"title": "Plan"})                      # step 1 seeds; step 2 changes a starting section
        self.go("update", id="OLD-S-005", changes={"title": "Later name"})
        status, out = self.undo({"project": "OLD", "apply_id": added["apply_id"]})
        self.assertEqual((status, out["skipped"]), (200, []))
        self.assertEqual(len(self.sections()), 11, "no starting section was lost")
        self.assertEqual(self.s.read(KIND, ref="OLD-S-005")["title"], "Later name")
        first = self.go("update", id="OLD-S-006", changes={"title": "First name"})["apply_id"]        # the rename is the first change
        later = self.go("update", id="OLD-S-006", changes={"title": "Second name"})["apply_id"]
        status, out = self.undo({"project": "OLD", "apply_id": first})
        self.assertEqual((status, [s["by_step"] for s in out["skipped"]]), (200, [later]))
        self.assertEqual((len(self.sections()), self.s.read(KIND, ref="OLD-S-006")["title"]), (11, "Second name"))

    def test_an_old_project_after_a_first_change_and_its_undo_is_a_new_projects_after_the_same(self):
        def settled(code):
            body = self.ok("new", project=code, values={"title": "Plan"})
            self.assertEqual(self.undo({"project": code, "apply_id": body["apply_id"]})[0], 200)
            return [(r["type"], r["title"], r["beside"], r["hidden"], r["sort_order"]) for r in order.in_order(self.s.read(KIND, code))]
        self.assertEqual(settled("OLD"), settled("ABC")[:11])
        self.assertEqual(len(settled("ABC")), 11)

    def test_the_ids_do_not_burn_twelve_for_each_add_and_undo(self):
        for _ in range(3):
            body = self.go("new", values={"title": "Plan"})
            self.assertEqual(self.undo({"project": "OLD", "apply_id": body["apply_id"]})[0], 200)
        self.assertEqual(self.go("new", values={"title": "Plan"})["ref"], "OLD-S-015")      # 11 starting ids, then one for each add

    def test_a_second_undo_of_an_old_projects_first_change_is_refused_as_undone_already(self):
        first = self.go("new", values={"title": "Plan"})["apply_id"]              # the step holds the seed rows and the add
        self.assertEqual(self.undo({"project": "OLD", "apply_id": first})[0], 200)
        before = self.snapshot()
        status, body = self.undo({"project": "OLD", "apply_id": first})
        self.assertEqual((status, body.get("ok"), body.get("message"), body.get("code")), (409, False, changes.UNDONE, "undone"))
        self.assertEqual(self.snapshot(), before, "nothing was written")
        self.assertEqual(len(self.sections()), 11, "the starting sections stay")

    def test_a_first_change_that_changes_nothing_still_seeds_but_offers_no_undo(self):
        for n, request in enumerate((self.req("update", id="S-005", changes={"hidden": 0}), self.req("update", id="S-005", changes={"title": "Summary"}),
                                     self.req("move", id="S-005", before="S-006"), self.req("move", id="S-011", before=None))):
            self.old(f"NO{n}")
            request = {**request, "project": self.code, "id": f"{self.code}-{request['id']}"}
            if request.get("before"):
                request["before"] = f"{self.code}-{request['before']}"
            with self.subTest(request=request):
                status, body = self.change(request)
                self.assertEqual((status, body["ok"], body["apply_id"], len(self.sections())), (200, True, None, 11))
                vias = {r[0] for r in self.s.con.execute("SELECT via FROM change_log WHERE item_id LIKE ?", (self.code + "-S-%",))}
                self.assertEqual(vias, {"seed"}, "the starting sections went in and nothing else")

    def test_a_second_change_does_not_seed_again(self):
        self.go("new", values={"title": "First"})
        steps, rows = self.snapshot()[0], self.sections()
        body = self.go("update", id=rows[-1]["id"], changes={"title": "Second"})
        self.assertEqual((body["apply_id"], len(self.sections())), (steps + 1, 12))
        self.assertEqual({r[0] for r in self.s.con.execute("SELECT item_id FROM change_log WHERE apply_id = ?", (body["apply_id"],))},
                         {rows[-1]["id"]})

    def test_a_project_that_has_sections_is_not_seeded(self):
        steps = self.snapshot()[0]
        self.ok("new", values={"title": "Plan"})
        self.assertEqual((self.snapshot()[0], len(self.rows())), (steps + 1, 12))

    def test_a_refused_change_seeds_nothing(self):
        for request in ({"id": "OLD-S-099", "changes": {"title": "x"}}, {"id": "OLD-S-005", "changes": {"title": ""}}):
            with self.subTest(request=request):
                before = self.snapshot()
                status, body = self.change(self.req("update", project="OLD", **request))
                self.assertEqual((status, body["ok"], self.snapshot(), self.sections()), (400, False, before, []))


class ByUser(Api):
    def test_by_user_is_the_login_name_unless_given(self):
        from clark import platform
        change = changes.make_change(self.path, [])
        body = change(self.req("update", id="ABC-S-005", changes={"title": "Who"}))[1]
        who = self.s.con.execute("SELECT by_user FROM applies WHERE apply_id = ?", (body["apply_id"],)).fetchone()[0]
        self.assertEqual(who, platform.login_name())
        self.assertTrue(who.strip())
        change = changes.make_change(self.path, [], lambda: "Someone Else")
        body = change(self.req("update", id="ABC-S-005", changes={"title": "Who again"}))[1]
        self.assertEqual(self.s.con.execute("SELECT by_user FROM applies WHERE apply_id = ?", (body["apply_id"],)).fetchone()[0],
                         "Someone Else")


ITEM_FIELDS = {"actions": {"status", "workstream", "owner", "priority", "due_date", "milestone", "use_case", "description"},
               "raid": {"status", "workstream", "owner", "due_date", "milestone", "use_case", "description"},
               "decisions": {"status", "made_by", "needed_by", "date", "use_case", "decision"}}      # #67: + the title


class Items(Api):
    """#68: the work items board changes one item's fields: one request is one step and one Undo; nothing else is reachable."""

    def setUp(self):
        super().setUp()
        self.a = self.demo.action(workstream="Build", owner="Sara Khan")
        self.ms = self.demo.milestone
        with self.s.step("dashboard", USER) as st:
            self.r = st.create("raid", {"project": "ABC", "type": "Risk", "description": "Supplier slips", "impact": "High",
                                        "likelihood": "Medium", "raised": "2026-10-01", "source": "demo"})
            self.d = st.create("decisions", {"project": "ABC", "decision": "Use the new tool", "status": "Pending",
                                             "needed_by": "2030-01-05", "source": "demo"})
            st.create("projects", {"code": "XYZ", "name": "Other Programme", "health": "On track"})
            st.create("workstreams", {"project": "XYZ", "name": "Other", "source": "demo"})
            self.xms = st.create("milestones", {"project": "XYZ", "name": "Their go-live", "baseline_date": "2030-03-01", "source": "demo"})
            self.xa = st.create("actions", {"project": "XYZ", "description": "Theirs", "raised": "2026-10-01", "source": "demo"})

    def item(self, kind, ref, **changes_):
        return {"project": "ABC", "kind": kind, "op": "update", "id": ref, "changes": changes_, "place": "cell"}

    def go(self, kind, ref, **changes_):
        status, body = self.change(self.item(kind, ref, **changes_))
        self.assertEqual((status, body.get("message")), (200, None), body)
        return body

    def snap(self):
        con = sqlite3.connect(str(self.path))
        try:
            return tuple(con.execute(f"SELECT count(*), group_concat(updated_at || status) FROM {t}").fetchone() for t in ("actions", "raid", "decisions")) + \
                (con.execute("SELECT count(*) FROM applies").fetchone()[0], con.execute("SELECT count(*) FROM change_log").fetchone()[0])
        finally:
            con.close()

    def no(self, request, words, status=400):
        before = self.snap()
        got = self.change(request)
        self.assertEqual((got[0], got[1]["ok"], got[1]["message"]), (status, False, words), request)
        self.assertEqual(self.snap(), before, "nothing was written")

    def test_the_before_raised_sentence_lives_in_one_place_and_the_route_key_is_part_of_it(self):
        from clark import changes, store
        said = "This item can't be closed or cancelled before the day it was raised. Check the raised date, then try again."
        self.assertEqual(store.BEFORE_RAISED, said)
        self.assertIs(changes.BEFORE_RAISED, store.BEFORE_RAISED)
        self.assertIn(store.BEFORE_RAISED_KEY, store.BEFORE_RAISED)
        self.assertEqual(changes._store_words(store.Invalid(store.BEFORE_RAISED)), said)

    def test_closing_or_cancelling_an_item_raised_in_the_future_says_so_in_plain_words_and_writes_nothing(self):
        """#135: it was a bare 500 (an unhandled database error); then the generic 'value' sentence."""
        said = "This item can't be closed or cancelled before the day it was raised. Check the raised date, then try again."
        for kind, extra in (("actions", {}), ("raid", {"type": "Risk"})):
            with self.s.step("dashboard", USER) as st:
                future = st.create(kind, {"project": "ABC", "description": "Later", "raised": "2999-01-01", "source": "demo", **extra})
            before = self.snap()
            for status in ("Closed", "Cancelled"):
                code, body = self.change(self.item(kind, future, status=status))
                self.assertEqual((code, body["ok"], body["message"]), (400, False, said), (kind, status))
            self.assertEqual(self.snap(), before, "nothing was written")
            self.go(kind, future, owner="Sam Example")

    # kinds and fields

    def test_the_fields_are_columns_and_priority_and_archived_are_never_in_the_wrong_list(self):
        columns = {k: set(store_module.columns(self.s.con, k)) for k in changes.ITEM_KINDS}
        for kind, fields in ITEM_FIELDS.items():
            self.assertEqual(set(changes.CHANGE_KINDS[kind]), {"update", "archive", "restore", "new", "bulk", "handover"}, kind)      # #67: + new; #196: + bulk; #199: + handover
            self.assertTrue(set(changes.CHANGE_KINDS[kind]["bulk"]) <= columns[kind], kind)
            for never in ("archived", "id", "project", "type", "client_visible", "closed", "description", "decision"):
                self.assertNotIn(never, changes.CHANGE_KINDS[kind]["bulk"], (kind, never))
            self.assertEqual(set(changes.CHANGE_KINDS[kind]["update"]), fields, kind)
            self.assertTrue(fields <= columns[kind], kind)
            self.assertTrue(set(changes.ITEM_SHOWN[kind]) <= columns[kind], kind)
            for never in ("archived", "id", "project", "type", "client_visible", "closed"):
                self.assertNotIn(never, fields, (kind, never))
        self.assertNotIn("priority", changes.CHANGE_KINDS["raid"]["update"])
        self.assertNotIn("priority", changes.CHANGE_KINDS["raid"]["bulk"])

    def test_one_request_with_several_fields_is_one_step_and_one_undo(self):
        body = self.go("actions", self.a, status="Closed", workstream=None)
        self.assertEqual({r["key"] for r in self.s.step_rows(body["apply_id"])}, {self.a}, "one row changed")
        row = self.s.read("actions", ref=self.a)
        self.assertEqual((row["status"], row["workstream"], row["closed"] is not None), ("Closed", None, True))
        self.assertEqual({k: body["item"][k] for k in ("id", "status", "workstream")}, {"id": self.a, "status": "Closed", "workstream": None})
        self.assertNotIn("description", body["item"])
        steps = self.snap()[3]
        status, back = self.undone(body["apply_id"])
        self.assertEqual(status, 200, back)
        row = self.s.read("actions", ref=self.a)
        self.assertEqual((row["status"], row["workstream"], row["closed"]), ("Open", "Build", None))
        self.assertEqual(self.snap()[3], steps + 1, "the undo is one step")
        self.assertIn(self.a, back["words"])
        self.assertNotIn("section", back["words"])

    def test_closing_and_reopening_through_the_store(self):
        self.go("actions", self.a, status="Cancelled")
        self.assertIsNotNone(self.s.read("actions", ref=self.a)["closed"])
        self.go("actions", self.a, status="Delayed")
        self.assertIsNone(self.s.read("actions", ref=self.a)["closed"])

    def test_each_kind_takes_its_own_fields(self):
        self.go("actions", self.a, priority="Urgent", owner="Omar Reid", due_date="2020-01-01", milestone=self.ms)
        row = self.s.read("actions", ref=self.a)
        self.assertEqual((row["priority"], row["owner"], row["due_date"], row["milestone"]), ("Urgent", "Omar Reid", "2020-01-01", self.ms))
        self.go("actions", self.a, due_date=None, milestone=None)
        self.assertEqual(self.s.read("actions", ref=self.a)["due_date"], None)
        self.go("raid", self.r, status="Closed", workstream="Build")
        self.assertEqual(self.s.read("raid", ref=self.r)["priority"], "High", "worked out, untouched")
        self.go("decisions", self.d, made_by="Sara Khan", needed_by=None)
        self.go("decisions", self.d, status="Made", date="2026-10-29")
        self.assertEqual(self.s.read("decisions", ref=self.d)["status"], "Made")

    def test_a_past_due_date_is_accepted_the_rule_is_the_pages(self):
        self.go("actions", self.a, due_date="2001-02-03")
        self.assertEqual(self.s.read("actions", ref=self.a)["due_date"], "2001-02-03")

    def test_a_change_that_changes_nothing_has_no_undo(self):
        self.assertIsNone(self.go("actions", self.a, status="Open")["apply_id"])

    def test_the_stores_rules_come_back_in_words_with_nothing_written(self):
        for request in (self.item("actions", self.a, workstream="Nowhere"), self.item("actions", self.a, milestone=self.xms),
                        self.item("actions", self.a, status="Paused"), self.item("raid", self.r, status="Delayed"),
                        self.item("actions", self.a, due_date="not a date"), self.item("decisions", self.d, status="Made")):
            with self.subTest(request=request):
                before = self.snap()
                status, body = self.change(request)
                self.assertEqual((status, body["ok"]), (400, False), body)
                self.assertTrue(body["message"])
                self.assertNotIn("sqlite", body["message"].lower())
                self.assertEqual(self.snap(), before)
        self.go("decisions", self.d, status="Made", date="2026-10-29")
        self.no(self.item("decisions", self.d, status="Pending"), changes.MADE_STAYS)

    def test_a_refusal_never_carries_a_field_name_or_the_value_sent(self):
        hostile = "nope <b>x</b> %s {0}"
        self.go("decisions", self.d, status="Made", date="2026-10-29")
        pending = self.demo.action()
        cases = [(self.item("actions", self.a, due_date=hostile), changes.NOT_A_DATE),
                 (self.item("actions", self.a, due_date="2026-02-31"), changes.NOT_A_DATE),
                 (self.item("actions", self.a, due_date="2026-13-45"), changes.NOT_A_DATE),
                 (self.item("actions", self.a, status="Paused"), changes.NOT_A_STATUS),
                 (self.item("actions", self.a, priority="Whenever"), changes.NOT_A_STATUS),
                 (self.item("raid", self.r, status="Delayed"), changes.NOT_A_STATUS),
                 (self.item("decisions", self.d, needed_by="soon"), changes.NOT_A_DATE),
                 (self.item("decisions", self.d, date="yesterday"), changes.NOT_A_DATE),
                 (self.item("decisions", self.d, status="Elsewhere"), changes.NOT_A_STATUS),
                 (self.item("actions", self.a, workstream="Nowhere"), changes.NO_WORKSTREAM),
                 (self.item("actions", self.a, workstream="Nowhere \u202e"), changes.ITEM_TEXT_WORDS),
                 (self.item("actions", self.a, milestone=self.xms), changes.NO_MILESTONE),
                 (self.item("actions", self.a, milestone="ABC-M-099"), changes.NO_MILESTONE),
                 (self.item("actions", self.a, milestone="XYZ-M-999"), changes.NO_MILESTONE),
                 (self.item("decisions", self.d, status="Pending"), changes.MADE_STAYS)]
        for request, words in cases:
            with self.subTest(request=request["changes"]):
                self.no(request, words)
        self.assertEqual(self.s.read("actions", ref=pending)["status"], "Open")
        self.no(self.item("actions", self.a, due_date="nope\u202e\n\x00"), changes.ITEM_TEXT_WORDS)

    def test_the_decision_rules_have_their_own_words(self):
        self.no(self.item("decisions", self.d, status="Made"), changes.DECISION_NEEDS_DATE)
        self.no(self.item("decisions", self.d, date="2026-10-29"), changes.DECISION_NOT_MADE)

    def test_no_store_sentence_reaches_a_reply_whatever_the_value(self):
        for field, value in (("due_date", "x" * 150), ("status", "\ud83d"), ("milestone", "' OR 1=1 --"), ("workstream", "%s%s")):
            with self.subTest(field=field):
                status, body = self.change(self.item("actions", self.a, **{field: value}))
                self.assertEqual((status, body["ok"]), (400, False), body)
                for leak in ("must be", "got ", "stored as", "YYYY", "due_date", "OR 1=1", "x" * 20, "belongs to"):
                    self.assertNotIn(leak, body["message"])

    def test_owner_and_decider_take_plain_text_only(self):
        bad = ["Ana\nBob", "Ana\x00", "Ana\ud800", "\u202eAna", "A\u200bna", "Ana\tBob", "Ana\u2028", "Ana\ue000", "\x1b[31mAna", "Ana\x7f"]
        for value in bad:
            for kind, ref, field in (("actions", self.a, "owner"), ("raid", self.r, "owner"), ("decisions", self.d, "made_by")):
                with self.subTest(kind=kind, value=value):
                    self.no(self.item(kind, ref, **{field: value}), changes.ITEM_TEXT_WORDS)
                    self.no(self.item(kind, ref, **{field: value, "status": "Closed" if kind != "decisions" else "Made"}), changes.ITEM_TEXT_WORDS)
        self.no(self.item("actions", self.a, workstream="Build\u200b"), changes.ITEM_TEXT_WORDS)
        self.no(self.item("actions", self.a, due_date="2026-10-01\n"), changes.ITEM_TEXT_WORDS)

    def test_ordinary_names_are_still_taken_and_trimmed(self):
        for name in ("Ana", "  Sara Khan  ", "Zoë O’Neil-Ng", "李明", "J. R. R. Tolkien (PMO) & Co", "<b>Ana</b>"):
            with self.subTest(name=name):
                self.go("actions", self.a, owner=name)
                self.assertEqual(self.s.read("actions", ref=self.a)["owner"], name.strip())
        self.go("decisions", self.d, made_by="Ana")
        self.assertEqual(self.s.read("decisions", ref=self.d)["made_by"], "Ana")

    def test_an_inactive_workstream_is_refused(self):
        with self.s.step("dashboard", USER) as st:
            st.create("workstreams", {"project": "ABC", "name": "Old", "source": "demo"})
        ws = [w for w in self.s.read("workstreams", "ABC") if w["name"] == "Old"][0]
        with self.s.step("dashboard", USER) as st:
            st.update("workstreams", ws["id"], {"status": "Closed"})
        before = self.snap()
        status, body = self.change(self.item("actions", self.a, workstream="Old"))
        self.assertEqual((status, body["ok"]), (400, False))
        self.assertEqual(self.snap(), before)

    # the words for what a work item never takes

    def test_no_delete_or_move_for_a_work_item(self):      # #67: `new` is allowed now (tests/test_changes_hidden.py)
        for kind, ref in (("actions", self.a), ("raid", self.r), ("decisions", self.d)):
            for op, more in (("delete", {"id": ref}), ("move", {"id": ref, "before": None}),
                             ("cancel", {"id": ref}), ("", {})):
                with self.subTest(kind=kind, op=op):
                    self.no({"project": "ABC", "kind": kind, "op": op, **more}, changes.BAD_OP)
        self.assertEqual(self.snap()[0][0], 2)

    def test_archived_is_refused_however_it_is_sent(self):
        for kind, ref in (("actions", self.a), ("raid", self.r), ("decisions", self.d)):
            for value in (1, 0, True, "1", None):
                with self.subTest(kind=kind, value=value):
                    self.no(self.item(kind, ref, archived=value), changes.NO_ARCHIVE)
                    self.no(self.item(kind, ref, archived=value, status="Closed"), changes.NO_ARCHIVE)
        self.assertEqual(changes.NO_ARCHIVE, "An item can't be archived by editing its details. Archiving isn't available from the page yet. Ask the clark team if you need an item hidden now.")
        self.assertEqual(self.s.read("actions", ref=self.a)["archived"], 0)

    def test_unknown_and_never_fields_are_refused(self):
        self.no(self.item("actions", self.a, client_message="x"), "The field 'client_message' can't be set here.")
        self.no(self.item("actions", self.a, client_visible=0), "The field 'client_visible' can't be set here.")
        self.no(self.item("actions", self.a, closed="2026-10-02"), "The field 'closed' can't be set here.")
        self.no(self.item("actions", self.a, project="XYZ"), "The field 'project' can't be set here.")
        self.no(self.item("actions", self.a, id="ABC-A-099"), "The field 'id' can't be set here.")
        self.no(self.item("actions", self.a, colour="red"), "The field 'colour' can't be set here.")
        self.no(self.item("actions", self.a, type="raid"), changes.ITEM_KEEPS_TYPE)
        self.no(self.item("raid", self.r, type="Issue"), changes.ITEM_KEEPS_TYPE)
        self.no(self.item("raid", self.r, impact="Low"), "The field 'impact' can't be set here.")
        self.no(self.item("actions", self.a, **{"status; DROP TABLE actions": "x"}), "The field 'status DROP TABLE actions' can't be set here.")
        self.no({**self.item("actions", self.a, status="Closed"), "values": {}}, "That change doesn't take 'values'.")
        self.no({**self.item("actions", self.a, status="Closed"), "after": None}, "That change doesn't take 'after'.")
        self.no(self.item("actions", self.a), "Say what to change.")
        self.no({**self.item("actions", self.a), "changes": ["status"]}, "Send the changes as an object.")

    def test_a_risks_priority_and_a_decisions_workstream_have_their_own_words(self):
        self.no(self.item("raid", self.r, priority="Low"), changes.NO_RAID_PRIORITY)
        self.assertEqual(changes.NO_RAID_PRIORITY, "A risk or issue's priority comes from its impact and likelihood. Change those in its details.", "the prototype never says RAID")
        self.assertEqual(changes.NOT_A_DATE, "That isn't a date. Pick a day from the calendar.")
        self.assertEqual(changes.MADE_STAYS, "A decision that has been made can't go back to Pending. Record a new decision that replaces it.")
        self.assertEqual(changes._kind_word("ABC-001"), "risk or issue")
        self.no(self.item("raid", self.r, priority="Low", status="Closed"), changes.NO_RAID_PRIORITY)
        self.no(self.item("decisions", self.d, workstream="Build"), "A decision isn't part of a workstream.")
        self.no(self.item("decisions", self.d, milestone=self.ms), "A decision isn't tied to a milestone.")
        self.no(self.item("decisions", self.d, priority="High"), "A decision has no priority.")
        self.assertEqual(self.s.read("raid", ref=self.r)["priority"], "High")

    def test_values_are_text_or_none_and_never_none_where_a_value_is_needed(self):
        for field in ("status", "owner", "priority"):
            self.no(self.item("actions", self.a, **{field: None}), changes.ITEM_VALUE_WORDS)
        for bad in (5, 1.5, True, ["Open"], {"a": 1}, "", "  ", "x" * 201):
            with self.subTest(bad=bad):
                self.no(self.item("actions", self.a, status=bad), changes.ITEM_VALUE_WORDS)
                self.no(self.item("actions", self.a, due_date=bad), changes.ITEM_VALUE_WORDS)

    # whose item it is

    def test_a_stale_missing_or_other_projects_id_is_refused_with_the_same_words(self):
        for kind, ref in (("actions", "ABC-A-099"), ("actions", self.xa), ("raid", "ABC-099"), ("decisions", "ABC-D-099"),
                          ("actions", self.r), ("raid", self.a), ("actions", None), ("actions", 5), ("actions", ["x"]),
                          ("actions", "' OR 1=1 --"), ("actions", ""), ("actions", self.d), ("decisions", self.xa)):
            with self.subTest(kind=kind, ref=ref):
                self.no(self.item(kind, ref, status="Closed"), changes.ITEM_NOT_MINE)
        self.no({"project": "XYZ", "kind": "actions", "op": "update", "id": self.a, "changes": {"status": "Closed"}}, changes.ITEM_NOT_MINE)
        self.assertEqual(self.s.read("actions", ref=self.xa)["status"], "Open")

    def test_an_archived_item_is_not_found(self):
        con = sqlite3.connect(str(self.path))
        con.execute("UPDATE actions SET archived = 1 WHERE id = ?", (self.a,))
        con.commit()
        con.close()
        self.no(self.item("actions", self.a, status="Closed"), changes.ITEM_NOT_MINE)

    def test_a_missing_project_is_404_and_an_item_request_makes_no_section(self):
        got = self.change({**self.item("actions", self.a, status="Closed"), "project": "NOP"})
        self.assertEqual((got[0], got[1]["code"]), (404, "project_not_found"))
        sections = self.s.read("report_sections", "ABC")
        self.go("actions", self.a, status="Closed")
        self.assertEqual(self.s.read("report_sections", "ABC"), sections, "an item change leaves the sections alone")

    # place

    def test_the_place_of_an_item_change_is_kept_and_an_unknown_place_is_not_taken(self):
        body = self.go("actions", self.a, status="Closed")
        row = self.s.con.execute("SELECT place FROM item_events WHERE apply_id = ?", (body["apply_id"],)).fetchone()
        self.assertEqual(row[0], "cell")
        self.no({**self.item("actions", self.a, status="Open"), "place": "peeek"}, changes.BAD_PLACE)

    @unittest.skipUnless("board" in store_module.PLACES, "waits for 'board' in store.PLACES (store.py is guarded and not part of this change)")
    def test_the_board_is_a_place(self):
        self.assertIn("board", changes.PLACES)
        status, body = self.change({**self.item("actions", self.a, status="Closed"), "place": "board"})
        self.assertEqual((status, body.get("message")), (200, None), body)
        self.assertEqual(self.s.con.execute("SELECT place FROM item_events WHERE apply_id = ?", (body["apply_id"],)).fetchone()[0], "board")

    def test_board_is_not_taken_while_the_store_does_not_know_it(self):
        if "board" in store_module.PLACES:
            self.skipTest("the store knows 'board' now")
        self.no({**self.item("actions", self.a, status="Closed"), "place": "board"}, changes.BAD_PLACE)

    # undo

    def test_a_made_decision_has_no_undo_and_the_undo_route_says_so(self):
        body = self.go("decisions", self.d, status="Made", date="2026-10-29", made_by="Sara Khan")
        self.assertIsNone(body["apply_id"], "the page shows no Undo")
        self.assertIs(body["undoable"], False)
        step = self.s.con.execute("SELECT max(apply_id) FROM applies").fetchone()[0]
        before = self.snap()
        status, back = self.undone(step)
        self.assertEqual((status, back["ok"], back["message"], back["code"]), (409, False, changes.MADE_CANT_BE_PUT_BACK, "not_undoable"))
        self.assertEqual(self.snap(), before, "nothing was written")
        self.assertEqual(self.s.read("decisions", ref=self.d)["status"], "Made")
        for leak in ("Made can't", "Pending;", "status", "made_by"):
            self.assertNotIn(leak, back["message"])

    def test_other_changes_say_they_can_be_undone(self):
        self.assertIs(self.go("actions", self.a, status="Closed")["undoable"], True)
        self.assertIs(self.go("decisions", self.d, made_by="Ana")["undoable"], True)
        self.assertIs(self.go("actions", self.a, status="Closed")["undoable"], False, "a change that changed nothing")

    def test_a_made_decision_step_with_a_later_change_still_names_it_in_plain_words(self):
        step = self.go("decisions", self.d, made_by="Ana")["apply_id"]
        self.go("decisions", self.d, made_by="Bob")
        status, back = self.undone(step)
        self.assertEqual(status, 200)
        self.assertEqual([s["why"] for s in back["skipped"]], [changes.CHANGED_LATER])
        self.assertNotIn("has changed since", json.dumps(back))

    def test_undoing_a_creation_names_the_kind(self):
        with self.s.step("dashboard", USER) as st:
            ref = st.create("actions", {"project": "ABC", "description": "Made by hand", "raised": "2026-10-01", "source": "demo"})
        step = self.s.con.execute("SELECT max(apply_id) FROM applies").fetchone()[0]
        status, back = self.undone(step)
        self.assertEqual(status, 200, back)
        self.assertIn(f"the new action {ref} was removed", back["words"])
        self.assertNotIn("section", back["words"])

    def test_undo_is_this_projects_items_only_and_not_for_another_route(self):
        mine = self.go("actions", self.a, status="Closed")["apply_id"]
        other = changes.make_undo(self.path, [], USER)({"project": "XYZ", "apply_id": mine})
        self.assertEqual((other[0], other[1]["message"]), (400, changes.NO_UNDO))
        self.assertEqual(self.s.read("actions", ref=self.a)["status"], "Closed")
        elsewhere = self.demo.update("actions", self.a, {"owner": "Someone"})          # made via the dashboard route name, by hand
        con = sqlite3.connect(str(self.path))
        con.execute("UPDATE change_log SET via = 'minutes' WHERE apply_id = ?", (elsewhere,))
        con.commit()
        con.close()
        self.assertEqual(self.undone(elsewhere), (400, {"ok": False, "message": changes.NO_UNDO, "code": "refused"}))
        self.assertEqual(self.undone(mine)[0], 200)
        self.assertEqual(self.undone(mine)[0], 409, "twice is refused")

    def test_a_later_change_to_the_item_is_left_and_named_in_words(self):
        first = self.go("actions", self.a, owner="Omar Reid")["apply_id"]
        self.go("actions", self.a, owner="Mia Hale")
        status, body = self.undone(first)
        self.assertEqual(status, 200)
        self.assertEqual(self.s.read("actions", ref=self.a)["owner"], "Mia Hale")
        self.assertIn(self.a + " was changed later", body["words"])

    def test_a_sections_step_still_works_as_before(self):
        body = self.ok("new", values={"title": "Notes"})
        self.assertEqual(self.undone(body["apply_id"])[0], 200)

    def test_the_source_still_has_no_sql_and_the_item_branch_takes_no_table_name_from_the_request(self):
        tree = ast.parse((SRC / "clark" / "changes.py").read_text(encoding="utf-8"))
        fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_do_item_change"][0]
        self.assertFalse(any(isinstance(n, ast.Constant) and n.value in ("delete", "cancel") for n in ast.walk(fn)))
        self.assertNotIn("DELETE", ast.dump(fn))


class Source(unittest.TestCase):
    def test_no_request_text_reaches_sql(self):
        """changes.py holds no SQL and builds none, imports no database module and opens no connection of its own."""
        path = SRC / "clark" / "changes.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + [getattr(node, "module", None) or ""]
                self.assertFalse(any("sqlite" in n for n in names), names)
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, ("execute", "executemany", "executescript", "cursor", "connect"), node.lineno)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                words = node.value.split()               # as the one-writer test: SQL is written in capitals
                self.assertFalse(len(words) > 1 and words[0] in ("SELECT", "INSERT", "UPDATE", "DELETE", "PRAGMA", "DROP", "REPLACE"),
                                 f"changes.py:{node.lineno} reads like SQL")
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("open_store",)]
        self.assertEqual(len(calls), 1, "one place opens a store, and it is inside the per-call function")

    def test_each_call_opens_its_own_store_and_closes_it(self):
        opened = []
        real = store_module.open_store

        def spy(*a, **k):
            s = real(*a, **k)
            opened.append(s)
            return s
        demo = DemoStore()
        self.addCleanup(demo.close)
        change = changes.make_change(demo.store.path, [], USER)
        from unittest import mock
        with mock.patch.object(store_module, "open_store", spy):
            change({"project": "ABC", "kind": KIND, "op": "new"})
            change({"project": "ABC", "kind": KIND, "op": "new"})
        self.assertEqual(len(opened), 2)
        self.assertIsNot(opened[0], opened[1])
        self.assertNotIn(demo.store, opened)
        for s in opened:
            with self.assertRaises(sqlite3.ProgrammingError):
                s.con.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
