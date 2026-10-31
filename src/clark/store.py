"""The one writer of clark.db (#31). Guarded: a cut-down copy of creaite's tracker.py at v2.6.9 (db5adb2).

Every write goes through a Step: one BEGIN IMMEDIATE ... COMMIT, one `applies` row, one `change_log` row per field changed and
one `item_events` row per change, as in creaite. An undo copies creaite's `undo-changes` (revert_plan / revert_group): it is
a new step of ordinary rows with via "revert:<rowids>"; the step it reverses keeps undone_at NULL (Head ruling on #31,
28-10-2026). Only undoing an undo sets undone_at, on that undo's own step, so the change it reversed is in force again.

What is cut from tracker.py: proposals and staging, file operations, cards, promises, recode, the daily archiving of old closed items, rejected
fingerprints, the CLI, paths.py and the vault; deleting records (a work item closes as Cancelled, and any record can be
archived and restored, #126: nothing of the five kinds is ever deleted by a person). The one removal left is an Undo of a step that
created a row, which takes that row back out (undoing your own create is not deleting a record; it is logged as an ordinary step); creaite's backup engine (a zip, the vault, a copy
in OneDrive). clark's backups (#86) take creaite's `backup_db`: the SQL is below ("Backups"), the names, folder, timing and
retention are in backup.py, and `Store.step` takes one before every undo, import and first write of the day. What differs is
marked "clark:".

Standard library only, Python 3.9. Table and field names reach SQL only from TABLES and PRAGMA table_info, never from a caller.
"""
import collections
import json
import re
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from clark import platform
from clark.default_sections import DEFAULT_SECTIONS
from clark.order import GAP

SCHEMA = Path(__file__).with_name("schema.sql")
SCHEMA_V2 = Path(__file__).with_name("schema_v2.sql")      # #126: version 2's tables as they were made, frozen: migrate_to_2 reads this, never schema.sql
SCHEMA_VERSION = 2          # 2 (#126): documents can be archived

# ── Rules (mirror schema.sql; the schema is still the final check) ─────────────

TABLES = ("projects", "milestones", "workstreams", "actions", "raid", "decisions", "use_cases", "links", "labels",
          "item_labels", "updates", "report_sections", "glance_tiles", "report_hidden", "documents")
# clark: - promises, + use_cases, and + the report's own tables (#65, one amendment: the route admits only report_sections)
KEYS = {"projects": ("code",), "milestones": ("id",), "workstreams": ("id",), "actions": ("id",), "raid": ("id",),
        "decisions": ("id",), "use_cases": ("id",), "links": ("from_item", "to_item", "kind"), "labels": ("name",),
        "item_labels": ("item_id", "label"), "updates": ("week_ending", "project"),
        "report_sections": ("id",), "glance_tiles": ("project", "tile"), "report_hidden": ("project", "item_id"),
        "documents": ("project", "id")}
# clark (#65): a section's id holds its project's code, so one column finds the row (and next_id and history keep working)
REQUIRED_NEW = {
    "projects": ("code", "name"),
    "milestones": ("project", "name", "source"),
    "workstreams": ("project", "name", "source"),
    "actions": ("project", "description", "raised", "source"),
    "raid": ("project", "type", "description", "raised", "source"),
    "decisions": ("project", "decision", "source"),             # `date` is needed only once it is Made (check_row)
    "use_cases": ("project", "title", "status", "source"),      # clark
    "links": ("from_item", "to_item", "source"),
    "labels": ("name",),
    "item_labels": ("item_id", "label"),
    "updates": ("week_ending", "project", "health", "summary"),
    "report_sections": ("project", "type", "title"),                    # clark (#65)
    "glance_tiles": ("project", "tile"),                                # clark: its sort_order is a rule (0 is a number)
    "report_hidden": ("project", "item_id"),
    "documents": ("project", "title", "url"),                           # clark (#126): registered so it can be archived; see DOCUMENTS_LATER
}
ARCHIVE_KINDS = ("projects", "milestones", "actions", "raid", "decisions", "use_cases", "documents")   # what Step.archive takes (#126)
DOCUMENTS_LATER = "Documents can only be archived or restored here."
SECTION_TYPES = ("current", "glance", "usecases", "milestones", "text", "raid", "actions", "decisions", "docs")
ALLOWED = {
    ("report_sections", "type"): SECTION_TYPES,                         # clark (#65): the nine of schema.sql's CHECK
    ("glance_tiles", "tile"): ("health", "overdue", "risks", "decisions"),
    ("glance_tiles", "outline"): ("R", "A", "G", "N"),                  # and '' (a blank is never checked)
    ("actions", "status"): ("Open", "Delayed", "Closed", "Cancelled"),
    ("raid", "status"): ("Open", "Closed", "Cancelled"),
    ("milestones", "status"): ("Planned", "Done", "Cancelled"),
    ("milestones", "state"): ("Achieved", "On track", "At risk", "Slipped", "Overdue", "Forecast"),   # clark: + Forecast
    ("milestones", "movement"): ("hold", "rebaseline", "recover", "escalate"),                     # clark
    ("workstreams", "status"): ("Active", "Closed"),
    ("actions", "priority"): ("Urgent", "High", "Medium", "Low"),
    ("raid", "type"): ("Risk", "Assumption", "Issue", "Dependency"),
    ("raid", "impact"): ("High", "Medium", "Low"),
    ("raid", "likelihood"): ("High", "Medium", "Low"),
    ("decisions", "status"): ("Pending", "Made", "Withdrawn"),
    ("use_cases", "status"): ("On track", "Flag", "High risk"),                                    # clark
    ("links", "kind"): ("blocks",),
    ("labels", "behaviour"): ("warn", "exclude"),
    ("labels", "default_choice"): ("include", "exclude"),
    ("projects", "health"): ("On track", "At risk", "Off track"),
    ("projects", "layout"): ("boxed", "spine", "cover"),                                           # clark
    ("updates", "health"): ("On track", "At risk", "Off track"),
}
CODE_RE = r"[A-Z][A-Z0-9]{2,6}"      # project codes: 3 to 7 capital letters or digits, starting with a letter
DATE_FIELDS = {"due_date", "raised", "closed", "date", "week_ending", "baseline_date", "forecast_date", "created",
               "needed_by", "actual_date"}
NO_EDIT = {"id", "updated_at"}
ID_PREFIX = {"actions": "-A-", "decisions": "-D-", "raid": "-", "milestones": "-M-", "workstreams": "-W-",
             "use_cases": "-U-", "report_sections": "-S-"}              # clark: - promises, + use cases, + sections (#65)
# ITEM_ID and ITEM_TABLE below stay as they are: a section is not linkable and carries no label
ITEM_ID = re.compile(r"([A-Z][A-Z0-9]{2,6})-(?:([ADMWU])-)?\d{3}")
ITEM_TABLE = {"A": "actions", "D": "decisions", "M": "milestones", "W": "workstreams", "U": "use_cases", None: "raid"}
LINKABLE = ("actions", "raid", "milestones", "decisions")               # either end of a link
LABELLED = ("actions", "raid", "decisions")                             # items that carry labels
ITEM_EXTRAS = ("labels", "label_reason", "label_suggested")              # on an item's values or changes, not columns
REMOVED = "(removed)"                 # change_log field for a deleted links / item_labels / labels row: old_value is the row as JSON
COLOUR_RE = r"[A-Za-z0-9#(),.% -]{1,30}"
CLOSED_STATUSES = ("Closed", "Cancelled")
SHARED_NUMBERS = ("actions", "raid", "decisions")    # one number sequence per project: ABC-A-002 and ABC-002 never both exist
BLANKABLE = {"decisions": ("date", "needed_by", "replaces", "reasoning", "options", "revisit"),
             "milestones": ("state", "state_reason", "owner", "actual_date", "client_message", "description", "internal_note",
                            "movement", "workstream")}
CLOSING = {"actions": CLOSED_STATUSES, "raid": CLOSED_STATUSES}          # statuses that set `closed`
DELETED_ON_CANCEL = ("links", "item_labels", "labels", "report_sections", "glance_tiles", "report_hidden")
# the only rows a step deletes (Head ruling on #31; #65: + the report's own tables; delete_row refuses a section that isn't text)
MAX_SECTIONS = 100                                                       # a project's sections (#65)
TITLE_LIMIT = 120                                                        # a section's title, in characters
CANCEL_CHANGES = {"actions": {"status": "Cancelled"}, "raid": {"status": "Cancelled"}, "projects": {"active": 0},
                  "workstreams": {"status": "Closed"}}

# clark: a step's route, as item_events records it (data-model.md), and the vias it is written with.
ROUTES = ("dashboard", "assistant", "excel", "undo", "client", "team", "migrate")
PLACES = ("peek", "cell", "bulk", "menu", "report", "dashboard", "excel", "board")      # + board (#126)
ORIGINS = ("report", "sneak")
ACTORS = ("you", "clark")
REVERT_VIA = "revert:"
PUBLISH_TABLES = ("milestones", "workstreams", "actions", "raid", "decisions", "use_cases")     # what publish_inputs reads, in
# Columns publish_inputs refuses to read, whatever it is asked for: working notes and folders that no report carries (Head
# place that reads for a published file.
NEVER_PUBLISH = frozenset({"internal_note", "movement", "source", "reasoning", "options", "response_action", "keywords",
                           "aliases", "lead", "publish_local", "publish_client", "by_user", "device"})
PUBLISH_ORDER = {"milestones": "sort_order, id", "workstreams": "id", "actions": "id", "raid": "id", "decisions": "id",
                 "use_cases": "sort_order, id"}                                                  # this order
# #136: what the Movement read (Store.milestone_moves) may read from change_log: a fixed list, never a caller's. The internal
# note's history and every other field are not in it. `id` is only there so a milestone's creation can be told from a change.
# What "note" is here: a step's note (Step.update(note=...)) is a change_log row with field "note", history only; it is not the
# milestones.internal_note column, and no request can change that column (changes.py _do_milestone_change refuses it). A Hold's
# dated line (dates only) and a rebaseline's reason line are stored this way, so a "note" row can sit in `shown` in
# milestone_moves, kept because its step also has a dated or Movement row. What keeps its text off the page is not this tuple but
# the Movement view's entries_for, which drops every entry of kind "note" or "internal_note"; the internal_note field itself is not in
# MOVE_FIELDS, so its history is never read.
MOVE_FIELDS = ("id", "baseline_date", "forecast_date", "actual_date", "status", "state", "state_reason", "movement", "note")
MOVE_DATED = ("baseline_date", "forecast_date", "actual_date", "status", "state", "movement")    # a note counts only beside one
MOVE_PER_MILESTONE = 50                 # events kept for one milestone
MOVE_PER_PROJECT = 1000                 # events kept for the whole project
MOVE_PLACE_NAME = "Movement"            # the src_ref a Movement change is written with (the place stays "dashboard")
MOVE_DECISION = re.compile(r"\b[A-Z][A-Z0-9]{2,6}-D-\d{3}\b")
MOVE_SQL = (
    "SELECT c.rowid AS rowid, c.item_id, c.field, c.old_value, c.new_value, c.op, c.via, c.apply_id, a.by_user, a.undone_at, "
    "e.event_id, e.at, e.route, e.place, e.origin, e.actor, e.src_ref, e.undoes "
    "FROM change_log c JOIN item_events e ON e.change = c.rowid LEFT JOIN applies a ON a.apply_id = c.apply_id "
    "WHERE c.tbl = 'milestones' AND c.item_id >= ? AND c.item_id < ? AND c.field IN (%s)")
OP_MADE = "insert"                    # the log's word for a row a step made; the one place it is spelt, changes.py imports it
SEED_VIA = "seed"                     # clark (#65): the via of the default sections a step makes (_seed_sections); an Undo never removes them
PENDING_VIA = "revert:pending"        # an undo's rows until it knows which rows it put back
BATCH_UNDO = "Undo several"           # #197: the src_ref of a step that undid several steps at once (Store.undo_many)
MAX_UNDO_MANY = 100                   # #197: the most steps one batch undo takes (the page asks a second time above 25)
# /api/undo's body is held to 1 KB by server.py: 100 step numbers of up to 7 digits fit; 8-digit numbers over about 100 steps do not
# (the server refuses the body as too big, in plain words). Raising either limit means raising both.
REVERT_CREATED = ("actions", "raid", "decisions", "milestones", "use_cases", "links", "item_labels", "labels",
                  "report_sections")
# a creation of these may be undone. clark: + use cases, and + links and labels, which creaite left to "undo last apply";
# clark has only this one undo.
REVERT_CREATED += ("report_hidden",)    # #67: hiding a row from the report adds a report_hidden row; Undo takes it away (kept apart, so it merges with the other additions to the list above)
REVERT_REFS = (("actions", "milestone"), ("raid", "milestone"), ("decisions", "replaces"), ("links", "from_item"),
               ("links", "to_item"), ("item_labels", "item_id"),
               ("actions", "use_case"), ("raid", "use_case"), ("decisions", "use_case"),   # clark: + use_case
               ("item_labels", "label"))                                                # clark: a label still on an item


class Invalid(Exception):
    """A change breaks a rule; the message is shown to the person."""


class Unfinished(Invalid):
    """A restore stopped part-way and the next start can't finish it. The message says where the database you had is; the
    launcher shows it as it stands, not as its general "can't read the data" text."""


# ── Small helpers ─────────────────────────────────────────────────────────────

def clock():
    """The current time, in UTC (a test replaces this to fix the time)."""
    return datetime.now(timezone.utc)


def now():
    """UTC to the millisecond, so steps within one second keep their order (clark: UTC, as datetime('now') in schema.sql)."""
    return clock().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def today():
    """Today's date as YYYY-MM-DD."""
    return date.today().isoformat()


def shown(iso):
    """YYYY-MM-DD → DD-MM-YYYY for anything a person reads."""
    return f"{iso[8:10]}-{iso[5:7]}-{iso[0:4]}" if iso and len(iso) >= 10 else iso


def _table(table):
    """`table` if it is one the writer knows; the only way a table name reaches SQL."""
    if table not in TABLES:
        raise Invalid(f"unknown table {table!r}")
    return table


def columns(con, table):
    """The column names of a table."""
    return [r["name"] for r in con.execute(f"PRAGMA table_info({_table(table)})")]


def key_of(table, row):
    """A row's key as one string: its key columns joined with '|' (an ID, or e.g. 'week_ending|project')."""
    return "|".join(str(row[k]) for k in KEYS[table])


def where_key(table):
    """The SQL WHERE clause matching a table's key columns."""
    return " AND ".join(f"{k} = ?" for k in KEYS[_table(table)])


def key_values(table, key):
    """The key column values in a key string made by key_of."""
    return key.split("|") if len(KEYS[table]) > 1 else [key]


def item_table(item_id):
    """The table an item ID belongs to (A actions, D decisions, M milestones, W workstreams, U use cases, plain RAID), or None."""
    m = ITEM_ID.fullmatch(str(item_id or ""))
    return ITEM_TABLE[m.group(2)] if m else None


