"""The one function behind GET /api/activity (#42): one item's Activity tab in the peek, for the owner only (Edit mode).

The server imports nothing from clark, so this is the seam it is given (as it is given `movement`). It checks the item is one of
the project's, opens its own read-only connection, asks history.activity_for_item and keeps only what the tab draws: for each
change, who made it, how, when, what changed and from what to what, newest first. Writes nothing. No publishing module uses it.
Standard library only, Python 3.9."""
from clark import history
from clark.store import connect

TABLES = ("actions", "raid", "decisions", "milestones")      # the rows a peek opens on
ROW_KEYS = ("when_text", "who", "how", "kind", "field", "from", "to", "diff", "diff_note")
ROW_LIMIT = 200                      # the newest changes the tab shows; the closing line says when older ones are left out
CLOSING = "Older changes are kept in clark. Showing the newest 200."
TEXT_LIMIT = 4000                    # characters of a from or to value the tab gets; a longer text ends with an ellipsis


def _short(value):
    text = "" if value is None else str(value)
    return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT] + "…"


def _row(r):
    out = {k: r.get(k) for k in ROW_KEYS}
    out["from"], out["to"] = _short(out["from"]), _short(out["to"])
    if out["diff_note"] is None:
        out.pop("diff_note")
    return out


def has_item(data, item_id):
    """True when `item_id` is a row of the project's data (an action, a register item, a decision or a milestone)."""
    return any(isinstance(r, dict) and r.get("id") == item_id for t in TABLES for r in (data.get(t) or []))


def make_read(path, data_for):
    """`read(code, item_id)` for the server: None when the project or the item isn't there, else {"rows", "empty", "closing"}.
    `path` is clark.db; `data_for(code)` is Store.data_for."""
    def read(code, item_id):
        data = data_for(code)
        if data is None or not has_item(data, item_id):
            return None
        con = connect(path, readonly=True)
        try:
            view = history.activity_for_item(con, item_id, "all", ROW_LIMIT)
        finally:
            con.close()
        rows = [_row(r) for r in view["rows"]]
        return {"rows": rows, "empty": "" if rows else "Nothing has changed on this item yet.",
                "closing": CLOSING if view["closing"] else ""}
    return read
