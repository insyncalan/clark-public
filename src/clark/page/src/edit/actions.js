// What each edit control asks of clark: one change, one request, one toast (stores/changes.js). The ordered list is the one on
// the page (data.report_sections), which is the one clark last sent. Nothing here edits it.
import { data } from "../stores/report.js";
import { change } from "../stores/changes.js";
import { keep } from "./focus.js";
import { note } from "./notes.js";
import { plan as planTemplate } from "../logic/templates.js";
import { place, step, beside as besideOf, fullWidth as fullOf, rows } from "../logic/placement.js";

export const TITLE_MAX = 120;

const list = () => (data.value && data.value.report_sections) || [];
const indexOf = (id) => list().findIndex((s) => s.id === id);

export function titleProblem(text) {
  if (!text) return "A title can't be blank. The old title was kept. Type a new title to change it.";
  const n = Array.from(text).length;
  if (n > TITLE_MAX) return `A title can be ${TITLE_MAX} characters at most, and this one has ${n}. The old title was kept. Shorten it and try again.`;
  return "";
}

// Every move is worked out by logic/placement.js (rows of one or two, never three) and sent as one change with one Undo.
// A refusal says why in a note, or nothing at all when there is nothing to say (dropped where it already is).
const run = (result, id, where, part) => {
  if (!result.ok) {
    if (!result.quiet) note(result.message);
    return Promise.resolve(null);
  }
  const done = change({ ...result.payload, place: where }, result.words);
  return part ? keep(done, id, part) : done;
};

// Move section `id` to `target`: { before: id | null } (a row of its own) or { beside: id, side: "left" | "right" }.
export function placeAt(id, target, where, part) { return run(place(list(), id, target), id, where, part); }
export function moveUp(id, where, part) { return run(step(list(), id, -1), id, where, part); }
export function moveDown(id, where, part) { return run(step(list(), id, 1), id, where, part); }
export function besideNext(id, where, part) { return run(besideOf(list(), id), id, where, part); }
export function fullWidth(id, where, part) { return run(fullOf(list(), id), id, where, part); }
// What each of those would do, without doing it: { ok } or { ok: false, message }.
export const canStep = (id, dir) => step(list(), id, dir);
export const canBeside = (id) => besideOf(list(), id);
export const inPair = (id) => rows(list()).some((r) => r.length === 2 && r.some((s) => s.id === id));

export function rename(id, title) {
  return change({ op: "update", id, changes: { title }, place: "cell" }, "Title changed.");
}
export function setHidden(id, hidden, place, part) {
  const done = change({ op: "update", id, changes: { hidden: hidden ? 1 : 0 }, place }, hidden ? "Section left out of the published page." : "Section included in the published page.");
  return part ? keep(done, id, part) : done;
}
// Add a text section just below section `after` (null: at the end). Its title takes focus, selected.
export function add(after, place) {
  return keep(change({ op: "new", values: { type: "text" }, after, place }, "Section added."), "new", "title");
}
// The same, but below the whole row that holds `after`: after the second half of a pair, so the pair stays as it was.
export function addBelowRow(after, place) {
  const row = after ? rows(list()).find((r) => r.some((s) => s.id === after)) : null;
  return add(row ? row[row.length - 1].id : after || null, place);
}
export function remove(id, place) {
  const i = indexOf(id), all = list();
  const next = all[i + 1] || all[i - 1];
  const done = change({ op: "delete", id, place }, "Section deleted.");
  return next ? keep(done, next.id, "handle") : done;
}

// Add template `id` below section `after` (null: at the end), alone or beside the next section (logic/templates.js plan). The
// requests go one after another; a request whose id is "$new" means the section the first one made. Resolves to the first
// reply, or to null when nothing was added (a refusal in a note, or clark said no in the toast). The new section's title takes focus.
export async function addFromTemplate(id, after, beside) {
  const p = planTemplate(list(), id, after, beside);
  if (!p.ok) { note(p.message); return null; }
  let first = null;
  for (const req of p.requests) {
    const r = await change(req.id === "$new" ? { ...req, id: first.ref } : req, p.words);
    if (!r) return first;                                   // the toast says why; what was made stays made, with its own Undo
    if (!first) first = r;
  }
  keep(Promise.resolve(first), "new", "title");
  return first;
}
