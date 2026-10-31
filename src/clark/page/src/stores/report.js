// The page's state: one signals store (as creaite's src/stores/). The view and the open project are the address, so a
// reload keeps them; the project's data comes from GET /api/data with this run's token (#33, #31's data_for).
// A published file (#39) has its data in an inline block, id="clark-data": then the page is a file (fromFile), reads that block
// and nothing else: no fetch, no token, no Settings tab, and "today" is the date it was published (as_at).
import { signal, computed } from "@preact/signals";
import * as route from "../router.js";
import { rowsOf } from "../workItems.js";
import { decode, encode, fits } from "../filters.js";
import { useFileStyle } from "./style.js";

export const VIEWS = route.VIEWS;
export const TITLES = { dashboard: "Dashboard", work: "Work items", milestones: "Milestones", settings: "Settings" };

// The address (router.js) holds the page, the project and the open peek, so a reload or a bookmark opens the same ones and
// Back and Forward step through them (#63). Each change of page, project or peek goes through navigate() there.
const start = route.current();
export const project = signal(start.project);
export const view = signal(start.view);
export const item = signal(start.item);              // the open peek: a work item's id, or "" (the peek itself is #42)
export const ms = signal(start.ms);                  // ... or a milestone's id
const filterText = signal(start.f);                  // the Work items filters' text, opaque to the router (#64a): see setFilters()
export const f = computed(() => filterText.value);   // read-only: a component changes it only through setFilters()
export const peek = computed(() => (item.value ? { kind: "item", id: item.value } : ms.value ? { kind: "milestone", id: ms.value } : null));
// Work items' filters (filters.js) live in the address as `f` and nowhere else: the state is read from the text each time it changes,
// so a reload, Back and Forward bring the filters back with the page. `openFilter` is which filter's box is open ("" for none).
export const filterState = computed(() => decode(f.value));
export const openFilter = signal("");
export const filterNote = signal("");                // a plain line when a filter could not be added; "" otherwise
export const refusals = signal(0);                   // counts the refusals, so a ticked box that was not kept is drawn unticked again
export const status = signal(project.value ? "loading" : "none");   // none | loading | ready | missing | failed
export const data = signal(null);
export const message = signal("");
export const fromFile = signal(false);       // true when the page is a published file (#39): it never edits and never asks a server
export const mode = signal("view");          // view | edit (#65): memory only, never in the database or the address, so a reload is View
export const dropAt = signal(undefined);     // Edit, while a section is dragged: what to draw (logic/placement.js indicator: { line: "before", ids } | { line: "end" } | { outline, side }), undefined for none
export const asAt = signal("");              // view mode: the publish date, YYYY-MM-DD; due dates and Overdue read as at this
export const tabs = signal(VIEWS);           // the views the tab bar offers; a published file has no Settings
export const moves = signal(0);              // counts Back and Forward (and a typed address): a menu that is open closes on each
export const projects = signal([]);                 // [{code, name}] from GET /api/projects
export const projectsState = signal("loading");     // loading | ready | failed

export const rows = computed(() => (data.value ? rowsOf(data.value) : []));

export const counts = computed(() => {
  const d = data.value;
  return d ? { work: d.actions.length + d.raid.length + d.decisions.length, milestones: d.milestones.length } : { work: 0, milestones: 0 };
});

let openedF = null;                                  // null: not known (a reload or a restored tab), so closing rewrites the entry

const where = () => ({ view: view.value, project: project.value, item: item.value, ms: ms.value, f: filterText.value });

// Draw the page from an address: the signals follow it, and a project that changed is read again. A published file has one
// project and only its own tabs: an address that names another project or a tab the file does not have (typed, or a Back to it)
// stays on the file's project and opens its first tab, as a reload of that address does.
function apply(s) {
  if (fromFile.value) s = { ...s, project: project.value, view: tabs.value.includes(s.view) ? s.view : (tabs.value[0] || s.view) };
  if (s.view !== view.value || s.project !== project.value) { openFilter.value = ""; filterNote.value = ""; }   // a filter change keeps its box open
  view.value = s.view;
  item.value = s.item;
  ms.value = s.ms;
  filterText.value = s.f;
  if (s.project !== project.value) {
    project.value = s.project;
    data.value = null;
    status.value = s.project ? "loading" : "none";
    load();
  } else {
    settle();
  }
}

