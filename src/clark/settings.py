"""The smallest reading seam for clark's settings (#111): `<data folder>/settings.json`, read with defaults.

There is no settings store in clark yet (FR-1 is still to come). This file holds only what a built item needs today: the number of
backups kept, and (#180) the person's name and email, so each has one place to read it. A later settings module replaces the reading and writing here and keeps the
names (`backups_kept`, `set_backups_kept`) and the file. Nothing here names a path outside the data folder it is given.

The file is a JSON object. A missing file, a file that isn't a JSON object, a value of the wrong kind or one out of range is not an
error: the default is used, so a bad settings file can never stop a backup or its tidying up. Standard library only, Python 3.9.
"""
import json
import re
import unicodedata
from pathlib import Path

from clark import platform

FILE = "settings.json"
LIMIT = 64 * 1024                       # a settings file larger than this is not read
BACKUPS_KEPT = "backups_kept"
BACKUPS_KEPT_DEFAULT = 14               # = backup.KEEP; a test keeps the two equal
BACKUPS_KEPT_RANGE = (1, 365)

# What Settings › Safety says about the number, in plain words (the page shows these, not the key).
BACKUPS_KEPT_LABEL = "How many backups to keep"
BACKUPS_KEPT_HELP = ("This many backups are kept of each kind (daily, before an undo, before an import and so on); the oldest "
                     "are removed after that. 14 is usual. The newest backup is always kept.")


def read(data_dir):
    """The settings object in `data_dir`, or {} when there is none or it can't be read as one."""
    path = Path(data_dir) / FILE
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > LIMIT:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return {}
    return value if isinstance(value, dict) else {}


def _whole_number_in(value, low, high):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def backups_kept(data_dir):
    """How many backups of each kind are kept: the file's whole number from 1 to 365, else the default (14)."""
    value = read(data_dir).get(BACKUPS_KEPT)
    return value if _whole_number_in(value, *BACKUPS_KEPT_RANGE) else BACKUPS_KEPT_DEFAULT


def set_backups_kept(data_dir, number):
    """Save the number kept (a whole number from 1 to 365), leaving every other setting as it is. Raises ValueError in plain
    words for anything else. The file is replaced in one step (platform.write_file)."""
    if not _whole_number_in(number, *BACKUPS_KEPT_RANGE):
        raise ValueError(f"Choose a whole number of backups from {BACKUPS_KEPT_RANGE[0]} to {BACKUPS_KEPT_RANGE[1]}.")
    data_dir = Path(data_dir)
    current = read(data_dir)
    path = data_dir / FILE
    if not current and (path.is_symlink() or path.exists()):
        try:
            readable = (not path.is_symlink() and path.is_file() and path.stat().st_size <= LIMIT
                        and isinstance(json.loads(path.read_text(encoding="utf-8")), dict))
        except (OSError, ValueError, RecursionError):
            readable = False
        if not readable:     # never replace a file that can't be read: it may hold other settings
            raise ValueError("Your settings couldn't be read, so the number wasn't changed. Nothing was lost.")
    current[BACKUPS_KEPT] = number
    platform.write_file(data_dir / FILE, json.dumps(current, indent=2, sort_keys=True) + "\n")
    return number


# ===== Your name and your email (#180, Settings › Personal › About you) =====
# Kept in the same file as the backups number: this person's, on this computer. Both are optional. The name is shown at the top of the
# profile menu and is the name on each change (by_user) instead of the login name; the email is only used to tell which addresses are
# the person's own (the Draft email's own domain). clark never reads either from the computer, the browser or the Claude sign-in, and
# never sends mail.
PROFILE_NAME = "profile_name"
PROFILE_EMAIL = "profile_email"
NAME_MAX, EMAIL_MAX = 60, 254
NAME_TOO_LONG = f"Your name is too long. Use {NAME_MAX} characters or fewer. Nothing was saved."
NAME_BAD = "Your name has a character that can't be kept. Remove it and try again. Nothing was saved."
EMAIL_BAD = "That email address is not complete. Check it, or leave it empty. Nothing was saved."
PROFILE_UNREADABLE = "Your settings couldn't be read, so your name and email were not changed. Nothing was saved."
_UNSEEN = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
_ADDRESS = re.compile(r"[^@\s<>?,;:\"()\[\]\\]+@[^@\s<>?,;:\"()\[\]\\]+\.[^@\s<>?,;:\"()\[\]\\]+")


def _one_line(value):
    """`value` as text on one line (runs of spaces made one, ends trimmed), or None when it holds a control, format, surrogate,
    private-use, unassigned or separator-line character (a bidi override, a zero-width mark, a line break)."""
    text = value if isinstance(value, str) else ""
    if any(unicodedata.category(c) in _UNSEEN or (c.isspace() and c != " ") for c in text):
        return None
    return " ".join(text.split())


def profile(data_dir):
    """{"name", "email"} as saved ("" for each that is not there, or is not a plain string within its limit): never an error, and
    never anything but what was typed in Settings."""
    got = read(data_dir)
    name, email = _one_line(got.get(PROFILE_NAME)), _one_line(got.get(PROFILE_EMAIL))
    return {"name": name if name is not None and len(name) <= NAME_MAX else "",
            "email": email if email and len(email) <= EMAIL_MAX and _ADDRESS.fullmatch(email) else ""}


def set_profile(data_dir, name, email):
    """Save the name and the email (each may be empty), leaving every other setting as it is; returns what was saved. Raises ValueError
    in plain words, ending "Nothing was saved.", for a name over 60 characters or with an unkeepable character, or an email that is
    not shaped like an address, and then writes nothing. The file is replaced in one step (platform.write_file), and a file that can't
    be read is never replaced."""
    if name is not None and not isinstance(name, str) or email is not None and not isinstance(email, str):
        raise ValueError(NAME_BAD)
    clean_name, clean_email = _one_line(name or ""), _one_line(email or "")
    if clean_name is None:
        raise ValueError(NAME_BAD)
    if len(clean_name) > NAME_MAX:
        raise ValueError(NAME_TOO_LONG)
    if clean_email is None or clean_email and (len(clean_email) > EMAIL_MAX or not _ADDRESS.fullmatch(clean_email)):
        raise ValueError(EMAIL_BAD)
    data_dir = Path(data_dir)
    current = read(data_dir)
    path = data_dir / FILE
    if not current and (path.is_symlink() or path.exists()):
        try:
            readable = (not path.is_symlink() and path.is_file() and path.stat().st_size <= LIMIT
                        and isinstance(json.loads(path.read_text(encoding="utf-8")), dict))
        except (OSError, ValueError, RecursionError):
            readable = False
        if not readable:
            raise ValueError(PROFILE_UNREADABLE)
    current[PROFILE_NAME], current[PROFILE_EMAIL] = clean_name, clean_email
    platform.write_file(path, json.dumps(current, indent=2, sort_keys=True) + "\n")
    return {"name": clean_name, "email": clean_email}
