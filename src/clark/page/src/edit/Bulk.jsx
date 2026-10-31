// #196: change several work items at once. Three ways in, the same actions and the same one change through clark (op "bulk": one
// step, one Undo, every item checked there first, those that can't take it left out and named in the toast):
// - the bar above the table or board while two or more are selected (BulkActions, handed to #195's SelectBar);
// - the right-click menu, Shift+F10 or the Menu key on a row, a card or a selection ("N items"; installBulkMenu);
// - the keys O owner, S status, P priority, T due date and C close on the row or card with the keyboard, on a selection, or on
//   the item open in the peek (installBulkKeys). They are single-key shortcuts: they ask the Single-key switch (#193) first, act
//   only in Edit, and only when the table, the board or the peek has the keyboard. No page key uses these letters.
// Above 25 items, and before a cell of a selected row changes every selected row (Done-when 6), a question is asked first. Nothing
// here deletes or archives. The rules are in ./bulkLogic.js; the pickers are the cells' own (./cells/).
import { signal } from "@preact/signals";
import { useLayoutEffect, useRef } from "preact/hooks";
import { data, item, mode, view, fromFile } from "../stores/report.js";
import { changeBulk, say } from "../stores/changes.js";
import { workSelection as sel } from "../stores/selection.js";
import { itemRows, contextFor, announce } from "../stores/work.js";
import { todayIso } from "../workItems.js";
import { people } from "./itemEdit.js";
import { singleKeysOn } from "./singleKeys.js";
import { Pop, roam } from "./cells/Pop.jsx";
import { MenuPick } from "./cells/MenuPick.jsx";
import { OwnerPick } from "./cells/OwnerPick.jsx";
import { DuePick } from "./cells/DuePick.jsx";
import * as B from "./bulkLogic.js";

// What is open: null, or {what: "menu" | "pick" | "ask", ids, at: an element or {x, y}, control, place, question, yes}.
export const bulkOpen = signal(null);

const editing = () => mode.value === "edit" && !fromFile.value;
const rowsOf = (ids) => { const all = new Map(itemRows.value.map((r) => [r.id, r])); return ids.map((id) => all.get(id)).filter(Boolean); };
const FIELD = /^(INPUT|TEXTAREA|SELECT)$/;
const OVERLAY = ".cpop, .ddmenu, .dpick, .fbox, [role='dialog']:not([data-peek]), [role='alertdialog'], dialog[open]";   // open over the list (the peek is not one)
const ITEM = "#work-list tr[data-id], #work-list article.bcard[data-id]";

/** Send one change to `ids` (all of `table`); `value` is a picker's choice. Asks first above 25; clears the selection after a
 *  change that saved. Resolves to the reply, or null. */
export function runBulk(table, ids, control, value, { place = "bulk" } = {}) {
  const changes = B.changesFor(table, control, value);
  if (!changes || !ids.length) return Promise.resolve(null);
  const go = (confirm) => changeBulk(B.requestFor(table, ids, changes, { confirm, place }), B.backWords(ids.length)).then((r) => {
    if (r && !r.ok && r.code === "confirm") { ask(B.confirmWords(r.count || ids.length), () => go(true)); return null; }
    if (r && r.ok && r.reply.changed.length) sel.clear();
    return r && r.ok ? r.reply : null;
  });
  if (B.needsConfirm(ids.length)) { ask(B.confirmWords(ids.length), () => go(true)); return Promise.resolve(null); }
  return go(false);
}

/** Ask a question with Change and Cancel; `yes` runs on Change. */
export function ask(question, yes) { bulkOpen.value = { what: "ask", question, yes, back: document.activeElement }; }

/** Open a control for `ids`: Close and Reopen act at once, the others open their picker at `at`. */
export function openControl(control, ids, at, place = "bulk") {
  const sum = B.summary(rowsOf(ids)), why = B.keyWhy(control, sum, editing());
  if (why) { say("note", why); announce.value = why; return; }
  const c = B.CONTROLS.find((x) => x.id === control);
  if (!c.menu) { bulkOpen.value = null; runBulk(sum.table, sum.ids, control, null, { place }); return; }
  bulkOpen.value = { what: "pick", control, ids: sum.ids, table: sum.table, at, place, back: document.activeElement };
}

/** Open the "N items" menu for `ids` at `at` (an element, or a point {x, y}). */
export function openMenu(ids, at, place = "menu") { bulkOpen.value = { what: "menu", ids: ids.slice(), at, place, back: document.activeElement }; }

