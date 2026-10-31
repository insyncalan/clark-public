"""#33: the local server's security (src/clark/server.py; guarded). Rules: docs/handoff/design-33-builder.md.

Run: python3 dev/run_tests.py test_server
Each test talks to a real server on 127.0.0.1 (a free port) with http.client, so the Host header, the token and the body
are exactly what the test sends. The data is a fake store with one fictional project (#31 brings the real one). The browser
test needs Google Chrome and is required: it fails, never skips, without it.
"""
import contextlib
import http.client
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from _paths import ROOT, SRC

from clark import appfiles, idle, server as sv
from run_support import chrome_command, chrome_path, remove_profile, start_chrome, stop_chrome

PROJECTS = [{"code": "DEMO", "name": "Demo programme", "client_name": "Not for the page", "week_ending": "2026-10-30"},
            {"code": "ABC", "name": None}]
DEMO = {"DEMO": {"name": "Demo programme", "actions": [{"id": "DEMO-A-001", "action": "Agree the plan"}]}}
CHROME = chrome_path() or ""        # CLARK_CHROME, then google-chrome / chromium / chromium-browser on the PATH, then the Mac app
SERVER_ERROR = "Something went wrong, and nothing was changed. Try again, or restart clark."   # the Head's ruling, word for word
SECURITY = [k for k, _ in sv.SECURITY_HEADERS if k != "Content-Security-Policy"] + ["Cache-Control"]


class StubPublisher:
    """Stands in for publish_flow.Publisher (#43): every publish route answers 200, and nothing is written anywhere."""

    def publish(self, body):
        return 200, {"ok": True}

    client_folder = publish

    def latest(self, code):
        return 200, {"ok": True, "latest": None}

    def preview(self, body):
        return 200, {"ok": True, "url": "/preview?id=none"}

    def export(self, code):
        return 404, {"ok": False, "code": "project_not_found", "message": "There is no project with that code."}

    def take_preview(self, nonce):
        return None


class Stoppable(sv.LocalServer):
    """#100: the server, which when stopped also drops the connections it has accepted. Chrome opens spare connections ahead of need
    and a thread goes on answering on one after the listening socket is closed (on Linux the page then still gets an answer);
    a stopped program would take them with it."""

    def __init__(self, *a, **kw):
        self.accepted = []
        super().__init__(*a, **kw)

    def process_request(self, request, client_address):
        self.accepted.append(request)
        super().process_request(request, client_address)

    def drop_connections(self):
        for conn in self.accepted:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class Running:
    """A server on a free port in a thread, stopped by close() (which also drops the connections it holds, as stopping would)."""

    def __init__(self, data_for=DEMO.get, page_html=None, projects=lambda: PROJECTS, change=None, undo=None, sneak=None,
                 publisher=StubPublisher()):
        self.httpd = Stoppable((sv.HOST, 0), data_for=data_for, page_html=page_html, projects=projects, change=change,
                               undo=undo, sneak=sneak, publisher=publisher)
        self.port = self.httpd.server_port
        self.httpd.handle_error = self._quiet_when_the_client_leaves(self.httpd.handle_error)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @staticmethod
    def _quiet_when_the_client_leaves(handle_error):
        """A client that hangs up mid-reply (the browser test closes Chrome) must not print a traceback into a green run."""
        def handle(request, client_address):
            if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
                return
            handle_error(request, client_address)
        return handle

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.httpd.drop_connections()

    def ask(self, method, path, headers=None, body=None, host="default"):
        """(status, headers message, body bytes). host=None sends no Host; "default" sends 127.0.0.1:<port>."""
        conn = http.client.HTTPConnection(sv.HOST, self.port, timeout=10)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            if host == "default":
                host = f"127.0.0.1:{self.port}"
            if host is not None:
                conn.putheader("Host", host)
            for k, v in (headers.items() if hasattr(headers, "items") else headers or ()):      # a list of pairs may repeat a name
                conn.putheader(k, v)
            conn.endheaders(body)
            r = conn.getresponse()
            return r.status, r.msg, r.read()
        finally:
            conn.close()

    def api(self, method, path, body=None, ctype="application/json", token=None, extra=None, host="default"):
        h = {sv.TOKEN_HEADER: sv.TOKEN if token is None else token, **(extra or {})}
        if body is not None:
            h["Content-Type"] = ctype
            h["Content-Length"] = str(len(body))
        return self.ask(method, path, h, body, host=host)


def echo(handler, req):
    """A POST route for the tests (no POST route exists in #33 yet)."""
    return handler.send(200, {"ok": True, "got": req})


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.s = Running()
        self.addCleanup(self.s.close)

    def report(self, body, host="default", ctype="application/csp-report", extra=None):
        h = {"Content-Type": ctype, "Content-Length": str(len(body)), **(extra or {})}
        return self.s.ask("POST", sv.CSP_REPORT_ROUTE, h, body, host=host)


class Binding(ServerTest):
    """Test 1."""

    def test_it_listens_on_127_0_0_1(self):
        self.assertEqual(self.s.httpd.socket.getsockname()[0], "127.0.0.1")

    def test_any_other_address_is_refused(self):
        for address in ("0.0.0.0", "", "localhost", "::", lan_address() or "192.168.1.10"):
            with self.assertRaisesRegex(ValueError, "127.0.0.1 only"):
                sv.LocalServer((address, 0))

    def test_the_lan_address_is_not_answered(self):
        lan = lan_address()
        if not lan:
            self.skipTest("this machine has no LAN address")
        with self.assertRaises(OSError):
            socket.create_connection((lan, self.s.port), timeout=2).close()

    def test_binding_does_no_dns_lookup(self):
        code = ("import socket, sys\nsys.path.insert(0, sys.argv[1])\n"
                "def no_lookup(*a, **k):\n    raise AssertionError('getfqdn called at bind')\n"
                "socket.getfqdn = no_lookup\nfrom clark import server\n"
                "s = server.LocalServer(('127.0.0.1', 0))\n"
                "assert s.server_name == '127.0.0.1' and s.server_port > 0\ns.server_close()\nprint('ok')\n")
        r = subprocess.run([sys.executable, "-c", code, str(SRC)], capture_output=True, text=True, timeout=60)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "ok"), r.stderr)


