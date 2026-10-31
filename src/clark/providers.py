"""AI sign-in for ask clark (#54): the routes to a model, the model list, the direct HTTPS caller, routing, limits and the fakes.

NEW CODE, CLEAN-ROOM. creaite's providers.py (#132) is not released yet (#53), so nothing here is copied from it; the owner approves the
exact code. It touches secrets: two readers before it merges.

THE ROUTES (`ROUTES`, in order; the first is the one clark had before #54):
- `claude-command`: the person's own Claude command and Claude plan (ask_claude.ClaudeCommand). clark never holds a key for it.
- `claude-api`: a Claude API key, in one HTTPS call to api.anthropic.com/v1/messages.
- `openai-api`: an OpenAI API key, in one HTTPS call to api.openai.com/v1/chat/completions with `store: false`.
ChatGPT sign-in waits on the spike (#52); it is not a route here. One route per provider is connected at a time.

THE SAME ASK CLARK ON EVERY ROUTE (FR-67). Every route sends ask.RULES as the system text and `Request.text` (ask.build_request,
the one builder) as the one user message, and asks for no tools. What differs is the envelope only (`envelope_for`).

THE KEY. A key lives in the key store only (platform.key_store(): the Mac Keychain), as service `clark.ai.<data folder id>.<provider>`,
account `clark`. It is read from there for one call and never kept on an object, written to a file, logged, put in an error, returned
by a route or shown. It goes in one header only (`x-api-key` or `Authorization`). A direct route is used only after the person
pressed Connect: no key in the store, no call.

EVERY OUTGOING CALL (`https_call`, the one place clark opens a network connection to another computer): https only, an exact host
from `HOSTS`, TLS 1.2 or later verified with the system's default certificates (`ssl.create_default_context`), an opener built from
nothing (no proxy handler, so no proxy from the environment; a redirect handler that refuses every redirect; no file, ftp or data
handler), a time limit per step, a cap on the bytes sent, the bytes read and the reply tokens. A source test fails if any other
module imports urllib.request, http.client, socket or ssl (two local-only exceptions are named there).

ERRORS are fixed sentences (`words`): the provider's name, at most a status number, and the next step. Never the key, the reply body or
an exception's text.

LIMITS (FR-66). HTTP 429 (or the provider's own limit error) comes back as `Limited`, a failure that carries an offer: the other
connected provider's recommended model, or a smaller model on the same route. Nothing ever switches by itself: the person chooses.

THE FAKES. `CLARK_FAKE_PROVIDERS=1` is honoured only when the data folder is inside the system's temporary folder, or the source tree
has the `.clark-dev` marker (`fakes_allowed`). The fakes hold no real key and open no connection.
"""
import hashlib
import json
import os
import re
import ssl
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from clark import ask, platform

PROVIDERS = {"claude": "Claude", "openai": "OpenAI"}
HOSTS = ("api.anthropic.com", "api.openai.com")
ANTHROPIC_VERSION = "2023-06-01"


@dataclass(frozen=True)
class Route:
    name: str            # "claude-command", "claude-api", "openai-api"
    provider: str        # "claude" or "openai"
    method: str          # "subscription" or "key"
    host: str = ""
    list_path: str = ""
    call_path: str = ""


ROUTES = (
    Route("claude-command", "claude", "subscription"),
    Route("claude-api", "claude", "key", "api.anthropic.com", "/v1/models?limit=100", "/v1/messages"),
    Route("openai-api", "openai", "key", "api.openai.com", "/v1/models", "/v1/chat/completions"),
)
ROUTE = {r.name: r for r in ROUTES}

# The Claude command takes these model names; the strongest is recommended. (A key route's models come from its model-list call.)
COMMAND_MODELS = (("opus", "Claude Opus"), ("sonnet", "Claude Sonnet"), ("haiku", "Claude Haiku"))

