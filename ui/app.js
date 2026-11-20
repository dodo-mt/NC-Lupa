// Lupa – UI. Volá Python cez window.pywebview.api.*
'use strict';

const $ = (id) => document.getElementById(id);

const state = {
  meta: null,
  types: {},           // kľúč typu -> {bg, fg, label, order}
  typeKeys: [],
  tree: [],
  openCust: new Set(),
  openJobs: new Set(),
  openDirs: new Set(), // "jobId|rel_path"
  positions: {},       // jobId -> [pozície]
  sel: null,           // vybraná zákazka/priečinok {job, rel}
  // filtre
  q: '',
  owner: '',
  typesOn: new Set(),
  scope: 'job',        // 'job' | 'all'
  // výsledok
  files: [],
  total: 0,
  limit: 0,
  view: [],            // zoradené riadky, ako sú zobrazené
  sortKey: 'ftype',
  sortDir: 1,
  selFile: null,
};

let api;
let reqSeq = 0;

// --- pomocné ---------------------------------------------------------------
const ICON_CHEVRON = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>';

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Názov s vyznačenými hľadanými slovami
function highlight(name) {
  const terms = state.q.split(/\s+/).filter(Boolean);
  if (!terms.length) return esc(name);
  const re = new RegExp(terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'gi');
  let out = '';
  let last = 0;
  for (const m of name.matchAll(re)) {
    out += esc(name.slice(last, m.index)) + '<mark>' + esc(m[0]) + '</mark>';
    last = m.index + m[0].length;
  }
  return out + esc(name.slice(last));
}

