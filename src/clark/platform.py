"""Everything that differs between Mac and Windows, in one place (#56).

clark runs on macOS first, built ready for Windows ("start with mac we can follow with windows but
ensure when we build for mac we make allowances for the future"). Only the Mac branch is written; each Windows branch
raises NotBuiltYet. No other module may start a program, call osascript or ctypes, or name a system folder: a source test
(tests/test_platform_source.py) fails if one does. See docs/handoff/portability-and-sharing.md.

Standard library only, Python 3.9.
"""
import errno
import getpass
import os
import re
import secrets
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

MAC = "darwin"
WINDOWS = "win32"
MAX_PATH = 260                  # Windows' default limit on a whole path, counted with its ending NUL
MAX_NAME = 120                  # clark keeps every file name it makes this short or shorter
RESERVED_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
                  *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10)),
                  *(f"{d}{n}" for d in ("COM", "LPT") for n in "\u00b9\u00b2\u00b3")}     # COM¹ COM² COM³ LPT¹ LPT² LPT³
REPLACE_ATTEMPTS = 5            # tries of os.replace before a locked file is reported
REPLACE_FIRST_WAIT = 0.05       # seconds; doubled after each failed try (0.05 + 0.1 + 0.2 + 0.4 = 0.75 s at most)
LOCKED = {errno.EACCES, errno.EPERM, errno.EBUSY}
NO_HARD_LINKS = {errno.EPERM, errno.EXDEV, errno.ENOTSUP, errno.ENOSYS}     # a disk (or network share) that can't link a file to a second name
CANCELLED = "-128"              # osascript's "User canceled." error number


class PlatformError(RuntimeError):
    """Something the system refused, in words a person can act on."""


class NotBuiltYet(PlatformError, NotImplementedError):
    """This system's branch isn't written yet (Windows follows the Mac)."""


def system():
    """The system clark is running on: MAC, WINDOWS or another sys.platform value."""
    return sys.platform


def _only_mac(what, on=None):
    """Raise NotBuiltYet unless `on` (default: this system) is the Mac."""
    on = on or system()
    if on != MAC:
        raise NotBuiltYet(f"{what} on {'Windows' if on == WINDOWS else on} is not built yet: clark runs on macOS for now")


# Who

def login_name():
    """The login name of the person at this machine: `by_user` for what they change in the report, until Settings has a
    profile that overrides it (#65). Never an email address. A system that can't say gives "This computer"."""
    try:
        name = getpass.getuser()
    except (KeyError, OSError, ImportError):
        name = ""
    return str(name).strip() or "This computer"


# Folders

def data_dir(home=None, on=None):
    """Where clark keeps its database and settings: ~/Library/Application Support/clark/ on the Mac. Not created here."""
    _only_mac("The data folder", on)
    return Path(home or Path.home()) / "Library" / "Application Support" / "clark"


def log_dir(home=None, on=None):
    """Where clark writes its daily log: ~/Library/Logs/clark/ on the Mac (#110). Not created here."""
    _only_mac("The log folder", on)
    return Path(home or Path.home()) / "Library" / "Logs" / "clark"


def onedrive_roots(home=None, on=None):
    """The OneDrive folders on this machine, as suggestions only (the user still picks a folder): the OneDrive app's
    ~/Library/CloudStorage/OneDrive-<name>/ folders, and the older app's ~/OneDrive*/ folders. Sorted; may be empty."""
    _only_mac("Finding OneDrive", on)
    home = Path(home or Path.home())
    found = list((home / "Library" / "CloudStorage").glob("OneDrive*")) + list(home.glob("OneDrive*"))
    return sorted(p for p in found if p.is_dir())


