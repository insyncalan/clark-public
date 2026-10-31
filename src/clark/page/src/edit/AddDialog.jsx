// The Add a section box (Edit only, #96): choose a template, say where it goes, add it. Opened by the window event
// `clark:add-section` (edit/addDialog.js). It is a modal dialog: focus starts in the search box and stays inside until it closes, Esc
// closes it, and focus goes back to what opened it. The page behind is `inert` while it is open. Every word from the catalogue is
// a text node.
import { useEffect, useRef, useState } from "preact/hooks";
import { mode, data } from "../stores/report.js";
import { ADD_SECTION_EVENT } from "./addDialog.js";
import { addFromTemplate } from "./actions.js";
import { KINDS, RECENT, MESSAGES, list, counts, find, available, besideState, remember, fitWords, noMatch } from "../logic/templates.js";

const STORE_KEY = "clark.recentTemplates";
const readRecent = () => { try { const v = JSON.parse(localStorage.getItem(STORE_KEY) || "[]"); return Array.isArray(v) ? remember(v.filter((x) => typeof x === "string"), "") : []; } catch (e) { return []; } };
const writeRecent = (v) => { try { localStorage.setItem(STORE_KEY, JSON.stringify(v)); } catch (e) { /* no storage: the box works without it */ } };

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
const BEHIND = ["#main", ".top"];                                    // made inert while the box is open (the message area stays live)

export function AddDialog() {
  const [open, setOpen] = useState(null);                           // null, or { after, opener }
  useEffect(() => {
    const on = (e) => {
      if (mode.value !== "edit") return;                              // View has no box: leave the request unclaimed
      e.preventDefault();                                             // claim it, so the sender does not say it is unavailable
      setOpen({ after: e.detail && e.detail.after !== undefined ? e.detail.after : null, opener: (e.detail && e.detail.opener) || null });
    };
    document.addEventListener(ADD_SECTION_EVENT, on);
    return () => document.removeEventListener(ADD_SECTION_EVENT, on);
  }, []);
  if (mode.value !== "edit" || !open) return null;
  return <Box key="box" after={open.after} opener={open.opener} onClose={() => setOpen(null)} />;
}

