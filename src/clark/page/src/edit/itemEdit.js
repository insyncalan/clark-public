// #80: what the Work items table's four cells may change, as plain functions with no DOM and no clock (the caller hands in
// today). Each cell (owner, due, priority, status) has its own picker in ./cells/, and the peek (#42) can use the same pickers
// later. A change is sent through api.js as kind actions, raid or decisions, op update (clark/changes.py, #68): only
// the fields it accepts are named here. A RAID item's priority comes from its impact and likelihood, so a risk's or an issue's
// Priority cell changes those two (#210); an assumption's or a dependency's is not a picker, and a decision has no priority.
import { dueField, showDate, dayNumber } from "../workItems.js";

export const PRIORITIES = ["Urgent", "High", "Medium", "Low"];
export const LEVELS = ["High", "Medium", "Low"];                       // a risk's or an issue's impact and likelihood
export const RAID_LEVELS = [["impact", "Impact"], ["likelihood", "Likelihood"]];
const STATUSES = {
  action: ["Open", "Delayed", "Closed", "Cancelled"],
  raid: ["Open", "Closed", "Cancelled"],
  decision: ["Pending", "Made", "Withdrawn"],
};
export const FIELDS = ["owner", "due", "priority", "status"];
const DAY = 86400000;
// A character no one can see or that breaks a line (control, format such as a zero-width space or a right-to-left override,
// surrogate, private use, line and paragraph separators): clark/changes.py refuses a name with one (ITEM_BAD_KINDS), so the
// picker says so first and keeps the box open with what was typed.
const HIDDEN = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Zl}\p{Zp}]/u;

/** The table a row lives in, as clark names it. */
export function tableOf(row) {
  return row.kind === "action" ? "actions" : row.kind === "decision" ? "decisions" : "raid";
}

/** Whether a cell of this row opens a picker. */
export function canPick(row, field) {
  if (field === "priority") return row.kind === "action" || raidLevels(row);
  return FIELDS.includes(field);
}

/** Whether the row's Priority cell changes its impact and likelihood (#210): a risk or an issue. */
export function raidLevels(row) { return row.kind === "risk" || row.kind === "issue"; }

/** A risk's or an issue's priority from its impact and likelihood, as clark works it out (store.priority); null if either is unset. */
export function priorityFrom(impact, likelihood) {
  if (!impact || !likelihood) return null;
  if (impact === "High" && likelihood === "High") return "Urgent";
  if (impact === "High" || likelihood === "High") return "High";
  return impact === "Low" && likelihood === "Low" ? "Low" : "Medium";
}

/** Why a cell that is not a picker can't be changed here, for its tooltip: an assumption's or a dependency's priority comes from its impact and likelihood. */
export function whyFixed(row, field) {
  return field === "priority" && tableOf(row) === "raid" && !raidLevels(row) ? "Set from impact and likelihood" : "";
}

/** The statuses a row may be given. A made decision can't go back to Pending, so Pending is not offered then. */
export function statusChoices(row) {
  const all = row.kind === "action" ? STATUSES.action : row.kind === "decision" ? STATUSES.decision : STATUSES.raid;
  return row.kind === "decision" && row.status === "Made" ? all.filter((s) => s !== "Pending") : all.slice();
}

// The Status cell in Edit shows the status itself, the word its picker offers, so a pick and the cell always say the same:
// Open and Pending blue, Delayed amber, Made green, Closed, Cancelled and Withdrawn grey. (View keeps #36's pills, where a late
// action reads Overdue and an open risk its colour.)
const STATUS_TONE = { Open: "b", Pending: "b", Delayed: "a", Made: "g", Closed: "n", Cancelled: "n", Withdrawn: "n" };

/** The Status cell's pill in Edit: {text, class}, with the item's own status as its word. */
export function statusPill(row) {
  const s = String(row.status == null ? "" : row.status);
  return { text: s, class: STATUS_TONE[s] || "n" };
}

/** The small print under a status in the picker: Made is the one pick that can't be undone. */
export function statusNote(row, status) {
  return row.kind === "decision" && status === "Made" && row.status !== "Made" ? "Can't be undone" : "";
}

