"""#54: Settings › AI routes (GET /api/ai/status, POST /api/ai/connect, /models, /choose, /disconnect; ai_service.py, routed by
server.py) and ask clark through the chosen route, against a real server and a real store, with FAKES only.

Run: python3 dev/run_tests.py test_ai_route
No real keychain and no network: the key store is providers.FakeKeyStore, the outgoing call providers.FakeTransport and the Claude
command providers.FakeCommand. Every key ends TESTONLY. The canary test runs one key through enter, test, call, error and remove and
then looks for it in clark.db, the choices file, every file in the data folder, the log, every answer, the process list and the repo.
Fictional data only.
"""
import json
import logging
import os
import secrets
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _paths import ROOT, SRC  # noqa: F401
import _publish_fixture as plant
from test_ask_route import Running
from clark import ai_service, ask_service, providers, store as st

CODE = "PUB"


def canary():
    return "sk-proj-" + secrets.token_hex(16) + "TESTONLY"


class Base(unittest.TestCase):
    def setUp(self):
        self.d = Path(os.path.realpath(tempfile.mkdtemp(prefix="clark-test-")))
        self.addCleanup(shutil.rmtree, self.d, True)
        self.db = plant.build_db(self.d / "clark.db")
        self.keys, self.fake, self.command = providers.FakeKeyStore(), providers.FakeTransport(), providers.FakeCommand()
        self.ai = providers.Ai(self.d, self.command, self.keys, self.fake)
        self.asking = ask_service.AskService(self.db, providers.RoutedProvider(self.ai), [])
        self.service = ai_service.AiService(self.ai, self.asking.enabled)
        self.s = Running()
        self.s.httpd.ask, self.s.httpd.ai = self.asking, self.service
        self.addCleanup(self.s.close)
        self.answers = []

    def api(self, method, path, body=None):
        status, got = self.s.api(method, path, body)
        self.answers.append(json.dumps(got))
        return status, got

    def set_switch(self, on):
        store = st.open_store(self.db, onedrive_roots=[])
        try:
            with store.step("dashboard", "tester", place="menu") as s:
                s.update("app_settings", "1", {"ask_enabled": on})
        finally:
            store.close()

    def connect(self, provider="openai", key=None, method="key"):
        body = {"provider": provider, "method": method}
        if method == "key":
            body["key"] = key or canary()
        return self.api("POST", "/api/ai/connect", body)

    def question(self, q="What is the state of the plan?"):
        return self.api("POST", "/api/ask", {"project": CODE, "question": q})

    def network_calls(self):
        return [c for c in self.fake.calls]


class Cards(Base):
    def test_two_cards_claude_by_subscription_or_key_openai_by_key_and_no_chatgpt_yet(self):
        status, got = self.api("GET", "/api/ai/status")
        self.assertEqual(status, 200)
        cards = {c["provider"]: c for c in got["providers"]}
        self.assertEqual(cards["claude"]["methods"], ["subscription", "key"])
        self.assertEqual(cards["openai"]["methods"], ["key"])
        self.assertTrue(cards["claude"]["connected"])            # the Claude command, as before #54
        self.assertFalse(cards["openai"]["connected"])
        self.assertEqual({o["provider"] for o in got["options"]}, {"claude"})        # connected providers only
        self.assertEqual(got["chosen"], "claude-command:opus")
        self.assertTrue(next(o for o in got["options"] if o["choice"] == got["chosen"])["recommended"])

    def test_the_connect_note_pins_where_passages_go(self):
        _s, got = self.api("GET", "/api/ai/status")
        self.assertEqual(got["note"], "When you ask, your question and the passages it needs leave this computer and go to the "
                                      "provider you connect, billed to that account. Claude and OpenAI are sent the same text in "
                                      "the same way.")

    def test_a_route_with_no_service_is_not_found(self):
        self.s.httpd.ai = None
        status, _got = self.s.api("GET", "/api/ai/status")
        self.assertEqual(status, 404)

    def test_the_token_is_checked_first(self):
        status, _got = self.s.api("POST", "/api/ai/connect", {"provider": "openai", "method": "key", "key": canary()}, token="x")
        self.assertEqual(status, 403)
        self.assertEqual(self.fake.calls, [])


