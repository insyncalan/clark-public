// The AI suggestion card (#72, slice 2): one card under a field, five states, four buttons. It is not wired to any editor yet; it mounts on
// anything and talks to an `aiClient` (edit/aiClient.js). Nothing changes in the field before Accept: the card only calls `onAccept(html)`
// from the Accept button while a suggestion is ready, and the html it passes is the cleaned one (cleanHtml), never the raw reply.
//
// States (data-state): working, ready, failed, off, not_signed_in. The card's status line is the one polite live region ("Working on it",
// "Suggestion ready", or the same plain line a failed or off card shows); it is never assertive, because nothing here is urgent and
// Accept is never done for the person.
// Keys and focus (docs/handoff/design-72-ai-menu-page.md section 6a): the card is not a trap; Tab goes Accept, Discard, Try again, Show
// changes. Focus goes to Stop while it works and to the heading line (the option's name) when the card has a result or a line to read. Accept,
// Discard, Stop and Esc call `returnTo()` so focus goes back to the editor; Try again and Show changes keep it on the card.
import { useEffect, useRef, useState } from "preact/hooks";
import { cleanHtml } from "../logic/cleanHtml.js";
import { WORDS, optionName } from "../logic/aiMenu.js";

const LINES = { failed: WORDS.failed, off: WORDS.off, not_signed_in: WORDS.notSignedIn };

export function AiCard({ client, place, option, text, instruction = "", returnTo, onAccept, onClose }) {
  const refusal = (status) => ({ kind: status === "not_signed_in" ? "not_signed_in" : status === "busy" ? "failed" : "off" });
  const [state, setState] = useState(() => { const s = client.status(); return s === "ready" ? { kind: "working" } : refusal(s); });
  const [say, setSay] = useState("");
  const [diff, setDiff] = useState(false);
  const run = useRef(0), abort = useRef(null);
  const head = useRef(null), stop = useRef(null);
  const name = optionName(option, instruction);

  const ask = () => {
    abort.current && abort.current.abort();
    const mine = ++run.current;
    setDiff(false);
    const status = client.status();
    if (status !== "ready") {                   // the provider is not asked when AI is off, not signed in or busy
      setState(refusal(status));
      return;
    }
    setState({ kind: "working" });
    const ctl = new AbortController();
    abort.current = ctl;
    client.suggest({ option, place, text, instruction }, ctl.signal).then(
      (r) => { if (mine === run.current) setState({ kind: "ready", reply: { html: cleanHtml(String(r.html || "")), notes: r.notes || [], changes: r.changes || [] } }); },
      () => { if (mine === run.current && !ctl.signal.aborted) setState({ kind: "failed" }); });
  };
  useEffect(() => { ask(); return () => { run.current += 1; abort.current && abort.current.abort(); }; }, []);

  const kind = state.kind;
  useEffect(() => {
    setSay(kind === "working" ? WORDS.working : kind === "ready" ? WORDS.ready : LINES[kind]);
    const to = kind === "working" ? stop.current : head.current;
    if (to) to.focus({ preventScroll: true });
  }, [kind]);

  const leave = (how) => { run.current += 1; abort.current && abort.current.abort(); if (returnTo) returnTo(how); onClose && onClose(how); };
  const accept = () => { if (kind === "ready") { onAccept(state.reply.html); leave("accept"); } };
  const keys = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); leave("esc"); } };
  const r = state.reply;

  return (
    <section class="aic" data-state={kind} aria-label={`Suggestion: ${name}`} onKeyDown={keys}>
      <h3 class="aic-h" tabIndex={-1} ref={head}>{name}</h3>
      <p class="aic-say" role="status" aria-live="polite" aria-atomic="true">
        {kind === "working" && <span class="aic-dot" aria-hidden="true" />}{say}
      </p>
      {kind === "ready" && <div class="aic-text" dangerouslySetInnerHTML={{ __html: r.html }} />}
      {kind === "ready" && r.notes.length > 0 && (
        <div class="aic-notes"><p class="aic-notes-h">{WORDS.notes}</p><ul>{r.notes.map((n, i) => <li key={i}>{n}</li>)}</ul></div>
      )}
      {kind === "ready" && diff && (
        <p class="aic-diff" id="aic-diff">
          {r.changes.length === 0 ? WORDS.noChanges : r.changes.map((c, i) => c.op === "del" ? <del key={i}>{c.text} </del> : c.op === "add" ? <ins key={i}>{c.text} </ins> : <span key={i}>{c.text} </span>)}
        </p>
      )}
      <div class="aic-row">
        {kind === "working" && <button type="button" class="aic-btn" ref={stop} onClick={() => leave("stop")}>{WORDS.stop}</button>}
        {kind === "ready" && <button type="button" class="again" onClick={accept}>{WORDS.accept}</button>}
        {kind !== "working" && <button type="button" class="aic-btn" onClick={() => leave("discard")}>{WORDS.discard}</button>}
        {(kind === "ready" || kind === "failed") && <button type="button" class="aic-btn" onClick={ask}>{WORDS.again}</button>}
        {kind === "ready" && <button type="button" class="aic-link" aria-expanded={diff ? "true" : "false"} aria-controls="aic-diff" onClick={() => setDiff(!diff)}>{diff ? WORDS.hideChanges : WORDS.changes}</button>}
      </div>
    </section>
  );
}