def lan_address():
    """This machine's LAN address, or None (no packet is sent: a UDP socket only picks its route)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            ip = s.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith("127.") else ip


class HostHeader(ServerTest):
    """Test 2."""

    def test_another_host_gets_403_everywhere(self):
        for host in ("evil.example", "127.0.0.1.evil.example", "localhost.evil.example", "LOCALHOST", "", None,
                     "127.0.0.2", "[::2]:80", "0.0.0.0", "127.0.0.1:abc", "localhost:80@evil",
                     "[::1]x", "127.0.0.1:99999", "127.0.0.1:0", "localhost:", "127.0.0.1:80:80"):
            for path in ("/", "/health", "/api/data?project=DEMO"):
                status, _, _ = self.s.ask("GET", path, {sv.TOKEN_HEADER: sv.TOKEN}, host=host)
                self.assertEqual(status, 403, f"{host!r} {path}")

    def test_this_machine_passes(self):
        for host in (f"localhost:{self.s.port}", f"127.0.0.1:{self.s.port}", f"[::1]:{self.s.port}", "localhost"):
            self.assertEqual(self.s.ask("GET", "/health", host=host)[0], 200, host)


class Token(ServerTest):
    """Test 3: every /api/ route, from the route tables themselves."""

    def routes(self):
        yield from (("GET", r + ("?project=DEMO" if r == "/api/data" else "")) for r in sv.GET_ROUTES)
        yield from (("POST", r) for r in sv.POST_ROUTES)

    def test_no_wrong_or_old_token_gets_403_on_every_route(self):
        with mock.patch.dict(sv.POST_ROUTES, {"/api/echo": echo}):
            routes = list(self.routes())
            self.assertIn(("POST", "/api/echo"), routes)
            old = sv.TOKEN
            with mock.patch.object(sv, "TOKEN", "n" * len(old)):     # a restart: the page still has the old token
                for method, path in routes:
                    body = b"{}" if method == "POST" else None
                    for token in ("", "wrong", "x" * len(old), old, "tökén", sv.TOKEN.upper()):
                        status, _, data = self.s.api(method, path, body, token=token)
                        self.assertEqual(status, 403, f"{method} {path} with {token!r}")
                    self.assertTrue(json.loads(data).get("stale"))
                    status = self.s.api(method, path, body)[0]
                    if path == "/api/echo":
                        self.assertEqual(status, 200, f"{method} {path} with the token")
                    else:       # /api/change and /api/undo (#65) answer an empty request in words (400 or 503), never 403
                        self.assertNotEqual(status, 403, f"{method} {path} with the token")

    def test_no_message_names_a_keyboard_shortcut(self):
        """A shortcut is wrong on other systems: plain words say 'Reload the page'."""
        for text in [sv.STALE_PAGE, *(m for m in sv.MESSAGES.values() if isinstance(m, str))]:
            self.assertNotRegex(text, r"Cmd|Ctrl|Control\+|\bF5\b|Command", text)
        self.assertIn("Reload the page", sv.STALE_PAGE)

    def test_a_missing_token_is_not_allowed_and_only_a_wrong_one_is_told_to_reload(self):
        status, _, data = self.s.ask("GET", "/api/data?project=DEMO")
        self.assertEqual((status, json.loads(data)), (403, sv.error_body("not_allowed")))
        self.assertEqual(json.loads(data)["code"], "not_allowed")
        status, _, data = self.s.api("GET", "/api/data?project=DEMO", token="wrong")
        body = json.loads(data)
        self.assertEqual((status, body["code"], body["message"], body["stale"]), (403, "stale", sv.STALE_PAGE, True))

    def test_the_token_comes_before_a_404_under_api(self):
        self.assertEqual(self.s.ask("GET", "/api/nothing")[0], 403)
        self.assertEqual(self.s.api("GET", "/api/nothing")[0], 404)
        self.assertEqual(self.s.ask("GET", "/nothing")[0], 404)

    def test_the_comparison_is_constant_time_on_bytes(self):
        src = (SRC / "clark" / "server.py").read_text(encoding="utf-8")
        self.assertIn('hmac.compare_digest((sent or "").encode("utf-8", "surrogatepass"), TOKEN.encode("ascii"))', src)
        self.assertNotRegex(src, r"[!=]= *TOKEN\b")

    def test_the_page_carries_the_token_in_a_data_block(self):
        status, _, data = self.s.ask("GET", "/")
        boot = re.search(r'<script type="application/json" id="clark-boot">(.*?)</script>', data.decode()).group(1)
        self.assertEqual(json.loads(boot), {"token": sv.TOKEN})
        self.assertNotIn(sv.csp_sha(boot), sv.csp_hashes(data.decode())["script"], "a data block is never run or hashed")

    def test_the_token_can_t_close_the_data_block(self):
        with mock.patch.object(sv, "TOKEN", "</script><script>alert(1)"):
            self.assertNotIn("</script><script>alert", sv.with_boot(sv.PLACEHOLDER))


class Saving(ServerTest):
    """#65: POST /api/change and /api/undo. The server imports no store: it hands the request to a seam, `change` or `undo`,
    and sends the (status, body) it returns. Everything before the seam is the one dispatcher's."""

    def seams(self):
        self.calls = []

        def change(req):
            self.calls.append(("change", req))
            return 200, {"ok": True, "got": req}

        def undo(req):
            self.calls.append(("undo", req))
            return 409, {"ok": False, "message": "That step has been undone already.", "code": "undone"}
        return Running(change=change, undo=undo)

    def test_the_post_routes_are_exactly_change_undo_the_sneak_read_the_publish_ones_and_the_two_backup_ones(self):
        self.assertEqual(set(sv.POST_ROUTES), {"/api/change", "/api/undo", "/api/sneak/read", "/api/publish", "/api/client-folder", "/api/preview",
                                                  "/api/backups/preview", "/api/backups/restore"})     # #42, #43, #111, #147
        self.assertEqual(sv.POST_ROUTES["/api/sneak/read"], sv.sneak_route)
        self.assertEqual(sv.POST_ROUTES["/api/change"], sv.change_route)
        self.assertEqual(sv.POST_ROUTES["/api/undo"], sv.undo_route)
        self.assertEqual(sv.ROUTE_BODY_LIMITS, {"/api/change": 16 * 1024, "/api/undo": 1024, "/api/sneak/read": 4 * 1024,
                                                "/api/backups/preview": 1024, "/api/backups/restore": 1024})     # #42, #111
        for route in ("/api/save", "/api/changes", "/api/change/", "/api/import"):
            self.assertEqual(self.s.api("POST", route, b"{}")[0], 404, route)

    def test_no_seam_is_503(self):
        for route in ("/api/change", "/api/undo"):
            status, _, data = self.s.api("POST", route, b"{}")
            body = json.loads(data)
            self.assertEqual((status, body["message"], body["code"], body["ok"]), (503, sv.MESSAGES["saving_off"],
                                                                                  "saving_off", False), route)

    def test_a_seam_gets_the_request_and_its_answer_is_sent_as_it_is(self):
        running = self.seams()
        self.addCleanup(running.close)
        status, _, data = running.api("POST", "/api/change", b'{"project": "ABC", "op": "new"}')
        self.assertEqual((status, json.loads(data)), (200, {"ok": True, "got": {"project": "ABC", "op": "new"}}))
        status, _, data = running.api("POST", "/api/undo", b'{"apply_id": 3}')
        self.assertEqual((status, json.loads(data)["code"]), (409, "undone"))
        self.assertEqual(self.calls, [("change", {"project": "ABC", "op": "new"}), ("undo", {"apply_id": 3})])

    def test_the_dispatcher_checks_come_first_and_the_seam_is_never_called_for_them(self):
        running = self.seams()
        self.addCleanup(running.close)
        for route in ("/api/change", "/api/undo"):
            self.assertEqual(running.ask("POST", route, {"Content-Type": "application/json", "Content-Length": "2"}, b"{}")[0], 403)
            self.assertEqual(running.api("POST", route, b"{}", token="wrong")[0], 403)
            self.assertEqual(running.ask("POST", route, {sv.TOKEN_HEADER: sv.TOKEN, "Content-Type": "application/json",
                                                         "Content-Length": "2"}, b"{}", host="evil.example")[0], 403)
            self.assertEqual(running.api("POST", route, b"{}", ctype="text/plain")[0], 415)
            self.assertEqual(running.api("POST", route, b"{not json")[0], 400)
            self.assertEqual(running.ask("POST", route, {sv.TOKEN_HEADER: sv.TOKEN, "Content-Type": "application/json"})[0], 411)
            self.assertEqual(running.ask("OPTIONS", route)[0], 403)
        self.assertEqual(self.calls, [])

    def test_a_foreign_origin_or_a_cross_site_request_is_refused_before_the_seam_and_a_plain_client_is_not(self):
        running = self.seams()
        self.addCleanup(running.close)
        here = f":{running.port}"
        for route, ok in (("/api/change", 200), ("/api/undo", 409)):
            for host, extra in ((None, {}), (None, {"Origin": f"http://127.0.0.1{here}"}), (f"localhost{here}", {"Origin": f"http://localhost{here}"}),
                                (f"[::1]{here}", {"Origin": f"http://[::1]{here}"}),
                                (None, {"Sec-Fetch-Site": "same-origin"}), (None, {"Sec-Fetch-Site": "none"})):
                with self.subTest(route=route, host=host, extra=extra):      # no Origin, or this very Host and port
                    self.assertEqual(running.api("POST", route, b"{}", extra=extra, host=host or "default")[0], ok)
            before = len(self.calls)
            for extra in ({"Origin": "https://evil.example"}, {"Origin": "http://evil.example"}, {"Origin": "null"},
                          {"Origin": "http://127.0.0.1.evil.example"}, {"Origin": f"https://127.0.0.1{here}"},
                          {"Origin": "http://127.0.0.1:99999"}, {"Origin": "http://localhost@evil.example"},
                          {"Origin": f"http://localhost{here}"}, {"Origin": f"http://[::1]{here}"},      # another name for this machine: another origin
                          {"Origin": f"http://127.0.0.1:{running.port % 60000 + 1024}"}, {"Origin": "http://127.0.0.1"},    # another port, or none
                          {"Origin": f"http://127.0.0.1{here}/"}, {"Origin": f" http://127.0.0.1{here}x"},
                          {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "Cross-Site"},
                          {"Origin": f"http://127.0.0.1{here}", "Sec-Fetch-Site": "cross-site"}):
                with self.subTest(route=route, extra=extra):
                    status, _, data = running.api("POST", route, b"{}", extra=extra)
                    self.assertEqual((status, json.loads(data)), (403, sv.error_body("not_allowed")))
            self.assertEqual(len(self.calls), before, "the seam was never called for a refused request")
            for host, origin in ((None, "http://localhost:" + str(running.port)),):        # a loopback name that is not the Host's own
                self.assertEqual(running.api("POST", route, b"{}", extra={"Origin": origin}, host=host or "default")[0], 403)

    def test_every_origin_and_every_sec_fetch_site_counts_not_only_the_first(self):
        running = self.seams()
        self.addCleanup(running.close)
        own, foreign = f"http://127.0.0.1:{running.port}", "https://evil.example"
        base = [(sv.TOKEN_HEADER, sv.TOKEN), ("Content-Type", "application/json"), ("Content-Length", "2")]
        for route in ("/api/change", "/api/undo"):
            before = len(self.calls)
            for extra in ([("Origin", own), ("Origin", foreign)], [("Origin", foreign), ("Origin", own)],
                          [("Origin", own), ("Origin", "null")], [("Sec-Fetch-Site", "same-origin"), ("Sec-Fetch-Site", "cross-site")],
                          [("Sec-Fetch-Site", "cross-site"), ("Sec-Fetch-Site", "same-origin")],
                          [("Sec-Fetch-Site", "same-origin, cross-site")], [("Sec-Fetch-Site", "cross-site , same-origin")]):      # one line, two values
                with self.subTest(route=route, extra=extra):
                    status, _, data = running.ask("POST", route, base + extra, b"{}")
                    self.assertEqual((status, json.loads(data)), (403, sv.error_body("not_allowed")))
            self.assertEqual(len(self.calls), before)
            self.assertIn(running.ask("POST", route, base + [("Origin", own), ("Origin", own)], b"{}")[0], (200, 409))   # all fine: fine

    def test_change_and_undo_limits_and_415(self):
        running = self.seams()
        self.addCleanup(running.close)
        for route, limit in (("/api/change", 16 * 1024), ("/api/undo", 1024)):
            over = {sv.TOKEN_HEADER: sv.TOKEN, "Content-Type": "application/json", "Content-Length": str(limit + 1)}
            status, _, data = running.ask("POST", route, over, b"{}")
            self.assertEqual((status, json.loads(data)["code"]), (400, "too_large"), route)       # refused from its length
            pad = limit - len(b'{"a": ""}')
            fits = b'{"a": "' + b"x" * pad + b'"}'
            self.assertEqual(len(fits), limit)
            self.assertIn(running.api("POST", route, fits)[0], (200, 409), route)
            self.assertEqual(running.api("POST", route, fits + b" ")[0], 400, route)
            self.assertEqual(running.api("POST", route, b"{}", ctype="application/x-www-form-urlencoded")[0], 415)

    def test_a_get_to_change_is_404_after_the_token(self):
        for route in ("/api/change", "/api/undo"):
            self.assertEqual(self.s.ask("GET", route)[0], 403)
            self.assertEqual(self.s.api("GET", route)[0], 404)

    def test_a_fault_in_a_seam_is_the_plain_500_without_a_class_or_text(self):
        def change(req):
            raise RuntimeError("/Users/someone/secret.db is locked")
        running = Running(change=change)
        self.addCleanup(running.close)
        with self.assertLogs("clark.server", "ERROR"):
            status, _, data = running.api("POST", "/api/change", b"{}")
        self.assertEqual((status, json.loads(data)["message"]), (500, SERVER_ERROR))
        self.assertNotIn(b"RuntimeError", data)
        self.assertNotIn(b"secret", data)

    def test_the_server_imports_no_store_or_changes_module(self):
        import ast
        tree = ast.parse((SRC / "clark" / "server.py").read_text(encoding="utf-8"))
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names += [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names]
        self.assertFalse([n for n in names if n.startswith("clark") or "sqlite" in n], names)


