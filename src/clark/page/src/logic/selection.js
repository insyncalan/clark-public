// Selecting several items (#195): the rules, as plain functions with no DOM, no signals and no clock. A selection is
//   { ids: [...], anchor: id | null, cursor: id | null, all: false }
// `ids` keeps the order things were added; `anchor` is where a Shift range starts; `cursor` is the row or card that has the
// keyboard; `all` is true after "Select all N matching", when the selection follows the filters (it holds every item the
// filters show, collapsed groups too) until the person picks by hand again.
// `order` is always the ids in the order they are drawn on the screen (a collapsed group's rows are not drawn), so a range
// is what the person sees between the two ends, never the order of the data.
// Nothing here is saved: the selection lives in memory only. stores/selection.js wraps these in signals for the page.

export const EMPTY = Object.freeze({ ids: [], anchor: null, cursor: null, all: false });

const uniq = (xs) => Array.from(new Set(xs));
const make = (ids, anchor, cursor, all = false) => ({ ids: uniq(ids), anchor: anchor == null ? null : anchor, cursor: cursor == null ? null : cursor, all: !!all });

/** The ids from `a` to `b` inclusive, in the drawn order (either way round). An end that is not drawn gives just the other end. */
export function rangeOf(order, a, b) {
  const i = order.indexOf(a), j = order.indexOf(b);
  if (j < 0) return i < 0 ? [] : [a];
  if (i < 0) return [b];
  return order.slice(Math.min(i, j), Math.max(i, j) + 1);
}

/** A click on `id`. `add` is Cmd (Mac) or Ctrl (Windows) held; `range` is Shift held. */
export function click(st, id, { add = false, range = false } = {}, order = []) {
  if (range) {
    const from = st.anchor != null && order.includes(st.anchor) ? st.anchor : id;
    const span = rangeOf(order, from, id);
    return make(add ? st.ids.concat(span) : span, from, id);
  }
  if (add) {
    const has = st.ids.includes(id);
    return make(has ? st.ids.filter((x) => x !== id) : st.ids.concat([id]), id, id);
  }
  return make([id], id, id);
}

/** Space on the cursor row: add it, or take it out. */
export function toggle(st, id) { return click(st, id, { add: true }); }

/** The cursor moved without a change to what is picked (an arrow key, a focus). */
export function moveCursor(st, id) { return { ...st, cursor: id }; }

/** Shift+Up (`step` -1) or Shift+Down (+1): move the cursor one row and select from the anchor to it. Returns the new
 *  selection; its `cursor` is the row to focus. At either end the cursor stays where it is. */
export function extend(st, step, order) {
  if (!order.length) return st;
  const at = st.cursor != null && order.includes(st.cursor) ? st.cursor : order[0];
  const i = order.indexOf(at), j = Math.max(0, Math.min(order.length - 1, i + step)), to = order[j];
  const from = st.anchor != null && order.includes(st.anchor) && st.ids.includes(st.anchor) ? st.anchor : at;
  return make(rangeOf(order, from, to), from, to);
}

/** Cmd or Ctrl+A: every row drawn. */
export function selectAll(st, order) { return make(order, order[0], st.cursor != null ? st.cursor : order[0]); }

/** A group's tick box: "checked" when every one of its drawn rows is picked, "mixed" when some are, else "unchecked". */
export function groupState(st, groupIds) {
  if (!groupIds.length) return "unchecked";
  const n = groupIds.filter((id) => st.ids.includes(id)).length;
  return n === 0 ? "unchecked" : n === groupIds.length ? "checked" : "mixed";
}

/** A click on a group's tick box: a group that is all picked is cleared, any other is picked in full. */
export function toggleGroup(st, groupIds) {
  if (groupState(st, groupIds) === "checked") return make(st.ids.filter((id) => !groupIds.includes(id)), st.anchor, st.cursor);
  return make(st.ids.concat(groupIds), groupIds[0], st.cursor);
}

/** "Select all N matching" is offered when two or more are picked and fewer than the filters show. */
export function offersAllMatching(st, matching) { return st.ids.length >= 2 && st.ids.length < matching.length; }

/** "Select all N matching": every item the filters show, collapsed groups too. The selection then follows the filters. */
export function selectMatching(st, matching) { return make(matching, st.anchor, st.cursor, matching.length > 0); }

/** After the list is drawn again (a filter, a collapse, new data): what is still picked, and how many left.
 *  `drawn` is the rows on the screen, `matching` every item the filters show. With "all matching" on, the selection is
 *  every match, while any still match; otherwise a row that is not drawn leaves the selection. */
export function sync(st, drawn, matching) {
  if (st.all) {
    if (!matching.length) return { sel: EMPTY, left: st.ids.length };
    const same = matching.length === st.ids.length && matching.every((id, i) => id === st.ids[i])
      && (st.anchor == null || matching.includes(st.anchor)) && (st.cursor == null || matching.includes(st.cursor));
    if (same) return { sel: st, left: 0 };
    const kept = make(matching, matching.includes(st.anchor) ? st.anchor : null, matching.includes(st.cursor) ? st.cursor : null, true);
    return { sel: kept, left: 0 };
  }
  const ids = st.ids.filter((id) => drawn.includes(id));
  if (ids.length === st.ids.length) return { sel: st, left: 0 };
  return { sel: make(ids, ids.includes(st.anchor) ? st.anchor : null, st.cursor), left: st.ids.length - ids.length };
}

/** The words a screen reader is told, and the bar shows. */
export function countWords(n) { return n === 0 ? "Nothing selected" : `${n} selected`; }
export function leftWords(n) { return `${n} left the selection`; }
export function matchingWords(n) { return `Select all ${n} matching`; }
