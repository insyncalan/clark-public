"""#54: the key store, the model lister, the direct caller, routing and limits (src/clark/providers.py, platform.MacKeychain).

Run: python3 dev/run_tests.py test_providers
Fakes only: the keychain is never touched (MacKeychain is given a fake `run`), no network call is made (the caller is given a fake
opener or FakeTransport), and every key ends TESTONLY.
"""
import io
import json
import secrets
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from _paths import SRC  # noqa: F401  (puts src/ on the path)
from clark import ask, ask_claude, platform, providers

CLAUDE_API, OPENAI_API, COMMAND = (providers.ROUTE[n] for n in ("claude-api", "openai-api", "claude-command"))


def canary():
    return "sk-ant-" + secrets.token_hex(16) + "TESTONLY"


class FakeRun:
    """Stands in for platform.run_stoppable: records (args, data, env) and answers (status, out, code)."""

    def __init__(self, answers=None):
        self.calls, self.answers = [], list(answers or [])

    def __call__(self, args, data, env, limit, max_out, stop=None, prefix=""):
        self.calls.append((list(args), data, dict(env)))
        return self.answers.pop(0) if self.answers else ("ok", b"", 0)


class MacKeychainTest(unittest.TestCase):
    SERVICE = providers.service_name("/tmp/clark-test-data", "openai")

    def test_the_service_and_account_are_the_issue_s(self):
        self.assertRegex(self.SERVICE, r"^clark\.ai\.[0-9a-f]{16}\.openai$")
        self.assertEqual(platform.KEY_ACCOUNT, "clark")
        self.assertNotEqual(providers.service_name("/tmp/a", "openai"), providers.service_name("/tmp/b", "openai"))

    def test_put_sends_the_key_on_standard_input_only_never_in_the_arguments_or_environment(self):
        key, run = canary(), FakeRun()
        platform.MacKeychain(run=run).put(self.SERVICE, key)
        args, data, env = run.calls[0]
        self.assertEqual(args, [platform.SECURITY, "-i"])
        self.assertNotIn(key, " ".join(args))
        self.assertNotIn(key, json.dumps(env))
        self.assertEqual(data, f"add-generic-password -U -s {self.SERVICE} -a clark -w {key}\n".encode("ascii"))
        self.assertEqual(set(env), {"PATH", "LANG", "HOME"})

    def test_has_never_asks_for_the_secret_and_peek_reads_it_from_standard_output(self):
        key = canary()
        run = FakeRun([("ok", b"keychain: x\n", 0), ("ok", (key + "\n").encode("ascii"), 0), ("failed", b"", 44)])
        kc = platform.MacKeychain(run=run)
        self.assertTrue(kc.has(self.SERVICE))
        self.assertNotIn("-w", run.calls[0][0])
        self.assertNotIn("-g", run.calls[0][0])
        self.assertEqual(kc.peek(self.SERVICE), key)
        self.assertEqual(run.calls[1][0][-1], "-w")
        self.assertIsNone(kc.peek(self.SERVICE))

    def test_remove_is_done_when_the_item_is_gone_or_was_never_there_and_says_so_plainly_otherwise(self):
        self.assertTrue(platform.MacKeychain(run=FakeRun([("ok", b"", 0)])).remove(self.SERVICE))
        self.assertTrue(platform.MacKeychain(run=FakeRun([("failed", b"", 44)])).remove(self.SERVICE))
        with self.assertRaises(platform.PlatformError) as e:
            platform.MacKeychain(run=FakeRun([("failed", b"", 51)])).remove(self.SERVICE)
        self.assertEqual(str(e.exception), platform.KEY_NOT_REMOVED)

    def test_a_key_or_service_of_the_wrong_shape_never_reaches_the_program(self):
        run = FakeRun()
        kc = platform.MacKeychain(run=run)
        for bad in ("short", "sk-ant-" + "a" * 20 + " -w x", "sk-ant-" + "a" * 20 + "\nadd-generic-password", "x" * 300, None):
            with self.assertRaises(platform.PlatformError):
                kc.put(self.SERVICE, bad)
        for bad in ("clark.ai.zz.openai", "other.service", "clark.ai.0123456789abcdef.openai -a x"):
            with self.assertRaises(platform.PlatformError):
                kc.has(bad)
        self.assertEqual(run.calls, [])

    def test_a_failed_put_says_the_fixed_sentence_without_the_key(self):
        key = canary()
        with self.assertRaises(platform.PlatformError) as e:
            platform.MacKeychain(run=FakeRun([("failed", b"", 1)])).put(self.SERVICE, key)
        self.assertEqual(str(e.exception), platform.KEY_NOT_SAVED)
        self.assertNotIn(key, str(e.exception))

    def test_other_systems_are_never_connected(self):
        store = platform.key_store(on="win32")
        self.assertIsInstance(store, platform.NotBuiltStore)
        self.assertFalse(store.has(self.SERVICE))
        self.assertIsNone(store.peek(self.SERVICE))
        with self.assertRaises(platform.NotBuiltYet):
            store.put(self.SERVICE, canary())
        self.assertIsInstance(platform.key_store(on="darwin"), platform.MacKeychain)


