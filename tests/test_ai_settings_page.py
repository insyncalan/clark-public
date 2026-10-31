"""#54: Settings › AI in a real browser against the real server, with FAKE providers only (desktop widths 1400 and 900 only).

Run: python3 dev/run_tests.py test_ai_settings_page
The server's ai service is ai_service.AiService over providers.Ai with FakeKeyStore, FakeTransport and FakeCommand: no keychain, no
network, and every key ends TESTONLY. Shown: the two cards, the connect box with its pinned words, a refused key that keeps the box
open, the model list of connected providers only with the recommended marked, a weaker choice that asks first, Disconnect, the
panel's offer after a limit, and the words. The published page has none of it. Chrome is required: fails, never skips.
"""
import json
import os
import re
import secrets
import shutil
import tempfile
import unittest
from pathlib import Path

from _paths import ROOT
from test_page import DATA, navigate
from test_page_words import NEVER
from test_report_editor import Base
from test_server import Running, chrome, wait

from clark import ai_service, ask_service, page, providers

PAGE_SRC = Path(page.PAGE).parent / "src" / "edit"
WIDTHS = (1400, 900)
NOTE = ("When you ask, your question and the passages it needs leave this computer and go to the provider you connect, billed to "
        "that account. Claude and OpenAI are sent the same text in the same way.")


def canary():
    return "sk-proj-" + secrets.token_hex(16) + "TESTONLY"


