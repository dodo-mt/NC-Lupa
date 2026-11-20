// Lupa – UI. Volá Python cez window.pywebview.api.*
'use strict';

const $ = (id) => document.getElementById(id);

const state = {
  meta: null,
  types: {},          // kľúč typu -> {bg, fg, label, order}
  tree: [],
  openCust: new Set(),
  openJobs: new Set(),
  openDirs: new Set(), // "jobId|rel_path"
  positions: {},       // jobId -> [pozície]
  sel: null,           // {job: id, rel: ''}
  files: [],
  sortKey: 'ftype',
  sortDir: 1,
  selFile: null,       // id súboru
};

let api;

// --- pomocné ---------------------------------------------------------------
const ICON_CHEVRON = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>';

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
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

let toastTimer;
function toast(msg) {
  const el = $('toast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 5000);
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

function renderTree() {
  const out = [];
  for (const c of state.tree) {
    const open = state.openCust.has(c.id);
    out.push(`<div class="node cust${open ? ' open' : ''}" data-cust="${c.id}" style="padding-left:6px">
      <span class="tw">${ICON_CHEVRON}</span><span class="lbl">${esc(c.name)}</span><span class="num">${c.jobs.length}</span></div>`);
    if (!open) continue;
    for (const j of c.jobs) {
      const jOpen = state.openJobs.has(j.id);
      const sel = state.sel && state.sel.job === j.id && state.sel.rel === '';
      out.push(`<div class="node job${jOpen ? ' open' : ''}${sel ? ' sel' : ''}" data-job="${j.id}" style="padding-left:22px">
        <span class="tw">${j.subdirs ? ICON_CHEVRON : ''}</span><span class="lbl">${esc(j.name)}</span></div>`);
      if (jOpen && state.positions[j.id]) renderDirs(out, j.id, buildDirTree(state.positions[j.id]), 2);
    }
  }
  $('tree').innerHTML = out.join('');
}

function renderDirs(out, jobId, nodes, depth) {
  for (const n of nodes) {
    const key = `${jobId}|${n.rel_path}`;
    const open = state.openDirs.has(key);
    const sel = state.sel && state.sel.job === jobId && state.sel.rel === n.rel_path;
    out.push(`<div class="node dir${open ? ' open' : ''}${sel ? ' sel' : ''}" data-job="${jobId}" data-rel="${esc(n.rel_path)}" style="padding-left:${6 + depth * 16}px">
      <span class="tw">${n.children.length ? ICON_CHEVRON : ''}</span><span class="lbl">${esc(n.name)}</span>${n.files ? `<span class="num">${n.files}</span>` : ''}</div>`);
    if (open) renderDirs(out, jobId, n.children, depth + 1);
  }
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

  if (node.classList.contains('job')) {
    const wasOpen = state.openJobs.has(jobId);
    const isSel = state.sel && state.sel.job === jobId && state.sel.rel === '';
    // klik na šípku = len rozbaliť/zbaliť; klik na názov = vybrať (+ rozbaliť)
    if (onTwisty || isSel) {
      wasOpen ? state.openJobs.delete(jobId) : state.openJobs.add(jobId);
    } else {
      state.openJobs.add(jobId);
    }
    if (state.openJobs.has(jobId) && !state.positions[jobId]) {
      state.positions[jobId] = await api.get_positions(jobId);
    }
    if (!onTwisty) await select(jobId, '');
    renderTree();
    return;
  }

  // priečinok
  const key = `${jobId}|${rel}`;
  const isSel = state.sel && state.sel.job === jobId && state.sel.rel === rel;
  if (onTwisty || isSel) {
    state.openDirs.has(key) ? state.openDirs.delete(key) : state.openDirs.add(key);
  } else {
    state.openDirs.add(key);
  }
  if (!onTwisty) await select(jobId, rel);
  renderTree();
}

// --- zoznam súborov --------------------------------------------------------
async function select(jobId, rel) {
  state.sel = { job: jobId, rel };
  state.selFile = null;
  state.files = await api.get_files(jobId, rel);
  const f = findJob(jobId);
  $('crumb').textContent = f ? `${f.cust.name} › ${f.job.name}${rel ? ' › ' + rel.split('\\').join(' › ') : ''}` : '';
  $('heading').textContent = rel ? rel.split('\\').pop() : (f ? f.job.name : '');
  renderFiles();
  renderDetail();
  $('tableWrap').scrollTop = 0;
}

function sortedFiles() {
  const k = state.sortKey;
  const dir = state.sortDir;
  const typeOrder = (t) => (state.types[t] ? state.types[t].order : 99);
  return [...state.files].sort((a, b) => {
    let r;
    if (k === 'ftype') r = typeOrder(a.ftype) - typeOrder(b.ftype);
    else if (k === 'size' || k === 'created' || k === 'modified') r = (a[k] || 0) - (b[k] || 0);
    else r = String(a[k] || '').localeCompare(String(b[k] || ''), 'sk', { numeric: true, sensitivity: 'base' });
    if (r === 0 && k !== 'name') r = a.name.localeCompare(b.name, 'sk', { numeric: true, sensitivity: 'base' });
    return r * dir;
  });
}

function renderFiles() {
  const files = sortedFiles();
  state.view = files;
  $('rows').innerHTML = files.map((f) => `<tr data-id="${f.id}"${f.id === state.selFile ? ' class="sel"' : ''}>
    <td class="c-type">${badge(f.ftype)}</td>
    <td class="c-name" title="${esc(f.name)}">${esc(f.name)}</td>
    <td class="c-folder" title="${esc(f.folder)}">${esc(f.folder)}</td>
    <td class="c-owner">${esc(f.owner)}</td>
    <td class="c-date">${fmtDate(f.created)}</td>
    <td class="c-date">${fmtDate(f.modified)}</td>
    <td class="c-size">${fmtSize(f.size)}</td></tr>`).join('');
  $('empty').hidden = !!files.length;
  $('empty').textContent = state.sel ? 'V tomto priečinku nie sú žiadne súbory.' : 'Vľavo vyber zákazku alebo priečinok.';
  $('count').textContent = state.sel ? `${files.length} ${plural(files.length)}` : '';
  for (const th of document.querySelectorAll('.files th')) {
    th.classList.toggle('asc', th.dataset.sort === state.sortKey && state.sortDir === 1);
    th.classList.toggle('desc', th.dataset.sort === state.sortKey && state.sortDir === -1);
  }
}

function plural(n) {
  if (n === 1) return 'súbor';
  if (n >= 2 && n <= 4) return 'súbory';
  return 'súborov';
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
    <div>${badge(f.ftype)} <span style="color:var(--muted);font-size:13px">${esc(t.label)}</span></div>
    <div>
      <div class="d-name">${esc(f.name)}</div>
      <div class="d-path">${esc(f.path)}</div>
    </div>
    <dl class="d-meta">
      <dt>Vlastník</dt><dd><strong>${esc(f.owner)}</strong></dd>
      <dt>Vytvorený</dt><dd>${fmtDate(f.created)}</dd>
      <dt>Zmenený</dt><dd>${fmtDate(f.modified)}</dd>
      <dt>Veľkosť</dt><dd>${fmtSize(f.size)}</dd>
    </dl>
    <div class="d-btns">
      <button type="button" class="btn primary" id="btnOpen">Otvoriť</button>
      <button type="button" class="btn" id="btnFolder">Otvoriť priečinok</button>
    </div>`;
  $('btnOpen').onclick = () => openFile(f.id);
  $('btnFolder').onclick = () => openFolder(f.id);
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

  // šípky hore/dole v zozname, Enter = otvoriť
  document.addEventListener('keydown', (e) => {
    if (!state.view || !state.view.length) return;
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

async function init() {
  api = window.pywebview.api;
  const meta = await api.get_meta();
  state.meta = meta;
  meta.types.forEach((t, i) => { state.types[t.key] = { ...t, order: i }; });
  $('root').textContent = meta.root;
  if (!meta.db_ok) {
    $('scanInfo').textContent = 'Databáza neexistuje';
    $('empty').textContent = `Databáza sa nenašla: ${meta.db}\nSpusti najprv scanner.py.`;
    return;
  }
  if (meta.last_scan) {
    const s = meta.last_scan;
    $('scanInfo').textContent = `Sken: ${fmtDate(s.finished)}${s.errors ? ` · chyby ${s.errors}` : ''}`;
  }
  state.tree = await api.get_tree();
  if (state.tree.length === 1) state.openCust.add(state.tree[0].id);
  renderTree();
}

bind();
window.addEventListener('pywebviewready', init);
