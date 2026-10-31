// What Hand over (#199) keeps in memory: whether pick mode is on, the name typed in "Hand over to", and the items ticked. Never saved
// and never in the address. The ticks are a selection of their own (createSelection, #195), apart from the Work items selection, so
// the row keys of that selection stay off while this is on. The rules are in ../logic/handOver.js; the screen is edit/HandOver.jsx.
import { signal } from "@preact/signals";
import { createSelection } from "./selection.js";

/** null when pick mode is off; else { to: the name typed so far }. */
export const handOver = signal(null);
/** True while pick mode is on: the Work items table then ticks instead of selecting or opening. */
export const handing = () => handOver.value !== null;
/** The items ticked. */
export const ticks = createSelection();
