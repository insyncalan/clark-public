// The profile circle and its menu (#77, #147), Edit parts only: what the page can do. Publish opens the dialog (#43). Preview opens
// the page as it would be published in a new tab, and Export downloads the project's workbook; both ask the server (publishApi.js)
// and neither publishes or saves a file. Settings is a tab, Help is the Help page. The tooltip lists the entries that carry a short
// word (`tip`), so it follows the entries; Help has none, as its "?" key is its own way in. The accessible name is just "Your menu".
// Appearance (Light, Dark, System) is in the menu (#179); the top line is the name and email from Settings › Personal (#180).
import { useEffect } from "preact/hooks";
import { signal } from "@preact/signals";
import { Menu } from "../components/Menu.jsx";
import { data, tabs, show, project, mode } from "../stores/report.js";
import { openInNewTab } from "../router.js";
import { openHelp } from "../help/helpStore.js";
import { openPublish, lastLine } from "./Publish.jsx";
import { latest } from "./publishState.js";
import { previewRequest, exportRequest, words } from "./publishApi.js";
import { appearance, setAppearance, MODES } from "../stores/appearance.js";
import { profile, loadProfile, wantName } from "../stores/profile.js";

export const MENU_NAME = "Your menu";
const LOOK_WORDS = { light: "Light", dark: "Dark", system: "System" };
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

export async function exportExcel() {
  const r = await exportRequest(project.value);
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
  useEffect(() => { loadProfile(); }, []);
  if (!data.value) return null;      // like the Publish button it replaced: not until the report is loaded, or Publish would open without the project's client folder
  const items = [{ id: "publish", name: "Publish…", tip: "Publish" }, { id: "preview", name: "Preview the page in a new tab", tip: "Preview" },
    { id: "export", name: "Export to Excel", tip: "Export" }];
  if (tabs.value.includes("settings")) items.push({ id: "settings", name: "Settings", tip: "Settings" });
  items.push({ id: "help", name: "Help" });
  const tip = menuTip(items);
  const last = lastLine(latest.value);
  // The last-published note is hidden from the bar in a narrow window, so the menu says it too; a separator sets the settings apart.
  // Appearance (#179; its group is called Appearance in the menu and in Settings): the same three choices as Settings › Personal, in the same order, below the separator that divides the actions
  // (Publish, Preview, Export) from the settings entries; the one in use is marked. One signal feeds both places.
  const look = [{ id: "look-lab", lab: "Appearance" }, ...MODES.map((m) => ({ id: `look-${m}`, name: LOOK_WORDS[m], checked: appearance.value === m }))];
  const actions = items.filter((i) => ["publish", "preview", "export"].includes(i.id)), rest = items.filter((i) => !actions.includes(i));
  // Who you are (#180), the top line: the name in bold with the email under it, or only the name; with neither, a link that opens
  // Settings › Personal and puts the cursor in the name box. Only what was typed in Settings: clark never makes up an email.
  const me = profile.value;
  const who = me.name || me.email ? { id: "who", head: { name: me.name || me.email, line: me.name ? me.email : "", title: [me.name, me.email].filter(Boolean).join("\n") } }
    : { id: "who", name: "Add your name in Settings", link: true };
  const shown = [who, ...(last ? [{ id: "note", lab: last }] : []), ...actions, { id: "sep", sep: true }, ...look, ...(rest.length ? [{ id: "sep", sep: true }] : []), ...rest];   // a separator sets the settings entries apart from the look group
  const pick = (id) => {
    if (id === "publish") openPublish();
    else if (id === "preview") preview();
    else if (id === "export") exportExcel();
    else if (id === "who") { wantName.value = true; show("settings"); }
    else if (id.startsWith("look-")) setAppearance(id.slice(5));
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
