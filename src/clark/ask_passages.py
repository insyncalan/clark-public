"""ask: passages from the folders a person saved for one project (#47d). Read only; nothing here writes, opens the database or
starts a process. Standard library only.

ONLY WHAT WAS SAVED, ONLY WHAT IS SAFE. The caller gives the project's own saved folders (the store's `source_folders` rows for
that project and no other). Each is judged again here with `reach.never_inside`, so a folder that has since become, or turned
out to be inside, a place clark keeps closed is dropped. The files come from `reach.readable_files` (which already leaves out
secrets such as .env and .pem files, clark's own data, links, files with more than one name, online-only and other-disk files).
A listing is only a list: EVERY file is opened again through `reach.read_bytes`, which classifies the path afresh, opens it
with O_NOFOLLOW and checks the open file (a regular file, one name on disk, the saved folder's disk) before reading a byte, so a
path swapped for a link, or for another file, after it was listed is refused at that moment.

TYPES. Word files (.docx) are read by `docx_read` (which refuses a hostile one); plain text files (.txt, .md, .csv and a few
more) are read as UTF-8. PDF is NOT supported yet: it is counted ("not supported yet"), never read. Any other type is counted too.

WHAT COMES BACK. `FolderData`: the chosen passages (each labelled with a name inside its folder, never a path), `left_out` (how
many did not fit the budget), `safety` (how many files were left out for safety, with the listing's own count), `pdf` and
`other` (files of a type not read), `stopped` (the listing was cut short) and `secret_labels` (#215: files left out whole because
the text looks like it holds a secret, screened by `secret_screen` before any of it becomes a passage; counted in `safety` too). No path, no file text and no reason that holds a
path is returned or logged here.
"""
import codecs
import os
import time
from dataclasses import dataclass

from clark import ask, ask_data, docx_read, reach, secret_screen

TEXT_TYPES = (".txt", ".md", ".markdown", ".csv", ".tsv", ".rst")
WORD_TYPES = (".docx",)
PDF_TYPES = (".pdf",)
MAX_TEXT_BYTES = 1024 * 1024               # a plain text file is read to here
MAX_FILES_READ = 300                       # files opened for one question
MAX_BYTES_READ = 60 * 1024 * 1024          # all the bytes opened for one question
MAX_CHARS = 2_000_000                      # all the text kept before passages are chosen
MAX_PARTS = 40                             # passages one file can give
READ_SECONDS = 20.0                        # time spent opening files for one question; files after it are left out


@dataclass(frozen=True)
class FolderData:
    passages: tuple = ()
    left_out: int = 0          # passages that did not fit the budget
    safety: int = 0            # files and folders left out for safety (including a Word file refused as unsafe)
    pdf: int = 0               # PDFs, not supported yet
    other: int = 0             # files of a type that is not read
    stopped: bool = False      # the listing was cut short by a cap
    secret_labels: tuple = ()  # labels of files left out because they look like they hold a secret (already counted in `safety`)


def _lines_of_word(data, name):
    got = docx_read.read(data, name)
    lines = []
    for b in got.blocks:
        if b.get("kind") == "table":
            lines += [" | ".join(str(c).replace("\n", " ") for c in row) for row in b.get("rows") or ()]
        elif b.get("text"):
            lines.append(str(b["text"]))
    return lines


def _lines_of_text(data, truncated):
    if b"\x00" in data:
        raise ValueError("not text")
    text = codecs.getincrementaldecoder("utf-8")("strict").decode(data, final=not truncated)    # a cut inside a character is not an error
    return text.lstrip("﻿").splitlines()


def _chunks(lines):
    """Lines no longer than a passage, so a long line is split and not cut."""
    size = ask_data.PASSAGE_SIZE
    for line in lines:
        line = line.rstrip()
        if not line.strip():
            continue
        for i in range(0, len(line), size):
            yield line[i:i + size]


def _label(root, path):
    rel = os.path.relpath(path, root)
    name = f"{os.path.basename(str(root))}/{rel.replace(os.sep, '/')}"
    return name if ask._label_ok(name) else None


def folder_data(folders, data_dir, question="", budget=ask.BUDGET, home=None, max_passages=ask.MAX_PASSAGES):
    """Passages from the saved `folders` (a list of paths) for one question; `data_dir` is clark's own folder. See the module note."""
    safety = pdf = other = 0
    secret_labels = []
    usable = []
    for f in folders or ():
        try:
            why = reach.never_inside(f, data_dir, home)
        except (OSError, ValueError, RuntimeError):
            why = "unusable"
        if why:
            safety += 1
        else:
            usable.append(f)
    if not usable:
        return FolderData(safety=safety)
    listing = reach.readable_files(usable, data_dir, None, home)
    safety += listing.skipped
    roots = reach.roots(usable, home)
    passages, files_read, bytes_read, chars = [], 0, 0, 0
    deadline = time.monotonic() + READ_SECONDS
    for path in listing.files:
        low = str(path).lower()
        if low.endswith(PDF_TYPES):
            pdf += 1
            continue
        word = low.endswith(WORD_TYPES)
        if not word and not low.endswith(TEXT_TYPES):
            other += 1
            continue
        root = next((r for r in roots if reach.inside(path, r)), None)
        label = _label(root, path) if root is not None else None
        if label is None:
            safety += 1
            continue
        if files_read >= MAX_FILES_READ or bytes_read >= MAX_BYTES_READ or chars >= MAX_CHARS or time.monotonic() > deadline:
            other += 1
            continue
        files_read += 1
        try:
            raw, truncated = reach.read_bytes(path, usable, data_dir, docx_read.MAX_FILE_BYTES if word else MAX_TEXT_BYTES, home)
        except reach.Never:
            safety += 1                                   # changed since it was listed, or never allowed
            continue
        bytes_read += len(raw)
        try:
            if word:
                if truncated:
                    raise docx_read.WordRefused("too big")
                lines = _lines_of_word(raw, os.path.basename(str(path)))
            else:
                lines = _lines_of_text(raw, truncated)
        except (docx_read.WordRefused, ValueError, UnicodeError):
            safety += 1                                   # a Word file refused as unsafe or damaged, or text that isn't text
            continue
        if secret_screen.looks_like_secret("\n".join(lines)):      # #215: the whole file, before any of it is a passage
            safety += 1
            secret_labels.append(label)
            continue
        parts = ask_data._cut(label, list(_chunks(lines)))[:MAX_PARTS]
        chars += sum(len(p.text) for p in parts)
        if len(parts) > 1:
            parts = [ask.Passage(f"{label} (part {i})", p.text) for i, p in enumerate(parts, 1)]
        passages += parts
    chosen, left = ask_data.choose(passages, question, budget)
    if len(chosen) > max_passages:
        left += len(chosen) - max_passages
        chosen = chosen[:max_passages]
    return FolderData(chosen, left, safety, pdf, other, bool(listing.stopped), tuple(secret_labels))
