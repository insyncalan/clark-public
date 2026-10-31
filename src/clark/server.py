"""clark's local server: the page and its data, for this machine only (#33; guarded; BRD NFR-2).

Copied from creaite v2.6.9 (db5adb2) system/scripts/live_server.py, only what clark needs today, with the changes
function. Later items add their routes to GET_ROUTES and POST_ROUTES, where the one dispatcher checks the token first.

Routes:
- GET  /health           {"ok": true} only (and "this_data" when asked with X-Clark-Data, #71); the Host is checked as everywhere
- GET  /                 the page, with this run's token in a JSON data block (id="clark-boot"), never run as a script
- GET  /api/projects     the projects the page can ask for: [{"code", "name"}], from the store (`projects`, #31)
- GET  /api/data         ?project=<CODE>: one project's data, from the store (`data_for`, #31)
- GET  /api/movement     ?project=<CODE>: Milestones Movement (#136), owner only, never published: the view of the store's `milestone_moves` read (movement_read.py); without the seam, not found
- GET  /api/activity     ?project=<CODE>&item=<ID>: one item's changes for the peek's Activity tab (#42), owner only, never published (activity_read.py); without the seam, not found
- POST /api/change       one change to a project's report sections (#65); the logic is `change(req)`, from clark.changes
- POST /api/undo         reverse one earlier step of the report's (#65); the logic is `undo(req)`
- POST /api/sneak/read  words about one work item as from → to changes (#42); read only, plain code (clark.sneak)
- POST /api/here         "still here" from an open page (#71); stops a launcher-started server when no page is left
- POST /api/publish      Publish (#43): Local, and the client folder only when the body says `to_client: true`; publish_flow.py
- POST /api/client-folder  choose or clear the project's client folder (#43); never writes into it
- GET  /api/publication  ?project=<CODE>: when the project was last published and whether to the client (#43)
- POST /api/preview      Preview (#147): builds the page as publish would, in memory; answers a one-visit address (publish_flow.py)
- GET  /preview          ?id=<from /api/preview>: that page, once, local only (a new tab cannot send the token header)
- GET  /api/export       ?project=<CODE>: the project's workbook as a download named <CODE>-<date>.xlsx (publish_flow.py)
- GET  /api/backups      the backups newest first, a status line, the daily-copy warning (#111; safety.py)
- POST /api/backups/preview  {name}: counts in a backup and now, from a temporary copy
- POST /api/backups/restore  {name, last_step}: put a backup back (one writer at a time, never waiting)
- POST /csp-report       the browser's reports of what the script policy blocked: local only, rate-limited, small

Run: python3 -m clark.server   (CLARK_PORT sets the port; the default is 8766, beside creaite's 8765)
Standard library only, Python 3.9.
"""
import base64
import errno
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import socketserver
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

LOG = logging.getLogger("clark.server")
HOST = "127.0.0.1"                    # the only address clark listens on, whatever any setting says
DEFAULT_PORT = 8766
TOKEN = secrets.token_urlsafe(24)     # new at every start; the page gets it in GET /
TOKEN_HEADER = "X-Clark-Token"
STALE_PAGE = "This page is out of date because clark was restarted. Reload the page and try again."
# What a person reads in an error reply (`message`), by the stable `code` the page and the tests use. A person never sees
# the code. A fault's class and text go to the log only, never into a reply.
RELOAD = "Reload the page and try again."
MESSAGES = {
    "not_allowed": f"That was not accepted. {RELOAD}",
    "stale": STALE_PAGE,
    "bad_request": f"That could not be read. {RELOAD}",
    "send_json": f"That could not be read. {RELOAD}",
    "length_required": f"That could not be read. {RELOAD}",
    "too_large": "That is too big for clark to take. Try again with less in it.",
    "unsupported_type": f"That could not be read. {RELOAD}",
    "not_found": f"That could not be found. {RELOAD}",
    "not_supported": "That is not something clark can do. Go back to the page you were on.",
    "bad_project_code": "Use a project code of 3 to 7 capital letters or digits.",
    "project_not_found": "There is no project with that code. Check the code in the address, or choose a project from the list.",     # = changes.NO_PROJECT (a test keeps the two equal)
    "bad_archived": "That way of showing archived records isn't available. Reload the page and try again.",
    "server_error": "Something went wrong, and nothing was changed. Try again, or restart clark.",
    "no_backups": "Backups can't be shown right now. Restart clark the usual way and try again.",
    "saving_off": "Saving is switched off, so that change was not kept. Restart clark the usual way to turn it on.",
    "item_not_found": f"That item could not be found. {RELOAD}",
    "reading_off": "Changing items with words is not available right now, and nothing was changed. Restart clark the usual way to turn it on.",
}
# The standard library's error status → the code of the plain reply (Handler.send_error). Any other 400 to 499 is
# bad_request and any 500 or more server_error.
ERROR_PAGES = {501: "not_supported", 505: "bad_request", 414: "too_large", 431: "too_large"}
BODY_LIMIT = 2 * 1024 * 1024          # any request; a route that needs more (an import) adds itself below
ROUTE_BODY_LIMITS = {"/api/change": 16 * 1024, "/api/undo": 1024, "/api/sneak/read": 4 * 1024, "/api/backups/preview": 1024, "/api/backups/restore": 1024}     # #65: a change or an undo is small; over is the 400 "too big"
PROJECT_CODE = re.compile(r"[A-Z][A-Z0-9]{2,6}")      # creaite's projects.code CHECK: 3 to 7 characters
CLIENT_LEFT = (BrokenPipeError, ConnectionResetError)  # the page went mid-reply: not a 500

