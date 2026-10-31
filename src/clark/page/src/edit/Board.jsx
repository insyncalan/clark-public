// The Work items board (#68) and its full screen (#81): columns for Group by, one level of swimlanes, cards, and moving a card by
// dragging it or by its "Move to..." menu. Spec: docs/handoff/design-68-81-board.md. Every rule (which column a card is in, what a
// move asks the server for, why it is refused) is in ../logic/board.js; this file draws it and sends what moveFor gives, through
// stores/changes.js. It is an Edit part (edit/index.js): the published page has no board. Cards move only in Edit; in View they
// can be read and opened. Nothing here removes an item: a card moves, and closing is a status.
import { useEffect, useRef, useState } from "preact/hooks";
import { mode, item, openPeek } from "../stores/report.js";
import { work, setWork, full, announce, contextFor } from "../stores/work.js";
import { changeItem, say } from "../stores/changes.js";
import { build, moveFor, dateMove, movedWords, boardGroup, isCollapsed, toggleCollapsed, groupLabel, LANE_GROUPS } from "../logic/board.js";
import { createDrag } from "../logic/dragCore.js";
import { Menu, MenuPanel } from "../components/Menu.jsx";
import { Icon } from "../components/Icon.jsx";
import { GroupTick } from "../components/SelectBar.jsx";
import { workSelection as pickSel } from "../stores/selection.js";
import { ownClick, noTextRange, pickClick, pickOpen, pickKeys } from "../components/pick.js";

const TONED = ["status", "due", "priority"];             // the groups whose columns carry their state's colour
const LANE_WORDS = { workstream: "Workstream", type: "Type" };

// The peek is #42's. Until it claims this, a click on a card puts the item in the address (the router's `item`) and tells the page.
export function openCard(id) {
  openPeek(id, "item");
  try { window.dispatchEvent(new CustomEvent("clark:open-peek", { detail: { id } })); } catch (e) { /* the address has it */ }
}

const cellKey = (lane, col) => `${lane == null ? "" : lane}\u0001${col}`;

function Eye() {
  return <span class="eye" title="Shown to the client"><Icon name="eye" /><span class="sr">Shown to the client</span></span>;
}

// A card is picked like a table row (#195): a click selects it, Cmd or Ctrl+click adds or removes it, Shift+click a range in the
// order drawn, a double click (or Enter) opens the peek; Space adds or removes it, Shift+Up and Shift+Down extend, Cmd or Ctrl+A
// selects every card shown.
function Card({ card, editing, selected, picked, dragging, ask, menu, onOpen, onPick, onMenu, children }) {
  const label = `${card.id} ${card.title}, ${card.state.text}${card.due.words ? ", " + card.due.words.toLowerCase() : ""}${picked ? ", selected" : ""}`;
  const focusCard = (id) => { const el = document.querySelector(`article[data-id="${CSS.escape(id)}"] .bc-main`); if (el) el.focus(); };
  return (
    <article class={`bcard k-${card.typeClass.slice(2)}${selected ? " sel" : ""}${picked ? " picked" : ""}${dragging ? " drag" : ""}${card.open ? "" : " done"}`} data-id={card.id} data-kind={card.typeClass.slice(2)}>
      <div class="bc-main" role="button" tabIndex={0} aria-label={label} onMouseDown={noTextRange}
        onClick={(e) => { if (ownClick(e.target, e.currentTarget)) onPick(e, card.id); }}
        onDblClick={(e) => { if (ownClick(e.target, e.currentTarget)) onOpen(card.id, true); }}
        onFocus={() => pickSel.moveCursor(card.id)}
        onKeyDown={(e) => {
          if (e.target !== e.currentTarget) return;
          if (e.key === "Enter" && !e.shiftKey && !e.metaKey && !e.ctrlKey && !e.altKey) { e.preventDefault(); onOpen(card.id); return; }
          pickKeys(e, card.id, focusCard);
        }}>
        <div class="bc-top"><span class={`type ${card.typeClass}`}>{card.type}</span><span class="bc-id num">{card.id}</span>{card.client ? <Eye /> : null}</div>
        <div class="bc-title">{picked ? <span class="tick" aria-hidden="true"><Icon name="check" /></span> : null}{card.title}</div>
        <div class="bc-foot">
          {card.initials ? <span class="av" title={card.owner} aria-hidden="true">{card.initials}</span> : null}
          {card.due.words ? <span class={`due-l${card.due.tone ? " " + card.due.tone : ""}`}>{card.due.words}</span> : null}
          <span class={`pill ${card.state.class}`}>{card.state.text}</span>
        </div>
      </div>
      {editing ? (
        <span class="dd bmv">
          <button type="button" class="bc-move" aria-label={`Move ${card.id} to…`} aria-haspopup="menu" aria-expanded={menu ? "true" : "false"} data-move={card.id} onClick={() => onMenu(card.id)}>
            <Icon name="dots" />
          </button>
          {children}
        </span>
      ) : null}
      {ask}
    </article>
  );
}

