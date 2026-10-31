"""Fill the user's own Word template ({{NAME}} placeholders) (#219, part of #48).

A pure function: `fill(template, values, name)` takes the template's bytes and a dict of names to text and returns the filled
file's bytes. It opens no file and no network. `fill_to_file` is the one small helper that writes, and only when the whole fill
has succeeded, so a refusal leaves nothing behind.

Rules:
- A placeholder is two braces, a name and two braces: {{PROJECT_NAME}}. A name is letters, digits and underscores, starting with
  a letter. A placeholder may be split across several runs in Word; it is found and filled all the same.
- Only the main text (word/document.xml, tables included) is filled. Every other part is copied byte for byte, in the same order,
  with the same date and storage. A placeholder in a header, footer, footnote, endnote or comment is not filled, so it stops the
  fill: Not filled: NAME. Nothing was written.
- A placeholder with no value, or whose name is not a valid name, stops the fill. Values are written as text, with < > & escaped.
- A template is opened with the same safety rules as any Word file (docx_read): size limits, no odd file names, no macros, no
  embedded or linked files, and no entity of any kind in the XML. A refusal is a WordRefused in plain words naming the file.
Standard library only, Python 3.9.
"""
import io
import os
import re
import zipfile

from clark import docx_read as _r
from clark import platform
from clark.docx_read import WordRefused

