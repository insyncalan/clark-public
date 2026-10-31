"""clark reach: the one place that decides what ask clark may read (#47b). Standard library only, Python 3.9.

Copied from creaite's reach.py (v2.6.9, db5adb2), cut down to the read rule and changed from a deny list to an ALLOW list.

    classify(path, "read", folders, data) -> ("ordinary" | "never", reason)
    read_bytes(path, folders, data, limit) -> (bytes, truncated)   (raises Never; truncated if the file held more than limit)
    readable_files(folders, data) -> (files, skipped, stopped)   (skipped is the count the person is shown: "skipped for safety";
                                                              stopped says the list is incomplete because a cap was reached)
    never_inside(folder, data) -> the first never place or secret name at or around a folder, or None   (used when a folder is saved)

`folders` is the open project's saved source folders: the `path` column of its `source_folders` rows (in `sort_order`;
`Store.read("source_folders", project)`), as a list of strings. `data` is clark's data folder (`platform.data_dir()`).
Both come in as arguments; this file knows no project, opens no database and writes nothing.

What may be read: a regular file inside a saved folder, and nothing else. The path is expanded (~) and resolved first, so a
link or `..` is judged by where it really points. It is refused (never) when:
  1. it is a place clark never reads: secrets and system folders (platform.never_read_places(), creaite's 39 read rows) and
     clark's own data folder (the database, its journals, backups and settings), wherever the path points, and clark's own
     program folder (#54: providers.py, which knows how keys are kept, is never readable by a question);
  2. it is not inside a saved folder (a second project's folder is not this project's);
  3. a name on the way holds secrets: any SECRET_NAMES pattern at the saved folder and at ANY depth inside it, and a secret
     a folder above the saved one called `dev.env` or `Plans.key` is no secret, so a project under it is read;
  4. it is not an ordinary file (a folder, link, pipe, socket or device), or it has more than one name on disk (a hard link
     carries no sign of where it came from), or it is an online-only OneDrive file (reading it would download it);
  5. it is on another disk or share than the saved folder (a different st_dev): clark does not cross into a mount.

Names are compared the way the Mac's disk does, not just without case: NFKC-normalised and case-folded on BOTH sides (the
name and the pattern), so `id_r\u017fa` (long s) and `.\u00dfh` (sharp s) are `id_rsa` and `.ssh`, as APFS says they are. Trailing
spaces and dots are dropped before a name is tested. `read_bytes` then judges the names the disk really holds for each folder
on the way (the entry with the same device and inode), so the name judged is the real one.

SECRET_NAMES (each name on the way is tested, so `.git/anything` and `a/b/c/.env` are caught):
  folders  .git .ssh .gnupg .aws .kube .docker .azure .password-store .terraform .oci .bundle
  files    .env*  *.env  *.pem*  *.key*  *.p12  *.pfx  *.p8  *.asc  *.gpg  *.pgp  *.kdbx  *.keychain*  *.ppk  *.jks  *.keystore
           *.tfstate*  *.tfvars*  id_rsa*  id_dsa*  id_ecdsa*  id_ed25519*  .netrc  _netrc  .npmrc  .pypirc  .pgpass*
           .git-credentials  .htpasswd  kubeconfig  client_secret*.json  service-account*.json  secrets.*
           credentials  credentials*.json  .dockercfg  .vault_pass*  service_account*.json  serviceAccountKey.json
           *credentials*  *secret*.json  .boto  .s3cfg  .my.cnf  .vault*  token*.json  oauth.json  private_key.json
           secret_key_base  .gitconfig
Choices: a public key (`id_rsa.pub`) is barred with its private key, because `id_rsa*` is simpler and safer than telling them
apart and a public key is of no use to a report; `*.key*` also bars Keynote files, and `.env.example` and `.envelope` are
barred with the real `.env`. Over-matching is safe here: the person sees a count of what was skipped.

Reads are opened by `read_bytes`, which opens the resolved path one folder at a time with O_NOFOLLOW, so the path that was
checked is the path that is opened and no folder on the way can be swapped for a link between the check and the open.
`read_bytes` reads one byte more than `limit` to say whether the file was cut. `readable_files` stops at MAX_FILES files,
MAX_TOTAL_BYTES bytes in all, and MAX_DEPTH folders deep, and says so in the skipped count.
Not done here, handed off to #47d: choosing which files are worth reading (filtering out binary files). This file decides only
what is safe to read.
Not determined without a real OneDrive volume: a placeholder *folder* (dataless directory); recorded for the hand check.
"""
import errno
import fnmatch
import functools
import os
import stat as stat_module
import time
import unicodedata
from collections import namedtuple
from pathlib import Path

