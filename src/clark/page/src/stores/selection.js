// The selection store (#195): what is picked on a list, in memory only (never saved, never in the address). The rules are in
// ../logic/selection.js; this wraps them in signals so any part of the page can read the selection and redraw when it changes.
// Work items has one (`workSelection`); another list (the Activity tab, for example) makes its own with createSelection().
//
// The API, which the bulk changes and the Activity tab build on:
//   sel.state        signal: { ids, anchor, cursor, all }        sel.ids  computed: the picked ids, in the order added
//   sel.size         computed: how many                         sel.has(id): picked or not
//   sel.anchor / sel.cursor   computed ids (or null)           sel.all  computed: "Select all N matching" is on
//   sel.live         signal: the polite words for a screen reader ("3 selected")
//   sel.note         signal: a short visible line, such as "2 left the selection" ("" for none)
//   sel.click(id, {add, range}, order)   sel.toggle(id)   sel.extend(step, order)   sel.selectAll(order)
//   sel.toggleGroup(groupIds)   sel.groupState(groupIds)   sel.selectMatching(matching)   sel.offersAllMatching(matching)
//   sel.moveCursor(id)   sel.sync(drawn, matching)   sel.clear()   sel.onChange(fn) -> unsubscribe
// `order`, `drawn`, `groupIds` and `matching` are arrays of ids; `order` and `drawn` are in the order drawn on the screen.
import { signal, computed } from "@preact/signals";
import * as S from "../logic/selection.js";

export function createSelection() {
  const state = signal(S.EMPTY);
  const live = signal("");
  const note = signal("");
  const listeners = new Set();
  let flip = false;
  // A polite region is read when its text changes: the same words twice in a row ("1 selected" for row A, then row B) would
  // be read once. A trailing space that comes and goes makes each one a change; a screen reader does not read the space.
  const speak = (words) => { flip = !flip; live.value = flip ? words : words + " "; };
  const ids = computed(() => state.value.ids);
  const size = computed(() => state.value.ids.length);

  function set(next, words) {
    const before = state.value;
    if (next === before) return;
    state.value = next;
    if (next.ids.length !== before.ids.length || next.ids.some((id, i) => id !== before.ids[i])) {
      speak(words || S.countWords(next.ids.length));
      if (!words) note.value = "";
      listeners.forEach((fn) => { try { fn(next, before); } catch (e) { /* a listener's fault never stops the selection */ } });
    }
  }

  return {
    state, ids, size, live, note,
    anchor: computed(() => state.value.anchor),
    cursor: computed(() => state.value.cursor),
    all: computed(() => state.value.all),
    has: (id) => state.value.ids.includes(id),
    click: (id, how, order) => set(S.click(state.value, id, how, order)),
    toggle: (id) => set(S.toggle(state.value, id)),
    extend: (step, order) => { const next = S.extend(state.value, step, order); set(next); return next.cursor; },
    selectAll: (order) => set(S.selectAll(state.value, order)),
    toggleGroup: (groupIds) => set(S.toggleGroup(state.value, groupIds)),
    groupState: (groupIds) => S.groupState(state.value, groupIds),
    selectMatching: (matching) => set(S.selectMatching(state.value, matching)),
    offersAllMatching: (matching) => S.offersAllMatching(state.value, matching),
    moveCursor: (id) => { if (state.value.cursor !== id) state.value = S.moveCursor(state.value, id); },
    sync(drawn, matching) {
      const r = S.sync(state.value, drawn, matching);
      if (r.left > 0 && r.sel.ids.length > 0) { note.value = S.leftWords(r.left); set(r.sel, `${S.leftWords(r.left)}. ${S.countWords(r.sel.ids.length)}`); }
      else if (r.left > 0) { note.value = S.leftWords(r.left); set(r.sel, `${S.leftWords(r.left)}. ${S.countWords(0)}`); }
      else set(r.sel);
      return r.left;
    },
    clear: () => { note.value = ""; set(S.EMPTY); },
    onChange: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
  };
}

export const workSelection = createSelection();