// Whether the loaded data has a work item (`milestone` false) or a milestone with this id.
function known(d, id, milestone) {
  return !!d && (milestone ? d.milestones.some((m) => m.id === id) : [...d.actions, ...d.raid, ...d.decisions].some((r) => r.id === id));
}

// Move to `s` through the router and draw it. Drawn from `s` itself (made well-formed as the router makes it), not from the
// address: if the router could not set the address at all it has not moved, and the page must still change.
function go(s, options) {
  if (route.navigate(s, options)) apply(route.parse(route.format(s)));
}

// A peek whose item or milestone isn't in the project's data (deleted, mistyped, from an old link) opens the page with no
// peek: the entry is rewritten, not added.
function settle() {
  const d = data.value;
  if (!d || status.value !== "ready" || (!item.value && !ms.value)) return;
  if (item.value ? known(d, item.value, false) : known(d, ms.value, true)) return;
  item.value = "";
  ms.value = "";
  route.navigate(where(), { replace: true });
}

// Back and Forward (the trackpad swipe, the mouse buttons, the keyboard) with something still open on the page. What is being typed
// (a section's title) is kept: the field is left first, so it is saved as a click on a tab saves it, to the project it belongs to,
// before the page moves, and the message says so, with Undo. A menu, a filter's box or a drag closes, and nothing is chosen. The
// peek has an entry of its own (closing it is a Back), so the page redraws after this as it would anyway.
function leave() {
  const el = document.activeElement;
  const typing = !!el && el !== document.body && (el.isContentEditable || el.tagName === "TEXTAREA" ||
    (el.tagName === "INPUT" && /^(text|search)$/.test(el.type)));
  if (typing && typeof el.blur === "function") el.blur();
  openFilter.value = "";
  dropAt.value = undefined;
  moves.value++;
}

route.onPop((s) => { leave(); apply(s); });

/** Go to a page: one new entry; an open peek closes, and so do the filters (they belong to one page). */
export function show(next) {
  go({ view: next, project: project.value, item: "", ms: "", f: "" });
}

/** Open Work items with a filter state already set (an At a glance tile, #79): one new entry, as any change of page is. */
export function openWork(state) {
  go({ view: "work", project: project.value, item: "", ms: "", f: fits(state) ? encode(state) : "" });
}

/** Open a work item's or a milestone's peek (`kind` "milestone" or "item"; left out, the project's data says which): one new entry; with a peek already open, this entry is rewritten (Previous, Next, another row). An id the loaded data doesn't have does nothing. */
export function openPeek(id, kind) {
  const d = data.value;
  if (!peek.value) openedF = filterText.value;           // the filters as they were when the peek opened: closing steps Back only if they still are
  const milestone = kind ? kind === "milestone" : known(d, id, true);
  if (d && !known(d, id, milestone)) return;               // with no data loaded there is nothing to check it against: open it
  go({ ...where(), item: milestone ? "" : id, ms: milestone ? id : "" }, { replace: !!peek.value });
}

/** Close the peek: Back if a click opened it (so no entry stays behind), else this entry is rewritten without it. A Back that
 *  goes nowhere (a restored tab whose stack is gone) falls back to the rewrite. */
export function closePeek() {
  if (!peek.value) return;
  const rewrite = () => go({ ...where(), item: "", ms: "" }, { replace: true });
  // Back would also take away a filter changed while the peek was open (that change rewrote this entry), so then the entry is rewritten.
  if (route.peekWasPushed() && openedF === filterText.value && route.back(rewrite)) return;       // onPop redraws
  rewrite();
}

/** Switch project: one new entry (and any peek and the filters close), so Back returns to the earlier one. */
export function setProject(code) {
  if (!route.isProject(code)) return;
  go({ view: view.value, project: code, item: "", ms: "", f: "" });
}

/** A filter change (#64a): `text` goes in the address as `f`, exactly as given (the router does not read, decode or encode it; the
 *  caller encodes it, and an untrustworthy text becomes ''). It rewrites the entry, so Back never stops on a filter. */
export function setFilters(text) {
  go({ ...where(), f: text }, { replace: true });
}

/** A filter change from the Work items page: the state is encoded (filters.js) into `f`. If it would not fit in the address, nothing
 *  changes and a plain line says why. */
export function setFilterState(next) {
  if (!fits(next)) {
    refusals.value++;
    filterNote.value = "That filter would not fit in the page's address, so it was not added. Remove another filter first.";
    return;
  }
  filterNote.value = "";
  setFilters(encode(next));
}