from clark import platform

OPERATIONS = ("read",)

SECRET = "it holds secrets (keys, passwords, sign-ins)"
SYSTEM = "it is part of the operating system"
DATA = "it is clark's own data (the database, its backups and settings)"
OUTSIDE = "it is not inside a folder you saved for this project"
NOT_FILE = "it is not an ordinary file (it is a folder, a link, a pipe or a device)"
NOT_THERE = "it isn't there"
LINKED = "it has more than one name on disk, so clark can't tell where it came from"
ONLINE = "it is an online-only OneDrive file (not on this device): clark never downloads one"
LINK = "it is a link to a folder, and clark doesn't follow links inside a folder"
MOUNT = "it is on another disk or share than the folder you saved, and clark doesn't cross into one"
TOO_MANY = "there are more files than clark takes in at once, so it stopped listing"
TOO_BIG = "the files add up to more than clark takes in at once, so it stopped listing"
TOO_DEEP = "it is in folders nested deeper than clark goes"
TOO_MANY_ENTRIES = "there are more folders and files than clark looks through at once, so it stopped listing"
TOO_SLOW = "looking through the folders took longer than clark allows, so it stopped listing"
NO_DATA = "clark can't tell where its own data is kept"
PROGRAM = "it is part of clark itself"
PROGRAM_DIR = Path(__file__).resolve().parent      # #54: the clark package (providers.py, the key store's code) is never read
KIND_REASON = {"secret": SECRET, "system": SYSTEM}

SECRET_FOLDERS = (".git", ".ssh", ".gnupg", ".aws", ".kube", ".docker", ".azure", ".password-store", ".terraform", ".oci",
                  ".bundle")
SECRET_FILES = (".env*", "*.env", "*.pem*", "*.key*", "*.p12", "*.pfx", "*.p8", "*.asc", "*.gpg", "*.pgp", "*.kdbx",
                "*.keychain*", "*.ppk", "*.jks", "*.keystore", "*.tfstate*", "*.tfvars*", "id_rsa*", "id_dsa*", "id_ecdsa*",
                "id_ed25519*", ".netrc", "_netrc", ".npmrc", ".pypirc", ".pgpass*", ".git-credentials", ".htpasswd", "kubeconfig",
                "client_secret*.json", "service-account*.json", "secrets.*", "credentials", "credentials*.json",
                ".dockercfg", ".vault_pass*", "service_account*.json", "serviceAccountKey.json", "*credentials*", "*secret*.json",
                ".boto", ".s3cfg", ".my.cnf", ".vault*", "token*.json", "oauth.json", "private_key.json", "secret_key_base",
                ".gitconfig")
SECRET_NAMES = SECRET_FOLDERS + SECRET_FILES

# Files the system and Office make that hold nothing to read. Left out of readable_files without being counted as skipped.
NOISE = (".DS_Store", "~$*", ".~lock.*", "._*", ".Trash", ".Trashes", ".Spotlight-V100", ".fseventsd", ".TemporaryItems",
         ".localized", "Thumbs.db", "desktop.ini")

