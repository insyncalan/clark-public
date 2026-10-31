// #80: a short list of values to choose one from (the Status and Priority pickers). A menu of radio items: focus goes to the
// value the item has now; Down and Up wrap, Home and End jump, Enter or Space picks, Esc leaves it as it was. A choice may carry
// a `note`, shown in small print under its word, a `group`, shown as a heading over the choices of that group (#210), and its
// own `checked`, when more than one value is the item's now (one per group).
import { useLayoutEffect, useRef } from "preact/hooks";
import { Pop, roam } from "./Pop.jsx";

export function MenuPick({ anchor, label, choices, current, onPick, onClose }) {
  const list = useRef(null);
  const items = () => Array.from(list.current ? list.current.querySelectorAll("[role=menuitemradio]") : []);
  useLayoutEffect(() => {
    const all = items();
    const now = all.find((el) => el.getAttribute("aria-checked") === "true") || all[0];
    if (now) now.focus({ preventScroll: true });
  }, []);                                                 // eslint-disable-line react-hooks/exhaustive-deps
  const item = (c) => (
    <button type="button" role="menuitemradio" class="menu-item" key={c.value} data-value={c.value}
      aria-checked={(c.checked === undefined ? c.value === current : c.checked) ? "true" : "false"} onClick={() => onPick(c.value)}>
      <span class="mi-t">{c.text}</span>{c.note ? <small class="mi-note">{c.note}</small> : null}</button>
  );
  const groups = [];
  for (const c of choices) {
    const g = c.group || "";
    if (!groups.length || groups[groups.length - 1].name !== g) groups.push({ name: g, items: [] });
    groups[groups.length - 1].items.push(c);
  }
  return (
    <Pop anchor={anchor} label={label} role="menu" cls="cmenu" onClose={onClose}>
      <div ref={list} onKeyDown={(e) => roam(e, items())}>
        {groups.map((g) => (g.name
          ? <div role="group" class="mi-group" key={g.name} aria-label={g.name} data-group={g.name}>
              <span class="mi-h" aria-hidden="true">{g.name}</span>{g.items.map(item)}</div>
          : g.items.map(item)))}
      </div>
    </Pop>
  );
}
