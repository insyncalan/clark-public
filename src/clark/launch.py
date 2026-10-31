"""python3 -m clark.launch: start clark if it isn't running, then open it in a Chrome app window (#71).

    python3 -m clark.launch [--data FOLDER] [--port N]      (clark.command in clark's folder runs this)

It asks what is on the port first, and never takes over what isn't its own:
- nothing there: it starts clark (python3 -m clark) in the background, marked CLARK_LAUNCHED=1 so that it stops by itself a
  minute after the last clark window closes (idle.py), waits up to 15 seconds for it to answer, and opens the window
- clark with this data folder: it is already running; only the window is opened
- clark with another data folder, or any other program (creaite also answers /health, without the mark): said in plain words,
  nothing started, nothing opened

The window is Chrome's app window (--app=<address>); if Chrome isn't found, the default browser, and it says so. The logic is
here and every system call is in platform.py, so a test runs it with fakes and a fake server. Copied from creaite v2.6.9
system/scripts/launch.py (BL-86, BL-212), cut down: no make-launcher, login agent, restart or starting-file. Standard library
only, Python 3.9.
"""
import argparse
import http.client
import json
import os
import sys
import time
from pathlib import Path

from clark import appfiles, platform, server
from clark.__main__ import Usage, free_port_near, port_free, port_number

NOTHING, OURS, OTHER_DATA, NOT_CLARK = "nothing", "ours", "other data folder", "not clark"
START_WAIT = 15.0               # seconds to wait for a started clark to answer
POLL = 0.1
ASK_TIMEOUT = 1.0
HEALTH_BYTES = 4096             # the most of an answer that is read
SRC = Path(__file__).resolve().parents[1]
LOG_NAME = "server.log"         # in the data folder
DB_NAME = "clark.db"


def ask_health(port, mark, timeout=ASK_TIMEOUT, connect=http.client.HTTPConnection):
    """What is on `port` of 127.0.0.1, by asking /health with the data folder's mark: NOTHING (the connection is refused), OURS
    (clark, with the same data folder), OTHER_DATA (clark, another data folder) or NOT_CLARK (anything else that answers, or
    holds the port and doesn't answer in time, or says something that isn't clark's answer). Only clark's answer to the mark
    has a boolean "this_data": creaite answers {"ok": true} and so counts as not clark. No proxy is used."""
    conn = connect("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", "/health", headers={appfiles.MARK_HEADER: mark})
        reply = conn.getresponse()
        raw = reply.read(HEALTH_BYTES + 1)
        status = reply.status
    except ConnectionRefusedError:
        return NOTHING
    except (OSError, http.client.HTTPException):
        return NOT_CLARK
    finally:
        conn.close()
    try:
        answer = json.loads(raw) if status == 200 and len(raw) <= HEALTH_BYTES else None
    except ValueError:
        answer = None
    if not isinstance(answer, dict) or answer.get("ok") is not True or not isinstance(answer.get("this_data"), bool):
        return NOT_CLARK
    return OURS if answer["this_data"] else OTHER_DATA


def address(port):
    """Where clark's window opens. Always 127.0.0.1: Chrome offers to install an app only from a loopback address."""
    return f"http://127.0.0.1:{port}/"


def launcher_file():
    """The file a person double-clicks to start clark, or None off a Mac (where the name is not known)."""
    try:
        return platform.launcher_name()
    except platform.NotBuiltYet:
        return None


def try_another(port, free=port_free):
    """A second line for a person who can't close the other program: the command with a free number, or "" if none is near."""
    other = free_port_near(port, free)
    name = launcher_file()
    return (f"\nIf you can't close it, open Terminal in the clark folder and type: ./{name} --port {other}"
            if other and name else "")      # off a Mac there is no launcher file to type


def report(kind, port, folder, free=port_free):
    """The plain line for a port that isn't ours."""
    if kind == OTHER_DATA:
        return (f"Another copy of clark is already open with different data (this one uses {platform.with_tilde(folder)}). "
                f"Close that copy, then start clark again.{try_another(port, free)}")
    launcher = launcher_file() or "the clark launcher"          # the launcher file is the Mac's: general words elsewhere
    return ("Nothing was started: clark is already open in another Terminal window, or another program is using the connection it needs. "
            f"Close that Terminal window or program, then double-click {launcher} again. If that does not help, restart your Mac.{try_another(port, free)}")


