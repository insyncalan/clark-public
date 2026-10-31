// The Single-key shortcuts switch (#193, Settings › Personal). On by default. Off, no key that works when pressed alone does anything:
// V and E, ? and / today, and every letter key added later (each one asks singleKeysOn() before it acts). Space, Esc, Enter, Tab, the
// arrow keys and anything with Cmd, Ctrl or Alt are not single-key shortcuts and never ask. It is one setting for this person on this
// computer, remembered in the browser like the section style (never in the project's data), and read live: no reload.
import { signal } from "@preact/signals";

const KEY = "clark.single-keys";

function remembered() {
  try { return localStorage.getItem(KEY) !== "off"; } catch (e) { return true; }      // nothing stored, or no storage: on
}

export const singleKeys = signal(remembered());

/** Whether a key pressed alone may act. Read live, so a change in Settings counts at once. */
export function singleKeysOn() { return singleKeys.value !== false; }

/** The words for a shortcut in a tooltip or a hint: "View (V)" when on, "View" when off. */
export function keyHint(label, key) { return singleKeysOn() ? `${label} (${key})` : label; }

/** Turn the switch (Settings › Personal): it applies at once and is remembered. */
export function setSingleKeys(on) {
  singleKeys.value = !!on;
  try { localStorage.setItem(KEY, on ? "on" : "off"); } catch (e) { /* a private window: it applies now, and is not remembered */ }
}
