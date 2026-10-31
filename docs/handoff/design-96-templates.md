# Design note: #96 Section templates and the Add a section dialog (first slice; guarded changes needed)

First slice: Text, Text and image, Key figures (three and four), RAID cards (three and four), Work items list, Documents and links, Callout, Key dates. The second slice (Headline band, Image gallery, Table, Link preview, Image with caption, Quote, Contacts, Checklist, One document) adds entries to the same catalogue.

## 1. What the store allows today (read from the code)
- `changes.py`: a `new` request takes `values` with `type` and `title` only, plus `after`. `values.type` other than `text` is refused (`ONLY_TEXT`). There is no `body` and no `beside` in a `new`.
- `store.py` / `schema.sql`: a section's `type` is one of nine (`current glance usecases milestones text raid actions decisions docs`, a CHECK and `SECTION_TYPES`). Only a text section may have a `body` (`_section_rules`). Only a text section may be deleted (`cancel`). There is no column for what a template holds (figures, a callout's kind, dates, images, the chosen work items).
- Result: **only the plain Text template can be created today.** Every other template in the slice needs the guarded change in section 6.

## 2. The catalogue, as data
Lives in `src/clark/page/src/logic/templates.js` (pure, no DOM, no signals; one list, so the second slice and Help's Section templates (#82) read the same data). One entry:

| field | meaning |
|---|---|
| `id` | stable key (`text`, `text-image`, `figures-3`, `figures-4`, `raid-3`, `raid-4`, `work-items`, `docs-links`, `callout`, `key-dates`) |
| `name` | what the dialog calls it |
| `kind` | one of the kinds: Text and pictures, Figures, Work items, Files and links, People and dates, Notes |
| `fit` | `["full"]`, `["half"]` or both: where it looks right. Half-width ones may be placed beside the next section |
| `description` | one plain sentence |
| `holds` | what it holds, as a short list, shown in the preview |
| `type` | the section type the store will have to accept (section 6) |
| `title` | the starting title (`New section` for Text, which keeps today's wording) |
| `body` | the starting content, `""` until the store has a field for it |

`ACCEPTS` in the same file mirrors what the store takes now (`types: ["text"]`). A template whose `type` is not accepted is **listed and readable but not placeable**: its description, parts and width show as for any template, the arrow keys reach it, a second line says "Coming with a later release.", and Add section stays off (the preview says why). A test sends the real request for such a template to the real route and expects the refusal, so the list cannot drift from the store. When the guarded change lands the owner adds the new types to `ACCEPTS` and that test is replaced.

## 3. The dialog's flow
1. **Open.** `openAddSection(after, opener)` (`edit/addDialog.js`) dispatches the cancelable, bubbling event `clark:add-section` on the document with `detail: { after, opener }`. `after` is the section the new one goes below (`null`: the end); `opener` is the element to give focus back to. #101's gutter "+" and the menu's "Add a section below…" call that function (or dispatch the event) and need nothing else. The dialog host (`edit/AddDialog.jsx`) is mounted once in Edit, beside the Toast, and ignores the event in View.
2. **Choose.** A search box, the kinds (All, Recently used when there is one, then each kind with its count for the current search), the templates as a radio group (name, fit, one-line description), and a preview of the chosen one (description, what it holds, fit).
3. **Place it** (the group's heading; the button is **Add section**, the prototype's word). "On its own row" (default), or "Beside the next section (half width)". Beside names the section (Beside “Summary” (half width)) and is offered only when the template fits half **and** the next row is a single section (design-95 section 8: beside only a section that is alone). Otherwise it is shown unavailable with the reason in words (the last section; the next row already has two; the template needs the full width).
4. **Do it.** Add section sends the change(s) through `stores/changes.js` (one at a time, Undo with the toast), closes the dialog, and gives the new section's title focus, selected (as Add does today). A refusal from clark shows in the toast and focus returns to the opener.

**Placement.** The new section goes below the **row** of the chosen section, not just below that section: if the chosen section is the left half of a pair, inserting after it would pair the new one with it and break the pair. `anchor()` takes the last section of the chosen section's row. If that section is alone and carries a stale `beside = 1` (a flag on the last section is ignored by the page), the plan also clears it, or the new section would pair with it.
**Beside the next:** the new section is made with `after: anchor`, then `update beside = 1` so it shares its row with the section that followed. That is **two requests and two Undo steps** until `new` can take `beside` (section 6, item 3).

**Keyboard and focus.** On open, focus goes to the search box. Tab and Shift+Tab stay inside the dialog (a trap). Esc closes and gives focus back to the opener (or the chosen section's handle if the opener is gone). Down in the search box moves to the chosen template; the arrow keys move between templates (native radios, so the choice follows focus); Enter anywhere in the form places it (when a usable template is chosen). The rest of the page is `inert` while the dialog is open (the Toast stays live). It is `role="dialog"`, `aria-modal`, labelled by its heading; the counts and the preview are announced politely. No text smaller than 13 px; tokens only.

**Recently used.** The last three template ids in this browser's `localStorage` (a per-person convenience, read and written in try/catch; the dialog works without it).

## 4. Plain words
Every string a person reads is in `templates.js` or the dialog. Refusals: "This is the last section, so there is nothing to sit beside." · "The next row already has two sections. Place it on its own row." · "This template needs the full width. Place it on its own row." · "That section isn't in the report any more. Reload the page."

## 5. What is built in this slice (no guarded change)
`logic/templates.js` and its tests; `edit/addDialog.js` (the entry point); `edit/AddDialog.jsx`; `actions.addFromTemplate`; styles in `shell.css`; wiring in `edit/index.js` and `App.jsx`. The existing "Add a text section below" button is left as it is (#101 replaces it).

## 6. Guarded changes needed before the other six templates can be made (STOP: not made here)
1. **`schema.sql` and `store.py` (`SECTION_TYPES`, `_section_rules`, the delete rule at `cancel`).** New section types for the six templates: `textimage`, `figures`, `raidcards`, `workitems`, `doclinks`, `callout`, `keydates` (seven, with `figures` and `raidcards` covering three and four across by their content). Alternatively one type `template` plus a `template` column. The "Only a text section has a body" rule is widened to these types, and they may be deleted like a text section (report sections are exempt from the never-delete rule).
2. **A field for what a template holds.** The existing `body` (a string) can carry it as JSON if the store allows `body` on the new types; otherwise a new `content` column. Needed by the second step of each template (filling it in), and by the starting content.
3. **`changes.py`: `new` accepts any of the new types (remove `ONLY_TEXT`), and `values` gains `beside` (0 or 1, `FLAG_FIELDS`) and `body`.** `beside` in `new` makes "Place it beside the next" one request and one Undo; the same flag rule as `update`.
4. **`publish.py` (not guarded):** an empty template stays out of the published page (the issue's "empty templates stay out"). Needs item 2 to know what empty is.

After 1 and 3 the build only adds the types to `ACCEPTS` and swaps the two-request beside for one.

## 7. Tests (what each Done-when line has)
`tests/test_templates.py`: the catalogue (every entry complete, ids unique, kinds known, the first slice present, plain words, no stale `ACCEPTS`), search and kinds and counts, Recently used, `anchor`, `besideState` for each refusal, and the request each template sends (text: the exact `new` request; beside: the `new` then the `update`; a pair's left half; the stale flag). In the real page with the real routes: open by the event, focus on the search box, the trap, Esc and focus back, a text template placed below and Undo, placed beside a lone section (two steps, rows right), a refusal when the next row is a pair, an unavailable template cannot be placed and the real route refuses its type, the page behind is inert, and the dialog fits at 1400 and 900 px with text of 13 px or more.

## 8. Which existing section type each template could reuse (decide before the guarded step)
Read from `schema.sql`/`store.py` (types: `current glance usecases milestones text raid actions decisions docs`). Nothing here changes the store.

| Template | Closest existing type | Reuse it? | Why |
|---|---|---|---|
| Text | `text` | Yes, already | Today's only placeable template. |
| Text and image | `text` | No: needs its own | A picture and a caption are content a text section's `body` does not hold. |
| Key figures, three / four | `glance` | Partly | `glance` is the report's one At a glance section, live tiles (#45). A figures section is placed any number of times, mixes live and typed figures and has its own labels, so it needs its own type. |
| RAID cards, three / four | `raid` | No | `raid` lists every RAID item as a table; a card section shows three or four chosen items with a line each. |
| Work items list | `raid`, `actions`, `decisions` | No | Those are fixed to one record type; this one is a saved filter across types. |
| Documents and links | `docs` | Maybe | `docs` shows the project's documents; this one is a list of files and links picked for this report. If `docs` can hold a chosen list, it could be reused; otherwise a new type. |
| Callout | none | New | A short message with a kind (information, decision, warning). |
| Key dates | `milestones` | Maybe | `milestones` shows the project's milestone calendar; Key dates is a short list, typed or taken from milestones. Reuse only if `milestones` can show a chosen few. |

So six or seven need a new type (or one `template` type with a column), as section 6 says; Documents and links and Key dates are the two for the lead to decide. This choice sets the CHECK, the delete rule and what "empty" means for publish.
