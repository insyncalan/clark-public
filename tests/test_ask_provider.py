"""#47c: the ask clark provider seam, the stub and a second fake (src/clark/ask.py, commit 4).

Run: python3 dev/run_tests.py test_ask_provider
Fictional data only. No process, network or file is used.
"""
import ast
import re
import unittest

from _paths import SRC
from clark import ask

P = [ask.Passage("notes/plan.md", "The go-live is planned for March."), ask.Passage("Actions", "ABC-A-001 Order the kit.")]
ITEMS = {"ABC-A-001"}


def exists(ref):
    return ref in ITEMS


class Words(unittest.TestCase):
    def test_the_dropped_turns_line_follows_the_count(self):
        self.assertEqual(ask.dropped_note(0), "")
        self.assertEqual(ask.dropped_note(1), ask.DROPPED_ONE)
        self.assertEqual(ask.dropped_note(2), ask.DROPPED_MANY)
        self.assertEqual(ask.dropped_note(9), ask.DROPPED_MANY)
        self.assertEqual(ask.dropped_note(-1), "")
        self.assertEqual(ask.dropped_note(True), "")
        self.assertEqual(ask.dropped_note(None), "")
        for text in (ask.DROPPED_ONE, ask.DROPPED_MANY, ask.COULD_NOT, ask.NOT_READY):
            self.assertFalse(text.lower().startswith("clark"))
            self.assertNotIn("claude", text.lower())

    def test_the_provider_sentences_are_pinned(self):
        self.assertEqual(ask.COULD_NOT, "Your question didn't get an answer. Try again in a moment. If it keeps happening, check that the program that "
                                       "answers questions on this computer is signed in.")
        self.assertEqual(ask.NOT_READY, "Asking clark isn't set up on this computer yet. Sign in to the program that answers questions on "
                                        "this computer, then try again. Everything else in the report works as before.")
        self.assertEqual(ask.STOPPED, "Stopped. Nothing was changed.")
        self.assertEqual(ask.DROPPED_MANY, "The oldest messages in this chat were left out to make room.")
        self.assertEqual(ask.DROPPED_ONE, "The oldest message in this chat was left out to make room.")
        for text in (ask.COULD_NOT, ask.NOT_READY):
            self.assertNotIn("assistant", text.lower())


class Interface(unittest.TestCase):
    def test_a_provider_has_a_name_ask_and_status(self):
        for cls in (ask.StubProvider, ask.FramedStubProvider):
            p = cls()
            self.assertTrue(p.provider and p.provider == p.provider.lower())
            self.assertTrue(callable(p.ask) and callable(p.status))
        self.assertNotEqual(ask.StubProvider.provider, ask.FramedStubProvider.provider)

    def test_the_base_class_has_no_answer_and_is_not_ready(self):
        with self.assertRaises(NotImplementedError):
            ask.Provider().ask(ask.build_request("Q?", P))
        self.assertEqual(ask.Provider().status(), {"connected": False, "why": ask.NOT_READY})

    def test_status_is_connected_and_why(self):
        self.assertEqual(ask.StubProvider().status(), {"connected": True, "why": ""})
        st = ask.StubProvider(connected=False).status()
        self.assertEqual(st, {"connected": False, "why": ask.NOT_READY})
        self.assertEqual(ask.StubProvider(connected=False, why="Not signed in.").status()["why"], "Not signed in.")
        self.assertEqual(set(st), {"connected", "why"})                       # nothing else: no key, no account

    def test_a_status_that_is_odd_or_raises_is_not_ready(self):
        class Odd(ask.Provider):
            def status(self):
                return {"connected": "yes", "why": 5, "key": "secret"}

        class Boom(ask.Provider):
            def status(self):
                raise RuntimeError("secret-in-error")
        for p in (Odd(), Boom()):
            self.assertEqual(ask.answer_status(p), {"connected": False, "why": ask.NOT_READY})


