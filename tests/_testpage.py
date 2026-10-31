"""The page the browser tests load (#42): the served page's sources plus the test hook `window.clarkPage` (src/.../testhook.js),
built from main-test.jsx. The committed page.html carries no hook, so no client file does. Needs the pinned esbuild, as the
router tests already do; built once per run."""
from _paths import TOOLS
import sys

sys.path.insert(0, str(TOOLS))
import build_page  # noqa: E402

_built = []


def html(branding=None):
    """The test page as text (the demo brand only; the tests that use it pass no brand of their own)."""
    if not _built:
        _built.append(build_page.build("main-test.jsx"))
    return _built[0]
