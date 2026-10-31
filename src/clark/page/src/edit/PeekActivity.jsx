// The peek's tabs in Edit (#42): Details (the fields) and Activity (who changed what, how and when, newest first, from
// GET /api/activity). Edit only: View and a published file show the fields and nothing else, so nothing here is in them.
// Every value is drawn as text, never as markup. The tabs follow the usual keys: Left and Right move, Home and End jump.
import { useEffect, useRef, useState } from "preact/hooks";
import { project, data } from "../stores/report.js";
import { peekTab } from "../stores/peekState.js";
import { readActivity } from "./activityApi.js";

const TABS = [["details", "Details"], ["activity", "Activity"]];
const LOADING = "Reading the history…";
const FAILED = "The history could not be read just now. Close the peek and open it again to try once more.";

export function PeekTabs() {
  const list = useRef(null);
  const key = (e) => {
    const i = TABS.findIndex(([k]) => k === peekTab.value);
    const to = e.key === "ArrowRight" ? (i + 1) % TABS.length : e.key === "ArrowLeft" ? (i + TABS.length - 1) % TABS.length
      : e.key === "Home" ? 0 : e.key === "End" ? TABS.length - 1 : -1;
    if (to < 0) return;
    e.preventDefault();
    peekTab.value = TABS[to][0];
    const btn = list.current && list.current.querySelector(`[data-pk-tab=${TABS[to][0]}]`);
    if (btn) btn.focus();
  };
  return (
    <div class="pk-tabs" role="tablist" aria-label="Item details and history" ref={list} onKeyDown={key}>
      {TABS.map(([k, label]) => {
        const on = peekTab.value === k;
        return <button key={k} type="button" role="tab" id={`pk-tab-${k}`} aria-controls={`pk-panel-${k}`} aria-selected={on ? "true" : "false"}
          tabIndex={on ? 0 : -1} class={`pk-tab${on ? " on" : ""}`} data-pk-tab={k} onClick={() => { peekTab.value = k; }}>{label}</button>;
      })}
    </div>
  );
}

function Change({ r }) {
  if (r.kind === "Created") return <p class="pa-what"><span class="pa-kind">Created</span>{r.to ? <span> {r.to}</span> : null}</p>;
  if (r.kind === "Comment") return <p class="pa-what"><span class="pa-kind">Comment</span> {r.to}</p>;
  const pieces = Array.isArray(r.diff) && r.diff.length ? r.diff : null;
  return (
    <p class="pa-what">
      {r.kind !== "Changed" ? <span class="pa-kind">{r.kind} </span> : null}
      <span class="pa-f">{r.field}</span>{": "}
      {pieces ? pieces.map((p, i) => (p.op === "removed" ? <del key={i}>{p.text}</del> : p.op === "added" ? <ins key={i}>{p.text}</ins> : <span key={i}>{p.text}</span>))
        : <>
          <span class="pa-from">{r.from || "nothing"}</span><span aria-hidden="true">{" → "}</span><span class="sr-only"> to </span><span class="pa-to">{r.to || "nothing"}</span>
        </>}
      {r.diff_note ? <span class="muted pa-note"> {r.diff_note}</span> : null}
    </p>
  );
}

export function PeekActivity({ id }) {
  const [got, setGot] = useState(null);           // null: reading; {ok, view}
  const d = data.value;                           // a change anywhere replaces the data, so the tab reads again
  useEffect(() => {
    let live = true;
    readActivity(project.value, id).then((r) => { if (live) setGot(r); });
    return () => { live = false; };
  }, [id, d]);                                    // eslint-disable-line react-hooks/exhaustive-deps
  let body;
  if (!got) body = <p class="muted pa-none" data-activity-loading>{LOADING}</p>;
  else if (!got.ok) body = <p class="muted pa-none" data-activity-failed>{FAILED}</p>;
  else if (!got.view.rows.length) body = <p class="muted pa-none" data-activity-empty>{got.view.empty || "Nothing has changed on this item yet."}</p>;
  else {
    body = (
      <ol class="pa-list" data-activity-rows>
        {got.view.rows.map((r, i) => (
          <li key={i} class="pa-row" data-activity-row>
            <p class="pa-meta"><span class="pa-who">{r.who || "Someone on this computer"}</span>{r.how ? <span> · {r.how}</span> : null}<span> · {r.when_text}</span></p>
            <Change r={r} />
          </li>
        ))}
      </ol>
    );
  }
  return (
    <section class="pk-activity" role="tabpanel" id="pk-panel-activity" aria-labelledby="pk-tab-activity" tabIndex={0} data-activity aria-busy={got ? "false" : "true"}>
      {body}
      {got && got.ok && got.view.closing ? <p class="muted pa-none">{got.view.closing}</p> : null}
    </section>
  );
}
