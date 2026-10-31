"""#43: POST /api/publish, POST /api/client-folder and GET /api/publication, through a real server on 127.0.0.1 (server.py,
publish_flow.py, to_client.py, publish.py). The data is the #39 plant in a real clark store; the client folder and the Local
folder are temporary folders; the system's Save and folder dialogs are replaced through one seam each. Nothing leaves the
machine and no Chrome is started: the page's own tests are tests/test_publish_dialog.py.

Run: python3 dev/run_tests.py test_publish_route
"""
import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import _publish_fixture as fx
from _paths import SRC  # noqa: F401  (puts src/ on the path)
from clark import changes, page, platform, publish, publish_flow, server as sv, to_client
from clark.store import Invalid, Store, open_store

EMPTY_BRANDING = tempfile.mkdtemp(prefix="clark-no-brand-")          # so a brand on this laptop never changes a test
DAY = "2026-10-28"
WANTED = "PUB-report-2026-10-23.html"                                  # the plant's week ending
USER = "Sam Carter"


class Rig:
    """A server over a publisher, a plant database, a Local folder, a client folder and fake dialogs."""

    def __init__(self, case, saved=True, branding=EMPTY_BRANDING):
        tmp = tempfile.TemporaryDirectory()
        case.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.onedrive = self.root / "OneDrive-Fictional"
        self.client = self.onedrive / "Client reports" / "Harbour Bridge"
        self.client.mkdir(parents=True)
        self.local = self.root / "Local"
        self.local.mkdir()
        self.data_dir = self.root / "clark-data"
        self.data_dir.mkdir()
        self.db = self.data_dir / "clark.db"
        self.plant = fx.load()
        fx.build_db(self.db, self.plant)
        self.store = open_store(self.db, onedrive_roots=[])
        case.addCleanup(self.store.close)
        self.saves, self.picks = [], []
        self.save_to = self.local / "chosen.html"              # what the Save dialog answers; None is Cancel
        self.pick = None                                      # what the folder dialog answers
        self.set_folder(str(self.client) if saved else None)          # the plant's own folder is not a real one
        self.publisher = publish_flow.Publisher(self.db, [str(self.onedrive)], choose_save_file=self.save_dialog,
                                                choose_folder=self.folder_dialog, today=lambda: DAY, by_user=lambda: USER,
                                                data_dir=self.data_dir, branding=branding)
        self.httpd = sv.LocalServer((sv.HOST, 0), data_for=self.store.data_for, page_html=lambda: page.page_html(branding),
                                    projects=lambda: [{"code": "PUB", "name": "Harbour Bridge Programme"}], publisher=self.publisher,
                                    change=changes.make_change(self.db, [], USER), undo=changes.make_undo(self.db, [], USER))
        self.httpd.handle_error = lambda *a: None
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        case.addCleanup(self.close)

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def set_folder(self, folder):
        with self.store.step("dashboard", USER) as st:
            st.update("projects", "PUB", {"publish_client": folder})

    def save_dialog(self, prompt, default_name, start=None):
        self.saves.append((prompt, default_name, start))
        return self.save_to

    def folder_dialog(self, prompt, start=None):
        self.picks.append((prompt, start))
        return self.pick

    def call(self, method, path, body=None, token=None, host=None):
        conn = http.client.HTTPConnection(sv.HOST, self.httpd.server_port, timeout=20)
        try:
            data = None if body is None else json.dumps(body).encode()
            headers = {"Host": host or f"127.0.0.1:{self.httpd.server_port}"}
            if token is not False:
                headers[sv.TOKEN_HEADER] = token or sv.TOKEN
            if data is not None:
                headers.update({"Content-Type": "application/json", "Content-Length": str(len(data))})
            conn.request(method, path, data, headers)
            r = conn.getresponse()
            raw = r.read()
            try:
                return r.status, json.loads(raw) if raw else None
            except ValueError:               # a download (the workbook) is a file, not JSON
                return r.status, raw
        finally:
            conn.close()

    def publish(self, **body):
        body.setdefault("project", "PUB")
        return self.call("POST", "/api/publish", body)

    def rows(self):
        con = open_store(self.db, onedrive_roots=[]).con
        try:
            return [dict(r) for r in con.execute("SELECT * FROM publications ORDER BY seq")]
        finally:
            con.close()

    def listing(self, folder):
        return sorted(p.name for p in Path(folder).iterdir())

    def everything_written(self):
        """Every file under the root except the database and clark's own database backups (the set-up takes the day's copy when it
        first writes): what a publish leaves on the disk."""
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*")
                      if p.is_file() and not p.name.startswith("clark.db") and p.parent.name != "backups")


