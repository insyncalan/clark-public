# Design: #122 Show what ask clark will send before it sends it

Written by a build agent, 31-10-2026. **Not built.** Design note only: no code, no test, no guarded file touched. **Sources:** #122 and its comments (the owner, 28-10-2026: "candidates as recommended"; the reviewer's Done-when of 29-10 and 31-10), #47 and its readiness note, #47c's request builder (`ask.py`, PR #123, branch the #47 branch), the #47 build branches (the #47 branch: folders and switch routes only), `docs/handoff/design-72-ai-menu-page.md`, `docs/handoff/readiness-54-providers.md`, BRD FR-61, FR-62b, FR-63a, FR-68. a reviewer's environment-scrub review was not found as a file or issue; its rule (a model run gets no inherited secrets) is taken from the #54 readiness note and is not repeated here.

**Scope.** #122 has two parts. This note covers part (a), the send preview, for v0.3 where it is cheap. Part (b), the rule-based health suggestion, is a separate pure function and the page's Edit area; it needs no model and no guarded file, and gets its own note when the owner asks. It is out of scope here.

## 1. What the person sees
Above Send in the ask clark panel, one slim line, on every question:

> Sends 6 passages (11,400 characters) from 3 files and the project data to Claude. **Details**

**Details** opens a list under the line:
- Each passage: its ID (P1, P2 ...), its label (a file name relative to the source folder, or "Work items" / "Milestones" for project data), and its size in characters. The first 100 characters of a passage may be shown on hover; never the whole text.
- The question and the earlier turns of the chat, with their sizes (they are sent too).
- The provider and model by name, and the plain sentence: "These passages leave this computer and are billed to that account."
- How many passages were skipped for safety (a closed place, a link out of a folder, a file that would not read), how many were left out for size, the 40,000 character budget, and how many old chat turns were dropped to fit.
- A count of hidden characters per passage, where there are any (`hidden`, already in `Request`), as a warning chip.

Never shown: a key, a full path (labels only), the text of a passage on the line, or a file the reach rules refuse (the list says "1 skipped for safety", not which).

**Left out, and why (stated in Details).** Another project's data and files outside the saved folders (FR-61); anything archived; a note or item marked team-only or confidential is never a passage unless the person has said yes once for it (the same one question the AI menu asks, #72); a password-looking question is refused before anything is shown (`SECRET`). If clark has no confidential flag on a row yet, the design must state that gap rather than imply it: see open question 2.

