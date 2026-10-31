"""Settings › AI (#54): the logic of GET /api/ai/status and POST /api/ai/connect, /api/ai/models, /api/ai/choose and
/api/ai/disconnect. Unguarded; server.py only routes to it. The routes, the key store and the calls are providers.py's.

- STATUS: the two provider cards (which way each is connected, the models listed and ticked), the model list (connected providers
  only, recommended marked) and the model in use. It never holds or returns a key: no route does.
- CONNECT {provider, method[, key]}: refused while asking is off (nothing is sent to any provider then). "subscription" checks the
  Claude command on this computer; "key" tests the key with the provider's model-list call and keeps it in the key store only after
  the provider accepted it. A refused key says why in a fixed sentence; neither the key nor the provider's reply is in any answer.
- MODELS {route, models}: the models ask clark may use on that route (ticked from what was listed).
- CHOOSE {choice[, anyway]}: the model ask clark uses. A weaker one than the recommended asks first (409 "weaker"); with
  `anyway: true` it is chosen and the "use it anyway" is remembered, so it is not asked again.
- DISCONNECT {provider}: the key is taken out of the key store; anything set to that provider's models goes back to the
  recommended model.
Every answer is (status, {ok, ...}) with a plain `message`; a refusal also has a stable `code`. Nothing here logs.
"""
import threading

from clark import platform, providers

MESSAGES = {
    "bad_request": "That request could not be read. Nothing was changed. Reload the page and try again.",
    "bad_key": "That doesn't look like a key. Copy the whole key again, paste it, then press Test and connect.",
    "asking_off": "Asking is off, so nothing was sent. Turn on asking first, then connect.",
    "other_method": "That provider is connected the other way already. Disconnect it first, then connect again.",
    "not_connected": "That provider isn't connected. Connect it first.",
    "not_listed": "That model isn't in the list. Choose one from the list.",
    "none_ticked": "Tick at least one model, then save.",
    "key_not_saved": platform.KEY_NOT_SAVED,
    "key_not_removed": platform.KEY_NOT_REMOVED,
    "no_store": "Keys can't be kept on this computer yet, so connect with your Claude subscription instead.",
}
CONNECT_FIELDS = ({"provider", "method"}, {"provider", "method", "key"})
METHODS = {"claude": ("subscription", "key"), "openai": ("key",)}
CONNECT_NOTE = ("When you ask, your question and the passages it needs leave this computer and go to the provider you connect, "
                "billed to that account. Claude and OpenAI are sent the same text in the same way.")


def route_for(provider, method):
    for r in providers.ROUTES:
        if r.provider == provider and r.method == method:
            return r
    return None