class Base(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(self)


class TheCopy(Base):
    def test_copy_is_byte_for_byte_and_logged(self):
        status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["ok"], got["action"]), (200, True, "done"), got)
        local, client = self.rig.local / "chosen.html", self.rig.client / WANTED
        self.assertEqual(local.read_bytes(), client.read_bytes())
        digest = hashlib.sha256(client.read_bytes()).hexdigest()
        (row,) = self.rig.rows()
        self.assertEqual((row["project"], row["local_path"], row["client_path"], row["file_sha256"], row["checks"],
                          row["by_user"], row["week_ending"], row["word"]),
                         ("PUB", str(local), str(client), digest, "not needed", USER, "2026-10-23", 0))
        self.assertEqual(self.rig.listing(self.rig.client), [WANTED], "no .part file, no backup")
        self.assertIn("copied to the client folder", got["message"])
        self.assertNotIn(str(self.rig.client), json.dumps(got), "the reply names no folder")

    def test_the_copy_holds_none_of_the_planted_markers_and_all_of_the_kept_ones(self):
        self.rig.publish(to_client=True)
        copy = (self.rig.client / WANTED).read_bytes().decode("utf-8")
        for key, marker in self.rig.plant["markers"].items():       # a hidden row, a flag-off row, a Sensitive row, an internal note...
            for spelling in fx.spellings(marker):
                self.assertNotIn(spelling, copy, f"{key}: {spelling!r} is in the copy")
        for key, marker in self.rig.plant["kept_markers"].items():
            self.assertTrue(any(s in copy for s in fx.spellings(marker)), f"{key}: {marker!r} is missing from the copy")
        self.assertEqual(publish.outside_addresses(copy), [])
        self.assertNotIn(str(self.rig.client), copy)

    def test_a_new_work_item_from_the_writer_is_in_the_copy(self):
        with self.rig.store.step("dashboard", USER) as st:
            ref = st.create("actions", {"project": "PUB", "description": "Fictional new item from the writer", "raised": "2026-10-20",
                                        "source": "demo"})
        self.assertEqual(self.rig.store.read("actions", ref=ref)["client_visible"], 1, "the flag is on by default")
        self.rig.publish(to_client=True)
        self.assertIn(ref, (self.rig.client / WANTED).read_text(encoding="utf-8"))
        self.assertIn("Fictional new item from the writer", (self.rig.client / WANTED).read_text(encoding="utf-8"))

    def test_a_row_with_the_flag_off_made_through_the_writer_is_absent(self):
        with self.rig.store.step("dashboard", USER) as st:
            ref = st.create("actions", {"project": "PUB", "description": "Fictional private matter ZQ-LATE-FLAG-OFF",
                                        "raised": "2026-10-20", "source": "demo"})
            st.update("actions", ref, {"client_visible": 0})
            mref = st.create("milestones", {"project": "PUB", "name": "Fictional kept milestone", "baseline_date": "2026-12-01",
                                            "source": "demo"})
            st.update("milestones", mref, {"internal_note": "ZQ-LATE-INTERNAL-NOTE for us only"})
        self.rig.publish(to_client=True)
        copy = (self.rig.client / WANTED).read_text(encoding="utf-8")
        for absent in ("ZQ-LATE-FLAG-OFF", "ZQ-LATE-INTERNAL-NOTE", ref):
            self.assertNotIn(absent, copy)

    def test_unticked_leaves_the_client_folder_untouched(self):
        before = {p.name: p.stat().st_mtime_ns for p in self.rig.client.iterdir()}
        status, got = self.rig.publish(to_client=False)
        self.assertEqual((status, got["ok"], got["to_client"]), (200, True, False))
        self.assertEqual({p.name: p.stat().st_mtime_ns for p in self.rig.client.iterdir()}, before)
        self.assertEqual(list(self.rig.client.iterdir()), [])
        (row,) = self.rig.rows()
        self.assertIsNone(row["client_path"])
        self.assertEqual(self.rig.rows()[0]["local_path"], str(self.rig.local / "chosen.html"))

    def test_leaving_to_client_out_means_local_only(self):
        self.rig.publish()
        self.assertEqual(list(self.rig.client.iterdir()), [])
        self.assertTrue((self.rig.local / "chosen.html").exists())

    def test_the_save_dialog_is_offered_the_standard_name_and_the_last_folder(self):
        self.rig.publish()
        self.rig.save_to = self.rig.local / "second.html"
        self.rig.publish()
        self.assertEqual([s[1] for s in self.rig.saves], [WANTED, WANTED])
        self.assertEqual([s[2] for s in self.rig.saves], [None, str(self.rig.local)])


class NothingWritten(Base):
    def test_cancelling_the_save_dialog_cancels_everything(self):
        self.rig.save_to = None
        status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["ok"], got["code"]), (200, False, "cancelled"))
        self.assertEqual(self.rig.everything_written(), [])
        self.assertEqual(self.rig.rows(), [])

    def test_a_folder_that_has_gone_writes_nothing_at_all_not_even_local(self):
        gone = self.rig.client.parent / "Gone"
        self.rig.set_folder(str(gone))
        status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["ok"], got["code"]), (409, False, "refused"))
        self.assertIn("Nothing was published", got["message"])
        self.assertIn("isn't there", got["message"])
        self.assertEqual((self.rig.everything_written(), self.rig.rows(), self.rig.saves), ([], [], []), "no dialog either")
        self.assertFalse(gone.exists())

    def test_no_folder_saved_is_refused_before_anything(self):
        rig = Rig(self, saved=False)
        status, got = rig.publish(to_client=True)
        self.assertEqual((status, got["ok"], got["code"]), (400, False, "not_saved"))
        self.assertEqual(got["message"], "No client folder yet. Set it in Settings.")
        self.assertEqual((rig.everything_written(), rig.rows()), ([], []))

    def test_a_client_folder_that_is_clarks_own_data_folder_is_refused(self):
        self.rig.set_folder(str(self.rig.data_dir))
        before = self.rig.everything_written()
        status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["code"]), (409, "refused"))
        self.assertEqual(self.rig.everything_written(), before)

    def test_text_that_must_be_left_out_is_held_back_before_any_write(self):
        with mock.patch.object(publish_flow, "markers_for", return_value=["Harbour"]):
            status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["ok"], got["code"]), (409, False, "refused"))
        self.assertIn("must not go to the client", got["message"])
        self.assertEqual((self.rig.everything_written(), self.rig.rows(), self.rig.saves), ([], [], []))

    def test_an_outside_address_in_the_file_is_held_back(self):
        real = publish.build

        def leaky(*a, **k):
            built = real(*a, **k)
            body = built["body"].replace(b"</body>", b'<img src="https://x.invalid/p.png"></body>')
            return dict(built, body=body, sha256=hashlib.sha256(body).hexdigest())
        with mock.patch.object(publish, "build", leaky):
            status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["code"]), (409, "refused"))
        self.assertEqual((self.rig.everything_written(), self.rig.rows()), ([], []))

    def test_a_link_tag_from_the_brand_says_it_is_the_brands_css(self):
        brand = Path(tempfile.mkdtemp(prefix="clark-brand-"))
        self.addCleanup(lambda: [p.unlink() for p in brand.iterdir()] or brand.rmdir())
        (brand / "tokens.css").write_text(':root { --x: 1; } /* kept out */ .a::after { content: "<link rel=stylesheet href=x>"; }\n',
                                          encoding="utf-8")
        rig = Rig(self, branding=str(brand))
        status, got = rig.publish(to_client=True)
        self.assertEqual((status, got["code"]), (409, "refused"), got)
        self.assertIn("The web link comes from the brand's styling file, not from anything you wrote: ask whoever looks after the brand to remove it.", got["message"])
        self.assertNotRegex(got["message"], r"(?i)<link>|tokens\.css|\bCSS\b|\btag\b")
        self.assertEqual((rig.everything_written(), rig.rows()), ([], []))

    def test_local_only_is_not_held_by_the_client_checks(self):
        with mock.patch.object(publish_flow, "markers_for", return_value=["Harbour"]):
            status, got = self.rig.publish(to_client=False)
        self.assertEqual((status, got["ok"]), (200, True))

    def test_the_local_folder_may_not_be_the_client_folder(self):
        self.rig.save_to = self.rig.client / "mine.html"
        status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["code"]), (409, "same_folder"))
        self.assertEqual((self.rig.listing(self.rig.client), self.rig.rows()), ([], []))