class Stub(unittest.TestCase):
    def test_the_stub_answers_and_the_reply_is_read(self):
        req = ask.build_request("What is late?", P)
        r = ask.ask_provider(ask.StubProvider("ABC-A-001 is late.\nCITE: P2"), req, ["ABC"], exists)
        self.assertIsInstance(r, ask.Reply)
        self.assertEqual((r.answer, r.cites, r.parsed, r.flags), ("ABC-A-001 is late.", ("P2",), True, ()))

    def test_the_claims_check_runs_on_what_a_provider_returns(self):
        req = ask.build_request("Q?", P)
        r = ask.ask_provider(ask.StubProvider("ABC-A-999.\nCITE: P5"), req, ["ABC"], exists)
        self.assertEqual(sorted(f.kind for f in r.flags), ["unknown_id", "unsent_passage"])

    def test_a_failure_is_passed_on_in_plain_words(self):
        req = ask.build_request("Q?", P)
        r = ask.ask_provider(ask.StubProvider(failure=ask.STOPPED), req)
        self.assertEqual(r, ask.Failure("Stopped. Nothing was changed."))

    def test_a_provider_that_is_not_ready_is_not_asked(self):
        p = ask.StubProvider(connected=False)
        r = ask.ask_provider(p, ask.build_request("Q?", P))
        self.assertEqual(r, ask.Failure(ask.NOT_READY))
        self.assertEqual(p.sent, [])

    def test_a_provider_that_raises_or_returns_junk_gives_a_plain_failure_without_its_message(self):
        class Boom(ask.StubProvider):
            def ask(self, request):
                raise RuntimeError("the question was: " + request.question)

        class Junk(ask.StubProvider):
            def ask(self, request):
                return {"text": "x"}

        class EmptyFailure(ask.StubProvider):
            def ask(self, request):
                return ask.Failure("")
        for p in (Boom(), Junk(), EmptyFailure()):
            r = ask.ask_provider(p, ask.build_request("Secret question?", P))
            self.assertEqual(r, ask.Failure(ask.COULD_NOT))

    def test_something_that_is_not_a_request_is_refused(self):
        self.assertEqual(ask.ask_provider(ask.StubProvider("x"), "just text"), ask.Failure(ask.BAD_INPUT))

    def test_an_empty_reply_is_unreadable_and_offers_no_change(self):
        r = ask.ask_provider(ask.StubProvider(""), ask.build_request("Q?", P))
        self.assertEqual((r.parsed, r.changes), (False, ()))


class SameRequest(unittest.TestCase):
    def test_two_providers_with_different_envelopes_carry_the_same_request_text(self):
        a, b = ask.StubProvider("ok"), ask.FramedStubProvider("ok")
        for question, passages in (("What is late?", P), ("Is ABC-A-001 ​ done?", P[:1]), ("Hello?", [])):
            req = ask.build_request(question, passages)
            ask.ask_provider(a, req)
            ask.ask_provider(b, req)
        self.assertEqual(len(a.sent), 3)
        for plain, framed in zip(a.sent, b.sent):
            self.assertNotEqual(plain, framed)                              # the envelopes differ ...
            self.assertEqual(framed, "<request>\n" + plain + "\n</request>")  # ... and nothing else does
        self.assertEqual(ask.build_request("What is late?", P).text, a.sent[0])

    def test_the_request_does_not_depend_on_the_provider(self):
        a, b = ask.StubProvider("ok"), ask.FramedStubProvider("ok")
        req1, req2 = ask.build_request("Q?", P), ask.build_request("Q?", P)
        ask.ask_provider(a, req1)
        ask.ask_provider(b, req2)
        self.assertEqual(req1, req2)


def _ask_modules():
    return sorted((SRC / "clark").glob("ask*.py"))


def _imports(tree):
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            out.add(n.module or "")
    return out


class Source(unittest.TestCase):
    PROVIDER_MODULE = "ask_claude.py"                    # the one provider module (commit 5); not built yet

    def test_nothing_outside_the_one_provider_module_names_the_company_or_its_model(self):
        mods = _ask_modules()
        self.assertIn("ask.py", [m.name for m in mods])
        for path in mods:
            if path.name == self.PROVIDER_MODULE:
                continue
            text = path.read_text(encoding="utf-8").lower()
            for word in ("claude", "anthropic", "opus", "sonnet", "haiku"):
                self.assertNotIn(word, text, f"{path.name} says {word}")

    def test_no_ask_module_reaches_the_network_and_only_the_provider_module_starts_a_process(self):
        for path in _ask_modules():
            names = _imports(ast.parse(path.read_text(encoding="utf-8")))
            for bad in ("urllib", "urllib.request", "http", "http.client", "socket", "ssl", "requests", "ftplib", "smtplib", "asyncio"):
                self.assertNotIn(bad, names, f"{path.name} imports {bad}")
            if path.name != self.PROVIDER_MODULE:
                self.assertNotIn("subprocess", names, f"{path.name} imports subprocess")

    def test_no_ask_module_logs_or_prints(self):
        for path in _ask_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            self.assertFalse({"logging", "log", "debug_log"} & _imports(tree), path.name)
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                    self.assertNotIn(n.func.id, {"print", "open"}, path.name)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                    self.assertFalse(re.fullmatch(r"(debug|info|warning|error|exception|log)", n.func.attr), f"{path.name}: {n.func.attr}")

    def test_no_person_facing_text_in_ask_py_starts_with_the_product_name(self):
        tree = ast.parse((SRC / "clark" / "ask.py").read_text(encoding="utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef))
                and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:        # docstrings are not shown
                self.assertFalse(n.value.lower().startswith(("clark", "ask clark")), n.value[:40])


if __name__ == "__main__":
    unittest.main()