def item_row(con, item_id, tables=LINKABLE):
    """The row an item ID names, if it is in one of `tables` and exists; else None."""
    t = item_table(item_id)
    return fetch(con, t, item_id) if t in tables else None


def fetch(con, table, key):
    """The row of `table` with key `key`, or None."""
    values = key_values(table, key)
    if len(values) != len(KEYS[_table(table)]):          # #126: a bare id for a two-part key (a document's) is not a key: no row
        return None
    return con.execute(f"SELECT * FROM {_table(table)} WHERE {where_key(table)}", values).fetchone()


def text(v):
    """A value as change_log stores it: str, or None (so NULL and '' stay different). A bool is the whole number SQLite keeps
    ("1" or "0", never "True" or "False"), so the log says what the column holds and an undo can see it still does (#89)."""
    if isinstance(v, bool):
        return "1" if v else "0"
    return None if v is None else str(v)


def label_names(value):
    """A labels value (a list, or comma-separated text) as a list of trimmed names, in order, without repeats."""
    if value is None or value == "":
        return []
    names = value.split(",") if isinstance(value, str) else list(value)
    out = []
    for n in names:
        n = str(n).strip()
        if n and n.lower() not in [o.lower() for o in out]:
            out.append(n)
    return out


def canonical_labels(con, value):
    """Each name in `value` in the spelling of the labels table; an unknown label is refused, never created."""
    out = []
    for n in label_names(value):
        r = con.execute("SELECT name FROM labels WHERE name = ?", (n,)).fetchone()
        if not r:
            known = ", ".join(x[0] for x in con.execute("SELECT name FROM labels ORDER BY name")) or "none"
            raise Invalid(f"unknown label {n!r} (labels: {known}); add it in Settings first")
        out.append(r[0])
    return out


def labels_of(con, item_id):
    """An item's label names, in alphabetical order."""
    return [r[0] for r in con.execute("SELECT label FROM item_labels WHERE item_id = ? ORDER BY label COLLATE NOCASE",
                                      (item_id,))]


def blocks_reach(con, start, goal):
    """True if `start` blocks `goal`, directly or through other items (so a new link goal→start would close a loop)."""
    edges = {}
    for a, b in con.execute("SELECT from_item, to_item FROM links WHERE kind = 'blocks'"):
        edges.setdefault(a, []).append(b)
    seen, todo = set(), [start]
    while todo:
        n = todo.pop()
        if n == goal:
            return True
        if n not in seen:
            seen.add(n)
            todo.extend(edges.get(n, []))
    return False


def priority(impact, likelihood):
    """A risk or issue's priority from its impact and likelihood: Urgent, High, Medium or Low; None if either is unset."""
    if not impact or not likelihood:
        return None
    if impact == "High" and likelihood == "High":
        return "Urgent"
    if "High" in (impact, likelihood):
        return "High"
    if impact == "Low" and likelihood == "Low":
        return "Low"
    return "Medium"


def is_archived(con, code):
    """Whether project `code` is archived."""
    r = con.execute("SELECT archived FROM projects WHERE code = ?", (code,)).fetchone()
    return bool(r and r[0])


# ── Values and rows ───────────────────────────────────────────────────────────

# Every column the schema holds as a 0/1 flag (CHECK (x IN (0,1))). `archived` is validated like the rest (#126), but only
# archive and restore (and the Undo of them) ever set it: refuse_archived_field turns it away from a new row and an update. tests/test_store_flags.py reads schema.sql and fails if a flag column is not named here,
# so a new flag can't slip past the rule (#89).
FLAG_COLUMNS = frozenset({"active", "builtin", "suggested", "state_set", "client_visible", "beside", "hidden", "word", "archived"})
FLAGS_ELSEWHERE = frozenset({"archived"})       # also named here: the flags test still reads it (#89)


def flag_value(field, v):
    """A flag as the whole number the column holds: True and False become 1 and 0, 0 and 1 stay; anything else (0.0, 1.0, None,
    "", "1", 2, -1, a list) is refused in plain words, so what is stored and what is logged are the same (#89)."""
    if v is True or v is False:
        return int(v)
    if type(v) is int and v in (0, 1):
        return v
    raise Invalid(f"{field} must be 0 or 1 (got {v!r})")


def check_values(table, values):
    """Each value's own rules (dates, allowed values, flags, a label's colour and name), field by field, then a project's code.
    A flag is turned into 0 or 1 in place, before anything else reads it."""
    for f, v in values.items():
        if f in FLAG_COLUMNS:
            values[f] = flag_value(f, v)
            continue
        if v is None or v == "":
            continue
        _check_date(f, v)
        allowed = ALLOWED.get((table, f))
        if allowed and v not in allowed:
            raise Invalid(f"{f} must be one of {', '.join(allowed)} (got {v!r})")
        _check_number_and_flags(f, v)
        _check_label_value(table, f, v)
    if table == "projects" and "code" in values and not re.fullmatch(CODE_RE, str(values["code"])):
        raise Invalid(f"project code must be 3 to 7 capital letters or digits, starting with a letter "
                      f"(got {values['code']!r})")


def _check_date(f, v):
    if f in DATE_FIELDS:
        if not (isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)):
            raise Invalid(f"{f} must be a date stored as YYYY-MM-DD (got {v!r})")
        try:
            date.fromisoformat(v)
        except ValueError:
            raise Invalid(f"{f} is not a real date ({v!r})")


def _check_number_and_flags(f, v):
    if f == "percent_complete" and (isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 100):
        raise Invalid(f"percent_complete must be a whole number from 0 to 100 (got {v!r})")
    if f == "sort_order" and (isinstance(v, bool) or not isinstance(v, int)):
        raise Invalid(f"sort_order must be a whole number (got {v!r})")


def _check_label_value(table, f, v):
    if (table, f) == ("labels", "colour") and not re.fullmatch(COLOUR_RE, str(v)):
        raise Invalid(f"a label's colour is a short colour name or code (got {v!r})")
    if (table, f) == ("labels", "name") and (re.search(r"[,|]", str(v)) or not str(v).strip()):
        raise Invalid("a label's name can't be empty or hold a comma or a bar")


def check_row(con, table, row, changed):
    """Rules that need the whole row after the change, in creaite's order. clark: creaite's client-message rules
    (_client_headings, _client_complete) are not copied, because client wording is optional in clark (#24)."""
    for rule in ROW_RULES.get(table, ()):
        rule(con, table, row, changed)


def _decision_source(con, table, row, changed):
    if not (row.get("source") or "").strip():
        raise Invalid("a decision must record its source")


def _decision_rules(con, table, row, changed):
    check_decision(con, row, changed)


def _milestone_rules(con, table, row, changed):
    check_milestone(row, changed)


def _link_rules(con, table, row, changed):
    check_link(con, row)


def _item_label(con, table, row, changed):
    t = item_table(row.get("item_id"))
    if t not in LABELLED or not fetch(con, t, row["item_id"]):
        raise Invalid(f"{row.get('item_id')} isn't an action, RAID item or decision here, so it can't carry a label")
    row["label"] = canonical_labels(con, row.get("label"))[0]


def _label_name(con, table, row, changed):
    if "name" in changed:
        row["name"] = str(row.get("name") or "").strip()


def _item_workstream(con, table, row, changed):
    if "workstream" in changed and str(row.get("workstream") or "").strip():
        w = active_workstream(con, row.get("project"), row["workstream"])     # blank is still allowed
        if not w:
            raise Invalid(f"“{row['workstream']}” isn't an active workstream of {row.get('project')}: add it to "
                          f"{row.get('project')}'s workstreams first, or leave the workstream blank")
        row["workstream"] = w["name"]                                          # the workstream's own spelling


def _workstream_unique(con, table, row, changed):
    name = str(row.get("name") or "").strip()
    if row.get("lead") is not None and not str(row["lead"]).strip():
        row["lead"] = None
    same = con.execute("SELECT id, archived FROM workstreams WHERE project = ? AND name = ? COLLATE NOCASE AND id IS NOT ?",
                       (row.get("project"), name, row.get("id"))).fetchone()
    if same:
        if same[1]:
            raise Invalid(f"{row.get('project')} already has a workstream called “{name}” ({same[0]}), which is archived. "
                          "Restore it, or choose another name.")
        raise Invalid(f"{row.get('project')} already has a workstream called “{name}” ({same[0]})")


def _project_exists(con, table, row, changed):
    if row.get("project") and not con.execute("SELECT 1 FROM projects WHERE code = ?", (row["project"],)).fetchone():
        raise Invalid(f"project {row['project']} isn't here")
    if row.get("project") and is_archived(con, row["project"]):
        raise Invalid(f"Project {row['project']} is archived. Restore it first.")


def _milestone_link(con, table, row, changed):
    if row.get("milestone"):  # optional link; must exist, in the same project
        ms = con.execute("SELECT project, archived FROM milestones WHERE id = ?", (row["milestone"],)).fetchone()
        if not ms:
            raise Invalid(f"milestone {row['milestone']} isn't here")
        if ms[1] and "milestone" in changed:                  # #126: an item is not put on an archived milestone (one it already has stays)
            raise Invalid(f"Milestone {row['milestone']} is archived. Restore it first.")
        if row.get("project") and ms[0] != row["project"]:
            raise Invalid(f"milestone {row['milestone']} belongs to {ms[0]}, not {row['project']}")


def _use_case_link(con, table, row, changed):
    """clark (FR-31): a work item's use case exists, in the same project."""
    if str(row.get("use_case") or "").strip():
        uc = con.execute("SELECT project, archived FROM use_cases WHERE id = ?", (row["use_case"],)).fetchone()
        if not uc:
            raise Invalid(f"use case {row['use_case']} isn't here")
        if uc[1] and "use_case" in changed:                   # #126: as for a milestone
            raise Invalid(f"Use case {row['use_case']} is archived. Restore it first.")
        if row.get("project") and uc[0] != row["project"]:
            raise Invalid(f"use case {row['use_case']} belongs to {uc[0]}, not {row['project']}")


# control, format (bidi, zero-width), lone surrogate, private use, line and paragraph separator:
_BAD_TITLE_KINDS = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"})
# letters and symbols that draw nothing (the braille blank, the Hangul fillers, the musical null notehead, the object replacement mark): a title of only these looks blank
_BLANK_LOOKING = frozenset("\u2800\u115f\u1160\u3164\uffa0\U0001d159\ufffc")


def section_title(value):
    """clark (#65): a section's title as it is stored, or Invalid in plain words. Plain text only: made NFC and trimmed, then
    not blank, at most TITLE_LIMIT characters (code points), no control or Unicode format character (a bidi override such
    as U+202E, a zero-width space, a line break), and at least one visible letter, number, punctuation mark or symbol (not
    only marks, selectors, the braille blank, a Hangul filler, U+1D159 or U+FFFC), because a title reaches the published file and a title that
    shows nothing is blank. The title is never quoted back. (Which characters are letters is Python's Unicode table, so a
    character assigned in a later Unicode version may count as visible on one Python and not on another.)"""
    if not isinstance(value, str):
        raise Invalid("A title must be text.")
    title = unicodedata.normalize("NFC", value).strip()
    if not title:
        raise Invalid("A title can't be blank.")
    if any(unicodedata.category(c) in _BAD_TITLE_KINDS for c in title):
        raise Invalid("A title can't hold control or invisible characters.")
    if not any(unicodedata.category(c)[0] in "LNPS" and c not in _BLANK_LOOKING for c in title):     # not a lone mark, filler or selector
        raise Invalid("A title needs at least one visible letter, number or symbol.")
    if len(title) > TITLE_LIMIT:
        raise Invalid(f"A title can be at most {TITLE_LIMIT} characters.")
    return title


def _section_rules(con, table, row, changed):
    """clark (#65): a section's own rules, in plain words. Runs before the id exists on a new row, so the id rules need an id."""
    row["title"] = section_title(row.get("title"))
    if type(row.get("sort_order")) is not int:
        raise Invalid("A section needs its place in the report (sort_order, a whole number).")
    if row.get("body") not in (None, "") and (row.get("type") != "text" or not isinstance(row["body"], str)):
        raise Invalid("Only a text section has a body.")
    if row.get("id") and not str(row["id"]).startswith(f"{row.get('project')}-S-"):
        raise Invalid("That section's id doesn't belong to its project.")
    if "id" in changed or not row.get("id"):          # a new section, or one put back by an undo: never count the row itself
        n = con.execute("SELECT count(*) FROM report_sections WHERE project = ? AND id IS NOT ?",
                        (row.get("project"), row.get("id"))).fetchone()[0]
        if n >= MAX_SECTIONS:
            raise Invalid(f"A report can have at most {MAX_SECTIONS} sections.")


def _tile_rules(con, table, row, changed):
    """clark (#65, registered now, written by #45): a tile has its place; 0 is a place."""
    if type(row.get("sort_order")) is not int:
        raise Invalid("A tile needs its place in the row (sort_order, a whole number).")


def _hidden_item(con, table, row, changed):
    """clark (#65, registered now, written by #67): what the report hides is an item of this same project."""
    t = item_table(row.get("item_id"))
    found = fetch(con, t, row["item_id"]) if t in LINKABLE + ("use_cases",) else None
    if not found or found["project"] != row.get("project"):
        raise Invalid("That isn't an item of this project.")


_ITEM_RULES = (_item_workstream, _project_exists, _milestone_link, _use_case_link)
ROW_RULES = {
    "actions": _ITEM_RULES,
    "raid": _ITEM_RULES,
    "decisions": (_decision_source, _decision_rules, _project_exists, _use_case_link),
    "milestones": (_milestone_rules, _item_workstream, _project_exists),     # clark: + workstream, as on actions (#60)
    "use_cases": (_project_exists,),                                         # clark
    "documents": (_project_exists,),                                         # #126: a document is not restored inside an archived project
    "links": (_link_rules,),
    "item_labels": (_item_label,),
    "labels": (_label_name,),
    "workstreams": (_workstream_unique, _project_exists),
    "report_sections": (_project_exists, _section_rules),                    # clark (#65)
    "glance_tiles": (_project_exists, _tile_rules),
    "report_hidden": (_project_exists, _hidden_item),
}


def check_decision(con, row, changed):
    """A Made decision has its date; a Pending one has none; `replaces` names an earlier decision of the same project."""
    status = row.get("status") or "Made"
    has_date = bool(str(row.get("date") or "").strip())
    if status == "Made" and not has_date:
        raise Invalid("a decision that is Made needs its date (a Pending one has none until it is made)")
    if status == "Pending" and has_date:
        raise Invalid("a Pending decision has no date until it is made; leave date empty, or set status to Made")
    if str(row.get("replaces") or "").strip():
        old = fetch(con, "decisions", row["replaces"])
        if not old:
            raise Invalid(f"{row['replaces']} (replaced by this decision) isn't here")
        if row.get("project") and old["project"] != row["project"]:
            raise Invalid(f"{row['replaces']} belongs to {old['project']}, not {row['project']}")
        if row.get("id"):
            seen, nxt = {row["id"]}, old
            while nxt is not None:                      # no loop: A replaces B replaces A
                if nxt["id"] in seen:
                    raise Invalid(f"{row['id']} and {row['replaces']} would replace each other")
                seen.add(nxt["id"])
                nxt = fetch(con, "decisions", nxt["replaces"]) if nxt["replaces"] else None