class Connect(Base):
    def test_a_key_is_tested_with_the_model_list_then_kept_in_the_key_store_only(self):
        key = canary()
        status, got = self.connect(key=key)
        self.assertEqual(status, 200, got)
        self.assertEqual([(c["method"], c["host"], c["path"]) for c in self.fake.calls], [("GET", "api.openai.com", "/v1/models")])
        self.assertEqual(self.keys.peek(self.ai.service("openai")), key)
        card = next(c for c in got["providers"] if c["provider"] == "openai")
        self.assertEqual(([m["model"] for m in card["models"]], card["method"]), (["gpt-5", "gpt-5-mini", "gpt-5-nano"], "key"))
        self.assertNotIn(key, json.dumps(got))

    def test_the_ticked_models_are_saved_and_only_they_are_offered(self):
        self.connect()
        status, got = self.api("POST", "/api/ai/models", {"route": "openai-api", "models": ["gpt-5-mini"]})
        self.assertEqual(status, 200, got)
        self.assertEqual([o["choice"] for o in got["options"] if o["provider"] == "openai"], ["openai-api:gpt-5-mini"])
        status, got = self.api("POST", "/api/ai/models", {"route": "openai-api", "models": ["gpt-9-made-up"]})
        self.assertEqual((status, got["code"]), (409, "not_listed"))
        status, got = self.api("POST", "/api/ai/models", {"route": "openai-api", "models": []})
        self.assertEqual((status, got["code"]), (409, "none_ticked"))

    def test_a_refused_key_says_why_without_the_key_or_the_body_and_keeps_nothing(self):
        key = canary()
        self.fake.answers[("GET", "api.openai.com")] = (401, json.dumps({"error": {"message": "bad key " + key}}).encode())
        status, got = self.connect(key=key)
        self.assertEqual((status, got["code"]), (409, "refused"))
        self.assertTrue(got["message"].startswith("OpenAI did not accept this key (401)."), got["message"])
        self.assertNotIn(key, json.dumps(got))
        self.assertNotIn("bad key", got["message"])
        self.assertFalse(self.keys.has(self.ai.service("openai")))

    def test_a_network_failure_says_it_could_not_reach_the_provider(self):
        self.fake.answers[("GET", "api.anthropic.com")] = providers.Unreachable()
        self.api("POST", "/api/ai/disconnect", {"provider": "claude"})
        status, got = self.connect("claude")
        self.assertEqual((status, got["message"]), (409, "Couldn't reach Claude. Check this computer's internet connection, then try again."))

    def test_a_key_of_the_wrong_shape_is_refused_before_anything_is_sent(self):
        for bad in ("short", "has spaces in it and is long enough", "x" * 400, 12):
            status, got = self.api("POST", "/api/ai/connect", {"provider": "openai", "method": "key", "key": bad})
            self.assertEqual(status, 400, bad)
        self.assertEqual(self.fake.calls, [])

    def test_with_asking_off_connect_sends_nothing(self):
        self.set_switch(False)
        status, got = self.connect()
        self.assertEqual((status, got["code"]), (409, "asking_off"))
        self.assertEqual(self.fake.calls, [])
        self.assertFalse(self.keys.has(self.ai.service("openai")))
        self.assertFalse(got["message"].lower().startswith(("clark", "ask clark")))

    def test_with_asking_off_a_question_sends_nothing_on_a_key_route(self):
        self.connect()
        self.api("POST", "/api/ai/choose", {"choice": "openai-api:gpt-5"})
        self.set_switch(False)
        before = len(self.fake.calls)
        status, got = self.question()
        self.assertEqual((status, got["code"]), (409, "asking_off"))
        self.assertEqual(len(self.fake.calls), before)

    def test_the_other_way_must_be_disconnected_first(self):
        status, got = self.connect("claude")
        self.assertEqual((status, got["code"]), (409, "other_method"))
        self.assertEqual(self.fake.calls, [])

    def test_the_subscription_connects_without_a_key_when_the_command_is_ready(self):
        self.api("POST", "/api/ai/disconnect", {"provider": "claude"})
        self.command.ready = False
        status, got = self.connect("claude", method="subscription")
        self.assertEqual((status, got["code"]), (409, "not_ready"))
        self.command.ready = True
        status, got = self.connect("claude", method="subscription")
        self.assertEqual(status, 200, got)
        self.assertEqual(self.fake.calls, [])
        status, got = self.api("POST", "/api/ai/connect", {"provider": "claude", "method": "subscription", "key": canary()})
        self.assertEqual(status, 400)

    def test_a_body_of_the_wrong_shape_is_refused(self):
        for body in ({}, {"provider": "openai"}, {"provider": "openai", "method": "chatgpt"},
                     {"provider": "openai", "method": "subscription"}, {"provider": "x", "method": "key", "key": canary()},
                     {"provider": "openai", "method": "key", "key": canary(), "more": 1}):
            status, _got = self.api("POST", "/api/ai/connect", body)
            self.assertEqual(status, 400, body)