class LocalNeverLandsInTheClientFolder(Base):
    """#43 review, MEDIUM 1: a Local save is refused in the saved client folder or below it, ticked or not."""

    def check(self, save_to, **body):
        self.rig.save_to = save_to
        before = self.rig.listing(self.rig.client)
        status, got = self.rig.publish(**body)
        self.assertEqual((status, got["code"]), (409, "same_folder"), got)
        self.assertEqual((self.rig.listing(self.rig.client), self.rig.rows()), (before, []))

    def test_local_only_into_the_client_folder_is_refused(self):
        self.check(self.rig.client / "mine.html", to_client=False)
        self.check(self.rig.client / "mine.html")

    def test_local_only_into_a_subfolder_of_the_client_folder_is_refused(self):
        sub = self.rig.client / "Drafts" / "More"
        sub.mkdir(parents=True)
        self.check(sub / "mine.html", to_client=False)
        self.check(sub / "mine.html", to_client=True)


class LocalNeverOverwritesClarksOwnFiles(Base):
    """#43 review, MEDIUM 2: the Save dialog can't choose the database, the data folder, the backups, or a non-.html name."""

    def test_the_database_is_untouched(self):
        before = self.rig.db.read_bytes()
        for target in (self.rig.db, self.rig.data_dir / "other.html", self.rig.data_dir / "sub" / "x.html"):
            self.rig.save_to = target
            status, got = self.rig.publish()
            self.assertEqual((status, got["ok"]), (409, False), got)
            self.assertIn("Nothing was published", got["message"])
        self.assertEqual(self.rig.db.read_bytes(), before)
        self.assertEqual(self.rig.rows(), [])

    def test_the_backups_folder_is_refused(self):
        backups = self.rig.root / "backups"
        backups.mkdir()
        self.rig.publisher.backups_dir = backups
        self.rig.save_to = backups / "x.html"
        status, got = self.rig.publish()
        self.assertEqual((status, got["ok"]), (409, False))
        self.assertEqual(self.rig.listing(backups), [])

    def test_only_html_names_are_saved(self):
        self.rig.save_to = self.rig.local / "report.txt"
        status, got = self.rig.publish()
        self.assertEqual((status, got["code"]), (409, "local_not_html"))
        self.assertEqual(self.rig.listing(self.rig.local), [])


class AFalseMarkerDoesNotBlock(Base):
    """#43 review (attacker 3): a note made of the page's own words is no marker; a real leak names the item."""

    def milestone_with_note(self, note):
        with self.rig.store.step("dashboard", USER) as st:
            ref = st.create("milestones", {"project": "PUB", "name": "Fictional kept milestone", "baseline_date": "2026-12-01",
                                           "source": "demo"})
            st.update("milestones", ref, {"internal_note": note})
        return ref

    def test_notes_made_of_the_pages_own_words_do_not_block_to_client(self):
        for note in ("Milestones", "background", "Milestones background"):
            self.milestone_with_note(note * 2 if len(note) < 8 else note)
        status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["ok"], got["action"]), (200, True, "done"), got)

    def test_a_real_leak_names_the_item(self):
        ref = self.milestone_with_note("ZQ-SECRET-NOTE for us only")
        with mock.patch.object(publish, "select", side_effect=lambda inputs, real=publish.select: _leak(real(inputs))):
            status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["code"]), (409, "refused"), got)
        self.assertIn("Look at: " + ref, got["message"])
        self.assertEqual((self.rig.everything_written(), self.rig.rows()), ([], []))


def _leak(published):
    """A selection that wrongly keeps a note in a kept row's description."""
    published["data"]["milestones"][-1]["description"] = "ZQ-SECRET-NOTE for us only"
    return published


