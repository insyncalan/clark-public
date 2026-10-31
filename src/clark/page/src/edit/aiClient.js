// The page's one way to ask for an AI suggestion (#72). Slice 2 has only this STUB: canned replies, no network, nothing sent anywhere.
// The real client (one fetch to the server's route, a stop signal, one fixed error line for any failure) replaces it in slice 4/5 with
// the same two methods:
//   status()                     -> "ready" | "off" | "not_signed_in" | "busy"   (the card does not ask unless it is "ready")
//   suggest(request, signal)     -> Promise of {html, notes: [string], changes: [{op: "same"|"del"|"add", text}]}; rejects on a
//                                   failure, and with an AbortError when the signal stops it
// request is {option, place, text, instruction}: the chosen text, the option and Ask…'s one line, and nothing else.

const escape = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// A word by word comparison for the stub's canned reply (the server's word_diff does this for the real one).
export function wordChanges(from, to) {
  const a = String(from).split(/\s+/).filter(Boolean), b = String(to).split(/\s+/).filter(Boolean);
  const n = a.length, m = b.length;
  const t = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) t[i][j] = a[i] === b[j] ? t[i + 1][j + 1] + 1 : Math.max(t[i + 1][j], t[i][j + 1]);
  const out = [];
  const put = (op, text) => { const last = out[out.length - 1]; if (last && last.op === op) last.text += " " + text; else out.push({ op, text }); };
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { put("same", a[i]); i++; j++; }
    else if (t[i + 1][j] >= t[i][j + 1]) put("del", a[i++]);
    else put("add", b[j++]);
  }
  while (i < n) put("del", a[i++]);
  while (j < m) put("add", b[j++]);
  return out;
}

// A stub whose answers are set by `opts`, read on every call so a test can change them: state (the status), fail (reject), hold (wait for
// release()), reply (a function from the request to the answer; the default shortens the text to its first six words).
export function stubAiClient(opts = {}) {
  let gate = null, open = null;
  const client = {
    opts,
    calls: [],
    status: () => opts.state || "ready",
    release() { if (open) open(); },
    suggest(request, signal) {
      client.calls.push(request);
      return new Promise((resolve, reject) => {
        const stop = () => reject(Object.assign(new Error("stopped"), { name: "AbortError" }));
        if (signal && signal.aborted) return stop();
        if (signal) signal.addEventListener("abort", stop, { once: true });
        const finish = () => {
          if (opts.fail) return reject(new Error("canned failure"));
          const text = String(request.text || "");
          const words = text.split(/\s+/).filter(Boolean);
          const made = opts.reply ? opts.reply(request) : { text: words.slice(0, 6).join(" ") + (words.length > 6 ? "." : "") };
          const html = made.html || "<p>" + escape(made.text) + "</p>";
          resolve({ html, notes: made.notes || [], changes: made.changes || wordChanges(text, made.text !== undefined ? made.text : text) });
        };
        if (opts.hold) { gate = new Promise((r) => { open = r; }); gate.then(finish); } else setTimeout(finish, opts.delay || 0);
      });
    },
  };
  return client;
}