class Choose(Base):
    def test_a_weaker_model_asks_first_and_use_it_anyway_is_remembered(self):
        status, got = self.api("POST", "/api/ai/choose", {"choice": "claude-command:haiku"})
        self.assertEqual((status, got["code"]), (409, "weaker"))
        self.assertEqual(got["message"], "Claude Haiku is less able than Claude Opus, so its answers may be less accurate. "
                                         "Choose it anyway, or keep the recommended model.")
        self.assertEqual(self.ai.chosen(), "claude-command:opus")
        status, got = self.api("POST", "/api/ai/choose", {"choice": "claude-command:haiku", "anyway": True})
        self.assertEqual((status, got["chosen"]), (200, "claude-command:haiku"))
        self.api("POST", "/api/ai/choose", {"choice": "claude-command:opus"})
        status, got = self.api("POST", "/api/ai/choose", {"choice": "claude-command:haiku"})
        self.assertEqual((status, got["chosen"]), (200, "claude-command:haiku"), "remembered: not asked again")

    def test_the_recommended_model_is_chosen_without_asking(self):
        status, got = self.api("POST", "/api/ai/choose", {"choice": "claude-command:opus"})
        self.assertEqual(status, 200)

    def test_a_model_that_is_not_connected_cannot_be_chosen(self):
        status, got = self.api("POST", "/api/ai/choose", {"choice": "openai-api:gpt-5"})
        self.assertEqual((status, got["code"]), (409, "not_listed"))

    def test_the_question_goes_to_the_chosen_model(self):
        self.api("POST", "/api/ai/choose", {"choice": "claude-command:sonnet", "anyway": True})
        self.command.reply = "On track.\nCITE: P1"
        status, got = self.question()
        self.assertEqual((status, got["ok"]), (200, True), got)
        self.assertEqual(self.command.models, ["sonnet"])


class Disconnect(Base):
    def test_disconnect_takes_the_key_out_and_its_models_go_back_to_the_recommended(self):
        self.connect()
        self.api("POST", "/api/ai/choose", {"choice": "openai-api:gpt-5-mini", "anyway": True})
        self.assertEqual(self.ai.chosen(), "openai-api:gpt-5-mini")
        status, got = self.api("POST", "/api/ai/disconnect", {"provider": "openai"})
        self.assertEqual(status, 200, got)
        self.assertFalse(self.keys.has(self.ai.service("openai")))
        self.assertEqual(got["chosen"], "claude-command:opus")
        self.assertEqual(got["chosen"], got["recommended"])
        self.assertEqual({o["provider"] for o in got["options"]}, {"claude"})
        self.assertIn("Its key is gone", got["message"])


class Limits(Base):
    def test_a_limit_is_said_with_an_offer_and_nothing_switches_by_itself(self):
        self.connect()
        self.api("POST", "/api/ai/choose", {"choice": "openai-api:gpt-5"})
        self.fake.answers[("POST", "api.openai.com")] = (429, b"")
        status, got = self.question()
        self.assertEqual((status, got["ok"], got["code"]), (200, False, "limit"), got)
        self.assertEqual([o["choice"] for o in got["offer"]], ["claude-command:opus", "openai-api:gpt-5-mini",
                                                            "openai-api:gpt-5-nano"])
        self.assertEqual(self.ai.chosen(), "openai-api:gpt-5")
        self.assertEqual(self.command.models, [], "the other provider was not asked")


class Canary(Base):
    """One key through enter, test, call, error and remove; then it is found nowhere."""

    def test_the_canary_key_is_found_nowhere(self):
        key = canary()
        logs = []

        class Keep(logging.Handler):
            def emit(self, record):
                logs.append(self.format(record))
        handler = Keep(level=logging.DEBUG)
        logger = logging.getLogger()
        old = logger.level
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        self.addCleanup(logger.setLevel, old)

        self.assertEqual(self.connect(key=key)[0], 200)                                         # enter and test
        self.api("POST", "/api/ai/choose", {"choice": "openai-api:gpt-5"})
        self.assertEqual(self.question()[1]["ok"], True)                                        # call
        self.fake.answers[("POST", "api.openai.com")] = (500, json.dumps({"error": {"message": key}}).encode())
        status, got = self.question()                                                            # error
        self.assertEqual(got["code"], "no_answer")
        self.question("My key is " + key + " please keep it")                                    # pasted in the chat box
        self.api("GET", "/api/ai/status")
        self.assertEqual(self.api("POST", "/api/ai/disconnect", {"provider": "openai"})[0], 200)   # remove
        self.assertFalse(self.keys.has(self.ai.service("openai")))

        # the key went to the provider in one header, and nowhere else on the wire
        posted = [c for c in self.fake.calls if c["method"] == "POST"]
        self.assertTrue(posted)
        for c in self.fake.calls:
            self.assertEqual([k for k, v in c["headers"].items() if key in v], ["Authorization"])
            self.assertNotIn(key.encode(), c["body"] or b"")
        self.assertEqual(len(posted), 2, "the pasted key was refused before anything was sent")

        found = []
        for path in self.d.rglob("*"):                       # clark.db, ai.json, backups, published files, logs in the data folder
            if path.is_file() and key.encode() in path.read_bytes():
                found.append(str(path))
        if any(key in line for line in logs):
            found.append("the log")
        if any(key in a for a in self.answers):
            found.append("an answer")
        ps = subprocess.run(["ps", "-axww", "-o", "command"], capture_output=True, text=True, check=False).stdout
        if key in ps:
            found.append("the process list")
        repo = subprocess.run(["git", "-C", str(ROOT), "grep", "-F", "--untracked", "-l", key], capture_output=True, text=True,
                              check=False)
        if repo.returncode == 0:
            found.append("the repo")
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
