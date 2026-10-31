// The page's only way to publish: POST /api/publish, POST /api/client-folder and GET /api/publication (#43). No other file names
// these routes, so the published page (view.jsx) has no way to publish and no mention of them. Nothing here names a folder or a
// file: the client folder is the one saved in Settings, which the server reads itself.
import { token, plain } from "../stores/report.js";

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

export const publishRequest = (body) => call("POST", "/api/publish", body);
export const folderRequest = (project, action) => call("POST", "/api/client-folder", { project, action });
export const previewRequest = (project) => call("POST", "/api/preview", { project });
export const latestRequest = (project) => call("GET", `/api/publication?project=${encodeURIComponent(project)}`);

// The words for a reply. The publish routes write plain words themselves (to_client.py and publish_flow.py: a test pins that none
// has a technical word), so the message of an answer in their shape (a stable `code` and a `message`, with a status they use) is
// shown as it is. Anything else (no answer, a refusal by the server's token check, a fault) gets the page's own words.
const KNOWN = [200, 400, 404, 409];
export function words(r, what) {
  const b = r.body;
  if (KNOWN.includes(r.status) && b && typeof b.code === "string" && /^[a-z_]+$/.test(b.code) && typeof b.message === "string" && b.message) return b.message;
  if (r.status === 0 || r.status === 403) return plain(r.status, b);
  if (r.status === 503) return `Could not ${what} just now. Wait a moment and try again.`;
  return `Something went wrong while this was working. ${what === "publish" ? "Some of the report may have been saved: check the folders before you publish again." : "Nothing was changed."} If it happens again, restart clark.`;
}

// The workbook (#147): {status, body, blob, name}. A download is a file, so the answer is read as a file when it is one and as
// words when it is not. Never a throw. `name` is the one the server gave; the page does not make up its own.
export async function exportRequest(project) {
  try {
    const r = await fetch(`/api/export?project=${encodeURIComponent(project)}`, { headers: { "X-Clark-Token": token() }, cache: "no-store" });
    if (r.status === 200) {
      const given = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") || "");
      let warning = "";
      try { warning = decodeURIComponent(r.headers.get("X-Export-Warning") || ""); } catch (e) { warning = ""; }
      return { status: 200, body: null, blob: await r.blob(), name: given ? given[1] : "", warning };
    }
    return { status: r.status, body: await r.json().catch(() => null), blob: null, name: "" };
  } catch (e) {
    return { status: 0, body: null, blob: null, name: "" };
  }
}
