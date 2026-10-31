// The Work items list (#36, read only; #64a filters and Add): one project's actions, risks, issues, assumptions, dependencies and
// decisions from GET /api/data, one flat table: type, item, owner, due date in words, priority, status. The list rules are in
// ../workItems.js, the filter rules in ../filters.js. A filter change redraws the list region and the switches' words only.
// In Edit (#80), the Owner, Due, Priority and Status cells change in place (tools.Cell, edit/cells/): each opens its own picker.
// A click on the row anywhere else opens the item's peek, in View and in Edit.
// The keyboard (#80): the table is one tab stop, the row last focused (the first until then). Up and Down move between rows (in
// Edit, from a cell to the same cell of the next row), Home and End to the first and last row, Right and Left across the row's
// cells and back to the row. Enter on a row opens its peek; on a cell, Enter, Space or Alt+Down opens its picker.
// Selecting several (#195, on the page clark serves): a click selects the row, Cmd or Ctrl+click adds or removes it, Shift+click
// selects a range in the order drawn, a double click opens the peek; Shift+Up and Shift+Down extend from the cursor row, Space
// adds or removes it, Cmd or Ctrl+A selects every row shown; each group heading has a tick box. The rules are in pick.js.
import { signal } from "@preact/signals";
import { useEffect, useLayoutEffect } from "preact/hooks";
import { data, rows as allRows, filterState, setFilterState, filterNote, openPeek, mode, fromFile } from "../stores/report.js";
import { workSelection as sel } from "../stores/selection.js";
import { selecting, ownClick, noTextRange, pickClick, pickOpen, pickKeys, drawnOrder, installSelectionRules } from "./pick.js";
import { SelectBar, GroupTick } from "./SelectBar.jsx";
import { itemRows } from "../stores/work.js";
import { KIND_WORDS, sortRows, dueCell, pillOf, ownerOf, metaOf, isOpen, todayIso } from "../workItems.js";
import { applyFilters, chips, canClear, countText, clearAll, removeFilter, addPlan } from "../filters.js";
import { Switches, FilterBar } from "./WorkFilters.jsx";
import { NewTile } from "./NewTile.jsx";
import { Menu } from "./Menu.jsx";
import { Icon } from "./Icon.jsx";
import { work, setWork, announce, contextFor } from "../stores/work.js";
import { GROUPS, groupLabel, boardGroup, columnsFor, cellOf, isCollapsed, toggleCollapsed } from "../logic/board.js";

// Adding an item is not built yet (#65 to #67): the Add button says so, in words, and records what was asked for.
const asked = signal("");
function onAdd(kind) { asked.value = `Add ${kind || "item"} is coming with a later release. Nothing was added.`; }

function Owner({ name }) {
  const o = ownerOf(name);
  return o.initials
    ? <span class="who"><span class="av" aria-hidden="true">{o.initials}</span><span>{o.text}</span></span>
    : <span class="muted">{o.text}</span>;
}

const active = signal("");                      // the id of the row that is the table's one tab stop

// The arrow keys inside the table. Only a key on a row or on a cell's own button: never one meant for an open picker.
function keys(e, row) {
  const tr = e.currentTarget, t = e.target;
  const cell = t !== tr && t.matches && t.matches("[data-cell]") ? t : null;
  if (t !== tr && !cell) return;
  if (selecting() && pickKeys(e, row.id, (id) => focusRow(tr, id, cell), { space: !cell })) return;
  if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || (selecting() && e.shiftKey)) return;
  if (!cell && e.key === "Enter") { openPeek(row.id, "item"); return; }
  const rows = Array.from(tr.closest("table").querySelectorAll("tr[data-id]")), at = rows.indexOf(tr);   // across the groups, never a group heading
  const cells = Array.from(tr.querySelectorAll("[data-cell]")), c = cells.indexOf(cell);
  const field = cell ? cell.dataset.cell.slice(cell.dataset.cell.lastIndexOf(":") + 1) : "";
  const toRow = (j) => {
    const r = rows[Math.max(0, Math.min(rows.length - 1, j))];
    const same = field ? r.querySelector(`[data-cell$=":${field}"]`) : null;
    (same || r).focus();
  };
  if (e.key === "ArrowDown") toRow(at + 1);
  else if (e.key === "ArrowUp") toRow(at - 1);
  else if (e.key === "Home" && !cell) toRow(0);
  else if (e.key === "End" && !cell) toRow(rows.length - 1);
  else if (e.key === "ArrowRight") { if (cells[c + 1]) cells[c + 1].focus(); }
  else if (e.key === "ArrowLeft" && cell) (c > 0 ? cells[c - 1] : tr).focus();
  else return;
  e.preventDefault();
}

