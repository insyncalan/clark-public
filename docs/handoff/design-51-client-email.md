# Design: #51 Draft email on the client page

Written by a teammate's agent, 31-10-2026. **Part built, not merged.** The build is on a separate branch. Not built: the Publish-screen field, its `server.py` route, and a per-item ticked set. **Sources:** #51 and the owner's hold (28-10-2026: "Put this on hold for the client for now - editor only"), BRD FR-94, FR-95 and D-6, and the branch diff.

**The hold is lifted** (Decisions, below). BRD D-6 still says "On hold" and needs updating.

## Decisions (the owner, 31-10-2026)
1. **The 28-10 hold is lifted.** Build it.
2. **One outside contact per project**, not chosen at each publish. It is a project setting (schema version 3: `projects.contact_name`, `projects.contact_email`), set on the Publish screen and saved as an ordinary step with history and Undo.
3. **No warning** on the Publish screen that the address will sit in the client's file.

Question 4 (per-item ticked sets) was not answered; "this item" and "all open items" stay as built. The build is on a separate branch.

## 1. What the person sees
The client opens a published report. If the file carries a contact, the Work items page shows a **Draft email** button, and each row shows a small **envelope** by its title. The envelope opens the draft on that item alone; the button opens it on every open item. The client types their name (it signs the email), picks a kind (update request, chase, decision), and sees the email addressed to the contact. They copy it out with **Copy for Outlook**, **Copy as text**, or **Open in mail app** (short emails only). A file with no contact shows no button and no envelope. Nothing is sent by clark.

## 2. Where the contact is set
At publish, on the Publish screen: two fields, the contact's name and address, remembered per project. **Not built.** Saving them needs a new `server.py` route (a guarded file), so the route is guarded by tier, not by choice: it writes a person's address that later goes into a client file. It must refuse without the session token, check the address as in section 3, and store nothing else. Until it exists, `build()` and `publish()` take the contact as arguments and the tests pass it in.

## 3. What the client page may and may not show
The page holds only what publish kept, so a hidden row or an internal note is not in the file to be drafted from. On top of that:
- Rows whose text, response or update contain "confidential" or "restricted" (read through the look-alike scan) are never offered.
- A row flagged sensitive is left out when the contact is outside the team's domains.
- The contact must be one plain address (no spaces, no list, no angle brackets) and **must not be on the team's own domains**. A team address, or a bad one, is dropped with no error; the file simply carries no contact.
- Name and address are one line of plain text; the name is cut to 80 characters.

## 4. The exact change to `publish.py` (a guarded file)
Four edits, 18 lines:
1. `import draft_email`.
2. `build()` and `publish()` gain `contact=None, own_domains=()`; `publish()` passes them on.
3. In `build()`, after `select()` and `add_glance()`, the contact goes through `draft_email.client_contact(...)`; if it passes, it is set as `published["contact"]`.
4. `data_block()` adds a `contact` key to the JSON block, only when there is one.

**This is not a change to the publish scan.** `select()`, the client checks (#43) and every scan that decides which rows reach the file are untouched, and no row is added, widened or let through. The change adds one new, separate field to the data block, checked by its own function. A reader can judge it by confirming: `select()` is not in the diff; a file built with no contact is byte for byte what it was before (test needed, below); the `<>&` escaping in `data_block()` still applies to the new key.

## 5. What the draft contains, and how it leaves
The page builder (`draftEmailBuild.js`) is a port of `draft_email.py`: same wording and rules, run in the browser, no server and no model. It takes the published rows (id, text, due, owner, status, latest update) and the contact, and returns a subject, an HTML body and a plain-text body. A test builds the same email in Python and in the page and compares them. Copy for Outlook puts the HTML on the clipboard; Copy as text puts the plain text; Open in mail app uses a `mailto:` link for a short email. The page asks for nothing outside itself. A draft never carries a change into clark (FR-95); edits come back only by the changes file.

## 6. Risks
- **A contact address is personal data in a published file.** It is readable by anyone who holds the file: the client and anyone the client forwards it to. The file is the client's once handed over; clark cannot recall it. The Publish field should say so in plain words, and the address should be the one the user chose for this purpose.
- The page port can drift from `draft_email.py`; the comparison test is the guard.
- A look-alike or confidential word missed by the scan would put a row in an email; the scan is the same as the editor's.
- The email shows the client the same rows they can already see; it adds no row.

## 7. Tests
**Exist (`tests/test_client_email.py`, 15):** Python and page builders agree; hidden, confidential and look-alike rows never offered; text read as the Python scan reads it; published rows become items; contact must be one plain address; outside contact kept and cut; team, bad or no address never kept; the file carries the contact and no team address or hidden marker; the dialog drafts to the contact from published rows only; a name is needed, then the email is ready; no kind or set of items puts a hidden row, an internal note or a team address in an email; the envelope opens that item alone; the page asks for nothing outside itself; no button without a contact; fit at 1400 and 900, light and dark.

**Still needed:**
- The Publish route refuses without the token.
- The route drops a team address and says so.
- A file published without a contact is byte for byte the file built before the change.
- A published page has no button when the contact is stripped.
- The contact never reaches a draft in which a sensitive row is included, and a sensitive row never reaches a draft to an outside contact.
- The ticked-set path, once built.

## 8. Tier
**Full.** It edits `publish.py` and (when built) `server.py`, both guarded, and its output goes to a client. Two readers are needed, one of them reading section 4 against the publish scan.

## 9. Questions for the owner
1. **Is the 28-10 hold lifted?** If not, the branch stays unmerged and the page keeps no button.
2. Is the project contact one per project (D-6's recommendation), or chosen at each publish?
3. Should the Publish screen warn that the address will sit in the client's file?
4. Per-item ticked sets: wanted now, or is "this item" and "all open items" enough?

**Recommendation.** Do not merge while the hold stands. If lifted, build the Publish field and route next as one Full item, with the section 7 tests.