## 2. The rule that makes it trustworthy
The list is **not** built beside the request; it is read from it. One function builds the `Request` (`ask.build_request`, #47c), and the preview is a plain-data summary of that same object (ids, labels, sizes, totals, provider, model, hidden counts, dropped turns). Send then sends that exact object, identified by a hash the server returns with the preview: Send posts the hash, and the server refuses (with a plain line asking the person to look again) if the data changed in between. So what was shown is what is sent, in the same order and with the same total. Cancel, Esc, closing the panel and editing the question all discard it; nothing is sent.

## 3. Choices
| | A. Always-on line + Details (the reviewer's Done-when) | B. A confirm panel with Send / Cancel every time | C. Only the first request of a session |
|---|---|---|---|
| Fits the owner's wording ("shows what will be sent") | Yes | Yes, heavier | Weaker |
| Cost to the person | One line they can ignore | An extra click on every question | Lowest |
| Trust | High: always visible | Highest, but trains click-through | Drops after the first |

**Recommendation: A, on every request** (the default taken in #122: it is one short line and trust is the point). Make B a Settings option for people who want a stop each time; do not build it in v0.3. Open question 1 asks the owner to confirm.

**Two-step flow (needed for A to be true).** The panel asks the server to prepare (`POST /api/ask/prepare`: question and chat in, summary and hash out, nothing sent) as the person types, with a short pause; Send then posts the hash to `POST /api/ask`. The line therefore always describes a request that exists. Preparing makes no model call and reads only what the reach rules allow.

## 4. Where it appears
- **ask clark panel:** the line sits directly above Send, inside the panel at 1400 and 900 px, light and dark; Details opens upward in the panel, not a new window. Esc closes Details first, then the panel.
- **AI menu (#72):** the suggestion card carries the same line (one passage, its size, the provider); the existing `sends_notice` text becomes this line. The text is the selection, so Details shows only its size and hidden count.
- **Published files:** nothing. Nothing in a published file mentions ask clark.

## 5. Done-when, as tests that could be written
1. `test_preview_matches_request`: for demo questions, the summary's passage IDs, labels, order and total equal those of `build_request`'s `Request`, and Send's body is byte-identical to the previewed `Request.text` (the hash matches).
2. `test_preview_makes_no_model_call`: with a fake provider that fails if called, `prepare` succeeds and the provider's call count is 0; Cancel leaves it 0.
3. `test_send_refused_if_changed`: change a work item between prepare and Send; Send is refused with the plain line and the provider is not called.
4. `test_preview_counts`: skipped-for-safety, left-out-for-size, dropped turns and the 40,000 budget match a request built with a planted link out of a folder, an over-budget set and a long chat.
5. `test_preview_never_leaks`: no full passage text, no absolute path, no key (canary string ending `TESTONLY`) appears in the summary or the line, for any input.
6. `test_second_project_not_listed`: a second project, a file outside the folders and a symlink out are absent from the list (shares the FR-61 fixture of 47d).
7. `test_two_providers_same_line`: two fake providers differ only in name and model in the line (FR-68).
8. `test_preview_source_writes_nothing`: a source test: the preview module opens no database for writing and no file for writing.
9. Page tests (harness, 1400 and 900 px): the line is above Send; Details opens and closes with Esc; Send is disabled until the line is ready; Cancel sends nothing.
10. `test_plain_words`: line and Details pass the plain-words and names tests (no "payload", "token", "context window").

## 6. Guarded files and tier
- **`server.py`** (the new `prepare` route and the hash check on `/api/ask`): guarded. The token-checked, every-route-authorised test applies.
- **`ask.py`** (a `summary()` method on `Request`): #47c is Full. Changing it later re-opens its review.
- **`reach.py` and `edit_ai.py` copies:** read, not changed.
- **`changes.py`:** not touched; the preview writes nothing and sends nothing.
- A new unguarded `ask_preview.py` can hold the summary and the plain sentences, so the guarded diff stays small.

**Tier: Full** (two independent readers, never the builder), because it sits on ask clark's request path, as the 29-10 Done-when says. Not Light, even though it adds no write. The page part alone (the line and Details, drawn from a summary the server gives) is Light and can be built first against a stub. **Order: after #47c lands; it needs no store change and no schema step.**

## 7. Risks
- **Preview and send drift** if two code paths build text. Mitigation: one builder, hash check, test 1.
- **Preview leaks what it protects**: a path, a key or a passage. Mitigation: labels only, test 5.
- **Click-through**: an always-there line becomes wallpaper. Mitigation: the line changes with the content, and a warning chip shows hidden characters or a large size.
- **Cost of preparing on every keystroke**: reach and search run each time. Mitigation: pause 400 ms, reuse the passages until the question or data changes.
- **A false promise about confidential rows** if the store has no flag. Mitigation: open question 2; do not say "nothing confidential was sent" until it is true.
- **Later providers:** OpenAI (#54, v0.5) must reuse this line unchanged; the provider name and model come from the provider interface.

## 8. Open questions
1. **For the owner:** the line on every request (recommended) or only the first of a session?
2. **For the lead:** does clark have a confidential or team-only flag on work items and notes that ask clark must respect? FR-68 says no provider difference; creaite's own rule sends confidential material only to Claude. If there is no flag, say so in Details, or add the flag first.
3. **For the lead:** is the two-step `prepare` then Send acceptable on the request path (one extra guarded route), or must the preview come from the same POST?
4. **For the owner:** should Details show a short opening (100 characters) of each passage, or only labels and sizes? Recommendation: labels and sizes, with the opening on hover.
5. **For the lead:** build the page part now against a stub (Light) and the server part after #47c (Full)?
