"""#72 slice 2: the AI suggestion card, five states, against a stub client (nothing is sent anywhere).

Run: python3 dev/run_tests.py test_ai_card
The real AiCard (src/clark/page/src/edit/AiCard.jsx) with the stub aiClient on a bare page in headless Chrome (tests/_ai_page.py),
checked against docs/handoff/design-72-ai-menu-page.md section 6a and the Done-when list of slice 2: each state, the keyboard path (Tab
order, Enter, Esc), focus after Accept, Discard, Esc and Stop, the exact announcements and a polite (never assertive) live region, nothing
changed before Accept, the off line at 4.5 to 1, reduced motion, and the card inside the window at 1400 and 900 px in light and dark
(no phone widths). The editors are not wired in this slice: the card is mounted on a stand-in.
"""
import re
import unittest

from _ai_page import AiHarness
from _paths import SRC
from test_server import chrome

TEXT = "The supplier confirmed the delivery for Friday and asked us to keep the room booked until then."
WORKING, READY = "Working on it", "Suggestion ready"
FAILED = "That did not work. Try again."
OFF = "AI is switched off in Settings."
NOT_SIGNED_IN = "Connect Claude in Settings to use this."
CSS = (SRC / "clark" / "page" / "src" / "edit" / "edit.css").read_text(encoding="utf-8")

CONTRAST = """(()=>{
  const lum=(c)=>{const m=c.match(/[\\d.]+/g).map(Number).slice(0,3).map(v=>{v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4);});return .2126*m[0]+.7152*m[1]+.0722*m[2];};
  const fg=getComputedStyle(document.querySelector(%s)).color, bg=getComputedStyle(document.querySelector('.aic')).backgroundColor;
  const a=lum(fg), b=lum(bg); return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
})()"""


