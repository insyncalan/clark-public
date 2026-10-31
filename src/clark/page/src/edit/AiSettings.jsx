// Settings › AI (#54): a card per provider (Claude: your Claude subscription through the Claude command, or an API key; OpenAI:
// an API key), the connect box that tests the sign-in and lists the models, Disconnect, and the model ask clark uses. Edit parts
// only: a published file has no Settings. Everything shown comes from GET /api/ai/status; the page keeps no key and no choice
// of its own. The key box is a password field, cleared as soon as it is sent, whatever the answer.
import { useEffect, useState } from "preact/hooks";
import { aiStatus, aiConnect, aiModels, aiChoose, aiDisconnect, aiWords } from "./aiApi.js";

export const METHOD_LABEL = { subscription: "Claude subscription", key: "API key" };
export const AI_INTRO = "Connect Claude or OpenAI for asking questions about a project. Keys stay in this Mac's keychain, never in clark's files.";
export const AI_UNAVAILABLE = "The AI settings could not be read just now. Reload the page to try again.";
export const KEY_KEPT = "The key is kept in this Mac's keychain, never in clark's files, backups or the repo, and is never shown again.";
export const SUBSCRIPTION_NOTE = "Uses the Claude command on this computer, signed in with your own Claude plan. No key is needed.";
export const NONE_CONNECTED = "Connect a provider first.";

function ConnectBox({ card, note, onDone, onCancel }) {
  const [method, setMethod] = useState(card.methods[0]);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setMsg("");
    const sent = key.trim();
    setKey("");                                     // the field never keeps the key once it has been sent
    const r = await aiConnect(card.provider, method, sent);
    setBusy(false);
    if (r.status === 200 && r.body && r.body.ok === true) { onDone(r.body); return; }
    setMsg(aiWords(r));                             // the box stays open and says why
  }

  return (
    <form class="ai-connect" data-ai-box={card.provider} onSubmit={submit}>
      <h4>Connect {card.name}</h4>
      <p class="muted" data-ai-note>{note}</p>
      {card.methods.length > 1 ? (
        <div class="seg" role="group" aria-label="How to connect">
          {card.methods.map((m) => (
            <button type="button" key={m} class="btn sm" data-ai-method={m} aria-pressed={method === m ? "true" : "false"} onClick={() => setMethod(m)}>{METHOD_LABEL[m]}</button>
          ))}
        </div>
      ) : null}
      {method === "key" ? (
        <>
          <label for={`ai-key-${card.provider}`}>{card.name} API key</label>
          <input class="field" id={`ai-key-${card.provider}`} type="password" autocomplete="off" spellcheck={false} data-ai-key value={key} onInput={(e) => setKey(e.currentTarget.value)} placeholder="Paste your key" />
          <p class="muted">{KEY_KEPT}</p>
        </>
      ) : <p class="muted">{SUBSCRIPTION_NOTE}</p>}
      <p class="error" role="alert" data-ai-msg>{msg}</p>
      <div class="row">
        <button type="button" class="btn quiet" data-ai-cancel onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" class="btn pri" data-ai-test disabled={busy || (method === "key" && !key.trim())}>Test and connect</button>
      </div>
    </form>
  );
}

function Card({ card, note, busy, open, setOpen, onBody, setMsg }) {
  const [ticks, setTicks] = useState(null);
  const ticked = ticks || card.models.filter((m) => m.ticked).map((m) => m.model);

  async function save() {
    const r = await aiModels(card.route, ticked);
    if (r.status === 200 && r.body && r.body.ok) { setTicks(null); onBody(r.body); } else setMsg({ kind: "error", text: aiWords(r) });
  }
  async function disconnect() {
    const r = await aiDisconnect(card.provider);
    if (r.status === 200 && r.body && r.body.ok) onBody(r.body); else setMsg({ kind: "error", text: aiWords(r) });
  }
  const flip = (m) => setTicks(ticked.includes(m) ? ticked.filter((x) => x !== m) : [...ticked, m]);

  return (
    <div class={`ai-prov${card.connected ? " on" : ""}`} data-ai-card={card.provider}>
      <h3>{card.name} <span class={`tag${card.connected ? " cl" : ""}`}>{card.connected ? "Connected" : "Not connected"}</span></h3>
      {card.connected ? (
        <>
          <p class="ai-how" data-ai-how>{METHOD_LABEL[card.method]}</p>
          <fieldset class="ai-models">
            <legend>Models ask clark may use</legend>
            {card.models.map((m) => (
              <label key={m.model}><input type="checkbox" data-ai-tick={m.model} checked={ticked.includes(m.model)} onChange={() => flip(m.model)} disabled={busy} /> {m.label}</label>
            ))}
          </fieldset>
          <div class="row">
            {ticks ? <button type="button" class="btn sm" data-ai-save onClick={save} disabled={busy}>Save models</button> : null}
            <button type="button" class="btn sm quiet" data-ai-disconnect={card.provider} onClick={disconnect} disabled={busy}>Disconnect</button>
          </div>
        </>
      ) : open ? (
        <ConnectBox card={card} note={note} onCancel={() => setOpen("")} onDone={(b) => { setOpen(""); onBody(b); }} />
      ) : (
        <button type="button" class="btn pri sm" data-ai-connect={card.provider} onClick={() => setOpen(card.provider)} disabled={busy}>Connect…</button>
      )}
    </div>
  );
}

