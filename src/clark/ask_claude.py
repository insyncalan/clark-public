"""The one provider module: the Claude command on this computer (#47c, commit 5 of the design note). GUARDED-DERIVED: new code
written for clark, not a copy (creaite's environment scrub is unreleased; the isolating flags, standard input, the fixed places,
the version and flag check and the process-group Stop are all new here). Two readers and the owner's own words before it merges.

What it does, and nothing more: it starts the person's own `claude` command, signed in with their own Claude plan, with every
customisation switched off and no tools, gives it the one request text on standard input, and reads the reply from standard
output. clark never sees, keeps or sends a key: the command holds its own sign-in.

The safety steps, each one tested in tests/test_ask_claude.py with a fake command:
- MAC ONLY: on any other system nothing is started and one fixed sentence (`MAC_ONLY`) is the status.
- FOUND IN FIXED PLACES ONLY (`PLACES`): an absolute path, never the PATH of whatever started clark, never a shell. The first place
  that holds anything decides; a later place is never tried after a refused one.
- A NATIVE PROGRAM ONLY (`native_problem`): the place is followed to the file it names, and that file must be a Mac program (a
  Mach-O file, never a script such as an npm or nvm shim, which would need a PATH the run does not give), a plain file owned by
  this user, writable by nobody else, in a folder writable by nobody else, inside the person's home folder or Homebrew's folders.
  The run starts that exact file, so the file checked is the file run.
- FAILS CLOSED ON VERSION AND FLAGS: `claude --version` must read as a version and `claude --help` must list every flag in
  `NEEDED_FLAGS`; otherwise nothing is sent and the status says to update the command. Kept per file (path, size, time, inode).
- FAILS CLOSED ON THE SIGN-IN (`login_problem`): before every question, `claude auth status` must report a Claude sign-in
  (`authMethod` "claude.ai"). An API key, an API key script, a token or another provider is refused, so a question can never move
  to paid use by accident; not signed in, or an answer that can't be read, sends nothing.
- ISOLATED RUN: `--safe-mode` (no CLAUDE.md, memory, skills, plugins, hooks, MCP servers or custom commands), `--setting-sources ""`
  (no settings file is read: the smoke test found that `--safe-mode` alone still ran the person's `apiKeyHelper`, a script that
  supplies an API key), `--disable-slash-commands`, `--tools ""` (no tool at all), `--strict-mcp-config` (no MCP server),
  `--no-session-persistence` (nothing saved under ~/.claude), `--system-prompt` with the fixed rules (the default prompt, which
  carries the folder, the platform and the date, is replaced), `--max-turns 1`, a pinned `--output-format json`
  (one result object, read strictly) and a `--max-budget-usd` cap. Never `--bare` (it would allow an API key only and never the sign-in),
  never `--add-dir`, never a model, never a file argument. `--max-turns` is documented for print mode but some versions leave it
  out of `--help`, so it is in `UNLISTED_FLAGS`: sent, not looked for (with no tools there is one answer either way).
- SCRUBBED ENVIRONMENT (`child_env`): an allow-list built from nothing: HOME, USER and LOGNAME from the system's own record of
  this user (never from clark's environment), a fixed system PATH and a plain language, plus the pinned switches in `PINNED_ENV`.
  Nothing clark was started with is passed on: no ANTHROPIC_*, CLAUDE_*, cloud keys, tokens, proxies, NODE_OPTIONS or DYLD_*.
- THE REQUEST ON STANDARD INPUT, never in the arguments (a long command line is visible to every local process); standard input
  then reaches its end, so the command can never wait for more.
- ITS OWN FOLDERS: an empty working folder and a private temporary folder (TMPDIR and CLAUDE_CODE_TMPDIR), both 0700, new for each
  run, outside clark's data folder and removed afterwards; umask 077; only standard input, output and error are inherited.
- LIMITS: one run at a time, a time limit, a cap on the bytes read back (checked after each read of at most 64 KB, so it can be
  passed by up to that much before the run is ended). Stop, the time limit and the cap end the WHOLE process group (the command
  starts helpers), then kill it after a short wait. The process handling itself is platform.run_stoppable (only platform.py
  starts a program).
- NO CONTENT IN LOGS OR ERRORS: no question, passage, reply, path or error text from the command is kept; failures are fixed
  sentences. The reply text is handed back to ask.ask_provider, which reads it with the reply reader and claims check.
"""
import json
import os
import pwd
import re
import stat
import threading
import time
from pathlib import Path

