"""python3 -m clark: the plain launcher that starts the page (#90).

    python3 -m clark [--data FOLDER] [--port N] [--open] [--demo]
    python3 -m clark restore [NAME] [--data FOLDER]       (#86: list the backups, or put one back; clark closed)

Plain wording: the server (server.py) and the store (store.py) are guarded and keep their own error text. The launcher says the
plain thing itself instead: it checks the port before starting, replaces the server's start line as it is printed (see
ServerOutput), and turns the store's "not a database" refusal into one line without the raw error.

Opens the store in the data folder (platform.data_dir() unless --data), makes it on first run, and starts the server (#33)
with the store's data and the built page (#35). The address is 127.0.0.1 only. Ctrl+C stops it. The `change` and `undo`
handlers (#65, clark.changes) are built for this data's file, each call on a store of its own; a test may pass its own through
main(change=..., undo=...).

The logic is in main() so a test can run it with fakes; everything that touches the system goes through platform.py.
"""
import argparse
import errno
import os
import re
import shutil
import socket
import signal
import sys
import tempfile
from pathlib import Path

from clark import ai_service, app_settings, appfiles, ask_claude, ask_folders, ask_service, backup, changes, idle, movement_read, page, platform, providers, publish, publish_flow, safety, server, store as clark_store, use_cases_read

DB_NAME = "clark.db"
HERE = Path(__file__).resolve().parent
DEV = HERE.parents[1] / "dev"            # dev/demo_data.py builds the demo database; it is not part of the package
ADDRESS_LINE = "Open http://"           # the start of the line server.serve prints once it is listening
LISTENING = re.compile(r"^Open http://127\.0\.0\.1:(\d+)/")


DEMO_CODE = "TUL"                       # the first project dev/demo_data.py makes (its CODES[0]); a test keeps the two together


class Quiet(Exception):
    """Something to say in one plain line, then exit with code 1."""


class Usage(Quiet):
    """A mistake in the options: one plain line, the hint to --help, and exit code 2 (as the parser's own errors)."""


HINT = "Run python3 -m clark --help to see the options."


def stop_with_usage(text):
    """A mistake in the options: one plain line, the hint to --help, and exit code 2 (as argparse's own errors)."""
    print(f"{text}\n{HINT}", file=sys.stderr)
    sys.exit(2)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        unknown = re.match(r"unrecognized arguments: (.*)", message)
        missing = re.match(r"argument (\S+): expected one argument", message)
        if unknown:
            names = unknown.group(1).split()
            text = (f"The option {names[0]} isn't recognised." if len(names) == 1
                    else f"These options aren't recognised: {', '.join(names)}.")
        elif missing:
            text = f"{missing.group(1)} needs a value after it."
        else:
            text = "These options can't be read. Run python3 -m clark --help to see the options."
        stop_with_usage(text)


class RestoreParser(Parser):
    def error(self, message):
        unknown = re.match(r"unrecognized arguments: (.*)", message)
        missing = re.match(r"argument (\S+): expected one argument", message)
        if unknown:
            names = unknown.group(1).split()
            text = (f"Restore has no option {names[0]}." if names[0].startswith("-")
                    else f"Restore takes one backup name at most. You gave: {unknown.group(1)}.")
        elif missing:
            text = f"{missing.group(1)} needs a value after it."
        else:
            text = "These options aren't recognised."           # argparse's own words are technical; the next line points to --help
        print(f"{text}\nRun python3 -m clark restore --help to see the options.", file=sys.stderr)
        sys.exit(2)


def restore_parser():
    p = RestoreParser(prog="python3 -m clark restore",
                      description="List clark's backups, or put one back. Close clark first: stop every running copy. With no NAME it only lists the copies.")
    p.add_argument("name", nargs="?", metavar="NAME", help="the backup to put back (as listed, for example clark-20261028T143005Z-undo.db)")
    p.add_argument("--data", metavar="FOLDER", help="the folder for clark's data (default: clark's own folder for your system)")
    return p