# The places clark never reads, whatever the person saved (#47b). creaite's reach.py names them as rows of (base, pattern,
# kind): "home" rows are below the home folder, "abs" rows are absolute paths; the pattern is matched one part at a time with
# shell wildcards and covers everything below it. They live here because seven name a folder under "Library/Application
# Support", and only this file may (tests/test_platform_source.py). creaite v2.6.9 reach.NEVER, the 39 rows that bar reading.
NEVER_READ = (
    ("home", ".ssh", "secret"), ("home", ".aws", "secret"), ("home", ".gnupg", "secret"),
    ("home", ".config/gcloud", "secret"), ("home", ".config/gh", "secret"), ("home", ".config/op", "secret"),
    ("home", ".kube", "secret"), ("home", ".docker", "secret"), ("home", ".netrc", "secret"),
    ("home", ".git-credentials", "secret"), ("home", ".npmrc", "secret"), ("home", ".pypirc", "secret"),
    ("home", ".password-store", "secret"), ("home", "Library/Keychains", "secret"),
    ("home", "Library/Group Containers/*1password*", "secret"), ("home", "Library/Application Support/1Password", "secret"),
    ("home", "Library/Application Support/Bitwarden", "secret"),
    ("home", "Library/Application Support/Google/Chrome", "secret"), ("home", "Library/Application Support/Firefox", "secret"),
    ("home", "Library/Application Support/Microsoft Edge", "secret"),
    ("home", "Library/Application Support/BraveSoftware", "secret"), ("home", "Library/Application Support/Arc", "secret"),
    ("home", "Library/Safari", "secret"), ("home", "Library/Containers/com.apple.Safari", "secret"),
    ("home", "Library/Cookies", "secret"), ("home", ".mozilla", "secret"), ("home", ".config/google-chrome", "secret"),
    ("home", ".claude.json", "secret"), ("home", ".claude/.credentials.json", "secret"),
    ("abs", "/System", "system"), ("abs", "/Library", "system"), ("abs", "/usr", "system"), ("abs", "/bin", "system"),
    ("abs", "/sbin", "system"), ("abs", "/etc", "system"), ("abs", "/private/etc", "system"), ("abs", "/opt", "system"),
    ("abs", "/Applications", "system"), ("abs", "/dev", "system"),
)


def never_read_places(on=None):
    """The places ask clark never reads, as (base, pattern, kind) rows: base "home" or "abs", kind "secret" or "system"
    (reach.py turns the kind into its plain-words reason). Windows' places are not written yet."""
    _only_mac("The list of places clark never reads", on)
    return NEVER_READ


def inside_onedrive(path, roots=None):
    """The OneDrive root that `path` is inside (after following links), or None."""
    path = Path(path).expanduser().resolve()
    for root in onedrive_roots() if roots is None else roots:
        root = Path(root).resolve()
        if path == root or root in path.parents:
            return root
    return None


def shown(path):
    """A folder or file as a person reads it in a message: under the home folder it is written from "~", so the user's name is
    never in a message that might be copied into a report or an email."""
    path = Path(path)
    try:
        return "~/" + path.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(path)


def check_data_dir(path, roots=None, what="data"):
    """`path`, resolved, if clark may keep its database there. A folder inside OneDrive is refused with the reason:
    OneDrive syncs a database part-way through a write and can't lock it, so the data would be damaged. `what="backups"`
    words the refusal for the backups folder (#86), where "backups can still go to OneDrive" would read wrongly."""
    root = inside_onedrive(path, roots)
    if root is not None:
        if what == "backups":
            raise PlatformError(f"Backups can't be kept in {shown(path)} because it is inside OneDrive ({root.name}). OneDrive "
                                "copies files while they are being written, which damages a database. Keep them beside the "
                                "database on this computer; a copy somewhere else is a separate, later feature.")
        raise PlatformError(f"Your data can't be kept in {shown(path)} because it is inside OneDrive ({root.name}). OneDrive "
                            "copies files while they are being written, which damages the database. Choose a folder on "
                            "this computer that OneDrive doesn't sync; backups can still go to OneDrive.")
    return Path(path).expanduser().resolve()


# Private files and folders (#86). Mode bits do nothing on Windows, where the user's profile permissions apply.

def private_folder(path):
    """`path` as a folder only this user can open (0700), made if it is not there and set right if it already was (it may
    have been made at the umask's 0755). A link is refused: setting its mode would change the folder it points to."""
    path = Path(path)
    if path.is_symlink():
        raise PlatformError(f"{shown(path)} is a shortcut, not a real folder. Replace it with a real folder, then try again.")
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path, 0o700)
    return path


