// The selection bar (#195) above the Work items table or board, shown while two or more are picked: "N selected", Select all N
// matching (when fewer than the filters show), any actions given to it (the bulk changes build on this: `actions`), and the X
// that clears the selection. Under it, a short line when rows left the selection ("3 left the selection").
// GroupTick is a group heading's tick box: checked, unchecked or part-checked, and off while the group is collapsed.
import { useLayoutEffect, useRef } from "preact/hooks";
import { Icon } from "./Icon.jsx";
import { countWords, matchingWords } from "../logic/selection.js";
import { workSelection } from "../stores/selection.js";

export function SelectBar({ sel, matching, actions }) {
  const n = sel.size.value, note = sel.note.value;
  const offer = sel.offersAllMatching(matching);
  return (
    <>
      {n >= 2 ? (
        <div class="selbar" role="region" aria-label="Selection" id="sel-bar">
          <span class="sb-n num" id="sel-count">{countWords(n)}</span>
          {offer ? <button type="button" class="link" id="sel-all" onClick={() => sel.selectMatching(matching)}>{matchingWords(matching.length)}</button> : null}
          {actions || null}
          <button type="button" class="bib sb-x" id="sel-clear" aria-label="Clear the selection" data-tip="Clear the selection (Esc)" onClick={() => sel.clear()}>
            <Icon name="x" />
          </button>
        </div>
      ) : null}
      {note ? <p class="muted sel-note" id="sel-note">{note}</p> : null}
    </>
  );
}

export function GroupTick({ ids, label, shut, sel: given }) {
  const box = useRef(null);
  const s = given || workSelection;
  const state = s.groupState(ids);
  void s.ids.value;                                          // redraw when the selection changes
  useLayoutEffect(() => { if (box.current) box.current.indeterminate = state === "mixed"; });
  const what = `${label}, ${ids.length === 1 ? "1 item" : ids.length + " items"}`;
  return (
    <label class="gtick-hit" onClick={(e) => e.stopPropagation()}>
    <input type="checkbox" ref={box} class="gtick" data-gtick={label} checked={state === "checked"} disabled={shut}
      aria-label={shut ? `Select ${what}. Open the group first` : `Select ${what}`}
      title={shut ? "Open the group to select its items" : undefined}
      onClick={(e) => e.stopPropagation()}
      onChange={() => { if (!shut) s.toggleGroup(ids); }} />
    </label>
  );
}
