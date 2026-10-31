/* clark prototype: Help, modelled on creaite's (its help.md, help.js and helpscreen.js). Three tabs from one source, Start here,
   How do I… and Reference, with a search over all of it, a grid of jobs, the keys and the icons. The tab used last is kept
   (C.store helpTab). Links in the text open another part of Help, or take you to the screen (C.go). The keys: ? opens Help from
   any page (when you aren't typing); in Help, / goes to the search box. The words describe the prototype as it is built. */
(function () {
  'use strict';
  const C = window.C, esc = C.esc;
  const MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');

  /* ── the small markup the text uses: **bold** a button or label, [[Mod+Enter]] keys, `code`, [words](#howto-id) a link to
     another part of Help (#start-…, #howto-…, #ref-…), [words](go:work) a link to a screen ── */
  const KEYS = { Mod: MAC ? '⌘' : 'Ctrl', Enter: 'Enter', Esc: 'Esc', Left: '←', Right: '→', Up: '↑', Down: '↓', Space: 'Space', Tab: 'Tab' };
  const kbd = k => k.split(/\+(?!$)/).map(p => `<kbd>${KEYS[p] || p}</kbd>`).join('+');
  const md = s => esc(s)
    .replace(/\[\[(.+?)\]\]/g, (_, k) => kbd(k))
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[([^\]]+)\]\((#|go:)([^)]+)\)/g, (_, t, kind, to) => kind === '#' ? `<a href="#" class="hp-a" data-hlink="${to}">${t}</a>` : `<a href="#" class="hp-a hp-goa" data-hgo="${to}">${t}</a>`);

  /* where a "go:" link takes you: a screen, a place on it, or an action */
  const GO_LABEL = { dashboard: 'Open the Dashboard', 'dashboard+edit': 'Open the Dashboard in Edit', work: 'Open Work items', milestones: 'Open Milestones', usecases: 'Open Use Cases', settings: 'Open Settings', publish: 'Open the Publish box', preview: 'Preview the page', ask: 'Open ask clark' };
  const goLabel = to => GO_LABEL[to] || (to.startsWith('settings#') ? 'Open Settings' : 'Open it');
  function goTo(to) {
    const [v, anchor] = to.split('#');
    if (v === 'ask') return C.askOpen();
    if (v === 'preview') return C.P() && C.publish('tab');
    if (v === 'publish') { C.go('dashboard'); if (C.P()) C.publishDialog(); return; }
    if (v === 'dashboard+edit') { C.go('dashboard'); C.UI.editing = true; C.render(); return; }
    C.go(v, { keepScroll: !!anchor });
    if (anchor) setTimeout(() => { const el = document.getElementById(anchor); if (el) el.scrollIntoView({ block: 'start', behavior: C.reduce ? 'auto' : 'smooth' }); }, 40);
  }

  /* ═════════════ Start here ═════════════ */
  const START = {
    label: 'clark · first day',
    title: 'Keep the record. Shape the report. Publish it.',
    lead: 'In clark you keep one project record of work items, milestones and use cases, shape the weekly report from it, and publish the report as a web page (and a Word document if you like) for the client. Every change saves on its own, and every change can be undone.',
  };
  const LOOP = [
    { n: 'In', t: 'Bring it in', ic: 'ul', d: 'Import from Excel: actions, risks and issues, decisions, milestones and use cases. Or add them by hand with the **+** buttons.' },
    { n: 'Update', t: 'Keep it current', ic: 'pencil', d: 'On Work items and Milestones, open anything in the peek and change it where it is.' },
    { n: 'Edit', t: 'Shape the report', ic: 'doc', d: 'On the Dashboard, press **Edit**. Write the current state, set the health and choose what the client sees.' },
    { n: 'Check', t: 'Check it', ic: 'chat', d: 'In ask clark, choose **Check this report**. It points out what looks wrong, such as an overdue action left off the page.' },
    { n: 'You', t: 'Publish', ic: 'ext', gate: 'Your call', d: 'Publish from the profile circle. Local is always saved; the client folder only when you tick **To client**.' },
  ];
  const FIRST = [
    { t: 'Say who you are', d: 'In [Settings › Profile](go:settings#profile), fill in your name. It goes on every change you make, and your initials go in the circle at the top right.' },
    { t: 'Pick a project', d: 'The project name in the top bar switches projects. **New project…** in the same menu adds one.' },
    { t: 'Bring in the work', d: 'On [Work items](go:work), press the import icon. **Get the template** gives you a workbook with the right columns.' },
    { t: 'Say where reports go', d: 'In [Settings › Publishing](go:settings#publishing), set a local folder and, if the client has one, their SharePoint folder.' },
    { t: 'Look before you publish', d: '**Preview the page in a new tab**, in the profile circle menu, shows exactly what the client will see. Nothing is saved.' },
  ];
  const JOBS = [
    ['write-the-weekly-report', 'Write this week’s report', 'Current state, summary and health, in place.', 'dashboard+edit'],
    ['add-a-work-item', 'Add a work item', 'An action, risk, issue or decision.', 'work'],
    ['find-work-items', 'Find any work item', 'Type, Open or Closed, filters and search.', 'work'],
    ['use-the-board', 'Move work on the board', 'Drag a card to change it, with Undo.', 'work'],
    ['change-an-item-in-the-peek', 'Change an item', 'Everything about it, in the peek.', 'work'],
    ['choose-what-the-client-sees', 'Choose what the client sees', 'The eye, and Add from your project record.', 'dashboard+edit'],
    ['update-a-milestone', 'Update a milestone', 'State, dates, progress and client wording.', 'milestones'],
    ['handle-a-slipped-milestone', 'Deal with a slipped milestone', 'Hold, move the agreed date, recover or escalate.', 'milestones'],
    ['import-and-export', 'Import or export Excel', 'One workbook in, one workbook out.', 'work'],
    ['check-the-report', 'Check the report', 'ask clark finds what looks wrong.', 'ask'],
    ['publish-the-report', 'Publish the report', 'Local, to the client, and Word.', 'publish'],
    ['undo-a-mistake', 'Undo a mistake', 'Every change has a way back.', 'dashboard'],
  ];
  const WHERE = [
    ['Dashboard', 'The weekly report itself. **View** shows it as the client will read it; **Edit** changes it in place.', 'dashboard'],
    ['Work items', 'Every action, risk, issue and decision, as a table or a board, with filters and search.', 'work'],
    ['Milestones', '**Plan** shows every milestone on a timeline or calendar; **Movement** shows slippage, for you and the team only.', 'milestones'],
    ['Use Cases', 'Every use case of the project, on the dashboard or not, with where it stands, next steps, milestones and history.', 'usecases'],
    ['ask clark', 'Checks the report and answers questions about the project. Opens from the top bar, or with [[/]].', 'ask'],
    ['The profile circle', 'Publish, Preview, Export to Excel, Settings and Dark mode. At the top right.', ''],
    ['Settings', 'Your profile and look, projects, Asking (ask clark on or off, and the folders it may read), publishing, data, the clark version and updates, and diagnostics.', 'settings'],
  ];
  const RULES = [
    ['Every change saves on its own', 'There is no Save button. A change is kept as you make it, and the message at the foot of the page offers **Undo**.'],
    ['Only what you show is published', 'Items, sections, tiles and documents you leave out are dropped from the published file, not hidden inside it.'],
    ['Nothing is sent without you', 'Publishing saves files. The client folder is used only when you tick **To client**. Nothing is ever emailed.'],
    ['ask clark reads; you decide', 'It works from this project’s data and the source folders you list, never mail, Teams or calendars. What it changes can be undone.'],
  ];

  /* ═════════════ How do I… ═════════════ */
  const GROUPS = ['Every week', 'Work items', 'The report', 'Milestones', 'Writing', 'Settings and safety'];
  const TASKS = [
    /* ── Every week ── */
    { id: 'write-the-weekly-report', g: 'Every week', t: 'Write this week’s report', w: 'Dashboard › Edit', go: 'dashboard+edit', s: [
      'Open the **Dashboard** and press **Edit** at the top. The line beside it says “Editing · each change saves on its own”.',
      'Set **Week ending** to the Friday the report covers. The cover shows it as “Week ending Friday 30 October 2026”.',
      'Click the text under **Current state** and write where the project stands. It turns into an editor where it is: there is no Save button. Click away or press [[Mod+Enter]] to keep it; [[Esc]] cancels.',
      'Write **Summary**, **This week** and **Next week** the same way. In an empty section, type [[/]] and choose **Draft with AI** for a first draft from the project.',
      'Set the health on the **Project health** tile: see [Set the project health](#howto-set-the-health). Under it, a line suggests a health from the data.',
      'Check the lists of risks and issues, open actions and decisions. Click any part of a row (the state, the title, the owner, the date) to change it there; the ID opens the whole item in the peek.',
      'Press **View** to read the report as the client will.' ],
      n: 'In this prototype, Draft with AI and the other AI options are written by rules, not by Claude.' },
    { id: 'set-the-health', g: 'Every week', t: 'Set the project health', w: 'Dashboard › Edit › Project health', go: 'dashboard+edit', s: [
      'In Edit, press the health pill on the **Project health** tile and choose **On track**, **At risk** or **Off track**.',
      'Write why in the box beside it, in a line or two. It saves when you leave the box, or with [[Mod+Enter]]; [[Esc]] puts the old reason back.',
      'Under the reason, **Suggested** gives a health worked out by plain rules, with its reasons: an action overdue by more than 7 days, a milestone that has slipped, two or more red risks or issues. One rule makes it **At risk**; all three make it **Off track**. **Use the suggestion** takes it; your own choice always stays.',
      'If you choose a better health than the suggestion, the reason is needed: the box asks you to say why and will not stay empty.',
      'The tile’s outline takes the health’s colour.' ],
      n: 'ask clark’s check warns you when the health says On track but a milestone has slipped, or when the reason is missing.' },
    { id: 'check-the-report', g: 'Every week', t: 'Check the report with ask clark', w: 'Top bar › ask clark · [[/]] · [[Mod+J]]', go: 'ask', s: [
      'Open **ask clark** from the top bar, or press [[/]] when you aren’t typing in a box. It opens down the right-hand side. Above the box, one sentence says what a question sends: this project’s work items, milestones and use cases, the size in words, any named source folders, and the provider (Claude). **Show details** lists each part.',
      'Press **Check this report**. It lists what to look at: an overdue action left off the page, a health that doesn’t match the milestones, a missing reason, items on the page with no latest update, a use case On track with overdue work, an empty Summary, and no supporting documents from this week.',
      'Some notes come with a button that fixes them at once, such as **Show them** or **Set it to At risk**. Each fix has **Undo**.',
      'Ask anything else in your own words, or press a suggestion: **What’s overdue?**, **Which risks are red?**, **Next milestone?**, **Summarise this week** (with **Use it as the Summary**) and **Use cases**. Item IDs in an answer open the item.',
      '**+** at the top starts a new chat. [[Esc]] or a click outside closes the panel. Drag its left edge to make it wider; a double-click puts it back.' ],
      say: ['Check this report', 'draft an update for PDF-A-012', 'who has the most actions?'] },
    { id: 'publish-the-report', g: 'Every week', t: 'Publish the report', w: 'Profile circle › Publish…', go: 'publish', s: [
      'Press your profile circle at the top right and choose **Publish…**. It opens the Dashboard first.',
      '**Local** is always ticked. The save window opens where you last saved for this project, and you choose the folder and the name.',
      'Tick **To client** to send it to the client folder set in Settings › Publishing as well. With no folder set, the box is off and says so, with a link to Settings › Publishing. A line reminds you that the client will see the page.',
      'Tick **Also a Word document** for a Word copy beside the web page, and **Also a PDF** for a PDF: your browser’s print box opens on the page in a new tab, and you choose **Save as PDF**.',
      'At the top of the box, a yellow note may say how many items have no owner or date, or were not reviewed in 14 days. **Show them** opens Work items filtered to them. It is a warning only: you can still publish.',
      'The box says which publication this will be. Each publish gets the next number, and a copy of the page is kept: see [Find a past publication](#howto-find-a-past-publication).',
      'Press **Publish locally** (or **Publish and send to the client**). The line at the top of the Dashboard then says when it was published, and whether to the client or locally.',
      'To look first, choose **Preview the page in a new tab** in the same menu. Nothing is saved.' ],
      n: 'In this prototype, To client is not sent: the message says where it would go. The file is named after the week ending date and the project, for example “2026-10-30 Data Platform Pilot weekly report.html”. The page ends with “Publication 3 · 30-10-2026”.' },
    { id: 'check-before-you-publish', g: 'Every week', t: 'See what has gone stale before you publish', w: 'Profile circle › Publish… · Work items › is:quiet in the filter line', go: 'publish', s: [
      'Open the Publish box. If any open item has no owner or no due date, a note says so (“3 items have no owner or date”); another says how many open items were not reviewed in 14 days.',
      'Press **Show them**. Work items opens with the **Freshness** filter set to exactly those items.',
      'Open an item. Under its title, “Raised … · Last reviewed …” say when it came in and when someone last changed it by hand. A grey chip, **Not reviewed in 14 days**, shows when that is overdue.',
      'Change anything on the item by hand, or fill in its owner and date, and it is fresh again.' ],
      n: 'Last reviewed is worked out from the item’s change history. Changes made by ask clark, an Excel import or an Undo do not count as a review.' },
    { id: 'find-a-past-publication', g: 'Every week', t: 'Find or open a past publication', w: 'Settings › Published reports · profile circle › Published reports', go: 'settings#pubs', s: [
      'Press your profile circle and choose **Published reports**, or go to Settings and find the **Published reports** card for the open project.',
      'Each row has the publication’s number, the date and time, where it went (Local, or Local and to client), and who published it. The newest is first.',
      'Press **Open** to see the page as it was published, in a new tab. The foot of the page says “Publication N” and the date.',
      'The last 10 copies are kept. An older row stays in the list, marked **Not kept**.' ] },
    { id: 'start-from-last-report', g: 'Every week', t: 'Start from last week’s report and see what changed', w: 'Dashboard › Edit', go: 'dashboard+edit', s: [
      'On the **Dashboard**, press **Edit**. Above the report, **Since the last report (Publication N, date)** lists what changed after the last publication: items opened and closed, status, due date and owner moves, milestone dates that moved, and decisions made. Each ID opens the item. Only you see it: it is never published.',
      'Before anything has been published it says “Not published yet, so there is nothing to compare with.”',
      'Press **Start from last week’s report** in the bar at the top. It copies the text of Summary, This week, Next week and any other text sections from the last publication into this week’s report, after you confirm. Nothing else changes, and one **Undo** puts it back.' ],
      n: 'The button is dimmed until the project has been published once, and when the copy of the last publication is no longer kept.' },
    { id: 'save-as-a-pdf', g: 'Every week', t: 'Save the report as a PDF', w: 'Profile circle › Publish…', go: 'publish', s: [
      'Open the Publish box and tick **Also a PDF**.',
      'Press **Publish locally**. The web page is saved as usual, and the page opens in a new tab with your browser’s print box over it.',
      'In the print box, choose **Save as PDF**. The PDF has the four tabs one after another, no buttons or menus, each section kept whole, light colours only, and the publication number and page number at the foot of each page.' ],
      n: 'Prototype: this uses your browser’s print box. The real clark makes the PDF with Chrome and checks its text before it is kept.' },
    /* ── Work items ── */
    { id: 'add-a-work-item', g: 'Work items', t: 'Add a work item', w: 'Work items · Dashboard › Edit · any editor', go: 'work', s: [
      'On **Work items**, press the **+** at the top right. Point at it and it shows what it adds, following the type in the filter line: **Add action** with type:action, **Add decision** with type:decision, and otherwise a menu of Action, Risk, Issue and Decision.',
      'The new item opens in the peek with its title selected: type over it. It is client-visible to start with, due in a week (a decision is dated today).',
      'In the report’s Edit mode, the last row of each list adds one: type “Owner: what it is”, for example “Jo Ellis: send the test plan”, and press [[Enter]]. A use case’s next steps add an action the same way.',
      'Selected text in any editor can become an item too: **Make into** in the AI menu ([Improve wording with AI](#howto-improve-wording-with-ai)).' ],
      n: 'IDs follow creaite’s: actions CODE-A-001, decisions CODE-D-001, and risks and issues share one series, CODE-001.' },
    { id: 'find-work-items', g: 'Work items', t: 'Find and filter work items', w: 'Work items', go: 'work', s: [
      'One **filter line** above the list does all the finding (a prototype for you to try). Type a field and a value, such as status:Open or owner:"First Last" (a full name goes in quotes); press [[Enter]] or a space and it becomes a chip. **×** on a chip removes it, and so does [[Backspace]] in an empty line.',
      'The fields are type:, status:, owner:, priority:, due:, workstream:, usecase:, milestone:, client: and is: (open, closed, overdue, quiet for not reviewed in 14 days, incomplete for no owner or no date, needed from the client). owner:me finds your own items once your name is in Settings.',
      'A minus leaves things out (-status:Closed), no: finds what is missing (no:owner), a comma means either (status:Open,Pending), and dates are in plain words (due:overdue, due:next-7-days). Plain words search the titles.',
      'As you type, a list offers the fields, then their values with how many items have each: the arrow keys choose, [[Enter]] accepts, [[Esc]] closes the list. Press [[/]] on Work items to go to the line. A word the line does not know says what it can offer instead, and is not applied.',
      '**Saved views** are the tabs above the line, with their counts: Open items, Overdue, Waiting on the client and My actions to start with. A dot shows when the line differs from the view; **Save view** keeps the change, and **Save as a new view…** adds a tab. Views are yours, for each project.',
      'The line is kept for each project while this browser tab is open. A tile on the Dashboard, or **See all work items** on a use case, opens Work items already filtered to what it counts.' ] },
    { id: 'use-the-board', g: 'Work items', t: 'Group work and use the board', w: 'Work items › View · Table and Board', go: 'work', s: [
      '**View** holds Group by and the swimlanes. **Group by** chooses the groups: Workstream, Status, Due, Owner, Priority, Milestone, Type, or Nothing (the table only). In the table, a group’s heading collapses it, and clark remembers.',
      'The two icons beside View switch between **Table** and **Board**. The board’s columns follow Group by (Status when it is Nothing).',
      'On the board, **View** also has the **swimlanes**, rows across the board: No lanes, Workstream lanes or Type lanes.',
      'Drag a card to another column to change that field. **Due** asks for the new date (never a past one); **Overdue** isn’t a place to drop; **No date** clears it. A move across a lane and a column changes both in one step.',
      'From the keyboard, or for a precise move, press **⋯** on a card and choose from **Move to…**: the columns, then the lanes.',
      'Press a column’s heading to collapse it. Drag a heading onto another column to move it, or press [[Alt+Left]] or [[Alt+Right]] on it. Drag a column’s right edge to make it wider or narrower (260 to 640 pixels); the arrow keys move it 16 pixels, and a double-click puts it back.',
      'Every move has **Undo** in the message. Click a card, or press [[Enter]] on it, to open it.' ],
      n: 'A move that doesn’t fit says so: an action can’t be Made, and nothing changes its type by moving.' },
    { id: 'change-an-item-in-the-peek', g: 'Work items', t: 'Change an item in the peek', w: 'Any work item: a row, a card or its ID', go: 'work', s: [
      'Click a row, a card or an ID. The item opens in the **peek** at the right, and the page stays where it was.',
      'Click the title to change it. [[Enter]] keeps it; [[Esc]] puts it back.',
      'Under the title are **Status**, **Priority**, **Owner** and **Due**. Click one to choose another value. A risk’s or issue’s status menu also sets its colour (Red, Amber or Green), which sets its priority. The due date offers Today, Tomorrow, Friday, Next week and No date.',
      'A warning shows when an action is overdue or due on a weekend, with one-click fixes such as **Move to Friday**.',
      'Under the properties, “Raised … · Last reviewed …” show how fresh the item is, with a **Not reviewed in 14 days** chip when it is. **Needed from the client** switches the item on to the client’s list: see [Ask the client for something](#howto-ask-the-client-for-something).',
      '**Latest update**: click to write it. **Draft** writes one from the item’s own facts.',
      '**Details** holds the description, type, workstream, milestone, use case and client wording. It stays open or closed as you last left it.',
      'At the foot, **All**, **Activity**, **Updates** and **Source** show the item’s history and where it came from. **Activity** lists every change, newest first, and has a filter: **All**, **Changes**, or **Comments and updates**.',
      'With the peek open, click another item anywhere on the page and the peek moves to it. A click elsewhere, or [[Esc]], closes it. The up and down arrows at the top step through the list.' ],
      n: 'Drag the peek’s left edge to make it wider (a double-click puts it back), or press the corners icon to take it across the whole screen. Your width is kept.' },
    { id: 'change-an-item-in-words', g: 'Work items', t: 'Change an item in words (Sneak peek)', w: 'An open peek › the sparkle, or [[/]] [[/]]', go: 'work', s: [
      'With an item or milestone open in the peek, press [[/]] twice quickly (when you aren’t typing in a box), press the sparkle at the top, or press “Change this item in words” at the foot.',
      'Type the change, for example “move to Friday, owner Jo, high priority”.',
      'The words clark read are marked above the box, and a card shows each field before and after.',
      'Press [[Enter]] (or [[Shift+Enter]]), or **Make the change**, to save it. **Not now** or [[Esc]] closes it. The fields that changed flash for a moment, and the message has **Undo**.',
      'In an empty box, [[Up]] brings back your last instruction.' ],
      n: 'If a name could be two people, it says so and asks for the full name. See [Sneak peek](#ref-sneak-peek) for every phrase it understands.' },
    { id: 'choose-what-the-client-sees', g: 'Work items', t: 'Choose what the client sees', w: 'Work items · the peek · Dashboard › Edit', go: 'dashboard+edit', s: [
      'On Work items, the eye in each row’s last column turns client-visible on or off. In the peek, it is the eye at the top.',
      'On the Dashboard in Edit, the eye beside a row takes it off the page. The row greys while **Undo** is offered, then leaves.',
      '**+ Add from your project record** under a list brings items back. A picker opens: search, choose a kind, tick what you want (or **Select all shown**) and press **Add**.',
      'Milestones, use cases, supporting documents and tiles have their own eye and their own **Add back**. A whole section is left out from its options: **Leave out of the published page**.',
      'An item’s **Client wording** (in the peek’s Details) is used on the page in place of its title. A milestone has the same, under **Client view**.' ],
      n: 'The report’s lists show only client-visible items. Everything else is left out of the published file altogether.' },
    { id: 'import-and-export', g: 'Work items', t: 'Import or export Excel', w: 'Work items toolbar · Settings › Data · profile circle', go: 'work', s: [
      '**Export**: press the down-arrow icon. You get one workbook with a sheet each for Actions, Risks and issues, Decisions, Milestones and Use cases, named after today and the project.',
      'The Use case summary has its own export icon (in View), for the use cases alone.',
      '**Import**: press the up-arrow icon. The box lists the sheets and columns it reads. **Get the template** downloads a workbook with the right columns.',
      'Press **Choose a file** (Excel or CSV). **Check the import** shows how many rows are new, updated or skipped, and the first few. Press **Import** to save them.',
      'A row with an ID that exists updates that item; a row without one adds a new item. Only the title or name is needed. A new workstream is added to the project.' ],
      n: 'The whole import is one step: one **Undo** takes it all back.' },
    /* ── The report ── */
    { id: 'arrange-the-report', g: 'The report', t: 'Arrange the report’s sections', w: 'Dashboard › Edit', go: 'dashboard+edit', s: [
      'In Edit, each section has a control in the margin at the left of its card: a **grip** and, under it, a **+**. They are faint until you point at the section or tab to them.',
      'Drag the grip to move the section, or focus it and press [[Alt+Up]] or [[Alt+Down]]. Click it, or press [[Enter]] or [[Space]] on it, to open the section’s menu.',
      'The menu has **Add a template below…**, then **Move up** and **Move down**, **Place beside the next section** (or **Full width** when it is already beside another), then **Leave out of the published page** (or **Include**) and, for a text section or a template, **Delete section**. A section that is left out shows an eye-off mark under its **+**.',
      'To rearrange the page, pick up a section by its grip and drop it. A line between rows puts it on a row of its own; the left or right half of a section that is on its own puts the two side by side, half the width each. A row never holds more than two. The cover stays at the top. Each drop is one step you can undo, and on a phone a pair stacks.',
      'Click a heading to rename it. [[Enter]] keeps it; [[Esc]] puts it back.',
      'A section left out stays in Edit, greyed, and disappears in View and on the published page.' ] },
    { id: 'add-a-section-from-a-template', g: 'The report', t: 'Add a section from a template', w: 'Dashboard › Edit › the + under a section’s grip', go: 'dashboard+edit', s: [
      'On the **Dashboard**, press **Edit**. Press the **+** under the grip of the section you want the new one to follow, or open its menu and choose **Add a template below…**.',
      'The **Add a section** box opens. Choose a kind on the left (on a phone the kinds are a row of chips along the top), or type in **Search templates**. [[Left]], [[Right]], [[Up]] and [[Down]] move through the templates; the preview on the right shows what the chosen one holds.',
      'Under **Where it goes**, choose **On its own row** or, when the next section is on a row of its own and the template can be half width, **Beside** that section.',
      'Press **Add section** (or [[Enter]]). The new section appears with its heading ready to rename; [[Esc]] closes the box without adding anything.',
      'Every template other than **Text** and **Needs from you** is empty when you add it, with each of its parts labelled. Filling the parts in comes in a later release; until then an empty template is left out of the published page. **Needs from you** works at once, from live data and the lines you add, and is published.',
      'One **Undo** takes the new section away again. See [Section templates](#ref-section-templates) for what each one is for.' ] },
    { id: 'ask-the-client-for-something', g: 'The report', t: 'Ask the client for something', w: 'The peek › Needed from the client · Dashboard › Edit › Add a section', go: 'dashboard+edit', s: [
      'Open the item in the peek and switch on **Needed from the client**. A pending decision is listed without it. Turn its eye on, so the client can see it.',
      'On the Dashboard, press **Edit**, then the **+** under a section’s grip, and choose **Needs from you** (under Work items). Place it on its own row or beside another section; on the published page it always sits straight after At a glance.',
      'The section lists every pending decision and every item you switched on: what it is, who and by when (“Needed by 05-11-2026”, or “No date set”) and its ID. A line past its date says **Overdue** in words, not just in red. To ask for something that is not a work item, fill in **What is needed**, **Owner** and **Due** under the list and press **Add**. **Due** opens clark’s own calendar, so the date reads DD-MM-YYYY; a line with no owner says “Not assigned yet”.',
      'A line you added is never deleted: **Archive** takes it off the list, and **Archived** under the list brings it back with **Restore**. When there is nothing to ask, the editor says “Nothing needed from you this week.” and the published page leaves the section out.',
      'The section is part of the report, so it is published. Switch the item off, close it or hide it from the client, and it leaves the list. To remove the whole section, use **Delete section** in its menu; **Undo** brings it back.' ] },
    { id: 'use-the-tiles', g: 'The report', t: 'Use the At a glance tiles', w: 'Dashboard › At a glance', go: 'dashboard', s: [
      'Next to **Project health** are the counts: **Overdue actions**, **High risks and issues** and **Decisions needed** (hidden to start with).',
      'Click a count, or press [[Enter]] on it, to open Work items filtered to exactly what it counts.',
      'In Edit, drag a tile to reorder it, or press [[Alt+Left]] or [[Alt+Right]]. The eye hides a tile: it is left out of the published page.',
      'Right-click a tile in Edit for **Tile colour**: **Automatic, from the data**, Green, Amber, Red or **No colour**.' ],
      n: 'The colour is a thin outline that fades from the bottom-left corner. Automatic is red when an action is overdue or a risk is red, amber when something waits, and green otherwise. A coloured tile also says its status in words beside its number: On track, At risk or Off track (Overdue on Overdue actions, Waiting on Decisions needed, Watch or High on High risks and issues). When the Project health tile’s colour is set by hand to something other than its pill, the words say so: for example “Tile colour: Off track”. No colour means no word.' },
    { id: 'keep-the-use-cases', g: 'The report', t: 'Keep the use case summary', w: 'Dashboard › Use case summary', go: 'dashboard', s: [
      'The section opens with a strip: how many use cases, a count for each status and a small meter. Then one slim row each: the ID, the name, the headline, the status and the open next steps.',
      'Click a row (or press [[Enter]] or [[Space]]) to open its detail in place: **Where it stands** and **Next steps**. **See all work items** opens Work items filtered to that use case.',
      'In Edit, **+ Add use case** asks for an ID, a name, a status and a headline. Click the headline or the name to change it; click the status word to choose **On track**, **Flag** or **High risk**.',
      'In the detail, write **Where it stands** (with **Draft from the project** in its AI menu), add a next step as “Owner: what it is”, or **+ Link an existing work item**.',
      '**Delete use case** asks first. Its work items stay and lose the link.' ] },
    { id: 'work-the-use-cases', g: 'The report', t: 'Work through every use case', w: 'Use Cases', go: 'usecases', s: [
      'Open **Use Cases** in the top bar. It lists every use case of the project, with a strip of counts and a meter at the top. Each row shows the reference, the name, where it stands, the status word, the work items (how many, and how many are open) and, on the right, the eye.',
      'The eye says **On the dashboard** or **Not on the dashboard**. It is the same switch as the one on the Dashboard: a use case that is on shows in the Use case summary and on the published page. One that is off stays on this page, muted.',
      'Select a row, or its arrow, to open the detail under it: the name and headline (click to change them), **Where it stands**, the next steps with their owner, ID and due date, the linked milestones and the history of changes.',
      'Click the status word to choose **On track**, **Flag** or **High risk**. Add a next step as “Owner: what it is”, or **+ Link an existing work item**. Every change is one step with **Undo**.',
      'Narrow the list with the **Group** pill (tick Group 1, 2 or more: Group 1 shows every 1.x), the **Status** pill, **All**, **On the dashboard** or **Not on the dashboard**, and the search box. **Sort** orders by use case number, status, open work items or name. Your choices are kept for each project.',
      'There is no Add or Archive on this page: new use cases come from the project record, or from an Excel import with a Use cases sheet. The export icon saves the use cases to Excel.' ] },
    { id: 'add-supporting-documents', g: 'The report', t: 'Add supporting documents', w: 'Dashboard › Edit › Supporting documents', go: 'dashboard+edit', s: [
      'In Edit, press **+ Add a document link** at the foot of the report.',
      'Give it a title, a kind (Minutes, Actions list, Report, Slides, Plan or Other), the link and a date, then press **Add**.',
      '**⋯** on a document edits or archives it. The eye takes it off the page; **+ Add back a document** brings it back. An archived document is never deleted: **Archived** under the list brings it back with **Restore**.',
      'In View, and on the published page, the title and the arrow open the document in a new tab.' ] },
    { id: 'change-the-layout-and-look', g: 'The report', t: 'Change the look', w: 'Settings › Personal', go: 'settings', s: [
      '**Personal › Dashboard sections** is yours alone: **Slim gaps** (the standard), **Roomy gaps**, **Grey headers** or **One card**.',
      '**Personal › Appearance** is **Light**, **Dark** or **System**. System is the standard: it follows your Mac’s setting and changes when the Mac does. **Dark mode** in the profile circle menu sets Light or Dark outright.' ] },
    /* ── Milestones ── */
    { id: 'update-a-milestone', g: 'Milestones', t: 'Add or update a milestone', w: 'Milestones · Dashboard › Milestones', go: 'milestones', s: [
      'On **Milestones**, press **+** (**Add milestone**). A new one, 30 days out, opens in the peek with its name selected: type over it.',
      'Click any milestone to open it: its mark or label on the timeline, its chip on the calendar, or its row in the details.',
      '**State**: Forecast, On track, At risk, Slipped or Achieved. Overdue follows the dates and can’t be picked. The line under it says why the milestone has that state.',
      '**Dates**: the **Agreed** date is the baseline; change the **Forecast** date as things move. When they differ, **Move the agreed date…** makes the forecast the new agreed date and keeps the original.',
      '**Progress** is set by hand with the slider or the number. Add a **Description**, the **Owner** and the **Workstream**.',
      '**Client view**: **Visible to client**, and the **Client wording** used on the page in place of the name.',
      '**Linked work items** lists the items tied to it. Link one from the item’s peek, under Details, Milestone.' ] },
    { id: 'read-the-milestones', g: 'Milestones', t: 'Read the timeline and calendar', w: 'Milestones › Plan · Dashboard › Milestones', go: 'milestones', s: [
      'The **Timeline** scrolls sideways. The arrows move along it and **Today** comes back. Drag its bottom edge to zoom in or out; **Reset** puts it back.',
      'A slipped milestone keeps its mark on the agreed date, with a dashed ring where it is now expected and a dashed line between them.',
      'The two icons at the top right switch between **Timeline** and **Calendar**. Your choice is kept.',
      'The calendar shows **Week**, **Month** (the standard) or **Quarter**, with the arrows and **Today**. In Quarter, click a month’s name to open that month.',
      '**Legend**, at the right under the milestones, explains every mark when you point at it or tab to it.',
      '**Show milestone details** lists them with their date, state and progress. The first five show; **Show all** shows the rest.' ],
      n: 'On the published page, Slipped reads “Expected later” and Overdue reads “Late”.' },
    { id: 'handle-a-slipped-milestone', g: 'Milestones', t: 'Deal with a slipped milestone', w: 'Milestones › Movement', go: 'milestones', s: [
      'On **Milestones**, press **Movement**. It is for you and the team: it is never published.',
      'The first line says how many open milestones are behind, and which is furthest behind.',
      'Each row has a track: a diamond for the original date (when the agreed date has moved), a bar for the agreed date, the forecast mark, a red line for the distance past agreed, and today. At the right, how far it is from the agreed date (“On the agreed date”, “4 days after the agreed date”) and whether the agreed date has moved or “Never moved”.',
      'Click a row to choose it. Its card shows the dates, how often it moved, and **What changed**.',
      'Then decide: **Hold** (notes that the agreed date stays), **Move the agreed date** (the agreed date moves to the expected date; the original is kept), **Add a recovery action** or **Escalate to steering**. The last two add a linked action or decision and open it.',
      'Write an **Internal note**. It saves when you leave the box and is never published.' ] },
    /* ── Writing ── */
    { id: 'format-text', g: 'Writing', t: 'Write and format text', w: 'Any longer text you click', go: 'dashboard+edit', s: [
      'Click the text. An editor opens where it is, with a bar of headings, bold, italic, strikethrough, lists, a checklist, indent and outdent, a quote, a divider, Link, Unlink, Clear, undo and redo, and **✦ AI**.',
      'Highlight some words and a small bar floats above them, with the same formatting and the AI menu.',
      'Type [[/]] at the start of a line or after a space for the command menu: Text, Heading 1 to 3, lists, a checklist, a quote, a divider and the AI options. Type to narrow it; [[Up]] and [[Down]] move, [[Enter]] inserts, [[Esc]] closes.',
      'Click away, or press [[Mod+Enter]], to keep the text. [[Esc]] cancels the edit.' ],
      n: 'Titles, headings and table cells are plain text: [[Enter]] keeps the change and [[Esc]] puts it back.' },
    { id: 'improve-wording-with-ai', g: 'Writing', t: 'Improve wording with AI', w: 'Any editor › select text › AI', go: 'dashboard+edit', s: [
      'Select some words. The floating bar has an AI part: **Format notes** (when you select two or more lines of a report section), **Improve**, **Structure**, **Make into** and **Ask…**.',
      'Or press **✦ AI** on the editor’s bar, or [[Alt+/]], for every option at once, on the selection or on the whole text. Where the field allows it, **Draft from the project** is first.',
      '**Improve**: Rewrite clearly, Shorter, Longer, Make it executive and Polish. **Structure**: Add headings and bold, Pull out the tasks and Summarise at the top. **Make into**: a new action, risk or decision from the text. **Ask…**: say what you want in your own words.',
      'The answer is a suggestion: your text is unchanged until you press **Accept** ([[Mod+Enter]]). **Show changes** marks what goes and what comes, word by word. **Try again** asks again; **Discard** ([[Esc]]) drops it.',
      'After you accept, the editor’s undo ([[Mod+Z]]) takes it back.' ],
      n: 'Item fields and client wording offer Improve and Ask; report sections offer Structure and Format notes as well. In this prototype, rules stand in for Claude, so the wording is mechanical.' },
    /* ── Settings and safety ── */
    { id: 'set-up-a-project', g: 'Settings and safety', t: 'Set up a project', w: 'Settings › Projects · the project switcher', go: 'settings', s: [
      'In **Settings › Projects**, press **+** (**Add project**). Give it a name, a short code (3 to 7 letters or digits, suggested from the name; it can’t change later), the client and its workstreams, separated by commas.',
      'A new project opens on Work items, ready for an import.',
      'Each project has **Open**, **Edit** and **Archive**. Archive hides the project and everything in it (its work items, milestones and use cases) from clark in one step, with **Undo**; nothing is deleted. To bring one back, turn on **Show archived** at the top of the Projects card and press **Restore**. Each step is also written in the history, as “Archived” and “Restored”.',
      'Under the projects, set this project’s **Asking** (ask clark on or off, and the folders it may read) and its **Publishing** folders.',
      'The project name in the top bar switches projects, shows each one’s open items, and has **New project…** and **Project settings**.' ] },
    { id: 'add-people-details', g: 'Settings and safety', t: 'Add people’s emails and roles', w: 'Settings › People', go: 'settings#people', s: [
      'Open **Settings** and find the **People** card. It lists everyone who owns a work item or a milestone. The line above the table says how many people still need details (“8 of 8 people need details”). **Show only these** lists just those people, each marked **Needs details**.',
      'Press **Paste from Excel**, then paste rows copied from a sheet: name, email, organisation and role, separated by tabs. A first row of headings is skipped.',
      'Press **Add to the list**. People are matched by name, so the owner pickers keep working on names. One **Undo** takes the paste back.' ],
      n: 'The table is read-only apart from the paste. Renaming, merging and picking from the address book come later.' },
    { id: 'set-your-profile', g: 'Settings and safety', t: 'Set your profile', w: 'Settings › Profile', go: 'settings#profile', s: [
      'Fill in your **Name**, **Alias**, **Email**, **Phone number** and **Organisation**.',
      'Each saves when you leave the box (or press [[Enter]]), with **Undo**.',
      'Your full name goes on every change you make, with where you made it, in each item’s history. Your initials fill the circle at the top right.' ],
      n: 'Your profile is kept on this computer only. Reset demo data keeps it.' },
    { id: 'undo-a-mistake', g: 'Settings and safety', t: 'Undo a mistake', w: 'The message at the foot of the page · the peek’s history', go: 'dashboard', s: [
      'Every change shows a message at the foot of the page with **Undo**, for about six seconds.',
      'A step of several changes undoes as one: an import, **Add from your project record**, a delete with everything under it, a board move across a lane and a column.',
      'The peek’s **Activity** shows every change, newest first: the date and time (your local time), who made it and where (in the peek, in the table, on the board, in the report, with the eye, by Excel import, via ask clark, with a draft, or by undo), the field by name, and what it was and what it became. Use its filter (**All**, **Changes**, **Comments and updates**) to narrow it. A latest update or note shows just the words that changed. Creating, deleting, restoring and undoing are listed too, and nothing is ever removed from the history. A milestone’s moves are also in **Movement › What changed**.',
      'In an editor, the undo button or [[Mod+Z]] steps back through your typing. [[Esc]] cancels the whole edit.',
      '**Reset demo data**, at the foot of the page or in Settings › Data, puts the prototype back as it started.' ] },
    { id: 'update-clark', g: 'Settings and safety', t: 'Update clark', w: 'Settings › clark version and updates', go: 'settings#update', s: [
      'Open [Settings](go:settings#update) and find **clark version and updates**. **Installed** is the version you have now.',
      'Download the new release, clark-X.Y.Z.zip, from the release page. If it is in Downloads, **Update** shows **Review X.Y.Z**; otherwise press **Choose zip…** and pick the file. The source code zip is refused.',
      'Read the review: the version change, the release notes, the files replaced and added. Your projects, settings and published reports are kept, and everything is backed up first.',
      'Press **Install clark X.Y.Z**. When it is done, restart clark to finish.',
      'To go back, press **Undo update** in the **Last update** row, then **Confirm undo** within five seconds. More in [Updating clark](#ref-updating-clark).' ] },
  ];

  /* ═════════════ Reference ═════════════ */
  const ic = n => `<span class="hp-ic">${C.icon(n)}</span>`;
  const MS_STATES = [['Achieved', 'Done, on the date it was achieved.'], ['On track', 'Expected on its agreed date.'], ['At risk', 'Marked at risk by hand.'], ['Slipped', 'Now expected after its agreed date. On the published page: Expected later.'], ['Overdue', 'Its agreed date has passed and it isn’t achieved. On the published page: Late.'], ['Forecast', 'A date not yet agreed.']];
  const SHORTCUTS = [
    ['[[?]]', 'Help, from any page (when you aren’t typing in a box)'],
    ['[[/]]', 'ask clark (when you aren’t typing in a box). On Work items it goes to the filter line, and in Help to the search box, instead'],
    ['[[Mod+J]]', 'Open or close ask clark'],
    ['[[/]] [[/]]', 'With a peek open: Sneak peek, change it in words. A single [[/]] opens ask clark after a moment'],
    ['[[Esc]]', 'Close the top thing: a menu, the command menu, Sneak peek, ask clark, the peek. In an editor or a field, cancel and put the old text back'],
    ['[[Enter]]', 'In a title, a heading or a cell: keep the change. On a row, a card, a tile or a milestone: open it. In Sneak peek: make the change'],
    ['[[Shift+Enter]]', 'In Sneak peek: make the change too. In ask clark: a new line'],
    ['[[Mod+Enter]]', 'In an editor: keep the text and close it. On an AI suggestion: accept it. In the health reason: keep it'],
    ['[[Alt+/]]', 'In an editor: the AI menu, for the selected text or all of it'],
    ['[[/]] in an editor', 'The command menu, at the start of a line or after a space. [[Up]], [[Down]], [[Enter]] and [[Esc]] work in it'],
    ['[[Up]]', 'In an empty Sneak peek box: your last instruction'],
    ['[[Up]] [[Down]] [[Enter]]', 'In any menu: move and choose. [[Esc]] closes it'],
    ['[[V]] [[E]]', 'On the Dashboard: View mode and Edit mode, as the **View** and **Edit** buttons do (when you aren’t typing in a box, and no menu, box or peek is open)'],
    ['[[Alt+Up]] [[Alt+Down]]', 'Dashboard in Edit, on a section’s grip: move the section'],
    ['[[Enter]] or [[Space]]', 'Dashboard in Edit, on a section’s grip: open its menu. In the Add a section box, [[Enter]] adds the chosen template and the arrow keys move through them'],
    ['[[Alt+Left]] [[Alt+Right]]', 'Dashboard in Edit, on a tile: move the tile. On a board column’s heading: move the column'],
    ['[[Left]] [[Right]]', 'On a board column’s right edge: 16 pixels narrower or wider'],
    ['[[Enter]] or [[Space]]', 'On a use case row: open or close its detail'],
    ['[[Home]] [[End]]', 'In Help’s tabs, with [[Left]] and [[Right]]: move between the tabs'],
    ['[[Mod+Z]]', 'In an editor: undo your typing, or an accepted AI suggestion'],
    ['Double-click', 'On the left edge of the peek or ask clark, or a board column’s right edge: back to the usual width'],
  ];
  const ICONS = [
    ['plus', 'Add', 'Add an item, a milestone, a use case or a project. Point at it to see what it adds', 'Work items, Milestones, the report in Edit, Settings'],
    ['dl', 'Export to Excel', 'One workbook of the project, or of the use cases', 'Work items, the Use case summary, Settings (Export workbook), the profile circle'],
    ['ul', 'Import from Excel', 'Read a workbook and check it before it is saved. Also Publish…, in the profile circle', 'Work items, Settings (Import workbook), the profile circle'],
    ['rows', 'Table', 'Work items as a table, in groups', 'Work items'],
    ['board', 'Board', 'Work items as cards in columns', 'Work items'],
    ['eye', 'Shown to the client', 'Select to hide it from the client. Crossed out: internal only', 'Work items, the peek, the report in Edit'],
    ['tline', 'Timeline', 'Milestones on a line that scrolls sideways', 'Milestones, the Dashboard'],
    ['cal', 'Calendar', 'Milestones by week, month or quarter. Also any date', 'Milestones, the Dashboard, the peek'],
    ['info', 'Legend', 'What each milestone mark means', 'Under the milestones'],
    ['sparkle', 'Sneak peek, Draft', 'Change an item in words; draft the latest update', 'The peek'],
    ['close', 'Close', 'Close the peek', 'The peek'],
    ['expand', 'Across the whole screen', 'Widen the peek; the inward corners put it back', 'The peek'],
    ['up', 'Previous and next', 'Step through the list in the peek', 'The peek'],
    ['link', 'Copy link', 'Copy a link to the open item', 'The peek'],
    ['more', 'More', 'Duplicate or Archive; on a card, Move to…; on a document, Edit or Archive', 'The peek, board cards, documents'],
    ['drag', 'Grip', 'Drag to move a section, click for its menu, or Alt and the arrows', 'The report in Edit'],
    ['chev', 'Collapse', 'Collapse or open a group, or open a pick list', 'Work items, Milestones, the report in Edit'],
    ['pencil', 'Edit', 'Switch the Dashboard to Edit', 'Dashboard'],
    ['half', 'Status', 'An item’s status, in its colour', 'The peek'],
    ['bars', 'Priority', 'An item’s priority, in its colour', 'The peek'],
    ['flash', 'Warning', 'Overdue, or due on a weekend, with a fix', 'The peek'],
    ['clock', 'Last updated', 'When the item last changed', 'The peek'],
    ['doc', 'Document', 'A supporting document; a history entry', 'The report, the peek'],
    ['ext', 'Open in a new tab', 'Open a document; preview the page', 'The report, the profile circle'],
    ['folder', 'Source folder', 'A folder ask clark may read', 'Settings'],
    ['trash', 'Remove, Delete', 'Remove a folder or a report section', 'Settings, menus'],
    ['archive', 'Archive, Show archived', 'Archive a work item, a milestone or a document (never deleted); list the archived ones and Restore them', 'The peek, Work items, Milestones, documents'],
    ['gear', 'Settings', 'Settings', 'The profile circle, the project switcher'],
    ['moon', 'Dark mode', 'Switch the dark look on or off', 'The profile circle'],
    ['chat', 'ask clark', 'Open ask clark', 'The top bar'],
    ['search', 'Search', 'Find work items, or anything in Help', 'Work items, pickers, Help'],
  ];
  const REF_GROUPS = ['Screens', 'Working with items', 'Milestones', 'Writing and AI', 'Publishing', 'Settings and data', 'Keys and icons'];
  const REFS = [
    /* ── Screens ── */
    { id: 'top-bar', g: 'Screens', t: 'The top bar', b: [
      ['ul', ['**The logo** (or clark’s icon and name): back to the Dashboard.', '**The project name**: switch projects. Each shows its count of open items; **New project…** and **Project settings** are at the foot.', '**Dashboard**, **Work items** and **Milestones**: the three screens.', '**ask clark**: opens the assistant down the right. The [[/]] beside it is its key.', '**?** (on a phone): Help, beside ask clark.', '**The profile circle**: your initials (a person icon until you add your name). See [The profile circle](#ref-profile-circle).']],
      ['p', 'A note at the foot of every page says this is a prototype with demo data, kept in this browser’s database, with **Reset demo data**.'] ] },
    { id: 'profile-circle', g: 'Screens', t: 'The profile circle', b: [
      ['p', 'At the top right. Its menu has your name and email at the top, then:'],
      ['ul', ['**Publish…**: the Publish box, on the Dashboard. See [Publishing](#ref-publishing).', '**Preview the page in a new tab**: the page as the client will see it. Nothing is saved.', '**Export to Excel**: the whole project as one workbook.', '**Published reports**: Settings, at the list of numbered publications.', '**Settings**.', '**Dark mode**: ticked when it is on.']],
      ['p', 'Publish, Preview and Export appear only when a project is open.'] ] },
    { id: 'dashboard', g: 'Screens', t: 'Dashboard', w: 'The report editor', b: [
      ['ul', ['**View** and **Edit**: View shows the report as the client will read it. Edit changes it in place; each change saves on its own.', '**Week ending**: the date on the cover, and in the published file’s name.', 'The line beside it: “Editing”, “Published 30-10-2026 to the client” (or “locally”), or “Draft · not published yet”.', 'The cover: the project, then “WEEKLY REPORT · Week ending …” and who it is for.']],
      ['p', 'A single click on a work item row, outside its fields, opens it in the peek. In Edit, every part of the row changes in place.'],
      ['p', 'At the right edge, **On this page** is a quiet line for each section; the current one is longer and darker, and a warm one needs a look. Point at it, or tab to it, for the list with counts (late, red, slipped, flagged, pending) and **Back to top**. In a narrow window it is a small **On this page** button at the bottom right: click it, or tab to it and press [[Enter]], for the same list.'] ] },
    { id: 'sections', g: 'Screens', t: 'Report sections', b: [
      ['tbl', ['Section', 'What it shows'], [
        ['Current state', 'Where the project stands, in your words.'],
        ['At a glance', 'Project health with its reason, and the count tiles. See [At a glance](#ref-at-a-glance).'],
        ['Use case summary', 'A strip of counts, then a row per use case that opens in place.'],
        ['Milestones', 'The timeline or calendar, the legend and the details list.'],
        ['Summary, This week, Next week', 'Text sections. This week and Next week sit side by side to start with; any section can sit beside another.'],
        ['Risks and issues', 'Open risks and issues on the page: colour, title, owner, review date, priority and response.'],
        ['Open actions', 'Open actions on the page, with the due date and how late or soon.'],
        ['Decisions', 'Pending decisions, and any dated in the last 14 days.'],
        ['Supporting documents', 'Links to the week’s papers.'],
        ['Needs from you', 'Added from a template: what you need from the client, from pending decisions, items marked Needed from the client and lines you add. Published straight after At a glance, and left out when empty. See [Needs from you](#ref-needs-from-you).'] ]],
      ['p', 'Add more sections from the **+** under any section’s grip, or its menu’s **Add a template below…**. See [Section templates](#ref-section-templates). Rename any heading in Edit.'] ] },
    { id: 'section-templates', g: 'Screens', t: 'Section templates', w: 'Dashboard › Edit › Add a section', b: [
      ['p', 'Ready-made sections you add in Edit from the **+** under a section’s grip, or **Add a template below…** in its menu. In the **Add a section** box you pick one, choose **On its own row** or **Beside** the next section (half width), and press **Add section**. See [Add a section from a template](#howto-add-a-section-from-a-template).'],
      ['p', 'In this prototype an added template is empty, with each part labelled, and an empty template is left out of the published page and the Word file. **Text** is the exception: it adds an ordinary text section. Each template works at the widths shown.'],
      ['tbl', ['Template', 'What it is for', 'Fits'], [
        ['Text', 'Words under a heading, written in clark’s one editor.', 'Full or half'],
        ['Text and image', 'A story with a picture: a site visit, a design, a screenshot of the new system.', 'Full or half'],
        ['Banner', 'Open the report with a message: a milestone reached, a go-live, a change of phase.', 'Full'],
        ['Key figures, four', 'Three or four numbers with labels and a change since last week.', 'Full or half'],
        ['Key figures, three', 'The same, for three numbers. Each card is wider, so a short note fits under the change.', 'Full or half'],
        ['Image gallery', 'Two to six pictures in a grid, each with a caption.', 'Full'],
        ['Table', 'Anything with rows: a budget line, a cut-over plan, a training schedule.', 'Full'],
        ['Link preview', 'A web page shown as a card: a dashboard, a news item, a recording.', 'Full'],
        ['RAID cards, three', 'The risks, actions, issues or decisions you want the reader to see, as cards.', 'Full'],
        ['RAID cards, four', 'Four shorter cards: good for “this week’s actions” or “decisions needed”.', 'Full'],
        ['Work items list', 'Live rows from Work items, chosen by a filter: open actions due soon, red risks, decisions needed.', 'Full or half'],
        ['Documents and links', 'The papers that go with this week’s report.', 'Full or half'],
        ['Callout', 'One thing the reader must see.', 'Half or full'],
        ['Image with caption', 'One picture beside text.', 'Half or full'],
        ['Quote', 'A voice from the business.', 'Half or full'],
        ['Contacts', 'Who to ask.', 'Half or full'],
        ['Checklist', 'Next steps or readiness, ticked off.', 'Half or full'],
        ['Key dates', 'What’s coming, from the milestones.', 'Half or full'],
        ['One document', 'A single file to read.', 'Half or full'],
        ['Needs from you', 'What you need from the client: decisions, information and dates, each with an owner and a due date. Live from pending decisions and items marked “Needed from the client”, plus lines you add. It works now, is published straight after At a glance, and is left out when empty.', 'Full or half'] ]] ] },
    { id: 'needs-from-you', g: 'Screens', t: 'Needs from you', w: 'Dashboard › Edit › Add a section', b: [
      ['p', 'A section template for what you need from the client: decisions, information and dates. It is live from the first moment. It lists every open **pending decision** and every open item switched on with **Needed from the client** in its peek, as long as the client can see it (its eye on), plus the lines you add by hand under the list. Soonest first, each line shows the state, what is needed, the owner, by when (“Needed by 05-11-2026”, or “No date set”) and, for a work item, the ID, which opens it. A line past its date says **Overdue** in words, so it does not rely on colour.'],
      ['p', 'A line you added is archived, never deleted: **Archive** takes it off the list and **Restore**, under **Archived**, brings it back. When nothing is needed the editor says “Nothing needed from you this week.” On the published page the section sits straight after At a glance, and is left out altogether when there is nothing to ask. It appears in the Word file as a table.'] ] },
    { id: 'since-last-report', g: 'Screens', t: 'Since the last report', w: 'Dashboard › Edit', b: [
      ['p', 'A panel above the report in Edit, headed “Since the last report (Publication N, date)”. It is worked out from the change history after the last publication, and is for you only: it is never in the published page.'],
      ['ul', ['**Opened** and **Closed**: work items added and closed.', '**Decision made**.', '**Status, due date and owner moves**, as “PDF-A-012 due 01-11-2026 → 05-11-2026”.', '**Milestone** agreed and forecast date moves, and milestones achieved.', 'A change that was made and then put back is left out.']],
      ['p', 'Before the first publication it says “Not published yet, so there is nothing to compare with.” **Start from last week’s report**, in the bar above the report, copies the text sections from the last publication; see [Start from last week’s report](#howto-start-from-last-report).'] ] },
    { id: 'freshness', g: 'Working with items', t: 'Freshness: raised, last reviewed, not reviewed', b: [
      ['ul', ['**Raised**: when the item came in (its first history row, or the day it was imported).', '**Last reviewed**: the latest change made by hand. Changes by ask clark, an Excel import or an Undo do not count.', '**Not reviewed in 14 days**: a grey chip in the peek, on an open item whose last review is 14 days ago or more.', 'In the Work items filter line: **is:quiet** for not reviewed in 14 days, and **is:incomplete** for no owner or no date.', 'The Publish box counts the open items with no owner or date, and those not reviewed in 14 days, with **Show them**. It warns; it never stops you.']],
      ['p', 'Nothing is stored for this: it is worked out from the history every time.'] ] },
    { id: 'at-a-glance', g: 'Screens', t: 'At a glance', b: [
      ['tbl', ['Tile', 'Counts', 'Automatic colour'], [
        ['Project health', 'On track, At risk or Off track, with the reason', 'The health'],
        ['Overdue actions', 'Open actions past their due date, “of n open actions”', 'Red when any; green when none'],
        ['High risks and issues', 'Open risks and issues of Urgent or High priority', 'Red when any is red; amber when some are open; green when none'],
        ['Decisions needed', 'Pending decisions, with the oldest date', 'Amber when any; green when none'] ]],
      ['p', 'In Edit, the health tile adds **Suggested: …**, a health worked out by plain rules, with its reasons: an action overdue by more than 7 days, a slipped milestone, two or more red risks or issues. One rule gives At risk; all three give Off track; none gives On track. It never changes your choice. If your health is better than the suggestion, the reason is needed.'],
      ['p', 'A count opens Work items filtered to it. In Edit: drag or [[Alt+Left]] / [[Alt+Right]] to reorder, the eye to hide, right-click for **Tile colour**.'] ] },
    { id: 'layouts', g: 'Screens', t: 'Section styles', b: [
      ['p', 'The report is the cover, then the sections in cards, with the contents at the right edge.'],
      ['tbl', ['Dashboard sections (yours)', 'What it does'], [
        ['Slim gaps (standard)', 'Each section is its own card, with a slim gap that shows the page picture.'],
        ['Roomy gaps', 'The same, with more space between the sections.'],
        ['Grey headers', 'Slim gaps, and each section title in a grey band.'],
        ['One card', 'All the sections in one long card.'] ]] ] },
    { id: 'work-items', g: 'Screens', t: 'Work items', b: [
      ['p', 'From the top: the import and export icons and **+**; the saved views as tabs; the **filter line**, with **View** (Group by and swimlanes) and the **Table** and **Board** icons beside it; then the count of items. On a phone the line takes the full width and each item is a card with its status, owner, priority and due date. When nothing matches, the list says why and gives one **Clear** button.'],
      ['tbl', ['Table column', 'Shows'], [
        ['Item', 'The type badge, the title, then the ID, use case and milestone'],
        ['Owner', 'Initials and name'],
        ['Due', 'The date, and Today, Tomorrow, “3 days late” or “In 5 days”'],
        ['Priority', 'Urgent, High, Medium or Low'],
        ['Status', 'The state in words and colour: see [Status words](#ref-status-words)'],
        ['The eye', 'Client-visible on or off'] ]],
      ['tbl', ['In the line', 'Values'], [
        ['type:', 'action, risk, issue, decision'], ['status:', 'Every status of every type'], ['owner:', 'Everyone with an item, and me; no:owner for none'], ['priority:', 'Urgent, High, Medium, Low'],
        ['due:', 'overdue, today, next-7-days, later; no:due for no date'], ['workstream:', 'The project’s workstreams'], ['usecase:', 'Each use case; no:usecase for none'], ['milestone:', 'Each milestone; no:milestone for none'],
        ['client:', 'shown, internal'], ['is:', 'open, closed, overdue, quiet (not reviewed in 14 days), incomplete (no owner or no date), needed (from the client)'] ]],
      ['p', 'Every field can be left out with a minus (-status:Closed) and can take either of several values (status:Open,Pending). Group by: Workstream, Status, Due, Owner, Priority, Milestone, Type and Nothing. On the board, View adds the **swimlanes** (Workstream or Type). See [Group work and use the board](#howto-use-the-board).'] ] },
    { id: 'milestones-page', g: 'Screens', t: 'Milestones: Plan and Movement', b: [
      ['p', 'The line under the heading names the last milestone, its agreed date and any later expected date, and how many are achieved and to come.'],
      ['ul', ['**Plan**: every milestone, internal ones too, on the timeline or calendar, with the legend and the details list.', '**Movement**: the open milestones against their original, agreed and forecast dates, with the days late, what changed and what to do. Never published. See [Deal with a slipped milestone](#howto-handle-a-slipped-milestone).']],
      ['p', 'On the Dashboard, the Milestones section shows only the milestones visible to the client. In Edit, the eye in the details takes one off the page, and **+ Add a milestone from your project record** brings it back.'] ] },
    { id: 'ask-clark', g: 'Screens', t: 'ask clark', w: 'Top bar · [[/]] · [[Mod+J]]', b: [
      ['p', 'Its purpose is to help you make the report as accurate as it can be. It works from this project’s data and the source folders listed in Settings. It never reads mail, Teams or calendars.'],
      ['ul', ['The suggestions sit in one row above the box (scroll it sideways for the rest): **Check this report**, **What’s overdue?**, **Which risks are red?**, **Next milestone?**, **Summarise this week**, **Use cases**.', 'Type a question and press [[Enter]] to send ([[Shift+Enter]] for a new line). While it works, an office quip shows in place of the suggestions, and they come back with the answer.', 'An answer’s IDs open the item; a milestone’s name opens the milestone. A button in an answer makes a change, with **Undo**.', '**+** starts a new chat; **×**, [[Esc]] or a click outside closes it.', 'Drag its left edge to make it wider; a double-click puts it back.']],
      ['p', '**What will be sent**: above the box, one sentence says what a question carries: this project’s work items, milestones and use cases (with their size in words), the named source folders, and the provider, Claude. **Show details** gives each part. Mail, Teams and calendars are never sent.'],
      ['p', '**Settings › Asking** turns ask clark on or off for each project. It is On for a new project, and the choice is saved on this computer with the project’s settings. When it is off, the button and [[/]] still open the panel, which says “Asking is off. Turn it on in Settings.”, and nothing is sent.'],
      ['p', '**Folders ask clark may read**: press **Choose folder** and pick the folder in the window that opens; there is nothing to type. Up to 20 folders for each project. A folder that is too wide is refused, and nothing is changed: your whole home folder, the whole of OneDrive, the top of a disk, a file, and clark’s own data and backups. **Remove** takes a folder off the list only (no file is touched), with **Undo**.'],
      ['p', 'In this prototype, answers are worked out by rules from the project’s data, and folders are not read; nothing is sent.'] ] },
    /* ── Working with items ── */
    { id: 'peek', g: 'Working with items', t: 'The peek', b: [
      ['p', 'A work item opens in the peek, over the page from the right. Everything in it saves as you change it, with **Undo**.'],
      ['ul', ['**The top bar**: Close, Across the whole screen, Previous and Next, then the eye, the sparkle (Sneak peek), Copy link and **⋯** (Duplicate, Archive).', '**The line above the title**: the type, the ID, the project, and Client when it is shown to the client.', '**A warning**, when an action is overdue or due on a weekend, with fixes.', '**The title**, then **Status**, **Priority**, **Owner** and **Due**, each with its icon in colour: the state’s colour, the priority’s, and the date’s (red when late, amber when due within a week).', '**Freshness**: Raised, Last reviewed and, when it applies, a **Not reviewed in 14 days** chip. Then **Needed from the client**, a switch that puts the item in the Needs from you section.', '**Latest update**, with **Draft**; then when it was last updated.', '**Details**: Description, Type, Workstream, Milestone, Use case and Client wording.', '**History**: All, Activity (every change, with a filter for All, Changes, or Comments and updates), Updates and Source.', '**The foot**: “Change this item in words”, and “Each change saves on its own, with Undo”.']],
      ['p', 'With the peek open, a click on another work item or milestone moves the peek to it. A click anywhere else, or [[Esc]], closes it. Drag the left edge to resize it; a double-click puts it back.'] ] },
    { id: 'archive-restore', g: 'Working with items', t: 'Archive and Restore', b: [
      ['p', 'Nothing is deleted: a work item, a milestone or a document is archived instead. **Archive** is in the peek’s **⋯** (and in a document’s **⋯**). It is one step with **Undo**, and the item’s history keeps who archived it, how and when.'],
      ['ul', ['An archived record leaves the lists, the counts, the Dashboard and the published page.', '**Show archived** on Work items and Milestones lists the archived ones in muted text, each marked Archived.', 'An archived record opens read-only, with one **Restore** button. Restore is one step with **Undo** too.', 'Archiving a milestone says how many work items point at it. They keep the link and show the milestone as “(archived)”.'] ] ] },
    { id: 'status-words', g: 'Working with items', t: 'Types, statuses and colours', b: [
      ['tbl', ['Type', 'Statuses', 'What the pill says'], [
        ['Action', 'Open, Delayed, Closed, Cancelled', 'Overdue (red) past its due date; Delayed or Due soon (amber, within 7 days); Open (blue); Closed or Cancelled (grey)'],
        ['Risk, Issue', 'Open, Closed, Cancelled', 'Its colour from its priority: Urgent or High red, Medium amber, Low green'],
        ['Decision', 'Pending, Made, Withdrawn', 'Pending (blue), Made (green), Withdrawn (grey)'] ]],
      ['p', 'Choosing Red, Amber or Green on a risk or issue sets its priority. Priorities are Urgent, High, Medium and Low.'],
      ['p', 'Use case statuses: **On track** (green), **Flag** (amber) and **High risk** (red).'] ] },
    { id: 'sneak-peek', g: 'Working with items', t: 'Sneak peek', w: 'An open peek › the sparkle or [[/]] [[/]]', b: [
      ['tbl', ['You type', 'It changes'], [
        ['due Friday · move to next week · by 12-12-2026 · on in 3 days', 'The due date (today, tomorrow, next week, in n days or weeks, a weekday, next Monday, DD-MM-YYYY)'],
        ['owner Jo · assign to Sam Rivers · give it to Priya', 'The owner (a second word counts when it has a capital)'],
        ['done · closed · reopen · delayed · cancelled', 'An action’s, risk’s or issue’s status'],
        ['made · agreed · withdrawn · pending', 'A decision’s status'],
        ['urgent · high priority · medium · low', 'The priority'],
        ['red · amber · green', 'A risk’s or issue’s colour'],
        ['show to client · hide from client', 'Client-visible'],
        ['use case 3.1', 'The use case'],
        ['rename to …', 'The title'],
        ['update: …', 'The latest update'] ]],
      ['tbl', ['For a milestone', 'It changes'], [
        ['forecast 12-12-2026 · move to next Friday', 'The forecast date'], ['achieved · done', 'Achieved today, progress 100%'], ['at risk · on track', 'The state'], ['progress 40%', 'The progress'], ['owner …, show to client, rename to …', 'As for an item'] ]] ] },
    { id: 'picker', g: 'Working with items', t: 'Add from your project record', b: [
      ['p', 'A box that lists what is not on the page yet: work items, milestones, use cases or documents. Type to search by name, ID, owner or use case; a switch narrows it by kind; tick what you want, or **Select all shown**. [[Enter]] in the search ticks the only match, and [[Down]] goes to the list. **Add** puts them on the page in one step, with one **Undo**.'] ] },
    /* ── Milestones ── */
    { id: 'milestone-states', g: 'Milestones', t: 'Milestone states and marks', b: [
      ['marks'],
      ['p', 'A state follows the dates unless you set it by hand. Achieved wins; then Forecast and At risk (set by hand); then Overdue once the agreed date has passed; then Slipped when the forecast is later than agreed; otherwise On track.'],
      ['p', 'Slip is counted in days from the agreed date to the expected date: the later of the forecast and, once the agreed date has passed, today.'] ] },
    { id: 'milestone-peek', g: 'Milestones', t: 'The milestone peek', b: [
      ['ul', ['**The top bar**: Close, Across the whole screen, Previous and Next, the eye, the sparkle (Sneak peek) and **⋯** (Archive milestone).', '**The chips**: the state, the agreed date, the forecast and the progress.', '**State**: the six states as buttons, and why it has the one it has.', '**Dates**: Agreed date, with **Move the agreed date…** and the original date; Forecast, with how many days later than agreed. An achieved milestone shows its achieved date.', '**Progress**: a slider and a number, set by hand.', '**Description**: scope and needs, then Owner and Workstream.', '**Client view**: Visible to client, and Client wording.', '**Linked work items**, then the history.']] ] },
    { id: 'timeline-calendar', g: 'Milestones', t: 'Timeline, calendar and details', b: [
      ['ul', ['**Timeline**: months along the top, a line for today, a mark per milestone with its name and date below. Earlier, Later and **Today**; drag the bottom edge to zoom (70% to 300%), **Reset**.', '**Calendar**: **Week**, **Month** or **Quarter**; earlier, later and **Today**; weekends are muted and today is marked. A slipped milestone shows on its agreed date and again, faintly, as “Expected”. In Quarter, a month’s name opens that month.', '**Legend**: point at it or tab to it.', '**Milestone details**: a rail with the date, the name, the state, the progress and, for internal ones, “Internal only”. The first five, then **Show all**. **Hide milestone details** folds it away.']] ] },
    /* ── Writing and AI ── */
    { id: 'editor', g: 'Writing and AI', t: 'The editor', b: [
      ['p', 'One editor everywhere: Current state, the text sections, a use case’s Where it stands, an item’s latest update, description and client wording, and a milestone’s description and client wording. Click the text and it opens in place.'],
      ['tbl', ['Part', 'What it has'], [
        ['The bar', 'H1, H2, H3 · Bold, Italic, Strikethrough · Bulleted list, Numbered list, Checklist, Outdent, Indent, Quote, Divider · Link, Unlink, Clear · Undo, Redo · ✦ AI'],
        ['The floating bar (select text)', 'Bold, Italic, Strikethrough · Heading, Small heading · Bulleted list, Numbered list, Quote · Link, Clear · the AI part'],
        ['The / menu', 'Text, Heading 1, 2 and 3, Bulleted list, Numbered list, Checklist, Quote, Divider, Draft with AI, Rewrite clearly, Shorter, Make it executive, Polish, Ask AI…'],
        ['The line under it', '“⌘↵ or click away saves · Esc cancels · / for commands and AI · highlight text to format it, Alt+/ for AI on it”'] ]] ] },
    { id: 'ai-menu', g: 'Writing and AI', t: 'The AI menu', b: [
      ['ai'],
      ['tbl', ['Where', 'What it offers'], [
        ['Current state, text sections, Where it stands', 'Draft from the project (where there is one), Format notes, Improve (with Longer), Structure, Make into, Ask'],
        ['An item’s latest update, description; a milestone’s description', 'Improve: Rewrite clearly, Shorter, Make it executive, Polish; Make into; Ask'],
        ['Client wording', 'The same as an item’s fields'] ]],
      ['p', 'The suggestion card: the new text, **Show changes** (word by word), **Try again**, **Discard** ([[Esc]]) and **Accept** ([[Mod+Enter]]). Nothing changes until you accept. **Make into** adds a new item at once, with **Undo** in the message.'] ] },
    /* ── Publishing ── */
    { id: 'publishing', g: 'Publishing', t: 'Publishing', w: 'Profile circle › Publish…', b: [
      ['p', 'Publish lives in the menu behind your profile circle (point at the circle and it says: Your menu: Publish, Preview, Export, Settings).'],
      ['ul', ['**Local**: always. Saved through your browser’s own save window, which opens where you last saved for the project (or your downloads, where the browser has no save window).', '**To client**: only when ticked, to the client folder in Settings › Publishing.', '**Also a Word document**: a Word copy beside the web page.', '**Also a PDF**: the page opens in a new tab with the print box, and you choose Save as PDF. Prototype: the real clark makes the PDF with Chrome.', 'A yellow note lists items with no owner or date, and items not reviewed in 14 days. It warns only.', 'The box stays open while it works: the **Publish** button shows a spinner, then a tick and **Published (Publication N)**, and the box closes. If you cancel the save window, the box stays so you can try again.']],
      ['p', 'Each publish gets the next number for the project (Publication 1, 2, 3…), is noted with the date and time, where it went and who published it, and keeps a copy of the page: see [Published reports](#ref-published-reports). The page’s foot says “Publication N · date”.'],
      ['p', 'The PDF has print rules: the four tabs one after another, no buttons, menus or contents, each section kept whole, light colours only, and the publication and page number at the foot of every page.'],
      ['p', 'The web page holds only what the report shows in View. Anything left out is dropped before the file is made. The Word document has the cover, the health and the sections as tables.'],
      ['p', 'Each publish is noted on the project, and the Dashboard says when it was last published. **Preview the page in a new tab** shows the page without saving it.'] ] },
    { id: 'published-reports', g: 'Publishing', t: 'Published reports', w: 'Settings › Published reports · profile circle', b: [
      ['tbl', ['Column', 'Shows'], [['#', 'The publication’s number for this project, counting up from 1'], ['Date and time', 'When it was published'], ['Where', 'Local, or Local and to client; with Word or PDF when ticked'], ['Who', 'The name in your profile'], ['Open', 'The kept copy of the page, in a new tab; or “Not kept” for an older one']]],
      ['p', 'The last 10 copies are kept in this browser’s database. A later release ties a client’s comment to the publication the client saw.'] ] },
    { id: 'client-page', g: 'Publishing', t: 'The published client page', b: [
      ['ul', ['**The cover**: the project, the week ending and who it is for.', '**Four tabs**: Dashboard, Work items, Milestones and Use Cases.', '**Dashboard**: the report in the section style you chose, with **On this page** at the right.', '**Work items**: actions, risks and issues, and decisions shown to the client, with a search box.', '**Milestones**: the Timeline and Calendar switch, the legend and every client-visible milestone, in client words.', '**Use Cases**: only the use cases on the dashboard. A row opens where it stands, the next steps and the milestones shown to the client; nothing else.', 'A click on an item, a row or a milestone opens a read-only panel marked **View only**. A click outside, or [[Esc]], closes it; a click on another item moves it.', 'A tile opens the Work items tab. A use case row opens its detail.']],
      ['p', 'The footer says when it was published. The page carries clark’s icon in its tab and needs no other files.'] ] },
    /* ── Settings and data ── */
    { id: 'settings', g: 'Settings and data', t: 'Settings', b: [
      ['p', 'On a phone the Projects, People and Published reports tables show one card per row, with the column name beside each value, so the page never scrolls sideways.'],
      ['tbl', ['Card', 'What it holds'], [
        ['Profile', 'Name, Alias, Email, Phone number and Organisation. On this computer only.'],
        ['Personal', 'Dashboard sections (Slim gaps, Roomy gaps, Grey headers, One card) and Appearance (Light, Dark or System).'],
        ['Projects', 'Every project with its code, client, workstreams and item count; Open, Edit and Archive; **Show archived** lists the archived ones, each with **Restore**; **+** adds one. Nothing is deleted.'],
        ['People', 'Everyone who owns an item or a milestone, with email, organisation and role; a line saying how many need details, and **Show only these**; **Paste from Excel**. See [People](#ref-people).'],
        ['Asking', 'The **ask clark** switch, On or Off, for this project; what is sent to Claude when you ask; and the folders ask clark may read, up to 20. See [ask clark](#ref-ask-clark).'],
        ['Publishing', 'The local folder, and the client’s SharePoint folder.'],
        ['Published reports', 'Every publication of the open project, numbered, with Open. See [Published reports](#ref-published-reports).'],
        ['Data', 'Export workbook, Import workbook, and Reset the demo data.'],
        ['clark version and updates', 'The installed version, **Review** or **Choose zip…** to update from a release file, and **Undo update**. See [Updating clark](#ref-updating-clark).'],
        ['Diagnostics', 'The log level (Normal or Debug), the log folder, **Copy diagnostics** and recent errors. See [Diagnostics and logs](#ref-diagnostics).'] ]] ] },
    { id: 'people', g: 'Settings and data', t: 'People', w: 'Settings › People', b: [
      ['p', 'The table is built from the distinct owners on work items and milestones of the projects that are not archived, and shows each person’s email, organisation and role. The line above it says how many need details; **Show only these** lists them, each marked **Needs details**.'],
      ['p', '**Paste from Excel** takes rows of name, email, organisation and role, separated by tabs; a heading row is skipped. A name that matches an owner updates that person; a new name is added. One **Undo** reverses a paste. Owner pickers still work on names.'] ] },
    { id: 'updating-clark', g: 'Settings and data', t: 'Updating clark', w: 'Settings › clark version and updates', b: [
      ['ul', ['**Installed** is the version you have. **Update** says **Up to date**, or **Review 0.3.0** when a newer clark-X.Y.Z.zip is in Downloads. There is no online check.', '**Choose zip…** takes a release file you saved. It must be named clark-X.Y.Z.zip, from the release page: not the source code zip.', '**Review** shows the version change, the release notes (**Copy the notes**), how many files are replaced and added, and that your projects, settings and published reports are kept.', 'Everything is backed up first, and if a step fails clark puts the old version back. A release is checked file by file against its list of checksums before anything changes.', '**Undo update** goes back to the version before: press it, then **Confirm undo** within five seconds.', 'In this prototype nothing is installed for real. **Simulate a new release** makes a clark 0.2.0 appear so you can try the steps.']] ] },
    { id: 'diagnostics', g: 'Settings and data', t: 'Diagnostics and logs', w: 'Settings › Diagnostics', b: [
      ['ul', ['**Log level**: **Normal** keeps a line for what clark did and for every error. **Debug** adds detail for fixing a problem. Switch back to Normal when you are done; Settings reminds you after a week.', 'Logs hold only counts, IDs and times, never your report text, names, emails or keys. The real clark keeps one file a day (5 MB at most) for 7 days in `~/Library/Logs/clark/`; **Open the folder** shows it.', '**Copy diagnostics** puts a plain-text report on the clipboard: the version, browser, system, log level, counts, safe settings and the last 20 log lines. It never holds a name, email, project name or report text, so it can go in a chat.', '**Errors in the last 7 days** lists what went wrong, or says None.', 'In this prototype the log lives in memory for the visit.']] ] },
    { id: 'excel', g: 'Settings and data', t: 'Excel in and out', b: [
      ['tbl', ['Sheet', 'Columns'], [
        ['Actions, Risks and issues, Decisions', 'ID, Type, Workstream, Title, Owner, Due, Status, Priority, Rating, Use case, Milestone, Client-visible, Client wording, Description, Latest update'],
        ['Milestones', 'ID, Milestone, Workstream, Original, Agreed, Forecast, Achieved, State, Progress, Owner, Client-visible, Description'],
        ['Use cases', 'ID, Shown as, Use case, Status, Headline, Where it stands, Client-visible, Open work items'] ]],
      ['p', 'On import, columns can be in any order and only the title or name is needed. Client-visible reads Yes or No. Dates can be DD-MM-YYYY.'] ] },
    { id: 'saving', g: 'Settings and data', t: 'Saving, history and undo', b: [
      ['ul', ['There is no Save button. Each change is written when you make it: a pick from a menu, [[Enter]] in a field, leaving a box, or closing an editor.', 'Each change records when (shown in your local time), who made it (your full name from Settings › Profile, or “You”), where or how (in the peek, in the table, on the board, in the report, with the eye, by Excel import with the file name, via ask clark, with a draft, from selected text, in words, or by undo), the field, what it was and what it became. The history is never pruned, and the Excel export has it as a History sheet.', '**Undo** in the message reverses exactly that step. Several changes made together undo together. Undoing is itself recorded: one line for each field put back, with its old and new value, and “Creation undone” when you undo an add.', 'In this prototype, everything is kept in this browser’s database. If the browser blocks it, changes last for this visit only, and Settings › Data says so.']] ] },
    { id: 'dates-and-ids', g: 'Settings and data', t: 'Dates and IDs', b: [
      ['ul', ['Dates are shown DD-MM-YYYY, for example 30-10-2026.', 'The week ends on a Friday.', 'IDs: actions CODE-A-001, decisions CODE-D-001, risks and issues CODE-001 (one series), milestones CODE-M-001. CODE is the project’s short code.', 'Use cases keep the ID you give them, such as 3.1.']] ] },
    { id: 'using-help', g: 'Settings and data', t: 'Using Help', b: [
      ['ul', ['Three tabs: **Start here**, **How do I…** and **Reference**. Help opens on the one you used last.', 'The search box looks through all three as you type. Press [[Enter]] for the first result, [[Esc]] to clear it.', 'A link with an arrow takes you to the screen it names.', '[[?]] opens Help from any page; in Help, [[/]] goes to the search box.']] ] },
    /* ── Keys and icons ── */
    { id: 'keys', g: 'Keys and icons', t: 'Keyboard shortcuts', b: [['keys']] },
    { id: 'icons', g: 'Keys and icons', t: 'Icons and marks', b: [['icons'], ['types']] },
  ];

  /* ═════════════ drawing ═════════════ */
  const TABS = [['start', 'Start here'], ['howto', 'How do I…'], ['reference', 'Reference']];
  const block = bl => {
    const [k, a, b] = bl;
    if (k === 'p') return `<p>${md(a)}</p>`;
    if (k === 'ul') return `<ul>${a.map(x => `<li>${md(x)}</li>`).join('')}</ul>`;
    if (k === 'tbl') return `<div class="hp-tw"><table class="hp-t"><thead><tr>${a.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${b.map(r => `<tr>${r.map(c => `<td>${md(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    if (k === 'marks') return `<div class="hp-tw"><table class="hp-t hp-marks"><thead><tr><th>Mark</th><th>State</th><th>Means</th></tr></thead><tbody>${MS_STATES.map(([s, d]) => `<tr><td><span class="hp-mk">${C.msMark(s)}</span></td><td>${esc(s)}</td><td>${md(d)}</td></tr>`).join('')}
      <tr><td><span class="hp-mk"><i class="mlg-ghost"></i></span></td><td>Expected</td><td>Where a slipped milestone is now expected; a dashed line joins it to its agreed date.</td></tr>
      <tr><td><span class="hp-mk"><i class="mlg-today"></i></span></td><td>Today</td><td>The line on the timeline; the marked day on the calendar.</td></tr></tbody></table></div>`;
    if (k === 'keys') return `<div class="hp-tw"><table class="hp-t hp-keys"><thead><tr><th>Keys</th><th>Does</th></tr></thead><tbody>${SHORTCUTS.map(([kk, d]) => `<tr><td>${md(kk)}</td><td>${md(d)}</td></tr>`).join('')}</tbody></table></div>`;
    if (k === 'icons') return `<div class="hp-tw"><table class="hp-t hp-icons"><thead><tr><th>Icon</th><th>Name</th><th>What it does</th><th>Where</th></tr></thead><tbody>${ICONS.map(([n, t, d, w]) => `<tr><td>${ic(n)}</td><td>${esc(t)}</td><td>${md(d)}</td><td>${esc(w)}</td></tr>`).join('')}
      <tr><td>${ic('eyeoff')}</td><td>Internal only</td><td>Not shown to the client. Select to show it</td><td>Work items, the peek, milestones</td></tr></tbody></table></div>`;
    if (k === 'types') return `<h3 class="hp-h3">Badges and words</h3><div class="hp-tw"><table class="hp-t"><thead><tr><th>Mark</th><th>Means</th></tr></thead><tbody>
      ${Object.entries(C.D.TYPES).map(([t, n]) => `<tr><td><span class="type ${t}">${t}</span></td><td>${esc(n)}</td></tr>`).join('')}
      <tr><td><span class="pill r">Overdue</span> <span class="pill a">Due soon</span> <span class="pill b">Open</span> <span class="pill g">Made</span> <span class="pill n">Closed</span></td><td>A work item’s state, in words and colour</td></tr>
      <tr><td>${['On track', 'Flag', 'High risk'].map(s => C.ucWord ? C.ucWord(s) : esc(s)).join(' ')}</td><td>A use case’s status</td></tr>
      <tr><td><span class="tag cl">${C.icon('eye', 's')}Client</span></td><td>Shown to the client</td></tr>
      <tr><td><span class="tag">Internal only</span></td><td>A milestone not shown to the client</td></tr>
      <tr><td><span class="av">JE</span></td><td>An owner’s initials</td></tr></tbody></table></div>`;
    if (k === 'ai') { const O = C.AI_OPTIONS || {}; const rows = [['Improve', ['rewrite', 'shorter', 'longer', 'executive', 'polish']], ['Structure', ['format', 'checklist', 'summary']], ['Notes', ['notes']], ['Ask', ['custom']]];
      return `<div class="hp-tw"><table class="hp-t"><thead><tr><th>Group</th><th>Option</th><th>What it does</th></tr></thead><tbody>${rows.flatMap(([g, ks]) => ks.filter(x => O[x]).map((x, i) => `<tr><td>${i ? '' : esc(g)}</td><td>${esc(O[x][0])}</td><td>${esc(O[x][1])}</td></tr>`)).join('')}
        <tr><td>Make into</td><td>Make this an action, a risk or a decision</td><td>A new work item from the selected text, with Undo</td></tr></tbody></table></div>`; }
    return '';
  };

  function startHtml() {
    return `<section class="hp-hero" id="hp-start-top" aria-labelledby="hpT0"><img class="hp-logo" src="assets/clark-icon.svg" alt=""><div><div class="hp-lab">${esc(START.label)}</div><h2 id="hpT0">${esc(START.title)}</h2><p>${md(START.lead)}</p></div></section>
      <section class="hp-sec hp-loop" id="hp-start-loop" aria-labelledby="hpT1"><div class="hp-sh"><h2 id="hpT1">The loop</h2><p>Every week follows the same five steps. Only the last one sends anything anywhere, and only when you say so.</p></div>
        <ol class="hp-steps">${LOOP.map((s, i) => `<li class="${s.gate ? 'gate' : ''}"><div class="hp-n">${i + 1} · ${esc(s.n)}</div><div class="hp-st">${C.icon(s.ic, 's')}<b>${esc(s.t)}</b></div><p>${md(s.d)}</p>${s.gate ? `<div class="hp-gate">${esc(s.gate)}</div>` : ''}</li>`).join('')}</ol>
        <p class="hp-ret">${C.icon('undo', 's')}Next week starts the loop again from the same record. The history keeps every change, so nothing is lost between weeks.</p></section>
      <section class="hp-sec" id="hp-start-first" aria-labelledby="hpT2"><div class="hp-lab">Once</div><h2 id="hpT2">Your first ten minutes</h2>
        <ol class="hp-first">${FIRST.map((f, i) => `<li><span class="hp-big">${i + 1}</span><b>${esc(f.t)}</b><p>${md(f.d)}</p></li>`).join('')}</ol></section>
      <section class="hp-sec" id="hp-start-jobs" aria-labelledby="hpT3"><div class="hp-lab">The jobs you will do most</div><h2 id="hpT3">Twelve jobs</h2><p class="hp-lead">Pick a job. Its title opens the steps; the arrow takes you to the screen.</p>
        <ul class="hp-jobs">${JOBS.map(([id, t, d, go]) => `<li class="hp-job"><a href="#" class="hp-jt" data-hlink="howto-${id}">${esc(t)}</a><span>${esc(d)}</span><a href="#" class="hp-jgo" data-hgo="${go}">${esc(goLabel(go))} ›</a></li>`).join('')}</ul></section>
      <section class="hp-sec" id="hp-start-where" aria-labelledby="hpT4"><div class="hp-lab">The screens</div><h2 id="hpT4">Where things are</h2>
        <ul class="hp-where-g">${WHERE.map(([t, d, go]) => `<li>${go ? `<a href="#" class="hp-wt" data-hgo="${go}">${esc(t)}</a>` : `<b class="hp-wt">${esc(t)}</b>`}<p>${md(d)}</p></li>`).join('')}</ul>
        <p class="hp-keyline">${md('[[/]] ask clark · [[/]] [[/]] Sneak peek, with an item open · [[Esc]] close the top thing · [[Mod+Enter]] keep an edit · [[Alt+/]] AI on selected text · [[?]] Help')} · <a href="#" class="hp-a" data-hlink="ref-keys">All the keys</a></p></section>
      <section class="hp-sec" id="hp-start-rules" aria-labelledby="hpT5"><div class="hp-lab">Never bends</div><h2 id="hpT5">Four rules</h2>
        <ul class="hp-rules">${RULES.map(([t, d]) => `<li><b>${esc(t)}</b><p>${md(d)}</p></li>`).join('')}</ul></section>
      <footer class="hp-foot" id="hp-start-foot"><p>Dates are shown DD-MM-YYYY. This is a prototype with demo data, kept in this browser’s database: <b>Reset demo data</b> at the foot of the page puts it back as it started.</p><a href="#" class="hp-a" data-htab="howto">How do I…: step by step for every job ›</a></footer>`;
  }
  const idx = (groups, list, pre) => `<nav class="hp-idx" aria-label="In this part">${groups.map(g => `<div class="hp-ig">${esc(g)}</div><ul>${list.filter(x => x.g === g).map(x => `<li><a href="#" data-hlink="${pre}-${x.id}">${esc(x.t)}</a></li>`).join('')}</ul>`).join('')}</nav>`;
  const goBtn = to => to ? `<a href="#" class="hp-go" data-hgo="${to}">${esc(goLabel(to))} ›</a>` : '';
  function howtoHtml() {
    return `<div class="hp-two">${idx(GROUPS, TASKS, 'howto')}<div class="hp-col"><div class="hp-sh"><h2>How do I…</h2><p>The common jobs, step by step. Each says where to go; the arrow at its foot takes you there.</p></div>
      ${GROUPS.map(g => `<h3 class="hp-grp">${esc(g)}</h3>${TASKS.filter(x => x.g === g).map(x => `<article class="hp-task" id="hp-howto-${x.id}" data-k="howto-${x.id}"><h3>${esc(x.t)}</h3><p class="hp-where">Where: ${md(x.w)}</p>
        <ol>${x.s.map(s => `<li>${md(s)}</li>`).join('')}</ol>${x.n ? `<p class="hp-note">${md(x.n)}</p>` : ''}${x.say ? `<p class="hp-say">Or ask clark: ${x.say.map(q => `<code>${esc(q)}</code>`).join(' ')}</p>` : ''}${goBtn(x.go)}</article>`).join('')}`).join('')}</div></div>`;
  }
  function refHtml() {
    return `<div class="hp-two">${idx(REF_GROUPS, REFS, 'ref')}<div class="hp-col"><div class="hp-sh"><h2>Reference</h2><p>Every screen and control, as clark has them today.</p></div>
      ${REF_GROUPS.map(g => `<h3 class="hp-grp">${esc(g)}</h3>${REFS.filter(x => x.g === g).map(x => `<article class="hp-ref" id="hp-ref-${x.id}" data-k="ref-${x.id}"><h3>${esc(x.t)}</h3>${x.w ? `<p class="hp-where">Where: ${md(x.w)}</p>` : ''}${x.b.map(block).join('')}</article>`).join('')}`).join('')}</div></div>`;
  }
  const PART = { start: startHtml, howto: howtoHtml, reference: refHtml };

  /* ── search: one index over all three tabs, built from the same HTML, in this page (nothing is sent) ── */
  let IDX = null;
  const norm = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const words = s => norm(s).match(/[a-z0-9]+/g) || [];
  const stems = w => { const c = [w]; if (w.length > 3) { if (w.endsWith('ies')) c.push(w.slice(0, -3) + 'y'); if (w.endsWith('es')) c.push(w.slice(0, -2)); if (w.endsWith('s')) c.push(w.slice(0, -1)); } return c; };
  const hit = (q, t) => stems(q).some(c => c.length >= 2 && t.startsWith(c));
  const LINES = 'p, li, td';
  function index() {
    if (IDX) return IDX; IDX = [];
    const box = document.createElement('div'), txt = el => (el.textContent || '').replace(/\s+/g, ' ').trim();
    TABS.forEach(([tab]) => { box.innerHTML = PART[tab]();
      const parts = tab === 'start' ? C.$$('section[id], footer', box) : C.$$('article[id]', box);
      parts.forEach(el => { const h = C.$('h2, h3', el), title = h ? txt(h) : 'Start here', lines = C.$$(LINES, el).map(txt).filter(Boolean);
        IDX.push({ tab, id: el.id, title, lines, tw: words(title), lw: lines.map(words) }); }); });
    return IDX;
  }
  function find(q) {
    const qw = words(q).filter(w => w.length >= 2); if (!qw.length) return [];
    const out = [];
    index().forEach((e, n) => { let s = 0;
      for (const w of qw) { if (e.tw.some(x => hit(w, x))) s += 10; else if (!e.lw.some(l => l.some(x => hit(w, x)))) return; }
      let li = -1, best = 0; e.lw.forEach((l, i) => { const k = qw.filter(w => l.some(x => hit(w, x))).length; if (k > best) { best = k; li = i; } });
      out.push({ e, n, li, score: s + best * 3 + (e.tab === 'howto' ? 1 : 0) }); });
    return out.sort((a, b) => b.score - a.score);
  }
  function mark(line, q) {
    const qw = words(q).filter(w => w.length >= 2); let o = '', last = 0, first = -1;
    for (const m of line.matchAll(/[\p{L}\p{N}]+/gu)) if (qw.some(w => hit(w, norm(m[0])))) { if (first < 0) first = m.index; o += esc(line.slice(last, m.index)) + '<mark>' + esc(m[0]) + '</mark>'; last = m.index + m[0].length; }
    o += esc(line.slice(last));
    if (first > 60 && line.length > 170) { const cut = line.lastIndexOf(' ', first - 40); if (cut > 0) return '…' + mark(line.slice(cut + 1), q); }
    return o;
  }

  /* ── state ── */
  let tab = C.store.get('helpTab', 'start'), query = '', pending = '';
  if (!PART[tab]) tab = 'start';

  function setTab(t, target) {
    if (!PART[t]) return; tab = t; C.store.set('helpTab', t);
    const pane = C.$('#hpPane'); if (!pane) return;
    pane.innerHTML = PART[t](); pane.dataset.tab = t; pane.setAttribute('aria-labelledby', 'hpTab-' + t);
    C.$$('#hpTabs [role=tab]').forEach(b => { const on = b.dataset.htab === t; b.setAttribute('aria-selected', on); b.tabIndex = on ? 0 : -1; });
    if (target) { const el = document.getElementById('hp-' + target); if (el) { el.scrollIntoView({ block: 'start' }); flash(el); return el; } }
    else window.scrollTo({ top: 0 });
    return null;
  }
  const flash = el => { el.classList.add('hp-found'); setTimeout(() => el.classList.remove('hp-found'), 2400); };
  /* a link inside Help: "howto-<id>", "ref-<id>", "start-<id>" (the tab follows from it) */
  function follow(k) { const t = k.startsWith('howto') ? 'howto' : k.startsWith('ref') ? 'reference' : 'start'; clearSearch(); setTab(t, k); }
  function clearSearch() { query = ''; const q = C.$('#hpQ'); if (q) q.value = ''; const r = C.$('#hpRes'), p = C.$('#hpPane'); if (r) { r.hidden = true; r.innerHTML = ''; } if (p) p.hidden = false; }
  const PARTN = { start: 'Start here', howto: 'How do I…', reference: 'Reference' };
  function drawResults() {
    const r = C.$('#hpRes'), pane = C.$('#hpPane'), q = query;
    if (!q.trim()) { r.hidden = true; r.innerHTML = ''; pane.hidden = false; return; }
    const res = find(q); pane.hidden = true; r.hidden = false;
    if (!res.length) { r.innerHTML = `<div class="hp-none" role="status"><b>Nothing in Help for “${esc(q.trim())}”</b><span>Try another word, or ask clark.</span><button type="button" class="btn" id="hpAsk">${C.icon('chat', 's')}ask clark</button></div>`; return; }
    r.innerHTML = `<p class="hp-resn" role="status">${res.length} result${res.length === 1 ? '' : 's'}</p>` + ['howto', 'reference', 'start'].map(g => { const grp = res.filter(x => x.e.tab === g); if (!grp.length) return '';
      return `<section class="hp-resg" aria-label="${esc(PARTN[g])}"><h3>${esc(PARTN[g])}</h3>${grp.map(x => `<a href="#" class="hp-r" data-hit="${x.n}" data-li="${x.li}"><span class="hp-rt">${mark(x.e.title, q)}</span><span class="hp-rl">${mark(x.li < 0 ? (x.e.lines[0] || '') : x.e.lines[x.li], q)}</span></a>`).join('')}</section>`; }).join('');
  }
  function openHit(n, li) {
    const e = index()[n]; if (!e) return; clearSearch();
    const box = setTab(e.tab, e.id.replace(/^hp-/, '')) || document.getElementById(e.id); if (!box) return;
    if (li >= 0) { const el = C.$$(LINES, box).filter(x => (x.textContent || '').trim())[li]; if (el) { el.scrollIntoView({ block: 'center' }); flash(el); } }
  }

  /* ═════════════ the view ═════════════ */
  C.views = C.views || {};
  C.views.help = {
    html() {
      if (pending) { const k = pending; tab = k.startsWith('howto') ? 'howto' : k.startsWith('ref') ? 'reference' : k.startsWith('start') ? 'start' : (PART[k] ? k : tab); }
      return `<div class="hp"><div class="head hp-head"><div><h1>Help</h1><p>How clark works, step by step, and every screen and key. <span class="hp-keyhint">Press <kbd>?</kbd> on any page to open Help; Esc or Back takes you where you were.</span><span class="hp-taphint">Tap <b>?</b> in the top bar on any page to open Help; Back takes you where you were.</span></p></div>
        <label class="search hp-search"><span class="sr">Search Help</span>${C.icon('search')}<input id="hpQ" type="search" placeholder="Search Help" autocomplete="off" value="${esc(query)}" aria-describedby="hpQk"><kbd id="hpQk" aria-label="Press slash to search">/</kbd></label></div>
        <div class="hp-tabs" role="tablist" aria-label="Help" id="hpTabs">${TABS.map(([k, t]) => `<button type="button" role="tab" id="hpTab-${k}" data-htab="${k}" aria-controls="hpPane" aria-selected="${tab === k}" tabindex="${tab === k ? 0 : -1}">${esc(t)}</button>`).join('')}</div>
        <div id="hpRes" class="hp-res" hidden aria-live="polite"></div>
        <div id="hpPane" class="hp-pane hp-${tab}" role="tabpanel" data-tab="${tab}" aria-labelledby="hpTab-${tab}" tabindex="-1">${PART[tab]()}</div></div>`;
    },
    wire() {
      const root = C.$('.hp'); if (!root) return;
      C.store.set('helpTab', tab);
      if (pending) { const k = pending; pending = ''; if (k.includes('-')) setTimeout(() => follow(k), 30); }
      if (query) drawResults();
      root.addEventListener('click', e => {
        const t = e.target.closest('[data-htab],[data-hlink],[data-hgo],[data-hit],#hpAsk'); if (!t) return;
        e.preventDefault();
        if (t.id === 'hpAsk') { const q = query.trim(); clearSearch(); C.askOpen(); const i = C.$('#askIn'); if (i && q) { i.value = q; i.dispatchEvent(new Event('input', { bubbles: true })); } return; }
        if (t.dataset.htab) { clearSearch(); setTab(t.dataset.htab); if (t.getAttribute('role') === 'tab') t.focus(); return; }
        if (t.dataset.hlink) return follow(t.dataset.hlink);
        if (t.dataset.hgo) return goTo(t.dataset.hgo);
        if (t.dataset.hit) return openHit(+t.dataset.hit, +t.dataset.li);
      });
      /* the tabs: arrows move between them, as any tab list */
      C.$('#hpTabs').addEventListener('keydown', e => { const ks = TABS.map(x => x[0]), i = ks.indexOf(tab);
        const j = e.key === 'ArrowRight' ? (i + 1) % ks.length : e.key === 'ArrowLeft' ? (i + ks.length - 1) % ks.length : e.key === 'Home' ? 0 : e.key === 'End' ? ks.length - 1 : -1;
        if (j < 0) return; e.preventDefault(); clearSearch(); setTab(ks[j]); C.$(`#hpTab-${ks[j]}`).focus(); });
      const q = C.$('#hpQ');
      q.addEventListener('input', () => { query = q.value; drawResults(); });
      q.addEventListener('keydown', e => {
        if (e.key === 'Escape' && q.value) { e.preventDefault(); e.stopPropagation(); clearSearch(); }
        else if (e.key === 'Enter') { const a = C.$('#hpRes a.hp-r'); if (a) { e.preventDefault(); a.click(); } }
        else if (e.key === 'ArrowDown') { const a = C.$('#hpRes a.hp-r'); if (a) { e.preventDefault(); a.focus(); } }
      });
    },
  };
  /* open Help at a place: C.help.open('howto-publish-the-report'), C.help.open('reference'), or C.help.open() for the tab used last */
  C.help = { open(where) { pending = where || ''; if (C.UI.view === 'help') { C.render(); } else C.go('help'); }, search(q) { query = q || ''; }, find };

  /* ── keys: ? opens Help from any page; in Help, / goes to the search box (before the page's own / opens ask clark) ── */
  const blocked = () => C.typing(document.activeElement) || C.$('#dlg')?.open || (C.popOpen && C.popOpen()) || (C.askIsOpen && C.askIsOpen()) || (C.edIsOpen && C.edIsOpen());
  document.addEventListener('keydown', e => {
    if (e.metaKey || e.ctrlKey || e.altKey || blocked()) return;
    if (e.key === '?') { e.preventDefault(); if (C.UI.view === 'help') { C.$('#hpQ')?.focus(); return; } C.help.open(); return; }
    if (e.key === '/' && C.UI.view === 'help' && !C.UI.peek) { const q = C.$('#hpQ'); if (q) { e.preventDefault(); e.stopImmediatePropagation(); q.focus(); q.select(); } }
  }, true);
})();