MAX_VALUE = 100_000                                  # characters in one value
PLACEHOLDER = re.compile(r"\{\{(.*?)\}\}", re.S)
VALID_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
TEXT_ELEMENT = re.compile(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>")
PARAGRAPH = re.compile(r"<w:p(?:\s[^>]*)?>.*?</w:p>", re.S)
OTHER_TEXT_PARTS = re.compile(r"^word/(header|footer|footnotes|endnotes|comments)[^/]*\.xml$")
BAD_XML_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


class NotFilled(ValueError):
    """The fill stopped. Nothing was written."""


def _not_filled(names, where=""):
    shown = ", ".join(sorted(set(names)))
    return NotFilled(f"Not filled: {shown}{where}. Nothing was written.")


def _escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _value_xml(value):
    """The value as the content of a w:t element; a line break becomes a Word line break."""
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return '</w:t><w:br/><w:t xml:space="preserve">'.join(_escape(x) for x in lines)


def _check_values(values):
    if not isinstance(values, dict):
        raise NotFilled("Not filled: no values were given. Nothing was written.")
    for k, v in values.items():
        if not isinstance(k, str) or not VALID_NAME.match(k) or not isinstance(v, str):
            raise NotFilled(f"Not filled: {k!r} is not a name with text. Nothing was written.")
        if len(v) > MAX_VALUE:
            raise NotFilled(f"Not filled: {k} is longer than {MAX_VALUE} characters. Nothing was written.")
        if BAD_XML_CHARS.search(v):
            raise NotFilled(f"Not filled: {k} has characters Word can't hold. Nothing was written.")


def _fill_paragraph(par, values, missing):
    """The paragraph's XML with every placeholder in its text filled; names with no value are added to `missing`."""
    texts = list(TEXT_ELEMENT.finditer(par))
    joined = "".join(m.group(1) for m in texts)
    found = list(PLACEHOLDER.finditer(joined))
    if not found:
        return par
    starts, pos = [], 0                               # where each w:t's text begins in the joined text
    for m in texts:
        starts.append(pos)
        pos += len(m.group(1))
    new = [m.group(1) for m in texts]
    for hit in reversed(found):
        name = hit.group(1)
        if not VALID_NAME.match(name) or name not in values:
            missing.append(name.strip() or "{{}}")
            continue
        a, b = hit.span()
        first = next(i for i, t in enumerate(texts) if starts[i] + len(t.group(1)) > a)   # the first run the placeholder touches
        for i in range(len(texts)):
            lo, hi = starts[i], starts[i] + len(texts[i].group(1))
            if hi <= a or lo >= b:
                continue
            cut_a, cut_b = max(a, lo) - lo, min(b, hi) - lo
            ins = _value_xml(values[name]) if i == first else ""
            new[i] = new[i][:cut_a] + ins + new[i][cut_b:]
    out, last = [], 0
    for m, text in zip(texts, new):
        tag = par[m.start():m.start(1)]
        if text != m.group(1) and "xml:space" not in tag:
            tag = tag[:-1] + ' xml:space="preserve">'
        out.append(par[last:m.start()] + tag + text + "</w:t>")
        last = m.end()
    out.append(par[last:])
    return "".join(out)


def _fill_main(xml, values, name):
    outside = re.sub(r"<[^>]*>", "", PARAGRAPH.sub("", xml))
    unreached = [m.group(1) for m in PLACEHOLDER.finditer(outside)]     # text the paragraph scan can't reach
    if unreached:
        raise _not_filled(unreached)
    missing = []
    text = PARAGRAPH.sub(lambda m: _fill_paragraph(m.group(0), values, missing), xml)
    if missing:
        raise _not_filled(missing)
    return text


def _open(template, name):
    """The template's directory entries after the same safety checks docx_read makes; the open zip."""
    if not isinstance(template, (bytes, bytearray)) or not template:
        raise _r._damaged(name)
    template = bytes(template)
    if len(template) > _r.MAX_FILE_BYTES:
        raise _r._too_big(name, "file", len(template), _r.MAX_FILE_BYTES)
    if template.startswith(_r.OLE_SIGNATURE):
        raise _r._password(name)
    try:
        z = zipfile.ZipFile(io.BytesIO(template))
        infos = z.infolist()
    except (zipfile.BadZipFile, EOFError, OverflowError, NotImplementedError, RuntimeError, ValueError, OSError):
        raise _r._damaged(name) from None
    return z, infos


def fill(template, values, name="The template"):
    """The template (bytes) with each {{NAME}} in its main text replaced by values["NAME"]; returns the new file's bytes.
    Raises WordRefused (an unsafe or unreadable template) or NotFilled (a name with no value); nothing is returned then."""
    _check_values(values)
    z, infos = _open(template, name)
    with z:
        _r._check_names_and_sizes(name, infos)
        names = {i.filename for i in infos}
        for n in sorted(names):
            if _r.MACRO_NAME.search(n):
                raise _r._macros_or_objects(name, "vba")
            if _r.EMBED_NAME.search(n):
                raise _r._macros_or_objects(name, "oleobject")
        if "[Content_Types].xml" not in names or "word/document.xml" not in names:
            raise WordRefused(f"{name} is not a Word document: it has no main text.")
        main = _r._check_types(name, _r._part(z, name, "[Content_Types].xml", _r.SMALL_PART_BYTES))
        if "wordprocessingml" not in main.lower():
            raise WordRefused(f"{name} is not a Word document: it has no main text.")
        for n in sorted(names):
            if n.endswith(".rels"):
                _r._check_rels(name, _r._part(z, name, n, _r.SMALL_PART_BYTES))
        data = {i.filename: _r._part(z, name, i.filename) for i in infos}
    stray = []
    for n in sorted(data):
        if OTHER_TEXT_PARTS.match(n):
            _r._run(name, data[n])
            stray += [m.group(1) for m in PLACEHOLDER.finditer(re.sub(r"<[^>]*>", "", data[n].decode("utf-8")))]
    if stray:
        raise _not_filled(stray, " (in a header, footer, note or comment, which are not filled)")
    raw = data["word/document.xml"]
    _r._run(name, raw)                                # the same hostile-XML checks as reading
    filled = _fill_main(raw.decode("utf-8"), values, name).encode("utf-8")
    if len(filled) > _r.MAX_PART_BYTES:
        raise _r._too_big(name, "part", len(filled), _r.MAX_PART_BYTES)
    data["word/document.xml"] = filled
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as w:
        for i in infos:
            zi = zipfile.ZipInfo(i.filename, i.date_time)
            zi.compress_type, zi.external_attr, zi.create_system = i.compress_type, i.external_attr, i.create_system
            zi.comment, zi.extra = i.comment, b""
            w.writestr(zi, data[i.filename])
    return out.getvalue()


def fill_to_file(template_path, target_path, values):
    """Fill the template file into a new file at target_path, only if the whole fill succeeds. Never replaces a file. The file is
    placed by platform.write_file_unless_exists, which also works on a disk that cannot hard-link (a cloud-synced or network folder)."""
    with open(template_path, "rb") as f:
        result = fill(f.read(), values, os.path.basename(template_path))
    if not platform.write_file_unless_exists(target_path, result):
        raise NotFilled(f"{os.path.basename(target_path)} already exists. Nothing was written.")
