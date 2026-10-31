// Who you are (#180): the name and email typed in Settings › Personal › About you, kept by clark on this computer (api.js). Edit's
// parts only. Nothing here is read from the computer, the browser or the Claude sign-in: a fresh store has neither.
import { signal } from "@preact/signals";
import { getProfile, saveProfile } from "../api.js";

export const profile = signal({ name: "", email: "" });
export const wantName = signal(false);                  // "Add your name in Settings": the name box takes the focus when Settings has drawn
let asked = false;

/** Read what was saved, once (the menu and Settings both ask; the first one reads). */
export async function loadProfile() {
  if (asked) return;
  asked = true;
  const got = await getProfile();
  if (got) profile.value = got; else asked = false;       // a failed read is tried again the next time something asks
}

/** Save both values. Resolves {ok: true} (the menu shows them at once) or {ok: false, message} (nothing changed on screen or on disk). */
export async function setProfile(name, email) {
  const r = await saveProfile(name, email);
  if (r.ok) profile.value = { name: r.name, email: r.email };
  return r;
}
