// #196: changing several work items at once, as plain functions with no DOM, no signals and no clock. The bar, the right-click
// menu, the keys and a cell of a selected row (edit/Bulk.jsx) all ask these what is offered, why something is off, and what to
// send. What is sent is one request to clark (op "bulk", clark/changes.py): one step, one Undo, every item checked there first.
import { PRIORITIES } from "./itemEdit.js";

export const CONFIRM_ABOVE = 25;                   // clark asks again above this many (changes.BULK_CONFIRM_ABOVE)
export const MAX = 500;                             // clark takes at most this many in one change (changes.MAX_BULK)
export const LEVELS = ["High", "Medium", "Low"];    // a risk's or issue's impact and likelihood
export const STATUSES = { actions: ["Open", "Delayed", "Closed", "Cancelled"], raid: ["Open", "Closed", "Cancelled"] };

export const WHY = {
  kinds: "These items are of different kinds",
  projects: "These items are in different projects",
  view: "Switch to Edit to change these",
  decision: "A decision takes only who makes it",
  raidPriority: "A risk's or issue's priority comes from its impact and likelihood",
  noDecision: "A decision has no priority",
  tooMany: `Choose at most ${MAX} items at a time`,
};

// The controls, in the order the bar and the menu show them. `field` is what is sent; `menu` controls open a picker first.
export const CONTROLS = [
  { id: "close", label: "Close", tables: ["actions", "raid"] },
  { id: "reopen", label: "Reopen", tables: ["actions", "raid"] },
  { id: "status", label: "Status", tables: ["actions", "raid"], menu: true },
  { id: "owner", label: "Owner", tables: ["actions", "raid"], menu: true },
  { id: "due", label: "Due date", tables: ["actions", "raid"], menu: true },
  { id: "priority", label: "Priority", tables: ["actions"], menu: true },
  { id: "impact", label: "Impact", tables: ["raid"], menu: true },
  { id: "likelihood", label: "Likelihood", tables: ["raid"], menu: true },
  { id: "workstream", label: "Workstream", tables: ["actions", "raid"], menu: true, oneProject: true },
  { id: "milestone", label: "Milestone", tables: ["actions", "raid"], menu: true, oneProject: true },
  { id: "made_by", label: "Made by", tables: ["decisions"], menu: true },
];

/** The table clark keeps a row in. */
export const tableOf = (row) => row.table || (row.kind === "action" ? "actions" : row.kind === "decision" ? "decisions" : "raid");
/** The project an item id belongs to (the code before the first hyphen). */
export const projectOf = (id) => String(id).split("-")[0];

/** What the selection is: how many, the one table they are all in (null when they are of different kinds), and how many projects. */
export function summary(rows) {
  const tables = new Set(rows.map(tableOf)), projects = new Set(rows.map((r) => projectOf(r.id)));
  return { n: rows.length, table: tables.size === 1 ? [...tables][0] : null, projects: projects.size, ids: rows.map((r) => r.id) };
}

/** The controls for a selection, each {id, label, on, why}: a control that does not fit is left out for the kind it does not
 *  belong to, and is off with its reason as words for every other cause. Mixed kinds: every one is off. */
export function controls(sum, { editing = true } = {}) {
  const shown = sum.table ? CONTROLS.filter((c) => c.tables.includes(sum.table)) : CONTROLS.filter((c) => !["impact", "likelihood", "made_by"].includes(c.id));
  return shown.map((c) => {
    let why = "";
    if (!sum.table) why = WHY.kinds;
    else if (!editing) why = WHY.view;
    else if (sum.n > MAX) why = WHY.tooMany;
    else if (c.oneProject && sum.projects > 1) why = WHY.projects;
    return { id: c.id, label: c.label, menu: !!c.menu, on: !why, why };
  });
}

/** The changes a control makes with `value` (a picker's choice; none for Close and Reopen), for `table`. null: nothing to send. */
export function changesFor(table, id, value) {
  if (id === "close") return { status: "Closed" };
  if (id === "reopen") return { status: "Open" };
  if (id === "due") return { due_date: value || null };
  if (id === "workstream" || id === "milestone") return { [id]: value || null };
  if (id === "owner" || id === "made_by") {
    const text = String(value == null ? "" : value).trim().split(/\s+/).filter(Boolean).join(" ");
    return text ? { [table === "decisions" ? "made_by" : "owner"]: text } : null;
  }
  if (["status", "priority", "impact", "likelihood"].includes(id)) return value ? { [id]: value } : null;
  return null;
}

