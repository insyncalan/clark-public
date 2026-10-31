# Design note: #122 show what ask clark will send, and a rule-based health suggestion (BRD FR-62b)

Written by a build agent, 29-10-2026, before any code. Docs only: nothing in `src/`, `tests/` or the page changes with this note. Review: **Light** for the pure modules and the page (the lead's Done-when), **Full** for the one commit that touches ask clark's request path in `server.py`. Two independent readers for the guarded diff, never the builder; the owner approves the exact diff in their own words (`RULES.md`).

**Read for this note:** issue #122 and its three comments (the owner's "taken in two parts", the prototype line, the reviewer's Done-when of 29-10); BRD FR-20, FR-62b; an internal notes file (it holds no text on #122: the issue only names it as the source, so nothing in it changes this plan); `design-47-ask-clark.md` (the #47 branch) and `src/clark/ask.py` on the #47 branch (a338b28 and after: `build_request`, `Passage`, `Request`, `Provider`, `MAX_PASSAGE_TOTAL`, `SECRET_QUESTION`); on `origin/main` (`ec0f87f`): `glance.py`, `milestones.py`, `publish.py` (its Sensitive rule), `store.py` (`_check_project`).

## 0. What exists, what does not
- **On main:** `glance.py` (the tiles, `is_open`, `is_overdue`, `day_number`, `colour_of_priority`, `health_pick` and the reason rule), `milestones.py` (`suggested_state`, `slip_days`). Everything part B needs is there. No new store field is needed.
- **Not on main:** `ask.py` and all of #47 (it is on the #47 branch, unmerged). `ask_sources.py` (47d) is not built: nothing yet chooses passages, so nothing yet knows which folder a passage came from, or which rows were left out as hidden or Sensitive. `/api/ask` does not exist.
- **`glance.py` says in its docstring that no "better than the dates suggest" hint is given for a project's health, and that "the AI suggestion waits".** Part B adds that hint; the docstring is updated in the same commit.
- **Naming rule:** "nothing outside the provider module may say Claude" (design-47). The provider's name comes from `provider.name`. Every message here takes `{name}`, and none starts with the product name.

## A. The "what will be sent" preview (v0.3 if cheap, needed by v0.5)

### A1. The principle: the preview is the request, rendered
`ask.build_request(question, passages, earlier)` returns a `Request` whose `.text` is the whole text a provider sends. The preview is **computed from that same `Request` and the same `Passage` list**, in one function that takes them as arguments. It never builds a second text, never reads the database or a file, and has no size limit of its own: it reports what it was given. So the preview and the request cannot differ except by being built at two different moments, and the digest (A4) closes that gap.

New pure module `src/clark/ask_preview.py` (standard library, Python 3.9, no network, no store, no clock):

```
Source = NamedTuple(kind, name)          # kind: "work_item" | "milestone" | "use_case" | "section" | "file"
                                         # name: "ABC-A-001", or a file's name relative to its saved folder; for a file also folder (its folder's own name, never a path)
Preview = NamedTuple(sentence, details, digest, over_budget, never)
preview(request, passages, sources, provider_name, left_out) -> Preview
```
- `sources` maps each passage ID to its `Source`; 47d fills it when it chooses passages (the 47d commit that makes passages is where this is attached; until then the tests build it by hand).
- `left_out` is a small dict 47d fills: rows left out as hidden (`report_hidden`) or Sensitive, files left out for safety, files not looked at. Counts only, never a name or a path.
- `digest` is `sha256(request.text)` as hex, 16 characters shown. A request that is the same text has the same digest.

### A2. What the person sees, field by field
**The sentence (always visible once a question is ready to send)**, pinned wording:
- With data and folders: `This question will send {name} this project's work items, milestones and use cases and parts of {folders}, about {n} words.`
- Data only (no folders set): `This question will send {name} this project's work items, milestones and use cases, about {n} words.`
- Kinds with no passage drop out of the list (no use cases sent, no "use cases").
- No passages found: `This question will send {name} your question only, about {n} words.`
- `{folders}` is the folders' own names, joined in plain words ("Contracts and Notes"), at most three then "and 2 more". Never a path. `{n}` is the words in `request.text` rounded to the nearest 10 (never 0 unless the text is empty).

**Show details** (a link under the sentence; the same box, one click) lists, in this order:
1. **Sources by name**: each work item, milestone or use case by its ID and title (passages from rows), each file by its name relative to its folder, with a count of parts per source ("Plan.md, 3 parts").
2. **Passages**: `{k} parts`.
3. **Size**: `{chars} of 40,000 characters`, with the real number and the budget (`ask.MAX_PASSAGE_TOTAL`), plus the words figure used in the sentence. When over the budget the request cannot be built (`Refused`); the preview then shows the refusal's own words, and nothing is sendable.
4. **Provider**: `{name}`, from `provider.name`, and "your question and these parts leave this computer" (the connect-box sentence of FR-65).
5. **Left out, and why** (counts, from `left_out`): `{a} items are hidden from the report and were not included`; `{b} items marked Sensitive were not included`; `{c} files were left out for safety (for example, they hold passwords or keys)`; `Not every file was looked at (there are too many)`. Only shown when non-zero. A count is the most it says: no ID, name or path of a left-out thing.
6. **Hidden characters**: `{h} parts hold characters you can't see` when `request.hidden` or `request.question_hidden` is non-zero (the count 47c already carries).
7. **Never sent** (a fixed line, always shown): `Never sent: passwords and keys, file paths, other projects, anything hidden or marked Sensitive.` Fixed text, because it is a rule, not a measurement.
8. **The exact text** (a second link, "View exactly what is sent"): the `request.text`, in a read-only box. It is local; showing it reveals nothing new, and it is the strongest form of "preview = request". Default yes (Question 3).

### A3. Confirm and cancel
- Pressing Enter on a question does **not** send. It asks the server for the preview (nothing leaves the laptop), and the panel shows the sentence with **Send** and **Cancel** (Cancel, or Esc, returns to the box with the question kept). Send sends. Default: this happens for every question (Question 1).
- If a password-like question is refused (`REFUSED_SECRET`), no preview is shown, only that message.
- If no provider is ready, no preview: the not-set-up or not-ready message.
- If the preview's digest no longer matches at Send (the report changed in between, or a folder file did), nothing is sent; the panel says `The report changed since you looked. Here is what will be sent now.` and shows the new preview. Always safe: no send is ever for a request the person did not see.

### A4. How the server keeps preview and send the same (the one guarded commit)
Stateless, no stored requests. `POST /api/ask` takes `{project, question, earlier, confirm}`:
- **`confirm` absent:** build the request, return the preview and its digest; send nothing.
- **`confirm` = digest:** build the request again from the same inputs; if `sha256(request.text)` equals `confirm`, send exactly that `Request` and return the answer; otherwise return the "changed" reply above with the new preview. The text sent is the text hashed: it is the same `Request` object that was just hashed, not a rebuild.
Preview and send share one function, `ask_preview.prepare(...)`, that builds the passages and the `Request` once. There is no second code path to drift.

### A5. Tests (the invariants first)
`tests/test_ask_preview.py` (pure, no server):
1. **The sentence matches the request** (Done-when 1): for a fixed set of cases the kinds named, the folder names and the words figure are recomputed independently from `request.text` (the `=== PASSAGE P1 ... from <label>` lines are parsed back out) and compared with the sentence and the details. Cases: data only, data and folders, folders only, none, 3 and 4 folders, 60 passages, a passage on the 4,000-character limit.
2. **Planted secret, Sensitive row and hidden row never appear** in `request.text`, the sentence, the details or the digest input. The fixture is built with `ask_sources`'s real selection once 47d exists; until then, the test passes the selection a store fixture with a Sensitive-labelled row, a `report_hidden` row, a work item holding `sk-ant-...`-shaped text and a file named `.env`, and asserts the strings are in neither the request nor the preview. (The selection is 47d's; this test pins the preview side: it fails if the preview ever reads from a source other than its arguments.)
3. **The preview takes only what the request holds:** a source test that `ask_preview.py` imports no `store`, `reach`, `os`, `pathlib`, `sqlite3`, `time` or `socket`, and opens nothing.
4. **Digest:** same inputs same digest; a one-character change in a passage changes it.
5. **Counts only for left-out things:** a name planted in a left-out item never appears in `details`.
6. **Wording pinned:** each sentence and each details line compared byte for byte (the messages are constants; a test asserts the constant set, and that none begins with the product name).
7. **Mutants** (listed here, run by hand and added to the test file as `# mutant:` cases that each must fail): drop the folders from the sentence; compute words from the question only; swap the rounding; show the budget as the request size; omit the `left_out` line; make the digest the question's; read `len(passages)` instead of the parsed count; let a label's path leak into details.
Route tests (`tests/test_server.py` additions, with the #47 route tests): a send without `confirm` sends nothing (a counting provider is called 0 times); a wrong `confirm` sends nothing and returns the new preview; a right `confirm` calls the provider once with text equal to the previewed `Request.text`; the every-route-authorised test passes unchanged.

## B. The rule-based health suggestion (v0.4 if ready earlier)

### B1. Where it lives
New pure module `src/clark/health_suggest.py` (standard library, Python 3.9; no model call, no network, no store write, no clock: `today` is an argument). It reuses `glance.is_open`, `glance.is_overdue`/`day_number`, `glance.colour_of_priority`, `glance.work_rows` (so archived rows are never counted, as in the tiles) and `milestones.slip_days`. It writes nothing: it returns data, and only the person's own pick through `glance.health_pick` writes the health.

```
suggest(rows_by_table, today, milestones) -> Suggestion
Suggestion = NamedTuple(health, rules, reasons)   # health: On track | At risk | Off track
                                                    # rules: the names that fired; reasons: list of (rule, item_id, plain words)
```

### B2. The rules (Done-when 2), with the reason text pinned
1. **Overdue by more than 7 days.** An open **action** whose due date is more than 7 days before today. Exactly 7 days is **not** enough; 8 is. (Open and overdue are the Work items list's rules: `glance.is_open`, `glance.day_number`.) Reason, one line per action, oldest first, at most 5 then "and {k} more": `ABC-A-003 is 9 days overdue.`
2. **A milestone has slipped.** A **Planned** milestone with `milestones.slip_days(row, today) > 0` (the forecast is later than the agreed date, or the agreed date has passed). Reason: `Milestone M2 is {n} days late.` (`M2` is the milestone's ID.) Slipping by one day counts; there is no threshold (Question 4).
3. **Two or more red risks or issues.** Open risks and issues whose priority is Urgent or High (`colour_of_priority` is red: D-12), counted together, **2 or more**. Reason: `ABC-R-004, ABC-R-007 and ABC-I-002 are red risks or issues.` (IDs listed in ID order, at most 5 then "and {k} more".)
**Result:** none fired is **On track**; one or two fired is **At risk**; all three fired is **Off track**. (The Done-when names only "one" and "all three": two is At risk by this note; Question 2.) The words for the sentence under the pill:
- On track: `Nothing in the project's items suggests a problem.`
- At risk: `Suggested: At risk. {the reasons, one per line}`
- Off track: `Suggested: Off track. {the reasons, one per line}`
Reasons name an item by its ID (a person reads the ID, and the code only as the ID's prefix, per the BRD's naming rule). **Not counted:** archived rows, closed/cancelled/made/withdrawn rows, decisions waiting (decisions needed is a tile, not a health rule, in this cut: Question 5), a milestone already Done, a due date that isn't a real day.

### B3. Where it shows and what it never does (Done-when 2 and 3)
- In the project's **Edit** (the project details), **beside the user's own health pill**: the suggestion's pill (a smaller, quiet pill with the words, never the user's pill's colour in the same place) and its reasons under it, plus the link **Use the suggestion**. The link fills the health picker and the reason box with the suggested value and the reasons text for the person to read and then save through the normal Save; it **does not save by itself**. It is a link, not a button (Done-when).
- It never replaces the user's health, never writes it, never moves the pill, never appears on the published page or in the Excel export or any client output (it is internal: the publish allow list does not carry it; a test pins that the published page and the client tiles are byte-for-byte unchanged with and without the module).
- The suggestion is for an On track / At risk / Off track the writer already knows; it invents no new health value.
- Updating: it is recomputed whenever Edit opens and when an item changes while it is open; there is no stored suggestion, so it is never stale.

### B4. The better-than-suggested reason (Done-when 3)
When the user's health is **better** than the suggestion (rank: Off track 0, At risk 1, On track 2; the user's rank is higher), the reason box is **required**, with the prompt `Your health is better than the items suggest. Say why, in a line.`, and **cannot be emptied**: Save stays off while it is blank (page logic, shown live), and `glance.health_pick`'s existing rule for a changed health stays. A pure function `health_suggest.needs_reason(user_health, suggestion)` returns whether the prompt applies; the page uses it. It is **not** enforced in `store.py`: that would be a guarded change and the store has no such rule today (creaite's has one for milestones only). The person who saves the same health as now without touching the reason is not asked again (nothing changed, as `health_pick` already treats it). Whether to also enforce this in the writer is Question 6.

### B5. Tests with mutants (`tests/test_health_suggest.py`)
- One test per rule firing alone, and per rule not firing; all three; none; each pair (two of three gives At risk).
- **Boundaries:** an action overdue by exactly 7 days does not fire, by 8 does; due today and tomorrow do not; a due date that isn't a real day does not; a milestone with the forecast equal to the agreed date does not, one day later does; a Done milestone does not; exactly 1 red risk or issue does not, 2 do; a Medium one is not red; a Closed one is not counted; an archived row is not counted; a risk and an issue count together; one risk plus one issue is 2.
- Reasons: IDs in the right order and capped at 5 with the "and k more" line; wording pinned byte for byte.
- `needs_reason`: all nine pairs of user and suggested health.
- Source test: no import of `store`, `server`, `reach`, `os`, `time`, `sqlite3`, `socket`; no `date.today()`; no use of the model.
- Never writes: the function is called with a read-only copy and a counting store (0 steps).
- The client version unchanged (B3).
- **Mutants** (each must fail a test): `>` for `>=` on the 7 days (and the reverse); 6 or 8 for 7; count `High` only; count Medium; `>= 1` for `>= 2`; count archived rows; count closed rows; ignore the milestone's Done status; use baseline instead of forecast; At risk for two rules becomes On track; Off track on two; the reason box required when the user's health is the same or worse; `needs_reason` rank reversed; the suggestion written back into the pill; an empty reason accepted.

## C. Commits, guarded files, and what waits on #47

All of part B and the pure core of part A can be built **now**, with no #47 code. The route (A4) and the page need #47's server route (design-47 commits 6 and 10) and the 47d selection (commits 7 to 10).

| # | Commit (small, in this order) | Files | Guarded? | Tests | Waits on |
|---|---|---|---|---|---|
| 1 | `#122: design note` | this file | no | none | nothing |
| 2 | `#122: the health suggestion rules` | `src/clark/health_suggest.py` (new); `glance.py` docstring line only | **No** (`glance.py` is not guarded; only a docstring change) | `tests/test_health_suggest.py` and its mutants | nothing (all on main) |
| 3 | `#122: suggestion beside the health pill in Edit` | `src/clark/page/src/` (Edit's health section), rebuilt with `python3 dev/tools/build_page.py` (`--check` clean; never a hand merge); a small read-only route to give the page the suggestion, **or** the page computing it from the data it already has through a JavaScript port tested against the Python fixtures | The page: no. **A new route would touch `server.py`: guarded** (Question 7 prefers the page port, with a shared fixture file, so no route is needed) | Chrome tests at 1400 and 900 px: pill and reasons shown beside the user's own, never replacing it; **Use the suggestion** fills but does not save; reason required and not emptyable when better; the published page unchanged; fail, never skip, when Chrome is missing | commit 2 |
| 4 | `#122: the send preview` | `src/clark/ask_preview.py` (new) | no | `tests/test_ask_preview.py` (A5) and mutants | `ask.py` (#47 commits 2 to 4, now on the #47 branch; rebased when #47's pure modules merge) |
| 5 | `#122: attach sources and left-out counts to passages` | `ask_sources.py` (47d's file), small | no | the planted-secret test using the real selection | #47d commits 7 to 9 |
| 6 | `#122: preview, then confirm, in the ask route` | `server.py` (`confirm` field and the "changed" reply, `prepare` shared by both steps), `tests/test_server.py` additions | **Yes** (`server.py`; Full; the owner approves the exact diff) | route tests in A5 | #47 commits 6 and 10 |
| 7 | `#122: the sentence and Send/Cancel in the panel` | `src/clark/page/src/` (the ask panel), rebuilt as above | no | Chrome tests: the sentence appears before send; Cancel and Esc keep the question; Send; details; the "changed" reply; the panel's other behaviour unchanged | commit 6 and #47a/#102's panel |
No change to `store.py`, `schema.sql`, `reach.py`, `edit_ai.py`, `changes.py`, `publish.py`, workflows, version or any guard test. A message beginning with a write-verb word trips the one-writer test, so no string in these modules starts with one (reworded where needed).

**Can be built now, without #47:** commits 2 and 3 (the whole of part B), and commit 4 against the `ask.py` on the #47 branch (its `Request` and `Passage` are all it needs). Commits 5 to 7 wait.

## D. Questions

### D1. Where a choice loosens a guard, or touches security, money or an outward connection (default given)
1. **Always confirm, or only some questions?** A confirm on every question is safest and the issue's wording ("before ask clark sends") is satisfied. A person may find it slow. *Default: confirm every question. A "don't ask again for the same sources" setting would loosen the guard and is not built unless the owner says so.*
2. **Two of three rules: At risk or Off track?** The Done-when gives only one and all three. *Default: At risk (Off track needs all three).* Not security; it decides what a person is told.
3. **Show the exact text (A2.8)?** It is local, and it makes the preview provably the request. *Default: yes, behind a link, closed by default.* It does show every passage in one box, including ones the person has not read.
4. **Does any slip count, or a threshold?** *Default: any slip; the milestone's own `slip_days > 0`.*
5. **Decisions waiting and the oldest needed-by date:** the issue's own ideas ("decisions waiting") are not in the reviewer's three rules. *Default: not a rule in this cut; the tile already shows it.* Add as a fourth rule only with her word.
6. **Enforce "better than the suggestion needs a reason" in the writer?** It would put a rule in `store.py` (guarded; Full; the owner's diff), and the suggestion depends on the day, so the same save could pass today and fail tomorrow. *Default: page only, pinned by tests; the writer's rule stays "a changed health needs a reason".*
7. **Page port, or a route, for the suggestion?** A route is a guarded `server.py` change. *Default: no route; the page computes it with a JavaScript port checked against the same fixture cases as Python (as the Work items list and the tiles already do).*
8. **A password-shaped passage.** `build_request` refuses a question that looks like a key, but a **row or file text** that looks like one is not checked. A passage that holds `sk-ant-...` today would be sent. *Default: when 47d selects passages, it drops a passage matching `ask.SECRET_QUESTION` and the preview says `{c} parts were left out because they looked like passwords or keys` (a count only). This tightens, so it needs no approval to loosen; it belongs in 47d's selection, and it needs the lead's wish to widen 47d's scope.*
9. **What is in the data.** Design-47's Question 7 (hidden and Sensitive rows) decides whether `left_out`'s first two lines can ever be non-zero. *Default as design-47: nothing the published page hides and nothing Sensitive is sent.* The preview is built either way.
10. **OpenAI at v0.5.** The sentence names the provider from `provider.name`, so a second provider changes the sentence with no change here. When a provider sends the text to a different place, the "leave this computer" line changes with it. *Default: the same sentence for any provider; #54 reruns the preview tests on real providers.*

### D2. Ambiguities in the issue, and a proposed Done-when
- The issue calls the preview "worth having for Claude in v0.3 if cheap and needed with OpenAI", and the board "v0.5, ask clark lane". *Default: part B can ship in v0.4; the preview ships with the first real send (the first v0.3 send, if #47's route lands), otherwise v0.5, and is needed before OpenAI.*
- "About N words" in the sentence against the 40,000-character budget in details: two units. *Default: words in the sentence (human), characters in the details (the real limit).*
- Whether "sources by name" may show a file name. A name is a label relative to a folder, not a path, so it shows; paths never do.
- Whether the suggestion also shows in the Overview page. *Default: Edit only, as the Done-when says.*

**Proposed Done-when (extends the reviewer's four points):**
1. Before ask clark sends, the panel shows the one sentence and **Send** and **Cancel**; nothing leaves the computer until Send. A test asserts that the sentence, the details and the sent text all come from one `Request`, that a changed report between Preview and Send sends nothing, and that a planted secret, Sensitive row and hidden row appear in neither the request nor the preview.
2. The details show sources by name, parts, characters against 40,000, the provider, counts of what was left out, and the fixed "never sent" line; the exact text is one click away.
3. The suggested health appears beside the user's own in Edit, with its reasons by ID, by the three rules above, and never writes or replaces anything. **Use the suggestion** fills the form and saves nothing.
4. A user health better than the suggestion makes the reason required and not emptyable.
5. Pure functions, a test per rule and per boundary (exactly 7 days), every mutant above failing, wording pinned, no store, route, `reach` or clock import in either module.
6. The published page, the client tiles and the Excel export are byte-for-byte unchanged.

## E. What would stop the build and go back to the Head
- Any change to `store.py`, `server.py` beyond commit 6, `publish.py`, a guard test or the CSP.
- #47's `Request` or `Passage` changing shape before commit 4 (the preview reads both).
- Any wish to send a passage the design-47 default leaves out (hidden, Sensitive, secret-shaped), or to widen what is sent beyond the preview's list.