function Box({ after, opener, onClose }) {
  const sections = (data.value && data.value.report_sections) || [];
  const [query, setQuery] = useState("");
  const [recent] = useState(readRecent);
  const [kind, setKind] = useState("all");
  const [chosen, setChosen] = useState("");
  const [beside, setBeside] = useState(false);
  const root = useRef(null), search = useRef(null);

  const shown = list({ query, kind, recent });
  const n = counts({ query, recent });
  const current = find(chosen) && shown.some((t) => t.id === chosen) ? find(chosen) : (shown.find(available) || shown[0] || null);
  const okBeside = besideState(sections, after, current);
  const sideOn = beside && okBeside.ok;
  const canPlace = available(current);

  // Where focus goes when the box closes: what opened it, or the handle of the section it was below.
  const giveBack = () => {
    let el = opener && opener.isConnected ? opener : null;
    if (!el && after) el = document.querySelector(`.secs > .sec[data-id="${CSS.escape(after)}"] [data-drag]`);
    if (el && el.focus) el.focus();
  };
  const close = () => { onClose(); setTimeout(giveBack, 0); };

  useEffect(() => {
    if (search.current) search.current.focus();
    const held = BEHIND.map((q) => document.querySelector(q)).filter(Boolean);
    held.forEach((el) => el.setAttribute("inert", ""));
    return () => held.forEach((el) => el.removeAttribute("inert"));
  }, []);

  // A click on text that cannot take focus lands on the box itself (tabindex -1), never on the page behind; if focus still
  // falls to the page, it comes back to the box. A click on the backdrop closes the box.
  const onFocusOut = (e) => {
    if (e.relatedTarget) return;
    setTimeout(() => {
      const r = root.current;
      if (r && r.isConnected && (!document.activeElement || document.activeElement === document.body)) (search.current || r).focus();
    }, 0);
  };
  const onScrimDown = (e) => { if (e.target === e.currentTarget) close(); };

  const onKeyDown = (e) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); return; }
    if (e.key === "Enter" && !e.isComposing && e.target.matches && e.target.matches('input[type="search"], input[type="radio"]')) {
      e.preventDefault();                                          // Enter in the search box or on a template places it, the same as the button
      if (canPlace && root.current) root.current.requestSubmit();
      return;
    }
    if (e.key === "ArrowDown" && e.target === search.current) {
      const r = root.current && (root.current.querySelector('input[name="template"]:checked') || root.current.querySelector('input[name="template"]'));
      if (r) { e.preventDefault(); r.focus(); }
      return;
    }
    if (e.key !== "Tab" || !root.current) return;
    const all = Array.from(root.current.querySelectorAll(FOCUSABLE));
    if (!all.length) return;
    const first = all[0], last = all[all.length - 1];
    if (!root.current.contains(document.activeElement) || document.activeElement === root.current) { e.preventDefault(); (e.shiftKey ? last : first).focus(); }
    else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };

  // Help opens over the page, so the box closes first and Help opens at the entry (Esc in Help comes back to the page).
  const help = (place) => {
    close();
    const h = window.clarkPage && window.clarkPage.help;
    if (h) setTimeout(() => h.open(place), 0);
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!canPlace) return;
    const id = current.id;
    onClose();
    const reply = await addFromTemplate(id, after, sideOn);
    if (reply) writeRecent(remember(recent, id)); else giveBack();   // the box is already closed: only the stored list changes
  };

  const kinds = [{ id: "all", name: "All templates" }, ...(recent.length ? [{ id: RECENT, name: "Recently used" }] : []), ...KINDS];

  return (
    <div class="ad-scrim" data-edit-only onKeyDown={onKeyDown} onPointerDown={onScrimDown}>
      <form class="ad" role="dialog" aria-modal="true" aria-labelledby="ad-title" tabindex="-1" ref={root} onSubmit={submit} onFocusOut={onFocusOut}>
        <div class="ad-head">
          <h2 id="ad-title">Add a section</h2>
          <label class="ad-q"><span class="sr">Search templates</span>
            <input ref={search} type="search" placeholder="Search templates" autocomplete="off" value={query}
              onInput={(e) => setQuery(e.currentTarget.value)} />
          </label>
        </div>
        <div class="ad-main">
          <nav class="ad-kinds" aria-label="Kinds of template">
            {kinds.map((k) => (
              <button type="button" class="ad-kind" key={k.id} data-kind={k.id} aria-pressed={kind === k.id ? "true" : "false"} onClick={() => setKind(k.id)}>
                <span>{k.name}</span><span class="ad-n">{n[k.id]}</span>
              </button>
            ))}
          </nav>
          <fieldset class="ad-where">
            <legend class="ad-lbl">Where it goes</legend>
            <label><input type="radio" name="where" value="row" checked={!sideOn} onChange={() => setBeside(false)} /> On its own row</label>
            <label class={okBeside.ok ? "" : "off"}><input type="radio" name="where" value="beside" checked={sideOn} disabled={!okBeside.ok}
              aria-describedby="ad-w-why" onChange={() => setBeside(true)} /> {okBeside.ok ? `Beside “${okBeside.next}” (half width)` : "Beside the next section (half width)"}</label>
            <p class="muted ad-why" id="ad-w-why">{okBeside.ok ? "" : okBeside.message}</p>
          </fieldset>
          <fieldset class="ad-list">
            <legend class="sr">Templates</legend>
            {shown.length === 0 ? <p class="muted ad-none" role="status">{noMatch({ query, kind })}</p> : null}
            {shown.map((t) => {
              const ok = available(t);
              return (
                <label class={`ad-tpl${ok ? "" : " off"}`} key={t.id} data-template={t.id}>
                  <input type="radio" name="template" value={t.id} checked={!!current && current.id === t.id}
                    aria-disabled={ok ? undefined : "true"} aria-describedby={ok ? `ad-d-${t.id}` : `ad-d-${t.id} ad-l-${t.id}`} onChange={() => setChosen(t.id)} />
                  <span class="ad-tn">{t.name}</span>
                  <span class="ad-fit">{fitWords(t)}</span>
                  <span class="ad-td" id={`ad-d-${t.id}`}>{t.description}</span>
                  {ok ? null : <span class="ad-td ad-later" id={`ad-l-${t.id}`}>{MESSAGES.later}</span>}
                </label>
              );
            })}
          </fieldset>
          <section class="ad-prev" aria-label="About this template">
            {current ? (
              <>
                <h3 aria-live="polite">{current.name}</h3>
                <p aria-live="polite">{current.description}</p>
                <p class="ad-lbl">Holds</p>
                <ul>{current.holds.map((h) => <li key={h}>{h}</li>)}</ul>
                <p class="muted">{fitWords(current)}</p>
                <button type="button" class="ad-help" data-help="ref-section-templates" onClick={() => help("ref-section-templates")}>See every template explained in Help</button>
                {canPlace ? null : <p class="muted ad-later-prev" id="ad-later-prev">{MESSAGES.later}</p>}
              </>
            ) : <p class="muted">Choose a template.</p>}
          </section>
        </div>
        <div class="ad-foot">
          <span class="ad-helpbox">
            <button type="button" class="ad-help" data-help="howto-add-a-section-from-a-template" onClick={() => help("howto-add-a-section-from-a-template")}>About section templates</button>
          </span>
          <button type="button" class="pk-btn" data-cancel onClick={close}>Cancel</button>
          <button type="submit" class="pk-btn pri" data-place disabled={!canPlace} aria-describedby={canPlace ? undefined : "ad-later-prev"}>Add section</button>
        </div>
      </form>
    </div>
  );
}
