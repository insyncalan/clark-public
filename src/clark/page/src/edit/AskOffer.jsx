// The ask panel's offer after a limit (#54, FR-66): the other connected provider's recommended model, or a smaller one. Nothing
// switches by itself: a button changes the model only when pressed, and a less able one asks first, as in Settings › AI.
import { useState } from "preact/hooks";
import { aiChoose, aiWords } from "./aiApi.js";

export function AskOffer({ turn }) {
  const [ask, setAsk] = useState(null);
  const [done, setDone] = useState("");
  const [busy, setBusy] = useState(false);

  async function pick(o, anyway) {
    setBusy(true);
    const r = await aiChoose(o.choice, anyway);
    setBusy(false);
    const b = r.body;
    if (r.status === 200 && b && b.ok) { setAsk(null); setDone(b.message || ""); return; }
    if (r.status === 409 && b && b.code === "weaker") { setAsk({ o, text: b.message }); return; }
    setDone(aiWords(r));
  }

  if (done) return <div class="ask-text" data-ask-offer-done>{done} Ask again when you're ready.</div>;
  return (
    <div class="ask-offer" data-ask-offer>
      <div class="ask-text">You can switch the model for your next question:</div>
      <div class="row">
        {turn.offer.map((o) => <button type="button" key={o.choice} class="btn sm" data-ask-switch-to={o.choice} disabled={busy} onClick={() => pick(o, false)}>Use {o.label}</button>)}
      </div>
      {ask ? (
        <div class="row">
          <p class="ask-text">{ask.text}</p>
          <button type="button" class="btn sm pri" data-ask-anyway onClick={() => pick(ask.o, true)} disabled={busy}>Use it anyway</button>
        </div>
      ) : null}
    </div>
  );
}