/** The column the Owner cell changes: a decision's is who makes it. */
export function ownerField(row) { return row.kind === "decision" ? "made_by" : "owner"; }

/** The column the Due cell changes: a pending decision's is the date it is needed by, any other decision's the date it was made. */
export function dueColumn(row) {
  if (row.kind !== "decision") return "due_date";
  return row.status === "Pending" ? "needed_by" : "date";
}

/** Whether the Due cell may be cleared: a made decision always has its date. */
export function canClearDue(row) { return !(row.kind === "decision" && row.status === "Made"); }

// What a cell is called in a sentence, for the label and the toast.
export function fieldName(row, field) {
  if (field === "owner") return row.kind === "decision" ? "Decider" : "Owner";
  if (field === "due") return row.kind !== "decision" ? "Due date" : row.status === "Pending" ? "Needed-by date" : "Decision date";
  return field === "priority" ? "Priority" : "Status";
}

/**
 * The change one pick makes: {changes, words, back} to send, {error} to say in the picker and send nothing, or null when the pick
 * is the value the row already has. `words` is what the toast says; `back` what its Undo says, the value the cell goes back to.
 * `today` is YYYY-MM-DD.
 */
export function changeFor(row, field, value, today) {
  const name = fieldName(row, field);
  if (field === "owner") {
    const text = String(value == null ? "" : value).trim().split(/\s+/).filter(Boolean).join(" ");
    const col = ownerField(row);
    const now = String(row.owner == null ? "" : row.owner).trim();
    if (!text) {
      if (row.kind !== "decision") return { error: "An owner can't be blank. Type a name, or TBC if no one is known yet." };
      return now ? { changes: { [col]: null }, words: `${name} of ${row.id} cleared.`, back: `${name} of ${row.id} is back to ${now}.` } : null;
    }
    if (HIDDEN.test(text)) return { error: "That name has a hidden character in it, often from copying and pasting. Type the name again, then press Enter." };
    if (Array.from(text).length > 200) return { error: "A name can be 200 characters at most. Shorten it and try again." };
    if (text === now) return null;
    const back = now ? `${name} of ${row.id} is back to ${now}.` : `${name} of ${row.id} is blank again.`;
    return { changes: { [col]: text }, words: `${name} of ${row.id} changed to ${text}.`, back };
  }
  if (field === "due") {
    const iso = value || null;
    if (iso !== null && dayNumber(iso) === null) return { error: "That date isn't a real day, so nothing was changed. Pick another date." };
    if (iso === null && !canClearDue(row)) return { error: "A made decision keeps the date it was made. Pick another date instead." };
    const was = dueField(row) || null;
    if (iso === was) return null;
    const back = was ? `${name} of ${row.id} is back to ${showDate(was)}.` : `${name} of ${row.id} is blank again.`;
    return { changes: { [dueColumn(row)]: iso }, words: iso ? `${name} of ${row.id} changed to ${showDate(iso)}.` : `${name} of ${row.id} cleared.`, back };
  }
  if (field === "priority" && raidLevels(row)) {                   // #210: the value is "impact:High" or "likelihood:Low"
    const [col, level] = String(value == null ? "" : value).split(":");
    const pair = RAID_LEVELS.find(([c]) => c === col);
    if (!pair || !LEVELS.includes(level)) return { error: "That level can't be used, so nothing was changed. Pick High, Medium or Low." };
    if (level === row[col]) return null;
    const now = { impact: row.impact, likelihood: row.likelihood, [col]: level };
    const after = priorityFrom(now.impact, now.likelihood);
    const back = row[col] ? `${pair[1]} of ${row.id} is back to ${row[col]}.` : `${pair[1]} of ${row.id} is blank again.`;
    return { changes: { [col]: level }, words: `${pair[1]} of ${row.id} changed to ${level}.${after ? ` Priority is now ${after}.` : ""}`, back };
  }
  if (field === "priority") {
    if (tableOf(row) === "raid") return { error: "A risk's or issue's priority is set from its impact and likelihood, so nothing was changed." };
    if (!canPick(row, "priority")) return { error: "A decision has no priority, so nothing was changed." };
    if (!PRIORITIES.includes(value)) return { error: "That priority can't be used, so nothing was changed. Pick Urgent, High, Medium or Low." };
    if (value === row.priority) return null;
    const back = row.priority ? `Priority of ${row.id} is back to ${row.priority}.` : `Priority of ${row.id} is blank again.`;
    return { changes: { priority: value }, words: `Priority of ${row.id} changed to ${value}.`, back };
  }
  if (field === "status") {
    if (!statusChoices(row).includes(value)) return { error: "That status isn't one this item can have, so nothing was changed. Pick one from the list." };
    if (value === row.status) return null;
    const changes = { status: value };
    if (row.kind === "decision") {
      if (value === "Made" && !row.date) changes.date = today;          // a made decision needs the date it was made: today
      if (value === "Pending" && row.date) changes.date = null;         // a pending one has none yet
    }
    const words = row.kind === "decision" && value === "Made"
      ? `${row.id} is now made, on ${showDate(changes.date || row.date)}. This can't be undone. To change it, record a new decision.`
      : `Status of ${row.id} changed to ${value}.`;
    return { changes, words, back: `Status of ${row.id} is back to ${row.status}.` };
  }
  return { error: "Only the owner, due date, priority and status can be changed here. Nothing was changed." };
}