TIME_LIMIT = 60.0                  # seconds for one network step (connect, send or read)
LIST_TIME_LIMIT = 15.0
MAX_SEND = 300 * 1024              # bytes in one request body (ask.MAX_REQUEST characters, as UTF-8, with the envelope)
MAX_READ = 2 * 1024 * 1024         # bytes read back from one call
MAX_LIST_READ = 1024 * 1024
MAX_ERROR_READ = 16 * 1024         # bytes of an error reply read, only to tell a limit from another refusal; never shown or kept
MAX_REPLY_TOKENS = 4000            # the model's reply, in tokens
MAX_MODELS = 30                    # models listed for one route
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
CHOICE = re.compile(r"(claude-command|claude-api|openai-api):([A-Za-z0-9][A-Za-z0-9._-]{0,79})")

NOT_SET_UP = "Asking isn't set up yet. Connect Claude or OpenAI in Settings, under AI, then ask again."
FAKE_ENV = "CLARK_FAKE_PROVIDERS"
DEV_MARKER = ".clark-dev"


# ----- names -----
def service_name(data_dir, provider):
    """The keychain service for `provider`'s key: clark.ai.<16 hex of the data folder's full path>.<provider>."""
    if provider not in PROVIDERS:
        raise ValueError("not a provider")
    folder = str(Path(data_dir).expanduser().resolve())
    return f"clark.ai.{hashlib.sha256(folder.encode('utf-8')).hexdigest()[:16]}.{provider}"


def rank(provider, model):
    """How strong a model is, from its name only (3 strongest). Used to mark the recommended one and to ask before a weaker one."""
    m = model.lower()
    if provider == "claude":
        return 3 if "opus" in m else 2 if "sonnet" in m else 1 if "haiku" in m else 0
    if "nano" in m:
        return 1
    if "mini" in m:
        return 2
    return 3 if m.startswith("gpt-") else 0


def model_label(route, model):
    if route == "claude-command":
        return dict(COMMAND_MODELS).get(model, model)
    return model


def usable_model(provider, model):
    """Whether a listed model is one ask clark can use: a chat model of that provider, by its name."""
    if not isinstance(model, str) or not MODEL_ID.fullmatch(model):
        return False
    m = model.lower()
    if provider == "claude":
        return m.startswith("claude-")
    return m.startswith("gpt-") and not any(w in m for w in ("audio", "realtime", "image", "transcribe", "tts", "search", "embedding"))


def recommended(provider, models):
    """The recommended model among `models`: the strongest by `rank`, the first listed of those (lists come newest first)."""
    best = None
    for m in models:
        if best is None or rank(provider, m) > rank(provider, best):
            best = m
    return best


# ----- words -----
def words(provider, what, status=None):
    """The fixed sentence for a failure. Never the key, the reply body or an exception's text."""
    name = PROVIDERS.get(provider, "The provider")
    if what == "refused_key":
        return f"{name} did not accept this key ({status}). Check you copied all of it and that it is still active, then try again."
    if what == "unreachable":
        return f"Couldn't reach {name}. Check this computer's internet connection, then try again."
    if what == "limit":
        return f"{name} says a limit has been reached. Choose another model below, or wait and ask again later."
    if what == "no_models":
        return f"{name} accepted the key but listed no model ask clark can use. Check the account, then try again."
    if what == "too_long":
        return "That needs too much text to send. Ask a narrower question."
    if what == "too_much":
        return f"{name}'s answer was too long to read, so it was left out. Ask a narrower question."
    if what == "unreadable":
        return f"{name}'s answer could not be read. Try again in a moment."
    status_part = f" ({status})" if isinstance(status, int) else ""
    return f"{name} couldn't answer just now{status_part}. Try again in a moment."


# ----- the one outgoing call -----
class Unreachable(Exception):
    """No answer from the host (no connection, TLS refused, a time limit, a redirect, or a reply over the cap). No text is kept."""


