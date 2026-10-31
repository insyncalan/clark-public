// The profile circle and its menu (#77, #147), Edit parts only: what the page can do. Publish opens the dialog (#43). Preview opens
// the page as it would be published in a new tab, and Export downloads the project's workbook; both ask the server (publishApi.js)
// and neither publishes or saves a file. Settings is a tab, Help is the Help page. The tooltip lists the entries that carry a short
// word (`tip`), so it follows the entries; Help has none, as its "?" key is its own way in. The accessible name is just "Your menu".
// There is no dark-mode setting in the page and no profile (name or email) to show, so the menu has neither.
import { signal } from "@preact/signals";
import { Menu } from "../components/Menu.jsx";
import { data, tabs, show, project, mode } from "../stores/report.js";
import { openInNewTab } from "../router.js";
import { openHelp } from "../help/helpStore.js";
import { openPublish, lastLine } from "./Publish.jsx";
import { latest } from "./publishState.js";
import { previewRequest, exportRequest, words } from "./publishApi.js";

export const MENU_NAME = "Your menu";
export const menuTip = (items) => `${MENU_NAME}: ${items.filter((i) => i.tip).map((i) => i.tip).join(", ")}`;

// What Preview or Export did, in words, until it is closed (or 20 seconds). The change toast is for Edit only, and this menu is in View too.
export const note = signal(null);
let noteTimer = 0, noteId = 0;
function say(kind, text) {
  clearTimeout(noteTimer);
  const id = ++noteId;
  note.value = { id, kind, text };
  if (kind !== "problem") noteTimer = setTimeout(() => { if (note.value && note.value.id === id) note.value = null; }, 20000);
}
const closeNote = () => { clearTimeout(noteTimer); note.value = null; };

// The note itself. There is one live region on the page: in Edit it is the change toast's (Toast.jsx shows this note in it, so
// the two never sit on top of each other), and in View, where there is no change toast, the menu has its own.
export function MenuNote() {
  const n = note.value;
  return n ? (
    <div class={`toast ${n.kind}`} key={n.id} data-kind={n.kind} role={n.kind === "problem" ? "alert" : undefined}>
      <span class="toast-text">{n.text}</span>
      <button type="button" class="toast-btn" data-dismiss aria-label="Dismiss this message" onClick={closeNote}>Close</button>
    </div>
  ) : null;
}

const isAnswer = (r) => r.body && typeof r.body.message === "string" && typeof r.body.code === "string";

// The new tab is opened first and pointed at the page by the router (openInNewTab), which is the one place that sets an address.
export async function preview() {
  let r = null;
  const opened = await openInNewTab(async () => {
    r = await previewRequest(project.value);
    return r.status === 200 && r.body && typeof r.body.url === "string" ? r.body.url : null;
  });
  if (opened) { say("note", r.body.message); return; }
  say("problem", r && r.status === 200 ? "The preview could not be opened. Allow pop-ups for this page, then try again." : words(r, "preview"));
}

let exporting = false;                               // one export at a time: a second click while one runs does nothing (#181)

export async function exportExcel() {
  if (exporting) return;
  exporting = true;
  let r;
  try { r = await exportRequest(project.value); } finally { exporting = false; }
  if (r.status !== 200 || !r.blob) {
    say("problem", isAnswer(r) && [400, 404, 409].includes(r.status) ? r.body.message : words(r, "export"));
    return;
  }
  // A download anchor on a blob: this saves a file, it does not navigate (only router.js touches history or the address).
  const url = URL.createObjectURL(r.blob), a = document.createElement("a");
  a.href = url; a.download = r.name || `${project.value}.xlsx`; a.hidden = true;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
  say("done", `Your browser has saved “${a.download}”.${r.warning ? " " + r.warning : ""}`);
}

export function ProfileMenu() {
  if (!data.value) return null;      // like the Publish button it replaced: not until the report is loaded, or Publish would open without the project's client folder
  const items = [{ id: "publish", name: "Publish…", tip: "Publish" }, { id: "preview", name: "Preview the page in a new tab", tip: "Preview" },
    { id: "export", name: "Export to Excel", tip: "Export" }];
  if (tabs.value.includes("settings")) items.push({ id: "settings", name: "Settings", tip: "Settings" });
  items.push({ id: "help", name: "Help" });
  const tip = menuTip(items);
  const last = lastLine(latest.value);
  // The last-published note is hidden from the bar in a narrow window, so the menu says it too; a separator sets the settings apart.
  const shown = [...(last ? [{ id: "note", lab: last }] : []), ...items.flatMap((i) => (i.id === "settings" || (i.id === "help" && !tabs.value.includes("settings")) ? [{ id: "sep", sep: true }, i] : [i]))];
  const pick = (id) => {
    if (id === "publish") openPublish();
    else if (id === "preview") preview();
    else if (id === "export") exportExcel();
    else if (id === "settings") show("settings");
    else if (id === "help") openHelp();
  };
  return (
    <>
      <Menu id="profile-btn" btnCls="me" icon="user" label="" chevron={false} ariaLabel={MENU_NAME} tip={tip} menuId="profile-menu" menuLabel={MENU_NAME} items={shown} onPick={pick} />
      {mode.value === "edit" ? null : <div class="toasts" role="status" aria-live="polite"><MenuNote /></div>}
    </>
  );
}