export function AiSettings() {
  const [st, setSt] = useState(null);        // null: not read yet; "unavailable"; or the status body
  const [open, setOpen] = useState("");      // the provider whose connect box is open
  const [ask, setAsk] = useState(null);      // a weaker choice waiting for "use it anyway": {choice, text}
  const [msg, setMsg] = useState(null);      // {kind: "error" | "note", text}
  const [busy, setBusy] = useState(false);

  function onBody(b) { setSt(b); setMsg(b.message ? { kind: "note", text: b.message } : null); }

  useEffect(() => {
    aiStatus().then((r) => setSt(r.status === 200 && r.body && r.body.ok === true ? r.body : "unavailable"));
  }, []);

  async function choose(choice, anyway) {
    setBusy(true);
    setMsg(null);
    const r = await aiChoose(choice, anyway);
    setBusy(false);
    const b = r.body;
    if (r.status === 200 && b && b.ok) { setAsk(null); onBody(b); return; }
    if (r.status === 409 && b && b.code === "weaker") { setAsk({ choice, text: b.message }); return; }
    setMsg({ kind: "error", text: aiWords(r) });
  }

  if (st === null) return <section class="frame setting" id="ai-settings"><h2>AI</h2><p class="muted">Checking which providers are connected…</p></section>;
  if (st === "unavailable") return <section class="frame setting" id="ai-settings"><h2>AI</h2><p class="muted" id="ai-unavailable">{AI_UNAVAILABLE}</p></section>;
  const options = Array.isArray(st.options) ? st.options : [];
  return (
    <section class="frame setting" id="ai-settings">
      <h2>AI</h2>
      <p class="muted" id="ai-intro">{AI_INTRO}</p>
      <div class="ai-provs">
        {st.providers.map((c) => <Card key={c.provider} card={c} note={st.note} busy={busy} open={open === c.provider} setOpen={setOpen} onBody={onBody} setMsg={setMsg} />)}
      </div>
      <div class="form ai-choice">
        <label for="ai-model">Model for ask clark</label>
        <select class="field" id="ai-model" disabled={busy || !options.length} value={ask ? ask.choice : st.chosen} onChange={(e) => choose(e.currentTarget.value, false)}>
          {options.length ? options.map((o) => <option key={o.choice} value={o.choice}>{o.label}{o.recommended ? " (recommended)" : ""}{o.provider === "openai" ? " · OpenAI" : " · Claude"}</option>) : <option value="">{NONE_CONNECTED}</option>}
        </select>
      </div>
      {ask ? (
        <div class="ai-weaker" role="alertdialog" aria-label="A less able model" id="ai-weaker">
          <p>{ask.text}</p>
          <div class="row">
            <button type="button" class="btn quiet" data-ai-keep onClick={() => setAsk(null)} disabled={busy}>Keep the recommended model</button>
            <button type="button" class="btn pri" data-ai-anyway onClick={() => choose(ask.choice, true)} disabled={busy}>Use it anyway</button>
          </div>
        </div>
      ) : null}
      <div class="pub-msg" role={msg && msg.kind === "error" ? "alert" : "status"} aria-live="polite">{msg && msg.text ? <p class={msg.kind}>{msg.text}</p> : null}</div>
    </section>
  );
}
