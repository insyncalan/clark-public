// #80: a Work items table cell (owner, due, priority, status) that changes in place, in Edit only. The cell's own content is a
// button; a click, Enter or Space opens that field's picker (Alt+Down too; a plain Down moves to the next row, WorkItems.jsx). A pick is one change through clark (one step,
// with Undo in the toast); Esc or a click away leaves it as it was. The button stops its click there, so a click on a cell
// never opens the peek; a click anywhere else on the row still does. One picker is open at a time. The Status cell shows the
// item's own status (itemEdit.statusPill), the same word as its picker and its toast. A RAID item's Priority is not a picker: its
// tooltip says it is set from impact and likelihood (a decision has none, and shows a dash).
import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import { data } from "../../stores/report.js";
import { changeCell, say } from "../../stores/changes.js";
import { workSelection } from "../../stores/selection.js";
import { itemRows } from "../../stores/work.js";
import { cellPlan } from "../bulkLogic.js";
import { ask, runBulk } from "../Bulk.jsx";
import { todayIso } from "../../workItems.js";
import { canPick, changeFor, fieldName, people, statusPill, tableOf, whyFixed } from "../itemEdit.js";
import { OwnerPick } from "./OwnerPick.jsx";
import { DuePick } from "./DuePick.jsx";
import { PriorityPick } from "./PriorityPick.jsx";
import { StatusPick } from "./StatusPick.jsx";

export const PICKERS = { owner: OwnerPick, due: DuePick, priority: PriorityPick, status: StatusPick };
export const openCell = signal("");                      // "<id>:<field>" of the open picker, or ""

const key = (row, field) => `${row.id}:${field}`;

// After a change has been drawn the row may have moved (the list is sorted by due date): focus goes back to its cell if it was lost.
function refocus(k) {
  setTimeout(() => {
    const now = document.activeElement;
    if (now && now !== document.body && now.isConnected) return;
    const el = document.querySelector(`[data-cell="${CSS.escape(k)}"]`);
    if (el) el.focus();
  }, 0);
}

export function Cell({ row, field, said, children }) {
  const button = useRef(null);
  if (!canPick(row, field)) {
    const why = whyFixed(row, field);                       // a RAID item's priority: say why a click does nothing
    return why ? <span class="cell-fixed" data-fixed={`${row.id}:${field}`} title={why}>{children}</span> : children;
  }
  const k = key(row, field), open = openCell.value === k, Picker = PICKERS[field];
  if (field === "status") { const p = statusPill(row); children = <span class={`pill ${p.class}`}>{p.text}</span>; }   // the picker's own word
  const close = (back) => { if (openCell.value === k) openCell.value = ""; if (back && button.current) button.current.focus(); };
  const pick = (value) => {
    // #196: on a row that is one of two or more selected, the pick changes that field of every selected row, and says so first.
    const chosen = workSelection.ids.value, plan = chosen.length >= 2 ? cellPlan(row.id, field, itemRows.value.filter((r) => chosen.includes(r.id))) : null;
    if (plan && plan.why) { if (field === "owner") return plan.why; close(true); say("note", plan.why); return ""; }
    if (plan) {
      if (field === "owner" && !String(value == null ? "" : value).trim()) return "An owner can't be blank. Type a name, or TBC if no one is known yet.";
      close(true);
      ask(plan.question, () => runBulk(plan.table, plan.ids, plan.id, value, { place: "cell" }));
      return "";
    }
    const today = todayIso();
    const c = changeFor(row, field, value, today);
    if (c && c.error) return c.error;
    close(true);
    if (c) changeCell(tableOf(row), row.id, c.changes, { text: c.words, back: c.back, always: row.kind === "decision" && field === "status" && value === "Made" }).then(() => refocus(k));
    return "";
  };
  const toggle = () => { openCell.value = open ? "" : k; };
  const down = (e) => {
    if (e.key === "Escape" && open) { e.preventDefault(); e.stopPropagation(); close(true); }
    else if (e.key === "ArrowDown" && e.altKey && !open) { e.preventDefault(); openCell.value = k; }
  };
  return (
    <>
      <button type="button" class="cell-pick" ref={button} tabIndex={-1} data-edit-only data-cell={k} aria-haspopup={field === "status" || field === "priority" ? "menu" : "dialog"}
        aria-expanded={open ? "true" : "false"} aria-label={`${fieldName(row, field)} of ${row.id}: ${said}. Change`}
        onClick={(e) => { e.stopPropagation(); toggle(); }} onKeyDown={down}>{children}</button>
      {open ? <Picker row={row} anchor={button} today={todayIso()} names={field === "owner" ? people(data.value) : undefined} onPick={pick} onClose={close} /> : null}
    </>
  );
}
