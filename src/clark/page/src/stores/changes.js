// Changes made on the page (#65): one request at a time, in the order they were made, and the toast that says what happened.
// A change is sent as it is; the page never edits its own copy. It redraws from the sections the reply carries, so what is on
// the page is what clark saved. A failed change draws nothing and the toast says why, in plain words (api.js).
import { signal } from "@preact/signals";
import { data, project, reread } from "./report.js";
import { sendChange, sendUndo, sendItemChange, sendCellChange, sendMilestoneChange } from "../api.js";

// null, or { id, kind: "done" | "note" | "problem", text, undo: the step's id or null, code: the project the step was made in }
export const toast = signal(null);
// Counts the undos that worked, so the Movement block (edit/Movement.jsx) reads its milestones again after one.
export const undone = signal(0);

let counter = 0, tail = Promise.resolve(), timer = 0;
const itemSteps = new Map();             // the steps that changed a work item (#80 cells, #68 board moves), to what their Undo says ("" for "Undone."): their undo reply has no items, so the data is read again

// #197: the steps the toast offered Undo for, newest last, so Cmd or Ctrl+Z (undoKey.js) undoes the last one even after the toast
// has gone. Kept in memory only; a step leaves it once it is undone (by the key or the toast's button).
const undoable = [];
const MAX_KEPT = 50;

export function say(kind, text, undo = null, code = project.value) {
  if (undo) {
    const at = undoable.findIndex((s) => s.step === undo);
    if (at >= 0) undoable.splice(at, 1);
    undoable.push({ step: undo, code });
    if (undoable.length > MAX_KEPT) undoable.shift();
  }
  clearTimeout(timer);
  const id = ++counter;
  toast.value = { id, kind, text, undo, code };
  if (kind !== "problem") timer = setTimeout(() => { if (toast.value && toast.value.id === id) toast.value = null; }, 20000);
}

export function dismiss() {
  clearTimeout(timer);
  toast.value = null;
}

// Draw what the reply carries: the sections, and (#45) the tiles or the project's health and reason when it has them. It is drawn only
// while the page is still on the project the change was made in (`code`): Back or Forward may have moved it to another project while
// the change was on its way, and that project's page must not take this reply's sections, tiles or health. A reply
// never carries a section's body (changes.py SHOWN), so each section keeps what the page already has of it: the reply's fields
// win, the rest stay (#188). readAgain then brings the body as clark stored it.
function redraw(code, reply) {
  if (project.value !== code || !data.value) return;
  const next = { ...data.value };
  if (Array.isArray(reply.sections)) {
    const was = new Map((next.report_sections || []).map((sec) => [sec.id, sec]));
    next.report_sections = reply.sections.map((sec) => ({ ...was.get(sec.id), ...sec }));
  }
  if (Array.isArray(reply.tiles)) next.glance_tiles = reply.tiles;
  if (reply.project && typeof reply.project === "object") next.project = { ...next.project, health: reply.project.health, health_reason: reply.project.health_reason };
  data.value = next;
}

// After a change or an undo the page reads the project again (#188), so a section's body is the one clark stored, not the one the
// page had: a body saved or undone elsewhere must never be written over by the next save. Resolves to false, with a plain line,
// when it could not be read; true when it was, or when the person has opened another project meanwhile (nothing is wrong then).
async function readAgain(code, what) {
  if (await reread(code) || project.value !== code) return true;
  say("problem", `${what}, but the page could not be read again. Reload the page to see it.`);
  return false;
}

// Runs `task` after every earlier one has finished, whether it worked or not.
function enqueue(task) {
  const run = tail.then(task);
  tail = run.catch(() => {});
  return run;
}

// Make one change. Resolves to the reply, or to null when it failed (and the toast says why). `done` is what the toast says
// when it worked; with a step to undo it carries Undo. A change that altered nothing (no step) says nothing.
export function change(req, done) {
  const code = project.value;
  return enqueue(async () => {
    const r = await sendChange(code, req);
    if (!r.ok) { say("problem", r.message); return null; }
    redraw(code, r.reply);
    if (!(await readAgain(code, "The change was saved"))) return r.reply;
    if (r.reply.apply_id) say("done", done, r.reply.apply_id, code);
    return r.reply;
  });
}

