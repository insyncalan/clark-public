// The AI menu's places and options on the page (#72, slice 1): what to draw, and the plain words the card uses.
// The server stays the authority (src/clark/ai_menu.py: OPTIONS, PLACES, GROUPS, PLACE_TABLE, MAKE_INTO); this copy only decides
// what the menu shows. tests/test_ai_menu_parity.py compares menu(place) with the server's for all five places. The instructions the
// model is given are the server's and are not here. Plain JS, no library, no DOM.

// id -> [the menu's name, what it does]
export const OPTIONS = {
  rewrite: ["Rewrite clearly", "The same points, in plainer words"],
  shorter: ["Shorter", "About half the length; the facts kept"],
  longer: ["Longer", "Fuller sentences; adds no facts"],
  executive: ["Make it executive", "The executive voice: the position and what matters first"],
  format: ["Add headings and bold", "Sub-headings, lists and bold where they help"],
  checklist: ["Pull out the tasks", "Finds the tasks and writes one a line to tick off"],
  summary: ["Summarise at the top", "A short summary first; the text kept below it"],
  polish: ["Polish", "Spelling, grammar and a lighter touch on the wording; the facts and length kept"],
  notes: ["Format notes", "Rough notes sorted under headings, with bullets; every point kept"],
  formal: ["More formal", "A more formal tone for the email"],
  warmer: ["Warmer", "A warmer, friendlier tone for the email"],
  custom: ["Ask…", "Your own instruction"],
};

// Each place's options, in the menu's order.
export const PLACES = {
  notes: ["notes", "rewrite", "shorter", "longer", "executive", "format", "checklist", "summary", "custom"],
  current: ["notes", "rewrite", "shorter", "longer", "executive", "format", "summary", "custom"],
  plain: ["rewrite", "shorter", "executive", "custom"],
  email: ["rewrite", "shorter", "longer", "formal", "warmer", "custom"],
  client_message: ["rewrite", "shorter", "executive", "custom"],
};

// How the bubble groups a place's options. Format notes and Ask… stand alone.
export const GROUPS = {
  notes: [["Improve", ["rewrite", "shorter", "longer", "executive"]], ["Structure", ["format", "checklist", "summary"]]],
  current: [["Improve", ["rewrite", "shorter", "longer", "executive"]], ["Structure", ["format", "summary"]]],
  plain: [["Improve", ["rewrite", "shorter", "executive"]]],
  email: [["Improve", ["rewrite", "shorter", "longer"]], ["Tone", ["formal", "warmer"]]],
  client_message: [["Improve", ["rewrite", "shorter", "executive"]]],
};

// "Make into": a new work item from the selection. No AI runs. Only in the rich places.
export const MAKE_INTO = { action: "Make this an action", risk: "Make this a risk", decision: "Make this a decision" };
const MAKE_INTO_PLACES = ["notes", "current"];

// The words the card says. Each is a whole line of text, never only colour. None starts with the product's name.
export const WORDS = {
  working: "Working on it",
  ready: "Suggestion ready",
  failed: "That did not work. Try again.",
  off: "AI is switched off in Settings.",
  notSignedIn: "Connect Claude in Settings to use this.",
  stop: "Stop",
  accept: "Accept",
  discard: "Discard",
  again: "Try again",
  changes: "Show changes",
  hideChanges: "Hide changes",
  noChanges: "The suggestion is the same words as the text.",
  notes: "Worth a look",
  sends: "The text you chose goes to Claude to make this suggestion.",
};

export const placeKnown = (place) => typeof place === "string" && Object.prototype.hasOwnProperty.call(PLACES, place);

// What the menu shows in a place, in the server's shape: {place, groups: [{label, items: [{id, name, line}]}], format_notes,
// make_into: [{id, name}], ask}. Format notes is its own button where the place has it; Ask… is last. An unknown place is never
// guessed at: it gives null, and the page draws no menu.
export function menu(place) {
  if (!placeKnown(place)) return null;
  const item = (id) => ({ id, name: OPTIONS[id][0], line: OPTIONS[id][1] });
  return {
    place,
    groups: GROUPS[place].map(([label, ids]) => ({ label, items: ids.map(item) })),
    format_notes: PLACES[place].includes("notes") ? item("notes") : null,
    make_into: MAKE_INTO_PLACES.includes(place) ? Object.entries(MAKE_INTO).map(([id, name]) => ({ id, name })) : [],
    ask: item("custom"),
  };
}

// The name an option is shown under (the card's heading). Ask… shows the person's own words, cut short.
export function optionName(option, instruction) {
  if (option === "custom") {
    const said = String(instruction || "").split(/\s+/).filter(Boolean).join(" ");
    return said ? (said.length > 60 ? said.slice(0, 59) + "…" : said) : OPTIONS.custom[0];
  }
  return OPTIONS[option] ? OPTIONS[option][0] : "";
}