function fmtDate(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function fmtSize(b) {
  if (b == null) return '';
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${Math.round(b / 1024)} kB`;
  if (b < 1024 * 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1).replace('.', ',')} MB`;
  return `${(b / 1024 / 1024 / 1024).toFixed(1).replace('.', ',')} GB`;
}

function badge(key) {
  const t = state.types[key] || state.types.OTH;
  return `<span class="badge" style="background:${t.bg};color:${t.fg}">${esc(key)}</span>`;
}

function plural(n) {
  if (n === 1) return 'súbor';
  if (n >= 2 && n <= 4) return 'súbory';
  return 'súborov';
}

let toastTimer;
function toast(msg) {
  const el = $('toast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 5000);
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// --- strom -----------------------------------------------------------------
function findJob(id) {
  for (const c of state.tree) for (const j of c.jobs) if (j.id === id) return { cust: c, job: j };
  return null;
}

// Z plochého zoznamu rel_path postaví vnorený strom priečinkov
function buildDirTree(positions) {
  const root = { children: [] };
  const byRel = { '': root };
  for (const p of positions) {
    const node = { ...p, children: [] };
    byRel[p.rel_path] = node;
    const parentRel = p.rel_path.includes('\\') ? p.rel_path.slice(0, p.rel_path.lastIndexOf('\\')) : '';
    (byRel[parentRel] || root).children.push(node);
  }
  return root.children;
}

function isSelNode(jobId, rel) {
  return state.scope === 'job' && state.sel && state.sel.job === jobId && state.sel.rel === rel;
}

function renderTree() {
  const out = [];
  for (const c of state.tree) {
    const open = state.openCust.has(c.id);
    out.push(`<div class="node cust${open ? ' open' : ''}" data-cust="${c.id}" style="padding-left:6px">
      <span class="tw">${ICON_CHEVRON}</span><span class="lbl">${esc(c.name)}</span><span class="num">${c.jobs.length}</span></div>`);
    if (!open) continue;
    for (const j of c.jobs) {
      const jOpen = state.openJobs.has(j.id);
      out.push(`<div class="node job${jOpen ? ' open' : ''}${isSelNode(j.id, '') ? ' sel' : ''}" data-job="${j.id}" style="padding-left:22px">
        <span class="tw">${j.subdirs ? ICON_CHEVRON : ''}</span><span class="lbl">${esc(j.name)}</span></div>`);
      if (jOpen && state.positions[j.id]) renderDirs(out, j.id, buildDirTree(state.positions[j.id]), 2);
    }
  }
  $('tree').innerHTML = out.join('');
}

function renderDirs(out, jobId, nodes, depth) {
  for (const n of nodes) {
    const open = state.openDirs.has(`${jobId}|${n.rel_path}`);
    out.push(`<div class="node dir${open ? ' open' : ''}${isSelNode(jobId, n.rel_path) ? ' sel' : ''}" data-job="${jobId}" data-rel="${esc(n.rel_path)}" style="padding-left:${6 + depth * 16}px">
      <span class="tw">${n.children.length ? ICON_CHEVRON : ''}</span><span class="lbl">${esc(n.name)}</span>${n.files ? `<span class="num">${n.files}</span>` : ''}</div>`);
    if (open) renderDirs(out, jobId, n.children, depth + 1);
  }
}

async function ensurePositions(jobId) {
  if (!state.positions[jobId]) state.positions[jobId] = await api.get_positions(jobId);
}

async function onTreeClick(e) {
  const node = e.target.closest('.node');
  if (!node) return;
  const onTwisty = !!e.target.closest('.tw');

  if (node.dataset.cust) {
    const id = Number(node.dataset.cust);
    state.openCust.has(id) ? state.openCust.delete(id) : state.openCust.add(id);
    renderTree();
    return;
  }

  const jobId = Number(node.dataset.job);
  const rel = node.dataset.rel ?? '';
  const isJob = node.classList.contains('job');
  const set = isJob ? state.openJobs : state.openDirs;
  const key = isJob ? jobId : `${jobId}|${rel}`;

  // klik na šípku = len rozbaliť/zbaliť; klik na názov = vybrať (+ rozbaliť), druhý klik zbalí
  if (onTwisty || isSelNode(jobId, rel)) {
    set.has(key) ? set.delete(key) : set.add(key);
  } else {
    set.add(key);
  }
  if (state.openJobs.has(jobId)) await ensurePositions(jobId);
  if (!onTwisty) await selectNode(jobId, rel);
  renderTree();
}

// Vyberie zákazku/priečinok a prepne rozsah na „Aktuálna zákazka“
async function selectNode(jobId, rel) {
  state.sel = { job: jobId, rel };
  state.scope = 'job';
  state.selFile = null;
  renderScope();
  await refresh();
  $('tableWrap').scrollTop = 0;
}

// Z výsledku „Celé L:\“ skočí na zákazku v strome
async function gotoJob(jobId, rel) {
  const f = findJob(jobId);
  if (!f) return;
  state.openCust.add(f.cust.id);
  state.openJobs.add(jobId);
  await ensurePositions(jobId);
  // rozbaliť cestu k priečinku
  if (rel) {
    const parts = rel.split('\\');
    for (let i = 1; i < parts.length; i++) state.openDirs.add(`${jobId}|${parts.slice(0, i).join('\\')}`);
  }
  const keepFile = state.selFile;
  await selectNode(jobId, rel || '');
  renderTree();
  const node = $('tree').querySelector('.node.sel');
  if (node) node.scrollIntoView({ block: 'center' });
  if (keepFile && state.files.some((x) => x.id === keepFile)) selectFile(keepFile, true);
}

// --- filtre ----------------------------------------------------------------
function renderChips() {
  $('chips').innerHTML = state.typeKeys.map((k) => {
    const t = state.types[k];
    const on = state.typesOn.has(k);
    const style = on ? `background:${t.bg};color:${t.fg};border-color:${t.fg}` : '';
    return `<button type="button" class="chip" data-type="${k}" aria-pressed="${on}" style="${style}" title="${esc(t.label)} – Ctrl+klik: len tento typ">${esc(k)}</button>`;
  }).join('');
}

function renderScope() {
  $('scopeJob').classList.toggle('on', state.scope === 'job');
  $('scopeAll').classList.toggle('on', state.scope === 'all');
}

function selectedTypes() {
  // všetky zapnuté = bez filtra
  return state.typesOn.size === state.typeKeys.length ? null : [...state.typesOn];
}

// --- zoznam súborov --------------------------------------------------------
async function refresh() {
  const seq = ++reqSeq;
  const types = selectedTypes();
  let res;
  if (types && types.length === 0) {
    res = { rows: [], total: 0, limit: 0 };
  } else {
    res = await api.search({
      q: state.q,
      owner: state.owner,
      types,
      scope: state.scope,
      job_id: state.sel ? state.sel.job : null,
      rel: state.sel ? state.sel.rel : '',
    });
  }
  if (seq !== reqSeq) return; // medzitým prišla novšia požiadavka
  state.files = res.rows;
  state.total = res.total;
  state.limit = res.limit;
  if (!state.files.some((x) => x.id === state.selFile)) state.selFile = null;
  renderHead();
  renderFiles();
  renderDetail();
}

function renderHead() {
  const all = state.scope === 'all';
  const f = state.sel ? findJob(state.sel.job) : null;
  let crumb = '';
  let heading = '';
  if (all) {
    crumb = `Celé ${state.meta.root}`;
    heading = state.q ? `Hľadanie „${state.q}“` : 'Všetky súbory';
  } else if (f) {
    const rel = state.sel.rel;
    crumb = `${f.cust.name} › ${f.job.name}${rel ? ' › ' + rel.split('\\').join(' › ') : ''}`;
    heading = rel ? rel.split('\\').pop() : f.job.name;
  } else {
    heading = 'Vyber zákazku';
  }
  $('crumb').textContent = crumb;
  $('heading').textContent = heading;

  const n = state.total;
  let cnt = '';
  if (all || state.sel) {
    cnt = `${n} ${plural(n)}`;
    if (n > state.files.length) cnt += ` · zobrazených ${state.files.length} najnovších`;
  }
  $('count').textContent = cnt;
  document.querySelector('th.c-folder').textContent = all ? 'Zákazka / priečinok' : 'Priečinok';
}

function sortedFiles() {
  const k = state.sortKey;
  const dir = state.sortDir;
  const typeOrder = (t) => (state.types[t] ? state.types[t].order : 99);
  const loc = (x) => (state.scope === 'all' ? `${x.job}\\${x.folder}` : x.folder);
  return [...state.files].sort((a, b) => {
    let r;
    if (k === 'ftype') r = typeOrder(a.ftype) - typeOrder(b.ftype);
    else if (k === 'size' || k === 'created' || k === 'modified') r = (a[k] || 0) - (b[k] || 0);
    else if (k === 'folder') r = loc(a).localeCompare(loc(b), 'sk', { numeric: true, sensitivity: 'base' });
    else r = String(a[k] || '').localeCompare(String(b[k] || ''), 'sk', { numeric: true, sensitivity: 'base' });
    if (r === 0 && k !== 'name') r = a.name.localeCompare(b.name, 'sk', { numeric: true, sensitivity: 'base' });
    return r * dir;
  });
}

function renderFiles() {
  const files = sortedFiles();
  state.view = files;
  const all = state.scope === 'all';
  $('rows').innerHTML = files.map((f) => {
    const loc = all ? (f.folder ? `${f.job} \\ ${f.folder}` : f.job) : f.folder;
    const locTitle = all ? `${f.customer} \\ ${f.job}${f.folder ? ' \\ ' + f.folder : ''}` : f.folder;
    return `<tr data-id="${f.id}"${f.id === state.selFile ? ' class="sel"' : ''}>
    <td class="c-type">${badge(f.ftype)}</td>
    <td class="c-name" title="${esc(f.name)}">${highlight(f.name)}</td>
    <td class="c-folder" title="${esc(locTitle)}">${esc(loc)}</td>
    <td class="c-owner">${esc(f.owner)}</td>
    <td class="c-date">${fmtDate(f.created)}</td>
    <td class="c-date">${fmtDate(f.modified)}</td>
    <td class="c-size">${fmtSize(f.size)}</td></tr>`;
  }).join('');

  let empty = '';
  if (!files.length) {
    if (state.scope === 'job' && !state.sel) empty = 'Vľavo vyber zákazku alebo prepni na „Celé L:\\“.';
    else if (state.typesOn.size === 0) empty = 'Nie je zapnutý žiadny typ súboru.';
    else if (state.q || state.owner || selectedTypes()) empty = 'Nič sa nenašlo. Skús zmeniť hľadanie alebo filtre.';
    else empty = 'V tomto priečinku nie sú žiadne súbory.';
  }
  $('empty').textContent = empty;
  $('empty').hidden = !!files.length;

  for (const th of document.querySelectorAll('.files th')) {
    th.classList.toggle('asc', th.dataset.sort === state.sortKey && state.sortDir === 1);
    th.classList.toggle('desc', th.dataset.sort === state.sortKey && state.sortDir === -1);
  }
}

function selectFile(id, scroll) {
  state.selFile = id;
  for (const tr of $('rows').children) tr.classList.toggle('sel', Number(tr.dataset.id) === id);
  if (scroll) {
    const tr = $('rows').querySelector(`tr[data-id="${id}"]`);
    if (tr) tr.scrollIntoView({ block: 'nearest' });
  }
  renderDetail();
}

// --- detail ----------------------------------------------------------------
function renderDetail() {
  const f = state.files.find((x) => x.id === state.selFile);
  if (!f) {
    $('detail').innerHTML = '<div class="detail-empty">Klikni na súbor pre detail.<br>Dvojklik ho otvorí.</div>';
    return;
  }
  const t = state.types[f.ftype] || state.types.OTH;
  $('detail').innerHTML = `
    <div class="preview" id="preview" title="Dvojklik otvorí súbor">
      <span class="pv-msg">Načítavam náhľad…</span>
    </div>
    <div>${badge(f.ftype)} <span style="color:var(--muted);font-size:13px">${esc(t.label)}</span><span class="pv-pages" id="pvPages"></span></div>
    <div>
      <div class="d-name">${esc(f.name)}</div>
      <div class="d-path">${esc(f.path)}</div>
    </div>
    <dl class="d-meta">
      <dt>Zákazník</dt><dd>${esc(f.customer)}</dd>
      <dt>Zákazka</dt><dd>${esc(f.job)}${f.folder ? ' \\ ' + esc(f.folder) : ''}</dd>
      <dt>Vlastník</dt><dd><strong>${esc(f.owner)}</strong></dd>
      <dt>Vytvorený</dt><dd>${fmtDate(f.created)}</dd>
      <dt>Zmenený</dt><dd>${fmtDate(f.modified)}</dd>
      <dt>Veľkosť</dt><dd>${fmtSize(f.size)}</dd>
    </dl>
    <div class="d-btns">
      <button type="button" class="btn primary" id="btnOpen">Otvoriť</button>
      <button type="button" class="btn" id="btnFolder">Otvoriť priečinok</button>
      ${state.scope === 'all' ? '<button type="button" class="btn" id="btnGoto" style="flex-basis:100%">Prejsť na zákazku</button>' : ''}
    </div>`;
  $('btnOpen').onclick = () => openFile(f.id);
  $('preview').ondblclick = () => openFile(f.id);
  $('btnFolder').onclick = () => openFolder(f.id);
  if ($('btnGoto')) $('btnGoto').onclick = () => gotoJob(f.job_id, f.folder);
  loadThumb(f.id);
}

// Náhľad – s krátkym oneskorením, aby pri listovaní šípkami nevznikali zbytočné požiadavky
let thumbSeq = 0;
let thumbTimer;
function loadThumb(id) {
  const seq = ++thumbSeq;
  clearTimeout(thumbTimer);
  thumbTimer = setTimeout(async () => {
    const r = await api.get_thumb(id);
    const box = $('preview');
    if (seq !== thumbSeq || !box) return;
    if (!r.ok) {
      box.innerHTML = `<span class="pv-msg">${esc(r.error)}</span>`;
      return;
    }
    if (r.kind === 'text') {
      box.classList.add('pv-textbox');
      box.innerHTML = `<pre class="pv-text">${esc(r.text)}${r.more ? '\n…' : ''}</pre>`;
      return;
    }
    box.innerHTML = `<img src="${r.src}" alt="Náhľad" class="pv-${r.kind}">`;
    if (r.pages > 1) $('pvPages').textContent = ` · ${r.pages} strán`;
  }, 120);
}

async function openFile(id) {
  const r = await api.open_file(id);
  if (!r.ok) toast(r.error);
}

async function openFolder(id) {
  const r = await api.open_folder(id);
  if (!r.ok) toast(r.error);
}

// --- udalosti --------------------------------------------------------------
function bind() {
  $('tree').addEventListener('click', onTreeClick);

  // hľadanie
  const runSearch = debounce(() => refresh(), 200);
  $('q').addEventListener('input', () => {
    state.q = $('q').value.trim();
    $('qClear').hidden = !$('q').value;
    runSearch();
  });
  $('q').addEventListener('keydown', (e) => {
    if (e.key === 'Escape') clearSearch();
  });
  $('qClear').addEventListener('click', () => { clearSearch(); $('q').focus(); });

  // filtre
  $('owner').addEventListener('change', () => { state.owner = $('owner').value; refresh(); });
  $('chips').addEventListener('click', (e) => {
    const b = e.target.closest('.chip');
    if (!b) return;
    const k = b.dataset.type;
    if (e.ctrlKey) {
      state.typesOn = new Set([k]);
    } else if (state.typesOn.has(k)) {
      state.typesOn.delete(k);
    } else {
      state.typesOn.add(k);
    }
    renderChips();
    refresh();
  });
  $('chipsAll').addEventListener('click', () => {
    state.typesOn = new Set(state.typeKeys);
    renderChips();
    refresh();
  });
  for (const b of document.querySelectorAll('.seg button')) {
    b.addEventListener('click', () => {
      if (state.scope === b.dataset.scope) return;
      state.scope = b.dataset.scope;
      renderScope();
      renderTree();
      refresh();
    });
  }

  // zoznam
  $('rows').addEventListener('click', (e) => {
    const tr = e.target.closest('tr');
    if (tr) selectFile(Number(tr.dataset.id));
  });
  $('rows').addEventListener('dblclick', (e) => {
    const tr = e.target.closest('tr');
    if (tr) openFile(Number(tr.dataset.id));
  });
  document.querySelector('.files thead').addEventListener('click', (e) => {
    const th = e.target.closest('th');
    if (!th) return;
    const k = th.dataset.sort;
    if (state.sortKey === k) state.sortDir = -state.sortDir;
    else { state.sortKey = k; state.sortDir = (k === 'modified' || k === 'created' || k === 'size') ? -1 : 1; }
    renderFiles();
  });

  // klávesnica: Ctrl+F = hľadanie, šípky = pohyb v zozname, Enter = otvoriť
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && (e.key === 'f' || e.key === 'F')) {
      e.preventDefault();
      $('q').focus();
      $('q').select();
      return;
    }
    if (e.target.tagName === 'SELECT') return;
    if (!state.view.length) return;
    const i = state.view.findIndex((f) => f.id === state.selFile);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const n = e.key === 'ArrowDown' ? Math.min(i + 1, state.view.length - 1) : Math.max(i - 1, 0);
      selectFile(state.view[n].id, true);
    } else if (e.key === 'Enter' && i >= 0) {
      openFile(state.view[i].id);
    }
  });
}

