/* clark prototype: the four pages. Dashboard is the report editor (View and Edit mode, the sections, Publish); Work items
   (creaite's filters, the eye, the peek); Milestones (creaite's line, the list, Movement for slippage); Settings (projects and
   ask clark's source folders, kept simple). */
(function () {
  'use strict';
  const C = window.C, D = C.D, UI = C.UI, esc = C.esc;
  C.views = {};
  const P = () => C.P();
  const saveProject = (ch, msg) => { const u = D.change('project', P(), ch, D.who('in the report')); if (u) { C.refresh(); if ('health' in ch) C.settle('.health-fig .hpill, .health-fig .hreason, .health-fig #hReason'); C.toast(msg || 'Saved', u); } };
  /* archive or restore one document link: one step with Undo and a history line on the project (FR-43a, FR-43c) */
  const docArch = (id, on) => { const p = P(), docs = D.clone(p.docs || []), d = docs.find(x => x.id === id); if (!d) return; if (on) d.archived = true; else delete d.archived;
    const u = D.change('project', p, { docs }, D.who('in the report'), `${on ? 'Archived' : 'Restored'} the document ${d.title}`); if (!u) return;
    C.refresh(); C.toast(on ? `Archived ${d.title}. It's out of the list and the published page.` : `Restored ${d.title}. It's back in the list.`, u); };
  const rep = () => { const p = P(); if (!p.report) p.report = D.defaultReport(); if (!p.report.glance.some(f => f.k === 'health')) { p.report.glance = p.report.glance.filter(f => f.k !== 'next'); p.report.glance.unshift({ k: 'health', hidden: false }); } return p.report; };
  const setRep = (fn, msg) => { const r = D.clone(rep()); fn(r); saveProject({ report: r }, msg); };
  const UC_CLS = { 'On track': 'g', Flag: 'a', 'High risk': 'r' };
  const ucBadge = s => `<span class="ucb ${UC_CLS[s] || 'n'}">${esc(s.toUpperCase())}</span>`;

  /* ═════════════ milestone line (creaite's): scrolls sideways; making it taller zooms in ═════════════ */
  const PXD0 = 6.5;
  C.timeline = (host, list, opts = {}) => {
    const key = opts.key || 'dash';
    let z = Math.max(.7, Math.min(3, C.store.get('tlZoom.' + key, 1))), setH = 0, centre = null;
    const all = list.flatMap(m => [m.agreed, m.forecast, m.achievedOn].filter(Boolean)).concat(D.TODAY).sort();
    const s0 = new Date(D.addDays(all[0], -20) + 'T00:00:00'); s0.setDate(1); const start = D.toIso(s0);
    const e0 = new Date(D.addDays(all[all.length - 1], 45) + 'T00:00:00'); e0.setDate(1); const end = D.toIso(e0);
    const months = []; const c = new Date(start + 'T00:00:00'); while (D.toIso(c) < end) { months.push(D.toIso(c)); c.setMonth(c.getMonth() + 1); }
    const rng = d => new Date(d + 'T00:00:00').toLocaleDateString('en-GB', { month: 'short', year: 'numeric' });
    host.innerHTML = `<div class="mv-bar"><button class="ib" data-mv="-1" aria-label="Earlier">${C.icon('left')}</button><button class="ib" data-mv="1" aria-label="Later">${C.icon('right')}</button><button class="btn" data-mv="0">Today</button><span class="mv-range">${rng(start)} to ${rng(D.addDays(end, -1))}</span><span style="flex:1"></span><span class="mv-zoom">${zoomHtml(z)}</span></div><div class="mv-wrap" tabindex="0" aria-label="Milestone line; scroll sideways for the whole line; drag the bottom edge to zoom"></div>`;
    const wrap = C.$('.mv-wrap', host);
    let rows1 = 1;
    /* the hint to drag the bottom edge is for a pointer: it is hidden on touch and on a phone (M4); the percentage and Reset stay once zoomed */
    function zoomHtml(zz) { return `<span class="mv-zh">Drag the bottom edge to zoom</span>${zz !== 1 ? `<span class="mv-zp"> · ${Math.round(zz * 100)}% <button class="link" data-zreset>Reset</button></span>` : ''}`; }
    const draw = () => {
      const PXD = PXD0 * z, x = iso => Math.round((D.days(iso) - D.days(start)) * PXD), W = x(end), RH = 34 * z, T0 = 66 * z, LY = 50 * z;
      /* a label's width is worked out from its words (the line is also drawn off screen for the published page, where nothing can be measured), and a label goes in
         the first lane where it clears the one before it, the "Expected" ones too: so no two labels meet (the sweep) */
      const lw = l => (Math.max(l.kind === 'exp' ? Math.max(l.m.name.length, 19) : Math.max(l.m.name.length, 10), 10) * 6.9 + 14) * z;
      const ends = [], place = l => { const a = l.x - lw(l) / 2; let r = 0; while (ends[r] !== undefined && ends[r] + 6 > a) r++; ends[r] = l.x + lw(l) / 2; return r; };
      const labs = [];
      list.forEach(m => { const st = D.msState(m), at = m.achievedOn || m.agreed; labs.push({ m, st, x: x(at), kind: 'main' }); if (!m.achievedOn && m.forecast && m.forecast > m.agreed) labs.push({ m, st, x: x(m.forecast), kind: 'exp' }); });
      labs.sort((a, b) => (a.x - lw(a) / 2) - (b.x - lw(b) / 2)).forEach(l => { l.row = place(l); });
      const rows = Math.max(1, ...labs.map(l => l.row + 1)); rows1 = rows;
      const marks = list.map(m => { const st = D.msState(m), at = m.achievedOn || m.agreed, px = x(at), slipped = !m.achievedOn && m.forecast && m.forecast > m.agreed;
        return `${slipped ? `<div class="mv-conn" style="left:${px}px;top:${LY}px;width:${x(m.forecast) - px}px"></div><div class="mv-ghost" style="left:${x(m.forecast)}px;top:${LY + 1}px" title="Expected ${D.fd(m.forecast)}"></div>` : ''}
          <button class="mv-mk ${C.msCls(st)}" style="left:${px}px;top:${LY + 1}px" data-ms="${m.id}" aria-label="${esc(m.name)}, ${D.fd(at)}, ${D.msWord(st, opts.key === 'pub')}" title="${esc(m.name)} · ${D.fd(at)} · ${D.msWord(st, opts.key === 'pub')}">${C.msMark(st)}</button>`; }).join('')
        + labs.map(l => l.kind === 'exp'
          ? `<button class="mv-lab gl" style="left:${l.x}px;top:${T0 + l.row * RH}px" data-ms="${l.m.id}" tabindex="-1">Expected ${D.fd(l.m.forecast)}<br>${esc(l.m.name)}</button>`
          : `<button class="mv-lab ${l.st === 'Achieved' ? 'ok' : ''}" style="left:${l.x}px;top:${T0 + l.row * RH}px" data-ms="${l.m.id}" tabindex="-1"><b>${esc(l.m.name)}</b>${D.fd(l.m.achievedOn || l.m.agreed)}</button>`).join('');
      wrap.innerHTML = `<div class="mv-strip" style="width:${W}px;--z:${z}">${months.map(mo => `<div class="mv-month" style="left:${x(mo)}px">${new Date(mo + 'T00:00:00').toLocaleDateString('en-GB', { month: 'short' })}${mo.slice(5, 7) === '01' ? ' ' + mo.slice(0, 4) : ''}</div>`).join('')}
        <div class="mv-line" style="top:${LY}px"></div><div class="mv-today" style="left:${x(D.TODAY)}px"><b>Today</b></div>${marks}</div>`;
      setH = Math.round((76 + rows * 34) * z); wrap.style.height = setH + 'px';
      if (centre != null) wrap.scrollLeft = centre * W - wrap.clientWidth / 2;
      C.$$('[data-ms]', wrap).forEach(b => b.addEventListener('click', () => C.openMs(b.dataset.ms, list.map(m => m.id))));
      return x;
    };
    let x = draw();
    const toToday = smooth => { if (wrap.clientWidth) wrap.dataset.placed = '1'; wrap.scrollTo({ left: Math.max(0, x(D.TODAY) - wrap.clientWidth * .35), behavior: smooth && !C.reduce ? 'smooth' : 'instant' }); };   /* 'instant': the line opens on the current month, not on a scroll that has not finished (M4) */
    requestAnimationFrame(() => toToday(false));
    C.$$('[data-mv]', host).forEach(b => b.addEventListener('click', () => { const d = +b.dataset.mv; d ? wrap.scrollBy({ left: d * 30 * PXD0 * z, behavior: C.reduce ? 'auto' : 'smooth' }) : toToday(true); }));
    C.$('[data-zreset]', host)?.addEventListener('click', () => { C.store.set('tlZoom.' + key, 1); C.refresh(); });
    /* the user drags the bottom edge: the line zooms to the new height (creaite's milestone line) */
    let rt = 0;
    const onResize = () => { const h = wrap.offsetHeight; if (!wrap.isConnected || !h || !setH || Math.abs(h - setH) < 4) return; clearTimeout(rt); rt = setTimeout(() => {
      const W0 = wrap.scrollWidth; centre = (wrap.scrollLeft + wrap.clientWidth / 2) / (W0 || 1);
      z = Math.max(.7, Math.min(3, h / (76 + rows1 * 34))); C.store.set('tlZoom.' + key, z); x = draw();
      const zl = C.$('.mv-zoom', host); if (zl) { zl.innerHTML = zoomHtml(z); C.$('[data-zreset]', zl)?.addEventListener('click', () => { C.store.set('tlZoom.' + key, 1); C.refresh(); }); }
    }, 120); };
    if ('ResizeObserver' in window) new ResizeObserver(onResize).observe(wrap);
    wrap.addEventListener('pointerup', onResize);   // the end of a drag on the bottom edge
    C.tlZoomTo = (k2, zz) => { if (k2 !== key) return; z = zz; C.store.set('tlZoom.' + key, z); x = draw(); };
  };

  /* the milestone list, in the design system's format (a rail with a point per milestone), with state, date and progress */
  const MS_CLS = { Achieved: 'g', 'On track': 'g', 'At risk': 'a', Slipped: 'r', Overdue: 'r', Forecast: 'b' };
  C.msListHtml = (list, editing, key) => msListHtml(list, editing, key);
  function msListHtml(list, editing, key) {
    const allOn = C.store.get('msAll.' + key, false), shown = allOn ? list : list.slice(0, 5);
    const rows = shown.map(m => {
      const st = D.msState(m), sl = D.slip(m), say = D.msWord(st, key === 'pub');
      /* each date once, and the state is said once (in its own column): the sweep found both repeated (M5) */
      const date = st === 'Achieved' ? `<b>${D.fd(m.achievedOn)}</b><small>${m.achievedOn > m.agreed ? `${C.dy(D.days(m.achievedOn) - D.days(m.agreed))} after the agreed date` : 'On the agreed date'}</small>`
        : `<b>${D.fd(m.agreed)}</b><small${sl > 0 ? ' class="late"' : ''}>${st === 'Forecast' ? 'Not agreed yet' : sl > 0 ? `Expected ${D.fd(D.expected(m))} · ${C.dy(sl)} later` : 'Agreed'}</small>`;
      return `<li class="msl-row${m.client ? '' : ' out'}" data-ms="${m.id}" tabindex="0" role="button" aria-label="${esc(m.name)}, ${say}"><span class="node ${MS_CLS[st]}${st === 'Achieved' ? ' fill' : ''}"></span>
        <span class="msl-date">${date}</span><span class="msl-name">${esc(m.name)}${m.client ? '' : ' <span class="tag">Internal only</span>'}</span>
        <span class="mst ${C.msCls(st)}">${C.msMark(st)}${say}</span>
        <span class="msl-prog" title="Progress">${m.progress == null ? '<span class="muted">Not set</span>' : `<span class="pbar"><i style="width:${m.progress}%"></i></span>${m.progress}%`}</span>
        ${editing ? `<button class="ib" data-ms-eye="${m.id}" aria-label="${m.client ? 'Shown' : 'Hidden'}: ${esc(m.name)}">${C.icon(m.client ? 'eye' : 'eyeoff', 's')}</button>` : ''}</li>`;
    }).join('');
    return `<ul class="msl">${rows}</ul>${list.length > 5 ? `<button class="link msl-all" data-msall="${key}">${allOn ? 'Show the first 5' : `Show all ${list.length} milestones`}</button>` : ''}`;
  }

  /* ── milestones: a Calendar view beside the timeline, with a discreet switcher ("add Calendar view... and a
     discreet switcher for both editor and client"). Every month that holds a milestone is drawn, one shown at a time, so the
     same markup works in the editor and in the published page; a slipped milestone also shows where it is now expected. ── */
  C.msCalHtml = (list, key) => {
    /* Week, Month (the default) or Quarter ("default view is month but we should have switches for week, month,
       quarter"): every pane of each scale is drawn, one shown at a time, so the published page needs no app code */
    const at = m => m.achievedOn || m.agreed, exp = m => !m.achievedOn && m.forecast && m.forecast > m.agreed ? m.forecast : '';
    const dates = list.flatMap(m => [at(m), exp(m)]).filter(Boolean).concat(D.TODAY).sort(), cur = D.TODAY.slice(0, 7);
    const months = []; const c = new Date(dates[0].slice(0, 7) + '-01T00:00:00'); while (D.toIso(c).slice(0, 7) <= dates[dates.length - 1].slice(0, 7)) { months.push(D.toIso(c).slice(0, 7)); c.setMonth(c.getMonth() + 1); }
    const lab = mo => new Date(mo + '-01T00:00:00').toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
    const nm = m => esc(m.clientText && key === 'pub' ? C.plain(m.clientText) : m.name);
    const chip = (m, iso, ghost) => { const st = D.msState(m), w = D.msWord(st, key === 'pub');
      return `<button class="cal-ms ${C.msCls(st)}${ghost ? ' ghost' : ''}" data-ms="${m.id}" title="${esc(m.name)} · ${D.fd(iso)} · ${ghost ? 'expected' : w}">${C.msMark(st)}<span>${ghost ? 'Expected: ' : ''}${nm(m)}</span></button>`; };
    /* on a phone the cells are too small for names, so the milestones of the shown period are listed under the month, one line each, by day (M3); hidden above 700 px */
    const agenda = (a, b) => { const rows = list.flatMap(m => [[at(m), m, false], [exp(m), m, true]]).filter(([iso]) => iso && iso >= a && iso <= b).sort((x, y) => x[0].localeCompare(y[0]));
      return rows.length ? `<ul class="cal-ag" aria-label="Milestones in this period">${rows.map(([iso, m, ghost]) => { const st = D.msState(m);
        return `<li><b>${new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })}</b><button type="button" class="cal-agb ${C.msCls(st)}${ghost ? ' ghost' : ''}" data-ms="${m.id}">${C.msMark(st)}<span>${ghost ? 'Expected: ' : ''}${nm(m)}</span><small>${ghost ? 'Expected later' : D.msWord(st, key === 'pub')}</small></button></li>`; }).join('')}</ul>` : '<p class="cal-ag cal-ag0 muted">No milestones in this period.</p>'; };
    const chips = iso => list.filter(m => at(m) === iso).map(m => chip(m, iso)).join('') + list.filter(m => exp(m) === iso).map(m => chip(m, iso, true)).join('');
    /* each day is a focusable cell (a roving tabindex, set in msvWire): its date, and how many milestones fall on it, are its label */
    const dayAttrs = iso => { const n = list.filter(m => at(m) === iso).length + list.filter(m => exp(m) === iso).length;
      return ` data-d="${iso}" tabindex="-1" role="group" aria-label="${new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}${n ? ', ' + n + ' milestone' + (n === 1 ? '' : 's') : ''}"`; };
    const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'], dow = `<div class="cal-dow" aria-hidden="true">${DOW.map(x => `<span>${x}</span>`).join('')}</div>`;
    const grid = mo => { const d1 = new Date(mo + '-01T00:00:00'), lead = (d1.getDay() + 6) % 7, n = new Date(d1.getFullYear(), d1.getMonth() + 1, 0).getDate();
      const cells = [...Array(lead).fill(''), ...Array.from({ length: n }, (_, i) => `${mo}-${String(i + 1).padStart(2, '0')}`)]; while (cells.length % 7) cells.push('');
      return `${dow}<div class="cal-g">${cells.map((iso, i) => !iso ? '<div class="cal-d out"></div>' : `<div class="cal-d${iso === D.TODAY ? ' today' : ''}${i % 7 > 4 ? ' we' : ''}"${dayAttrs(iso)}><span class="cal-n">${+iso.slice(8)}</span>${chips(iso)}</div>`).join('')}</div>`; };
    const pane = (mode, id, label, body, show) => `<div class="cal-m cal-${mode}" data-cal-m="${id}" data-mode="${mode}" data-label="${label}"${show ? '' : ' hidden'}>${body}</div>`;
    const mon = iso => { const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() - (d.getDay() + 6) % 7); return D.toIso(d); };
    const weeks = []; for (let w = mon(months[0] + '-01'); w <= dates[dates.length - 1]; w = D.addDays(w, 7)) weeks.push(w);
    const wlab = w => `Week of ${D.fd(w)}`, curW = mon(D.TODAY);
    const weekPane = w => pane('week', w, wlab(w), `${dow}<div class="cal-g cal-wk">${DOW.map((x, i) => { const iso = D.addDays(w, i); return `<div class="cal-d${iso === D.TODAY ? ' today' : ''}${i > 4 ? ' we' : ''}"${dayAttrs(iso)}><span class="cal-n">${+iso.slice(8)} ${new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', { month: 'short' })}</span>${chips(iso)}</div>`; }).join('')}</div>${agenda(w, D.addDays(w, 6))}`, false);
    const q = mo => `${mo.slice(0, 4)}-Q${Math.floor((+mo.slice(5, 7) - 1) / 3) + 1}`, quarters = [...new Set(months.map(q))], curQ = q(cur);
    const qMonths = qq => { const y = qq.slice(0, 4), f = (+qq.slice(-1) - 1) * 3; return [1, 2, 3].map(k => `${y}-${String(f + k).padStart(2, '0')}`); };
    const qlab = qq => `Q${qq.slice(-1)} ${qq.slice(0, 4)}`;
    const quarterPane = qq => pane('quarter', qq, qlab(qq), `<div class="cal-q">${qMonths(qq).map(mo => `<div><button class="cal-qm" data-cal-goto="${mo}" title="Show ${lab(mo)}">${new Date(mo + '-01T00:00:00').toLocaleDateString('en-GB', { month: 'long' })}</button>${grid(mo)}</div>`).join('')}</div>${agenda(qMonths(qq)[0] + '-01', qMonths(qq)[2] + '-31')}`, false);
    return `<div class="cal" data-cal-day="${D.TODAY}" data-cal-today="${cur}" data-cal-week="${curW}" data-cal-quarter="${curQ}" data-calv="month"><div class="cal-bar"><button class="ib" data-cal="-1" aria-label="Earlier">${C.icon('left')}</button><button class="ib" data-cal="1" aria-label="Later">${C.icon('right')}</button><button class="btn" data-cal="0">Today</button><b class="cal-t">${lab(months.includes(cur) ? cur : months[0])}</b>
      <span class="seg cal-sc" role="group" aria-label="Calendar scale">${[['week', 'Week'], ['month', 'Month'], ['quarter', 'Quarter']].map(([v, t]) => `<button data-calv-b="${v}" aria-pressed="${v === 'month'}">${t}</button>`).join('')}</span></div>
      ${months.map(mo => pane('month', mo, lab(mo), grid(mo) + agenda(mo + '-01', mo + '-31'), mo === cur)).join('')}${weeks.map(weekPane).join('')}${quarters.map(quarterPane).join('')}</div>`;
  };
  /* the legend: a discreet word under the milestones that shows what each mark means on hover or focus;
     plain CSS, so it works in the published page too, where the client words are used */
  C.msLegendHtml = key => { const pub = key === 'pub', row = (mark, t, d) => `<li><span class="mlg-m">${mark}</span><span><b>${t}</b>${d ? ` <span>${d}</span>` : ''}</span></li>`;
    return `<div class="mlg"><button class="mlg-b" type="button" aria-describedby="mlg-${key}">${C.icon('info', 's')}Legend</button><div class="mlg-p" role="tooltip" id="mlg-${key}"><ul>
      ${row(C.msMark('Achieved'), 'Achieved', 'Done, on the date it was achieved')}${row(C.msMark('On track'), 'On track', 'Expected on its agreed date')}
      ${row(C.msMark('At risk'), 'At risk', 'Marked at risk by the project team')}${row(C.msMark('Slipped'), D.msWord('Slipped', pub), 'Now expected after its agreed date')}
      ${row(C.msMark('Overdue'), D.msWord('Overdue', pub), 'Its agreed date has passed')}${row(C.msMark('Forecast'), 'Forecast', 'A date not yet agreed')}</ul>
      <ul class="mlg-sym">${row('<i class="mlg-ghost"></i>', 'Expected', 'Where a slipped milestone is now expected; a dashed line joins it to its agreed date')}
      ${row('<i class="mlg-today"></i>', 'Today', 'The line on the timeline; the blue date on the calendar')}</ul></div></div>`; };
  /* the switcher and both views; lineHtml is the timeline's own markup when it is drawn already (the published page) */
  C.msViewsHtml = (list, key, lineHtml = '') => `<div class="msv" data-msvk="${key}" data-msv="${esc(key === 'pub' ? 'line' : C.store.get('msv.' + key, 'line'))}"><div class="msv-sw" role="group" aria-label="Milestone view">${[['line', 'tline', 'Timeline'], ['cal', 'cal', 'Calendar']].map(([v, i, t]) => `<button type="button" class="msv-b" data-msvb="${v}">${C.icon(i, 's')}<span>${t}</span></button>`).join('')}</div><div class="msv-line"${lineHtml ? '' : ' data-tl'}>${lineHtml}</div><div class="msv-cal">${C.msCalHtml(list, key)}</div>${C.msLegendHtml(key)}</div>`;
  /* the same few lines run in the published page (its source is copied there, see io.js), so they use no app code */
  function msvWire(r, get, set) {
    const k = r.dataset.msvk, b = [...r.querySelectorAll('[data-msvb]')], sync = () => b.forEach(x => x.setAttribute('aria-pressed', x.dataset.msvb === r.dataset.msv));
    r.dataset.msv = get(k) || r.dataset.msv; sync();
    /* the view that appears fades in with a 4 px rise (the .vin class); nothing with reduced motion */
    const fade = el => { if (!el || (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches)) return; el.classList.remove('vin'); void el.offsetWidth; el.classList.add('vin'); };
    /* a timeline drawn while the Calendar was showing has no width yet: when it appears it is placed on today, once (M4) */
    const place = () => { const w = r.querySelector('.mv-wrap'), td = r.querySelector('.mv-today'); if (w && td && w.clientWidth && !w.dataset.placed) { w.dataset.placed = '1'; w.scrollTo({ left: Math.max(0, td.offsetLeft - w.clientWidth * .35), behavior: 'instant' }); } };
    b.forEach(x => x.addEventListener('click', () => { r.dataset.msv = x.dataset.msvb; set(k, x.dataset.msvb); sync(); fade(r.querySelector(x.dataset.msvb === 'cal' ? '.msv-cal' : '.msv-line')); place(); }));
    const c = r.querySelector('.cal'); if (!c) return;
    const t = c.querySelector('.cal-t'), today = { month: c.dataset.calToday, week: c.dataset.calWeek, quarter: c.dataset.calQuarter };
    let mode = get('calv.' + k) || 'month', i = 0;
    const ps = () => [...c.querySelectorAll('[data-mode="' + mode + '"]')];
    /* the days: one cell of the shown period has tabindex 0 (today, else the first day); the arrow keys move by a day or a week, into the
       next period when they leave this one; Enter on a day with milestones goes to its first chip */
    const add = (iso, n) => { const d = new Date(iso + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
    const cells = () => ps()[i] ? [...ps()[i].querySelectorAll('.cal-d[data-d]')] : [];
    const rove = iso => { const cs = cells(), at = cs.find(x => x.dataset.d === iso) || cs.find(x => x.dataset.d === c.dataset.calDay) || cs[0]; c.querySelectorAll('.cal-d[data-d]').forEach(x => { x.tabIndex = x === at ? 0 : -1; }); return at; };
    const show = iso => { const all = ps(); i = Math.max(0, Math.min(all.length - 1, i)); c.querySelectorAll('[data-cal-m]').forEach(p => { p.hidden = p !== all[i]; }); t.textContent = all[i] ? all[i].dataset.label : ''; c.dataset.calv = mode;
      c.querySelectorAll('[data-calv-b]').forEach(x => x.setAttribute('aria-pressed', x.dataset.calvB === mode)); return rove(typeof iso === 'string' ? iso : ''); };
    const toToday = () => { i = Math.max(0, ps().findIndex(p => p.dataset.calM === today[mode])); };
    toToday(); show();
    c.querySelectorAll('[data-cal]').forEach(x => x.addEventListener('click', () => { const d = +x.dataset.cal; if (d) i += d; else toToday(); show(); }));
    c.querySelectorAll('[data-calv-b]').forEach(x => x.addEventListener('click', () => { mode = x.dataset.calvB; set('calv.' + k, mode); toToday(); show(); fade(ps()[i]); }));
    /* from a milestone chip, Shift+Tab, or Esc when no peek is open, goes back to the day it sits in (#99); #panel is the published page's peek */
    c.addEventListener('keydown', e => { const b = e.target.closest ? e.target.closest('.cal-ms') : null, d = b && b.closest('.cal-d[data-d]'); if (!d) return;
      if ((e.key === 'Tab' && e.shiftKey) || (e.key === 'Escape' && !document.querySelector('#peek.on, #panel.on'))) { e.preventDefault(); const f = rove(d.dataset.d); if (f) f.focus(); } });
    c.addEventListener('keydown', e => { const d = e.target.closest ? e.target.closest('.cal-d[data-d]') : null; if (!d || e.target !== d) return;
      const mv = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
      if (mv) { e.preventDefault(); const to = add(d.dataset.d, mv), at = ps().findIndex(p => p.querySelector('.cal-d[data-d="' + to + '"]')); if (at < 0) return; i = at; const f = show(to); if (f) f.focus(); }
      else if (e.key === 'Enter') { const b = d.querySelector('.cal-ms'); if (b) { e.preventDefault(); b.focus(); } } });
    /* in Quarter, a month's name opens that month */
    c.querySelectorAll('[data-cal-goto]').forEach(x => x.addEventListener('click', () => { mode = 'month'; set('calv.' + k, mode); i = Math.max(0, ps().findIndex(p => p.dataset.calM === x.dataset.calGoto)); show(); }));
  }
  C.MSV_JS = msvWire.toString();
  C.wireMsViews = (root, list) => { C.$$('.msv', root).forEach(r => { msvWire(r, k => C.store.get('msv.' + k, ''), (k, v) => C.store.set('msv.' + k, v));
    C.$$('.cal-ms, .cal-agb', r).forEach(b => b.addEventListener('click', () => C.openMs(b.dataset.ms, list.map(m => m.id)))); }); };
  function wireMsList(host, list, key) {
    C.$$('.msl-row', host).forEach(r => { const go = e => { if (e.target.closest('[data-ms-eye]')) return; C.openMs(r.dataset.ms, list.map(m => m.id)); }; r.addEventListener('click', go); r.addEventListener('keydown', e => { if (e.key === 'Enter') go(e); }); });
    C.$$('[data-ms-eye]', host).forEach(b => b.addEventListener('click', e => { e.stopPropagation(); const m = C.mss().find(x => x.id === b.dataset.msEye); C.hideLater(b.closest('li'), D.change('ms', m, { client: false }, D.who('with the eye')), `${m.name} taken off the page`); }));
    C.$('[data-msall]', host)?.addEventListener('click', () => { C.store.set('msAll.' + key, !C.store.get('msAll.' + key, false)); C.refresh(); });
    const t = C.$('.mv-detog', host); if (t) t.addEventListener('click', () => { const on = t.getAttribute('aria-expanded') !== 'true'; t.setAttribute('aria-expanded', on); t.lastChild.textContent = on ? ' Hide milestone details' : ' Show milestone details'; C.$('.mv-rows', host).classList.toggle('shut', !on); C.store.set('msDetails', on); });
  }
  const msDetailsHtml = (list, editing, key) => { const on = C.store.get('msDetails', true);
    return `<button class="mv-detog" aria-expanded="${on}">${C.icon('chev', 's chev')}<span> ${on ? 'Hide' : 'Show'} milestone details</span></button><div class="mv-rows${on ? '' : ' shut'}"><div>${msListHtml(list, editing, key)}</div></div>`; };

  /* a tooltip that waits a second (the use case rows say they can be opened) */
  let tipT = 0, tipEl = null;
  const tipHide = () => { clearTimeout(tipT); tipEl?.remove(); tipEl = null; };
  C.slowTip = (el, text) => {
    el.addEventListener('mouseenter', e => { tipHide(); const x = e.clientX, y = e.clientY; tipT = setTimeout(() => { tipEl = document.createElement('div'); tipEl.className = 'slowtip'; tipEl.setAttribute('role', 'tooltip'); tipEl.textContent = text; document.body.appendChild(tipEl);
      tipEl.style.left = Math.min(x + 12, innerWidth - tipEl.offsetWidth - 8) + 'px'; tipEl.style.top = (y + 18) + 'px'; }, 1000); });
    el.addEventListener('mouseleave', tipHide); el.addEventListener('mousedown', tipHide);
  };

  /* ═════════════ dashboard: the report editor ═════════════ */
  C.glanceData = p => {
    const its = D.S.items.filter(x => x.code === p.code && !x.archived);   /* an archived item is in no count (FR-43c) */
    const over = its.filter(x => x.type === 'A' && C.isOpen(x) && x.due && D.days(x.due) < 0);
    const high = its.filter(x => (x.type === 'R' || x.type === 'I') && C.isOpen(x) && (x.priority === 'Urgent' || x.priority === 'High'));
    const dec = its.filter(x => x.type === 'D' && x.status === 'Pending');
    const openA = its.filter(x => x.type === 'A' && C.isOpen(x)).length, red = high.filter(x => C.ragOf(x) === 'R').length;
    /* rag: the tile's automatic colour, from the data; the user can set another with a right-click (Edit mode) */
    return {
      health: { k: 'Project health', rag: p.health },
      overdue: { v: over.length, k: 'Overdue actions', d: `of ${openA} open actions`, rag: over.length ? 'R' : 'G', go: () => C.workFilter({ type: 'A', due: ['overdue'] }) },
      risks: { v: high.length, k: 'High risks and issues', d: red ? `${red} red or urgent` : high.length ? 'None red' : 'None open', rag: red ? 'R' : high.length ? 'A' : 'G', go: () => C.workFilter({ type: 'R', priority: ['Urgent', 'High'] }) },
      decisions: { v: dec.length, k: 'Decisions needed', d: dec.length ? `Oldest ${D.fd(dec.map(x => x.due).sort()[0])}` : 'None waiting', rag: dec.length ? 'A' : 'G', go: () => C.workFilter({ type: 'D', status: ['Pending'] }) },
    };
  };
  /* ── a suggested health (FR-62b, #122): plain rules, shown beside the user's own and never replacing it. At risk when any rule applies, Off track
     when all three do: an action overdue by more than 7 days, a milestone that has slipped, two or more red risks or issues. ── */
  const HN_ALL = { G: 'On track', A: 'At risk', R: 'Off track' }, RANK = { G: 0, A: 1, R: 2 };
  C.healthSuggest = p => {
    const its = D.S.items.filter(x => x.code === p.code && C.isOpen(x) && !x.archived), over = its.filter(x => x.type === 'A' && x.due && D.days(x.due) < -7);
    const slipped = D.S.milestones.filter(m => m.code === p.code && !m.archived && !m.achievedOn && m.manual !== 'Forecast' && D.slip(m) > 0), red = its.filter(x => (x.type === 'R' || x.type === 'I') && C.ragOf(x) === 'R');
    const parts = [];
    if (over.length) parts.push(`${over.length} ${over.length === 1 ? 'action' : 'actions'} overdue by more than 7 days (${over.map(x => x.id).join(', ')})`);
    if (slipped.length) parts.push(`${slipped.length} slipped ${slipped.length === 1 ? 'milestone' : 'milestones'}`);
    if (red.length >= 2) parts.push(`${red.length} red risks or issues`);
    const h = !parts.length ? 'G' : parts.length >= 3 ? 'R' : 'A', because = parts.length > 1 ? parts.slice(0, -1).join(', ') + ' and ' + parts[parts.length - 1] : parts[0] || 'no action is overdue by more than 7 days, no milestone has slipped and fewer than 2 risks are red';
    return { h, word: HN_ALL[h], because, parts, text: `Suggested: ${HN_ALL[h]}, because ${because}`, better: RANK[p.health] < RANK[h] };   /* better: the user's own health is better than the suggestion, so the reason is needed */
  };
  const ITEMS_OF = { raid: x => x.type === 'R' || x.type === 'I', actions: x => x.type === 'A', decisions: x => x.type === 'D' };
  const ADD_TYPE = { raid: 'R', actions: 'A', decisions: 'D' };
  /* a tile's status in words as well as colour (#140: colour is never the only signal). The word follows the colour the tile shows, automatic or
     set by hand; a tile with no colour has no word. Three tiles say it more exactly: red Overdue actions are "Overdue", amber Decisions needed are "Waiting",
     and High risks and issues are "Watch" (amber) or "High" (red), so a count of risks never reads as late. Project health's word sits beside a pill that
     may say something else, so it says what it is: "Tile colour: Off track". The same tables as the product's glanceTiles.js */
  const TILE_WORD = { G: 'On track', A: 'At risk', R: 'Off track' }, TILE_WORD_OF = { overdue: { R: 'Overdue' }, decisions: { A: 'Waiting' }, risks: { A: 'Watch', R: 'High' } };
  C.HEALTH_WORD_LABEL = 'Tile colour: ';
  C.tileWord = (k, rag) => (TILE_WORD_OF[k] || {})[rag] || TILE_WORD[rag] || '';
  C.glanceHtml = (p, r, editing) => glanceHtml(p, r, editing);
  function glanceHtml(p, r, editing) {
      const g = C.glanceData(p), HN = { G: 'On track', A: 'At risk', R: 'Off track' }, sug = editing ? C.healthSuggest(p) : null;
      return `<div class="glance" data-glance>${r.glance.filter(f => editing || !f.hidden).map(f => { const d = g[f.k]; if (!d) return '';
        const rag = f.rag || d.rag || '', word = f.rag === 'N' ? '' : C.tileWord(f.k, rag), sw = word ? `<span class="sw sw-${rag}">${word}</span>` : '';
        if (f.k === 'health') return `<div class="fig health-fig rag-${f.rag === 'N' ? 'N' : rag}" data-fig="health" ${editing ? 'draggable="true"' : ''}><div class="k">Project health${rag !== p.health && word ? `<span class="sw sw-${rag}">${C.HEALTH_WORD_LABEL}${word}</span>` : ''}</div><div class="hrow">${editing ? `<button class="hpill ${p.health}" id="hPill" aria-label="Project health: ${HN[p.health]}. Select to change">${HN[p.health]}</button><textarea id="hReason" rows="2" aria-label="Why the project has this health" ${sug.better ? 'required aria-required="true" aria-describedby="hReq"' : ''} placeholder="${sug.better ? 'Why is it better than the suggestion? (needed)' : 'Why, in a line or two'}">${esc(p.reason)}</textarea>` : `<span class="hpill ${p.health}">${HN[p.health]}</span><div class="hreason">${esc(p.reason).replace(/\n/g, '<br>')}</div>`}</div>${editing ? `<div class="hsug" id="hSug"><span>${esc(sug.text)}.</span>${sug.h !== p.health ? ' <button class="link" id="hUse">Use the suggestion</button>' : ' <span class="hsug-ok">Your choice matches it.</span>'}</div>${sug.better ? `<p class="hreq${p.reason.trim() ? ' ok' : ''}" id="hReq" role="${p.reason.trim() ? 'status' : 'alert'}">${p.reason.trim() ? 'Your health is better than the suggestion, so the reason is needed. It is there; check it still fits.' : 'Your health is better than the suggestion. Say why in the box above: the reason is needed.'}</p>` : ''}` : ''}</div>`;
        return `<div class="fig go kpi rag-${f.rag === 'N' ? 'N' : rag}${f.hidden ? ' out' : ''}" data-fig="${f.k}" ${editing ? 'draggable="true"' : ''} role="button" tabindex="0" aria-label="${esc(String(d.k))}: ${d.v}, ${esc(d.d || '')}${word ? ', ' + word : ''}. Open the list">${editing ? `<button class="ib eye" data-fig-eye="${f.k}" aria-label="${f.hidden ? 'Show' : 'Hide'} ${esc(String(d.k))}">${C.icon(f.hidden ? 'eyeoff' : 'eye', 's')}</button>` : ''}<div class="k"><i class="ragdot"></i>${d.k}</div><div class="vrow"><div class="v">${d.v}</div>${sw}</div>${d.d ? `<div class="d">${esc(d.d)}</div>` : ''}</div>`; }).join('')}</div>
        ${editing ? '<p class="note">Drag a tile to reorder it (or Alt with the arrow keys); the eye hides it; right-click a tile to change its colour. Hidden tiles are left out of the published page.</p>' : ''}`;
  }
  /* the dashboard's rows (#95): a section with beside:true shares its row with the next one drawn, so a row holds one or two and pairs never chain.
     'secs' is what is drawn (At a glance is left out when it sits inside the cover); 'show' drops hidden sections, and a pair with one half hidden shows the other full width */
  C.secRows = (secs, show) => { const rows = []; for (let i = 0; i < secs.length; i++) { const s = secs[i], n = secs[i + 1]; if (s.beside && n) { rows.push([s, n]); i++; } else rows.push([s]); }
    return show ? rows.map(r2 => r2.filter(show)).filter(r2 => r2.length) : rows; };
  /* one report layout: Boxed ("only have boxed as default - not in settings for selection"); Health spine and Cover-led are in the backlog (#46) */
  C.layOf = () => 'boxed';
  C.drawnSecs = (r, p) => r.sections.filter(s => !(C.layOf(p) !== 'boxed' && s.type === 'glance'));
  /* tidy: beside only on the first of a two-section row; nothing on a lone section or on one that is not drawn */
  function tidySecs(a, drawn) { C.secRows(drawn).forEach(row => { if (row.length < 2) delete row[0].beside; else delete row[1].beside; }); a.forEach(s => { if (!drawn.includes(s)) delete s.beside; }); }
  /* place a section: at = { before: id|null } for a full row (before that row, or at the end) or { ref: id, side: 'l'|'r' } for beside a section that is alone. Works on a copy of the list and returns false if it cannot */
  function placeSec(a, gl, id, at) {
    const it = a.find(s => s.id === id); if (!it) return false;
    const row0 = C.secRows(a.filter(s => !gl(s))).find(row => row.includes(it)); if (row0) delete row0[0].beside; delete it.beside;
    a.splice(a.indexOf(it), 1);
    if (at.ref) { const ref = a.find(s => s.id === at.ref); if (!ref || ref === it || C.secRows(a.filter(s => !gl(s))).find(row => row.includes(ref))?.length > 1) return false;
      if (at.side === 'l') { it.beside = true; a.splice(a.indexOf(ref), 0, it); } else { ref.beside = true; a.splice(a.indexOf(ref) + 1, 0, it); } }
    else { const k = at.before ? a.findIndex(s => s.id === at.before) : -1; a.splice(k < 0 ? a.length : k, 0, it); }
    tidySecs(a, a.filter(s => !gl(s))); return true;
  }
  /* Move up and Move down go by rows: a lone section swaps rows with its neighbour; half of a pair steps out of it, to full width */
  function stepSec(a, gl, id, dir) {
    const drawn = a.filter(s => !gl(s)), rows = C.secRows(drawn), k = rows.findIndex(row => row.some(s => s.id === id)); if (k < 0) return false;
    const row = rows[k], it = row.find(s => s.id === id), second = row.length > 1 && row[1] === it, rest = rows.filter((_, j) => j !== k); if (row.length > 1) rest.splice(k, 0, row.filter(s => s !== it));
    const to = row.length < 2 ? k + dir : dir < 0 ? (second ? k : k - 1) : (second ? k + 2 : k + 1); if (to < 0 || to > rest.length) return false;
    rest.splice(to, 0, [it]); const out = []; rest.forEach(g => g.forEach((s, j) => { if (g.length > 1 && j === 0) s.beside = true; out.push(s); }));
    a.filter(s => gl(s)).forEach(s => out.splice(Math.min(a.indexOf(s), out.length), 0, s)); a.splice(0, a.length, ...out); tidySecs(a, a.filter(s => !gl(s))); return true;
  }
  /* ── section templates (#96): the one list the Add a section box, the empty sections and Help's table draw from. fit = where it works, first the
     better one; kind = the box's left list; sk = the small sketch [grid style, parts]; els = what it holds (the tags in the preview);
     ph = its empty state, [element, how it is drawn, spans the row], laid out in cols (the mockup's "Empty, ready to fill") ── */
  const sk = (g, ...c) => [g, c.map(x => `<i${x ? ` style="${x}"` : ''}></i>`).join('')];
  const KINDS = [['text', 'Text and pictures'], ['figures', 'Figures'], ['raid', 'Work items'], ['files', 'Files and links'], ['people', 'People and dates'], ['notes', 'Notes']];
  const TPL = [
    { id: 'text', name: 'Text', kind: 'text', fit: ['Full', 'Half'], d: 'Words under a heading, written in clark’s one editor.', els: ['Heading', 'Text'], sk: sk('grid-template-rows:repeat(3,1fr)', '', 'width:80%', 'width:60%'), cols: '1fr', ph: [['Text', 'text']] },
    { id: 'text-image', name: 'Text and image', kind: 'text', fit: ['Full', 'Half'], d: 'A story with a picture: a site visit, a design, a screenshot of the new system.', els: ['Heading', 'Text', 'Image', 'Caption'], sk: sk('grid-template-columns:1.4fr 1fr', '', 'background:#B9C8FF'), cols: '1.4fr 1fr', ph: [['Text', 'text'], ['Image', 'image'], ['Caption', 'caption', 1]] },
    { id: 'banner', name: 'Banner', kind: 'text', fit: ['Full'], d: 'Open the report with a message: a milestone reached, a go-live, a change of phase.', els: ['Image (background, optional)', 'Heading', 'Text', 'Button'], sk: sk('', 'background:#22386A'), cols: '1fr', ph: [['Image (background, optional)', 'image'], ['Text', 'text'], ['Button', 'button']] },
    { id: 'figures-4', name: 'Key figures, four', kind: 'figures', fit: ['Full', 'Half'], d: 'Three or four numbers with labels and a change since last week.', els: ['Heading', 'Figure · live', 'Figure · live', 'Figure · typed', 'Figure · typed', 'Caption'], sk: sk('grid-template-columns:repeat(4,1fr)', '', '', '', ''), cols: 'repeat(4,minmax(0,1fr))', ph: [['Figure', 'figure'], ['Figure', 'figure'], ['Figure', 'figure'], ['Figure', 'figure'], ['Caption', 'caption', 1]] },
    { id: 'figures-3', name: 'Key figures, three', kind: 'figures', fit: ['Full', 'Half'], d: 'The same, for three numbers. Each card is wider, so a short note fits under the change.', els: ['Heading', 'Figure · live', 'Figure · live', 'Figure · typed'], sk: sk('grid-template-columns:repeat(3,1fr)', '', '', ''), cols: 'repeat(3,minmax(0,1fr))', ph: [['Figure', 'figure'], ['Figure', 'figure'], ['Figure', 'figure']] },
    { id: 'gallery', name: 'Image gallery', kind: 'text', fit: ['Full'], d: 'Two to six pictures in a grid, each with a caption.', els: ['Heading', 'Image', 'Caption', 'Image', 'Caption', 'Image'], sk: sk('grid-template-columns:repeat(3,1fr)', 'background:#B9C8FF', 'background:#B9C8FF', 'background:#B9C8FF'), cols: 'repeat(3,minmax(0,1fr))', ph: [['Image', 'image'], ['Image', 'image'], ['Image', 'image'], ['Caption', 'caption', 1]] },
    { id: 'table', name: 'Table', kind: 'notes', fit: ['Full'], d: 'Anything with rows: a budget line, a cut-over plan, a training schedule.', els: ['Heading', 'Table'], sk: sk('grid-template-rows:repeat(4,1fr)', '', '', '', ''), cols: '1fr', ph: [['Table', 'table']] },
    { id: 'link', name: 'Link preview', kind: 'files', fit: ['Full'], d: 'A web page shown as a card: a dashboard, a news item, a recording.', els: ['Heading', 'Link (with preview)'], sk: sk('grid-template-columns:1fr 2fr', 'background:#B9C8FF', ''), cols: '1fr', ph: [['Link (with preview)', 'link']] },
    { id: 'raid-3', name: 'RAID cards, three', kind: 'raid', fit: ['Full'], d: 'The risks, actions, issues or decisions you want the reader to see, as cards.', els: ['Heading', 'RAID card ×3', 'Text source', 'Text'], sk: sk('grid-template-columns:repeat(3,1fr)', 'border-top:3px solid #BE3A2B', 'border-top:3px solid #E8A013', 'border-top:3px solid #3B5BDB'), cols: 'repeat(3,minmax(0,1fr))', ph: [['RAID card', 'raid'], ['RAID card', 'raid'], ['RAID card', 'raid']] },
    { id: 'raid-4', name: 'RAID cards, four', kind: 'raid', fit: ['Full'], d: 'Four shorter cards: good for “this week’s actions” or “decisions needed”.', els: ['Heading', 'RAID card ×4'], sk: sk('grid-template-columns:repeat(4,1fr)', 'border-top:3px solid #BE3A2B', 'border-top:3px solid #E8A013', 'border-top:3px solid #E8A013', ''), cols: 'repeat(4,minmax(0,1fr))', ph: [['RAID card', 'raid'], ['RAID card', 'raid'], ['RAID card', 'raid'], ['RAID card', 'raid']] },
    { id: 'wi-list', name: 'Work items list', kind: 'raid', fit: ['Full', 'Half'], d: 'Live rows from Work items, chosen by a filter: open actions due soon, red risks, decisions needed.', els: ['Heading', 'Filter (set in Edit)', 'Work item list · live', 'Caption (optional)'], sk: sk('grid-template-rows:repeat(4,1fr)', 'width:90%', 'width:75%', 'width:85%', 'width:70%'), cols: '1fr', ph: [['Filter (set in Edit)', 'filter'], ['Work item list · live', 'list'], ['Caption (optional)', 'caption']] },   /* "it's capable of being half or full and it allows you to present work items" */
    { id: 'needs', name: 'Needs from you', kind: 'raid', fit: ['Full', 'Half'], live: true, d: 'What you need from the client: decisions, information and dates, each with an owner and a due date. Live from pending decisions and items marked “Needed from the client”, plus lines you add. It works now, is published straight after At a glance, and is left out when empty.', els: ['Heading', 'Pending decisions · live', 'Items for the client to act on · live', 'Lines added by hand', 'Quiet line when nothing is needed'], sk: sk('grid-template-rows:repeat(3,1fr)', 'border-left:3px solid #E8A013', 'border-left:3px solid #E8A013;width:80%', 'width:55%'), cols: '1fr', ph: [] },
    { id: 'docs', name: 'Documents and links', kind: 'files', fit: ['Full', 'Half'], d: 'The papers that go with this week’s report.', els: ['Heading', 'File (one or more)', 'Link list'], sk: sk('grid-template-rows:repeat(3,1fr)', '', '', ''), cols: '1fr', ph: [['File (one or more)', 'file'], ['Link list', 'link']] },
    { id: 'callout', name: 'Callout', kind: 'notes', fit: ['Half', 'Full'], d: 'One thing the reader must see.', els: ['Heading', 'Callout · decision'], sk: sk('', 'background:#FCEFCF;border-left:3px solid #E8A013'), cols: '1fr', ph: [['Callout', 'callout']] },
    { id: 'image-caption', name: 'Image with caption', kind: 'text', fit: ['Half', 'Full'], d: 'One picture beside text.', els: ['Heading', 'Image', 'Caption'], sk: sk('grid-template-rows:2fr 1fr', 'background:#B9C8FF', 'width:50%'), cols: '1fr', ph: [['Image', 'image'], ['Caption', 'caption']] },
    { id: 'quote', name: 'Quote', kind: 'text', fit: ['Half', 'Full'], d: 'A voice from the business.', els: ['Heading', 'Text (quote)', 'Person'], sk: sk('grid-template-rows:2fr 1fr', 'border-left:3px solid #4FD1E8', 'width:40%'), cols: '1fr', ph: [['Text (quote)', 'quote'], ['Person', 'person']] },
    { id: 'contacts', name: 'Contacts', kind: 'people', fit: ['Half', 'Full'], d: 'Who to ask.', els: ['Heading', 'Person', 'Person', 'Person'], sk: sk('grid-template-rows:repeat(3,1fr)', 'width:70%', 'width:70%', 'width:70%'), cols: '1fr 1fr', ph: [['Person', 'person'], ['Person', 'person'], ['Person', 'person']] },
    { id: 'checklist', name: 'Checklist', kind: 'people', fit: ['Half', 'Full'], d: 'Next steps or readiness, ticked off.', els: ['Heading', 'Checklist · linked to work items'], sk: sk('grid-template-rows:repeat(3,1fr)', 'width:80%', 'width:60%', 'width:70%'), cols: '1fr', ph: [['Checklist', 'checklist']] },
    { id: 'dates', name: 'Key dates', kind: 'people', fit: ['Half', 'Full'], d: 'What’s coming, from the milestones.', els: ['Heading', 'Date (from milestones)'], sk: sk('grid-template-rows:repeat(3,1fr)', 'width:90%', 'width:90%', 'width:90%'), cols: '1fr', ph: [['Date (from milestones)', 'date'], ['Date (from milestones)', 'date']] },
    { id: 'one-doc', name: 'One document', kind: 'files', fit: ['Half', 'Full'], d: 'A single file to read.', els: ['Heading', 'File', 'Text'], sk: sk('grid-template-rows:1fr 1fr', '', 'width:70%'), cols: '1fr', ph: [['File', 'file'], ['Text', 'text']] },
  ];
  C.templates = TPL;
  const TP_HINT = { text: 'Say what matters here', filter: 'Choose the rows: type, status, due, owner, workstream', list: 'Rows from Work items appear here, live', caption: 'One line under it', button: 'Button label and link', figure: 'Number, label and change', raid: 'Pick a work item', table: 'Type rows and columns, or paste from Excel', link: 'Paste a web address', callout: 'Information, a decision needed or a warning', person: 'Pick a person from the project', checklist: 'Add the first step', date: 'Type a date, or take one from a milestone', quote: 'A short quote from the business' };
  /* an added template is empty until it is filled in (a later release, #96): drawn as dashed drop areas with each element's name, and left out of the published page */
  C.onPage = s => !s.hidden && s.type !== 'tpl';
  function tplHtml(s) {
    const T = TPL.find(t => t.id === s.kind); if (!T) return '<p class="muted">This template is not available.</p>';
    const el = ([n, k, span]) => `<div class="tp-el tp-${k}${k === 'image' || k === 'file' ? ' tp-drop' : ''}"${span ? ' style="grid-column:1/-1"' : ''}><span class="tp-tag">${esc(n)}</span>${k === 'image' ? `${C.icon('image')}<span>Drop an image, paste, or browse</span>` : k === 'file' ? `${C.icon('doc')}<span>Drop a document</span>` : `<span class="tp-h">${esc(TP_HINT[k] || '')}</span><i class="tp-ln"></i>${k === 'caption' || k === 'button' || k === 'date' ? '' : '<i class="tp-ln s"></i>'}`}</div>`;
    return `<div class="tp" data-tpl="${esc(T.id)}" style="grid-template-columns:${T.cols}">${T.ph.map(el).join('')}</div><p class="note">This is the “${esc(T.name)}” template, still empty. Filling in its parts comes in a later release; until then it is left out of the published page.</p>`;
  }
  /* ── Needs from you (FR-12b, #121, #144): what the programme manager needs from the client. Live from the open client-visible items that are
     pending decisions or marked "Needed from the client", plus lines added by hand in the section (what, owner, due). Each line says what,
     who and by when; a late one says "Overdue" in words, not by colour alone. A hand-added line is archived, never deleted (FR-43c) ── */
  C.needsList = p => D.S.items.filter(x => x.code === p.code && C.isOpen(x) && x.client === true && !x.archived && ((x.type === 'D' && x.status === 'Pending') || x.clientAct))   /* the eye decides, as everywhere (FR-82): an item hidden from the client is never listed */.sort((a, b) => (a.due || '9').localeCompare(b.due || '9'));
  const needsSec = (p, s) => s || (p.report.sections || []).find(x => x.type === 'needs') || {};
  /* the lines in the order they are drawn, soonest first: { src: 'item', x } or { src: 'ask', a } */
  C.needsRows = (p, s) => [...C.needsList(p).map(x => ({ src: 'item', x, due: x.due })), ...(needsSec(p, s).asks || []).filter(a => !a.archived).map(a => ({ src: 'ask', a, due: a.due }))].sort((u, v) => (u.due || '9').localeCompare(v.due || '9'));
  C.ND_NOONE = 'Not assigned yet';   /* a line with no owner says so plainly */
  C.needsDue = iso => { if (!iso) return 'No date set'; const late = D.days(iso) < 0; return `Needed by ${D.fd(iso)}${late ? ` <b class="tag od">Overdue</b> ${C.dueWords(iso)}` : ''}`; };
  /* on the published page the section sits straight after At a glance, and is left out when there is nothing to ask */
  C.onPub = (s, p) => C.onPage(s) && (s.type !== 'needs' || C.needsRows(p || P(), s).length > 0);
  C.pubOrder = secs => {
    const a = secs.map(s => ({ ...s })), nd = a.filter(s => s.type === 'needs'); if (!nd.length) return a;
    a.forEach((s, i) => { if (s.beside && a[i + 1] && a[i + 1].type === 'needs') delete s.beside; }); nd.forEach(s => delete s.beside);
    const rest = a.filter(s => s.type !== 'needs'), g = rest.findIndex(s => s.type === 'glance'); if (g < 0) return [...nd, ...rest];
    const at = rest[g].beside && rest[g + 1] ? g + 2 : g + 1; rest.splice(at, 0, ...nd); return rest;
  };
  C.needsHtml = (editing, pub, s0) => {
    const p = P(), s = needsSec(p, s0), rows = C.needsRows(p, s), gone = (s.asks || []).filter(a => a.archived), sid = esc(s.id || '');
    const row = r => {
      if (r.src === 'ask') { const a = r.a, late = a.due && D.days(a.due) < 0;
        return `<li class="wl-row nd-ask${late ? ' od' : ''}" data-ask="${esc(a.id)}"><span class="wl-state">${C.pill(['b', 'Needed'])}</span>
        <span class="wl-main"><span class="wl-title"><span class="tag">Asked</span> ${esc(a.what)}</span><span class="wl-meta"><span class="av">${C.initials(a.owner)}</span>${esc(a.owner || C.ND_NOONE)}<span class="dot">·</span><span class="${late ? 'late' : ''}">${C.needsDue(a.due)}</span></span></span>
        <span class="wl-id">${editing ? `<button type="button" class="btn sm quiet" data-nd-arch="${sid}:${esc(a.id)}" aria-label="Archive ${esc(a.what)}">Archive</button>` : ''}</span></li>`; }
      const x = r.x, late = x.due && D.days(x.due) < 0, what = !editing && x.clientText ? C.plain(x.clientText) : x.title;
      return `<li class="wl-row${late ? ' od' : ''}" data-row="${x.id}"><span class="wl-state">${C.pill(C.look(x))}</span>
        <span class="wl-main"><span class="wl-title"><span class="tag">${x.type === 'D' ? 'Decision' : D.TYPES[x.type]}</span> ${esc(what)}</span><span class="wl-meta"><span class="av">${C.initials(x.owner)}</span>${esc(x.owner || C.ND_NOONE)}<span class="dot">·</span><span class="${late ? 'late' : ''}">${C.needsDue(x.due)}</span></span></span>
        <span class="wl-id"><button class="idl" data-open="${x.id}" aria-label="Open ${x.id}">${x.id}</button></span></li>`; };
    const list = rows.length ? `<ul class="wl needs">${rows.map(row).join('')}</ul>` : `<p class="muted nd-none">Nothing needed from you this week.</p>`;
    if (!editing) return list;
    const add = `<form class="nd-add" data-nd-add="${sid}" autocomplete="off" novalidate><label><span class="k">What is needed</span><input name="what" type="text" placeholder="A decision, some information or a date" aria-describedby="nd-err-${sid}"></label><label><span class="k">Owner</span><input name="owner" type="text" placeholder="Who on the client side"></label><label><span class="k">Due</span><input name="due" type="hidden" value=""><button type="button" class="nd-due" data-nd-due aria-label="Due: no date set. Choose a date">${C.icon('cal', 's')}<span>No date set</span></button></label><button type="submit" class="btn sm">${C.icon('plus', 's')} Add</button><p class="nd-err" id="nd-err-${sid}" role="alert" hidden>Say what is needed, then press Add.</p></form>`;
    const arch = gone.length ? `<details class="nd-arch"><summary>Archived (${gone.length})</summary><ul class="nd-arch-l">${gone.map(a => `<li><span>${esc(a.what)}</span><span class="muted">${esc(a.owner || C.ND_NOONE)} · ${a.due ? D.fd(a.due) : 'No date set'}</span><button type="button" class="link" data-nd-back="${sid}:${esc(a.id)}">Restore</button></li>`).join('')}</ul></details>` : '';
    return `${list}${add}${arch}<p class="note">Live: open pending decisions and items marked “Needed from the client”, if the client can see them, plus the lines you add here. On the published page it sits straight after At a glance, and it is left out when there is nothing to ask.</p>`;
  };
  function secHtml(s, i, r, editing) {
    const p = P(), out = s.hidden;
    if (out && !editing) return '';
    /* the section control (#101, option A): a grip with a + under it, in the margin at the card's left; faint until the pointer or the keyboard is on the section */
    const ctl = editing ? `<div class="sh-ctl"><button type="button" class="ib sh-b sh-grip" data-drag="${s.id}" data-opts="${s.id}" aria-haspopup="menu" aria-label="Move or change ${esc(s.title)}" title="Drag to move · click for options">${C.icon('drag', 's')}</button><button type="button" class="ib sh-b sh-add" data-addbelow="${s.id}" aria-label="Add a template below ${esc(s.title)}" title="Add a template below">${C.icon('plus', 's')}</button>${out ? `<span class="sh-off" role="img" aria-label="Left out of the published page" title="Left out of the published page">${C.icon('eyeoff', 's')}</span>` : ''}</div>` : '';
    const title = editing ? `<span class="st-t" contenteditable="plaintext-only" data-title="${s.id}" role="textbox" aria-label="Section title" spellcheck="true">${esc(s.title)}</span>` : `<span>${esc(s.title)}</span>`;
    let tools = '', body = '';
    if (s.type === 'current') body = editing ? `<div class="cs-inl" data-cs></div>` : `<div class="prose">${p.current || '<p class="muted">Nothing recorded.</p>'}</div>`;
    else if (s.type === 'glance') {
      body = glanceHtml(p, r, editing);
    } else if (s.type === 'usecases') {
      tools = editing ? C.addBtn('data-uc-add', 'Add use case') : `<button class="ib tip" data-uc-export aria-label="Export the use cases to Excel" data-tip="Export the use cases to Excel">${C.icon('dl', 's')}</button>`;
      body = ucTableHtml(p, editing) + C.ucMoreHtml(p);   /* the line to the Use Cases page: the editor only, never the published page */
    } else if (s.type === 'milestones') {
      const hid = C.mss().filter(m => !m.client).length;
      body = `${C.msViewsHtml(C.mss().filter(m => m.client), 'dash')}${msDetailsHtml(C.mss().filter(m => m.client), editing, 'dash')}${editing && hid ? `<button class="link add-from" data-msback>+ Add a milestone from your project record (${hid})</button>` : ''}`;
    } else if (s.type === 'text') body = editing ? `<div class="txt-inl" data-txt="${s.id}"></div>` : `<div class="prose">${s.html || '<p class="muted">Nothing recorded.</p>'}</div>`;
    else if (s.type === 'raid' || s.type === 'actions' || s.type === 'decisions') body = itemTableHtml(s.type, editing);
    else if (s.type === 'docs') body = docsHtml(p, editing);
    else if (s.type === 'needs') body = C.needsHtml(editing, false, s);
    else if (s.type === 'tpl') body = tplHtml(s);
    return `<section class="sec${out ? ' out' : ''}${s.type === 'tpl' ? ' sec-tpl' : ''}" id="sec-${s.id}" data-sec="${s.id}" data-i="${i}">${ctl}<h2 class="st">${title}${s.type === 'tpl' ? '<span class="tp-tag" aria-hidden="true">Heading</span>' : ''}<span class="sp"></span>${tools}</h2>${body}</section>`;
  }
  /* report work items as list rows (no boxed tables): a state pill, the item, a quiet line of who and when, the ID on the right.
     In Edit mode every part edits in place, and the last row adds a new item ("Owner: what it is", then Enter). */
  C.itemListHtml = (type, editing) => itemTableHtml(type, editing);
  function itemTableHtml(type, editing) {
    const all = C.items().filter(ITEMS_OF[type]).filter(x => type === 'decisions' ? (x.status === 'Pending' || (x.due && D.days(x.due) >= -14)) : C.isOpen(x)).sort((a, b) => (a.due || '9').localeCompare(b.due || '9'));
    const shown = all.filter(x => x.client);
    const ce = (x, f, v, lab, ph) => editing ? `<span class="cell-ce" contenteditable="plaintext-only" data-ce="${x.id}" data-f="${f}" role="textbox" aria-label="${lab} of ${x.id}" data-ph="${ph || ''}">${esc(v)}</span>` : esc(v || ph || '');
    const state = x => { const [c, t] = C.look(x); return editing ? `<button class="pill ${c} cell-pill" data-cst="${x.id}" aria-label="Status of ${x.id}: ${t}. Change">${esc(t)}</button>` : `<span class="pill ${c}">${esc(t)}</span>`; };
    const when = x => { const lab = type === 'decisions' ? 'Decided' : type === 'raid' ? 'Review' : 'Due'; const t = x.due ? `${lab} ${D.fd(x.due)}${type === 'actions' ? ` · <span class="${D.days(x.due) < 0 ? 'late' : ''}">${C.dueWords(x.due)}</span>` : ''}` : 'No date';
      return editing ? `<button class="cell-btn" data-cdue="${x.id}" aria-label="Date of ${x.id}: ${D.fd(x.due) || 'none'}. Change">${t}</button>` : `<span>${t}</span>`; };
    const prio = x => type !== 'raid' ? '' : editing ? `<button class="cell-btn" data-cpr="${x.id}" aria-label="Priority of ${x.id}: ${x.priority}. Change"><span class="prio ${x.priority}">${x.priority}</span></button>` : `<span class="prio ${x.priority}">${x.priority}</span>`;
    const word = { raid: 'a risk', actions: 'an action', decisions: 'a decision' }[type];
    return `<ul class="wl">${shown.map(x => `<li class="wl-row" data-row="${x.id}">
        <span class="wl-state">${state(x)}</span>
        <span class="wl-main"><span class="wl-title">${type === 'raid' ? `<span class="tag">${x.type === 'I' ? 'Issue' : 'Risk'}</span> ` : ''}${ce(x, 'title', type !== 'decisions' && !editing && x.clientText ? C.plain(x.clientText) : x.title, 'Title')}</span>
          <span class="wl-meta"><span class="av">${C.initials(x.owner)}</span>${ce(x, 'owner', x.owner, 'Owner', 'No owner')}<span class="dot">·</span>${when(x)}${prio(x) ? `<span class="dot">·</span>${prio(x)}` : ''}</span>
          ${type === 'raid' ? `<span class="wl-resp">${editing ? ce(x, 'update', C.plain(x.update), 'Response', 'Add the response') : esc(C.plain(x.update))}</span>` : ''}</span>
        <span class="wl-id"><button class="idl" data-open="${x.id}" aria-label="Open ${x.id}">${x.id}</button>${editing ? `<button class="ib" data-eye="${x.id}" aria-label="Take ${x.id} off the page" title="Take off the page">${C.icon('eye', 's')}</button>` : ''}</span></li>`).join('')}
      ${editing ? `<li class="wl-add"><input class="add-in" data-add="${type}" placeholder="+ Add ${word}: type “Owner: what it is”, then Enter" aria-label="Add ${word}"></li>` : ''}</ul>
      ${!shown.length && !editing ? '<p class="muted">Nothing to show this week.</p>' : ''}
      ${editing ? `<p class="note">Showing ${shown.length} of ${all.length}. Select any part to change it; the ID opens the full item; the eye takes it off the page.</p>${all.length > shown.length ? `<button class="link add-from" data-addfrom="${type}">+ Add from your project record (${all.length - shown.length})</button>` : ''}` : ''}`;
  }
  C.docsHtml = (p, editing) => docsHtml(p, editing);
  function docsHtml(p, editing) {
    /* a document link is archived, never deleted (FR-43c, #166): Archive in its menu takes it off the list and the published page; Archived under the list brings it back with Restore */
    const docs = (p.docs || []).filter(d => !d.hidden && !d.archived), hid = (p.docs || []).filter(d => d.hidden && !d.archived).length, gone = (p.docs || []).filter(d => d.archived);
    const arch = editing && gone.length ? `<details class="nd-arch doc-arch"><summary>Archived (${gone.length})</summary><ul class="nd-arch-l">${gone.map(d => `<li><span>${esc(d.title)}</span><span class="muted">Archived · ${esc(d.kind)} · ${D.fd(d.date)}</span><button type="button" class="link" data-doc-back="${esc(d.id)}">Restore</button></li>`).join('')}</ul></details>` : '';
    return (docs.length ? `<ul class="docs">${docs.map(d => `<li class="${d.hidden ? 'out' : ''}"><span class="dic">${C.icon('doc', 's')}</span><span><a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.title)}</a><div class="dm">${esc(d.kind)} · ${D.fd(d.date)}</div></span>
      ${editing ? `<button class="ib" data-doc-eye="${d.id}" aria-label="${d.hidden ? 'Show' : 'Hide'} ${esc(d.title)}">${C.icon(d.hidden ? 'eyeoff' : 'eye', 's')}</button><button class="ib" data-doc-more="${d.id}" aria-label="${esc(d.title)}: options">${C.icon('more', 's')}</button>` : `<a class="ib" href="${esc(d.url)}" target="_blank" rel="noopener" aria-label="Open ${esc(d.title)}">${C.icon('ext', 's')}</a><span></span>`}</li>`).join('')}</ul>`
      : '<p class="muted">No documents yet.</p>') + (editing ? `<button class="link add-from" data-doc-add>+ Add a document link</button>${hid ? ` <button class="link add-from" data-docback>+ Add back a document (${hid})</button>` : ''}${arch}` : '');
  }
  /* the use case summary, option D2: a summary strip (counts and a small meter), then one slim row per use
     case: an ID tag, the name, the headline on one line, the status as a coloured word in an aligned column, the open steps.
     Selecting a row opens its detail in place. */
  const UC_WORD = s => `<span class="ucw ${UC_CLS[s] || 'n'}">${esc(s)}</span>`;
  C.ucWord = UC_WORD;
  C.ucTableHtml = (p, editing) => ucTableHtml(p, editing);
  function ucTableHtml(p, editing) {
    const ucs = D.S.usecases.filter(u => u.code === p.code && u.client), hiddenN = D.S.usecases.filter(u => u.code === p.code && !u.client).length, openId = C.store.get('ucOpen', '');
    const back = editing && hiddenN ? `<button class="link add-from" data-ucback>+ Add a use case from your project record (${hiddenN})</button>` : '';
    if (!ucs.length) return `<p class="muted">No use cases on the page.${editing ? '' : ' Add one in Edit mode, or import them from Excel (a Use cases sheet).'}</p>${back}`;
    const n = s => ucs.filter(u => u.status === s).length, order = ['On track', 'Flag', 'High risk'].filter(s => n(s));
    const strip = `<div class="uc-strip"><span class="uc-total"><b>${ucs.length}</b> use case${ucs.length > 1 ? 's' : ''}</span>${order.map(s => `<span class="uc-count">${UC_WORD(s)}<b>${n(s)}</b></span>`).join('')}<span class="uc-meter" aria-hidden="true">${order.map(s => `<i class="${UC_CLS[s]}" style="flex:${n(s)}"></i>`).join('')}</span></div>`;
    return `${strip}<div class="ucl">${ucs.map(u => {
      const steps = C.items().filter(x => x.uc === u.id && C.isOpen(x) && (editing || x.client)), isOpen = openId === u.key, K = esc(u.key), titles = u.title.split('\n'), refs = (u.ref || u.id).split(/,| and /).map(x => x.trim()).filter(Boolean);
      return `<div class="ucr${u.client ? '' : ' out'}${isOpen ? ' open' : ''}" data-uc="${K}" role="button" tabindex="0" aria-expanded="${isOpen}" aria-label="Use case ${esc(u.ref || u.id)}: ${esc(titles[0])}, ${esc(u.status)}">
        ${editing ? `<button class="ib uc-eye" data-uc-eye="${K}" aria-label="Take ${esc(u.id)} off the page">${C.icon('eye', 's')}</button>` : ''}
        <span class="uc-tag">${refs.map(esc).join(' + ')}</span>
        <span class="uc-name">${esc(titles.join(' · '))}</span>
        ${editing ? `<span class="uc-head" contenteditable="plaintext-only" data-uc-head="${K}" role="textbox" aria-label="Headline for ${esc(u.id)}">${esc(u.headline)}</span>` : `<span class="uc-head" title="${esc(u.headline)}">${esc(u.headline)}</span>`}
        <span class="uc-st">${editing ? `<button class="ucw-btn" data-uc-status="${K}" aria-label="Status: ${esc(u.status)}. Change">${UC_WORD(u.status)}</button>` : UC_WORD(u.status)}</span>
        <span class="uc-steps">${steps.length ? `${steps.length} next step${steps.length > 1 ? 's' : ''}` : 'No open steps'}</span>
      </div>
      <div class="ucd${isOpen ? ' open' : ''}" data-ucd="${K}"><div class="ucd-in"><div>
          ${editing ? `<div class="ucd-h"><h3>Use case ${esc(u.ref || u.id)}: <span contenteditable="plaintext-only" data-uc-title="${K}" role="textbox" aria-label="Use case name">${esc(titles[0])}</span></h3></div>` : ''}
          <div class="ucd-cols"><div><div class="ucd-lab">Where it stands</div>${editing ? `<div class="ucd-std" data-uc-std="${K}"></div>` : `<div class="prose">${u.standing || '<p class="muted">Not written yet.</p>'}</div>`}</div>
          <div><div class="ucd-lab">Next steps · ${steps.length}</div><ul class="ucd-steps">${steps.map(x => editing ? `<li><b><span contenteditable="plaintext-only" data-ce="${x.id}" data-f="owner" role="textbox" aria-label="Owner of ${x.id}">${esc(x.owner || 'No owner')}</span>:</b> <span contenteditable="plaintext-only" data-ce="${x.id}" data-f="title" role="textbox" aria-label="Next step ${x.id}">${esc(x.title)}</span> <button class="link" data-open="${x.id}">${x.id}</button><span class="muted">${x.due ? ' · due ' + D.fd(x.due) : ''}</span></li>`
            : `<li><b>${esc(x.owner || 'No owner')}:</b> ${esc(x.title.charAt(0).toLowerCase() + x.title.slice(1))} <button class="link" data-open="${x.id}">${x.id}</button><span class="muted">${x.due ? ' · due ' + D.fd(x.due) : ''}</span></li>`).join('')}
            ${editing ? `<li class="addli"><input class="add-in" data-uc-step="${K}" placeholder="+ Add a next step: “Owner: what it is”, then Enter" aria-label="Add a next step"></li><li class="addli"><button class="link" data-uc-link="${K}">+ Link an existing work item</button></li>` : ''}</ul></div></div>
          <div class="ucd-acts"><button class="link" data-uc-work="${esc(u.id)}">See all ${C.items().filter(x => x.uc === u.id).length} work items for ${esc(u.ref || u.id)} ›</button>${editing ? `<span style="flex:1"></span><button class="btn sm danger" data-uc-del="${K}">Delete use case</button>` : ''}</div>
      </div></div></div>`;
    }).join('')}</div>${back}`;
  }
  /* "On this page": the contents rail beside the report (a scroll-progress line, the current section, counts) */
  C.tocCounts = (p, s) => {
    const its = D.S.items.filter(x => x.code === p.code && x.client && !x.archived);
    if (s.type === 'actions') { const o = its.filter(x => x.type === 'A' && C.isOpen(x)); const l = o.filter(x => x.due && D.days(x.due) < 0).length; return l ? `${l} late` : `${o.length}`; }
    if (s.type === 'raid') { const o = its.filter(x => (x.type === 'R' || x.type === 'I') && C.isOpen(x)); const red = o.filter(x => C.ragOf(x) === 'R').length; return red ? `${red} red` : `${o.length}`; }
    if (s.type === 'decisions') { const n = its.filter(x => x.type === 'D' && x.status === 'Pending').length; return n ? `${n} pending` : ''; }
    if (s.type === 'milestones') { const n = D.S.milestones.filter(m => m.code === p.code && m.client && !m.archived && !m.achievedOn && D.slip(m) > 0).length; return n ? `${n} slipped` : ''; }
    if (s.type === 'usecases') { const n = D.S.usecases.filter(u => u.code === p.code && u.client && u.status !== 'On track').length; return n ? `${n} flagged` : ''; }
    if (s.type === 'docs') { const n = (p.docs || []).filter(d => !d.hidden && !d.archived).length; return n ? `${n}` : ''; }
    if (s.type === 'needs') { const n = C.needsRows(p, s).length; return n ? `${n} needed` : ''; }
    return '';
  };
  /* a discreet minimap at the right edge: one short line per section, the current one longer and darker, a warm line where
     something needs a look; pointing at it (or Tab to it) opens the list (the Notion and "Subtle TOC" pattern) */
  C.tocHtml = (p, secs) => `<nav class="toc" aria-label="On this page" tabindex="0"><div class="toc-lines" aria-hidden="true">${secs.map(s => { const n = C.tocCounts(p, s); return `<i data-tl="${s.id}" class="${/late|red|slipped|flagged|pending|needed/.test(n) ? 'hot' : ''}"></i>`; }).join('')}</div>
    <button type="button" class="toc-btn" aria-expanded="false" aria-controls="toc-card"><svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M2 4h12M2 8h12M2 12h8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" fill="none"/></svg>On this page</button>
    <div class="toc-card" id="toc-card"><div class="toc-h">On this page</div><ul>${secs.map(s => { const n = C.tocCounts(p, s); return `<li><a href="#sec-${s.id}" data-toc="${s.id}"><span>${esc(s.title)}</span>${n ? `<em class="${/late|red|slipped|flagged|pending|needed/.test(n) ? 'hot' : ''}">${n}</em>` : ''}</a></li>`; }).join('')}</ul><button class="toc-top" data-totop>Back to top ↑</button></div></nav>`;
  C.wireToc = (root = document) => {
    const links = C.$$('[data-toc]', root); if (!links.length) return;
    const secs = links.map(a => document.getElementById('sec-' + a.dataset.toc)).filter(Boolean), lines = C.$$('[data-tl]', root);
    const spy = () => { const y = innerHeight * .3; let cur = secs[0];
      secs.forEach(s => { if (s.getBoundingClientRect().top < y) cur = s; });
      const id = cur && cur.id.slice(4); links.forEach(a => a.classList.toggle('on', a.dataset.toc === id)); lines.forEach(l => l.classList.toggle('on', l.dataset.tl === id)); };
    links.forEach(a => a.addEventListener('click', e => { e.preventDefault(); const t = document.getElementById('sec-' + a.dataset.toc); t && t.scrollIntoView({ behavior: C.reduce ? 'auto' : 'smooth', block: 'start' }); }));
    C.$('[data-totop]', root)?.addEventListener('click', () => scrollTo({ top: 0, behavior: C.reduce ? 'auto' : 'smooth' }));
    /* the list opens while the pointer is over it or the keyboard is in it, and closes as soon as either leaves (and after a jump).
       At 1000 px and below the rail gives way to a compact "On this page" button (#141): a click, Enter or Space opens the same list,
       and Esc, a click outside, a jump or the focus leaving closes it; the pointer alone does not open it there */
    C._tocOff && C._tocOff(); C._tocOff = null;
    const toc = C.$('.toc', root), btn = toc && C.$('.toc-btn', toc);
    if (toc) { const narrow = matchMedia('(max-width: 1000px)'), still = toc.classList.contains('toc-static'); let inside = false, wanted = false;
      const set = () => { const open = narrow.matches ? wanted : !still && (inside || toc.contains(document.activeElement)); toc.classList.toggle('open', open); btn && btn.setAttribute('aria-expanded', String(narrow.matches && open)); };
      const shut = (back) => { wanted = false; set(); if (back && btn) btn.focus(); };
      const mode = () => { toc.tabIndex = narrow.matches ? -1 : 0; wanted = false; inside = false; set(); };
      toc.addEventListener('mouseenter', () => { inside = true; set(); }); toc.addEventListener('mouseleave', () => { inside = false; set(); });
      toc.addEventListener('focusin', set); toc.addEventListener('focusout', () => setTimeout(() => { if (narrow.matches && !toc.contains(document.activeElement)) wanted = false; set(); }, 0));
      btn && btn.addEventListener('click', () => { wanted = !wanted; set(); if (wanted) setTimeout(() => C.$('.toc-card a', toc)?.focus({ preventScroll: true }), 0); });
      toc.addEventListener('keydown', e => { if (e.key === 'Escape' && narrow.matches && wanted) { e.stopPropagation(); shut(true); } });
      C.$$('a, [data-totop]', toc).forEach(a => a.addEventListener('click', () => { inside = false; wanted = false; a.blur(); toc.blur(); set(); }));
      const outside = e => { if (wanted && !toc.contains(e.target)) shut(false); };
      document.addEventListener('pointerdown', outside, true); narrow.addEventListener('change', mode); mode();
      C._tocOff = () => { document.removeEventListener('pointerdown', outside, true); narrow.removeEventListener('change', mode); }; }
    removeEventListener('scroll', C._spy); C._spy = spy; addEventListener('scroll', spy, { passive: true }); spy();
  };

  /* ── Since the last report (FR-12c, #118): what changed after the last publication, worked out from history. For the author only: it is drawn in Edit
     and never put in the published page. A change that was made and then put back is left out. ── */
  C.lastPub = p => { const pubs = p.published || []; if (!pubs.length) return null; const i = pubs.length - 1; return { rec: pubs[i], n: D.pubNo(p, i), date: pubs[i].at.slice(0, 10) }; };
  C.sinceLast = p => {
    const lp = C.lastPub(p); if (!lp) return null;
    const after = h => lp.rec.hseq != null ? h.seq > lp.rec.hseq : D.whenIso(h) > lp.rec.at;
    const rows = D.S.history.filter(h => h.code === p.code && (h.kind === 'item' || h.kind === 'ms') && after(h)).sort((a, b) => a.seq - b.seq);
    const by = new Map(); rows.forEach(h => { const k = h.kind + '|' + h.id + '|' + h.field, g = by.get(k); if (g) g.to = h.to; else by.set(k, { kind: h.kind, id: h.id, field: h.field, from: h.from, to: h.to, seq: h.seq, text: h.text }); });
    const gone = new Set(rows.filter(h => h.field === '-').map(h => h.kind + '|' + h.id)), lines = [];
    const itemOf = id => D.S.items.find(x => x.id === id && x.code === p.code), msOf = id => D.S.milestones.find(m => m.id === id && m.code === p.code), kind = x => (D.TYPES[x.type] || 'item').toLowerCase();
    [...by.values()].sort((a, b) => a.seq - b.seq).forEach(g => {
      if (gone.has(g.kind + '|' + g.id) || g.from === g.to && g.field !== '+') return;
      if (g.kind === 'item') { const x = itemOf(g.id); if (!x) return; const t = x.title, add = (pre, post) => lines.push({ kind: 'item', id: g.id, pre, post, group: g.field === '+' ? 'Opened' : g.field });
        if (g.field === '+') add(`Opened ${kind(x)}`, `: ${t}`);
        else if (g.field === 'status') { if (x.type === 'D' && g.to === 'Made') add('Decision', ` made: ${t}`); else if (g.to === 'Closed' || g.to === 'Cancelled' || g.to === 'Withdrawn') add(`${g.to === 'Closed' ? 'Closed' : g.to}`, `: ${t}`); else if (g.from === 'Closed' || g.from === 'Cancelled') add('Reopened', `: ${t}`); else add('', ` status ${g.from} → ${g.to}`); }
        else if (g.field === 'due') add('', ` due ${D.fd(g.from) || 'no date'} → ${D.fd(g.to) || 'no date'}`);
        else if (g.field === 'owner') add('', ` owner ${g.from || 'none'} → ${g.to || 'none'}`); }
      else { const m = msOf(g.id); if (!m) return; const add = post => lines.push({ kind: 'ms', id: g.id, pre: 'Milestone', post: ` ${m.name}: ${post}`, group: 'Milestones' });
        if (g.field === '+') add('added');
        else if (g.field === 'agreed') add(`agreed date ${D.fd(g.from) || 'none'} → ${D.fd(g.to) || 'none'}`);
        else if (g.field === 'forecast') add(`forecast ${D.fd(g.from) || 'none'} → ${D.fd(g.to) || 'none'}`);
        else if (g.field === 'achievedOn') add(g.to ? `achieved on ${D.fd(g.to)}` : 'no longer marked achieved'); }
    });
    return { n: lp.n, date: lp.date, lines };
  };
  const sinceHtml = p => {
    const sl = C.sinceLast(p);
    if (!sl) return `<section class="card since" id="since" aria-label="Since the last report"><div class="card-h"><h2>Since the last report</h2><span class="tag">Only you see this</span></div><p class="muted">Not published yet, so there is nothing to compare with.</p></section>`;
    const L = sl.lines, show = L.slice(0, 40);
    return `<section class="card since" id="since" aria-label="Since the last report"><div class="card-h"><h2>Since the last report (Publication ${sl.n}, ${D.fd(sl.date)})</h2><span class="tag">Only you see this</span></div>
      ${L.length ? `<ul class="since-l">${show.map(l => `<li>${esc(l.pre)} <button class="link" ${l.kind === 'ms' ? 'data-since-ms' : 'data-open'}="${esc(l.id)}">${esc(l.id)}</button>${esc(l.post)}</li>`).join('')}</ul>${L.length > show.length ? `<p class="muted">and ${L.length - show.length} more</p>` : ''}` : `<p class="muted">Nothing has changed since Publication ${sl.n}.</p>`}
      <p class="note">Worked out from the change history: items opened and closed, status, due date and owner moves, milestone date moves and decisions made. It is never published.</p></section>`;
  };
  C.views.dashboard = {
    html() {
      const p = P(), r = rep(), editing = UI.editing;
      const B = window.BRAND || {}, week = p.week || D.friday();
      return `<div class="rbar"><div class="seg" role="group" aria-label="Mode"><button data-mode="view" aria-pressed="${!editing}" title="View (V)" aria-keyshortcuts="V">View</button><button data-mode="edit" aria-pressed="${editing}" title="Edit (E)" aria-keyshortcuts="E">${C.icon('pencil', 's')} Edit</button></div>
        <label class="muted" style="font-size:14px;display:flex;align-items:center;gap:8px">Week ending <input class="field" type="date" id="wk" value="${week}" style="width:auto"></label>
        <span class="state">${editing ? 'Editing · each change saves on its own' : (p.published || []).length ? `Published ${D.fd(p.published.slice(-1)[0].at.slice(0, 10))}${p.published.slice(-1)[0].client ? ' to the client' : ' locally'}` : 'Draft · not published yet'}</span>${editing && C.edHint ? '<span class="sh-hint" id="shHint">Drag to move, + to add a template</span>' : ''}<span class="sp"></span>${editing ? (() => { const lp = C.lastPub(p), kept = lp && D.pubCopy(p.code, lp.n); return `<button class="btn sm" id="startLast" ${kept ? '' : 'aria-disabled="true"'} title="${kept ? `Copy the text sections from Publication ${lp.n} (${D.fd(lp.date)})` : lp ? 'The copy of the last publication is no longer kept' : 'Publish once first: there is no last report to start from'}">Start from last week’s report</button>`; })() : ''}
        </div>
      ${editing ? sinceHtml(p) : ''}
      ${(() => { const lay = C.layOf(p), open = lay !== 'boxed', HN = { G: 'On track', A: 'At risk', R: 'Off track' };
        const wkLine = `<div class="wk"><b>WEEKLY REPORT</b> · Week ending ${C.dayName(week)} ${new Date(week + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}${p.client ? ' · for ' + esc(p.client) : ''}</div>`;
        const cover = lay === 'cover'
          ? `<header class="cover hero"><h1>${esc(p.name)}</h1>${wkLine}<p class="verdict"><b>${HN[p.health]}.</b> ${esc(p.reason).replace(/\n/g, ' ')}</p>${B.mark ? `<img class="mark" src="${B.mark}" alt="">` : ''}<div class="hero-tiles">${glanceHtml(p, r, editing)}</div></header>`
          : `<header class="cover"><h1>${esc(p.name)}</h1>${wkLine}${B.mark ? `<img class="mark" src="${B.mark}" alt="">` : ''}</header>`;
        const secs = r.sections.filter(s => !(open && s.type === 'glance'));
        const bodyHtml = C.secRows(secs, s => editing || C.onPage(s)).map(row => row.length > 1 ? `<div class="pair">${row.map(s => secHtml(s, r.sections.indexOf(s), r, editing)).join('')}</div>` : secHtml(row[0], r.sections.indexOf(row[0]), r, editing)).join('');
        const tocSecs = r.sections.filter(s => C.onPage(s) && !(open && s.type === 'glance'));
        if (lay === 'spine') return `<div class="lay-spine"><aside class="spine" aria-label="Project health and contents"><div class="spine-h">Project health</div>${glanceHtml(p, r, editing)}${C.tocHtml(p, tocSecs).replace('class="toc"', 'class="toc toc-static"')}</aside><article class="sheet open${editing ? ' editing' : ''}">${cover}<div class="sbody">${bodyHtml}</div></article></div>`;
        return `<div class="dash-wrap lay-${lay}"><article class="sheet${open ? ' open' : ''}${editing ? ' editing' : ''}">${cover}<div class="sbody">${bodyHtml}</div></article>${C.tocHtml(p, tocSecs)}</div>`;
      })()}`;
    },
    wire() {
      const p = P(), r = rep(), editing = UI.editing;
      C.$$('[data-mode]').forEach(b => b.addEventListener('click', () => { UI.editing = b.dataset.mode === 'edit';
        /* the first time in Edit (once per profile): the first grip and plus pulse once, and a one-line hint stays for the session (idea 8) */
        const first = UI.editing && !C.store.get('editHintSeen', false); if (first) { C.store.set('editHintSeen', true); C.edHint = true; }
        C.render(); if (first && !C.reduce) C.$('.sheet .sec > .sh-ctl')?.classList.add('first'); }));
      C.$$('[data-since-ms]').forEach(b => b.addEventListener('click', () => C.openMs(b.dataset.sinceMs)));
      C.$('#startLast')?.addEventListener('click', () => { const b = C.$('#startLast'), lp = C.lastPub(p), cp = lp && D.pubCopy(p.code, lp.n);
        if (!cp) return C.toast(lp ? 'The copy of the last publication is no longer kept.' : 'Publish once first: there is no last report to start from.');
        const secs = r.sections.filter(x => x.type === 'text' && x.id in (cp.texts || {}) && (x.html || '') !== cp.texts[x.id]);
        if (!secs.length) return C.toast(`The text sections already match Publication ${lp.n}.`);
        C.confirm(`Start from Publication ${lp.n}?`, `<p>The text of ${secs.map(x => esc(x.title)).join(', ')} is replaced with the text published on ${D.fd(lp.date)}. Nothing else changes. You can undo it.</p>`, 'Use that text', () => setRep(r2 => { r2.sections.forEach(x => { if (x.type === 'text' && x.id in cp.texts) x.html = cp.texts[x.id]; }); }, `Text carried forward from Publication ${lp.n}`)); });
      C.$('#wk').addEventListener('change', e => e.target.value && saveProject({ week: e.target.value }, 'Week ending changed'));
      /* project health: click the pill to change it; the reason is edited in place */
      const pickHealth = (v, t) => { const better = RANK[v] < RANK[C.healthSuggest(p).h]; saveProject({ health: v }, 'Health set to ' + t); if (better) setTimeout(() => { const r2 = C.$('#hReason'); if (r2) { r2.focus(); r2.select(); } }, 60); };   /* a better choice than the suggestion: the reason box is ready to be rewritten */
      C.$('#hPill')?.addEventListener('click', e => { e.stopPropagation(); C.menu(e.currentTarget, [['G', 'On track'], ['A', 'At risk'], ['R', 'Off track']].map(([v, t]) => ({ html: `<span class="hpill ${v}">${t}</span>`, selected: p.health === v, onPick: () => pickHealth(v, t) })), { select: true }); });
      C.$('#hUse')?.addEventListener('click', () => { const h = C.healthSuggest(p).h; saveProject({ health: h }, 'Health set to ' + HN_ALL[h]); });
      const rs = C.$('#hReason'); if (rs) { const fit = () => { rs.style.height = 'auto'; rs.style.height = rs.scrollHeight + 'px'; }; fit(); rs.addEventListener('input', fit);
        rs.addEventListener('change', () => { if (!rs.value.trim() && C.healthSuggest(p).better) { rs.value = p.reason; fit(); C.toast('A reason is needed when your health is better than the suggestion'); return; } saveProject({ reason: rs.value.trim() }, 'Reason saved'); }); rs.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); rs.value = p.reason; rs.blur(); } if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) rs.blur(); }); }
      /* every heading edits in place */
      C.$$('[data-title]').forEach(t => { const id = t.dataset.title, old = r.sections.find(s => s.id === id).title;
        t.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); t.blur(); } if (e.key === 'Escape') { e.stopPropagation(); t.textContent = old; t.blur(); } });
        t.addEventListener('blur', () => { const v = t.textContent.trim(); if (!v || v === old) { t.textContent = old; return; } setRep(r2 => { r2.sections.find(s => s.id === id).title = v; }, 'Heading changed'); }); });
      /* one editor everywhere: current state (no AI here) and the text sections */
      const cs = C.$('[data-cs]'); if (cs) C.inline(cs, { html: p.current, label: 'Current state', placeholder: 'Say where the project stands', place: 'current', onSave: h => { const u = D.change('project', p, { current: h }, D.who('in the report')); C.refresh(); u && C.toast('Current state saved', u); } });
      C.$$('[data-txt]').forEach(v => { const s = r.sections.find(x => x.id === v.dataset.txt);
        C.inline(v, { html: s.html, label: s.title, placeholder: /next week/i.test(s.title) || s.id === 'nextweek' ? 'Say what is planned for next week' : /this week/i.test(s.title) || s.id === 'thisweek' ? 'Say what matters this week' : 'Say what matters here', place: 'current', draft: () => C.draftText(p, s), onSave: h => setRep(r2 => { r2.sections.find(x => x.id === s.id).html = h; }, `${s.title} saved`) }); });
      /* tiles: open their list in either mode; reorder and hide in Edit mode */
      C.$$('[data-fig]').forEach(f => {
        const k = f.dataset.fig, g = C.glanceData(p)[k];
        f.addEventListener('click', e => { if (e.target.closest('[data-fig-eye],#hPill,#hReason')) return; g && g.go && g.go(); });
        f.addEventListener('keydown', e => { if (UI.editing && e.altKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) { e.preventDefault(); moveFig(k, e.key === 'ArrowLeft' ? -1 : 1); } else if (e.key === 'Enter' && e.target === f) g && g.go && g.go(); });
        if (UI.editing) {
          /* right-click: the tile's colour (automatic from the data, or set by hand) */
          f.addEventListener('contextmenu', e => { e.preventDefault(); const cur = (r.glance.find(x => x.k === k) || {}).rag || '';
            C.menu(f, [{ lab: 'Tile colour' }, ...[['', 'Automatic, from the data'], ['G', 'Green'], ['A', 'Amber'], ['R', 'Red'], ['N', 'No colour']].map(([v, t]) => ({ html: `<span class="swatch rag-${v || (g && g.rag) || 'N'}"></span>${t}`, selected: cur === v, onPick: () => setRep(r2 => { const fx = r2.glance.find(x => x.k === k); if (v) fx.rag = v; else delete fx.rag; }, v ? `Tile colour set to ${t.toLowerCase()}` : 'Tile colour automatic again') }))], { select: true }); });
          f.addEventListener('dragstart', e => { e.dataTransfer.setData('text/fig', k); e.dataTransfer.effectAllowed = 'move'; });
          f.addEventListener('dragover', e => { if ([...e.dataTransfer.types].includes('text/fig')) { e.preventDefault(); f.classList.add('drop'); } });
          f.addEventListener('dragleave', () => f.classList.remove('drop'));
          f.addEventListener('drop', e => { e.preventDefault(); f.classList.remove('drop'); const from = e.dataTransfer.getData('text/fig'); if (from && from !== k) setRep(r2 => { const a = r2.glance, i = a.findIndex(x => x.k === from), it = a.splice(i, 1)[0]; a.splice(a.findIndex(x => x.k === k), 0, it); }, 'Tile moved'); });
        }
      });
      C.$$('[data-fig-eye]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); const k = b.dataset.figEye; setRep(r2 => { const f = r2.glance.find(x => x.k === k); f.hidden = !f.hidden; }, 'Tile ' + (r.glance.find(x => x.k === k).hidden ? 'shown' : 'hidden')); }));
      // milestones
      const tl = C.$('[data-tl]'); if (tl) { const list = C.mss().filter(m => m.client); C.timeline(tl, list, { key: 'dash' }); wireMsList(tl.closest('.sec') || tl.parentElement, list, 'dash'); C.wireMsViews(tl.closest('.sec') || document, list); }
      // item tables and next steps: cells edit in place
      wireCells();
      C.$$('[data-open]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); C.openItem(b.dataset.open, C.$$('[data-open]').map(x => x.dataset.open)); }));
      /* a single click anywhere on a work item row, outside a field, button or link, opens its peek */
      C.$$('.wl-row[data-row]').forEach(r => r.addEventListener('click', e => { if (e.target.closest('[data-ce], [contenteditable], button, input, a, select, textarea') || String(getSelection()).trim()) return;
        C.openItem(r.dataset.row, C.$$('.wl-row[data-row]').map(x => x.dataset.row)); }));
      C.$$('[data-eye]').forEach(b => b.addEventListener('click', () => { const x = D.S.items.find(i => i.id === b.dataset.eye); C.hideLater(b.closest('[data-row]'), D.change('item', x, { client: false }, D.who('with the eye')), `${x.id} taken off the page`); }));
      C.$$('[data-addfrom]').forEach(b => b.addEventListener('click', () => addFrom(b.dataset.addfrom)));
      C.$$('[data-add]').forEach(i => i.addEventListener('keydown', e => { if (e.key !== 'Enter' || !i.value.trim()) return; e.preventDefault(); addInline(ADD_TYPE[i.dataset.add], i.value, { client: true }, `[data-add="${i.dataset.add}"]`); }));
      // documents
      C.$('[data-doc-add]')?.addEventListener('click', () => docForm(null));
      C.$$('[data-doc-eye]').forEach(b => b.addEventListener('click', () => { const id = b.dataset.docEye; const docs = D.clone(p.docs); docs.find(x => x.id === id).hidden = true; C.hideLater(b.closest('li'), D.change('project', p, { docs }, D.who('with the eye')), 'Document taken off the page'); }));
      C.$('[data-docback]')?.addEventListener('click', () => C.picker({ title: 'Add back a document', items: p.docs.filter(d => d.hidden).map(d => ({ id: d.id, title: d.title, meta: `${d.kind} · ${D.fd(d.date)}` })), onAdd: ids => { const docs = D.clone(p.docs); docs.forEach(d => { if (ids.includes(d.id)) d.hidden = false; }); saveProject({ docs }, 'Documents added back'); } }));
      C.$('[data-msback]')?.addEventListener('click', () => C.picker({ title: 'Add a milestone from your project record', items: C.mss().filter(m => !m.client).map(m => ({ id: m.id, title: m.name, meta: `${D.msState(m)} · ${D.fd(m.agreed)}` })), onAdd: ids => { const u = D.batch(ids.map(id => () => D.change('ms', C.mss().find(m => m.id === id), { client: true }, D.who('in the report')))); C.refresh(); C.toast(`${ids.length} milestone${ids.length > 1 ? 's' : ''} added to the page`, u); } }));
      C.$$('[data-doc-more]').forEach(b => b.addEventListener('click', e => { const id = b.dataset.docMore; C.menu(e.currentTarget, [{ html: `${C.icon('pencil', 's')} Edit`, onPick: () => docForm(p.docs.find(x => x.id === id)) }, { html: `${C.icon('archive', 's')} Archive`, onPick: () => docArch(id, true) }], { align: 'right' }); }));
      C.$$('[data-doc-back]').forEach(b => b.addEventListener('click', () => docArch(b.dataset.docBack, false)));
      wireUc(p);
      if (editing) wireSections(r);
      C.wireToc();
    },
  };
  /* V and E switch the Dashboard to View and Edit, unless the key is going into a box, an editor, a menu, a dialog, ask clark or a peek */
  document.addEventListener('keydown', e => {
    if (UI.view !== 'dashboard' || e.metaKey || e.ctrlKey || e.altKey || e.shiftKey || e.repeat || e.isComposing || (e.key !== 'v' && e.key !== 'V' && e.key !== 'e' && e.key !== 'E')) return;
    if (C.typing(document.activeElement) || (C.popOpen && C.popOpen()) || document.querySelector('dialog[open]') || UI.peek || (C.askIsOpen && C.askIsOpen()) || (C.edIsOpen && C.edIsOpen())) return;
    const b = C.$(`[data-mode=${e.key.toLowerCase() === 'e' ? 'edit' : 'view'}]`); if (!b) return; e.preventDefault(); b.click();
  });
  /* "Owner: what it is" → a new item; the same one path for every inline add */
  function addInline(type, text, extra, refocus) {
    const p = P(), m = /^\s*([^:]{2,40}):\s*(.+)$/.exec(text), owner = m ? m[1].trim() : '', title = (m ? m[2] : text).trim();
    const x = { id: C.nextId(type), code: p.code, type, ws: p.ws[0], title, owner, due: type === 'D' ? D.TODAY : D.addDays(D.TODAY, 7), status: D.STATUSES[type][0], priority: 'Medium', desc: '', update: '', updatedAt: D.stamp(), client: true, clientText: '', ms: '', uc: '', source: 'Added in the report', ...extra };
    const u = D.create('item', x, D.who('in the report')); C.refresh(); C.toast(`${x.id} added`, u);
    setTimeout(() => { C.changed(C.$(`[data-row="${x.id}"]`)); const i = refocus && C.$(refocus); i && i.focus(); }, 30);
    return x;
  }
  function wireCells() {
    C.$$('[data-ce]').forEach(el => { const x = D.S.items.find(i => i.id === el.dataset.ce), f = el.dataset.f, old = f === 'update' ? C.plain(x.update) : x[f] || '';
      el.addEventListener('click', e => e.stopPropagation());
      el.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); el.blur(); } if (e.key === 'Escape') { e.stopPropagation(); el.textContent = old; el.blur(); } });
      el.addEventListener('blur', () => { const v = el.textContent.trim(); if (v === old || (!v && f === 'title') || (f === 'owner' && v === 'No owner')) { el.textContent = old || (f === 'owner' ? 'No owner' : ''); return; }
        const u = D.change('item', x, { [f]: f === 'update' ? C.toHtml(v) : v }, D.who('in the report')); C.refresh(); C.toast(`${x.id} saved`, u); }); });
    /* the pill's menu offers what the pill shows: a risk or issue's rating (with Close or Reopen below), otherwise the status */
    C.$$('[data-cst]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); const x = D.S.items.find(i => i.id === b.dataset.cst);
      const set = (ch, msg) => { const u = D.change('item', x, ch, D.who('in the report')); C.refresh(); C.toast(msg, u); };
      if (x.type === 'R' || x.type === 'I') return C.menu(b, [{ lab: 'Rating' }, ...[['R', 'Red', 'r'], ['A', 'Amber', 'a'], ['G', 'Green', 'g']].map(([v2, t, c2]) => ({ html: `<span class="pill ${c2}">${t}</span>`, selected: C.ragOf(x) === v2 && C.isOpen(x), onPick: () => set(C.ragSet(x, v2), `${x.id} rated ${t}`) })),
        { sep: true }, C.isOpen(x) ? { html: `${C.icon('check', 's')} Close it`, onPick: () => set({ status: 'Closed' }, `${x.id} closed`) } : { html: `${C.icon('undo', 's')} Reopen it`, onPick: () => set({ status: 'Open' }, `${x.id} reopened`) }], { select: true });
      C.menu(b, D.STATUSES[x.type].map(s => ({ label: s, selected: x.status === s, onPick: () => set({ status: s }, `${x.id} set to ${s}`) })), { select: true }); }));
    C.$$('[data-cpr]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); const x = D.S.items.find(i => i.id === b.dataset.cpr);
      C.menu(b, D.PRIORITIES.map(s => ({ label: s, selected: x.priority === s, onPick: () => { const u = D.change('item', x, { priority: s }, D.who('in the report')); C.refresh(); C.toast(`${x.id} priority ${s}`, u); } })), { select: true }); }));
    C.$$('[data-cdue]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); const x = D.S.items.find(i => i.id === b.dataset.cdue);
      C.calPick(b, x.due, v => { const u = D.change('item', x, { due: v }, D.who('in the report')); C.refresh(); C.toast(v ? `${x.id} moved to ${D.fd(v)}` : `${x.id} has no date now`, u); }, { quick: [['Today', D.TODAY], ['Next week', D.addDays(D.TODAY, 7)], ['No date', '']] }); }));
  }
  function moveFig(k, d) { setRep(r2 => { const a = r2.glance, i = a.findIndex(x => x.k === k), j = Math.max(0, Math.min(a.length - 1, i + d)); a.splice(j, 0, a.splice(i, 1)[0]); }, 'Tile moved'); setTimeout(() => C.$(`[data-fig="${k}"]`)?.focus(), 30); }
  /* every layout change goes through here: tried on a copy first, and when nothing would change there is no step and no toast */
  function reflow(fn, msg, focusId) {
    const p = P(), cur = rep().sections, gl = s => C.layOf(p) !== 'boxed' && s.type === 'glance', t = D.clone(cur);
    if (!fn(t, gl) || JSON.stringify(t) === JSON.stringify(cur)) return false;
    setRep(r2 => { fn(r2.sections, gl); }, msg); if (focusId) setTimeout(() => C.$(`[data-drag="${focusId}"]`)?.focus(), 30); return true;
  }
  const secName = id => (rep().sections.find(s => s.id === id) || {}).title || '';
  function moveSec(id, dir) { reflow((a, g) => stepSec(a, g, id, dir), `${secName(id)} moved ${dir < 0 ? 'up' : 'down'}`, id); }
  /* ── the Add a section box (#96, #101): kinds on the left, the templates in the middle, a preview on the right. It opens set to put the new section below a chosen one ── */
  let tplSeq = 0;
  const skHtml = (t, big) => `<div class="sk${big ? ' big' : ''}" style="${t.sk[0]}">${t.sk[1]}</div>`;
  function addTemplate(afterId, tid, place) {
    const T = TPL.find(t => t.id === tid), p = P(), gl = s => C.layOf(p) !== 'boxed' && s.type === 'glance';
    const nid = (T.id === 'text' ? 't' : 'x') + Date.now().toString(36) + (tplSeq++), rows0 = C.secRows(rep().sections.filter(s => !gl(s))), k0 = rows0.findIndex(w => w.some(s => s.id === afterId)), nx0 = rows0[k0 + 1];
    C.store.set('tplRecent', [tid, ...C.store.get('tplRecent', []).filter(x => x !== tid)].slice(0, 4));
    setRep(r2 => {
      const rows = C.secRows(r2.sections.filter(x => !gl(x))), k = rows.findIndex(w => w.some(x => x.id === afterId)), row = rows[k] || [r2.sections[r2.sections.length - 1]], nx = rows[k + 1];
      const sec = T.id === 'text' ? { id: nid, type: 'text', title: 'New section', html: '' } : T.live ? { id: nid, type: T.id, title: T.name } : { id: nid, type: 'tpl', kind: T.id, title: T.name };   /* a live template is a section of its own type, drawn from the data and published */
      if (place === 'beside' && nx && nx.length === 1) { sec.beside = true; r2.sections.splice(r2.sections.indexOf(nx[0]), 0, sec); }
      else r2.sections.splice(r2.sections.indexOf(row[row.length - 1]) + 1, 0, sec);
      tidySecs(r2.sections, r2.sections.filter(x => !gl(x)));
    }, place === 'beside' && nx0 && nx0.length === 1 ? `${T.name} added beside ${nx0[0].title}` : `${T.name} added below ${secName(afterId)}`);
    /* the new section's heading is ready to rename */
    setTimeout(() => { const h = C.$(`[data-title="${nid}"]`); if (!h) return; h.focus(); const rg = document.createRange(); rg.selectNodeContents(h); const sl = getSelection(); sl.removeAllRanges(); sl.addRange(rg); }, 40);
  }
  function addDialog(afterId) {
    const p = P(), gl = s => C.layOf(p) !== 'boxed' && s.type === 'glance', rows = C.secRows(rep().sections.filter(s => !gl(s))), k = rows.findIndex(w => w.some(s => s.id === afterId));
    const next = rows[k + 1] && rows[k + 1].length === 1 ? rows[k + 1][0] : null;   /* #95's rules: beside only a section that is alone on its row */
    const recent = C.store.get('tplRecent', []).map(id => TPL.find(t => t.id === id)).filter(Boolean);
    let kind = 'all', q = '', sel = TPL[0].id, place = 'row', lastSel = sel;
    const shown = () => TPL.filter(t => (kind === 'all' || t.kind === kind) && (!q || [t.name, t.d, t.els.join(' '), KINDS.find(x => x[0] === t.kind)[1]].join(' ').toLowerCase().includes(q)));
    C.dialog(`<div class="atd" role="group" aria-labelledby="atdT"><div class="atd-h"><h2 id="atdT">Add a section</h2><label class="search"><span class="sr">Search templates</span>${C.icon('search')}<input id="atdQ" type="search" placeholder="Search templates" autocomplete="off" aria-controls="atdG"></label><button type="button" class="ib" data-close aria-label="Close">${C.icon('x')}</button></div>
      <div class="atd-b"><nav class="atd-k" id="atdK" aria-label="Kinds"></nav><div class="atd-g" id="atdG" role="listbox" aria-label="Templates"></div><aside class="atd-p" id="atdP" aria-live="polite"></aside></div>
      <div class="dlg-f atd-f"><button type="button" class="link" data-help>${C.icon('info', 's')} <span class="atd-long">About section templates</span><span class="atd-short">Help</span></button><span class="sp"></span><button type="button" class="btn quiet" data-close>Cancel</button><button type="button" class="btn pri" id="atdGo">Add section</button></div></div>`, d => {
      d.classList.add('atd-d'); d.addEventListener('close', () => d.classList.remove('atd-d'), { once: true });
      const qi = C.$('#atdQ', d), G = C.$('#atdG', d), cols = () => { const cs = C.$$('.atd-c', G); return cs.length ? Math.max(1, cs.filter(c => c.offsetTop === cs[0].offsetTop).length) : 1; };
      C.$('#atdK', d).innerHTML = `${[['all', 'All', TPL.length], ...KINDS.map(([id, n]) => [id, n, TPL.filter(t => t.kind === id).length])].map(([id, n, c]) => `<button type="button" data-k="${id}" aria-pressed="${id === kind}">${n}<i>${c}</i></button>`).join('')}
        <div class="lab" id="atdRL">Recently used</div>${recent.length ? recent.map(t => `<button type="button" data-r="${t.id}" aria-describedby="atdRL">${esc(t.name)}</button>`).join('') : '<span class="atd-none">None yet</span>'}`;
      const mark = focus => { C.$$('.atd-c', G).forEach(c => { const on = c.dataset.t === sel; c.setAttribute('aria-selected', on); c.tabIndex = on ? 0 : -1; if (on) { qi.setAttribute('aria-activedescendant', c.id); focus && c.focus(); c.scrollIntoView({ block: 'nearest' }); } }); prev(); };
      const prev = () => {
        const T = TPL.find(t => t.id === sel), P2 = C.$('#atdP', d); C.$('#atdGo', d).disabled = !T;
        if (!T) { P2.innerHTML = '<p class="muted">Pick a template to see what it holds.</p>'; return; }
        const half = T.fit.includes('Half'); if (place === 'beside' && !(next && half)) place = 'row';
        if (lastSel !== sel && !C.reduce) { P2.classList.remove('swap'); void P2.offsetWidth; P2.classList.add('swap'); } lastSel = sel;   /* the preview cross-fades when the selection moves (idea 10) */
        P2.innerHTML = `<h3>${esc(T.name)}</h3>${skHtml(T, true)}<p>${esc(T.d)}</p>
          <div><span class="atd-lab">Holds</span><div class="atd-els">${T.els.map(e => `<span>${esc(e)}</span>`).join('')}</div></div>
          <fieldset class="atd-place"><legend class="atd-lab">Where it goes</legend><label><input type="radio" name="atdPlace" value="row" ${place === 'row' ? 'checked' : ''}> On its own row</label>
            ${next ? `<label><input type="radio" name="atdPlace" value="beside" ${place === 'beside' ? 'checked' : ''} ${half ? '' : 'disabled'}> Beside “${esc(next.title)}” (half width)${half ? '' : ' <span class="muted">· full width only</span>'}</label>` : ''}</fieldset>
          <button type="button" class="link" data-help>${C.icon('info', 's')} See every template explained in Help</button>`;
        C.$$('[data-help]', P2).forEach(b => b.addEventListener('click', help)); C.$$('input[name=atdPlace]', P2).forEach(i => i.addEventListener('change', () => { place = i.value; }));
      };
      const grid = () => { const vs = shown(); if (!vs.some(t => t.id === sel)) sel = vs[0] ? vs[0].id : '';
        G.innerHTML = vs.length ? vs.map(t => `<div class="atd-c" role="option" id="atdC-${t.id}" data-t="${t.id}" aria-selected="false" tabindex="-1">${skHtml(t)}<b>${esc(t.name)}</b><span class="fit">${t.fit.map(f => `<em>${f}</em>`).join('')}</span></div>`).join('') : '<p class="muted atd-none">No template matches. Try another word, or choose All.</p>';
        C.$$('.atd-c', G).forEach(c => { c.addEventListener('click', () => { sel = c.dataset.t; mark(); }); c.addEventListener('dblclick', go); }); mark(); };
      const help = () => { d.close(); C.help.open('ref-section-templates'); };
      const go = () => { if (!sel) return; const t = sel, pl = place; d.close(); addTemplate(afterId, t, pl); };
      const move = (dx, focus) => { const vs = shown(); if (!vs.length) return; const i = Math.max(0, Math.min(vs.length - 1, vs.findIndex(t => t.id === sel) + dx)); sel = vs[i].id; mark(focus); };
      C.$$('[data-k]', d).forEach(b => b.addEventListener('click', () => { kind = b.dataset.k; C.$$('[data-k]', d).forEach(z => z.setAttribute('aria-pressed', z === b)); grid(); }));
      C.$$('[data-r]', d).forEach(b => b.addEventListener('click', () => { kind = 'all'; q = ''; qi.value = ''; C.$$('[data-k]', d).forEach(z => z.setAttribute('aria-pressed', z.dataset.k === 'all')); sel = b.dataset.r; grid(); }));
      C.$('[data-help]', d).addEventListener('click', help); C.$('#atdGo', d).addEventListener('click', go);
      qi.addEventListener('input', () => { q = qi.value.trim().toLowerCase(); grid(); });
      d.addEventListener('keydown', e => {
        if (e.altKey || e.metaKey || e.ctrlKey) return;
        const inQ = e.target === qi, onCard = !!e.target.closest('.atd-c');
        if (e.key === 'Enter' && (inQ || onCard || e.target.matches('input[type=radio]'))) { e.preventDefault(); go(); return; }
        const dx = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -cols(), ArrowDown: cols() }[e.key];
        if (dx && (onCard || (inQ && (e.key === 'ArrowUp' || e.key === 'ArrowDown' || !qi.value)))) { e.preventDefault(); move(dx, onCard); }
        else if ((e.key === 'Home' || e.key === 'End') && onCard) { e.preventDefault(); move(e.key === 'Home' ? -99 : 99, true); }
      });
      grid(); setTimeout(() => qi.focus(), 30);
    });
  }
  function wireSections(r) {
    const p = P(), gl = s => C.layOf(p) !== 'boxed' && s.type === 'glance', rowsOf = () => C.secRows(r.sections.filter(s => !gl(s)));
    const canStep = (id, dir) => stepSec(D.clone(r.sections), gl, id, dir), pairOf = id => rowsOf().find(row => row.some(s => s.id === id));
    C.$$('[data-opts]').forEach(b => b.addEventListener('click', e => {
      const id = b.dataset.opts, i = r.sections.findIndex(x => x.id === id), s = r.sections[i], row = pairOf(id) || [s], nxt = (() => { const d = rowsOf(), k = d.findIndex(g => g.includes(s)); return d[k + 1]; })();
      const canBeside = row.length === 1 && nxt && nxt.length === 1;
      C.menu(e.currentTarget, [
        { html: `${C.icon('plus', 's')} Add a template below…`, onPick: () => addDialog(id) },
        { sep: true },
        { html: `${C.icon('up', 's')} Move up<kbd>Alt ↑</kbd>`, disabled: !canStep(id, -1), onPick: () => moveSec(id, -1) },
        { html: `${C.icon('down', 's')} Move down<kbd>Alt ↓</kbd>`, disabled: !canStep(id, 1), onPick: () => moveSec(id, 1) },
        ...(row.length > 1 ? [{ html: `${C.icon('rows', 's')} Full width`, onPick: () => reflow(a => { const g = C.secRows(a.filter(x => !gl(x))).find(w => w.some(x => x.id === id)); if (g) delete g[0].beside; return true; }, `${s.title} set to full width`, id) }]
          : canBeside ? [{ html: `${C.icon('board', 's')} Place beside the next section`, onPick: () => reflow(a => placeSec(a, gl, id, { ref: nxt[0].id, side: 'l' }), `${s.title} placed beside ${nxt[0].title}`, id) }] : []),
        { sep: true },
        { html: `${C.icon(s.hidden ? 'eye' : 'eyeoff', 's')} ${s.hidden ? 'Include in the published page' : 'Leave out of the published page'}`, onPick: () => setRep(r2 => { r2.sections[i].hidden = !s.hidden; }, s.hidden ? `${s.title} included` : `${s.title} left out`) },
        ...(s.type === 'text' || s.type === 'tpl' || s.type === 'needs' ? [{ html: `${C.icon('trash', 's')} Delete section`, danger: true, onPick: () => setRep(r2 => { const k = r2.sections.findIndex(x => x.id === id), g = C.secRows(r2.sections.filter(x => !gl(x))).find(w => w.some(x => x.id === id)); if (g) delete g[0].beside; r2.sections.splice(k, 1); }, `${s.title} deleted`) }] : []),
      ]);
    }));
    C.$$('[data-addbelow]').forEach(b => b.addEventListener('click', () => addDialog(b.dataset.addbelow)));
    /* Needs from you: add a line by hand; archive it or bring it back (never deleted, FR-43c) */
    const ndSet = (code, fn, msg) => { const [sid, aid] = code.split(':'); setRep(r2 => { const s = r2.sections.find(x => x.id === sid); if (s) fn(s, (s.asks || []).find(a => a.id === aid)); }, msg); };
    C.$$('[data-nd-add]').forEach(f => f.addEventListener('submit', e => { e.preventDefault(); const what = f.what.value.trim(), owner = f.owner.value.trim(), due = f.due.value, err = f.querySelector('.nd-err'); if (!what) { err.hidden = false; f.what.setAttribute('aria-invalid', 'true'); f.what.focus(); return; }
      setRep(r2 => { const s = r2.sections.find(x => x.id === f.dataset.ndAdd); if (!s) return; s.asks = s.asks || []; s.asks.push({ id: 'n' + Date.now().toString(36) + (tplSeq++), what, owner, due, archived: false }); }, `Added to ${secName(f.dataset.ndAdd)}`); }));
    /* the Due box is clark's own date picker, so the date reads DD-MM-YYYY like everywhere else (not the browser's own date box) */
    C.$$('[data-nd-add] [name=what]').forEach(i => i.addEventListener('input', () => { const err = i.form.querySelector('.nd-err'); if (i.value.trim()) { err.hidden = true; i.removeAttribute('aria-invalid'); } }));
    C.$$('[data-nd-due]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); const f = b.closest('form');
      C.calPick(b, f.due.value, v => { f.due.value = v || ''; b.querySelector('span').textContent = v ? D.fd(v) : 'No date set'; b.setAttribute('aria-label', `Due: ${v ? D.fd(v) : 'no date set'}. Choose a date`); }, { quick: [['Today', D.TODAY], ['Next week', D.addDays(D.TODAY, 7)], ['No date', '']] }); }));
    C.$$('[data-nd-arch]').forEach(b => b.addEventListener('click', () => ndSet(b.dataset.ndArch, (s, a) => { if (a) a.archived = true; }, 'Line archived')));
    C.$$('[data-nd-back]').forEach(b => b.addEventListener('click', () => ndSet(b.dataset.ndBack, (s, a) => { if (a) a.archived = false; }, 'Line restored')));
    /* drag and drop (Edit only). Picking up the grip makes the section draggable; over another section the pointer chooses where it lands:
       the top or bottom edge = a full row above or below that row (a line); the middle of a section that is alone = beside it, on the left or right half (an outline) */
    let from = null;
    const clear = () => C.$$('.drop-before,.drop-after,.drop-l,.drop-r').forEach(x => x.classList.remove('drop-before', 'drop-after', 'drop-l', 'drop-r'));
    C.$$('[data-drag]').forEach(h => {
      const sec = h.closest('.sec'), id = h.dataset.drag;
      h.addEventListener('keydown', e => { if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) { e.preventDefault(); moveSec(id, e.key === 'ArrowUp' ? -1 : 1); } });
      h.addEventListener('mousedown', () => { sec.draggable = true; }); h.addEventListener('mouseup', () => { sec.draggable = false; });
      sec.addEventListener('dragstart', e => { if (!sec.draggable) return; from = id; e.dataTransfer.setData('text/sec', id); e.dataTransfer.effectAllowed = 'move'; sec.classList.add('dragging'); });
      sec.addEventListener('dragend', () => { from = null; sec.draggable = false; sec.classList.remove('dragging'); clear(); });
    });
    /* where would a drop land: { at, mark: [[id, class]...] } or null */
    const where = e => {
      const secs = C.$$('.sbody .sec'); if (!from || !secs.length) return null;
      let best = null, bd = 1e9; secs.forEach(el => { const b = el.getBoundingClientRect(), dx = Math.max(b.left - e.clientX, 0, e.clientX - b.right), dy = Math.max(b.top - e.clientY, 0, e.clientY - b.bottom), d = dx * dx + dy * dy; if (d < bd) { bd = d; best = el; } });
      const id = best.dataset.sec, b = best.getBoundingClientRect(), y = e.clientY - b.top, edge = Math.min(b.height * .25, 56), rows = rowsOf(), k = rows.findIndex(g => g.some(s => s.id === id)), row = rows[k];
      if (id === from) return null;
      const above = () => ({ at: { before: row[0].id }, mark: row.map(s => [s.id, 'drop-before']) }), below = () => ({ at: { before: rows[k + 1] ? rows[k + 1][0].id : null }, mark: row.map(s => [s.id, 'drop-after']) });
      if (y < edge) return above(); if (y > b.height - edge) return below();
      if (row.filter(s => s.id !== from).length === 1) { const left = e.clientX < b.left + b.width / 2; return { at: { ref: id, side: left ? 'l' : 'r' }, mark: [[id, left ? 'drop-l' : 'drop-r']] }; }
      return y < b.height / 2 ? above() : below();
    };
    const body = C.$('.sbody');
    body?.addEventListener('dragover', e => { if (![...e.dataTransfer.types].includes('text/sec')) return; e.preventDefault(); e.dataTransfer.dropEffect = 'move'; const w = where(e); clear(); w && w.mark.forEach(([id, c]) => C.$(`[data-sec="${id}"]`)?.classList.add(c)); });
    body?.addEventListener('dragleave', e => { if (!body.contains(e.relatedTarget)) clear(); });
    body?.addEventListener('drop', e => { const id = from || e.dataTransfer.getData('text/sec'); if (!id) return; e.preventDefault(); from = id; const w = where(e); clear(); if (!w) return;
      const ref = w.at.ref ? secName(w.at.ref) : '', nb = w.at.before ? secName(w.at.before) : '';
      reflow(a => placeSec(a, gl, id, w.at), w.at.ref ? `${secName(id)} moved beside ${ref}` : nb ? `${secName(id)} moved to a full row above ${nb}` : `${secName(id)} moved to a full row at the end`, id); });
  }
  function addFrom(type) {
    const list = C.items().filter(ITEMS_OF[type]).filter(x => !x.client && (type === 'decisions' || C.isOpen(x)));
    C.picker({ title: 'Add from your project record', sub: { raid: 'Risks and issues', actions: 'Open actions', decisions: 'Decisions' }[type] + ' not on the page yet',
      items: list.map(x => ({ id: x.id, title: x.title, meta: `${x.id} · ${x.owner || 'No owner'}${x.due ? ' · ' + D.fd(x.due) : ''}${x.uc ? ' · use case ' + x.uc : ''}`, type: x.type, badge: C.pill(C.look(x)), search: [x.id, x.title, x.owner, x.ws, x.uc].join(' ') })),
      types: type === 'raid' ? [['R', 'Risks'], ['I', 'Issues']] : null,
      onAdd: ids => { const u = D.batch(ids.map(id => () => D.change('item', D.S.items.find(x => x.id === id), { client: true }, D.who('in the report')))); C.refresh(); C.toast(`${ids.length} added to the page`, u); } });
  }
  function docForm(doc) {
    const p = P();
    C.dialog(`<form id="dF"><div class="dlg-h"><h2>${doc ? 'Edit the document link' : 'Add a document link'}</h2><p>Minutes, action lists and other papers from the week. The published page links to them.</p></div>
      <div class="dlg-b"><div class="form"><label for="dT">Title</label><input class="field" id="dT" required value="${esc(doc?.title || '')}" placeholder="For example: Steering minutes">
      <label for="dK">Kind</label><select class="field" id="dK">${['Minutes', 'Actions list', 'Report', 'Slides', 'Plan', 'Other'].map(k => `<option${doc?.kind === k ? ' selected' : ''}>${k}</option>`).join('')}</select>
      <label for="dU">Link</label><input class="field" id="dU" required type="url" value="${esc(doc?.url || '')}" placeholder="https://…">
      <label for="dD">Date</label><input class="field" id="dD" type="date" value="${doc?.date || D.TODAY}"></div></div>
      <div class="dlg-f"><button type="button" class="btn quiet" data-close>Cancel</button><button class="btn pri">${doc ? 'Save' : 'Add'}</button></div></form>`, d => C.$('#dF', d).addEventListener('submit', e => {
      e.preventDefault(); const v = { title: C.$('#dT', d).value.trim(), kind: C.$('#dK', d).value, url: C.$('#dU', d).value.trim(), date: C.$('#dD', d).value };
      const docs = D.clone(p.docs || []); if (doc) Object.assign(docs.find(x => x.id === doc.id), v); else docs.push({ id: 'D' + Date.now().toString(36), ...v });
      d.close(); saveProject({ docs }, doc ? 'Document saved' : 'Document added');
    }));
  }
  function wireUc(p) {
    const find = k => D.S.usecases.find(u => u.key === k);
    C.$('[data-uc-export]')?.addEventListener('click', () => C.exportExcel({ only: 'usecases' }));
    C.$('[data-uc-page]')?.addEventListener('click', () => C.go('usecases'));
    C.$('[data-uc-add]')?.addEventListener('click', () => ucForm(p));
    const toggle = k => { const cur = C.store.get('ucOpen', ''); C.store.set('ucOpen', cur === k ? '' : k); const now = C.store.get('ucOpen', '');
      C.$$('.ucr').forEach(r => { const on = r.dataset.uc === now; r.classList.toggle('open', on); r.setAttribute('aria-expanded', on); });
      C.$$('.ucd').forEach(r => r.classList.toggle('open', r.dataset.ucd === now)); };
    C.$$('.ucr').forEach(r => { C.slowTip(r, r.classList.contains('open') ? 'Select to close the detail' : 'Select to open the detail of this use case');
      r.addEventListener('click', e => { if (e.target.closest('[contenteditable],[data-uc-status],[data-uc-eye]')) return; toggle(r.dataset.uc); });
      r.addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target === r) { e.preventDefault(); toggle(r.dataset.uc); } }); });
    C.$$('[data-uc-status]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); const u = find(b.dataset.ucStatus); C.menu(e.currentTarget, Object.keys(UC_CLS).map(s => ({ html: UC_WORD(s), selected: u.status === s, onPick: () => { const un = D.change('uc', u, { status: s }, D.who('in the report')); C.refresh(); C.toast(`Use case ${u.ref || u.id} set to ${s}`, un); } })), { select: true }); }));
    const ce = (sel, field, attr) => C.$$(sel).forEach(el => { const u = find(el.dataset[attr]);
      el.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); el.blur(); } if (e.key === 'Escape') { e.stopPropagation(); el.textContent = field === 'title' ? u.title.split('\n')[0] : u[field]; el.blur(); } });
      el.addEventListener('blur', () => { const v = el.textContent.trim(), old = field === 'title' ? u.title.split('\n')[0] : u[field]; if (!v || v === old) { el.textContent = old; return; }
        const un = D.change('uc', u, { [field]: field === 'title' ? [v, ...u.title.split('\n').slice(1)].join('\n') : v }, D.who('in the report')); C.refresh(); C.toast(`Use case ${u.ref || u.id} saved`, un); }); });
    ce('[data-uc-head]', 'headline', 'ucHead'); ce('[data-uc-title]', 'title', 'ucTitle');
    C.$$('[data-uc-std]').forEach(el => { const u = find(el.dataset.ucStd);
      C.inline(el, { html: u.standing, label: 'Where it stands', placeholder: 'Where the use case stands', place: 'current', draft: () => C.draftUc(u), onSave: h => { const un = D.change('uc', u, { standing: h }, D.who('in the report')); C.refresh(); C.toast(`Use case ${u.ref || u.id} saved`, un); } }); });
    C.$$('[data-uc-eye]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); const u = find(b.dataset.ucEye); const row = b.closest('.ucr'); C.hideLater([row, row.nextElementSibling], D.change('uc', u, { client: false }, D.who('with the eye')), `Use case ${u.ref || u.id} taken off the page`); }));
    C.$('[data-ucback]')?.addEventListener('click', () => C.picker({ title: 'Add a use case from your project record', items: D.S.usecases.filter(u => u.code === p.code && !u.client).map(u => ({ id: u.key, title: `${u.ref || u.id} ${u.title.split('\n')[0]}`, meta: u.headline, badge: ucBadge(u.status) })),
      onAdd: ids => { const un = D.batch(ids.map(k => () => D.change('uc', find(k), { client: true }, D.who('in the report')))); C.refresh(); C.toast(`${ids.length} use case${ids.length > 1 ? 's' : ''} added to the page`, un); } }));
    C.$$('[data-uc-step]').forEach(i => i.addEventListener('keydown', e => { if (e.key !== 'Enter' || !i.value.trim()) return; e.preventDefault(); const u = find(i.dataset.ucStep);
      addInline('A', i.value, { uc: u.id, client: true, source: 'Added from use case ' + (u.ref || u.id) }, `[data-uc-step="${CSS.escape(u.key)}"]`); }));
    C.$$('[data-uc-work]').forEach(b => b.addEventListener('click', () => C.workFilter({ uc: [b.dataset.ucWork] })));
    /* link work items that already exist (they keep everything else; only the use case link changes) */
    C.$$('[data-uc-link]').forEach(b => b.addEventListener('click', () => { const u = find(b.dataset.ucLink);
      const other = id => { const o = D.S.usecases.find(z => z.code === u.code && z.id === id); return o ? ` · now in use case ${o.ref || o.id}` : ''; };
      C.picker({ title: `Link work items to use case ${u.ref || u.id}`, sub: 'Open work items not linked to this use case yet',
        items: C.items().filter(x => x.uc !== u.id && C.isOpen(x)).map(x => ({ id: x.id, title: x.title, type: x.type, meta: `${x.id} · ${x.owner || 'No owner'}${x.due ? ' · ' + D.fd(x.due) : ''}${other(x.uc)}`, badge: C.pill(C.look(x)), search: [x.id, x.title, x.owner, x.ws, x.uc].join(' ') })),
        types: [['A', 'Actions'], ['R', 'Risks'], ['I', 'Issues'], ['D', 'Decisions']],
        onAdd: ids => { const un = D.batch(ids.map(id => () => D.change('item', D.S.items.find(x => x.id === id), { uc: u.id }, D.who('in the report')))); C.refresh(); C.toast(`${ids.length} work item${ids.length > 1 ? 's' : ''} linked to use case ${u.ref || u.id}`, un); } }); }));
    C.$$('[data-uc-del]').forEach(b => b.addEventListener('click', () => { const u = find(b.dataset.ucDel); C.confirm(`Delete use case ${u.ref || u.id}?`, `<p>Its work items stay; they lose the link to this use case.</p>`, 'Delete', () => {
      const un = D.batch([() => D.remove('uc', u, D.who('in the report')), ...C.items().filter(x => x.uc === u.id).map(x => () => D.change('item', x, { uc: '' }, D.who('in the report')))]); C.refresh(); C.toast('Use case deleted', un); }); }));
  }
  function ucForm(p) {
    C.dialog(`<form id="ucF"><div class="dlg-h"><h2>Add a use case</h2></div><div class="dlg-b"><div class="form">
      <label for="ucI">ID</label><input class="field" id="ucI" required placeholder="For example: 3.1">
      <label for="ucT">Use case</label><input class="field" id="ucT" required placeholder="What it does">
      <label for="ucS">Status</label><select class="field" id="ucS">${Object.keys(UC_CLS).map(s => `<option>${s}</option>`).join('')}</select>
      <label for="ucH">Headline</label><input class="field" id="ucH" placeholder="One line on where it stands"></div></div>
      <div class="dlg-f"><button type="button" class="btn quiet" data-close>Cancel</button><button class="btn pri">Add</button></div></form>`, d => C.$('#ucF', d).addEventListener('submit', e => {
      e.preventDefault(); const id = C.$('#ucI', d).value.trim();
      if (D.S.usecases.some(u => u.code === p.code && u.id === id)) { const i = C.$('#ucI', d); i.setCustomValidity('That ID is already used'); i.reportValidity(); i.setCustomValidity(''); return; }
      const u = { key: p.code + '/' + id, id, code: p.code, title: C.$('#ucT', d).value.trim(), status: C.$('#ucS', d).value, headline: C.$('#ucH', d).value.trim(), standing: '', client: true };
      d.close(); const un = D.create('uc', u, D.who('in the report')); C.store.set('ucOpen', u.key); C.refresh(); C.toast(`Use case ${id} added`, un);
    }));
  }
  C.addInline = addInline;
  /* the picker: searchable, selectable, keyboard-friendly */
  C.picker = ({ title, sub, items, types, onAdd }) => {
    const sel = new Set(); let q = '', tf = '';
    C.dialog(`<form id="pkF" class="picker"><div class="dlg-h"><h2>${esc(title)}</h2><p>${esc(sub || (items.length ? 'Choose what to add to the page.' : 'Everything is already on the page.'))}</p></div>
      <div class="pk-search"><label class="search"><span class="sr">Search</span>${C.icon('search')}<input id="pkQ" type="search" placeholder="Search by name, ID, owner or use case" autocomplete="off"></label>
        ${types ? `<div class="seg" role="group" aria-label="Kind"><button type="button" data-t="" aria-pressed="true">All</button>${types.map(([k, t]) => `<button type="button" data-t="${k}" aria-pressed="false">${t}</button>`).join('')}</div>` : ''}
        <button type="button" class="btn sm" id="pkAll">Select all shown</button></div>
      <div class="dlg-b"><ul class="pick" id="pkList"></ul><p class="muted" id="pkNone" hidden>Nothing matches.</p></div>
      <div class="dlg-f"><span class="muted" id="pkCount" style="margin-right:auto;font-size:14px">None selected</span><button type="button" class="btn quiet" data-close>Cancel</button><button class="btn pri" id="pkGo" disabled>Add selected</button></div></form>`, d => {
      const listEl = C.$('#pkList', d), count = () => { C.$('#pkCount', d).textContent = sel.size ? `${sel.size} selected` : 'None selected'; C.$('#pkGo', d).disabled = !sel.size; C.$('#pkGo', d).textContent = sel.size ? `Add ${sel.size}` : 'Add selected'; };
      const shown = () => items.filter(it => (!tf || it.type === tf) && (!q || (it.search || it.title + ' ' + (it.meta || '')).toLowerCase().includes(q)));
      const draw = () => { const s = shown(); listEl.innerHTML = s.map(it => `<li><label><input type="checkbox" value="${esc(it.id)}" ${sel.has(it.id) ? 'checked' : ''}>${it.type ? `<span class="type ${it.type}">${it.type}</span>` : '<span></span>'}<span>${esc(it.title)}<br><span class="muted" style="font-size:12px">${esc(it.meta || '')}</span></span>${it.badge || ''}</label></li>`).join('');
        C.$('#pkNone', d).hidden = !!s.length; C.$$('input', listEl).forEach(c => c.addEventListener('change', () => { c.checked ? sel.add(c.value) : sel.delete(c.value); count(); })); };
      draw(); count(); const qi = C.$('#pkQ', d); setTimeout(() => qi.focus(), 30);
      qi.addEventListener('input', () => { q = qi.value.trim().toLowerCase(); draw(); });
      qi.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); const s = shown(); if (s.length === 1) { sel.add(s[0].id); draw(); count(); } } if (e.key === 'ArrowDown') { e.preventDefault(); C.$('input', listEl)?.focus(); } });
      C.$$('[data-t]', d).forEach(b => b.addEventListener('click', () => { tf = b.dataset.t; C.$$('[data-t]', d).forEach(z => z.setAttribute('aria-pressed', z === b)); draw(); }));
      C.$('#pkAll', d).addEventListener('click', () => { shown().forEach(it => sel.add(it.id)); draw(); count(); });
      C.$('#pkF', d).addEventListener('submit', e => { e.preventDefault(); if (!sel.size) return; d.close(); onAdd([...sel]); });
    });
  };


  /* ═════════════ work items ═════════════ */
  /* The filter line (#145, the prototype of #137): one line for fields and plain words replaces the type and Open / Closed
     switches and the "Filter by" row. The line is chips (the filters it has taken) and the words being typed; fline.js reads it.
     Group by and swimlanes live in one View menu; the layout toggle stays. Layout, grouping and open groups are kept as before. */
  const FL = C.fline;
  const WF = C.store.get('wf', null) || {};
  const W = { open: WF.open || {}, layout: WF.layout || 'table', group: WF.group || 'ws', lane: WF.lane || 'none', chips: [], q: '', view: '', code: null };
  const saveW = () => { C.store.set('wf', { open: W.open, layout: W.layout, group: W.group, lane: W.lane }); if (W.code) FL.linePut(W.code, { chips: W.chips, q: W.q, view: W.view }); };
  /* the plain words in the box (a field word still being typed is not applied until it is accepted) */
  const qWords = () => FL.words(W.q).filter(w => !FL.isField(w)).map(w => w.replace(/"/g, '')).filter(Boolean);
  const lineNow = () => [...W.chips, ...qWords()].join(' ');
  const setLine = line => { const p = FL.parse(line); W.chips = p.conds.map(c => c.text); W.q = p.words.join(' '); };
  /* the view whose saved line this is, if any; otherwise the current tab stays chosen and shows its dot */
  const pickView = () => { const v = FL.views(UI.code).find(z => FL.norm(z.line) === lineNow()); if (v) W.view = v.id; };
  /* the line is kept per project (FL.OPT.REMEMBER); a project seen for the first time opens on its first saved view */
  const lineLoad = () => { if (W.code === UI.code) return; W.code = UI.code; const m = FL.lineGet(UI.code), vs = FL.views(UI.code);
    if (m) { W.chips = m.chips || []; W.q = m.q || ''; W.view = m.view || ''; } else { W.view = vs[0]?.id || ''; setLine(vs[0] && FL.OPT.VIEWS === 'tabs' ? vs[0].line : FL.BASE); } };
  const conds = () => FL.parse(W.chips.join(' ')).conds;
  /* the one value a field has in the line (for Add and the board's columns), or '' */
  const one = k => { const c = conds().filter(x => x.field === k && !x.not && !x.none); return c.length === 1 && c[0].vals.length === 1 ? c[0].vals[0] : ''; };
  const lineType = () => { const c = conds().filter(x => x.field === 'type' && !x.not && !x.none); if (c.length !== 1) return 'all'; return { action: 'A', decision: 'D', risk: 'R', issue: 'R', 'issue,risk': 'R' }[c[0].vals.map(v => v.toLowerCase()).sort().join()] || 'all'; };
  const lineShow = () => { const pos = conds().filter(x => x.field === 'is' && !x.not && !x.none).flatMap(x => x.vals); return pos.includes('open') && !pos.includes('closed') ? 'open' : pos.includes('closed') && !pos.includes('open') ? 'closed' : 'all'; };
  C.workFilter = o => { W.code = UI.code; setLine(FL.fromFilter(o)); W.view = FL.views(UI.code)[0]?.id || ''; pickView(); saveW(); C.go('work'); };   // a tile opens Work items on a line that shows exactly what it counts
  C.workLine = line => { W.code = UI.code; setLine(line); pickView(); saveW(); if (UI.view === 'work') C.render(); else C.go('work'); };   // the same, from a line (ask clark could fill it; the self-test uses it)
  /* arch: the archived items instead (Show archived, #166), with the same line, open or closed alike (an is: filter on open or closed is left out) */
  function workList(line, arch) {
    const p = line === undefined ? { ...FL.parse(W.chips.join(' ')), words: qWords() } : FL.parse(line);
    if (arch) p.conds = p.conds.filter(c => !(c.field === 'is' && (c.vals || []).some(v => ['open', 'closed'].includes(String(v).toLowerCase()))));
    return (arch ? C.itemsAll().filter(x => x.archived) : C.items()).filter(x => FL.match(p, x));
  }
  const addWord = () => ({ all: 'Add item', A: 'Add action', R: 'Add risk or issue', D: 'Add decision' })[lineType()] || 'Add item';

  /* ── the Work board, as creaite's (its FR-89, FR-110 and FR-116): the same items, filters and search as the
     table, as cards in columns. Group by status, due, owner, priority or milestone, with one level of swimlanes (workstream or
     type). Dragging a card, or its Move to… menu, changes the item as an edit does, one step with Undo; a move across a lane and
     a column changes both in one step. Due asks for a date (never a past one; Overdue is not a drop target). Columns count,
     collapse and are remembered. ── */
  const friday = n => { const d = new Date(D.TODAY + 'T00:00:00'); d.setDate(d.getDate() + ((5 - d.getDay() + 7) % 7) + 7 * n); return D.toIso(d); };
  const weekEnd = n => { const d = new Date(D.TODAY + 'T00:00:00'); d.setDate(d.getDate() + ((7 - d.getDay()) % 7) + 7 * n); return D.toIso(d); };
  const me = () => (D.S.profile || {}).name || '';
  const GROUPS = {
    ws: { t: 'Workstream', cols: xs => [...new Set([...P().ws, ...xs.map(x => x.ws)])].map(w => [w, w]), of: x => x.ws, set: (x, k) => ({ ws: k }) },
    status: { t: 'Status', cols: xs => [...new Set([...(lineType() === 'D' ? [] : D.STATUSES.A), ...D.STATUSES.R, ...(lineType() === 'A' || lineType() === 'R' ? [] : D.STATUSES.D)])].filter(s => lineShow() === 'all' || (lineShow() === 'open') === !['Closed', 'Cancelled', 'Made', 'Withdrawn'].includes(s)).map(s => [s, s]), of: x => x.status,
      set: (x, k) => (D.STATUSES[x.type === 'I' ? 'R' : x.type] || []).includes(k) ? { status: k } : `A ${D.TYPES[x.type].toLowerCase()} can't be ${k}` },
    due: { t: 'Due', cols: () => [['overdue', 'Overdue'], ['week', 'This week'], ['next', 'Next week'], ['later', 'Later'], ['none', 'No date']],
      of: x => !x.due ? 'none' : x.due < D.TODAY ? 'overdue' : x.due <= weekEnd(0) ? 'week' : x.due <= weekEnd(1) ? 'next' : 'later', ask: true },
    owner: { t: 'Owner', cols: xs => { const n = o => xs.filter(x => (x.owner || '') === o).length, os = [...new Set(C.items().map(x => x.owner || ''))].filter(Boolean).sort((a, b) => (b === me()) - (a === me()) || n(b) - n(a) || a.localeCompare(b));
      return [...os.map(o => [o, o === me() ? o + ' (me)' : o]), ['', 'No owner']]; }, of: x => x.owner || '', set: (x, k) => ({ owner: k }) },
    priority: { t: 'Priority', cols: () => D.PRIORITIES.map(v => [v, v]), of: x => x.priority, set: (x, k) => ({ priority: k }) },
    ms: { t: 'Milestone', cols: () => [...C.mss().map(m => [m.id, m.name]), ['', 'No milestone']], of: x => x.ms || '', set: (x, k) => ({ ms: k }) },
    type: { t: 'Type', cols: () => [['A', 'Actions'], ['R', 'Risks and issues'], ['D', 'Decisions']], of: x => x.type === 'I' ? 'R' : x.type, set: x => `A ${D.TYPES[x.type].toLowerCase()} can't change its type` },
    none: { t: 'Nothing', cols: () => [['', 'All items']], of: () => '', table: true },
  };
  /* Group by replaces the workstream dropdown: the table's groups and the board's columns; "Nothing" is for the table only */
  const grp = () => GROUPS[W.group] && !(W.layout === 'board' && GROUPS[W.group].table) ? GROUPS[W.group] : W.layout === 'board' ? GROUPS.status : GROUPS.ws;
  const LANES = { none: { t: 'None' }, ws: { t: 'Workstream', of: x => x.ws, list: xs => [...new Set([...P().ws, ...xs.map(x => x.ws)])].filter(w => xs.some(x => x.ws === w)), set: (x, k) => ({ ws: k }) },
    type: { t: 'Type', of: x => x.type === 'I' ? 'R' : x.type, list: xs => ['A', 'R', 'D'].filter(t => xs.some(x => (x.type === 'I' ? 'R' : x.type) === t)), lab: k => ({ A: 'Actions', R: 'Risks and issues', D: 'Decisions' })[k] } };
  const shut = () => new Set(C.store.get('bshut', []));
  /* coloured state labels on the board's column headings: the state's own colour for status, due and priority */
  const TONE = { status: { Open: 'b', Delayed: 'a', Closed: 'n', Cancelled: 'n', Pending: 'b', Made: 'g', Withdrawn: 'n' },
    due: { overdue: 'r', week: 'a', next: 'b', later: 'g', none: 'n' }, priority: { Urgent: 'r', High: 'a', Medium: 'b', Low: 'n' } };
  /* creaite's column widths (its #144): 260 to 640 px, 272 by default, remembered per grouping; the handle on a column's right
     edge drags, ←/→ move it 16 px, a double-click puts it back. Column order is the user's too: drag a heading onto another
     column, or Alt+←/→ on a focused heading ("we can reorganise the board and we can also extend the width") */
  const BW_MIN = 260, BW_MAX = 640, BW_DEF = 272;
  const bw = () => C.store.get('bw', {}), bwOf = (g, k) => { const w = (bw()[g] || {})[k]; return typeof w === 'number' && w >= BW_MIN && w <= BW_MAX ? w : 0; };
  const bwPut = (g, k, w) => { w = Math.round(Math.max(BW_MIN, Math.min(BW_MAX, w))); const all = bw(); all[g] = all[g] || {}; if (w === BW_DEF) delete all[g][k]; else all[g][k] = w; C.store.set('bw', all);
    C.$$(`.bcol[data-col="${CSS.escape(k)}"]`).forEach(c => { c.style.flexBasis = c.style.width = w + 'px'; C.$('.bcrz', c)?.setAttribute('aria-valuenow', w); }); return w; };
  const ordered = (g, cols) => { const o = (C.store.get('bord', {})[g] || []), at = k => { const i = o.indexOf(k); return i < 0 ? 1e3 + cols.findIndex(c => c[0] === k) : i; }; return cols.slice().sort((a, b) => at(a[0]) - at(b[0])); };
  const reorder = (g, cols, from, to) => { const ks = ordered(g, cols).map(c => c[0]), i = ks.indexOf(from); if (i < 0 || from === to) return; ks.splice(i, 1); const j = ks.indexOf(to); ks.splice(to === null ? ks.length : j, 0, from); const all = C.store.get('bord', {}); all[g] = ks; C.store.set('bord', all); };
  function cardHtml(x) {
    return `<article class="bcard${UI.peek === x.id ? ' sel' : ''}" draggable="true" tabindex="0" role="button" data-card="${x.id}" aria-label="${esc(x.id + ' ' + x.title)}">
      <div class="bc-top"><span class="type ${x.type}" title="${D.TYPES[x.type]}">${x.type}</span><span class="bc-id">${x.id}</span>${x.client ? `<span class="bc-cl" title="Shown to the client">${C.icon('eye', 's')}</span>` : ''}<button class="ib bc-mv" data-mvto="${x.id}" aria-label="Move ${x.id} to…" title="Move to…">${C.icon('more', 's')}</button></div>
      <div class="bc-t">${esc(x.title)}</div>
      <div class="bc-meta">${x.owner ? `<span class="av" title="${esc(x.owner)}">${C.initials(x.owner)}</span>` : ''}${x.due ? `<span class="due-l ${D.days(x.due) < 0 && C.isOpen(x) ? 'late' : ''}">${C.dueWords(x.due)}</span>` : ''}<span class="sp"></span>${C.pill(C.look(x))}</div></article>`;
  }
  function boardHtml(list) {
    const G = grp(), L = W.lane !== W.group && LANES[W.lane] || LANES.none, cols = ordered(W.group, G.cols(list)), off = shut();
    const lanes = L.list ? L.list(list).map(k => [k, L.lab ? L.lab(k) : k, list.filter(x => L.of(x) === k)]) : [['', '', list]];
    const full = document.body.classList.contains('bfull');
    return `<div class="bbar"><span class="sp"></span><button class="ib tip" id="bFull" aria-pressed="${full}" aria-label="${full ? 'Leave full screen' : 'View full screen'}" data-tip="${full ? 'Leave full screen (Esc)' : 'View full screen'}">${C.icon(full ? 'collapse' : 'expand')}</button></div><div class="board" data-group="${W.group}">${lanes.map(([lk, lt, xs]) => `${L.list ? `<div class="blane-h">${esc(lt)} <em>${xs.length}</em></div>` : ''}
      <div class="bcols">${cols.map(([ck, ct]) => { const cs = xs.filter(x => G.of(x) === ck), key = W.group + ':' + ck, closed = off.has(key);
        const w = bwOf(W.group, ck);
        return `<section class="bcol${closed ? ' shut' : ''}${W.group === 'due' && ck === 'overdue' ? ' nodrop' : ''}" data-col="${esc(ck)}" data-lane="${esc(lk)}" data-key="${esc(key)}"${w && !closed ? ` style="flex-basis:${w}px;width:${w}px"` : ''}>
          <button class="bcol-h tone-${TONE[W.group]?.[ck] || 'none'}" draggable="true" aria-expanded="${!closed}" title="${closed ? 'Show' : 'Collapse'} ${esc(ct)}. Drag to move the column; Alt+arrows from the keyboard"><span class="t">${esc(ct)}</span><em>${cs.length}</em></button>
          ${closed ? '' : `<span class="bcrz" role="separator" tabindex="0" aria-orientation="vertical" aria-label="Resize the ${esc(ct)} column" aria-valuemin="${BW_MIN}" aria-valuemax="${BW_MAX}" aria-valuenow="${w || BW_DEF}"></span>`}
          <div class="bcards">${closed ? '' : cs.map(cardHtml).join('') || '<p class="bempty">Nothing here</p>'}</div></section>`; }).join('')}</div>`).join('')}</div>`;
  }
  /* one move: the column's field, and the lane's when the card crossed lanes; one step with Undo */
  function moveCard(x, ck, lk, rer) {
    const G = grp(), L = W.lane !== W.group && LANES[W.lane] || LANES.none;
    const go = ch => { const laneCh = L.set && lk !== undefined && L.of(x) !== lk ? L.set(x, lk) : null;
      if (L.of && !L.set && lk !== undefined && L.of(x) !== lk) return C.toast(`A ${D.TYPES[x.type].toLowerCase()} can't change its type`);
      const all = { ...(ch || {}), ...(laneCh || {}) }; if (!Object.keys(all).length) return;
      const u = D.change('item', x, all, D.who('on the board')); C.toast(`${x.id} moved`, () => { u && u(); rer(); }); rer(); };
    if (G.ask) { if (ck === 'overdue') return C.toast('Overdue is worked out from the date. Pick a date instead'); if (ck === 'none') return go({ due: '' });
      const def = { week: friday(0) < D.TODAY ? D.TODAY : friday(0), next: friday(1), later: D.addDays(D.TODAY, 28) }[ck] || D.TODAY;
      const anchor = C.$(`.bcol[data-col="${ck}"] .bcol-h`) || C.$('#viewBtn');
      C.calPick(anchor, def, v => { if (v && v >= D.TODAY) go({ due: v }); }, { min: D.TODAY });   // clark's own picker: one panel, one Esc
      return; }
    const ch = G.set(x, ck); if (typeof ch === 'string') return C.toast(ch); go(ch);
  }
  function wireBoard(rer) {
    const G = grp, ids = () => C.$$('[data-card]').map(c => c.dataset.card);
    /* the board scrolls inside itself, so a wheel or a swipe over it would never move the page and the toolbar would stay: until the board has reached the top bar, the page takes the scroll */
    { const bd = C.$('.board'), pin = () => C.$('.top').getBoundingClientRect().bottom; let y0 = 0;
      bd?.addEventListener('wheel', e => { const gap = bd.getBoundingClientRect().top - pin(); if (e.deltaY > 0 && Math.abs(e.deltaY) >= Math.abs(e.deltaX) && gap > 1) { e.preventDefault(); window.scrollBy(0, Math.min(e.deltaY, gap)); } }, { passive: false });
      bd?.addEventListener('touchstart', e => { y0 = e.touches[0].clientY; }, { passive: true });
      bd?.addEventListener('touchmove', e => { const dy = y0 - e.touches[0].clientY, gap = bd.getBoundingClientRect().top - pin(); if (dy > 0 && gap > 1) { e.preventDefault(); window.scrollBy(0, Math.min(dy, gap)); y0 = e.touches[0].clientY; } }, { passive: false }); }
    /* the board full screen: the board fills the window; the same icon or Esc brings it back */
    C.$('#bFull')?.addEventListener('click', () => { document.body.classList.toggle('bfull'); rer(); });
    C.$$('.bcol-h').forEach(h => {
      h.addEventListener('click', () => { const k = h.closest('.bcol').dataset.key, s = shut(); s.has(k) ? s.delete(k) : s.add(k); C.store.set('bshut', [...s]); rer(); });
      /* move a column: drag its heading onto another column, or Alt+←/→ */
      h.addEventListener('dragstart', e => { e.stopPropagation(); e.dataTransfer.setData('application/x-clark-col', h.closest('.bcol').dataset.col); e.dataTransfer.effectAllowed = 'move'; });
      h.addEventListener('keydown', e => { if (!e.altKey || (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight')) return; e.preventDefault(); const cols = ordered(W.group, G().cols(workList())), ks = cols.map(c => c[0]), k = h.closest('.bcol').dataset.col, i = ks.indexOf(k), j = i + (e.key === 'ArrowRight' ? 1 : -1);
        if (j < 0 || j >= ks.length) return; reorder(W.group, cols, k, e.key === 'ArrowRight' ? (ks[j + 1] ?? null) : ks[j]); rer(); C.$(`.bcol[data-col="${CSS.escape(k)}"] .bcol-h`)?.focus(); });
    });
    /* resize a column, as creaite's */
    C.$$('.bcrz').forEach(hd => { const col = hd.closest('.bcol'), k = col.dataset.col;
      hd.addEventListener('pointerdown', e => { if (e.button !== 0) return; e.preventDefault(); e.stopPropagation(); const x0 = e.clientX, w0 = col.getBoundingClientRect().width; hd.setPointerCapture(e.pointerId); document.body.classList.add('resizing');
        const mv = ev => bwPut(W.group, k, w0 + ev.clientX - x0), up = () => { hd.removeEventListener('pointermove', mv); hd.removeEventListener('pointerup', up); document.body.classList.remove('resizing'); };
        hd.addEventListener('pointermove', mv); hd.addEventListener('pointerup', up); });
      hd.addEventListener('dblclick', () => { bwPut(W.group, k, BW_DEF); C.toast('Column width reset'); });
      hd.addEventListener('keydown', e => { if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return; e.preventDefault(); bwPut(W.group, k, col.getBoundingClientRect().width + (e.key === 'ArrowRight' ? 16 : -16)); });
    });
    C.$$('[data-card]').forEach(c => {
      c.addEventListener('click', e => { if (e.target.closest('[data-mvto]')) return; C.openItem(c.dataset.card, ids()); });
      c.addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target === c) { e.preventDefault(); C.openItem(c.dataset.card, ids()); } });   /* Enter or Space on the card itself; its Move button keeps its own keys */
      c.addEventListener('dragstart', e => { e.dataTransfer.setData('text/plain', c.dataset.card); e.dataTransfer.effectAllowed = 'move'; c.classList.add('dragging'); });
      c.addEventListener('dragend', () => c.classList.remove('dragging'));
    });
    C.$$('.bcol').forEach(col => {
      col.addEventListener('dragover', e => { if (col.classList.contains('nodrop') && !e.dataTransfer.types.includes('application/x-clark-col')) return; e.preventDefault(); col.classList.add('over'); });
      col.addEventListener('dragleave', () => col.classList.remove('over'));
      col.addEventListener('drop', e => { e.preventDefault(); col.classList.remove('over'); const mc = e.dataTransfer.getData('application/x-clark-col'); if (mc) { reorder(W.group, G().cols(workList()), mc, col.dataset.col); return rer(); } const x = D.S.items.find(i => i.id === e.dataTransfer.getData('text/plain')); if (x) moveCard(x, col.dataset.col, (LANES[W.lane] || {}).of ? col.dataset.lane : undefined, rer); });
    });
    C.$$('[data-mvto]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); const x = D.S.items.find(i => i.id === b.dataset.mvto), g = G(), L = W.lane !== W.group && LANES[W.lane] || LANES.none;
      const cols = g.cols(workList()).filter(([k]) => !(W.group === 'due' && k === 'overdue') && k !== g.of(x));
      const lanes = L.set ? L.list(workList()).filter(k => k !== L.of(x)) : [];
      C.menu(b, [{ lab: 'Move to ' + g.t.toLowerCase() }, ...cols.map(([k, t]) => ({ label: t, onPick: () => moveCard(x, k, undefined, rer) })),
        ...(lanes.length ? [{ sep: true }, { lab: 'Move to ' + L.t.toLowerCase() }, ...lanes.map(k => ({ label: k, onPick: () => moveCard(x, g.of(x), k, rer) }))] : [])], { align: 'right' }); }));
  }
  function listHtml() {
    const p = P(), list = workList();
    const G = grp(), groups = G.cols(list).map(([k, t]) => [W.group + ':' + k, t, list.filter(x => G.of(x) === k).sort((a, b) => (a.due || '9').localeCompare(b.due || '9'))]).filter(g => g[2].length);
    const what = { open: 'open', closed: 'closed', all: '' }[lineShow()];
    return `<div class="factive"><span>${list.length} ${what ? what + ' ' : ''}item${list.length === 1 ? '' : 's'}</span>
        ${lineNow() !== FL.norm(FL.BASE) && list.length ? '<button class="link" id="clearAll" style="font-size:13px">Clear all</button>' : ''}</div>
      ${FL.needsMe(lineNow()) ? `<p class="fl-note" id="flMe">${FL.NO_ME}</p>` : ''}
      ${W.layout === 'board' ? (list.length ? boardHtml(list) : emptyHtml()) : groups.length ? groups.map(([w, gt, xs]) => { const open = W.open[w] !== false;
        return `<div class="group${open ? ' open' : ''}" data-ws="${esc(w)}"><button class="ghead" aria-expanded="${open}">${C.icon('chev', 's chev')}<span class="t">${esc(gt)}<span>${xs.length} item${xs.length === 1 ? '' : 's'}</span></span></button>
          <div class="gbody"><div><table class="items"><thead><tr><th>Item</th><th style="width:170px">Owner</th><th style="width:130px">Due</th><th style="width:100px">Priority</th><th style="width:120px">Status</th><th style="width:44px"><span class="sr">Client-visible</span></th></tr></thead><tbody>
          ${xs.map(x => `<tr tabindex="0" data-id="${x.id}" class="${UI.peek === x.id ? 'sel' : ''}"><td><div class="tcell"><span class="type ${x.type}" title="${D.TYPES[x.type]}">${x.type}</span><span>${esc(x.title)}<br><span class="meta">${x.id}${x.uc ? ' · use case ' + esc(x.uc) : ''}${x.ms ? ' · ' + esc(C.msName(x.ms)) : ''}</span></span></div></td>
            <td><button class="cell-pick" data-prop="owner" data-pick="${x.id}" aria-label="Owner of ${x.id}: ${esc(x.owner || 'none')}. Change"><span class="av">${C.initials(x.owner)}</span>${esc(x.owner || '—')}</button></td><td class="num"><button class="cell-pick" data-prop="due" data-pick="${x.id}" aria-label="Due date of ${x.id}: ${D.fd(x.due) || 'none'}. Change">${D.fd(x.due) || '—'}${x.due ? `<span class="due-l ${D.days(x.due) < 0 && C.isOpen(x) ? 'late' : ''}">${C.dueWords(x.due)}</span>` : ''}</button></td>
            <td><button class="cell-pick" data-prop="priority" data-pick="${x.id}" aria-label="Priority of ${x.id}: ${x.priority}. Change">${esc(x.priority)}</button></td><td><button class="cell-pick" data-prop="status" data-pick="${x.id}" aria-label="Status of ${x.id}. Change">${C.pill(C.look(x))}</button></td><td><button class="ib" data-weye="${x.id}" aria-pressed="${x.client}" aria-label="${x.client ? 'Shown to the client' : 'Not shown to the client'}: ${esc(x.title)}" title="${x.client ? 'In client reports. Select to hide' : 'Internal only. Select to show the client'}">${C.icon(x.client ? 'eye' : 'eyeoff', 's')}</button></td></tr>`).join('')}
          </tbody></table></div></div></div>`; }).join('') : emptyHtml()}${archHtml()}`;
  }
  /* Show archived (FR-43c, #166): the archived items under the list, in muted text, each with the word Archived; one opens read-only with Restore */
  const wArchOn = () => C.store.get('wArch', false);
  function archHtml() {
    if (!wArchOn()) return '';
    const xs = workList(undefined, true).sort((a, b) => a.id.localeCompare(b.id));
    return `<div class="arch-box" id="wArchList"><h2 class="arch-h">Archived <span>${xs.length} item${xs.length === 1 ? '' : 's'}</span></h2>${xs.length ? `<table class="items arch"><thead><tr><th>Item</th><th style="width:170px">Owner</th><th style="width:130px">Due</th><th style="width:120px">Status</th><th style="width:100px"><span class="sr">Archived</span></th></tr></thead><tbody>
      ${xs.map(x => `<tr tabindex="0" data-id="${x.id}" class="arch${UI.peek === x.id ? ' sel' : ''}"><td><div class="tcell"><span class="type ${x.type}" title="${D.TYPES[x.type]}">${x.type}</span><span>${esc(x.title)}<br><span class="meta">${x.id}${x.ms ? ' · ' + esc(C.msName(x.ms)) : ''}</span></span></div></td>
        <td>${esc(x.owner || '—')}</td><td class="num">${D.fd(x.due) || '—'}</td><td>${esc(x.status)}</td><td><span class="tag arch">${C.icon('archive', 's')}Archived</span></td></tr>`).join('')}</tbody></table>` : '<p class="muted">No archived items match.</p>'}</div>`;
  }
  /* an empty list says why it is empty and offers one way out (the single Clear control; the "Clear all" link above hides while this shows) */
  function emptyHtml() {
    const show = lineShow(), what = { open: 'open ', closed: 'closed ', all: '' }[show], extra = W.chips.filter(t => t !== FL.norm(FL.BASE)), q = qWords().join(' ');
    if (!extra.length && !q && show === 'open') return `<div class="empty"><p>No open items yet.</p></div>`;
    const why = q && !extra.length ? `“${esc(q)}”` : q ? `“${esc(q)}” with these filters` : 'these filters';
    return `<div class="empty"><p>No ${what}items match ${why}.</p><button class="btn" id="clearAll">${q && !extra.length && show === 'open' ? 'Clear search' : 'Clear the filters'}</button></div>`;
  }
  /* ── the filter line: saved views as tabs, the line with its chips, the suggestions, the hint chips ── */
  const HINTS = ['type:action', 'status:Open,Pending', '-status:Closed', 'no:owner', 'due:overdue', 'due:next-7-days', 'is:quiet', 'owner:me'];
  const vcount = line => workList(line).length;
  function viewsHtml() {
    if (FL.OPT.VIEWS !== 'tabs') return '';
    const vs = FL.views(UI.code), cur = vs.find(v => v.id === W.view), dirty = !!cur && FL.norm(cur.line) !== lineNow(), focusable = cur ? cur.id : vs[0]?.id;
    return `<div class="fvtabs" role="tablist" aria-label="Saved views">${vs.map(v => { const on = v.id === W.view, n = vcount(v.line);
      return `<button role="tab" class="fvtab" data-wv="${esc(v.id)}" aria-selected="${on}" tabindex="${v.id === focusable ? 0 : -1}" aria-controls="wlist" aria-label="${esc(v.name)}, ${n} item${n === 1 ? '' : 's'}${on && dirty ? ', changed and not saved' : ''}${FL.needsMe(v.line) ? '. ' + FL.NO_ME : ''}" title="${esc((on && dirty ? 'Changed since you saved it. ' : '') + (FL.needsMe(v.line) ? FL.NO_ME + ' ' : '') + 'Shows: ' + FL.sayLine(v.line))}"><span>${esc(v.name)}</span><em>${n}</em>${on && dirty ? '<i class="fvdot" aria-hidden="true" title="Changed since you saved it"></i>' : ''}</button>`; }).join('')}</div>
      <span class="fvacts">${dirty ? `<button class="btn sm" id="fvSave">Save view</button><button class="link" id="fvRevert">Discard changes</button>` : ''}<button class="link" id="fvNew">Save as a new view…</button></span>`;
  }
  const chipsHtml = () => W.chips.map((t, i) => { const c = FL.token(t), s = c.err ? t : FL.say(c);
    return `<span class="fchip" data-tok="${esc(t)}" title="${esc(s)}" data-gloss="${esc(t + ': ' + s)}"><span class="fc-t">${esc(t)}</span><button type="button" data-fx="${i}" aria-label="Remove the filter: ${esc(s)}">${C.icon('x', 's')}</button></span>`; }).join('');
  const holder = () => W.chips.length ? '' : 'Filter by keyword or by field';
  function lineHtml() {
    const key = FL.OPT.SLASH_KEY;
    return `<div class="fline-w${FL.OPT.HINTS === 'always' ? ' hints-always' : FL.OPT.HINTS === 'never' ? ' hints-never' : ''}" id="flw">
      <div class="fline" id="fline">${C.icon('filter', 's fl-ic')}<span class="fl-chips" id="flChips">${chipsHtml()}</span>
        <input id="fl" type="text" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="flList" aria-label="Filter work items" aria-describedby="flHelp" autocomplete="off" spellcheck="false" placeholder="${holder()}" value="${esc(W.q)}">
        <ul class="fl-list" id="flList" role="listbox" aria-label="Suggestions" hidden></ul></div>
      <p class="fl-err" id="flErr" hidden></p>
      <div class="fl-hints" id="flHints" role="group" aria-label="Examples to add">${HINTS.map(h => { const m = FL.say(FL.token(h)); return `<button type="button" class="fl-hint" data-hint="${esc(h)}" title="${esc(m)}" aria-label="${esc(h)}: ${esc(m)}" data-gloss="${esc(h + ': ' + m)}">${esc(h)}</button>`; }).join('')}<span class="fl-hw">Plain words search titles.${key ? `<span class="fl-key"> Press <kbd>${esc(key)}</kbd> to come back here.</span>` : ''}</span><span class="fl-gloss" id="flGloss" aria-hidden="true" hidden></span></div>
      <span class="sr" id="flHelp">Type a field such as status: and then a value, or plain words to search titles. The arrow keys choose a suggestion, Enter accepts it, Backspace in an empty box removes the last filter and Esc closes the list.</span>
      <span class="sr" id="flSay" role="status" aria-live="polite"></span></div>`;
  }
  /* the controls' state, set in place so the buttons survive a filter change */
  function syncBars() {
    C.$$('[data-layout]').forEach(b => b.setAttribute('aria-pressed', W.layout === b.dataset.layout));
    const nb = C.$('#newBtn'); if (nb) { const w = addWord(), t = lineType(), menu = t === 'all' || t === 'R'; nb.setAttribute('aria-label', w); nb.title = w; C.$('.w', nb).textContent = w; nb.classList.toggle('hasmenu', menu); menu ? nb.setAttribute('aria-haspopup', 'menu') : nb.removeAttribute('aria-haspopup'); if (menu && !C.$('.nch', nb)) nb.insertAdjacentHTML('beforeend', C.icon('chev', 's nch')); if (!menu) C.$('.nch', nb)?.remove(); }
    const vb = C.$('#viewBtn'); if (vb) { const t = `View: grouped by ${grp().t}${W.layout === 'board' && W.lane !== 'none' && W.lane !== W.group ? ', ' + LANES[W.lane].t.toLowerCase() + ' lanes' : ''}`; vb.setAttribute('aria-label', t); vb.title = t; }
    { const ab = C.$('#wArchBtn'); if (ab) { ab.setAttribute('aria-pressed', wArchOn()); C.$('em', ab).textContent = C.itemsAll().filter(x => x.archived).length; } }
  }
  C.views.work = {
    html() {
      const p = P(); lineLoad();
      return `<div class="crumbs">${esc(p.name)}</div><div class="head"><div><h1>Work items</h1><p>Select an item to open it beside the list. The eye shows or hides it from the client.</p></div>
        <div class="hacts">${C.ioBtn('impBtn', 'ul', 'Import from Excel')}${C.ioBtn('expBtn', 'dl', 'Export to Excel')}${C.addBtn('id="newBtn"', addWord(), lineType() === 'all' || lineType() === 'R')}</div></div>
      <div class="wctl" id="wctl">${FL.OPT.VIEWS === 'tabs' ? `<div class="fviews" id="fviews">${viewsHtml()}</div>` : ''}
        <div class="wbar">${lineHtml()}
        <button class="arch-pill" id="wArchBtn" aria-pressed="${wArchOn()}">${C.icon('archive', 's')}Show archived <em></em></button>
        <button class="btn" id="viewBtn" aria-haspopup="menu">${C.icon('rows', 's')} View ${C.icon('chev', 's')}</button>
        <div class="seg lay-sw" role="group" aria-label="Layout">${[['table', 'rows', 'Table'], ['board', 'board', 'Board']].map(([v, i, t]) => `<button class="tip" data-layout="${v}" aria-label="${t}" data-tip="${t}" aria-pressed="${W.layout === v}">${C.icon(i, 's')}</button>`).join('')}</div></div></div>
      <div id="wlist">${listHtml()}</div>`;
    },
    wire() {
      const ids = () => C.$$('tr[data-id]').map(r => r.dataset.id);
      const fl = C.$('#fl'), lst = C.$('#flList'), err = C.$('#flErr'), say = t => { const s = C.$('#flSay'); s.textContent = ''; setTimeout(() => { s.textContent = t; }, 30); };
      const wireList = () => {
        if (W.layout === 'board') wireBoard(rer);
        C.$('#clearAll')?.addEventListener('click', clr);
        C.$$('.ghead').forEach(h => h.addEventListener('click', () => { const g = h.parentElement, on = !g.classList.contains('open'); g.classList.toggle('open', on); h.setAttribute('aria-expanded', on); W.open[g.dataset.ws] = on; saveW(); }));
        /* owner, due, priority and status change in place, from the same pickers as the peek, each one step with Undo */
        C.$$('[data-pick]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); C.propPick(b, D.S.items.find(i => i.id === b.dataset.pick), 'in the table'); }));
        C.$$('tr[data-id]').forEach(r => { r.addEventListener('click', e => { if (e.target.closest('[data-weye], [data-pick]')) return; C.openItem(r.dataset.id, ids()); }); r.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); C.openItem(r.dataset.id, ids()); } }); });
        C.$$('[data-weye]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); const x = D.S.items.find(i => i.id === b.dataset.weye); const u = D.change('item', x, { client: !x.client }, D.who('with the eye')); C.refresh(); C.toast(`${x.id} ${x.client ? 'shown to' : 'hidden from'} the client`, u); }));
      };
      /* the chips and the views redraw with the list; the box itself is never redrawn, so it keeps the focus and what is typed */
      const wireLine = () => {
        C.$$('[data-fx]').forEach(b => b.addEventListener('click', () => { const t = W.chips[+b.dataset.fx], c = FL.token(t); W.chips.splice(+b.dataset.fx, 1); rer(); fl.focus(); gloss(null); say('Removed the filter: ' + (c.err ? t : FL.say(c))); }));
        C.$$('[data-wv]').forEach(b => {
          b.addEventListener('click', () => { const v = FL.views(UI.code).find(z => z.id === b.dataset.wv); if (!v) return; W.view = v.id; setLine(v.line); fl.value = W.q; showErr(''); rer(); C.$(`[data-wv="${CSS.escape(v.id)}"]`)?.focus(); });
          /* a tab row: ←/→ move between the views (and choose them), Home and End jump */
          b.addEventListener('keydown', e => { const tabs = C.$$('[data-wv]'), i = tabs.indexOf(b), j = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key]; if (j === undefined) return; e.preventDefault(); tabs[(j + tabs.length) % tabs.length].click(); });
        });
        C.$('#fvSave')?.addEventListener('click', () => { const vs = FL.views(UI.code), v = vs.find(z => z.id === W.view); if (!v) return; v.line = lineNow(); FL.viewsPut(UI.code, vs); rer(); C.toast(`View saved: ${v.name}`); C.$('[data-wv][aria-selected=true]')?.focus(); });
        C.$('#fvRevert')?.addEventListener('click', () => C.$(`[data-wv="${CSS.escape(W.view)}"]`)?.click());
        C.$('#fvNew')?.addEventListener('click', () => C.dialog(`<form id="fvF"><div class="dlg-h"><h2>Save as a new view</h2><p>The view keeps this filter line: ${esc(lineNow() || 'everything')}. It shows as a tab on this project's Work items, for you.</p></div>
          <div class="dlg-b"><div class="form"><label for="fvN">Name</label><input class="field" id="fvN" required placeholder="For example: Due this week"></div></div>
          <div class="dlg-f"><button type="button" class="btn quiet" data-close>Cancel</button><button class="btn pri">Save view</button></div></form>`, d => { C.$('#fvN', d).focus(); C.$('#fvF', d).addEventListener('submit', e => { e.preventDefault();
          const name = C.$('#fvN', d).value.trim(); if (!name) return; const vs = FL.views(UI.code), v = { id: 'v' + Date.now().toString(36), name, line: lineNow() }; vs.push(v); FL.viewsPut(UI.code, vs); W.view = v.id; d.close(); rer(); C.toast(`View saved: ${name}`); }); }));
      };
      const drawLine = () => { C.$('#flChips').innerHTML = chipsHtml(); fl.placeholder = holder(); const fv = C.$('#fviews'); if (fv) { const had = fv.contains(document.activeElement) && document.activeElement.dataset.wv; fv.innerHTML = viewsHtml(); if (had) C.$(`[data-wv="${CSS.escape(had)}"]`)?.focus(); } wireLine(); };
      /* a filter change: the list, the chips, the views and the labels only */
      const rer = () => { const oldC = C.$('.factive > span')?.textContent; saveW(); C.$('#wlist').innerHTML = listHtml(); drawLine(); syncBars(); wireList();
        /* the count line fades when a filter changes it (idea 9): the number only, opacity only */
        if (!C.reduce) { const nf = el => { el.classList.remove('n-chg'); void el.offsetWidth; el.classList.add('n-chg'); setTimeout(() => el.classList.remove('n-chg'), 300); };
          const c = C.$('.factive > span'); if (c && oldC && c.textContent !== oldC) nf(c); } };
      const clr = () => { const v0 = FL.views(UI.code).find(v => FL.norm(v.line) === FL.norm(FL.BASE)); if (v0) W.view = v0.id; setLine(FL.BASE); fl.value = ''; showErr(''); rer(); };

      /* ── the box: suggestions (fields, then values with counts), chips, plain-words errors ── */
      let opts = [], at = -1, open = false;
      const showErr = m => { err.hidden = !m; err.textContent = m || ''; fl.setAttribute('aria-invalid', !!m); fl.setAttribute('aria-describedby', m ? 'flHelp flErr' : 'flHelp'); C.$('#fline').classList.toggle('bad', !!m); };
      const openQ = () => (fl.value.match(/"/g) || []).length % 2 === 1;
      const cur = () => { const v = fl.value, ws = FL.words(v); return !ws.length || (/\s$/.test(v) && !openQ()) ? '' : ws[ws.length - 1]; };
      const replaceCur = s => { const w = cur(), v = fl.value; fl.value = (w ? v.slice(0, v.length - w.length) : v) + s; fl.setSelectionRange(fl.value.length, fl.value.length); };
      /* the counts are of the items the other filters leave, so a value's count is what choosing it would show */
      const baseFor = w => { const k = (w.replace(/^-/, '').split(':')[0] || '').toLowerCase(); return workList(W.chips.filter(t => FL.token(t).field !== k).join(' ')); };
      const close = () => { open = false; at = -1; lst.hidden = true; lst.innerHTML = ''; fl.setAttribute('aria-expanded', 'false'); fl.removeAttribute('aria-activedescendant'); };
      const draw = () => { const w = cur(); opts = FL.suggest(w, baseFor(w)).slice(0, 12); if (!opts.length) return close();
        open = true; if (at >= opts.length) at = opts.length - 1;
        if (at === 0) { const bare = v => v.replace(/"/g, '').toLowerCase(), ex = opts.findIndex(o => o.kind === 'value' && bare(o.ins) === bare(w)); if (ex > 0) at = ex; }   // a value typed in full is the one Enter takes
        lst.innerHTML = opts.map((o, i) => `<li role="option" id="flo-${i}" class="flo${i === at ? ' on' : ''}" aria-selected="${i === at}" data-o="${i}" aria-label="${esc(o.label + (o.note ? ', ' + o.note : '') + (o.n !== undefined ? `, ${o.n} item${o.n === 1 ? '' : 's'}` : ''))}"><b>${esc(o.label)}</b>${o.note ? `<span>${esc(o.note)}</span>` : ''}${o.n !== undefined ? `<em>${o.n}</em>` : ''}</li>`).join('');
        lst.hidden = false; fl.setAttribute('aria-expanded', 'true'); at >= 0 ? fl.setAttribute('aria-activedescendant', 'flo-' + at) : fl.removeAttribute('aria-activedescendant');
        C.$('#flo-' + at)?.scrollIntoView({ block: 'nearest' }); };
      /* the field words in the box become chips; a word with an error stays in the box with its message, never applied; plain words stay too */
      const commit = () => { const keep = [], errs = [], added = [];
        FL.words(fl.value).forEach(w => { if (!FL.isField(w)) return keep.push(w); const t = FL.token(w); if (t.err) { keep.push(w); errs.push(t.err); return; }
          /* a second filter on the same field, the same way round, takes the first one's place (is:closed after is:open shows closed items) */
          const i = W.chips.findIndex(c => { const o = FL.token(c); return o.field === t.field && !!o.not === !!t.not && !!o.none === !!t.none; });
          if (i >= 0) W.chips.splice(i, 1, t.text); else W.chips.push(t.text); added.push(FL.say(t)); });
        fl.value = keep.join(' '); W.q = fl.value; showErr(errs[0] || ''); close(); rer();
        if (errs.length) say(errs[0]); else if (added.length) say('Added the filter: ' + added.join('; ')); };
      const accept = o => { if (o.kind === 'field') { replaceCur(o.ins); at = 0; W.q = fl.value; showErr(''); draw(); } else { replaceCur(o.ins); commit(); } };
      /* while typing: plain words search at once; a field that does not exist is said straight away */
      fl.addEventListener('input', () => { W.q = fl.value; const w = cur();
        if (/\s$/.test(fl.value) && !openQ() && FL.words(fl.value).some(FL.isField)) return commit();
        /* an earlier word with an error keeps its message; the word being typed is only checked for its field */
        const ws = FL.words(fl.value), rest = w ? ws.slice(0, -1) : ws, old = rest.filter(FL.isField).map(FL.token).find(t => t.err);
        const t = FL.isField(w) && !/^-?no:/i.test(w) ? FL.token(w.replace(/:.*$/, ':x')) : null; showErr(old ? old.err : t && t.err && /There is no/.test(t.err) ? t.err : '');
        if (fl.value.trim()) { at = 0; draw(); } else close(); rer(); });
      fl.addEventListener('keydown', e => {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); if (!open) { at = 0; draw(); return; } at = (at + (e.key === 'ArrowDown' ? 1 : opts.length - 1)) % opts.length; draw(); return; }
        if (e.key === 'Enter') { e.preventDefault(); if (open && at >= 0 && opts[at]) accept(opts[at]); else commit(); return; }
        if (e.key === 'Escape') { if (open) { e.preventDefault(); e.stopPropagation(); close(); } return; }
        if (e.key === 'Backspace' && fl.selectionStart === 0 && fl.selectionEnd === 0 && W.chips.length) { e.preventDefault(); const t = W.chips.pop(), c = FL.token(t); rer(); say('Removed the filter: ' + (c.err ? t : FL.say(c))); return; }
        if (e.key === 'Tab') close();
      });
      fl.addEventListener('blur', () => setTimeout(() => { if (document.activeElement !== fl) close(); }, 150));
      lst.addEventListener('mousedown', e => e.preventDefault());   // a click on a suggestion keeps the cursor in the box
      lst.addEventListener('click', e => { const li = e.target.closest('[data-o]'); if (li) accept(opts[+li.dataset.o]); });
      C.$('#fline').addEventListener('click', e => { if (e.target === e.currentTarget || e.target.closest('.fl-ic')) fl.focus(); });
      C.$$('[data-hint]').forEach(b => { b.addEventListener('mousedown', e => e.preventDefault()); b.addEventListener('click', () => { fl.value = (fl.value.trim() ? fl.value.trim() + ' ' : '') + b.dataset.hint; commit(); fl.focus(); }); });

      /* a chip's plain meaning also shows in the hint line, not only on hover: when the chip (or its remove button) has the
         keyboard focus, when the mouse is on it, and when a finger touches it (a touch keeps it there until another one).
         A screen reader already hears it in the chip's label, so this line is hidden from it */
      const flw = C.$('#flw'), gl = C.$('#flGloss'), glossOf = el => el?.closest?.('#flw [data-gloss]') || null;
      const gloss = el => { gl.hidden = !el; gl.textContent = el ? el.dataset.gloss : ''; };
      flw.addEventListener('focusin', e => gloss(glossOf(e.target)));
      flw.addEventListener('focusout', e => { if (!glossOf(e.relatedTarget)) gloss(null); });
      flw.addEventListener('pointerover', e => { if (e.pointerType === 'mouse' && glossOf(e.target)) gloss(glossOf(e.target)); });
      flw.addEventListener('pointerout', e => { const el = glossOf(e.target); if (e.pointerType !== 'mouse' || !el || el.contains(e.relatedTarget)) return; gloss(glossOf(document.activeElement)); });
      flw.addEventListener('pointerdown', e => { if (e.pointerType !== 'mouse' && glossOf(e.target)) gloss(glossOf(e.target)); });

      C.$('#wArchBtn').addEventListener('click', () => { C.store.set('wArch', !wArchOn()); rer(); });
      C.$$('[data-layout]').forEach(b => b.addEventListener('click', () => { W.layout = b.dataset.layout; rer(); }));
      /* one View menu: Group by, and on the board the swimlanes */
      C.$('#viewBtn').addEventListener('click', e => C.menu(e.currentTarget, [{ lab: 'Group by' }, ...Object.entries(GROUPS).filter(([, g]) => !(W.layout === 'board' && g.table)).map(([k, g]) => ({ label: g.t, selected: grp() === g, onPick: () => { W.group = k; rer(); } })),
        ...(W.layout === 'board' ? [{ sep: true }, { lab: 'Swimlanes' }, ...Object.entries(LANES).filter(([k]) => k !== W.group).map(([k, l]) => ({ label: k === 'none' ? 'No lanes' : l.t + ' lanes', selected: W.lane === k, onPick: () => { W.lane = k; rer(); } }))] : [])], { select: true }));
      /* Add follows the type in the line: Add action or Add decision at once; Add item or Add risk or issue offers a menu */
      C.$('#newBtn').addEventListener('click', e => { const t = lineType(), ks = t === 'all' ? Object.keys(D.TYPES) : t === 'R' ? ['R', 'I'] : null; if (!ks) return newItem(t);
        C.menu(e.currentTarget, ks.map(k => ({ label: 'Add ' + D.TYPES[k].toLowerCase(), onPick: () => newItem(k) })), { align: 'right' }); });
      C.$('#expBtn').addEventListener('click', () => C.exportExcel()); C.$('#impBtn').addEventListener('click', () => C.importExcel());
      syncBars(); wireLine(); wireList();
    },
  };
  /* "/" on Work items puts the cursor in the filter line (FL.OPT.SLASH_KEY); everywhere else, and with a peek open, it opens ask clark as before */
  document.addEventListener('keydown', e => {
    const k = FL.OPT.SLASH_KEY; if (!k || e.key !== k || e.metaKey || e.ctrlKey || e.altKey) return;
    if (UI.view !== 'work' || UI.peek || C.typing(document.activeElement) || C.$('#dlg')?.open || C.popOpen() || (C.askIsOpen && C.askIsOpen())) return;
    const f = C.$('#fl'); if (!f) return; e.preventDefault(); e.stopImmediatePropagation(); f.focus(); f.setSelectionRange(f.value.length, f.value.length);
  }, true);
  /* so the ask clark button does not promise "/" on Work items: there it says Ctrl or Cmd + J */
  { const dt = C.drawTop; C.drawTop = () => { dt(); const b = C.$('#askBtn'), on = UI.view === 'work' && !!FL.OPT.SLASH_KEY, k = C.$('kbd', b); if (!b) return;
    b.title = on ? `Open ask clark (Ctrl or Cmd + J). Here, ${FL.OPT.SLASH_KEY} goes to the filter line` : 'Open ask clark (/ or Ctrl or Cmd + J)'; if (k) k.style.display = on ? 'none' : ''; }; }
  function newItem(type) {
    const p = P(), x = { id: C.nextId(type), code: p.code, type, ws: one('workstream') || p.ws[0], title: `New ${D.TYPES[type].toLowerCase()}`, owner: '', due: type === 'D' ? D.TODAY : D.addDays(D.TODAY, 7), status: D.STATUSES[type][0], priority: 'Medium', desc: '', update: '', updatedAt: D.stamp(), client: true, clientText: '', ms: '', uc: '', source: 'Added by hand in clark' };
    const u = D.create('item', x, D.who(W.layout === 'board' ? 'on the board' : 'in the table')); Object.assign(W, { type: 'all', show: 'open', q: '', f: {}, not: {} }); W.open[x.ws] = true; saveW(); C.render();
    C.changed(C.$(`tr[data-id="${x.id}"]`)); C.openItem(x.id, C.$$('tr[data-id]').map(r => r.dataset.id));
    setTimeout(() => { const t = C.$('#pkTitle'); if (t) { t.focus(); document.getSelection().selectAllChildren(t); } }, 60);
    C.toast(`${x.id} added`, u);
  }

  /* ═════════════ milestones: Plan and Movement ═════════════ */
  let mview = C.store.get('mview', 'plan'), msel = null;
  C.views.milestones = {
    html() {
      const p = P(), ms = C.mss(), open = ms.filter(m => !m.achievedOn), behind = open.filter(m => D.slip(m) > 0), over = open.filter(m => D.msState(m) === 'Overdue'), last = ms[ms.length - 1];
      const sentence = last ? `<b>${esc(last.name)}</b> is agreed for ${D.fd(last.agreed)}${D.slip(last) > 0 ? ` and now expected ${D.fd(D.expected(last))}` : ''}. ${ms.filter(m => m.achievedOn).length} achieved, ${open.length} to come.` : 'No milestones yet.';
      return `<div class="crumbs">${esc(p.name)}</div><div class="head"><div><h1>Milestones</h1><p>${sentence}</p></div>${C.addBtn('id="addMs"', 'Add milestone')}</div>
      <div class="wbar"><div class="seg" role="group" aria-label="View"><button data-mv="plan" aria-pressed="${mview === 'plan'}">Plan</button><button data-mv="move" aria-pressed="${mview === 'move'}">Movement</button></div><span class="muted mv-hint">${mview === 'move' ? 'Movement is for you and the team: it is never published.' : 'Every milestone sits on the line; a dashed ring shows where a slipped one is now expected.'}</span><span class="sp"></span><button class="arch-pill" id="mArchBtn" aria-pressed="${mArchOn()}">${C.icon('archive', 's')}Show archived <em>${C.mssAll().filter(m => m.archived).length}</em></button></div>
      ${mview === 'plan' ? `<div class="card">${C.msViewsHtml(ms, 'page')}${msDetailsHtml(ms, false, 'page')}</div>` : moveHtml(ms, open, behind, over)}${msArchHtml()}`;
    },
    wire() {
      C.$('#addMs').addEventListener('click', () => { const p = P(), id = D.nextMsId(p.code), d = D.addDays(D.TODAY, 30);
        const m = { key: p.code + '/' + id, id, code: p.code, name: 'New milestone', ws: p.ws[0], agreed: d, original: d, forecast: d, achievedOn: '', manual: '', progress: null, desc: '', owner: '', client: true, clientText: '' };
        const u = D.create('ms', m, D.who('on the milestones page')); C.refresh(); C.openMs(m.id); setTimeout(() => { const t = C.$('#pkTitle'); if (t) { t.focus(); document.getSelection().selectAllChildren(t); } }, 60); C.toast('Milestone added', u); });
      C.$$('[data-mv]').forEach(b => b.addEventListener('click', () => { mview = b.dataset.mv; C.store.set('mview', mview); C.render(); }));
      C.$('#mArchBtn').addEventListener('click', () => { C.store.set('mArch', !mArchOn()); C.render(); C.$('#mArchBtn')?.focus(); });
      { const ids = C.$$('#mArchList [data-ms]').map(b => b.dataset.ms); C.$$('#mArchList [data-ms]').forEach(b => b.addEventListener('click', () => C.openMs(b.dataset.ms, ids))); }
      if (mview === 'plan') { const tl = C.$('[data-tl]'); C.timeline(tl, C.mss(), { key: 'page' }); wireMsList(tl.closest('.card'), C.mss(), 'page'); C.wireMsViews(tl.closest('.card'), C.mss()); }
      else wireMove();
    },
  };
  /* Show archived (FR-43c, #166): the archived milestones in muted text, each with the word Archived and the work items that still link to it */
  const mArchOn = () => C.store.get('mArch', false);
  function msArchHtml() {
    if (!mArchOn()) return '';
    const ms = C.mssAll().filter(m => m.archived), n = m => C.items().filter(x => x.ms === m.id).length;
    return `<div class="card arch-box" id="mArchList"><h2 class="arch-h">Archived <span>${ms.length} milestone${ms.length === 1 ? '' : 's'}</span></h2>${ms.length ? `<ul class="arch-l">${ms.map(m => `<li class="arch"><button class="link" data-ms="${esc(m.id)}">${esc(m.name)}</button><span class="tag arch">${C.icon('archive', 's')}Archived</span><span>Agreed ${D.fd(m.agreed)} · ${n(m)} work item${n(m) === 1 ? '' : 's'} still linked</span></li>`).join('')}</ul>` : '<p class="muted">No archived milestones.</p>'}</div>`;
  }
  function moveHtml(ms, open, behind, over) {
    if (!open.length) return '<div class="card"><p class="muted">Every milestone is achieved.</p></div>';
    const worst = open.slice().sort((a, b) => D.slip(b) - D.slip(a))[0];
    const all = open.flatMap(m => [m.original, m.agreed, m.forecast]).concat(D.TODAY).sort();
    const s0 = new Date(D.addDays(all[0], -10) + 'T00:00:00'); s0.setDate(1); const start = D.toIso(s0), e0 = new Date(D.addDays(all[all.length - 1], 20) + 'T00:00:00'); e0.setMonth(e0.getMonth() + 1, 1); const end = D.toIso(e0);
    const pc = iso => ((D.days(iso) - D.days(start)) / (D.days(end) - D.days(start)) * 100).toFixed(2) + '%';
    const months = []; const c = new Date(start + 'T00:00:00'); while (D.toIso(c) < end) { months.push(D.toIso(c)); c.setMonth(c.getMonth() + 1); }
    if (!msel || !open.some(m => m.id === msel)) msel = (behind[0] || open[0]).id;
    const sel = open.find(m => m.id === msel), moves = D.S.history.filter(h => h.kind === 'ms' && h.id === sel.id && h.code === sel.code && ['agreed', 'forecast', 'achievedOn'].includes(h.field));
    return `<div class="card"><div class="card-h"><h2>Movement</h2><span class="tag info">Internal only: never published</span></div>
      <p style="font-size:16px;margin:0 0 14px">${behind.length} of ${open.length} open milestones are behind their agreed date; ${over.length} overdue.${D.slip(worst) > 0 ? ` <b>${esc(worst.name)}</b> is <b>${C.dy(D.slip(worst))}</b> behind the agreed date and ${C.dy(D.days(worst.forecast) - D.days(worst.original || worst.agreed))} behind the original.` : ''}</p>
      <div class="mv-move" role="list"><div class="hd">Milestone</div><div class="hd" style="position:relative">${months.map(m => `<span style="position:absolute;left:${pc(m)}">${new Date(m + 'T00:00:00').toLocaleDateString('en-GB', { month: 'short' })}</span>`).join('')}&nbsp;</div><div class="hd">Variance</div>
        ${open.map(m => { const st = D.msState(m), sl = D.slip(m);
          return `<div class="mvrow${m.id === msel ? ' sel' : ''}" data-msel="${m.id}" role="listitem" tabindex="0"><div class="lbl"><b>${esc(m.name)}</b><span class="mst ${C.msCls(st)}" style="font-size:12px">${C.msMark(st)}${st}</span><div class="muted" style="font-size:12px">Agreed ${D.fd(m.agreed)}${sl > 0 ? ' · forecast ' + D.fd(m.forecast) : ''}</div></div>
            <div class="mvtrack">${months.map(mo => `<span class="grid" style="left:${pc(mo)}"></span>`).join('')}<span class="td" style="left:${pc(D.TODAY)}"></span>
              ${m.original && m.original !== m.agreed ? `<span class="og" style="left:${pc(m.original)}" title="Original ${D.fd(m.original)}"></span>` : ''}<span class="ag" style="left:${pc(m.agreed)}" title="Agreed ${D.fd(m.agreed)}"></span>
              ${sl > 0 ? `<span class="sl" style="left:${pc(m.agreed)};width:calc(${pc(m.forecast)} - ${pc(m.agreed)})"></span>` : ''}<span class="fc" style="left:${pc(m.forecast || m.agreed)}" title="Forecast ${D.fd(m.forecast || m.agreed)}">${C.msMark(st)}</span></div>
            <div class="var ${sl > 0 ? 'late' : 'ok'}">${sl > 0 ? `<b>${C.dy(sl)}</b> after the agreed date` : sl < 0 ? `<b>${C.dy(-sl)}</b> before the agreed date` : '<b>On the agreed date</b>'}<br><span class="muted">${m.original && m.original !== m.agreed ? 'Agreed date moved' : 'Never moved'}</span></div></div>`; }).join('')}</div>
      <div class="mvkey"><span>◇ Original (if the agreed date moved)</span><span>| Agreed</span><span>Forecast, shaped by state</span><span style="color:var(--status-red-text)">— Distance past agreed</span><span>│ Today</span></div></div>
    <div class="card"><div class="card-h"><h2>${esc(sel.name)}</h2><span class="mst ${C.msCls(D.msState(sel))}">${C.msMark(D.msState(sel))}${D.msState(sel)}</span><span class="sp"></span><button class="btn sm" data-msedit="${sel.id}">Edit milestone</button></div>
      <div class="mp-chips"><span>Original <b>${D.fd(sel.original || sel.agreed)}</b></span><span>Agreed <b>${D.fd(sel.agreed)}</b></span><span>Forecast <b>${D.fd(sel.forecast || sel.agreed)}</b></span><span>${moves.length ? `Moved <b>${moves.length} ${moves.length === 1 ? 'time' : 'times'}</b>` : '<b>Never moved</b>'}</span><span>Progress <b>${sel.progress == null ? 'not set' : sel.progress + '%'}</b></span><span>Owner <b>${esc(sel.owner || 'not set')}</b></span></div>
      <h3 style="font-size:15px;font-weight:500;margin:4px 0 6px">What changed</h3>${moves.length ? `<ul class="feed">${moves.slice().reverse().map(h => `<li><span class="fi">${C.icon('cal', 's')}</span><span><b>${esc(h.how)}</b> moved the ${h.field === 'agreed' ? 'agreed date' : h.field === 'forecast' ? 'forecast' : 'achieved date'} from ${D.fd(h.from) || 'none'} to ${D.fd(h.to) || 'none'} <span class="t">· ${D.fd(h.at.slice(0, 10))}</span></span></li>`).join('')}</ul>` : '<p class="muted" style="font-size:14px">Nothing has changed since it was first agreed.</p>'}
      <h3 style="font-size:15px;font-weight:500;margin:14px 0 4px">Decide what to do</h3><p class="muted" style="font-size:13px;margin:0 0 8px">Each choice changes the record at once, with Undo.</p>
      <div class="decide"><button class="btn" data-dec="hold">Hold: keep the forecast, agreed date unchanged</button><button class="btn pri" data-dec="rebase" ${D.slip(sel) > 0 ? '' : 'disabled'}>Move the agreed date</button><button class="btn" data-dec="recover">Add a recovery action</button><button class="btn" data-dec="escalate">Escalate to steering</button></div>
      <h3 style="font-size:15px;font-weight:500;margin:16px 0 4px">Internal note</h3><textarea class="field" id="mvNote" placeholder="What is going on, what you are waiting for">${esc(sel.note || '')}</textarea><p class="muted" style="font-size:12px;margin:4px 0 0">Saves when you leave the box. Never published.</p></div>`;
  }
  function wireMove() {
    C.$$('[data-msel]').forEach(r => { r.addEventListener('click', () => { msel = r.dataset.msel; C.render(); }); r.addEventListener('keydown', e => { if (e.key === 'Enter') { msel = r.dataset.msel; C.render(); } }); });
    const m = C.mss().find(x => x.id === msel); if (!m) return;
    C.$('[data-msedit]').addEventListener('click', () => C.openMs(m.id));
    C.$('#mvNote').addEventListener('change', e => { const u = D.change('ms', m, { note: e.target.value.trim() }, D.who('in Movement')); C.refresh(); u && C.toast('Note saved', u); });
    C.$$('[data-dec]').forEach(b => b.addEventListener('click', () => {
      const p = P(), k = b.dataset.dec;
      if (k === 'hold') { const u = D.change('ms', m, { note: ((m.note ? m.note + '\n' : '') + `${D.fd(D.TODAY)}: holding; agreed date unchanged, forecast ${D.fd(m.forecast)}.`) }, D.who('in Movement')); C.refresh(); C.toast('Hold recorded in the note', u); }
      if (k === 'rebase') { const to = D.expected(m) || m.forecast, u = D.change('ms', m, { agreed: to, forecast: to, original: m.original || m.agreed }, D.who('in Movement')); C.refresh(); C.toast(`${m.name}: the agreed date is now ${D.fd(to)}`, u); }
      if (k === 'recover' || k === 'escalate') {
        const type = k === 'recover' ? 'A' : 'D', x = { id: C.nextId(type), code: p.code, type, ws: m.ws, title: k === 'recover' ? `Recover ${m.name.charAt(0).toLowerCase() + m.name.slice(1)}` : `Steering decision on ${m.name.charAt(0).toLowerCase() + m.name.slice(1)}`, owner: '', due: D.addDays(D.TODAY, 7), status: D.STATUSES[type][0], priority: 'High', desc: `${m.name} is ${C.dy(D.slip(m))} behind its agreed date.`, update: '', updatedAt: D.stamp(), client: true, clientText: '', ms: m.id, uc: '', source: 'Movement, ' + m.name };
        const u = D.create('item', x, D.who('in Movement')); C.refresh(); C.openItem(x.id); C.toast(`${x.id} added and linked to ${m.name}`, u);
      }
    }));
  }

  /* AI sign-in (#54: "include logging into Claude and OpenAI as options for AI using ask clark"; "ChatGPT sign-in
     too"): a card per provider, a connect box that tests the sign-in and lists the models, Disconnect, and the model for ask clark.
     In the prototype nothing is sent and no key is kept: Connect only records that the provider is connected. */
  const AI_PROVS = [['claude', 'Claude', ['Claude subscription', 'API key'], 'Through your Claude subscription (the Claude command) or an API key.'],
    ['openai', 'OpenAI', ['API key', 'ChatGPT sign-in'], 'Coming in a later version, with an API key or your ChatGPT sign-in.', 1]];   /* until v0.5, Claude only (the owner; BRD FR-63a) */
  const AI_MODELS = { claude: [['claude-opus', 'Claude Opus 5.5', 1], ['claude-sonnet', 'Claude Sonnet 5.5'], ['claude-haiku', 'Claude Haiku 5.5']], openai: [['oa-flagship', 'OpenAI flagship'], ['oa-small', 'OpenAI small']] };
  const aiConn = () => C.store.get('aiConn', {});
  const aiModels = () => Object.keys(aiConn()).flatMap(k => (AI_MODELS[k] || []).filter(([v]) => (aiConn()[k].ids || []).includes(v)));
  function aiConnect(k) {
    const [, n, hows] = AI_PROVS.find(x => x[0] === k);
    C.dialog(`<form id="aiF"><div class="dlg-h"><h2>Connect ${n}</h2><p>The passages ask clark and the AI menu send go to ${n}: they leave this computer and are billed to that account. The key is kept in this Mac's keychain, never in clark's files, backups or the repo, and is never shown again.</p></div>
      <div class="form"><label>How</label><span class="seg">${hows.map((h, i) => `<button type="button" data-how="${esc(h)}" aria-pressed="${!i}">${h}</button>`).join('')}</span>
      <label for="aiKey" id="aiKeyL">Key</label><input class="field" id="aiKey" type="password" autocomplete="off" placeholder="Paste your key"></div><p class="muted" id="aiMsg" style="font-size:13px" role="alert"></p>
      <div class="dlg-f"><button type="button" class="btn quiet" data-close>Cancel</button><button class="btn pri">Test and connect</button></div></form>`, d => {
      let how = hows[0]; const sync = () => { const sign = /subscription|sign-in/.test(how); C.$('#aiKey', d).hidden = C.$('#aiKeyL', d).hidden = sign; };
      C.$$('[data-how]', d).forEach(b => b.addEventListener('click', () => { how = b.dataset.how; C.$$('[data-how]', d).forEach(z => z.setAttribute('aria-pressed', z === b)); sync(); })); sync();
      C.$('#aiF', d).addEventListener('submit', e => { e.preventDefault(); const key = C.$('#aiKey', d).value.trim();
        if (!/subscription|sign-in/.test(how) && key.length < 12) { C.$('#aiMsg', d).textContent = `${n} did not accept this key (401). Check you copied all of it, and that it has not been revoked.`; return; }
        const all = aiConn(); all[k] = { how, models: AI_MODELS[k].map(m => m[1]), ids: AI_MODELS[k].map(m => m[0]) }; C.store.set('aiConn', all); if (!C.store.get('aiModel', '')) C.store.set('aiModel', AI_MODELS[k][0][0]);
        d.close(); C.render(); C.toast(`${n} connected (prototype: nothing was sent and no key was kept)`); });
    });
  }
  /* ═════════════ Settings › clark version and updates, and Diagnostics ("add an 'update' functionality to settings like
     creaite" and "add logging to the application - log or debug set in settings"). Both are simulated: no real file is read or written. ═════════════ */
  const CLARK_VER = '0.2.0', RELZIP = /^clark-(\d+)\.(\d+)\.(\d+)\.zip$/;
  const vnum = v => String(v).split('.').reduce((a, x) => a * 1000 + Number(x || 0), 0);
  const updSt = () => ({ ver: CLARK_VER, found: '', last: null, ...C.store.get('upd', {}) });
  const updSave = o => C.store.set('upd', { ...updSt(), ...o });
  C.version = () => updSt().ver;
  const nowText = () => { const d = new Date(); return `${D.fd(D.toIso(d))} ${D.pad(d.getHours())}:${D.pad(d.getMinutes())}`; };
  /* what a release holds (made up, the same for any version number) */
  const relInfo = v => ({ date: D.fd(D.addDays(D.TODAY, -1)), replaced: 12 + vnum(v) % 7, added: 2 + vnum(v) % 3,
    notes: ['Work items can be grouped by milestone on the board.', 'Publish remembers the last folder you chose.', 'Small fixes to the contents list and to keys in the editor.'] });
  const updMsg = (t, bad) => { const m = C.$('#updMsg'); if (m) { m.className = 'upd-msg' + (bad ? ' bad' : ''); m.textContent = t || ''; } };
  function updCard() {
    const u = updSt(), newer = u.found && vnum(u.found) > vnum(u.ver);
    return `<div class="card" id="update"><div class="card-h"><h2>clark version and updates</h2></div><p class="muted" style="font-size:14px;margin:-4px 0 12px">Your projects, settings and published reports are kept when clark is updated.</p>
      <div class="form wide"><span class="fl">Installed</span><div class="fc"><b style="font-weight:500" id="updVer">clark ${esc(u.ver)}</b></div>
        <span class="fl">Update</span><div class="fc">${newer ? `<button class="btn pri sm" id="updReview">Review ${esc(u.found)}</button>` : '<span class="muted" id="updNone">Up to date</span>'}<small>${newer ? `clark ${esc(u.found)} is ready to install` : 'Download the new clark from the release page, then choose the zip below'}</small>
          ${newer ? '' : '<button class="link" id="updSim">Simulate a new release</button>'}</div>
        <span class="fl">Install from a file</span><div class="fc"><button class="btn sm" id="updFile">Choose zip…</button><input type="file" id="updPick" accept=".zip" hidden aria-label="Choose a clark release zip"><small>The clark-X.Y.Z.zip attached to the release, not the source code zip</small></div>
        ${u.last ? `<span class="fl">Last update</span><div class="fc"><span id="updLast">${esc(u.last.from)} → ${esc(u.last.to)}, ${esc(u.last.at)}</span><button class="btn sm" id="updUndo">Undo update</button></div>` : ''}</div>
      <div id="updMsg" role="status"></div>
      <p class="muted" style="font-size:13px;margin:12px 0 0">How it works for real: a release is checked file by file against its list of checksums before anything changes.</p></div>`;
  }
  function updReview(to) {
    const from = updSt().ver, r = relInfo(to);
    C.dialog(`<div class="dlg-h"><h2>clark ${esc(from)} → ${esc(to)}</h2><p>Released ${esc(r.date)}</p></div>
      <div class="dlg-b"><b style="font-weight:500">What's new</b><ul class="upd-notes">${r.notes.map(n => `<li>${esc(n)}</li>`).join('')}</ul><button class="btn sm" id="updNotes">Copy the notes</button>
        <p class="muted" style="margin:12px 0 0">${r.replaced} files replaced, ${r.added} added.</p>
        <p class="upd-kept"><b>Your projects, settings and published reports are kept.</b> Everything is backed up first, and if a step fails clark puts the old version back.</p></div>
      <div class="dlg-f"><button type="button" class="btn quiet" data-close id="updCancel">Cancel</button><button class="btn pri" id="updGo">Install clark ${esc(to)}</button></div>`, d => {
      C.$('#updNotes', d).addEventListener('click', () => { const t = `clark ${to}\n` + r.notes.map(n => '- ' + n).join('\n'); (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(() => C.toast('Notes copied'), () => C.toast("Couldn't copy the notes")); });
      C.$('#updGo', d).addEventListener('click', e => { e.currentTarget.disabled = true; e.currentTarget.textContent = 'Installing…'; C.$('#updCancel', d).disabled = true;
        setTimeout(() => { const was = updSt().ver; updSave({ ver: to, found: '', last: { from: was, to, at: nowText() } }); C.log('info', 'update', `installed ${to} from ${was}`);
          d.close(); C.refresh(); C.toast(`Prototype: clark ${to} is installed. Restart clark to finish.`); }, C.reduce ? 60 : 900); });
    });
  }
  function updUndo(btn) {
    if (!btn.dataset.armed) { btn.dataset.armed = '1'; btn.textContent = 'Confirm undo'; btn.classList.add('danger');
      setTimeout(() => { if (btn.isConnected && btn.dataset.armed) { delete btn.dataset.armed; btn.textContent = 'Undo update'; btn.classList.remove('danger'); } }, 5000); return; }
    const l = updSt().last; if (!l) return;
    updSave({ ver: l.from, last: null }); C.log('info', 'update', `undone, back to ${l.from}`); C.refresh(); C.toast(`Prototype: update undone, clark ${l.from} is back. Restart clark to finish.`);
  }
  function updWire() {
    C.$('#updSim')?.addEventListener('click', () => { updSave({ found: '0.3.0' }); C.refresh(); });
    C.$('#updReview')?.addEventListener('click', () => updReview(updSt().found));
    C.$('#updFile').addEventListener('click', () => C.$('#updPick').click());
    C.$('#updPick').addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; if (!f) return;
      const m = RELZIP.exec(f.name); if (!m) { updMsg("That isn't a clark release. Download clark-X.Y.Z.zip from the release page, not the source code zip.", true); return; }
      const v = `${m[1]}.${m[2]}.${m[3]}`, cur = updSt().ver;
      if (vnum(v) <= vnum(cur)) { updMsg(`clark ${v} is not newer than the installed clark ${cur}.`, true); return; }
      updMsg(''); updReview(v); });
    C.$('#updUndo')?.addEventListener('click', e => updUndo(e.currentTarget));
  }
  /* Diagnostics: the report holds the version, the log level, counts, safe settings (never names, emails or report text) and the last 20 log lines */
  C.diagText = () => {
    const ua = navigator.userAgent, bro = (/(Edg|Chrome|Firefox)\/([\d.]+)/.exec(ua) || /(Version)\/([\d.]+)/.exec(ua) || []), name = { Edg: 'Edge', Version: 'Safari' }[bro[1]] || bro[1] || 'unknown';
    const os = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || 'unknown';
    const arch = rs => rs.filter(r => r.archived).length, live = rs => rs.length - arch(rs);
    return ['clark diagnostics (prototype)', `Version: clark ${C.version()}`, `Browser: ${name} ${bro[2] || ''}`.trim(), `System: ${os}`, `Log level: ${C.logLevel() === 'debug' ? 'Debug' : 'Normal'}`,
      `Counts: ${live(D.S.projects)} projects, ${live(D.S.items)} work items, ${live(D.S.milestones)} milestones`, `Archived, not in the counts: ${arch(D.S.projects)} projects, ${arch(D.S.items)} work items, ${arch(D.S.milestones)} milestones`,
      `Settings: appearance ${C.themePref()}, section style ${C.secs()}, layout ${D.S.projects.map(p => `${p.code} ${C.layOf(p)}`).join(', ') || 'none'}`,
      '', 'Last 20 log lines:', ...(C.logLines(20).length ? C.logLines(20) : ['(none)'])].join('\n');
  };
  function dgCard() {
    const lv = C.logLevel(), since = C.store.get('logLevelSince', 0), days = since ? Math.floor((Date.now() - since) / 864e5) : 0, errs = C.logErrors(7);
    return `<div class="card" id="diagnostics"><div class="card-h"><h2>Diagnostics</h2></div>
      <div class="form wide"><span class="fl" id="dgLvLab">Log level</span><div class="fc"><div class="seg" role="group" aria-labelledby="dgLvLab">${[['info', 'Normal'], ['debug', 'Debug']].map(([v, t]) => `<button data-ll="${v}" aria-pressed="${lv === v}">${t}</button>`).join('')}</div>
          <small>Debug adds detail for fixing problems. Logs hold only counts, IDs and times, never your report text, names or keys.</small>${lv === 'debug' && since && days >= 7 ? `<div class="dg-note" id="dgOld">Debug has been on for ${days} days. Switch back to Normal when you're done.</div>` : ''}</div>
        <span class="fl">Log folder</span><div class="fc"><span>clark’s own log folder</span><button class="btn sm" id="dgOpen">Open the folder</button></div>
        <span class="fl">Report</span><div class="fc"><button class="btn sm" id="dgCopy">Copy diagnostics</button><small>The version, counts, safe settings and the last 20 log lines, for pasting into a chat: no names, emails or report text.</small></div>
        <span class="fl">Errors in the last 7 days</span><div class="fc" id="dgErrs">${errs.length ? `<ul class="dg-errs">${errs.slice(-5).reverse().map(l => `<li>${esc(l)}</li>`).join('')}</ul>` : '<span class="muted">None</span>'}</div></div>
      <p class="muted" style="font-size:13px;margin:12px 0 0">clark keeps one log a day (5 MB at most) and keeps 7 days.</p></div>`;
  }
  function dgWire() {
    C.$$('[data-ll]').forEach(b => b.addEventListener('click', () => { const v = b.dataset.ll, was = C.logLevel(), wasSince = C.store.get('logLevelSince', 0); if (v === was) return;
      C.store.set('logLevel', v); C.store.set('logLevelSince', v === 'debug' ? Date.now() : 0); C.log('info', 'settings', 'log level ' + v); C.refresh();
      C.toast('Log level: ' + (v === 'debug' ? 'Debug' : 'Normal'), () => { C.store.set('logLevel', was); C.store.set('logLevelSince', wasSince); C.log('info', 'settings', 'log level ' + was); }); }));
    C.$('#dgOpen').addEventListener('click', () => C.toast('Prototype: would open the log folder in Finder'));
    C.$('#dgCopy').addEventListener('click', () => { const t = C.diagText(); C.log('info', 'diag', 'report copied');
      const fallback = () => C.dialog(`<div class="dlg-h"><h2>Diagnostics</h2><p>The browser would not copy it for you. Select all and copy.</p></div><div class="dlg-b"><textarea class="field dg-rep" id="dgRep" readonly aria-label="Diagnostics report"></textarea></div><div class="dlg-f"><button class="btn pri" data-close>Done</button></div>`, d => { const a = C.$('#dgRep', d); a.value = t; a.select(); });
      try { navigator.clipboard.writeText(t).then(() => C.toast('Diagnostics copied: paste them into the chat'), fallback); } catch (e) { fallback(); } });
  }

  /* ── Published reports (FR-83a, #120): every publish of the open project, newest first, with its number, when, where, who and a kept copy to Open.
     The last 10 pages are kept (in this browser's database); an older publication keeps its row but not its page. ── */
  C.openPub = n => { const p = C.P(), cp = D.pubCopy(p.code, n); if (!cp) return C.toast('That copy is no longer kept.');
    const url = URL.createObjectURL(new Blob([cp.html], { type: 'text/html' })); const w = window.open(url, '_blank'); if (!w) C.toast('Your browser blocked the new tab'); setTimeout(() => URL.revokeObjectURL(url), 60000); };
  const pubsCard = p => { const pubs = (p.published || []).map((r, i) => ({ r, n: D.pubNo(p, i) })).reverse();
    return `<div class="card" id="pubs"><div class="card-h"><h2>Published reports · ${esc(p.name)}</h2></div><p class="muted" style="font-size:14px;margin:-4px 0 12px">Every time you publish, the report gets the next number for this project and a copy of the page is kept. Open shows the copy as it was published. The last ${D.PUB_KEEP} copies are kept.</p>
      ${pubs.length ? `<table class="set stack ppl"><thead><tr><th>#</th><th>Date and time</th><th>Where</th><th>Who</th><th></th></tr></thead><tbody>${pubs.map(({ r, n }) => `<tr data-pub="${n}"><td class="nm" data-l="Publication"><b style="font-weight:500">${n}</b></td><td data-l="Date and time">${D.fd(r.at.slice(0, 10))} ${esc(r.at.slice(11))}</td><td data-l="Where">${esc(r.where || (r.client ? 'Local and to client' : 'Local'))}${r.word ? ' · Word' : ''}${r.pdf ? ' · PDF' : ''}</td><td data-l="Who">${esc(r.who || 'Not recorded')}</td>
        <td class="acts">${D.pubCopy(p.code, n) ? `<button class="btn sm" data-pubopen="${n}">Open</button>` : '<span class="muted">Not kept</span>'}</td></tr>`).join('')}</tbody></table>` : '<p class="muted" id="pubsNone">Nothing published yet. Each publish is listed here with its number.</p>'}</div>`; };
  /* ── People (FR-31a, v0.5; a light simulation): a table from the distinct owners in the data, details by name, "Needs details" where the email is empty, and a paste from Excel ── */
  C.peopleRows = () => { const det = D.S.people || {}, names = new Map(C.people(true).map(n => [n.toLowerCase(), n]));
    Object.keys(det).forEach(k => { if (!names.has(k.toLowerCase())) names.set(k.toLowerCase(), k); });
    return [...names.values()].sort((a, b) => a.localeCompare(b)).map(name => ({ name, email: (det[name] || {}).email || '', org: (det[name] || {}).org || '', role: (det[name] || {}).role || '' })); };
  let ppOnly = false;   /* the People list filtered to those who need details: the only time a row carries the chip (S4) */
  const peopleCard = () => { const rows = C.peopleRows(), need = rows.filter(r => !r.email).length, shown = ppOnly && need ? rows.filter(r => !r.email) : rows, one = rows.length === 1;
    return `<div class="card" id="people"><div class="card-h"><h2>People</h2><span class="sp"></span><button class="btn sm" id="ppPasteBtn" aria-expanded="false" aria-controls="ppPaste">Paste from Excel</button></div><p class="muted" style="font-size:14px;margin:-4px 0 12px">Everyone who owns a work item or a milestone. Owners are still picked by name. Add an email, organisation and role so people can be found and emailed.</p>
      <div class="pp-paste" id="ppPaste" hidden><label for="ppText">Rows from Excel: name, email, organisation, role, separated by tabs</label><textarea class="field" id="ppText" rows="5" placeholder="Sam Rivers[tab]sam@example.com[tab]Supplier[tab]Delivery lead"></textarea><div class="pp-acts"><button class="btn sm pri" id="ppAdd">Add to the list</button><span class="muted" id="ppMsg" role="status"></span></div></div>
      ${rows.length ? `<p class="pp-sum" id="ppCount"><span>${need} of ${rows.length} ${one ? 'person needs' : 'people need'} details</span>${need || ppOnly ? ` <button type="button" class="link" id="ppOnly" aria-pressed="${ppOnly && need ? 'true' : 'false'}">${ppOnly && need ? 'Show everyone' : 'Show only these'}</button>` : ''}</p>
      <table class="set stack ppl" id="ppTable"><thead><tr><th>Name</th><th>Email</th><th>Organisation</th><th>Role</th></tr></thead><tbody>${shown.map(r => `<tr data-person="${esc(r.name)}"><td class="nm"><b style="font-weight:500">${esc(r.name)}</b>${ppOnly && !r.email ? ' <span class="tag need">Needs details</span>' : ''}</td><td data-l="Email">${esc(r.email) || '<span class="muted">—</span>'}</td><td data-l="Organisation">${esc(r.org) || '<span class="muted">—</span>'}</td><td data-l="Role">${esc(r.role) || '<span class="muted">—</span>'}</td></tr>`).join('')}</tbody></table>
      ` : '<p class="muted">No owners yet.</p>'}</div>`; };
  /* ═════════════ settings (simple) ═════════════ */
  /* go to a card, or to a field in one (Help's Settings links, the Publish box's "Set it in Settings, Publishing"): scrolled clear of the bars, and the field takes the focus */
  C.settingsGo = id => { const el = document.getElementById(id); if (!el) return false; const field = /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName);
    el.scrollIntoView({ block: field ? 'center' : 'start', behavior: C.reduce ? 'auto' : 'smooth' });
    if (!field) el.setAttribute('tabindex', '-1'); el.focus({ preventScroll: true }); C.$$('[data-sn]').forEach(a => a.removeAttribute('aria-current')); C.$(`[data-sn="${field ? (el.closest('.card') || {}).id : id}"]`)?.setAttribute('aria-current', 'location'); return true; };
  /* the link of the card you are reading is marked as you scroll */
  let spyOn = false;
  function settingsSpy() { const mark = () => { if (UI.view !== 'settings') return; const links = C.$$('[data-sn]'); if (!links.length) return;
      const edge = C.$('.set-nav').getBoundingClientRect().bottom + 24; let cur = links[0];
      links.forEach(a => { const el = document.getElementById(a.dataset.sn); if (el && el.getBoundingClientRect().top <= edge) cur = a; });
      links.forEach(a => { if (a === cur) a.setAttribute('aria-current', 'location'); else a.removeAttribute('aria-current'); }); };
    if (!spyOn) { spyOn = true; window.addEventListener('scroll', mark, { passive: true }); } mark(); }
  /* Settings › Asking (#170): the ask clark switch, what is sent, and the folders ask clark may read. One card per project; the switch and
     the folders are kept with the project's settings (so they survive a reload), and every change is one step with Undo.
     A folder is chosen in a picker (the real clark opens the system's own folder window), never typed; a folder that is too wide is refused. */
  const ASK_MAX = 20, ASK_WIDE = 'That folder is too wide. Choose the folder for this project instead. Nothing was changed.';
  const ASK_HOME = '~/Library/Application Support/clark';   /* clark's own data, with its backups inside: never read */
  C.askOn = (p = C.P()) => !p || p.ask !== false;   /* on unless turned off: a new project starts On */
  /* why a chosen place cannot be added, or '' when it can; kind is 'folder' or 'file' */
  C.askFolderWhy = (path, kind, list = []) => {
    const x = String(path || '').replace(/\/+$/, '') || '/';
    if (kind !== 'folder' || x === '~' || x === '/' || /^\/Volumes\/[^/]+$/.test(x) || /^~\/(OneDrive[^/]*|Library\/CloudStorage\/OneDrive[^/]*)$/.test(x)
      || x === ASK_HOME || x.startsWith(ASK_HOME + '/') || ASK_HOME.startsWith(x + '/')) return ASK_WIDE;
    if (list.includes(x)) return 'That folder is already in the list. Nothing was changed.';
    if (list.length >= ASK_MAX) return `This project already has ${ASK_MAX} folders, the most it can have. Remove one to add another. Nothing was changed.`;
    return '';
  };
  /* the simulated folder window: fictional places on this computer, the wide ones among them */
  const ASK_PLACES = p => { const d = `~/Documents/${p.name}`, o = '~/OneDrive - Example Consulting';
    return [['folder', '~', 'Your home folder'], ['folder', '/', 'Macintosh HD, the top of the disk'], ['folder', o, 'OneDrive, all of it'], ['folder', d + '/Minutes', 'Minutes'], ['folder', d + '/Designs', 'Designs'],
      ['folder', `${o}/${p.name}/Status reports`, 'Status reports, in OneDrive'], ['file', d + '/Project plan.pdf', 'Project plan.pdf, a file'], ['folder', ASK_HOME, 'The data clark keeps'], ['folder', ASK_HOME + '/backups', 'The backups clark makes']]; };
  let askMsg = '';
  const askCard = p => { const on = C.askOn(p), src = p.sources || [];
    return `<div class="card" id="sources"><div class="card-h"><h2>Asking · ${esc(p.name)}</h2></div><p class="muted" style="font-size:14px;margin:-4px 0 12px" id="askConnect">When you ask, your question and the parts of your report and files it needs are sent to Claude, run by Anthropic (up to 40,000 characters each time). They count towards your Claude plan. You can turn ask clark off here.</p>
      <label class="sw ask-sw"><button class="switch" id="askSw" role="switch" aria-checked="${on}" aria-label="ask clark"></button><span>ask clark</span><b class="ask-sw-st" id="askSwSt" aria-hidden="true">${on ? 'On' : 'Off'}</b></label>
      <h3 class="set-h">Folders ask clark may read</h3>
      <ul class="docs" id="askFolders">${src.map((s, i) => `<li><span class="dic">${C.icon('folder', 's')}</span><span class="ask-loc">${esc(s)}</span><span></span><button class="btn sm" data-sd="${i}" aria-label="Remove ${esc(s)} from the list">Remove</button></li>`).join('') || '<li><span></span><span class="muted">No folders yet.</span></li>'}</ul>
      <div class="ask-fr"><button type="button" class="btn" id="askChoose" data-choose-folder>Choose folder</button><span class="muted" id="askCount">${src.length} of ${ASK_MAX} folders</span></div>
      <p class="ask-msg" id="askFMsg" role="alert">${esc(askMsg)}</p>
      <p class="muted" style="font-size:13px;margin:8px 0 0" id="askReads">ask clark reads text and Markdown files and PDFs in these folders, and the project’s own folders. Parts of what it reads are sent to Claude when you ask.</p></div>`; };
  const askPick = p => C.dialog(`<div class="dlg-h"><h2>Choose a folder</h2><p>Prototype: the real clark opens your Mac’s own folder window. Here, pick one of these.</p></div>
      <div class="dlg-b"><ul class="docs ask-pick">${ASK_PLACES(p).map(([k, path, t]) => `<li><span class="dic">${C.icon(k === 'file' ? 'doc' : 'folder', 's')}</span><span><b style="font-weight:500">${esc(t)}</b><br><span class="muted ask-loc">${esc(path)}</span></span><span></span><button class="btn sm" data-pick="${esc(path)}" data-kind="${k}">Choose</button></li>`).join('')}</ul></div>
      <div class="dlg-f"><button type="button" class="btn quiet" data-close>Cancel</button></div>`, d => {
    C.$$('[data-pick]', d).forEach(b => b.addEventListener('click', () => { d.close(); const list = p.sources || [], x = b.dataset.pick.replace(/\/+$/, '') || '/', why = C.askFolderWhy(x, b.dataset.kind, list);
      askMsg = why; if (why) { C.refresh(); C.$('#askChoose')?.focus(); return; }
      const u = D.change('project', p, { sources: [...list, x] }, D.who('in Settings'), 'Folder added'); C.refresh(); C.$('#askChoose')?.focus(); if (u) C.toast('Folder added', () => { u(); askMsg = ''; }); })); });
  const askWire = p => {
    C.$('#askSw')?.addEventListener('click', () => { const on = !C.askOn(p), u = D.change('project', p, { ask: on }, D.who('in Settings'), on ? 'ask clark turned on' : 'ask clark turned off');
      C.refresh(); C.$('#askSw')?.focus(); C.askOffDraw && C.askOffDraw(); if (u) C.toast(on ? 'ask clark is on' : 'ask clark is off', () => { u(); C.askOffDraw && C.askOffDraw(); }); });
    C.$('#askChoose')?.addEventListener('click', () => askPick(p));
    /* Remove takes it off the list only: no file is touched */
    C.$$('[data-sd]').forEach(b => b.addEventListener('click', () => { const s = (p.sources || [])[+b.dataset.sd]; askMsg = '';
      const u = D.change('project', p, { sources: (p.sources || []).filter((_, i) => i !== +b.dataset.sd) }, D.who('in Settings'), 'Folder removed'); C.refresh(); C.$('#askChoose')?.focus();
      if (u) C.toast(`${s} is off the list. No file was touched.`, u); }));
  };
  C.views.settings = {
    html() {
      const p = C.P(), showArch = C.store.get('showArchived', false), nArch = D.S.projects.filter(x => x.archived).length, vis = D.S.projects.filter(x => showArch || !x.archived);
      const me = D.S.profile || {}, pf = (id, k, label, type, ph, ac) => `<label for="${id}">${label}</label><input class="field" id="${id}" data-pf="${k}" type="${type}" autocomplete="${ac}" value="${esc(me[k] || '')}" placeholder="${ph}">`;
      /* an in-page navigation (S2): a sticky row of links to the cards, a row of chips you can scroll sideways on a phone */
      const nav = [['profile', 'Profile'], ['personal', 'Personal'], ['aiset', 'AI'], ['projects', 'Projects'], ['people', 'People'], ...(p ? [['sources', 'Asking'], ['publishing', 'Publishing'], ['pubs', 'Published reports']] : []), ['data', 'Data'], ['update', 'Version'], ['diagnostics', 'Diagnostics']];
      return `<div class="head"><div><h1>Settings</h1><p>Your profile, projects, where reports are published, and the folders ask clark may read.</p></div></div>
      <nav class="set-nav" aria-label="Settings sections"><ul>${nav.map(([id, t]) => `<li><a href="#${id}" data-sn="${id}">${t}</a></li>`).join('')}</ul></nav>
      <div class="card" id="profile"><div class="card-h"><h2>Profile</h2></div><p class="muted" style="font-size:14px;margin:-4px 0 12px">Who you are in clark: your name goes on your changes and on what you publish. Kept on this computer only.</p>
        <div class="form">${pf('pfName', 'name', 'Name', 'text', 'Your full name', 'name')}${pf('pfAlias', 'alias', 'Alias', 'text', 'What colleagues call you, or your initials', 'nickname')}${pf('pfEmail', 'email', 'Email', 'email', 'name@company.com', 'email')}${pf('pfPhone', 'phone', 'Phone number', 'tel', '+971 50 123 4567', 'tel')}${pf('pfOrg', 'org', 'Organisation', 'text', 'Your company or team', 'organization')}</div></div>
      <div class="card" id="personal"><div class="card-h"><h2>Personal</h2></div><p class="muted" style="font-size:14px;margin:-4px 0 12px">How clark looks for you. The section style is used on the published report too; Light or Dark is yours alone.</p>
        <h3 class="set-h">Dashboard sections</h3><div class="lays secs" role="radiogroup" aria-label="Dashboard sections">${[['slim', 'Slim gaps', 'Each section is its own card, with a slim gap that shows the page picture.'], ['roomy', 'Roomy gaps', 'The same, with more space between the sections.'], ['head', 'Grey headers', 'Slim gaps, and each section title in a grey band, like the Work items groups.'], ['one', 'One card', 'All the sections in one long card.']].map(([v, t, d]) => `<button class="lay sk-${v}" role="radio" aria-checked="${C.secs() === v}" data-secs="${v}"><span class="lay-sk" aria-hidden="true"><i></i><i></i><i></i></span><b>${t}</b><small>${d}</small></button>`).join('')}</div>
        <h3 class="set-h">Appearance</h3><div class="seg" role="group" aria-label="Appearance">${[['light', 'Light'], ['dark', 'Dark'], ['system', 'System']].map(([v, t]) => `<button data-theme-pick="${v}" aria-pressed="${C.themePref() === v}">${t}</button>`).join('')}</div>
        <p class="muted" style="font-size:13px;margin:8px 0 0">System follows your Mac's Light or Dark setting, and changes when it does.</p></div>
      <div class="card" id="aiset"><div class="card-h"><h2>AI</h2></div><p class="muted" style="font-size:14px;margin:-4px 0 12px">Sign in to Claude for ask clark and the AI menu: the passages they send go to Claude. OpenAI comes in a later version. Keys stay in this computer's keychain, never in clark's files.</p>
        <div class="ai-provs">${AI_PROVS.map(([k, n, how, note, later]) => { const c = aiConn()[k]; return `<div class="ai-prov${c ? ' on' : ''}${later ? ' later' : ''}"><h3>${n} <span class="tag${c ? ' cl' : ''}">${c ? 'Connected' : later ? 'Later' : 'Not connected'}</span></h3><p class="muted">${note}</p>${later ? '' : c ? `<p class="ai-how">${esc(c.how)} · ${c.models.map(esc).join(', ')}</p><button class="btn sm" data-aidisc="${k}">Disconnect</button>` : `<button class="btn pri sm" data-aicon="${k}">Connect…</button>`}</div>`; }).join('')}</div>
        <div class="form" style="margin-top:12px"><label for="aiModel">Model for ask clark</label><select class="field" id="aiModel">${aiModels().length ? aiModels().map(([v, t, rec]) => `<option value="${v}"${C.store.get('aiModel', '') === v ? ' selected' : ''}>${t}${rec ? ' (recommended)' : ''}</option>`).join('') : '<option>Connect Claude first</option>'}</select></div></div>
      <div class="card" id="projects"><div class="card-h"><h2>Projects</h2><span class="sp"></span><button class="btn sm" id="showArch" aria-pressed="${showArch}">Show archived${nArch ? ` (${nArch})` : ''}</button>${C.addBtn('id="npBtn"', 'Add project')}</div>
        <p class="muted" style="font-size:14px;margin:-4px 0 12px">Archive hides a project and everything in it from clark. Nothing is deleted: Show archived brings it back to the list, and Restore puts it back to work.</p>
        ${vis.length ? `<table class="set stack"><thead><tr><th>Name</th><th>Code</th><th>Client</th><th>Workstreams</th><th>Items</th><th></th></tr></thead><tbody>${vis.map(x => `<tr${x.archived ? ' class="arch"' : ''}><td class="nm"><b style="font-weight:500">${esc(x.name)}</b>${x.archived ? ' <span class="tag">Archived</span>' : x.code === UI.code ? ' <span class="tag cl">Open now</span>' : ''}</td><td data-l="Code">${esc(x.code)}</td><td data-l="Client">${esc(x.client || '—')}</td><td data-l="Workstreams">${esc(x.ws.join(', '))}</td><td data-l="Items">${D.S.items.filter(i => i.code === x.code).length}</td>
          <td class="acts">${x.archived ? `<button class="btn sm" data-pr="${x.code}">Restore</button>` : `${x.code !== UI.code ? `<button class="btn sm" data-pop="${x.code}">Open</button> ` : ''}<button class="btn sm" data-pe="${x.code}">Edit</button> <button class="btn sm" data-pa="${x.code}">Archive</button>`}</td></tr>`).join('')}</tbody></table>` : `<p class="muted" id="projNone">${D.S.projects.length ? 'Every project is archived. Choose Show archived to restore one.' : 'No projects yet. Create one to start.'}</p>`}</div>
      ${peopleCard()}
      ${p ? askCard(p) : ''}
      ${p ? `<div class="card" id="publishing"><div class="card-h"><h2>Publishing · ${esc(p.name)}</h2></div><p class="muted" style="font-size:14px;margin:-4px 0 12px">Where Publish saves the report. Local is always used; the client folder only when you tick To client.</p>
        <div class="form"><label for="pubL">Local folder</label><input class="field" id="pubL" value="${esc((p.publish || {}).local || '')}" placeholder="A folder on this computer, for example Reports">
        <label for="pubC">Client folder (SharePoint)</label><input class="field" id="pubC" type="url" value="${esc((p.publish || {}).client || '')}" placeholder="https://yourcompany.sharepoint.com/sites/…/Client reports"></div></div>
      ${pubsCard(p)}` : ''}
      <div class="card" id="data"><div class="card-h"><h2>Data</h2></div><div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn" id="sExp">${C.icon('dl', 's')}Export workbook</button><button class="btn" id="sImp">${C.icon('ul', 's')}Import workbook</button><button class="btn danger" id="sReset">Reset the demo data</button></div>
        <p class="muted" style="font-size:13px;margin:10px 0 0">The workbook has a sheet each for actions, risks and issues, decisions, milestones and use cases. ${D.S.persistent ? 'Everything is kept in this browser\'s database.' : 'This browser blocked its database, so changes last for this visit only.'}</p></div>
      ${updCard()}${dgCard()}`;
    },
    wire() {
      C.$$('[data-pf]').forEach(el => el.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); el.blur(); } }));   // Enter saves, as everywhere
      C.$$('[data-pf]').forEach(el => el.addEventListener('change', () => {
        if (!el.checkValidity()) { el.reportValidity(); return; }
        const label = C.$(`label[for="${el.id}"]`).textContent, u = D.setProfile({ [el.dataset.pf]: el.value });
        if (u) { C.drawTop(); C.toast(`${label} saved`, () => { u(); C.refresh(); }); }
      }));
      C.$('#npBtn').addEventListener('click', () => C.projectForm(null));
      C.$$('[data-pop]').forEach(b => b.addEventListener('click', () => { C.setProject(b.dataset.pop); C.go('dashboard'); }));
      C.$$('[data-pe]').forEach(b => b.addEventListener('click', () => C.projectForm(D.S.projects.find(x => x.code === b.dataset.pe))));
      /* Archive and Restore are one step each, with Undo and a history row (FR-43a, FR-43c); a project's data is never deleted */
      C.$$('[data-pa]').forEach(b => b.addEventListener('click', () => { const x = D.S.projects.find(z => z.code === b.dataset.pa), open = UI.code === x.code, u = D.archive(x, true); if (!u) return;
        if (open) { UI.code = C.live()[0]?.code || ''; C.store.set('project', UI.code); }
        C.refresh(); C.toast(`${x.name} archived. Show archived brings it back.`, () => { u(); if (open) { UI.code = x.code; C.store.set('project', x.code); } }); }));
      C.$$('[data-pr]').forEach(b => b.addEventListener('click', () => { const x = D.S.projects.find(z => z.code === b.dataset.pr), u = D.archive(x, false); if (!u) return; C.refresh(); C.toast(`${x.name} restored`, u); }));
      C.$('#showArch').addEventListener('click', () => { C.store.set('showArchived', !C.store.get('showArchived', false)); C.render(); C.$('#showArch')?.focus(); });
      const p = C.P();
      if (p) askWire(p);
      C.$('#pubL')?.addEventListener('change', e => saveProject({ publish: { ...(p.publish || {}), local: e.target.value.trim() } }, 'Local folder saved'));
      C.$('#pubC')?.addEventListener('change', e => { if (e.target.value && !e.target.checkValidity()) { e.target.reportValidity(); return; } saveProject({ publish: { ...(p.publish || {}), client: e.target.value.trim() } }, 'Client folder saved'); });
      C.$$('[data-aicon]').forEach(b => b.addEventListener('click', () => aiConnect(b.dataset.aicon)));
      C.$$('[data-aidisc]').forEach(b => b.addEventListener('click', () => { const all = aiConn(), k = b.dataset.aidisc; delete all[k]; C.store.set('aiConn', all); if (!aiModels().some(([v]) => v === C.store.get('aiModel', ''))) C.store.set('aiModel', aiModels()[0]?.[0] || ''); C.render(); C.toast('Disconnected; its models are out of the list'); }));
      C.$('#aiModel')?.addEventListener('change', e => { C.store.set('aiModel', e.target.value); C.toast('ask clark will use ' + e.target.selectedOptions[0].textContent); });
      C.$$('[data-secs]').forEach(b => b.addEventListener('click', () => { C.secs(b.dataset.secs); C.$$('[data-secs]').forEach(z => z.setAttribute('aria-checked', z === b)); C.toast('Dashboard sections: ' + b.querySelector('b').textContent); }));
      C.$$('[data-theme-pick]').forEach(b => b.addEventListener('click', () => { C.themeSet(b.dataset.themePick); C.$$('[data-theme-pick]').forEach(z => z.setAttribute('aria-pressed', z === b)); }));   /* the same words as the profile menu's Dark mode (S7) */
      C.$('#ppOnly')?.addEventListener('click', () => { ppOnly = !ppOnly; C.render(); C.$('#ppOnly')?.focus(); });
      C.$$('[data-sn]').forEach(a => a.addEventListener('click', e => { e.preventDefault(); C.settingsGo(a.dataset.sn); }));
      settingsSpy();
      C.$('#sExp').addEventListener('click', () => C.exportExcel()); C.$('#sImp').addEventListener('click', () => C.importExcel());
      C.$$('[data-pubopen]').forEach(b => b.addEventListener('click', () => C.openPub(+b.dataset.pubopen)));
      C.$('#ppPasteBtn')?.addEventListener('click', e => { const box = C.$('#ppPaste'), on = box.hidden; box.hidden = !on; e.currentTarget.setAttribute('aria-expanded', on); if (on) C.$('#ppText').focus(); });
      C.$('#ppAdd')?.addEventListener('click', () => { const txt = C.$('#ppText').value, known = new Map(C.peopleRows().map(r => [r.name.toLowerCase(), r.name]));
        const rows = txt.split(/\r?\n/).map(l => l.split('\t').map(c => c.trim())).filter(c => c[0] && !(c[0].toLowerCase() === 'name' && /mail/i.test(c[1] || ''))).map(c => ({ name: known.get(c[0].toLowerCase()) || c[0], email: c[1] || '', org: c[2] || '', role: c[3] || '' }));
        if (!rows.length) { C.$('#ppMsg').textContent = 'Nothing to add. Paste rows copied from Excel: name, email, organisation, role.'; return; }
        const u = D.setPeople(rows); if (!u) { C.$('#ppMsg').textContent = 'Those details are already in the list.'; return; }
        C.refresh(); C.toast(`${rows.length} ${rows.length === 1 ? 'person' : 'people'} updated`, () => { u(); C.refresh(); }); });
      updWire(); dgWire();
      C.$('#sReset').addEventListener('click', () => C.confirm('Reset the demo data?', '<p>Every change you made in this prototype is replaced by the starting demo data.</p>', 'Reset', () => C.$('#resetDemo').click()));
    },
  };
  C.projectForm = x => {
    C.dialog(`<form id="pF"><div class="dlg-h"><h2>${x ? 'Edit ' + esc(x.name) : 'New project'}</h2>${x ? '' : '<p>You can import its work items, milestones and use cases from Excel afterwards.</p>'}</div>
      <div class="dlg-b"><div class="form"><label for="pN">Name</label><input class="field" id="pN" required value="${esc(x?.name || '')}" placeholder="For example: Finance System Upgrade">
      <label for="pC">Short code</label><input class="field" id="pC" required maxlength="7" pattern="[A-Za-z][A-Za-z0-9]{2,6}" value="${esc(x?.code || '')}" ${x ? 'disabled' : ''} placeholder="3 to 7 letters or digits" style="text-transform:uppercase">
      <label for="pCl">Client</label><input class="field" id="pCl" value="${esc(x?.client || '')}" placeholder="Who the reports are for">
      <label for="pW">Workstreams</label><input class="field" id="pW" value="${esc((x?.ws || ['Delivery']).join(', '))}" placeholder="Separated by commas"></div></div>
      <div class="dlg-f"><button type="button" class="btn quiet" data-close>Cancel</button><button class="btn pri">${x ? 'Save' : 'Create project'}</button></div></form>`, d => {
      const n = C.$('#pN', d), c = C.$('#pC', d); n.focus();
      if (!x) { n.addEventListener('input', () => { if (!c.dataset.t) c.value = n.value.split(/\s+/).map(w => w[0] || '').join('').toUpperCase().slice(0, 4); }); c.addEventListener('input', () => { c.dataset.t = 1; }); }
      C.$('#pF', d).addEventListener('submit', e => {
        e.preventDefault(); const ws = C.$('#pW', d).value.split(',').map(s => s.trim()).filter(Boolean);
        if (x) { const u = D.change('project', x, { name: n.value.trim(), client: C.$('#pCl', d).value.trim(), ws: ws.length ? ws : x.ws }, D.who('in the project form')); d.close(); C.refresh(); u && C.toast('Project saved', u); return; }
        const code = c.value.toUpperCase();
        if (D.S.projects.some(z => z.code === code)) { c.setCustomValidity('That code is already in use'); c.reportValidity(); c.setCustomValidity(''); return; }
        const np = { code, name: n.value.trim(), client: C.$('#pCl', d).value.trim(), ws: ws.length ? ws : ['Delivery'], health: 'G', reason: 'Just started.', current: '', report: D.defaultReport(), docs: [], sources: [], week: D.friday() };
        const u = D.create('project', np, D.who('in the project form')); d.close(); C.setProject(code); C.go('work'); C.toast(`${np.name} created`, u ? () => { u(); UI.code = D.S.projects[0]?.code; C.store.set('project', UI.code); } : null);
      });
    });
  };

  /* ═════════════ drafts (rules standing in for AI) ═════════════ */
  C.draftCurrent = p => { const g = C.glanceData(p), ms = D.S.milestones.filter(m => m.code === p.code && !m.archived), next = ms.filter(m => !m.achievedOn).sort((a, b) => (a.forecast || a.agreed).localeCompare(b.forecast || b.agreed))[0];
    return `<p>${esc(p.name)} is ${{ G: 'on track', A: 'at risk', R: 'off track' }[p.health]}. ${esc(p.reason)}</p><p>${ms.filter(m => m.achievedOn).length} of ${ms.length} milestones are achieved${next ? `; the next is ${esc(next.name.charAt(0).toLowerCase() + next.name.slice(1))}, ${D.slip(next) > 0 ? `now expected ${D.fd(next.forecast)} (${C.dy(D.slip(next))} late)` : `due ${D.fd(next.agreed)}`}` : ''}. ${g.overdue.v} actions are overdue and ${g.risks.v} high risks and issues are open.</p>`; };
  C.draftText = (p, s) => { const its = D.S.items.filter(x => x.code === p.code && !x.archived);
    if (/next/i.test(s.title)) { const soon = its.filter(x => x.type === 'A' && C.isOpen(x) && x.due && D.days(x.due) >= 0 && D.days(x.due) <= 10); return soon.length ? `<ul>${soon.map(x => `<li>${esc(x.title)} (${esc(x.owner)}, ${D.fd(x.due)})</li>`).join('')}</ul>` : '<p>Nothing due in the next week.</p>'; }
    if (/this week/i.test(s.title)) { const done = D.S.history.filter(h => h.code === p.code && h.kind === 'item' && h.field === 'status' && h.to === 'Closed'); return `<ul><li>${done.length} actions closed; ${its.filter(x => x.type === 'A' && C.isOpen(x) && x.due && D.days(x.due) < 0).length} overdue.</li><li>${its.filter(x => (x.type === 'R' || x.type === 'I') && C.isOpen(x)).length} risks and issues open.</li></ul>`; }
    return C.draftCurrent(p); };
  C.draftUc = u => { const steps = D.S.items.filter(x => x.code === u.code && x.uc === u.id && C.isOpen(x) && !x.archived); return `<p>${esc(u.headline)}.</p><p>${steps.length ? `${steps.length} next steps are open; the first is due ${D.fd(steps.map(x => x.due).sort()[0])}.` : 'No next steps are open.'}</p>`; };
})();