// Open a project chosen from the list: one new entry, so the address takes its code (a reload keeps it) and its data is read.
export function openProject(code) {
  setProject(code);
}

// The published file's data block: null when the page is the editor's, "bad" when the block is there but is not ours.
function published() {
  const el = document.getElementById("clark-data");
  if (!el) return document.documentElement.dataset.mode === "view" ? "bad" : null;
  try {
    const p = JSON.parse(el.textContent);
    return p && p.v === 1 && p.data && p.data.project && Array.isArray(p.tabs) ? p : "bad";
  } catch (e) { return "bad"; }
}

function openPublished(p) {
  fromFile.value = true;
  mode.value = "view";
  if (p === "bad") { tabs.value = []; status.value = "failed"; message.value = "This report's data could not be read."; return; }
  tabs.value = VIEWS.filter((v) => p.tabs.includes(v));
  if (!tabs.value.includes(view.value)) view.value = tabs.value[0];
  project.value = p.data.project.code;
  asAt.value = p.as_at || "";
  useFileStyle(p.style);                                  // the look it was published with (#45); a file written before that has the default
  data.value = { ...p.data, report_sections: Array.isArray(p.sections) ? p.sections : [] };     // the file holds only the sections that show
  status.value = "ready";
  settle();
}

export function token() {
  try { return JSON.parse(document.getElementById("clark-boot").textContent).token; } catch (e) { return ""; }
}

let reading = 0;                                       // the newest read wins when the project changed meanwhile

// What the page says when clark could not give the data. The page never shows the server's own text, because it might be a
// program's error name or a technical phrase: it looks the server's message up here by the HTTP status, and a message it does not
// know (or none at all) gets the plain fallback for that status. Every line says what to do next. A status of 0 is "no answer".
const READ_FAILED = "clark could not read this project. Reload the page. If it happens again, restart clark.";
const STALE = "clark was restarted after you opened this page. Reload the page and try again.";
const BAD_CODE = "Use a project code of 3 to 7 capital letters or digits.";
const NO_PROJECT = "There is no project with that code. Check the code in the address, or choose a project from the list.";
const NOT_ACCEPTED = "clark did not accept that request. Reload the page.";
const ALLOWED = {
  400: { fallback: "clark could not read that request. Reload the page.",
         known: { [BAD_CODE]: BAD_CODE } },
  403: { fallback: NOT_ACCEPTED,
         known: { "Not allowed": NOT_ACCEPTED, [NOT_ACCEPTED]: NOT_ACCEPTED, [STALE]: STALE,
                  "The server was restarted since this page was opened. Reload the page (Cmd+R) and try again.": STALE } },
  404: { fallback: "Check the project's code.",
         known: { [NO_PROJECT]: NO_PROJECT,
                  "There is no project with that code.": NO_PROJECT } },
  500: { fallback: "clark hit a problem reading this project. Reload the page. If it happens again, restart clark.", known: {} },
  0: { fallback: "clark has stopped. It stops by itself after a while with nothing open. Start it again from clark.command.", known: {} },
};
export function plain(code, body) {
  const row = ALLOWED[code];
  if (!row) return READ_FAILED;
  const said = body && typeof body.message === "string" ? body.message : "";
  if (code === 403 && body && body.stale === true) return STALE;
  return Object.prototype.hasOwnProperty.call(row.known, said) ? row.known[said] : row.fallback;
}

