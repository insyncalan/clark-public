// The appearance choice (#179, Settings › Personal and the profile menu): Light, Dark or System. One setting for this person on this
// computer, remembered in the browser (never in a project's data, as the section style is), applied at once as `data-theme` on the
// page: Light sets no attribute (the page's default), Dark sets "dark", and System sets "auto", which brand/tokens.css answers
// with the computer's own colour scheme, so it changes with the computer and needs no reload. Only Edit's parts import this file, so
// a published file never has it: it carries no `data-theme` and follows the viewer's own setting.
import { signal } from "@preact/signals";

export const MODES = ["system", "light", "dark"];                 // the ruled order: System first, the default
const KEY = "clark.appearance";
export const DEFAULT_MODE = "system";
export const valid = (v) => MODES.includes(v);

function remembered() {
  try { const v = localStorage.getItem(KEY); return valid(v) ? v : DEFAULT_MODE; } catch (e) { return DEFAULT_MODE; }
}

export const appearance = signal(remembered());

function paint(v) {
  try {
    const root = document.documentElement;
    if (v === "dark") root.dataset.theme = "dark";
    else if (v === "system") root.dataset.theme = "auto";
    else delete root.dataset.theme;
  } catch (e) { /* no document: nothing to paint */ }
}
paint(appearance.value);

/** Choose Light, Dark or System: it applies at once and is remembered. Anything else is ignored. */
export function setAppearance(v) {
  if (!valid(v)) return;
  appearance.value = v;
  paint(v);
  try { localStorage.setItem(KEY, v); } catch (e) { /* a private window: it applies now, and is not remembered */ }
}