def private_file(path):
    """A new, empty file at `path` that only this user can read (0600) from the moment it exists, so a database written into
    it is never open to others, not even for a moment. Never replaces a file: it raises FileExistsError if `path` is taken."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)       # the umask can only remove bits
    os.close(fd)
    return Path(path)


# Opening files and the system's own dialogs

def _run(args, run=None):
    """Start a program from an argument list (never through a shell) and return the finished process."""
    return (run or subprocess.run)(list(args), capture_output=True, text=True, check=False)


def open_file(path, run=None, on=None):
    """Open `path` in the program the system uses for it (Finder's double-click)."""
    _only_mac("Opening a file", on)
    path = _existing(path)
    _checked(_run(["open", str(path)], run), f"{path.name} could not be opened")


def reveal_file(path, run=None, on=None):
    """Show `path` selected in its folder in Finder."""
    _only_mac("Showing a file in its folder", on)
    path = _existing(path)
    _checked(_run(["open", "-R", str(path)], run), f"{path.name} could not be shown in its folder")


def open_url(url, run=None, on=None):
    """Open a web address (http or https only) in the person's default browser."""
    _only_mac("Opening a web page", on)
    url = str(url)
    if not re.match(r"https?://[^\s]+\Z", url):       # also keeps a value starting with "-" from being read as an option
        raise PlatformError(f"Only web addresses starting http:// or https:// can be opened. You gave {url}.")
    done = _run(["open", url], run)
    if done.returncode != 0:
        raise PlatformError(f"The browser could not be opened. {TRY_AGAIN}")


def _existing(path):
    path = Path(path)
    if not path.exists():
        raise PlatformError(f"{path.name} isn't there any more.")
    return path.resolve()           # absolute, so a name starting with "-" is never read as an option


TRY_AGAIN = "Try again; if it keeps happening, restart clark."          # the system's own error text is never shown


def _checked(done, what):
    if done.returncode != 0:
        raise PlatformError(f"{what}. {TRY_AGAIN}")
    return done


# The scripts read the prompt, names and folders as arguments, so no text a person typed ever becomes part of a script.
FOLDER_SCRIPT = """on run argv
  if (count of argv) > 1 then
    return POSIX path of (choose folder with prompt (item 1 of argv) default location (POSIX file (item 2 of argv)))
  end if
  return POSIX path of (choose folder with prompt (item 1 of argv))
end run"""
SAVE_SCRIPT = """on run argv
  if (count of argv) > 2 then
    return POSIX path of (choose file name with prompt (item 1 of argv) default name (item 2 of argv) default location (POSIX file (item 3 of argv)))
  end if
  return POSIX path of (choose file name with prompt (item 1 of argv) default name (item 2 of argv))
end run"""


def choose_folder(prompt, start=None, run=None, on=None):
    """The system's own folder dialog. The chosen folder, or None if the person cancelled."""
    _only_mac("The folder dialog", on)
    return _dialog(FOLDER_SCRIPT, [prompt] + ([str(start)] if start else []), run, "folder")


def choose_save_file(prompt, default_name, start=None, run=None, on=None):
    """The system's own Save dialog, suggesting `default_name` (made safe). The chosen file, or None if cancelled."""
    _only_mac("The Save dialog", on)
    return _dialog(SAVE_SCRIPT, [prompt, safe_name(default_name)] + ([str(start)] if start else []), run, "Save")


def _dialog(script, args, run, which):
    done = _run(["osascript", "-e", script, *args], run)
    if done.returncode != 0:
        if CANCELLED in (done.stderr or ""):
            return None
        raise PlatformError(f"The {which} window could not be opened. {TRY_AGAIN}")
    return Path(done.stdout.strip())


# File names and replacing files

def safe_name(name, folder=None, max_name=MAX_NAME):
    """`name` made safe for Windows, OneDrive and SharePoint, applied on every system: reserved characters become "-",
    no trailing dot or space, a device name (CON, NUL, COM1...) gets "_" in front, and the name is shortened (keeping
    its extension) to `max_name` characters, and so the whole path in `folder` stays under Windows' 260-character limit."""
    name = RESERVED_CHARS.sub("-", str(name)).strip().rstrip(". ")
    if not name:
        name = "untitled"
    if name.split(".")[0].rstrip(" ").upper() in RESERVED_NAMES:      # Windows checks the name up to the first dot, minus spaces
        name = "_" + name
    limit = max_name
    if folder is not None:
        room = MAX_PATH - 1 - len(str(Path(folder))) - 1      # the NUL, and the separator before the name
        if room < 12:
            raise PlatformError("That folder is too deep for the report to be saved in it. Choose a folder nearer the top of the drive.")
        limit = min(limit, room)
    if len(name) > limit:
        stem, dot, ext = name.rpartition(".")
        if not dot or not stem or len(ext) > 10:
            stem, ext = name, ""
        keep = limit - (len(ext) + 1 if ext else 0)
        name = stem[:keep].rstrip(". ") + ("." + ext if ext else "")
    return name


def replace_file(source, dest, attempts=REPLACE_ATTEMPTS, first_wait=REPLACE_FIRST_WAIT, sleep=time.sleep,
                 replace=os.replace):
    """Move `source` over `dest` in one step. Another program (OneDrive, Word, antivirus) may hold `dest` for a moment,
    so a refused replace is retried with a short backoff; if it stays locked, the message names the file."""
    wait = first_wait
    for attempt in range(1, attempts + 1):
        try:
            replace(source, dest)
            return Path(dest)
        except OSError as e:
            if e.errno not in LOCKED and not isinstance(e, PermissionError):
                raise
            if attempt == attempts:
                raise PlatformError(f"{Path(dest).name} couldn't be saved because another program is using it or it "
                                    f"is locked ({shown(dest)}). Close it there and try again.") from e
            sleep(wait)
            wait *= 2


def open_plain_file(path, flags):
    """An `opener` for open(): opens `path` for reading without following a link and without waiting on a pipe, and only
    hands back the descriptor if it is an ordinary file (OSError otherwise). Used to read a file in a client's folder, where
    another program may have put a link or a pipe under the name."""
    fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "not an ordinary file")
    except BaseException:
        os.close(fd)
        raise
    return fd