from clark import ask, platform

PROVIDER = "claude"
PLACES = ("~/.local/bin/claude", "~/.claude/local/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude")
OTHER_ROOTS = ("/opt/homebrew", "/usr/local")       # besides the home folder, where the file a place names may be
NEEDED_FLAGS = ("--print", "--safe-mode", "--disable-slash-commands", "--tools", "--strict-mcp-config", "--setting-sources",
                "--no-session-persistence", "--system-prompt", "--output-format", "--max-budget-usd")
UNLISTED_FLAGS = ("--max-turns",)                 # documented for print mode, missing from some versions' --help: sent, not checked
NEVER_FLAGS = ("--bare", "--add-dir", "--mcp-config", "--settings", "--dangerously-skip-permissions", "--resume", "--continue",
               "--model", "--verbose", "--append-system-prompt", "--plugin-dir", "--agents")
SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
KEEP_ENV = ("HOME", "USER", "LOGNAME", "LANG")      # what the sign-in and the text need; everything else is left out
# Set in the child, never copied from clark's. The first three are the ones the design read named (no telemetry, no self-update,
# no other non-essential traffic); the last two are the documented belt and braces for error reports and saved prompt history.
PINNED_ENV = {"DISABLE_TELEMETRY": "1", "DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
              "DISABLE_ERROR_REPORTING": "1", "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1"}
TMP_NAMES = ("TMPDIR", "CLAUDE_CODE_TMPDIR")        # set by platform.run_stoppable to a new private folder for each run
SIGNED_IN = "claude.ai"                             # the only `authMethod` a question may use: the person's Claude plan
KEY_LOGINS = ("api_key", "api_key_helper")
AUTH_ARGS = ("--setting-sources", "", "auth", "status")   # the sign-in check reads no settings file (no apiKeyHelper, env or hooks)
LOGIN_REUSE = 2.0                                   # seconds a status() sign-in check stands for the question that follows it
MAX_BUDGET_USD = "1.00"                             # the command's own cap on one question's spend (counts against the plan)
TIME_LIMIT = 120.0                                  # seconds for one answer
CHECK_LIMIT = 15.0                                  # seconds for --version, --help or auth status
MAX_OUT = 4 * ask.MAX_REPLY + 65536                 # bytes read back: the reply as UTF-8, in its JSON wrapping
MAX_HELP = 512 * 1024
MAX_AUTH = 64 * 1024
VERSION = re.compile(rb"^\s*v?(\d+)\.(\d+)\.(\d+)\b")
_FLAG = r"-{1,2}[A-Za-z][A-Za-z0-9-]*"
OPTION_LINE = re.compile(r"^[ \t]*(" + _FLAG + r"(?:[ \t]*,[ \t]*" + _FLAG + r")*)(?=[ \t<\[=]|$)")   # "  -p, --print <x>  text"
MACH_O = (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca")
PROXY_NAMES = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy", "NODE_EXTRA_CA_CERTS",
               "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_TLS_REJECT_UNAUTHORIZED")
KEY_NAMES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

MAC_ONLY = ("Questions work on a Mac for now. Everything else in the report works as before, and a later version will cover this computer.")
NOT_INSTALLED = ("Questions need the Claude command, and it isn't installed on this computer. Install it from claude.com/claude-code, "
                 "sign in once, then ask again. Everything else in the report works as before.")