class AFlagTurnedOffWhileTheSaveWindowIsOpen(Base):
    """#43 review (attacker, LOW): what the client gets is what the data says when the window closes."""

    def test_the_copy_and_local_leave_out_a_row_turned_off_meanwhile(self):
        with self.rig.store.step("dashboard", USER) as st:
            ref = st.create("actions", {"project": "PUB", "description": "Fictional ZQ-FLIPPED-WHILE-OPEN item",
                                        "raised": "2026-10-20", "source": "demo"})
        real = self.rig.save_dialog

        def dialog(prompt, default_name, start=None):
            other = open_store(self.rig.db, onedrive_roots=[])           # the dialog runs on the server's thread
            try:
                with other.step("dashboard", USER) as st:
                    st.update("actions", ref, {"client_visible": 0})
            finally:
                other.close()
            return real(prompt, default_name, start)
        self.rig.publisher.choose_save_file = dialog
        status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["ok"]), (200, True), got)
        for path in (self.rig.client / WANTED, self.rig.local / "chosen.html"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("ZQ-FLIPPED-WHILE-OPEN", text)
            self.assertNotIn(ref, text)
        self.assertEqual((self.rig.client / WANTED).read_bytes(), (self.rig.local / "chosen.html").read_bytes())


class TheClientFolderChangedWhileTheSaveWindowIsOpen(Base):
    """#43 review (fresh reader, MEDIUM): the client folder is checked again after the Save window, always, and the copy goes only
    to the real folder that check finds."""

    def during_dialog(self, action):
        real = self.rig.save_dialog

        def dialog(prompt, default_name, start=None):
            action()
            return real(prompt, default_name, start)
        self.rig.publisher.choose_save_file = dialog

    def data_files(self):
        return sorted(p.name for p in self.rig.data_dir.iterdir() if not p.name.startswith("clark.db") and p.name != "backups")

    def test_a_link_to_clarks_data_folder_swapped_in_copies_nothing(self):
        def swap():
            self.rig.client.rmdir()
            self.rig.client.symlink_to(self.rig.data_dir, target_is_directory=True)
        self.during_dialog(swap)
        status, got = self.rig.publish(to_client=True)
        self.assertFalse(got["ok"], got)
        self.assertNotIn("copied to the client folder", got["message"])
        self.assertEqual(self.data_files(), [], "nothing next to the database")
        self.assertEqual(self.rig.listing(self.rig.local), [], "and Local was not written either")
        self.assertEqual(self.rig.rows(), [])

    def test_a_link_swapped_in_after_the_second_check_is_refused_by_the_copy(self):
        real = self.rig.publisher.write_local

        def write_local(dest, data, digest):
            out = real(dest, data, digest)
            self.rig.client.rmdir()
            self.rig.client.symlink_to(self.rig.data_dir, target_is_directory=True)
            return out
        self.rig.publisher.write_local = write_local
        status, got = self.rig.publish(to_client=True)
        self.assertFalse(got["ok"], got)
        self.assertEqual(self.data_files(), [])
        self.assertTrue(got["local_saved"], "Local is kept")

    def test_a_link_to_another_real_folder_gets_the_copy_at_that_real_folder(self):
        """As designed: the new place is checked afresh and is a good folder, so the copy goes there (its real path), never to
        the saved spelling."""
        other = self.rig.onedrive / "Client reports" / "Elsewhere"
        other.mkdir()

        def swap():
            self.rig.client.rmdir()
            self.rig.client.symlink_to(other, target_is_directory=True)
        self.during_dialog(swap)
        status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["ok"]), (200, True), got)
        self.assertEqual(self.rig.listing(other), [WANTED])
        self.assertEqual(self.data_files(), [])
        (row,) = self.rig.rows()
        self.assertEqual(row["client_path"], str(other / WANTED))

    def test_a_folder_removed_meanwhile_fails_safe(self):
        self.during_dialog(self.rig.client.rmdir)
        status, got = self.rig.publish(to_client=True)
        self.assertFalse(got["ok"], got)
        self.assertFalse(self.rig.client.exists())
        self.assertEqual(self.rig.listing(self.rig.local), [])
        self.assertEqual(self.rig.rows(), [])


class SmallerFindings(Base):
    """#43 review LOWs."""

    def test_a_saved_folder_of_slash_dotdot_or_home_gets_the_folder_message(self):
        for saved in ("/", "..", "~"):
            self.rig.set_folder(saved)
            status, got = self.rig.publish(to_client=True)
            self.assertEqual((status, got["code"]), (409, "refused"), (saved, got))
            self.assertNotIn("must not go to the client", got["message"], saved)
            self.assertIn("Nothing was published", got["message"])
        self.assertEqual((self.rig.everything_written(), self.rig.rows()), ([], []))

    def test_a_nul_in_the_saved_folder_is_refused_in_words(self):
        self.rig.set_folder("/tmp/x\x00y")
        status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["code"]), (409, "refused"), got)
        self.assertEqual(got["message"], "The saved client folder can't be used. Choose it again in Settings. Nothing was published.")

    def test_a_direction_changing_character_in_a_rename_is_refused(self):
        (self.rig.client / WANTED).write_bytes(b"other")
        status, got = self.rig.publish(to_client=True, on_clash="rename", new_name="report\u202egpj")
        self.assertEqual((status, got["code"]), (409, "refused"), got)
        self.assertIn("character clark can't use", got["message"])
        self.assertEqual(self.rig.listing(self.rig.client), [WANTED])

    def test_line_and_paragraph_separators_and_odd_spaces_in_a_rename_are_refused_but_a_plain_space_is_not(self):
        (self.rig.client / WANTED).write_bytes(b"other")
        for bad in ("a\u2028b", "a\u2029b", "a\u202fb", "a\u00a0b"):
            with self.subTest(repr(bad)):
                status, got = self.rig.publish(to_client=True, on_clash="rename", new_name=bad)
                self.assertEqual((status, got["code"]), (409, "refused"), got)
                self.assertIn("character clark can't use", got["message"])
        status, got = self.rig.publish(to_client=True, on_clash="rename", new_name="my report")
        self.assertEqual(status, 200, got)

    def test_a_nul_in_the_local_save_path_is_said_in_words_not_a_fault(self):
        self.rig.save_to = "/tmp/x\x00y.html"
        status, got = self.rig.publish()
        self.assertEqual((status, got["code"]), (409, "local_failed"), got)
        self.assertEqual(got["message"], "The file could not be saved. Check you can edit that folder and that the disk has room, then try again. Nothing was published.")
        self.assertEqual((self.rig.everything_written(), self.rig.rows()), ([], []))

    def test_a_folder_outside_onedrive_warns_when_publishing_too(self):
        elsewhere = self.rig.root / "Elsewhere"
        elsewhere.mkdir()
        self.rig.set_folder(str(elsewhere))
        status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["ok"]), (200, True), got)
        self.assertIn("isn't one OneDrive syncs", got["warning"])
        self.assertIn("isn't one OneDrive syncs", got["message"])


