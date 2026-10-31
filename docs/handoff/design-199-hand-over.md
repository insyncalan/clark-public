# #199 design note: Hand over

For the Full readers. Hand over gives the open work items on the list to someone else: tick them, name a person, one step, one Undo.

## What it builds on

- **#195** (selecting several) and **#196** (the bulk change): used as they are. Hand over sends its request through #196's `changeBulk`
  and shows #196's question (`ask`) above 25. Nothing of theirs is changed except two guards in `edit/Bulk.jsx` (the right-click menu and
  the keys O S P T C do nothing while pick mode is on).
- **#115** (the people table) is **not merged**: its branch holds only a design note, so there is no table or code to use. The
  "Hand over to" box is a text box that suggests the names already on the project (`people(data)`, the same list the Owner picker uses).
  When the people table lands, that list is the one place to change. Any text is accepted, as for a single owner change.

## The request

`POST /api/change`, the existing route and its 16 KiB limit:

```json
{"project": "ABC", "kind": "actions", "op": "handover", "ids": ["ABC-A-001", "ABC-006", "ABC-D-009"], "to": "Zelda Quince", "confirm": false, "place": "bulk"}
```

- **Why a new op:** #196's `bulk` takes one kind per request ("These items are of different kinds"), so a person's actions, risks and
  decisions together would be three steps and three Undos. `handover` takes all three in **one step**. `kind` is any work item kind (the
  page sends the first item's); only `ids`, `to` and `confirm` are read. Nothing else can be changed: no status, archive or delete.
- **The field:** an action's or risk's `owner`, a decision's `made_by` (`HAND_OVER_FIELD`).
- **Checks, the same as `bulk`:** 1 to 500 ids, each of this project and a work item id; `to` is plain text, 1 to 200 characters; more
  than 25 ids (every id sent) without `confirm: true` is a 409 `confirm` ("Change 26 items?"); an archived project is read only.
- **How it is written:** a trial step (always rolled back) tries each item; one that is gone or archived, or that the store refuses, is
  left out and named with #196's fixed words; one that has the owner already is counted. Then one real step writes the rest. If one is
  refused there, the whole step rolls back ("Your page is out of date"). The reply is `bulk`'s: `apply_id`, `changed`, `unchanged`,
  `left_out`, `words`, `items` (id and new owner only).
- **Undo:** the existing `/api/undo`. One Undo puts every owner back (the store's standing rule applies if an item was changed again).

## The page

- **The button:** **Hand over**, beside Add on Work items, in Edit, only while the Owner filter is on and picks people. There is no
  person page in clark yet (#115 is not built), so that button waits for it.
- **Pick mode** (`edit/HandOver.jsx`, ticks in `stores/handover.js`, a selection of its own so the Work items selection is untouched):
  a tick box on each open item (closed, cancelled, made and withdrawn items have none; archived items are not in the list), a click or
  Space on a row ticks it, **All** and **None**, "N of M selected", **Hand over to**, **Hand over** (waits, with the reason in words,
  until something is ticked and a name is given) and **Cancel**. Esc leaves it unless a question or a picker is open. It is drawn as
  the table, also when the board was showing.
- **Off while it is on:** Shift with an arrow, Ctrl or Cmd+A, Enter and double click (no peek), the cells' pickers, the right-click menu,
  Shift+F10 and the keys O S P T C. The arrows still move between rows.
- **Ends:** after a hand over that changed something, on Cancel or Esc, on a change of tab or project, and on leaving Edit.
  A filter that hides a ticked item unticks it and says so.

## Guarded files

`src/clark/changes.py` only: the op, its allow-list entry, `_do_hand_over`. No change to the store, server, schema or backups.
Three existing assertions in `tests/test_changes.py` that pin the exact list of ops gain `handover`.

## Not done

- Help is unchanged: its tests pin the counts of tasks and keys, and Hand over is neither.
- The prototype (`system/prototype`) has no Hand over; only the product page does.
