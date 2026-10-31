// The Work items list's rules, as plain functions with no DOM and no clock (#36; spec docs/handoff/design-36-work-items-list.md,
// cases tests/fixtures/work-items-list-cases.json). The logic follows creaite's `rel`, `OPENST` and the prototype's `C.look`
// and `C.dueWords`, rewritten here. `todayIso()` is the only place that reads the clock.

export const KIND_WORDS = { action: "Action", risk: "Risk", issue: "Issue", assumption: "Assumption", dependency: "Dependency", decision: "Decision" };
const CLOSED = ["Closed", "Cancelled", "Made", "Withdrawn"];
const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;
const DAY = 86400000;
const DASH = "—";

export function todayIso() {
  const t = new Date();
  return `${String(t.getFullYear()).padStart(4, "0")}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`;
}

// A day number for a real calendar day, null for anything else (including 2026-02-30). Both dates are read as plain days
// in UTC, so a clock change never moves a count.
export function dayNumber(iso) {
  const m = ISO.exec(typeof iso === "string" ? iso : "");
  if (!m) return null;
  const t = Date.UTC(+m[1], +m[2] - 1, +m[3]);
  const back = new Date(t);
  return back.getUTCFullYear() === +m[1] && back.getUTCMonth() === +m[2] - 1 && back.getUTCDate() === +m[3] ? Math.round(t / DAY) : null;
}

// DD-MM-YYYY; a stored text that is not a real day is shown as stored (reordered when it has the shape), no date is a dash.
export function showDate(iso) {
  if (!iso) return DASH;
  const m = ISO.exec(String(iso));
  return m ? `${m[3]}-${m[2]}-${m[1]}` : String(iso);
}

// "1 day", "2 days", "0 days": the one place a count and its noun are joined (#130 point 7); `many` is spelled out for a noun that adds more than "s".
export function plural(n, one, many) { return `${n} ${n === 1 ? one : (many || one + "s")}`; }

export function isOpen(row) { return !CLOSED.includes(row.status); }

// The date in the Due column: a decision's is the date it is needed by while pending, otherwise the date it was made.
export function dueField(row) {
  if (row.kind === "decision") return row.status === "Pending" ? row.needed_by : row.date;
  return row.due_date;
}

export function dueCell(row, today) {
  const iso = dueField(row);
  const out = { date: showDate(iso), words: "", tone: "" };
  const a = dayNumber(iso), b = dayNumber(today);
  if (a === null || b === null || !isOpen(row)) return out;
  const n = a - b;
  out.words = n === 0 ? "Today" : n === 1 ? "Tomorrow" : n === -1 ? "Yesterday" : n < 0 ? `${plural(-n, "day")} late` : `In ${plural(n, "day")}`;
  if (n < 0) out.tone = "late";
  return out;
}

// D-12: a risk's or issue's colour is its priority; there is no separate RAG column.
export function colourOf(priority) {
  if (priority === "Urgent" || priority === "High") return { colour: "red", word: "Red", class: "r" };
  if (priority === "Medium") return { colour: "amber", word: "Amber", class: "a" };
  if (priority === "Low") return { colour: "green", word: "Green", class: "g" };
  return { colour: null, word: "Not rated", class: "n" };
}

export function pillOf(row, today) {
  const s = row.status;
  if (row.kind === "decision") return { text: s, class: s === "Made" ? "g" : s === "Withdrawn" ? "n" : "b" };
  if (s === "Closed" || s === "Cancelled") return { text: s, class: "n" };
  if (row.kind === "risk" || row.kind === "issue") { const c = colourOf(row.priority); return { text: c.word, class: c.class }; }
  if (row.kind === "action") {
    const n = dayNumber(row.due_date), t = dayNumber(today);
    if (n !== null && t !== null && n < t) return { text: "Overdue", class: "r" };
    if (s === "Delayed") return { text: "Delayed", class: "a" };
    if (n !== null && t !== null && n - t <= 7) return { text: "Due soon", class: "a" };
  }
  return { text: "Open", class: "b" };
}

export function ownerOf(name) {
  const text = String(name == null ? "" : name).trim().split(/\s+/).filter(Boolean).join(" ");
  if (!text) return { text: DASH, initials: "" };
  if (text.toUpperCase() === "TBC") return { text, initials: "" };
  return { text, initials: text.split(" ").slice(0, 2).map((w) => w[0]).join("").toUpperCase() };
}

// Open rows first; then the Due date ascending (no date, or not a real day, last); then the ID.
export function sortRows(rows, today) { // eslint-disable-line no-unused-vars
  const key = (r) => { const iso = dueField(r); return dayNumber(iso) === null ? null : iso; };
  return rows.slice().sort((x, y) => {
    if (isOpen(x) !== isOpen(y)) return isOpen(x) ? -1 : 1;
    const a = key(x), b = key(y);
    if (a !== b) return a === null ? 1 : b === null ? -1 : a < b ? -1 : 1;
    return x.id < y.id ? -1 : x.id > y.id ? 1 : 0;
  });
}

// One flat list of rows from /api/data: actions, then RAID (its type, lower-cased, is the kind), then decisions.
export function rowsOf(data) {
  const ucs = Object.fromEntries((data.use_cases || []).map((u) => [u.id, u.ref]));
  const ms = Object.fromEntries((data.milestones || []).map((m) => [m.id, m.name]));
  const common = (r) => ({ id: r.id, status: r.status, client: !!r.client_visible,
    uc: r.use_case && ucs[r.use_case] ? `Use case ${ucs[r.use_case]}` : "", milestone: (r.milestone && ms[r.milestone]) || "", workstream: r.workstream || "" });
  const rows = [];
  for (const r of data.actions || []) rows.push({ ...common(r), kind: "action", title: r.description, owner: r.owner, priority: r.priority, due_date: r.due_date, closed: r.closed });
  for (const r of data.raid || []) rows.push({ ...common(r), kind: String(r.type).toLowerCase(), title: r.description, owner: r.owner, priority: r.priority, impact: r.impact, likelihood: r.likelihood, due_date: r.due_date, closed: r.closed });
  for (const r of data.decisions || []) rows.push({ ...common(r), kind: "decision", title: r.decision, owner: r.made_by, priority: null, needed_by: r.needed_by, date: r.date, workstream: "", milestone: "" });
  return rows;
}

// The count line's parts: "1 work item, 1 open." / "2 work items, 1 open." (one is singular, nought and the rest are plural).
export function countOf(total, open) { return { total, open, noun: total === 1 ? "work item" : "work items" }; }

export function metaOf(row) { return [row.id, row.uc, row.milestone, row.workstream].filter(Boolean).join(" · "); }