MAX_FILES = 20000                # what readable_files lists at most
MAX_TOTAL_BYTES = 2 * 1024 ** 3  # the size of those files added together
MAX_DEPTH = 64                   # folders below a saved folder
MAX_ENTRIES = 100000             # folders and files looked at (kept or skipped): 60,000 empty folders took 109 s with no file to count
TIME_BUDGET = 60.0               # seconds readable_files may take in all
CLOCK = time.monotonic           # the clock for TIME_BUDGET (a test replaces it)
MAX_PATH_BYTES = 1024            # macOS's PATH_MAX
MAX_NAME_BYTES = 255
SF_DATALESS = 0x40000000


Listing = namedtuple("Listing", "files skipped stopped")     # what readable_files answers


class BadPath(ValueError):
    """A path clark can't use, with the reason in plain words."""


class Never(Exception):
    """A read that is refused. `reason` says why, in plain words (never a path)."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def never_rows():
    """creaite's read-barring never rows as (base, pattern, "all", reason), from platform.never_read_places() (it raises
    NotBuiltYet where the places aren't written)."""
    return tuple((base, pattern, "all", KIND_REASON[kind]) for base, pattern, kind in platform.never_read_places())


def home(given=None):
    """The home folder's real path (`given` is for tests)."""
    return Path(os.path.realpath(given if given else os.path.expanduser("~")))


def real(path, home_dir=None):
    """The real path: `~` expanded, then symlinks and `..` resolved (a file that doesn't exist yet is resolved through its
    folder). Changed from creaite: no mapping of stored paths (no vault), a relative path is refused, and `\\` is kept as the
    legal file-name character it is on the Mac (the path checked must be the path opened). Raises BadPath for a path that
    can't be used; an empty or NUL-holding path, bytes, a number, a relative path, or one over the system's limits."""
    if not isinstance(path, (str, os.PathLike)):
        raise BadPath("the path is not text")
    s = os.fspath(path)
    if not isinstance(s, str):
        raise BadPath("the path is not text")
    if not s:
        raise BadPath("the path is empty")
    if "\0" in s:
        raise BadPath("the path has a character that can't be in a file name")
    if home_dir and (s == "~" or s.startswith("~/")):
        s = str(home_dir) + s[1:]
    s = os.path.expanduser(s)
    if not os.path.isabs(s):
        raise BadPath("the path is not an absolute path")
    try:
        raw = os.fsencode(s)
    except UnicodeError:
        raise BadPath("the path can't be written as a file name") from None
    if len(raw) >= MAX_PATH_BYTES or any(len(part) > MAX_NAME_BYTES for part in raw.split(b"/")):
        raise BadPath("the path is too long")
    return Path(os.path.realpath(s))


@functools.lru_cache(maxsize=16384)
def fold(name):
    """A name as the Mac's disk compares it: NFKC-normalised and case-folded (so a long s is an s, a sharp s is "ss", and the
    two spellings of an accent are one), then normalised again. For comparing only, never for opening."""
    return unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", name).casefold())


def parts_under(p, base):
    """p's parts below base, compared as fold() does; None if p isn't base or below it. (A deny list may over-match.)"""
    a, b = [fold(x) for x in Path(p).parts], [fold(x) for x in Path(base).parts]
    return list(Path(p).parts[len(b):]) if a[:len(b)] == b else None


def inside(p, root):
    """Whether the real path p is root or below it, by IDENTITY: the ancestor of p at root's depth must be the same folder as
    root (os.path.samefile). Case and Unicode spelling then differ only where the volume says they are one name (APFS), and
    on a case-sensitive volume `source` is never `Source`. Any OSError means not inside. For the allow list only."""
    pp, rp = Path(p).parts, Path(root).parts
    if len(pp) < len(rp) or not rp:
        return False
    try:
        return os.path.samefile(Path(*pp[:len(rp)]), root)
    except (OSError, ValueError):
        return False


def below(p, base):
    """p's parts below base for the never rows: by identity (inside), else compared without case (a deny list may
    over-match). None if p isn't base or below it."""
    if inside(p, base):
        return list(Path(p).parts[len(Path(base).parts):])
    return parts_under(p, base)