def check_link(con, row):
    """Both ends exist (any project), they differ, and the links don't loop."""
    a, b = row.get("from_item"), row.get("to_item")
    for end, label in ((a, "from_item"), (b, "to_item")):
        if item_table(end) not in LINKABLE:
            raise Invalid(f"{label} {end!r} isn't an action, RAID item, milestone or decision ID")
        found = item_row(con, end)
        if not found:
            raise Invalid(f"{label} {end} isn't here")
        if found["archived"]:
            raise Invalid(f"{end} is archived. Restore it first.")
    if a == b:
        raise Invalid("an item can't block itself")
    if blocks_reach(con, b, a):
        raise Invalid(f"{b} already blocks {a}, so {a} can't block {b} (the links would loop)")


def active_workstream(con, project, name):
    """The project's Active workstream with this name (any case), or None."""
    return con.execute("SELECT * FROM workstreams WHERE project = ? AND name = ? COLLATE NOCASE AND status = 'Active'",
                       (project, str(name).strip())).fetchone()


# ── Milestones (creaite BL-186; the states themselves are #32) ────────────────

MS_STATES = ("Achieved", "On track", "At risk", "Slipped", "Overdue")
MS_RANK = {s: i for i, s in enumerate(MS_STATES)}


def suggested_state(row, on=None):
    """What the dates say: Achieved when Done; Overdue when the agreed date has passed; Slipped when the forecast is later than
    the agreed date; On track otherwise. At risk is only ever the person's call."""
    on = on or today()
    if row.get("status") == "Done":
        return "Achieved"
    base = row.get("baseline_date")
    fc = row.get("forecast_date") or base
    if base and base < on:
        return "Overdue"
    if base and fc and fc > base:
        return "Slipped"
    return "On track"


def norm_milestone(row, current, changed):
    """In place, before the checks: a state set by hand marks state_set (and clearing it returns the state to the dates); Done
    fills the achieved date (today if none is given) and leaving Done clears it; a Done milestone's state is Achieved or empty."""
    if "state" in changed and "state_set" not in changed:
        row["state_set"] = 1 if row.get("state") else 0
    if "state_set" in changed and not row.get("state_set"):
        row["state"] = None
    if not row.get("state"):
        row["state_set"] = 0
        if {"state", "state_set"} & changed:
            row["state_reason"] = None
    if "status" in changed:
        if row.get("status") == "Done":
            fc = row.get("forecast_date")                       # a forecast already passed is when it was done; else today
            row["actual_date"] = row.get("actual_date") or (fc if fc and fc <= today() else today())
            if "state" not in changed and row.get("state") not in (None, "Achieved"):
                row["state"], row["state_set"], row["state_reason"] = None, 0, None
        elif current is not None and current.get("status") == "Done":
            if "actual_date" not in changed:
                row["actual_date"] = None
            if "state" not in changed and row.get("state") == "Achieved":
                row["state"], row["state_set"], row["state_reason"] = None, 0, None


def check_milestone(row, changed):
    """A milestone's status and state agree (Done is Achieved; state_set exactly when a state is set) and a state set by hand
    that is better than the dates has a reason. clark: Forecast needs no reason (the date isn't agreed yet), and client wording
    is optional (#24), so creaite's last rule (a client-visible milestone needs its wording) is not copied."""
    state, status = row.get("state"), row.get("status") or "Planned"
    if state == "Achieved" and status != "Done":
        raise Invalid("an Achieved milestone is Done: set status Done (with the achieved date, actual_date)")
    if status == "Done" and state not in (None, "Achieved"):
        raise Invalid(f"a Done milestone is Achieved, not {state}; reopen it (status Planned) to give it another state")
    if bool(row.get("state_set")) != bool(state):
        raise Invalid("state_set is 1 exactly when a state is set; leave both empty and clark suggests the state from the dates")
    if {"state", "state_set", "state_reason"} & changed and state in MS_RANK and state != "Achieved":
        sug = suggested_state(row)
        if MS_RANK[state] < MS_RANK[sug] and not str(row.get("state_reason") or "").strip():
            raise Invalid(f"{state} is better than the dates suggest ({sug}): give a one-line reason (state_reason)")
    if {"actual_date", "status"} & changed and row.get("actual_date"):
        if status != "Done":
            raise Invalid("the achieved date (actual_date) is set only when the milestone is Done")
        if row["actual_date"] > today():
            raise Invalid(f"the achieved date can't be after today ({shown(row['actual_date'])})")


def rebaseline_of(item, current, row):
    """A change to an existing agreed date (baseline_date) is a rebaseline: it needs who agreed it, why and where (the item's
    `rebaseline`: agreed_with, reason, source) and records a decision. Returns the decision's values, or None (no rebaseline).
    clark: an undo puts the agreed date back without a new decision; it removes the rebaseline's own decision instead."""
    old, new = current.get("baseline_date"), row.get("baseline_date")
    if not old or old == new or item.get("revert"):
        return None
    rb = item.get("rebaseline") if isinstance(item.get("rebaseline"), dict) else {}
    who = rb.get("agreed_with")
    who = ", ".join(str(w).strip() for w in who if str(w).strip()) if isinstance(who, list) else str(who or "").strip()
    reason, source = str(rb.get("reason") or "").strip(), str(rb.get("source") or "").strip()
    missing = [w for w, v in (("who agreed it (agreed_with)", who), ("the reason", reason), ("the source", source)) if not v]
    if not new:
        raise Invalid("a milestone's agreed date (baseline_date) can't be cleared once agreed; rebaseline it to a new date")
    if missing:
        raise Invalid(f"changing the agreed date is a rebaseline and records a decision: give {', '.join(missing)} "
                      "in the item's rebaseline")
    when = str(rb.get("date") or "").strip() or today()
    return {"project": row["project"], "decision": f"{row['name']}: agreed date moves from {shown(old)} to {shown(new)}",
            "made_by": who, "date": when, "status": "Made", "reasoning": reason, "source": source}


# ── IDs ───────────────────────────────────────────────────────────────────────

def next_id(con, table, project):
    """The next ID for `table`. Actions, RAID items and decisions share one sequence per project, so a number is never used twice
    across them (ABC-A-002 means ABC-002 and ABC-D-002 are never issued). Milestones, workstreams and use cases keep their own.
    clark: an ID ever logged in change_log counts too, so undoing a creation (which deletes the row) never frees its number
    (Head ruling on #31)."""
    tables = SHARED_NUMBERS if table in SHARED_NUMBERS else (table,)
    n = 0
    for t in tables:
        prefix = f"{project}{ID_PREFIX[t]}"
        for (i,) in con.execute(f"SELECT id FROM {_table(t)} WHERE project = ? AND length(id) = ? AND id LIKE ? "
                                "UNION SELECT item_id FROM change_log WHERE tbl = ? AND length(item_id) = ? AND item_id LIKE ?",
                                (project, len(prefix) + 3, prefix + "%", t, len(prefix) + 3, prefix + "%")):
            tail = i[len(prefix):]
            if tail.isdigit():
                n = max(n, int(tail))
    if n + 1 > 999:
        if table == "report_sections":              # clark (#65): said of sections, in everyday words; a deleted section keeps its number
            raise Invalid(f"{project}'s report has used up all the section numbers clark has (999), so no more sections can be added.")
        raise Invalid(f"{project} has used every number it can for this kind of item (999). Close or archive old items first.")
    return f"{project}{ID_PREFIX[table]}{n + 1:03d}"


# ── Logging ───────────────────────────────────────────────────────────────────

def log(con, step, table, key, field, old, new, op, undoes=None):
    """Record one field's change in change_log under the step, so undo can reverse it, and its event (undoes: the change_log
    rowid an undo reverses)."""
    cur = con.execute("INSERT INTO change_log (at, apply_id, tbl, item_id, field, old_value, new_value, op, via) "
                      "VALUES (?,?,?,?,?,?,?,?,?)",
                      (now(), step.apply_id(), table, key, field, text(old), text(new), op, step.via))
    emit_event(con, cur.lastrowid, step, key, field, undoes)


def emit_event(con, rowid, step, key, field, undoes=None):
    """The item_events row for change_log row `rowid` (none for updated_at, as in creaite). clark: the route, place, origin and
    actor come from the step, not from creaite's EVENT_CTX global."""
    if field == "updated_at":
        return
    was = con.execute("SELECT event_id FROM item_events WHERE change = ? ORDER BY event_id DESC LIMIT 1",
                      (undoes,)).fetchone() if undoes else None
    con.execute("INSERT INTO item_events (at, apply_id, item_id, change, kind, route, place, origin, actor, src_ref, undoes) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (now(), step.apply_id(), key, rowid, "change", step.route, step.place, step.origin, step.actor, step.src_ref,
                 was[0] if was else None))


# ── Writing one item ──────────────────────────────────────────────────────────

def write_item(con, item, step):
    """Write one item ({table, op: new|update|cancel|archive|restore, values | id and changes}). Returns its key (the given ID for
    a new row). archive and restore (#126) are the only ops that set `archived`; each builds its own change here."""
    table, op = item.get("table"), item.get("op")
    _table(table)
    reverting = bool(item.get("revert"))
    if not reverting:
        refuse_archived_field(item)
    if op not in ("new", "update", "cancel", "archive", "restore"):
        raise Invalid(f"op must be new, update, cancel, archive or restore (got {op!r})")
    if table == "documents" and op in ("new", "update") and not reverting:    # clark (#126): no ID scheme, no url rule (doclinks) yet; only an Undo of an archive or restore writes it
        raise Invalid(DOCUMENTS_LATER)
    cols = columns(con, table)
    if op == "new":
        if not reverting:
            _refuse_label_on_archived(con, table, item.get("values") or {})
        return _insert_row(con, table, item, cols, step)
    if op in ("archive", "restore"):
        return _archive_or_restore(con, table, op, item, cols, step)
    key, current = _existing_row(con, table, item, op)
    if not reverting:
        _refuse_if_archived(table, key, current)
        _refuse_label_on_archived(con, table, current)
    if op == "cancel" and table in DELETED_ON_CANCEL:
        return delete_row(con, table, key, current, step)
    changes = _cancel_changes(table) if op == "cancel" else dict(item.get("changes") or {})
    return _update_row(con, table, item, key, current, changes, cols, step)


def refuse_archived_field(item):
    """`archived` is never set by an ordinary new item, update or cancel; only archive and restore set it."""
    if "archived" in (item.get("values") or {}) or "archived" in (item.get("changes") or {}):
        raise Invalid("Use Archive or Restore to hide or bring back a record.")


def _refuse_if_archived(table, key, current):
    """An archived row is read-only: only restore changes it (#126)."""
    if current.get("archived"):
        raise Invalid(f"{key} is archived. Restore it first.")


def _refuse_label_on_archived(con, table, row):
    """A label can't be put on or taken off an archived item (#126)."""
    if table == "item_labels":
        t = item_table(row.get("item_id"))
        found = fetch(con, t, row["item_id"]) if t in LABELLED else None
        if found is not None and found["archived"]:
            raise Invalid(f"{row['item_id']} is archived. Restore it first.")


PROJECT_CHILDREN = ("workstreams", "milestones", "use_cases", "actions", "raid", "decisions", "documents")   # the order they archive in


def _archive_project(con, code, current, cols, step):
    """Archive a project (#126), all in the caller's one step: its children first, then the project, so an Undo (newest first)
    puts the project back before its children. The project gets archived = 1 and active = 0 in the same UPDATE (the schema's
    CHECK needs both). A child already archived is left alone and not logged. Links, labels, weekly updates, report sections,
    tiles, hidden flags and publications stay as they are."""
    counts = {}
    for t in PROJECT_CHILDREN:
        n = 0
        for row in con.execute(f"SELECT * FROM {_table(t)} WHERE project = ? AND archived = 0 ORDER BY rowid", (code,)).fetchall():
            row = dict(row)
            key = key_of(t, row)
            _update_row(con, t, {"table": t, "op": "archive", "id": key}, key, row, {"archived": 1}, columns(con, t), step)
            n += 1
        counts[t] = n
    _update_row(con, "projects", {"table": "projects", "op": "archive", "id": code}, code, current,
                {"archived": 1, "active": 0}, cols, step)
    step.result = {"counts": counts, "found_step": True}
    return code


def _restore_project(con, code, current, cols, step):
    """Restore a project (#126), in one step and in the reverse order: the project first, with `active` put back to what it was
    before the archive, then only the children that the project's last archive step archived (a child archived earlier on its
    own stays archived). With no such step in the log, only the project comes back and step.result says so."""
    last = con.execute("SELECT rowid, apply_id FROM change_log WHERE tbl = 'projects' AND item_id = ? AND field = 'archived' "
                       "AND new_value = '1' ORDER BY rowid DESC LIMIT 1", (code,)).fetchone()
    changes = {"archived": 0}
    if last is not None:
        was = con.execute("SELECT old_value FROM change_log WHERE apply_id = ? AND tbl = 'projects' AND item_id = ? "
                          "AND field = 'active'", (last["apply_id"], code)).fetchone()
        if was is not None and was["old_value"] in ("0", "1"):
            changes["active"] = int(was["old_value"])
    _update_row(con, "projects", {"table": "projects", "op": "restore", "id": code}, code, current, changes, cols, step)
    counts = {t: 0 for t in PROJECT_CHILDREN}
    if last is not None:
        for t in PROJECT_CHILDREN:
            for r in con.execute("SELECT item_id FROM change_log WHERE apply_id = ? AND tbl = ? AND field = 'archived' "
                                 "AND new_value = '1' ORDER BY rowid", (last["apply_id"], t)).fetchall():
                row = fetch(con, t, r["item_id"])
                if row is not None and row["archived"]:
                    _update_row(con, t, {"table": t, "op": "restore", "id": r["item_id"]}, r["item_id"], dict(row),
                                {"archived": 0}, columns(con, t), step)
                    counts[t] += 1
    step.result = {"counts": counts, "found_step": last is not None}
    return code


def _archive_or_restore(con, table, op, item, cols, step):
    """Archive or restore one existing row (#126), through the ordinary update: checked, stamped and logged field by field.
    An archive checks only the flag, so a legacy row that breaks a later rule can still be archived; a restore runs the full
    row rules (a clash is refused in plain words). Status is never touched."""
    if table not in ARCHIVE_KINDS:
        raise Invalid("That kind of record can't be archived here.")
    key, current = _existing_row(con, table, item, op)
    if op == "archive" and current["archived"]:
        raise Invalid(f"{key} is already archived. Nothing was changed.")
    if op == "restore" and not current["archived"]:
        raise Invalid(f"{key} is not archived. Nothing was changed. Only an archived record can be restored.")
    if table == "projects":
        return _archive_project(con, key, current, cols, step) if op == "archive" else _restore_project(con, key, current, cols, step)
    return _update_row(con, table, item, key, current, {"archived": 1 if op == "archive" else 0}, cols, step)


