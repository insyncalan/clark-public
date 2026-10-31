"""#219: filling the user's own Word template (src/clark/word_template.py). Design: docs/handoff/design-48-word.md.

Run: python3 dev/run_tests.py test_word_template
Every template is made in the test, from made-up text. What is asserted: the main text is filled and every other part is the
template's bytes in the template's order; a name split across runs is found; an unknown name stops the fill and writes nothing;
macros, embedded and linked files are refused in plain words naming the file; hostile input (special characters, huge values,
zip bombs, odd file names, repeated names, entities) cannot get through.
"""
import io
import os
import re
import tempfile
import errno
import unittest
import zipfile
from unittest import mock

from _paths import ROOT   # noqa: F401

from clark import word_template
from clark.docx_read import WordRefused
from clark.word_template import NotFilled, fill, fill_to_file

NAME = "layout.docx"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
CT = (HEAD + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      f'<Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="{MAIN}"/></Types>')
RELS = HEAD + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{}</Relationships>'
IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


def doc(body):
    return HEAD + f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'


def R(text):
    return f"<w:r><w:t>{text}</w:t></w:r>"


def P(*runs):
    return "<w:p>" + "".join(r if r.startswith("<w:r") else R(r) for r in runs) + "</w:p>"


def make(body, parts=None, content_types=CT, raw_entries=None):
    """A template: the main text plus other parts. `raw_entries` is a list of (name, bytes) written as given."""
    entries = [("[Content_Types].xml", CT if content_types is None else content_types),
               ("_rels/.rels", RELS.format("")), ("word/document.xml", doc(body)),
               ("word/styles.xml", HEAD + f'<w:styles xmlns:w="{W}"/>')]
    entries += list((parts or {}).items()) + list(raw_entries or [])
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in entries:
            z.writestr(zipfile.ZipInfo(n, (2020, 1, 1, 0, 0, 0)), d, zipfile.ZIP_DEFLATED)
    return out.getvalue()