NOT_NATIVE = ("The Claude command on this computer can't be used safely, so nothing was sent. Install Claude with its own installer "
              "from claude.com/claude-code, then ask again.")
CANT_USE = "The version of Claude on this computer can't be used safely with clark. Update it, then ask again. Nothing was sent."
NOT_SIGNED_IN = "Claude isn't signed in on this computer. Open Terminal, type claude, and sign in when it asks. Then ask again."
API_KEY_LOGIN = ("Claude on this computer is signed in with an API key, which is paid for by use, so nothing was sent. "
                 "Connect Claude in Settings to use this.")
OTHER_LOGIN = ("Claude on this computer is signed in a way questions can't use, so nothing was sent. Open Terminal, type claude, "
               "and sign in with your Claude account. Then ask again.")
READY = "Claude is ready. Your question and the parts of the report it needs are sent to Claude, which Anthropic runs."
NO_ANSWER = ("Claude couldn't answer just now. Try again in a moment. If it keeps happening, open Terminal, type claude, and sign in "
             "when it asks.")
TOO_SLOW = "Claude took too long to answer, so it was stopped. Try a shorter question."
TOO_LONG_REPLY = "Claude's answer was too long to read, so it was stopped. Ask a narrower question."
BUSY = "Another question is being answered. Wait for it, or press Stop."
# Hints: added after the status sentence when this computer's set-up is one questions can't follow.
PROXY_HINT = ("This computer reaches the internet through a proxy or its own security certificates. Questions don't use those "
              "settings, so Claude may not answer here. If questions fail, ask whoever runs your network for a way to reach Claude "
              "without them.")
CONFIG_HINT = ("Your Claude settings are kept in a folder of their own. Questions use the standard folder, so Claude may say you "
               "aren't signed in. To fix it, open Terminal, type env -u CLAUDE_CONFIG_DIR claude, and sign in when it asks.")
KEY_HINT = ("An API key is set up for Claude on this computer. Questions never use it: they use your Claude sign-in. Connect Claude "
            "in Settings to use this.")


def _me():
    """This user's home folder and name, from the system's own record (never from an environment variable)."""
    try:
        rec = pwd.getpwuid(os.getuid())
        return rec.pw_dir, rec.pw_name
    except (KeyError, OSError):
        return "", ""


def child_env(home=None, user=None):
    """The child's whole environment, built from nothing: the home folder and the user name (from the system's record of this
    user, so the command finds its own sign-in), a fixed system PATH, a plain language and the pinned switches. Nothing else
    that clark was started with is passed on. `home` and `user` are seams for the tests and the smoke test."""
    my_home, my_user = _me()
    home = my_home if home is None else home
    user = my_user if user is None else user
    env = {"PATH": SAFE_PATH, "LANG": "en_GB.UTF-8"}
    if home and os.path.isabs(home):
        env["HOME"] = home
    if user and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", user):
        env["USER"] = env["LOGNAME"] = user
    env = {k: v for k, v in env.items() if k in KEEP_ENV + ("PATH",)}
    env.update(PINNED_ENV)
    return env


def arguments(path):
    """The command line for one run: the fixed flags, the fixed rules as the system prompt, and nothing the person typed."""
    return [str(path), "--print", "--safe-mode", "--disable-slash-commands", "--tools", "", "--strict-mcp-config",
            "--setting-sources", "", "--no-session-persistence", "--max-turns", "1", "--output-format", "json",
            "--max-budget-usd", MAX_BUDGET_USD, "--system-prompt", ask.RULES]


def roots_for(home=None):
    """The folders the command's file may be in: the person's home folder and Homebrew's."""
    home = _me()[0] if home is None else home
    return tuple(str(Path(r).resolve()) for r in ((home,) if home else ()) + OTHER_ROOTS)


def _inside(path, roots):
    return any(path == Path(r) or Path(r) in path.parents for r in roots)


