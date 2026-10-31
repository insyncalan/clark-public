"""The one provider module: the Claude command on this computer (#47c, commit 5 of the design note). GUARDED-DERIVED: new code
written for clark, not a copy (creaite's environment scrub is unreleased; the isolating flags, standard input, the fixed places,
the version and flag check and the process-group Stop are all new here). Two readers and the owner's own words before it merges.

What it does, and nothing more: it starts the person's own `claude` command, signed in with their own Claude plan, with every
customisation switched off and no tools, gives it the one request text on standard input, and reads the reply from standard
output. clark never sees, keeps or sends a key: the command holds its own sign-in.

The safety steps, each one tested in tests/test_ask_claude.py with a fake command:
- FOUND IN FIXED PLACES ONLY (`PLACES`): an absolute path, never the PATH of whatever started clark, never a shell.
- FAILS CLOSED ON VERSION AND FLAGS: before a run (and in status) `claude --version` must read as a version and `claude --help`
  must list every flag in `NEEDED_FLAGS`; otherwise nothing is sent and the status says to update the command.
- ISOLATED RUN: `--safe-mode` (no CLAUDE.md, memory, skills, plugins, hooks, MCP servers or custom commands),
  `--setting-sources ""` (no settings file is read: the home folder is kept for the sign-in, so without it the person's own
  ~/.claude/settings.json would still apply, and a key helper named there could move a question to a paid key unseen),
  `--disable-slash-commands`, `--tools ""` (no tool at all), `--strict-mcp-config` (no MCP server), `--no-session-persistence`
  (nothing saved under ~/.claude), `--system-prompt` with the fixed rules (the default prompt, which carries the folder, the
  platform and the date, is replaced), a pinned `--output-format text` and a `--max-budget-usd` cap. Never `--bare` (it would
  allow an API key only and never the sign-in), never `--add-dir`, never a file argument.
- SCRUBBED ENVIRONMENT (`child_env`): the child gets an environment built from scratch, holding only `KEEP_ENV` (the home
  folder and user name the sign-in needs, a fixed system PATH, the language), never anything clark was started with: no
  ANTHROPIC_*, CLAUDE_CODE_*, cloud keys, tokens or passwords can reach it, so a run can never move to a paid key by accident
  and never inherits a secret.
- THE REQUEST ON STANDARD INPUT, never in the arguments (a long command line is visible to every local process).
- AN EMPTY WORKING FOLDER of its own, outside clark's data folder, removed afterwards; files it makes are private (umask 077).
- LIMITS: one run at a time, a time limit, a cap on the bytes read back. Stop, the time limit and the cap end the WHOLE process
  group (the command starts helpers), then kill it after a short wait. The process handling itself is platform.run_stoppable
  (only platform.py starts a program).
- NO CONTENT IN LOGS OR ERRORS: no question, passage, reply, path or error text from the command is kept; failures are fixed
  sentences.
"""
import os
import re
import threading
from pathlib import Path

from clark import ask, platform

PROVIDER = "claude"
PLACES = ("~/.local/bin/claude", "~/.claude/local/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude")
NEEDED_FLAGS = ("--print", "--safe-mode", "--setting-sources", "--disable-slash-commands", "--tools", "--strict-mcp-config",
                "--no-session-persistence", "--system-prompt", "--output-format", "--max-budget-usd", "--model")
MODELS = ("opus", "sonnet", "haiku")               # #54: the model names the command takes; a chosen model is one of these only
NEVER_FLAGS = ("--bare", "--add-dir", "--mcp-config", "--settings", "--dangerously-skip-permissions", "--resume", "--continue")
SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
KEEP_ENV = ("HOME", "USER", "LOGNAME", "LANG")      # what the sign-in and the text need; everything else is left out
MAX_BUDGET_USD = "1.00"                             # the command's own cap on one question's spend (counts against the plan)
TIME_LIMIT = 120.0                                  # seconds for one answer
CHECK_LIMIT = 15.0                                  # seconds for --version or --help
MAX_OUT = 4 * ask.MAX_REPLY                         # bytes read back (UTF-8 can be up to four bytes a character)
MAX_HELP = 512 * 1024
VERSION = re.compile(rb"^\s*v?(\d+)\.(\d+)\.(\d+)\b")

NOT_INSTALLED = ("Questions need the Claude command, and it isn't installed on this computer. Install it from claude.com/claude-code, "
                 "sign in once, then ask again. Everything else in the report works as before.")