def wait_for_clark(port, mark, process, seconds=START_WAIT, health=ask_health, sleep=time.sleep, clock=time.monotonic):
    """Wait for the clark we started to answer with our data folder: what /health says at the end of the wait, or as soon as
    it answers or the process has gone (and one last look then: a second launch that won the port counts)."""
    end = clock() + seconds
    while True:
        seen = health(port, mark)
        if seen != NOTHING or clock() >= end:
            return seen
        if process.poll() is not None:
            return health(port, mark)
        sleep(POLL)


def launch(port, folder, say=print, environ=None, start=platform.start_detached, find_chrome=platform.find_chrome,
           open_window=platform.open_app_window, open_browser=platform.open_url, health=ask_health, wait=wait_for_clark,
           free=port_free):
    """Start clark if nothing answers on `port`, then open its window. The exit code: 0 opened, 1 not (the reason is said)."""
    environ = os.environ if environ is None else environ
    folder = Path(folder)
    mark = appfiles.data_mark(folder)
    seen = health(port, mark)
    if seen in (OTHER_DATA, NOT_CLARK):
        say(report(seen, port, folder, free))
        return 1
    if seen == OURS:
        say("It is already running. Opening its window.")
    else:
        say("Starting clark...")
        log = folder / LOG_NAME
        env = {**environ, "CLARK_LAUNCHED": "1", "CLARK_PORT": str(port), "PYTHONPATH": str(SRC)}
        try:
            process = start([sys.executable, "-m", "clark", "--data", str(folder), "--port", str(port)], env, log, cwd=str(folder))
        except platform.PlatformError as e:
            say(str(e))
            return 1
        seen = wait(port, mark, process, health=health)
        if seen != OURS:
            if seen in (OTHER_DATA, NOT_CLARK):
                say(report(seen, port, folder, free))
            else:
                say("It didn't start. Close this window and try again. If it still doesn't start, send the file "
                    f"{platform.with_tilde(log)} to the clark team.")
            return 1
        say("A minute after the last window closes, clark stops by itself.")
    return open_clark(address(port), say, environ, find_chrome, open_window, open_browser)


def open_clark(url, say, environ, find_chrome, open_window, open_browser):
    """Open `url` in a Chrome app window; the default browser, with a line saying so, if Chrome isn't found."""
    chrome = find_chrome(environ)
    try:
        if chrome:
            open_window(url, chrome)
            say("Opened clark in its own window.")
        else:
            open_browser(url)
            say("Chrome wasn't found, so clark opened in your default browser. Install Chrome to give clark its own window.")
    except platform.PlatformError as e:
        say(f"{e} Open this address in your browser: {url}")
        return 1
    return 0


def parser():
    p = argparse.ArgumentParser(prog="python3 -m clark.launch", description="Start clark if it isn't running, and open its window.")
    p.add_argument("--data", metavar="FOLDER", help="the folder for clark's data (default: clark's own folder for your system)")
    p.add_argument("--port", metavar="N", help=f"the port number clark listens on (advanced; default: the CLARK_PORT setting, or {server.DEFAULT_PORT})")
    return p


def main(argv=None, say=print, environ=None, home=None, onedrive_roots=None, **seams):
    """The command. `seams` are launch()'s fakes (start, health, find_chrome, ...)."""
    environ = os.environ if environ is None else environ
    args = parser().parse_args(argv)
    want = None
    try:
        port = port_number(args.port if args.port is not None else (environ.get("CLARK_PORT") or server.DEFAULT_PORT),
                           "--port" if args.port is not None else "CLARK_PORT")
        want = Path(args.data).expanduser() if args.data else platform.data_dir(home)
        folder = platform.check_data_dir(want, onedrive_roots)
        folder.mkdir(parents=True, exist_ok=True)           # the log goes here; clark itself makes the database on first run
    except Usage as e:
        say(str(e))
        return 2
    except platform.PlatformError as e:
        say(str(e))
        return 1
    except OSError as e:
        say(f"The data folder can't be made ({platform.with_tilde(want)}). Check you can save files there, then try again.")
        return 1
    return launch(port, folder, say, environ, **seams)


if __name__ == "__main__":
    sys.exit(main())
