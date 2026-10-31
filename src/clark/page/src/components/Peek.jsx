// The peek (#42a): one work item's or milestone's fields beside the list. Read only in View and in a published file: fields and
// nothing else (no history, no words box, no /api/ text). `tools.Words`, `tools.WordsButton`, `tools.PeekTabs` and
// `tools.PeekActivity` (Details and Activity, #42) are the Edit part.
// The address holds which item is open (router.js, #63); Previous and Next replace that entry, Esc and Close go through
// closePeek(). The width is dragged from the left edge (keys too), double-click resets it.
import { useEffect, useRef } from "preact/hooks";
import { data, rows, peek, openPeek, closePeek, mode, fromFile } from "../stores/report.js";
import { width, wide, setWidth, resetWidth, MIN, peekTab } from "../stores/peekState.js";
import { KIND_WORDS, dueCell, pillOf, ownerOf, showDate, todayIso } from "../workItems.js";
import { itemIds, milestoneIds, around } from "../peek/list.js";
import { Icon } from "./Icon.jsx";
import { wordsOpen, flashed } from "../stores/wordsState.js";

const DASH = "—";
const text = (v) => (v === null || v === undefined || v === "" ? DASH : String(v));

const ROW_OF = { owner: "owner", made_by: "owner", due_date: "due", needed_by: "due", date: "due", priority: "priority", status: "status" };

function Row({ name, children, ref_, key_ }) {          // key_: which field this row shows, so it can flash when that field changes
  const f = flashed.value;
  const hit = !!(f && key_ && f.list.some((e) => e.ref === ref_ && ROW_OF[e.field] === key_));
  return <div class={`pk-row${hit ? " flash" : ""}`} data-row={key_ || undefined} data-flash={hit ? "1" : undefined}><dt>{name}</dt><dd>{children}{hit ? <span class="tag chg">Changed</span> : null}</dd></div>;
}

function ItemFields({ row, editing }) {
  const today = todayIso(), due = dueCell(row, today), pill = pillOf(row, today), who = ownerOf(row.owner);
  return (
    <dl class="pk-fields">
      <Row name="Type">{KIND_WORDS[row.kind] || row.kind}</Row>
      <Row key_="owner" ref_={row.id} name={row.kind === "decision" ? "Decision by" : "Owner"}>{who.text}</Row>
      <Row key_="due" ref_={row.id} name={row.kind === "decision" && row.status === "Pending" ? "Needed by" : row.kind === "decision" ? "Date" : "Due"}>
        {due.date}{due.words ? <span class={`due-l${due.tone ? " " + due.tone : ""}`}> {due.words}</span> : null}
      </Row>
      {row.kind !== "decision" ? <Row key_="priority" ref_={row.id} name="Priority">{text(row.priority)}</Row> : null}
      <Row key_="status" ref_={row.id} name="Status"><span class={`pill ${pill.class}`}>{pill.text}</span></Row>
      <Row name="Workstream">{text(row.workstream)}</Row>
      <Row name="Milestone">{text(row.milestone)}</Row>
      <Row name="Use case">{text(row.uc)}</Row>
      {editing ? <Row name="Shown to client">{row.client ? "Yes" : "No"}</Row> : null}
    </dl>
  );
}

function MilestoneFields({ m }) {
  return (
    <dl class="pk-fields">
      <Row name="Owner">{ownerOf(m.owner).text}</Row>
      <Row name="Agreed date">{showDate(m.baseline_date)}</Row>
      <Row name="Forecast date">{showDate(m.forecast_date)}</Row>
      <Row name="Status">{text(m.state || m.status)}</Row>
      <Row name="Workstream">{text(m.workstream)}</Row>
    </dl>
  );
}

// The edge you drag. Keys work too: Left widens, Right narrows, Home resets. Double-click resets.
function Edge() {
  const start = useRef(null);
  const down = (e) => { start.current = true; try { e.currentTarget.setPointerCapture(e.pointerId); } catch (err) { /* no capture: the move still follows */ } e.preventDefault(); };
  const move = (e) => { if (start.current) setWidth(document.documentElement.clientWidth - e.clientX); };
  const up = () => { start.current = null; };
  const key = (e) => {
    const step = e.shiftKey ? 80 : 20;
    if (e.key === "ArrowLeft") setWidth(width.value + step); else if (e.key === "ArrowRight") setWidth(width.value - step);
    else if (e.key === "Home") resetWidth(); else return;
    e.preventDefault();
  };
  return <div class="pk-edge" role="separator" aria-orientation="vertical" aria-label="Peek width" aria-valuemin={MIN} aria-valuenow={width.value}
    tabIndex={0} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onDblClick={resetWidth} onKeyDown={key} />;
}