/** The request for clark: one bulk change of `ids` in `table`. */
export function requestFor(table, ids, changes, { confirm = false, place = "bulk" } = {}) {
  return { kind: table, op: "bulk", ids: ids.slice(), changes: { ...changes }, place, ...(confirm ? { confirm: true } : {}) };
}

/** Whether to ask first, and the question: above CONFIRM_ABOVE, counting every item in the request. */
export const needsConfirm = (n) => n > CONFIRM_ABOVE;
export const confirmWords = (n) => `Change ${n} items?`;

/** What a picker chooses from, for a control: [{value, text}]. `ctx` has the active workstreams and the milestones. */
export function choicesFor(table, id, ctx = {}) {
  if (id === "status") return (STATUSES[table] || []).map((s) => ({ value: s, text: s }));
  if (id === "priority") return PRIORITIES.map((p) => ({ value: p, text: p }));
  if (id === "impact" || id === "likelihood") return LEVELS.map((p) => ({ value: p, text: p }));
  if (id === "workstream") return (ctx.workstreams || []).map((w) => ({ value: w, text: w })).concat([{ value: "", text: "No workstream" }]);
  if (id === "milestone") return (ctx.milestones || []).map((m) => ({ value: m.id, text: m.name })).concat([{ value: "", text: "No milestone" }]);
  return [];
}

/** "3 items", "1 item": how the menu, a picker's label and a question name the selection. */
export const itemsWords = (n) => `${n} item${n === 1 ? "" : "s"}`;

/** The words for a picker's label: "Owner of 3 items". */
export function pickerLabel(id, n) {
  const c = CONTROLS.find((x) => x.id === id);
  return `${c ? c.label : "Change"} of ${itemsWords(n)}`;
}

/** What the toast says after an Undo of a bulk change. */
export const backWords = (n) => `Undone: ${itemsWords(n)} ${n === 1 ? "is" : "are"} back as ${n === 1 ? "it was" : "they were"}.`;

/** The ids for Copy IDs, one line. */
export const copyText = (ids) => ids.join(", ");

// ── A cell of a selected row (Done-when 6) ──

const CELL_TO_CONTROL = { owner: "owner", due: "due", priority: "priority", status: "status" };

/** When a cell is changed on a row that is one of two or more selected: the control it stands for, the question to ask first
 *  ("Change the owner of all 4 selected items?"), or `why` when the whole selection can't take it (the cell then changes
 *  nothing, and the words say so). null: not a selection change (a lone row, or a row that is not selected). */
export function cellPlan(rowId, field, selectedRows) {
  if (selectedRows.length < 2 || !selectedRows.some((r) => r.id === rowId)) return null;
  const sum = summary(selectedRows);
  const id = sum.table === "decisions" && field === "owner" ? "made_by" : CELL_TO_CONTROL[field];
  const name = { owner: sum.table === "decisions" ? "decider" : "owner", due: "due date", priority: "priority", status: "status" }[field] || field;
  if (!sum.table) return { why: `${WHY.kinds}, so the ${name} can't be changed for all of them. Clear the selection to change only this one.` };
  const c = controls(sum).find((x) => x.id === id);
  if (!c) return { why: `${sum.table === "decisions" ? WHY.decision : sum.table === "raid" && field === "priority" ? WHY.raidPriority : "That can't be changed for all of them"}. Clear the selection to change only this one.` };
  if (!c.on) return { why: `${c.why}. Clear the selection to change only this one.` };
  return { id, question: `Change the ${name} of all ${sum.n} selected items?`, n: sum.n, table: sum.table, ids: sum.ids };
}

// ── Keys on a row, a card, a selection or the open peek (Done-when 3) ──

/** The control a letter key opens, for a table: O owner, S status, P priority, T due date, C close. V is not one yet. */
export function keyControl(key, table) {
  const k = String(key || "").toLowerCase();
  if (k === "o") return table === "decisions" ? "made_by" : "owner";
  if (k === "s") return "status";
  if (k === "p") return "priority";
  if (k === "t") return "due";
  if (k === "c") return "close";
  return null;
}

/** Why a key does nothing on these items, in words (for the toast); "" when it can act. */
export function keyWhy(id, sum, editing = true) {
  if (!sum.table) return `${WHY.kinds}.`;
  if (!editing) return `${WHY.view}.`;
  const c = controls(sum).find((x) => x.id === id);
  if (c) return c.on ? "" : `${c.why}.`;
  if (sum.table === "decisions") return `${WHY.decision}.`;
  if (id === "priority" && sum.table === "raid") return `${WHY.raidPriority}. Change its impact or likelihood instead.`;
  return "That can't be changed here.";
}