// What the page says when a change or an undo (api.js) failed, by the same rule as plain(): the status picks the words, and a
// message from the server is used only to pick one of these, never shown. Each says that nothing was changed (or what is
// still true) and what to do next.
const CHANGE_FAILED = "clark could not make that change, and nothing was changed. Reload the page and try again.";
const CHANGE_KNOWN = {
  "Your page is out of date. Reload it, then try again.": "The report has changed since you opened it, and nothing was changed. Reload the page and try again.",
  "That section isn't in this project.": "That section is no longer in this report, and nothing was changed. Reload the page.",
  "That step can't be undone from here.": "That change can't be undone any more. Reload the page to see how the report is now.",
  "That step has been undone already.": "That change has been undone already. Reload the page to see how the report is now.",
  // #80: a work item change clark would not make (clark/changes.py's words; the page says its own)
  "That item isn't in this project.": "That item is no longer in this project, and nothing was changed. Reload the page.",
  "Pick a real date.": "That date isn't a real day, and nothing was changed. Pick another date.",
  "That status isn't available for this item.": "That status isn't one this item can have, and nothing was changed.",
  "A decision that is made needs the date it was made.": "A made decision needs the date it was made, and nothing was changed. Pick a date.",
  "A decision that isn't made yet has no date.": "A decision that isn't made yet has no decision date, and nothing was changed.",
  "A decision that has been made can't go back to pending. Record a new decision that replaces it.":
    "A decision that has been made can't go back to pending, and nothing was changed. Record a new decision that replaces it.",
  "A decision that has been made can't be put back. Record a new decision that replaces it.":
    "That decision has been made, so it was left as it is. Record a new decision that replaces it.",
  "Use plain text, with no line breaks or hidden characters.": "A name can only be plain text, with no line breaks or hidden characters. Nothing was changed.",
  "That value isn't one clark can use.": "That value can't be used, and nothing was changed. Try another.",
};
export function plainChange(code, body) {
  const said = body && typeof body.message === "string" ? body.message : "";
  const known = Object.prototype.hasOwnProperty.call(CHANGE_KNOWN, said) ? CHANGE_KNOWN[said] : "";
  if (code === 400 || code === 409) return known || CHANGE_FAILED;
  if (code === 403 || code === 0) return plain(code, body);
  if (code === 404) return "clark could not find this project, and nothing was changed. Check the code in the address, then reload the page.";
  if (code === 500) return "clark hit a problem saving that, and nothing was changed. Try again. If it happens again, restart clark.";
  if (code === 503) return "clark could not save just now, and nothing was changed. Wait a moment and try again. If it keeps happening, restart clark.";
  return CHANGE_FAILED;
}

const LIST_FAILED = "clark could not read the list of projects. Reload the page. If it happens again, restart clark.";
// The list's own words, picked by status like plain(): a refusal or no answer says what plain() says; anything else is LIST_FAILED.
function plainList(code, body) {
  return code === 0 || code === 400 || code === 403 ? plain(code, body) : LIST_FAILED;
}

// The projects to choose from (GET /api/projects) when the address names none. "There are no projects yet" is said only when the
// list was read and is empty: a list that could not be read says so, with Try again.
export async function loadProjects() {
  projectsState.value = "loading";
  try {
    const r = await fetch("/api/projects", { headers: { "X-Clark-Token": token() }, cache: "no-store" });
    const body = await r.json().catch(() => ({}));
    if (!r.ok || !body.ok || !Array.isArray(body.projects)) {
      projects.value = []; projectsState.value = "failed"; message.value = plainList(r.status, body);
      return;
    }
    projects.value = body.projects;
    projectsState.value = "ready";
  } catch (e) {
    projects.value = []; projectsState.value = "failed"; message.value = plain(0);
  }
}

export async function load() {
  const p = published();
  if (p) return openPublished(p);          // a published file never asks a server for anything
  const code = project.value;
  const mine = ++reading;
  if (!code) { status.value = "none"; return loadProjects(); }
  status.value = "loading";
  try {
    const r = await fetch(`/api/data?project=${encodeURIComponent(code)}`, { headers: { "X-Clark-Token": token() } });
    const body = await r.json().catch(() => ({}));
    if (mine !== reading) return;
    if (r.status === 404) { status.value = "missing"; message.value = plain(404, body); return; }
    if (!r.ok || !body.ok) { status.value = "failed"; message.value = plain(r.status, body); return; }
    data.value = body.data;
    status.value = "ready";
    settle();
  } catch (e) {
    if (mine !== reading) return;
    status.value = "failed";
    message.value = plain(0);
  }
}

/** Read the open project's data again without redrawing the page as loading (#80: after an undo of a work item change, whose
 *  reply carries no items). Resolves to true when the data was read and drawn; false leaves the page as it is. */
export async function reread(code) {
  if (fromFile.value || !code || code !== project.value) return false;
  try {
    const r = await fetch(`/api/data?project=${encodeURIComponent(code)}`, { headers: { "X-Clark-Token": token() }, cache: "no-store" });
    const body = await r.json().catch(() => ({}));
    if (!r.ok || !body.ok || !body.data || code !== project.value) return false;
    data.value = body.data;
    settle();
    return true;
  } catch (e) {
    return false;
  }
}

// "Try again": a page that clark would not accept has a token from an earlier run, so only a reload of the page helps.
export function tryAgain() {
  if (message.value === STALE || message.value === NOT_ACCEPTED) location.reload(); else load();
}