class AfterLocal(Base):
    def test_a_refused_copy_keeps_local_and_logs_no_client_path(self):
        with mock.patch.object(platform, "write_file_unless_exists", side_effect=OSError(13, "Permission denied")):
            status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["ok"], got["local_saved"]), (409, False, True))
        self.assertTrue(got["message"].startswith("Saved locally, but not copied to the client folder"), got["message"])
        self.assertTrue((self.rig.local / "chosen.html").exists())
        self.assertEqual(self.rig.listing(self.rig.client), [])
        (row,) = self.rig.rows()
        self.assertIsNone(row["client_path"])
        self.assertNotRegex(got["message"], r"(?i)errno|traceback|sha|api|route")

    def test_a_locked_file_message_is_plain(self):
        with mock.patch.object(platform, "write_file_unless_exists",
                               side_effect=platform.PlatformError("X couldn't be saved because another program is using it or it is locked. Close it there and try again.")):
            status, got = self.rig.publish(to_client=True)
        self.assertIn("another program is using it", got["message"])
        self.assertEqual(self.rig.rows()[0]["client_path"], None)

    def test_a_copy_that_differs_is_removed_and_not_logged(self):
        real = to_client.RealFs.read_bytes
        client = self.rig.client

        seen = []

        def read_back(fs, path, limit=None):
            data = real(fs, path, limit)
            if Path(path).parent == client and not seen:          # only the read-back is wrong; the proof it is ours is not
                seen.append(1)
                return data + b" "
            return data
        with mock.patch.object(to_client.RealFs, "read_bytes", read_back):
            status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["ok"]), (409, False))
        self.assertIn("did not match", got["message"])
        self.assertEqual(self.rig.listing(self.rig.client), [], "the copy this publish made is taken back")
        self.assertIsNone(self.rig.rows()[0]["client_path"])
        self.assertTrue((self.rig.local / "chosen.html").exists())

    def test_a_failed_record_says_the_files_are_fine(self):
        with mock.patch.object(Store, "log_publication", side_effect=Invalid("clark's data is busy")):
            status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["code"], got["local_saved"]), (409, "not_recorded", True))
        self.assertIn("publish again to record it", got["message"])
        self.assertEqual(self.rig.listing(self.rig.client), [WANTED])


class AnythingGoingWrongAfterTheWrite(Base):
    """#43 review (attacker 1, reader LOW): whatever fails between the copy's write and its check, the copy this call made is
    taken back; a file someone else put there is never removed."""

    def read_back_raises(self, error):
        real, client = to_client.RealFs.read_bytes, self.rig.client

        seen = []

        def read(fs, path, limit=None):
            if Path(path).parent == client and not seen:
                seen.append(1)
                raise error
            return real(fs, path, limit)
        return mock.patch.object(to_client.RealFs, "read_bytes", read)

    def test_a_runtime_error_in_the_read_back_removes_the_copy(self):
        with self.read_back_raises(RuntimeError("boom")):
            status, got = self.rig.publish(to_client=True)
        self.assertEqual(status, 409, got)
        self.assertEqual(self.rig.listing(self.rig.client), [], "nothing unverified is left in the client folder")
        self.assertTrue((self.rig.local / "chosen.html").exists())
        (row,) = self.rig.rows()
        self.assertIsNone(row["client_path"])

    def test_a_check_that_raises_removes_the_copy(self):
        real = to_client.check_copy
        calls = []

        def check(data, **kw):
            calls.append(1)
            if len(calls) >= 3:               # the first two are before anything is written
                raise ValueError("bad")
            return real(data, **kw)
        with mock.patch.object(to_client, "check_copy", check):
            status, got = self.rig.publish(to_client=True)
        self.assertEqual(len(calls), 3)
        self.assertEqual((status, self.rig.listing(self.rig.client)), (409, []))

    def test_a_file_someone_else_put_there_is_left_alone(self):
        real, client = to_client.RealFs.read_bytes, self.rig.client

        def read(fs, path, limit=None):
            if Path(path).parent == client:
                Path(path).unlink()
                Path(path).write_bytes(b"someone else's file")      # a different file (a new inode) under the same name
                return b"someone else's file"
            return real(fs, path, limit)
        with mock.patch.object(to_client.RealFs, "read_bytes", read):
            status, got = self.rig.publish(to_client=True)
        self.assertEqual(status, 409)
        self.assertEqual((self.rig.client / WANTED).read_bytes(), b"someone else's file")

    def test_a_stale_part_file_is_cleaned_on_the_next_publish_and_a_fresh_one_is_not(self):
        import os
        import time
        stale = self.rig.client / f".{WANTED}.123.0a1b2c3d.part"
        fresh = self.rig.client / f".{WANTED}.124.0a1b2c3e.part"
        other = self.rig.client / ".notes.txt"
        for f in (stale, fresh, other):
            f.write_bytes(b"x")
        old = time.time() - 3600
        os.utime(stale, (old, old))
        os.utime(other, (old, old))
        status, got = self.rig.publish(to_client=True)
        self.assertEqual(status, 200, got)
        self.assertEqual(self.rig.listing(self.rig.client), sorted([fresh.name, other.name, WANTED]))