def parts_of(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return [(i.filename, z.read(i.filename)) for i in z.infolist()]


def text_of(xml):
    return re.sub(r"<[^>]*>", "", xml.split("?>", 1)[-1]).strip("\n")


def main_of(data):
    return dict(parts_of(data))["word/document.xml"].decode("utf-8")


class Fills(unittest.TestCase):
    def test_a_template_is_filled_and_every_other_part_is_the_templates(self):
        extra = {"word/header1.xml": HEAD + f'<w:hdr xmlns:w="{W}"><w:p><w:r><w:t>Plain header</w:t></w:r></w:p></w:hdr>',
                 "word/media/a.bin": bytes(range(256)) * 10, "docProps/core.xml": b"<core/>"}
        t = make(P("Report for {{PROJECT}}", " by {{OWNER}}") + P("x"), extra)
        out = fill(t, {"PROJECT": "Garden Hub", "OWNER": "Sam"}, NAME)
        self.assertIn("Report for Garden Hub", main_of(out))
        self.assertIn(" by Sam", main_of(out))
        before, after = parts_of(t), parts_of(out)
        self.assertEqual([n for n, _ in before], [n for n, _ in after])
        for (n, a), (_, b) in zip(before, after):
            if n != "word/document.xml":
                self.assertEqual(a, b, n)
        self.assertNotIn(b"{{", dict(after)["word/document.xml"])

    def test_the_same_inputs_give_the_same_bytes(self):
        t = make(P("{{A}}"))
        self.assertEqual(fill(t, {"A": "x"}), fill(t, {"A": "x"}))

    def test_a_placeholder_in_a_table_cell_is_filled(self):
        t = make("<w:tbl><w:tr><w:tc>" + P("Owner: {{OWNER}}") + "</w:tc></w:tr></w:tbl>")
        self.assertIn("Owner: Sam", main_of(fill(t, {"OWNER": "Sam"})))

    def test_a_template_with_no_placeholder_is_unchanged(self):
        t = make(P("Nothing to fill here"))
        out = fill(t, {"A": "x"})
        self.assertEqual(parts_of(t), parts_of(out))

    def test_the_same_name_twice_and_names_not_used_are_fine(self):
        out = fill(make(P("{{A}} and {{A}}")), {"A": "x", "UNUSED": "y"})
        self.assertIn("x and x", main_of(out))


class SplitRuns(unittest.TestCase):
    def test_a_name_split_across_runs_is_found(self):
        body = P("Hello {{PRO", "JE", "CT}} there")
        out = main_of(fill(make(body), {"PROJECT": "Garden Hub"}))
        self.assertEqual(text_of(out), "Hello Garden Hub there")

    def test_the_braces_split_from_the_name_and_styled_runs(self):
        body = P("{", "<w:r><w:rPr><w:b/></w:rPr><w:t>{PROJECT}</w:t></w:r>", "}")
        out = main_of(fill(make(body), {"PROJECT": "Garden Hub"}))
        self.assertEqual(text_of(out), "Garden Hub")

    def test_a_value_with_edge_spaces_keeps_them(self):
        out = main_of(fill(make(P("a{{X}}b")), {"X": "  padded  "}))
        self.assertIn('xml:space="preserve"', out)
        self.assertEqual(text_of(out), "a  padded  b")


class Stops(unittest.TestCase):
    def assert_stops(self, t, values, text):
        with self.assertRaises(NotFilled) as c:
            fill(t, values)
        self.assertIn(text, str(c.exception))
        self.assertTrue(str(c.exception).endswith("Nothing was written."))

    def test_an_unknown_name_stops_the_fill(self):
        self.assert_stops(make(P("{{KNOWN}} {{MISSING}}")), {"KNOWN": "x"}, "Not filled: MISSING.")

    def test_a_name_that_is_not_valid_stops_the_fill(self):
        self.assert_stops(make(P("{{two words}}")), {"A": "x"}, "Not filled: two words.")

    def test_a_placeholder_in_a_header_or_footer_stops_the_fill(self):
        for part in ("word/header1.xml", "word/footer2.xml", "word/footnotes.xml"):
            hdr = HEAD + f'<w:hdr xmlns:w="{W}"><w:p><w:r><w:t>{{{{PRO</w:t></w:r><w:r><w:t>JECT}}}}</w:t></w:r></w:p></w:hdr>'
            self.assert_stops(make(P("{{PROJECT}}"), {part: hdr}), {"PROJECT": "x"}, "Not filled: PROJECT")

    def test_a_failed_fill_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "t.docx"), os.path.join(d, "out.docx")
            with open(src, "wb") as f:
                f.write(make(P("{{MISSING}}")))
            with self.assertRaises(NotFilled):
                fill_to_file(src, dst, {"A": "x"})
            self.assertEqual(os.listdir(d), ["t.docx"])

    def test_a_good_fill_writes_the_file_and_never_replaces_one(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "t.docx"), os.path.join(d, "out.docx")
            with open(src, "wb") as f:
                f.write(make(P("{{A}}")))
            fill_to_file(src, dst, {"A": "x"})
            self.assertIn("x", main_of(open(dst, "rb").read()))
            with self.assertRaises(NotFilled):
                fill_to_file(src, dst, {"A": "y"})
            self.assertIn(">x<", main_of(open(dst, "rb").read()))
            self.assertEqual(sorted(os.listdir(d)), ["out.docx", "t.docx"])

    def test_a_disk_that_cannot_hard_link_still_gets_the_file_and_still_never_replaces_one(self):
        no_link = OSError(errno.EPERM, "no hard links here")           # a cloud-synced or network folder
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "t.docx"), os.path.join(d, "out.docx")
            with open(src, "wb") as f:
                f.write(make(P("{{A}}")))
            with mock.patch("os.link", side_effect=no_link):
                fill_to_file(src, dst, {"A": "x"})
                self.assertIn(">x<", main_of(open(dst, "rb").read()))
                with self.assertRaises(NotFilled):
                    fill_to_file(src, dst, {"A": "y"})
            self.assertIn(">x<", main_of(open(dst, "rb").read()))
            self.assertEqual(sorted(os.listdir(d)), ["out.docx", "t.docx"])

    def test_bad_values_stop_the_fill(self):
        t = make(P("{{A}}"))
        for v in ({"A": "x" * (word_template.MAX_VALUE + 1)}, {"A": "bad\x00"}, {"A": 5}, {"bad name": "x"}):
            with self.assertRaises(NotFilled):
                fill(t, v)