/** Everyone named as an owner or a decider in the project's data, in alphabetical order, once each. */
export function people(data) {
  const names = new Set();
  const add = (v) => { const t = String(v == null ? "" : v).trim(); if (t && t.toUpperCase() !== "TBC") names.add(t); };
  for (const r of (data && data.actions) || []) add(r.owner);
  for (const r of (data && data.raid) || []) add(r.owner);
  for (const r of (data && data.decisions) || []) add(r.made_by);
  for (const m of (data && data.milestones) || []) add(m.owner);
  return Array.from(names).sort((a, b) => a.localeCompare(b, "en-GB"));
}

/** The names that match what has been typed (any word starting with it, or the whole name containing it), best first. */
export function matching(names, typed) {
  const q = String(typed || "").trim().toLowerCase();
  if (!q) return names.slice();
  const starts = names.filter((n) => n.toLowerCase().split(/\s+/).some((w) => w.startsWith(q)) || n.toLowerCase().startsWith(q));
  const inside = names.filter((n) => !starts.includes(n) && n.toLowerCase().includes(q));
  return starts.concat(inside);
}

// ── Dates for the picker: plain days, read in UTC so a clock change never moves one ──

function iso(t) {
  const d = new Date(t);
  return `${String(d.getUTCFullYear()).padStart(4, "0")}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
}

/** The day `n` days after `day` (YYYY-MM-DD). */
export function addDays(day, n) { return iso((dayNumber(day) + n) * DAY); }

/** YYYY-MM of the month `n` months after `ym`. */
export function addMonths(ym, n) {
  const y = +ym.slice(0, 4), m = +ym.slice(5, 7) - 1 + n;
  const t = new Date(Date.UTC(y, m, 1));
  return iso(t.getTime()).slice(0, 7);
}

/** A month's grid, Monday first: '' for a blank before the 1st, then each day as YYYY-MM-DD. */
export function monthCells(ym) {
  const y = +ym.slice(0, 4), m = +ym.slice(5, 7) - 1;
  const first = new Date(Date.UTC(y, m, 1)), lead = (first.getUTCDay() + 6) % 7;
  const n = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  const out = new Array(lead).fill("");
  for (let d = 1; d <= n; d++) out.push(`${ym}-${String(d).padStart(2, "0")}`);
  return out;
}

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
export function monthTitle(ym) { return `${MONTHS[+ym.slice(5, 7) - 1]} ${ym.slice(0, 4)}`; }

/** The quick choices under the month: Today, Tomorrow, Friday (the next one, a week on if today is Friday), Next week. */
export function quickDates(today) {
  const wd = new Date(dayNumber(today) * DAY).getUTCDay();               // 0 Sunday .. 6 Saturday
  const toFri = ((5 - wd + 7) % 7) || 7;
  return [["Today", today], ["Tomorrow", addDays(today, 1)], ["Friday", addDays(today, toFri)], ["Next week", addDays(today, 7)]];
}
