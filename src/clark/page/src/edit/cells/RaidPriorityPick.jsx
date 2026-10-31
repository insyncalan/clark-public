// #210: a risk's or an issue's Priority picker. Its priority is worked out from its impact and its likelihood, so the picker
// offers those two, each High, Medium or Low, under its own heading; the value it has now is ticked in each. A pick changes that
// one field (one step, with Undo), and the cell then shows the priority clark worked out. The same look and keys as the action's
// Priority picker (MenuPick), and the same props, so the peek (#42) can use it as it is.
import { MenuPick } from "./MenuPick.jsx";
import { LEVELS, RAID_LEVELS } from "../itemEdit.js";

export function RaidPriorityPick({ row, anchor, onPick, onClose }) {
  const choices = [];
  for (const [col, name] of RAID_LEVELS) {
    for (const level of LEVELS) choices.push({ group: name, value: `${col}:${level}`, text: level, checked: row[col] === level });
  }
  return <MenuPick anchor={anchor} label={`Impact and likelihood of ${row.id}`} current="" onPick={onPick} onClose={onClose} choices={choices} />;
}