class TooMuch(Exception):
    """The reply was bigger than the cap."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Every redirect is refused: the 3xx answer comes back as an error and is never followed, to any host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def tls_context():
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def opener():
    """An opener built from nothing: HTTPS only (verified, TLS 1.2+), no proxy handler, every redirect refused."""
    od = urllib.request.OpenerDirector()
    for handler in (urllib.request.HTTPSHandler(context=tls_context()), _NoRedirect(), urllib.request.HTTPDefaultErrorHandler(),
                    urllib.request.HTTPErrorProcessor()):
        od.add_handler(handler)
    return od


def check_target(host, path):
    """The address for one call, only to an exact host in HOSTS and a fixed path; anything else raises ValueError."""
    if host not in HOSTS or not isinstance(path, str) or not path.startswith("/v1/") or any(c in path for c in "@\\# \r\n"):
        raise ValueError("not an allowed address")
    return f"https://{host}{path}"


def https_call(method, host, path, headers, body, timeout, max_read, open_with=None):
    """One HTTPS call. Returns (status, body bytes) for any HTTP answer (an error status too, its body capped at MAX_ERROR_READ);
    raises Unreachable when there is no usable answer and TooMuch when the reply is over `max_read`. `open_with` is a seam for
    tests (an opener's `open`); the real one is never used by a test."""
    url = check_target(host, path)
    if body is not None and len(body) > MAX_SEND:
        raise ValueError("too much to send")
    req = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
    do_open = open_with or opener().open
    try:
        resp = do_open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            code = int(e.code)
            if 300 <= code < 400:
                raise Unreachable() from None            # a redirect: never followed
            return code, e.read(MAX_ERROR_READ)
        except Unreachable:
            raise
        except Exception:  # noqa: BLE001
            return int(getattr(e, "code", 0) or 0), b""
        finally:
            try:
                e.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001  urllib.error.URLError, ssl, socket and time limits: no text is kept
        raise Unreachable() from None
    try:
        data = resp.read(max_read + 1)
        code = int(getattr(resp, "status", 200))
    except Exception:  # noqa: BLE001
        raise Unreachable() from None
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass
    if len(data) > max_read:
        raise TooMuch()
    return code, data


def key_headers(route, key):
    """The headers of one call: the key in exactly one of them."""
    if route.provider == "claude":
        return {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION, "Content-Type": "application/json",
                "Accept": "application/json"}
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json"}


def envelope_for(route, model, text):
    """The JSON body of one question on a key route: the fixed rules as the system text, `text` as the one user message, no tools."""
    if route.provider == "claude":
        return {"model": model, "max_tokens": MAX_REPLY_TOKENS, "system": ask.RULES,
                "messages": [{"role": "user", "content": text}]}
    return {"model": model, "store": False, "max_completion_tokens": MAX_REPLY_TOKENS,
            "messages": [{"role": "system", "content": ask.RULES}, {"role": "user", "content": text}]}


def _is_limit(route, status, raw):
    if status == 429:
        return True
    try:
        err = json.loads(raw.decode("utf-8")).get("error") or {}
    except Exception:  # noqa: BLE001
        return False
    kind = str(err.get("type") or err.get("code") or "") if isinstance(err, dict) else ""
    return kind in ("rate_limit_error", "insufficient_quota", "rate_limit_exceeded")


@dataclass(frozen=True)
class Limited(ask.Failure):
    """A limit was reached. `offer` is a tuple of {"choice", "label"} the person may switch to; nothing is switched for them."""
    offer: tuple = ()


class Refused(Exception):
    """A key route's answer that is not a model list or a reply. `message` is a fixed sentence (`words`)."""

    def __init__(self, message, limit=False):
        super().__init__(message)
        self.message, self.limit = message, limit


def list_models(route, key, call=https_call):
    """The models a key may use on `route`, newest first as the provider lists them, or raises Refused with a fixed sentence."""
    try:
        status, raw = call("GET", route.host, route.list_path, key_headers(route, key), None, LIST_TIME_LIMIT, MAX_LIST_READ)
    except (Unreachable, TooMuch):
        raise Refused(words(route.provider, "unreachable")) from None
    if status in (401, 403):
        raise Refused(words(route.provider, "refused_key", status))
    if status != 200:
        limit = _is_limit(route, status, raw)
        raise Refused(words(route.provider, "limit" if limit else "failed", status), limit=limit)
    try:
        data = json.loads(raw.decode("utf-8")).get("data")
        ids = [m.get("id") for m in data if isinstance(m, dict)]
    except Exception:  # noqa: BLE001
        raise Refused(words(route.provider, "unreadable")) from None
    out = []
    for m in ids:
        if usable_model(route.provider, m) and m not in out:
            out.append(m)
    if not out:
        raise Refused(words(route.provider, "no_models"))
    return out[:MAX_MODELS]


def send(route, key, model, text, call=https_call):
    """One question on a key route: the reply text, or raises Refused with a fixed sentence."""
    body = json.dumps(envelope_for(route, model, text), ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_SEND:
        raise Refused(words(route.provider, "too_long"))
    try:
        status, raw = call("POST", route.host, route.call_path, key_headers(route, key), body, TIME_LIMIT, MAX_READ)
    except TooMuch:
        raise Refused(words(route.provider, "too_much")) from None
    except Unreachable:
        raise Refused(words(route.provider, "unreachable")) from None
    if status in (401, 403):
        raise Refused(words(route.provider, "refused_key", status))
    if status != 200:
        limit = _is_limit(route, status, raw)
        raise Refused(words(route.provider, "limit" if limit else "failed", status), limit=limit)
    try:
        got = json.loads(raw.decode("utf-8"))
        if route.provider == "claude":
            text = "".join(b.get("text", "") for b in got.get("content", []) if isinstance(b, dict) and b.get("type") == "text")
        else:
            text = got["choices"][0]["message"]["content"]
    except Exception:  # noqa: BLE001
        raise Refused(words(route.provider, "unreadable")) from None
    if not isinstance(text, str) or not text.strip():
        raise Refused(words(route.provider, "unreadable"))
    return text


# ----- the choices (never a key) -----
CHOICES_FILE = "ai.json"


class Choices:
    """What the person chose, in ai.json in the data folder: for each connected route its ticked models (and, for a key route, the
    models the provider listed), the chosen model, and the weaker choices they said to use anyway. Never a key. (The database's
    settings rows wait on a schema step; this file is the stand-in.)"""

    def __init__(self, data_dir):
        self.path = Path(data_dir) / CHOICES_FILE
        self.lock = threading.Lock()

    def read(self):
        try:
            got = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            # Never chosen: the Claude command stays connected as it was before #54 (v0.3 asked through it with no Connect step).
            return {"routes": {"claude-command": {"listed": [], "models": [m for m, _l in COMMAND_MODELS]}}, "chosen": "",
                    "anyway": []}
        except (OSError, ValueError):
            got = {}
        routes = got.get("routes") if isinstance(got, dict) else None
        out = {"routes": {}, "chosen": "", "anyway": []}
        if isinstance(routes, dict):
            for name, r in routes.items():
                if name in ROUTE and isinstance(r, dict):
                    listed = [m for m in r.get("listed", []) if isinstance(m, str) and MODEL_ID.fullmatch(m)][:MAX_MODELS]
                    ticked = [m for m in r.get("models", []) if isinstance(m, str) and MODEL_ID.fullmatch(m)][:MAX_MODELS]
                    out["routes"][name] = {"listed": listed, "models": ticked}
        if isinstance(got, dict) and isinstance(got.get("chosen"), str) and CHOICE.fullmatch(got["chosen"]):
            out["chosen"] = got["chosen"]
        if isinstance(got, dict) and isinstance(got.get("anyway"), list):
            out["anyway"] = [c for c in got["anyway"] if isinstance(c, str) and CHOICE.fullmatch(c)][:50]
        return out

    def write(self, state):
        platform.write_file(self.path, json.dumps(state, indent=1, sort_keys=True) + "\n")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass


# ----- the fakes (tests only) -----
def fakes_allowed(data_dir, environ=None, source_root=None):
    """True only when CLARK_FAKE_PROVIDERS=1 and the data folder is inside the system's temporary folder, or the source tree has the
    development marker. A real data folder never gets the fakes, whatever the environment says."""
    environ = os.environ if environ is None else environ
    if environ.get(FAKE_ENV) != "1":
        return False
    root = Path(source_root) if source_root else Path(__file__).resolve().parents[2]
    if (root / DEV_MARKER).is_file():
        return True
    try:
        folder = Path(data_dir).resolve()
        temp = Path(tempfile.gettempdir()).resolve()
    except OSError:
        return False
    return folder == temp or temp in folder.parents


class FakeKeyStore(platform.KeyStore):
    """A key store in memory. Every key a test gives it must end TESTONLY."""
    built = True

    def __init__(self):
        self.items = {}

    def has(self, service):
        return service in self.items

    def put(self, service, key):
        if not isinstance(key, str) or not key.endswith("TESTONLY") or not platform.KEY_SHAPE.fullmatch(key):
            raise platform.PlatformError(platform.KEY_NOT_SAVED)
        self.items[service] = key

    def remove(self, service):
        self.items.pop(service, None)
        return True

    def peek(self, service):
        return self.items.get(service)


class FakeTransport:
    """Stands in for https_call: records each call (the method, host, path, header names and body) and answers from `answers`, a
    dict of (method, host) -> (status, body bytes) or an exception to raise. The key a call carried is kept apart in `keys`, so a
    test can check it went in one header only."""

    def __init__(self, answers=None):
        self.calls, self.keys = [], []
        self.answers = dict(answers or {})

    def __call__(self, method, host, path, headers, body, timeout, max_read):
        check_target(host, path)
        self.calls.append({"method": method, "host": host, "path": path, "headers": dict(headers), "body": body,
                           "timeout": timeout, "max_read": max_read})
        got = self.answers.get((method, host))
        if got is None:
            if method == "GET":
                ids = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"] if host == "api.anthropic.com" \
                    else ["gpt-5", "gpt-5-mini", "gpt-5-nano"]
                return 200, json.dumps({"data": [{"id": i} for i in ids]}).encode("utf-8")
            if host == "api.anthropic.com":
                return 200, json.dumps({"content": [{"type": "text", "text": "A fake answer."}]}).encode("utf-8")
            return 200, json.dumps({"choices": [{"message": {"content": "A fake answer."}}]}).encode("utf-8")
        if isinstance(got, BaseException):
            raise got
        return got


class FakeCommand(ask.Provider):
    """The Claude command, faked: ready (or not), answers with fixed text, records the model it was given."""
    provider = "claude"

    def __init__(self, ready=True, reply="A fake answer.", failure=None):
        self.ready, self.reply, self.failure, self.models, self.sent = ready, reply, failure, [], []

    def status(self):
        return {"connected": bool(self.ready), "why": "" if self.ready else "The Claude command isn't installed on this computer."}

    def ask(self, request, model=None):
        self.models.append(model)
        self.sent.append(self.envelope(request.text))
        return ask.Failure(self.failure) if self.failure else self.reply

    def stop(self):
        return False


# ----- the routing: the one ask.Provider the ask service holds -----
class Ai:
    """The connected routes, the choices and the key store, for one data folder. `command` is the Claude command (ask_claude.
    ClaudeCommand, or a fake); `keys` a platform.KeyStore; `call` the outgoing call (https_call, or a FakeTransport)."""

    def __init__(self, data_dir, command, keys, call=https_call):
        self.data_dir = Path(data_dir)
        self.command, self.keys, self.call = command, keys, call
        self.choices = Choices(self.data_dir)

    def service(self, provider):
        return service_name(self.data_dir, provider)

    def connected(self, state=None):
        """The connected routes in ROUTES order, as {route name: ticked models}. A key route counts only while its key is in the
        store (a key removed in Keychain Access disconnects it)."""
        state = state or self.choices.read()
        out = {}
        for r in ROUTES:
            got = state["routes"].get(r.name)
            if not got or not got["models"]:
                continue
            if r.method == "key" and not self.keys.has(self.service(r.provider)):
                continue
            out[r.name] = list(got["models"])
        return out

    def options(self, state=None):
        """The model list: connected routes only, each model as {choice, route, provider, label, recommended, weaker}."""
        state = state or self.choices.read()
        out = []
        for name, models in self.connected(state).items():
            r = ROUTE[name]
            best = recommended(r.provider, models)
            for m in models:
                out.append({"choice": f"{name}:{m}", "route": name, "provider": r.provider,
                            "label": model_label(name, m), "recommended": m == best,
                            "weaker": rank(r.provider, m) < rank(r.provider, best)})
        return out

    def default_choice(self, state=None):
        """The recommended model of the first connected route, or "" when nothing is connected."""
        for o in self.options(state):
            if o["recommended"]:
                return o["choice"]
        return ""

    def chosen(self, state=None):
        """The model ask clark uses: the saved choice while it is still in the list, else the recommended one."""
        state = state or self.choices.read()
        opts = {o["choice"] for o in self.options(state)}
        return state["chosen"] if state["chosen"] in opts else self.default_choice(state)

    def offer_for(self, choice, state=None):
        """What a limit offers instead of `choice`: the recommended model of each other connected provider, then the smaller models
        on the same route. Never switched to by itself."""
        state = state or self.choices.read()
        route = choice.split(":", 1)[0]
        here = ROUTE[route].provider if route in ROUTE else ""
        opts = self.options(state)
        other = [o for o in opts if o["provider"] != here and o["recommended"]]
        cur = next((o for o in opts if o["choice"] == choice), None)
        smaller = [o for o in opts if cur and o["route"] == route and o["choice"] != choice
                   and rank(o["provider"], o["choice"].split(":", 1)[1]) < rank(cur["provider"], choice.split(":", 1)[1])]
        return tuple({"choice": o["choice"], "label": o["label"]} for o in other + smaller)


class RoutedProvider(ask.Provider):
    """The one ask.Provider ask clark holds (#54): it sends the request to the chosen model's route. With nothing connected it is
    not ready and says where to connect."""
    provider = "routed"

    def __init__(self, ai):
        self.ai = ai

    def status(self):
        choice = self.ai.chosen()
        if not choice:
            return {"connected": False, "why": NOT_SET_UP}
        route = ROUTE[choice.split(":", 1)[0]]
        if route.name == "claude-command":
            return ask.answer_status(self.ai.command)
        return {"connected": True, "why": f"Your question and the passages it needs go to {PROVIDERS[route.provider]}."}

    def ask(self, request):
        state = self.ai.choices.read()
        choice = self.ai.chosen(state)
        if not choice:
            return ask.Failure(NOT_SET_UP)
        name, model = choice.split(":", 1)
        route = ROUTE[name]
        if route.name == "claude-command":
            got = self.ai.command.ask(request, model=model)
            return got
        key = self.ai.keys.peek(self.ai.service(route.provider))
        if not key:
            return ask.Failure(NOT_SET_UP)
        try:
            return send(route, key, model, request.text, call=self.ai.call)
        except Refused as e:
            if e.limit:
                return Limited(e.message, self.ai.offer_for(choice, state))
            return ask.Failure(e.message)

    def stop(self):
        stop = getattr(self.ai.command, "stop", None)
        return bool(stop()) if callable(stop) else False


def build(data_dir, command, environ=None):
    """The Ai for this data folder: the real key store and caller, or the fakes when `fakes_allowed`."""
    if fakes_allowed(data_dir, environ):
        return Ai(data_dir, FakeCommand(), FakeKeyStore(), FakeTransport())
    return Ai(data_dir, command, platform.key_store())