class RealSaving(unittest.TestCase):
    """#65 end to end: the real seams (clark.changes) on a real store, through the real server. Fictional data."""

    def setUp(self):
        from _demo import DemoStore
        from clark import changes
        self.demo = DemoStore()
        self.addCleanup(self.demo.close)
        path = self.demo.store.path
        self.s = Running(change=changes.make_change(path, [], "Demo User"), undo=changes.make_undo(path, [], "Demo User"))
        self.addCleanup(self.s.close)

    def post(self, route, request):
        status, _, data = self.s.api("POST", route, json.dumps(request).encode("utf-8"))
        return status, json.loads(data)

    def test_a_change_an_undo_and_a_refusal(self):
        change = {"project": "ABC", "kind": "report_sections", "op": "update", "id": "ABC-S-005", "changes": {"title": "Via HTTP"}}
        status, body = self.post("/api/change", change)
        self.assertEqual((status, body["ok"], body["ref"]), (200, True, "ABC-S-005"))
        self.assertEqual([r["title"] for r in body["sections"] if r["id"] == "ABC-S-005"], ["Via HTTP"])
        self.assertTrue(all("body" not in r for r in body["sections"]))
        status, body = self.post("/api/undo", {"project": "ABC", "apply_id": body["apply_id"]})
        self.assertEqual((status, body["ok"], body["skipped"]), (200, True, []))
        self.assertEqual(self.demo.store.read("report_sections", ref="ABC-S-005")["title"], "Summary")
        status, body = self.post("/api/change", {**change, "changes": {"hidden": True}})
        self.assertEqual((status, body["message"], body["code"]), (400, "That must be 0 or 1.", "refused"))
        status, body = self.post("/api/change", {**change, "id": "XYZ-S-001"})
        self.assertEqual((status, body["message"]), (400, "That section isn't in this project."))

    def old_project(self, code):
        """A project made before #65: no section rows."""
        from clark import store as store_module
        with mock.patch.dict(store_module.AFTER_NEW, clear=True):
            with self.demo.store.step("dashboard", "Demo User") as st:
                st.create("projects", {"code": code, "name": "Older Programme"})

    def sections(self, code):
        from clark import order
        return [r["title"] for r in order.in_order(self.demo.store.read("report_sections", code))]

    def test_undoing_the_first_add_on_an_old_project_over_http_leaves_the_starting_sections_and_the_others(self):
        self.old_project("OLD")
        made = []
        for title in ("x", "y", "Hello"):
            status, body = self.post("/api/change", {"project": "OLD", "kind": "report_sections", "op": "new", "values": {"title": title}})
            self.assertEqual(status, 200, body)
            made.append(body["apply_id"])
        self.assertEqual(len(self.sections("OLD")), 14)
        status, body = self.post("/api/undo", {"project": "OLD", "apply_id": made[0]})
        self.assertEqual((status, body["skipped"]), (200, []))
        titles = self.sections("OLD")
        self.assertEqual((len(titles), titles[:1], titles[-2:], "x" in titles), (13, ["Current state"], ["y", "Hello"], False))

    def test_a_second_undo_of_an_old_projects_first_change_over_http_is_409_undone_already(self):
        self.old_project("OLD")
        status, body = self.post("/api/change", {"project": "OLD", "kind": "report_sections", "op": "new", "values": {"title": "Hello"}})
        self.assertEqual(status, 200, body)
        self.assertEqual(self.post("/api/undo", {"project": "OLD", "apply_id": body["apply_id"]})[0], 200)
        steps = self.demo.store.con.execute("SELECT count(*) FROM applies").fetchone()[0]
        status, again = self.post("/api/undo", {"project": "OLD", "apply_id": body["apply_id"]})
        self.assertEqual((status, again.get("ok"), again.get("message"), again.get("code")), (409, False, "That step has been undone already.", "undone"))
        self.assertEqual(self.demo.store.con.execute("SELECT count(*) FROM applies").fetchone()[0], steps, "no step was written")
        self.assertEqual(len(self.sections("OLD")), 11, "the starting sections stay")

    def test_a_rename_that_seeded_and_is_undone_leaves_all_the_starting_sections(self):
        self.old_project("OLD")
        status, body = self.post("/api/change", {"project": "OLD", "kind": "report_sections", "op": "update", "id": "OLD-S-005",
                                                 "changes": {"title": "Renamed"}})
        self.assertEqual(status, 200)
        self.assertEqual(self.post("/api/undo", {"project": "OLD", "apply_id": body["apply_id"]})[0], 200)
        titles = self.sections("OLD")
        self.assertEqual((len(titles), titles[4]), (11, "Summary"))

    def test_two_first_adds_at_once_on_an_old_project_make_one_seed_and_two_steps(self):
        self.old_project("OLD")
        results, gate = [], threading.Barrier(2)

        def add(title):
            gate.wait(5)
            results.append(self.post("/api/change", {"project": "OLD", "kind": "report_sections", "op": "new", "values": {"title": title}}))
        threads = [threading.Thread(target=add, args=(t,)) for t in ("One", "Two")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(20)
        self.assertEqual(sorted(r[0] for r in results), [200, 200], results)
        titles = self.sections("OLD")
        self.assertEqual((len(titles), sorted(titles[-2:])), (13, ["One", "Two"]))
        self.assertEqual(titles.count("Current state"), 1, "one seed")
        steps = {r[0] for r in self.demo.store.con.execute("SELECT DISTINCT apply_id FROM change_log WHERE item_id LIKE 'OLD-S-%'")}
        self.assertEqual(len(steps), 2, "one step each")
        self.assertEqual(len({r[1]["apply_id"] for r in results}), 2)

    def test_a_change_from_another_site_is_refused_and_not_made(self):
        change = {"project": "ABC", "kind": "report_sections", "op": "update", "id": "ABC-S-005", "changes": {"title": "From afar"}}
        steps = self.demo.store.con.execute("SELECT count(*) FROM applies").fetchone()[0]
        for extra in ({"Origin": "https://evil.example"}, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}):
            status, _, data = self.s.api("POST", "/api/change", json.dumps(change).encode("utf-8"), extra=extra)
            self.assertEqual((status, json.loads(data)["code"]), (403, "not_allowed"), extra)
        self.assertEqual(self.demo.store.read("report_sections", ref="ABC-S-005")["title"], "Summary")
        self.assertEqual(self.demo.store.con.execute("SELECT count(*) FROM applies").fetchone()[0], steps)
        status, _, data = self.s.api("POST", "/api/change", json.dumps(change).encode("utf-8"),
                                     extra={"Origin": f"http://127.0.0.1:{self.s.port}"})
        self.assertEqual(status, 200)                                   # the page's own Origin works

    def test_a_missing_database_is_503_in_words_and_no_empty_one_is_made(self):
        path = self.demo.store.path
        self.demo.store.close()
        for suffix in ("", "-wal", "-shm"):
            path.with_name(path.name + suffix).unlink(missing_ok=True)
        status, body = self.post("/api/change", {"project": "ABC", "kind": "report_sections", "op": "new"})
        self.assertEqual((status, body["message"]), (503, "clark's data can't be found."))
        self.assertFalse(path.exists())


