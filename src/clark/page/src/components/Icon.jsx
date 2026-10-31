// One of the page's icons as elements, never raw HTML (creaite v2.6.9 `system/templates/dashboard/src/components/Icon.jsx`,
// with only the icons clark's Work items needs; the shapes are creaite's `core/dom.js` ICONS). Hidden from screen readers:
// the words beside an icon carry the meaning.
const ICONS = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
  chevleft: '<path d="m15 18-6-6 6-6"/>',
  chevright: '<path d="m9 18 6-6-6-6"/>',
  left: '<path d="m15 6-6 6 6 6"/>',
  right: '<path d="m9 6 6 6-6 6"/>',
  tline: '<path d="M3 12h18"/><circle cx="7" cy="12" r="2"/><circle cx="15" cy="12" r="2"/><path d="M7 8V6M15 8V6"/>',
  cal: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>',
  chevdown: '<path d="m6 9 6 6 6-6"/>',
  table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M3 15h18M9 4v16"/>',
  board: '<rect x="3" y="4" width="5" height="16" rx="1"/><rect x="10" y="4" width="5" height="10" rx="1"/><rect x="17" y="4" width="4" height="13" rx="1"/>',
  expand: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  shrink: '<path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/>',
  dots: '<circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  eyeoff: '<path d="M3 3l18 18M10.6 5.1A10.4 10.4 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4M6.5 6.6A17 17 0 0 0 2 12s3.6 7 10 7a9.8 9.8 0 0 0 4.2-.9M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/>',
};
const SHAPES = new Set(["path", "circle", "rect", "line", "polyline", "polygon", "ellipse"]);
const PARSED = {};

// An icon's shapes as element data: [["path", {d: "..."}]]. Only plain SVG shapes and their attributes are kept.
export function iconShapes(name) {
  if (PARSED[name]) return PARSED[name];
  const src = String(ICONS[name] || ""), out = [];
  for (const m of src.matchAll(/<([a-z]+)((?:\s+[a-z-]+="[^"]*")*)\s*\/?>/g)) {
    if (!SHAPES.has(m[1])) continue;
    const attrs = {};
    for (const a of m[2].matchAll(/([a-z-]+)="([^"]*)"/g)) if (!/^on/i.test(a[1])) attrs[a[1]] = a[2];
    out.push([m[1], attrs]);
  }
  PARSED[name] = out;
  return out;
}

export function Icon({ name, cls }) {
  return (
    <svg class={`i${cls ? " " + cls : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
      stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" data-icn={name}>
      {iconShapes(name).map(([tag, attrs], i) => { const T = tag; return <T key={i} {...attrs} />; })}
    </svg>
  );
}