class TheTakenName(Base):
    def setUp(self):
        super().setUp()
        self.rig.publish(to_client=True)
        self.rig.saves.clear()
        self.taken = (self.rig.client / WANTED)
        self.taken.write_bytes(b"<!doctype html>a different earlier file")
        self.rig.save_to = self.rig.local / "second.html"

    def test_a_taken_name_asks_and_writes_nothing(self):
        before = self.rig.everything_written()
        status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["ok"], got["clash"], got["can_overwrite"]), (200, False, True, True))
        self.assertEqual(got["numbered"], "PUB-report-2026-10-23 (2).html")
        self.assertEqual((self.rig.everything_written(), self.rig.saves, len(self.rig.rows())), (before, [], 1))
        self.assertEqual(self.taken.read_bytes(), b"<!doctype html>a different earlier file")

    def test_add_a_number(self):
        status, got = self.rig.publish(to_client=True, on_clash="number")
        self.assertEqual((status, got["ok"], got["name"]), (200, True, "PUB-report-2026-10-23 (2).html"))
        self.assertEqual(self.rig.listing(self.rig.client), sorted([WANTED, "PUB-report-2026-10-23 (2).html"]))
        self.assertEqual(self.taken.read_bytes(), b"<!doctype html>a different earlier file")

    def test_rename_it(self):
        status, got = self.rig.publish(to_client=True, on_clash="rename", new_name="Week 43 report")
        self.assertEqual((status, got["ok"]), (200, True), got)
        self.assertEqual(self.rig.listing(self.rig.client), sorted([WANTED, "Week 43 report.html"]))

    def test_a_rename_that_is_taken_asks_again(self):
        status, got = self.rig.publish(to_client=True, on_clash="rename", new_name=WANTED.upper())
        self.assertEqual((status, got.get("clash")), (200, True))
        self.assertEqual(self.rig.listing(self.rig.client), [WANTED])

    def test_overwrite_needs_confirmed_true_exactly(self):
        for body in ({"on_clash": "overwrite"}, {"on_clash": "overwrite", "confirmed": "true"}, {"on_clash": "overwrite", "confirmed": 1},
                     {"on_clash": "overwrite", "confirmed": False}):
            with self.subTest(body=body):
                status, got = self.rig.publish(to_client=True, **body)
                self.assertEqual((status, got["ok"]), (400, False))
                self.assertEqual(self.taken.read_bytes(), b"<!doctype html>a different earlier file")
        self.assertEqual(self.rig.saves, [])

    def test_a_confirmed_overwrite_replaces_it_with_no_backup(self):
        status, got = self.rig.publish(to_client=True, on_clash="overwrite", confirmed=True)
        self.assertEqual((status, got["ok"], got["replaced"]), (200, True, True), got)
        self.assertEqual(self.taken.read_bytes(), (self.rig.local / "second.html").read_bytes())
        self.assertEqual(self.rig.listing(self.rig.client), [WANTED], "no backup beside the client's file")

    def test_cancel_writes_nothing(self):
        before = self.rig.everything_written()
        status, got = self.rig.publish(to_client=True, on_clash="cancel")
        self.assertEqual((status, got["ok"], got["code"]), (200, False, "cancel"))
        self.assertEqual((self.rig.everything_written(), self.rig.saves), (before, []))

    def test_the_same_file_already_there_copies_nothing_and_is_logged_with_its_path(self):
        self.taken.write_bytes((self.rig.local / "chosen.html").read_bytes())
        status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["ok"], got["action"]), (200, True, "nothing_to_do"))
        self.assertEqual(self.rig.rows()[-1]["client_path"], str(self.taken))
        self.assertEqual(self.rig.listing(self.rig.client), [WANTED])


class TheRequest(Base):
    def test_only_true_means_to_client(self):
        for value in ("true", 1, None, "yes", [True]):
            with self.subTest(value=value):
                status, got = self.rig.publish(to_client=value)
                self.assertEqual((status, got["ok"], got["code"]), (400, False, "to_client_flag"))
        self.assertEqual((self.rig.everything_written(), self.rig.rows(), self.rig.saves), ([], [], []))

    def test_a_request_never_names_a_folder_or_a_file(self):
        for extra in ({"client_folder": "/tmp/elsewhere"}, {"path": "/tmp/x.html"}, {"folder": "/tmp"}, {"file_name": "x.html"},
                      {"client_path": "/tmp/x.html"}, {"local_path": "/tmp/x"}):
            with self.subTest(extra=extra):
                status, got = self.rig.publish(to_client=True, **extra)
                self.assertEqual((status, got["code"]), (400, "names_a_folder"))
        self.assertEqual((self.rig.everything_written(), self.rig.rows()), ([], []))

    def test_a_bad_or_unknown_project(self):
        self.assertEqual(self.rig.publish(project="x")[0:2], (400, mock.ANY))
        status, got = self.rig.publish(project="NOPE")
        self.assertEqual((status, got["code"]), (404, "project_not_found"))
        status, got = self.rig.call("POST", "/api/publish", {"to_client": True})
        self.assertEqual((status, got["code"]), (400, "bad_project_code"))

    def test_every_reply_has_a_plain_message_and_a_stable_code(self):
        replies = [self.rig.publish(to_client="true"), self.rig.publish(project="NOPE"), self.rig.publish(to_client=True, client_folder="/x"),
                   self.rig.publish(to_client=True, on_clash="maybe")]
        for status, got in replies:
            self.assertFalse(got["ok"])
            self.assertRegex(got["code"], r"^[a-z_]+$")
            self.assertTrue(got["message"].endswith((".", "!", "?")), got["message"])
            self.assertNotRegex(got["message"], r"(?i)\b(sha|route|errno|traceback|api|json|http|token)\b|report editor")
            self.assertNotIn("Clark", got["message"])

    def test_the_token_comes_first(self):
        for token in (False, "wrong"):
            for method, path, body in (("POST", "/api/publish", {"project": "PUB"}), ("POST", "/api/client-folder", {"project": "PUB", "action": "clear"}),
                                       ("GET", "/api/publication?project=PUB", None)):
                status, _ = self.rig.call(method, path, body, token=token)
                self.assertEqual(status, 403, (method, path))
        self.assertEqual((self.rig.everything_written(), self.rig.rows()), ([], []))

    def test_another_host_is_refused(self):
        status, _ = self.rig.call("POST", "/api/publish", {"project": "PUB", "to_client": True}, host="evil.example")
        self.assertEqual(status, 403)
        self.assertEqual(self.rig.everything_written(), [])

    def test_a_second_publish_at_once_is_told_to_wait(self):
        gate, inside = threading.Event(), threading.Event()
        save = self.rig.publisher.choose_save_file

        def slow(prompt, name, start=None):
            inside.set()
            gate.wait(10)
            return save(prompt, name, start)
        self.rig.publisher.choose_save_file = slow
        first = []
        t = threading.Thread(target=lambda: first.append(self.rig.publish()))
        t.start()
        self.assertTrue(inside.wait(10))
        status, got = self.rig.publish()
        gate.set()
        t.join(10)
        self.assertEqual((status, got["code"]), (409, "busy"))
        self.assertEqual(first[0][0], 200)
        self.assertEqual(len(self.rig.rows()), 1)


