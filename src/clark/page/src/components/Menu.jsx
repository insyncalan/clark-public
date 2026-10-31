// A button that opens a menu of commands (creaite v2.6.9 `system/templates/dashboard/src/components/Menu.jsx`, cut down: the
// button, the role="menu" box and the keys. The hover opening, the pointer-placed menu and the menu group are left out).
// Keyboard and names: the button has aria-haspopup="menu" and aria-expanded; Down opens it. Inside, Up, Down, Home and End move,
// Enter or Space runs an item, Esc closes it with focus back on the button, Tab or a click away closes it.
import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import { Icon } from "./Icon.jsx";
import { moves } from "../stores/report.js";

// The items a key can move between: every item that is not disabled.
export const menuItemsIn = (box) => (box ? [...box.querySelectorAll("[role^=menuitem]")].filter((b) => b.getAttribute("aria-disabled") !== "true") : []);

// Up, Down (wrapping), Home and End between `items`: true when the key was one of them (it is then used up).
export function menuMove(e, items) {
  const i = items.indexOf(document.activeElement);
  let to = null;
  if (e.key === "ArrowDown") to = items[(i + 1) % items.length];
  else if (e.key === "ArrowUp") to = items[(i < 0 ? 0 : i + items.length - 1) % items.length];
  else if (e.key === "Home") to = items[0];
  else if (e.key === "End") to = items[items.length - 1];
  else return false;
  e.preventDefault(); e.stopPropagation();
  if (to) to.focus({ preventScroll: true });
  return true;
}

// The role="menu" box: focus to its first item when it opens, the keys, and a click away.
export function MenuPanel({ label, id, cls, anchor, onClose, boxRef, children }) {
  const own = useRef(null), box = boxRef || own;
  const closeRef = useRef(onClose); closeRef.current = onClose;
  useLayoutEffect(() => { (menuItemsIn(box.current)[0] || box.current).focus({ preventScroll: true }); }, []);
  useLayoutEffect(() => {                        // not after the next frame: a click away that quick still closes it
    const away = (e) => { if (!box.current.contains(e.target) && !(anchor && anchor.contains(e.target))) closeRef.current("away"); };
    document.addEventListener("pointerdown", away, true);
    return () => document.removeEventListener("pointerdown", away, true);
  }, [anchor]);
  const keys = (e) => {
    if (menuMove(e, menuItemsIn(box.current))) return;
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onClose("esc"); }
    else if (e.key === "Tab") onClose("tab");
  };
  return <div class={`ddmenu on${cls ? " " + cls : ""}`} id={id} role="menu" aria-label={label} ref={box} tabIndex={-1} onKeyDown={keys}>{children}</div>;
}

// The open state of a menu that Back or Forward (or a typed address) closes, with nothing chosen (#63). Only a menu that was already
// open before the move closes. The move count is taken when the menu is opened (in the setter, not in a render), so a menu opened a
// frame before the close effect runs (a quick click or key straight after a typed address, or in the first draw) is still known to
// have been opened on the new page and stays open. Use it where useState(false) would be.
export function useMenuState() {
  const [open, setRaw] = useState(false);
  const moved = moves.value, seen = useRef(moved), openedAt = useRef(moved);
  const setOpen = (value) => {
    const next = typeof value === "function" ? value(open) : value;
    if (next) openedAt.current = moves.peek();
    setRaw(next);
  };
  useEffect(() => { if (seen.current !== moved) { seen.current = moved; if (openedAt.current !== moved) setRaw(false); } }, [moved]);
  return [open, setOpen];
}

// items: [{id, name, line?}], or {id, sep: true} for a separator, or {id, lab} for a line of words that is not a command. `onPick(id)` runs after the menu has closed. With no items the button is a plain button and a click
// is `onClick()` (so a button that sometimes has a menu keeps the same element when it has none).
export function Menu({ label, items, onPick, onClick, icon, tip, ariaLabel, id, btnCls, labelCls, menuId, menuLabel, left, chevron = true }) {
  const [open, setOpen] = useMenuState();
  const btn = useRef(null);
  const back = useRef(false);
  const menu = items.length > 0;
  const close = (how) => { back.current = how === "esc" || how === "pick"; setOpen(false); };
  // Focus goes back to the button only if nothing took it: an item that opens a dialog has put focus there, and the menu must not steal it.
  useEffect(() => { if (!open && back.current) { back.current = false; const at = document.activeElement; if (btn.current && (!at || at === document.body || at === btn.current)) btn.current.focus(); } }, [open]);
  const onBtnKey = (e) => { if (menu && e.key === "ArrowDown" && !open) { e.preventDefault(); setOpen(true); } };
  return (
    <span class="dd">
      <button type="button" class={btnCls || "btn"} id={id} ref={btn} aria-haspopup={menu ? "menu" : undefined} aria-expanded={menu ? (open ? "true" : "false") : undefined}
        aria-label={ariaLabel} title={tip} data-tip={tip} onKeyDown={onBtnKey} onClick={(e) => { e.preventDefault(); if (menu) setOpen(!open); else if (onClick) onClick(); }}>
        {icon ? <Icon name={icon} /> : null}<span class={labelCls}>{label}</span>{chevron ? <Icon name="chevdown" cls="nch" /> : null}
      </button>
      {open && menu ? (
        <MenuPanel label={menuLabel || ariaLabel || label} id={menuId} cls={left ? "left" : ""} anchor={btn.current} onClose={close}>
          {items.map((it) => it.sep ? <div key={it.id} class="sep" role="separator"></div> : it.lab ? <div key={it.id} class="lab" role="presentation">{it.lab}</div> : (
            <button key={it.id} type="button" role="menuitem" tabIndex={-1} data-kind={it.id} onClick={() => { close("pick"); onPick(it.id); }}>
              {it.line ? <span><b>{it.name}</b><small>{it.line}</small></span> : it.name}
            </button>
          ))}
        </MenuPanel>
      ) : null}
    </span>
  );
}
