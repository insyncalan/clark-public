// Publish: its dialog (#43) and the last-published note in the top bar of a page clark serves (Edit parts only: a published file
// has none). The command itself is in the profile menu (#77), which calls `open`. The dialog
// is a native <dialog> opened as a modal, so Tab stays inside it and Esc cancels; it is in the page only while it is open, so
// View has no form field in it. Local is ticked and disabled. To client is unticked every time, and disabled until the project
// has a client folder (Settings). The words are the spec's (docs/handoff/design-43-to-client.md).
import { useEffect, useRef } from "preact/hooks";
import { data, project } from "../stores/report.js";
import { dialog, latest, NO_FOLDER, folderName, open, tick, pick, rename, confirmOverwrite, ready, cancel, go, refreshLatest } from "./publishState.js";

const shownDate = (iso) => (/^\d{4}-\d\d-\d\d$/.test(iso) ? iso.slice(8) + "-" + iso.slice(5, 7) + "-" + iso.slice(0, 4) : iso);
export const lastLine = (l) => (l ? `Published ${shownDate(l.at)} ${l.to_client ? "to the client" : "locally"}` : "");

function Dialog() {
  const s = dialog.value, el = useRef(null);
  const d = data.value, p = d && d.project;
  useEffect(() => {
    const dlg = el.current;
    if (dlg && !dlg.open) dlg.showModal();
    return () => {      // the menu item that opened it is gone: focus goes back to the profile circle
      if (dlg && dlg.open) dlg.close();
      const me = document.getElementById("profile-btn");
      if (me) me.focus();
    };
  }, []);
  // Where focus goes: the To client tick when it can be ticked, else the button; the question's chosen answer when it is asked.
  useEffect(() => {
    const dlg = el.current;
    if (!dlg) return;
    const target = s.phase === "clash" ? dlg.querySelector(s.choice === "rename" ? "#pub-name" : "input[name=clash]:checked") : s.phase === "done" ? dlg.querySelector("[data-go]")
      : dlg.querySelector("#pub-client:not([disabled])") || dlg.querySelector("[data-go]");
    if (target) target.focus();
  }, [s.phase, s.phase === "clash" ? s.choice : ""]);
  const working = s.phase === "working", clash = s.clash;
  const stateWords = lastLine(latest.value);
  return (
    <dialog id="publish-dialog" class="dlg" aria-labelledby="pub-title" ref={el} onCancel={(e) => { e.preventDefault(); cancel(); }}>
      <form class="dlg-form" onSubmit={(e) => { e.preventDefault(); go(); }}>
        <h2 id="pub-title">{s.phase === "clash" ? clash.title : "Publish the report"}</h2>
        {s.phase === "clash" ? null : (
          <p class="muted dlg-sub">{p ? p.name : project.value}{p && p.week_ending ? ` · week ending ${shownDate(p.week_ending)}` : ""}{stateWords ? ` · ${stateWords}` : ""}</p>
        )}
        {s.phase === "clash" ? (
          <fieldset class="pub-clash">
            <legend class="sr-only">What should clark do?</legend>
            <label class="pubopt"><input type="radio" name="clash" value="number" checked={s.choice === "number"} onChange={() => pick("number")} />
              <span><b>Add a number</b>{clash.numbered ? <small>saves as “{clash.numbered}”</small> : null}</span></label>
            <label class="pubopt"><input type="radio" name="clash" value="rename" checked={s.choice === "rename"} onChange={() => pick("rename")} />
              <span><b>Rename it</b></span></label>
            {s.choice === "rename" ? (
              <label class="pub-field">New file name
                <input type="text" id="pub-name" value={s.newName} onInput={(e) => rename(e.currentTarget.value)} autocomplete="off" spellcheck={false} />
              </label>
            ) : null}
            {clash.canOverwrite ? (
              <label class="pubopt"><input type="radio" name="clash" value="overwrite" checked={s.choice === "overwrite"} onChange={() => pick("overwrite")} />
                <span><b>Overwrite the existing file</b></span></label>
            ) : null}
            {s.choice === "overwrite" ? (
              <div class="pub-note">
                <p>{clash.note}</p>
                <label class="pubopt"><input type="checkbox" id="pub-confirm" checked={s.confirmed} onChange={(e) => confirmOverwrite(e.currentTarget.checked)} />
                  <span>Yes, replace the file in the client folder</span></label>
              </div>
            ) : null}
          </fieldset>
        ) : (
          <div class="pubopts">
            <label class="pubopt"><input type="checkbox" id="pub-local" checked disabled />
              <span><b>Local</b><small>Always. You choose the folder and name in the save window.</small></span></label>
            <label class={`pubopt${s.saved ? "" : " off"}`}><input type="checkbox" id="pub-client" checked={s.ticked} disabled={!s.saved || working} onChange={(e) => tick(e.currentTarget.checked)} />
              <span><b>To client</b><small>{s.saved ? `Copied to the client folder: ${folderName(s.saved)}` : NO_FOLDER}</small></span></label>
          </div>
        )}
        {s.phase !== "clash" && s.ticked ? <p class="muted dlg-warn" id="pub-warn">The client will see this page.</p> : null}
        <div class="pub-msg" id="pub-msg" role={s.message && s.message.kind === "error" ? "alert" : "status"} aria-live="polite">
          {working ? "Publishing…" : s.message ? <p class={s.message.kind}>{s.message.text}</p> : null}
        </div>
        <div class="dlg-f">
          {s.phase === "done" ? null : <button type="button" class="btn quiet" data-cancel onClick={cancel} disabled={working}>Cancel</button>}
          <button type="submit" class="btn pri" data-go disabled={working || !ready(s)}>
            {s.phase === "done" ? "Close" : s.phase === "clash" ? "OK" : s.ticked ? "Publish and send to the client" : "Publish locally"}
          </button>
        </div>
      </form>
    </dialog>
  );
}

export { open as openPublish };
export function Publish() {
  useEffect(() => { refreshLatest(); }, [project.value]);
  if (!data.value) return null;
  const note = lastLine(latest.value);
  return (
    <>
      <span class="pubbar">
        {note ? <span class="pubnote num" id="pub-note">{note}</span> : null}
      </span>
      {dialog.value ? <Dialog /> : null}
    </>
  );
}