// --- ťahateľné panely (šírka sa pamätá v localStorage) ---------------------
const PANES = {
  tree: { sel: '.tree-pane', min: 180, max: 600 },
  detail: { sel: '.detail-pane', min: 280, max: 1100 },
};

function setPaneWidth(name, w) {
  const p = PANES[name];
  w = Math.max(p.min, Math.min(p.max, Math.round(w)));
  document.querySelector(p.sel).style.width = `${w}px`;
  return w;
}

function bindResizers() {
  for (const name of Object.keys(PANES)) {
    try {
      const saved = Number(localStorage.getItem(`lupa.width.${name}`));
      if (saved) setPaneWidth(name, saved);
    } catch (e) { /* localStorage nedostupný – nevadí */ }
  }
  for (const r of document.querySelectorAll('.resizer')) {
    const name = r.dataset.pane;
    r.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      r.setPointerCapture(e.pointerId);
      r.classList.add('drag');
      document.body.classList.add('resizing');
      const pane = document.querySelector(PANES[name].sel);
      const startX = e.clientX;
      const startW = pane.getBoundingClientRect().width;
      let w = startW;
      const move = (ev) => {
        const dx = ev.clientX - startX;
        w = setPaneWidth(name, name === 'tree' ? startW + dx : startW - dx);
      };
      const up = () => {
        r.removeEventListener('pointermove', move);
        r.removeEventListener('pointerup', up);
        r.classList.remove('drag');
        document.body.classList.remove('resizing');
        try { localStorage.setItem(`lupa.width.${name}`, String(w)); } catch (e2) { /* nevadí */ }
      };
      r.addEventListener('pointermove', move);
      r.addEventListener('pointerup', up);
    });
    // dvojklik = pôvodná šírka
    r.addEventListener('dblclick', () => {
      const def = name === 'tree' ? 270 : 360;
      setPaneWidth(name, def);
      try { localStorage.removeItem(`lupa.width.${name}`); } catch (e) { /* nevadí */ }
    });
  }
}

