// Settings › Personal (#45, #179): how the page looks for you: Appearance (Light, Dark or System) and how the Dashboard's sections look. It applies at once and is remembered on this computer. Edit's page only:
// a published file has no Settings.
import { style, setStyle } from "../stores/style.js";
import { useEffect, useRef, useState } from "preact/hooks";
import { appearance, setAppearance } from "../stores/appearance.js";
import { profile, loadProfile, setProfile, wantName } from "../stores/profile.js";
import { singleKeys, setSingleKeys } from "../stores/keyPrefs.js";

export const STYLES = [
  ["slim", "Slim gaps", "Sections close together, divided by a thin line."],
  ["roomy", "Roomy gaps", "More space between sections."],
  ["grey", "Grey headers", "Each section's title sits on a grey band."],
  ["card", "One card", "All the sections inside a single card."],
];

export const APPEARANCES = [                                 // the ruled order: System first, the default
  ["system", "System", "Follows your Mac's setting."],
  ["light", "Light", "Always light."],
  ["dark", "Dark", "Always dark."],
];

// About you (#180): the two optional boxes. Each is saved when it is left (or on Enter); a refusal says why under the box and writes
// nothing, and what was typed stays in the box so it can be mended. Emptying the name returns the menu's top line to its link.
function AboutYou() {
  const name = useRef(null), email = useRef(null);
  const [typed, setTyped] = useState({ name: profile.value.name, email: profile.value.email });
  const [said, setSaid] = useState({ name: "", email: "" });
  useEffect(() => { loadProfile(); }, []);
  const mounted = useRef(false);
  // The boxes follow what clark saved (a read that finished after Settings opened, or a save), never on the first draw: a box typed in
  // before that effect ran must not be emptied by it.
  useEffect(() => { if (mounted.current) setTyped({ name: profile.value.name, email: profile.value.email }); mounted.current = true; }, [profile.value.name, profile.value.email]);
  useEffect(() => { if (wantName.value && name.current) { wantName.value = false; name.current.focus(); } });
  const save = async (field) => {
    // both boxes are read as they are now (not from an earlier draw), so a box left a moment ago is never saved over the other
    const r = await setProfile(name.current ? name.current.value : typed.name, email.current ? email.current.value : typed.email);
    setSaid(r.ok ? { name: "", email: "" } : { name: field === "name" ? r.message : "", email: field === "email" ? r.message : "" });
  };
  const box = (field, label, type, line, ref) => (
    <div class="fld">
      <label for={`about-${field}`}>{label}</label>
      <input id={`about-${field}`} ref={ref} type={type} value={typed[field]} autocomplete={field === "name" ? "name" : "email"} data-about={field}
        aria-describedby={`about-${field}-line`} aria-invalid={said[field] ? "true" : undefined}
        onInput={(e) => { const v = e.currentTarget.value; setTyped((t) => ({ ...t, [field]: v })); }}
        onBlur={() => save(field)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); save(field); } }} />
      <small id={`about-${field}-line`}>{line}</small>
      <p class="fld-bad" role="alert">{said[field]}</p>
    </div>
  );
  return (
    <fieldset class="styles about" data-about-you>
      <legend>About you</legend>
      {box("name", "Your name", "text", "Shown at the top of your menu, and as the name on each change you make. Optional.", name)}
      {box("email", "Your email", "email", "Optional. Used only to tell which email addresses are your own. clark does not send email.", email)}
    </fieldset>
  );
}

export function Personal() {
  return (
    <section class="frame personal" id="personal" aria-labelledby="personal-h">
      <h2 id="personal-h">Personal</h2>
      <p class="muted">These are for you, on this computer. This changes the page you edit. The published page uses Slim gaps for now.</p>
      <fieldset class="styles" data-appearance>
        <legend>Appearance</legend>
        {APPEARANCES.map(([id, name, line]) => (
          <label key={id} class="stylepick"><input type="radio" name="appearance" value={id} checked={appearance.value === id} onChange={() => setAppearance(id)} />
            <span><b>{name}</b><small>{line}</small></span></label>
        ))}
      </fieldset>
      <AboutYou />
      <fieldset class="styles">
        <legend>Section style</legend>
        {STYLES.map(([id, name, line]) => (
          <label key={id} class="stylepick"><input type="radio" name="secstyle" value={id} checked={style.value === id} onChange={() => setStyle(id)} />
            <span><b>{name}</b><small>{line}</small></span></label>
        ))}
      </fieldset>
      <fieldset class="keys">
        <legend>Keys</legend>
        <label class="stylepick"><input type="checkbox" checked={singleKeys.value} onChange={(e) => setSingleKeys(e.currentTarget.checked)} />
          <span><b>Single-key shortcuts</b><small>Letter keys such as V and E work alone on the page. Turn them off if you type by voice or hit keys by accident. Arrows, Enter, Esc and Ctrl or Cmd combinations still work.</small></span></label>
      </fieldset>
    </section>
  );
}