class TheClientFolderSetting(Base):
    def setUp(self):
        self.rig = Rig(self, saved=False)

    def folder(self):
        return self.rig.store.read("projects", ref="PUB")["publish_client"]

    def post(self, **body):
        return self.rig.call("POST", "/api/client-folder", {"project": "PUB", **body})

    def test_choose_saves_clear_and_undo(self):
        self.rig.pick = self.rig.client
        status, got = self.post(action="choose")
        self.assertEqual((status, got["ok"], got["changed"], got["folder_name"]), (200, True, True, "Harbour Bridge"))
        self.assertEqual(self.folder(), str(self.rig.client))
        self.assertEqual(self.rig.picks, [("Choose the folder OneDrive syncs for the client", str(self.rig.onedrive))])
        step = self.rig.store.con.execute("SELECT max(apply_id) FROM applies").fetchone()[0]
        status, got = self.post(action="clear")
        self.assertEqual((status, got["changed"], self.folder()), (200, True, None))
        done = self.rig.store.undo(step + 1, USER)           # undoing the clear puts the folder back
        self.assertEqual((done["skipped"], self.folder()), ([], str(self.rig.client)))
        self.rig.store.undo(step, USER)
        self.assertIsNone(self.folder(), "undo of the choice")

    def test_cancelling_the_dialog_changes_nothing_and_says_nothing(self):
        self.rig.pick = None
        status, got = self.post(action="choose")
        self.assertEqual((status, got["ok"], got["changed"], self.folder()), (200, True, False, None))
        self.assertNotIn("message", got)

    def test_a_refused_folder_leaves_the_setting_alone_and_says_why(self):
        for place, words in ((self.rig.data_dir, "inside clark's own data folder"), (self.rig.root, "contains clark's own data folder"),
                             (self.rig.root / "missing", "isn't there")):
            with self.subTest(place=place.name):
                self.rig.pick = place
                status, got = self.post(action="choose")
                self.assertEqual((status, got["ok"], got["code"]), (409, False, "client_folder_refused"))
                self.assertIn(words, got["message"])
                self.assertIsNone(self.folder())

    def test_a_folder_outside_onedrive_is_saved_with_a_warning(self):
        outside = self.rig.root / "Elsewhere"
        outside.mkdir()
        self.rig.pick = outside
        status, got = self.post(action="choose")
        self.assertEqual((status, got["changed"]), (200, True))
        self.assertIn("isn't one OneDrive syncs", got["warning"])

    def test_it_never_writes_into_the_folder(self):
        self.rig.pick = self.rig.client
        before = self.rig.client.stat().st_mtime_ns
        self.post(action="choose")
        self.post(action="clear")
        self.assertEqual((list(self.rig.client.iterdir()), self.rig.client.stat().st_mtime_ns), ([], before))

    def test_only_choose_and_clear_and_nothing_else(self):
        for body in ({"action": "open"}, {"action": "choose", "folder": "/tmp"}, {}):
            status, got = self.post(**body) if body else self.rig.call("POST", "/api/client-folder", {"project": "PUB"})
            self.assertEqual((status, got["code"]), (400, "bad_action"))
        self.assertEqual(self.rig.picks, [])


class TheReportBar(Base):
    def test_the_latest_publication_says_when_and_whether_to_the_client(self):
        self.assertEqual(self.rig.call("GET", "/api/publication?project=PUB"), (200, {"ok": True, "latest": None}))
        self.rig.publish()
        status, got = self.rig.call("GET", "/api/publication?project=PUB")
        self.assertEqual((status, sorted(got["latest"]), got["latest"]["to_client"]), (200, ["at", "to_client"], False))
        self.rig.save_to = self.rig.local / "again.html"
        self.rig.publish(to_client=True)
        status, got = self.rig.call("GET", "/api/publication?project=PUB")
        self.assertTrue(got["latest"]["to_client"])
        self.assertRegex(got["latest"]["at"], r"^\d{4}-\d\d-\d\d$")
        self.assertNotIn(str(self.rig.local), json.dumps(got))

    def test_a_bad_or_unknown_project(self):
        self.assertEqual(self.rig.call("GET", "/api/publication?project=x")[0], 400)
        self.assertEqual(self.rig.call("GET", "/api/publication?project=NOPE")[0], 404)


class OnlyOneRouteWritesIntoTheClientFolder(Base):
    """Every route of the server is called, with a valid body and then with a folder and a path added. The client folder must
    stay empty after every call except POST /api/publish with to_client: true, which writes exactly one file."""

    def test_only_publish_with_to_client_true_writes_into_it(self):
        self.rig.pick = self.rig.client
        routes = [("GET", p) for p in sv.GET_ROUTES] + [("POST", p) for p in sv.POST_ROUTES]
        self.assertIn(("POST", "/api/publish"), routes)
        writers = []
        for method, path in routes:
            for extra in ({}, {"to_client": True, "client_folder": str(self.rig.client), "path": str(self.rig.client / "x.html"),
                               "folder": str(self.rig.client)}, {"to_client": "true"}):
                body = {"project": "PUB", "action": "clear", **extra} if method == "POST" else None
                where = path + ("?project=PUB" if method == "GET" else "")
                if method == "POST" and path == "/api/publish":
                    body.pop("action")
                self.rig.call(method, where, body)
                self.rig.call(method, where, body, token="wrong")
                if list(self.rig.client.iterdir()):
                    writers.append((method, path, extra))
                    for p in self.rig.client.iterdir():
                        p.unlink()
            self.rig.set_folder(str(self.rig.client))          # the "clear" above emptied the setting
        self.assertEqual([w[:2] for w in writers], [], "only the real to_client: true request may write; none did here")
        status, got = self.rig.publish(to_client=True)
        self.assertEqual((status, got["ok"]), (200, True))
        self.assertEqual(self.rig.listing(self.rig.client), [WANTED], "exactly one file")

    def test_a_valid_change_and_undo_write_nothing_into_the_client_folder(self):
        status, got = self.rig.call("POST", "/api/change", {"project": "PUB", "kind": "report_sections", "op": "new",
                                                             "values": {"title": "Fictional section"}})
        self.assertEqual((status, got.get("ok")), (200, True), got)
        self.assertEqual(self.rig.listing(self.rig.client), [])
        status, got = self.rig.call("POST", "/api/undo", {"project": "PUB", "apply_id": got["apply_id"]})
        self.assertEqual(status, 200, got)
        self.assertEqual(self.rig.listing(self.rig.client), [])

    def test_every_route_is_listed_and_the_set_is_what_the_issue_expects(self):
        self.assertEqual(sorted(sv.POST_ROUTES), ["/api/backups/preview", "/api/backups/restore", "/api/change", "/api/client-folder",
                                                  "/api/preview", "/api/publish", "/api/sneak/read", "/api/undo"])     # #111: the two backup routes; #147: preview; #42: the sneak read
        self.assertEqual(sorted(sv.GET_ROUTES), ["/api/activity", "/api/backups", "/api/data", "/api/export", "/api/movement", "/api/projects",
                                                 "/api/publication", "/api/use-cases"])     # #147: export; #136: movement; #42: activity

    def test_no_route_takes_the_client_folder_from_the_request(self):
        status, got = self.rig.publish(to_client=True, client_folder=str(self.rig.root / "Elsewhere"))
        self.assertEqual(status, 400)
        self.assertFalse((self.rig.root / "Elsewhere").exists())