// Esc closes a small panel from wherever focus is (once, and the page's other Esc handlers leave it alone).
function useEscape(close) {
  const ref = useRef(close); ref.current = close;
  useEffect(() => {
    const esc = (e) => { if (e.key === "Escape" && !e.defaultPrevented) { e.preventDefault(); e.stopPropagation(); ref.current(); } };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, []);
}

// A date to choose for Due, never before today (the page's rule; the server takes any real day so the peek can enter an old one).
function DatePicker({ ask, today, onSet, onCancel }) {
  const input = useRef(null), [error, setError] = useState("");
  useEscape(onCancel);
  useEffect(() => { if (input.current) input.current.focus({ preventScroll: true }); }, []);
  const submit = () => { const r = onSet(input.current.value); if (r) setError(r); };
  return (
    <div class="dpick" role="dialog" aria-label="Pick a due date" onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onCancel(); } else if (e.key === "Enter" && e.target === input.current) { e.preventDefault(); submit(); } }}>
      <label>Due date<input type="date" ref={input} min={today} value={ask.move.needsDate.suggested} onInput={() => setError("")} /></label>
      {error ? <p class="dp-err" role="alert">{error}</p> : null}
      <div class="dp-act"><button type="button" class="btn sm" data-set onClick={submit}>Set date</button><button type="button" class="btn sm" data-cancel onClick={onCancel}>Cancel</button></div>
    </div>
  );
}

// A decision dragged to Made is final (a made decision is replaced by a new one, never put back), so it asks first.
function Confirm({ onYes, onCancel }) {
  const yes = useRef(null);
  useEscape(onCancel);
  useEffect(() => { if (yes.current) yes.current.focus({ preventScroll: true }); }, []);
  return (
    <div class="dpick" role="dialog" aria-label="Record this decision" onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onCancel(); } }}>
      <p>Record this decision as made today? A made decision can't go back to Pending. If it changes, record a new one.</p>
      <div class="dp-act"><button type="button" class="btn sm" data-yes ref={yes} onClick={onYes}>Record it</button><button type="button" class="btn sm" data-cancel onClick={onCancel}>Cancel</button></div>
    </div>
  );
}

// The table or board icon switch (remembered), shown only where there is a board to show (the page clark serves).
export function LayoutSwitch() {
  const set = (view) => { setWork({ view }); announce.value = view === "board" ? `Showing the board, grouped by ${groupLabel(boardGroup(work.value.group))}.` : "Showing the table."; };
  const v = work.value.view;
  return (
    <div class="seg icons" role="group" aria-label="Layout">
      {["table", "board"].map((k) => (
        <button type="button" key={k} class="bib" data-layout={k} aria-pressed={v === k ? "true" : "false"} aria-label={k === "table" ? "Table" : "Board"} data-tip={k === "table" ? "Table" : "Board"} onClick={() => set(k)}>
          <Icon name={k} />
        </button>
      ))}
    </div>
  );
}