class Card(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = AiHarness(chrome).__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.h.__exit__(None, None, None)

    def setUp(self):
        h = self.h
        h.ev("window.unmount()")
        h.ev("for (const k of Object.keys(window.opts)) delete window.opts[k]; window.client.calls.length = 0; "
             "window.applied.length = 0; window.exits.length = 0; window.returned.length = 0; window.useEditor = false; "
             "document.getElementById('ed').innerHTML = ''")
        h.resize(1400)
        h.theme("light")
        h.cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "no-preference"}]}, h.sid)

    def ready(self, **cfg):
        self.h.card(text=TEXT, **cfg)
        self.assertTrue(self.h.until("document.querySelector('.aic').dataset.state === 'ready'"), self.h.state())

    def working(self, **cfg):
        self.h.ev("window.opts.hold = true")
        self.h.card(text=TEXT, **cfg)
        self.assertEqual(self.h.state(), "working")

    def enter(self):
        h = self.h
        for kind in ("keyDown", "keyUp"):
            h.cdp.call("Input.dispatchKeyEvent", {"type": kind, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13,
                                                  "text": "\r" if kind == "keyDown" else ""}, h.sid)

    def buttons(self):
        return self.h.ev("[...document.querySelectorAll('.aic button')].map(b=>b.textContent.trim())")

    # ---- the five states
    def test_working(self):
        self.working()
        self.assertEqual(self.h.say(), WORKING)
        self.assertEqual(self.buttons(), ["Stop"])
        self.assertTrue(self.h.until("document.activeElement.textContent === 'Stop'"))      # focus stays on Stop
        self.assertEqual(self.h.ev("document.querySelector('.aic-h').textContent"), "Shorter")

    def test_ready(self):
        self.ready()
        self.assertTrue(self.h.until(f"document.querySelector('.aic-say').textContent.trim() === {READY!r}"))
        self.assertEqual(self.h.say(), READY)
        self.assertEqual(self.buttons(), ["Accept", "Discard", "Try again", "Show changes"])
        self.assertIn("The supplier confirmed", self.h.ev("document.querySelector('.aic-text').textContent"))
        self.assertTrue(self.h.until("document.activeElement.className === 'aic-h'"))     # the result is read first
        self.assertEqual(self.h.ev("window.client.calls.length"), 1)
        self.assertEqual(self.h.ev("JSON.stringify(Object.keys(window.client.calls[0]).sort())"),
                         '["instruction","option","place","text"]')                     # nothing else goes with a request

    def test_failed(self):
        self.h.ev("window.opts.fail = true")
        self.h.card(text=TEXT)
        self.assertTrue(self.h.until("document.querySelector('.aic').dataset.state === 'failed'"))
        self.assertEqual(self.h.say(), FAILED)
        self.assertEqual(self.buttons(), ["Discard", "Try again"])
        self.assertNotRegex(self.h.ev("document.querySelector('.aic').innerText"), r"canned|Error|Exception|JSON")

    def test_off_and_not_signed_in_never_ask(self):
        for state, line in (("off", OFF), ("not_signed_in", NOT_SIGNED_IN)):
            with self.subTest(state=state):
                self.h.ev("window.unmount()")
                self.h.ev(f"window.opts.state = {state!r}")
                self.h.card(text=TEXT)
                self.assertEqual(self.h.state(), state)
                self.assertEqual(self.h.say(), line)
                self.assertEqual(self.buttons(), ["Discard"])
                self.assertEqual(self.h.ev("window.client.calls.length"), 0)          # the provider was not asked
                self.assertTrue(self.h.until("document.activeElement.className === 'aic-h'"))

    def test_the_off_line_is_real_text_at_4_5_to_1(self):
        for theme in ("light", "dark"):
            for width in (1400, 900):
                with self.subTest(theme=theme, width=width):
                    self.h.ev("window.unmount()")
                    self.h.theme(theme)
                    self.h.resize(width)
                    self.h.ev("window.opts.state = 'not_signed_in'")
                    self.h.card(text=TEXT)
                    self.assertGreaterEqual(self.h.ev(CONTRAST % "'.aic-say'"), 4.5)

    # ---- nothing changes before Accept
    def test_nothing_is_applied_before_accept(self):
        self.ready()
        self.assertEqual(self.h.ev("window.applied.length"), 0)
        self.h.tab()                      # moving about the card applies nothing either
        self.h.tab()
        self.assertEqual(self.h.ev("window.applied.length"), 0)
        self.assertEqual(self.h.ev("window.exits.length"), 0)

    def test_accept_applies_the_cleaned_suggestion_once_and_returns_focus(self):
        self.h.ev("window.opts.reply = () => ({html: '<p>Short <strong>one</strong></p><script>alert(1)</script><img src=x onerror=alert(2)>'})")
        self.ready()
        self.assertEqual(self.h.ev("document.querySelectorAll('.aic-text script, .aic-text img').length"), 0)   # drawn cleaned
        self.h.ev("[...document.querySelectorAll('.aic button')].find(b=>b.textContent==='Accept').click()")
        self.assertEqual(self.h.ev("window.applied.length"), 1)
        html = self.h.ev("window.applied[0]")
        self.assertIn("<strong>one</strong>", html)
        self.assertNotRegex(html, r"script|onerror|<img")
        self.assertEqual(self.h.ev("window.exits"), ["accept"])
        self.assertEqual(self.h.active(), "stand")

    def editor_text(self):
        return self.h.ev("document.querySelector('#ed .ProseMirror').textContent")

    def test_with_the_real_editor_nothing_changes_before_accept_and_one_undo_puts_it_back(self):
        h = self.h
        h.ev("window.mountEditor('<p>" + TEXT + "</p>')")
        self.assertTrue(h.until("!!document.querySelector('#ed .ProseMirror')"))
        self.ready()
        self.assertEqual(self.editor_text(), TEXT)                    # the suggestion is shown, the text is not changed
        h.ev("[...document.querySelectorAll('.aic button')].find(b=>b.textContent==='Accept').click()")
        self.assertTrue(h.until("document.querySelector('#ed .ProseMirror').textContent !== " + repr(TEXT)))
        self.assertEqual(self.editor_text(), "The supplier confirmed the delivery for.")
        self.assertTrue(h.ev("document.activeElement === document.querySelector('#ed .ProseMirror')"), "focus returns to the editor")
        h.key("z", h.mod, "KeyZ", 90)                                 # Cmd+Z / Ctrl+Z: one step puts the whole text back
        self.assertTrue(h.until("document.querySelector('#ed .ProseMirror').textContent === " + repr(TEXT)))

    def test_with_the_real_editor_discard_and_esc_leave_the_text_and_focus_the_editor(self):
        h = self.h
        for how in ("discard", "esc"):
            with self.subTest(how=how):
                h.ev("window.unmount(); window.mountEditor('<p>" + TEXT + "</p>')")
                self.ready()
                if how == "discard":
                    h.ev("[...document.querySelectorAll('.aic button')].find(b=>b.textContent==='Discard').click()")
                else:
                    h.key("Escape", 0, "Escape", 27)
                self.assertTrue(h.until("!document.querySelector('.aic')"))
                self.assertEqual(self.editor_text(), TEXT)
                self.assertTrue(h.ev("document.activeElement === document.querySelector('#ed .ProseMirror')"))

    def test_accept_by_keyboard(self):
        self.ready()
        self.h.tab()                                           # heading -> Accept
        self.assertEqual(self.h.ev("document.activeElement.textContent"), "Accept")
        self.enter()
        self.assertEqual(self.h.ev("window.applied.length"), 1)
        self.assertEqual(self.h.active(), "stand")

    def test_accept_does_nothing_while_it_is_working_or_failed(self):
        self.working()
        self.assertEqual(self.h.ev("[...document.querySelectorAll('.aic button')].some(b=>b.textContent==='Accept')"), False)
        self.assertEqual(self.h.ev("window.applied.length"), 0)
        self.h.ev("window.unmount(); window.opts.hold = false; window.opts.fail = true")
        self.h.card(text=TEXT)
        self.assertTrue(self.h.until("document.querySelector('.aic').dataset.state === 'failed'"))
        self.assertEqual(self.h.ev("window.applied.length"), 0)

    def test_discard_changes_nothing_and_returns_focus(self):
        self.ready()
        self.h.ev("[...document.querySelectorAll('.aic button')].find(b=>b.textContent==='Discard').click()")
        self.assertEqual(self.h.ev("window.applied.length"), 0)
        self.assertEqual(self.h.ev("window.exits"), ["discard"])
        self.assertEqual(self.h.active(), "stand")

    def test_esc_closes_from_every_state_and_returns_focus(self):
        for how in ("ready", "working", "failed", "off"):
            with self.subTest(state=how):
                self.h.ev("window.unmount(); window.returned.length = 0; window.exits.length = 0")
                self.h.ev("for (const k of Object.keys(window.opts)) delete window.opts[k]")
                if how == "working":
                    self.working()
                elif how == "failed":
                    self.h.ev("window.opts.fail = true")
                    self.h.card(text=TEXT)
                    self.assertTrue(self.h.until("document.querySelector('.aic').dataset.state === 'failed'"))
                elif how == "off":
                    self.h.ev("window.opts.state = 'off'")
                    self.h.card(text=TEXT)
                else:
                    self.ready()
                self.assertTrue(self.h.until("!!document.activeElement.closest('.aic')"))     # the card has taken focus
                self.h.key("Escape", 0, "Escape", 27)
                self.assertEqual(self.h.ev("window.exits"), ["esc"])
                self.assertEqual(self.h.ev("window.returned"), ["esc"])
                self.assertEqual(self.h.active(), "stand")
                self.assertEqual(self.h.ev("window.applied.length"), 0)

    def test_stop_ends_the_work_and_a_late_reply_is_ignored(self):
        self.working()
        self.h.ev("[...document.querySelectorAll('.aic button')].find(b=>b.textContent==='Stop').click()")
        self.assertEqual(self.h.ev("window.exits"), ["stop"])
        self.assertEqual(self.h.active(), "stand")
        self.h.ev("window.release()")
        self.assertEqual(self.h.ev("window.applied.length"), 0)
        self.assertEqual(self.h.ev("document.querySelectorAll('.aic').length"), 0)

    # ---- keyboard and focus
    def test_tab_order_and_the_card_is_not_a_trap(self):
        self.ready()
        seen = []
        for _ in range(4):
            self.h.tab()
            seen.append(self.h.ev("document.activeElement.textContent"))
        self.assertEqual(seen, ["Accept", "Discard", "Try again", "Show changes"])
        self.h.tab()                                           # leaves the card
        self.assertFalse(self.h.ev("!!document.activeElement.closest('.aic')"))
        self.h.ev("document.querySelector('.aic button').focus()")
        self.h.tab(back=True)                                  # and back out the other way: the card holds nobody
        self.assertEqual(self.h.active(), "stand")

    def test_try_again_keeps_focus_in_the_card_and_asks_again(self):
        self.ready()
        self.h.ev("window.opts.hold = true")
        self.h.ev("[...document.querySelectorAll('.aic button')].find(b=>b.textContent==='Try again').focus()")
        self.enter()
        self.assertTrue(self.h.until("document.querySelector('.aic').dataset.state === 'working'"))
        self.assertTrue(self.h.until("!!document.activeElement.closest('.aic')"))
        self.assertEqual(self.h.say(), WORKING)
        self.h.ev("window.opts.hold = false; window.release()")
        self.assertTrue(self.h.until("document.querySelector('.aic').dataset.state === 'ready'"))
        self.assertTrue(self.h.until("document.activeElement.className === 'aic-h'"))      # the new card takes focus when ready
        self.assertEqual(self.h.ev("window.client.calls.length"), 2)
        self.assertEqual(self.h.ev("window.applied.length"), 0)

    def test_try_again_from_a_failure(self):
        self.h.ev("window.opts.fail = true")
        self.h.card(text=TEXT)
        self.assertTrue(self.h.until("document.querySelector('.aic').dataset.state === 'failed'"))
        self.h.ev("window.opts.fail = false")
        self.h.ev("[...document.querySelectorAll('.aic button')].find(b=>b.textContent==='Try again').click()")
        self.assertTrue(self.h.until("document.querySelector('.aic').dataset.state === 'ready'"))

    def test_show_changes_toggles_and_keeps_focus_on_its_link(self):
        self.ready()
        link = "[...document.querySelectorAll('.aic button')].find(b=>/changes/.test(b.textContent))"
        self.h.ev(link + ".focus()")
        self.enter()
        self.assertEqual(self.h.ev(f"{link}.getAttribute('aria-expanded')"), "true")
        self.assertEqual(self.h.ev(f"{link}.textContent"), "Hide changes")
        self.assertEqual(self.h.ev("document.activeElement.textContent"), "Hide changes")
        self.assertGreater(self.h.ev("document.querySelectorAll('.aic-diff del').length"), 0)
        self.assertEqual(self.h.ev("window.applied.length"), 0)
        self.enter()
        self.assertEqual(self.h.ev(f"{link}.getAttribute('aria-expanded')"), "false")
        self.assertEqual(self.h.ev("document.querySelectorAll('.aic-diff').length"), 0)

    def test_notes_are_listed_under_the_suggestion(self):
        self.h.ev("window.opts.reply = () => ({text: 'Short one', notes: ['The date 12-11-2026 is missing.']})")
        self.ready()
        self.assertIn("The date 12-11-2026 is missing.", self.h.ev("document.querySelector('.aic-notes').textContent"))

    # ---- announcements
    def test_one_polite_live_region_never_assertive(self):
        self.ready()
        self.assertEqual(self.h.ev("document.querySelectorAll('.aic [aria-live]').length"), 1)
        self.assertEqual(self.h.ev("document.querySelector('.aic [aria-live]').getAttribute('aria-live')"), "polite")
        self.assertEqual(self.h.ev("document.querySelectorAll('[aria-live=assertive], [role=alert]').length"), 0)

    def test_the_announcements_in_order(self):
        self.h.ev("window.opts.hold = true")
        self.h.card(text=TEXT)
        self.assertEqual(self.h.say(), WORKING)
        self.h.ev("window.heard = []; new MutationObserver(() => window.heard.push(document.querySelector('.aic-say').textContent.trim()))"
                  ".observe(document.querySelector('.aic-say'), {childList: true, characterData: true, subtree: true})")
        self.h.ev("window.opts.hold = false; window.release()")
        self.assertTrue(self.h.until("document.querySelector('.aic').dataset.state === 'ready'"))
        self.assertTrue(self.h.until(f"document.querySelector('.aic-say').textContent.trim() === {READY!r}"))
        heard = self.h.ev("window.heard.filter((v, i, a) => v && v !== a[i - 1])")
        self.assertEqual(heard[-1], READY)
        self.assertLessEqual(set(heard), {WORKING, READY})
        self.assertEqual(self.h.say(), READY)

    # ---- the look
    def test_inside_the_window_and_roles_only_in_light_and_dark_at_both_widths(self):
        for theme in ("light", "dark"):
            for width in (1400, 900):
                with self.subTest(theme=theme, width=width):
                    self.h.ev("window.unmount()")
                    self.h.theme(theme)
                    self.h.resize(width)
                    self.ready(option="custom", instruction="Say it more kindly and keep the two dates, please, and be brief about it")
                    self.h.ev("[...document.querySelectorAll('.aic button')].find(b=>/changes/.test(b.textContent)).click()")
                    box = self.h.ev("(()=>{const r=document.querySelector('.aic').getBoundingClientRect();"
                                    "return [r.left, r.right, innerWidth, document.documentElement.scrollWidth];})()")
                    self.assertGreaterEqual(box[0], 0)
                    self.assertLessEqual(box[1], box[2])
                    self.assertLessEqual(box[3], box[2])                           # no sideways scroll
                    self.assertGreaterEqual(self.h.ev("Math.min(...[...document.querySelectorAll('.aic button')].map(b=>b.getBoundingClientRect().height))"), 24)
                    self.assertEqual(self.h.ev("""(()=>{
                      const probe = (v) => { const e = document.createElement('i'); e.style.color = `var(${v})`; document.body.append(e); const c = getComputedStyle(e).color; e.remove(); return c; };
                      const bad = new Set(['--status-green','--status-amber','--status-red','--status-grey','--status-green-text','--status-amber-text','--status-red-text'].map(probe));
                      return [...document.querySelectorAll('.aic, .aic *')].filter(e => { const s = getComputedStyle(e); return bad.has(s.color) || bad.has(s.backgroundColor) || bad.has(s.borderTopColor) || bad.has(s.outlineColor); }).length;
                    })()"""), 0)
                    self.assertGreaterEqual(self.h.ev(CONTRAST % "'.aic-say'"), 4.5)
                    self.assertGreaterEqual(self.h.ev(CONTRAST % "'.aic-h'"), 4.5)

    def test_reduced_motion_stops_the_running_state(self):
        self.working()
        self.assertNotEqual(self.h.ev("getComputedStyle(document.querySelector('.aic-dot')).animationName"), "none")
        self.h.cdp.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]}, self.h.sid)
        self.assertEqual(self.h.ev("getComputedStyle(document.querySelector('.aic-dot')).animationName"), "none")
        self.assertEqual(self.h.say(), WORKING)             # the words stay: the state is text, not motion

    def test_the_card_css_uses_tokens_and_no_raw_colour_or_fixed_pixels(self):
        block = CSS[CSS.index("/* The AI suggestion card"):]
        self.assertNotRegex(block, r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl")
        self.assertEqual(sorted(set(re.findall(r"\b\d+px", block))), ["1px", "2px"])      # borders and focus rings only
        self.assertNotRegex(block, r"var\(--status-")

    def test_the_card_has_a_name_and_heading(self):
        self.ready()
        self.assertEqual(self.h.ev("document.querySelector('.aic').getAttribute('aria-label')"), "Suggestion: Shorter")
        self.assertEqual(self.h.ev("document.querySelector('.aic-h').tagName"), "H3")


if __name__ == "__main__":
    unittest.main()