function close(back = true) {
  const was = bulkOpen.value;
  bulkOpen.value = null;
  if (back && was && was.back && was.back.isConnected) was.back.focus({ preventScroll: true });
}

// ── The bar's buttons (the SelectBar draws "N selected", Select all N matching and the X) ──
export function BulkActions() {
  const ids = sel.ids.value, sum = B.summary(rowsOf(ids)), list = B.controls(sum, { editing: editing() });
  const why = list.length && list.every((c) => !c.on) ? list[0].why : "";
  return (
    <span class="sb-acts" role="group" aria-label={`Change ${B.itemsWords(sum.n)}`}>
      {list.map((c) => (
        <button type="button" key={c.id} class="sb-a" data-bulk={c.id} aria-disabled={c.on ? undefined : "true"} title={c.on ? undefined : c.why}
          aria-haspopup={c.menu ? "dialog" : undefined}
          onClick={(e) => { if (c.on) openControl(c.id, ids, e.currentTarget, "bulk"); else { say("note", `${c.why}.`); announce.value = `${c.why}.`; } }}>
          {c.label}
        </button>
      ))}
      {why ? <span class="sb-why muted" id="sel-why">{why}</span> : null}
    </span>
  );
}

// ── What is open: the menu, a picker or the question ──
function anchorOf(at) {
  if (at && at.nodeType === 1) return { current: at };
  return { current: { getBoundingClientRect: () => ({ left: at.x, right: at.x, top: at.y, bottom: at.y, width: 0, height: 0 }), contains: () => false } };
}

