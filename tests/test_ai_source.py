"""#54: source rules for the outgoing calls and the Claude command, read from the syntax tree of every .py file in src/.

Run: python3 dev/run_tests.py test_ai_source
- Only src/clark/providers.py imports urllib.request, http.client, socket or ssl. Two local-only uses are named, each with its
  reason: launch.py's health check of clark's own server on 127.0.0.1, and __main__.py's free-port check on 127.0.0.1.
- `--bare` is never in an argument list: the one place the text may appear is ask_claude.NEVER_FLAGS, the list of flags refused.
- No module but providers.py names a provider's host.
- reach.py never lets a question read clark's own program folder (providers.py included), even inside a saved folder.
"""
import ast
import unittest
from pathlib import Path

from _paths import SRC
from clark import ask_claude, reach

NETWORK = {"urllib.request", "http.client", "socket", "ssl"}
CALLER = Path("clark") / "providers.py"
LOCAL_ONLY = {(Path("clark") / "launch.py", "http.client"), (Path("clark") / "__main__.py", "socket")}


def sources():
    for path in sorted((SRC / "clark").rglob("*.py")):
        yield path.relative_to(SRC), ast.parse(path.read_text(encoding="utf-8"))


def imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield node.lineno, a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.lineno, node.module
            for a in node.names:
                yield node.lineno, f"{node.module}.{a.name}"


def network_imports(rel, tree):
    out = []
    for line, name in imports(tree):
        hit = next((m for m in NETWORK if name == m or name.startswith(m + ".")), None)
        if hit and rel != CALLER and (rel, hit) not in LOCAL_ONLY:
            out.append(f"{rel.as_posix()}:{line}: imports {name}")
    return out


class OneCaller(unittest.TestCase):
    def test_only_the_provider_caller_imports_a_network_module(self):
        problems = [p for rel, tree in sources() for p in network_imports(rel, tree)]
        self.assertEqual(problems, [])

    def test_the_rule_catches_each_form(self):
        for text in ("import ssl", "import urllib.request", "from urllib import request\nimport http.client",
                     "from socket import create_connection", "from http.client import HTTPSConnection"):
            self.assertTrue(network_imports(Path("clark") / "other.py", ast.parse(text)), text)
        self.assertEqual(network_imports(Path("clark") / "other.py", ast.parse("import socketserver\nimport urllib.parse")), [])

    def test_only_the_caller_names_a_provider_host(self):
        problems = []
        for rel, tree in sources():
            if rel == CALLER:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and \
                        any(h in node.value for h in ("api.anthropic.com", "api.openai.com")):
                    problems.append(f"{rel.as_posix()}:{node.lineno}")
        self.assertEqual(problems, [])


class NeverBare(unittest.TestCase):
    def test_bare_is_only_in_the_list_of_refused_flags(self):
        found = []
        for rel, tree in sources():
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and "--bare" in node.value:
                    found.append((rel.as_posix(), node.value))
        self.assertEqual([f for f in found if f[1] == "--bare"], [("clark/ask_claude.py", "--bare")])
        self.assertIn("--bare", ask_claude.NEVER_FLAGS)
        for model in (None, "opus", "sonnet", "haiku"):
            args = ask_claude.arguments("/x/claude", model)
            self.assertFalse(set(args) & set(ask_claude.NEVER_FLAGS), model)
            self.assertEqual(args[args.index("--tools") + 1], "")
            self.assertIn("--strict-mcp-config", args)
            self.assertIn("--no-session-persistence", args)


class NeverReadable(unittest.TestCase):
    def test_providers_py_is_never_readable_even_inside_a_saved_folder(self):
        import tempfile
        with tempfile.TemporaryDirectory() as data:
            for name in ("providers.py", "platform.py", "ai_service.py"):
                kind, why = reach.classify(str(SRC / "clark" / name), "read", [str(SRC)], data)
                self.assertEqual((kind, why), ("never", reach.PROGRAM), name)


if __name__ == "__main__":
    unittest.main()
