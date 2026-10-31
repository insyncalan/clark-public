"""Tech debt #203: in Edit, the Work items cells that change in place (owner, due, priority, status) are not cramped.

Run: python3 dev/run_tests.py test_edit_cells_layout
The real page and a real server over the fictional demo data, at 1400 and 900 px, light and dark: in each Edit cell the caret stays
beside the value (the box is no taller than the value, never a second line for the caret), a priority, a status or a due date is
on one line, and no word of it (the date's hyphens included) is broken in the middle, an owner's name breaks only between words, and the Type pill ("Dependency")
is on one line. The browser parts are required: they fail, never skip, without Chrome (set CLARK_CHROME to its path).
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _paths import SRC  # noqa: F401  (puts src/ on the path)

from clark import page, server as sv  # noqa: E402
from clark.store import open_store  # noqa: E402
from test_server import CHROME, Running, chrome, wait  # noqa: E402
from test_work_items import FIXED_DATE, load_demo, page_target  # noqa: E402

EMPTY_BRANDING = tempfile.mkdtemp(prefix="clark-no-brand-")

# One look at every Edit cell: its field, the value's box and lines, and whether the value is broken inside a word.
MEASURE = r"""(() => {
  const out = [];
  for (const b of document.querySelectorAll('table.items .cell-pick')) {
    const v = b.querySelector('.cell-val') || b, field = b.dataset.cell.split(':').pop();
    // how far anything inside the value reaches past the value's own box (a pill that runs on into the caret)
    const spill = (node) => { const r = document.createRange(); r.selectNodeContents(node); const right = Math.max(0, ...[...node.querySelectorAll('*'), node].flatMap((e) => [...e.getClientRects()].map((x) => x.right))); const rr = [...r.getClientRects()].map((x) => x.right); return Math.round(Math.max(right, ...rr) - node.getBoundingClientRect().right); };
    const lines = (node) => { const r = document.createRange(); r.selectNodeContents(node); return new Set([...r.getClientRects()].filter((x) => x.width > 0).map((x) => Math.round(x.top))).size; };
    // a word is broken when a single word of the value spans two lines: measure each word on its own
    let broken = 0;
    const walker = document.createTreeWalker(v, NodeFilter.SHOW_TEXT); let n;
    while ((n = walker.nextNode())) { const re = /\S+/g; let m; while ((m = re.exec(n.textContent))) { const r = document.createRange(); r.setStart(n, m.index); r.setEnd(n, m.index + m[0].length); if (new Set([...r.getClientRects()].filter((x) => x.width > 0).map((x) => Math.round(x.top))).size > 1) broken++; } }
    out.push({ field, text: v.textContent.trim().slice(0, 30), pick: Math.round(b.getBoundingClientRect().height), val: Math.round(v.getBoundingClientRect().height),
               lines: lines(v), broken, over: b.scrollWidth > b.clientWidth + 1, spill: spill(v) });
  }
  const pills = [...document.querySelectorAll('table.items td.c-type .tag, table.items td.c-type .pill')].map((p) => ({ text: p.textContent.trim(), h: Math.round(p.getBoundingClientRect().height), broken: (() => { const r = document.createRange(); r.selectNodeContents(p); return new Set([...r.getClientRects()].filter((x) => x.width > 0).map((x) => Math.round(x.top))).size > 1; })() }));
  return JSON.stringify({ cells: out, pills, sw: document.documentElement.scrollWidth, vw: innerWidth });
})()"""


def tearDownModule():
    shutil.rmtree(EMPTY_BRANDING, ignore_errors=True)


class Cells(unittest.TestCase):
    def setUp(self):
        assert Path(CHROME).is_file(), f"Google Chrome is needed for the required browser tests ({CHROME}); set CLARK_CHROME"
        self.store, self.folder, _ = load_demo()
        self.addCleanup(shutil.rmtree, str(self.folder), True)
        self.addCleanup(self.store.close)
        self.path = self.folder / "clark.db"
        self.s = Running(data_for=self.read, projects=lambda: [{"code": "TUL", "name": "Tulip"}], page_html=lambda: page.page_html(EMPTY_BRANDING))
        self.addCleanup(self.s.close)
        quiet = mock.patch.object(sv.LOG, "disabled", True)
        quiet.start()
        self.addCleanup(quiet.stop)

    def read(self, code):
        st = open_store(self.path, onedrive_roots=[])
        try:
            return st.data_for(code)
        finally:
            st.close()

    def measure(self, cdp, width, theme):
        sid = page_target(cdp)
        cdp.call("Page.enable", {}, sid)
        cdp.call("Page.addScriptToEvaluateOnNewDocument", {"source": FIXED_DATE}, sid)
        cdp.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False}, sid)
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{self.s.port}/#work&p=TUL&f=mode:all"}, sid)
        self.assertTrue(wait(lambda: cdp.js("document.querySelectorAll('#work tbody tr').length", sid) > 0), "the list drew")
        cdp.js(f"document.documentElement.dataset.theme = {json.dumps(theme)}", sid)
        cdp.js("document.querySelector('[data-mode=edit]').click()", sid)
        self.assertTrue(wait(lambda: cdp.js("!!document.querySelector('table.items .cell-pick')", sid)), "Edit shows the cells' pickers")
        return json.loads(cdp.js(MEASURE, sid))

    def test_every_edit_cell_is_one_tidy_box_at_both_widths_in_both_looks(self):
        with chrome() as cdp:
            for width in (1400, 900):
                for theme in ("light", "dark"):
                    got = self.measure(cdp, width, theme)
                    where = f"{width} px, {theme}"
                    fields = {c["field"] for c in got["cells"]}
                    self.assertEqual(fields, {"owner", "due", "priority", "status"}, where + ": every kind of cell is on the page")
                    for c in got["cells"]:
                        label = f"{where}: {c['field']} '{c['text']}'"
                        self.assertEqual(c["broken"], 0, label + " has a word broken in the middle")
                        self.assertFalse(c["over"], label + " runs outside its box")
                        self.assertLessEqual(c["spill"], 1, label + " runs past its value box into the caret")
                        self.assertLessEqual(c["pick"] - c["val"], 12, label + ": the caret has a line of its own (the box is taller than the value)")
                        if c["field"] in ("priority", "status"):
                            self.assertLessEqual(c["val"], 30, label + " is not on one line")
                        if c["field"] == "due":
                            self.assertLessEqual(c["val"], 48, label + " is taller than the date and its 'In n days' line")
                        if c["field"] == "owner":
                            self.assertLessEqual(c["val"], 56, label + " is taller than two lines of a name")
                    for p in got["pills"]:
                        self.assertFalse(p["broken"], f"{where}: the Type pill '{p['text']}' is broken across lines")
                    self.assertLessEqual(got["sw"], got["vw"], where + ": the page does not scroll sideways")   # not equal: a page with a scroll bar of its own (Linux) is a little narrower


if __name__ == "__main__":
    unittest.main()