class AiPage(unittest.TestCase):
    def setUp(self):
        self.s = Running(data_for=DATA.get, page_html=lambda: page.page_html(tempfile.mkdtemp()))
        self.addCleanup(self.s.close)
        self.d = Path(os.path.realpath(tempfile.mkdtemp(prefix="clark-test-")))
        self.addCleanup(shutil.rmtree, self.d, True)
        self.keys, self.fake, self.command = providers.FakeKeyStore(), providers.FakeTransport(), providers.FakeCommand()
        self.ai = providers.Ai(self.d, self.command, self.keys, self.fake)
        self.on = True
        self.s.httpd.ai = ai_service.AiService(self.ai, lambda: self.on)

    def show(self, cdp):
        sid = navigate(cdp, self.s.port, "#settings&p=ABC")
        self.sid = sid
        js = lambda e: cdp.js(e, sid)          # noqa: E731
        self.assertTrue(wait(lambda: js("!!document.querySelector('#ai-settings .ai-provs')"), 20), "the AI entry is in Settings")
        return js

    def text(self, js, sel):
        return js(f"(document.querySelector({json.dumps(sel)}) || {{}}).innerText || ''")

    def test_two_cards_the_model_list_and_laptop_widths_light_and_dark(self):
        with chrome() as cdp:
            js = self.show(cdp)
            self.assertIn("Connected", self.text(js, "[data-ai-card=claude] h3"))
            self.assertEqual(self.text(js, "[data-ai-card=claude] [data-ai-how]"), "Claude subscription")
            self.assertIn("Not connected", self.text(js, "[data-ai-card=openai] h3"))
            self.assertEqual(js("[...document.querySelectorAll('#ai-model option')].map(o => o.textContent)"),
                             ["Claude Opus (recommended) · Claude", "Claude Sonnet · Claude", "Claude Haiku · Claude"])
            self.assertEqual(js("document.querySelector('#ai-model').value"), "claude-command:opus")
            for w in WIDTHS:
                cdp.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": 900, "deviceScaleFactor": 1, "mobile": False}, self.sid)
                for theme in ("light", "dark"):
                    js(f"document.documentElement.dataset.theme = '{theme}'")
                    self.assertTrue(js("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), f"{w} {theme}")
                    for card in ("claude", "openai"):
                        sel = f"document.querySelector('[data-ai-card={card}]')"
                        self.assertTrue(js(f"{sel}.scrollWidth <= {sel}.clientWidth + 1"), f"{w} {theme} {card} fits")
                        bg, fg = js(f"getComputedStyle({sel}).backgroundColor"), js(f"getComputedStyle({sel}).color")
                        self.assertNotEqual(bg, fg)
                        if theme == "dark":
                            self.assertNotEqual(bg, "rgb(255, 255, 255)", "the card follows dark mode")

    def test_connect_openai_with_a_key_the_box_says_where_passages_go_and_the_key_never_shows(self):
        key = canary()
        with chrome() as cdp:
            js = self.show(cdp)
            js("document.querySelector('[data-ai-connect=openai]').click()")
            self.assertTrue(wait(lambda: js("!!document.querySelector('[data-ai-box=openai]')"), 10))
            self.assertEqual(self.text(js, "[data-ai-box=openai] [data-ai-note]"), NOTE)
            self.assertFalse(js("!!document.querySelector('[data-ai-box=openai] [data-ai-method]')"), "OpenAI: an API key only")
            self.assertEqual(js("document.querySelector('[data-ai-key]').type"), "password")
            self.assertEqual(js("document.querySelector('[data-ai-key]').autocomplete"), "off")
            js("document.querySelector('[data-ai-key]').focus()")
            cdp.call("Input.insertText", {"text": key}, self.sid)
            self.assertTrue(wait(lambda: js("!document.querySelector('[data-ai-test]').disabled"), 10))
            js("document.querySelector('[data-ai-test]').click()")
            self.assertTrue(wait(lambda: "Connected" in self.text(js, "[data-ai-card=openai] h3")
                                 and "Not" not in self.text(js, "[data-ai-card=openai] h3"), 10))
            self.assertEqual(self.keys.peek(self.ai.service("openai")), key)
            self.assertNotIn(key, js("document.documentElement.outerHTML"))
            self.assertNotIn(key, js("JSON.stringify(Object.assign({}, localStorage, sessionStorage))"))
            labels = js("[...document.querySelectorAll('#ai-model option')].map(o => o.textContent)")
            self.assertIn("gpt-5 (recommended) · OpenAI", labels)
            self.assertEqual(js("[...document.querySelectorAll('[data-ai-card=openai] [data-ai-tick]')].map(b => b.checked)"),
                             [True, True, True])
            js("document.querySelector('[data-ai-tick=\"gpt-5-nano\"]').click()")
            self.assertTrue(wait(lambda: js("!!document.querySelector('[data-ai-save]')"), 10))
            js("document.querySelector('[data-ai-save]').click()")
            self.assertTrue(wait(lambda: "gpt-5-nano · OpenAI" not in js("[...document.querySelectorAll('#ai-model option')].map(o => o.textContent)"), 10))

    def test_a_refused_key_keeps_the_box_open_says_why_and_empties_the_field(self):
        self.fake.answers[("GET", "api.openai.com")] = (401, b'{"error": {"message": "nope"}}')
        with chrome() as cdp:
            js = self.show(cdp)
            js("document.querySelector('[data-ai-connect=openai]').click()")
            self.assertTrue(wait(lambda: js("!!document.querySelector('[data-ai-key]')"), 10))
            js("document.querySelector('[data-ai-key]').focus()")
            cdp.call("Input.insertText", {"text": canary()}, self.sid)
            js("document.querySelector('[data-ai-test]').click()")
            self.assertTrue(wait(lambda: self.text(js, "[data-ai-msg]").startswith("OpenAI did not accept this key (401)."), 10))
            self.assertTrue(js("!!document.querySelector('[data-ai-box=openai]')"), "the box stays open")
            self.assertEqual(js("document.querySelector('[data-ai-key]').value"), "")
            self.assertNotIn("nope", self.text(js, "#ai-settings"))

    def test_a_weaker_model_asks_first_and_use_it_anyway_chooses_it(self):
        with chrome() as cdp:
            js = self.show(cdp)
            js("var s = document.querySelector('#ai-model'); s.value = 'claude-command:haiku'; s.dispatchEvent(new Event('change', {bubbles: true}))")
            self.assertTrue(wait(lambda: js("!!document.querySelector('#ai-weaker')"), 10))
            self.assertEqual(self.text(js, "#ai-weaker p"), "Claude Haiku is less able than Claude Opus, so its answers may be less "
                                                             "accurate. Choose it anyway, or keep the recommended model.")
            self.assertEqual(self.ai.chosen(), "claude-command:opus", "not chosen yet")
            js("document.querySelector('[data-ai-anyway]').click()")
            self.assertTrue(wait(lambda: not js("!!document.querySelector('#ai-weaker')"), 10))
            self.assertEqual(self.ai.chosen(), "claude-command:haiku")
            self.assertEqual(js("document.querySelector('#ai-model').value"), "claude-command:haiku")

    def test_disconnect_takes_the_provider_out_of_the_list(self):
        with chrome() as cdp:
            js = self.show(cdp)
            js("document.querySelector('[data-ai-disconnect=claude]').click()")
            self.assertTrue(wait(lambda: "Not connected" in self.text(js, "[data-ai-card=claude] h3"), 10))
            self.assertEqual(js("[...document.querySelectorAll('#ai-model option')].map(o => o.textContent)"), ["Connect a provider first."])
            self.assertTrue(js("document.querySelector('#ai-model').disabled"))


class PanelOffer(Base):
    """After a limit the panel offers the other provider's recommended model and a smaller one; nothing switches until a button
    is pressed."""

    def setUp(self):
        super().setUp()
        self.d = Path(os.path.realpath(tempfile.mkdtemp(prefix="clark-test-")))
        self.addCleanup(shutil.rmtree, self.d, True)
        self.keys, self.fake, self.command = providers.FakeKeyStore(), providers.FakeTransport(), providers.FakeCommand()
        self.ai = providers.Ai(self.d, self.command, self.keys, self.fake)
        self.s.httpd.ask = ask_service.AskService(self.store.path, providers.RoutedProvider(self.ai), [])
        self.s.httpd.ai = ai_service.AiService(self.ai, lambda: True)
        service = self.s.httpd.ai
        self.assertEqual(service.connect({"provider": "openai", "method": "key", "key": canary()})[0], 200)
        self.assertEqual(service.choose({"choice": "openai-api:gpt-5"})[0], 200)
        self.fake.answers[("POST", "api.openai.com")] = (429, b"")

    def test_a_limit_offers_a_switch_and_only_a_press_switches(self):
        with chrome() as cdp:
            p = self.visit(cdp)
            p.key("/", code="Slash", vk=191)
            p.until("!!document.querySelector('#ask-panel') && !document.querySelector('#ask-box').disabled", "the panel is ready")
            p.js("document.querySelector('#ask-box').focus()")
            p.type("What is late?")
            p.key("Enter", code="Enter", vk=13)
            p.until("!!document.querySelector('[data-ask-offer]')", "the offer")
            self.assertIn("OpenAI says a limit has been reached.", p.js("document.querySelector('#ask-log').innerText"))
            self.assertEqual(p.js("[...document.querySelectorAll('[data-ask-switch-to]')].map(b => b.innerText)"),
                             ["Use Claude Opus", "Use gpt-5-mini", "Use gpt-5-nano"])
            self.assertEqual(self.ai.chosen(), "openai-api:gpt-5", "nothing switched by itself")
            self.assertEqual(self.command.models, [])
            p.js("document.querySelector('[data-ask-switch-to=\"claude-command:opus\"]').click()")
            p.until("!!document.querySelector('[data-ask-offer-done]')", "the switch is said")
            self.assertEqual(p.js("document.querySelector('[data-ask-offer-done]').innerText"),
                             "Questions now go to Claude Opus. Ask again when you're ready.")
            self.assertEqual(self.ai.chosen(), "claude-command:opus")


class Words(unittest.TestCase):
    SOURCES = ("AiSettings.jsx", "AskOffer.jsx", "aiApi.js")

    def sentences(self):
        out = []
        for name in self.SOURCES:
            text = (PAGE_SRC / name).read_text(encoding="utf-8")
            out += re.findall(r'export const [A-Z_]+ = "((?:[^"\\]|\\.)*)"', text)
            out += re.findall(r'return "((?:[^"\\]|\\.)*)"', text)
        out += list(ai_service.MESSAGES.values()) + [ai_service.CONNECT_NOTE, providers.NOT_SET_UP]
        out += [providers.words(p, w, 401) for p in ("claude", "openai") for w in
                ("refused_key", "unreachable", "limit", "no_models", "too_long", "too_much", "unreadable", "failed")]
        return out

    def test_every_sentence_is_plain_and_never_starts_with_the_product_name(self):
        said = self.sentences()
        self.assertGreater(len(said), 30)
        for text in said:
            self.assertIsNone(NEVER.search(text), text)
            self.assertFalse(re.match(r"(ask )?clark", text, re.I), f"starts with the product name: {text}")
            self.assertRegex(text, r"[.…]$", text)

    def test_every_failure_says_the_next_step(self):
        steps = r"(try again|Try again|Reload|Connect|Disconnect|Tick|Choose|Copy|Turn on|connect|Ask a narrower|Open Keychain|then|Check)"
        for code, text in ai_service.MESSAGES.items():
            self.assertRegex(text, steps, code)
        for p in ("claude", "openai"):
            for w in ("refused_key", "unreachable", "limit", "no_models", "unreadable", "failed"):
                self.assertRegex(providers.words(p, w, 401), steps, w)

    def test_the_published_page_has_none_of_it(self):
        view = (ROOT / "src" / "clark" / "page" / "page-view.html").read_text(encoding="utf-8")
        for needle in ("/api/ai/", "ai-settings", "data-ai-", "ask-offer"):
            self.assertNotIn(needle, view)
        self.assertIn("/api/ai/connect", (ROOT / "src" / "clark" / "page" / "page.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
