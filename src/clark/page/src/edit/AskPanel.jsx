// The ask panel (#47a): a full-height panel on the right, over the open page. Edit pages only (a published file has none). A stub
// look, built from the page's own tokens; the real look (#102) lands over it. The reply is drawn as text only: it is never read as
// markup. Nothing is sent while asking is off.
import { useEffect, useRef, useState } from "preact/hooks";
import { project, show, token } from "../stores/report.js";
import { words } from "./publishApi.js";
import { panelOpen, panelState, panelModel, panelWidth, panelFocus, turns, pending, closePanel, setWidth, clampWidth, nextQuip, quipDelay } from "./askPanelState.js";
import * as W from "./askWords.js";
import { ChangeCards, fixedLine } from "./AskChange.jsx";
import { AskOffer } from "./AskOffer.jsx";

async function post(path, body) {
  try {
    const r = await fetch(path, { method: "POST", headers: { "X-Clark-Token": token(), "Content-Type": "application/json" }, body: JSON.stringify(body), cache: "no-store" });
    return { status: r.status, body: await r.json().catch(() => null) };
  } catch (e) {
    return { status: 0, body: null };
  }
}

export function AskPanel() {
  const open = panelOpen.value, state = panelState.value, model = panelModel.value, width = panelWidth.value;
  const list = turns.value, busy = pending.value;
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const [quip, setQuip] = useState("");
  const box = useRef(null), log = useRef(null);

  useEffect(() => { if (open && state === "ready" && box.current) box.current.focus(); else if (open) { const c = document.getElementById("ask-panel"); if (c) c.focus(); } }, [open, state, panelFocus.value]);
  useEffect(() => { if (log.current) log.current.scrollTop = log.current.scrollHeight; }, [list.length, busy]);
  useEffect(() => {
    if (!busy) { setQuip(""); return undefined; }
    let t = null, last = nextQuip("");
    setQuip(last);
    const tick = () => { t = setTimeout(() => { last = nextQuip(last); setQuip(last); tick(); }, quipDelay()); };
    tick();
    return () => clearTimeout(t);
  }, [busy]);

  if (!open) return null;

  async function send(e) {
    if (e) e.preventDefault();
    if (state !== "ready" || busy) return;
    const q = text.trim();
    if (!q) { setNote(W.EMPTY_LINE); return; }
    setNote("");
    const earlier = list.filter((t) => !t.kind).map((t) => ({ role: t.role, text: t.text }));
    turns.value = [...list, { role: "user", text: q }];
    setText("");
    pending.value = true;
    const r = await post("/api/ask", { project: project.value, question: q, earlier });
    pending.value = false;
    const b = r.body;
    if (r.status === 200 && b && b.ok === true && typeof b.answer === "string") {
      const extra = Array.isArray(b.notes) ? b.notes.filter((n) => typeof n === "string") : [];
      turns.value = [...turns.value, { role: "assistant", text: b.answer }, ...extra.map((n) => ({ role: "assistant", text: n, kind: "note" }))];
      if (typeof b.reply === "string" && b.reply && Array.isArray(b.changes) && b.changes.length) await showChanges(b.reply);
    } else if (r.status === 409 && b && b.code === "asking_off") {
      panelState.value = "off";
    } else if (r.status === 0) {
      turns.value = [...turns.value, { role: "assistant", text: W.NOT_REACHED_LINE, kind: "problem" }];
    } else {
      const m = r.status === 200 && !(b && typeof b.message === "string" && b.message) ? W.NO_ANSWER_LINE : words(r, "answer");
      turns.value = [...turns.value, { role: "assistant", text: m, kind: "problem" }];
      if (b && b.code === "limit" && Array.isArray(b.offer) && b.offer.length) turns.value = [...turns.value, { role: "assistant", text: "", kind: "offer", offer: b.offer.slice(0, 6) }];   // #54
    }
  }

  // #47e: the dry run of the changes the answer suggested; the server holds them, so only the reply's ID is sent.
  async function showChanges(reply) {
    pending.value = true;
    const r = await post("/api/ask/change/dry", { project: project.value, reply });
    pending.value = false;
    const b = r.body;
    if (r.status === 200 && b && b.ok === true && Array.isArray(b.plans)) {
      turns.value = [...turns.value, { role: "assistant", kind: "changes", text: "", plans: b.plans, fromSource: b.from_source === true, passages: b.passages }];
    } else if (r.status === 409 && b && b.code === "asking_off") {
      panelState.value = "off";
    } else {
      const m = r.status === 400 || r.status === 409 ? fixedLine(b && b.message, W.CHANGES_GONE_LINE) : W.CHANGES_GONE_LINE;
      turns.value = [...turns.value, { role: "assistant", text: m, kind: "problem" }];
    }
  }

  async function stop() {
    setNote(W.STOPPING_LINE);
    await post("/api/ask/stop", {});
  }

  function grip(e) {
    e.preventDefault();
    const el = e.currentTarget;
    el.setPointerCapture(e.pointerId);
    const move = (ev) => setWidth(document.documentElement.clientWidth - ev.clientX, false);
    const up = () => { el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", up); setWidth(panelWidth.value, true); };
    el.addEventListener("pointermove", move); el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
  }
  function gripKey(e) {
    const d = e.key === "ArrowLeft" ? 24 : e.key === "ArrowRight" ? -24 : 0;
    if (d) { e.preventDefault(); setWidth(panelWidth.value + d, true); }
  }
  function toSettings(e) { e.preventDefault(); closePanel(); show("settings"); }

  return (
    <aside id="ask-panel" class="ask-panel" role="complementary" aria-label={W.PANEL_TITLE} tabindex="-1" style={{ width: clampWidth(width) + "px" }}>
      <div class="ask-grip" id="ask-grip" role="separator" aria-orientation="vertical" aria-label={W.GRIP} tabindex="0" onPointerDown={grip} onKeyDown={gripKey} />
      <header class="ask-head">
        <h2>{W.PANEL_TITLE}</h2>
        <button type="button" class="btn sm quiet" id="ask-close" onClick={closePanel}>{W.CLOSE}</button>
      </header>
      <p class="ask-status muted" id="ask-status" role="status" aria-live="polite">
        {state === "checking" ? W.CHECKING_LINE : state === "off" ? null : state === "signed-out" ? null : model ? W.MODEL_LINE(model) : W.READY_LINE}
      </p>
      {state === "off" || state === "checking" ? (
        <p class="ask-off" id="ask-off">{W.OFF_LINE} <a href="#settings" data-ask-settings onClick={toSettings}>{W.OFF_LINK}</a></p>
      ) : null}
      {state === "signed-out" ? (
        <p class="ask-off" id="ask-signed-out">{W.SIGNED_OUT_LINE} <a href="#settings" data-ask-settings onClick={toSettings}>{W.SETTINGS_LINK}</a></p>
      ) : null}
      <div class="ask-log" id="ask-log" ref={log}>
        {list.map((t, i) => (
          <div key={i} class={`ask-turn ${t.role}${t.kind ? " " + t.kind : ""}`} data-role={t.role}>
            <div class="ask-who">{t.role === "user" ? W.YOU : W.REPLY}</div>
            {t.kind === "changes" ? <ChangeCards turn={t} /> : t.kind === "offer" ? <AskOffer turn={t} /> : <div class="ask-text">{t.text}</div>}
          </div>
        ))}
        {busy ? <p class="ask-quip muted" id="ask-quip">{quip}</p> : null}
      </div>
      <p class="ask-note muted" id="ask-note" role="status" aria-live="polite">{note}</p>
      <form class="ask-form" onSubmit={send}>
        <textarea ref={box} id="ask-box" rows="3" value={text} placeholder={W.PLACEHOLDER} aria-label={W.PLACEHOLDER} disabled={state !== "ready"}
          onInput={(e) => setText(e.currentTarget.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) send(e); }} />
        <div class="ask-actions">
          {busy ? <button type="button" class="btn" id="ask-stop" onClick={stop}>{W.STOP}</button> : null}
          <button type="submit" class="btn primary" id="ask-send" disabled={state !== "ready" || busy}>{W.SEND}</button>
        </div>
      </form>
    </aside>
  );
}