CANT_USE = "The version of Claude on this computer can't be used safely with clark. Update it, then ask again. Nothing was sent."
READY = "Claude is ready. Your question and the parts of the report it needs are sent to Claude, which Anthropic runs."
NO_ANSWER = ("Claude couldn't answer just now. Try again in a moment. If it keeps happening, open Terminal, type claude, and sign in "
             "when it asks.")
TOO_SLOW = "Claude took too long to answer, so it was stopped. Try a shorter question."
TOO_LONG_REPLY = "Claude's answer was too long to read, so it was stopped. Ask a narrower question."
BUSY = "Another question is being answered. Wait for it, or press Stop."


def child_env(home=None, user=None):
    """The child's whole environment, built from nothing: the home folder and the user name (from this process, so the command
    finds its own sign-in), a fixed system PATH and a plain language. Nothing else that clark was started with is passed on."""
    env = {"PATH": SAFE_PATH, "LANG": "en_GB.UTF-8"}
    home = home if home is not None else os.path.expanduser("~")
    if home and home != "~":
        env["HOME"] = home
    user = user if user is not None else (os.environ.get("USER") or os.environ.get("LOGNAME") or "")
    if user and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", user):
        env["USER"] = env["LOGNAME"] = user
    return {k: v for k, v in env.items() if k in KEEP_ENV + ("PATH",)}


def arguments(path, model=None):
    """The command line for one run: the fixed flags, the chosen model (#54; one of MODELS, else the command's own default), the
    fixed rules as the system prompt, and nothing the person typed."""
    chosen = ["--model", model] if model in MODELS else []
    return [str(path), "--print", "--safe-mode", "--setting-sources", "", "--disable-slash-commands", "--tools", "", "--strict-mcp-config",
            "--no-session-persistence", "--output-format", "text", "--max-budget-usd", MAX_BUDGET_USD, *chosen,
            "--system-prompt", ask.RULES]


def find_command(places=PLACES):
    """The first of the fixed places that is an executable file (a link is followed to its end), as an absolute Path, or None."""
    for place in places:
        p = Path(os.path.expanduser(place))
        if not p.is_absolute():
            continue
        try:
            real = p.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if real.is_file() and os.access(str(real), os.X_OK):
            return p
    return None


def run(args, data, env, limit, max_out, stop=None):
    """One run of the command (platform.run_stoppable: its own group, an empty folder, the environment exactly `env`)."""
    return platform.run_stoppable(args, data, env, limit, max_out, stop=stop, prefix="clark-ask-")


class ClaudeCommand(ask.Provider):
    """The Claude command as an ask.Provider. `places`, `env`, `limit` and `max_out` are seams for the tests (a fake command)."""
    provider = PROVIDER

    def __init__(self, places=PLACES, env=None, limit=TIME_LIMIT, max_out=MAX_OUT, check_limit=CHECK_LIMIT):
        self.places, self.limit, self.max_out, self.check_limit = tuple(places), limit, max_out, check_limit
        self.env = env if env is not None else child_env()
        self.lock = threading.Lock()           # one run at a time
        self.stop_event = threading.Event()
        self.checked = {}                      # (path, size, mtime) -> True or False: the version and flag check, once per file

    # ----- the checks -----
    def usable(self):
        """(path, None) when the command is found and passes the version and flag check, else (None, plain reason)."""
        path = find_command(self.places)
        if path is None:
            return None, NOT_INSTALLED
        try:
            st = path.resolve().stat()
            key = (str(path), st.st_size, st.st_mtime_ns)
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
        text = out.decode("utf-8", "replace")
        return all(re.search(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", text) for flag in NEEDED_FLAGS)

    def status(self):
        path, why = self.usable()
        return {"connected": path is not None, "why": READY if path is not None else why}

    # ----- one question -----
    def ask(self, request, model=None):
        if not self.lock.acquire(blocking=False):
            return ask.Failure(BUSY)
        try:
            self.stop_event.clear()
            path, why = self.usable()
            if path is None:
                return ask.Failure(why)
            data = self.envelope(request.text).encode("utf-8")
            status, out, _code = run(arguments(path, model), data, self.env, self.limit, self.max_out, stop=self.stop_event)
            if status == "stopped":
                return ask.Failure(ask.STOPPED)
            if status == "slow":
                return ask.Failure(TOO_SLOW)
            if status == "too_much":
                return ask.Failure(TOO_LONG_REPLY)
            if status != "ok" or not out.strip():
                return ask.Failure(NO_ANSWER)
            return out.decode("utf-8", "replace")
        finally:
            self.lock.release()

    def stop(self):
        """Stop the question being answered, if there is one (its whole process group ends). True when one was running."""
        running = self.lock.locked()
        if running:
            self.stop_event.set()
        return running