export function Peek({ tools }) {
  const p = peek.value;
  const box = useRef(null), back = useRef(null);
  const editing = !!tools && !fromFile.value && mode.value === "edit";
  const Words = editing && tools.Words, WordsBtn = editing && tools.WordsButton;
  const Tabs = editing && tools.PeekTabs, Activity = editing && tools.PeekActivity;
  const showActivity = !!(Tabs && Activity && peekTab.value === "activity");
  // Focus goes in when the peek opens and back to where it was when it closes.
  useEffect(() => {
    if (!p) return undefined;
    back.current = document.activeElement;
    const close = box.current && box.current.querySelector("[data-pk-close]");
    if (close) close.focus();
    return () => { wordsOpen.value = false; const el = back.current; back.current = null; if (el && el.isConnected && el.focus) el.focus(); };
  }, [!!p]);                                              // eslint-disable-line react-hooks/exhaustive-deps
  // Esc closes the words box first, then the peek; two slashes outside a field open the words box (Edit only).
  useEffect(() => {
    if (!p) return undefined;
    let last = 0;
    const onKey = (e) => {
      if (e.defaultPrevented || e.isComposing) return;
      if (e.key === "Escape") {
        if (document.querySelector("[role=menu]")) return;
        e.preventDefault();
        if (wordsOpen.value) wordsOpen.value = false; else closePeek();
        return;
      }
      const t = e.target, inField = t && t.nodeType === 1 && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
      if (e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey && !inField && Words) {
        if (last && performance.now() - last < 1000) { e.preventDefault(); last = 0; wordsOpen.value = true; } else last = performance.now() || 1;
      } else if (e.key !== "Shift") last = 0;
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [p && p.id, !!Words]);                               // eslint-disable-line react-hooks/exhaustive-deps
  if (!p || !data.value) return null;
  const milestone = p.kind === "milestone";
  const row = milestone ? null : rows.value.find((r) => r.id === p.id);
  const m = milestone ? (data.value.milestones || []).find((x) => x.id === p.id) : null;
  if (!row && !m) return null;
  const near = around(milestone ? milestoneIds() : itemIds(), p.id);
  const go = (id) => id && openPeek(id, p.kind);
  const title = row ? row.title : m.name;
  return (
    <aside class={`peek${wide.value ? " wide" : ""}`} id="peek" ref={box} aria-label={`${p.id} details`} style={wide.value ? "" : `width:${Math.min(width.value, document.documentElement.clientWidth)}px`} data-peek={p.id}>
      <Edge />
      <div class="pk-bar">
        <button type="button" class="pkp-btn" data-pk-prev title="Previous item" aria-label="Previous item" disabled={!near.prev} onClick={() => go(near.prev)}><Icon name="chevleft" /></button>
        <button type="button" class="pkp-btn" data-pk-next title="Next item" aria-label="Next item" disabled={!near.next} onClick={() => go(near.next)}><Icon name="chevright" /></button>
        <span class="pk-id num">{p.id}</span>
        <span class="pk-sp" />
        {WordsBtn ? <WordsBtn /> : null}
        <button type="button" class="pkp-btn" data-pk-wide aria-pressed={wide.value} title={wide.value ? "Return the panel to its usual width" : "Make this panel fill the screen"} aria-label={wide.value ? "Return the panel to its usual width" : "Make this panel fill the screen"} onClick={() => { wide.value = !wide.value; }}><Icon name="expand" /></button>
        <button type="button" class="pkp-btn" data-pk-close title="Close this panel" aria-label="Close this panel" onClick={closePeek}><Icon name="x" /></button>
      </div>
      <h2 class="pk-title">{title}</h2>
      {Tabs ? <Tabs /> : null}
      {showActivity ? <Activity key={p.id} id={p.id} />
        : <div role={Tabs ? "tabpanel" : undefined} id={Tabs ? "pk-panel-details" : undefined} aria-labelledby={Tabs ? "pk-tab-details" : undefined}>
          {row ? <ItemFields row={row} editing={editing} /> : <MilestoneFields m={m} />}
        </div>}
      {Words && wordsOpen.value && row ? <Words key={row.id} row={row} /> : null}
    </aside>
  );
}
