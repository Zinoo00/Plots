/* Plots — progress for Claude Code projects, one workspace at a time.
   Claude updates the data with the `plots` CLI; this page shows it, follows changes
   live, and lets you chat with your Claude project (or a fork of the working session), answer and change statuses.
   No build step, no dependencies. */
(() => {
  'use strict';

  // inside the Plots Mac app (WKWebView) the app draws the window, the sidebar, the toolbar and the menus
  const NATIVE = !!(window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.plots);
  if (NATIVE) document.documentElement.classList.add('native');
  // ?panel=chat: only the chat panel, which the Mac app shows in its sidebar beside the page
  const PANEL = new URLSearchParams(location.search).get('panel') === 'chat';
  if (PANEL) document.documentElement.classList.add('panel-doc');
  // in the Mac app the page and its chat panel are two documents: each keeps only its own drafts and choices
  const OWN_CHAT = PANEL || !NATIVE;
  const OWN_PAGE = !PANEL;
  const native = (msg) => { if (NATIVE) { try { window.webkit.messageHandlers.plots.postMessage(msg); } catch (e) { /* the app is gone */ } } };
  // Light / Dark / Automatic (Automatic follows the Mac)
  const THEMES = { auto: 'Automatic', light: 'Light', dark: 'Dark' };
  let theme = 'auto';
  try { theme = JSON.parse(localStorage.getItem('plots-theme')) || 'auto'; } catch (e) { /* storage unavailable */ }
  if (!THEMES[theme]) theme = 'auto';
  function applyTheme() {
    const r = document.documentElement;
    if (theme === 'auto') r.removeAttribute('data-theme'); else r.dataset.theme = theme;
  }
  applyTheme();

  // ------------------------------------------------------------------ constants
  // Workflow: Not started → Fixing → Done → Testing → Tested → Merged (In progress, In review and
  // Fixing review notes map to Fixing). Up next sits before Fixing; Blocked and Out of scope alongside.
  const STATUS = ['Not started', 'Up next', 'Fixing', 'Done', 'Testing', 'Tested', 'Merged', 'Blocked', 'Out of scope'];
  // Out-of-scope screens are not worked on — shown, but left out of totals, progress and "up next"
  const OOS = 'Out of scope';
  const FLIGHT = ['Fixing'];
  const WORKING = FLIGHT.concat('Blocked');
  const TODO = ['Not started', 'Up next'];
  const FINISHED = ['Done', 'Testing', 'Tested', 'Merged'];   // all count as done
  const QA = ['Testing', 'Tested', 'Merged'];                 // your own testing, then merging
  const LEGACY = { 'In progress': 'Fixing', 'In review': 'Fixing', 'In flight': 'Fixing', 'Fixing review notes': 'Fixing' };
  // the steps bar and the progress pips follow the process; the in-between statuses sit on their step
  const STEPS = ['Not started', 'Fixing', 'Done', 'Testing', 'Tested', 'Merged'];
  const STEP_OF = { 'Up next': 0, 'Blocked': 1 };
  const stepOf = (st) => (st in STEP_OF ? STEP_OF[st] : STEPS.indexOf(st));
  const PIPE_RANK = ['Not started', 'Up next', 'Fixing', 'Blocked', 'Done', 'Testing', 'Tested', 'Merged', 'Out of scope'];
  const SHORT = { 'Fixing review notes': 'Fixing' };
  const SCLS = { 'Not started': 's-ns', 'Up next': 's-next', 'Fixing': 's-wip',
    'Done': 's-done', 'Testing': 's-tsg', 'Tested': 's-tst', 'Merged': 's-mrg', 'Blocked': 's-blk', 'Out of scope': 's-oos' };
  const DCLS = { 'Waiting on you': 'd-wait', 'Please confirm': 'd-ask', 'Decided': 'd-ok', 'Confirmed': 'd-ok', 'Answered': 'd-sent' };
  const D_OPEN = ['Waiting on you', 'Please confirm'];
  const BY = { claude: 'Claude', user: 'You', import: 'From Excel' };
  // status filters that cover several statuses
  const GROUPS = {
    'g:flight': { label: 'Fixing or blocked', test: (st) => WORKING.includes(st) },
    'g:todo': { label: 'Not started yet', test: (st) => TODO.includes(st) },
    'g:done': { label: 'Done or later', test: (st) => FINISHED.includes(st) },
    'g:qa': { label: 'Testing, tested or merged', test: (st) => QA.includes(st) },
  };
  // the four classes the Status card shows
  const CLASSES = [
    { k: 'done', label: 'Done', test: (st) => FINISHED.includes(st), f: 'g:done' },
    { k: 'flight', label: 'Fixing', test: (st) => FLIGHT.includes(st), f: 'Fixing' },
    { k: 'blocked', label: 'Blocked', test: (st) => st === 'Blocked', f: 'Blocked' },
    { k: 'todo', label: 'Not started', test: (st) => TODO.includes(st), f: 'g:todo' },
  ];
  const VIEWS = ['overview', 'screens', 'decisions', 'activity'];      // ⌘1–4; Chat (⌘0) is in the sidebar
  const MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  const KEY = MAC ? '⌘' : 'Ctrl ';

  const ICONS = {
    home: '<path d="M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5.5h-5V20H5a1 1 0 0 1-1-1z"/>',
    caps: '<rect x="4" y="4" width="4" height="16" rx="2"/><rect x="10" y="4" width="4" height="16" rx="2"/><rect x="16" y="4" width="4" height="16" rx="2"/>',
    decide: '<path d="M20 12a8 8 0 0 1-11.6 7.1L4 20l1-4.1A8 8 0 1 1 20 12z"/><path d="m8.6 12.1 2.3 2.3 4.5-4.6"/>',
    clock: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l2.5 2.5"/>',
    sidebar: '<rect x="3.5" y="4.5" width="17" height="15" rx="3.5"/><path d="M9.5 4.5v15"/><path d="M5.9 8.2h1.4M5.9 11h1.4"/>',
    sun: '<circle cx="12" cy="12" r="3.6"/><path d="M12 3.5v1.8M12 18.7v1.8M3.5 12h1.8M18.7 12h1.8M6 6l1.3 1.3M16.7 16.7 18 18M6 18l1.3-1.3M16.7 7.3 18 6"/>',
    moon: '<path d="M19.5 14.6A7.5 7.5 0 0 1 9.4 4.5a7.5 7.5 0 1 0 10.1 10.1z"/>',
    halfcircle: '<circle cx="12" cy="12" r="7.5"/><path d="M12 4.5v15a7.5 7.5 0 0 0 0-15z" fill="currentColor" stroke="none"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.3-4.3"/>',
    download: '<path d="M12 4v11m0 0-4.5-4.5M12 15l4.5-4.5M5 19.5h14"/>',
    close: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    chev: '<path d="m7 10 5 5 5-5"/>',
    chevR: '<path d="m10 7 5 5-5 5"/>',
    arrow: '<path d="M5 12h14m0 0-5.5-5.5M19 12l-5.5 5.5"/>',
    copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2.5"/><path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    checkc: '<circle cx="12" cy="12" r="8.5"/><path d="m8.3 12.3 2.6 2.6 4.9-5"/>',
    alert: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.8v5"/><path d="M12 16.2h.01"/>',
    branch: '<circle cx="7" cy="6" r="2"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="7.5" r="2"/><path d="M7 8v8M17 9.5c0 4.5-5 4-8.6 7"/>',
    group: '<rect x="4" y="4.5" width="16" height="6" rx="2"/><rect x="4" y="13.5" width="16" height="6" rx="2"/>',
    up: '<path d="m8 14 4-4 4 4"/>',
    down: '<path d="m8 10 4 4 4-4"/>',
    pulse: '<path d="M3.5 12h4l2.5-6 4 12 2.5-6h4"/>',
    layers: '<path d="m12 4 8.5 4.5L12 13 3.5 8.5z"/><path d="m3.5 12.5 8.5 4.5 8.5-4.5"/>',
    chart: '<path d="M6 20V11M11 20V5M16 20v-6.5M20.5 20v-3.5"/>',
    note: '<path d="M5 5.5A1.5 1.5 0 0 1 6.5 4h11A1.5 1.5 0 0 1 19 5.5v9a1.5 1.5 0 0 1-1.5 1.5H10l-4 3.5V16h0a1.5 1.5 0 0 1-1-1.4z"/><path d="M8.5 8.5h7M8.5 11.5h4.5"/>',
    updown: '<path d="m8.5 9.5 3.5-3.5 3.5 3.5M8.5 14.5l3.5 3.5 3.5-3.5"/>',
    excl: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.8v5"/><path d="M12 16.2h.01"/>',
    send: '<path d="m4.5 11.5 15-6.5-6 15-2.6-6z"/><path d="m10.9 14 8.6-9"/>',
    folder: '<path d="M3.5 7.2A1.7 1.7 0 0 1 5.2 5.5h3.9l1.9 2h7.8a1.7 1.7 0 0 1 1.7 1.7v8.1a1.7 1.7 0 0 1-1.7 1.7H5.2a1.7 1.7 0 0 1-1.7-1.7z"/>',
    bubble: '<path d="M4.5 7A2.5 2.5 0 0 1 7 4.5h10A2.5 2.5 0 0 1 19.5 7v7a2.5 2.5 0 0 1-2.5 2.5h-6l-4.5 3.5v-3.5H7A2.5 2.5 0 0 1 4.5 14z"/>',
    bubbles: '<path d="M3.5 6.5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2V11a2 2 0 0 1-2 2H9l-3.5 3v-3a2 2 0 0 1-2-2z"/><path d="M15.5 8.5h3a2 2 0 0 1 2 2V15a2 2 0 0 1-2 2v3L15 17h-3.5a2 2 0 0 1-2-2"/>',
    compose: '<path d="M11.5 4.5h-5a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-5"/><path d="M17.9 3.6a1.7 1.7 0 0 1 2.5 2.5l-7.6 7.6-3.3.9.9-3.3z"/>',
    hub: '<circle cx="12" cy="5.8" r="2.3"/><circle cx="5.8" cy="17.2" r="2.3"/><circle cx="18.2" cy="17.2" r="2.3"/><path d="M10.9 7.8 6.9 15.2M13.1 7.8l4 7.4M8.1 17.2h7.8"/>',
    term: '<rect x="3.5" y="5" width="17" height="14" rx="3"/><path d="m7.5 10 2.5 2-2.5 2M12.5 14.5h4"/>',
    fork: '<circle cx="7" cy="5.5" r="2"/><circle cx="17" cy="5.5" r="2"/><circle cx="12" cy="18.5" r="2"/><path d="M7 7.5v1.5a3 3 0 0 0 3 3h4a3 3 0 0 0 3-3V7.5M12 12v4.5"/>',
    laptop: '<rect x="5" y="5.5" width="14" height="10" rx="1.5"/><path d="M3 18.5h18"/>',
    cloud: '<path d="M7.5 18.5h9.8a3.7 3.7 0 0 0 .3-7.4 5.6 5.6 0 0 0-10.8-1.3A4.4 4.4 0 0 0 7.5 18.5z"/>',
    at: '<circle cx="12" cy="12" r="3.6"/><path d="M15.6 12v1.4a2.3 2.3 0 0 0 4.6 0V12a8.2 8.2 0 1 0-3.2 6.5"/>',
    plus: '<path d="M12 5.5v13M5.5 12h13"/>',
    stop: '<rect x="7.5" y="7.5" width="9" height="9" rx="1.8" fill="currentColor" stroke="none"/>',
    arrowUp: '<path d="M12 18.5v-13M6.5 11 12 5.5l5.5 5.5"/>',
    ext: '<path d="M8 16 16 8M9.5 8H16v6.5"/>',
    more: '<circle cx="6.5" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="17.5" cy="12" r="1.4" fill="currentColor" stroke="none"/>',
    pane: '<rect x="3.5" y="4.5" width="17" height="15" rx="3.5"/><path d="M14.5 4.5v15"/>',
    retry: '<path d="M19 12a7 7 0 1 1-2.05-4.95"/><path d="M19 4.5v4h-4"/>',
    list: '<path d="M9.5 7h10M9.5 12h10M9.5 17h10"/><circle cx="5.2" cy="7" r="1.15" fill="currentColor" stroke="none"/><circle cx="5.2" cy="12" r="1.15" fill="currentColor" stroke="none"/><circle cx="5.2" cy="17" r="1.15" fill="currentColor" stroke="none"/>',
    assist: '<path d="M3.5 7.5h5M3.5 12h4M3.5 16.5h5"/><path d="M15.5 5.5c.5 3.3 2 4.8 5.2 5.3-3.2.5-4.7 2-5.2 5.3-.5-3.3-2-4.8-5.2-5.3 3.2-.5 4.7-2 5.2-5.3z" fill="currentColor" stroke-width="1.2"/>',
    screen: '<rect x="3.5" y="5" width="17" height="12" rx="2"/><path d="M9 20h6M12 17v3"/>',
    archive: '<rect x="3.5" y="4.5" width="17" height="4" rx="1.2"/><path d="M5 8.5v9a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-9M10 12.5h4"/>',
    pencil: '<path d="M5 19.5h3.5L19 9a2.1 2.1 0 0 0-3-3L5.5 16.5z"/><path d="m14.5 7.5 3 3"/>',
  };
  // segmented controls: one thumb slides under the chosen segment (placeThumbs, after every render)
  const SEG_THUMB = '<i class="seg-thumb" data-key="thumb" aria-hidden="true"></i>';
  const icon = (n, cls = '') => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ''}</svg>`;
  const LOGO = '<svg viewBox="0 0 32 32" aria-hidden="true"><rect x="5.0" y="5.0" width="6.4" height="6.4" rx="1.8" fill="#30D47A"/><rect x="12.9" y="5.0" width="6.4" height="6.4" rx="1.8" fill="#30D47A"/><rect x="20.8" y="5.0" width="6.4" height="6.4" rx="1.8" fill="#30D47A"/><rect x="5.0" y="12.9" width="6.4" height="6.4" rx="1.8" fill="#30D47A"/><rect x="12.9" y="12.9" width="6.4" height="6.4" rx="1.8" fill="#2F8CFF"/><rect x="20.8" y="12.9" width="6.4" height="6.4" rx="1.8" fill="#2F8CFF"/><rect x="5.0" y="20.8" width="6.4" height="6.4" rx="1.8" fill="#FFFFFF" fill-opacity=".5"/><rect x="12.9" y="20.8" width="6.4" height="6.4" rx="1.8" fill="#FFFFFF" fill-opacity=".5"/><rect x="20.8" y="20.8" width="6.4" height="6.4" rx="1.8" fill="#FFFFFF" fill-opacity=".5"/></svg>';

  // ------------------------------------------------------------------ state
  const store = {
    get(k, d) { try { const v = localStorage.getItem('plots-' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('plots-' + k, JSON.stringify(v)); } catch (e) { /* storage unavailable */ } },
  };
  // the workspace this page shows: ?ws=<id> (the Mac app sets it), else the last one used here, else the server's
  let WSID = new URLSearchParams(location.search).get('ws') || (NATIVE ? null : store.get('ws', null));
  const api = (path) => (WSID ? `${path}${path.includes('?') ? '&' : '?'}ws=${encodeURIComponent(WSID)}` : path);
  const S = {
    data: null, live: false, offline: false,
    batch: 'All',                                   // fix-batch scope for Overview + Screens
    sbPref: store.get('sidebar', 'expanded'), peek: false,
    ovTab: 'flight', range: store.get('range', 14), mapBy: store.get('mapBy', 'menu'),
    q: '', fStatus: '', fMenu: '', group: true, sort: { key: 'id', dir: 1 },
    dFilter: 'all', aFilter: 'all', repo: store.get('repo', 'All'), codeTab: store.get('codeTab', 'worktrees'), code: null, codeOthers: false,
    pal: false, palQ: '', palI: 0, palItems: [],
    pop: false,
    notes: [], noteDelay: 8, noteMode: 'fork', bridge: null, sessions: null, workspaces: [], wsMenu: false,
    side: NATIVE ? 'views' : store.get('side', 'views'),   // what a browser's sidebar shows: views, or chat
    chatConv: null, chatTo: {}, chatLocal: {}, chatMenu: null, chatEdit: null, mention: null,
    // the Mac app's chat panel counts as hidden until the app says it shows (Plots.visible)
    panelCtx: null, ctxDropped: null, histQ: '', histArchived: false, panelVisible: !PANEL,
    // unsent text, keyed: screen:<id>, dec:<n>, msg, chat:<conversation>
    drafts: Object.assign({}, store.get('drafts', {}) || {}, store.get('chatDrafts', {}) || {}),
    inspW: Math.max(320, Math.min(560, +store.get('inspW', 384) || 384)),
  };
  const saveDrafts = () => {
    const chat = {}; const page = {};
    Object.keys(S.drafts).forEach((k) => { (k.startsWith('chat:') ? chat : page)[k] = S.drafts[k]; });
    if (OWN_PAGE) store.set('drafts', page);
    if (OWN_CHAT) store.set('chatDrafts', chat);
  };
  const draft = (key, saved) => (key in S.drafts ? S.drafts[key] : (saved || ''));

  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pct = (a, b) => (b ? (100 * a) / b : 0);
  const round = (x) => Math.round(x);
  const plural = (n, one, many) => `${n} ${n === 1 ? one : (many || one + 's')}`;
  const dayISO = (d) => d.toLocaleDateString('sv-SE');
  const parseT = (t) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/.exec(t || '');
    return m ? new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0)) : null;
  };
  const hasTime = (t) => /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(t || '');
  const fmtDay = (d) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  const fmtClock = (d) => d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  const relDay = (d, lower) => {
    const iso = dayISO(d);
    const w = iso === dayISO(new Date()) ? 'Today' : iso === dayISO(new Date(Date.now() - 864e5)) ? 'Yesterday' : null;
    return w ? (lower ? w.toLowerCase() : w) : fmtDay(d);
  };
  // "Today, 17:25" (or "today, 17:25" mid-sentence)
  function fmtWhen(t, lower) {
    const d = parseT(t);
    if (!d) return esc(t || '—');
    const extra = /\(([^)]*)\)/.exec(t || '');
    return relDay(d, lower) + (hasTime(t) ? ', ' + fmtClock(d) : extra ? ' (' + esc(extra[1]) + ')' : '');
  }
  // short form for table cells: "17:25" today, "Yesterday", "Oct 18"
  function fmtShort(t) {
    const d = parseT(t);
    if (!d) return '—';
    const r = relDay(d);
    return r === 'Today' && hasTime(t) ? fmtClock(d) : r;
  }
  const menuLabel = (m) => {
    const x = String(m || '').replace(/^\((.*)\)$/, '$1');
    const o = /^other menu:\s*(.+)$/i.exec(x);
    if (o) return o[1] + ' (other menu)';
    return x.charAt(0).toUpperCase() + x.slice(1);
  };
  const menuName = (m) => menuLabel(m).replace(/ \(other menu\)$/, '');
  // Statuses read like Linear's: a small icon and the word, both in the status colour, no capsule. The icon is a
  // ring that fills as the work moves along (dashed before it is planned), a check when done, a mark when blocked.
  const pieTo = (f) => {
    const r = 3.6; const a = f * 2 * Math.PI;
    return `<path class="sf" d="M8 8V${8 - r}A${r} ${r} 0 ${f > 0.5 ? 1 : 0} 1 ${(8 + r * Math.sin(a)).toFixed(2)} ${(8 - r * Math.cos(a)).toFixed(2)}Z"/>`;
  };
  const RING = '<circle class="sr" cx="8" cy="8" r="6.25"/>';
  const DISC = '<circle class="sf" cx="8" cy="8" r="7"/>';
  const ST_SVG = {
    's-ns': '<circle class="sr dash" cx="8" cy="8" r="6.25" transform="rotate(-101.25 8 8)"/>',
    's-next': RING,
    's-wip': RING + pieTo(0.5),
    's-fix': RING + pieTo(0.75),
    's-tsg': RING + '<path class="sf" d="M6.6 5.2v5.6l4.6-2.8z"/>',
    's-tst': DISC + '<path class="sk" d="M3.9 8.4l1.9 1.9 3.6-3.9M7.6 10.1l.2.2 3.6-3.9"/>',
    's-mrg': DISC + '<path class="sk" d="M6 4.6v6.8M6 6.4c0 2 1.6 2.6 4 2.6"/><circle class="skf" cx="10.3" cy="9" r="1.05"/>',
    's-done': DISC + '<path class="sk" d="M5.2 8.3l1.9 1.9 3.8-4"/>',
    's-blk': DISC + '<path class="sk" d="M8 4.8v3.7"/><circle class="skf" cx="8" cy="10.9" r=".95"/>',
    's-oos': DISC + '<path class="sk" d="M6 6l4 4M10 6l-4 4"/>',
    'd-wait': RING + '<circle class="sf" cx="8" cy="8" r="2.6"/>',
    'd-ask': RING + '<circle class="sf" cx="8" cy="8" r="2.6"/>',
    'd-sent': RING + pieTo(0.5),
    'd-ok': DISC + '<path class="sk" d="M5.2 8.3l1.9 1.9 3.8-4"/>',
    'a-ok': DISC + '<path class="sk" d="M5.2 8.3l1.9 1.9 3.8-4"/>',
    'a-stop': RING + '<path class="sf" d="M6.2 6.2h3.6v3.6H6.2z"/>',
  };
  const stIcon = (cls, extra = '') => `<svg class="sti ${cls}${extra ? ' ' + extra : ''}" viewBox="0 0 16 16" aria-hidden="true">${ST_SVG[cls] || RING}</svg>`;
  // small ones (tables, lists) use the short label; the full status is in the tooltip and the details
  const statusPill = (s, small) => `<span class="st ${SCLS[s] || ''}${small ? ' sm' : ''}"${small && SHORT[s] ? ` title="${esc(s)}"` : ''}>${stIcon(SCLS[s])}<span class="stw">${esc(small ? (SHORT[s] || s) : s)}</span></span>`;
  // a status cell in a table: the status, and a menu to change it (like Linear)
  const stCell = (s) => `<button class="st-cell" data-act="stMenu" data-id="${esc(s.id)}" aria-haspopup="menu" aria-expanded="false" aria-label="Status: ${esc(s.status)}. Change">${statusPill(s.status, true)}</button>`;
  // the next step of your testing, one click from the details
  const NEXT_QA = { 'Done': 'Testing', 'Testing': 'Tested', 'Tested': 'Merged' };
  const dPill = (s, small) => `<span class="st ${DCLS[s] || ''}${small ? ' sm' : ''}">${stIcon(DCLS[s])}<span class="stw">${esc(s)}</span></span>`;
  const findings = (s) => (s.p1 || 0) + (s.p2 || 0) + (s.p3 || 0);
  // You answered and the answer is still unread in Claude's inbox: Claude's move, so it leaves the orange counts.
  // Once Claude has read it, a decision that is still open waits on you again. A status change (an Undo) is not an answer.
  const D_CHANGE = /^(Waiting on you|Please confirm|Decided|Confirmed) → /;
  function answered(x) {
    if (!D_OPEN.includes(x.status) || !x.myNotes) return false;
    const items = ((S.data && S.data.inbox) || []).filter((i) => i.kind === 'decision' && String(i.ref) === String(x.n));
    const last = items[items.length - 1];
    return !!last && !last.read && !D_CHANGE.test(last.text || '');
  }
  const waitsOnUser = (x) => D_OPEN.includes(x.status) && !answered(x);
  function idChip(id, title) {
    const s = S.data && S.data.screens.find((x) => x.id === id);
    const glyph = s ? stIcon(SCLS[s.status], 'xs') : '';
    const tipText = s ? `${s.name} · ${s.status}` : title;
    return `<button class="idc" data-act="open" data-id="${esc(id)}"${tipText ? ` data-tip-text="${esc(tipText)}"` : ''}>${glyph}${esc(shortId(id))}</button>`;
  }


  // ------------------------------------------------------------------ data
  // the workspace's data and its notes, in one go
  async function fetchState() {
    try {
      const [r, rn] = await Promise.all([fetch(api('/api/state'), { cache: 'no-store' }), fetch(api('/api/notes'), { cache: 'no-store' })]);
      if (r.status === 404) {
        // the server runs but there is no workspace yet (a new Mac), or the chosen one went away
        const e = await r.json().catch(() => ({}));
        if (/no workspace/i.test(e.error || '')) { S.offline = false; S.noWorkspace = true; return null; }
        if (WSID && !NATIVE) { WSID = null; store.set('ws', null); return fetchState(); }
      }
      if (!r.ok) throw new Error(r.status);
      S.noWorkspace = false;
      const j = normalizeLegacy(await r.json());
      S.offline = false;
      S.sig = r.headers.get('X-Data-Sig');
      const ws = r.headers.get('X-Workspace');
      if (ws && !WSID) WSID = ws;
      if (rn.ok) { const n = await rn.json(); S.notes = n.notes || []; S.noteDelay = n.delay || 8; S.noteMode = n.mode || 'fork'; S.bridge = n.bridge; }
      if (WSID && !S.workspaces.some((w) => w.id === WSID)) await fetchWorkspaces();
      return j;
    } catch (e) {
      S.offline = true;
      return null;
    }
  }
  // In progress, In review, In flight and Fixing review notes are Fixing now (the server rewrites older files; this
  // covers the moment between)
  function normalizeLegacy(d) {
    (d.screens || []).forEach((s) => { if (LEGACY[s.status]) s.status = LEGACY[s.status]; });
    if ((d.events || []).some((e) => LEGACY[e.from] || LEGACY[e.to])) {
      d.events = d.events.map((e) => ({ ...e, from: LEGACY[e.from] || e.from, to: LEGACY[e.to] || e.to })).filter((e) => e.from !== e.to);
    }
    return d;
  }
  async function fetchWorkspaces() {
    try {
      const r = await fetch('/api/workspaces', { cache: 'no-store' });
      if (r.ok) { const j = await r.json(); S.workspaces = j.workspaces || []; }
    } catch (e) { /* the server is gone; the offline banner says so */ }
    return S.workspaces;
  }
  const curWS = () => S.workspaces.find((w) => w.id === WSID) || { id: WSID || '', name: (S.data && S.data.title) || 'Plots', initials: '·', color: 'blue', cli: 'plots' };
  const CLI = () => curWS().cli || 'plots';
  const idPrefix = () => { const m = S.data && S.data.meta; return m && 'idPrefix' in m ? (m.idPrefix || '') : ''; };
  const shortId = (id) => { const p = idPrefix(); return p && String(id).startsWith(p) ? String(id).slice(p.length) : String(id); };

  async function post(url, body) {
    const r = await fetch(api(url), {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Plots': '1' }, body: JSON.stringify(body || {}),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || 'Could not save. Is Plots still running?');
    return j;
  }
  // notes: answers you haven't looked at yet, notes that failed, and notes on their way
  const NOTE_LIVE = ['scheduled', 'queued', 'sending', 'held'];
  const unseenNotes = () => S.notes.filter((n) => !n.seen && (n.state === 'answered' || n.state === 'failed')).length;
  const activeNotes = () => S.notes.filter((n) => NOTE_LIVE.includes(n.state)).length;
  const unreadCount = () => unseenNotes();

  function stats(screens) {
    const by = {};
    STATUS.forEach((s) => (by[s] = 0));
    screens.forEach((s) => (by[s.status] = (by[s.status] || 0) + 1));
    const oos = by[OOS] || 0;
    const total = screens.length - oos;
    const flight = FLIGHT.reduce((a, s) => a + by[s], 0);
    const done = FINISHED.reduce((a, s) => a + by[s], 0);
    return {
      by, total, oos, done, flight, blocked: by['Blocked'], working: flight + by['Blocked'],
      todo: by['Not started'] + by['Up next'],
      pct: pct(done, total), wpct: pct(flight + by['Blocked'], total),
      findings: screens.filter((s) => s.status !== OOS).reduce((a, s) => a + findings(s), 0),
      findingsDone: screens.filter((s) => FINISHED.includes(s.status)).reduce((a, s) => a + findings(s), 0),
    };
  }
  const scoped = () => (S.batch === 'All' ? S.data.screens : S.data.screens.filter((s) => s.batch === S.batch));
  const byRecent = (a, b) => ((b.updated || '') > (a.updated || '') ? 1 : (b.updated || '') < (a.updated || '') ? -1 : a.order - b.order);

  function upNext(screens, n) {
    const q = screens.filter((s) => s.status === 'Up next').sort((a, b) => a.order - b.order);
    const r = screens.filter((s) => s.status === 'Not started').sort((a, b) => a.order - b.order);
    return q.concat(r).slice(0, n);
  }

  // status of every screen at the end of each day, replayed from the events
  function series(screens, days) {
    const ids = new Set(screens.map((s) => s.id));
    const evs = (S.data.events || []).filter((e) => ids.has(e.id)).slice().sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0));
    const first = {};
    evs.forEach((e) => { if (!(e.id in first)) first[e.id] = e.from; });
    const cur = {};
    screens.forEach((s) => (cur[s.id] = s.id in first ? first[s.id] : s.status));
    const allEvs = S.data.events || [];
    const firstDay = allEvs.length ? allEvs.map((e) => e.t.slice(0, 10)).sort()[0] : null;
    const out = [];
    let i = 0;
    days.forEach((d) => {
      while (i < evs.length && evs[i].t.slice(0, 10) <= d) { cur[evs[i].id] = evs[i].to; i++; }
      let done = 0; let fl = 0;
      screens.forEach((s) => {
        const st = cur[s.id];
        if (FINISHED.includes(st)) done++;
        else if (WORKING.includes(st)) fl++;
      });
      out.push({ d, done, fl, total: screens.length, pre: !firstDay || d < firstDay });
    });
    return out;
  }
  function lastDays(n) {
    const out = [];
    const t = new Date();
    for (let k = n - 1; k >= 0; k--) out.push(dayISO(new Date(t.getFullYear(), t.getMonth(), t.getDate() - k)));
    return out;
  }
  function allDays() {
    const evs = S.data.events || [];
    const firstT = evs.reduce((m, e) => (m && m < e.t ? m : e.t), null);
    const start = parseT(firstT) || new Date();
    const out = [];
    const t = new Date();
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() - 1);
    while (dayISO(d) <= dayISO(t) && out.length < 400) { out.push(dayISO(d)); d.setDate(d.getDate() + 1); }
    return out.length >= 7 ? out : lastDays(7);
  }

  // the newest log line or status change
  function timeline() {
    const d = S.data;
    const items = [];
    (d.log || []).forEach((l, i) => items.push({ t: l.t, k: 'log', text: l.text, i }));
    const grouped = [];
    (d.events || []).forEach((e) => {
      const g = grouped.find((x) => x.t === e.t && x.to === e.to && x.by === e.by);
      if (g) g.ids.push(e.id); else grouped.push({ t: e.t, to: e.to, by: e.by, ids: [e.id] });
    });
    grouped.forEach((g) => items.push({ t: g.t, k: 'ev', g }));
    // newest first; a log line sorts above status changes of the same minute
    items.sort((a, b) => (a.t < b.t ? 1 : a.t > b.t ? -1 : a.k === b.k ? (b.i || 0) - (a.i || 0) : a.k === 'log' ? -1 : 1));
    return items;
  }

  // ------------------------------------------------------------------ routing
  function route() {
    const h = location.hash.replace(/^#\/?/, '');
    const [view, id] = h.split('/');
    return { view: VIEWS.includes(view) ? view : 'overview', id: id ? decodeURIComponent(id) : null };
  }
  function go(hash, replace) {
    if (location.hash === hash) { render(); return; }
    if (replace) { history.replaceState(null, '', hash); render(); } else location.hash = hash;
  }

  // ------------------------------------------------------------------ shell
  const root = $('#root');
  let shell = null;
  const mqCompact = window.matchMedia('(max-width: 1099px)');
  const mqPhone = window.matchMedia('(max-width: 699px)');
  const mqNarrow = window.matchMedia('(max-width: 899px)');     // too narrow for Chat beside the page
  // a phone-sized window (the Mac app's chat panel is as narrow, but it is no phone)
  const isPhone = () => mqPhone.matches && !PANEL;

  function ensureShell() {
    if (shell) return shell;
    root.innerHTML = `<div class="win" id="win">
      <aside class="sb" id="sb" aria-label="Sidebar"></aside>
      <div class="sb-scrim" data-act="peekClose" aria-hidden="true"></div>
      <div class="main" id="main">
        <div id="banner"></div>
        <header class="tb" id="tb"></header>
        <main class="content" id="content"></main>
      </div>
    </div>`;
    shell = { win: $('#win'), sb: $('#sb'), tb: $('#tb'), content: $('#content'), banner: $('#banner') };
    // the browser's own sidebar slides too (its column width animates): the breakpoints stand still meanwhile
    const slides = (e) => e.target === shell.win && e.propertyName === 'grid-template-columns';
    shell.win.addEventListener('transitionrun', (e) => { if (slides(e)) holdLayout(true); });
    ['transitionend', 'transitioncancel'].forEach((t) => shell.win.addEventListener(t, (e) => { if (slides(e)) holdLayout(false); }));
    applySidebar();
    return shell;
  }

  function applySidebar() {
    if (!shell) return;
    const phone = mqPhone.matches;
    const auto = mqCompact.matches;
    // Chat is a column beside the page in a wide window, and comes over the page in a narrow one
    const chat = !NATIVE && S.side === 'chat';
    const compact = !phone && (chat ? mqNarrow.matches : (auto || S.sbPref === 'compact'));
    if (chat || !compact || !auto) S.peek = false;
    shell.win.classList.toggle('compact', compact);
    shell.win.classList.toggle('peek', compact && S.peek);
    shell.win.classList.toggle('phone', phone);
    shell.win.classList.toggle('chat', chat);
    const open = !compact || S.peek;
    $$('[data-act="sidebar"]').forEach((b) => {
      const label = chat ? 'Close Chat' : open ? 'Collapse sidebar' : 'Expand sidebar';
      b.setAttribute('aria-expanded', String(open || chat));
      b.setAttribute('aria-label', label);
      b.dataset.tipText = `${label}  ${chat ? KEY + '0' : MAC ? '⌃⌘S' : 'Ctrl+\\'}`;
    });
  }
  function toggleSidebar() {
    if (!NATIVE && S.side === 'chat') { setSide('views'); return; }
    if (mqPhone.matches) return;
    if (mqCompact.matches) S.peek = !S.peek;
    else { S.sbPref = S.sbPref === 'compact' ? 'expanded' : 'compact'; store.set('sidebar', S.sbPref); }
    hideTip();
    applySidebar();
  }

  function ringSVG(st, size = 20) {
    const r = 7;
    const C = 2 * Math.PI * r;
    const dl = (C * st.done) / (st.total || 1);
    const fl = (C * st.working) / (st.total || 1);
    return `<svg class="ring" width="${size}" height="${size}" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="${r}" class="r-tr"/>${
      fl > 0 ? `<circle cx="10" cy="10" r="${r}" class="r-fl" stroke-dasharray="${fl.toFixed(2)} ${C.toFixed(2)}" stroke-dashoffset="${(-dl).toFixed(2)}"/>` : ''}${
      dl > 0 ? `<circle cx="10" cy="10" r="${r}" class="r-dn" stroke-dasharray="${dl.toFixed(2)} ${C.toFixed(2)}"/>` : ''}</svg>`;
  }

  // the workspace badge: the workspace's colour and initials
  const WS_COLORS = { blue: '#0A84FF', green: '#30C85A', orange: '#FF9F0A', purple: '#AF52DE', pink: '#FF375F', teal: '#30B0C7',
    indigo: '#5E5CE6', red: '#FF453A', yellow: '#E5B800', gray: '#8E8E93' };
  const wsBadge = (w, cls = '') => `<span class="wsb ${cls}" style="--wc:${WS_COLORS[w.color] || WS_COLORS.blue}" aria-hidden="true">${esc(w.initials || '·')}</span>`;
  function wsSwitcherHTML() {
    const w = curWS();
    const st = S.data ? stats(S.data.screens) : null;
    return `<button class="ws-btn" data-act="wsMenu" aria-haspopup="menu" aria-expanded="${S.wsMenu ? 'true' : 'false'}" aria-label="Workspace: ${esc(w.name)}">
        ${wsBadge(w)}<span class="ws-t"><b>${esc(w.name)}</b><span>${st ? `${st.done} of ${st.total} done` : '&nbsp;'}</span></span>${icon('updown', 'sm ws-chev')}</button>`;
  }

  function sidebarHTML(view) {
    if (S.side === 'chat') return `<div class="sb-top">${modeSwitchHTML()}</div>${chatPanelHTML()}`;
    const d = S.data;
    const waiting = d.decisions.filter(waitsOnUser).length;
    const nav = [
      ['overview', 'Overview', 'home'], ['screens', 'Screens', 'caps', d.screens.length],
      ['decisions', 'Decisions', 'decide', null, waiting], ['activity', 'Activity', 'clock'],
    ];
    const items = nav.map(([k, label, ic, count, badge]) => `<a class="nv" href="#/${k}" data-nav="${k}" ${view === k ? 'aria-current="page"' : ''} data-tip-text="${label}${badge ? ` · ${badge} waiting on you` : ''}" data-tip-pos="right"${badge ? ` aria-label="${label}, ${badge} waiting on you"` : ''}>
        <span class="ic">${icon(ic)}${badge ? `<span class="badge" aria-hidden="true">${badge}</span>` : ''}</span>
        <span class="lbl">${label}</span>${count != null ? `<span class="cnt">${count}</span>` : badge ? `<span class="cnt hot" aria-hidden="true">${badge}</span>` : ''}</a>`).join('');
    const batches = d.batches.length ? ['All'].concat(d.batches).map((b) => {
      const st = stats(b === 'All' ? d.screens : d.screens.filter((s) => s.batch === b));
      return `<button class="bt" role="radio" aria-checked="${S.batch === b}" data-act="batch" data-v="${esc(b)}">
        <span class="ic">${ringSVG(st)}</span><span class="lbl">${b === 'All' ? 'All batches' : esc(b)}</span><span class="cnt${st.total ? '' : ' oos'}">${st.total ? `${st.done}/${st.total}` : 'Out of scope'}</span></button>`;
    }).join('') : '';
    return `<div class="sb-top">${modeSwitchHTML()}</div>
      <div class="sb-head">${wsSwitcherHTML()}</div>
      <nav class="nav" aria-label="Sections">${items}</nav>
      ${batches ? `<div class="sb-sec" role="radiogroup" aria-labelledby="fb-h"><h3 id="fb-h">Fix Batches</h3>${batches}</div>` : ''}`;
  }

  function scopeTag() {
    if (S.batch === 'All') return '';
    return `<button class="scope" data-act="batch" data-v="All" data-tip-text="Show all batches">${icon('layers', 'sm')}<span>${esc(S.batch)}</span>${icon('close', 'xs')}</button>`;
  }

  const themeIcon = () => (theme === 'light' ? 'sun' : theme === 'dark' ? 'moon' : 'halfcircle');
  function toolbarHTML(view) {
    return `<button class="tb-btn" data-act="sidebar" aria-controls="sb">${icon('sidebar')}</button>
      ${view === 'overview' || view === 'screens' ? scopeTag() : ''}
      <div class="tb-actions">
        <button class="tb-btn theme-btn" data-act="theme" aria-haspopup="menu" aria-expanded="${S.themeMenu ? 'true' : 'false'}" aria-label="Appearance: ${THEMES[theme]}" data-tip-text="Appearance: ${THEMES[theme]}">${icon(themeIcon())}</button>
        <button class="searchbtn" data-act="palette" aria-label="Search" aria-keyshortcuts="${MAC ? 'Meta+K' : 'Control+K'}">${icon('search', 'sm')}<span class="ph">Search</span><kbd>${KEY}K</kbd></button>
        <a class="btn primary" href="${api('/api/export')}" download data-tip-text="Download the tracker as an Excel file">${icon('download', 'sm')}<span>Export</span></a>
      </div>`;
  }

  // ------------------------------------------------------------------ overview
  function overviewHTML() {
    const sc = scoped();
    const st = stats(sc);
    return `<div class="ov">
      ${activeCardHTML(sc, st)}
      ${statusCardHTML(sc, st)}
      ${mapCardHTML()}
      ${progressCardHTML(sc)}
      <div class="c-side">${waitingCardHTML()}${latestCardHTML()}</div>
    </div>`;
  }

  // the progress pips: one per step of the process, the current one in its status colour
  function pipeHTML(s) {
    if (s.status === OOS) return `<span class="pipe oos" aria-hidden="true"><b>Out of scope</b></span>`;
    const idx = stepOf(s.status);
    return `<span class="pipe" aria-hidden="true">${STEPS.map((x, i) => {
      let c = '';
      if (i < idx) c = 'past';
      else if (i === idx && (i > 0 || s.status === 'Up next')) c = 'cur ' + SCLS[s.status];
      return `<i class="${c}"></i>`;
    }).join('')}</span>`;
  }
  const pfHTML = (s) => `<span class="pf" aria-label="Findings: P1 ${s.p1}, P2 ${s.p2}, P3 ${s.p3}"><span><em>P1</em>${s.p1}</span><span><em>P2</em>${s.p2}</span><span><em>P3</em>${s.p3}</span></span>`;

  function activeCardHTML(sc, st) {
    // Blocked screens are listed and counted under the Done tab, not under Fixing (their status stays Blocked)
    const tabs = [['flight', 'Fixing', st.flight], ['next', 'Up Next', null], ['done', 'Done', st.done + st.blocked]];
    let rows; let empty;
    if (S.ovTab === 'next') { rows = upNext(sc, 12); empty = 'Every screen has started.'; }
    else if (S.ovTab === 'done') { rows = sc.filter((s) => FINISHED.includes(s.status) || s.status === 'Blocked').sort(byRecent); empty = 'No screen is done yet.'; }
    else { rows = sc.filter((s) => FLIGHT.includes(s.status)).sort(byRecent); empty = 'Nothing is being worked on right now.'; }
    const lastCol = S.ovTab === 'next' ? 'Fix #' : 'Updated';
    const body = rows.map((s) => `<tr class="row" data-act="open" data-id="${esc(s.id)}" data-tip="screen">
        <td class="c-name"><button class="rb" data-act="open" data-id="${esc(s.id)}"><span class="nm">${esc(s.name)}</span><span class="sub"><span class="mono">${esc(s.id)}</span> · ${esc(menuName(s.menu))}</span></button></td>
        <td class="c-st">${stCell(s)}</td>
        <td class="c-pipe">${pipeHTML(s)}</td>
        <td class="c-f">${pfHTML(s)}</td>
        <td class="c-upd num">${S.ovTab === 'next' ? '#' + esc(s.order) : fmtShort(s.updated)}</td></tr>`).join('');
    return `<section class="card c-active" aria-labelledby="act-h">
      <div class="ch"><h2 id="act-h">Screens</h2>
        <div class="seg" role="group" aria-label="Show">${SEG_THUMB}${tabs.map(([k, l, n]) => `<button data-act="ovTab" data-v="${k}" aria-pressed="${S.ovTab === k}">${l}${n != null ? `<span class="n">${n}</span>` : ''}</button>`).join('')}</div>
        <div class="end"><a class="link" href="#/screens">All ${sc.length}${icon('chevR', 'xs')}</a></div>
      </div>
      <div class="cb flush" data-scroll="ov-active">${rows.length ? `<table class="tbl t-active">
        <colgroup><col class="w-name"><col class="w-st"><col class="w-pipe"><col class="w-f"><col class="w-upd"></colgroup>
        <thead><tr><th class="c-name">Screen</th><th class="c-st">Status</th><th class="c-pipe">Progress</th><th class="c-f">Findings</th><th class="c-upd num">${lastCol}</th></tr></thead>
        <tbody>${body}</tbody></table>` : `<div class="empty">${empty}</div>`}</div>
    </section>`;
  }

  // one donut sector, like Swift Charts' SectorMark: flat ends with softened corners and an even gap to its
  // neighbours. Angles run clockwise from 12 o'clock; `gap` is the width of the gap in viewBox units.
  function sectorPath(r0, r1, a0, a1, gap, cr) {
    const pt = (r, a) => `${(60 + r * Math.sin(a)).toFixed(2)} ${(60 - r * Math.cos(a)).toFixed(2)}`;
    const off = (r) => Math.asin(Math.min(1, gap / 2 / r));
    const o0 = a0 + off(r1); const o1 = a1 - off(r1);   // outer edge, inset so the gap is the same width all along
    const i0 = a0 + off(r0); const i1 = a1 - off(r0);   // inner edge
    if (o1 - o0 <= 0.002 || i1 - i0 <= 0.002) {         // too thin for a sector: a sliver along the outside
      const m = (a0 + a1) / 2;
      return `M${pt(r0, m)} L${pt(r1, m)}`;
    }
    const c = Math.max(0, Math.min(cr, (r1 - r0) / 2, ((o1 - o0) * r1) / 2.2, ((i1 - i0) * r0) / 2.2));
    const co = c / r1; const ci = c / r0;
    const big = (x) => (x > Math.PI ? 1 : 0);
    return `M${pt(r1 - c, o0)} Q${pt(r1, o0)} ${pt(r1, o0 + co)} A${r1} ${r1} 0 ${big(o1 - o0 - 2 * co)} 1 ${pt(r1, o1 - co)} `
      + `Q${pt(r1, o1)} ${pt(r1 - c, o1)} L${pt(r0 + c, i1)} Q${pt(r0, i1)} ${pt(r0, i1 - ci)} `
      + `A${r0} ${r0} 0 ${big(i1 - i0 - 2 * ci)} 0 ${pt(r0, i0 + ci)} Q${pt(r0, i0)} ${pt(r0 + c, i0)} Z`;
  }
  const ringPath = (r0, r1) => `M${60 - r1} 60a${r1} ${r1} 0 1 0 ${2 * r1} 0a${r1} ${r1} 0 1 0 ${-2 * r1} 0Z M${60 - r0} 60a${r0} ${r0} 0 1 1 ${2 * r0} 0a${r0} ${r0} 0 1 1 ${-2 * r0} 0Z`;

  function statusCardHTML(sc, st) {
    const total = st.total;
    const cls = CLASSES.map((c) => ({ ...c, n: sc.filter((s) => c.test(s.status)).length }));
    // donut: Done, Fixing, Blocked and Not started as sectors from 12 o'clock, each in its own colour
    const R0 = 39; const R1 = 56; const GAP = 2.6; const CR = 3.2;
    const live = cls.filter((c) => c.n > 0);
    let at = 0;
    const segs = !total ? `<path class="seg todo empty" d="${ringPath(R0, R1)}" fill-rule="evenodd"/>`
      : live.length === 1 ? `<path class="seg ${live[0].k}" data-cls="${live[0].k}" d="${ringPath(R0, R1)}" fill-rule="evenodd"/>`
      : live.map((c) => {
        const a0 = at; at += (2 * Math.PI * c.n) / total;
        return `<path class="seg ${c.k}" data-cls="${c.k}" d="${sectorPath(R0, R1, a0, at, GAP, CR)}"/>`;
      }).join('');
    const subOf = (c) => {
      if (c.k === 'flight') return '';
      if (c.k === 'todo') return st.by['Up next'] ? `${st.by['Up next']} up next` : '';
      if (c.k === 'done') {
        const q = QA.filter((x) => st.by[x]).map((x) => `<span class="nw">${st.by[x]} ${x.toLowerCase()}</span>`).join(' · ');
        return q || (st.findingsDone ? `${st.findingsDone} findings fixed` : '');
      }
      return '';
    };
    const legend = cls.map((c) => {
      const sub = subOf(c);
      return `<li><button class="lg-row" data-act="filterStatus" data-v="${c.f}" data-cls="${c.k}" data-n="${c.n}" data-label="${esc(c.label)}">
        <i class="sw ${c.k}" aria-hidden="true"></i><span class="t">${c.label}${sub ? `<small>${sub}</small>` : ''}</span>
        <span class="n">${c.n}</span><span class="p">${round(pct(c.n, total))}%</span>${icon('chevR', 'xs go')}</button></li>`;
    }).join('');
    const center = `<b>${round(st.pct)}%</b><span>done</span>`;
    const decSettled = S.data.decisions.filter((x) => !D_OPEN.includes(x.status)).length;
    const aria = `${st.done} of ${total} done, ${st.flight} fixing, ${st.blocked} blocked, ${st.todo} not started${st.oos ? `, ${st.oos} out of scope (not counted)` : ''}`;
    const oosRow = st.oos ? `<li><button class="lg-row" data-act="filterStatus" data-v="${OOS}" data-cls="oos" data-n="${st.oos}" data-label="${OOS}">
        <i class="sw oos" aria-hidden="true"></i><span class="t">${OOS}<small>not counted</small></span>
        <span class="n">${st.oos}</span><span class="p"></span>${icon('chevR', 'xs go')}</button></li>` : '';
    return `<section class="card c-status" aria-labelledby="st-h">
      <div class="ch"><h2 id="st-h">Status</h2><div class="end faint">${S.batch === 'All' ? plural(total, 'screen') : `${esc(S.batch)} · ${total}`}${st.oos ? ` · ${st.oos} out of scope` : ''}</div></div>
      <div class="cb st-body">
        <div class="donut" role="img" aria-label="${esc(aria)}">
          <svg viewBox="0 0 120 120" aria-hidden="true">${segs}</svg>
          <div class="dn-center" data-center="${esc(center)}">${center}</div>
        </div>
        <ul class="lg-list" aria-label="Screens by status">${legend}${oosRow}</ul>
      </div>
      <div class="cf meters">${meterHTML('Findings fixed', st.findingsDone, st.findings)}${meterHTML('Decisions settled', decSettled, S.data.decisions.length)}</div>
    </section>`;
  }

  const meterHTML = (label, a, b) => `<div class="mt"><div class="mt-l"><span>${label}</span><b>${a}<small> of ${b}</small></b></div>
    <div class="meter" role="img" aria-label="${a} of ${b} ${label.toLowerCase()}"><i style="width:${pct(a, b)}%"></i></div></div>`;

  function capHTML(s, extra = '') {
    return `<button class="cap ${SCLS[s.status]} ${extra}" data-key="cap:${esc(s.id)}" data-act="open" data-id="${esc(s.id)}" data-tip="screen" tabindex="-1" aria-label="${esc(s.id + ' ' + s.name + ', ' + s.status)}"></button>`;
  }

  function mapCardHTML() {
    const d = S.data;
    const groups = S.mapBy === 'batch'
      ? d.batches.map((b) => ({ label: b, sub: '', items: d.screens.filter((s) => s.batch === b), act: 'batch', v: b }))
      : d.menus.map((m) => ({ label: menuName(m), sub: /other menu/i.test(menuLabel(m)) ? 'Other menu' : '', items: d.screens.filter((s) => s.menu === m), act: 'filterMenu', v: m }));
    const filtering = S.batch !== 'All';
    const rows = groups.map((g) => {
      const st = stats(g.items);
      const caps = g.items.map((s) => capHTML(s, filtering ? (s.batch === S.batch ? 'hit' : 'dim') : '')).join('');
      return `<div class="mrow" data-key="m:${g.act}:${esc(g.v)}" data-act="${g.act}" data-v="${esc(g.v)}">
        <button class="mlab" data-act="${g.act}" data-v="${esc(g.v)}" data-tip-text="${esc(g.label)} · ${g.act === 'batch' ? 'show only this batch' : 'see these screens'}"><span class="mn">${esc(g.label)}</span><span class="mc">${g.sub ? g.sub + ' · ' : ''}${st.done}/${st.total}${st.working ? ` · ${st.working} fixing` : ''}</span></button>
        <div class="mcaps" role="group" aria-label="${esc(g.label)}">${caps}</div></div>`;
    }).join('');
    const lg = [['ns', 'Not started'], ['next', 'Up next'], ['wip', 'Fixing'], ['done', 'Done'], ['tsg', 'Testing'], ['tst', 'Tested'], ['mrg', 'Merged'], ['blk', 'Blocked'], ['oos', 'Out of scope']]
      .map(([k, l]) => `<span><i class="lgd ${k}" aria-hidden="true"></i>${l}</span>`).join('');
    return `<section class="card c-map" aria-labelledby="map-h">
      <div class="ch"><h2 id="map-h">Screen Map</h2>
        <div class="end"><div class="seg" role="group" aria-label="Group by">${SEG_THUMB}${[['menu', 'Menu'], ['batch', 'Batch']].map(([k, l]) => `<button data-act="mapBy" data-v="${k}" aria-pressed="${S.mapBy === k}">${l}</button>`).join('')}</div></div>
      </div>
      <div class="cb" data-scroll="ov-map" data-map>${rows}</div>
      <div class="cf legend" aria-hidden="true">${lg}</div>
    </section>`;
  }

  function progressCardHTML(sc) {
    const days = S.range === 'all' ? allDays() : lastDays(S.range);
    const data = series(sc.filter((s) => s.status !== OOS), days);
    const today = dayISO(new Date());
    const n = data.length;
    const last = data[n - 1];
    const every = n > 21 ? Math.ceil(n / 7) : n > 10 ? 2 : 1;
    const cols = data.map((x, i) => {
      const dp = pct(x.done, x.total);
      const fp = pct(x.done + x.fl, x.total);
      const isToday = x.d === today;
      const tag = isToday && fp > 0 ? `<span class="vtag" style="bottom:calc(${fp}% + 6px)">${round(fp)}%</span>` : '';
      return `<div class="pc ${x.pre ? 'pre' : ''} ${isToday ? 'today' : ''}" data-tip="day" data-i="${i}">
        <span class="tube"></span>${fp > 0 ? `<span class="fl" style="height:${fp}%"></span>` : ''}${dp > 0 ? `<span class="dn" style="height:${dp}%"></span>` : ''}${tag}</div>`;
    }).join('');
    const xl = data.map((x, i) => {
      const isToday = x.d === today;
      const show = isToday || (n - 1 - i) % every === 0;
      return `<span class="${isToday ? 'today' : ''}">${show ? (isToday ? 'Today' : esc(fmtDay(parseT(x.d)))) : ''}</span>`;
    }).join('');
    const ticks = [100, 75, 50, 25, 0];
    const grid = ticks.map((v) => `<i style="bottom:${v}%"></i>`).join('');
    const yax = ticks.map((v) => `<span style="bottom:${v}%">${v}%</span>`).join('');
    const ranges = [[14, '2W'], [30, '1M'], ['all', 'All']];
    const aria = `Share of screens done and being fixed per day over ${n} days. Today ${last ? round(pct(last.done, last.total)) : 0} percent done and ${last ? round(pct(last.fl, last.total)) : 0} percent being fixed.`;
    progressData = data;
    return `<section class="card c-prog" aria-labelledby="pg-h">
      <div class="ch"><h2 id="pg-h">Progression</h2>
        <div class="end"><div class="seg" role="group" aria-label="Time range">${SEG_THUMB}${ranges.map(([v, l]) => `<button data-act="range" data-v="${v}" aria-pressed="${String(S.range) === String(v)}" data-tip-text="${v === 'all' ? 'Since work started' : `Last ${v} days`}">${l}</button>`).join('')}</div></div>
      </div>
      <div class="cb pg-body">
        <div class="pg-sum"><span><i class="lgd flight" aria-hidden="true"></i>Fixing <b>${last ? round(pct(last.fl, last.total)) : 0}%</b></span><span><i class="lgd done" aria-hidden="true"></i>Done <b>${last ? round(pct(last.done, last.total)) : 0}%</b></span></div>
        <div class="plot" role="img" aria-label="${esc(aria)}">
          <div class="yax" aria-hidden="true">${yax}</div>
          <div class="pl-area"><div class="grid" aria-hidden="true">${grid}</div><div class="pcols">${cols}</div></div>
          <div class="xax" aria-hidden="true">${xl}</div>
        </div>
      </div>
    </section>`;
  }
  let progressData = [];

  function waitingCardHTML() {
    const d = S.data;
    const open = d.decisions.filter((x) => D_OPEN.includes(x.status)).sort((a, b) => a.n - b.n);
    const waiting = open.filter(waitsOnUser).length;
    const list = open.map((x) => `<a class="wrow${answered(x) ? ' sent' : ''}" href="#/decisions/${x.n}"><span class="num">#${x.n}</span><span class="tx"><span class="t">${esc(x.topic)}</span><span class="s">${answered(x) ? 'Answered · waiting for Claude' : `${esc(x.status)}${x.myNotes ? ' · you answered' : ''}`}</span></span>${icon('chevR', 'xs')}</a>`).join('');
    return `<section class="card c-wait" aria-labelledby="w-h">
      <div class="ch"><span class="ch-ic ${waiting ? 'warn' : 'ok'}" aria-hidden="true">${icon(waiting ? 'excl' : 'checkc', 'sm')}</span><h2 id="w-h">Waiting on You</h2><span class="end"><span class="cnt-pill ${waiting ? 'warn' : ''}">${waiting}</span></span></div>
      <div class="cb" data-scroll="ov-wait">${open.length ? list : `<p class="calm-msg">${d.decisions.length ? `Nothing right now. All ${plural(d.decisions.length, 'decision')} are settled.` : 'Nothing right now. Questions Claude has for you show up here.'}</p>`}</div>
      <div class="cf">Answer here or in your Claude chat.</div>
    </section>`;
  }

  function latestCardHTML() {
    const it = timeline()[0];
    let body = '<p class="lt">Nothing logged yet.</p>';
    if (it && it.k === 'log') body = `<p class="lt">${esc(it.text)}</p>`;
    else if (it) body = `<p class="lt">${it.g.ids.length === 1 ? `<b>${esc((S.data.screens.find((s) => s.id === it.g.ids[0]) || {}).name || it.g.ids[0])}</b> moved to` : `<b>${it.g.ids.length} screens</b> moved to`} ${esc(it.g.to)}.</p>`;
    return `<a class="card c-latest" href="#/activity">
      <div class="lt-h"><span class="ch-ic info" aria-hidden="true">${icon('clock', 'sm')}</span><b>Latest Update</b><span>${it ? fmtWhen(it.t) : ''}</span>${icon('chevR', 'xs')}</div>
      ${body}
    </a>`;
  }

  // ------------------------------------------------------------------ screens (split view)
  function statusMatch(st) {
    if (!S.fStatus) return true;
    if (GROUPS[S.fStatus]) return GROUPS[S.fStatus].test(st);
    return st === S.fStatus;
  }
  function filteredScreens() {
    const q = S.q.trim().toLowerCase();
    const list = scoped().filter((s) => statusMatch(s.status) && (!S.fMenu || s.menu === S.fMenu) &&
      (!q || [s.id, s.name, s.note, s.menu, s.batch, (s.covers || []).join(' ')].join(' ').toLowerCase().includes(q)));
    const { key, dir } = S.sort;
    const val = {
      order: (s) => s.order, id: (s) => S.data.screens.indexOf(s), batch: (s) => S.data.batches.indexOf(s.batch),
      status: (s) => PIPE_RANK.indexOf(s.status), findings: (s) => findings(s), updated: (s) => s.updated || '',
    }[key] || ((s) => s.order);
    return list.slice().sort((a, b) => {
      const x = val(a); const y = val(b);
      return (x < y ? -1 : x > y ? 1 : a.order - b.order) * dir;
    });
  }

  // a pop-up menu in the Linear manner: a quiet rounded button with a chevron; filled while it filters something
  // (the first option is the one that shows everything)
  function popup(act, label, value, options) {
    const on = options.length && value !== options[0][0];
    return `<label class="popup${on ? ' on' : ''}"><span class="sr">${label}</span><select data-act="${act}">${options.map(([v, l]) => `<option value="${esc(v)}" ${value === v ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>${icon('chev', 'xs chev')}</label>`;
  }

  function screensHTML(selId) {
    const d = S.data;
    const list = filteredScreens();
    const sel = selId ? d.screens.find((s) => s.id === selId) : null;
    const statusOpts = [['', 'Any status'], ['g:flight', 'Fixing or blocked'], ['g:todo', 'Not started yet'], ['g:done', 'Done or later'], ['g:qa', 'Testing, tested or merged']].concat(STATUS.map((s) => [s, s]));
    const menuOpts = [['', 'Any menu']].concat(d.menus.map((m) => [m, menuLabel(m)]));
    const batchOpts = [['All', 'All batches']].concat(d.batches.map((b) => [b, b]));
    const filtered = S.q || S.fStatus || S.fMenu || S.batch !== 'All';
    return `<div class="split ${sel ? 'has-sel' : ''} ${sel && S.fresh ? 'fresh' : ''}" style="--insp-w:${S.inspW}px">
      <section class="card list-card" aria-label="Screen list">
        <div class="fbar" role="search">
          <label class="field-search"><span class="sr">Search screens</span>${icon('search', 'sm')}<input id="q" type="search" placeholder="Search screens" value="${esc(S.q)}" data-act="q" autocomplete="off" spellcheck="false"><kbd aria-hidden="true">/</kbd></label>
          ${popup('fStatus', 'Status', S.fStatus, statusOpts)}
          ${popup('fMenu', 'Menu', S.fMenu, menuOpts)}
          ${popup('batchSel', 'Fix batch', S.batch, batchOpts)}
          <button class="tog" data-act="group" aria-pressed="${S.group}" aria-label="Group by menu" data-tip-text="Group by menu">${icon('group', 'sm')}</button>
          ${filtered ? `<span class="count" aria-live="polite">${list.length} of ${d.screens.length}</span><button class="linkbtn" data-act="clearFilters">Clear</button>` : ''}
        </div>
        <div class="tbl-scroll" data-scroll="screens-list">${list.length ? screenTableHTML(list, sel) : `<div class="empty">No screens match.<br><button class="linkbtn" data-act="clearFilters">Clear search and filters</button></div>`}</div>
      </section>
      <div class="split-scrim" data-act="deselect" aria-hidden="true"></div>
      <div class="split-handle" role="separator" aria-orientation="vertical" aria-label="Resize details" aria-valuemin="320" aria-valuemax="560" aria-valuenow="${S.inspW}" tabindex="0" data-tip-text="Drag to resize"></div>
      <aside class="card insp" aria-label="Screen details">${sel ? inspectorHTML(sel) : inspectorEmptyHTML(list)}</aside>
    </div>`;
  }

  function screenTableHTML(list, sel) {
    // least important columns last: narrow lists drop them from the end
    const cols = [['order', '#', 'c-ord'], ['id', 'Screen', 'c-name'], ['status', 'Status', 'c-st'], ['findings', 'Findings', 'c-f'], ['batch', 'Batch', 'c-batch'], ['updated', 'Updated', 'c-upd']];
    const th = cols.map(([k, label, c]) => {
      const on = S.sort.key === k;
      return `<th class="${c}" aria-sort="${on ? (S.sort.dir > 0 ? 'ascending' : 'descending') : 'none'}"><button class="sorth ${on ? 'on' : ''}" data-act="sort" data-k="${k}">${label}${icon(on && S.sort.dir < 0 ? 'down' : 'up', 'xs ar')}</button></th>`;
    }).join('');
    const tabTarget = sel && list.includes(sel) ? sel.id : list[0] && list[0].id;
    const row = (s) => {
      const on = sel && sel.id === s.id;
      return `<tr class="row ${on ? 'sel' : ''}" data-act="select" data-id="${esc(s.id)}" aria-selected="${on ? 'true' : 'false'}">
      <td class="c-ord num">${esc(s.order)}</td>
      <td class="c-name"><button class="rb" data-act="select" data-id="${esc(s.id)}" data-row="${esc(s.id)}" tabindex="${s.id === tabTarget ? 0 : -1}"><span class="nm">${esc(s.name)}</span><span class="sub"><span class="mono">${esc(s.id)}</span>${S.group ? '' : ' · ' + esc(menuName(s.menu))}</span></button></td>
      <td class="c-st">${stCell(s)}</td>
      <td class="c-f">${pfHTML(s)}</td>
      <td class="c-batch">${esc(s.batch)}</td>
      <td class="c-upd num">${fmtShort(s.updated)}</td></tr>`;
    };
    let body = '';
    if (S.group) {
      S.data.menus.forEach((m) => {
        const items = list.filter((s) => s.menu === m);
        if (!items.length) return;
        const st = stats(S.data.screens.filter((s) => s.menu === m && (S.batch === 'All' || s.batch === S.batch)));
        body += `<tbody><tr class="grp"><th colspan="6" scope="rowgroup"><span class="gn">${esc(menuLabel(m))}</span><span class="gc">${st.done}/${st.total} done${st.working ? ` · ${st.working} fixing` : ''}</span></th></tr>${items.map(row).join('')}</tbody>`;
      });
    } else body = `<tbody>${list.map(row).join('')}</tbody>`;
    return `<table class="tbl t-screens ${S.group ? 'grouped' : ''}" aria-label="Screens" aria-rowcount="${list.length}">
      <colgroup><col class="w-ord"><col class="w-name"><col class="w-st"><col class="w-f"><col class="w-batch"><col class="w-upd"></colgroup>
      <thead><tr>${th}</tr></thead>${body}</table>`;
  }

  // the steps bar: Not started → Fixing → Done → Testing → Tested → Merged; the current step shows the status
  // itself (Up next, Fixing, Blocked) in its colour
  function stepsHTML(s) {
    if (s.status === OOS) return `<div class="steps-wrap oos" aria-hidden="true"><div class="steps-lbl"><span class="on">Out of scope — not worked on</span></div></div>`;
    const idx = stepOf(s.status);
    const segs = STEPS.map((x, i) => {
      let cls = '';
      if (i < idx) cls = 'past';
      else if (i === idx && (i > 0 || s.status === 'Up next')) cls = `cur ${SCLS[s.status]}`;
      return `<span class="${cls}"></span>`;
    }).join('');
    const labels = STEPS.map((x, i) => `<span class="${i === idx ? 'on' : ''}">${esc(i === idx ? (SHORT[s.status] || s.status) : x)}</span>`).join('');
    return `<div class="steps-wrap" aria-hidden="true"><div class="steps">${segs}</div><div class="steps-lbl">${labels}</div></div>`;
  }

  const copyRow = (v, label) => `<div class="copyrow">${label ? `<span class="lbl">${label}</span>` : ''}<code>${esc(v)}</code><button class="copy" data-act="copy" data-v="${esc(v)}" aria-label="Copy ${esc(v)}" data-tip-text="Copy">${icon('copy', 'sm')}</button></div>`;

  function inspectorHTML(s) {
    const d = S.data;
    const max = Math.max(1, s.p1, s.p2, s.p3);
    const pb = (k, v) => `<div class="pbar"><span>${k}</span><span class="tr"><i style="width:${(100 * v) / max}%"></i></span><b>${v}</b></div>`;
    const decs = new Set(d.decisions.map((x) => x.n));
    const checks = (s.checks || []).map((n) => (decs.has(n)
      ? `<a class="idc" href="#/decisions/${n}">#${n}</a>`
      : `<span class="idc plain" data-tip-text="Needs-check item #${n}">#${n}</span>`)).join('');
    const hist = (d.events || []).filter((e) => e.id === s.id).slice().reverse().map((e) =>
      `<li><span class="t">${fmtWhen(e.t)}</span>${statusPill(e.to, true)}<span class="by">${esc(BY[e.by] || e.by || '')}</span></li>`).join('');
    const key = `screen:${s.id}`;
    const hasDraft = key in S.drafts && S.drafts[key] !== (s.myNotes || '');
    return `<div class="insp-head"><span class="idc plain">${esc(s.id)}</span><span class="crumb">${esc(menuLabel(s.menu))}</span>
        <button class="icon-btn" data-act="deselect" aria-label="Close details" data-tip-text="Close  Esc">${icon('close', 'sm')}</button></div>
      <div class="insp-body" data-scroll="insp-${esc(s.id)}">
        <h2 class="insp-title" id="insp-title">${esc(s.name)}</h2>
        <div class="insp-meta">${statusPill(s.status)}<span class="tag">${esc(s.batch)}</span><span class="tag">Fix #${esc(s.order)}</span>${s.updated ? `<span class="faint">${fmtWhen(s.updated)}</span>` : ''}</div>
        ${stepsHTML(s)}
        <div class="box note ${s.status === 'Blocked' ? 'blocked' : ''}"><h3>What's Happening</h3><p>${esc(s.note) || 'No update yet.'}</p></div>
        <div class="facts">
          <div class="fact"><div class="k">Findings <span class="faint">${findings(s)}</span></div><div class="pbars">${pb('P1', s.p1)}${pb('P2', s.p2)}${pb('P3', s.p3)}</div></div>
          <div class="fact"><div class="k">Review</div><div class="v">${esc(s.review) || '<span class="faint">Not reviewed yet</span>'}</div>${checks ? `<div class="k mt">Needs-check</div><div class="ids">${checks}</div>` : ''}</div>
          ${s.be || s.fe ? `<div class="fact wide"><div class="k">Branches</div>${s.be ? copyRow(s.be, 'BE') : ''}${s.fe ? copyRow(s.fe, 'FE') : ''}</div>` : ''}
          ${s.findings || s.report ? `<div class="fact wide"><div class="k">Files</div>${s.findings ? copyRow(s.findings) : ''}${s.report ? copyRow(s.report) : ''}</div>` : ''}
          ${(s.covers || []).length ? `<div class="fact wide"><div class="k">Also Covers</div><div class="ids">${s.covers.map((c) => `<span class="idc plain">${esc(c)}</span>`).join('')}</div></div>` : ''}
        </div>
        <div class="form">
          <div class="field"><label for="my-notes">Your Notes</label>
            <textarea id="my-notes" data-draft="${esc(key)}" data-id="${esc(s.id)}" placeholder="Anything Claude should know about this screen">${esc(draft(key, s.myNotes))}</textarea>
            <div class="field-row"><span class="hint" data-hint="${esc(key)}">${hasDraft ? 'Draft, not sent yet.' : 'Claude reads new notes from its inbox.'}</span><button class="btn primary sm" data-act="saveNote" data-id="${esc(s.id)}">Save Note</button></div></div>
          <div class="field"><label for="st-sel">Status</label>
            <div class="field-row"><button class="popup-btn st-pop ${SCLS[s.status]}" id="st-sel" data-act="stMenu" data-id="${esc(s.id)}" aria-haspopup="menu" aria-expanded="false" data-tip-text="Change the status  S">${stIcon(SCLS[s.status])}<span>${esc(s.status)}</span>${icon('chev', 'xs chev')}</button>${NEXT_QA[s.status] ? `<button class="btn sm next-qa" data-act="stNext" data-id="${esc(s.id)}" data-v="${esc(NEXT_QA[s.status])}">${stIcon(SCLS[NEXT_QA[s.status]])}${NEXT_QA[s.status] === 'Testing' ? 'Start Testing' : `Mark ${esc(NEXT_QA[s.status])}`}</button>` : ''}</div>
            <span class="hint">${QA.includes(s.status) || s.status === 'Done' ? 'Testing, Tested and Merged are yours and don’t go to Claude’s inbox. Found a bug? Set it back to Fixing (that tells Claude) and describe it in Your Notes.' : 'Claude normally sets this. A change here goes to Claude’s inbox.'}</span></div>
        </div>
        ${hist ? `<div class="box"><h3>History</h3><ul class="hist">${hist}</ul></div>` : ''}
      </div>`;
  }

  function inspectorEmptyHTML(list) {
    const st = stats(list);
    const rows = CLASSES.map((c) => `<li><i class="sw ${c.k}" aria-hidden="true"></i><span>${c.label}</span><b>${list.filter((s) => c.test(s.status)).length}</b></li>`).join('');
    return `<div class="insp-empty">
      <div class="glyph" aria-hidden="true">${icon('caps', 'lg')}</div>
      <h2>No Screen Selected</h2>
      <p>Select a screen to see what's happening, its findings, review, branches and history.</p>
      <ul class="mini">${rows}</ul>
      <p class="faint small">${plural(st.total, 'screen')} in this list${st.oos ? ` (+ ${st.oos} out of scope)` : ''} · use ↑ ↓ to move</p>
    </div>`;
  }

  // ------------------------------------------------------------------ decisions (split view)
  function decisionsHTML(selN) {
    const d = S.data;
    const open = d.decisions.filter(waitsOnUser).sort((a, b) => a.n - b.n);
    const sent = d.decisions.filter(answered).sort((a, b) => a.n - b.n);
    const settled = d.decisions.filter((x) => !D_OPEN.includes(x.status)).sort((a, b) => b.n - a.n);
    const sel = selN != null ? d.decisions.find((x) => String(x.n) === String(selN)) : null;
    const show = S.dFilter;
    const tabTarget = sel ? sel.n : (open[0] || sent[0] || settled[0] || {}).n;
    const row = (x) => `<button class="drow ${sel && sel.n === x.n ? 'sel' : ''}" data-act="selectDec" data-n="${x.n}" data-row="d${x.n}" tabindex="${x.n === tabTarget ? 0 : -1}" aria-pressed="${sel && sel.n === x.n ? 'true' : 'false'}">
        <span class="num">#${x.n}</span><span class="tx"><span class="t">${esc(x.topic)}</span>${x.decision && !D_OPEN.includes(x.status) ? `<span class="s">${esc(x.decision)}</span>` : answered(x) ? `<span class="s">You: ${esc(x.myNotes)}</span>` : ''}</span>${answered(x) ? dPill('Answered', true) : dPill(x.status, true)}</button>`;
    const sec = (title, items, cls) => (items.length ? `<div class="dsec ${cls}"><h2 class="dsec-h">${title}<span>${items.length}</span></h2>${items.map(row).join('')}</div>` : '');
    const body = (show === 'all' || show === 'open' ? sec('Waiting on You', open, 'open') + sec('Answered', sent, 'sent') : '') + (show === 'all' || show === 'settled' ? sec('Settled', settled, '') : '');
    const tabs = [['all', 'All', d.decisions.length], ['open', 'Waiting', open.length + sent.length], ['settled', 'Settled', settled.length]];
    return `<div class="split dsplit ${sel ? 'has-sel' : ''} ${sel && S.fresh ? 'fresh' : ''}">
      <section class="card list-card" aria-label="Decision list">
        <div class="fbar"><div class="seg" role="group" aria-label="Show">${SEG_THUMB}${tabs.map(([k, l, n]) => `<button data-act="dFilter" data-v="${k}" aria-pressed="${show === k}">${l}<span class="n">${n}</span></button>`).join('')}</div></div>
        <div class="dlist" data-scroll="dec-list">${body || '<div class="empty">Nothing here.</div>'}</div>
      </section>
      <div class="split-scrim" data-act="deselect" aria-hidden="true"></div>
      <aside class="card insp" aria-label="Decision details">${sel ? decisionDetailHTML(sel) : `<div class="insp-empty"><div class="glyph" aria-hidden="true">${icon('decide', 'lg')}</div><h2>No Decision Selected</h2><p>${open.length ? `${plural(open.length, 'decision')} ${open.length === 1 ? 'is' : 'are'} waiting on you. Select one to read it.` : sent.length ? `Claude has your ${plural(sent.length, 'answer')}. Select a decision to read it.` : 'Select a decision to read it.'}</p></div>`}</aside>
    </div>`;
  }

  function decisionDetailHTML(x) {
    const open = D_OPEN.includes(x.status);
    const pointer = /^see\s/i.test(x.decision || '');
    const names = {};
    S.data.screens.forEach((s) => (names[s.id] = s.name));
    const chips = (x.screens || []).map((id) => (names[id] ? idChip(id, names[id]) : `<span class="idc plain">${esc(shortId(id))}</span>`)).join('');
    const key = `dec:${x.n}`;
    const hasDraft = key in S.drafts && S.drafts[key] !== (x.myNotes || '');
    const ask = x.status === 'Please confirm';
    const refs = S.data.screens.filter((s) => (s.checks || []).includes(x.n) && !(x.screens || []).includes(s.id));
    return `<div class="insp-head"><span class="idc plain">#${x.n}</span>${dPill(x.status, true)}
        <button class="icon-btn" data-act="deselect" aria-label="Close details" data-tip-text="Close  Esc">${icon('close', 'sm')}</button></div>
      <div class="insp-body" data-scroll="dec-${x.n}">
        <h2 class="insp-title">${esc(x.topic)}</h2>
        ${x.decision ? `<div class="box ${open ? 'warn' : 'ok'}"><h3>${open ? (pointer ? 'Details' : 'Proposal') : 'Decision'}</h3><p>${esc(x.decision)}</p></div>` : ''}
        ${chips ? `<div class="box"><h3>Screens</h3><div class="ids">${chips}</div></div>` : ''}
        ${refs.length ? `<div class="box"><h3>Related Screens</h3><div class="ids">${refs.map((s) => idChip(s.id, s.name)).join('')}</div></div>` : ''}
        ${open ? `<div class="form"><div class="field"><label for="dn-${x.n}">Your Answer</label>
          <textarea id="dn-${x.n}" data-draft="${key}" data-dn="${x.n}" placeholder="${ask ? 'Optional: add a comment' : 'Tell Claude what to do'}">${esc(draft(key, x.myNotes))}</textarea>
          <div class="field-row"><span class="hint" data-hint="${key}">${hasDraft ? 'Draft, not sent yet.' : answered(x) ? 'Sent. Claude reads it at the start of its next task.' : ask ? 'Confirm tells Claude to go ahead, with your comment if you wrote one. Send Answer sends only your comment.' : 'Claude reads this from its inbox. You can also answer in your Claude chat.'}</span>
            ${ask ? `<button class="btn sm" data-act="dSend" data-n="${x.n}">Send Answer</button><button class="btn primary sm" data-act="dConfirm" data-n="${x.n}">${icon('check', 'sm')}Confirm</button>` : `<button class="btn primary sm" data-act="dSend" data-n="${x.n}">${icon('send', 'sm')}Send Answer</button>`}</div></div></div>` : ''}
        ${!open && x.myNotes ? `<div class="box"><h3>Your Note</h3><p>${esc(x.myNotes)}</p></div>` : ''}
      </div>`;
  }

  // ------------------------------------------------------------------ activity
  function activityHTML() {
    const d = S.data;
    const items = timeline().filter((x) => S.aFilter === 'all' || (S.aFilter === 'log' ? x.k === 'log' : x.k === 'ev'));
    let lastDay = null;
    let feed = '';
    items.forEach((x) => {
      const dd = parseT(x.t);
      const day = dd ? dayISO(dd) : '';
      if (day !== lastDay) {
        if (lastDay !== null) feed += '</ol>';
        feed += `<h3 class="dayh">${dd ? relDay(dd) + (relDay(dd) === fmtDay(dd) ? '' : ` · ${fmtDay(dd)}`) : 'Undated'}</h3><ol class="feed">`;
        lastDay = day;
      }
      const time = hasTime(x.t) ? fmtClock(dd) : (/\(([^)]*)\)/.exec(x.t || '') || [])[1] || '';
      feed += x.k === 'log'
        ? `<li class="fi"><span class="dotm" aria-hidden="true"></span><span class="when">${esc(time)}</span><p class="what">${esc(x.text)}</p></li>`
        : `<li class="fi ev"><span class="dotm" aria-hidden="true"></span><span class="when">${esc(time)}${x.g.by ? ` · ${esc(BY[x.g.by] || x.g.by)}` : ''}</span><p class="what">${x.g.ids.map((id) => idChip(id, (d.screens.find((s) => s.id === id) || {}).name)).join('')}${icon('arrow', 'xs to')}${statusPill(x.g.to, true)}</p></li>`;
    });
    if (lastDay !== null) feed += '</ol>';
    const atabs = [['all', 'All'], ['ev', 'Status'], ['log', 'Log']];
    return `<div class="act">
      <section class="card" aria-labelledby="tl-h">
        <div class="ch"><h2 id="tl-h">Timeline</h2><div class="end"><div class="seg" role="group" aria-label="Show">${SEG_THUMB}${atabs.map(([k, l]) => `<button data-act="aFilter" data-v="${k}" aria-pressed="${S.aFilter === k}">${l}</button>`).join('')}</div></div></div>
        <div class="cb" data-scroll="act-tl">${feed || '<div class="empty">Nothing logged yet.</div>'}</div>
      </section>
      ${codeCardHTML()}
    </div>`;
  }

  // ------------------------------------------------------------------ code: worktrees, branches, shared commits
  // The server reads the repositories with read-only git in the background (GET /api/code returns the last scan
  // at once and says when a new one is on the way; the event stream says when it lands).
  let codeBusy = false;
  async function loadCode(force) {
    if (codeBusy || !WSID && !S.data) return;
    codeBusy = true;
    const gen = wsGen;
    S.codeTry = Date.now();
    try {
      const r = await fetch(api('/api/code' + (force ? '?force=1' : '')), { cache: 'no-store' });
      const j = r.ok ? await r.json() : null;
      if (gen === wsGen && j) { S.code = j; S.codeAt = Date.now(); if (route().view === 'activity') render(); }
    } catch (e) { /* the offline banner says so */ } finally { codeBusy = false; }
  }
  function wantCode() {
    const stale = !S.code || S.code.ws !== (WSID || S.code.ws) || Date.now() - (S.codeAt || 0) > 20000;
    if (stale && Date.now() - (S.codeTry || 0) > 4000) setTimeout(() => loadCode(false), 0);
  }
  // "5m", "4h", "2d", like Linear's lists
  function agoShort(t) {
    const s = Math.max(0, Date.now() / 1000 - t);
    if (s < 60) return 'now';
    if (s < 3600) return Math.floor(s / 60) + 'm';
    if (s < 86400) return Math.floor(s / 3600) + 'h';
    if (s < 86400 * 60) return Math.floor(s / 86400) + 'd';
    return fmtDay(new Date(t * 1000));
  }
  const whenTitle = (t) => (t ? new Date(t * 1000).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '');
  // ahead / behind the common branch
  function abHTML(x, base) {
    if (x.ahead == null || x.behind == null) return '';
    if (!x.ahead && !x.behind) return `<span class="ab even" data-tip-text="Even with ${esc(base)}">${icon('check', 'xs')}</span>`;
    const tipText = [x.ahead ? `${plural(x.ahead, 'commit')} not on ${base} yet` : '', x.behind ? `${x.behind} on ${base} not here yet` : ''].filter(Boolean).join(' · ');
    return `<span class="ab" data-tip-text="${esc(tipText)}">${x.ahead ? `<span class="up">↑${x.ahead}</span>` : ''}${x.behind ? `<span class="dn">↓${x.behind}</span>` : ''}</span>`;
  }
  // one row per folder: a piece of work's folder holds its be/ and fe/ worktrees
  function wtGroups(list) {
    const m = new Map();
    list.forEach((w) => {
      if (!m.has(w.group)) m.set(w.group, { path: w.group, name: w.groupName, here: false, rel: false, t: 0, items: [] });
      const g = m.get(w.group);
      g.items.push(w); g.here = g.here || w.here; g.rel = g.rel || w.rel; g.t = Math.max(g.t, w.t || 0);
    });
    return [...m.values()].sort((a, b) => (b.here - a.here) || (b.t - a.t));
  }
  const repoTag = (r) => `<span class="repo ${esc(String(r).toLowerCase())}">${esc(r)}</span>`;
  function codeCardHTML() {
    const d = S.data;
    const c = S.code && (!WSID || S.code.ws === WSID) ? S.code : null;
    const base = (c && c.base) || d.branch || '';
    const names = [...new Set([...(c ? c.repos.map((r) => r.name) : []), ...(d.commits || []).map((x) => x.repo)])];
    const repo = names.includes(S.repo) ? S.repo : 'All';
    const inRepo = (r) => repo === 'All' || r === repo;
    const groups = c ? wtGroups(c.worktrees.filter((w) => inRepo(w.repo))) : [];
    const rel = groups.filter((g) => g.rel);
    const other = groups.filter((g) => !g.rel);
    const brs = c ? c.branches.filter((b) => Object.keys(b.repos).some(inRepo)) : [];
    const commits = (d.commits || []).slice().reverse().filter((x) => inRepo(x.repo));
    const tab = S.codeTab;
    if (tab !== 'commits') wantCode();
    const tabs = [['worktrees', 'Worktrees', c ? rel.length : null], ['branches', 'Branches', c ? brs.length : null], ['commits', 'Commits', commits.length]];
    const shortRepoName = (p) => String(p || '').split('/').pop();
    // what kept a repository from being read
    const errs = c ? c.repos.filter((r) => r.error && inRepo(r.name)) : [];
    const errHTML = errs.map((r) => {
      const where = r.protected ? `your ${r.protected} folder` : '';
      const msg = r.protected
        ? `Plots needs access to ${where} to read ${esc(r.name)}${r.error === 'timeout' ? ' (macOS may be asking right now)' : ''}.`
        : r.error === 'timeout' ? `Reading ${esc(r.name)} took too long.` : `Couldn't read ${esc(r.name)}: ${esc(r.error)}`;
      return `<div class="cnote">${icon('alert', 'sm')}<span>${msg}</span>${r.protected && NATIVE ? `<button class="linkbtn" data-act="askFolder" data-v="${esc(r.protected)}">Allow Access…</button>` : ''}<button class="linkbtn" data-act="codeRefresh">Try Again</button></div>`;
    }).join('');
    const loading = !c || (c.busy && !c.scanned);
    const wtLine = (w) => `<li>${repoTag(w.repo)}${w.branch ? `<code class="bn">${esc(w.branch)}</code>` : `<code class="bn faint">detached at ${esc(w.head)}</code>`}${abHTML(w, base)}${w.screen ? idChip(w.screen) : ''}${w.prunable ? '<span class="tag warn">Missing</span>' : ''}${w.locked ? '<span class="tag">Locked</span>' : ''}</li>`;
    const groupRow = (g) => `<div class="crow wt${g.rel ? '' : ' other'}" data-act="reveal" data-v="${esc(g.path)}" data-key="wt:${esc(g.path)}">
        <div class="cr-h">${icon('folder', 'sm cr-ic')}<button class="cr-t" data-act="reveal" data-v="${esc(g.path)}" data-tip-text="${esc(g.path.replace(/^\/Users\/[^/]+/, '~'))}${NATIVE ? ' · Show in Finder' : ' · Copy the path'}">${esc(g.name)}</button>${g.here ? '<span class="here">This workspace</span>' : ''}<span class="when" data-tip-text="${esc(whenTitle(g.t))}">${g.t ? agoShort(g.t) : ''}</span></div>
        <ul class="cr-ls">${g.items.slice().sort((a, b) => names.indexOf(a.repo) - names.indexOf(b.repo)).map(wtLine).join('')}</ul></div>`;
    const brRow = (b) => {
      const reps = Object.entries(b.repos).filter(([k]) => inRepo(k));
      const at = [...new Set(reps.map(([, v]) => v.wt).filter(Boolean).map((p) => {
        const w = c.worktrees.find((x) => x.path === p);
        return w ? w.groupName : shortRepoName(p);
      }))];
      const scr = b.screen && d.screens.find((s) => s.id === b.screen);
      return `<div class="crow br" data-act="${scr ? 'open' : 'copy'}" data-id="${esc(b.screen || '')}" data-v="${esc(b.name)}" data-key="br:${esc(b.name)}">
        <div class="cr-h">${icon('branch', 'sm cr-ic')}<code class="bn">${esc(b.name)}</code>${b.base ? '<span class="tag">Common</span>' : ''}${scr ? statusPill(scr.status, true) : ''}<span class="when" data-tip-text="${esc(whenTitle(b.t))}">${b.t ? agoShort(b.t) : ''}</span><button class="copy" data-act="copy" data-v="${esc(b.name)}" aria-label="Copy ${esc(b.name)}" data-tip-text="Copy branch name">${icon('copy', 'sm')}</button></div>
        <div class="cr-s">${reps.map(([k, v]) => `<span class="rp">${repoTag(k)}${b.base ? '' : abHTML(v, base)}</span>`).join('')}${scr ? `<span>${esc(scr.name)}</span>` : ''}${at.length ? `<span>in ${at.map(esc).join(', ')}</span>` : ''}${b.subject ? `<span class="subj">${esc(b.subject)}</span>` : ''}</div>
      </div>`;
    };
    const cmRow = (x) => `<div class="crow cm" data-act="copy" data-v="${esc(x.hash)}" data-key="cm:${esc(x.repo)}:${esc(x.hash)}" data-tip-text="Copy ${esc(x.hash)}">
        ${repoTag(x.repo)}<span class="m">${esc(x.msg)}</span><span class="meta"><code>${esc(x.hash)}</code><span>${fmtWhen(x.date)}</span></span></div>`;
    let body;
    if (tab === 'commits') {
      body = (base ? `<div class="cbase">${icon('branch', 'xs')}<span>On</span><code>${esc(base)}</code><button class="copy" data-act="copy" data-v="${esc(base)}" aria-label="Copy ${esc(base)}" data-tip-text="Copy branch name">${icon('copy', 'sm')}</button></div>` : '')
        + (commits.length ? commits.map(cmRow).join('') : '<div class="empty">No commits recorded.</div>');
    } else if (loading) {
      body = `<div class="empty"><span class="spin" aria-hidden="true"></span> Reading the repositories…</div>`;
    } else if (!c.repos.length) {
      body = `<div class="empty">No git repositories in this workspace’s folder.<br><span class="faint small">Name them with <code>${esc(CLI())} ws set ${esc(WSID || '')} repos=&lt;path&gt;,&lt;path&gt;</code></span></div>`;
    } else if (tab === 'branches') {
      body = errHTML + (brs.length ? brs.map(brRow).join('') : errs.length ? '' : '<div class="empty">No branches for this workspace.</div>');
    } else {
      body = errHTML + (rel.length ? rel.map(groupRow).join('') : errs.length ? '' : '<div class="empty">No worktrees for this workspace.</div>')
        + (other.length ? `<button class="more-row" data-act="codeOthers" aria-expanded="${S.codeOthers ? 'true' : 'false'}">${icon(S.codeOthers ? 'chev' : 'chevR', 'xs')}<span>${plural(other.length, 'other worktree')} in ${esc([...new Set(c.worktrees.filter((w) => !w.rel).map((w) => w.repo))].join(' and '))}</span></button>${S.codeOthers ? other.map(groupRow).join('') : ''}` : '');
    }
    return `<section class="card c-code" aria-labelledby="sc-h">
        <div class="ch"><h2 id="sc-h">Code</h2>
          <div class="seg" role="group" aria-label="Show">${SEG_THUMB}${tabs.map(([k, l, n]) => `<button data-act="codeTab" data-v="${k}" aria-pressed="${tab === k}">${l}${n != null ? `<span class="n">${n}</span>` : ''}</button>`).join('')}</div>
          <div class="end">${c && c.busy && c.scanned ? '<span class="spin sm" aria-label="Updating"></span>' : ''}${names.length > 1 ? popup('repo', 'Repository', repo, [['All', 'All repos']].concat(names.map((n) => [n, n]))) : ''}</div></div>
        <div class="cb crows" data-scroll="act-code-${tab}">${body}</div>
      </section>`;
  }

  // ------------------------------------------------------------------ render
  let lastView = null;
  let lastSel = null;

  function focusKey(el) {
    if (!el || el === document.body || !root.contains(el)) return null;
    if (el.id) return { id: el.id, s: el.selectionStart, e: el.selectionEnd };
    if (el.dataset.row) return { sel: `[data-row="${el.dataset.row}"]` };
    if (el.dataset.nav) return { sel: `[data-nav="${el.dataset.nav}"]` };
    if (el.dataset.act) {
      const parts = ['act', 'v', 'k', 'id', 'n'].filter((k) => el.dataset[k] != null).map((k) => `[data-${k}="${CSS.escape(el.dataset[k])}"]`);
      return { sel: parts.join('') };
    }
    return null;
  }
  function restoreFocus(k) {
    if (!k) return;
    const el = k.id ? document.getElementById(k.id) : $(k.sel);
    if (!el) return;
    el.focus({ preventScroll: true });
    if (k.id && k.s != null) { try { el.setSelectionRange(k.s, k.e); } catch (e) { /* not a text field */ } }
  }
  function saveScroll() {
    const m = {};
    $$('[data-scroll]').forEach((el) => (m[el.dataset.scroll] = [el.scrollTop, el.scrollLeft]));
    return m;
  }
  function restoreScroll(m) {
    $$('[data-scroll]').forEach((el) => {
      const v = m[el.dataset.scroll];
      if (v) { el.scrollTop = v[0]; el.scrollLeft = v[1]; }
    });
  }

  // Update a container in place: keep the elements that stay (their scroll, hover, focus and running
  // transitions), change only what differs. Keyed by id or data-key where lists reorder.
  const keyOf = (n) => (n.nodeType === 1 ? (n.getAttribute('data-key') || n.id || null) : null);
  function morphNode(a, b) {
    if (a.nodeType !== b.nodeType || a.nodeName !== b.nodeName) { a.replaceWith(b); return; }
    if (a.nodeType === 1 && a.classList.contains('seg-thumb')) return;
    if (a.nodeType !== 1) { if (a.nodeValue !== b.nodeValue) a.nodeValue = b.nodeValue; return; }
    // (a part's breakpoints stay while they stand still; otherwise watchCQ sets them again right after)
    for (let i = a.attributes.length - 1; i >= 0; i--) { const n = a.attributes[i].name; if (!b.hasAttribute(n) && !(cqHeld && n === 'data-cq')) a.removeAttribute(n); }
    for (let i = 0; i < b.attributes.length; i++) { const { name, value } = b.attributes[i]; if (a.getAttribute(name) !== value) a.setAttribute(name, value); }
    if (cqHeld && heldTables.has(a)) a.style.minWidth = heldTables.get(a);
    const busy = a === document.activeElement;
    if (a.nodeName === 'TEXTAREA') { if (!busy && a.value !== b.value) a.value = b.value; return; }
    if (a.nodeName === 'INPUT') { if (!busy && a.type !== 'checkbox' && a.type !== 'radio' && a.value !== b.value) a.value = b.value; return; }
    morphKids(a, b);
    if (a.nodeName === 'SELECT' && !busy) { const o = b.querySelector('option[selected]'); if (o && a.value !== o.value) a.value = o.value; }
  }
  function morphKids(a, b) {
    let x = a.firstChild; let y = b.firstChild;
    while (y) {
      const yn = y.nextSibling;
      if (!x) { a.appendChild(y); y = yn; continue; }
      const kx = keyOf(x); const ky = keyOf(y);
      if (kx !== ky) {
        let m = ky ? x.nextSibling : null;
        while (m && keyOf(m) !== ky) m = m.nextSibling;
        if (m) { a.insertBefore(m, x); morphNode(m, y); }
        else a.insertBefore(y, x);
        y = yn; continue;
      }
      const xn = x.nextSibling; morphNode(x, y); x = xn; y = yn;
    }
    while (x) { const xn = x.nextSibling; x.remove(); x = xn; }
  }
  const tpl = document.createElement('template');
  function patch(el, html) {
    if (!el.firstChild) { el.innerHTML = html; return; }
    tpl.innerHTML = html;
    morphKids(el, tpl.content);
  }

  // ------------------------------------------------------------------ breakpoints
  // The page's parts lay themselves out by their own widths: the Overview stacks its cards at 999px or less, a list
  // drops columns, the details cover a narrow list. The page sets these breakpoints on the parts (data-cq) as their
  // widths change, instead of CSS container queries, so that they can stand still while the Mac app's sidebar
  // slides: the page stretches or narrows to the space as it is, then rearranges once, gliding, when the sidebar
  // stops (rearranging at every step of the slide made the page shift about).
  const CQ = [
    ['main', '.main', [['le', 999], ['le', 899], ['le', 860], ['le', 819], ['le', 659]]],
    ['active', '.c-active', [['le', 600], ['le', 500], ['le', 400]]],
    ['status', '.c-status', [['le', 460]]],
    ['map', '.c-map', [['ge', 820]]],
    ['latest', '.c-latest', [['le', 300]]],
    ['list', '.list-card', [['le', 680], ['le', 580], ['le', 470], ['le', 360]]],
    ['code', '.c-code', [['le', 420]]],
  ];
  let cqHeld = false;
  let barW = 0; // while held: the screen list's filter bar width from before the slide (see .layout-held in app.css)
  const px = (v) => parseFloat(v) || 0;
  // the width a part lays out in (its content box, as a container query sees it)
  function contentWidth(el) {
    const cs = getComputedStyle(el);
    return el.getBoundingClientRect().width - px(cs.borderLeftWidth) - px(cs.borderRightWidth) - px(cs.paddingLeft) - px(cs.paddingRight);
  }
  function cqTokens(name, el, rules) {
    const w = contentWidth(el);
    return rules.filter(([op, n]) => (op === 'le' ? w <= n : w >= n)).map(([op, n]) => `${name}-${op}${n}`).join(' ');
  }
  // sets the breakpoints from the widths (until nothing changes, since one part's layout moves another's); while they
  // stand still, only parts that have none yet get theirs
  function applyCQ(force) {
    let changed = false;
    // an element that the page reuses for something else (see morphNode) drops breakpoints it no longer has
    $$('[data-cq]').forEach((el) => { if (!CQ.some(([, sel]) => el.matches(sel))) el.removeAttribute('data-cq'); });
    for (let pass = 0; pass < 4; pass++) {
      let again = false;
      CQ.forEach(([name, sel, rules]) => $$(sel).forEach((el) => {
        if (cqHeld && !force && el.dataset.cq != null) return;
        const t = cqTokens(name, el, rules);
        if (el.dataset.cq !== t) { el.dataset.cq = t; again = true; }
      }));
      changed = changed || again;
      if (!again) break;
    }
    return changed;
  }
  // What each breakpoint's rules style, from the style sheet ("main-le999" → [".ov", ".c-active", …]): a breakpoint
  // that comes or goes on a part with none of those inside it changes nothing that shows (the Overview's stacking on
  // the Activity view).
  let cqRules = null;
  function cqRuleMap() {
    if (cqRules) return cqRules;
    cqRules = {};
    // a selector list split at its top-level commas (not those inside :is(th, td))
    const parts = (s) => { const out = []; let d = 0; let cur = ''; for (const ch of s) { if (ch === '(') d++; if (ch === ')') d--; if (ch === ',' && !d) { out.push(cur); cur = ''; } else cur += ch; } out.push(cur); return out; };
    const walk = (rules) => {
      for (const r of rules) {
        if (!r.selectorText) { if (r.cssRules) walk(r.cssRules); continue; }
        if (!r.selectorText.includes('data-cq')) continue;
        parts(r.selectorText).forEach((p) => {
          const m = p.match(/data-cq~="([a-z0-9-]+)"\]\)?(.*)$/);
          if (m) (cqRules[m[1]] = cqRules[m[1]] || []).push(m[2].trim());
        });
      }
    };
    for (const sh of document.styleSheets) { try { walk(sh.cssRules); } catch (e) { /* another origin's sheet */ } }
    return cqRules;
  }
  const cqShows = (token, el) => (cqRuleMap()[token] || ['']).some((rest) => { try { return !rest || !!el.querySelector(rest); } catch (e) { return true; } });
  // whether letting the breakpoints go would change what shows
  const cqWouldChange = () => CQ.some(([name, sel, rules]) => $$(sel).some((el) => {
    const now = (el.dataset.cq || '').split(' ').filter(Boolean);
    const next = cqTokens(name, el, rules).split(' ').filter(Boolean);
    return now.filter((t) => !next.includes(t)).concat(next.filter((t) => !now.includes(t))).some((t) => cqShows(t, el));
  }));
  const cqWatched = new Set();
  const cqRO = window.ResizeObserver ? new ResizeObserver(() => { if (!cqHeld) applyCQ(); }) : null;
  if (!cqRO) window.addEventListener('resize', () => { if (!cqHeld) applyCQ(); });
  // after a render: new parts get their breakpoints before they show, and are watched from then on
  function watchCQ() {
    applyCQ();
    if (!cqRO) return;
    cqWatched.forEach((el) => { if (!el.isConnected) { cqRO.unobserve(el); cqWatched.delete(el); } });
    CQ.forEach(([, sel]) => $$(sel).forEach((el) => { if (!cqWatched.has(el)) { cqWatched.add(el); cqRO.observe(el); } }));
  }
  // While the sidebar slides the breakpoints stand still, the screen list's filter bar keeps its rows, and a table
  // that gets narrower is cut off at the edge of its card rather than squeezing its names (the columns it would
  // drop go first); when the sidebar stops the page rearranges once, gliding.
  let heldTimer = 0;
  let heldTables = new Map(); // a table → its width before the slide, kept as its least width while held
  const clientInner = (el) => { const cs = getComputedStyle(el); return el.clientWidth - px(cs.paddingLeft) - px(cs.paddingRight); };
  function holdLayout(on) {
    if (on) {
      if (cqHeld) return;
      cqHeld = true;
      hideTip();
      const bar = $('.list-card .fbar');
      barW = bar ? bar.getBoundingClientRect().width : 0;
      if (barW) shell.win.style.setProperty('--fbar-w', barW + 'px');
      heldTables = new Map($$('.content .tbl').filter((t) => t.offsetParent !== null).map((t) => [t, t.getBoundingClientRect().width + 'px']));
      heldTables.forEach((w, t) => { t.style.minWidth = w; });
      shell.win.classList.add('layout-held');
      // a slide takes a fraction of a second: if its end never comes, the page doesn't stay held
      heldTimer = setTimeout(() => holdLayout(false), 2500);
      return;
    }
    if (!cqHeld) return;
    clearTimeout(heldTimer);
    cqHeld = false;
    // whether the filter bar's items move once it has its width again (measured both ways before anything shows)
    const bar = barW && $('.list-card .fbar');
    let barMoves = false;
    if (bar) {
      const at = () => Array.from(bar.children, (k) => { const r = k.getBoundingClientRect(); return [r.left, r.top, r.width].map(Math.round).join(','); }).join(' ');
      const held = at();
      shell.win.classList.remove('layout-held');
      barMoves = at() !== held;
      shell.win.classList.add('layout-held');
    }
    const cut = [...heldTables.keys()].some((t) => t.isConnected && t.offsetParent !== null && t.getBoundingClientRect().width > clientInner(t.parentElement) + 0.5);
    const free = () => {
      shell.win.classList.remove('layout-held');
      shell.win.style.removeProperty('--fbar-w');
      barW = 0;
      heldTables.forEach((w, t) => { t.style.minWidth = ''; });
      heldTables = new Map();
    };
    if (barMoves || cut || cqWouldChange()) glide(() => { free(); applyCQ(true); });
    else { free(); applyCQ(true); placeThumbs(); edgeFades(); }
  }
  // A change of layout glides: the cards move and resize to their new places and the rest crossfades (with the
  // engine's view transitions; at once with Reduce Motion or without them). A glide that can't keep up (frames
  // over 60ms apart: a view with much to draw, a busy Mac) ends at once; a view where that happens twice rearranges
  // at once from then on.
  let glideGen = 0;
  let glided = [];
  const slowGlide = new Map(); // view → glides cut short
  function glide(change) {
    const view = shell.win.dataset.view || '';
    const done = () => { placeThumbs(); edgeFades(); };
    const still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    glided.forEach((el) => { el.style.viewTransitionName = ''; });
    glided = [];
    shell.win.classList.remove('gliding');
    // (at once, too, while a menu, popover or the search palette is open over the page)
    if (!document.startViewTransition || still || document.hidden || (slowGlide.get(view) || 0) >= 2 || $('.pop, .pal, .menu')) { change(); done(); return; }
    // the cards in view glide (one partly scrolled out at the top crossfades instead: a gliding card isn't cut off
    // by the scrolling area, so it would show over what is above it)
    const top = shell.content.getBoundingClientRect().top - 1;
    const cards = $$('.content .card').filter((el) => {
      if (el.offsetParent === null) return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.top >= top && r.top < window.innerHeight;
    });
    cards.forEach((el, i) => { el.style.viewTransitionName = 'card-' + i; });
    // The scrim that dims a list under its details moves with them; one that only appears now waits until the cards
    // have glided, then fades in (gliding, it would show over the details). Notices stay on top.
    const shown = (el) => { const cs = getComputedStyle(el); return cs.display !== 'none' && parseFloat(cs.opacity) > 0; };
    const scrims = $$('.content .split-scrim').filter(shown).slice(0, 1);
    scrims.forEach((el) => { el.style.viewTransitionName = 'scrim'; });
    const toasts = $('#toasts');
    const notes = toasts && toasts.children.length ? [toasts] : [];
    notes.forEach((el) => { el.style.viewTransitionName = 'toasts'; });
    glided = cards.concat(scrims, notes);
    const gen = ++glideGen;
    const clear = () => {
      if (gen !== glideGen) return;
      glided.forEach((el) => { el.style.viewTransitionName = ''; });
      glided = [];
      shell.win.classList.remove('gliding');
      done();
    };
    try {
      const tr = document.startViewTransition(() => { change(); if (!scrims.length) shell.win.classList.add('gliding'); });
      tr.finished.then(clear, clear);
      tr.ready.then(() => {
        let last = performance.now();
        let n = 0;
        const watch = (t) => {
          if (gen !== glideGen || !glided.length) return;
          if (t - last > 60) { slowGlide.set(view, (slowGlide.get(view) || 0) + 1); tr.skipTransition(); return; }
          last = t;
          if (++n < 30) requestAnimationFrame(watch);
        };
        requestAnimationFrame(watch);
      }, () => {});
    } catch (e) { change(); clear(); }
  }

  function render() {
    if (PANEL) { renderPanel(); return; }
    ensureShell();
    if (!S.data) { if (S.noWorkspace) renderWelcome(); else renderOffline(); reportChrome(); return; }
    // links from before Chat moved into the sidebar (#/chat/<id>): open that conversation there
    if (/^#\/chat\b/.test(location.hash)) {
      const cid = location.hash.split('/')[2];
      history.replaceState(null, '', '#/' + (VIEWS.includes(lastView) ? lastView : 'overview'));
      setTimeout(() => (cid === 'new' ? newChat() : openChat(cid ? decodeURIComponent(cid) : null)), 0);
    }
    const { view, id } = route();
    const fk = focusKey(document.activeElement);
    const scroll = saveScroll();
    const contentTop = shell.content.scrollTop;
    const winY = window.scrollY;
    const same = view === lastView;
    // details slide in only when a selection first appears, not on every re-render
    S.fresh = !!id && (!lastSel || !lastSel.startsWith(view + ':') || lastSel === view + ':');
    hideTip();
    const wsName = curWS().name;
    document.title = view === 'overview' ? `${wsName} · Plots` : `${view[0].toUpperCase() + view.slice(1)} · ${wsName}`;
    shell.win.dataset.view = view;
    const chatPrev = chatScroll();
    // a context left out (× on its chip) comes back once something else is open
    if (S.ctxDropped) { const cx = chatContext(); if (!cx || cx.key !== S.ctxDropped) S.ctxDropped = null; }
    if (!NATIVE) { patch(shell.sb, sidebarHTML(view)); patch(shell.tb, toolbarHTML(view)); }
    shell.banner.innerHTML = S.offline ? `<div class="banner" role="status">${icon('alert', 'sm')}<span>Lost the connection to Plots, so this shows the last data. It reconnects on its own, or run <code>${esc(CLI())} open</code>.</span></div>` : '';
    patch(shell.content, view === 'screens' ? screensHTML(id) : view === 'decisions' ? decisionsHTML(id) : view === 'activity' ? activityHTML() : overviewHTML());
    applySidebar();
    watchCQ();
    if (same) {
      restoreScroll(scroll);
      shell.content.scrollTop = contentTop;
      if (mqPhone.matches) window.scrollTo(0, winY);
    } else {
      shell.content.scrollTop = 0;
      if (mqPhone.matches) window.scrollTo(0, 0);
    }
    restoreFocus(fk);
    if (!NATIVE && S.side === 'chat') afterChatRender(chatPrev);
    // keep the selected row in sight when the selection changes; on narrow windows the
    // details cover the list, so move focus into them
    const selKey = view + ':' + (id || '');
    if (id && selKey !== lastSel) {
      const r = $('.row.sel, .drow.sel');
      if (r) reveal(r, !same);
      if (detailsCover()) { const c = $('.insp [data-act="deselect"]'); if (c) c.focus({ preventScroll: true }); }
      // arriving from another view: the list takes the keyboard, so its selection shows as active
      else if (!same && r) { const f = r.matches('.drow') ? r : $('.rb', r); if (f) f.focus({ preventScroll: true }); }
    }
    initMap();
    lastView = view;
    lastSel = selKey;
    if (S.pal) renderPalette();
    edgeFades();
    placeThumbs();
    reportChrome();
  }

  // Each segmented control's thumb sits under its chosen segment and slides when the choice changes. A control
  // that just appeared places its thumb without sliding.
  function placeThumbs() {
    $$('.seg > .seg-thumb').forEach((th) => {
      const on = th.parentNode.querySelector(':scope > button[aria-pressed="true"]');
      if (!on) { th.style.opacity = '0'; th._pos = null; return; }
      const x = on.offsetLeft; const w = on.offsetWidth;
      const p = th._pos;
      if (p && p.x === x && p.w === w) return;
      if (!p) th.classList.add('still');
      th.style.width = w + 'px';
      th.style.transform = `translateX(${x}px)`;
      th.style.opacity = '1';
      th._pos = { x, w };
      if (!p) { void th.offsetWidth; requestAnimationFrame(() => th.classList.remove('still')); }
    });
  }
  let thumbTimer = null;
  window.addEventListener('resize', () => { clearTimeout(thumbTimer); thumbTimer = setTimeout(placeThumbs, 60); });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => placeThumbs());
  let lastChrome = '';
  function reportChrome() {
    if (PANEL) return;
    if (NATIVE && !S.data && S.noWorkspace) { native({ type: 'chrome', view: 'overview', batch: 'All', screens: 0, waiting: 0, batches: [], unread: 0, busy: 0, theme, ws: null, workspaces: [] }); return; }
    if (!NATIVE || !S.data) return;
    const d = S.data;
    const { view } = route();
    const batches = d.batches.length ? ['All'].concat(d.batches).map((b) => {
      const st = stats(b === 'All' ? d.screens : d.screens.filter((s) => s.batch === b));
      return { id: b, done: st.done, total: st.total, flight: st.working };
    }) : [];
    const st = stats(d.screens);
    const w = curWS();
    const cs = convos().filter((c) => !c.archived);
    const cc = chatCounts();
    const rid = route().id;
    const chat = { total: cs.length, working: cc.working, waiting: cc.waiting, unread: cc.unread,
      attention: cs.filter((c) => c.kind === 'wait' || c.unread).length, mode: S.noteMode };
    // what's open in the page goes with a chat message (the chat panel shows it as a chip)
    const sel = rid && view === 'screens' ? 'screen:' + rid : rid && view === 'decisions' ? 'decision:' + rid : null;
    const msg = { type: 'chrome', view, batch: S.batch, screens: d.screens.length,
      waiting: d.decisions.filter(waitsOnUser).length, batches, live: !!(S.live && !S.offline), offline: !!S.offline,
      unread: unseenNotes(), busy: activeNotes(), theme, chat, sel,
      ws: { id: w.id, name: w.name, color: w.color, initials: w.initials, done: st.done, total: st.total, cli: w.cli || 'plots' },
      workspaces: S.workspaces.map((x) => ({ id: x.id, name: x.name, color: x.color, initials: x.initials, done: x.done || 0, total: x.total || 0 })) };
    const j = JSON.stringify(msg);
    if (j !== lastChrome) { lastChrome = j; native(msg); }
  }
  // a soft fade where a card's list continues below (the macOS scroll edge effect)
  function edgeFades() {
    $$('[data-scroll]').forEach((el) => el.classList.toggle('fade-b', el.scrollTop + el.clientHeight < el.scrollHeight - 2));
  }
  document.addEventListener('scroll', (e) => { const el = e.target; if (el && el.dataset && 'scroll' in el.dataset) el.classList.toggle('fade-b', el.scrollTop + el.clientHeight < el.scrollHeight - 2); }, true);
  let fadeRAF = 0;
  window.addEventListener('resize', () => { if (!fadeRAF) fadeRAF = requestAnimationFrame(() => { fadeRAF = 0; edgeFades(); }); });
  // scroll a row into view inside its own scroll area only (scrollIntoView would also nudge the window)
  function reveal(el, center) {
    const box = el.closest('.tbl-scroll, .dlist, .cb');
    if (!box || box.scrollHeight <= box.clientHeight) { if (mqPhone.matches) el.scrollIntoView({ block: 'center' }); return; }
    const head = box.querySelector('thead');
    const top = (head ? head.offsetHeight : 0) + (el.closest('tbody') && el.closest('tbody').querySelector('.grp') ? 36 : 0);
    const er = el.getBoundingClientRect(); const br = box.getBoundingClientRect();
    const y = er.top - br.top + box.scrollTop;
    if (center) box.scrollTop = y - (box.clientHeight - er.height) / 2;
    else if (er.top < br.top + top) box.scrollTop = y - top - 4;
    else if (er.bottom > br.bottom) box.scrollTop = y + er.height - box.clientHeight + 4;
  }
  const detailsCover = () => {
    const i = $('.split.has-sel .insp');
    if (!i) return false;
    const p = getComputedStyle(i).position;
    return p === 'absolute' || p === 'fixed';
  };

  function renderWelcome() {
    root.innerHTML = '';
    shell = null;
    root.innerHTML = `<div class="offline">
      <div class="card off-card">
        <div class="logo big" aria-hidden="true">${LOGO}</div>
        <h1>Track your first project</h1>
        <p>Plots keeps one workspace per project. Claude Code updates it as it works, and you can send it notes from here.</p>
        <button class="btn primary" data-act="wsAdd">New Workspace…</button>
        <p>Or in your project folder, in Terminal or Claude Code:</p>
        ${copyRow('plots init "My Project"')}
      </div></div>`;
  }
  function renderOffline() {
    root.innerHTML = '';
    shell = null;
    root.innerHTML = `<div class="offline">
      <div class="card off-card">
        <div class="logo big" aria-hidden="true">${LOGO}</div>
        <h1>Plots isn’t running</h1>
        <p>Open the <b>Plots</b> app, or run this in Terminal:</p>
        ${copyRow('plots open')}
        <button class="btn primary" data-act="retry">Try Again</button>
      </div></div>`;
  }

  // ------------------------------------------------------------------ screen map: roving focus
  function initMap() {
    const caps = $$('.cap');
    if (!caps.length) return;
    const t = (S.focusCap && caps.find((c) => c.dataset.id === S.focusCap)) || caps[0];
    t.tabIndex = 0;
  }

  // ------------------------------------------------------------------ tooltip
  const tip = $('#tip');
  let tipFor = null;
  const railMode = () => shell && shell.win.classList.contains('compact') && !shell.win.classList.contains('peek');
  function tipContent(el) {
    if (el.dataset.tipText) {
      // sidebar labels are visible unless the sidebar is compact
      if (el.closest('.sb') && !railMode()) return null;
      return `<span class="tt">${esc(el.dataset.tipText)}</span>`;
    }
    const kind = el.dataset.tip;
    if (kind === 'screen') {
      const s = S.data && S.data.screens.find((x) => x.id === el.dataset.id);
      if (!s) return null;
      const note = s.note ? `<span class="tn">${esc(s.note.length > 150 ? s.note.slice(0, 147) + '…' : s.note)}</span>` : '';
      return `<span class="th">${esc(s.name)}</span><span class="tm"><span class="mono">${esc(s.id)}</span> · ${esc(s.status)} · fix #${esc(s.order)} · ${esc(s.batch)}</span>${note}`;
    }
    if (kind === 'day') {
      const x = progressData[+el.dataset.i];
      if (!x) return null;
      const dd = parseT(x.d);
      return `<span class="tm">${esc(relDay(dd) === fmtDay(dd) ? fmtDay(dd) : relDay(dd) + ', ' + fmtDay(dd))}${x.pre ? ' · before tracking' : ''}</span>
        <span class="tv"><i class="k flight"></i><b>${x.fl}</b> fixing <span class="faint">${round(pct(x.fl, x.total))}%</span></span>
        <span class="tv"><i class="k done"></i><b>${x.done}</b> done <span class="faint">${round(pct(x.done, x.total))}%</span></span>`;
    }
    return null;
  }
  function showTip(el) {
    const html = tipContent(el);
    if (!html) { hideTip(); return; }
    tipFor = el;
    tip.innerHTML = html;
    tip.classList.toggle('wide', !!el.dataset.tip);
    tip.classList.add('on');
    const r = el.getBoundingClientRect();
    const tw = tip.offsetWidth; const th = tip.offsetHeight;
    let x; let y;
    if (el.dataset.tipPos === 'right') {
      x = r.right + 10; y = r.top + r.height / 2 - th / 2;
    } else {
      x = r.left + r.width / 2 - tw / 2;
      y = r.top - th - 8;
      if (el.dataset.tip === 'day') y = Math.min(y, r.top + 4);
      if (y < 8) y = r.bottom + 8;
    }
    x = Math.max(8, Math.min(window.innerWidth - tw - 8, x));
    y = Math.max(8, Math.min(window.innerHeight - th - 8, y));
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  }
  let tipTimer = null;
  let tipWait = null;
  function hideTip() { clearTimeout(tipTimer); tipWait = null; tipFor = null; tip.classList.remove('on'); }
  const tipTarget = (t) => t && t.closest && t.closest('[data-tip], [data-tip-text]');
  // chart marks answer at once; buttons and rows wait a moment, like native help tags
  const instant = (el) => el.classList.contains('cap') || el.classList.contains('pc') || tip.classList.contains('on');
  document.addEventListener('pointerover', (e) => {
    const el = tipTarget(e.target);
    if (!el) { if (tipFor || tipWait) hideTip(); return; }
    if (el === tipFor || el === tipWait) return;
    clearTimeout(tipTimer);
    if (instant(el)) { tipWait = null; showTip(el); return; }
    tip.classList.remove('on'); tipFor = null; tipWait = el;
    tipTimer = setTimeout(() => { if (tipWait === el && document.contains(el)) showTip(el); tipWait = null; }, 450);
  });
  document.addEventListener('pointerdown', hideTip);
  document.documentElement.addEventListener('pointerleave', hideTip);
  document.addEventListener('focusin', (e) => {
    const el = tipTarget(e.target);
    if (el && e.target.matches(':focus-visible')) showTip(el); else hideTip();
  });
  document.addEventListener('scroll', hideTip, true);
  window.addEventListener('blur', hideTip);

  // donut ⇄ legend highlight
  function setHot(k) {
    const card = $('.c-status');
    if (!card) return;
    const center = $('.dn-center', card);
    if (!k) { delete card.dataset.hot; if (center) center.innerHTML = center.dataset.center; return; }
    card.dataset.hot = k;
    const row = $(`.lg-row[data-cls="${k}"]`, card);
    if (row && center) center.innerHTML = `<b>${row.dataset.n}</b><span>${esc(row.dataset.label.toLowerCase())}</span>`;
  }
  document.addEventListener('pointerover', (e) => {
    const h = e.target.closest && e.target.closest('.lg-row, .donut .seg');
    if (h) setHot(h.dataset.cls);
    else if ($('.c-status[data-hot]') && !(e.target.closest && e.target.closest('.st-body'))) setHot(null);
  });
  document.addEventListener('focusin', (e) => {
    const h = e.target.closest && e.target.closest('.lg-row');
    if (h) setHot(h.dataset.cls); else if ($('.c-status[data-hot]')) setHot(null);
  });

  // ------------------------------------------------------------------ command palette
  function paletteItems(q) {
    const d = S.data;
    const ql = q.trim().toLowerCase();
    const has = (...xs) => !ql || xs.join(' ').toLowerCase().includes(ql);
    const out = [];
    const num = /^#?(\d+)$/.exec(ql);
    const hit = num ? d.decisions.find((x) => String(x.n) === num[1]) : null;
    if (hit) out.push({ sec: 'Decision', icon: 'decide', label: `#${hit.n} ${hit.topic}`, meta: answered(hit) ? 'Answered' : hit.status, run: () => go('#/decisions/' + hit.n) });
    [['overview', 'Overview', 'home'], ['screens', 'Screens', 'caps'], ['decisions', 'Decisions', 'decide'], ['activity', 'Activity', 'clock'], ['chat', 'Chat', 'assist']]
      .filter((n) => has(n[1], 'go to', 'open'))
      .forEach((n) => out.push({ sec: 'Go To', icon: n[2], label: n[1], run: () => (n[0] === 'chat' ? openChat() : go('#/' + n[0])) }));
    const sc = ql
      ? d.screens.filter((s) => has(s.id, s.name, menuLabel(s.menu), s.batch, s.status)).slice(0, 14)
      : d.screens.filter((s) => WORKING.includes(s.status)).sort(byRecent).slice(0, 8);
    sc.forEach((s) => out.push({ sec: ql ? 'Screens' : 'Fixing', cap: SCLS[s.status], label: s.name, meta: `${s.id} · ${s.status}`, run: () => go('#/screens/' + s.id) }));
    const dl = (ql ? d.decisions.filter((x) => has('#' + x.n, x.topic, x.status, x.decision)).slice(0, 8) : d.decisions.filter(waitsOnUser)).filter((x) => x !== hit);
    dl.forEach((x) => out.push({ sec: ql ? 'Decisions' : 'Waiting on You', icon: 'decide', label: `#${x.n} ${x.topic}`, meta: answered(x) ? 'Answered' : x.status, run: () => go('#/decisions/' + x.n) }));
    if (ql) {
      convos().filter((c) => has(c.title, 'chat', 'conversation') || c.items.some((n) => has(n.text))).slice(0, 6)
        .forEach((c) => out.push({ sec: 'Conversations', icon: 'bubble', label: c.title, meta: KIND_LABEL[c.kind] || whenShort(c.at), run: () => openChat(c.id) }));
      ['All'].concat(d.batches).filter((b) => has(b, 'batch', 'scope', 'fix')).forEach((b) => out.push({ sec: 'Fix Batch', icon: 'layers', label: b === 'All' ? 'All batches' : b, meta: 'Show only this batch', run: () => setBatch(b) }));
    }
    const chatSide = !NATIVE && S.side === 'chat';
    [{ label: chatSide ? 'Close Chat' : shell && shell.win.classList.contains('compact') && !S.peek ? 'Expand Sidebar' : 'Collapse Sidebar', icon: chatSide ? 'list' : 'sidebar', kbd: chatSide ? KEY + '0' : MAC ? '⌃⌘S' : 'Ctrl+\\', run: toggleSidebar },
      { label: 'New Conversation', icon: 'compose', run: () => newChat() },
      { label: 'Export to Excel', icon: 'download', run: () => { location.href = api('/api/export'); } }]
      .filter((a) => has(a.label, 'action')).forEach((a) => out.push(Object.assign({ sec: 'Actions' }, a)));
    return out;
  }
  const overlay = $('#overlay');
  let palReturn = null;
  function openPalette(external) {
    if (!S.data) return;
    S.palExternal = !!external;
    closeChatMenu(); closeMention();
    palReturn = document.activeElement;
    S.pal = true; S.palQ = ''; S.palI = 0;
    overlay.innerHTML = `<div class="pal-scrim" data-act="palClose"></div>
      <div class="pal" role="dialog" aria-modal="true" aria-label="Search">
        <label class="pal-in">${icon('search')}<span class="sr">Search screens, decisions and commands</span>
          <input id="palq" type="text" role="combobox" aria-expanded="true" aria-controls="pal-list" aria-autocomplete="list" placeholder="Search screens, decisions and commands" autocomplete="off" spellcheck="false"><kbd>esc</kbd></label>
        <div class="pal-list" id="pal-list" role="listbox" aria-label="Results"></div>
        <div class="pal-foot"><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>↵</kbd> open</span><span><kbd>esc</kbd> close</span></div>
      </div>`;
    renderPalette();
    if (!external) requestAnimationFrame(() => { const i = $('#palq'); i && i.focus(); });
  }
  function closePalette(restore = true) {
    const wasExternal = S.palExternal;
    S.pal = false; S.palExternal = false;
    overlay.innerHTML = '';
    if (wasExternal) native({ type: 'palette', open: false });
    if (restore && palReturn && document.contains(palReturn)) palReturn.focus({ preventScroll: true });
  }
  function renderPalette() {
    const list = $('#pal-list');
    if (!list) return;
    S.palItems = paletteItems(S.palQ);
    if (S.palI >= S.palItems.length) S.palI = Math.max(0, S.palItems.length - 1);
    let sec = null;
    let html = '';
    S.palItems.forEach((it, i) => {
      if (it.sec !== sec) { html += `<div class="pal-sec" role="presentation">${esc(it.sec)}</div>`; sec = it.sec; }
      const lead = it.cap ? `<span class="pal-cap">${stIcon(it.cap)}</span>` : `<span class="pal-ic">${icon(it.icon || 'chevR', 'sm')}</span>`;
      html += `<div class="pal-it ${i === S.palI ? 'on' : ''}" role="option" id="pal-${i}" aria-selected="${i === S.palI}" data-act="palRun" data-i="${i}">${lead}<span class="pl">${esc(it.label)}</span>${it.meta ? `<span class="pm">${esc(it.meta)}</span>` : ''}${it.kbd ? `<kbd>${esc(it.kbd)}</kbd>` : ''}</div>`;
    });
    list.innerHTML = html || `<div class="pal-empty">No results for “${esc(S.palQ)}”</div>`;
    const inp = $('#palq');
    if (inp) inp.setAttribute('aria-activedescendant', S.palItems.length ? 'pal-' + S.palI : '');
    const on = $('.pal-it.on', list);
    if (on) {
      if (on.offsetTop < list.scrollTop) list.scrollTop = on.offsetTop - 6;
      else if (on.offsetTop + on.offsetHeight > list.scrollTop + list.clientHeight) list.scrollTop = on.offsetTop + on.offsetHeight - list.clientHeight + 6;
    }
  }
  // the pointer moves the highlight too, without re-rendering the list
  document.addEventListener('pointermove', (e) => {
    if (!S.pal) return;
    const it = e.target.closest && e.target.closest('.pal-it');
    if (!it || +it.dataset.i === S.palI) return;
    const prev = $('.pal-it.on');
    if (prev) { prev.classList.remove('on'); prev.setAttribute('aria-selected', 'false'); }
    it.classList.add('on'); it.setAttribute('aria-selected', 'true');
    S.palI = +it.dataset.i;
    const inp = $('#palq'); if (inp) inp.setAttribute('aria-activedescendant', it.id);
  });
  function runPalette(i) {
    const it = S.palItems[i];
    if (!it) return;
    closePalette(false);
    it.run();
  }

  // ------------------------------------------------------------------ chat with your Claude project
  // A conversation is a message and its follow-ups. With notes=project the project's coordinator (Claude)
  // answers in place or hands the message to a thread and says which; follow-ups go to the same thread.
  // With notes=fork a fork of the working session answers. Chat is a panel where the sidebar is (✦), one
  // conversation at a time; what's open in the page (a screen or a decision) goes with a message.
  // The Mac app shows the panel in its own sidebar.
  const Notes = {
    async send(text, opts = {}) {
      const r = await post('/api/notes', { text, parent: opts.parent || null, target: opts.target || null, delay: opts.delay,
        to: opts.to || null, local: !!opts.local, context: opts.context || null });
      await refresh(false);
      return r.result;
    },
    async act(id, op, text) {
      const r = await post(`/api/notes/${id}/${op}`, text != null ? { text } : {});
      await refresh(false);
      return r.result;
    },
    async open(id, where) { await post(`/api/notes/${id}/open`, { where: where || 'desktop' }); },
    async seen(ids) {
      const want = ids ? S.notes.filter((n) => ids.includes(n.id) && !n.seen) : S.notes.filter((n) => !n.seen);
      if (!want.length) return;
      await post('/api/notes/seen', ids ? { ids: want.map((n) => n.id) } : {});
      await refresh(false);
    },
    async sessions() {
      try {
        const r = await fetch(api('/api/sessions'), { cache: 'no-store' });
        const j = await r.json();
        S.sessions = j.sessions || []; S.claude = j.claude !== false; S.protectedFolders = j.protected || [];
      } catch (e) { S.sessions = S.sessions || []; }
      if (PANEL || (!NATIVE && S.side === 'chat')) render();
      return S.sessions;
    },
  };
  const projectMode = () => S.noteMode === 'project';
  const SPIN = '<svg class="wspin" viewBox="0 0 16 16" aria-hidden="true"><circle class="t" cx="8" cy="8" r="6"/><circle class="h" cx="8" cy="8" r="6"/></svg>';
  const clock = (t) => { const d = parseT(t); return d && hasTime(t) ? fmtClock(d) : ''; };
  // when: "15:44" today, "Yesterday", "Oct 20"
  const whenShort = (t) => (t ? fmtShort(t) : '');
  function autoTitle(t) {
    const line = (String(t || '').split('\n').find((l) => l.trim()) || '').trim().replace(/\s+/g, ' ');
    return line.length > 64 ? line.slice(0, 63).trimEnd() + '…' : line;
  }
  const threadOf = (n) => (n && n.fork && n.fork.thread) || null;

  // the conversations, newest activity first
  let convCache = null;
  function convos() {
    if (convCache && convCache.src === S.notes) return convCache.list;
    const by = {};
    S.notes.forEach((n) => { by[n.id] = n; });
    const map = {}; const list = [];
    S.notes.forEach((n) => {
      let r = n; let g = 0;
      while (r.parent && by[r.parent] && g++ < 200) r = by[r.parent];
      let c = map[r.id];
      if (!c) { c = map[r.id] = { id: r.id, root: r, items: [] }; list.push(c); }
      c.items.push(n);
    });
    list.forEach((c) => {
      c.items.sort((a, b) => a.id - b.id);
      c.last = c.items[c.items.length - 1];
      c.title = c.root.title || autoTitle(c.root.text);
      c.archived = !!c.root.archived;
      c.unread = c.items.some((n) => !n.seen && (n.state === 'answered' || n.state === 'failed'));
      c.at = (c.last.reply && c.last.reply.t) || c.last.t || '';
      c.kind = convKind(c);
    });
    list.sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : b.id - a.id));
    convCache = { src: S.notes, list };
    return list;
  }
  // work: a thread or fork is on it · wait: a thread waits on you · send: on its way · held: paused
  // fail: couldn't be answered · review: a pull request is ready · idle: answered
  function convKind(c) {
    const live = c.items.filter((n) => n.state === 'sending');
    if (live.some((n) => (threadOf(n) || {}).state === 'waiting')) return 'wait';
    if (live.length) return 'work';
    if (c.items.some((n) => n.state === 'scheduled' || n.state === 'queued')) return 'send';
    if (c.items.some((n) => n.state === 'held')) return 'held';
    if (c.last.state === 'failed') return 'fail';
    const th = threadOf(c.last) || {};
    if (th.state === 'waiting') return 'wait';
    if (th.state === 'review') return 'review';
    return 'idle';
  }
  function chatCounts() {
    const cs = convos().filter((c) => !c.archived);
    return {
      working: cs.filter((c) => c.kind === 'work' || c.kind === 'send').length,
      waiting: cs.filter((c) => c.kind === 'wait').length,
      unread: cs.filter((c) => c.unread).length,
    };
  }
  const KIND_LABEL = { work: 'Working', wait: 'Waiting on you', send: 'Sending', held: 'Paused', fail: 'Couldn’t be answered', review: 'Ready for review', idle: '' };
  function convIcon(c) {
    if (c.kind === 'work') return SPIN;
    if (c.kind === 'wait') return stIcon('d-wait');
    if (c.kind === 'fail') return stIcon('s-blk');
    if (c.kind === 'review') return stIcon('s-done');
    if (c.kind === 'send' || c.kind === 'held') return stIcon('s-ns');
    return icon('bubble', 'sm');
  }
  // the conversation to open from the toolbar or ⌘0: one waiting on you, else an unread answer, else the newest
  function convToOpen() {
    const cs = convos().filter((c) => !c.archived);
    const c = cs.find((x) => x.kind === 'wait') || cs.find((x) => x.unread) || cs[0];
    return c ? String(c.id) : 'new';
  }

  // ---- reading an answer: paragraphs, lists, tables, code, **bold**, `code`, links, and screen ids as chips
  const escRe = (s) => String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  let idReCache = null;
  function idRegex() {
    if (idReCache && idReCache.src === S.data) return idReCache.re;
    const p = idPrefix();
    const shorts = S.data.screens.map((s) => shortId(s.id)).filter((x) => x.length >= 4).sort((a, b) => b.length - a.length).map(escRe);
    const re = shorts.length ? new RegExp(`(^|[^A-Za-z0-9_#])(${p ? `(?:${escRe(p)})?` : ''}(?:${shorts.join('|')}))(?![A-Za-z0-9_])`, 'gi') : null;
    idReCache = { src: S.data, re };
    return re;
  }
  const fullId = (raw) => {
    const p = idPrefix();
    const s = String(raw).toLowerCase();
    return S.data.screens.find((x) => x.id.toLowerCase() === s || (p && x.id.toLowerCase() === p.toLowerCase() + s)) || null;
  };
  // screen ids in a piece of already-escaped text become chips
  function chipify(html) {
    const re = idRegex();
    if (!re) return html;
    return html.replace(re, (m, pre, raw) => { const s = fullId(raw); return s ? pre + idChip(s.id) : m; });
  }
  const decRe = /(^|[\s(])#(\d{1,4})(?![\w])/g;
  function decChips(html) {
    return html.replace(decRe, (m, pre, n) => {
      const x = S.data.decisions.find((d) => String(d.n) === n);
      return x ? `${pre}<button class="idc dc" data-act="selectDecGo" data-n="${n}" data-tip-text="${esc(x.topic)}">#${n}</button>` : m;
    });
  }
  function inline(s) {
    return String(s).split(/(`[^`\n]+`)/g).map((part) => {
      if (/^`[^`\n]+`$/.test(part)) return `<code>${esc(part.slice(1, -1))}</code>`;
      return part.split(/(\[[^\]\n]+\]\(https?:\/\/[^\s)]+\))/g).map((bit) => {
        const lk = /^\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)$/.exec(bit);
        if (lk) return `<a href="${esc(lk[2])}" target="_blank" rel="noopener">${esc(lk[1])}</a>`;
        let x = esc(bit).replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>');
        x = decChips(chipify(x));
        return x.replace(/\n/g, '<br>');
      }).join('');
    }).join('');
  }
  function mdTable(rows) {
    const cells = (r) => r.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
    const head = cells(rows[0]);
    const body = rows.slice(1).map(cells);
    return `<div class="ct-tbl"><table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>${
      body.map((r) => `<tr>${head.map((_, k) => `<td>${inline(r[k] || '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  function richText(t) {
    const lines = String(t || '').replace(/\r\n?/g, '\n').split('\n');
    let out = ''; let i = 0;
    const para = [];
    const flush = () => { if (para.length) { out += `<p>${inline(para.join('\n'))}</p>`; para.length = 0; } };
    const isRow = (l) => /^\s*\|.*\|\s*$/.test(l || '');
    const LI = /^\s*([-*•]|\d{1,3}[.)])\s+/;
    while (i < lines.length) {
      const l = lines[i];
      if (/^\s*```/.test(l)) {
        flush();
        const buf = []; i++;
        while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) buf.push(lines[i++]);
        i++;
        out += `<pre class="ct-code"><code>${esc(buf.join('\n'))}</code></pre>`;
        continue;
      }
      if (isRow(l) && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1] || '')) {
        flush();
        const rows = [l]; i += 2;
        while (i < lines.length && isRow(lines[i])) rows.push(lines[i++]);
        out += mdTable(rows);
        continue;
      }
      const h = /^\s*#{1,4}\s+(.*)$/.exec(l);
      if (h) { flush(); out += `<p class="ct-h">${inline(h[1])}</p>`; i++; continue; }
      if (LI.test(l)) {
        flush();
        const ordered = /^\s*\d/.test(l); const items = [];
        while (i < lines.length && LI.test(lines[i])) items.push(lines[i++].replace(LI, ''));
        out += `<${ordered ? 'ol' : 'ul'}>${items.map((x) => `<li>${inline(x)}</li>`).join('')}</${ordered ? 'ol' : 'ul'}>`;
        continue;
      }
      if (!l.trim()) { flush(); i++; continue; }
      para.push(l); i++;
    }
    flush();
    return out;
  }

  // ---- what a conversation is about, and what it changed
  function textIds(t) {
    const re = idRegex();
    const out = [];
    if (!re || !t) return out;
    String(t).replace(re, (m, pre, raw) => { const s = fullId(raw); if (s && !out.includes(s.id)) out.push(s.id); return m; });
    return out;
  }
  function convScreens(c) {
    const out = [];
    c.items.forEach((n) => [n.text, n.reply && n.reply.text].forEach((t) => textIds(t).forEach((id) => { if (!out.includes(id)) out.push(id); })));
    return out;
  }
  // status changes Claude made while it handled a message, on screens the conversation is about
  // (from the message until its answer, or until the next message while it's still being worked on)
  function itemEvents(n, c, ids) {
    const i = c.items.indexOf(n);
    const next = c.items[i + 1];
    const end = next ? next.t : '9999';
    const done = n.reply && n.reply.t;
    return (S.data.events || []).filter((e) => e.by === 'claude' && ids.includes(e.id) && e.t >= n.t && e.t < end && (!done || e.t <= done));
  }

  // ---- the transcript
  function threadState(n) {
    const fk = n.fork || {};
    const th = fk.thread || {};
    if (n.state === 'failed') return { k: 'fail', label: 'Failed' };
    if (n.state === 'cancelled') return { k: 'stop', label: 'Stopped' };
    if (th.state === 'waiting') return { k: 'wait', label: 'Waiting on you' };
    if (th.state === 'review') return { k: 'review', label: 'Ready for review' };
    if (n.state === 'answered') return { k: 'ok', label: 'Answered' };
    return { k: 'work', label: 'Working' };
  }
  const stateMark = (k) => (k === 'work' ? SPIN : stIcon({ wait: 'd-wait', review: 's-done', ok: 'a-ok', fail: 's-blk', stop: 'a-stop' }[k] || 'a-ok'));
  const stateCls = (k) => ({ work: 's-wip', wait: 'd-wait', review: 's-done', ok: 'a-ok', fail: 's-blk', stop: 'a-stop' }[k] || 'a-ok');
  // how long it has been working ("6 min"), or how long the answer took ("took 21s")
  const age = (n) => {
    const t0 = n.startedAt ? n.startedAt * 1000 : (parseT(n.t) || new Date()).getTime();
    if (n.state !== 'sending') {
      const ms = n.reply && n.reply.ms ? n.reply.ms : (n.reply && parseT(n.reply.t) ? parseT(n.reply.t).getTime() - t0 : 0);
      if (!ms || ms < 0) return '';
      const sec = Math.round(ms / 1000);
      const m = Math.round(ms / 60000);
      return 'took ' + (sec < 60 ? `${Math.max(1, sec)}s` : m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`);
    }
    const m = Math.max(0, Math.round((Date.now() - t0) / 60000));
    return m < 1 ? 'just now' : m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
  };
  const whereHTML = (th) => (th && th.where === 'cloud' ? `${icon('cloud', 'xs')}<span>Cloud</span>` : th && th.where === 'mac' ? `${icon('laptop', 'xs')}<span>On this Mac</span>` : '');
  function threadCardHTML(n) {
    const fk = n.fork || {};
    const th = fk.thread || {};
    const s = threadState(n);
    const name = fk.project ? (fk.to || 'Claude project') : `Fork of “${(fk.fromTitle || 'the working session')}”`;
    let act = '';
    if (n.state === 'sending' && s.k === 'wait' && th.url) act = `<a class="btn sm" href="${esc(th.url)}" target="_blank" rel="noopener">Answer in Claude${icon('ext', 'xs')}</a>`;
    else if (n.state === 'sending') act = `<button class="btn sm" data-act="note" data-op="cancel" data-n="${n.id}">Stop</button>`;
    else if (s.k === 'review' && th.url) act = `<a class="btn sm" href="${esc(th.url)}" target="_blank" rel="noopener">Review${icon('ext', 'xs')}</a>`;
    else if (s.k === 'fail') act = `<button class="btn sm" data-act="note" data-op="retry" data-n="${n.id}">${icon('retry', 'xs')}Retry</button>`;
    const took = age(n);
    const meta = [whereHTML(th), took ? `<span>${esc(took)}</span>` : ''].filter(Boolean).join('<span aria-hidden="true">·</span>');
    const upd = n.state === 'sending' ? (th.progress || n.hint || '') : '';
    return `<div class="ct-th${act ? '' : ' noact'}" data-key="th${n.id}">
        <span class="ct-th-ic">${icon(fk.project ? 'term' : 'fork')}</span>
        <span class="ct-th-t">${esc(name)}</span>
        <span class="st ${stateCls(s.k)}">${stateMark(s.k)}<span class="stw">${s.label}</span></span>
        <span class="ct-th-m">${meta}</span>${act ? `<span class="ct-th-a">${act}</span>` : ''}
        ${upd ? `<span class="ct-th-u${n.hint && !th.progress ? ' warn' : ''}">${esc(upd)}</span>` : ''}
      </div>`;
  }
  // Undo only on the screen's latest change, while the screen still has that status
  function lastEventOf(id) {
    const evs = S.data.events || [];
    for (let i = evs.length - 1; i >= 0; i--) if (evs[i].id === id) return evs[i];
    return null;
  }
  function changeRowHTML(e) {
    const s = S.data.screens.find((x) => x.id === e.id);
    const canUndo = s && s.status === e.to && lastEventOf(e.id) === e;
    return `<div class="ct-chg">${icon('check', 'xs')}<span class="sr">Moved</span>${idChip(e.id)}<span class="sr">from</span>${statusPill(e.from, true)}<svg class="i xs ar" viewBox="0 0 24 24" aria-hidden="true">${ICONS.arrow}</svg><span class="sr">to</span>${statusPill(e.to, true)}${
      canUndo ? `<button class="lk" data-act="chatUndo" data-id="${esc(e.id)}" data-v="${esc(e.from)}">Undo</button>` : ''}</div>`;
  }
  function aiHead(kind, name, t, extra) {
    return `<div class="ct-ai-h"><span class="ct-av${kind === 'thread' ? ' sq' : ''}">${icon(kind === 'thread' ? 'term' : 'hub', 'sm')}</span><b>${esc(name)}</b>${t ? `<span class="time">${esc(t)}</span>` : ''}${extra || ''}</div>`;
  }
  // what was open beside the chat when the message went (it went with it)
  function ctxSentHTML(n) {
    const chips = (n.context || []).map((r) => {
      const dn = /^#(\d+)$/.exec(r);
      if (dn) {
        const x = S.data.decisions.find((d) => String(d.n) === dn[1]);
        return x ? `<button class="idc dc" data-act="selectDecGo" data-n="${x.n}" data-tip-text="${esc(x.topic)}">#${x.n}</button>` : '';
      }
      return S.data.screens.some((x) => x.id === r) ? idChip(r) : '';
    }).filter(Boolean).join('');
    return chips ? `<div class="ct-me-ctx"><span>With</span>${chips}</div>` : '';
  }
  function exchangeHTML(n, c, ids) {
    const st = n.state;
    const fk = n.fork || {};
    const btn = (op, label) => `<button class="lk" data-act="note" data-op="${op}" data-n="${n.id}">${label}</button>`;
    let meta = '';
    if (st === 'scheduled') meta = `<span data-countdown="${n.id}" data-at="${Date.now() + (n.sendsIn || 0) * 1000}">Sending in ${Math.ceil(n.sendsIn || 0)}s</span>${btn('edit', 'Edit')}${btn('cancel', 'Cancel')}${btn('send', 'Send Now')}`;
    else if (st === 'held') meta = `<span>Paused, not sent</span>${btn('edit', 'Edit')}${btn('send', 'Send')}${btn('cancel', 'Cancel')}`;
    else if (st === 'queued') meta = `<span>Waits for the message before it</span>${btn('edit', 'Edit')}${btn('cancel', 'Cancel')}`;
    else if (st === 'cancelled' && !fk.project && !fk.from && !fk.session) meta = `<span>Not sent</span>${btn('edit', 'Edit and Send')}`;
    const loc = n.local ? `<span class="ct-loc">${icon('laptop', 'xs')}On this Mac</span>` : '';
    const me = `<div class="ct-me${st === 'cancelled' && !meta ? '' : st === 'cancelled' ? ' off' : ''}" data-key="m${n.id}">
        ${ctxSentHTML(n)}<div class="ct-bub">${inline(n.text)}</div>
        <div class="ct-me-m">${loc}<span class="time">${clock(n.t)}${n.edited ? ' · edited' : ''}</span>${meta}</div></div>`;
    if (['scheduled', 'held', 'queued'].includes(st) || (st === 'cancelled' && meta)) return me;
    const evs = itemEvents(n, c, ids);
    const changes = evs.map(changeRowHTML).join('');
    const relayed = (n.relayed || []).map((r) => `<div class="ct-relay">${icon('arrow', 'xs')}<span>Passed on to the working session: ${esc(r.text)}</span></div>`).join('');
    let ai = '';
    if (fk.project) {
      const claimed = !!fk.claimed || st !== 'sending';
      if (st === 'sending' && !claimed) {
        ai = `<div class="ct-ai" data-key="a${n.id}">${aiHead('coord', 'Claude', '')}<div class="ct-ai-b"><p class="ct-wait">${SPIN}<span>Reading your message…</span><button class="lk" data-act="note" data-op="cancel" data-n="${n.id}">Stop</button></p></div></div>`;
      } else if (fk.to) {
        const said = fk.followUp && c.items.indexOf(n) > 0 && (c.items[c.items.indexOf(n) - 1].fork || {}).to === fk.to
          ? 'Sent to the same thread.' : `Handed to the thread <b>${esc(fk.to)}</b>.`;
        ai = `<div class="ct-ai" data-key="a${n.id}">${aiHead('coord', 'Claude', clock(fk.claimed || n.t))}<div class="ct-ai-b"><p>${said}</p>${threadCardHTML(n)}${changes}</div></div>`;
        if (n.reply) ai += `<div class="ct-ai" data-key="r${n.id}">${aiHead('thread', fk.to, clock(n.reply.t))}<div class="ct-ai-b ct-md">${richText(n.reply.text)}</div></div>`;
      } else if (n.reply) {
        ai = `<div class="ct-ai" data-key="r${n.id}">${aiHead('coord', 'Claude', clock(n.reply.t))}<div class="ct-ai-b"><div class="ct-md">${richText(n.reply.text)}</div>${changes}</div></div>`;
      } else if (st === 'sending') {
        ai = `<div class="ct-ai" data-key="a${n.id}">${aiHead('coord', 'Claude', '')}<div class="ct-ai-b"><p class="ct-wait">${SPIN}<span>Answering…</span><button class="lk" data-act="note" data-op="cancel" data-n="${n.id}">Stop</button></p>${changes}</div></div>`;
      }
    } else if (st === 'sending' || st === 'cancelled') {
      ai = `<div class="ct-ai" data-key="a${n.id}">${aiHead('coord', 'Claude', '')}<div class="ct-ai-b">${threadCardHTML(n)}${changes}</div></div>`;
    } else if (n.reply) {
      const by = fk.followUp ? 'same fork' : fk.from ? `fork of “${fk.fromTitle || 'the working session'}”` : 'a new session';
      const cost = [n.reply.ms ? `${Math.max(1, Math.round(n.reply.ms / 1000))}s` : '', n.reply.cost ? `$${n.reply.cost.toFixed(2)}` : ''].filter(Boolean).join(' · ');
      const acts = `<div class="ct-acts"><span class="faint">${esc(by)}${cost ? ' · ' + cost : ''}</span>${fk.session ? btn('openDesktop', 'Open in Claude') : ''}${
        n.forwarded ? `<span class="ct-ok">${icon('check', 'xs')}In the working session’s inbox</span>` : btn('forward', 'Send to Working Session')}</div>`;
      ai = `<div class="ct-ai" data-key="r${n.id}">${aiHead('coord', 'Claude', clock(n.reply.t))}<div class="ct-ai-b"><div class="ct-md">${richText(n.reply.text)}</div>${relayed}${changes}${acts}</div></div>`;
    }
    if (st === 'failed') {
      ai += `<div class="ct-err" data-key="e${n.id}">${stIcon('s-blk')}<div><b>Couldn’t be answered</b><p>${esc(n.error || 'Something went wrong.')}</p>
        <div class="ct-err-a"><button class="btn sm" data-act="note" data-op="retry" data-n="${n.id}">${icon('retry', 'xs')}Retry</button><button class="btn sm" data-act="note" data-op="edit" data-n="${n.id}">Edit</button></div></div></div>`;
    }
    return me + ai;
  }
  function transcriptHTML(c) {
    const ids = convScreens(c);
    let html = ''; let lastDay = '';
    c.items.forEach((n) => {
      const d = parseT(n.t);
      const day = d ? dayISO(d) : '';
      if (day && day !== lastDay) { html += `<div class="ct-day" data-key="d${day}">${esc(relDay(d))}</div>`; lastDay = day; }
      html += exchangeHTML(n, c, ids);
    });
    return html;
  }
  const SUGGEST = [
    ['What’s waiting on me?', 'Decisions and threads that need you', 'what’s waiting on me?'],
    ['What changed today?', 'Statuses, threads and commits', 'what changed today?'],
    ['Which screens can I test?', 'Everything that is Done', 'which screens can I test now?'],
    ['Hand off the next screen', 'Claude starts a thread for it', 'hand the next screen to a thread'],
  ];
  function chatEmptyHTML() {
    const p = projectMode();
    return `<div class="ct-empty" data-key="empty">
        <span class="glyph">${icon(p ? 'hub' : 'bubbles', 'lg')}</span>
        <h2>${p ? 'Ask your Claude project' : 'Ask Claude anything'}</h2>
        <p>${p ? 'Claude answers here, or hands the work to a thread and tells you which one. Follow-ups go to the same thread.'
    : 'A fork of the session that’s doing the work answers here, even while that session is busy. It can pass instructions on to it.'}</p>
        <div class="ct-sugg">${SUGGEST.map((s, i) => `<button data-act="chatSuggest" data-i="${i}"><b>${esc(s[0])}</b><span>${esc(s[1])}</span></button>`).join('')}</div>
      </div>`;
  }

  // ---- the message field
  const chatKey = (c) => (c ? 'chat:' + c.id : 'chat:new');
  // project threads seen lately, newest first, with what they're doing
  function knownThreads() {
    const out = [];
    S.notes.slice().reverse().forEach((n) => {
      const fk = n.fork || {};
      if (!fk.project || !fk.to || out.some((x) => x.name === fk.to)) return;
      out.push({ name: fk.to, n });
    });
    return out.slice(0, 8);
  }
  function chatTo(c) {
    const k = c ? String(c.id) : 'new';
    if (k in S.chatTo) return S.chatTo[k];
    if (!projectMode()) return c ? 'same' : '';
    const last = c && c.items.slice().reverse().find((n) => (n.fork || {}).to);
    return last ? last.fork.to : '';
  }
  function toLabel(c) {
    const v = chatTo(c);
    if (projectMode()) return v === 'new' ? { ic: 'plus', t: 'New thread' } : v ? { ic: 'term', t: v } : { ic: 'hub', t: 'Claude decides' };
    if (c) return { ic: 'fork', t: 'Same fork' };
    const ss = S.sessions || [];
    const s = v === 'new' ? null : ss.find((x) => x.id === v) || ss[0];
    return s ? { ic: 'fork', t: `Fork of “${s.title.slice(0, 40)}”` } : { ic: 'fork', t: v === 'new' ? 'A new session' : 'Looking for the session…' };
  }
  // What's open beside the chat: the screen or decision the page shows. It goes with a message unless you leave it
  // out (× on its chip, until something else is open). The Mac app tells its chat panel what its page shows.
  function chatContext() {
    let k = null;
    if (PANEL) k = S.panelCtx || null;
    else {
      const r = route();
      if (r.id && r.view === 'screens') k = 'screen:' + r.id;
      else if (r.id && r.view === 'decisions') k = 'decision:' + r.id;
    }
    if (!k || !S.data) return null;
    const i = k.indexOf(':');
    const kind = k.slice(0, i); const id = k.slice(i + 1);
    if (kind === 'screen') {
      const s = S.data.screens.find((x) => x.id === id);
      return s ? { key: k, ref: s.id, label: shortId(s.id), name: s.name, ic: stIcon(SCLS[s.status], 'xs') } : null;
    }
    if (kind === 'decision') {
      const x = S.data.decisions.find((d) => String(d.n) === id);
      return x ? { key: k, ref: '#' + x.n, label: '#' + x.n, name: x.topic, ic: icon('decide', 'xs') } : null;
    }
    return null;
  }
  const ctxShown = () => { const x = chatContext(); return x && S.ctxDropped !== x.key ? x : null; };
  function composerHTML(c) {
    const key = chatKey(c);
    const busy = !!(c && c.items.some((n) => n.state === 'sending'));
    const editing = S.chatEdit && S.notes.find((n) => n.id === S.chatEdit);
    const text = editing ? editing.text : draft(key, '');
    const empty = !String(text).trim();
    const tl = toLabel(c);
    const local = !!S.chatLocal[c ? c.id : 'new'];
    const ph = editing ? 'Edit your message' : c ? 'Follow up…' : projectMode() ? 'Ask, or hand the project some work…' : 'Ask about the work…';
    const stop = busy && empty && !editing;
    const cx = !editing && ctxShown();
    const fixedTo = !projectMode() && c;
    return `<div class="cp-f">
        ${editing ? `<div class="ct-ctx">${icon('note', 'xs')}<span>Editing your message</span><button class="lk" data-act="chatEditCancel">Cancel</button></div>` : ''}
        <div class="fld${S.mention ? ' menu-open' : ''}">
          ${cx ? `<div class="fld-ctx"><span class="tok" data-tip-text="Open beside the chat, so it goes with your message">${cx.ic}<span class="tid">${esc(cx.label)}</span><span class="tn">${esc(cx.name)}</span><button class="tok-x" data-act="chatCtxDrop" aria-label="Leave ${esc(cx.label)} out">${icon('close', 'xs')}</button></span></div>` : ''}
          <label class="sr" for="chat-msg">Message</label>
          <textarea id="chat-msg" class="fld-ta" rows="1" data-draft="${esc(key)}" placeholder="${esc(ph)}">${esc(text)}</textarea>
          ${stop ? `<button class="fld-send" data-act="chatStop" aria-label="Stop" data-tip-text="Stop">${icon('stop', 'sm')}</button>`
    : `<button class="fld-send${empty ? ' off' : ''}" data-act="chatSend" aria-label="${editing ? 'Save' : 'Send'}"${empty ? ' aria-disabled="true"' : ''}>${icon('arrowUp', 'sm')}</button>`}
        </div>
        <div class="fld-bar">
          <button class="mb" data-act="chatPlus" aria-haspopup="menu" aria-expanded="${S.chatMenu === 'plus'}" aria-label="Mention a screen or decision${projectMode() ? ', or run on this Mac' : ''}" data-tip-text="Mention a screen or decision">${icon('plus', 'sm')}${icon('chev', 'xs')}</button>
          <button class="ct-to" data-act="chatTo" aria-haspopup="menu" aria-expanded="${S.chatMenu === 'to'}" aria-label="Send to: ${esc(tl.t)}"${fixedTo ? ' disabled' : ''}>${icon(tl.ic, 'xs')}<span>${esc(tl.t)}</span>${fixedTo ? '' : icon('updown', 'xs')}</button>
          ${local ? `<span class="ct-local">${icon('laptop', 'xs')}<span>On this Mac</span><button data-act="chatLocal" aria-label="Don’t run it on this Mac">${icon('close', 'xs')}</button></span>` : ''}
        </div>
      </div>`;
  }

  // ---- the panel: Chat where the sidebar is, like Xcode's coding
  // assistant. ≡ and ✦ at the top of the sidebar switch between the views and Chat, and the page stays beside it.
  // One conversation at a time: ✎ starts one, its title has Rename, Open Thread in Claude and Archive, and the clock
  // lists them all. In a browser the page draws it in its own sidebar; the Mac app shows this page with ?panel=chat
  // in its sidebar.
  function chatPanelHTML() {
    const c = curConv();
    const title = c ? c.title : 'New Conversation';
    const others = convos().filter((x) => !x.archived && (!c || x.id !== c.id) && (x.kind === 'wait' || x.unread));
    const hdot = others.some((x) => x.kind === 'wait') ? ' wait' : others.length ? ' dot' : '';
    return `<div class="cp" data-conv="${c ? c.id : 'new'}">
        <div class="cp-h">
          <span class="cp-l">
            <button class="ct-ib" data-act="chatNew" aria-label="New Conversation" data-tip-text="New Conversation${NATIVE ? `  ${KEY}N` : ''}">${icon('compose', 'sm')}</button>
            <button class="ct-ib c" data-act="chatCompose" aria-haspopup="menu" aria-expanded="${S.chatMenu === 'compose'}" aria-label="More ways to start a conversation">${icon('chev', 'xs')}</button>
          </span>
          <button class="cp-t" data-act="chatTitle" aria-haspopup="menu" aria-expanded="${S.chatMenu === 'title'}"${c ? '' : ' disabled'} data-tip-text="${esc(title)}"><span>${esc(title)}</span>${c ? icon('chev', 'xs') : ''}</button>
          <span class="cp-r"><button class="ct-ib hist${hdot}" data-act="chatHistory" aria-haspopup="dialog" aria-expanded="${S.chatMenu === 'history'}" aria-label="Conversations${others.length ? `, ${others.length} need you` : ''}" data-tip-text="Conversations">${icon('clock', 'sm')}</button></span>
        </div>
        <div class="cp-b" id="ct-body" data-scroll="chat"><div class="ct-col" aria-live="polite">${c ? transcriptHTML(c) : chatEmptyHTML()}</div></div>
        ${composerHTML(c)}
      </div>`;
  }
  // in a browser, the top of the sidebar: ≡ the views and batches, ✦ Chat (a dot while something needs you)
  function modeSwitchHTML() {
    const cc = chatCounts();
    const chat = S.side === 'chat';
    const dot = !chat && (cc.waiting || cc.unread);
    return `<div class="sb-mode" role="group" aria-label="The sidebar shows">
        <button class="md${chat ? '' : ' on'}" data-act="sideViews" aria-pressed="${!chat}" aria-label="Views and batches" data-tip-text="Views and batches">${icon('list')}</button>
        <button class="md${chat ? ' on' : ''}" data-act="sideChat" aria-pressed="${chat}" aria-label="Chat${cc.waiting ? `, ${cc.waiting} waiting on you` : cc.unread ? `, ${cc.unread} new` : ''}" data-tip-text="Chat  ${KEY}0">${icon('assist')}${dot ? `<span class="bdg${cc.waiting ? ' wait' : ''}" aria-hidden="true"></span>` : ''}</button>
      </div>`;
  }
  const curConv = () => {
    const id = S.chatConv;
    if (!id || id === 'new' || !S.data) return null;
    return convos().find((x) => String(x.id) === String(id)) || null;
  };
  // the chat is on screen: the browser's sidebar shows it, or the Mac app shows its chat panel
  const chatVisible = () => (PANEL ? S.panelVisible !== false && !document.hidden : !NATIVE && S.side === 'chat' && !document.hidden);
  const saveConv = () => { if (WSID && OWN_CHAT) store.set('chatConv:' + WSID, S.chatConv); };
  function focusChat() {
    requestAnimationFrame(() => { const t = $('#chat-msg'); if (t && !isPhone()) t.focus({ preventScroll: true }); });
  }
  function setSide(side) {
    S.side = side === 'chat' ? 'chat' : 'views';
    S.peek = false;
    store.set('side', S.side);
    if (S.side === 'chat' && !S.chatConv) S.chatConv = convToOpen();
    closeChatMenu(); closeMention();
    render();
  }
  // open the chat on a conversation (none: the one you had, else the one that needs you)
  function openChat(id) {
    if (!S.data) return;
    if (NATIVE && !PANEL) { native({ type: 'openChat', id: id == null ? null : String(id) }); return; }
    if (id != null) { S.chatConv = String(id); S.chatEdit = null; }
    else if (!S.chatConv || (S.chatConv !== 'new' && !curConv())) S.chatConv = convToOpen();
    saveConv();
    closeChatMenu(); closeMention();
    if (!PANEL && S.side !== 'chat') setSide('chat'); else render();
    focusChat();
  }
  function newChat(o = {}) {
    if (!S.data) return;
    if (NATIVE && !PANEL) { native({ type: 'newChat' }); return; }
    S.chatConv = 'new'; S.chatEdit = null; saveConv();
    if (o.to) S.chatTo.new = o.to; else delete S.chatTo.new;
    if (o.about) S.ctxDropped = null;
    closeChatMenu(); closeMention();
    if (!PANEL && S.side !== 'chat') setSide('chat'); else render();
    focusChat();
  }
  function toggleChat() {
    if (!S.data || PANEL) return;
    if (NATIVE) { native({ type: 'toggleChat' }); return; }
    if (S.side === 'chat') setSide('views'); else openChat();
  }
  function pickConv(id) {
    S.chatConv = String(id); S.chatEdit = null; saveConv();
    closeChatMenu();
    render();
    focusChat();
  }

  // ---- doing things
  let chatSending = false;
  async function chatSend() {
    const t = $('#chat-msg');
    if (!t || !t.value.trim() || chatSending) { if (t) t.focus(); return; }
    const c = curConv();
    const key = chatKey(c);
    chatSending = true;
    try {
      if (S.chatEdit) {
        await Notes.act(S.chatEdit, 'edit', t.value);
        S.chatEdit = null;
      } else {
        const to = chatTo(c);
        const opts = { delay: 0, local: !!S.chatLocal[c ? c.id : 'new'] };
        if (c) opts.parent = c.last.id;
        if (projectMode()) { if (to && to !== 'same') opts.to = to; } else if (!c) opts.target = to || null;
        const cx = ctxShown();
        if (cx) opts.context = [cx.ref];
        const n = await Notes.send(t.value, opts);
        delete S.drafts[key]; saveDrafts();
        if (!projectMode() && S.protectedFolders && S.protectedFolders.length) native({ type: 'askFolders', folders: S.protectedFolders, quiet: true });
        if (!c && n) {
          delete S.chatTo.new; delete S.chatLocal.new;
          S.chatConv = String(n.id); saveConv();
        }
      }
      const t2 = $('#chat-msg'); if (t2) { t2.value = ''; growTA(t2); t2.focus(); }
      render();
    } catch (err) { toast(esc(err.message), err.message, 'Blocked'); }
    chatSending = false;
  }
  async function chatStop() {
    const c = curConv();
    if (!c) return;
    const live = c.items.filter((n) => n.state === 'sending');
    try { for (const n of live) await Notes.act(n.id, 'cancel'); } catch (err) { toast(esc(err.message), err.message, 'Blocked'); }
  }
  async function noteOp(a) {
    const id = +a.dataset.n;
    const op = a.dataset.op;
    const n = S.notes.find((x) => x.id === id);
    if (!n) return;
    try {
      if (op === 'edit') {
        if (['scheduled', 'queued'].includes(n.state)) await Notes.act(id, 'hold');
        S.chatEdit = id;
        render();
        const t = $('#chat-msg'); if (t) { t.value = n.text; growTA(t); t.focus(); t.setSelectionRange(t.value.length, t.value.length); }
      } else if (op === 'openDesktop') {
        await Notes.open(id, 'desktop');
        toast('Opening the fork in Claude', 'Opening the fork in Claude', 'note');
      } else if (op === 'forward') {
        await Notes.act(id, 'forward');
        toast('Sent to the working session’s inbox', 'Sent to the working session', 'note');
      } else {
        await Notes.act(id, op);
      }
    } catch (err) { toast(esc(err.message), err.message, 'Blocked'); }
  }
  // the field grows with what you type, up to about eight lines, and fits again when its width changes (the
  // sidebar sliding open, a resized window)
  function growTA(t) {
    if (!t) return;
    t.style.height = 'auto';
    t.style.height = Math.min(t.scrollHeight, 172) + 'px';
  }
  let taWidth = 0;
  const taRO = window.ResizeObserver ? new ResizeObserver((es) => {
    const e = es[es.length - 1];
    const w = Math.round(e.contentRect.width);
    if (w !== taWidth) { taWidth = w; growTA(e.target); }
  }) : null;
  function watchTA(t) {
    if (!taRO || !t || taRO.el === t) return;
    taRO.disconnect(); taRO.observe(t); taRO.el = t; taWidth = 0;
  }
  // the panel's menus: ✎ ⌄ (ways to start), the title (this conversation), the clock (every conversation),
  // + ⌄ (what to add) and To ⌄ (where it goes)
  const MENU_ACTS = '[data-act="chatCompose"], [data-act="chatTitle"], [data-act="chatHistory"], [data-act="chatPlus"], [data-act="chatTo"]';
  function closeChatMenu() {
    const m = $('#ct-menu'); if (m) m.remove();
    if (S.chatMenu) { S.chatMenu = null; $$(MENU_ACTS).forEach((b) => b.setAttribute('aria-expanded', 'false')); }
  }
  // every item keeps the check column, like a Mac menu, so the icons line up
  const mi = (act, v, ic, label, opts = {}) => `<button role="${opts.radio ? 'menuitemradio' : 'menuitem'}"${opts.radio ? ` aria-checked="${!!opts.on}"` : ''} data-act="${act}" data-v="${esc(v)}">${opts.on ? icon('check', 'sm') : '<span class="i sm"></span>'}<span class="mic">${ic}</span><span class="ml"><span>${esc(label)}</span>${opts.sub ? `<span class="ms">${esc(opts.sub)}</span>` : ''}</span>${opts.right ? `<span class="mr">${opts.right}</span>` : ''}</button>`;
  // the conversations, as the clock lists them: newest first by day; waiting and unread ones stand out
  function historyListHTML() {
    const c = curConv();
    const ql = (S.histQ || '').trim().toLowerCase();
    const list = convos().filter((x) => (S.histArchived ? x.archived : !x.archived) && (!ql || x.title.toLowerCase().includes(ql) || x.items.some((n) => String(n.text).toLowerCase().includes(ql))));
    if (!list.length) return `<p class="h-none">${ql ? 'No conversations match.' : S.histArchived ? 'Nothing archived.' : 'No conversations yet.'}</p>`;
    const today = dayISO(new Date());
    const yest = dayISO(new Date(Date.now() - 864e5));
    let last = '';
    return list.map((x) => {
      const d = parseT(x.at);
      const day = d ? dayISO(d) : '';
      const grp = day === today ? 'Today' : day === yest ? 'Yesterday' : 'Earlier';
      const head = grp !== last ? `<div class="mh">${grp}</div>` : '';
      last = grp;
      const right = x.unread ? '<span class="dot" aria-label="unread"></span>' : `<span class="w">${esc(KIND_LABEL[x.kind] || whenShort(x.at))}</span>`;
      return `${head}<button class="hrow${c && c.id === x.id ? ' cur' : ''}${x.unread ? ' unread' : ''}${x.kind === 'wait' ? ' wait' : ''}" role="menuitem" data-act="chatPick" data-v="${x.id}"><span class="ic">${convIcon(x)}</span><span class="t">${esc(x.title)}</span>${right}</button>`;
    }).join('');
  }
  function openChatMenu(kind, btn) {
    closeChatMenu();
    closeMention();
    const c = curConv();
    const ck = c ? c.id : 'new';
    let items = '';
    if (kind === 'compose') {
      const cx = chatContext();
      items = mi('chatNew', '', icon('compose', 'sm'), 'New Conversation', { right: NATIVE ? `${KEY}N` : '' });
      if (cx) items += mi('chatNewAbout', '', icon('screen', 'sm'), `New Conversation About ${cx.label}`, { sub: 'What’s open beside the chat' });
      if (projectMode()) items += '<hr>' + mi('chatNewThread', '', icon('term', 'sm'), 'Hand Off to a New Thread…');
    } else if (kind === 'title' && c) {
      const url = (c.items.slice().reverse().map((n) => ((n.fork || {}).thread || {}).url).find(Boolean)) || '';
      items = mi('chatRename', '', icon('pencil', 'sm'), 'Rename…');
      if (url) items += mi('chatOpenThread', url, icon('ext', 'sm'), 'Open Thread in Claude');
      else if (c.items.some((n) => (n.fork || {}).session)) items += mi('chatOpenFork', String(c.last.id), icon('ext', 'sm'), 'Open in Claude');
      items += '<hr>' + mi('chatArchive', c.archived ? 'unarchive' : 'archive', icon('archive', 'sm'), c.archived ? 'Move Out of the Archive' : 'Archive');
    } else if (kind === 'history') {
      const nArch = convos().filter((x) => x.archived).length;
      items = `<label class="hs">${icon('search', 'xs')}<span class="sr">Search conversations</span><input id="hist-q" type="text" placeholder="Search Conversations" value="${esc(S.histQ || '')}" autocomplete="off" spellcheck="false"></label>
        <div class="h-list" id="hist-list">${historyListHTML()}</div>
        ${nArch || S.histArchived ? `<hr>${mi('chatHistArchived', '', '', S.histArchived ? 'Back to Conversations' : 'Show Archived', { right: S.histArchived ? '' : String(nArch) })}` : ''}`;
    } else if (kind === 'plus') {
      items = mi('chatInsert', '@', icon('at', 'sm'), 'Mention a Screen…', { right: '@' }) + mi('chatInsert', '#', icon('decide', 'sm'), 'Mention a Decision…', { right: '#' });
      const cx = chatContext();
      if (cx && S.ctxDropped === cx.key) items += mi('chatCtxAdd', '', icon('screen', 'sm'), `Add ${cx.label}, Open Beside the Chat`);
      if (projectMode()) items += `<hr>${mi('chatLocal', '1', icon('laptop', 'sm'), 'Run on This Mac', { radio: true, on: !!S.chatLocal[ck], sub: 'For files and tools only this Mac has' })}`;
    } else if (kind === 'to') {
      const v = chatTo(c);
      if (projectMode()) {
        items = mi('chatPickTo', '', icon('hub', 'sm'), 'Claude decides', { radio: true, on: !v, sub: 'Answers here or picks the thread' });
        const ts = knownThreads();
        if (ts.length) items += '<hr><div class="mh">Threads</div>' + ts.map((x) => { const s = threadState(x.n); return mi('chatPickTo', x.name, s.k === 'work' && x.n.state === 'sending' ? SPIN : stIcon(stateCls(s.k)), x.name, { radio: true, on: v === x.name, right: esc(x.n.state === 'sending' ? s.label : 'Idle') }); }).join('');
        items += '<hr>' + mi('chatPickTo', 'new', icon('plus', 'sm'), 'New Thread', { radio: true, on: v === 'new' });
      } else {
        const ss = S.sessions;
        if (ss === null) { Notes.sessions(); items = '<div class="mh">Looking for the working session…</div>'; } else {
          items = '<div class="mh">Fork from</div>' + ss.map((x, i) => mi('chatPickTo', x.id, icon('fork', 'sm'), x.title.slice(0, 54), { radio: true, on: v ? v === x.id : i === 0, right: esc(x.ago) })).join('')
            + '<hr>' + mi('chatPickTo', 'new', icon('plus', 'sm'), 'A New Session (no context)', { radio: true, on: v === 'new' });
        }
      }
    }
    if (!items) return;
    const m = document.createElement('div');
    m.className = 'menu ct-menu' + (kind === 'history' ? ' ct-hist' : ''); m.id = 'ct-menu'; m.setAttribute('role', kind === 'history' ? 'dialog' : 'menu');
    if (kind === 'history') m.setAttribute('aria-label', 'Conversations');
    m.innerHTML = items;
    document.body.appendChild(m);
    const r = btn.getBoundingClientRect();
    const up = kind === 'plus' || kind === 'to';
    const W = window.innerWidth;
    let x = r.left;
    if (kind === 'history') x = r.right - m.offsetWidth;
    else if (kind === 'title') x = r.left + r.width / 2 - m.offsetWidth / 2;
    m.style.left = Math.round(Math.max(8, Math.min(W - m.offsetWidth - 8, x))) + 'px';
    m.style.top = Math.round(up ? Math.max(8, r.top - m.offsetHeight - 6) : r.bottom + 6) + 'px';
    S.chatMenu = kind;
    btn.setAttribute('aria-expanded', 'true');
    const first = kind === 'history' ? (isPhone() ? m.querySelector('.hrow.cur, .hrow') : m.querySelector('#hist-q')) : (m.querySelector('[aria-checked="true"]') || m.querySelector('button'));
    if (first) first.focus();
  }
  document.addEventListener('pointerdown', (e) => {
    if (S.chatMenu && !e.target.closest('#ct-menu, ' + MENU_ACTS)) closeChatMenu();
    if (S.mention && !e.target.closest('#ct-mention, #chat-msg')) closeMention();
  });
  // @ and # in the message field: a menu of screens or decisions, inserted as their ids
  function mentionAt(t) {
    const before = t.value.slice(0, t.selectionStart);
    const m = /(^|\s)([@#])([^\s@#]{0,40})$/.exec(before);
    return m ? { ch: m[2], q: m[3], start: before.length - m[3].length - 1 } : null;
  }
  function mentionItems(ch, q) {
    const ql = q.toLowerCase();
    if (ch === '#') {
      return S.data.decisions.filter((x) => !ql || String(x.n).startsWith(ql) || x.topic.toLowerCase().includes(ql)).slice(0, 8)
        .map((x) => ({ ins: `#${x.n}`, html: `<span class="mic dn">#${x.n}</span><span class="ml"><span>${esc(x.topic)}</span></span>${dPill(answered(x) ? 'Answered' : x.status, true)}` }));
    }
    const p = idPrefix().toLowerCase();
    return S.data.screens.filter((s) => !ql || s.id.toLowerCase().includes(ql) || (p + shortId(s.id)).toLowerCase().includes(ql) || s.name.toLowerCase().includes(ql))
      .sort((a, b) => (WORKING.includes(b.status) - WORKING.includes(a.status)) || a.order - b.order).slice(0, 8)
      .map((s) => ({ ins: s.id, html: `<span class="mic">${stIcon(SCLS[s.status])}</span><span class="ml"><span><span class="mono">${esc(shortId(s.id))}</span> ${esc(s.name)}</span></span><span class="mr">${esc(SHORT[s.status] || s.status)}</span>` }));
  }
  function closeMention() { S.mention = null; const m = $('#ct-mention'); if (m) m.remove(); }
  function renderMention() {
    const t = $('#chat-msg');
    const at = t && mentionAt(t);
    if (!at) { closeMention(); return; }
    const items = mentionItems(at.ch, at.q);
    if (!items.length) { closeMention(); return; }
    const i = S.mention && S.mention.ch === at.ch && S.mention.q === at.q ? Math.min(S.mention.i, items.length - 1) : 0;
    S.mention = { ...at, items, i };
    let m = $('#ct-mention');
    if (!m) { m = document.createElement('div'); m.className = 'menu ct-menu ct-mention'; m.id = 'ct-mention'; m.setAttribute('role', 'listbox'); document.body.appendChild(m); }
    m.innerHTML = `<div class="mh">${at.ch === '#' ? 'Decisions' : 'Screens'}</div>` + items.map((x, k) => `<button role="option" aria-selected="${k === i}" class="${k === i ? 'on' : ''}" data-act="chatMentionPick" data-i="${k}">${x.html}</button>`).join('');
    const box = t.closest('.fld').getBoundingClientRect();
    m.style.left = Math.round(Math.max(8, box.left)) + 'px';
    m.style.width = Math.round(Math.min(420, box.width, window.innerWidth - 16)) + 'px';
    m.style.top = Math.round(Math.max(8, box.top - m.offsetHeight - 6)) + 'px';
  }
  function pickMention(k) {
    const t = $('#chat-msg');
    const mm = S.mention;
    if (!t || !mm || !mm.items[k]) return;
    const ins = mm.items[k].ins + ' ';
    const end = t.selectionStart;
    t.value = t.value.slice(0, mm.start) + ins + t.value.slice(end);
    const pos = mm.start + ins.length;
    t.setSelectionRange(pos, pos);
    closeMention();
    S.drafts[t.dataset.draft] = t.value; saveDrafts();
    growTA(t);
    syncSend();
    t.focus();
  }
  function insertTrigger(ch) {
    const t = $('#chat-msg');
    if (!t) return;
    const s = t.selectionStart; const v = t.value;
    const pre = s > 0 && !/\s/.test(v[s - 1]) ? ' ' : '';
    t.value = v.slice(0, s) + pre + ch + v.slice(t.selectionEnd);
    const pos = s + pre.length + 1;
    t.focus(); t.setSelectionRange(pos, pos);
    renderMention();
  }
  // the send button follows the field without a full render
  function syncSend() {
    const t = $('#chat-msg');
    const b = $('.fld-send');
    if (!t || !b) return;
    const c = curConv();
    const busy = !!(c && c.items.some((n) => n.state === 'sending'));
    const empty = !t.value.trim();
    const wantStop = busy && empty && !S.chatEdit;
    const isStop = b.dataset.act === 'chatStop';
    if (wantStop !== isStop) { render(); return; }
    if (!isStop) { b.classList.toggle('off', empty); if (empty) b.setAttribute('aria-disabled', 'true'); else b.removeAttribute('aria-disabled'); }
  }
  document.addEventListener('input', (e) => {
    if (e.target.id === 'hist-q') { S.histQ = e.target.value; const l = $('#hist-list'); if (l) l.innerHTML = historyListHTML(); return; }
    if (e.target.id !== 'chat-msg') return;
    growTA(e.target);
    syncSend();
    renderMention();
  });
  document.addEventListener('keydown', (e) => {
    const t = e.target;
    if (!t) return;
    // the clock's list: ↓ from the search field into the list, Enter on the first match
    if (t.id === 'hist-q') {
      if (e.key === 'ArrowDown') { e.preventDefault(); const r = $('#hist-list .hrow'); if (r) r.focus(); }
      else if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); const r = $('#hist-list .hrow'); if (r) pickConv(r.dataset.v); }
      return;
    }
    if (t.classList && t.classList.contains('hrow') && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault();
      const rows = $$('#hist-list .hrow'); const i = rows.indexOf(t);
      const n = rows[i + (e.key === 'ArrowDown' ? 1 : -1)];
      if (n) n.focus(); else if (e.key === 'ArrowUp') { const q = $('#hist-q'); if (q) q.focus(); }
      return;
    }
    if (t.id !== 'chat-msg') return;
    if (S.mention) {
      const n = S.mention.items.length;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); S.mention.i = (S.mention.i + (e.key === 'ArrowDown' ? 1 : -1) + n) % n; renderMention(); return; }
      if ((e.key === 'Enter' || e.key === 'Tab') && !e.isComposing) { e.preventDefault(); e.stopImmediatePropagation(); pickMention(S.mention.i); return; }
      if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); closeMention(); return; }
    }
    if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229 && !e.shiftKey && !e.altKey) {
      e.preventDefault(); e.stopImmediatePropagation();
      chatSend();
    }
  }, true);
  // opening a conversation marks its answers read
  let seenTimer = 0;
  function markConvSeen(c) {
    if (!c || !chatVisible() || !c.items.some((n) => !n.seen)) return;
    clearTimeout(seenTimer);
    seenTimer = setTimeout(() => Notes.seen(c.items.map((n) => n.id)).catch(() => {}), 600);
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) markConvSeen(curConv()); });
  // after a render: a newly opened conversation shows its end; one you're reading keeps its place unless you were at the end
  function afterChatRender(prev) {
    const b = $('#ct-body');
    if (!b) return;
    const conv = b.closest('.cp').dataset.conv;
    if (!prev || prev.conv !== conv || prev.end) b.scrollTop = b.scrollHeight;
    else b.scrollTop = prev.top;
    const t = $('#chat-msg');
    if (t) { growTA(t); watchTA(t); }
    if (prev && prev.conv !== conv) { closeMention(); closeChatMenu(); }
    markConvSeen(curConv());
    tickCountdowns();
    // with forks answering, the field says which session the fork comes from: look it up once per workspace
    if (!projectMode() && S.sessions === null && !S.sessionsAsked) { S.sessionsAsked = true; Notes.sessions(); }
  }
  const chatScroll = () => {
    const b = $('#ct-body');
    return b ? { conv: b.closest('.cp').dataset.conv, top: b.scrollTop, end: b.scrollTop + b.clientHeight >= b.scrollHeight - 30 } : null;
  };
  // the Mac app's chat panel: this page with ?panel=chat, alone in the app's sidebar
  function renderPanel() {
    if (!S.data) {
      root.innerHTML = `<div class="cp-doc"><p class="cp-off">${S.noWorkspace ? 'No workspace yet.' : S.offline ? 'Can’t reach Plots. It reconnects on its own.' : 'Opening…'}</p></div>`;
      return;
    }
    if (!$('#cpdoc')) root.innerHTML = '<div class="cp-doc" id="cpdoc"></div>';
    const fk = focusKey(document.activeElement);
    const prev = chatScroll();
    patch($('#cpdoc'), chatPanelHTML());
    restoreFocus(fk);
    afterChatRender(prev);
    edgeFades();
    const c = curConv();
    const shown = c ? String(c.id) : 'new';
    if (shown !== S.reportedConv) { S.reportedConv = shown; native({ type: 'panel', conv: shown }); }
  }

  let cdTimer = 0;
  function tickCountdowns() {
    clearTimeout(cdTimer);
    const els = $$('[data-countdown]');
    els.forEach((el) => { el.textContent = `Sending in ${Math.max(0, Math.ceil((+el.dataset.at - Date.now()) / 1000))}s`; });
    if (els.length) cdTimer = setTimeout(tickCountdowns, 250);
  }

  // keep keyboard focus inside an open dialog
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const dlg = overlay.querySelector('[role="dialog"]');
    if (!dlg) return;
    const f = $$('a[href], button:not([disabled]), textarea, input, select, summary, [tabindex="0"]', dlg).filter((x) => x.offsetParent !== null);
    if (!f.length) return;
    const first = f[0]; const last = f[f.length - 1];
    if (!dlg.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
    else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  // ------------------------------------------------------------------ writes (notes, answers, status) go to Claude's inbox
  function setHint(key, text) {
    const h = $(`[data-hint="${key}"]`);
    if (h) h.textContent = text;
  }
  async function saveNote(btn) {
    const id = btn.dataset.id;
    const key = `screen:${id}`;
    const t = $('#my-notes');
    btn.disabled = true;
    try {
      await post(`/api/screen/${id}`, { myNotes: t ? t.value : '' });
      delete S.drafts[key]; saveDrafts();
      toast('Note saved to Claude’s inbox', 'Note saved', 'note');
      await refresh(false);
      setHint(key, 'Saved. Claude will see it in its inbox.');
    } catch (err) { toast(esc(err.message), err.message, 'Blocked'); }
    btn.disabled = false;
  }
  // changes made here already get their own notice; the live update must not announce them again
  const mine = new Set();
  const expect = (k) => { mine.add(k); setTimeout(() => mine.delete(k), 15000); };
  async function answerDecision(btn, confirm) {
    const n = btn.dataset.n;
    const key = `dec:${n}`;
    const t = $(`[data-dn="${n}"]`);
    const body = { myNotes: t ? t.value : '' };
    const prev = (S.data.decisions.find((x) => String(x.n) === String(n)) || {}).status;
    if (confirm) body.status = 'Confirmed';
    else if (!body.myNotes.trim()) { if (t) t.focus(); return; }
    btn.disabled = true;
    try {
      if (confirm) expect(`d:${n}:Confirmed`);
      await post(`/api/decision/${n}`, body);
      delete S.drafts[key]; saveDrafts();
      if (confirm && prev && prev !== 'Confirmed') {
        toast(`Decision <b>#${n}</b> confirmed`, `Decision ${n} confirmed`, 'Done',
          { label: 'Undo', run: () => undo(`/api/decision/${n}`, prev, `d:${n}:${prev}`, `Decision <b>#${n}</b> is back to ${esc(prev)}`, `Decision ${n} is back to ${prev}`, 'note') });
      } else toast(`Answer for <b>#${n}</b> sent to Claude`, `Answer for decision ${n} sent`, 'note');
      await refresh(false);
    } catch (err) { toast(esc(err.message), err.message, 'Blocked'); btn.disabled = false; }
  }
  async function setStatus(sel) { return changeStatus(sel.dataset.id, sel.value); }
  async function changeStatus(id, to) {
    const s = S.data.screens.find((x) => x.id === id);
    const prev = s && s.status;
    if (!s || prev === to) return;
    try {
      expect(`s:${id}:${to}`);
      await post(`/api/screen/${id}`, { status: to });
      if (s && prev !== to) {
        toast(`<b>${esc(s.name)}</b> → ${esc(to)}`, `${s.name} moved to ${to}`, to,
          { label: 'Undo', run: () => undo(`/api/screen/${s.id}`, prev, `s:${s.id}:${prev}`, `<b>${esc(s.name)}</b> is back to ${esc(prev)}`, `${s.name} is back to ${prev}`, prev) });
      }
      await refresh(false);
    } catch (err) { toast(esc(err.message), err.message, 'Blocked'); render(); }
  }
  // Undo posts the previous status back; Claude's inbox keeps both changes
  async function undo(url, status, key, html, text, kind) {
    try {
      expect(key);
      await post(url, { status });
      toast(html, text, kind);
      await refresh(false);
    } catch (err) { toast(esc(err.message), err.message, 'Blocked'); }
  }

  // ------------------------------------------------------------------ the status menu
  // Click a status (in a table or the details) or press S on the selected screen: every status with its icon,
  // the number keys pick one.
  let stMenuFor = null;
  function openStatusMenu(btn, id) {
    closeStatusMenu();
    const s = S.data && S.data.screens.find((x) => x.id === id);
    if (!s || !btn) return;
    stMenuFor = { id, btn };
    const m = document.createElement('div');
    m.className = 'menu st-menu'; m.id = 'st-menu'; m.setAttribute('role', 'menu');
    m.setAttribute('aria-label', `Status of ${s.id}`);
    m.innerHTML = `<div class="st-menu-h"><span class="mono">${esc(shortId(s.id))}</span> ${esc(s.name)}</div>`
      + STATUS.map((x, i) => `<button role="menuitemradio" aria-checked="${x === s.status}" data-act="stPick" data-v="${esc(x)}">${stIcon(SCLS[x])}<span class="stw">${esc(x)}</span>${x === s.status ? icon('check', 'sm st-on') : ''}<kbd>${(i + 1) % 10}</kbd></button>`).join('');
    document.body.appendChild(m);
    const r = btn.getBoundingClientRect();
    const h = m.offsetHeight; const w = m.offsetWidth;
    let top = r.bottom + 4;
    if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 4);
    m.style.top = Math.round(top) + 'px';
    m.style.left = Math.round(Math.min(window.innerWidth - w - 8, Math.max(8, r.left - 6))) + 'px';
    btn.setAttribute('aria-expanded', 'true');
    (m.querySelector('[aria-checked="true"]') || m.querySelector('button')).focus();
  }
  function closeStatusMenu(refocus) {
    const m = $('#st-menu');
    if (m) m.remove();
    const f = stMenuFor;
    stMenuFor = null;
    if (f && f.btn && f.btn.isConnected) { f.btn.setAttribute('aria-expanded', 'false'); if (refocus) f.btn.focus({ preventScroll: true }); }
  }
  document.addEventListener('pointerdown', (e) => { if (stMenuFor && !e.target.closest('#st-menu, [data-act="stMenu"]')) closeStatusMenu(); });
  function statusMenuKey(e) {
    const m = $('#st-menu');
    if (!m) return false;
    const items = $$('button', m);
    const i = items.indexOf(document.activeElement);
    if (e.key === 'Escape') { closeStatusMenu(true); return true; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      const n = items.length;
      items[(i + (e.key === 'ArrowDown' ? 1 : -1) + n) % n].focus();
      return true;
    }
    if (/^[0-9]$/.test(e.key) && !e.metaKey && !e.ctrlKey) {
      const k = (+e.key + 9) % 10;
      if (items[k]) items[k].click();
      return true;
    }
    if (e.key === 'Tab') { closeStatusMenu(); return false; }
    return false;
  }

  // ------------------------------------------------------------------ toasts + live changes
  const toasts = $('#toasts');
  const announcer = $('#announce');
  let lastUndo = null;
  // a notification; it may carry one action (Undo), and the pointer holds it open
  function toast(html, text, kind, action) {
    const el = document.createElement('div');
    el.className = 'toast';
    // a status change shows that status's icon; other notices a small glyph
    const tile = SCLS[kind] ? `<span class="tt-ic t-st" aria-hidden="true">${stIcon(SCLS[kind])}</span>`
      : `<span class="tt-ic ${kind === 'Blocked' ? 't-blk' : kind === 'note' ? 't-note' : kind === 'copy' ? 't-copy' : 't-note'}" aria-hidden="true">${icon(kind === 'Blocked' ? 'alert' : kind === 'note' ? 'note' : kind === 'copy' ? 'copy' : 'check', 'sm')}</span>`;
    el.innerHTML = `${tile}<span class="tt-tx">${html}</span>${action ? `<button class="btn sm tt-act" type="button">${esc(action.label)}</button>` : ''}`;
    let timer = null;
    const close = () => {
      clearTimeout(timer);
      if (lastUndo && lastUndo.el === el) lastUndo = null;
      el.classList.add('out'); setTimeout(() => el.remove(), 300);
    };
    const arm = () => { clearTimeout(timer); timer = setTimeout(close, action ? 8000 : 7000); };
    if (action) {
      const run = () => { close(); action.run(); };
      el.querySelector('.tt-act').addEventListener('click', run);
      lastUndo = { el, run };
    }
    el.addEventListener('pointerenter', () => clearTimeout(timer));
    el.addEventListener('pointerleave', arm);
    toasts.appendChild(el);
    while (toasts.children.length > 3) toasts.firstChild.remove();
    arm();
    announcer.textContent = text + (action ? `. ${action.label}: ${KEY}Z` : '');
  }
  function diff(a, b) {
    const old = {}; a.screens.forEach((s) => (old[s.id] = s.status));
    const moved = b.screens.filter((s) => old[s.id] && old[s.id] !== s.status);
    const logs = (b.log || []).slice((a.log || []).length);
    const dOld = {}; a.decisions.forEach((x) => (dOld[x.n] = x.status));
    const decs = b.decisions.filter((x) => dOld[x.n] && dOld[x.n] !== x.status);
    const newDecs = b.decisions.filter((x) => !(x.n in dOld));
    return { moved, logs, decs, newDecs };
  }
  function announce(ch) {
    const byTo = {};
    ch.moved.filter((s) => !mine.has(`s:${s.id}:${s.status}`)).forEach((s) => (byTo[s.status] = byTo[s.status] || []).push(s));
    Object.keys(byTo).forEach((to) => {
      const list = byTo[to];
      if (list.length === 1) toast(`<b>${esc(list[0].name)}</b> <span class="mono">${esc(list[0].id)}</span> → ${esc(to)}`, `${list[0].id} ${list[0].name} moved to ${to}`, to);
      else toast(`<b>${list.length} screens</b> → ${esc(to)}`, `${list.length} screens moved to ${to}`, to);
    });
    ch.newDecs.forEach((x) => toast(`New decision <b>#${x.n}</b>: ${esc(x.topic)}`, `New decision ${x.n}: ${x.topic}`, 'Blocked'));
    ch.decs.filter((x) => !mine.has(`d:${x.n}:${x.status}`)).forEach((x) => toast(`Decision <b>#${x.n}</b> → ${esc(x.status)}`, `Decision ${x.n} is now ${x.status}`));
    if (!ch.moved.length && ch.logs.length) toast(esc(ch.logs[ch.logs.length - 1].text), `Log: ${ch.logs[ch.logs.length - 1].text}`);
    requestAnimationFrame(() => ch.moved.forEach((s) => {
      $$(`.cap[data-id="${CSS.escape(s.id)}"], tr.row[data-id="${CSS.escape(s.id)}"]`).forEach((el) => { el.classList.remove('pulse'); void el.offsetWidth; el.classList.add('pulse'); });
    }));
  }
  // a note got its answer (or failed) while you were looking elsewhere
  function announceNotes(prev, next) {
    const was = {}; prev.forEach((n) => (was[n.id] = { st: n.state, th: ((n.fork || {}).thread || {}).state }));
    // the conversation on screen doesn't need a notice (in the Mac app, the one its chat panel shows)
    const open = NATIVE ? S.panelShown : chatVisible() && curConv() ? String(curConv().id) : null;
    next.forEach((n) => {
      const w = was[n.id];
      if (!w) return;
      const c = convos().find((x) => x.items.includes(n));
      if (!c || (open && open === String(c.id) && !document.hidden)) return;
      const view = { label: 'View', run: () => openChat(c.id) };
      const th = ((n.fork || {}).thread || {}).state;
      if (w.st !== n.state && n.state === 'answered') toast(`${esc((n.fork || {}).to || 'Claude')} answered: <b>${esc(c.title)}</b>`, 'Claude answered', 'note', view);
      else if (w.st !== n.state && n.state === 'failed') toast(`Couldn’t be answered: <b>${esc(c.title)}</b>`, 'A message failed', 'Blocked', view);
      else if (w.th !== th && th === 'waiting' && n.state === 'sending') toast(`${esc((n.fork || {}).to || 'A thread')} is waiting on you: <b>${esc(c.title)}</b>`, 'A thread is waiting on you', 'note', view);
    });
  }
  let refreshing = null;
  async function refresh(announceChanges) {
    if (refreshing) { refreshing.again = refreshing.again || announceChanges || 'quiet'; return; }
    refreshing = {};
    const prev = S.data;
    const prevNotes = S.notes;
    const gen = wsGen;
    const next = await fetchState();
    if (gen !== wsGen) { refreshing = null; return; }     // switched workspace meanwhile
    if (next) S.data = next;
    if (next && !prev && PANEL && (!S.chatConv || (S.chatConv !== 'new' && !curConv()))) S.chatConv = convToOpen();
    render();
    flushReady();
    if (next && announceChanges && prev && !PANEL) { announce(diff(prev, next)); announceNotes(prevNotes, S.notes); }
    const again = refreshing.again;
    refreshing = null;
    if (again) refresh(again === true);
  }
  function updateLive() {
    if (shell && shell.banner && S.data) {
      shell.banner.innerHTML = S.offline ? `<div class="banner" role="status">${icon('alert', 'sm')}<span>Lost the connection to Plots, so this shows the last data. It reconnects on its own.</span></div>` : '';
    }
    reportChrome();
  }
  // the server sends the workspace's signature on connect and whenever its data or notes change
  let es = null;
  let wsGen = 0;          // bumped on every workspace switch, so a late answer for the old one is dropped
  function connect() {
    if (!window.EventSource) return;
    if (es) es.close();
    es = new EventSource(api('/api/events'));
    es.addEventListener('change', (ev) => {
      if (S.data && !S.offline && ev.data === S.sig) return;
      refresh(!!S.data && !S.offline);
    });
    es.addEventListener('workspaces', () => fetchWorkspaces().then(() => { if (S.noWorkspace || !S.data) refresh(false); else render(); }));
    es.addEventListener('code', () => { if (S.code) loadCode(false); });
    // Plots was updated (the engine or this page): reload, keeping the view
    es.addEventListener('build', (ev) => {
      if (!S.build) { S.build = ev.data; return; }
      if (ev.data === S.build) return;
      // not in the middle of something: a search, a note, a menu
      const later = () => {
        const busy = S.pal || S.chatMenu || S.mention || stMenuFor || /INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || '');
        if (busy) setTimeout(later, 2000); else location.reload();
      };
      setTimeout(later, 300);
    });
    es.onopen = () => { S.live = true; if (S.offline) refresh(false); else updateLive(); };
    es.onerror = () => { S.live = false; updateLive(); };
  }
  async function switchWorkspace(id) {
    if (!id || id === WSID) return;
    WSID = id;
    wsGen++;
    if (!NATIVE) { store.set('ws', id); history.replaceState(null, '', `?ws=${encodeURIComponent(id)}${location.hash}`); }
    S.batch = 'All'; S.sessions = null; S.sessionsAsked = false; S.chatEdit = null; S.chatTo = {}; S.chatLocal = {}; S.code = null; S.codeOthers = false;
    S.chatConv = store.get('chatConv:' + id, null); S.ctxDropped = null; S.panelCtx = null; S.histQ = ''; S.histArchived = false;
    closeWsMenu(); closeChatMenu(); closeMention();
    if (S.pal) closePalette(false);
    const gen = wsGen;
    const next = await fetchState();
    if (gen !== wsGen) return;
    S.data = next;
    lastSel = null;
    if ((PANEL || (!NATIVE && S.side === 'chat')) && (!S.chatConv || (S.chatConv !== 'new' && !curConv()))) S.chatConv = convToOpen();
    if (PANEL) render(); else go('#/overview', true);
    connect();
    post('/api/workspaces/' + encodeURIComponent(id) + '/use', {}).catch(() => {});
  }

  // ------------------------------------------------------------------ actions
  async function copyText(v, btn) {
    try { await navigator.clipboard.writeText(v); } catch (e) {
      const t = document.createElement('textarea'); t.value = v; document.body.appendChild(t); t.select(); document.execCommand('copy'); t.remove();
    }
    announcer.textContent = 'Copied';
    // a copy button turns into a check for a moment; anything else (a row, a name) says so in a quiet notice
    if (btn && btn.classList.contains('copy')) {
      if (btn.classList.contains('copied')) return;
      btn.classList.add('copied');
      const old = btn.innerHTML; btn.innerHTML = icon('check', 'sm');
      setTimeout(() => { btn.innerHTML = old; btn.classList.remove('copied'); }, 1200);
    } else toast(`Copied <code>${esc(v.length > 60 ? v.slice(0, 57) + '…' : v)}</code>`, `Copied ${v}`, 'copy');
  }
  function setBatch(b) {
    S.batch = b;
    const { view } = route();
    if (view === 'decisions' || view === 'activity') go('#/overview'); else render();
  }
  function deselect() {
    const { view } = route();
    const prev = route().id;
    go('#/' + view, true);
    const back = prev && ($(`[data-row="${CSS.escape(prev)}"]`) || $(`[data-row="d${CSS.escape(prev)}"]`));
    if (back) back.focus({ preventScroll: true });
  }

  // switch instantly: no element fades on its own schedule while the colours change
  function setTheme(t) {
    if (!THEMES[t]) return;
    const changed = t !== theme;
    theme = t;
    try { localStorage.setItem('plots-theme', JSON.stringify(t)); } catch (e) { /* storage unavailable */ }
    if (changed) {
      const r = document.documentElement;
      r.classList.add('theme-switch');
      applyTheme();
      void r.offsetWidth;
      const done = () => r.classList.remove('theme-switch');
      requestAnimationFrame(() => requestAnimationFrame(done));
      setTimeout(done, 200);          // also when the window is hidden and frames don't run
    } else applyTheme();
    if (S.data && !NATIVE) patch(shell.tb, toolbarHTML(route().view));
  }
  // the workspace menu (in a browser; the Mac app has it at the top of its sidebar)
  function openWsMenu(btn) {
    S.wsMenu = true;
    const r = btn.getBoundingClientRect();
    const m = document.createElement('div');
    m.className = 'menu ws-menu'; m.id = 'ws-menu'; m.setAttribute('role', 'menu');
    m.innerHTML = S.workspaces.map((w) => `<button role="menuitemradio" aria-checked="${w.id === WSID}" data-act="ws" data-v="${esc(w.id)}">${w.id === WSID ? icon('check', 'sm') : '<span class="i sm"></span>'}${wsBadge(w, 'sm')}<span class="ws-mt">${esc(w.name)}</span><span class="ws-mc">${w.total ? `${w.done}/${w.total}` : ''}</span></button>`).join('')
      + '<hr><button role="menuitem" data-act="wsAdd"><span class="i sm"></span><span class="ws-mt">New Workspace…</span></button>';
    document.body.appendChild(m);
    m.style.top = Math.round(r.bottom + 4) + 'px';
    m.style.left = Math.round(Math.max(8, r.left)) + 'px';
    m.style.minWidth = Math.round(r.width) + 'px';
    btn.setAttribute('aria-expanded', 'true');
    const first = m.querySelector('[aria-checked="true"]') || m.querySelector('button');
    if (first) first.focus();
  }
  function closeWsMenu() {
    S.wsMenu = false;
    const m = $('#ws-menu'); if (m) m.remove();
    const b = $('.ws-btn'); if (b) b.setAttribute('aria-expanded', 'false');
  }
  document.addEventListener('pointerdown', (e) => { if (S.wsMenu && !e.target.closest('#ws-menu, .ws-btn')) closeWsMenu(); });
  async function addWorkspace() {
    const name = window.prompt('Name of the new workspace (one per project):');
    if (!name || !name.trim()) return;
    const root = window.prompt('The project folder Claude Code works in (optional, a full path):', '') || null;
    try {
      const r = await fetch('/api/workspaces', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Plots': '1' }, body: JSON.stringify({ name: name.trim(), root }) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Could not add the workspace');
      await fetchWorkspaces();
      switchWorkspace(j.workspace.id);
    } catch (err) { toast(esc(err.message), err.message, 'Blocked'); }
  }
  function openThemeMenu(btn) {
    S.themeMenu = true;
    const r = btn.getBoundingClientRect();
    const m = document.createElement('div');
    m.className = 'menu'; m.id = 'theme-menu'; m.setAttribute('role', 'menu');
    m.innerHTML = Object.keys(THEMES).map((k) => `<button role="menuitemradio" aria-checked="${theme === k}" data-act="setTheme" data-v="${k}">${theme === k ? icon('check', 'sm') : '<span class="i sm"></span>'}${icon(k === 'light' ? 'sun' : k === 'dark' ? 'moon' : 'halfcircle', 'sm')}<span>${THEMES[k]}</span></button>`).join('');
    document.body.appendChild(m);
    m.style.top = Math.round(r.bottom + 6) + 'px';
    m.style.left = Math.round(Math.min(window.innerWidth - m.offsetWidth - 8, r.left)) + 'px';
    btn.setAttribute('aria-expanded', 'true');
    const first = m.querySelector('[aria-checked="true"]') || m.querySelector('button');
    if (first) first.focus();
  }
  function closeThemeMenu() {
    S.themeMenu = false;
    const m = $('#theme-menu'); if (m) m.remove();
    const b = $('.theme-btn'); if (b) b.setAttribute('aria-expanded', 'false');
  }
  document.addEventListener('pointerdown', (e) => { if (S.themeMenu && !e.target.closest('#theme-menu, .theme-btn')) closeThemeMenu(); });

  document.addEventListener('click', (e) => {
    const a = e.target.closest('[data-act]');
    if (!a) {
      // links inside the app close the peeking sidebar
      if (S.peek && e.target.closest('.sb a')) { S.peek = false; applySidebar(); }
      return;
    }
    const act = a.dataset.act;
    const { view } = route();
    switch (act) {
      case 'open':
        e.preventDefault();
        // in the Mac app's chat panel a screen opens in the page beside it
        if (PANEL) { native({ type: 'navigate', hash: '#/screens/' + a.dataset.id }); break; }
        if (a.classList.contains('cap')) S.focusCap = a.dataset.id;
        go('#/screens/' + a.dataset.id);
        break;
      case 'select': {
        e.preventDefault();
        go('#/screens/' + a.dataset.id, true);
        // a click anywhere on the row gives the list the keyboard, like a table view
        const rb = !detailsCover() && $(`.rb[data-row="${CSS.escape(a.dataset.id)}"]`);
        if (rb) rb.focus({ preventScroll: true });
        break;
      }
      case 'selectDec':
        go('#/decisions/' + a.dataset.n, true);
        break;
      case 'deselect': deselect(); break;
      case 'batch': if (S.peek) { S.peek = false; applySidebar(); } setBatch(a.dataset.v); break;
      case 'sidebar': toggleSidebar(); break;
      case 'peekClose': if (S.side === 'chat') setSide('views'); else { S.peek = false; applySidebar(); } break;
      case 'palette': openPalette(); break;
      case 'theme': if (S.themeMenu) closeThemeMenu(); else openThemeMenu(a); break;
      case 'setTheme': setTheme(a.dataset.v); closeThemeMenu(); break;
      case 'palClose': closePalette(); break;
      case 'palRun': runPalette(+a.dataset.i); break;
      case 'ovTab': S.ovTab = a.dataset.v; render(); break;
      case 'range': S.range = a.dataset.v === 'all' ? 'all' : +a.dataset.v; store.set('range', S.range); render(); break;
      case 'mapBy': S.mapBy = a.dataset.v; store.set('mapBy', S.mapBy); render(); break;
      case 'filterStatus': S.fStatus = a.dataset.v; S.fMenu = ''; S.q = ''; go('#/screens'); break;
      case 'filterMenu': S.fMenu = a.dataset.v; S.fStatus = ''; S.q = ''; go('#/screens'); break;
      case 'clearFilters': S.q = ''; S.fStatus = ''; S.fMenu = ''; S.batch = 'All'; render(); break;
      case 'sort': {
        const k = a.dataset.k;
        S.sort = S.sort.key === k ? { key: k, dir: -S.sort.dir } : { key: k, dir: k === 'updated' || k === 'findings' ? -1 : 1 };
        render();
        break;
      }
      case 'group': S.group = !S.group; render(); break;
      case 'dFilter': S.dFilter = a.dataset.v; render(); break;
      case 'aFilter': S.aFilter = a.dataset.v; render(); break;
      case 'stMenu':
        e.preventDefault();
        if (stMenuFor && stMenuFor.btn === a) closeStatusMenu(); else openStatusMenu(a, a.dataset.id);
        break;
      case 'stPick': {
        const f = stMenuFor;
        closeStatusMenu(true);
        if (f) changeStatus(f.id, a.dataset.v);
        break;
      }
      case 'stNext': changeStatus(a.dataset.id, a.dataset.v); break;
      case 'codeTab': S.codeTab = a.dataset.v; store.set('codeTab', S.codeTab); render(); break;
      case 'codeOthers': S.codeOthers = !S.codeOthers; render(); break;
      case 'codeRefresh': loadCode(true); break;
      case 'reveal':
        // a worktree's folder: shown in Finder by the Mac app; in a browser its path is copied
        if (NATIVE) native({ type: 'reveal', path: a.dataset.v }); else copyText(a.dataset.v, a.classList.contains('crow') ? a.querySelector('.cr-t') : a);
        break;
      case 'askFolder': native({ type: 'askFolders', folders: [a.dataset.v] }); setTimeout(() => loadCode(true), 1500); break;
      case 'copy': copyText(a.dataset.v, a); break;
      case 'pop': case 'chatOpen': e.preventDefault(); openChat(); break;
      case 'note': noteOp(a); break;
      case 'sideViews': if (S.side === 'views') toggleSidebar(); else setSide('views'); break;
      case 'sideChat': if (S.side === 'chat') setSide('views'); else openChat(); break;
      case 'chatNew': newChat(); break;
      case 'chatNewAbout': newChat({ about: true }); break;
      case 'chatNewThread': newChat({ to: 'new' }); break;
      case 'chatPick': pickConv(a.dataset.v); break;
      case 'chatCtxDrop': { const x = chatContext(); S.ctxDropped = x ? x.key : null; render(); const t = $('#chat-msg'); if (t) t.focus(); break; }
      case 'chatCtxAdd': S.ctxDropped = null; closeChatMenu(); render(); break;
      case 'chatHistArchived': S.histArchived = !S.histArchived; S.histQ = ''; { const b = $('[data-act="chatHistory"]'); closeChatMenu(); if (b) openChatMenu('history', b); } break;
      case 'chatOpenThread': closeChatMenu(); if (/^https?:\/\//i.test(a.dataset.v || '')) window.open(a.dataset.v, '_blank', 'noopener'); break;
      case 'chatOpenFork': closeChatMenu(); Notes.open(+a.dataset.v, 'desktop').then(() => toast('Opening the fork in Claude', 'Opening the fork in Claude', 'note')).catch((err) => toast(esc(err.message), err.message, 'Blocked')); break;
      case 'chatSend': chatSend(); break;
      case 'chatStop': chatStop(); break;
      case 'chatCompose': case 'chatTitle': case 'chatHistory': case 'chatPlus': case 'chatTo': {
        const kind = { chatCompose: 'compose', chatTitle: 'title', chatHistory: 'history', chatPlus: 'plus', chatTo: 'to' }[act];
        if (S.chatMenu === kind) closeChatMenu(); else openChatMenu(kind, a);
        break;
      }
      case 'chatAt': insertTrigger('@'); break;
      case 'chatInsert': closeChatMenu(); insertTrigger(a.dataset.v); break;
      case 'chatMentionPick': pickMention(+a.dataset.i); break;
      case 'chatLocal': {
        const k = (curConv() || { id: 'new' }).id;
        S.chatLocal[k] = !S.chatLocal[k];
        closeChatMenu(); render();
        break;
      }
      case 'chatPickTo': {
        const c = curConv();
        S.chatTo[c ? String(c.id) : 'new'] = a.dataset.v;
        closeChatMenu(); render();
        const t = $('#chat-msg'); if (t) t.focus();
        break;
      }
      case 'chatSuggest': {
        const t = $('#chat-msg');
        if (t) { t.value = SUGGEST[+a.dataset.i][2]; S.drafts[t.dataset.draft] = t.value; saveDrafts(); growTA(t); syncSend(); t.focus(); }
        break;
      }
      case 'chatRename': {
        closeChatMenu();
        const c = curConv();
        if (!c) break;
        const name = window.prompt('Name this conversation:', c.title);
        if (name != null) Notes.act(c.root.id, 'title', name).catch((err) => toast(esc(err.message), err.message, 'Blocked'));
        break;
      }
      case 'chatArchive': {
        closeChatMenu();
        const c = curConv();
        if (!c) break;
        const op = a.dataset.v;
        Notes.act(c.root.id, op).then(() => {
          if (op === 'archive') {
            toast(`Archived <b>${esc(c.title)}</b>`, `Archived ${c.title}`, 'note', { label: 'Undo', run: () => Notes.act(c.root.id, 'unarchive').then(() => pickConv(c.id)) });
            S.chatConv = convToOpen(); saveConv(); render();
          }
        }).catch((err) => toast(esc(err.message), err.message, 'Blocked'));
        break;
      }
      case 'chatEditCancel': {
        const was = S.chatEdit;
        S.chatEdit = null;
        render();
        if (was) Notes.act(was, 'send').catch(() => {});   // leaving the edit sends the message as it was
        break;
      }
      case 'chatUndo': {
        const s = S.data.screens.find((x) => x.id === a.dataset.id);
        if (s) undo(`/api/screen/${s.id}`, a.dataset.v, `s:${s.id}:${a.dataset.v}`, `<b>${esc(s.name)}</b> is back to ${esc(a.dataset.v)}`, `${s.name} is back to ${a.dataset.v}`, a.dataset.v);
        break;
      }
      case 'selectDecGo': e.preventDefault(); if (PANEL) native({ type: 'navigate', hash: '#/decisions/' + a.dataset.n }); else go('#/decisions/' + a.dataset.n); break;
      case 'wsMenu': if (S.wsMenu) closeWsMenu(); else openWsMenu(a); break;
      case 'ws': switchWorkspace(a.dataset.v); break;
      case 'wsAdd': closeWsMenu(); if (NATIVE) native({ type: 'newWorkspace' }); else addWorkspace(); break;
      case 'saveNote': saveNote(a); break;
      case 'dConfirm': answerDecision(a, true); break;
      case 'dSend': answerDecision(a, false); break;
      case 'retry': refresh(false); break;
      default: break;
    }
    if (view !== route().view && S.peek) { S.peek = false; applySidebar(); }
  });

  document.addEventListener('change', (e) => {
    const a = e.target.closest('[data-act]');
    if (!a) return;
    const act = a.dataset.act;
    if (act === 'fStatus' || act === 'fMenu') { S[act] = a.value; render(); }
    else if (act === 'batchSel') { S.batch = a.value; render(); }
    else if (act === 'repo') { S.repo = a.value; store.set('repo', S.repo); render(); }
    else if (act === 'setStatus') setStatus(a);
  });

  document.addEventListener('input', (e) => {
    const t = e.target;
    if (t.id === 'palq') { S.palQ = t.value; S.palI = 0; renderPalette(); return; }
    if (t.dataset && t.dataset.act === 'q') { S.q = t.value; render(); return; }
    if (t.dataset && t.dataset.draft) {
      S.drafts[t.dataset.draft] = t.value;
      saveDrafts();
      if (!/^(msg|chat:)/.test(t.dataset.draft)) setHint(t.dataset.draft, 'Draft, not sent yet.');
    }
  });

  function moveSel(list, cur, delta, key) {
    if (!list.length) return null;
    let i = list.indexOf(cur);
    if (key === 'Home') i = 0;
    else if (key === 'End') i = list.length - 1;
    else i = i < 0 ? 0 : Math.max(0, Math.min(list.length - 1, i + delta));
    return list[i];
  }

  document.addEventListener('keydown', (e) => {
    const k = e.key;
    const mod = e.metaKey || e.ctrlKey;
    const inField = /INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || '');
    // the status menu has the keys while it is open
    if (stMenuFor && statusMenuKey(e)) { e.preventDefault(); return; }
    // palette
    if (S.pal) {
      if (k === 'Escape') { e.preventDefault(); closePalette(); return; }
      if (k === 'ArrowDown' || k === 'ArrowUp') {
        e.preventDefault();
        const n = S.palItems.length;
        if (n) { S.palI = (S.palI + (k === 'ArrowDown' ? 1 : -1) + n) % n; renderPalette(); }
        return;
      }
      if (k === 'Enter') { e.preventDefault(); runPalette(S.palI); return; }
      if (k === 'Tab') { e.preventDefault(); $('#palq') && $('#palq').focus(); return; }
      return;
    }
    // in the Mac app's chat panel ⌘0–⌘9 and / are the app's (its menus, its page): leave them alone
    if (PANEL && ((mod && /^[0-9]$/.test(k)) || (k === '/' && !inField))) return;
    const ta = document.activeElement && document.activeElement.tagName === 'TEXTAREA' ? document.activeElement : null;
    if (ta && mod && k === 'Enter') {
      // ⌘↩ sends what was typed (on a decision it sends the answer; it never confirms)
      e.preventDefault();
      const scope = ta.closest('.field, .pop');
      const btn = scope && $('[data-act="sendMsg"], [data-act="saveNote"], [data-act="dSend"]', scope);
      if (btn) btn.click();
      return;
    }
    if ((S.chatMenu || S.mention) && k === 'Escape') { e.preventDefault(); closeChatMenu(); closeMention(); return; }
    if (ta && k === 'Escape') { e.preventDefault(); ta.blur(); return; }
    if (mod && (k === 'k' || k === 'K') && !NATIVE) { e.preventDefault(); openPalette(); return; }
    if (mod && !e.shiftKey && !e.altKey && /^[1-4]$/.test(k) && S.data) { e.preventDefault(); go('#/' + VIEWS[+k - 1]); return; }
    if (mod && !e.shiftKey && !e.altKey && k === '0' && S.data && !NATIVE) { e.preventDefault(); toggleChat(); return; }
    if (mod && !e.shiftKey && (k === 'z' || k === 'Z') && !inField && lastUndo && document.contains(lastUndo.el)) { e.preventDefault(); lastUndo.run(); return; }
    if (!NATIVE && ((e.ctrlKey && e.metaKey && (k === 's' || k === 'S')) || (mod && k === '\\'))) { e.preventDefault(); toggleSidebar(); return; }
    if (S.themeMenu && k === 'Escape') { e.preventDefault(); closeThemeMenu(); return; }
    if (S.wsMenu && k === 'Escape') { e.preventDefault(); closeWsMenu(); const b = $('.ws-btn'); if (b) b.focus(); return; }
    if (k === '/' && !inField && !mod) {
      e.preventDefault();
      const q = $('#q');
      if (q) q.focus(); else openPalette();
      return;
    }
    // S: the status menu of the screen in the details (or of the row with the keyboard)
    if ((k === 's' || k === 'S') && !inField && !mod && !e.altKey) {
      const row = document.activeElement && document.activeElement.closest && document.activeElement.closest('tr.row');
      const btn = $('#st-sel') || (row && $('.st-cell', row));
      if (btn) { e.preventDefault(); openStatusMenu(btn, btn.dataset.id); return; }
    }
    if (k === 'Escape') {
      if (S.peek) { S.peek = false; applySidebar(); return; }
      if (!NATIVE && !PANEL && S.side === 'chat' && shell && shell.win.classList.contains('compact')) { setSide('views'); return; }
      if (document.activeElement && document.activeElement.id === 'q' && S.q) { S.q = ''; render(); return; }
      const { id } = route();
      if (id) { e.preventDefault(); deselect(); }
      return;
    }
    // screen list: ↑ ↓ move the selection
    const el = document.activeElement;
    if (el && el.classList && el.classList.contains('rb') && el.dataset.row && ['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(k)) {
      e.preventDefault();
      const ids = $$('.t-screens .rb').map((b) => b.dataset.row);
      const nx = moveSel(ids, el.dataset.row, k === 'ArrowDown' ? 1 : -1, k);
      if (nx) go('#/screens/' + nx, true);
      const b = nx && $(`[data-row="${CSS.escape(nx)}"]`); if (b) b.focus({ preventScroll: true });
      return;
    }
    if (el && el.classList && el.classList.contains('drow') && ['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(k)) {
      e.preventDefault();
      const ns = $$('.drow').map((b) => b.dataset.n);
      const nx = moveSel(ns, el.dataset.n, k === 'ArrowDown' ? 1 : -1, k);
      if (nx) go('#/decisions/' + nx, true);
      const b = $(`[data-row="d${nx}"]`); if (b) b.focus({ preventScroll: true });
      return;
    }
    if (el && el.id === 'q' && k === 'ArrowDown') {
      const first = $('.t-screens .rb');
      if (first) { e.preventDefault(); first.focus(); }
      return;
    }
    // screen map: arrow keys move between capsules
    const c = el && el.classList && el.classList.contains('cap') ? el : null;
    if (c && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(k)) {
      const caps = $$('.cap');
      const rows = $$('.mcaps');
      const i = caps.indexOf(c);
      let next = null;
      if (k === 'ArrowRight') next = caps[i + 1];
      if (k === 'ArrowLeft') next = caps[i - 1];
      if (k === 'Home') next = caps[0];
      if (k === 'End') next = caps[caps.length - 1];
      if (k === 'ArrowDown' || k === 'ArrowUp') {
        const row = c.parentElement; const ri = rows.indexOf(row); const ci = Array.from(row.children).indexOf(c);
        const target = rows[ri + (k === 'ArrowDown' ? 1 : -1)];
        if (target && target.children.length) next = target.children[Math.min(ci, target.children.length - 1)];
      }
      if (next) { e.preventDefault(); c.tabIndex = -1; next.tabIndex = 0; next.focus({ preventScroll: true }); S.focusCap = next.dataset.id; reveal(next.closest('.mrow') || next, false); }
    }
  });

  // drag (or arrow keys on) the divider to resize the details pane
  function setInspW(w, save) {
    S.inspW = Math.round(Math.max(320, Math.min(560, w)));
    const sp = $('.split');
    if (sp) sp.style.setProperty('--insp-w', S.inspW + 'px');
    const h = $('.split-handle');
    if (h) h.setAttribute('aria-valuenow', S.inspW);
    if (save) store.set('inspW', S.inspW);
  }
  document.addEventListener('pointerdown', (e) => {
    const h = e.target.closest && e.target.closest('.split-handle');
    if (!h) return;
    e.preventDefault();
    const sp = h.closest('.split');
    const right = sp.getBoundingClientRect().right;
    h.setPointerCapture(e.pointerId);
    sp.classList.add('resizing');
    const move = (ev) => setInspW(right - ev.clientX - 7, false);
    const up = () => { h.removeEventListener('pointermove', move); sp.classList.remove('resizing'); setInspW(S.inspW, true); };
    h.addEventListener('pointermove', move);
    h.addEventListener('pointerup', up, { once: true });
    h.addEventListener('pointercancel', up, { once: true });
  });
  document.addEventListener('dblclick', (e) => { if (e.target.closest && e.target.closest('.split-handle')) setInspW(384, true); });
  document.addEventListener('keydown', (e) => {
    if (!(e.target.classList && e.target.classList.contains('split-handle'))) return;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); setInspW(S.inspW + (e.key === 'ArrowLeft' ? 16 : -16), true); }
  });

  window.addEventListener('hashchange', () => { hideTip(); render(); });
  const onMQ = () => { applySidebar(); hideTip(); };
  [mqCompact, mqPhone, mqNarrow].forEach((mq) => { if (mq.addEventListener) mq.addEventListener('change', onMQ); else mq.addListener(onMQ); });

  // ------------------------------------------------------------------ Mac app
  const readyQ = [];
  const whenReady = (f) => { if (S.data) f(); else readyQ.push(f); };
  function flushReady() { if (S.data && readyQ.length) readyQ.splice(0).forEach((f) => { try { f(); } catch (e) { console.error(e); } }); }
  // the app's sidebar, toolbar, search field and menus call these
  window.Plots = {
    view: (v) => { if (VIEWS.includes(v) && S.data) go('#/' + v); },
    batch: (b) => { if (S.data && (b === 'All' || S.data.batches.includes(b))) setBatch(b); },
    sidebar: () => toggleSidebar(),
    search: () => openPalette(),
    find: () => { const q = $('#q'); if (q) q.focus(); else openPalette(); },
    palette: (q) => { if (!S.data) return; if (!S.pal) openPalette(true); S.palQ = String(q || ''); S.palI = 0; renderPalette(); },
    paletteKey: (k) => {
      if (!S.pal) return;
      const n = (S.palItems || []).length;
      if (k === 'Escape') closePalette(false);
      else if (k === 'Enter') runPalette(S.palI);
      else if ((k === 'ArrowDown' || k === 'ArrowUp') && n) { S.palI = (S.palI + (k === 'ArrowDown' ? 1 : -1) + n) % n; renderPalette(); }
    },
    // Chat: the app's ✦ and menus call these on the page (openChat, newChat) and on its chat panel (?panel=chat),
    // maybe before the page has its data: then they run once it has
    chat: (id) => whenReady(() => openChat(id == null || id === '' ? null : id)),
    newChat: () => whenReady(() => newChat()),
    toggleChat: () => whenReady(() => toggleChat()),
    focusChat: () => whenReady(() => focusChat()),
    // the panel: what the page shows (screen:<id> or decision:<n>), and whether the panel is on screen
    context: (k) => { const v = k ? String(k) : null; if (v === S.panelCtx) return; S.panelCtx = v; if (S.ctxDropped && S.ctxDropped !== v) S.ctxDropped = null; if (PANEL) render(); },
    visible: (v) => { S.panelVisible = !!v; if (S.panelVisible) markConvSeen(curConv()); else { closeChatMenu(); closeMention(); } },
    // the page: open what the panel links to (a screen or a decision chip), and which conversation the panel shows
    go: (hash) => whenReady(() => { if (/^#\/(overview|screens|decisions|activity)(\/|$)/.test(String(hash || ''))) go(String(hash)); }),
    panelConv: (id) => { S.panelShown = id ? String(id) : null; },
    // the app's sidebar slides: the page's breakpoints stand still and it rearranges once when it stops
    hold: (on) => holdLayout(!!on),
    toast: (text) => toast(esc(text), text, 'note'),
    theme: (t) => setTheme(t),
    exportXlsx: () => { location.href = api('/api/export'); },
    reload: () => refresh(false),
    chrome: () => { lastChrome = ''; reportChrome(); },
    workspace: (id) => switchWorkspace(id),
    workspaces: () => fetchWorkspaces().then(() => { lastChrome = ''; reportChrome(); }),
    notes: {
      send: (text, opts) => Notes.send(text, opts || {}).then((n) => n.id),
      act: (id, op, text) => Notes.act(id, op, text).then(() => true),
      open: (id, where) => Notes.open(id, where),
      seen: () => Notes.seen(),
      sessions: () => Notes.sessions().then(() => true),
      refresh: () => refresh(false).then(() => true),
    },
  };

  // ------------------------------------------------------------------ boot
  (async () => {
    const [data] = await Promise.all([fetchState(), fetchWorkspaces()]);
    S.data = data;
    if (!NATIVE && WSID) store.set('ws', WSID);
    // the conversation the chat had open here last time (else the one that needs you)
    if (OWN_CHAT && WSID) S.chatConv = store.get('chatConv:' + WSID, null);
    if ((PANEL || S.side === 'chat') && S.data && (!S.chatConv || (S.chatConv !== 'new' && !curConv()))) S.chatConv = convToOpen();
    render();
    flushReady();
    connect();
    // relative times ("10 min ago") stay current
    setInterval(() => { if (S.data && !S.pal && !document.hidden) render(); }, 60000);
  })();
})();