// Shift+Up or Shift+Down moved the cursor: the keyboard goes to that row (to the same cell when it was on one).
function focusRow(tr, id, cell) {
  const r = tr.closest("table").querySelector(`tr[data-id="${CSS.escape(id)}"]`);
  if (!r) return;
  const field = cell ? cell.dataset.cell.slice(cell.dataset.cell.lastIndexOf(":") + 1) : "";
  const same = field ? r.querySelector(`[data-cell$=":${field}"]`) : null;
  (same || r).focus();
}

function Row({ row, today, Cell, stop }) {
  const due = dueCell(row, today), pill = pillOf(row, today);
  const cell = (field, said, content) => (Cell ? <Cell row={row} field={field} said={said}>{content}</Cell> : content);
  const on = selecting(), picked = on && sel.ids.value.includes(row.id);
  const click = (e) => {
    if (!ownClick(e.target, e.currentTarget)) return;
    if (on) pickClick(e, row.id);
    else if (!String(window.getSelection()).length) openPeek(row.id, "item");
  };
  const dbl = (e) => { if (on && ownClick(e.target, e.currentTarget)) pickOpen(row.id); };
  return (
    <tr data-id={row.id} data-kind={row.kind} class={`${isOpen(row) ? "" : "done"}${picked ? " picked" : ""}`.trim()} tabIndex={stop ? 0 : -1} aria-label={on ? `Select or open ${row.id}` : `Open ${row.id}`}
      aria-selected={on ? (picked ? "true" : "false") : undefined}
      onFocusIn={() => { active.value = row.id; if (on) sel.moveCursor(row.id); }} onKeyDown={(e) => keys(e, row)} onMouseDown={on ? noTextRange : undefined} onClick={click} onDblClick={dbl}>
      <td class="c-type"><span class={`type k-${row.kind}`}>{KIND_WORDS[row.kind] || row.kind}</span></td>
      <td class="c-item">
        {picked ? <span class="tick" aria-hidden="true"><Icon name="check" /></span> : null}
        <span class="t">{row.title}</span>
        <span class="meta">{metaOf(row)}{row.client ? <span class="tag cl">Shown to client</span> : null}</span>
      </td>
      <td class="c-owner">{cell("owner", ownerOf(row.owner).text === "—" ? "none" : ownerOf(row.owner).text, <Owner name={row.owner} />)}</td>
      <td class="c-due">{cell("due", due.date === "—" ? "none" : due.date, <><span class="num">{due.date}</span>{due.words ? <span class={`due-l${due.tone ? " " + due.tone : ""}`}>{due.words}</span> : null}</>)}</td>
      <td class="c-prio">{cell("priority", row.priority || "none", row.priority || <span class="muted">{"—"}</span>)}</td>
      <td class="c-status">{cell("status", row.status, <span class={`pill ${pill.class}`}>{pill.text}</span>)}</td>
    </tr>
  );
}

// The table, in groups (Group by): a heading row with the name and the count that opens and shuts the group, then its rows.
// "Nothing" is the flat list. A group with no rows is not drawn here (the board draws every column).
// The table's one tab stop (#80) is the row last focused while it is drawn, else the first row drawn.
function Table({ rows, today, type, Cell }) {
  const st = work.value, g = st.group, on = selecting(), grid = on ? { role: "grid", "aria-multiselectable": "true", "aria-label": "Work items" } : {};
  const head = <thead><tr><th class="c-type">Type</th><th class="c-item">Item</th><th class="c-owner">Owner</th><th class="c-due">Due</th><th class="c-prio">Priority</th><th class="c-status">Status</th></tr></thead>;
  const stopOf = (drawn) => (drawn.some((r) => r.id === active.value) ? active.value : drawn.length ? drawn[0].id : "");
  const row = (r, stop) => <Row key={r.id} row={r} today={today} Cell={Cell} stop={r.id === stop} />;
  if (g === "nothing") { const flat = sortRows(rows, today), stop = stopOf(flat); return <table class="items" {...grid}>{head}<tbody>{flat.map((r) => row(r, stop))}</tbody></table>; }
  const ctx = contextFor(today, type);
  const groups = columnsFor(g, rows, ctx).map((c) => ({ ...c, rows: sortRows(rows.filter((r) => cellOf(g, r, ctx) === c.key), today) })).filter((c) => c.rows.length > 0)
    .map((c) => ({ ...c, shut: isCollapsed(st, g, c.key) }));
  const stop = stopOf(groups.flatMap((c) => (c.shut ? [] : c.rows)));
  return (
    <table class="items grouped" {...grid}>
      {head}
      {groups.map((c) => {
        const shut = c.shut;
        return (
          <tbody key={c.key} data-group={c.key}>
            <tr class="grp"><th colspan="6" scope="colgroup">
              {on ? <GroupTick ids={c.rows.map((r) => r.id)} label={c.label} shut={shut} /> : null}
              <button type="button" class="grp-b" aria-expanded={shut ? "false" : "true"} onClick={() => setWork(toggleCollapsed(work.value, g, c.key))}>
                <Icon name="chevdown" cls={shut ? "turn" : ""} /><span class="gl">{c.label}</span><span class="gc num">{c.rows.length}</span>
              </button>
            </th></tr>
            {shut ? null : c.rows.map((r) => row(r, stop))}
          </tbody>
        );
      })}
    </table>
  );
}