def _cancel_changes(table):
    """What cancelling a row of `table` changes; a table not listed can't be cancelled (work items are never deleted)."""
    if table not in CANCEL_CHANGES:
        raise Invalid(f"{table} rows can't be cancelled; edit them instead")
    return dict(CANCEL_CHANGES[table])


def _take_extras(table, fields):
    """Pop the item's label fields (not columns) from `fields`; only actions, RAID items and decisions carry labels."""
    extras = {k: fields.pop(k) for k in ITEM_EXTRAS if k in fields}
    if extras and table not in LABELLED:
        raise Invalid("labels can only be put on actions, RAID items and decisions")
    return extras


def _existing_row(con, table, item, op):
    """(key, current row as a dict) for an update or a cancel."""
    key = item.get("id")
    if not key:
        raise Invalid(f"{op} needs the item's id")
    current = fetch(con, table, key)
    if current is None:
        raise Invalid(f"{key} is not in {table}")
    return key, dict(current)


def _insert_sql(con, table, values):
    """Insert `values` (column names already checked against the table) into `table`."""
    cols = set(columns(con, table))
    bad = set(values) - cols
    if bad:
        raise Invalid(f"unknown field(s) for {table}: {', '.join(sorted(bad))}")
    con.execute(f"INSERT INTO {_table(table)} ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
                list(values.values()))


# ---------- new rows ----------
def _new_workstream(values):
    values["name"] = str(values["name"]).strip()
    values.setdefault("created", today())


def _new_raid(values):
    values["priority"] = priority(values.get("impact"), values.get("likelihood"))


def _new_label(values):
    if values.get("builtin"):
        raise Invalid("built-in labels come with clark; a new label is never built in")
    values["name"] = str(values["name"]).strip()


def _new_milestone(values):
    norm_milestone(values, None, set(values))


def _new_link(values):
    values.setdefault("kind", "blocks")


def _new_project(values):
    """clark (#45, review MEDIUM 2): a new project's health reason is held to the same text rules as a change to it."""
    if "health_reason" in values:
        values["health_reason"] = health_reason_text(values["health_reason"])


NEW_HOOKS = {"projects": _new_project, "workstreams": _new_workstream, "raid": _new_raid, "labels": _new_label, "milestones": _new_milestone,
             "links": _new_link}


def _check_new_fields(table, values, cols):
    unknown = set(values) - set(cols)
    if unknown:
        raise Invalid(f"unknown field(s) for {table}: {', '.join(sorted(map(str, unknown)))}. "
                      f"Valid: {', '.join(c for c in cols if c not in NO_EDIT)}")
    if table in ID_PREFIX and values.get("id"):
        raise Invalid("new items carry no ID; clark gives them one")
    missing = [f for f in REQUIRED_NEW[table] if not str(values.get(f) or "").strip()]
    if missing:
        raise Invalid(f"missing required field(s): {', '.join(missing)}")


def _closed_for_new(table, values):
    if table in CLOSING:
        status = values.get("status") or "Open"
        if status in CLOSING[table]:
            values.setdefault("closed", today())
        else:
            values["closed"] = None


def blank_to_none(table, values):
    """In place: an empty text for an optional field is not set."""
    for f in BLANKABLE.get(table, ()):
        if f in values and values[f] is not None and not str(values[f]).strip():
            values[f] = None


def _insert_row(con, table, item, cols, step):
    """A new row: checked, normalised, given its ID, written and logged field by field."""
    values = dict(item.get("values") or {})
    extras = _take_extras(table, values)
    want = canonical_labels(con, extras.get("labels"))
    blank_to_none(table, values)
    _check_new_fields(table, values, cols)
    check_values(table, values)
    if table in NEW_HOOKS:
        NEW_HOOKS[table](values)
    _closed_for_new(table, values)
    _not_before_raised(table, values)
    check_row(con, table, values, set(values))
    if table in ID_PREFIX:
        values["id"] = next_id(con, table, values["project"])
    if "updated_at" in cols:
        values["updated_at"] = now()
    if fetch(con, table, key_of(table, values)):
        raise Invalid(f"{table} already has {key_of(table, values)}")
    values = {k: v for k, v in values.items() if v is not None}
    _insert_sql(con, table, values)
    key = key_of(table, values)
    row = fetch(con, table, key)
    for f in cols:
        if row[f] is not None and not (f == "archived" and not row[f]):     # a new row is never archived; not logged
            log(con, step, table, key, f, None, row[f], OP_MADE)
    if want:
        set_labels(con, key, want, extras.get("label_reason"), extras.get("label_suggested"), step)
    if table in AFTER_NEW:
        AFTER_NEW[table](con, key, step)
    return key


def _seed_sections(con, code, step):
    """clark (#65, FR-10): a new project starts with the default report sections (clark.default_sections), in its own step, so
    every project (the demo data too) has them. Ids and places are clark's. Their change_log rows carry SEED_VIA, so an Undo of
    the step (a new project's, or an old project's first change: Step.seed_sections) never takes the starting sections away."""
    was, step.via = step.via, SEED_VIA
    try:
        for n, section in enumerate(DEFAULT_SECTIONS, 1):
            values = {"project": code, "type": section["type"], "title": section["title"], "sort_order": GAP * n}
            if section.get("beside"):
                values["beside"] = 1
            write_item(con, {"table": "report_sections", "op": "new", "values": values}, step)
    finally:
        step.via = was


# clark (#45): the four tiles a project starts with, in order, and whether each is hidden. glance.py holds the same list for the
# page (glance.TILES, glance.DEFAULT_HIDDEN); a test says the two agree, so the writer does not import the page's module.
DEFAULT_TILES = (("health", 0), ("overdue", 0), ("risks", 0), ("decisions", 1))


def _seed_tiles(con, code, step):
    """clark (#45): give a project the four tile rows with the defaults, in the caller's step, with SEED_VIA. The rows are
    history only: an Undo of the step never removes them (REVERT_CREATED is not widened), and says nothing about them."""
    was, step.via = step.via, SEED_VIA
    try:
        for n, (tile, hidden) in enumerate(DEFAULT_TILES, 1):
            write_item(con, {"table": "glance_tiles", "op": "new",
                             "values": {"project": code, "tile": tile, "hidden": hidden, "outline": "", "sort_order": GAP * n}}, step)
    finally:
        step.via = was


# Decision (#45 review LOW, recorded for the Head): the tile rows are NOT seeded when a project is created. Nothing reads a missing row as
# an error: the editor and the published file take the four defaults from glance.tile_settings, and the rows are written, as
# history only, in the step of the first tile change (Step.seed_tiles). A test pins that a new project has no rows and shows the defaults.
AFTER_NEW = {"projects": _seed_sections}                   # run at the end of a new row's insert: table -> f(con, key, step)


def set_labels(con, item_id, want, reason, suggested, step):
    """Make `want` (canonical names) the item's label set: add the missing ones, remove the others, each logged."""
    have = labels_of(con, item_id)
    lower = {w.lower() for w in want}
    for old in have:
        if old.lower() not in lower:
            delete_row(con, "item_labels", f"{item_id}|{old}", fetch(con, "item_labels", f"{item_id}|{old}"), step)
    for name in want:
        if name.lower() not in {h.lower() for h in have}:
            row = {"item_id": item_id, "label": name, "added_by": step.by_user, "added_at": now(), "reason": reason or None,
                   "suggested": 1 if suggested else 0}
            _insert_sql(con, "item_labels", {k: v for k, v in row.items() if v is not None})
            stored = fetch(con, "item_labels", f"{item_id}|{name}")
            for f in stored.keys():
                if stored[f] is not None:
                    log(con, step, "item_labels", f"{item_id}|{name}", f, None, stored[f], OP_MADE)
    return bool(set(h.lower() for h in have) ^ lower)


def delete_row(con, table, key, current, step):
    """Remove a links, item_labels, labels (or, #65, report_sections, glance_tiles, report_hidden) row. The row is kept in
    change_log (field REMOVED) so undo can put it back."""
    if table not in DELETED_ON_CANCEL:
        raise Invalid(f"{table} rows are never deleted; close or cancel them instead")
    current = dict(current)
    if table == "report_sections" and current["type"] != "text":
        raise Invalid("Only a text section can be deleted; hide the others.")
    if table == "labels":
        if current["builtin"]:
            raise Invalid(f"{current['name']} is a built-in label and can't be deleted")
        n = con.execute("SELECT count(*) FROM item_labels WHERE label = ?", (current["name"],)).fetchone()[0]
        if n:
            raise Invalid(f"{n} item(s) still carry {current['name']}; remove it from them first")
    con.execute(f"DELETE FROM {_table(table)} WHERE {where_key(table)}", key_values(table, key))
    log(con, step, table, key, REMOVED, json.dumps(current, ensure_ascii=False), None, "update")
    return key


# ---------- updates and cancels ----------
def _prepare_workstream(changes, current):
    if "project" in changes and changes["project"] != current["project"]:
        raise Invalid("a workstream stays in its project; close it and add one to the other project instead")
    if "name" in changes:
        changes["name"] = str(changes["name"]).strip()


UPDATE_PREPARE = {"workstreams": _prepare_workstream}


def _derive_raid(row, current, changes):
    row["priority"] = priority(row.get("impact"), row.get("likelihood"))


DERIVE = {"raid": _derive_raid}                            # fields worked out from the merged row (before `closed`)


def _check_decision(row, current, changes):
    if current.get("status") == "Made" and row.get("status") == "Pending":
        raise Invalid("a decision that has been Made can't go back to Pending; record a new decision that replaces it")


REASON_LIMIT = 2000                                                       # a project's health reason, in characters
REASON_NOT_TEXT = "A reason must be text."
REASON_TOO_LONG = f"A reason can be at most {REASON_LIMIT} characters."
REASON_BAD_CHARS = "A reason can't hold control or invisible characters (line breaks are fine)."
REASON_REFUSALS = (REASON_NOT_TEXT, REASON_TOO_LONG, REASON_BAD_CHARS)


def health_reason_text(value):
    """clark (#45, review): a project's health reason as it is stored, or Invalid in plain words. Several lines are
    fine (a Windows line break, \\r\\n, is made \\n first and the length is counted after that); at most REASON_LIMIT characters
    (code points); no other control character, no format, surrogate, private-use or separator character (a bidi override, a
    zero-width space), which would reach the published page unseen. The text is kept as given otherwise (never trimmed or
    changed), and never quoted back. None (no reason) passes as None. It lives here so that every writer of the reason is held
    to it: /api/change, a teammate's change, anything that later calls Step.update on a project."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise Invalid(REASON_NOT_TEXT)
    text = value.replace("\r\n", "\n").replace("\t", " ")             # a tab (pasted from a table) becomes a space, not a refusal
    if not text:
        return None                                                        # an empty reason is stored one way only: None
    if any(c != "\n" and unicodedata.category(c) in _BAD_TITLE_KINDS for c in text):
        raise Invalid(REASON_BAD_CHARS)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise Invalid(REASON_BAD_CHARS) from None
    if len(text) > REASON_LIMIT:
        raise Invalid(REASON_TOO_LONG)
    if not text.strip():
        return None                                                        # spaces or line breaks only is blank: stored as None
    return text


def _check_project(row, current, changes):
    if "health_reason" in changes:                    # the one place the reason's text is checked, whoever writes it
        changes["health_reason"] = row["health_reason"] = health_reason_text(changes["health_reason"])
    if "health" in changes and changes["health"] != current.get("health") \
            and not str(changes.get("health_reason") or "").strip():
        raise Invalid("a health change needs a reason (health_reason)")
    if "health_reason" in changes and not str(changes["health_reason"] or "").strip() \
            and changes.get("health", current.get("health")) != "On track":
        raise Invalid("a health change needs a reason (health_reason)")      # the reason can't be cleared while health isn't On track


def _check_milestone(row, current, changes):
    norm_milestone(row, current, set(changes))


CHECK = {"decisions": _check_decision, "projects": _check_project, "milestones": _check_milestone}   # after `closed`


def _check_changes(table, changes, extras, cols):
    if set(changes) - set(cols):
        raise Invalid(f"unknown field(s) for {table}: {', '.join(sorted(map(str, set(changes) - set(cols))))}. "
                      f"Valid: {', '.join(c for c in cols if c not in NO_EDIT)}")
    bad = (set(changes) & NO_EDIT) | (set(changes) & set(KEYS[table]))
    if table == "labels":
        bad |= set(changes) & {"builtin"}
    if table == "report_sections":
        bad |= set(changes) & {"type", "project"}              # clark (#65): a section keeps its type and its project
    if bad:
        raise Invalid(f"these fields can't be changed: {', '.join(sorted(bad))}")
    if not changes and "labels" not in extras:
        raise Invalid("update has no changes")


BEFORE_RAISED = "This item can't be closed or cancelled before the day it was raised. Check the raised date, then try again."
BEFORE_RAISED_KEY = "before the day it was raised"      # the part of that sentence the route matches on (changes.STORE_WORDS)


def _not_before_raised(table, row):
    """#135: the table's own rule (closed >= raised), said in plain words before the database fails it."""
    if table in CLOSING and row.get("closed") and row.get("raised") and str(row["closed"]) < str(row["raised"]):
        raise Invalid(BEFORE_RAISED)


def _closed_for_update(table, row, current, changes):
    if table in CLOSING and "status" in changes:
        if row["status"] in CLOSING[table]:
            row["closed"] = changes.get("closed") or current.get("closed") or today()
        else:
            row["closed"] = None


def _merged_row(con, table, current, changes, revert=False, archiving=False):
    """The row as it will be: the changes merged in, derived fields worked out, every rule checked. clark: an undo that puts a
    project's health back together with its reason is not a new health change, so it needs no new reason; one that puts
    health back alone (called straight) still does. revert_group sends the reason as it stands with such a health, so an Undo of a
    pick that kept the reason is not refused."""
    row = {**current, **changes}
    if archiving:                                      # #126: an archive checks only its own change (the flag), nothing else
        return row
    if table in DERIVE:
        DERIVE[table](row, current, changes)
    _closed_for_update(table, row, current, changes)
    _not_before_raised(table, row)
    if table in CHECK and not (revert and table == "projects" and "health_reason" in changes):
        CHECK[table](row, current, changes)
    check_row(con, table, row, set(changes))
    return row


def _carry_workstream_rename(con, current, diff, step):
    """A rename carries the project's items with it (clark: milestones too, as they name a workstream)."""
    if "name" not in diff:
        return
    for t in ("actions", "raid", "milestones"):
        for r in con.execute(f"SELECT id, workstream, updated_at FROM {_table(t)} WHERE project = ? AND "
                             "workstream = ? COLLATE NOCASE", (current["project"], current["name"])).fetchall():
            at = now()
            con.execute(f"UPDATE {_table(t)} SET workstream = ?, updated_at = ? WHERE id = ?", (diff["name"], at, r[0]))
            log(con, step, t, r[0], "workstream", r[1], diff["name"], "update")
            log(con, step, t, r[0], "updated_at", r[2], at, "update")