class Preflight(ServerTest):
    """Test 4."""

    def test_every_options_gets_403(self):
        for path in ("/", "/health", "/api/data", "/csp-report"):
            self.assertEqual(self.s.ask("OPTIONS", path, {"Origin": "https://evil.example",
                                                          "Access-Control-Request-Method": "POST"})[0], 403, path)


class Headers(ServerTest):
    """Test 5: each security header once on every reply; the enforced policy on HTML."""

    def replies(self):
        with mock.patch.dict(sv.POST_ROUTES, {"/api/echo": echo}):
            yield "200 health", self.s.ask("GET", "/health")
            yield "200 page", self.s.ask("GET", "/")
            yield "200 api", self.s.api("GET", "/api/data?project=DEMO")
            yield "403", self.s.ask("GET", "/", host="evil.example")
            yield "404", self.s.ask("GET", "/nothing")
            yield "415", self.s.api("POST", "/api/echo", b"{}", ctype="text/plain")
            yield "400", self.s.api("POST", "/api/echo", b"{not json")
            yield "411", self.s.api("POST", "/api/echo", extra={"Content-Type": "application/json"})
            yield "204 report", self.report(b'{"csp-report": {"effective-directive": "script-src-elem", "blocked-uri": "inline"}}')
        with mock.patch.object(self.s.httpd, "data_for", side_effect=RuntimeError("/Users/someone/secret")), \
                self.assertLogs("clark.server", "ERROR"):          # the fault is logged on purpose: keep it out of the test output
            yield "500", self.s.api("GET", "/api/data?project=DEMO")
        yield "stdlib 431", raw_reply(self.s.port, b"GET / HTTP/1.1\r\nX-Long: " + b"a" * 70000 + b"\r\n\r\n")

    def test_every_reply_carries_each_security_header_once(self):
        seen = set()
        for name, (status, msg, _) in self.replies():
            seen.add(status)
            for header in SECURITY:
                self.assertEqual(len(msg.get_all(header) or []), 1, f"{name}: {header}")
            self.assertEqual(msg.get_all("Cache-Control"), ["no-store"], name)
            self.assertIn("frame-ancestors 'none'", msg.get_all("Content-Security-Policy"), name)
        self.assertEqual(seen, {200, 204, 400, 403, 404, 411, 415, 431, 500})

    def test_html_carries_both_policies_and_the_hashes_of_its_own_bytes(self):
        status, msg, data = self.s.ask("GET", "/")
        policies = msg.get_all("Content-Security-Policy")
        self.assertEqual(len(policies), 2)
        self.assertIn("frame-ancestors 'none'", policies)
        full = next(p for p in policies if p != "frame-ancestors 'none'")
        self.assertEqual(full, sv.csp_policy(data))
        h = sv.csp_hashes(data.decode())
        self.assertEqual(len(h["script"]), 1)
        self.assertIn(f"script-src {h['script'][0]};", full)
        self.assertIn(f"style-src-elem 'self' {h['style'][0]};", full)
        self.assertIsNone(msg.get("Content-Security-Policy-Report-Only"), "no second, report-only header")

    def test_the_policy_allows_nothing_from_outside(self):
        policy = sv.csp_policy(sv.with_boot(sv.PLACEHOLDER))
        for outside in ("http:", "https:", "*", "unsafe-eval"):
            self.assertNotIn(outside, policy)
        script = re.search(r"script-src ([^;]*)", policy).group(1)
        self.assertNotIn("'self'", script, "the page is one file: script-src is hashes only")
        self.assertNotIn("unsafe-inline", script)
        self.assertIn("style-src-attr 'unsafe-inline'", policy, "Preact and Tiptap set style attributes")
        self.assertIn("report-uri /csp-report", policy)
        self.assertIn("worker-src 'self'", policy)
        self.assertNotIn("blob:", re.search(r"worker-src ([^;]*)", policy).group(1))

    def test_a_500_names_only_the_kind_of_fault(self):
        with mock.patch.object(self.s.httpd, "data_for", side_effect=RuntimeError("/Users/someone/secret")), \
                self.assertLogs("clark.server", "ERROR"):
            status, _, data = self.s.api("GET", "/api/data?project=DEMO")
        self.assertEqual((status, json.loads(data)), (500, {"ok": False, "message": SERVER_ERROR, "code": "server_error"}))

    def test_a_500_never_shows_the_class_the_fault_or_a_path_and_the_log_has_them(self):
        with mock.patch.object(self.s.httpd, "data_for", side_effect=RuntimeError("/Users/someone/secret")), \
                self.assertLogs("clark.server", "ERROR") as logged:
            status, _, data = self.s.api("GET", "/api/data?project=DEMO")
        text = data.decode()
        self.assertEqual(status, 500)
        for leak in ("RuntimeError", "/Users", "secret", "Traceback", ".py"):
            self.assertNotIn(leak, text)
        self.assertEqual(json.loads(text)["message"], SERVER_ERROR)
        self.assertIn("RuntimeError", "\n".join(logged.output), "the log names the class and keeps the stack")
        self.assertIn("/Users/someone/secret", "\n".join(logged.output))

    def test_every_error_reply_has_a_plain_message_and_a_stable_code(self):
        asks = [
            ("not_allowed", self.s.ask("GET", "/", host="evil.example")),
            ("not_allowed", self.s.ask("GET", "/api/data?project=DEMO")),
            ("not_found", self.s.ask("GET", "/nothing")),
            ("send_json", self.s.api("POST", "/api/echo", b"{}", ctype="text/plain")),
            ("bad_request", self.s.api("POST", "/api/echo", b"{not json")),
            ("length_required", self.s.api("POST", "/api/echo", extra={"Content-Type": "application/json"})),
            ("too_large", self.s.api("POST", "/api/echo", extra={"Content-Type": "application/json",
                                                                      "Content-Length": str(sv.BODY_LIMIT + 1)})),
            ("bad_project_code", self.s.api("GET", "/api/data?project=x")),
            ("project_not_found", self.s.api("GET", "/api/data?project=NOPE")),
        ]
        for code, (status, _, data) in asks:
            body = json.loads(data)
            self.assertGreaterEqual(status, 400, code)
            self.assertEqual(body["code"], code)
            self.assertEqual(body["message"], sv.MESSAGES[code])
            for jargon in ("Not allowed", "Bad request", "Send JSON", "Clark", "report editor", "Exception", "Error"):
                self.assertNotIn(jargon, body["message"], code)

    def test_no_python_version_is_sent(self):
        _, msg, _ = self.s.ask("GET", "/health")
        self.assertEqual(msg.get("Server").strip(), "clark")


def raw_reply(port, raw):
    """Send raw bytes and read the reply as (status, headers, body)."""
    with socket.create_connection((sv.HOST, port), timeout=10) as s:
        s.sendall(raw)
        data = b""
        while chunk := s.recv(65536):
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1").split("\r\n")
    msg = http.client.parse_headers(io.BytesIO(("\r\n".join(lines[1:]) + "\r\n\r\n").encode("iso-8859-1")))
    return int(lines[0].split()[1]), msg, body


