"""Stopping a launcher-started server when no clark window is left (#71; the logic only, server.py wires it in).

An open clark page says "still here" every 10 seconds (POST /api/here, which needs the token; opening the page counts too).
A server the launcher started (CLARK_LAUNCHED=1) stops once nothing has said so for STOP_AFTER seconds (a minute), and never
while a job is running. A server started by hand, or any server with CLARK_LAUNCHED unset, never stops by itself.

The time is read from a monotonic clock, so a change of the computer's clock never stops the server. (A Mac's monotonic clock
should not run while the computer sleeps, so waking up should not stop it either: a hand check in
docs/handoff/design-71-launcher.md. creaite live_server.watch_for_close, BL-86.)
Standard library only, Python 3.9.
"""
import math
import time

STOP_AFTER = 60.0           # seconds without a "still here" before a launcher-started server stops
STOP_CHECK = 5.0            # how often it looks
HEARTBEAT = 10              # seconds between an open page's "still here" (the page's; kept here so the two stay in step)


def number(environ, name, default):
    """A positive, finite number from the environment (the tests shorten them), else `default` itself."""
    raw = environ.get(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if not math.isfinite(value) or value <= 0:
        return default
    return value


def launched(environ):
    """Whether this server was started by the launcher: only then does it stop by itself."""
    return environ.get("CLARK_LAUNCHED") == "1"


class Idle:
    """When a page last said it was open, and whether that was too long ago."""

    def __init__(self, stop_after=STOP_AFTER, check=STOP_CHECK, clock=time.monotonic, sleep=time.sleep):
        self.stop_after, self.check, self.clock, self.sleep = stop_after, check, clock, sleep
        self.last = clock()                  # the start counts as "here": the window is about to open

    @classmethod
    def from_environ(cls, environ, **kw):
        return cls(number(environ, "CLARK_STOP_AFTER", STOP_AFTER), number(environ, "CLARK_STOP_CHECK", STOP_CHECK), **kw)

    def here(self):
        """A page said it is open (its heartbeat, or the page being opened)."""
        self.last = self.clock()

    def quiet_for(self):
        return self.clock() - self.last

    def due(self, busy=False):
        """True when the server should stop now: quiet for longer than `stop_after`, and no job running."""
        return not busy and self.quiet_for() > self.stop_after

    def watch(self, stop, busy=lambda: False, say=print, keep_going=lambda: True):
        """Look every `check` seconds; when due, say so once and call `stop()`, then return. Run it in a daemon thread.
        `busy()` is true while a job runs: the server waits for it, then stops. `keep_going()` is for tests."""
        while keep_going():
            self.sleep(self.check)
            if self.due(busy()):
                say(f"No clark window has been open for {int(self.stop_after)} seconds, so clark is stopping.")
                stop()
                return