AFTER_WRITE = {"workstreams": _carry_workstream_rename}


def _write_rebaseline(con, table, key, item, rebase, step):
    """The decision that goes with a rebaseline, in the same step (so one undo takes both)."""
    did = write_item(con, {"op": "new", "table": "decisions", "values": rebase}, step)
    why = str(item.get("note") or rebase["reasoning"]).strip().rstrip(".")
    log(con, step, table, key, "note", None, f"{why}. Agreed with {rebase['made_by']}. Decision {did}", "update")


def _update_row(con, table, item, key, current, changes, cols, step):
    """An update (or a cancel, as the update it makes): checked, the changed fields written and logged."""
    extras = _take_extras(table, changes)
    _check_changes(table, changes, extras, cols)
    want = canonical_labels(con, extras.get("labels")) if "labels" in extras else None
    blank_to_none(table, changes)
    check_values(table, changes)
    if table in UPDATE_PREPARE:
        UPDATE_PREPARE[table](changes, current)
    row = _merged_row(con, table, current, changes, revert=bool(item.get("revert")), archiving=item.get("op") == "archive")
    rebase = rebaseline_of(item, current, row) if table == "milestones" else None     # checked before anything is written
    diff = {f: row[f] for f in cols if f != "updated_at" and row.get(f) != current.get(f)}
    if want is not None:      # the item's labels; a label change alone leaves the item's own row (and updated_at) alone
        set_labels(con, key, want, extras.get("label_reason"), extras.get("label_suggested"), step)
    if not diff:
        return key
    if "updated_at" in cols:
        diff["updated_at"] = now()
    con.execute(f"UPDATE {_table(table)} SET {', '.join(f'{f} = ?' for f in diff)} WHERE {where_key(table)}",
                list(diff.values()) + key_values(table, key))
    for f, v in diff.items():
        log(con, step, table, key, f, current.get(f), v, "update", undoes=(item.get("undoes") or {}).get(f))
    if table in AFTER_WRITE:
        AFTER_WRITE[table](con, current, diff, step)
    if item.get("note") and not rebase:   # a reason that goes with the change; history only, not a column
        log(con, step, table, key, "note", None, item["note"], "update")
    if rebase:
        _write_rebaseline(con, table, key, item, rebase, step)
    return key


# ── Undo: creaite's undo-changes (revert_plan, revert_group) ──────────────────

def reverted_rowids(con):
    """change_log rowids put back by a revert step that is still in force."""
    out = set()
    for (via,) in con.execute("SELECT DISTINCT c.via FROM change_log c JOIN applies a ON a.apply_id = c.apply_id "
                              "WHERE c.via LIKE 'revert:%' AND a.undone_at IS NULL"):
        out |= {int(x) for x in via[len(REVERT_VIA):].split(",") if x.strip().isdigit()}
    return out


def holds(con, table, key, changes):
    """True while every field still holds the value these rows wrote."""
    row = fetch(con, table, key)
    if changes[-1]["field"] == REMOVED:                # a deleted row: it holds while it is still gone
        return row is None
    if row is None:
        return False
    return not any(c["field"] in row.keys() and c["field"] != "updated_at" and text(row[c["field"]]) != c["new_value"]
                   for c in changes)      # #197: the stamp follows every change and every undo; the fields say whether it holds


def changed_after(con, rowid, table, key, skip=()):
    """The newest later step still in force that touched the item (or a row keyed by it, such as its labels), or None.
    clark: steps in `skip` (the step being undone, and the undo itself) don't count, so a label put on a new item in the
    same step doesn't make its own creation look changed since. clark (#65): an undo's own rows, and the rows an undo still in
    force has put back, don't count either: a change that was undone is no longer a change, and an undo is never "the later
    change" (so Add, change it, undo that change, undo the Add works; a change that stays still blocks it)."""
    gone = reverted_rowids(con)
    for (apply_id, row, via) in con.execute(
            "SELECT c.apply_id, c.rowid, c.via FROM change_log c LEFT JOIN applies a ON a.apply_id = c.apply_id WHERE c.rowid > ? "
            "AND a.undone_at IS NULL AND c.field != 'updated_at' AND ((c.tbl = ? AND c.item_id = ?) OR c.item_id LIKE ?) "
            "ORDER BY c.rowid DESC",                    # #197: a stamp is never the later change: a field row always comes with it
            (rowid, table, key, key + "|%")):
        if apply_id not in skip and row not in gone and not str(via).startswith(REVERT_VIA):
            return apply_id
    return None


def referred_to(con, key):
    """(table, the referring row's key) where an item is named by another row (a milestone on an action, a link, a label, a
    decision it replaces, a use case), or None."""
    for table, col in REVERT_REFS:
        if col in columns(con, table):
            r = con.execute(f"SELECT * FROM {_table(table)} WHERE {col} = ? LIMIT 1", (key,)).fetchone()
            if r:
                return table, key_of(table, r)
    return None


def why_not(con, r, reverted, done_ids, undoing_a_revert):
    """Why a change_log row can't be put back at all, or None."""
    if r["tbl"] not in TABLES:
        return "can't be undone"
    if not undoing_a_revert and r["rowid"] in reverted:
        return "already undone"
    if r["rowid"] in done_ids:
        return "already undone"
    if r["field"] in ("note", "updated_at") or (r["field"] != REMOVED and r["field"] not in columns(con, r["tbl"])):
        return "history only; nothing to put back"
    if r["op"] == OP_MADE and r["tbl"] == "glance_tiles" and r["via"] == SEED_VIA:      # clark (#45): the starting tiles: kept, not a skip
        return "history only; nothing to put back"
    if r["op"] == OP_MADE and r["tbl"] not in REVERT_CREATED:
        return "a new " + r["tbl"].rstrip("s") + " can't be removed by an undo"
    if r["op"] == OP_MADE and r["tbl"] == "report_sections" and con.execute(     # clark (#65): the sections a new project was made with
            "SELECT 1 FROM change_log WHERE apply_id = ? AND tbl = 'projects' AND op = 'insert' AND item_id = ? LIMIT 1",
            (r["apply_id"], str(r["item_id"]).split("-S-")[0])).fetchone():    # go with it: it stays, so they do (never half)
        return "a new project's sections can't be removed by an undo"
    if r["op"] == OP_MADE and r["via"] == SEED_VIA:           # an old project's starting sections: left alone, and not worth a line
        return "history only; nothing to put back"
    return None


def revert_plan(con, rows, step, undoing_a_revert):
    """Put back `rows` (one step's change_log rows) inside the caller's transaction. Returns (done, skipped)."""
    reverted = reverted_rowids(con)
    done, skipped, done_ids, groups = [], [], set(), {}
    for r in sorted(rows, key=lambda x: x["rowid"], reverse=True):     # newest first, so two changes to one field go back in turn
        why = why_not(con, r, reverted, done_ids, undoing_a_revert)
        if why:
            if why != "history only; nothing to put back":
                skipped.append({"rowid": r["rowid"], "ref": r["item_id"], "field": r["field"], "why": why, "by_step": None})
            continue
        groups.setdefault((r["apply_id"], r["tbl"], r["item_id"]), []).append(r)
    for (apply_id, table, key), rows_ in sorted(groups.items(), key=lambda kv: -max(x["rowid"] for x in kv[1])):
        con.execute("SAVEPOINT revert_item")
        try:
            got = revert_group(con, apply_id, table, key, sorted(rows_, key=lambda x: x["rowid"]), step)
        except (Invalid, sqlite3.IntegrityError) as e:          # clark: + a database rule, said plainly
            con.execute("ROLLBACK TO revert_item")
            if step.peek_apply_id() is not None and not con.execute(
                    "SELECT 1 FROM applies WHERE apply_id = ?", (step.peek_apply_id(),)).fetchone():
                step.forget_apply_id()                  # the rollback took this step's row: the next group makes a new one
            why = str(e) if isinstance(e, Invalid) else "other data depends on it: left as it is"
            got = [], [{"rowid": x["rowid"], "ref": key, "field": x["field"], "why": why, "by_step": None} for x in rows_]
        con.execute("RELEASE revert_item")
        done += got[0]
        skipped += got[1]
        done_ids |= {d["rowid"] for d in got[0]}
    return done, skipped


def revert_group(con, apply_id, table, key, rows_, step):
    """One item's rows from one step (`apply_id`), put back under `step`. Returns (done, skipped)."""
    def entry(r, **k):
        return {"rowid": r["rowid"], "ref": key, "field": r["field"], **k}

    created = [r for r in rows_ if r["op"] == OP_MADE]
    if created:                                        # the step created the row: remove it, only if untouched since
        made = con.execute("SELECT rowid, * FROM change_log WHERE apply_id = ? AND tbl = ? AND item_id = ? AND op = 'insert' "
                           "ORDER BY rowid", (apply_id, table, key)).fetchall()
        whole = con.execute("SELECT rowid, * FROM change_log WHERE apply_id = ? AND tbl = ? AND item_id = ? ORDER BY rowid",
                            (apply_id, table, key)).fetchall()
        final = list({c["field"]: c for c in whole}.values())      # the step's last word on each field: a row made and then
        #                                                            changed (or deleted) in the same step still goes back whole
        later = changed_after(con, whole[-1]["rowid"], table, key, skip=(apply_id, step.peek_apply_id()))
        if not holds(con, table, key, final) or later:
            return [], [entry(rows_[0], field=None, why="has changed since: left as it is", by_step=later)]
        if final[-1]["field"] == REMOVED:                          # made and deleted in this one step: nothing is there to remove
            return [entry(r, change="removed") for r in rows_], []
        ref = referred_to(con, key)
        if ref:
            return [], [entry(rows_[0], field=None, by_step=None,
                              why=f"something refers to it now ({_REF_WORDS.get(ref[0], ref[0])} {ref[1]}): left as it is")]
        current = fetch(con, table, key)
        con.execute(f"DELETE FROM {_table(table)} WHERE {where_key(table)}", key_values(table, key))
        log(con, step, table, key, REMOVED, json.dumps(dict(current), ensure_ascii=False), None, "update",
            undoes=made[0]["rowid"])
        return [entry(r, change="removed") for r in rows_], []
    removed = [r for r in rows_ if r["field"] == REMOVED]
    if removed:                                        # the step deleted a link or a label: put it back while it is still gone
        r = removed[0]
        if fetch(con, table, key) is not None:
            return [], [entry(x, why="is back already: left as it is", by_step=None) for x in rows_]
        old = json.loads(r["old_value"])
        back = {k: v for k, v in old.items() if k in columns(con, table) and v is not None}
        before = {}                                    # #197: a field the step changed before the delete goes back to its first old value
        for x in rows_:
            if x["rowid"] < r["rowid"] and x["field"] in columns(con, table) and x["field"] not in before:
                before[x["field"]] = x["old_value"]
        back.update(_typed(con, table, before))       # a first old value of NULL is put back as NULL, never the column's default
        check_row(con, table, dict(back), set(back))
        _insert_sql(con, table, back)
        for f, v in back.items():
            log(con, step, table, key, f, None, v, OP_MADE, undoes=r["rowid"])
        return [entry(x, change="put back") for x in rows_], []
    done, skipped, changes, undoes = [], [], {}, {}
    row = fetch(con, table, key)
    if row is None:
        return [], [entry(rows_[0], field=None, why="no longer exists", by_step=None)]
    if "archived" in row.keys() and row["archived"] and not any(r["field"] == "archived" for r in rows_):
        raise Invalid(f"{key} is archived. Restore it first.")        # #126: an older step's edit is not put back onto an archived row
    by_field = {}                                     # a field changed twice in one step: judged by its last value, put back
    for r in rows_:                                   # to its first old value (creaite's whole-step cmd_undo)
        by_field.setdefault(r["field"], []).append(r)
    for f, rs in by_field.items():
        if text(row[f]) != rs[-1]["new_value"]:
            skipped.append(entry(rs[-1], why="has changed since: left as it is",
                                 by_step=changed_after(con, rs[-1]["rowid"], table, key, skip=(step.peek_apply_id(),))))
        else:
            changes[f] = rs[0]["old_value"]
            undoes[f] = rs[-1]["rowid"]
    if table == "projects" and "health" in changes and "health_reason" not in changes:    # a health change takes its reason back too
        hr = con.execute("SELECT rowid, * FROM change_log WHERE apply_id = ? AND tbl = 'projects' AND item_id = ? "
                         "AND field = 'health_reason' AND op = 'update' ORDER BY rowid", (apply_id, key)).fetchall()
        if hr and text(row["health_reason"]) == hr[-1]["new_value"]:
            changes["health_reason"] = hr[0]["old_value"]
            undoes["health_reason"] = hr[-1]["rowid"]
            by_field["health_reason"] = [dict(x) for x in hr]
    if table == "projects" and "health" in changes and "health_reason" not in changes:
        changes["health_reason"] = row["health_reason"]       # the pick kept the reason as it stood: put it back as it stands (no change)
    if not changes:
        return done, skipped
    write_item(con, {"table": table, "op": "update", "id": key, "changes": _typed(con, table, changes), "revert": True,
                     "undoes": undoes}, step)
    after = fetch(con, table, key)
    for f, rs in by_field.items():
        if f not in changes:
            continue
        if text(after[f]) == rs[0]["old_value"]:
            done.extend(entry(r, change="set", **{"from": r["new_value"], "to": rs[0]["old_value"]}) for r in rs)
        else:                                          # derived (a RAID priority, a closed date): it follows other fields
            skipped.append(entry(rs[-1], why="it follows other fields: left as it is", by_step=None))
    return done, skipped


_REF_WORDS = {"actions": "an action", "raid": "a RAID item", "decisions": "a decision", "links": "a link",
              "item_labels": "a label on an item"}   # named with the referring row's key


def _typed(con, table, changes):
    """change_log holds text; give an INTEGER column its number back, so the validated update path checks the real value."""
    kinds = {r["name"]: (r["type"] or "").upper() for r in con.execute(f"PRAGMA table_info({_table(table)})")}
    out = {}
    for f, v in changes.items():
        out[f] = int(v) if v is not None and kinds.get(f) == "INTEGER" and re.fullmatch(r"-?\d+", v) else v
    return out


# ── The store ─────────────────────────────────────────────────────────────────