class BodyAndType(ServerTest):
    """Test 7."""

    def setUp(self):
        super().setUp()
        p = mock.patch.dict(sv.POST_ROUTES, {"/api/echo": echo})
        p.start()
        self.addCleanup(p.stop)

    def test_json_only(self):
        self.assertEqual(self.s.api("POST", "/api/echo", b'{"a": 1}')[0], 200)
        self.assertEqual(self.s.api("POST", "/api/echo", b'{"a": 1}', ctype="application/json; charset=utf-8")[0], 200)
        for ctype in ("text/plain", "application/jsonx", "text/json", "application/x-www-form-urlencoded",
                      "multipart/form-data; boundary=x", ""):
            self.assertEqual(self.s.api("POST", "/api/echo", b"{}", ctype=ctype)[0], 415, ctype)

    def test_the_body_limit(self):
        over = {sv.TOKEN_HEADER: sv.TOKEN, "Content-Type": "application/json", "Content-Length": str(sv.BODY_LIMIT + 1)}
        self.assertEqual(self.s.ask("POST", "/api/echo", over, b"{}")[0], 400, "refused from its length, before reading")
        fits = b'{"a": "' + b"x" * (sv.BODY_LIMIT - 20) + b'"}'
        self.assertEqual(self.s.api("POST", "/api/echo", fits)[0], 200)

    def test_bad_json_or_length_is_400(self):
        self.assertEqual(self.s.api("POST", "/api/echo", b"{not json")[0], 400)
        h = {sv.TOKEN_HEADER: sv.TOKEN, "Content-Type": "application/json", "Content-Length": "abc"}
        self.assertEqual(self.s.ask("POST", "/api/echo", h, b"{}")[0], 400)

    def test_no_length_or_chunked_is_411(self):
        h = {sv.TOKEN_HEADER: sv.TOKEN, "Content-Type": "application/json"}
        self.assertEqual(self.s.ask("POST", "/api/echo", h)[0], 411)
        self.assertEqual(self.s.ask("POST", "/api/echo", {**h, "Transfer-Encoding": "chunked"}, b"2\r\n{}\r\n0\r\n\r\n")[0],
                         411)

    def test_an_unknown_post_route_is_404_after_the_checks(self):
        self.assertEqual(self.s.api("POST", "/api/nothing", b"{}")[0], 404)
        self.assertEqual(self.s.api("POST", "/api/nothing", b"{}", token="wrong")[0], 403)


class Health(ServerTest):
    """Test 8."""

    def test_health_says_only_ok(self):
        status, msg, data = self.s.ask("GET", "/health")
        self.assertEqual((status, data), (200, b'{"ok": true}'))


class OpenRoutes(ServerTest):
    """#71: exactly six fixed files answer without the token (design-71-launcher.md, section 1); everything else still needs it."""
    SIX = {"/manifest.webmanifest", "/sw.js", "/offline", "/app/icon-192.png", "/app/icon-512.png", "/app/icon-maskable-512.png"}

    def setUp(self):
        patch = mock.patch.dict(sv.OPEN_GET_ROUTES, appfiles.open_files())      # what __main__ gives the server
        patch.start()
        self.addCleanup(patch.stop)
        super().setUp()

    def test_the_server_alone_opens_nothing_and_main_gives_it_the_six(self):
        with mock.patch.dict(sv.OPEN_GET_ROUTES, clear=True):
            self.assertEqual(self.s.ask("GET", "/sw.js")[0], 404)
            sv.set_open_files(appfiles.open_files())
            self.assertEqual(set(sv.OPEN_GET_ROUTES), self.SIX)
        src = (ROOT / "src" / "clark" / "__main__.py").read_text(encoding="utf-8")
        self.assertIn("server.set_open_files(appfiles.open_files())", src)

    def test_open_routes_are_exactly_these(self):
        self.assertEqual(set(sv.OPEN_GET_ROUTES), self.SIX)
        for path in sorted(self.SIX):
            with self.subTest(path=path):
                status, msg, data = self.s.ask("GET", path)                    # no token at all
                self.assertEqual(status, 200)
                self.assertEqual(data, sv.OPEN_GET_ROUTES[path][0])
                self.assertEqual(self.s.ask("GET", path + "?v=1")[0], 200, "a query on an icon is dropped")
                self.assertEqual(self.s.ask("GET", path, host="evil.example")[0], 403, "the Host is checked")
                self.assertEqual(self.s.ask("GET", path, host=None)[0], 403)
                self.assertEqual(self.s.ask("OPTIONS", path)[0], 403)
                self.assertNotEqual(self.s.api("POST", path, b"{}")[0], 200, "GET only")
                self.assertEqual(self.s.ask("POST", path, {"Content-Type": "application/json", "Content-Length": "2"}, b"{}")[0], 403,
                                 "a POST without the token is refused as everywhere")
                for h in SECURITY:
                    self.assertEqual(len(msg.get_all(h) or []), 1, f"{h} once on {path}")

    def test_everything_else_still_needs_the_token(self):
        for path in ("/app/x", "/app/", "/app", "/app/../health", "/app/icon-192.png/", "/app/icon-192.png.bak", "/offline/", "/sw.js/",
                     "/OFFLINE", "/Sw.js", "/manifest.json", "/manifest.webmanifest/", "/%73w.js", "/sw.js%00",
                     "/app/%2e%2e/health", "/api/projects", "/api/data?project=DEMO", "/api/here", "/favicon.ico", "/app/sw.js"):
            with self.subTest(path=path):
                status, _, data = self.s.ask("GET", path)
                self.assertIn(status, (403, 404))
                self.assertNotIn(b"clark-boot", data)
                if path.startswith("/api/"):
                    self.assertEqual(status, 403, "an API path without the token is 403")
                else:
                    self.assertEqual(status, 404, "a path that is not one of the six is not found")
        self.assertEqual(self.s.api("GET", "/app/x")[0], 404, "a token does not make a path under /app/ a route")

    def test_open_routes_are_fixed_bytes(self):
        first = {p: self.s.ask("GET", p)[2] for p in self.SIX}
        with mock.patch.object(sv, "TOKEN", "n" * len(sv.TOKEN)):               # a restart
            second = {p: self.s.ask("GET", p, {sv.TOKEN_HEADER: "ignored"})[2] for p in self.SIX}
        self.assertEqual(first, second)
        for path, data in first.items():
            self.assertNotIn(sv.TOKEN.encode(), data, path)

    def test_types_and_the_workers_own_policy(self):
        types = {p: self.s.ask("GET", p)[1] for p in self.SIX}
        self.assertTrue(types["/manifest.webmanifest"]["Content-Type"].startswith("application/manifest+json"))
        self.assertTrue(types["/sw.js"]["Content-Type"].startswith("text/javascript"))
        self.assertTrue(types["/offline"]["Content-Type"].startswith("text/html"))
        self.assertTrue(types["/app/icon-512.png"]["Content-Type"].startswith("image/png"))
        self.assertIn("default-src 'none'; connect-src 'self'", types["/sw.js"].get_all("Content-Security-Policy"))
        self.assertIsNone(types["/sw.js"]["Service-Worker-Allowed"], "the worker's scope is / and cannot be wider")
        self.assertTrue(any(v.startswith("default-src 'self'") for v in types["/offline"].get_all("Content-Security-Policy")),
                        "the offline page carries the page policy")

    def test_a_fault_in_an_open_file_is_the_one_500(self):
        with mock.patch.dict(sv.OPEN_GET_ROUTES, {"/sw.js": (None, "text/javascript", {})}), self.assertLogs("clark.server", "ERROR"):
            self.assertEqual(self.s.ask("GET", "/sw.js")[0], 500)


class HealthMark(ServerTest):
    """#71: the data mark on /health, only when asked with X-Clark-Data (test 8 above is unchanged)."""

    def setUp(self):
        super().setUp()
        patch = mock.patch.object(sv, "DATA_MARK", appfiles.data_mark("/some/folder"))
        patch.start()
        self.addCleanup(patch.stop)

    def test_health_mark_only_when_asked(self):
        mark = appfiles.data_mark("/some/folder")
        for headers, want in (({}, {"ok": True}), ({"X-Clark-Data": ""}, {"ok": True}),
                              ({"X-Clark-Data": mark}, {"ok": True, "this_data": True}),
                              ({"X-Clark-Data": "0" * 16}, {"ok": True, "this_data": False}),
                              ({"X-Clark-Data": mark.upper()}, {"ok": True, "this_data": False})):
            with self.subTest(headers=headers):
                status, _, data = self.s.ask("GET", "/health", headers)
                self.assertEqual((status, json.loads(data)), (200, want))
        self.assertEqual(self.s.ask("GET", "/health")[2], b'{"ok": true}', "a plain call is exactly as before")

    def test_a_server_with_no_mark_never_says_yes(self):
        with mock.patch.object(sv, "DATA_MARK", None):
            self.assertEqual(json.loads(self.s.ask("GET", "/health", {"X-Clark-Data": "None"})[2]), {"ok": True, "this_data": False})
            self.assertEqual(json.loads(self.s.ask("GET", "/health", {"X-Clark-Data": "x"})[2])["this_data"], False)

    def test_the_mark_is_a_hash_and_the_host_is_still_checked(self):
        self.assertEqual(self.s.ask("GET", "/health", {"X-Clark-Data": sv.DATA_MARK}, host="evil.example")[0], 403)
        self.assertEqual(self.s.ask("OPTIONS", "/health", {"X-Clark-Data": sv.DATA_MARK})[0], 403)
        self.assertNotIn("/some/folder", self.s.ask("GET", "/health", {"X-Clark-Data": sv.DATA_MARK})[2].decode())

    def test_main_gives_the_server_the_mark_of_its_data_folder(self):
        src = (ROOT / "src" / "clark" / "__main__.py").read_text(encoding="utf-8")
        self.assertIn("server.set_data_mark(appfiles.data_mark(store.path.parent))", src)


def free_port():
    with socket.socket() as s:
        s.bind((sv.HOST, 0))
        return s.getsockname()[1]