def matches(rel_parts, pattern):
    """Whether a path's parts below its base match a never-list pattern: part by part, shell wildcards, both sides folded
    (see fold); a pattern naming a folder covers everything in it."""
    pat = [x for x in pattern.strip("/").split("/") if x]
    return len(rel_parts) >= len(pat) and all(fnmatch.fnmatchcase(fold(r), fold(q)) for r, q in zip(rel_parts, pat))


def never_reason(p, home_dir, data):
    """The never row (platform's, then clark's data folder) that bars reading the real path p, as its reason; else None."""
    rels = {"home": below(p, home_dir), "data": below(p, data), "abs": list(Path(p).parts[1:])}      # worked out once each
    for base, pattern, _ops, reason in never_rows() + (("data", "", "all", DATA),):
        rel = rels[base]
        if rel is not None and matches(rel, pattern):
            return reason
    if below(p, PROGRAM_DIR) is not None:
        return PROGRAM
    return None


def secret_name(parts, folders_only=False):
    """The first of these path parts (names) that is a SECRET_NAMES pattern, else None (only SECRET_FOLDERS if `folders_only`).
    Both sides are folded (see fold) and trailing spaces and dots are dropped from the name first."""
    pats = [fold(pat) for pat in (SECRET_FOLDERS if folders_only else SECRET_NAMES)]
    for name in parts:
        key = fold(name).rstrip(" .")
        if any(fnmatch.fnmatchcase(key, pat) for pat in pats):
            return name
    return None


def secret_on_the_way(root, below):
    """The first secret name on the way to a file: ABOVE the saved folder `root` only a secret folder name counts (a folder
    called `dev.env` or `Plans.key` holds a project, not a secret); at the saved folder (its own name) and below it (the names
    in `below`) every SECRET_NAMES pattern counts. None if there is none."""
    return secret_name(root.parts[1:-1], True) or secret_name([root.parts[-1]] + list(below))


def roots(folders, home_dir=None):
    """The real paths of the saved folders that can be used: a text path, absolute, an existing folder, not "/". Anything
    else in the list (a NUL, a number, a folder that is gone) is left out: it is no place in reach."""
    out = []
    for f in folders or ():
        try:
            r = real(f, home_dir)
            if len(r.parts) > 1 and r.is_dir() and r not in out:
                out.append(r)
        except (OSError, ValueError, RuntimeError):
            continue
    return out


def online_only_stat(st):
    """A OneDrive placeholder, from a stat result: the dataless flag, or a size with no blocks (creaite paths.is_online_only)."""
    if getattr(st, "st_flags", 0) & SF_DATALESS:
        return True
    return st.st_size > 0 and getattr(st, "st_blocks", 1) == 0


def online_only(p):
    """A OneDrive placeholder: a file whose content isn't on this device. Reading one would download it. (creaite
    paths.is_online_only, kept here so no paths module is needed.)"""
    try:
        return online_only_stat(Path(p).stat())
    except OSError:
        return False


def data_path(data, home_dir=None):
    """The real path of clark's data folder, or None when it can't be worked out."""
    try:
        return real(data, home_dir) if isinstance(data, (str, os.PathLike)) and str(data) else None
    except (OSError, ValueError, RuntimeError):
        return None