def _ancestor_problem(folder):
    """True when a folder above `folder` (up to /) could let someone else swap the path: owned by anyone but this user or the
    system, or writable by others without the sticky bit (a sticky folder such as /tmp lets others add names, never move ours)."""
    for up in folder.parents:
        try:
            st = os.stat(str(up))
        except OSError:
            return True
        if st.st_uid not in (0, os.getuid()):
            return True
        if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH) and not st.st_mode & stat.S_ISVTX:
            return True
    return False


def native_problem(real, roots):
    """None when `real` (a resolved absolute path) is a Mac program this user owns that nobody else can change, inside `roots`,
    in a folder nobody else can write to, below folders nobody else can use to swap the path; otherwise True. Reads the first
    four bytes only."""
    try:
        st = os.stat(str(real), follow_symlinks=False)
        folder = os.stat(str(real.parent))
    except OSError:
        return True
    if not stat.S_ISREG(st.st_mode) or not (st.st_mode & stat.S_IXUSR) or st.st_uid != os.getuid():
        return True
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH) or folder.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return True
    if not _inside(real, roots) or _ancestor_problem(real.parent):
        return True
    try:
        fd = os.open(str(real), os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))
        try:
            head = os.read(fd, 4)
        finally:
            os.close(fd)
    except OSError:
        return True
    return None if head in MACH_O else True


def find_command(places=PLACES, roots=None):
    """(the resolved absolute Path of the command, None), or (None, plain reason). The first place that holds anything decides."""
    roots = roots_for() if roots is None else tuple(roots)
    for place in places:
        p = Path(os.path.expanduser(place))
        if not p.is_absolute() or not os.path.lexists(str(p)):
            continue
        try:
            real = p.resolve(strict=True)
        except (OSError, RuntimeError):
            return None, NOT_NATIVE
        if native_problem(real, roots):
            return None, NOT_NATIVE
        return real, None
    return None, NOT_INSTALLED


def listed_flags(text):
    """The option names `--help` lists: only the names at the start of an option's own line count, never a name that appears in
    another option's description."""
    names = set()
    for line in text.splitlines():
        m = OPTION_LINE.match(line)
        if m:
            names.update(re.findall(_FLAG, m.group(1)))
    return names


def hints(environ=None):
    """The plain hints for this computer's set-up, from the environment clark was started with (only names are looked at)."""
    environ = os.environ if environ is None else environ
    out = []
    if any(environ.get(n) for n in PROXY_NAMES):
        out.append(PROXY_HINT)
    if environ.get("CLAUDE_CONFIG_DIR"):
        out.append(CONFIG_HINT)
    if any(environ.get(n) for n in KEY_NAMES):
        out.append(KEY_HINT)
    return out


