import { ADD_EVENT } from "./addSection.js";
// The way in to the Add a section box (#96). #101's gutter "+" and the section menu's "Add a section below…" call
// `openAddSection(after, opener)`; anything else may dispatch the same event: a cancelable CustomEvent on the document that bubbles (the box listens on the document and calls preventDefault() to claim it). Nothing here draws or sends.
// `after` is the id of the section the new one goes below (null: at the end); `opener` is the element that had focus, so Esc and
// Cancel can give it back. The box (AddDialog.jsx) is mounted in Edit only, so in View the event does nothing.
// One name for the event: addSection.js (the gutter's askToAdd) owns the string and this file re-exports it, so the two cannot drift.
export const ADD_SECTION_EVENT = ADD_EVENT;

export function openAddSection(after, opener) {
  const e = new CustomEvent(ADD_SECTION_EVENT, { detail: { after: after === undefined ? null : after, opener: opener || document.activeElement || null }, cancelable: true, bubbles: true });
  document.dispatchEvent(e);
  return e;
}