def _judge(path, operation, folders, data, home_dir, want="file", saved=None):
    """(kind, reason, real path, saved folder it is in). `want` is "file", or "folder" when the walk asks about a folder.
    `saved` is the folders already resolved by roots(), so the walk doesn't do it for every file."""
    if operation not in OPERATIONS:
        raise ValueError(f"operation is one of {', '.join(OPERATIONS)}")
    try:
        p = real(path, home_dir)
    except BadPath as e:
        return "never", f"{e}", None, None
    except (OSError, ValueError, RuntimeError) as e:
        return "never", f"the path can't be worked out ({type(e).__name__})", None, None
    h = home(home_dir)
    d = data_path(data, home_dir)
    if d is None:
        return "never", NO_DATA, p, None
    why = never_reason(p, h, d)                     # secrets are named even for a path outside every folder
    if why:
        return "never", why, p, None
    root = next((r for r in (roots(folders, home_dir) if saved is None else saved) if inside(p, r)), None)
    if root is None:
        return "never", OUTSIDE, p, None
    if secret_on_the_way(root, p.parts[len(root.parts):]):         # secret folders above the saved folder, any secret name from it down
        return "never", SECRET, p, root
    try:
        st = os.lstat(p)
    except OSError:
        return "never", NOT_THERE, p, root
    try:
        root_dev = os.stat(root).st_dev
    except OSError:
        return "never", NOT_THERE, p, root
    if st.st_dev != root_dev:
        return "never", MOUNT, p, root
    if want == "folder":
        return ("ordinary", "", p, root) if stat_module.S_ISDIR(st.st_mode) else ("never", NOT_FILE, p, root)
    if not stat_module.S_ISREG(st.st_mode):
        return "never", NOT_FILE, p, root
    if st.st_nlink > 1:
        return "never", LINKED, p, root
    if online_only_stat(st):
        return "never", ONLINE, p, root
    return "ordinary", "", p, root


def classify(path, operation, folders, data, home_dir=None):
    """("ordinary" | "never", reason). See the module's description. Changed from creaite, whose classify is a deny list over
    the vault, the projects folder and the whole home folder: here only the saved folders are in reach. `home_dir` is for tests."""
    kind, why, _p, _root = _judge(path, operation, folders, data, home_dir)
    return kind, why


def never_inside(folder, data=None, home_dir=None):
    """The first never-read place (secrets, the operating system, clark's data folder) at or below this folder, or the one
    this folder is inside; failing that a secret folder name (`.git`, `.kube`...) above it, or a secret name for the folder itself; else None.
    Used when a folder is saved (47d)."""
    try:
        root = real(folder, home_dir)
    except (OSError, ValueError, RuntimeError):
        return str(folder)[:200]
    h = home(home_dir)
    for base, pattern, _ops, _why in never_rows():
        place = Path(pattern) if base == "abs" else h / pattern.split("*")[0].rstrip("/")
        place = Path(os.path.realpath(place))
        if parts_under(place, root) is not None or parts_under(root, place) is not None:
            return ("~/" + pattern) if base == "home" else pattern
    if data:
        try:
            d = real(data, home_dir)
        except (OSError, ValueError, RuntimeError):
            return secret_on_the_way(root, ())
        if parts_under(d, root) is not None or parts_under(root, d) is not None:
            return "clark's data folder"
    return secret_on_the_way(root, ())         # a secret folder above the folder (proj/.git/modules/x, ~/.kube/y), or its own name


# ===== the one way a source file is read =====
FLAGS = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
DIR_FLAGS = FLAGS | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
FILE_FLAGS = FLAGS | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0)    # a pipe must not block
CHUNK = 65536
DIR_FD_OPEN = os.open in os.supports_dir_fd       # not on Windows
_LOOP = {errno.ELOOP, errno.ENOTDIR}      # what O_NOFOLLOW / O_DIRECTORY answer when a name has become a link


def _same_folder(fd, root):
    a, b = os.fstat(fd), os.stat(root)
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def _disk_name(fd, name, st):
    """The name the folder open as `fd` really holds for the entry whose fstat is `st`: the entry with the same inode and
    device. On APFS a path may spell a name another way (a long s for an s) and still reach the entry; the name judged should
    be the one on the disk. `name` if the folder can't be listed or no entry is found (it is then judged as spelled)."""
    try:
        with os.scandir(fd) as entries:
            for entry in entries:
                if entry.inode() != st.st_ino:
                    continue
                found = os.stat(entry.name, dir_fd=fd, follow_symlinks=False)
                if (found.st_dev, found.st_ino) == (st.st_dev, st.st_ino):
                    return entry.name
    except (OSError, NotImplementedError, TypeError, ValueError):
        pass
    return name


