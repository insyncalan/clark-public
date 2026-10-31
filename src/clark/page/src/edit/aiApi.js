// Settings › AI (#54): the page's only way to the /api/ai/ routes. Edit pages only: no other file names them, so a published page
// has no way to connect a provider. A key is sent once, in the body of POST /api/ai/connect, and never comes back: no answer holds it.
import { token } from "../stores/report.js";

// {status, body}: never a throw, whatever the network or the server did. A status of 0 is "no answer".
async function call(method, path, body) {
  try {
    const headers = { "X-Clark-Token": token() };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store" });
    return { status: r.status, body: await r.json().catch(() => null) };
  } catch (e) {
    return { status: 0, body: null };
  }
}

export const aiStatus = () => call("GET", "/api/ai/status");
export const aiConnect = (provider, method, key) => call("POST", "/api/ai/connect", method === "key" ? { provider, method, key } : { provider, method });
export const aiModels = (route, models) => call("POST", "/api/ai/models", { route, models });
export const aiChoose = (choice, anyway) => call("POST", "/api/ai/choose", anyway ? { choice, anyway: true } : { choice });
export const aiDisconnect = (provider) => call("POST", "/api/ai/disconnect", { provider });

// The words: the server's own plain message when it gave one (it never starts with the product's name), else the page's.
export function aiWords(r) {
  const b = r.body;
  if (b && typeof b.message === "string" && b.message && typeof b.code === "string" && /^[a-z_]+$/.test(b.code)) return b.message;
  if (r.status === 0) return "The AI settings could not be reached. Check that clark is still running, then try again.";
  return "That didn't work just now. Wait a moment and try again; if it keeps happening, close clark and start it again.";
}