def parser():
    p = Parser(prog="python3 -m clark", description="Start clark on this computer. Only this computer can reach it.",
               epilog="To list the backups or put one back: python3 -m clark restore --help")
    p.add_argument("--data", metavar="FOLDER", help="the folder for clark's data (default: clark's own folder for your system)")
    p.add_argument("--port", metavar="N", help=f"the port clark listens on (default: the CLARK_PORT setting, or {server.DEFAULT_PORT})")
    p.add_argument("--open", action="store_true", help="also open the page in your browser")
    p.add_argument("--demo", action="store_true", help="use fictional demo data, in a temporary folder removed when you stop")
    return p


def port_number(text, where):
    """`text` as a port from 1 to 65535, or a plain error naming where it came from."""
    try:
        port = int(text)
    except (TypeError, ValueError):
        port = 0
    if not 1 <= port <= 65535:
        raise Usage(f"The port setting ({where}) must be a whole number from 1 to 65535.")
    return port


def port_free(port):
    """True when nothing is listening on `port` of 127.0.0.1 (the address the server uses)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if os.name == "posix":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)       # as the server binds: a recent stop is not "in use"
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as e:
            if e.errno == errno.EADDRINUSE:
                return False
            raise
    return True


def free_port_near(port, free=port_free):
    """A port that is free now, close above `port` if there is one (None if none is found). launch.py offers it as a second line."""
    for other in range(port + 1, min(port + 50, 65535) + 1):
        if free(other):
            return other
    return None


def address_for(port, code):
    """The address to open: with `#dashboard&p=CODE` when there is one project to open, so the page is not empty (#36 will
    list the projects; until then the address names one)."""
    return f"http://127.0.0.1:{port}/" + (f"#dashboard&p={code}" if code else "")


def start_line(address):
    return f"Open {address} to use clark. Leave this window open. Press Ctrl+C to stop."


class ServerOutput:
    """Wraps the output stream. The server (guarded, so not edited here) prints its own start line when it is listening, in
    its old words (not the product's name). This writes the launcher's line in its place (the same address, plus the
    project to open), and opens the browser then if asked."""

    def __init__(self, out, code, opener, err):
        self.out, self.code, self.opener, self.err, self.done = out, code, opener, err, False

    def write(self, text):
        found = None if self.done else LISTENING.match(text)
        if not found:
            return self.out.write(text)
        self.done = True
        address = address_for(int(found.group(1)), self.code)
        self.out.write(start_line(address))
        if self.opener:
            try:
                self.opener(address)
            except platform.PlatformError as e:
                why = str(e).replace(" " + platform.TRY_AGAIN, "")        # one next step only: the address, not "try again" as well
                print(f"{why} Open {address} yourself.", file=self.err, flush=True)
        return len(text)

    def flush(self):
        self.out.flush()


def demo_database(folder):
    """Build the fictional demo database (dev/demo_data.py, #30) in `folder`; its path."""
    if str(DEV) not in sys.path:
        sys.path.insert(0, str(DEV))
    try:
        import demo_data
    except ImportError as e:
        raise Quiet("--demo needs a file that is missing (dev/demo_data.py). Use a full copy of the clark folder.") from e
    try:
        demo_data.build(Path(folder) / DB_NAME, demo_data.parse_now(os.environ.get("CLARK_NOW")))
    except demo_data.DemoError as e:
        raise Quiet(str(e)) from e
    return Path(folder) / DB_NAME


def open_data(folder, onedrive_roots):
    """The store in `folder`, made on first run. OneDrive is refused before anything is created there."""
    folder = platform.check_data_dir(folder, onedrive_roots)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise Quiet(f"The data folder {folder} can't be made ({backup.plain_reason(e)}). Check you may write there, or choose "
                    f"another folder with --data.") from e
    try:
        return clark_store.open_store(folder / DB_NAME, onedrive_roots=onedrive_roots)
    except clark_store.Unfinished as e:                   # its own words say where the database you had is (F1)
        raise Quiet(str(e)) from e
    except clark_store.Invalid as e:
        if not str(e).startswith(f"{DB_NAME} is "):       # the store's own wording for a file it can't use; never shown raw
            raise
        raise Quiet(f"The data in {DB_NAME} can't be read. Start clark with --data to use another folder, or restore a "
                    f"backup.") from e


def only_project(store):
    """The code of the one project in the store, or None when there are none or several."""
    codes = [r["code"] for r in store.read("projects", archived=False)]
    return codes[0] if len(codes) == 1 else None


def projects_of(path, onedrive_roots=None):
    """The `projects` function the server calls for GET /api/projects: [{"code", "name"}] for every project that isn't archived,
    by code (`projects(archived=True)` gives the archived ones instead, for Show archived, #126). Each call opens its own short-lived store, because the server answers from several threads and a SQLite
    connection belongs to the thread that made it: it must not use the launcher's own store (#90)."""
    def projects(archived=False):
        try:
            found = clark_store.open_store(path, onedrive_roots=onedrive_roots)
        except clark_store.Invalid as e:
            if str(e) == backup.RESTORE_BUSY:
                raise server.Busy(str(e)) from None             # a reload during a restore: its own sentence, 503
            raise
        try:
            rows = found.read("projects", archived=bool(archived))
        finally:
            found.close()
        return [{"code": r["code"], "name": r["name"]} for r in sorted(rows, key=lambda r: r["code"])]
    return projects


def restore_main(argv, out, err, home=None, onedrive_roots=None):
    """`python3 -m clark restore [NAME] [--data FOLDER]` (#86): the exit code. With no NAME, the copies in local time and nothing
    else happens. With one, it is put back over clark.db, which must not be open anywhere (backup.restore_path)."""
    args = restore_parser().parse_args(argv)
    shown_data = "the data folder"
    try:
        folder = platform.check_data_dir(Path(args.data).expanduser() if args.data else platform.data_dir(home), onedrive_roots)
        shown_data = backup.shown(folder)
        folder_shown = backup.shown(folder / "backups")
        if args.name is None:
            found = backup.listing(folder / "backups")
            if not found:
                print(f"There are no backups in {folder_shown} yet. clark makes one before every undo and every import, and on "
                      "the first change you save each day.", file=out, flush=True)
                return 0
            print(f"Backups in {folder_shown}, newest first (times are your local time):", file=out)
            for row in found:
                print(f"  {row['when']}  {row['kind']:<17} {row['name']}", file=out)
            print(backup.RESTORE_HELP, file=out, flush=True)
            return 0
        database = folder / DB_NAME
        held = None
        if database.exists() and database.stat().st_size > 0:        # never open an empty file: that would build a new database in it
            try:
                held = clark_store.open_store(database, onedrive_roots=onedrive_roots)
            except clark_store.Invalid:
                held = None                   # too damaged to open: that is when a restore is needed, and it is moved aside whole
        try:
            done = backup.restore_path(database, args.name, folder / "backups", onedrive_roots, held)
        finally:
            if held is not None:
                held.close()
        if not done["replaced"]:
            where = ""
        elif done["backed_up"]:
            where = f" The database you had before is kept in {backup.shown(done['replaced'])}, and clark made a backup of it first."
        else:
            where = (f" The database you had before is kept in {backup.shown(done['replaced'])}. clark could not make a backup of it "
                     "first, because it was empty or damaged, so that folder holds the only copy.")
        print(f"Put {args.name} back as your clark data.{where} Start clark again to use it.", file=out, flush=True)
        return 0
    except (Quiet, platform.PlatformError, clark_store.Invalid) as e:
        print(e, file=err, flush=True)
        return 1
    except KeyboardInterrupt:             # Ctrl+C in the move window: what was done is kept, and starting clark finishes the rest
        print("Stopped. Nothing has been lost. Start clark again to finish the restore, or to carry on as before if it had not begun.",
              file=err, flush=True)
        return 130
    except OSError as e:                  # a folder that is a file or can't be read: words, never a traceback or the user's name
        print(f"A file clark needs couldn't be read or written ({backup.plain_reason(e)}). Check {shown_data} "
              f"and the backups folder in it, then try again.", file=err, flush=True)
        return 1


def use_case_ids_on_file(store):
    """The rule for Use Cases' on_dashboard, as a function of the project code: today publish.select's own choice. When
    publish.client_use_cases exists (#168) this is the one place to point at it."""
    def ids(code):
        chosen = publish.select(publish.read_inputs(store, code))
        return {u["id"] for u in chosen["data"]["use_cases"]}
    return ids


def main(argv=None, out=None, err=None, serve=server.serve, open_url=platform.open_url, home=None, onedrive_roots=None,
         change=None, undo=None, environ=None, is_free=port_free):
    """Run the launcher; the exit code. `serve`, `open_url`, `home` (for the default data folder) and `onedrive_roots` are
    `is_free` (the check that the port is taken or not) are seams for tests. `change` and `undo` are the handlers for POST
    /api/change and /api/undo (#65): built from clark.changes for this data's file unless a test gives its own."""
    out, err = out or sys.stdout, err or sys.stderr
    environ = os.environ if environ is None else environ
    given = sys.argv[1:] if argv is None else list(argv)
    if given[:1] == ["restore"]:
        return restore_main(given[1:], out, err, home, onedrive_roots)
    p = parser()
    args = p.parse_args(argv)
    store, scratch, code = None, None, None
    try:
        try:
            if args.demo and args.data:
                raise Usage("--demo makes its own temporary folder. Use --data or --demo, not both.")
            if args.port is not None:
                port = port_number(args.port, "--port")
            else:
                port = port_number(environ.get("CLARK_PORT") or server.DEFAULT_PORT, "CLARK_PORT")
            if not is_free(port):                    # before anything is made or started, and the server's own line is not used
                print(server.PORT_TAKEN, file=err, flush=True)
                return 1
            if args.demo:
                scratch = tempfile.mkdtemp(prefix="clark-demo-")
                store = clark_store.open_store(demo_database(scratch), onedrive_roots=[])
                code = DEMO_CODE
                print("Using fictional demo data in a temporary folder; it is removed when you stop.", file=out, flush=True)
            else:
                folder = Path(args.data).expanduser() if args.data else platform.data_dir(home)
                store = open_data(folder, onedrive_roots)
                code = only_project(store)
                print(f"Using the data in {store.path.parent}", file=out, flush=True)
        except Usage as e:
            stop_with_usage(str(e))
        except (Quiet, platform.PlatformError, clark_store.Invalid) as e:
            print(e, file=err, flush=True)
            return 1
        roots = [] if args.demo else onedrive_roots
        store.close()           # #111: nothing keeps the database open while clark runs (each request opens its own), so Restore can swap the file
        handlers = {"change": change or changes.make_change(store.path, roots),
                    "undo": undo or changes.make_undo(store.path, roots)}
        server.set_open_files(appfiles.open_files())
        server.set_idle(idle.Idle.from_environ(environ) if idle.launched(environ) else None)
        server.set_data_mark(appfiles.data_mark(store.path.parent))
        shown = ServerOutput(out, code, open_url if args.open else None, err)
        ai = providers.build(store.path.parent, ask_claude.ClaudeCommand())       # #54: the routes to a model (Settings › AI)
        asking = ask_service.AskService(store.path, providers.RoutedProvider(ai), roots)
        done = serve(port=port, data_for=store.data_for, page_html=page.page_html,
                     projects=projects_of(store.path, roots), out=shown,
                     err=err,
                     publisher=publish_flow.Publisher(store.path, roots, data_dir=store.path.parent),
                     movement=movement_read.make_read(store.milestone_moves, store.data_for),
                     use_cases=use_cases_read.make_read(store.data_for, use_case_ids_on_file(store)),
                     safety=safety.Safety(store.path, roots),
                     ask_folders=ask_folders.AskFolders(store.path, roots, data_dir=store.path.parent),
                     app_settings=app_settings.AppSettings(store.path, roots),
                     ask=asking, ai=ai_service.AiService(ai, asking.enabled),
                     **handlers)
        if done == 0:
            print("Stopped.", file=out, flush=True)
        return done
    except KeyboardInterrupt:
        print("Stopped.", file=out, flush=True)
        return 0
    finally:
        if store is not None:
            store.close()
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)


def stop(signum, frame):
    raise KeyboardInterrupt


def run():
    """The command: Ctrl+C and a plain kill both stop it cleanly, even if the shell started it with Ctrl+C ignored."""
    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.signal(signal.SIGTERM, stop)
    return main()


if __name__ == "__main__":
    sys.exit(run())