def _open_file(p, root):
    """(the descriptor of the real path p, the names the disk holds for each part of it), opened from "/" one folder at a
    time with O_NOFOLLOW (and O_DIRECTORY), so no part of the path can have been swapped for a link since it was checked; the
    folder at the saved folder's depth must still be the saved folder. The disk's names are listed only for the saved folder
    and what is below it (the path above it is already real, see real()), so a read costs the same however deep the folder is.
    Raises Never."""
    if not (hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY") and DIR_FD_OPEN):
        raise platform.NotBuiltYet("Reading a source file safely on this system is not built yet: clark runs on macOS for now")
    parts = p.parts
    depth = len(root.parts)
    names = [parts[0]]
    fd = os.open(parts[0], DIR_FLAGS)
    try:
        if depth == 1 and not _same_folder(fd, root):
            raise Never(OUTSIDE)
        for i, name in enumerate(parts[1:-1], start=2):
            nxt = os.open(name, DIR_FLAGS, dir_fd=fd)
            try:
                names.append(_disk_name(fd, name, os.fstat(nxt)) if i >= depth else name)       # above the saved folder it is real already
            except BaseException:
                os.close(nxt)
                raise
            os.close(fd)
            fd = nxt
            if i == depth and not _same_folder(fd, root):
                raise Never(OUTSIDE)
        last = os.open(parts[-1], FILE_FLAGS, dir_fd=fd)
        try:
            names.append(_disk_name(fd, parts[-1], os.fstat(last)))
        except BaseException:
            os.close(last)
            raise
    finally:
        os.close(fd)
    return last, names


def read_bytes(path, folders, data, limit, home_dir=None):
    """(bytes, truncated): at most `limit` bytes of the file `path`, if ask clark may read it, and whether the file held more
    than that (one byte more is read to find out); else Never(reason). Classifies, then opens the RESOLVED path with
    O_NOFOLLOW (see _open_file), judges again the names the disk really holds, and checks the open file (a regular file, one
    name on disk, on the saved folder's device) before reading, so what was checked is what is read. Nothing is decoded here:
    a file that isn't UTF-8 comes back as bytes. clark's addition (no creaite original); the only way a source file is read."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ValueError("limit is a whole number of bytes, 0 or more")
    kind, why, p, root = _judge(path, "read", folders, data, home_dir)
    if kind != "ordinary":
        raise Never(why)
    try:
        fd, names = _open_file(p, root)
    except Never:
        raise
    except OSError as e:
        raise Never("it was changed while clark was opening it, or can't be opened "
                    f"({'it became a link' if getattr(e, 'errno', 0) in _LOOP else type(e).__name__})") from None
    try:
        st = os.fstat(fd)
        if not stat_module.S_ISREG(st.st_mode):
            raise Never(NOT_FILE)
        if st.st_nlink > 1:
            raise Never(LINKED)
        if online_only_stat(st):
            raise Never(ONLINE)
        if st.st_dev != os.stat(root).st_dev:
            raise Never(MOUNT)
        real_path = Path(*names)                            # the names the disk holds, judged as _judge judged the given ones
        why = never_reason(real_path, home(home_dir), data_path(data, home_dir))
        if why:
            raise Never(why)
        if secret_on_the_way(root, names[len(root.parts) - 1:]):
            raise Never(SECRET)
        out = b""
        while len(out) <= limit:
            chunk = os.read(fd, min(CHUNK, limit + 1 - len(out)))
            if not chunk:
                break
            out += chunk
        return out[:limit], len(out) > limit
    except OSError as e:
        raise Never(f"clark couldn't read it ({type(e).__name__})") from None
    finally:
        os.close(fd)


def is_noise(name):
    """Whether a file or folder name is one the system or Office makes (see NOISE); readable_files leaves it out unmentioned."""
    low = name.lower()
    return any(fnmatch.fnmatchcase(low, pat.lower()) for pat in NOISE)


def readable_files(folders, data, reasons=None, home_dir=None):
    """(files, skipped, stopped): the real paths of every file ask clark may read in the saved folders, sorted, each once; and how
    many things were skipped for safety (a file or folder that holds secrets, is part of clark's data, is a link, is not
    an ordinary file, has more than one name, is online only, is on another disk, or can't be opened). A skipped folder
    counts once, and its contents are not looked at. The system's and Office's own files (NOISE) are left out without being
    counted. The listing stops at MAX_FILES files or MAX_TOTAL_BYTES bytes (counted once, with its reason) and does not go
    deeper than MAX_DEPTH folders (each folder not entered counts once). It also stops, counted once with its reason, after
    MAX_ENTRIES folders and files looked at (kept or skipped, so a tree of empty folders ends too) or TIME_BUDGET seconds by CLOCK.
    `stopped` is True when the list is incomplete because one of those caps was reached (files, bytes, depth, entries or time), so the page can say "not everything was listed", not only count.
    `reasons`, if a dict, gets {plain reason: how many}.
    The UI shows the count so a file that never appears is explained."""
    files, seen, skipped = [], set(), [0]
    total = 0
    cut = False                                              # a cap was reached: the list is not everything
    entries, began = 0, CLOCK()

    def over():
        """The reason to stop now, if more than MAX_ENTRIES things have been looked at or TIME_BUDGET has run out."""
        nonlocal entries
        entries += 1
        if entries > MAX_ENTRIES:
            return TOO_MANY_ENTRIES
        return TOO_SLOW if CLOCK() - began > TIME_BUDGET else None

    def skip(why):
        skipped[0] += 1
        if reasons is not None:
            reasons[why] = reasons.get(why, 0) + 1

    saved = roots(folders, home_dir)

    def failed(e):
        skip("a folder couldn't be opened")

    for root in saved:
        kind, why, _p, _r = _judge(root, "read", folders, data, home_dir, "folder", saved)
        if kind != "ordinary":                               # the saved folder is itself, or is inside, a never place
            skip(why)
            continue
        stopped = False
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=failed):
            depth = len(Path(dirpath).parts) - len(root.parts)
            keep = []
            for name in sorted(dirnames):
                full = os.path.join(dirpath, name)
                if is_noise(name):
                    continue
                why = over()
                if why:
                    skip(why)
                    stopped = cut = True
                    break
                if os.path.islink(full):
                    skip(LINK)
                    continue
                kind, why, _p, _r = _judge(full, "read", folders, data, home_dir, "folder", saved)
                if kind != "ordinary":
                    skip(why)
                elif depth + 1 > MAX_DEPTH:
                    skip(TOO_DEEP)
                    cut = True
                else:
                    keep.append(name)
            dirnames[:] = keep
            if stopped:
                break
            for name in sorted(filenames):
                if is_noise(name):
                    continue
                why = over()
                if why:
                    skip(why)
                    stopped = cut = True
                    break
                kind, why, p, _r = _judge(os.path.join(dirpath, name), "read", folders, data, home_dir, "file", saved)
                if kind != "ordinary":
                    skip(why)
                elif p not in seen:
                    try:
                        size = os.lstat(p).st_size
                    except OSError:
                        skip(NOT_THERE)
                        continue
                    if len(files) >= MAX_FILES:
                        skip(TOO_MANY)
                        stopped = cut = True
                    elif total + size > MAX_TOTAL_BYTES:
                        skip(TOO_BIG)
                        stopped = cut = True
                    if stopped:
                        break
                    total += size
                    seen.add(p)
                    files.append(p)
            if stopped:
                dirnames[:] = []
                break
        if stopped:
            break
    return Listing(sorted(files), skipped[0], cut)
