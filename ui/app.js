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
  mode: 'list',        // 'list' | 'gallery'
  similar: null,       // podobné výkresy: {id, name} hľadaného PDF, inak null
  sortBeforeSim: null, // triedenie pred podobnými výkresmi (obnoví sa po zavretí)
};

function lsGet(k, def) {
  try { const v = localStorage.getItem(k); return v === null ? def : v; } catch (e) { return def; }
}
function lsSet(k, v) {
  try { localStorage.setItem(k, v); } catch (e) { /* nevadí */ }
}

let api;
let reqSeq = 0;

// --- pomocné ---------------------------------------------------------------
const ICON_CHEVRON = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6"></path></svg>';

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Názov s vyznačenými hľadanými slovami
function highlight(name) {
  const terms = state.similar ? [] : state.q.split(/\s+/).filter(Boolean);
  if (!terms.length) return esc(name);
  // slovo so * / ? = celý názov, inak časť názvu
  const toRe = (t) => {
    const e = t.replace(/[.+^${}()|[\]\\]/g, '\\$&');
    return /[*?]/.test(t) ? `^${e.replace(/\*/g, '.*').replace(/\?/g, '.')}$` : e.replace(/[*?]/g, '');
  };
  const re = new RegExp(terms.map(toRe).join('|'), 'gi');
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

function findCust(id) {
  return state.tree.find((c) => c.id === id) || null;
}

// Výsledok obsahuje viac zákaziek (Celé L:\ alebo vybraný zákazník) → ukazovať aj zákazku
function multiJob() {
  return !!state.similar || state.scope === 'all' || (state.sel && !state.sel.job);
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

// --- úplnosť ---------------------------------------------------------------
// missing = názvy chýbajúcich položiek (počíta Python podľa config.COMPLETENESS)
function complCheck(missing) {
  return state.meta.completeness.map((name) => ({ name, ok: !missing.includes(name) }));
}

function complStatus(miss) {
  if (!miss.length) return '<span class="st ok" title="Úplné">úplné</span>';
  const txt = miss.length === 1 ? `chýba ${miss[0]}` : `chýba ${miss.length}`;
  return `<span class="st miss" title="Chýba: ${esc(miss.join(', '))}">${esc(txt)}</span>`;
}

// Úplnosť sa ukazuje vždy za celú zákazku – aj pri vybranom podpriečinku
// (model a výkres bývajú v koreni zákazky, NC v podpriečinkoch pozícií).
function renderCompl() {
  const box = $('compl');
  if (state.similar || state.scope !== 'job' || !state.sel) { box.hidden = true; return; }
  if (!state.sel.job) {
    // zákazník: súhrn – koľko zákaziek je úplných
    const c = findCust(state.sel.cust);
    if (!c || !c.jobs.length) { box.hidden = true; return; }
    const ok = c.jobs.filter((j) => !j.missing.length).length;
    const all = ok === c.jobs.length;
    box.hidden = false;
    box.innerHTML = `<span class="${all ? 'y' : 'n'}" title="Úplné zákazky (Model, PDF, CAM, NC, Listy)">${all ? '✓' : '✗'} úplné ${ok}/${c.jobs.length}</span>`;
    return;
  }
  const f = findJob(state.sel.job);
  if (!f) { box.hidden = true; return; }
  box.hidden = false;
  box.innerHTML = complCheck(f.job.missing).map((c) =>
    `<span class="${c.ok ? 'y' : 'n'}" title="${c.ok ? 'Je' : 'Chýba'}">${c.ok ? '✓' : '✗'} ${esc(c.name)}</span>`).join('');
}

function isSelNode(jobId, rel) {
  return state.scope === 'job' && state.sel && state.sel.job === jobId && state.sel.rel === rel;
}

function isSelCust(custId) {
  return state.scope === 'job' && state.sel && !state.sel.job && state.sel.cust === custId;
}

function renderTree() {
  const out = [];
  for (const c of state.tree) {
    const open = state.openCust.has(c.id);
    out.push(`<div class="node cust${open ? ' open' : ''}${isSelCust(c.id) ? ' sel' : ''}" data-cust="${c.id}" style="padding-left:6px">
      <span class="tw">${ICON_CHEVRON}</span><span class="lbl">${esc(c.name)}</span><span class="num">${c.jobs.length}</span></div>`);
    if (!open) continue;
    for (const j of c.jobs) {
      const jOpen = state.openJobs.has(j.id);
      out.push(`<div class="node job${jOpen ? ' open' : ''}${isSelNode(j.id, '') ? ' sel' : ''}" data-job="${j.id}" style="padding-left:22px">
        <span class="tw">${j.subdirs ? ICON_CHEVRON : ''}</span><span class="lbl">${esc(j.name)}</span>${complStatus(j.missing)}</div>`);
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
    // klik na šípku = rozbaliť/zbaliť; klik na názov = vybrať zákazníka (+ rozbaliť), druhý klik zbalí
    const id = Number(node.dataset.cust);
    if (onTwisty || isSelCust(id)) {
      state.openCust.has(id) ? state.openCust.delete(id) : state.openCust.add(id);
    } else {
      state.openCust.add(id);
    }
    if (!onTwisty) await selectCustomer(id);
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
  const f = findJob(jobId);
  await applySelection({ cust: f ? f.cust.id : null, job: jobId, rel });
}

// Vyberie zákazníka – zoznam ukáže súbory všetkých jeho zákaziek
async function selectCustomer(custId) {
  await applySelection({ cust: custId, job: null, rel: '' });
}

async function applySelection(sel) {
  leaveSimilar();
  state.sel = sel;
  state.scope = 'job';
  state.selFile = null;
  renderScope();
  await refresh();
  $('tableWrap').scrollTop = 0;
  $('galleryWrap').scrollTop = 0;
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

// --- kontextové menu stromu (pravé tlačidlo) --------------------------------
async function expandCustomer(custId) {
  const c = findCust(custId);
  if (!c) return;
  state.openCust.add(custId);
  const all = await api.get_customer_positions(custId); // naraz pre všetky zákazky
  for (const j of c.jobs) {
    state.positions[j.id] = all[String(j.id)] || [];
    state.openJobs.add(j.id);
    for (const p of state.positions[j.id]) state.openDirs.add(`${j.id}|${p.rel_path}`);
  }
}

function collapseCustomer(custId) {
  const c = findCust(custId);
  if (!c) return;
  state.openCust.delete(custId);
  for (const j of c.jobs) collapseUnder(j.id, '');
}

async function expandUnder(jobId, rel) {
  state.openJobs.add(jobId);
  await ensurePositions(jobId);
  for (const p of state.positions[jobId]) {
    if (!rel || p.rel_path === rel || p.rel_path.startsWith(rel + '\\')) state.openDirs.add(`${jobId}|${p.rel_path}`);
  }
}

function collapseUnder(jobId, rel) {
  if (!rel) state.openJobs.delete(jobId);
  const prefix = `${jobId}|${rel}`;
  for (const k of [...state.openDirs]) {
    if (!rel ? k.startsWith(`${jobId}|`) : (k === prefix || k.startsWith(prefix + '\\'))) state.openDirs.delete(k);
  }
}

function hideCtx() {
  $('ctx').hidden = true;
}

function onTreeContext(e) {
  const node = e.target.closest('.node');
  e.preventDefault();
  const items = [];   // [text, akcia] alebo '-' / {title}
  if (node && node.dataset.cust) {
    const c = findCust(Number(node.dataset.cust));
    items.push({ title: c.name });
    items.push(['Rozbaliť všetky zákazky', async () => { await expandCustomer(c.id); }]);
    items.push(['Zbaliť', () => collapseCustomer(c.id)]);
    items.push('-');
    items.push(['Otvoriť priečinok', () => openPath(c.path)]);
  } else if (node) {
    const jobId = Number(node.dataset.job);
    const rel = node.dataset.rel ?? '';
    const f = findJob(jobId);
    const pos = rel ? (state.positions[jobId] || []).find((p) => p.rel_path === rel) : null;
    items.push({ title: rel ? `${f.job.name} \\ ${rel}` : f.job.name });
    items.push(['Rozbaliť všetko pod', async () => { await expandUnder(jobId, rel); }]);
    items.push(['Zbaliť všetko pod', () => collapseUnder(jobId, rel)]);
    items.push('-');
    items.push(['Otvoriť priečinok', () => openPath(pos ? pos.path : f.job.path)]);
  }
  if (items.length) items.push('-');
  items.push(['Zbaliť celý strom', () => {
    state.openCust.clear();
    state.openJobs.clear();
    state.openDirs.clear();
  }]);

  const menu = $('ctx');
  const actions = [];
  menu.innerHTML = items.map((it) => {
    if (it === '-') return '<hr>';
    if (it.title) return `<div class="ctx-title">${esc(it.title)}</div>`;
    actions.push(it[1]);
    return `<button type="button" role="menuitem" data-i="${actions.length - 1}">${esc(it[0])}</button>`;
  }).join('');
  menu.onclick = async (ev) => {
    const b = ev.target.closest('button');
    if (!b) return;
    hideCtx();
    await actions[Number(b.dataset.i)]();
    renderTree();
  };
  menu.hidden = false;
  // umiestniť k myši, ale nevyliezť z okna
  const r = menu.getBoundingClientRect();
  menu.style.left = `${Math.min(e.clientX, window.innerWidth - r.width - 4)}px`;
  menu.style.top = `${Math.min(e.clientY, window.innerHeight - r.height - 4)}px`;
}

async function openPath(path) {
  const r = await api.open_folder(null, path);
  if (!r.ok) toast(r.error);
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
  $('scopeJob').textContent = state.sel && !state.sel.job ? 'Aktuálny zákazník' : 'Aktuálna zákazka';
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
  if (state.similar) {
    res = await api.similar(state.similar.id, state.owner);
    if (seq !== reqSeq) return;
    if (!res.ok) {
      toast(res.error);
      leaveSimilar();
      return refresh();
    }
    res.total = res.rows.length;
    res.limit = 0;
  } else if (types && types.length === 0) {
    res = { rows: [], total: 0, limit: 0 };
  } else {
    res = await api.search({
      q: state.q,
      owner: state.owner,
      types,
      scope: state.scope,
      customer_id: state.sel ? state.sel.cust : null,
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
  const f = state.sel && state.sel.job ? findJob(state.sel.job) : null;
  const cust = state.sel && !state.sel.job ? findCust(state.sel.cust) : null;
  let crumb = '';
  let heading = '';
  if (state.similar) {
    crumb = 'Podobné výkresy';
    heading = `Podobné ako <span class="mono h-q">${esc(state.similar.name)}</span>` +
      '<button type="button" class="iconbtn h-close" id="simClose" title="Zavrieť podobné výkresy (Esc)" aria-label="Zavrieť podobné výkresy">' +
      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"></path></svg></button>';
  } else if (all) {
    crumb = `Celé ${state.meta.root}`;
    heading = esc(state.q ? `Hľadanie „${state.q}“` : 'Všetky súbory');
  } else if (cust) {
    crumb = 'Zákazník';
    const n = cust.jobs.length;
    heading = esc(cust.name) + `<span class="h-sub"> · ${n} ${n === 1 ? 'zákazka' : n >= 2 && n <= 4 ? 'zákazky' : 'zákaziek'}</span>`;
  } else if (f) {
    // nadpis = zákazka, podpriečinok menším sivým písmom za lomkou
    const rel = state.sel.rel;
    crumb = f.cust.name;
    heading = esc(f.job.name) + (rel ? `<span class="h-sub"> / ${esc(rel.split('\\').join(' \\ '))}</span>` : '');
  } else {
    heading = 'Vyber zákazku';
  }
  $('crumb').textContent = crumb;
  $('heading').innerHTML = heading;
  if ($('simClose')) $('simClose').onclick = () => exitSimilar();
  renderCompl();

  const n = state.total;
  let cnt = '';
  if (state.similar) {
    const k = n - 1;
    cnt = k ? `${k} ${k === 1 ? 'podobný výkres' : k >= 2 && k <= 4 ? 'podobné výkresy' : 'podobných výkresov'}`
      : 'Nenašiel sa žiadny podobný výkres';
    if (state.owner) cnt += ` · vlastník ${state.owner}`;
  } else if (all || state.sel) {
    cnt = `${n} ${plural(n)}`;
    if (n > state.files.length) cnt += ` · zobrazených ${state.files.length} najnovších`;
  }
  $('count').textContent = cnt;
  // meniť len text, nie celý obsah (v hlavičke je úchyt na ťahanie)
  document.querySelector('th.c-folder').firstChild.nodeValue = multiJob() ? 'Zákazka / priečinok' : 'Priečinok';
}

function sortedFiles() {
  const k = state.sortKey;
  const dir = state.sortDir;
  const typeOrder = (t) => (state.types[t] ? state.types[t].order : 99);
  const loc = (x) => (multiJob() ? `${x.job}\\${x.folder}` : x.folder);
  return [...state.files].sort((a, b) => {
    let r;
    if (k === 'ftype') r = typeOrder(a.ftype) - typeOrder(b.ftype);
    else if (k === 'size' || k === 'created' || k === 'modified' || k === 'sim') r = (a[k] || 0) - (b[k] || 0);
    else if (k === 'folder') r = loc(a).localeCompare(loc(b), 'sk', { numeric: true, sensitivity: 'base' });
    else r = String(a[k] || '').localeCompare(String(b[k] || ''), 'sk', { numeric: true, sensitivity: 'base' });
    if (r === 0 && k !== 'name') r = a.name.localeCompare(b.name, 'sk', { numeric: true, sensitivity: 'base' });
    return r * dir;
  });
}

function renderFiles() {
  const files = sortedFiles();
  state.view = files;
  renderEmpty(files);
  if (state.mode === 'gallery') {
    renderGallery(files);
    $('rows').innerHTML = '';
    return;
  }
  $('gallery').innerHTML = '';
  const all = multiJob();
  $('files').classList.toggle('sim-on', !!state.similar);
  applyCols();
  $('rows').innerHTML = files.map((f) => {
    const loc = all ? (f.folder ? `${f.job} \\ ${f.folder}` : f.job) : f.folder;
    const locTitle = all ? `${f.customer} \\ ${f.job}${f.folder ? ' \\ ' + f.folder : ''}` : f.folder;
    return `<tr data-id="${f.id}"${f.id === state.selFile ? ' class="sel"' : ''}>
    <td class="c-type">${badge(f.ftype)}</td>
    <td class="c-sim">${simCell(f)}</td>
    <td class="c-name" title="${esc(f.name)}">${highlight(f.name)}</td>
    <td class="c-folder" title="${esc(locTitle)}">${esc(loc)}</td>
    <td class="c-owner">${esc(f.owner)}</td>
    <td class="c-date">${fmtDate(f.created)}</td>
    <td class="c-date">${fmtDate(f.modified)}</td>
    <td class="c-size">${fmtSize(f.size)}</td></tr>`;
  }).join('');

  for (const th of document.querySelectorAll('.files th')) {
    th.classList.toggle('asc', th.dataset.sort === state.sortKey && state.sortDir === 1);
    th.classList.toggle('desc', th.dataset.sort === state.sortKey && state.sortDir === -1);
  }
}

// --- podobné výkresy -------------------------------------------------------
function simPct(f) {
  return Math.round((f.sim || 0) * 100);
}

function simCell(f) {
  if (!state.similar) return '';
  if (f.query) return '<span class="sim-q">hľadaný</span>';
  const p = simPct(f);
  return `<span class="simbar" aria-hidden="true"><i style="width:${p}%"></i></span><span class="sim-v">${p} %</span>`;
}

function simTag(f) {
  return f.query ? '<span class="sim-q">hľadaný</span>' : `<span class="g-sim">${simPct(f)} %</span>`;
}

async function startSimilar(f) {
  if (!state.similar) state.sortBeforeSim = { key: state.sortKey, dir: state.sortDir };
  state.similar = { id: f.id, name: f.name };
  state.sortKey = 'sim';
  state.sortDir = -1;
  state.selFile = f.id;
  $('galSortSim').hidden = false;
  syncGalSort();
  $('count').textContent = 'Hľadám podobné výkresy…';
  await refresh();
  $('tableWrap').scrollTop = 0;
  $('galleryWrap').scrollTop = 0;
}

// Ukončí režim podobných výkresov (bez obnovenia zoznamu)
function leaveSimilar() {
  if (!state.similar) return;
  state.similar = null;
  if (state.sortBeforeSim) {
    state.sortKey = state.sortBeforeSim.key;
    state.sortDir = state.sortBeforeSim.dir;
  }
  $('galSortSim').hidden = true;
  syncGalSort();
}

function exitSimilar() {
  if (!state.similar) return;
  const keep = state.similar.id;   // späť na výkres, z ktorého sa hľadalo
  leaveSimilar();
  state.selFile = keep;
  refresh();
}

function renderEmpty(files) {
  let empty = '';
  if (!files.length) {
    if (state.scope === 'job' && !state.sel) empty = `Vľavo vyber zákazníka alebo zákazku, alebo prepni na „${$('scopeAll').textContent}“.`;
    else if (state.typesOn.size === 0) empty = 'Nie je zapnutý žiadny typ – klikni hore na štítky typov, ktoré chceš vidieť.';
    else if (state.q || state.owner || selectedTypes()) empty = 'Nič sa nenašlo. Skús zmeniť hľadanie alebo filtre.';
    else empty = 'V tomto priečinku nie sú žiadne súbory.';
  }
  $('empty').textContent = empty;
  $('empty').hidden = !!files.length;
}

// --- galéria ---------------------------------------------------------------
const thumbCache = new Map();   // id -> výsledok get_thumb('s'); obmedzená veľkosť
const THUMB_CACHE_MAX = 300;
const THUMB_PARALLEL = 4;
let thumbQueue = [];
let thumbBusy = 0;
let galObserver = null;
let galGen = 0;                 // generácia vykreslenia – staré požiadavky sa zahodia

function renderGallery(files) {
  galGen++;
  thumbQueue = [];
  if (galObserver) galObserver.disconnect();
  const all = multiJob();
  $('gallery').innerHTML = files.map((f) => {
    const sub = all ? `${f.job}${f.folder ? ' \\ ' + f.folder : ''}` : (f.folder || '');
    const date = fmtDate(f.modified).slice(0, 10);
    return `<div class="card${f.id === state.selFile ? ' sel' : ''}" data-id="${f.id}" title="${esc(f.name)}">
      <div class="g-thumb" data-id="${f.id}"><span class="pv-msg"></span></div>
      <div class="g-name">${badge(f.ftype)}<span>${highlight(f.name)}</span></div>
      <div class="g-sub">${state.similar ? simTag(f) + ' · ' : ''}${esc(sub)}${sub ? ' · ' : ''}${date} · ${esc(f.owner)}</div>
    </div>`;
  }).join('');

  galObserver = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      galObserver.unobserve(e.target);
      queueThumb(e.target);
    }
  }, { root: $('galleryWrap'), rootMargin: '400px 0px' });
  for (const el of $('gallery').querySelectorAll('.g-thumb')) galObserver.observe(el);
}

function paintThumb(el, r) {
  if (!r.ok) {
    el.innerHTML = '<span class="pv-msg">Bez náhľadu</span>';
  } else if (r.kind === 'text') {
    el.classList.add('text');
    el.innerHTML = `<pre>${esc(r.text)}</pre>`;
  } else {
    el.innerHTML = `<img src="${r.src}" alt="" class="pv-${r.kind}" loading="lazy">`;
  }
}

function queueThumb(el) {
  const id = Number(el.dataset.id);
  if (thumbCache.has(id)) { paintThumb(el, thumbCache.get(id)); return; }
  el.firstElementChild.textContent = 'Načítavam…';
  thumbQueue.push({ el, id, gen: galGen });
  pumpThumbs();
}

function pumpThumbs() {
  while (thumbBusy < THUMB_PARALLEL && thumbQueue.length) {
    const job = thumbQueue.shift();
    if (job.gen !== galGen || !job.el.isConnected) continue;
    thumbBusy++;
    api.get_thumb(job.id, 's').then((r) => {
      thumbCache.set(job.id, r);
      if (thumbCache.size > THUMB_CACHE_MAX) thumbCache.delete(thumbCache.keys().next().value);
      if (job.gen === galGen && job.el.isConnected) paintThumb(job.el, r);
    }).finally(() => { thumbBusy--; pumpThumbs(); });
  }
}

function setMode(mode) {
  state.mode = mode;
  lsSet('lupa.mode', mode);
  $('modeList').classList.toggle('on', mode === 'list');
  $('modeGallery').classList.toggle('on', mode === 'gallery');
  $('tableWrap').hidden = mode !== 'list';
  $('galleryWrap').hidden = mode !== 'gallery';
  syncGalSort();
  renderFiles();
}

function syncGalSort() {
  const v = `${state.sortKey}:${state.sortDir}`;
  const sel = $('galSort');
  if ([...sel.options].some((o) => o.value === v)) sel.value = v;
}

function setCardSize(px) {
  $('gallery').style.setProperty('--card', `${px}px`);
  $('galSize').value = px;
}

// počet stĺpcov galérie (pre šípky hore/dole)
function galColumns() {
  const cards = $('gallery').children;
  if (cards.length < 2) return 1;
  const top = cards[0].offsetTop;
  let n = 0;
  while (n < cards.length && cards[n].offsetTop === top) n++;
  return Math.max(1, n);
}

function selectFile(id, scroll) {
  state.selFile = id;
  const box = state.mode === 'gallery' ? $('gallery') : $('rows');
  for (const el of box.children) el.classList.toggle('sel', Number(el.dataset.id) === id);
  if (scroll) {
    const el = box.querySelector(`[data-id="${id}"]`);
    if (el) el.scrollIntoView({ block: 'nearest' });
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
      ${state.similar ? `<dt>Podobnosť</dt><dd>${f.query ? 'hľadaný výkres' : `${simPct(f)} %`}</dd>` : ''}
      <dt>Vlastník</dt><dd><strong>${esc(f.owner)}</strong></dd>
      <dt>Vytvorený</dt><dd>${fmtDate(f.created)}</dd>
      <dt>Zmenený</dt><dd>${fmtDate(f.modified)}</dd>
      <dt>Veľkosť</dt><dd>${fmtSize(f.size)}</dd>
    </dl>
    <div class="d-btns">
      <button type="button" class="btn primary" id="btnOpen">Otvoriť</button>
      <button type="button" class="btn" id="btnFolder">Otvoriť priečinok</button>
      ${multiJob() ? '<button type="button" class="btn" id="btnGoto" style="flex-basis:100%">Prejsť na zákazku</button>' : ''}
      ${f.ftype === 'PDF' && !f.query ? `<button type="button" class="btn btn-icon" id="btnSimilar" style="flex-basis:100%" title="Nájde výkresy s podobnými pohľadmi v celom ${esc(state.meta.root)}">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="8" height="8" rx="1"></rect><rect x="13" y="13" width="8" height="8" rx="1"></rect><path d="M15 3h5a1 1 0 0 1 1 1v5M9 21H4a1 1 0 0 1-1-1v-5"></path></svg>
        Podobné výkresy</button>` : ''}
    </div>`;
  $('btnOpen').onclick = () => openFile(f.id);
  $('preview').ondblclick = () => openFile(f.id);
  $('btnFolder').onclick = () => openFolder(f.id);
  if ($('btnGoto')) $('btnGoto').onclick = () => gotoJob(f.job_id, f.folder);
  if ($('btnSimilar')) $('btnSimilar').onclick = () => startSimilar(f);
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
  $('tree').addEventListener('contextmenu', onTreeContext);
  $('treeExpand').addEventListener('click', () => {
    // rozbalí len zákazníkov (zákazky so všetkými priečinkami by pri tisícoch zákaziek boli priveľa)
    state.tree.forEach((c) => state.openCust.add(c.id));
    renderTree();
  });
  $('treeCollapse').addEventListener('click', () => {
    state.openCust.clear();
    state.openJobs.clear();
    state.openDirs.clear();
    renderTree();
  });
  document.addEventListener('mousedown', (e) => { if (!e.target.closest('#ctx')) hideCtx(); });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (!$('ctx').hidden) { hideCtx(); return; }
    if (state.similar && $('ownerDrop').hidden && e.target.id !== 'q') exitSimilar();
  });
  $('tree').addEventListener('scroll', hideCtx);
  window.addEventListener('blur', hideCtx);

  // hľadanie
  const runSearch = debounce(() => refresh(), 200);
  $('q').addEventListener('input', () => {
    state.q = $('q').value.trim();
    $('qClear').hidden = !$('q').value;
    leaveSimilar();
    runSearch();
  });
  $('q').addEventListener('keydown', (e) => {
    if (e.key === 'Escape') clearSearch();
  });
  $('qClear').addEventListener('click', () => { clearSearch(); $('q').focus(); });

  // filtre
  bindOwnerDropdown();
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
  $('chipsNone').addEventListener('click', () => {
    state.typesOn = new Set();
    renderChips();
    refresh();
  });
  for (const b of document.querySelectorAll('.seg button[data-scope]')) {
    b.addEventListener('click', () => {
      if (state.scope === b.dataset.scope && !state.similar) return;
      leaveSimilar();
      state.scope = b.dataset.scope;
      renderScope();
      renderTree();
      refresh();
    });
  }

  // galéria
  for (const b of document.querySelectorAll('.seg.dark button')) {
    b.addEventListener('click', () => setMode(b.dataset.mode));
  }
  $('gallery').addEventListener('click', (e) => {
    const c = e.target.closest('.card');
    if (c) selectFile(Number(c.dataset.id));
  });
  $('gallery').addEventListener('dblclick', (e) => {
    const c = e.target.closest('.card');
    if (c) openFile(Number(c.dataset.id));
  });
  $('galSort').addEventListener('change', () => {
    const [k, d] = $('galSort').value.split(':');
    state.sortKey = k;
    state.sortDir = Number(d);
    renderFiles();
  });
  $('galSize').addEventListener('input', () => {
    setCardSize(Number($('galSize').value));
    lsSet('lupa.card', $('galSize').value);
  });

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
    if (!th || colDragged || e.target.closest('.col-grip')) return;
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
    if (!$('ownerDrop').hidden) return; // rozbalený výber vlastníka má vlastné klávesy
    if (e.target.tagName === 'SELECT' || (e.target.tagName === 'INPUT' && e.target.type === 'range')) return;
    if (!state.view.length) return;
    const i = state.view.findIndex((f) => f.id === state.selFile);
    const gal = state.mode === 'gallery';
    const step = { ArrowDown: gal ? galColumns() : 1, ArrowUp: gal ? -galColumns() : -1 };
    if (gal) { step.ArrowRight = 1; step.ArrowLeft = -1; }
    // v poli hľadania nechať šípky vľavo/vpravo na pohyb kurzora
    if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && e.target.id === 'q') return;
    if (step[e.key]) {
      e.preventDefault();
      const n = i < 0 ? 0 : Math.max(0, Math.min(state.view.length - 1, i + step[e.key]));
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
  if (name === 'tree') {
    // šírka stromu je CSS premenná – podľa nej sa zarovnáva aj hľadanie a lišta filtrov
    document.documentElement.style.setProperty('--tree-w', `${w}px`);
  } else {
    document.querySelector(p.sel).style.width = `${w}px`;
  }
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

// --- ťahateľné stĺpce tabuľky ---------------------------------------------
// Názov nemá pevnú šírku – vypĺňa voľné miesto; jeho ťahaním sa mení minimum.
const COL_DEFAULTS = { ftype: 64, sim: 120, name: 300, folder: 200, owner: 100, created: 130, modified: 130, size: 84 };
const COL_MIN = 40;
let colW = { ...COL_DEFAULTS };
let colDragged = false; // po ťahaní potlačiť klik = triedenie

function applyCols() {
  let sum = 0;
  for (const th of document.querySelectorAll('.files th')) {
    const k = th.dataset.sort;
    if (k !== 'sim' || state.similar) sum += colW[k];
    th.style.width = k === 'name' ? '' : `${colW[k]}px`;
  }
  document.querySelector('table.files').style.minWidth = `${sum}px`;
}

function saveCols() {
  try { localStorage.setItem('lupa.cols', JSON.stringify(colW)); } catch (e) { /* nevadí */ }
}

function bindColumns() {
  try {
    const saved = JSON.parse(localStorage.getItem('lupa.cols') || 'null');
    if (saved) colW = { ...COL_DEFAULTS, ...saved };
  } catch (e) { /* nevadí */ }

  for (const th of document.querySelectorAll('.files th')) {
    const k = th.dataset.sort;
    const grip = document.createElement('span');
    grip.className = 'col-grip';
    grip.title = 'Ťahaním zmeníš šírku, dvojklik = predvolená';
    th.appendChild(grip);

    grip.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      e.stopPropagation();
      grip.setPointerCapture(e.pointerId);
      grip.classList.add('drag');
      document.body.classList.add('resizing');
      const startX = e.clientX;
      const startW = th.getBoundingClientRect().width;
      colDragged = false;
      const move = (ev) => {
        const dx = ev.clientX - startX;
        if (Math.abs(dx) > 2) colDragged = true;
        colW[k] = Math.max(COL_MIN, Math.round(startW + dx));
        applyCols();
      };
      const up = () => {
        grip.removeEventListener('pointermove', move);
        grip.removeEventListener('pointerup', up);
        grip.classList.remove('drag');
        document.body.classList.remove('resizing');
        saveCols();
        setTimeout(() => { colDragged = false; }, 0);
      };
      grip.addEventListener('pointermove', move);
      grip.addEventListener('pointerup', up);
    });
    grip.addEventListener('click', (e) => e.stopPropagation());
    grip.addEventListener('dblclick', (e) => {
      e.stopPropagation();
      colW[k] = COL_DEFAULTS[k];
      applyCols();
      saveCols();
    });
  }
  applyCols();
}

// --- výber vlastníka (vlastné rozbaľovacie menu v štýle Lupy) ---------------
let ownerCur = 0;   // index zvýraznenej položky (klávesnica)

function ownerItems() {
  const f = $('ownerFilter').value.trim().toLowerCase();
  const list = (state.owners || []).filter((o) => !f || o.owner.toLowerCase().includes(f));
  return f ? list : [{ owner: '', n: null }, ...list];   // „Všetci“ len bez filtra
}

function renderOwnerList() {
  const items = ownerItems();
  ownerCur = Math.max(0, Math.min(ownerCur, items.length - 1));
  const chk = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"></path></svg>';
  $('ownerList').innerHTML = items.length ? items.map((o, i) => {
    const sel = o.owner === state.owner;
    const row = `<button type="button" role="option" aria-selected="${sel}" class="dd-item${sel ? ' sel' : ''}${i === ownerCur ? ' cur' : ''}" data-i="${i}">
      <span class="chk">${sel ? chk : ''}</span><span class="nm">${o.owner ? esc(o.owner) : 'Všetci'}</span>${o.n != null ? `<span class="cnt">${o.n.toLocaleString('sk-SK')}</span>` : ''}</button>`;
    return row + (!o.owner && items.length > 1 ? '<div class="dd-sep"></div>' : '');
  }).join('') : '<div class="dd-empty">Nikto taký nie je.</div>';
  const cur = $('ownerList').querySelector('.dd-item.cur');
  if (cur) cur.scrollIntoView({ block: 'nearest' });
}

function openOwnerDrop() {
  const chip = $('ownerChip');
  const r = chip.getBoundingClientRect();
  const dd = $('ownerDrop');
  $('ownerFilter').value = '';
  const items = ownerItems();
  ownerCur = Math.max(0, items.findIndex((o) => o.owner === state.owner));
  renderOwnerList();
  dd.hidden = false;
  dd.style.left = `${Math.min(r.left, window.innerWidth - dd.offsetWidth - 8)}px`;
  dd.style.top = `${r.bottom + 4}px`;
  chip.setAttribute('aria-expanded', 'true');
  $('ownerFilter').focus();
}

function closeOwnerDrop() {
  $('ownerDrop').hidden = true;
  $('ownerChip').setAttribute('aria-expanded', 'false');
}

function pickOwner(owner) {
  closeOwnerDrop();
  if (owner === state.owner) return;
  state.owner = owner;
  $('ownerValue').textContent = owner || 'Všetci';
  $('ownerChip').classList.toggle('active', !!owner);
  refresh();
}

function bindOwnerDropdown() {
  $('ownerChip').addEventListener('click', () => {
    $('ownerDrop').hidden ? openOwnerDrop() : closeOwnerDrop();
  });
  $('ownerList').addEventListener('click', (e) => {
    const b = e.target.closest('.dd-item');
    if (b) pickOwner(ownerItems()[Number(b.dataset.i)].owner);
  });
  $('ownerFilter').addEventListener('input', () => { ownerCur = 0; renderOwnerList(); });
  $('ownerFilter').addEventListener('keydown', (e) => {
    const items = ownerItems();
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      ownerCur = Math.max(0, Math.min(items.length - 1, ownerCur + (e.key === 'ArrowDown' ? 1 : -1)));
      renderOwnerList();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (items[ownerCur]) pickOwner(items[ownerCur].owner);
    } else if (e.key === 'Escape') {
      closeOwnerDrop();
      $('ownerChip').focus();
    }
  });
  document.addEventListener('mousedown', (e) => {
    if (!$('ownerDrop').hidden && !e.target.closest('#ownerDrop, #ownerChip')) closeOwnerDrop();
  });
  window.addEventListener('blur', closeOwnerDrop);
  window.addEventListener('resize', closeOwnerDrop);
}

// --- stavový riadok ---------------------------------------------------------
function renderStatus() {
  const m = state.meta;
  const c = m.counts;
  const num = (n) => n.toLocaleString('sk-SK');
  $('stLeft').innerHTML = `<span class="mono">${esc(m.root)}</span>` +
    (c ? ` · ${num(c.customers)} zákazníkov · ${num(c.jobs)} zákaziek · ${num(c.files)} súborov` : '') +
    (c && c.pdfs ? ` · <span title="Výkresy (PDF) s odtlačkom pre Podobné výkresy – dopočítavajú sa postupne pri skenoch">odtlačky ${num(c.prints)} / ${num(c.pdfs)}</span>` : '');
  const s = m.last_scan;
  if (!m.db_ok) {
    $('stRight').innerHTML = '<span class="stale">Databáza neexistuje</span>';
  } else if (s) {
    const stale = Date.now() / 1000 - s.finished > m.stale_hours * 3600;
    const txt = `Posledný sken: ${fmtDate(s.finished)}${s.errors ? ` · chyby ${s.errors}` : ''}`;
    $('stRight').innerHTML = stale
      ? `<span class="stale" title="Údaje môžu byť neaktuálne – sken neprebehol viac ako ${m.stale_hours} h">${esc(txt)}</span>`
      : esc(txt);
  }
}

function clearSearch() {
  $('q').value = '';
  $('qClear').hidden = true;
  if (state.q) { state.q = ''; refresh(); }
}

// Chyba pri štarte (napr. DB sa nedá otvoriť) – ukázať v okne, nie nechať prázdne
async function init() {
  try {
    await initApp();
  } catch (e) {
    const msg = (e && (e.message || e.toString())) || 'neznáma chyba';
    $('empty').hidden = false;
    $('empty').textContent = `Lupa sa nepodarilo načítať: ${msg}`;
    $('heading').textContent = 'Chyba';
  }
}

async function initApp() {
  api = window.pywebview.api;
  const meta = await api.get_meta();
  state.meta = meta;
  meta.types.forEach((t, i) => { state.types[t.key] = { ...t, order: i }; });
  state.typeKeys = meta.types.map((t) => t.key);
  state.typesOn = new Set(state.typeKeys);
  // na tlačidle krátko (L:\ ostane L:\, dlhá cesta = posledný priečinok), celá cesta v bublinke
  const root = meta.root.replace(/[\\/]+$/, '');
  $('scopeAll').textContent = `Celé ${root.length <= 3 ? meta.root : root.split(/[\\/]/).pop()}`;
  $('scopeAll').title = `Hľadať v celom ${meta.root}`;
  renderChips();
  renderScope();
  setCardSize(Number(lsGet('lupa.card', 220)));
  setMode(lsGet('lupa.mode', 'list') === 'gallery' ? 'gallery' : 'list');
  renderStatus();
  if (!meta.db_ok) {
    $('empty').textContent = `Databáza sa nenašla: ${meta.db} – spusti najprv scanner.py.`;
    return;
  }
  state.owners = await api.get_owners();
  state.tree = await api.get_tree();
  if (state.tree.length === 1) state.openCust.add(state.tree[0].id);
  renderTree();
  renderHead();
  renderFiles();
  $('q').focus();
}

bind();
bindResizers();
bindColumns();
window.addEventListener('pywebviewready', init);
