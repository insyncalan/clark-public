// Cmd or Ctrl+Z (#197): in Edit, on the Dashboard, Work items and Milestones, it undoes the last change, the same step as the
// toast's Undo (stores/changes.js, undoLast). With nothing to undo it says so. Focus in a box, a rich-text field (which keeps its own
// undo), a dialog or a menu leaves the key to that; with Shift (redo) or Alt, or a held key, it is not taken either.
import { view, data, mode, fromFile } from "../stores/report.js";
import { undoLast } from "../stores/changes.js";

const FIELD = /^(INPUT|TEXTAREA|SELECT)$/;
const OWN = "[role=textbox],[role=combobox],[role=listbox],[role=menu],[role=dialog],[role=alertdialog],dialog";
const OPEN = "dialog[open],[role=dialog],[role=alertdialog],[role=menu],[role=listbox]";
const PAGES = ["dashboard", "work", "milestones"];

function busy(el) {
  return !!el && el.nodeType === 1 && (el.isContentEditable || FIELD.test(el.tagName) || !!el.closest(OWN));
}

/** Whether a keydown is the undo key that clark should take here. Pure apart from reading the page's state. */
export function isUndoKey(e) {
  if (!e || (e.key !== "z" && e.key !== "Z" && e.code !== "KeyZ")) return false;
  if (!(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey || e.repeat || e.isComposing || e.defaultPrevented) return false;
  if (fromFile.value || !data.value || mode.value !== "edit" || !PAGES.includes(view.value)) return false;
  if (busy(document.activeElement) || busy(e.target)) return false;
  return !document.querySelector(OPEN);
}

/** Handle one keydown: undo the last change when it is the undo key here. Returns whether it did. */
export function undoKey(e) {
  if (!isUndoKey(e)) return false;
  e.preventDefault();
  undoLast();
  return true;
}