// Move one work item on the board (#68): the work items are read again (reread, report.js) after it and after its undo, so
// the page shows what clark saved. `done` is the toast's words; an Undo goes with it only when the reply says the step can be put
// back (a decision made is not). A refusal is a note: nothing was changed and there is nothing to undo.
export function changeItem(req, done) {
  const code = project.value;
  return enqueue(async () => {
    const r = await sendItemChange(code, req);
    if (!r.ok) { say("note", r.message); return null; }
    await reread(code);
    const step = r.reply.undoable === false ? null : r.reply.apply_id;
    if (step) itemSteps.set(step, "");
    say("done", done, step, code);
    return r.reply;
  });
}

// Undo one step, by the id the change's reply gave, in the project the step was made in (`code`; the open one if not given). If
// some rows were left as they are, the toast says which, in the words clark gives (they name the section and why); otherwise it
// says what went back (a work item's cell, #80) or that it is undone.
export function undo(applyId, code = project.value) {
  const at = undoable.findIndex((s) => s.step === applyId);
  if (at >= 0) undoable.splice(at, 1);
  return enqueue(async () => {
    const r = await sendUndo(code, applyId);
    if (!r.ok) { say("problem", r.message); return null; }
    redraw(code, r.reply);
    undone.value++;
    const back = itemSteps.get(applyId);
    itemSteps.delete(applyId);
    // Read again after every undo: an item's cell, or a section's body, comes back from the database. Not read again because the
    // person has opened another project meanwhile: nothing is wrong, so nothing is said about it.
    if (!(await readAgain(code, "The change was undone"))) return r.reply;
    const skipped = Array.isArray(r.reply.skipped) && r.reply.skipped.length > 0;
    say("done", skipped && typeof r.reply.words === "string" && r.reply.words ? r.reply.words : back || "Undone.", null, code);
    return r.reply;
  });
}

// #80: change fields of one work item, in one step. `table` is actions, raid or decisions; `changes` the fields to set. The page
// draws the item as clark saved it (the reply's item), never its own guess. `done.text` is what the toast says; it carries Undo
// when the step can be undone, and `done.back` is what the toast says after that Undo. A decision that is made has none (the reply says so): with `done.always` the toast still says what
// happened. Otherwise a change that altered nothing says nothing.
export function changeCell(table, id, changes, done) {
  const code = project.value;
  return enqueue(async () => {
    const r = await sendCellChange(code, table, id, changes, "cell");
    if (!r.ok) { say("problem", r.message); return null; }
    const item = r.reply.item;
    const d = data.value;
    if (d && project.value === code && Array.isArray(d[table])) {
      data.value = { ...d, [table]: d[table].map((row) => (row.id === item.id ? { ...row, ...item } : row)) };
    }
    const step = r.reply.undoable === true && r.reply.apply_id ? r.reply.apply_id : null;
    if (step) { itemSteps.set(step, done.back || ""); say("done", done.text, step, code); }
    else if (done.always) say("done", done.text, null, code);                   // a decision that is made: it changed, and has no Undo
    return r.reply;
  });
}

// A change to one milestone from the Movement block (#136): one step, one Undo. Resolves to {ok: true, reply} or {ok: false, message};
// a refusal says nothing here (the block shows it where the person is), a success says `done` with Undo.
export function changeMilestone(req, done) {
  const code = project.value;
  return enqueue(async () => {
    const r = await sendMilestoneChange(code, req);
    if (r.ok && r.reply.apply_id) say("done", done, r.reply.apply_id, code);
    return r;
  });
}

// #197: Cmd or Ctrl+Z. Undoes the newest step of the open project that the toast offered Undo for (the same as its button); with none,
// it says "Nothing to undo." Resolves to the undo's reply, or null.
export function undoLast(code = project.value) {
  for (let i = undoable.length - 1; i >= 0; i--) {
    if (undoable[i].code === code) {
      const { step } = undoable[i];
      if (toast.value && toast.value.undo === step) dismiss();
      return undo(step, code);
    }
  }
  say("note", "Nothing to undo.");
  return Promise.resolve(null);
}
