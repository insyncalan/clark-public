# #196 design note: the bulk change (stage 1, the writer side)

For the two Full readers. Stage 1 is the server side only; the bar, the right-click menu and the keys come in stage 2, on top of
#195's selection.

## The request

`POST /api/change`, the existing route and its 16 KiB body limit. One new op, `bulk`, for the three work item kinds only:

```json
{"project": "ABC", "kind": "actions", "op": "bulk", "ids": ["ABC-A-001", "ABC-A-002"],
 "changes": {"owner": "Zelda Quince"}, "confirm": false, "place": "bulk"}
```

- **Fields** (`CHANGE_KINDS[kind]["bulk"]`): actions take status, owner, due date, priority, workstream and milestone; risks and
  issues take status, owner, due date, impact, likelihood, workstream and milestone (their priority is worked out by the store);
  decisions take only `made_by`. Close and Reopen are a status. Never a title, `archived`, the type, the project or the
  client-visible flag (V stays a one-item change).
- **ids**: 1 to 500 (`MAX_BULK`; 500 of the longest ids fit the body limit, a test says so), duplicates dropped. Each one is
  checked from the id alone before anything is read: not an item id is "That item isn't in this project.", another project's
  is "These items are in different projects.", another kind's is "These items are of different kinds." Any of these refuses
  the whole request.
- **confirm**: more than 25 distinct ids (every id sent, those that will be left out included) without `confirm: true` is a
  409 with code `confirm`, the words "Change 26 items?" and `count`. Nothing is written.
- **place**: as sent (the table, the board, the menu), else `bulk`; the store already knows `bulk`, and the history says
  "In the table".

## How it is written: one batch, one writer

1. A **trial** step (`store.step(..., dry=True)`, always rolled back, no safety copy) tries each item with the ordinary
   `Step.update`. An item that is gone or archived, or that the store refuses (a closing date before it was raised, an
   archived milestone, a workstream that isn't active), is **left out and named**, with the same fixed words a single edit
   uses. An item whose row is the same after the trial **already has it**.
2. If none can take it: refused (400, code `none_can`, with `left_out`), with the shared reason when there is one. If they
   all have it already: 200, no step, "Nothing changed: they already have that."
3. Otherwise **one real step** writes every item that can take it: one `applies` row, one safety copy at most (the store's
   own daily rule), and per item and field one `change_log` and `item_events` row, exactly as a single edit writes them.
   If any item is refused here (the data changed between the trial and the write) the whole step rolls back and the reply
   is "Your page is out of date. Reload it, then try again."

The reply: `apply_id`, `undoable`, `changed`, `unchanged`, `left_out` (id and why), `items` (the changed rows' shown fields,
never a title) and `words` for the toast ("Changed 3 items. 1 already had that. Left out ABC-A-004: It is archived. Restore
it first.").

## Undo

The batch is one step, so the existing `/api/undo` reverses it whole, and #197 sees one row. `_eligible` gains only the bulk
fields (impact and likelihood) in its work-item family. An undo of the undo is the store's, as for one edit; the page route
still refuses it.

"One Undo restores all" holds unless an item was changed again after the batch: then the Undo puts the others back, leaves
that item as it is and says why (the store's standing rule for every Undo, not new here).

## Deliberate choices, for the readers to confirm

- A bulk change tells an archived item ("It is archived. Restore it first.") apart from a missing one ("It isn't in this
  project now."). Both are this project's own ids, so nothing about another project is told.
- A decision that is Made or Withdrawn keeps who made it: a bulk "Made by" leaves it out and says so, so the record of
  who decided is never rewritten.
- Impact and likelihood can be changed in bulk only; a single change still doesn't take them. This widens what a request may
  change on a risk or issue.
- `changed` lists only the items whose row is different after the real write; one that had the value by then is counted
  with `unchanged`.

## Guarded files

Only `src/clark/changes.py`. No change to the store, the server, the schema or backups. `Refused` gains an optional `extra`
that `_call` adds to the reply without replacing `ok`, `message` or `code`.

## Never deletes

Archiving and deleting are not bulk fields. A bulk Archive is a later proposal (the standing rule: "we never delete, we archive").