def connect(path, readonly=False, existing=False):
    """A connection to clark.db: rows by column name, foreign keys on, autocommit (a Step uses BEGIN IMMEDIATE).
    clark: WAL and a busy timeout, because the server and an import may write at once. `existing` opens a file that is there
    without the power to make it: a file that has moved away is refused instead of being made again."""
    if readonly:
        con = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, isolation_level=None,
                              check_same_thread=False)
    elif existing:
        con = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=rw", uri=True, isolation_level=None)
    else:
        con = sqlite3.connect(str(path), isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    if not readonly:
        con.execute("PRAGMA journal_mode = WAL")
    return con


MIGRATE_DISK = ("The database could not be updated. Nothing was changed. Your data is as it was. "
                "Check that the folder has space and you can save files there, then restart clark and try again.")
MIGRATE_BUSY = ("The database could not be updated because it is in use by another program. Nothing was changed. "
                "Your data is as it was. Close the other program, or wait a moment, and try again.")
MIGRATE_FAILED = ("The database could not be updated. Nothing was changed. Your data is as it was. Try again; if it keeps "
                  "happening, ask the clark team for help and tell them the name of the data file.")
MIGRATE_INCONSISTENT = ("The database could not be updated because some of its records no longer match each other. Nothing was "
                        "changed. Your data is as it was. Ask the clark team for help, and tell them the name of the data file.")


# How every plain refusal of an update begins (MIGRATE_FAILED, the safety-copy refusals from backup.refusal, the plan's refusals):
# the server shows these sentences as they are instead of "clark can't read its data".
MIGRATE_REFUSAL_STARTS = ("The database could not be updated", "This copy of clark cannot bring the database",
                          "The database has a version clark does not know")


def open_store(path, onedrive_roots=None):
    """The store at `path` (clark.db), made from schema.sql if it is new. Refuses a folder inside OneDrive and a database made by
    a newer clark."""
    path = Path(path)
    platform.check_data_dir(path.parent, onedrive_roots)
    from clark import backup
    backup.finish_restore(path)          # a restore that stopped half-way is finished (or refused) before a new database could be made
    existing = path.exists() or path.with_name(path.name + backup.MARKER).exists()     # looked at before the flag: a restore moving the file after this still finds it "there"
    if backup.restoring(path):           # one place for every "a restore is running" test made before connecting
        raise Invalid(backup.RESTORE_BUSY)
    try:
        con = connect(path, existing=existing)     # a file that is there is opened without the power to make it
    except sqlite3.OperationalError as e:     # a folder or file that can't be written to, or a lock: said in clark's words
        if backup.restoring(path):          # the file moved away between the check and the connect: a restore has begun
            raise Invalid(backup.RESTORE_BUSY) from e
        raise Invalid(_busy(e)) from e
    except sqlite3.DatabaseError as e:        # a file that isn't a database fails on the first pragma
        raise Invalid(f"{path.name} is not a database clark can read. Choose another file, or restore a backup.") from e
    try:
        if backup.restoring(path):          # a restore began after the check above: build nothing in a file it is about to move
            raise Invalid(backup.RESTORE_BUSY)
        have = con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'").fetchone()
        if not have:
            if con.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]:
                raise Invalid(f"{path.name} is a database, but not one clark made. Choose another file.")
            con.execute("BEGIN IMMEDIATE")
            try:
                for statement in _statements(SCHEMA.read_text(encoding="utf-8")):
                    con.execute(statement)
                for k, v in (("schema_version", str(SCHEMA_VERSION)), ("created_at", now()), ("device", uuid.uuid4().hex),
                             ("db_id", uuid.uuid4().hex), ("role", "owner")):
                    con.execute("INSERT INTO meta (k, v) VALUES (?, ?)", (k, v))
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
        row = con.execute("SELECT v FROM meta WHERE k = 'schema_version'").fetchone()
        if row is None or not str(row[0]).isdigit():
            raise Invalid(f"{path.name} is a clark database with no usable version. It may be damaged.")
        version = int(row[0])
        if version > SCHEMA_VERSION:
            raise Invalid(f"This database was made by a newer clark (version {version}); update clark to open it.")
        if version < SCHEMA_VERSION:
            # #126: the plan is checked first, so a refused plan makes no copy. Then the safety copy of an existing older file,
            # through backup.make's own `migrate` family. If it cannot be made the migration is refused in plain words
            # (backup.refusal) and nothing is changed. A new database never gets here.
            migration_plan(version)
            backup.make(path, path.parent / "backups", onedrive_roots, "migrate")
            try:
                migrate(con)
            except Invalid:
                raise
            except sqlite3.OperationalError as e:
                raise Invalid(_migrate_words(e)) from e               # busy, a disk or file that can't be written, or neither
            except sqlite3.IntegrityError as e:                       # a foreign key or a CHECK: the records, not the space
                raise Invalid(MIGRATE_INCONSISTENT) from e
            except Exception as e:                # any other fault in a step: rolled back by migrate, said in plain words
                raise Invalid(MIGRATE_FAILED) from e
        return Store(con, path, onedrive_roots)
    except sqlite3.OperationalError as e:
        con.close()
        raise Invalid(_busy(e)) from e
    except sqlite3.DatabaseError as e:
        con.close()
        raise Invalid(f"{path.name} is not a database clark can read. Choose another file, or restore a backup.") from e
    except Invalid:
        con.close()
        raise


def _table_statements():
    """The CREATE TABLE IF NOT EXISTS statements of schema_v2.sql (frozen: a later version never changes what version 2 makes), for
    migrate_to_2."""
    out = []
    for statement in _statements(SCHEMA_V2.read_text(encoding="utf-8")):
        code = "\n".join(line for line in statement.splitlines() if not line.strip().startswith("--")).strip()
        if code.upper().startswith("CREATE TABLE IF NOT EXISTS"):
            out.append(statement)
    return out


def _add_documents_archived(con):
    """The documents table's archived column, if it is not there yet (a half-applied copy is safe)."""
    if "archived" not in columns(con, "documents"):
        con.execute("ALTER TABLE documents ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0,1))")


def _item_events_allow_board(con):
    """item_events.place gains 'board' (#126). SQLite cannot change a CHECK in place, so the table is made again from schema_v2.sql's
    own statement, the rows are copied with their ids, the sequence is kept and the indexes are made again. Only when the table's
    own definition does not name 'board' yet, so a second run (or a new database) does nothing. Inside the caller's transaction."""
    have = con.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'item_events'").fetchone()
    if have is None or "'board'" in have[0]:
        return
    statement = next(st for st in _table_statements() if "CREATE TABLE IF NOT EXISTS item_events (" in st)
    seq = con.execute("SELECT seq FROM sqlite_sequence WHERE name = 'item_events'").fetchone()
    con.execute(statement.replace("CREATE TABLE IF NOT EXISTS item_events (", "CREATE TABLE item_events_v2 (", 1))
    con.execute("INSERT INTO item_events_v2 (event_id, at, apply_id, item_id, change, kind, route, place, origin, actor, src_ref, undoes) "
                "SELECT event_id, at, apply_id, item_id, change, kind, route, place, origin, actor, src_ref, undoes FROM item_events")
    con.execute("DROP TABLE item_events")
    con.execute("ALTER TABLE item_events_v2 RENAME TO item_events")
    if seq is not None:
        con.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = 'item_events'", (seq[0],))
    con.execute("CREATE INDEX IF NOT EXISTS item_events_item ON item_events(item_id)")
    con.execute("CREATE INDEX IF NOT EXISTS item_events_change ON item_events(change)")


def migrate_to_2(con):
    """Schema version 1 to 2 (#126): the idempotent CREATE TABLE IF NOT EXISTS statements (a version-1 file made before the report
    tables had no version bump may lack them), then documents.archived, then item_events accepting 'board'. Runs inside the
    caller's transaction and does not touch the version (the runner does)."""
    for statement in _table_statements():
        con.execute(statement)
    _add_documents_archived(con)
    _item_events_allow_board(con)


MIGRATIONS = ((2, migrate_to_2),)     # version -> the step that brings a file TO that version; the next one (#115: 3) is added here


def migration_plan(version, table=None):
    """The steps that take a file at `version` to SCHEMA_VERSION, in order. The table must run 2, 3, ... with no gap and end at
    SCHEMA_VERSION (an empty table is right only while SCHEMA_VERSION is 1), and the file's version must be one clark knows (1 or later); anything else is refused in plain words."""
    table = MIGRATIONS if table is None else table
    numbers = [n for n, _ in table]
    if numbers != list(range(2, 2 + len(numbers))) or (numbers[-1] if numbers else 1) != SCHEMA_VERSION:
        raise Invalid("This copy of clark cannot bring the database up to date because it is missing a step. Install the latest clark, then try again.")
    if version > SCHEMA_VERSION:
        raise Invalid(f"The database has a version clark does not know ({version}). Install the latest clark, then try again.")
    if version < 1:
        raise Invalid(f"The database has a version clark does not know ({version}). Restore a backup, or ask the clark team for help.")
    return [(n, fn) for n, fn in table if n > version]


def _violations(con):
    """Foreign-key problems already in the file, counted by table, parent and key (not by row, which a rebuilt table renumbers)."""
    return collections.Counter((r[0], r[2], r[3]) for r in con.execute("PRAGMA foreign_key_check"))


def migrate(con, table=None):
    """Bring a file to SCHEMA_VERSION: every step still to run, in order, in ONE BEGIN IMMEDIATE, the version written after each
    step. The version is read again after the lock is taken, so a second window that found an old version finds the new one and
    does nothing. Any error rolls back and leaves the file as it was. A migration is not a step: no applies row, no Undo.

    Foreign keys are switched OFF before the transaction begins (the pragma does nothing inside one) and back ON afterwards, also
    after a failure: item_events is made again, and with the keys on the drop of the old table refuses when an Undo row points at
    it. A row that was ALREADY dangling before the update is not the update's doing and never blocks it; only a NEW violation
    (more than before, by table, parent and key) refuses and rolls back."""
    con.execute("PRAGMA foreign_keys = OFF")
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            row = con.execute("SELECT v FROM meta WHERE k = 'schema_version'").fetchone()
            if row is not None and str(row[0]).isdigit():
                steps = migration_plan(int(row[0]), table)
                if steps:
                    before = _violations(con)
                    for n, step in steps:
                        step(con)
                        con.execute("UPDATE meta SET v = ? WHERE k = 'schema_version'", (str(n),))
                    if _violations(con) - before:
                        raise Invalid(MIGRATE_INCONSISTENT)
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    finally:
        con.execute("PRAGMA foreign_keys = ON")


# ── Backups (#86): the SQL is here, so backup.py holds none. A copy of creaite v2.6.9 `backup_db` (tracker.py:2826) ──

HISTORY_COUNTS = {"applies": "SELECT count(*) FROM applies", "change_log": "SELECT count(*) FROM change_log",
                  "item_events": "SELECT count(*) FROM item_events"}


def _summary(con):
    """What a copy holds, to compare with the live database: the last step and a row count for every table the file has. A
    table it lacks (an older file made before a later table existed) counts as absent, not as an error, on both sides of a
    comparison."""
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    rows = {t: con.execute(f"SELECT count(*) FROM {_table(t)}").fetchone()[0] for t in TABLES if t in have}
    rows.update({t: con.execute(sql).fetchone()[0] for t, sql in HISTORY_COUNTS.items()})
    return {"last_step": con.execute("SELECT max(apply_id) FROM applies").fetchone()[0] or 0, "rows": rows}


CHECK_FAILED = "One was made, but clark could not confirm it is complete, so it was not kept."   # backup.refusal puts it after its own first sentence


def snapshot(path, dest):
    """Copy the committed data of the database at `path` into `dest`, an empty file the caller made private. A separate
    read-only connection, never the store's own (that one may be mid-step and belongs to one thread); `backup()` with the
    default pages=-1 copies in one read transaction, so the copy is one moment even while another program commits (a positive
    page count would restart it on every write). The row counts of the copy are compared with the source's, read in that same
    transaction. The copy is made a single finished file (journal mode DELETE, no -wal or -shm
    left beside it, which Python 3.9's SQLite does leave) and checked. Returns _summary. A failure removes `dest`, raises Invalid."""
    dest, src, dst, done = Path(dest), None, None, False
    try:
        src = connect(path, readonly=True)
        dst = sqlite3.connect(str(dest), isolation_level=None)
        src.execute("BEGIN")
        try:
            wanted = _summary(src)               # inside the read transaction the backup() below also reads: the same moment
            src.backup(dst)
        finally:
            src.execute("ROLLBACK")
        dst.execute("PRAGMA journal_mode = DELETE")
        if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise Invalid(CHECK_FAILED)
        summary = _summary(dst)
        if summary != wanted:
            raise Invalid(CHECK_FAILED)
        done = True
        return summary
    except sqlite3.Error as e:
        raise Invalid("The backup could not be saved.") from e          # the system's own words stay in the cause, never the message
    finally:
        for con in (dst, src):
            if con is not None:
                con.close()
        for side in ("-wal", "-shm", "-journal"):
            Path(str(dest) + side).unlink(missing_ok=True)
        if not done:
            dest.unlink(missing_ok=True)


def check_copy(path):
    """Open `path` read-only and check it is a whole clark database that clark can put back: integrity_check ok, a schema_version
    that is a number from 1 up to this clark's (a newer one needs a newer clark; an older one can be put back, and #126's
    migration brings it up to date when it is opened), a db_id, and no foreign-key violation. Returns _summary plus
    schema_version and db_id; Invalid otherwise."""
    name = Path(path).name
    try:
        con = connect(path, readonly=True)
    except sqlite3.Error as e:
        raise Invalid(f"{name} is damaged, so it can't be used. Choose another backup.") from e
    try:
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Invalid(f"{name} is damaged, so it can't be used. Choose another backup.")
        meta = {r[0]: r[1] for r in con.execute("SELECT k, v FROM meta")}
        version = str(meta.get("schema_version", ""))
        if not version.isdigit():
            raise Invalid(f"{name} is a clark database with no usable version, so it can't be used.")
        if int(version) > SCHEMA_VERSION:
            raise Invalid(f"{name} was made by a newer clark (version {version}); update clark to use it.")
        if int(version) < 1:
            raise Invalid(f"{name} is a clark database with no usable version, so it can't be used.")
        if not meta.get("db_id"):
            raise Invalid(f"{name} has no identity, so it isn't a clark backup.")
        if con.execute("PRAGMA foreign_key_check").fetchall():
            raise Invalid(f"{name} is damaged, so it can't be used. Choose another backup.")
        return {**_summary(con), "schema_version": int(version), "db_id": meta["db_id"]}
    except sqlite3.Error as e:
        raise Invalid(f"{name} is damaged, so it can't be used. Choose another backup.") from e
    finally:
        con.close()


def identity(path):
    """The db_id of the database at `path`, or None if it can't be read (a restore is for a damaged one too)."""
    try:
        con = connect(path, readonly=True)
    except sqlite3.Error:
        return None
    try:
        row = con.execute("SELECT v FROM meta WHERE k = 'db_id'").fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def _held(path):
    """The refusal when the database can't be taken over for a restore. The system's reason stays in the cause, never the words."""
    return (f"{path.name} can't be opened right now. Close any other window or program using clark, then try again. "
            "Nothing was changed.")