class AiService:
    """`ai` is a providers.Ai; `enabled()` reads the ask switch now (off when it can't say)."""

    def __init__(self, ai, enabled):
        self.ai = ai
        self.enabled = enabled
        self.lock = threading.Lock()

    def fail(self, code, message=None):
        return {"ok": False, "code": code, "message": message or MESSAGES[code]}

    # ----- GET /api/ai/status -----
    def body(self, message=None):
        state = self.ai.choices.read()
        connected = self.ai.connected(state)
        cards = []
        for provider, name in providers.PROVIDERS.items():
            on = [r for r in providers.ROUTES if r.provider == provider and r.name in connected]
            card = {"provider": provider, "name": name, "methods": list(METHODS[provider]), "connected": bool(on),
                    "method": on[0].method if on else "", "route": on[0].name if on else "", "models": []}
            if on:
                got = state["routes"][on[0].name]
                listed = got["listed"] or [m for m, _l in providers.COMMAND_MODELS]
                card["models"] = [{"model": m, "label": providers.model_label(on[0].name, m), "ticked": m in got["models"]}
                                  for m in listed]
            cards.append(card)
        out = {"ok": True, "providers": cards, "options": self.ai.options(state), "chosen": self.ai.chosen(state),
               "recommended": self.ai.default_choice(state), "note": CONNECT_NOTE,
               "keys_kept": bool(getattr(self.ai.keys, "built", False))}
        if message:
            out["message"] = message
        return out

    def status(self, *_ignored):
        with self.lock:
            return 200, self.body()

    # ----- POST /api/ai/connect -----
    def connect(self, body):
        if not isinstance(body, dict) or set(body) not in CONNECT_FIELDS:
            return 400, self.fail("bad_request")
        provider, method, key = body.get("provider"), body.get("method"), body.get("key")
        if provider not in METHODS or method not in METHODS[provider] or (method == "key") != ("key" in body):
            return 400, self.fail("bad_request")
        if method == "key" and (not isinstance(key, str) or not platform.KEY_SHAPE.fullmatch(key.strip())):
            return 400, self.fail("bad_key")
        if not self.enabled():
            return 409, self.fail("asking_off")
        route = route_for(provider, method)
        with self.lock:
            state = self.ai.choices.read()
            connected = self.ai.connected(state)
            if any(providers.ROUTE[n].provider == provider and n != route.name for n in connected):
                return 409, self.fail("other_method")
            if method == "subscription":
                st = self.ai.command.status() if self.ai.command is not None else {"connected": False}
                if not (isinstance(st, dict) and st.get("connected") is True):
                    why = st.get("why") if isinstance(st, dict) and isinstance(st.get("why"), str) and st.get("why") else None
                    return 409, self.fail("not_ready", why or providers.NOT_SET_UP)
                listed = [m for m, _l in providers.COMMAND_MODELS]
            else:
                if not getattr(self.ai.keys, "built", False):
                    return 409, self.fail("no_store")
                try:
                    listed = providers.list_models(route, key.strip(), call=self.ai.call)
                except providers.Refused as e:
                    return 409, self.fail("refused", e.message)
                try:
                    self.ai.keys.put(self.ai.service(provider), key.strip())
                except platform.PlatformError:
                    return 409, self.fail("key_not_saved")
            state["routes"][route.name] = {"listed": [] if method == "subscription" else listed, "models": list(listed)}
            self.ai.choices.write(state)
            name = providers.PROVIDERS[provider]
            return 200, self.body(f"{name} is connected. Untick any model ask clark shouldn't use, then save.")

    # ----- POST /api/ai/models -----
    def models(self, body):
        if not isinstance(body, dict) or set(body) != {"route", "models"} or body["route"] not in providers.ROUTE \
                or not isinstance(body["models"], list) or len(body["models"]) > providers.MAX_MODELS:
            return 400, self.fail("bad_request")
        name, ticked = body["route"], body["models"]
        if not all(isinstance(m, str) for m in ticked):
            return 400, self.fail("bad_request")
        with self.lock:
            state = self.ai.choices.read()
            if name not in self.ai.connected(state):
                return 409, self.fail("not_connected")
            listed = state["routes"][name]["listed"] or [m for m, _l in providers.COMMAND_MODELS]
            if any(m not in listed for m in ticked):
                return 409, self.fail("not_listed")
            if not ticked:
                return 409, self.fail("none_ticked")
            state["routes"][name]["models"] = [m for m in listed if m in ticked]
            self.ai.choices.write(state)
            return 200, self.body("Saved.")

    # ----- POST /api/ai/choose -----
    def choose(self, body):
        if not isinstance(body, dict) or not ({"choice"} <= set(body) <= {"choice", "anyway"}) \
                or not isinstance(body["choice"], str) or ("anyway" in body and type(body["anyway"]) is not bool):
            return 400, self.fail("bad_request")
        choice, anyway = body["choice"], body.get("anyway") is True
        with self.lock:
            state = self.ai.choices.read()
            opts = {o["choice"]: o for o in self.ai.options(state)}
            if choice not in opts:
                return 409, self.fail("not_listed")
            o = opts[choice]
            if o["weaker"] and choice not in state["anyway"]:
                if not anyway:
                    best = next((x for x in opts.values() if x["route"] == o["route"] and x["recommended"]), None)
                    better = best["label"] if best else "the recommended model"
                    out = self.fail("weaker", f"{o['label']} is less able than {better}, so its answers may be less accurate. "
                                              "Choose it anyway, or keep the recommended model.")
                    out["choice"] = choice
                    return 409, out
                state["anyway"].append(choice)
            state["chosen"] = choice
            self.ai.choices.write(state)
            return 200, self.body(f"Questions now go to {o['label']}.")

    # ----- POST /api/ai/disconnect -----
    def disconnect(self, body):
        if not isinstance(body, dict) or set(body) != {"provider"} or body["provider"] not in providers.PROVIDERS:
            return 400, self.fail("bad_request")
        provider = body["provider"]
        with self.lock:
            try:
                self.ai.keys.remove(self.ai.service(provider))
            except platform.PlatformError:
                return 409, self.fail("key_not_removed")
            state = self.ai.choices.read()
            had_key = any(r.provider == provider and r.method == "key" and r.name in state["routes"] for r in providers.ROUTES)
            for r in providers.ROUTES:
                if r.provider == provider:
                    state["routes"].pop(r.name, None)
            if state["chosen"] and providers.ROUTE[state["chosen"].split(":", 1)[0]].provider == provider:
                state["chosen"] = ""                 # back to the recommended model of what is still connected
            self.ai.choices.write(state)
            name = providers.PROVIDERS[provider]
            gone = " Its key is gone from this Mac's keychain." if had_key else ""
            return 200, self.body(f"{name} is disconnected.{gone} Connect it again in this section whenever you need it.")