def is_mine(st):
    """Whether a file's stat says it belongs to the user running clark (always True where the system has no owner numbers)."""
    return not hasattr(os, "getuid") or st.st_uid == os.getuid()


def _write_temp(dest, data):
    """Write `data` (bytes, or text as UTF-8) to a new temporary file beside `dest`; the temporary file's path.
    The name is unique per call, so threads never share one."""
    dest = Path(dest)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.{secrets.token_hex(4)}.part")
    try:
        if isinstance(data, str):
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                f.write(data)
        else:
            with open(tmp, "wb") as f:
                f.write(data)
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise
    return tmp


def write_file(dest, data, **retry):
    """Write `data` (bytes, or text written as UTF-8) to `dest` safely: to a temporary file beside it, then replace_file.
    Nothing half-written is ever left at `dest`, and the temporary file is removed if the replace fails. Two writers
    at once each use their own temporary file; the last replace wins."""
    dest = Path(dest)
    tmp = _write_temp(dest, data)
    try:
        return replace_file(tmp, dest, **retry)
    finally:
        if tmp.exists():
            tmp.unlink()


def move_unless_exists(src, dest, link=os.link, replace=replace_file, exists=os.path.lexists):
    """Move `src` to `dest` only if nothing is called `dest` yet. True if it was placed (and `src` is gone); False if the name
    was taken, in which case nothing at `dest` is touched and `src` is left where it was for the caller to remove.
    A rename replaces a file that appeared a moment ago; a hard link does not: os.link fails if `dest` exists, whatever
    made it, whenever it came. So the file is linked into place and then `src` is unlinked. A disk that can't link
    (errno EPERM, EXDEV, ENOTSUP or ENOSYS) gets a last look at whether `dest` exists and then replace_file, which leaves
    a very small gap that a link does not. Any other error is raised. `link`, `replace` and `exists` are for tests."""
    try:
        link(src, dest)
    except FileExistsError:
        return False
    except OSError as e:
        if e.errno not in NO_HARD_LINKS:
            raise
        if exists(dest):
            return False
        replace(src, dest)
        return True
    try:
        os.unlink(src)
    except OSError:
        pass                      # placed; a leftover temporary name is the caller's to remove (write_file_unless_exists does)
    return True


