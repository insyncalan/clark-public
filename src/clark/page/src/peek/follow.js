// What an open peek does when the multi-select count changes (#42 with #195). The one rule, written once: while selecting is on, a
// single click selects (it does not open the peek); with 2 or more selected an open peek closes; with exactly 1 it moves to that
// item (or stays, if it is already showing it); with none it stays as it is. A closed peek is never opened by selecting.
// No imports, so it can be checked on its own.

/** "close" | "follow" | "stay" | "none" for `count` items selected and the peek open or not. */
export function peekFollowsSelection(count, peekOpen) {
  if (!peekOpen) return "none";
  const n = Number(count);
  if (!Number.isInteger(n) || n <= 0) return "stay";
  return n === 1 ? "follow" : "close";
}