class FakeResponse(io.BytesIO):
    status = 200


class OutgoingCallTest(unittest.TestCase):
    def test_only_the_two_hosts_over_https_on_a_v1_path(self):
        self.assertEqual(providers.HOSTS, ("api.anthropic.com", "api.openai.com"))
        self.assertEqual(providers.check_target("api.openai.com", "/v1/models"), "https://api.openai.com/v1/models")
        for host, path in (("api.openai.com.example.com", "/v1/models"), ("evil.example", "/v1/models"),
                           ("api.openai.com", "/v2/x"), ("api.openai.com", "/v1/x@evil.example"), ("api.openai.com", "/v1/a b"),
                           ("API.OPENAI.COM", "/v1/models")):
            with self.assertRaises(ValueError):
                providers.check_target(host, path)

    def test_the_opener_has_no_proxy_no_plain_http_no_file_handler_and_refuses_redirects(self):
        od = providers.opener()
        kinds = {type(h) for h in od.handlers}
        self.assertNotIn(urllib.request.ProxyHandler, kinds)
        self.assertNotIn(urllib.request.HTTPHandler, kinds)
        self.assertNotIn(urllib.request.FileHandler, kinds)
        self.assertNotIn(urllib.request.HTTPRedirectHandler, kinds)
        self.assertIn(providers._NoRedirect, kinds)
        redirect = providers._NoRedirect()
        self.assertIsNone(redirect.redirect_request(None, None, 302, "Found", {}, "https://evil.example/"))

    def test_tls_is_verified_and_at_least_1_2(self):
        import ssl
        ctx = providers.tls_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertGreaterEqual(ctx.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_a_redirect_answer_is_never_followed(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 302, "Found", {"Location": "https://evil.example/"}, io.BytesIO(b""))
        with self.assertRaises(providers.Unreachable):
            providers.https_call("GET", "api.openai.com", "/v1/models", {}, None, 5, 100, open_with=opener)

    def test_the_bytes_read_and_sent_are_capped(self):
        with self.assertRaises(providers.TooMuch):
            providers.https_call("GET", "api.openai.com", "/v1/models", {}, None, 5, 10,
                                 open_with=lambda req, timeout: FakeResponse(b"x" * 11))
        with self.assertRaises(ValueError):
            providers.https_call("POST", "api.openai.com", "/v1/chat/completions", {}, b"x" * (providers.MAX_SEND + 1), 5, 10,
                                 open_with=lambda req, timeout: FakeResponse(b""))

    def test_a_network_failure_keeps_no_text_and_the_time_limit_is_passed(self):
        seen = {}

        def opener(req, timeout):
            seen["timeout"] = timeout
            raise urllib.error.URLError("secret-looking reason " + canary())
        with self.assertRaises(providers.Unreachable) as e:
            providers.https_call("GET", "api.openai.com", "/v1/models", {}, None, 7, 100, open_with=opener)
        self.assertEqual(str(e.exception), "")
        self.assertIsNone(e.exception.__cause__)
        self.assertEqual(seen["timeout"], 7)

    def test_the_key_goes_in_one_header_only(self):
        key = canary()
        for route in (CLAUDE_API, OPENAI_API):
            headers = providers.key_headers(route, key)
            self.assertEqual(sum(key in v for v in headers.values()), 1, route.name)
            body = json.dumps(providers.envelope_for(route, "m", "text"))
            self.assertNotIn(key, body)


class ListAndSendTest(unittest.TestCase):
    def test_connect_lists_usable_models_newest_first_and_marks_the_strongest(self):
        fake = providers.FakeTransport()
        models = providers.list_models(CLAUDE_API, canary(), call=fake)
        self.assertEqual(models, ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"])
        self.assertEqual(providers.recommended("claude", models), "claude-opus-5-5")
        self.assertEqual(fake.calls[0]["path"], "/v1/models?limit=100")
        self.assertEqual(providers.recommended("openai", providers.list_models(OPENAI_API, canary(), call=fake)), "gpt-5")

    def test_a_refused_key_and_a_network_failure_say_why_without_the_key_or_the_body(self):
        key = canary()
        body = json.dumps({"error": {"message": "Incorrect API key provided: " + key}}).encode("utf-8")
        fake = providers.FakeTransport({("GET", "api.openai.com"): (401, body)})
        with self.assertRaises(providers.Refused) as e:
            providers.list_models(OPENAI_API, key, call=fake)
        self.assertTrue(e.exception.message.startswith("OpenAI did not accept this key (401)."), e.exception.message)
        self.assertNotIn(key, e.exception.message)
        self.assertNotIn("Incorrect", e.exception.message)
        fake = providers.FakeTransport({("GET", "api.anthropic.com"): providers.Unreachable()})
        with self.assertRaises(providers.Refused) as e:
            providers.list_models(CLAUDE_API, key, call=fake)
        self.assertEqual(e.exception.message, "Couldn't reach Claude. Check this computer's internet connection, then try again.")

    def test_one_question_is_one_call_with_no_tools_and_the_same_text_on_every_route(self):
        request = ask.build_request("What is late?", [ask.Passage("Actions", "ABC-A-001 is late.")])
        fake = providers.FakeTransport()
        for route in (CLAUDE_API, OPENAI_API):
            self.assertEqual(providers.send(route, canary(), "m", request.text, call=fake), "A fake answer.")
        sent = [json.loads(c["body"]) for c in fake.calls]
        for body in sent:
            self.assertNotIn("tools", body)
            self.assertNotIn("tool_choice", body)
            self.assertNotIn("functions", body)
        claude, openai = sent
        self.assertEqual(claude["system"], ask.RULES)
        self.assertEqual(claude["messages"], [{"role": "user", "content": request.text}])
        self.assertEqual(openai["messages"], [{"role": "system", "content": ask.RULES}, {"role": "user", "content": request.text}])
        self.assertIs(openai["store"], False)
        self.assertEqual(claude["max_tokens"], providers.MAX_REPLY_TOKENS)
        self.assertEqual(openai["max_completion_tokens"], providers.MAX_REPLY_TOKENS)
        self.assertEqual([c["path"] for c in fake.calls], ["/v1/messages", "/v1/chat/completions"])
        # the Claude command gets the same rules and the same text
        args = ask_claude.arguments("/x/claude", "opus")
        self.assertEqual(args[args.index("--system-prompt") + 1], ask.RULES)
        self.assertEqual(args[args.index("--model") + 1], "opus")
        self.assertEqual(ask_claude.ClaudeCommand.envelope(None, request.text), request.text)

    def test_the_chosen_model_reaches_the_command_and_an_unknown_one_never_does(self):
        self.assertNotIn("--model", ask_claude.arguments("/x/claude", "opus; rm -rf"))
        self.assertIn("--model", ask_claude.NEEDED_FLAGS)
        self.assertNotIn("--bare", ask_claude.arguments("/x/claude", "opus"))

    def test_a_429_or_the_provider_s_limit_error_is_a_limit(self):
        for status, raw in ((429, b""), (400, json.dumps({"error": {"type": "rate_limit_error"}}).encode()),
                            (403, b"x"), (500, b"")):
            fake = providers.FakeTransport({("POST", "api.anthropic.com"): (status, raw)})
            with self.assertRaises(providers.Refused) as e:
                providers.send(CLAUDE_API, canary(), "m", "t", call=fake)
            self.assertEqual(e.exception.limit, status in (429, 400), status)


class RoutingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.keys, self.fake, self.command = providers.FakeKeyStore(), providers.FakeTransport(), providers.FakeCommand()
        self.ai = providers.Ai(self.dir, self.command, self.keys, self.fake)

    def tearDown(self):
        self.tmp.cleanup()

    def connect(self, route, models):
        state = self.ai.choices.read()
        state["routes"][route] = {"listed": [] if route == "claude-command" else models, "models": models}
        self.ai.choices.write(state)
        if route != "claude-command":
            self.keys.put(self.ai.service(providers.ROUTE[route].provider), canary())

    def test_before_any_choice_the_claude_command_stays_as_it_was(self):
        self.assertEqual(self.ai.chosen(), "claude-command:opus")
        self.assertEqual(providers.RoutedProvider(self.ai).status(), {"connected": True, "why": ""})

    def test_with_nothing_connected_asking_says_it_is_not_set_up(self):
        self.ai.choices.write({"routes": {}, "chosen": "", "anyway": []})
        routed = providers.RoutedProvider(self.ai)
        self.assertEqual(routed.status(), {"connected": False, "why": providers.NOT_SET_UP})
        self.assertEqual(ask.ask_provider(routed, ask.build_request("Hi", [])), ask.Failure(providers.NOT_SET_UP))

    def test_a_key_route_counts_only_while_its_key_is_in_the_store(self):
        self.ai.choices.write({"routes": {}, "chosen": "", "anyway": []})
        self.connect("openai-api", ["gpt-5", "gpt-5-mini"])
        self.assertEqual(self.ai.chosen(), "openai-api:gpt-5")
        self.keys.remove(self.ai.service("openai"))
        self.assertEqual(self.ai.chosen(), "")
        self.assertEqual(self.fake.calls, [])

    def test_a_limit_offers_the_other_provider_and_a_smaller_model_and_never_switches(self):
        self.ai.choices.write({"routes": {}, "chosen": "openai-api:gpt-5", "anyway": []})
        self.connect("openai-api", ["gpt-5", "gpt-5-mini"])
        self.connect("claude-command", ["opus", "sonnet"])
        self.fake.answers[("POST", "api.openai.com")] = (429, b"")
        routed = providers.RoutedProvider(self.ai)
        got = ask.ask_provider(routed, ask.build_request("What is late?", []))
        self.assertIsInstance(got, providers.Limited)
        self.assertEqual([o["choice"] for o in got.offer], ["claude-command:opus", "openai-api:gpt-5-mini"])
        self.assertEqual(self.ai.choices.read()["chosen"], "openai-api:gpt-5")         # nothing switched
        self.assertEqual(self.ai.chosen(), "openai-api:gpt-5")
        self.assertEqual(self.command.models, [])                                     # and nothing was sent elsewhere
        self.assertEqual(len(self.fake.calls), 1)

    def test_the_choices_file_never_holds_a_key(self):
        self.ai.choices.write({"routes": {}, "chosen": "", "anyway": []})
        self.connect("claude-api", ["claude-opus-5-5"])
        text = (self.dir / providers.CHOICES_FILE).read_text(encoding="utf-8")
        self.assertNotIn("TESTONLY", text)
        self.assertNotIn("sk-", text)


class FakesGateTest(unittest.TestCase):
    def test_the_fakes_are_honoured_only_for_a_temporary_data_folder_or_the_marker(self):
        on = {"CLARK_FAKE_PROVIDERS": "1"}
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as root:
            self.assertTrue(providers.fakes_allowed(tmp, on, source_root=root))
            self.assertFalse(providers.fakes_allowed(tmp, {}, source_root=root))
            self.assertFalse(providers.fakes_allowed(tmp, {"CLARK_FAKE_PROVIDERS": "yes"}, source_root=root))
            self.assertFalse(providers.fakes_allowed(Path.home() / "Library-not-temp", on, source_root=root))
            (Path(root) / providers.DEV_MARKER).write_text("", encoding="utf-8")
            self.assertTrue(providers.fakes_allowed(Path.home() / "Library-not-temp", on, source_root=root))
            ai = providers.build(tmp, None, environ=on)
            self.assertIsInstance(ai.keys, providers.FakeKeyStore)
            self.assertIsInstance(ai.call, providers.FakeTransport)


if __name__ == "__main__":
    unittest.main()