def write_file_unless_exists(dest, data, **kw):
    """write_file that never replaces: the bytes go to a temporary file beside `dest`, then move_unless_exists. True if
    written; False if a file or folder called `dest` is there, even if it came after this call began. The temporary file is
    always removed. `kw` is passed to move_unless_exists (link, replace, exists)."""
    dest = Path(dest)
    tmp = _write_temp(dest, data)
    try:
        return move_unless_exists(tmp, dest, **kw)
    finally:
        if tmp.exists():
            tmp.unlink()


# Starting clark and opening its window (#71). The launcher (launch.py) holds the logic; the system calls are here.

CHROME_MAC = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"     # also looked for in ~/Applications
LAUNCHER_MAC = "clark.command"          # the double-clickable file in clark's folder; Windows will have clark.cmd (#57)
LOG_LIMIT = 1024 * 1024                 # the server's log is started again when it is bigger than this


def launcher_name(on=None):
    """The file name a person double-clicks to start clark."""
    _only_mac("The launcher file", on)
    return LAUNCHER_MAC


def find_chrome(environ=None, home=None, exists=os.path.exists, on=None):
    """The Chrome program to open clark's window with, or None. CLARK_BROWSER names another program to use instead (the
    tests use a stub); if it isn't there, None, so the default browser is used."""
    _only_mac("Finding Chrome", on)
    environ = os.environ if environ is None else environ
    named = environ.get("CLARK_BROWSER")
    if named:
        return named if exists(named) else None
    for found in (CHROME_MAC, str(Path(home or Path.home()) / "Applications" / "Google Chrome.app" / "Contents" / "MacOS"
                                  / "Google Chrome")):
        if exists(found):
            return found
    return None


ROOT_NAME = "the top of the drive"


def folder_name(path):
    """The last part of `path`, for a message. A drive root (/ or C:\\) has no name, so it reads "the top of the drive"."""
    text = str(path).rstrip("/\\")
    name = os.path.basename(text.replace("\\", "/"))
    return name if name and not (len(name) == 2 and name[1] == ":") else ROOT_NAME


def folder_phrase(path, capital=False):
    """The folder as a sentence reads it: the folder “Reports”, or the top of the drive for a root (never an empty quote)."""
    name = folder_name(path)
    text = name if name == ROOT_NAME else f"the folder “{name}”"
    return text[0].upper() + text[1:] if capital else text


def with_tilde(path, home=None):
    """`path` as a person reads it: the home folder written ~, so a message never shows the account's folder name."""
    text, home = str(path), str(Path(home) if home else Path.home())
    return "~" + text[len(home):] if text == home or text.startswith(home.rstrip("/") + "/") else text


def start_detached(argv, env, log_path, cwd=None, popen=None, on=None):
    """Start `argv` (an argument list, never a shell) in a session of its own, so it keeps running when this program and its
    window end. Its output is added to `log_path` (started again first if it has grown past LOG_LIMIT). The process."""
    _only_mac("Starting clark in the background", on)
    log_path = Path(log_path)
    try:
        if log_path.exists() and log_path.stat().st_size > LOG_LIMIT:
            log_path.write_bytes(b"")
        with open(log_path, "ab") as log:
            return (popen or subprocess.Popen)(list(argv), cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                               start_new_session=True)
    except OSError as e:
        raise PlatformError(f"The app could not start. Try again; if it keeps happening, send the file {with_tilde(log_path)} to the clark team.") from e