function clearSearch() {
  $('q').value = '';
  $('qClear').hidden = true;
  if (state.q) { state.q = ''; refresh(); }
}

async function init() {
  api = window.pywebview.api;
  const meta = await api.get_meta();
  state.meta = meta;
  meta.types.forEach((t, i) => { state.types[t.key] = { ...t, order: i }; });
  state.typeKeys = meta.types.map((t) => t.key);
  state.typesOn = new Set(state.typeKeys);
  $('root').textContent = meta.root;
  $('scopeAll').textContent = `Celé ${meta.root}`;
  renderChips();
  renderScope();
  if (!meta.db_ok) {
    $('scanInfo').textContent = 'Databáza neexistuje';
    $('empty').textContent = `Databáza sa nenašla: ${meta.db} – spusti najprv scanner.py.`;
    return;
  }
  if (meta.last_scan) {
    const s = meta.last_scan;
    $('scanInfo').textContent = `Sken: ${fmtDate(s.finished)}${s.errors ? ` · chyby ${s.errors}` : ''}`;
  }
  const owners = await api.get_owners();
  $('owner').insertAdjacentHTML('beforeend',
    owners.map((o) => `<option value="${esc(o.owner)}">${esc(o.owner)} (${o.n})</option>`).join(''));
  state.tree = await api.get_tree();
  if (state.tree.length === 1) state.openCust.add(state.tree[0].id);
  renderTree();
  renderHead();
  renderFiles();
  $('q').focus();
}

bind();
bindResizers();
window.addEventListener('pywebviewready', init);