# creaite SECURITY_HEADERS (BL-212). clark: Cache-Control is sent from end_headers too, so every reply carries it once.
SECURITY_HEADERS = (("Content-Security-Policy", "frame-ancestors 'none'"), ("X-Frame-Options", "DENY"),
                    ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"))
NO_STORE = ("Cache-Control", "no-store")


class Busy(Exception):
    """A read the store refused in plain words that must reach the page as they are (a restore is under way): 503."""


class LengthRequired(ValueError):
    """A body sent without a Content-Length (chunked): refused with 411."""


class TooLarge(ValueError):
    """A body over the limit (or a negative length): refused with 400, code too_large."""


def error_body(code, **extra):
    """The JSON of an error reply: `message` in plain words for people, `code` stable for the page and the tests."""
    return {"ok": False, "message": MESSAGES[code], "code": code, **extra}


def host_name(host):
    """The host part of a Host header: `127.0.0.1:8766` → 127.0.0.1, `[::1]:8766` → ::1. (creaite host_name)"""
    host = (host or "").strip()
    if host.startswith("["):
        return host[1:host.find("]")] if "]" in host else ""
    return host.split(":")[0]


HOST_HEADER = re.compile(r"(127\.0\.0\.1|localhost|\[::1\])(?::([0-9]{1,5}))?")


def host_allowed(host):
    """Whether a Host header (or an Origin's host) is exactly this machine: 127.0.0.1, localhost or [::1], with an
    optional port of 1 to 65535 and nothing else. (clark: stricter than creaite's host_name check)"""
    m = HOST_HEADER.fullmatch(host or "")
    return bool(m) and (m.group(2) is None or 1 <= int(m.group(2)) <= 65535)


def token_ok(sent):
    """Whether `sent` is this run's token, compared in constant time as bytes (a non-ASCII token is simply wrong)."""
    return hmac.compare_digest((sent or "").encode("utf-8", "surrogatepass"), TOKEN.encode("ascii"))


# #71: /health says only {"ok": true}, unless the launcher asks with its mark of the data folder in X-Clark-Data: then it also says
# whether this server's data folder is that one ("this_data"). A web page can't send that header without a preflight, which is
# always refused. __main__ gives the server its mark (clark.appfiles.data_mark); with none set, "this_data" is false.
MARK_HEADER = "X-Clark-Data"
DATA_MARK = None


def set_data_mark(mark):
    """Give the server the mark of its data folder."""
    global DATA_MARK
    DATA_MARK = mark


def health_answer(asked):
    """What /health says: {"ok": true}, plus "this_data" only when `asked` (the X-Clark-Data header) is not empty."""
    out = {"ok": True}
    if asked:
        out["this_data"] = DATA_MARK is not None and asked == DATA_MARK
    return out


# ===== The script policy (creaite BL-255, copied from report-only and sent enforced; #71 adds worker-src 'self') =====
# Every HTML reply carries Content-Security-Policy with the SHA-256 of each inline <script> the browser runs and each
# inline <style>, taken from the exact bytes sent. clark's page is one HTML file with inline scripts, so script-src lists
# hashes only (no 'self'); Tiptap keeps injectCSS: false (#35, #41). What the policy blocks is reported to /csp-report.
CSP_REPORT_ROUTE = "/csp-report"
CSP_REPORT_LIMIT, CSP_REPORT_WINDOW, CSP_REPORT_BYTES = 60, 60.0, 16 * 1024   # reports a minute; the largest body read
CSP_REPORTS = {"since": 0.0, "n": 0, "dropped": 0}
CSP_LOCK = threading.Lock()
CSP_BLOCK = re.compile(r"<!--|<(script|style)\b([^>]*)>", re.I)
CSP_END = {"script": re.compile(r"</script[\s/>]", re.I), "style": re.compile(r"</style[\s/>]", re.I)}
CSP_TYPE = re.compile(r"""\btype\s*=\s*["']?([^"'\s>]*)""", re.I)
CSP_JS_TYPES = ("", "module", "text/javascript", "application/javascript", "application/ecmascript", "text/ecmascript")
CSP_KINDS = ("inline", "eval", "wasm-eval", "trusted-types-policy", "trusted-types-sink")
CSP_LOOPBACK = ("127.0.0.1", "localhost", "::1")


def csp_sha(text):
    """The CSP source for one block's text: 'sha256-<base64>' of its UTF-8 bytes, line ends as the HTML parser reads them."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"


def csp_hashes(html):
    """{"script": [...], "style": [...]}: the hashes of the inline blocks a browser would run or apply, in page order. A
    block ends at its first close tag, as the parser ends it; script text (a "<style>" in a string) is never read as markup;
    a script with src= or a data type (the JSON data block) is not run, so it needs no hash."""
    out, at = {"script": [], "style": []}, 0
    while True:
        m = CSP_BLOCK.search(html, at)
        if not m:
            return out
        if m.group(0) == "<!--":
            end = html.find("-->", m.end())
            at = len(html) if end < 0 else end + 3
            continue
        tag, attrs = m.group(1).lower(), m.group(2)
        end = CSP_END[tag].search(html, m.end())
        stop = end.start() if end else len(html)
        kind = (CSP_TYPE.search(attrs) or [None, ""])[1].lower()
        if tag == "style" or (kind in CSP_JS_TYPES and not re.search(r"\bsrc\s*=", attrs, re.I)):
            sha = csp_sha(html[m.end():stop])
            if sha not in out[tag]:
                out[tag].append(sha)
        at = stop


def csp_policy(html):
    """The enforced policy for one page: this page's script and style hashes, nothing from outside this machine.
    style="" attributes stay allowed (style-src-attr 'unsafe-inline'), which Preact and Tiptap need."""
    h = csp_hashes(html if isinstance(html, str) else html.decode("utf-8", "surrogateescape"))
    scripts = " ".join(h["script"]) or "'none'"
    return "; ".join([
        "default-src 'self'", f"script-src {scripts}", "worker-src 'self'",
        "style-src 'self' 'unsafe-inline'", " ".join(["style-src-elem 'self'"] + h["style"]), "style-src-attr 'unsafe-inline'",
        "img-src 'self' data: blob:", "font-src 'self' data:", "connect-src 'self'", "object-src 'none'",
        "base-uri 'none'", "form-action 'self'", "frame-ancestors 'none'", f"report-uri {CSP_REPORT_ROUTE}"])


def csp_kind(blocked):
    """What kind of source a report names, never the source itself: inline, eval, data, blob, self, external or other."""
    b = str(blocked or "").strip().lower()
    if b in CSP_KINDS:
        return b
    for scheme in ("data", "blob", "about", "filesystem"):
        if b.startswith(scheme + ":") or b == scheme:
            return scheme
    if b.startswith(("http://", "https://", "ws://", "wss://")):
        return "self" if host_name(b.split("://", 1)[1].split("/", 1)[0]) in CSP_LOOPBACK else "external"
    return "other"


def csp_directive(name):
    """A report's directive as a short plain name (script-src-elem…), or "unknown"."""
    d = (str(name or "").strip().lower().split() or [""])[0]
    return d if re.fullmatch(r"[a-z][a-z-]{0,39}", d) else "unknown"


def csp_reports(raw, ctype):
    """[(directive, kind)] from a report body: the classic application/csp-report form or the Reporting API's list."""
    data = json.loads(raw or b"{}")
    if ctype == "application/csp-report" or (isinstance(data, dict) and "csp-report" in data):
        r = data.get("csp-report") if isinstance(data, dict) else None
        r = r if isinstance(r, dict) else {}
        return [(csp_directive(r.get("effective-directive") or r.get("violated-directive")), csp_kind(r.get("blocked-uri")))]
    out = []
    for r in data if isinstance(data, list) else []:
        b = r.get("body") if isinstance(r, dict) and r.get("type") == "csp-violation" else None
        if isinstance(b, dict):
            out.append((csp_directive(b.get("effectiveDirective")), csp_kind(b.get("blockedURL"))))
    return out


def csp_local(handler):
    """Whether a request comes from this machine's own page: a local address and Host, and no other site's Origin. Every
    Origin and Sec-Fetch-Site header counts, not only the first, and an Origin must be this very Host and port (#65: the page
    is served from that one address; a page on another local port is another site). No Origin at all (a plain client) is fine."""
    if not handler.host_ok() or handler.client_address[0] not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        return False
    get_all = getattr(handler.headers, "get_all", None)                  # a request with no version has no parsed headers (a dict)
    every = (lambda name: get_all(name) or []) if get_all else (lambda name: [v for v in [handler.headers.get(name)] if v])
    if any(p.strip().lower() == "cross-site" for v in every("Sec-Fetch-Site") for p in v.split(",")):      # one line may hold several values
        return False
    host = (handler.headers.get("Host") or "").lower()
    return all(o.lower() == "http://" + host for o in every("Origin"))


def csp_take(n):
    """Of `n` new reports, how many fit this minute's allowance; the rest are counted as dropped and said once a minute."""
    with CSP_LOCK:
        now = time.time()
        if now - CSP_REPORTS["since"] >= CSP_REPORT_WINDOW:
            if CSP_REPORTS["dropped"]:
                LOG.warning("%d more script-policy reports in the last minute were not logged", CSP_REPORTS["dropped"])
            CSP_REPORTS.update(since=now, n=0, dropped=0)
        room = max(0, min(n, CSP_REPORT_LIMIT - CSP_REPORTS["n"]))
        CSP_REPORTS["n"] += room
        CSP_REPORTS["dropped"] += n - room
        return room


def csp_report_route(handler):
    """POST /csp-report: what the policy blocked. Local only, rate-limited, a small body; each report is one log line naming
    the directive and the kind of source, never a URL, a sample or page text. Writes nothing else."""
    if not csp_local(handler):
        return handler.send(403, error_body("not_allowed"))
    if handler.chunked():
        return handler.send(411, error_body("length_required"))
    try:
        n = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        n = -1
    if n < 0 or n > CSP_REPORT_BYTES:
        return handler.send(413, error_body("too_large"))
    ctype = (handler.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype not in ("application/csp-report", "application/reports+json", "application/json"):
        return handler.send(415, error_body("unsupported_type"))
    try:
        found = csp_reports(handler.rfile.read(n) if n else b"", ctype)
    except (ValueError, AttributeError, RecursionError):   # not JSON, not a browser's shape, or nested too deep
        return handler.send(400, error_body("bad_request"))
    for directive, kind in found[:csp_take(len(found))]:
        LOG.info("script policy blocked: %s %s", directive, kind)
    handler.send_response(204)
    handler.send_header("Content-Length", "0")
    handler.end_headers()
    return None
# ===== end of the script policy =====


# ===== The page and the data (the seams to #35 and #31) =====
PLACEHOLDER = """<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8"><title>clark</title>
<style>body{font:16px system-ui,sans-serif;margin:3rem}</style></head>
<body><p id="state">clark is starting.</p>
<script>document.getElementById("state").dataset.ready = "1";</script>
</body></html>
"""


def placeholder_html():
    """The page until #35 bundles the real one: one inline style and one inline script."""
    return PLACEHOLDER


def with_boot(html):
    """`html` with this run's token in a JSON data block before </body>. A data block is never run, so it needs no hash,
    and "<" is escaped so the block can't be closed early."""
    boot = json.dumps({"token": TOKEN}).replace("<", "\\u003c")
    block = f'<script type="application/json" id="clark-boot">{boot}</script>'
    i = html.rfind("</body>")
    return html[:i] + block + html[i:] if i >= 0 else html + block


def data_route(handler):
    """GET /api/data?project=<CODE>[&archived=hide|show|only]: one project's data. 400 for a malformed code or an archived value
    that isn't in the list, 404 for a project that isn't there."""
    query = parse_qs(urlsplit(handler.path).query)
    code = (query.get("project") or [""])[0]
    if not PROJECT_CODE.fullmatch(code):
        return handler.send(400, error_body("bad_project_code"))
    given = parse_qs(urlsplit(handler.path).query, keep_blank_values=True).get("archived") or [None]
    shown = given[0]                                    # #126: hide (the default), show or only; checked against a fixed list, and given once
    if len(given) > 1 or shown is not None and shown not in ARCHIVED_VIEWS:
        return handler.send(400, error_body("bad_archived"))
    data = handler.server.data_for(code) if shown is None else handler.server.data_for(code, archived=shown)
    if data is None:
        return handler.send(404, error_body("project_not_found"))
    return handler.send(200, {"ok": True, "project": code, "data": data})


def movement_route(handler):
    """GET /api/movement?project=<CODE> (#136): what the Movement page draws, for the owner only. The read is a seam (`movement`,
    movement_read.make_read: the store's milestone_moves cut down by movement_view); this server imports nothing from clark. It is not
    in ask clark's reach and no published file is made from it. No body is accepted (400), a malformed code or another parameter is
    400, a missing project 404, and without the seam the route is not there (404). The reply is whatever movement_view lets
    through: no raw event, no internal note."""
    read = getattr(handler.server, "movement", None)
    if read is None:
        return handler.send(404, error_body("not_found"))
    if handler.headers.get("Content-Length") not in (None, "0") or handler.headers.get("Transfer-Encoding"):
        return handler.send(400, error_body("bad_request"))
    query = parse_qs(urlsplit(handler.path).query, keep_blank_values=True)
    given = query.get("project") or [""]
    code = given[0]
    if len(given) > 1 or set(query) - {"project"} or not PROJECT_CODE.fullmatch(code):
        return handler.send(400, error_body("bad_project_code"))
    view = read(code)
    if view is None:
        return handler.send(404, error_body("project_not_found"))
    return handler.send(200, {"ok": True, "project": code, "movement": view})


ITEM_ID = re.compile(r"[A-Z][A-Z0-9]{2,6}-(?:[A-Z]-)?\d{3,6}")      # #42: a work item's or milestone's ID, at most 16 characters


def activity_route(handler):
    """GET /api/activity?project=<CODE>&item=<ID> (#42): one item's changes, newest first, for the peek's Activity tab (Edit only).
    The read is a seam (`activity`, activity_read.make_read): it checks the item is the project's, reads history on a read-only
    connection and keeps only who, how, when and what changed. No body is accepted (400); each parameter once, nothing else, a
    code and an ID of the stored shape with the ID inside the project (400); a missing project or item 404; without the seam
    the route is not there (404)."""
    read = getattr(handler.server, "activity", None)
    if read is None:
        return handler.send(404, error_body("not_found"))
    if handler.headers.get("Content-Length") not in (None, "0") or handler.headers.get("Transfer-Encoding"):
        return handler.send(400, error_body("bad_request"))
    query = parse_qs(urlsplit(handler.path).query, keep_blank_values=True)
    codes, items = query.get("project") or [""], query.get("item") or [""]
    code, item = codes[0], items[0]
    if (set(query) != {"project", "item"} or len(codes) != 1 or len(items) != 1 or not PROJECT_CODE.fullmatch(code)
            or not ITEM_ID.fullmatch(item) or not item.startswith(code + "-")):
        return handler.send(400, error_body("bad_request"))
    view = read(code, item)
    if view is None:
        return handler.send(404, error_body("item_not_found"))
    return handler.send(200, {"ok": True, "project": code, "item": item, "activity": view})


ARCHIVED_VIEWS = ("hide", "show", "only")          # what ?archived= may be on /api/data (#126); never passed on unchecked
PROJECT_LIST_LIMIT = 500
PROJECT_NAME_LIMIT = 200


def projects_route(handler):
    """GET /api/projects[?archived=1]: the code and name of each project, nothing else, so the page can choose which one to ask for.
    Only a code of the shape the store accepts is listed (3 to 7 capital letters or digits), a row that isn't a dict is
    skipped, a name that is not text falls back to the code, a name is cut at PROJECT_NAME_LIMIT characters, and the list stops at
    PROJECT_LIST_LIMIT."""
    given = parse_qs(urlsplit(handler.path).query, keep_blank_values=True).get("archived") or [None]
    shown = given[0]                                    # #126: 1 lists the archived ones; given once
    if len(given) > 1 or shown not in (None, "1"):
        return handler.send(400, error_body("bad_archived"))
    out = []
    try:
        listed = handler.server.projects() if shown is None else handler.server.projects(archived=True)
    except Busy as e:
        return handler.send(503, {"ok": False, "message": str(e), "code": "restore_busy"})
    for row in listed:
        if len(out) >= PROJECT_LIST_LIMIT:
            break
        try:
            code = str(row["code"])
        except (KeyError, TypeError, IndexError):
            continue
        if not PROJECT_CODE.fullmatch(code):
            continue
        try:
            name = row["name"]
        except (KeyError, TypeError, IndexError):
            name = None
        if not isinstance(name, str) or not name.strip():           # only text is a name; anything else falls back to the code
            name = code
        out.append({"code": code, "name": name[:PROJECT_NAME_LIMIT]})
    return handler.send(200, {"ok": True, "projects": out})


def use_cases_route(handler):
    """GET /api/use-cases?project=<CODE>: the project's use cases for the Use Cases page (#163), read only. The one parameter is
    checked like data_route's; any other is refused. Without a reader (the server was given none) the route does not exist: 404
    not_found, whatever the request. 404 for a project that isn't there. The reader does all the work and writes nothing."""
    if handler.server.use_cases is None:
        return handler.send(404, error_body("not_found"))
    query = parse_qs(urlsplit(handler.path).query, keep_blank_values=True)
    given = query.get("project") or [""]
    if set(query) != {"project"} or len(given) != 1 or not PROJECT_CODE.fullmatch(given[0]):
        return handler.send(400, error_body("bad_project_code"))
    found = handler.server.use_cases(given[0])
    if found is None:
        return handler.send(404, error_body("project_not_found"))
    return handler.send(200, {"ok": True, "project": given[0], "use_cases": found})


def seam_route(handler, seam, req):
    """Pass a request to a seam (`change` or `undo`, given to the server) and send its answer, (status, body). The server
    imports no store: the seam does all the work, in plain words. With no seam, 503 saving_off (saving is switched off)
    A fault inside the seam is the one 500 of run_route, with no class and no text."""
    if seam is None:
        return handler.send(503, error_body("saving_off"))
    status, body = seam(req)
    return handler.send(status, body)


def change_route(handler, req):
    """POST /api/change (#65). The token, the Host, JSON only, the length and the body are checked before this runs."""
    return seam_route(handler, handler.server.change, req)


def undo_route(handler, req):
    """POST /api/undo (#65). Checked like change_route before this runs."""
    return seam_route(handler, handler.server.undo, req)


def sneak_route(handler, req):
    """POST /api/sneak/read (#42): typed words about one work item as from → to changes. Read only: the seam (clark.sneak) reads
    the project's data and the words with plain code and writes nothing. A refusal of the words is 200 with ok false and plain
    words; no seam is the 503 of the other routes."""
    ok = isinstance(req, dict) and set(req) <= {"project", "id", "text"}
    code, item, text = (req.get(k) for k in ("project", "id", "text")) if ok else (None, None, None)
    if not (isinstance(code, str) and PROJECT_CODE.fullmatch(code) and isinstance(item, str) and isinstance(text, str)):
        return handler.send(400, error_body("bad_request"))
    if handler.server.sneak is None:
        return handler.send(503, error_body("reading_off"))                 # a read, so not "saving is switched off"
    return seam_route(handler, handler.server.sneak, req)


# #71: the six files a browser fetches with no token (it sends no custom header for a manifest, a worker script or an icon).
# Their own table, GET only, matched by exact path (the query is dropped), fixed bytes read once, no data and no token in them.
# {route: (bytes, content type, extra headers)}. The server imports no other clark module (a guard test), so __main__ gives it
# the table from clark.appfiles.open_files() with set_open_files(); until then the table is empty and nothing is open.
OPEN_GET_ROUTES = {}


def set_open_files(files):
    """Give the server its open files, replacing any earlier set. (Module setting, so serve()'s signature stays as it is.)"""
    OPEN_GET_ROUTES.clear()
    OPEN_GET_ROUTES.update(files)


def open_route(handler, route):
    """Send one of the six open files: fixed bytes, its own type and its extra headers (the worker's own policy)."""
    data, ctype, extra = OPEN_GET_ROUTES[route]
    return handler.send(200, data, ctype, extra)


# #71: "still here". An open clark page posts to /api/here every few seconds (with the token), and opening the page counts too.
# Only a server the launcher started has an Idle (clark.idle, given by __main__ with set_idle); it stops that server when no
# window has said so for a minute and no job is running. A server started by hand has none and never stops by itself.
HERE_ROUTE = "/api/here"
IDLE = None
BUSY = {"n": 0}
BUSY_LOCK = threading.Lock()
JOB_WAIT_LIMIT = 60.0                  # seconds the server waits for a running job once it has been told to stop


def set_idle(idle):
    """Give the server the idle watch of a launcher-started run (None: it never stops by itself)."""
    global IDLE
    IDLE = idle


def mark_here():
    """A window said it is open."""
    if IDLE is not None:
        IDLE.here()


def busy():
    """Whether a POST route is running now (a later Publish or Import is covered by run_route, with no list to keep)."""
    with BUSY_LOCK:
        return BUSY["n"] > 0


def page_load_is_ours(headers, port):
    """Whether a load of the page counts as "a window is open": the browser says it came from the address bar or this site
    (`Sec-Fetch-Site` absent, none or same-origin) and no foreign Origin is sent. Anything else still gets the page
    (it cannot read it) but cannot keep a launcher-started server alive."""
    site = headers.get("Sec-Fetch-Site")
    if site is not None and site.strip().lower() not in ("none", "same-origin"):      # an empty value is not a browser's
        return False
    origin = headers.get("Origin")
    return origin is None or origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")


def here_route(handler, req):
    """POST /api/here: the token, the Host, JSON only, the length and the body are checked before this runs."""
    mark_here()
    return handler.send(200, {"ok": True})


def publisher_route(method):
    """A route that hands its request to the server's publisher (publish_flow.Publisher, #43), which answers (status, body).
    Without a publisher there is nothing to ask: not found. The decisions, the checks and the only write into a client folder
    are in publish_flow.py and to_client.py, not here."""
    def route(handler, *req):
        publisher = getattr(handler.server, "publisher", None)
        if publisher is None:
            return handler.send(404, error_body("not_found"))
        if not req:                          # a GET: the project comes from the address
            req = ((parse_qs(urlsplit(handler.path).query).get("project") or [""])[0],)
        status, body = getattr(publisher, method)(*req)
        return handler.send(status, body)
    return route


PREVIEW_ROUTE = "/preview"
DOWNLOAD_CHUNK = 64 * 1024
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def preview_page_route(handler):
    """GET /preview?id=: the page a preview made, once. A new tab can't send the token, so the address itself is the one-visit
    secret (made by POST /api/preview); the Host and Origin checks are as everywhere. Nothing is written."""
    publisher = getattr(handler.server, "publisher", None)
    if publisher is None or not csp_local(handler):
        return handler.send(404 if publisher is None else 403, error_body("not_found" if publisher is None else "not_allowed"))
    body = publisher.take_preview((parse_qs(urlsplit(handler.path).query).get("id") or [""])[0])
    if body is None:
        return handler.send(404, error_body("not_found"))
    return handler.send(200, body, "text/html")


def export_route(handler):
    """GET /api/export?project=<CODE>: the workbook as a download, or the publisher's plain refusal as JSON."""
    publisher = getattr(handler.server, "publisher", None)
    if publisher is None:
        return handler.send(404, error_body("not_found"))
    status, body = publisher.export((parse_qs(urlsplit(handler.path).query).get("project") or [""])[0])
    if status != 200:
        return handler.send(status, body)
    data = body["data"]
    handler.send_response(200)
    handler.send_header("Content-Type", XLSX_TYPE)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Content-Disposition", f'attachment; filename="{body["name"]}"')
    if body.get("warnings"):
        handler.send_header("X-Export-Warning", quote(" ".join(body["warnings"]), safe=" "))        # plain words, any logo warning
    handler.end_headers()
    for i in range(0, len(data), DOWNLOAD_CHUNK):
        handler.wfile.write(data[i:i + DOWNLOAD_CHUNK])
    return None


def safety_route(method):
    """A route that hands its request to the server's `safety` (safety.Safety, #111), which answers (status, body): the backup list,
    Preview and Restore. Without one: 503, in plain words. The checks and the swap are in safety.py and backup.py, not here."""
    def route(handler, *req):
        safety = handler.server.safety
        if safety is None:
            return handler.send(503, error_body("no_backups"))
        status, body = getattr(safety, method)(*req)
        return handler.send(status, body)
    return route


GET_ROUTES = {"/api/projects": projects_route, "/api/data": data_route, "/api/publication": publisher_route("latest"),
              "/api/export": export_route, "/api/use-cases": use_cases_route, "/api/backups": safety_route("listing"),
              "/api/movement": movement_route, "/api/activity": activity_route}
POST_ROUTES = {"/api/change": change_route, "/api/undo": undo_route, "/api/sneak/read": sneak_route, "/api/publish": publisher_route("publish"),
               "/api/client-folder": publisher_route("client_folder"), "/api/preview": publisher_route("preview"),
               "/api/backups/preview": safety_route("preview"), "/api/backups/restore": safety_route("restore")}     # later items: /api/import
# ===== end of the page and the data =====


class Handler(BaseHTTPRequestHandler):
    """The requests. Every reply carries the security headers; every /api/ route goes through authorised() first."""
    server_version = "clark"
    sys_version = ""                                   # clark: the Python version isn't sent
    default_request_version = "HTTP/1.0"               # clark: a request line that doesn't parse still gets headers
    timeout = 30                                       # clark: an idle or half-sent request never holds a thread

    def log_message(self, fmt, *args):
        """Quiet: one log line per API call; safe when the request line didn't parse. (creaite log_message)"""
        path = getattr(self, "path", "") or ""
        if path.startswith("/api/") and path.split("?")[0] != HERE_ROUTE:       # the page's heartbeat is not logged
            LOG.info("%s %s", ascii(getattr(self, "command", "") or "")[1:-1], ascii(path.split("?")[0])[1:-1])   # escaped: no raw bytes

    def send_error(self, code, message=None, explain=None):
        """The standard library's own error pages (a method clark has no handler for, a request line or headers it cannot
        read) as the server's plain JSON error, never Python's HTML. `message` and `explain` carry the method or the
        request's bytes and are ignored, so nothing of the request is echoed. A HEAD reply has the headers and no body."""
        key = ERROR_PAGES.get(code) or ("server_error" if code >= 500 else "bad_request")
        data = json.dumps(error_body(key)).encode()
        self.send_response(code)           # the standard reason for the code, not the request's text
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        if getattr(self, "command", None) != "HEAD":
            self.wfile.write(data)

    def host_ok(self):
        """Whether the Host header is exactly this machine. (creaite host_ok, BL-212; clark: strict, see host_allowed)"""
        return host_allowed(self.headers.get("Host"))

    def headers_ok(self):
        """No second Host or Content-Length (which one counts would depend on who reads it); sends the 400 when not."""
        get_all = getattr(self.headers, "get_all", None)       # a request with no version has no parsed headers (a dict)
        if get_all and any(len(get_all(h) or []) > 1 for h in ("Host", "Content-Length")):
            self.send(400, error_body("bad_request"))
            return False
        return True

    def end_headers(self):
        """Every response, `send` and the standard library's own errors alike, carries the security headers and no-store,
        once each. (creaite end_headers, BL-212; clark: no-store here, not in send)"""
        for k, v in SECURITY_HEADERS + (NO_STORE,):
            self.send_header(k, v)
        super().end_headers()

    def send(self, code, body, ctype="application/json", extra=None):
        """Send one reply: JSON for a dict, else text or bytes as `ctype`; an HTML reply carries its enforced script
        policy, built from its own bytes. (creaite send)"""
        data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if ctype == "text/html":
            extra = {"Content-Security-Policy": csp_policy(data), **(extra or {})}
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def chunked(self):
        """Whether the body is sent chunked (no Content-Length)."""
        return "chunked" in (self.headers.get("Transfer-Encoding") or "").lower()

    def body(self):
        """The request's JSON body ({} when empty). LengthRequired when it has no Content-Length; ValueError when the length
        is malformed or over the limit, or the body isn't JSON. (creaite body; clark: 411 and a malformed length)"""
        if self.chunked() or self.headers.get("Content-Length") is None:
            raise LengthRequired("no Content-Length")
        n = int(self.headers["Content-Length"])          # ValueError when it isn't a number
        if n < 0 or n > ROUTE_BODY_LIMITS.get(self.path.split("?")[0], BODY_LIMIT):
            raise TooLarge("request too large")
        try:
            return json.loads(self.rfile.read(n) or b"{}") if n else {}
        except RecursionError:                          # nested too deep to read: a bad request, not a fault
            raise ValueError("nested too deep") from None

    def authorised(self):
        """Whether an API call may go ahead: the right Host, no other site's Origin (csp_local's test, #65: a page on another
        site can't make the browser change anything), and this run's token. Sends the 403 itself when not; a page opened
        before a restart is told to reload. (creaite authorised; clark: compared in constant time)"""
        if not csp_local(self):
            self.send(403, error_body("not_allowed"))
            return False
        sent = self.headers.get(TOKEN_HEADER)
        if not sent:
            self.send(403, error_body("not_allowed"))
            return False
        if not token_ok(sent):
            self.send(403, error_body("stale", stale=True))
            return False
        return True

    def run_route(self, route, *args):
        """Run a route; a fault is a 500 in plain words (code server_error). The class, the text and the stack go to the log
        only: the text could name a path, and a person gets no technical word."""
        counted = self.command == "POST" and route is not here_route       # a POST mid-run keeps the idle stop waiting
        if counted:
            with BUSY_LOCK:
                BUSY["n"] += 1
        try:
            return route(self, *args)
        except CLIENT_LEFT:
            return None
        except Exception:  # noqa: BLE001  the server answers whatever a route does
            LOG.exception("%s %s failed", self.command, self.path.split("?")[0])
            return self.send(500, error_body("server_error"))
        finally:
            if counted:
                with BUSY_LOCK:
                    BUSY["n"] -= 1

    def do_OPTIONS(self):
        """Refuse every preflight: no cross-origin call is allowed. (creaite do_OPTIONS, BL-212)"""
        if self.headers_ok():
            self.send(403, error_body("not_allowed"))

    def do_GET(self):
        """GET /health, the page, and the API's GET routes (token first, also before a 404 under /api/)."""
        if not self.headers_ok():
            return None
        if not self.host_ok():
            return self.send(403, error_body("not_allowed"))
        route = self.path.split("?")[0]
        if route == "/health":
            return self.send(200, health_answer(self.headers.get(MARK_HEADER)))
        if route == "/":
            if page_load_is_ours(self.headers, self.server.server_port):
                mark_here()
            return self.send(200, with_boot(self.server.page_html()), "text/html")
        if route in OPEN_GET_ROUTES:
            return self.run_route(open_route, route)
        if route == PREVIEW_ROUTE:
            return self.run_route(preview_page_route)
        api = GET_ROUTES.get(route)
        if api or route.startswith("/api/"):
            if not self.authorised():
                return None
            if api:
                return self.run_route(api)
        return self.send(404, error_body("not_found"))

    def do_POST(self):
        """POST /csp-report (its own local checks: a browser's report carries no token), then every other POST: the token,
        JSON only (415), a Content-Length (411), the body (400), then the route (404 if none)."""
        if not self.headers_ok():
            return None
        route = self.path.split("?")[0]
        if route == CSP_REPORT_ROUTE:
            return csp_report_route(self)
        if not self.authorised():
            return None
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return self.send(415, error_body("send_json"))
        try:
            req = self.body()
        except LengthRequired:
            return self.send(411, error_body("length_required"))
        except TooLarge:
            return self.send(400, error_body("too_large"))
        except ValueError:
            return self.send(400, error_body("bad_request"))
        api = here_route if route == HERE_ROUTE else POST_ROUTES.get(route)      # /api/here has its own statement, outside POST_ROUTES
        if not api:
            return self.send(404, error_body("not_found"))
        return self.run_route(api, req)


class LocalServer(ThreadingHTTPServer):
    """The server, on 127.0.0.1 only, without the reverse DNS lookup at bind. (creaite LocalServer, #83: http.server's
    server_bind calls socket.getfqdn(host), which can stall for 30 s on some Macs.) `data_for(code)` is the store's read
    of one project (None when there is none); `projects()` lists them as rows with a code and a name; `page_html()` gives
    the page's HTML (#35 supplies the bundle); `change(req)` and `undo(req)` (#65) answer POST /api/change and /api/undo
    with (status, body), each on a store of its own (None: those routes answer 503); `sneak(req)` (#42) answers POST /api/sneak/read the same way, reading only; `publisher` answers the publish routes (#43); `use_cases(code)` reads one project's use cases (#163); `activity(code, item)` reads one item's changes (#42)."""
    daemon_threads = True

    def __init__(self, server_address, handler=Handler, data_for=None, page_html=None, projects=None, change=None, undo=None,
                 publisher=None, movement=None, use_cases=None, safety=None, sneak=None, activity=None):
        if server_address[0] != HOST:
            raise ValueError(f"The server listens on {HOST} only, not {server_address[0]}")
        self.data_for = data_for or (lambda code: None)
        self.projects = projects or (lambda: [])
        self.change, self.undo, self.sneak = change, undo, sneak
        self.page_html = page_html or placeholder_html
        self.publisher = publisher            # publish_flow.Publisher (#43); None until the launcher gives one
        self.movement = movement              # store.milestone_moves (#136): the owner-only Movement read; None: no such route
        self.activity = activity              # activity(code, item) -> the peek's Activity rows, or None (#42); None: no such route
        self.use_cases = use_cases            # use_cases(code) -> the project's use cases, or None (#163); None: no such route
        self.safety = safety                  # safety.Safety (#111): the backup list, Preview and Restore; None: those routes answer 503
        super().__init__(server_address, handler)

    def server_bind(self):
        """Bind as TCPServer does, then name the server after its own address instead of looking the name up."""
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


# What a person reads when the address is taken: the cause, and the one thing to do. The launcher (__main__.py prints this line;
# launch.py says the same cause in Terminal words) and START-HERE agree with it. No port number and no other command here: closing the
# other window or program is the next step.
PORT_TAKEN = ("Nothing was started: clark is already open in another window, or another program is using the connection it needs. "
              "Close the other window or program, then start clark again.")


def port_setting():
    """The port: CLARK_PORT, or 8766."""
    return int(os.environ.get("CLARK_PORT") or DEFAULT_PORT)


def wait_for_jobs(limit=JOB_WAIT_LIMIT, sleep=time.sleep):
    """After the loop has stopped, wait (at most `limit` seconds) until no POST route is running."""
    waited = 0.0
    while busy() and waited < limit:
        sleep(0.05)
        waited += 0.05


def serve(port=None, data_for=None, page_html=None, projects=None, out=None, err=None, change=None, undo=None,
          publisher=None, movement=None, use_cases=None, safety=None, sneak=None, activity=None):
    """Start the server on 127.0.0.1 and serve until stopped. A port in use is one plain line and exit code 1."""
    out, err = out or sys.stdout, err or sys.stderr
    port = port_setting() if port is None else port
    try:
        httpd = LocalServer((HOST, port), data_for=data_for, page_html=page_html, projects=projects, change=change, undo=undo,
                            publisher=publisher, movement=movement, use_cases=use_cases, safety=safety, sneak=sneak,
                            activity=activity)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            print(PORT_TAKEN, file=err)
            return 1
        raise
    print(f"Open http://{HOST}:{httpd.server_port}/ to use clark. Leave this window open; press Ctrl+C to stop.",
          file=out, flush=True)
    if IDLE is not None:                  # a launcher-started run: stop when no window is left (never while a job runs)
        threading.Thread(target=IDLE.watch, args=(httpd.shutdown, busy, lambda text: print(text, file=out, flush=True)),
                         daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        wait_for_jobs()                   # a POST that began just before the stop finishes first (its write is not cut off)
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(serve())