def open_app_window(url, chrome, popen=None, on=None):
    """Open `url` in a Chrome app window (no address bar or tabs). It is left running."""
    _only_mac("Opening an app window", on)
    url = str(url)
    if not re.match(r"https?://[^\s]+\Z", url):
        raise PlatformError(f"Only web addresses starting http:// or https:// can be opened. You gave {url}.")
    try:
        (popen or subprocess.Popen)([str(chrome), "--app=" + url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        raise PlatformError("The window could not be opened.") from e


# The Claude command (ask clark). Found on the PATH and started from an argument list. A .cmd or .bat is refused on every
# system: Windows passes its arguments through cmd.exe, which can turn text in an argument into a command
# (docs/handoff/portability-and-sharing.md).
CLAUDE = "claude"
NO_SCRIPTS = (".cmd", ".bat")


def find_claude(which=shutil.which):
    """The Claude command to run, or None if it isn't on the PATH. A .cmd or .bat file is refused with the reason."""
    found = which(CLAUDE)
    if found and Path(found).suffix.lower() in NO_SCRIPTS:
        raise PlatformError("The copy of Claude Code on this computer can't be used safely by ask clark. Install Claude "
                            "Code's own app (claude.exe), then start clark again.")
    return found or None


STOP_WAIT = 2.0          # seconds between the polite stop and the kill of a run_stoppable group


def _end_group(proc):
    """End `proc`'s whole process group: a polite stop, a short wait, then a kill. The program was started in a new session, so
    its group's id is its own pid, which still names the group after the leader itself has gone. Safe to call twice."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            return                              # no one is left in the group
        try:
            proc.wait(timeout=STOP_WAIT)
        except subprocess.TimeoutExpired:
            continue
        if sig == signal.SIGTERM:
            time.sleep(0.05)                    # a helper may outlive its leader by a moment; the kill that follows catches it


def run_stoppable(args, data, env, limit, max_out, stop=None, prefix="clark-run-"):
    """Run one program from an argument list (never a shell) as the leader of its own process group, in a new empty folder of its
    own (removed afterwards), with exactly `env` as its environment, umask 077 (what it makes is private to the person), `data`
    on standard input, and read at most `max_out` bytes of standard output within `limit` seconds. `stop` (a threading.Event) ends it early. Returns (status, out, code): status is
    "ok" (exit code 0), "failed" (any other code, or it could not start), "slow", "too_much" or "stopped"; `out` is empty unless
    the program finished. Standard error is thrown away (it could hold what it was given). Whatever ends the run, the whole
    group is ended (anything the program started goes too). Used by ask clark's provider (#47c); never raises for the program's
    own faults."""
    work = tempfile.mkdtemp(prefix=prefix)
    proc = None
    try:
        try:
            proc = subprocess.Popen(list(args), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=work,
                                    env=dict(env), close_fds=True, start_new_session=True, shell=False,
                                    umask=0o077)
        except (OSError, ValueError, subprocess.SubprocessError):
            return "failed", b"", None

        def feed():
            try:
                proc.stdin.write(data)
            except (OSError, ValueError):
                pass
            finally:
                try:
                    proc.stdin.close()
                except (OSError, ValueError):
                    pass
        threading.Thread(target=feed, daemon=True).start()
        deadline, out, status = time.monotonic() + limit, bytearray(), None
        fd = proc.stdout.fileno()
        while status is None:
            if stop is not None and stop.is_set():
                status = "stopped"
                break
            left = deadline - time.monotonic()
            if left <= 0:
                status = "slow"
                break
            ready, _w, _x = select.select([fd], [], [], min(0.2, left))
            if not ready:
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            out += chunk
            if len(out) > max_out:
                status = "too_much"
        if status is None:
            try:
                code = proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                status = "slow"
            else:
                _end_group(proc)                # helpers it left behind in its group go too
                return ("ok" if code == 0 else "failed"), bytes(out), code
        _end_group(proc)
        return status, b"", proc.returncode
    finally:
        if proc is not None:
            if proc.poll() is None:
                _end_group(proc)
            for pipe in (proc.stdout, proc.stdin):
                try:
                    pipe.close()
                except (OSError, ValueError, AttributeError):
                    pass
        shutil.rmtree(work, ignore_errors=True)


# The key store (#54): where an AI provider's API key is kept. Only the macOS Keychain is built; any other system answers "not
# connected" (NotBuiltStore), so a key is never kept in a file. The key never goes into clark's database, settings, logs, history,
# error text or the page, and never onto a command line: `security` runs from a fixed argument list (no shell) and `put` hands it
# the whole command, key included, on standard input through its interactive mode (`security -i`), which reads commands from
# there. `has` never reads the secret. Standard error is thrown away (run_stoppable) and no failure carries the program's words.
SECURITY = "/usr/bin/security"
KEY_ACCOUNT = "clark"
KEY_SHAPE = re.compile(r"[A-Za-z0-9_-]{20,256}")         # every key clark keeps; nothing in it needs quoting on security's line
KEY_SERVICE = re.compile(r"clark\.ai\.[0-9a-f]{16}\.[a-z]{2,16}")
KEY_LIMIT = 15.0                                        # seconds for one keychain step
KEY_MAX_OUT = 4096
NOT_FOUND = 44                                          # security's exit code for "The specified item could not be found"
KEY_NOT_SAVED = "The key could not be kept in this Mac's keychain. Nothing was saved. Try again; if it keeps happening, restart clark."
KEY_NOT_REMOVED = "The key could not be taken out of this Mac's keychain. Open Keychain Access and delete it there, then try again."


class KeyStore:
    """The interface: `has(service)` (True or False, never reading the secret), `put(service, key)`, `remove(service)` (True when
    there is no item afterwards) and `peek(service)` (the key, or None). `put` and `remove` raise PlatformError with fixed words."""
    built = False

    def has(self, service):
        return False

    def put(self, service, key):
        raise NotBuiltYet("Keeping a key on this system isn't built yet. Nothing was saved.")

    def remove(self, service):
        return True

    def peek(self, service):
        return None


class NotBuiltStore(KeyStore):
    """Every system but macOS until its own store is written (Windows: Credential Manager, later): never connected."""


def _key_env():
    env = {"PATH": "/usr/bin:/bin", "LANG": "en_GB.UTF-8"}
    home = os.path.expanduser("~")
    if home and home != "~":
        env["HOME"] = home
    return env


class MacKeychain(KeyStore):
    """The login keychain through /usr/bin/security. `run` is a seam for the tests (run_stoppable's shape); no test uses the real
    keychain."""
    built = True

    def __init__(self, run=None, program=SECURITY):
        self.run = run or run_stoppable
        self.program = program

    def _step(self, args, data=b""):
        return self.run([self.program, *args], data, _key_env(), KEY_LIMIT, KEY_MAX_OUT, prefix="clark-key-")

    def _service(self, service):
        if not isinstance(service, str) or not KEY_SERVICE.fullmatch(service):
            raise PlatformError("That isn't a key clark keeps. Nothing was changed.")
        return service

    def has(self, service):
        status, _out, code = self._step(["find-generic-password", "-s", self._service(service), "-a", KEY_ACCOUNT])
        return status == "ok" and code == 0

    def put(self, service, key):
        service = self._service(service)
        if not isinstance(key, str) or not KEY_SHAPE.fullmatch(key):
            raise PlatformError(KEY_NOT_SAVED)
        line = f"add-generic-password -U -s {service} -a {KEY_ACCOUNT} -w {key}\n".encode("ascii")
        status, _out, code = self._step(["-i"], line)
        if status != "ok" or code != 0:
            raise PlatformError(KEY_NOT_SAVED)

    def remove(self, service):
        status, _out, code = self._step(["delete-generic-password", "-s", self._service(service), "-a", KEY_ACCOUNT])
        if (status == "ok" and code == 0) or code == NOT_FOUND:
            return True
        raise PlatformError(KEY_NOT_REMOVED)

    def peek(self, service):
        status, out, code = self._step(["find-generic-password", "-s", self._service(service), "-a", KEY_ACCOUNT, "-w"])
        if status != "ok" or code != 0:
            return None
        key = out.decode("ascii", "replace").strip()
        return key if KEY_SHAPE.fullmatch(key) else None


def key_store(on=None):
    """This system's key store: the Mac Keychain on macOS, otherwise one that is never connected."""
    return MacKeychain() if (on or system()) == MAC else NotBuiltStore()
