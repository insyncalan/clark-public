// #199: Hand over, the rules as plain functions with no DOM, no signals and no clock. Hand over gives the open work items on the
// list to someone else in one step with one Undo: the items are ticked, a person is named, and one request goes to clark (op
// "handover", clark/changes.py). The ticks are the page's own and never saved. Archived and closed items are never offered.
import { isOpen } from "../workItems.js";
import { CONFIRM_ABOVE, MAX, tableOf, itemsWords } from "../edit/bulkLogic.js";

/** The items Hand over offers from the rows shown: the open ones, in the order given. */
export const offered = (rows) => rows.filter((r) => isOpen(r));

/** Whether a row may be ticked. */
export const canTick = (row) => isOpen(row);

/** "3 of 12 selected": what the bar and a screen reader say. */
export const countWords = (n, m) => `${n} of ${m} selected`;

/** What stops the Hand over button, in words, or "" when it can go. `to` is what has been typed in the person field. */
export function why(n, to) {
  if (n === 0) return "Tick at least one item.";
  if (n > MAX) return `Tick at most ${MAX} items at a time.`;
  if (!clean(to)) return "Say who to hand over to.";
  return "";
}

/** The name as it will be saved: trimmed, with inner spaces made single. */
export const clean = (to) => String(to == null ? "" : to).trim().split(/\s+/).filter(Boolean).join(" ");

/** The request for clark: one hand over of `ids` to `to`. The kind is the first item's; the items may be of all three kinds. */
export function requestFor(rows, ids, to, { confirm = false } = {}) {
  const first = rows.find((r) => r.id === ids[0]);
  return { kind: first ? tableOf(first) : "actions", op: "handover", ids: ids.slice(), to: clean(to), place: "bulk", ...(confirm ? { confirm: true } : {}) };
}

/** Whether to ask first, and the question: above CONFIRM_ABOVE items. */
export const needsConfirm = (n) => n > CONFIRM_ABOVE;
export const confirmWords = (n, to) => `Hand over ${n} items to ${clean(to)}?`;

/** What the toast says after the Undo of a hand over. */
export const backWords = (n) => `Undone: ${itemsWords(n)} ${n === 1 ? "is" : "are"} back with ${n === 1 ? "its" : "their"} owner.`;

/** Whether the Owner filter is on and picks people (not "is not"): the Hand over button is offered then. */
export function ownerFilterOn(state) {
  const f = state && state.filters && state.filters.owner;
  return Array.isArray(f) && f.length > 0 && !(state.not && state.not.owner);
}