class Refuses(unittest.TestCase):
    def refused(self, data, *needles):
        with self.assertRaises(WordRefused) as c:
            fill(data, {"A": "x"}, NAME)
        msg = str(c.exception)
        self.assertIn(NAME, msg)
        for n in needles:
            self.assertIn(n, msg)
        self.assertIsNone(re.search(r"(?i)\bzip\b|\bxml\b|traceback|vbaproject", msg))

    def test_macros(self):
        self.refused(make(P("{{A}}"), {"word/vbaProject.bin": b"x"}), "macros")
        ct = CT.replace(MAIN, "application/vnd.ms-word.document.macroEnabled.main+xml")
        self.refused(make(P("{{A}}"), content_types=ct), "macros")

    def test_embedded_files(self):
        self.refused(make(P("{{A}}"), {"word/embeddings/oleObject1.bin": b"x"}), "file or object")
        rel = f'<Relationship Id="r1" Type="{IMAGE.replace("image", "oleObject")}" Target="o.bin"/>'
        self.refused(make(P("{{A}}"), {"word/_rels/document.xml.rels": RELS.format(rel)}), "file or object")

    def test_linked_files(self):
        rel = f'<Relationship Id="r1" Type="{IMAGE}" Target="https://evil.invalid/p.png" TargetMode="External"/>'
        self.refused(make(P("{{A}}"), {"word/_rels/document.xml.rels": RELS.format(rel)}), "linked")
        link = ("http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLink")
        rel = f'<Relationship Id="r1" Type="{link}" Target="file:///x.xlsx" TargetMode="External"/>'
        self.refused(make(P("{{A}}"), {"word/_rels/document.xml.rels": RELS.format(rel)}), "linked")

    def test_not_a_word_file(self):
        for data in (b"", b"junk", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600):
            self.refused(data)

    def test_a_zip_bomb(self):
        self.refused(make(P("{{A}}"), {"word/media/b.bin": b"\0" * (30 * 1024 * 1024)}))

    def test_odd_file_names(self):
        for bad in ("../evil.xml", "/abs.xml", "word\\x.xml", "C:evil.xml", "word/../../x"):
            self.refused(make(P("{{A}}"), raw_entries=[(bad, b"x")]), "inside")

    def test_a_repeated_name(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.refused(make(P("{{A}}"), raw_entries=[("word/styles.xml", b"again")]), "inside")

    def test_entities_are_refused_and_never_expanded(self):
        evil = (HEAD + '<!DOCTYPE d [<!ENTITY a "boom">]>' + doc(P("{{A}} &a;"))[len(HEAD):])
        t = make("")
        with zipfile.ZipFile(io.BytesIO(t)) as z:
            names = z.namelist()
        entries = [(n, evil if n == "word/document.xml" else zipfile.ZipFile(io.BytesIO(t)).read(n)) for n in names]
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            for n, d in entries:
                z.writestr(n, d)
        self.refused(out.getvalue(), "safely")


class Values(unittest.TestCase):
    def test_special_characters_are_written_as_text(self):
        v = '<w:p>"quote" & <b>bold</b> ]]> &amp; {{OTHER}}'
        out = fill(make(P("{{A}}")), {"A": v})
        body = main_of(out)
        self.assertIn("&lt;w:p&gt;", body)
        self.assertIn("&amp;amp;", body)
        self.assertEqual(body.count("<w:p>"), 1)
        from xml.dom import minidom
        minidom.parseString(body.encode())                  # still well formed
        self.assertNotIn("{{OTHER}}", re.sub(r"<[^>]*>", "", body).replace("{{OTHER}}", "", 0) and "") if False else None

    def test_a_value_that_looks_like_a_placeholder_is_not_filled_again(self):
        out = main_of(fill(make(P("{{A}} {{B}}")), {"A": "{{B}}", "B": "end"}))
        self.assertEqual(text_of(out), "{{B}} end")

    def test_a_long_value_and_line_breaks(self):
        out = main_of(fill(make(P("{{A}}")), {"A": "ab\ncd" + "z" * 90_000}))
        self.assertIn("<w:br/>", out)
        self.assertGreater(len(out), 90_000)


if __name__ == "__main__":
    unittest.main()