def in_use(path):
    """Is another program using the database at `path`? Opens it with no wait and takes the lock for itself, then reads. Returns
    that open probe connection, which the caller keeps open until its move is done, so no program can open the file between;
    None when there is no file. "Locked" means in use; any other error (permission, read-only) also refuses, in its own words, as Invalid.
    A file that is not a database at all passes: nobody can have it open, and a damaged database is what a restore is for."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        probe = sqlite3.connect(str(path), timeout=0, isolation_level=None)
    except sqlite3.Error as e:
        raise Invalid(_held(path)) from e
    try:
        probe.execute("PRAGMA locking_mode = EXCLUSIVE")
        probe.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return probe
    except sqlite3.OperationalError as e:
        probe.close()
        if "locked" in str(e) or "busy" in str(e):
            raise Invalid("Another window or program has clark's data open, so it can't be replaced. Close it there and "
                          "try again. Nothing was changed.") from e
        raise Invalid(_held(path)) from e
    except sqlite3.DatabaseError:
        return probe          # not a database (damaged): the lock was ours to take, so no program has it open; a restore is for this


_DISK_NAMES = ("SQLITE_FULL", "SQLITE_IOERR", "SQLITE_CANTOPEN", "SQLITE_READONLY")
_DISK_WORDS = ("disk is full", "disk i/o error", "unable to open database file", "readonly database", "read-only")


def _migrate_words(e):
    """The plain words for an OperationalError during an update: busy, disk or file access, or the neutral failure."""
    text = str(e).lower()
    if "locked" in text or "busy" in text:
        return MIGRATE_BUSY
    name = str(getattr(e, "sqlite_errorname", "") or "")        # Python 3.11 and later; absent on 3.9
    if name.startswith(_DISK_NAMES) or any(w in text for w in _DISK_WORDS):
        return MIGRATE_DISK
    return MIGRATE_FAILED


def _busy(e):
    """A plain message for a database that is locked by another program for more than the busy timeout."""
    if "locked" in str(e) or "busy" in str(e):
        return "clark's data is in use by another program or step. Wait a moment and try again."
    return "clark's data could not be opened for writing."          # never SQLite's own words: the person doesn't read them


def _statements(sql):
    """schema.sql split into whole statements (executescript would commit, so the schema goes in one transaction)."""
    out, buf = [], ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                out.append(buf)
            buf = ""
    return out


def cut_whole_steps(events, cap):
    """#136: the newest `cap` events or a little fewer, cut by whole step: the steps are taken newest first (by their newest event)
    and a step is never split. The newest step is always kept, whatever its size. Newest first, as given."""
    if len(events) <= cap:
        return list(events)
    steps = {}
    for e in events:
        steps.setdefault(e["step"], []).append(e)
    keep, used = set(), 0
    for step, g in sorted(steps.items(), key=lambda kv: max(e["event_id"] for e in kv[1]), reverse=True):
        if keep and used + len(g) > cap:
            break
        keep.add(step)
        used += len(g)
    return [e for e in events if e["step"] in keep]


class Store:
    """clark.db, written only through steps."""

    def __init__(self, con, path, onedrive_roots=None):
        self.con = con
        self.onedrive_roots = onedrive_roots                   # None: the OneDrive folders on this computer (a test passes its own)
        self.path = Path(path)
        self.backups_dir = self.path.parent / "backups"        # beside the database, never inside OneDrive (backup.py checks)
        self._backup_hold = None                               # set by backup.py alone, and only inside `with store.backup_once(...)`
        self.backup_warning = None                             # plain words when the last daily copy failed (backup.before); else None
        self.device = con.execute("SELECT v FROM meta WHERE k = 'device'").fetchone()[0]

    def close(self):
        self.con.close()

    def backup_once(self, tag):
        """`with store.backup_once("changes"):` one backup for every step inside it (an import of several files), taken now.
        Nothing outlives the `with`."""
        from clark import backup
        return backup.once(self, tag)

    @contextmanager
    def step(self, via, by_user, place=None, origin=None, actor="you", src_ref=None, dry=False):
        """One step: BEGIN IMMEDIATE ... COMMIT, and one `applies` row once something is written. An error anywhere rolls the
        whole step back. A step that changes nothing writes nothing.

        clark (#86): before the step opens, a safety copy is taken when the route is an undo or an import, or no copy has been
        made today (backup.before). If an undo's or an import's copy can't be made this raises Invalid and nothing has been written;
        if only the daily copy can't be made the step goes ahead with a warning in `backup_warning`. `dry=True` (an Excel
        preview) takes none and is ALWAYS rolled back at the end, whatever the body wrote: it can never save a change, and so it is
        no way round the copy."""
        st = Step(self, via, by_user, place, origin, actor, src_ref)
        from clark import backup
        pending = None if dry else backup.before(self, st.route)
        try:
            self.con.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as e:
            backup.finish(pending, False)
            raise Invalid(_busy(e)) from e
        try:
            yield st
            self.con.execute("ROLLBACK" if dry else "COMMIT")
        except BaseException:
            self.con.execute("ROLLBACK")
            backup.finish(pending, False)        # a failed undo or import leaves no copy behind and costs no older one its place
            raise
        backup.finish(pending, st.peek_apply_id() is not None)

    def read(self, kind, project=None, ref=None, archived=None):
        """Rows of `kind` (one project's, or one row by ref) as dicts. `archived` None keeps today's behaviour (every row, so the
        exporter and the glance callers are untouched); False is live rows only; True is archived rows only (#126). A row asked
        for by ref is returned whatever its flag. The SQL comes from the table list and a fixed fragment, never from the caller."""
        _table(kind)
        if archived not in (None, False, True):
            raise Invalid("archived is None, False or True")
        if ref is not None:
            r = fetch(self.con, kind, ref)
            return dict(r) if r else None
        where, args = [], []
        if project is not None:
            where.append("project = ?")
            args.append(project)
        if archived is not None:
            if "archived" not in columns(self.con, kind):
                raise Invalid(f"{kind} cannot be archived")
            where.append("archived = 1" if archived else "archived = 0")
        sql = f"SELECT * FROM {_table(kind)}" + (" WHERE " + " AND ".join(where) if where else "")
        return [dict(r) for r in self.con.execute(sql, args)]

    def data_for(self, code, archived="hide"):
        """One project's data for the page (#33), from its own read-only connection; None if there's no such project.
        `archived` is "hide" (live rows: today's), "only" (archived rows, for Show archived) or "show" (both) (#126). An archived
        project's children are all archived, so for it "hide" returns them too: the page opens it read-only with Restore."""
        if archived not in ("hide", "only", "show"):
            raise Invalid('archived is "hide", "only" or "show"')
        con = connect(self.path, readonly=True)
        try:
            p = con.execute("SELECT * FROM projects WHERE code = ?", (code,)).fetchone()
            if p is None:
                return None
            if p["archived"] and archived == "hide":
                archived = "show"
            flags = {"hide": (0, 0), "only": (1, 1), "show": (0, 1)}[archived]      # the flags to keep, as values: no SQL is built
            out = {"project": dict(p)}
            for t in PUBLISH_TABLES:
                out[t] = [dict(r) for r in con.execute(
                    f"SELECT * FROM {_table(t)} WHERE project = ? AND archived IN (?, ?) ORDER BY {PUBLISH_ORDER[t]}", (code, *flags))]
            ids = {r["id"] for t in ("milestones", "actions", "raid", "decisions") for r in out[t]}
            shut = {}                                       # #126: is an end an archived item? (links may cross projects)

            def archived_end(end):
                if end not in shut:
                    found = item_row(con, end)
                    shut[end] = bool(found and found["archived"])
                return shut[end]
            out["links"] = [dict(r) for r in con.execute("SELECT * FROM links ORDER BY from_item, to_item")
                            if (r["from_item"] in ids or r["to_item"] in ids)
                            and (archived != "hide" or not (archived_end(r["from_item"]) or archived_end(r["to_item"])))]
            labels = {}
            for r in con.execute("SELECT item_id, label FROM item_labels ORDER BY item_id, label COLLATE NOCASE"):
                if r["item_id"] in ids:
                    labels.setdefault(r["item_id"], []).append(r["label"])
            out["labels"] = labels
            out["report_sections"] = [dict(r) for r in con.execute(           # #65: its own query; no archived column
                "SELECT id, type, title, body, beside, hidden, sort_order FROM report_sections WHERE project = ? "
                "ORDER BY sort_order, id", (code,))]
            out["glance_tiles"] = [dict(r) for r in con.execute(              # #45: the tiles' place, hidden flag and outline; no archived column
                "SELECT project, tile, hidden, outline, sort_order FROM glance_tiles WHERE project = ? "
                "ORDER BY sort_order, tile", (code,))]
            return out
        finally:
            con.close()

    def publish_inputs(self, code, fields):
        """What clark.publish needs to make a report for project `code`: one project's rows with only the columns in `fields`
        ({table: columns}; every name is checked against the table's own columns, never taken as given), the links, labels,
        hidden rows, sections, label rules and the milestone dates' history, all read from ONE read-only connection in ONE
        transaction, so a write can't come between two reads. None when there is no such project (#39; a clark addition: creaite
        has no published page of its own data)."""
        con = connect(self.path, readonly=True)
        try:
            con.execute("BEGIN")
            try:
                def pick(table):
                    have = set(columns(con, table))
                    bad = [c for c in fields[table] if c not in have]
                    if bad:
                        raise Invalid(f"unknown field(s) for {table}: {', '.join(bad)}")
                    never = [c for c in fields[table] if c in NEVER_PUBLISH]
                    if never:
                        raise Invalid(f"{', '.join(never)} is never read for a published file")
                    return ", ".join(dict.fromkeys(fields[table]))

                picked_columns = pick("projects")
                p = con.execute(f"SELECT {picked_columns} FROM projects WHERE code = ?", (code,)).fetchone()
                if p is None:
                    return None
                data = {"project": dict(p)}
                for t in PUBLISH_TABLES:
                    picked_columns = pick(t)
                    data[t] = [dict(r) for r in con.execute(
                        f"SELECT {picked_columns} FROM {_table(t)} WHERE project = ? ORDER BY {PUBLISH_ORDER[t]}", (code,))]
                ids = {r["id"] for t in ("milestones", "actions", "raid", "decisions") for r in data[t]}
                mine_like = code + "-%"                      # every id of a project starts with its code and a hyphen
                #                                              (links are kept only when BOTH ends are this project's rows)
                data["links"] = [dict(r) for r in con.execute(
                    "SELECT from_item, to_item, kind FROM links WHERE from_item LIKE ? OR to_item LIKE ? "
                    "ORDER BY from_item, to_item", (mine_like, mine_like))
                                 if r["from_item"] in ids and r["to_item"] in ids]
                labelled = ids | {r["id"] for r in data["use_cases"]}      # use cases too: Sensitive must be seen on them
                data["labels"] = {}
                for r in con.execute("SELECT item_id, label FROM item_labels WHERE item_id LIKE ? "
                                     "ORDER BY item_id, label COLLATE NOCASE", (mine_like,)):
                    if r["item_id"] in labelled:
                        data["labels"].setdefault(r["item_id"], []).append(r["label"])
                mine = {r["id"] for r in data["milestones"]}
                return {
                    "data": data,
                    "hidden": [r["item_id"] for r in con.execute("SELECT item_id FROM report_hidden WHERE project = ?", (code,))],
                    "sections": [dict(r) for r in con.execute(
                        "SELECT id, type, title, body, beside, hidden, sort_order FROM report_sections WHERE project = ? "
                        "ORDER BY sort_order, id", (code,))],
                    "glance_tiles": [dict(r) for r in con.execute(           # #45: the same query as data_for's, in this transaction
                        "SELECT project, tile, hidden, outline, sort_order FROM glance_tiles WHERE project = ? "
                        "ORDER BY sort_order, tile", (code,))],
                    "label_rules": [dict(r) for r in con.execute("SELECT name, behaviour, default_choice FROM labels")],
                    "changes": [dict(r) for r in con.execute(
                        "SELECT apply_id, tbl, item_id, field, op, new_value FROM change_log WHERE tbl = 'milestones' "
                        "AND field = 'baseline_date' AND item_id LIKE ? ORDER BY rowid", (mine_like,)) if r["item_id"] in mine],
                    "undone": [r["apply_id"] for r in con.execute("SELECT apply_id FROM applies WHERE undone_at IS NOT NULL")],
                }
            finally:
                con.execute("COMMIT")
        finally:
            con.close()

    def log_publication(self, code, path, week_ending, sha256, by_user, client_path=None):
        """Record one published file: a `publications` row with the file's SHA-256, and nothing else. No change_log,
        no step and no write to any other table: a publication is a record of a file, not an edit (#39; Head ruling,
        28-10-2026), so Undo never meets it. The folder to offer next time is read back from the latest publication
        (`last_publish_folder`), not kept as a field of the project. `client_path` (#43) is the verified copy in the client
        folder, given only when To client was ticked and the copy read back with the same SHA-256; it is the same file, so it
        is never the Local path. Returns the publication's number."""
        if not str(by_user or "").strip():
            raise Invalid("a publication needs who made it (by_user)")
        if not re.fullmatch(r"[0-9a-f]{64}", str(sha256 or "")):
            raise Invalid("a publication needs the file's SHA-256")
        if not Path(str(path)).is_absolute():
            raise Invalid("a publication needs the file's full path")
        if week_ending is not None:
            try:
                if not re.fullmatch(r"\d{4}-\d\d-\d\d", str(week_ending)):
                    raise ValueError
                date.fromisoformat(str(week_ending))
            except ValueError:
                raise Invalid(f"the report's date must be YYYY-MM-DD (got {week_ending!r})") from None
        if client_path is not None:
            if not Path(str(client_path)).is_absolute():
                raise Invalid("a publication needs the client copy's full path")
            if Path(str(client_path)) == Path(str(path)):
                raise Invalid("the client copy can't be the Local file")
        if self.con.in_transaction:
            raise Invalid("A publication can't be recorded in the middle of a step: finish the step first.")
        try:
            self.con.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as e:
            raise Invalid(_busy(e)) from e
        try:
            if not self.con.execute("SELECT 1 FROM projects WHERE code = ?", (code,)).fetchone():
                raise Invalid(f"project {code} isn't here")
            cur = self.con.execute(
                "INSERT INTO publications (project, week_ending, local_path, client_path, word, file_sha256, checks, by_user) "
                "VALUES (?, ?, ?, ?, 0, ?, 'not needed', ?)",
                (code, week_ending, str(path), None if client_path is None else str(client_path), sha256, str(by_user).strip()))
            self.con.execute("COMMIT")
            return cur.lastrowid
        except BaseException:
            self.con.execute("ROLLBACK")
            raise

    def latest_publication(self, code):
        """The project's latest publication for the report bar (#43): {"at", "to_client"} (when, and whether a verified copy went
        into the client folder), or None. Read-only; no path and no hash leave it."""
        r = self.con.execute("SELECT at, client_path FROM publications WHERE project = ? ORDER BY seq DESC LIMIT 1",
                             (code,)).fetchone()
        return {"at": r["at"], "to_client": r["client_path"] is not None} if r else None

    def last_publish_folder(self, code):
        """The folder the project's report was last published to (from the latest `publications` row), or None."""
        r = self.con.execute("SELECT local_path FROM publications WHERE project = ? AND local_path IS NOT NULL "
                             "ORDER BY seq DESC LIMIT 1", (code,)).fetchone()
        return str(Path(r["local_path"]).parent) if r else None

    def undo(self, step_id, by_user, place=None):
        """Reverse step `step_id` as a new step (creaite's undo-changes). Returns {"step_id", "reversed", "skipped"}; each
        skipped row names its ref, why, and the later step that changed it (by_step) when there is one. step_id is None when
        nothing could be put back (no step is written then).

        The new step's rows say which change_log rows they put back (via "revert:<rowids>"), and only rows actually put back
        are named: a row that is skipped stays in force. The step reversed keeps undone_at NULL, except that undoing an undo
        sets undone_at on that undo's step, once at least one row is put back, so the change it reversed is in force again.
        An undo of an undo can't be undone a third time (the change can be made again instead)."""
        with self.step("undo", by_user, place=place) as st:
            con = self.con
            a = con.execute("SELECT * FROM applies WHERE apply_id = ?", (step_id,)).fetchone()
            if a is None:
                raise Invalid(f"There's no step {step_id} to undo.")
            rows = [dict(r) for r in con.execute("SELECT rowid, * FROM change_log WHERE apply_id = ? ORDER BY rowid",
                                                 (step_id,))]
            undoing_a_revert = bool(rows) and all(str(r["via"]).startswith(REVERT_VIA) for r in rows)
            if a["undone_at"]:
                raise Invalid(f"Step {step_id} has been undone already.")
            reverted = reverted_rowids(con)
            real = [r for r in rows if r["field"] not in ("note", "updated_at") and r["via"] != SEED_VIA]   # the rows an undo can put back
            if not undoing_a_revert and real and all(r["rowid"] in reverted for r in real):
                raise Invalid(f"Step {step_id} has been undone already.")
            if undoing_a_revert:
                named = {int(x) for r in rows for x in str(r["via"])[len(REVERT_VIA):].split(",") if x.strip().isdigit()}
                if any(con.execute("SELECT 1 FROM change_log WHERE rowid = ? AND via LIKE 'revert:%'", (n,)).fetchone()
                       for n in sorted(named)):
                    raise Invalid(f"Step {step_id} undid an undo, so it can't be undone again. Make the change again instead.")
            st.via = PENDING_VIA
            done, skipped = revert_plan(con, rows, st, undoing_a_revert)
            new = st.peek_apply_id()
            if new is not None:
                con.execute("UPDATE change_log SET via = ? WHERE apply_id = ? AND via = ?",
                            (REVERT_VIA + ",".join(str(d["rowid"]) for d in done), new, PENDING_VIA))
                if undoing_a_revert and done:        # the change this undo reversed is in force again
                    con.execute("UPDATE applies SET undone_at = ? WHERE apply_id = ?", (now(), step_id))
            return {"step_id": new, "reversed": done, "skipped": skipped}

    def undo_many(self, step_ids, by_user, dry=False):
        """#197: reverse several steps, newest first, as ONE new step (its src_ref is BATCH_UNDO), so one Undo of it puts them all
        back (Store.undo of a revert step). Returns Store.undo's shape; each entry also says its `step`. A step that is an undo, or
        that has been undone already, is skipped and named, never refused. Each later step's put-back rows count as gone while an
        earlier one is judged, so a change and the creation it followed go back together. `dry=True` is the preview: the very same
        run, always rolled back. A step that isn't there refuses the whole request; nothing is written then."""
        ids = sorted({int(i) for i in step_ids}, reverse=True)
        if not ids or len(ids) > MAX_UNDO_MANY:
            raise Invalid(f"Choose 1 to {MAX_UNDO_MANY} changes to undo.")
        with self.step("undo", by_user, src_ref=BATCH_UNDO, dry=dry) as st:
            con, done_all, skipped_all = self.con, [], []
            st.via = PENDING_VIA
            for sid in ids:
                a = con.execute("SELECT undone_at FROM applies WHERE apply_id = ?", (sid,)).fetchone()
                rows = [dict(r) for r in con.execute("SELECT rowid, * FROM change_log WHERE apply_id = ? ORDER BY rowid", (sid,))]
                if a is None or not rows:
                    raise Invalid(f"There's no step {sid} to undo.")
                real, reverted = [r for r in rows if r["field"] not in ("note", "updated_at") and r["via"] != SEED_VIA], reverted_rowids(con)
                why = ("is an undo" if all(str(r["via"]).startswith(REVERT_VIA) for r in rows) else
                       "already undone" if a["undone_at"] or (real and all(r["rowid"] in reverted for r in real)) else None)
                if why:
                    done, skipped = [], [{"rowid": r["rowid"], "ref": r["item_id"], "field": r["field"], "why": why, "by_step": None}
                                         for r in real]
                else:
                    done, skipped = revert_plan(con, rows, st, False)
                tbl = {r["rowid"]: r["tbl"] for r in rows}
                done_all += [dict(d, step=sid, table=tbl.get(d["rowid"])) for d in done]
                skipped_all += [dict(x, step=sid, table=tbl.get(x["rowid"])) for x in skipped]
                if st.peek_apply_id() is not None:      # the rows put back so far count as gone for the older steps still to come
                    con.execute("UPDATE change_log SET via = ? WHERE apply_id = ? AND via LIKE 'revert:%'",
                                (REVERT_VIA + ",".join(str(d["rowid"]) for d in done_all), st.peek_apply_id()))
            return {"step_id": None if dry else st.peek_apply_id(), "reversed": done_all, "skipped": skipped_all}

    def batch_undo_steps(self, apply_id):
        """#197: the steps a batch undo (Store.undo_many) reversed, oldest first, or None when `apply_id` is not one. Read only."""
        if not self.con.execute("SELECT 1 FROM item_events WHERE apply_id = ? AND src_ref = ? LIMIT 1", (apply_id, BATCH_UNDO)).fetchone():
            return None
        vias = [r[0] for r in self.con.execute("SELECT via FROM change_log WHERE apply_id = ?", (apply_id,))]
        if not vias or not all(str(v).startswith(REVERT_VIA) for v in vias):
            return None
        named = {int(x) for v in vias for x in str(v)[len(REVERT_VIA):].split(",") if x.strip().isdigit()}
        return sorted({r[0] for n in sorted(named) for r in self.con.execute(
            "SELECT apply_id FROM change_log WHERE rowid = ?", (n,)) if r[0] is not None})

    def step_rows(self, apply_id):
        """What step `apply_id` wrote, read only: [{"table", "key", "field", "via", "op"}], one per change_log row, oldest first; [] for a step
        that wrote nothing or is not there. #65: so /api/undo can refuse a step that is not the report's before it asks for an
        undo. It changes nothing. #45: each row also says its `field`, so an Undo can check the field and not only the table."""
        return [{"table": r["tbl"], "key": r["item_id"], "field": r["field"], "via": r["via"], "op": r["op"]} for r in self.con.execute(
            "SELECT tbl, item_id, field, via, op FROM change_log WHERE apply_id = ? ORDER BY rowid", (apply_id,))]

    def history(self, ref):
        from clark import history
        return history.history(self.con, ref)

    def milestone_moves(self, code):
        """#136: the date and state history of a project's live milestones, for Movement (owner only: never published, never in
        data_for or publish_inputs). One read-only connection, one transaction, one query on MOVE_FIELDS (the internal note is not
        among them), which uses the index on change_log's item_id. Writes nothing. None when there is no such project, else
        {"project", "milestones": {id: {"original", "total", "events"}}, "truncated"}: every live milestone (one with no changes
        has events []; the step that made it is not listed), its events newest first in history.history's shape (plus the last decision ID its step names and src_ref
        when it is Movement), at most MOVE_PER_MILESTONE each and MOVE_PER_PROJECT in all (the newest across the project);
        `total` counts them before the cut and `truncated` says something was cut. A note row is kept only in a step that also
        has a date, status, state or Movement row, so a note written alone (a Hold's dated line) never comes out."""
        con = connect(self.path, readonly=True)
        try:
            con.execute("BEGIN")
            if con.execute("SELECT 1 FROM projects WHERE code = ?", (code,)).fetchone() is None:
                return None
            live = [r["id"] for r in con.execute("SELECT id FROM milestones WHERE project = ? AND archived = 0 ORDER BY id", (code,))]
            rows = sorted(con.execute(MOVE_SQL % ", ".join("?" * len(MOVE_FIELDS)), (code + "-M-", code + "-M.") + MOVE_FIELDS),
                          key=lambda r: r["rowid"])
            reverted = reverted_rowids(con)
        finally:
            con.close()
        by_milestone = {m: [] for m in live}
        for r in rows:
            if r["item_id"] in by_milestone:
                by_milestone[r["item_id"]].append(r)
        out, kept = {}, []
        for mid, mine in by_milestone.items():
            beside = {r["apply_id"] for r in mine if r["field"] in MOVE_DATED}
            steps = {}
            for r in mine:
                if r["field"] == "note":
                    steps.setdefault(r["apply_id"], []).append(r["new_value"] or "")
            original = next((r["new_value"] for r in mine if r["field"] == "baseline_date" and r["new_value"] is not None
                             and r["undone_at"] is None and not str(r["via"]).startswith(REVERT_VIA)
                             and r["rowid"] not in reverted), None)
            made = {r["apply_id"] for r in mine if r["field"] == "id"}     # the step that made the milestone is not a movement
            shown = [r for r in mine if r["apply_id"] not in made and (r["field"] != "note" or r["apply_id"] in beside)]
            undone_by = {r["undoes"]: r["event_id"] for r in shown if r["undoes"] is not None}
            events = []
            for r in shown:
                found = MOVE_DECISION.findall(" ".join(steps.get(r["apply_id"], ())))
                events.append({
                    "event_id": r["event_id"], "at": r["at"], "step": r["apply_id"], "by_user": r["by_user"], "table": "milestones",
                    "ref": r["item_id"], "field": r["field"], "before": r["old_value"], "after": r["new_value"], "op": r["op"],
                    "route": r["route"], "place": r["place"], "origin": r["origin"], "actor": r["actor"],
                    "src_ref": r["src_ref"] if r["src_ref"] == MOVE_PLACE_NAME else None, "decision": found[-1] if found else "",
                    "undoes": r["undoes"], "is_undo": str(r["via"]).startswith(REVERT_VIA),
                    "undone_by": undone_by.get(r["event_id"]), "in_force": not r["undone_at"] and r["rowid"] not in reverted})
            events.sort(key=lambda e: e["event_id"], reverse=True)
            from clark import milestone_rows        # the count of moves is made here, over the whole history, before any cut
            # Same counting rule as the Movement page's list and card (one function, milestone_rows.moves); test_store_movement pins the two together.
            moves = milestone_rows.moves(milestone_rows.movement(events, mid))
            out[mid] = {"original": original, "total": len(events), "moves": moves, "events": cut_whole_steps(events, MOVE_PER_MILESTONE)}
            kept.extend((e["event_id"], mid) for e in out[mid]["events"])
        truncated = any(len(b["events"]) < b["total"] for b in out.values())
        if len(kept) > MOVE_PER_PROJECT:
            groups = {}
            for b_id, b in out.items():
                for e in b["events"]:
                    groups.setdefault((b_id, e["step"]), []).append(e)
            keep, used = set(), 0
            for key, g in sorted(groups.items(), key=lambda kv: max(e["event_id"] for e in kv[1]), reverse=True):
                if keep and used + len(g) > MOVE_PER_PROJECT:
                    break
                keep.add(key)
                used += len(g)
            for b_id, b in out.items():
                b["events"] = [e for e in b["events"] if (b_id, e["step"]) in keep]
            truncated = True
        return {"project": code, "milestones": out, "truncated": truncated}


class Step:
    """The step being written: who, how (route, place, origin, actor), and its applies row once it has one."""

    def __init__(self, store, via, by_user, place, origin, actor, src_ref):
        route = "undo" if via == "undo" else via
        if route not in ROUTES:
            raise Invalid(f"unknown route {via!r}")
        if place is not None and place not in PLACES or origin is not None and origin not in ORIGINS or actor not in ACTORS:
            raise Invalid("unknown place, origin or actor")
        if not str(by_user or "").strip():
            raise Invalid("a step needs who made it (by_user)")
        self.store, self.con = store, store.con
        self.via, self.route, self.place, self.origin, self.actor, self.src_ref = via, route, place, origin, actor, src_ref
        self.by_user = str(by_user).strip()
        self._apply_id = None
        self.result = {}                       # #126: what a project's archive or restore did: {"counts": {table: n}, "found_step": bool}

    def apply_id(self):
        """This step's applies row, made the first time something is logged."""
        if self._apply_id is None:
            cur = self.con.execute("INSERT INTO applies (at, proposals, by_user, device) VALUES (?, '[]', ?, ?)",
                                   (now(), self.by_user, self.store.device))
            self._apply_id = cur.lastrowid
        return self._apply_id

    def forget_apply_id(self):
        """The applies row was rolled back with a failed group: the next write makes a new one."""
        self._apply_id = None

    def peek_apply_id(self):
        """This step's applies row, or None if nothing is written yet."""
        return self._apply_id

    def create(self, kind, values):
        """A new row; returns its ref (the ID clark gives it, or its key)."""
        return write_item(self.con, {"table": kind, "op": "new", "values": dict(values)}, self)

    def seed_sections(self, code):
        """clark (#65, FR-10): give a project that has no report sections (one made before #65) the default ones, in THIS step,
        with the ids and places a new project gets. An Undo of the step takes back the change only: the seed stays (SEED_VIA)."""
        if self.store.read("report_sections", code):
            raise Invalid(f"{code} has its report sections already.")
        _seed_sections(self.con, code, self)

    def seed_tiles(self, code):
        """clark (#45): give a project that has no tile rows the four default ones, in THIS step, as history only (SEED_VIA). An
        Undo of the step takes back the change only: the tiles stay. Refused when the project has tile rows already."""
        if self.store.read("glance_tiles", code):
            raise Invalid(f"{code} has its At a glance tiles already.")
        _seed_tiles(self.con, code, self)

    def update(self, kind, ref, changes, rebaseline=None, note=None):
        """Change fields of one row; only fields that differ are written."""
        item = {"table": kind, "op": "update", "id": ref, "changes": dict(changes)}
        if rebaseline is not None:
            item["rebaseline"] = rebaseline
        if note:
            item["note"] = note
        return write_item(self.con, item, self)

    def archive(self, kind, ref):
        """Hide a record (#126): nothing is deleted and its status is unchanged. One of the only two setters of `archived`."""
        return write_item(self.con, {"table": kind, "op": "archive", "id": ref}, self)

    def restore(self, kind, ref):
        """Bring an archived record back, as it was (#126)."""
        return write_item(self.con, {"table": kind, "op": "restore", "id": ref}, self)

    def cancel(self, kind, ref):
        """Close a row as cancelled (work items, projects, workstreams), or remove a link, label or item label."""
        return write_item(self.con, {"table": kind, "op": "cancel", "id": ref}, self)