class WithoutAPublisher(unittest.TestCase):
    def test_a_server_with_no_publisher_cannot_publish_anything(self):
        httpd = sv.LocalServer((sv.HOST, 0))
        self.addCleanup(httpd.server_close)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        for method, path in (("POST", "/api/publish"), ("POST", "/api/client-folder"), ("GET", "/api/publication?project=PUB")):
            conn = http.client.HTTPConnection(sv.HOST, httpd.server_port, timeout=10)
            body = b'{"project": "PUB", "to_client": true}'
            conn.request(method, path, body if method == "POST" else None,
                         {"Host": f"127.0.0.1:{httpd.server_port}", sv.TOKEN_HEADER: sv.TOKEN, "Content-Type": "application/json",
                          "Content-Length": str(len(body) if method == "POST" else 0)})
            self.assertEqual(conn.getresponse().status, 404, path)
            conn.close()


class TheModuleIsTheOnlyCaller(unittest.TestCase):
    def test_publish_flow_reaches_the_writer_in_one_place_and_is_stdlib_only(self):
        import ast
        source = (SRC / "clark" / "publish_flow.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in ("copy_to_client", "send_to_client", "RealFs")]
        self.assertEqual(sorted(c.attr for c in calls), ["RealFs", "copy_to_client"])
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse(imported & {"socket", "urllib", "http", "ssl", "smtplib", "subprocess", "ctypes", "sqlite3", "requests"})
        self.assertNotRegex(source, r"(?i)microsoft|graph\.|oauth|sharepoint\.com")


RAW = r"(?i)permission denied|errno|oserror|database is locked|no such file|no space|read-only|held by|\(\w[^)]*\)\.|/tmp|/Users|\.db\b"


class PlainWords(Base):
    """Every message a person can see from the publish routes is a fixed plain sentence: the system's own text (an OS error,
    the database's complaint) is never shown, and no location of an internal place appears (#43, plain-words review)."""

    def seen(self, got):
        text = got.get("message", "") + " " + got.get("warning", "")
        self.assertNotRegex(text, RAW, text)
        return text

    def test_a_refused_local_save_shows_a_plain_sentence_not_the_system_text(self):
        for error in (OSError(13, "Permission denied"), OSError(2, "No such file or directory"), OSError(28, "No space left on device")):
            with self.subTest(str(error)), mock.patch.object(platform, "write_file", side_effect=error):
                status, got = self.rig.publish()
                self.assertEqual((status, got["code"]), (409, "local_failed"), got)
                self.assertEqual(self.seen(got), "chosen.html could not be saved. Check you can edit that folder and that the disk has "
                                                 "room, then try again. Nothing was published. ")

    def test_a_failed_record_shows_no_database_text(self):
        with mock.patch.object(Store, "log_publication", side_effect=Invalid("database is locked")):
            status, got = self.rig.publish()
        self.assertEqual((status, got["code"]), (409, "not_recorded"), got)
        self.assertEqual(self.seen(got), "Published, but clark could not record it. The files are fine; publish again to record it. ")

    def test_a_database_that_cannot_be_read_shows_no_database_text(self):
        with mock.patch.object(Store, "publish_inputs", side_effect=OSError(5, "disk I/O error")):
            status, got = self.rig.publish()
        self.assertEqual((status, got["code"]), (409, "not_made"), got)
        self.assertEqual(self.seen(got), "The records could not be read. Restart clark and try again. Nothing was published. ")

    def test_a_refused_client_folder_save_shows_no_database_text(self):
        rig = Rig(self, saved=False)
        rig.pick = rig.client
        with mock.patch.object(Store, "step", side_effect=Invalid("database is locked")):
            status, got = rig.call("POST", "/api/client-folder", {"project": "PUB", "action": "choose"})
        self.assertEqual((status, got["code"]), (409, "settings_failed"), got)
        self.assertEqual(self.seen(got), "The client folder could not be saved. Nothing was changed. Try again. ")

    def test_a_system_dialog_that_fails_shows_a_plain_sentence_for_the_save_and_the_folder_windows(self):
        import subprocess
        raw = "execution error: Permission denied (-1743)"
        run = lambda args, **kw: subprocess.CompletedProcess(args, 1, "", raw)          # noqa: E731
        self.rig.publisher.choose_save_file = lambda prompt, name, start=None: platform.choose_save_file(
            prompt, name, start, run=run, on=platform.MAC)
        status, got = self.rig.publish()
        self.assertEqual((status, got["code"]), (409, "dialog_failed"), got)
        self.assertEqual(self.seen(got), "The Save window could not be opened. Try again; if it keeps happening, restart clark. "
                                         "Nothing was published. ")
        rig = Rig(self, saved=False)
        rig.publisher.choose_folder = lambda prompt, start=None: platform.choose_folder(prompt, start, run=run, on=platform.MAC)
        status, got = rig.call("POST", "/api/client-folder", {"project": "PUB", "action": "choose"})
        self.assertEqual((status, got["code"]), (409, "dialog_failed"), got)
        self.assertEqual(self.seen(got), "The folder window could not be opened. Try again; if it keeps happening, restart clark. ")


if __name__ == "__main__":
    unittest.main()
