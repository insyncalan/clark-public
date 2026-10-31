"""#42: GET /api/activity (src/clark/server.py; guarded): the peek's Activity tab, one item's changes, owner only, read only.
Run: PYTHONPATH=../src python3 test_server_activity.py"""
import http.client
import json
import threading
import unittest
from pathlib import Path

from _demo import USER, DemoStore
from _paths import SRC
from clark import activity_read
from clark import server as sv


class Rig:
    def __init__(self, case, activity=True):
        self.demo = DemoStore()
        case.addCleanup(self.demo.close)
        store = self.demo.store
        read = activity_read.make_read(store.path, store.data_for)
        self.httpd = sv.LocalServer((sv.HOST, 0), data_for=store.data_for, projects=lambda: [], activity=read if activity else None)
        self.httpd.handle_error = lambda *a: None
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        case.addCleanup(self.close)

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def get(self, path, token=True, host=None, origin=None, body=None):
        conn = http.client.HTTPConnection(sv.HOST, self.httpd.server_port, timeout=20)
        try:
            headers = {"Host": host or f"127.0.0.1:{self.httpd.server_port}"}
            if token:
                headers[sv.TOKEN_HEADER] = sv.TOKEN
            if origin:
                headers["Origin"] = origin
            data = None
            if body is not None:
                data = body.encode()
                headers["Content-Length"] = str(len(data))
            conn.request("GET", path, data, headers)
            r = conn.getresponse()
            return r.status, json.loads(r.read())
        finally:
            conn.close()


def counts(con):
    return [con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("change_log", "item_events", "applies")]


class TheRoute(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(self)
        d = self.rig.demo
        self.action = d.action(owner="Sam Reed", priority="Low")
        d.update("actions", self.action, {"priority": "High"})
        d.update("actions", self.action, {"owner": "Jo Ellis"})

    def test_it_answers_who_how_when_and_what_newest_first_and_nothing_else(self):
        status, got = self.rig.get(f"/api/activity?project=ABC&item={self.action}")
        self.assertEqual((status, got["ok"], got["item"]), (200, True, self.action))
        self.assertEqual(set(got), {"ok", "project", "item", "activity"})
        rows = got["activity"]["rows"]
        self.assertGreaterEqual(len(rows), 3)
        for r in rows:
            self.assertTrue(set(r) <= set(activity_read.ROW_KEYS), r)
            self.assertEqual(r["who"], USER)
            self.assertTrue(r["when_text"] and r["how"])
        self.assertEqual((rows[0]["field"], rows[0]["from"], rows[0]["to"]), ("Owner", "Sam Reed", "Jo Ellis"), "newest first")
        self.assertEqual(rows[-1]["kind"], "Created")
        self.assertEqual(got["activity"]["empty"], "")

    def test_it_writes_nothing(self):
        con = self.rig.demo.store.con
        before = counts(con)
        self.rig.get(f"/api/activity?project=ABC&item={self.action}")
        self.assertEqual(counts(con), before)

    def test_a_milestone_has_its_tab_too_and_no_rows_say_so_plainly(self):
        status, got = self.rig.get(f"/api/activity?project=ABC&item={self.rig.demo.milestone}")
        self.assertEqual((status, got["activity"]["rows"][-1]["kind"]), (200, "Created"))
        from unittest import mock
        with mock.patch.object(activity_read.history, "activity_for_item", return_value={"rows": [], "closing": ""}):
            status, got = self.rig.get(f"/api/activity?project=ABC&item={self.action}")
        self.assertEqual((status, got["activity"]["rows"], got["activity"]["empty"]), (200, [], "Nothing has changed on this item yet."))

    def test_the_token_the_host_and_the_origin_are_checked(self):
        for kw in ({"token": False}, {"host": "evil.example"}, {"origin": "https://evil.example"}):
            status, got = self.rig.get(f"/api/activity?project=ABC&item={self.action}", **kw)
            self.assertEqual((status, got["ok"]), (403, False), kw)
            self.assertNotIn("activity", got)

    def test_plain_refusals(self):
        a = self.action
        for path, want, code in (("/api/activity", 400, "bad_request"), (f"/api/activity?item={a}", 400, "bad_request"),
                                 ("/api/activity?project=ABC", 400, "bad_request"),
                                 (f"/api/activity?project=abc&item={a}", 400, "bad_request"),
                                 (f"/api/activity?project=ABC&item={a}&item={a}", 400, "bad_request"),
                                 (f"/api/activity?project=ABC&item={a}&x=1", 400, "bad_request"),
                                 ("/api/activity?project=ABC&item=XYZ-A-001", 400, "bad_request"),
                                 ("/api/activity?project=ABC&item=ABC-A-" + "9" * 40, 400, "bad_request"),
                                 ("/api/activity?project=ABC&item=ABC-A-999", 404, "item_not_found"),
                                 ("/api/activity?project=ZZZ&item=ZZZ-A-001", 404, "item_not_found")):
            status, got = self.rig.get(path)
            self.assertEqual((status, got["ok"], got["code"]), (want, False, code), path)
            self.assertNotIn("Traceback", got["message"])

    def test_a_request_with_a_body_is_refused(self):
        status, got = self.rig.get(f"/api/activity?project=ABC&item={self.action}", body='{"project": "ABC"}')
        self.assertEqual((status, got["code"]), (400, "bad_request"))

    def test_a_fault_in_the_read_is_the_plain_500(self):
        def broken(code, item):
            raise RuntimeError("PLANTED-FAULT")
        self.rig.httpd.activity = broken
        status, got = self.rig.get(f"/api/activity?project=ABC&item={self.action}")
        self.assertEqual((status, got["code"]), (500, "server_error"))
        self.assertNotIn("PLANTED-FAULT", json.dumps(got))

    def test_a_long_text_is_cut_and_the_rows_are_capped(self):
        self.assertEqual(len(activity_read._short("x" * 9000)), activity_read.TEXT_LIMIT + 1)
        self.assertLessEqual(activity_read.ROW_LIMIT, 500)


class WithoutTheRead(unittest.TestCase):
    def test_no_seam_means_no_route(self):
        rig = Rig(self, activity=False)
        status, got = rig.get("/api/activity?project=ABC&item=ABC-A-001")
        self.assertEqual((status, got["code"]), (404, "not_found"))


class TheSource(unittest.TestCase):
    def read(self, name):
        return (Path(SRC) / "clark" / name).read_text(encoding="utf-8")

    def test_only_the_route_table_the_launcher_and_the_seam_know_the_route(self):
        for name in sorted(p.name for p in (Path(SRC) / "clark").glob("*.py")):
            if name in ("server.py", "__main__.py", "activity_read.py"):
                continue
            self.assertNotIn("/api/activity", self.read(name), name)

    def test_the_launcher_hands_the_server_the_read(self):
        self.assertIn("activity_read.make_read(store.path, store.data_for)", self.read("__main__.py"))
        self.assertIn('"/api/activity": activity_route', self.read("server.py"))

    def test_the_published_page_never_names_the_route(self):
        from clark import page
        self.assertNotIn("/api/activity", page.VIEW_PAGE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