class Here(ServerTest):
    """#71: POST /api/here and the idle stop. /api/here is outside POST_ROUTES (test_the_post_routes_are_exactly_change_and_undo
    stays as it is), so the token checks the Token class makes for the table are made here for it."""

    def test_here_needs_the_token_and_the_dispatcher_checks(self):
        r = "/api/here"
        self.assertEqual(self.s.ask("POST", r, {"Content-Type": "application/json", "Content-Length": "2"}, b"{}")[0], 403)
        self.assertEqual(self.s.api("POST", r, b"{}", token="wrong")[0], 403)
        self.assertEqual(self.s.api("POST", r, b"{}", token="")[0], 403)
        old = sv.TOKEN
        with mock.patch.object(sv, "TOKEN", "n" * len(old)):
            status, _, data = self.s.api("POST", r, b"{}", token=old)
            self.assertEqual((status, json.loads(data)["code"]), (403, "stale"))
        self.assertEqual(self.s.api("POST", r, b"{}", host="evil.example")[0], 403)
        self.assertEqual(self.s.api("POST", r, b"{}", extra={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.s.api("POST", r, b"{}", ctype="text/plain")[0], 415)
        self.assertEqual(self.s.api("POST", r, b"{not json")[0], 400)
        self.assertEqual(self.s.ask("POST", r, {sv.TOKEN_HEADER: sv.TOKEN, "Content-Type": "application/json"})[0], 411)
        self.assertEqual(self.s.ask("OPTIONS", r)[0], 403)
        self.assertEqual(self.s.api("GET", r)[0], 404, "GET only: /api/here is not a GET route")
        self.assertEqual(self.s.api("POST", r, b"{}")[0], 200)
        self.assertEqual(json.loads(self.s.api("POST", r, b"{}")[2]), {"ok": True})

    def test_here_and_the_page_count_but_health_and_the_open_files_do_not(self):
        clock = [0.0]
        watch = idle.Idle(stop_after=60, clock=lambda: clock[0])
        with mock.patch.object(sv, "IDLE", watch), mock.patch.dict(sv.OPEN_GET_ROUTES, appfiles.open_files()):
            for do, counts in ((lambda: self.s.ask("GET", "/health"), False), (lambda: self.s.ask("GET", "/sw.js"), False),
                               (lambda: self.s.ask("GET", "/api/projects", {sv.TOKEN_HEADER: sv.TOKEN}), False),
                               (lambda: self.s.api("POST", "/api/here", b"{}"), True), (lambda: self.s.ask("GET", "/"), True)):
                clock[0] += 30
                watch.last = 0.0 if not counts else watch.last
                before = watch.last
                do()
                self.assertEqual(watch.last != before, counts)
                if counts:
                    self.assertEqual(watch.last, clock[0])

    def test_here_without_the_watch_is_fine_and_is_not_logged(self):
        seen = []
        handler = type("Seen", (__import__("logging").Handler,), {"emit": lambda self, record: seen.append(record.getMessage())})()
        sv.LOG.addHandler(handler)
        sv.LOG.setLevel("INFO")
        self.addCleanup(sv.LOG.removeHandler, handler)
        with mock.patch.object(sv, "IDLE", None):
            self.assertEqual(self.s.api("POST", "/api/here", b"{}")[0], 200)
            self.assertEqual(self.s.api("POST", "/api/change", b"{}")[0], 503)       # a call that is logged, so the handler works
        self.assertEqual(seen, ["POST /api/change"])

    def serving(self, watch, hold=None):
        """serve() in a thread on a free port with `watch`; (port, thread, output). `hold` is an extra POST route that waits."""
        port, out = free_port(), io.StringIO()
        p = mock.patch.object(sv, "IDLE", watch)
        p.start()
        self.addCleanup(p.stop)
        t = threading.Thread(target=lambda: self.codes.append(sv.serve(port=port, out=out, err=io.StringIO())), daemon=True)
        self.codes = []
        t.start()
        for _ in range(100):
            try:
                socket.create_connection((sv.HOST, port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.05)
        return port, t, out

    def test_idle_stop(self):
        port, t, out = self.serving(idle.Idle(stop_after=0.4, check=0.05))
        t.join(10)
        self.assertFalse(t.is_alive(), "a launcher-started server stops when no page says it is here")
        self.assertEqual(self.codes, [0])
        self.assertIn("No clark window has been open", out.getvalue())

    def test_a_page_that_keeps_saying_here_keeps_it_running(self):
        port, t, _ = self.serving(idle.Idle(stop_after=0.5, check=0.05))
        end = time.time() + 1.5
        while time.time() < end:
            c = http.client.HTTPConnection(sv.HOST, port, timeout=5)
            c.request("POST", "/api/here", b"{}", {sv.TOKEN_HEADER: sv.TOKEN, "Content-Type": "application/json", "Content-Length": "2"})
            self.assertEqual(c.getresponse().status, 200)
            c.close()
            time.sleep(0.1)
        self.assertTrue(t.is_alive())
        t.join(10)
        self.assertFalse(t.is_alive(), "and it stops once the page stops")

    def test_idle_stop_waits_for_a_running_post(self):
        started, release = threading.Event(), threading.Event()

        def slow(handler, req):
            started.set()
            release.wait(10)
            return handler.send(200, {"ok": True})
        with mock.patch.dict(sv.POST_ROUTES, {"/api/slow": slow}):
            port, t, _ = self.serving(idle.Idle(stop_after=0.3, check=0.05))
            c = http.client.HTTPConnection(sv.HOST, port, timeout=15)
            threading.Thread(target=lambda: (c.request("POST", "/api/slow", b"{}", {sv.TOKEN_HEADER: sv.TOKEN, "Content-Type": "application/json",
                                                                                   "Content-Length": "2"}), c.getresponse().read()), daemon=True).start()
            self.assertTrue(started.wait(10))
            self.assertTrue(sv.busy())
            time.sleep(1.0)
            self.assertTrue(t.is_alive(), "a running job keeps the server up, quiet for longer than the limit")
            release.set()
            t.join(10)
            self.assertFalse(t.is_alive(), "and it stops after the job")
            self.assertFalse(sv.busy())

    def test_a_stranger_cannot_hold_off_the_stop_by_asking_for_the_page(self):
        clock = [0.0]
        watch = idle.Idle(stop_after=60, clock=lambda: clock[0])
        with mock.patch.object(sv, "IDLE", watch):
            for headers, counts in (({}, True), ({"Sec-Fetch-Site": "none"}, True), ({"Sec-Fetch-Site": "same-origin"}, True),
                                    ({"Sec-Fetch-Site": "cross-site"}, False), ({"Sec-Fetch-Site": "same-site"}, False),
                                    ({"Sec-Fetch-Site": ""}, False), ({"Sec-Fetch-Site": "  "}, False),
                                    ({"Origin": "https://evil.example"}, False),
                                    ({"Origin": "https://evil.example", "Sec-Fetch-Site": "same-origin"}, False),
                                    ({"Origin": f"http://127.0.0.1:{self.s.port}"}, True)):
                clock[0] += 30
                watch.last = 0.0
                status = self.s.ask("GET", "/", headers)[0]
                self.assertEqual(status, 200, headers)
                self.assertEqual(watch.last != 0.0, counts, headers)

    def test_stopping_waits_for_a_post_that_began_just_before(self):
        started, release = threading.Event(), threading.Event()

        def slow(handler, req):
            started.set()
            release.wait(10)
            return handler.send(200, {"ok": True})
        watch = idle.Idle(stop_after=0.3, check=0.05)
        gate = threading.Event()
        orig_due = watch.due

        def due(busy=False):         # the watch looked a moment before the job was counted: it sees "not busy"
            return orig_due(False) if gate.is_set() else False
        watch.due = due
        with mock.patch.dict(sv.POST_ROUTES, {"/api/slow": slow}):
            port, t, _ = self.serving(watch)
            c = http.client.HTTPConnection(sv.HOST, port, timeout=15)
            threading.Thread(target=lambda: (c.request("POST", "/api/slow", b"{}", {sv.TOKEN_HEADER: sv.TOKEN, "Content-Type": "application/json",
                                                                                   "Content-Length": "2"}), c.getresponse().read()), daemon=True).start()
            self.assertTrue(started.wait(10))
            gate.set()
            time.sleep(1.0)
            self.assertTrue(t.is_alive(), "the server does not leave while a job that began before the stop is still running")
            release.set()
            t.join(10)
            self.assertFalse(t.is_alive())
            self.assertEqual(self.codes, [0])

    def test_a_failing_post_is_not_left_counted(self):
        def broken(handler, req):
            raise RuntimeError("x")
        with mock.patch.dict(sv.POST_ROUTES, {"/api/broken": broken}), self.assertLogs("clark.server", "ERROR"):
            self.assertEqual(self.s.api("POST", "/api/broken", b"{}")[0], 500)
        self.assertFalse(sv.busy())
        self.assertEqual(self.s.api("POST", "/api/here", b"{}")[0], 200)
        self.assertFalse(sv.busy(), "/api/here is not counted as a job")

    def test_hand_started_server_never_stops(self):
        port, t, _ = self.serving(None)
        time.sleep(1.0)
        self.assertTrue(t.is_alive())
        c = http.client.HTTPConnection(sv.HOST, port, timeout=5)
        c.request("GET", "/health")
        self.assertEqual(c.getresponse().status, 200)
        c.close()

    def test_main_starts_the_watch_only_when_launched(self):
        import clark.__main__ as cm
        seen = []
        with mock.patch.object(sv, "set_idle", side_effect=seen.append), tempfile.TemporaryDirectory() as tmp:
            for env, want in (({"CLARK_LAUNCHED": "1", "CLARK_STOP_AFTER": "7"}, True), ({}, False), ({"CLARK_LAUNCHED": "0"}, False),
                              ({"CLARK_LAUNCHED": "yes"}, False)):
                seen.clear()
                code = cm.main(["--demo", "--port", str(free_port())], out=io.StringIO(), err=io.StringIO(), environ=env, serve=lambda **kw: 0)
                self.assertEqual(code, 0)
                self.assertEqual(len(seen), 1)
                self.assertEqual(isinstance(seen[0], idle.Idle), want, env)
                if want:
                    self.assertEqual(seen[0].stop_after, 7.0)


class Data(ServerTest):
    def test_one_project(self):
        status, _, data = self.s.api("GET", "/api/data?project=DEMO")
        self.assertEqual((status, json.loads(data)), (200, {"ok": True, "project": "DEMO", "data": DEMO["DEMO"]}))

    def test_a_malformed_code_is_400_and_an_unknown_one_404(self):
        for code in ("", "DE", "demo", "DEMO1234", "DE-MO", "1DEMO", "DEMO%20"):
            self.assertEqual(self.s.api("GET", f"/api/data?project={code}")[0], 400, code)
        self.assertEqual(self.s.api("GET", "/api/data")[0], 400)
        self.assertEqual(self.s.api("GET", "/api/data?project=NOPE")[0], 404)


class ProjectList(ServerTest):
    """GET /api/projects: what the page needs to choose a project (the #36 finding)."""

    def test_the_list_has_only_a_code_and_a_name(self):
        status, msg, data = self.s.api("GET", "/api/projects")
        self.assertEqual((status, json.loads(data)), (200, {"ok": True, "projects": [
            {"code": "DEMO", "name": "Demo programme"}, {"code": "ABC", "name": "ABC"}]}))
        self.assertNotIn(b"client_name", data)
        self.assertEqual(msg.get_all("Cache-Control"), ["no-store"])

    def test_it_needs_the_token_and_this_machine(self):
        self.assertEqual(self.s.ask("GET", "/api/projects")[0], 403)
        self.assertEqual(self.s.api("GET", "/api/projects", token="wrong")[0], 403)
        self.assertEqual(self.s.api("GET", "/api/projects", extra={})[0], 200)
        status, _, _ = self.s.ask("GET", "/api/projects", {sv.TOKEN_HEADER: sv.TOKEN}, host="evil.example")
        self.assertEqual(status, 403)

    def test_odd_rows_are_skipped_and_the_list_is_capped(self):
        rows = [{"code": "OK1", "name": "Fine"}, {"code": "ab"}, {"code": "TOOLONG99", "name": "x"}, {"name": "no code"},
                "not a dict", None, {"code": "NONAME"}, {"code": "BAD-1", "name": "dash"}, {"code": "<B>", "name": "tag"}]
        s = Running(projects=lambda: rows)
        self.addCleanup(s.close)
        self.assertEqual(json.loads(s.api("GET", "/api/projects")[2])["projects"],
                         [{"code": "OK1", "name": "Fine"}, {"code": "NONAME", "name": "NONAME"}])
        many = [{"code": f"P{n:03d}", "name": f"Project {n}"} for n in range(800)]
        s2 = Running(projects=lambda: many)
        self.addCleanup(s2.close)
        got = json.loads(s2.api("GET", "/api/projects")[2])["projects"]
        self.assertEqual((len(got), got[0]["code"], got[-1]["code"]), (sv.PROJECT_LIST_LIMIT, "P000", "P499"))

    def test_a_name_is_text_and_at_most_200_characters(self):
        rows = [{"code": "LONG", "name": "n" * 500}, {"code": "NUM", "name": 12345}, {"code": "BLANK", "name": "   "},
                {"code": "LST", "name": ["a", "b"]}]
        s = Running(projects=lambda: rows)
        self.addCleanup(s.close)
        got = json.loads(s.api("GET", "/api/projects")[2])["projects"]
        self.assertEqual(got, [{"code": "LONG", "name": "n" * 200}, {"code": "NUM", "name": "NUM"},
                               {"code": "BLANK", "name": "BLANK"}, {"code": "LST", "name": "LST"}])

    def test_no_projects_is_an_empty_list(self):
        s = Running(projects=lambda: [])
        self.addCleanup(s.close)
        self.assertEqual(json.loads(s.api("GET", "/api/projects")[2]), {"ok": True, "projects": []})

    def test_a_fault_names_only_its_kind(self):
        def broken():
            raise RuntimeError("/Users/someone/secret")
        s = Running(projects=broken)
        self.addCleanup(s.close)
        with self.assertLogs("clark.server", "ERROR"):
            status, _, data = s.api("GET", "/api/projects")
        self.assertEqual((status, json.loads(data)), (500, {"ok": False, "message": SERVER_ERROR, "code": "server_error"}))

    def test_a_post_to_it_is_not_a_route(self):
        self.assertEqual(self.s.api("POST", "/api/projects", b"{}")[0], 404)


class CspReport(ServerTest):
    """/csp-report: creaite's limits, loopback only, and what is logged."""

    def test_a_report_is_logged_as_blocked_by_kind_only(self):
        body = b'{"csp-report": {"effective-directive": "script-src-elem", "blocked-uri": "https://evil.example/x.js"}}'
        with mock.patch.dict(sv.CSP_REPORTS, since=time.time(), n=0, dropped=0), \
                self.assertLogs("clark.server", "INFO") as logs:
            self.assertEqual(self.report(body)[0], 204)
        self.assertEqual(logs.output, ["INFO:clark.server:script policy blocked: script-src-elem external"])

    def test_limits(self):
        self.assertEqual((sv.CSP_REPORT_LIMIT, sv.CSP_REPORT_WINDOW, sv.CSP_REPORT_BYTES), (60, 60.0, 16 * 1024))
        self.assertEqual(self.report(b"{" + b" " * sv.CSP_REPORT_BYTES + b"}")[0], 413)
        self.assertEqual(self.report(b"{}", ctype="text/plain")[0], 415)
        self.assertEqual(self.report(b"{not json")[0], 400)
        with mock.patch.dict(sv.CSP_REPORTS, since=time.time(), n=0, dropped=0):
            self.assertEqual(sv.csp_take(59), 59)
            self.assertEqual(sv.csp_take(3), 1)
            self.assertEqual(sv.csp_take(1), 0)
            self.assertEqual(sv.CSP_REPORTS["dropped"], 3)

    def test_only_from_this_machine_s_page(self):
        body = b"{}"
        self.assertEqual(self.report(body, host="evil.example")[0], 403)
        self.assertEqual(self.report(body, extra={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.report(body, extra={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.report(body, extra={"Origin": f"http://127.0.0.1:{self.s.port}"})[0], 204)

    def test_chunked_is_411(self):
        h = {"Content-Type": "application/csp-report", "Transfer-Encoding": "chunked"}
        self.assertEqual(self.s.ask("POST", sv.CSP_REPORT_ROUTE, h, b"2\r\n{}\r\n0\r\n\r\n")[0], 411)


class RobustReplies(ServerTest):
    """The Full review's MEDIUM and LOWs: every bad request gets a reply with the headers, and nothing holds a thread."""

    def test_a_request_line_that_doesn_t_parse_gets_a_reply_with_the_headers(self):
        for raw in (b"GARBAGE\r\n\r\n", b"GET / HTTP/9.9\r\n\r\n", b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\n\r\n",
                    b"GET / HTTP/1.1 extra\r\n\r\n"):
            status, msg, _ = raw_reply(self.s.port, raw)
            self.assertIn(status, (400, 414, 505), raw[:20])
            for header in SECURITY:
                self.assertEqual(len(msg.get_all(header) or []), 1, f"{raw[:20]}: {header}")

    def test_a_request_with_no_version_gets_a_reply_and_never_a_traceback(self):
        """`GET /` with no HTTP version has no parsed headers (Python 3.15 gives a dict): the Host check refuses it."""
        for raw in (b"GET /\r\n\r\n", b"GET /health\r\n\r\n", b"GET /api/data?project=DEMO\r\n\r\n"):
            with mock.patch("sys.stderr", io.StringIO()) as err:
                with socket.create_connection((sv.HOST, self.s.port), timeout=5) as c:
                    c.sendall(raw)
                    data = b""
                    while chunk := c.recv(65536):
                        data += chunk
            self.assertIn(b'"ok": false', data, raw)
            self.assertNotIn("Traceback", err.getvalue(), raw)
        self.assertEqual(self.s.ask("GET", "/health")[0], 200, "the server still answers")

    def test_deeply_nested_json_always_gets_a_reply(self):
        """16,000 levels: Python 3.9 raises RecursionError (answered 400); a newer decoder may read it (200). Never silence."""
        with mock.patch.dict(sv.POST_ROUTES, {"/api/echo": lambda h, r: h.send(200, {"ok": True})}):
            deep = b"[" * 16000 + b"]" * 16000
            status, msg, _ = self.s.api("POST", "/api/echo", deep)
            self.assertIn(status, (200, 400))
            self.assertEqual(msg.get_all("Cache-Control"), ["no-store"])
            self.assertIn(self.report(b'{"csp-report": ' + b"[" * 5000 + b"]" * 5000 + b"}")[0], (204, 400))

    def test_a_recursion_error_while_reading_json_is_400(self):
        with mock.patch.dict(sv.POST_ROUTES, {"/api/echo": echo}), \
                mock.patch.object(sv.json, "loads", side_effect=RecursionError):
            self.assertEqual(self.s.api("POST", "/api/echo", b"[[]]")[0], 400)
            self.assertEqual(self.report(b"[[]]", ctype="application/json")[0], 400)

    def test_a_second_host_or_content_length_is_400(self):
        raw = (f"GET /health HTTP/1.1\r\nHost: 127.0.0.1:{self.s.port}\r\nHost: evil.example\r\n\r\n").encode()
        self.assertEqual(raw_reply(self.s.port, raw)[0], 400)
        raw = (f"POST /api/echo HTTP/1.1\r\nHost: 127.0.0.1:{self.s.port}\r\n{sv.TOKEN_HEADER}: {sv.TOKEN}\r\n"
               "Content-Type: application/json\r\nContent-Length: 2\r\nContent-Length: 9\r\n\r\n{}").encode()
        self.assertEqual(raw_reply(self.s.port, raw)[0], 400)
        raw = (f"POST /csp-report HTTP/1.1\r\nHost: 127.0.0.1:{self.s.port}\r\nContent-Type: application/csp-report\r\n"
               "Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}").encode()
        self.assertEqual(raw_reply(self.s.port, raw)[0], 400)

    def test_an_idle_connection_is_let_go_by_the_timeout(self):
        self.assertEqual(sv.Handler.timeout, 30)
        with mock.patch.object(sv.Handler, "timeout", 0.5), socket.create_connection((sv.HOST, self.s.port)) as c:
            c.sendall(b"POST /csp-report HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 50\r\n")   # half-sent
            c.settimeout(5)
            t0 = time.time()
            try:
                c.recv(65536)
            except ConnectionResetError:
                pass
            self.assertLess(time.time() - t0, 4, "the server let go well inside 5 s")


class Port(unittest.TestCase):
    def test_a_port_in_use_is_one_plain_line(self):
        with socket.socket() as taken:
            taken.bind((sv.HOST, 0))
            taken.listen()
            err = io.StringIO()
            self.assertEqual(sv.serve(port=taken.getsockname()[1], out=io.StringIO(), err=err), 1)
        self.assertEqual(err.getvalue(), sv.PORT_TAKEN + "\n")
        self.assertEqual(sv.PORT_TAKEN, "Nothing was started: clark is already open in another window, or another program is using the "
                                        "connection it needs. Close the other window or program, then start clark again.")
        self.assertNotIn("Port", err.getvalue())
        self.assertNotIn("--port", err.getvalue(), "no port number and no other command: one next step")

    def test_the_port_setting(self):
        with mock.patch.dict(os.environ, {"CLARK_PORT": ""}):
            self.assertEqual(sv.port_setting(), 8766)
        with mock.patch.dict(os.environ, {"CLARK_PORT": "9123"}):
            self.assertEqual(sv.port_setting(), 9123)


class Record(unittest.TestCase):
    """Test 9."""

    def test_the_copy_is_recorded(self):
        rows = [l for l in (ROOT / "docs" / "REUSE-FROM-CREAITE.md").read_text(encoding="utf-8").splitlines()
                if "live_server.py" in l and "v2.6.9 `db5adb2`" in l]
        self.assertEqual(len(rows), 1)
        for name in ("LocalServer", "host_name", "host_ok", "authorised", "do_OPTIONS", "SECURITY_HEADERS", "end_headers",
                     "send", "body", "csp_sha", "csp_hashes", "csp_policy", "csp_report_route", "/health",
                     "copied from report-only, sent enforced, worker-src cut"):
            self.assertIn(name, rows[0])


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Policy test</title></head><body>
<p id="own">waiting</p>
<script>
document.getElementById("own").textContent = "ran";
var s = document.createElement("script"); s.textContent = "window.injected = 1"; document.body.appendChild(s);
var t = document.createElement("script"); t.src = "https://example.com/outside.js"; document.body.appendChild(t);
</script>
<img src="data:," onerror="window.handler = 1" onload="window.handler = 1">
</body></html>"""


class RealBrowser(unittest.TestCase):
    """Test 6, required: in headless Chrome, the page's own script runs; an injected inline script, an outside script and
    an inline handler are blocked; and /csp-report hears of it. (#35 runs this again against the real bundle.)"""

    def test_the_policy_blocks_in_a_real_browser(self):
        self.assertTrue(Path(CHROME).is_file(), f"Chrome is needed for the required browser test: set CLARK_CHROME, or put google-chrome or chromium on the PATH ({CHROME!r})")
        s = Running(page_html=lambda: PAGE)
        self.addCleanup(s.close)
        blocked = []
        handler = _Collect(blocked)
        sv.LOG.addHandler(handler)
        sv.LOG.setLevel("INFO")
        self.addCleanup(sv.LOG.removeHandler, handler)
        with mock.patch.dict(sv.CSP_REPORTS, since=time.time(), n=0, dropped=0):
            with chrome() as cdp:
                tid = next(t["targetId"] for t in cdp.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
                sid = cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
                cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{s.port}/"}, sid)
                state = wait(lambda: cdp.js("document.getElementById('own') && document.getElementById('own').textContent",
                                            sid) == "ran")
                self.assertTrue(state, "the page's own, hashed script ran")
                self.assertTrue(wait(lambda: len(blocked) >= 2, 10), f"reports reached /csp-report: {blocked}")
                found = cdp.js("[window.injected === undefined, window.handler === undefined]", sid)
        self.assertEqual(found, [True, True], "the injected script and the inline handler were blocked")
        self.assertTrue(any("script-src" in b and "inline" in b for b in blocked), blocked)
        self.assertTrue(any("external" in b for b in blocked), blocked)


class _Collect(__import__("logging").Handler):
    def __init__(self, into):
        super().__init__()
        self.into = into

    def emit(self, record):
        if "blocked" in record.getMessage():
            self.into.append(record.getMessage())


def wait(check, seconds=15):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if check():
            return True
        time.sleep(0.2)
    return False


class _Pipe:
    """Chrome's --remote-debugging-pipe (as system/prototype/run_selftest.py): JSON messages ended by a NUL byte."""

    def __init__(self, w, r):
        self.w, self.r, self.n, self.buf = w, r, 0, b""

    def call(self, method, params=None, session=None):
        self.n += 1
        msg = {"id": self.n, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        os.write(self.w, json.dumps(msg).encode() + b"\0")
        while True:
            while b"\0" not in self.buf:
                chunk = os.read(self.r, 1 << 16)
                if not chunk:
                    raise RuntimeError("Chrome closed the pipe")
                self.buf += chunk
            raw, self.buf = self.buf.split(b"\0", 1)
            m = json.loads(raw)
            if m.get("id") == self.n:
                if "error" in m:
                    raise RuntimeError(m["error"])
                return m["result"]

    def js(self, expr, session):
        return self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True}, session)["result"].get("value")


@contextlib.contextmanager
def chrome():
    """Headless Chrome with a fresh profile, driven over its DevTools pipe. It is started and stopped through run_support
    (both keychain flags; stopped on exit, on SIGTERM and by the runner's group kill), so no dialog and no orphan (#104)."""
    to_r, to_w = os.pipe()
    from_r, from_w = os.pipe()
    prof = tempfile.mkdtemp(prefix="clark-chrome-profile-")
    try:
        proc = start_chrome(chrome_command(CHROME, prof), to_r, from_w)
        os.close(to_r)
        os.close(from_w)
        try:
            yield _Pipe(to_w, from_r)
        finally:
            stop_chrome(proc)                  # asked, waited for, killed if need be, reaped
            os.close(to_w)
            os.close(from_r)
    finally:
        remove_profile(prof)                   # not TemporaryDirectory: Chrome's helpers may still be writing (Linux)


if __name__ == "__main__":
    unittest.main()
