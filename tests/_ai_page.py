"""Shared by test_ai_card.py (#72): the AI suggestion card on a bare page with a stub client. Not a test file.

Same shape as _rich_page.Harness (the real component bundled the way build_page builds the page, the page's own CSS, headless Chrome
through test_server.chrome). The page offers:
  mount(cfg)       draws AiCard for {option, place, text, instruction}; window.applied has every html passed to onAccept, window.exits
                   every way the card closed, window.opts is the stub's settings (state, fail, hold, delay, reply), window.release()
  #stand           a focusable stand-in for the editor: returnTo() focuses it
Fictional text only.
"""
import json
import tempfile
from pathlib import Path

from _paths import TOOLS
from _rich_page import CTRL, META, Harness, PAGE_SRC, wait_for

import sys
sys.path.insert(0, str(TOOLS))
import build_page  # noqa: E402
import esbuild  # noqa: E402

ENTRY = """import { render } from "preact";
import { AiCard } from %(card)s;
import { stubAiClient } from %(client)s;
import { clarkEditor } from %(editor)s;
import { forEditor } from %(html)s;
window.opts = {};
window.client = stubAiClient(window.opts);
window.release = () => window.client.release();
window.applied = []; window.exits = []; window.returned = [];
const root = document.getElementById("root");
window.unmount = () => render(null, root);
// The real editor, for the Accept and Undo test: mountEditor(html) draws it in #ed; useEditor = true makes Accept replace the editor's whole
// text with the suggestion in one editor step (one transaction), and Esc/Discard/Accept return focus to it.
window.useEditor = false;
window.mountEditor = (html) => {
  window.handle && window.handle.destroy();
  const el = document.getElementById("ed"); el.innerHTML = "";
  window.handle = clarkEditor(el, { profile: "rich", html });
  window.useEditor = true;
};
const focusTarget = () => (window.useEditor ? window.handle.editor.view.dom : document.getElementById("stand"));
const applyAccepted = (h) => {
  window.applied.push(h);
  if (window.useEditor) { const ed = window.handle.editor; ed.chain().insertContentAt({ from: 0, to: ed.state.doc.content.size }, forEditor(h)).run(); }
};
window.mount = (cfg) => {
  render(null, root);
  render(<AiCard client={window.client} place={cfg.place || "current"} option={cfg.option || "shorter"} text={cfg.text}
    instruction={cfg.instruction || ""}
    returnTo={cfg.noReturn ? null : (how) => { window.returned.push(how); focusTarget().focus(); }}
    onAccept={applyAccepted}
    onClose={(how) => { window.exits.push(how); render(null, root); }} />, root);
};
"""


def bundle(tmp):
    q = lambda *p: json.dumps(str(PAGE_SRC.joinpath(*p)))  # noqa: E731
    entry = Path(tmp) / "entry.jsx"
    entry.write_text(ENTRY % {"card": q("edit", "AiCard.jsx"), "client": q("edit", "aiClient.js"),
                                                          "editor": q("core", "editor.js"), "html": q("core", "richHtml.js")}, encoding="utf-8")
    out = Path(tmp) / "ai.js"
    args = ["--bundle", "--format=iife", "--target=es2020", "--tsconfig-raw={}", "--loader:.jsx=jsx", *build_page.preact_flags(),
            str(entry), f"--outfile={out}"]
    done = esbuild.run(args, cwd=PAGE_SRC, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return out.read_text(encoding="utf-8")


class AiHarness(Harness):
    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        (tmp / "ai.js").write_text(bundle(tmp), encoding="utf-8")
        css = build_page.page_css(build_page.ENTRY)        # the served page's CSS: it holds the Edit parts' (edit.css)
        (tmp / "page.html").write_text(f"<!doctype html><meta charset=utf-8><style>{css}</style>"
                                       "<body><div id=stand tabindex=0>The editor stands here.</div><div id=ed></div><div id=root></div>"
                                       "<script src=ai.js></script></body>", encoding="utf-8")
        self.chrome = self.launch()
        self.cdp = self.chrome.__enter__()
        tid = next(t["targetId"] for t in self.cdp.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
        self.sid = self.cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
        self.cdp.call("Page.enable", {}, self.sid)
        self.resize(1400)
        self.cdp.call("Page.navigate", {"url": (tmp / "page.html").as_uri()}, self.sid)
        assert wait_for(lambda: self.ev("typeof window.mount === 'function'") is True, 60), "the page's script did not load"
        self.mod = META if self.ev("/Mac/.test(navigator.platform)") else CTRL        # ProseMirror's Mod key
        return self

    def card(self, **cfg):
        self.ev(f"window.mount({json.dumps(cfg)})")
        assert self.until("!!document.querySelector('.aic')"), "the card did not open"

    def state(self):
        return self.ev("(document.querySelector('.aic')||{dataset:{}}).dataset.state")

    def say(self):
        """The status line, once the card has said something."""
        self.until("document.querySelector('.aic-say') && document.querySelector('.aic-say').textContent.trim() !== ''")
        return self.ev("document.querySelector('.aic-say').textContent.trim()")

    def active(self):
        """What has focus: the class, or id, or button text."""
        return self.ev("(()=>{const a=document.activeElement;return a.id||a.className||a.tagName;})()")

    def tab(self, back=False):
        self.key("Tab", 8 if back else 0, "Tab", 9)
