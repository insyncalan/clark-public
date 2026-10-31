// The page's only way to change anything: POST /api/change and POST /api/undo (#65). No other file names these two routes, so a
// build that leaves this file out (the published page, view.jsx) has no way to change a thing and no mention of them.
// Every reply is turned into plain words here: the page never shows the server's own text, only what plainChange (report.js)
// picks for the status, or for a message it knows.
import { token, plainChange } from "./stores/report.js";
import { knownRefusal } from "./edit/movementWords.js";

const KIND = "report_sections";

// {ok: true, reply} or {ok: false, message}: never a throw, whatever the network or the server did.
// `fits(reply)` says whether a 200 reply has what the page needs: a section change's and an undo's carry the sections, a work
// item change's (#80) carries the item.
const hasSections = (reply) => Array.isArray(reply.sections);
const hasItem = (reply) => !!reply.item && typeof reply.item === "object" && typeof reply.item.id === "string";

async function post(path, body, fits = hasSections) {
  try {
    const r = await fetch(path, {
      method: "POST",
      headers: { "X-Clark-Token": token(), "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const reply = await r.json().catch(() => null);
    if (!r.ok || !reply || reply.ok !== true || !fits(reply)) return { ok: false, message: plainChange(r.ok ? 500 : r.status, reply) };
    return { ok: true, reply };
  } catch (e) {
    return { ok: false, message: plainChange(0) };
  }
}

// A work item change (#68): the reply carries the changed row, not the sections. The server's refusals of these are fixed plain
// sentences (changes.py), so a short one is shown as it is; anything else gets plainChange's words.
async function postItem(path, body, fits = (r) => !!r.item) {
  try {
    const r = await fetch(path, {
      method: "POST",
      headers: { "X-Clark-Token": token(), "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const reply = await r.json().catch(() => null);
    if (r.ok && reply && reply.ok === true && fits(reply)) return { ok: true, reply };
    const said = reply && typeof reply.message === "string" ? reply.message : "";
    const mine = (r.status === 400 || r.status === 409) && said && said.length <= 200 && !/[\u0000-\u001f]/.test(said);
    return { ok: false, message: mine ? said : plainChange(r.ok ? 500 : r.status, reply) };
  } catch (e) {
    return { ok: false, message: plainChange(0) };
  }
}

// An archive, or a copy of an item (#97): the reply says the step (apply_id) and the record, with no sections.
export const sendRecordChange = (project, req) => postItem("/api/change", { ...req, project }, (r) => typeof r.apply_id === "number");

// `req` is the change's own parts: op, id, values, changes, before, after, place (see clark/changes.py). `kind` is report_sections
// unless the request says otherwise (#45: glance_tiles and projects reply with tiles or the project, not the sections).
export const sendChange = (project, req) => post("/api/change", { project, kind: KIND, ...req }, !req.kind || req.kind === KIND ? hasSections : () => true);
export const sendUndo = (project, applyId) => post("/api/undo", { project, apply_id: applyId });
// #80: change fields of one work item from its cell (`table` actions, raid or decisions; `changes` only the fields
// clark/changes.py takes for it). A refusal is said in the page's own words (plainChange), never the server's.
export const sendCellChange = (project, table, id, changes, place) =>
  post("/api/change", { project, kind: table, op: "update", id, changes, place }, hasItem);
// A board move (#68): `req` is {kind: actions | raid | decisions, op, id, changes, place} as logic/board.js moveFor builds it.
export const sendItemChange = (project, req) => postItem("/api/change", { ...req, project });

// One change to a milestone from the Movement block (#136), in the Movement place (clark/changes.py). {ok: true, reply} or
// {ok: false, message, known}: `known` is true when the message is clark's own fixed refusal (shown as it is).
export async function sendMilestoneChange(project, req) {
  try {
    const r = await fetch("/api/change", {
      method: "POST",
      headers: { "X-Clark-Token": token(), "Content-Type": "application/json" },
      body: JSON.stringify({ project, kind: "milestones", op: "update", place: "movement", ...req }),
      cache: "no-store",
    });
    const reply = await r.json().catch(() => null);
    if (r.ok && reply && reply.ok === true) return { ok: true, reply };
    const said = reply && typeof reply.message === "string" ? knownRefusal(reply.message) : "";
    if (said && (r.status === 400 || r.status === 409)) return { ok: false, message: said, known: true };
    return { ok: false, message: plainChange(r.ok ? 500 : r.status, reply), known: false };
  } catch (e) {
    return { ok: false, message: plainChange(0), known: false };
  }
}