// Group by, the swimlanes' neighbour: a menu button reading "Group by: Status". On the board "Nothing" is not offered.
function GroupBy({ board }) {
  const g = work.value.group, shown = board ? boardGroup(g) : g;
  return (
    <Menu label={`Group by: ${groupLabel(shown)}`} ariaLabel={`Group by: ${groupLabel(shown)}`} id="group-by" btnCls="btn gb" menuLabel="Group by" left
      items={GROUPS.filter((x) => !board || x.id !== "nothing").map((x) => ({ id: x.id, name: x.label }))}
      onPick={(id) => { const lane = work.value.lane; setWork({ group: id, lane: lane === id ? null : lane }); announce.value = `Grouped by ${groupLabel(id)}.`; }} />
  );
}

// The part a filter change redraws: the count, the chips with Clear all, and the table or the board.
function List({ Board, Cell, Bulk }) {
  const st = filterState.value, today = todayIso();
  const filtered = applyFilters(itemRows.value, st, today);
  const cs = chips(st);
  const clear = () => setFilterState(clearAll());
  const board = !!Board && work.value.view === "board";
  const matching = filtered.map((r) => r.id);
  // After each draw: a row no longer drawn (filtered out, its group collapsed) leaves the selection, unless "all matching" is on.
  useLayoutEffect(() => { if (selecting()) sel.sync(drawnOrder(), matching); });
  return (
    <div id="work-list">
      {selecting() ? <SelectBar sel={sel} matching={matching} actions={Bulk ? <Bulk.Actions /> : null} /> : null}
      {Bulk ? <Bulk.Layer /> : null}
      <div class="factive">
        <span id="work-count" class="num">{countText(filtered.length, st.mode)}</span>
        {cs.map((c) => (
          <span class="fchip" key={c.field} data-chip={c.field}>{c.text}
            <button type="button" data-fx={c.field} aria-label={`Remove the ${c.name} filter`} onClick={() => setFilterState(removeFilter(filterState.value, c.field))}>{"×"}</button>
          </span>
        ))}
        {canClear(st) ? <button type="button" class="link" id="clearAll" onClick={clear}>Clear all</button> : null}
      </div>
      {filtered.length === 0
        ? <div class="empty"><p class="muted">No items match these filters.</p>{canClear(st) ? <button type="button" class="btn" id="clearAll2" onClick={clear}>Clear all</button> : null}</div>
        : board ? <Board rows={filtered} today={today} type={st.type} /> : <Table rows={filtered} today={today} type={st.type} Cell={Cell} />}
    </div>
  );
}

export function WorkItems({ tools }) {
  useEffect(() => { if (selecting()) installSelectionRules(); if (tools && tools.Bulk) tools.Bulk.install(); }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  const d = data.value, plan = addPlan(filterState.value.type), Board = tools && tools.Board;
  const Cell = tools && tools.Cell && mode.value === "edit" && !fromFile.value ? tools.Cell : null;
  const board = !!Board && work.value.view === "board";
  return (
    <section class="frame work" id="work">
      <p class="crumbs">{d.project.name}</p>
      <div class="head">
        <h1>Work items</h1>
        {tools ? <NewTile word={plan.word} kind={plan.kind} items={plan.menu} onAdd={onAdd} /> : null}   {/* a published file is read only: no Add (#204) */}
      </div>
      <p class="muted note" role="status" id="work-note">{filterNote.value || asked.value}</p>
      <p class="sr" role="status" aria-live="polite" id="work-live">{announce.value}</p>
      {selecting() ? <p class="sr" role="status" aria-live="polite" id="sel-live">{sel.live.value}</p> : null}
      {allRows.value.length === 0
        ? <p class="muted">{tools ? `This project has no work items yet. Use ${plan.word} to add the first.` : "This report has no work items."}</p>
        : <>
            <Switches><GroupBy board={board} />{tools && tools.LayoutSwitch ? <tools.LayoutSwitch /> : null}</Switches>
            <FilterBar />
            <List Board={Board} Cell={Cell} Bulk={tools && tools.Bulk} />
          </>}
    </section>
  );
}