function ItemsMenu({ open }) {
  const list = useRef(null), anchor = anchorOf(open.at);
  const sum = B.summary(rowsOf(open.ids)), ctl = B.controls(sum, { editing: editing() });
  const items = () => Array.from(list.current ? list.current.querySelectorAll("[role=menuitem]") : []);
  useLayoutEffect(() => { const first = items().find((b) => b.getAttribute("aria-disabled") !== "true"); if (first) first.focus({ preventScroll: true }); }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  const copy = () => {
    close();
    const text = B.copyText(sum.ids), done = `Copied ${sum.n === 1 ? "the ID" : `${sum.n} IDs`}.`, fail = "The IDs could not be copied. Select them in the table instead.";
    const put = navigator.clipboard && navigator.clipboard.writeText ? navigator.clipboard.writeText(text) : Promise.reject(new Error("no clipboard"));
    put.then(() => { say("note", done); announce.value = done; }, () => { say("note", fail); announce.value = fail; });
  };
  return (
    <Pop anchor={anchor} label={B.itemsWords(sum.n)} role="menu" cls="cmenu bmenu" onClose={(back) => close(back)}>
      <div ref={list} onKeyDown={(e) => roam(e, items().filter((b) => b.getAttribute("aria-disabled") !== "true"))}>
        <div class="bm-h" role="presentation">{B.itemsWords(sum.n)}</div>
        {sum.table ? ctl.map((c) => (
          <button type="button" role="menuitem" class="menu-item" key={c.id} data-bulk-menu={c.id} aria-disabled={c.on ? undefined : "true"}
            onClick={() => { if (c.on) { const at = open.at; bulkOpen.value = null; openControl(c.id, sum.ids, at, open.place); } }}>
            <span class="mi-t">{c.menu ? `${c.label}…` : c.label}</span>{c.on ? null : <small class="mi-note">{c.why}</small>}
          </button>
        )) : <div class="bm-why" role="presentation" aria-disabled="true">{B.WHY.kinds}</div>}
        <div class="sep" role="separator" />
        <button type="button" role="menuitem" class="menu-item" data-bulk-menu="copy" onClick={copy}><span class="mi-t">Copy IDs</span></button>
      </div>
    </Pop>
  );
}

function Picker({ open }) {
  const anchor = anchorOf(open.at), n = open.ids.length, label = B.pickerLabel(open.control, n);
  const pick = (value) => {
    const changes = B.changesFor(open.table, open.control, value);
    if (!changes) return open.control === "owner" || open.control === "made_by" ? "A name can't be blank. Type a name, or TBC if no one is known yet." : "";
    close();
    runBulk(open.table, open.ids, open.control, value, { place: open.place });
    return "";
  };
  const shut = (back) => close(back);
  const who = { id: B.itemsWords(n), kind: open.table === "decisions" ? "decision" : "action", owner: "", due_date: null, status: "" };
  if (open.control === "owner" || open.control === "made_by") return <OwnerPick row={who} anchor={anchor} names={people(data.value)} onPick={pick} onClose={shut} />;
  if (open.control === "due") return <DuePick row={who} anchor={anchor} today={todayIso()} onPick={pick} onClose={shut} />;
  return <MenuPick anchor={anchor} label={label} current={null} onPick={pick} onClose={shut} choices={B.choicesFor(open.table, open.control, contextFor(todayIso(), null))} />;
}

function Ask({ open }) {
  const yes = useRef(null);
  useLayoutEffect(() => { if (yes.current) yes.current.focus({ preventScroll: true }); }, []);
  const keys = (e) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === "Tab") {                                   // the keyboard stays in the question
      const b = Array.from(e.currentTarget.querySelectorAll("button")), i = b.indexOf(document.activeElement);
      e.preventDefault(); b[(i + (e.shiftKey ? b.length - 1 : 1)) % b.length].focus();
    }
  };
  return (
    <div class="bask-back" data-edit-only>
      <div class="bask" role="alertdialog" aria-modal="true" aria-labelledby="bask-q" onKeyDown={keys}>
        <p id="bask-q" class="bask-q">{open.question}</p>
        <div class="bask-b">
          <button type="button" class="btn pri" ref={yes} data-bask="yes" onClick={() => { const y = open.yes; close(); y(); }}>Change</button>
          <button type="button" class="btn" data-bask="no" onClick={() => close()}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

export function BulkLayer() {
  const open = bulkOpen.value;
  if (!open || view.value !== "work") return null;
  if (open.what === "menu") return <ItemsMenu open={open} key="menu" />;
  if (open.what === "pick") return <Picker open={open} key={`pick-${open.control}`} />;
  return <Ask open={open} key="ask" />;
}

// ── The ways in from a row, a card or the peek ──

// The items a key or the menu acts on: the selection when the row is one of it, else that row alone.
function targetIds(id) { return sel.size.value >= 1 && sel.has(id) ? sel.ids.value.slice() : [id]; }

function busy(el) { return !!el && el.nodeType === 1 && (el.isContentEditable || FIELD.test(el.tagName) || !!el.closest("[role=textbox],[role=combobox],[role=listbox],[role=menu],[role=dialog]:not([data-peek]),[role=alertdialog]")); }

// The row or card that has the keyboard, or null.
function focusedItem(t) { return t && t.closest ? t.closest(ITEM) : null; }

let installed = false;
export function installBulk() {
  if (installed || typeof document === "undefined") return;
  installed = true;
  // The right-click menu on a row or a card: a row that is not selected is selected on its own first. A link, a box or text being
  // typed keeps the browser's own menu.
  document.addEventListener("contextmenu", (e) => {
    const el = focusedItem(e.target);
    if (!el || view.value !== "work" || fromFile.value || e.target.isContentEditable || (e.target.closest && e.target.closest("a, input, textarea, select"))) return;
    e.preventDefault();
    const id = el.dataset.id;
    if (!sel.has(id)) sel.click(id, {}, [id]);
    openMenu(targetIds(id), { x: e.clientX, y: e.clientY }, el.matches("article") ? "board" : "menu");
  });
  window.addEventListener("keydown", (e) => {
    if (e.defaultPrevented || e.isComposing || view.value !== "work" || fromFile.value || bulkOpen.value) return;
    const t = e.target, row = focusedItem(t), inPeek = !!item.value && !!(t && t.closest && t.closest("[data-peek]"));
    // Shift+F10 or the Menu key: the same menu, under the row or card.
    if ((e.key === "F10" && e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) || e.key === "ContextMenu") {
      if (!row) return;
      e.preventDefault();
      const r = row.getBoundingClientRect();
      openMenu(targetIds(row.dataset.id), { x: r.left + 24, y: r.bottom }, row.matches("article") ? "board" : "menu");
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey || e.repeat || !e.key || e.key.length !== 1) return;
    if (!/^[ospct]$/i.test(e.key) || !singleKeysOn() || !editing()) return;
    if (!row && !inPeek) return;                                  // only the table, the board or the peek
    if (busy(t) || document.querySelector(OVERLAY)) return;
    const ids = inPeek ? [item.value] : targetIds(row.dataset.id);
    const sum = B.summary(rowsOf(ids));
    if (!sum.n) return;
    const control = B.keyControl(e.key, sum.table || "actions");
    e.preventDefault();
    openControl(control, ids, inPeek ? t : row, row && row.matches("article") ? "board" : "bulk");
  });
}

