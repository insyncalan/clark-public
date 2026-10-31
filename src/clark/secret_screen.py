"""ask: a plain-code screen for secrets in text read from a saved folder (#215). No model, no file, no network, no logging.
Standard library only.

ONE LIST. The shapes are the publish scan's own (`dev/tools/publish_public.py`, SECRET_PATTERNS, GENERIC_SECRET and
UNQUOTED_SECRET), written here as text because that tool is a development tool that is not shipped; a test compares the two
lists, so they cannot drift apart. The question screen `ask.looks_like_secret` is used too (named secrets with a value, long
mixed runs, web addresses with a password), on the text as the client check sees it (hidden characters and look-alike letters
undone).

THE SAFE CHOICE. If any of it matches, the WHOLE file is left out, never part of it. The caller counts it and names its label
and the reason; the matched text is not kept, not returned and not put in an error. The file is read two ways (as it is and
with line breaks taken out), so a secret that a line break or a Word run cut in two is
still caught. The cost is fixed by the size: every pattern is a single pass with no nested repeats, and base64 runs are
looked at up to a cap, past which the file counts as a hit (fail closed).
"""
import base64
import re

from clark import ask

REASON = "looks like it holds a secret"
NEXT_STEP = "Remove the secret from the file or move it out of the saved folder."
MAX_RUNS = 2000                      # base64-looking runs looked at in one file; more than this counts as a hit

SECRET_PATTERNS = (
    ("a private key", r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY"),
    ("a GitHub token", r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,})"),
    ("an AWS access key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("a Slack token", r"\bxox[baprs]-[A-Za-z0-9-]{8,}"),
    ("a JSON web token", r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ("an Anthropic or OpenAI key", r"\bsk-(?:ant-|proj-|svcacct-|admin-)[A-Za-z0-9_-]{8,}|\bsk-[A-Za-z0-9]{32,}"),
    ("a Stripe live key", r"\b[sr]k_live_[A-Za-z0-9]{8,}"),
    ("a Google API key", r"\bAIza[0-9A-Za-z_-]{30,}"),
    ("an npm token", r"\bnpm_[A-Za-z0-9]{20,}|_authToken\s*=\s*[A-Za-z0-9][^\s$\x22']{15,}"),
    ("a PyPI token", r"\bpypi-[A-Za-z0-9_-]{20,}"),
    ("a password in an address", r"[A-Za-z][A-Za-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@[^/\s]"),
    ("an authorization header", r"(?i)authorization\s*[:=]\s*[\x22']?(?:bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{8,}"),
)
GENERIC_SECRET = r"""(?i)(?:api[_-]?key|secret|token|passw(?:or)?d|pwd)["']?\s*[:=]\s*["']([^"'\s]{16,})["']"""
UNQUOTED_SECRET = r"""(?i)(?:api[_-]?key|secret|token|(passw(?:or)?d|pwd))\w*["']?[ \t]*[:=][ \t]*([^\s"'`$<>{}()\[\],;]{8,})"""
BASE64_RUN = r"[A-Za-z0-9+/_-]{24,}"

# The publish scan's address shape starts at every letter and can take a long time on a long run of letters, so here it starts at
# the "://" instead (the same addresses are found).
ADDRESS_KIND = "a password in an address"
ADDRESS_LINEAR = r"[A-Za-z0-9+.-]://[^/\s:@]+:[^/\s@]+@[^/\s]"
_SHAPES = tuple(re.compile(ADDRESS_LINEAR if k == ADDRESS_KIND else p) for k, p in SECRET_PATTERNS)
_GENERIC = re.compile(GENERIC_SECRET)
_UNQUOTED = re.compile(UNQUOTED_SECRET)
_RUN = re.compile(BASE64_RUN)
_BYTE_SHAPES = tuple(re.compile((ADDRESS_LINEAR if k == ADDRESS_KIND else p).encode("ascii")) for k, p in SECRET_PATTERNS)
_BREAKS = re.compile(r"[\r\n]+")


def _mixed(value):
    return bool(re.search(r"[0-9]", value) and re.search(r"[A-Za-z]", value))


def _in_base64(text):
    for i, m in enumerate(_RUN.finditer(text)):
        if i >= MAX_RUNS:
            return True                                   # too many to look at: leave the file out
        run = m.group().replace("-", "+").replace("_", "/")
        for offset in range(4):
            chunk = run[offset:]
            chunk = chunk[:len(chunk) - len(chunk) % 4]
            if len(chunk) < 24:
                continue
            try:
                plain = base64.b64decode(chunk)
            except ValueError:
                continue
            if any(rx.search(plain) for rx in _BYTE_SHAPES):
                return True
    return False


def _one(text):
    if any(rx.search(text) for rx in _SHAPES):
        return True
    for m in _GENERIC.finditer(text):
        if _mixed(m.group(1)):
            return True
    for m in _UNQUOTED.finditer(text):
        if len(m.group(2)) >= (8 if m.group(1) else 16) and _mixed(m.group(2)):
            return True
    return _in_base64(text) or ask.looks_like_secret(text)


def looks_like_secret(text):
    """Whether `text` looks like it holds a secret. Never raises, never keeps or returns what matched; text that cannot be
    read as a string counts as a hit."""
    if not isinstance(text, str):
        return True
    try:
        return _one(text) or _one(_BREAKS.sub("", text))
    except (RecursionError, MemoryError, ValueError):
        return True                                       # fail closed
