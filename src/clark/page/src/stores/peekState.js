// The peek's width and whether it spans the screen (#42). The width is kept in this browser (localStorage, wrapped: it can throw or
// come back empty in a private window) so a reload and the next item keep it. "Across the whole screen" is for now only.
import { signal } from "@preact/signals";

export const MIN = 420;
const KEY = "clark.peekWidth";
export const DEFAULT = 560;

export function limit(w, win = document.documentElement.clientWidth) {
  const top = Math.max(MIN, win), n = Math.round(Number(w));
  return Number.isFinite(n) ? Math.min(top, Math.max(Math.min(MIN, top), n)) : DEFAULT;
}

function saved() {
  try { const n = Number(localStorage.getItem(KEY)); return n ? limit(n) : DEFAULT; } catch (e) { return DEFAULT; }
}

export const width = signal(saved());
export const wide = signal(false);

/** Set the width (kept between MIN and the window) and remember it. */
export function setWidth(w) {
  width.value = limit(w);
  try { localStorage.setItem(KEY, String(width.value)); } catch (e) { /* the width still holds for this visit */ }
}

/** Double-click on the edge: back to the default, and forget the saved one. */
export function resetWidth() {
  width.value = limit(DEFAULT);
  try { localStorage.removeItem(KEY); } catch (e) { /* as above */ }
}

// Which part of the peek shows in Edit: "details" (the fields) or "activity" (#42). Memory only; View has no tabs.
export const peekTab = signal("details");

// The rule for the peek and multi-select (#195), in peek/follow.js so it can be checked without the page.
export { peekFollowsSelection } from "../peek/follow.js";
