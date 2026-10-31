// Whether Change in words's words box is open (#42b). Memory only, never in the address.
import { signal } from "@preact/signals";

export const wordsOpen = signal(false);

// The fields that just changed, { token, list: [{ref, field}] }, or null: the peek flashes them (set by stores/changes.js).
export const flashed = signal(null);
