# Design: #42 the peek and Sneak peek: the Activity tab and the rule with multi-select

**Status, 01-11-2026:** built on the peek branch. Short note: what the peek shows in each mode, where its history comes from, and the one rule it follows when multi-select (#195) lands.

## 1. What the peek shows
- **View and a published file:** the item's fields and nothing else: no tabs, no Activity, no words box, no `/api/` text.
- **Edit:** two tabs under the title, **Details** (the fields) and **Activity**. Left and Right move between the tabs, Home and End jump. The sparkle and `//` open Sneak peek, as before.

## 2. The Activity tab
- Read from `GET /api/activity?project=<CODE>&item=<ID>` (`server.py`, guarded), through the seam `src/clark/activity_read.py`, which calls `history.activity_for_item` on a read-only connection. Nothing is written.
- Each row says who made the change, how (the place or route, in plain words), when, and what changed from what to what; a long text shows as a word diff. Newest first, at most 200 rows, then a closing line.
- An item with no rows says so in a plain line. If the read fails, the tab says so and how to try again.
- The page file is `edit/PeekActivity.jsx` (with `edit/activityApi.js`); neither is in `page-view.html`.

## 3. The rule with multi-select (#195)
While selecting is on:
1. A single click selects the row; it does not open the peek.
2. With 2 or more selected, an open peek closes.
3. With exactly 1 selected, an open peek moves to that item, or stays if it already shows it.
4. With none selected, an open peek stays as it is. Selecting never opens a closed peek.

The rule is one pure function, `peekFollowsSelection(count, peekOpen)` in `src/clark/page/src/peek/follow.js` (exported from `stores/peekState.js`). It answers `"close"`, `"follow"`, `"stay"` or `"none"`, and `tests/test_peek_activity.py` checks it for 0, 1 and 2 selected with the peek open and closed. #195 is not on this branch's base, so nothing calls it yet: whichever of the two branches lands second wires the selection count to it.
