// Selecting Work items rows and cards (#195), the part that reads the screen: the drawn order, what a click or a key on a row
// or a card does, and the page-wide ways a selection ends (Esc, a click outside, a change of tab or project, a peek closed when
// two or more are picked). The rules are in ../logic/selection.js and the state in ../stores/selection.js.
// The table (WorkItems.jsx) and the board (edit/Board.jsx) both call these, so a row and a card behave the same.
import { effect } from "@preact/signals";
import { item, view, project, openPeek, closePeek, fromFile } from "../stores/report.js";
import { workSelection as sel } from "../stores/selection.js";

const ITEMS = "#work-list tr[data-id], #work-list article.bcard[data-id]";
const CONTROL = "a, button, input, select, textarea, label, .ddmenu, .dpick, [data-peek]";   // and any text that can be typed in: isContentEditable
// Open things that take Esc and clicks for themselves: a menu, a picker, a date or filter box, a dialog, the peek.
const OVERLAY = ".ddmenu, .dpick, .fbox, .pop, [data-pop], [role='dialog'], [aria-modal='true'], [data-peek]";   // #196: + a picker's own panel

/** The ids of the rows or cards on the screen, in the order drawn (a collapsed group's are not drawn). */
export function drawnOrder() { return Array.from(document.querySelectorAll(ITEMS), (e) => e.dataset.id); }

/** True when the selection works here: the page clark serves, not a published file (a file is read only: nothing to do with several). */
export const selecting = () => !fromFile.value;

/** Whether a click on `target` is the row's own (a link, a button, a box or a field keeps its job). */
export function ownClick(target, within) {
  if (!target || target.isContentEditable || !target.closest) return false;
  const c = target.closest(CONTROL);
  return !c || c === within || !within.contains(c);
}

/** A mouse press with Shift would select the text between the clicks: stop that, so a Shift range reads only as a range. */
export function noTextRange(e) { if (e.shiftKey && e.button === 0) e.preventDefault(); }

/** A click on a row or card: plain selects only it; Cmd or Ctrl adds or removes it; Shift selects the range from the last one,
 *  in the drawn order; Cmd or Ctrl with Shift adds the range. With the peek open on one item, the peek follows. */
export function pickClick(e, id, opener = (x) => openPeek(x, "item")) {
  const add = e.metaKey || e.ctrlKey, range = e.shiftKey;
  if (!add && !range && String(window.getSelection ? window.getSelection() : "").length) return;    // the person is selecting text
  sel.click(id, { add, range }, drawnOrder());
  if (item.value && sel.size.value === 1 && sel.has(id) && item.value !== id) opener(id);
}

/** A double click opens the peek on that item (and selects only it). */
export function pickOpen(id, opener = (x) => openPeek(x, "item")) { sel.click(id, {}, drawnOrder()); opener(id); }

/** The selection keys on a row or a card (the element with the keyboard), before the arrow keys move the cursor.
 *  `focus(id)` puts the keyboard on that row or card. Returns true when the key was used. */
export function pickKeys(e, id, focus, { space = true } = {}) {
  if (e.defaultPrevented || e.altKey) return false;
  const mod = e.metaKey || e.ctrlKey;
  if (mod && !e.shiftKey && (e.key === "a" || e.key === "A")) { e.preventDefault(); sel.selectAll(drawnOrder()); return true; }
  if (mod) return false;
  if (e.shiftKey && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
    e.preventDefault();
    sel.moveCursor(id);
    const to = sel.extend(e.key === "ArrowDown" ? 1 : -1, drawnOrder());
    if (to && to !== id) focus(to);
    return true;
  }
  if (space && !e.shiftKey && e.key === " ") { e.preventDefault(); sel.toggle(id); return true; }
  return false;
}

// ---- the page-wide endings, installed once by the Work items page ----
let installed = false;
export function installSelectionRules() {
  if (installed || typeof document === "undefined") return;
  installed = true;
  // Two or more picked: a peek that shows one record closes.
  sel.onChange((next) => { if (next.ids.length >= 2 && item.value) closePeek(); });
  // A change of tab or of project ends it.
  let where = `${view.value}\u0001${project.value}`;
  effect(() => {
    const now = `${view.value}\u0001${project.value}`;
    if (now !== where) { where = now; sel.clear(); }
  });
  // Esc ends it, unless something open takes Esc first (a menu, a picker, a box, a dialog, the peek) or the person is typing.
  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || e.defaultPrevented || sel.size.value === 0 || view.value !== "work") return;
    const t = e.target;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    if (item.value || document.querySelector(OVERLAY)) return;
    e.preventDefault();
    e.stopPropagation();
    sel.clear();
  }, true);
  // A click outside the Work items page (and outside anything open over it, and the toast) ends it.
  document.addEventListener("click", (e) => {
    if (sel.size.value === 0) return;
    const t = e.target;
    if (!t || !t.isConnected || !t.closest) return;
    if (t.closest("#work, .toast, " + OVERLAY)) return;
    sel.clear();
  }, true);
}