def read_answer(out):
    """The reply text from the command's JSON output, or None when it isn't one successful result object holding text."""
    try:
        got = json.loads(out.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(got, dict) or got.get("type") != "result" or got.get("subtype") != "success" or got.get("is_error") is not False:
        return None
    text = got.get("result")
    if not isinstance(text, str) or not text.strip():
        return None
    return text


def run(args, data, env, limit, max_out, stop=None):
    """One run of the command (platform.run_stoppable: its own group, its own folders, the environment exactly `env`)."""
    return platform.run_stoppable(args, data, env, limit, max_out, stop=stop, prefix="clark-ask-", tmp_names=TMP_NAMES)


class ClaudeCommand(ask.Provider):
    """The Claude command as an ask.Provider. `places`, `roots`, `env`, `limit` and `max_out` are seams for the tests (a fake
    command); clark itself uses the defaults."""
    provider = PROVIDER

    def __init__(self, places=PLACES, env=None, limit=TIME_LIMIT, max_out=MAX_OUT, check_limit=CHECK_LIMIT, roots=None):
        self.places, self.limit, self.max_out, self.check_limit = tuple(places), limit, max_out, check_limit
        self.roots = roots
        self.env = env if env is not None else child_env()
        self.lock = threading.Lock()           # one run at a time
        self.stop_event = threading.Event()
        self.checked = {}                      # (path, size, mtime, inode, device) -> the version and flag check, once per file
        self.passed = None                     # (path, when) of the last sign-in check status() passed, used once by ask()

    # ----- the checks -----
    def command(self):
        """(path, None) when the command is found, native and passes the version and flag check, else (None, plain reason)."""
        if platform.system() != platform.MAC:           # the fixed places, the process handling and the sign-in are the Mac's
            return None, MAC_ONLY
        path, why = find_command(self.places, self.roots)
        if path is None:
            return None, why
        try:
            st = path.stat()
            key = (str(path), st.st_size, st.st_mtime_ns, st.st_ino, st.st_dev)
        except OSError:
            return None, NOT_INSTALLED
        if key not in self.checked:
            self.checked = {key: self._flags_ok(path)}
        return (path, None) if self.checked[key] else (None, CANT_USE)

    def _flags_ok(self, path):
        status, out, _code = run([str(path), "--version"], b"", self.env, self.check_limit, 4096)
        if status != "ok" or not VERSION.match(out):
            return False
        status, out, _code = run([str(path), "--help"], b"", self.env, self.check_limit, MAX_HELP)
        if status != "ok":
            return False
        return set(NEEDED_FLAGS) <= listed_flags(out.decode("utf-8", "replace"))

    def login_problem(self, path):
        """None when the command reports a Claude sign-in; otherwise the plain reason nothing is sent. Asked before every question."""
        status, out, code = run([str(path), *AUTH_ARGS], b"", self.env, self.check_limit, MAX_AUTH)
        if status not in ("ok", "failed") or code is None:
            return CANT_USE
        try:
            got = json.loads(out.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            return CANT_USE
        if not isinstance(got, dict):
            return CANT_USE
        method = got.get("authMethod")
        if method in KEY_LOGINS:
            return API_KEY_LOGIN
        if code != 0 or got.get("loggedIn") is not True or method == "none":
            return NOT_SIGNED_IN
        return None if method == SIGNED_IN else OTHER_LOGIN

    def usable(self, reuse=False):
        """(path, None) when a question may be sent now, else (None, plain reason). With `reuse`, a sign-in check that status()
        passed for this same file less than LOGIN_REUSE seconds ago stands (once), so a question costs one check, not two."""
        path, why = self.command()
        if path is None:
            return None, why
        passed, self.passed = self.passed, None
        if reuse and passed is not None and passed[0] == path and time.monotonic() - passed[1] < LOGIN_REUSE:
            return path, None
        why = self.login_problem(path)
        return (path, None) if why is None else (None, why)

    def status(self):
        path, why = self.usable()
        self.passed = (path, time.monotonic()) if path is not None else None
        words = " ".join([READY if path is not None else why] + hints())
        return {"connected": path is not None, "why": words}

    # ----- one question -----
    def answer(self, path, text):
        """Send `text` to the command at `path` (already checked) and read its answer: the reply text, or an ask.Failure."""
        status, out, _code = run(arguments(path), text.encode("utf-8"), self.env, self.limit, self.max_out, stop=self.stop_event)
        if status == "stopped":
            return ask.Failure(ask.STOPPED)
        if status == "slow":
            return ask.Failure(TOO_SLOW)
        if status == "too_much":
            return ask.Failure(TOO_LONG_REPLY)
        reply = read_answer(out) if status == "ok" else None
        if reply is None:
            return ask.Failure(" ".join([NO_ANSWER] + hints()))
        return reply

    def ask(self, request):
        if not self.lock.acquire(blocking=False):
            return ask.Failure(BUSY)
        try:
            self.stop_event.clear()
            path, why = self.usable(reuse=True)
            if path is None:
                return ask.Failure(why)
            return self.answer(path, self.envelope(request.text))
        finally:
            self.lock.release()

    def stop(self):
        """Stop the question being answered, if there is one (its whole process group ends). True when one was running."""
        running = self.lock.locked()
        if running:
            self.stop_event.set()
        return running