// What an empty Move to menu says. A made or withdrawn decision is changed only by a new one; other cards by opening them.
const noMove = (row) => row && row.kind === "decision" && (row.status === "Made" || row.status === "Withdrawn")
  ? "This card can't move on this board. Record a new decision to change it."
  : "This card can't move on this board. Open it to change its details.";

export function Board({ rows, today, type }) {
  const st = work.value, g = boardGroup(st.group), editing = mode.value === "edit";
  const ctx = contextFor(today, type);
  const b = build(rows, { group: g, lane: st.lane, ctx });
  const byId = Object.fromEntries(rows.map((r) => [r.id, r]));
  const [menu, setMenu] = useState(null);            // the id of the card whose Move to... is open
  const [ask, setAsk] = useState(null);              // { kind: "date" | "confirm", id, move, row }
  const [dragId, setDragId] = useState(null);
  const [over, setOver] = useState("");
  const pos = useRef(null), frame = useRef(0), listening = useRef(null);
  const live = useRef({}), ghost = useRef(null), endedAt = useRef(-1e9), fsBtn = useRef(null), box = useRef(null);
  const peeked = item.value;

  const from = (id, laneKey, colKey) => ({ group: g, key: colKey, lane: b.lane ? { group: b.lane, key: laneKey } : null });
  const to = (laneKey, colKey) => from(null, laneKey, colKey);

  // Send a move, or say why it can't be made. The refusal is the logic's own words; the server checks everything again.
  function attempt(row, fromCell, toCell, afterDate) {
    const m = moveFor(row, fromCell, toCell, ctx);
    if (m.ok && m.noop) return;
    if (!m.ok) { say("note", m.message); return; }
    if (m.needsDate && !afterDate) { setAsk({ kind: "date", id: row.id, move: m, row }); return; }
    if (row.kind === "decision" && m.request.changes.status === "Made" && !afterDate) { setAsk({ kind: "confirm", id: row.id, move: m, row }); return; }
    changeItem(m.request, movedWords(m, row));
  }
  live.current = { byId, attempt, from, to, b };

  // Dragging: pointer events, so a mouse, a pen or a finger do the same. The logic's drag only starts after a few pixels.
  const drag = useRef(null);
  if (!drag.current) {
    drag.current = createDrag({
      onStart: (d) => { setDragId(d.id); setMenu(null); setAsk(null); },
      onMove: ({ x, y }) => {
        pos.current = { x, y };
        if (ghost.current) ghost.current.style.transform = `translate(${x + 12}px, ${y + 12}px)`;
        showOver(x, y);
        if (!frame.current) frame.current = requestAnimationFrame(scrollStep);
      },
      onDrop: ({ x, y, data }) => {
        endedAt.current = performance.now();
        setDragId(null); setOver("");
        const c = document.elementFromPoint(x, y), cell = c && c.closest ? c.closest("[data-cell]") : null;
        const L = live.current, row = L.byId[data.id];
        if (cell && row) L.attempt(row, data.from, L.to(cell.dataset.lane === "" ? null : cell.dataset.lane, cell.dataset.col));
      },
      onCancel: () => { endedAt.current = performance.now(); setDragId(null); setOver(""); },
    });
  }
  function showOver(x, y) {
    const c = document.elementFromPoint(x, y), cell = c && c.closest ? c.closest("[data-cell]") : null;
    setOver(cell ? cellKey(cell.dataset.lane, cell.dataset.col) : "");
  }
  // A drag near the edge of the board scrolls it (the board is wider than the window), so any column can be reached.
  function scrollStep() {
    frame.current = 0;
    const p = pos.current;
    if (!p || !drag.current.dragging) return;
    const sc = document.body.classList.contains("board-full") ? document.querySelector("main") : box.current;
    if (sc) {
      const r = sc.getBoundingClientRect(), edge = 56, speed = (d) => Math.min(24, Math.ceil(d / 3));
      const dx = p.x > r.right - edge ? speed(p.x - (r.right - edge)) : p.x < r.left + edge ? -speed(r.left + edge - p.x) : 0;
      const dy = p.y > r.bottom - edge ? speed(p.y - (r.bottom - edge)) : p.y < r.top + edge ? -speed(r.top + edge - p.y) : 0;
      if (dx || dy) { sc.scrollLeft += dx; sc.scrollTop += dy; showOver(p.x, p.y); }
    }
    frame.current = requestAnimationFrame(scrollStep);
  }
  const startDrag = (e, id, laneKey, colKey) => {
    endedAt.current = -1e9;                            // a new press: the click that ended the last drag is long gone
    if (!editing || e.button !== 0 || e.target.closest("button, input, .dpick, .ddmenu")) return;
    const d = drag.current;
    d.down(e.clientX, e.clientY, { id, from: live.current.from(id, laneKey, colKey) });
    const move = (ev) => d.move(ev.clientX, ev.clientY);
    const done = (ev) => { off(); d.up(ev.clientX, ev.clientY); };
    const esc = (ev) => { if (ev.key === "Escape") { off(); d.cancel(); } };
    const stop = () => { off(); d.cancel(); };
    const off = () => {
      listening.current = null;
      document.removeEventListener("pointermove", move, true); document.removeEventListener("pointerup", done, true);
      document.removeEventListener("pointercancel", stop, true); document.removeEventListener("keydown", esc, true);
    };
    document.addEventListener("pointermove", move, true); document.addEventListener("pointerup", done, true);
    document.addEventListener("pointercancel", stop, true); document.addEventListener("keydown", esc, true);
    listening.current = off;
  };
  // If the board goes away mid-drag (another project opened with the button held), take the listeners and the scroll off.
  useEffect(() => () => { if (listening.current) listening.current(); if (frame.current) cancelAnimationFrame(frame.current); }, []);
  const open = (id, dbl) => { if (performance.now() - endedAt.current < 400) return; if (dbl) pickOpen(id, openCard); else openCard(id); };
  const pick = (e, id) => { if (performance.now() - endedAt.current < 400) return; pickClick(e, id, openCard); };
  const picked = pickSel.ids.value;

  // Full screen (#81): a class on the body, so a redraw after a move keeps it. Esc leaves it unless a menu, a date picker or the
  // peek is open (the peek's root carries data-peek, for #42): those take their own Esc first.
  const isFull = full.value;
  useEffect(() => {
    document.body.classList.toggle("board-full", isFull);
    if (!isFull) return undefined;
    const esc = (e) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (document.querySelector("[data-peek], .ddmenu, .dpick, .fbox")) return;
      leave(true);
    };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [isFull]);
  useEffect(() => () => { document.body.classList.remove("board-full"); full.value = false; }, []);
  // Board view (#134): a class on the body for the pinned board, and the page takes the wheel (or a swipe) first, until the board
  // has reached the foot of the top bar; after that the board scrolls inside itself.
  useEffect(() => {
    document.body.classList.add("board-view");
    const bx = box.current, bar = () => document.querySelector(".top"), gap = () => bx.getBoundingClientRect().top - (bar() ? bar().getBoundingClientRect().bottom : 0);
    let y0 = 0;
    const wheel = (e) => { const g = gap(); if (!document.body.classList.contains("board-full") && e.deltaY > 0 && Math.abs(e.deltaY) >= Math.abs(e.deltaX) && g > 1) { e.preventDefault(); window.scrollBy(0, Math.min(e.deltaY, g)); } };
    const start = (e) => { y0 = e.touches[0].clientY; };
    const move = (e) => { const dy = y0 - e.touches[0].clientY, g = gap(); if (!document.body.classList.contains("board-full") && dy > 0 && g > 1) { e.preventDefault(); window.scrollBy(0, Math.min(dy, g)); y0 = e.touches[0].clientY; } };
    if (bx) { bx.addEventListener("wheel", wheel, { passive: false }); bx.addEventListener("touchstart", start, { passive: true }); bx.addEventListener("touchmove", move, { passive: false }); }
    return () => {
      document.body.classList.remove("board-view");
      if (bx) { bx.removeEventListener("wheel", wheel); bx.removeEventListener("touchstart", start); bx.removeEventListener("touchmove", move); }
    };
  }, []);
  function leave(refocus) {
    full.value = false; announce.value = "Full screen off.";
    if (refocus) setTimeout(() => { if (fsBtn.current) fsBtn.current.focus(); }, 0);
  }
  const toggleFull = () => { if (isFull) leave(false); else { full.value = true; announce.value = "Full screen on."; } };

  const toned = TONED.includes(g);
  const laneItems = [{ id: "none", name: "None" }].concat(LANE_GROUPS.filter((x) => x !== g).map((x) => ({ id: x, name: LANE_WORDS[x] })));
  const laneNow = b.lane ? LANE_WORDS[b.lane] : "None";
  const sendMenu = (id, pick) => {                    // a Move to... choice
    setMenu(null);
    const L = live.current, row = L.byId[id];
    if (!row) return;
    const here = L.cardCell[id];
    if (!here) return;
    L.attempt(row, here, pick.lane ? { ...here, lane: { group: b.lane, key: pick.key } } : { ...here, key: pick.key });
  };
  const cardCell = {};
  b.lanes.forEach((ln) => ln.columns.forEach((c) => c.cards.forEach((cd) => { cardCell[cd.id] = from(cd.id, ln.key, c.key); })));
  live.current.cardCell = cardCell;

  // The items of a card's Move to... menu: every column (and lane) moveFor accepts, not where the card is now.
  function menuFor(id) {
    const row = byId[id], here = cardCell[id], out = [];
    if (!row || !here) return out;
    const ok = (t) => { const r = moveFor(row, here, t, ctx); return r.ok && !r.noop; };
    const cols = b.lanes[0].columns.filter((c) => ok({ ...here, key: c.key }));
    if (cols.length) out.push({ head: `Move to ${groupLabel(g)}` }, ...cols.map((c) => ({ key: c.key, name: c.label })));
    if (b.lane) {
      const lanes = b.lanes.filter((l) => ok({ ...here, lane: { group: b.lane, key: l.key } }));
      if (lanes.length) out.push({ head: `Move to ${LANE_WORDS[b.lane]}` }, ...lanes.map((l) => ({ key: l.key, name: l.label || "No " + LANE_WORDS[b.lane].toLowerCase(), lane: true })));
    }
    return out;
  }

  const cardNode = (cd, ln, c) => {
    const here = cardCell[cd.id];
    return (
      <div key={cd.id} class="bwrap" onPointerDown={(e) => startDrag(e, cd.id, ln.key, c.key)}>
        <Card card={cd} editing={editing} selected={peeked === cd.id} picked={picked.includes(cd.id)} dragging={dragId === cd.id} menu={menu === cd.id}
          onOpen={open} onPick={pick} onMenu={(id) => setMenu(menu === id ? null : id)}
          ask={ask && ask.id === cd.id
            ? ask.kind === "date"
              ? <DatePicker ask={ask} today={today} onCancel={() => setAsk(null)} onSet={(date) => {
                  const m = dateMove(ask.move, date, today);
                  if (!m.ok) return m.message;
                  setAsk(null); changeItem(m.request, movedWords(m, ask.row)); return "";
                }} />
              : <Confirm onCancel={() => setAsk(null)} onYes={() => { const { move, row } = ask; setAsk(null); changeItem(move.request, movedWords(move, row)); }} />
            : null}>
          {menu === cd.id ? (
            <MenuPanel label={`Move ${cd.id} to`} cls="left" anchor={document.querySelector(`[data-move="${cd.id}"]`)} onClose={() => { setMenu(null); const el = document.querySelector(`[data-move="${cd.id}"]`); if (el) el.focus(); }}>
              {menuFor(cd.id).map((it, i) => it.head
                ? <div key={"h" + i} class="mh" role="presentation">{it.head}</div>
                : <button key={(it.lane ? "l" : "c") + it.key} type="button" role="menuitem" tabIndex={-1} data-to={it.key} data-lane={it.lane ? "1" : undefined}
                    onClick={() => sendMenu(cd.id, it)}>{it.name}</button>)}
              {menuFor(cd.id).length === 0 ? <button type="button" role="menuitem" aria-disabled="true" tabIndex={-1}>{noMove(byId[cd.id])}</button> : null}
            </MenuPanel>
          ) : null}
        </Card>
      </div>
    );
  };

  return (
    <div class="board" id="work-board" data-full={isFull ? "1" : "0"} data-editing={editing ? "1" : "0"}>
      <div class="lanebar" role="group" aria-label="Board view">
        <Menu label={`Swimlanes: ${laneNow}`} ariaLabel={`Swimlanes: ${laneNow}`} id="swimlanes" btnCls="btn gb" menuLabel="Swimlanes" left items={laneItems}
          onPick={(id) => setWork({ lane: id === "none" ? null : id })} />
        {!editing ? <span class="muted lb-hint">Switch to Edit to move cards.</span> : null}
        <button type="button" class="bib fs" id="board-full" ref={fsBtn} aria-pressed={isFull ? "true" : "false"} aria-label={isFull ? "Leave full screen" : "View full screen"}
          data-tip={isFull ? "Leave full screen (Esc)" : "View full screen"} onClick={toggleFull}>
          <Icon name={isFull ? "shrink" : "expand"} />
        </button>
      </div>
      <div class="boardbox" role="region" aria-label="Work items board" ref={box}>
        {b.lanes.map((ln) => (
          <div class={`lane${b.lane ? " has" : ""}`} key={ln.key == null ? "all" : ln.key} data-lane={ln.key == null ? "" : ln.key}>
            {b.lane ? <div class="lane-h" role="heading" aria-level="3"><span class="lh-in"><span class="ll">{ln.label}</span><span class="lc num">{ln.count}</span></span></div> : null}
            <div class="cols">
              {ln.columns.map((c) => {
                const shut = isCollapsed(st, g, c.key), key = cellKey(ln.key, c.key);
                const tone = toned && c.tone ? ` tone-${c.tone}` : "";
                return (
                  <section class={`col${shut ? " shut" : ""}${tone}${over === key ? " over" : ""}${c.nodrop ? " nodrop" : ""}`} key={c.key}
                    data-cell="1" data-col={c.key} data-lane={ln.key == null ? "" : ln.key} data-count={c.count} aria-label={`${c.label}, ${c.count}`} aria-disabled={c.nodrop ? "true" : undefined}>
                    <h4 class="col-h">
                      <GroupTick ids={c.cards.map((cd) => cd.id)} label={b.lane ? `${c.label} in ${ln.label || "No " + LANE_WORDS[b.lane].toLowerCase()}` : c.label} shut={shut || c.cards.length === 0} />
                      <button type="button" class="col-b" aria-expanded={shut ? "false" : "true"} aria-label={`${c.label}, ${c.count}${shut ? ", collapsed" : ""}`} data-toggle={c.key}
                        onClick={() => setWork(toggleCollapsed(work.value, g, c.key))}>
                        <span class="dot" aria-hidden="true"></span><span class="cl">{c.label}</span><span class="cn num">{c.count}</span>
                      </button>
                    </h4>
                    {c.nodrop && !shut ? <p class="muted nd">{c.key === "overdue" ? "Can't drop here. Use This week, Next week or Later." : "Can't drop here"}</p> : null}
                    {shut ? null : (
                      <div class="col-body">
                        {c.cards.length === 0 ? <p class="muted none">Nothing here</p> : c.cards.map((cd) => cardNode(cd, ln, c))}
                      </div>
                    )}
                  </section>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      {dragId ? <div class="bghost" ref={ghost} aria-hidden="true">{dragId}</div> : null}
    </div>
  );
}
