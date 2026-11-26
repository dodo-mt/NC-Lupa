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
  lists: false,        // len CNC listy (config.list_sql)
  odladene: false,     // len odladené programy (priečinok odlad*, odladene.py)
  bezOdl: null,        // strom len so zákazkami BEZ odladeného programu: null = vypnuté, inak počet mesiacov (0 = všetky)
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
const ICON_CHECK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"></path></svg>';

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

// v zozname len dátum (užší stĺpec) – čas je v bublinke a v detaile
function fmtDay(ts) {
  return fmtDate(ts).slice(0, 10);
}

// Vlastník s veľkým začiatočným písmenom (v DB ostáva pôvodný tvar – podľa neho sa filtruje)
function ownerName(o) {
  return o ? o.charAt(0).toUpperCase() + o.slice(1) : '';
}

// Cesta bez koreňa ('L:\100020\009712' -> '100020\009712')
function shortPath(p) {
  const r = state.meta.root.replace(/[\\/]+$/, '') + '\\';
  return p && p.toLowerCase().startsWith(r.toLowerCase()) ? p.slice(r.length) : (p || '');
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

// zákazky zákazníka podľa filtra „bez odladeného programu“ (len zobrazenie stromu): majú NC programy, ale žiadny odladený,
// a (pri zvolenom období) sa v nich menilo za posledných N mesiacov
function treeJobs(c) {
  if (state.bezOdl === null) return c.jobs;
  const od = state.bezOdl ? Date.now() / 1000 - state.bezOdl * 30.44 * 86400 : 0;
  return c.jobs.filter((j) => j.has_nc && !j.odl && (j.changed || 0) >= od);
}

function renderBezOdlBadge() {
  const b = $('bezOdlBadge');
  b.hidden = state.bezOdl === null;
  if (state.bezOdl === null) return;
  b.firstElementChild.textContent = `Bez odladeného · ${state.bezOdl ? `${state.bezOdl} mes.` : 'všetky'}`;
  const n = state.tree.reduce((s, c) => s + treeJobs(c).length, 0);
  b.title = `Strom ukazuje len zákazky s NC programami, ktoré nemajú odladený program (${n}). Klik = vypnúť.`;
}

function setBezOdl(mesiace) {
  state.bezOdl = mesiace;
  renderBezOdlBadge();
  renderTree();
  if (mesiace !== null) {
    const zakaznici = state.tree.filter((c) => treeJobs(c).length).length;
    const zakazky = state.tree.reduce((s, c) => s + treeJobs(c).length, 0);
    toast(`Zákazky bez odladeného programu: ${zakazky} u ${zakaznici} zákazníkov. Strom rozbalíš tlačidlom „Rozbaliť všetkých zákazníkov“.`);
  }
}

function renderTree() {
  const out = [];
  for (const c of state.tree) {
    const jobs = treeJobs(c);
    if (state.bezOdl !== null && !jobs.length) continue;
    const open = state.openCust.has(c.id);
    // zákazník so zákazkami v jednej skupine – otvorený zákazník sa pri rolovaní drží hore (sticky)
    out.push('<div class="cgroup">');
    out.push(`<div class="node cust${open ? ' open' : ''}${isSelCust(c.id) ? ' sel' : ''}" data-cust="${c.id}" style="padding-left:6px">
      <span class="tw">${ICON_CHEVRON}</span><span class="lbl">${esc(c.name)}</span><span class="num">${jobs.length}</span></div>`);
    if (open) {
      for (const j of jobs) {
        const jOpen = state.openJobs.has(j.id);
        out.push(`<div class="node job${jOpen ? ' open' : ''}${isSelNode(j.id, '') ? ' sel' : ''}" data-job="${j.id}" style="padding-left:22px">
          <span class="tw">${j.subdirs ? ICON_CHEVRON : ''}</span><span class="lbl">${esc(j.name)}</span>${j.linked ? `<span class="lk" title="Odkazy .lnk na iné zákazky alebo z iných zákaziek">${ICON_LINK}</span>` : ''}${j.odl ? `<span class="lk odl" title="Zákazka obsahuje ${j.odl} ${j.odl === 1 ? 'odladený NC program' : j.odl >= 2 && j.odl <= 4 ? 'odladené NC programy' : 'odladených NC programov'} (priečinok odladené alebo Zo stroja). Posledný odladený: ${fmtDay(j.odl_cas)}. Klik = vybrať zákazku a ukázať len odladené programy.">${ICON_ODL}</span>` : ''}${complStatus(j.missing)}</div>`);
        if (jOpen && state.positions[j.id]) renderDirs(out, j.id, buildDirTree(state.positions[j.id]), 2);
      }
    }
    out.push('</div>');
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
  if (e.target.closest('.lk.odl')) {            // značka „odladené“: vybrať zákazku a zapnúť filter odladených programov
    state.odladene = true;
    renderListsChip();
  }
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
    // zbalený (aj z prilepenej hlavičky) – ukázať ho, nie nechať strom odrolovaný ďaleko dole
    if (!state.openCust.has(id)) treeNodeEl({ cust: id, job: null, rel: '' })?.scrollIntoView({ block: 'nearest' });
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

// --- strom z klávesnice (keď je fokus v strome – po kliknutí doň) ---------------
// ↑/↓ = posun (súbory sa načítajú s malým oneskorením), ← = zbaliť / na nadradený uzol,
// → = rozbaliť / na prvý podriadený. Ako v Prieskumníkovi.
function nodeSel(node) {
  if (node.dataset.cust) return { cust: Number(node.dataset.cust), job: null, rel: '' };
  const jobId = Number(node.dataset.job);
  const f = findJob(jobId);
  return { cust: f ? f.cust.id : null, job: jobId, rel: node.dataset.rel ?? '' };
}

function treeNodeEl(sel) {
  return [...$('tree').querySelectorAll('.node')].find((n) => {
    if (!sel.job) return Number(n.dataset.cust) === sel.cust;
    return Number(n.dataset.job) === sel.job && (n.dataset.rel ?? '') === sel.rel;
  }) || null;
}

function parentSel(sel) {
  if (!sel.job) return null;
  if (!sel.rel) return { cust: sel.cust, job: null, rel: '' };
  const i = sel.rel.lastIndexOf('\\');
  return { cust: sel.cust, job: sel.job, rel: i < 0 ? '' : sel.rel.slice(0, i) };
}

async function setTreeOpen(sel, open) {
  if (!sel.job) {
    open ? state.openCust.add(sel.cust) : state.openCust.delete(sel.cust);
  } else if (!sel.rel) {
    if (open) { state.openJobs.add(sel.job); await ensurePositions(sel.job); } else state.openJobs.delete(sel.job);
  } else {
    const key = `${sel.job}|${sel.rel}`;
    open ? state.openDirs.add(key) : state.openDirs.delete(key);
  }
}

const loadTreeSel = debounce((sel) => applySelection(sel), 250);

// Presun výberu v strome z klávesnice – hneď zvýrazniť, súbory načítať až po zastavení
function moveTreeTo(node) {
  if (!node) return;
  const sel = nodeSel(node);
  state.sel = sel;
  state.scope = 'job';
  renderScope();
  renderTree();
  treeNodeEl(sel)?.scrollIntoView({ block: 'nearest' });
  loadTreeSel(sel);
}

async function onTreeKey(e) {
  if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
  e.preventDefault();
  e.stopPropagation();   // šípky nech nepohnú zoznamom súborov
  const nodes = [...$('tree').querySelectorAll('.node')];
  if (!nodes.length) return;
  const cur = state.scope === 'job' && state.sel ? treeNodeEl(state.sel) : null;
  if (!cur) { moveTreeTo(nodes[0]); return; }
  const i = nodes.indexOf(cur);
  if (e.key === 'ArrowDown') { moveTreeTo(nodes[Math.min(nodes.length - 1, i + 1)]); return; }
  if (e.key === 'ArrowUp') { moveTreeTo(nodes[Math.max(0, i - 1)]); return; }
  if (e.key === 'Home') { moveTreeTo(nodes[0]); return; }
  if (e.key === 'End') { moveTreeTo(nodes[nodes.length - 1]); return; }
  const sel = nodeSel(cur);
  const hasKids = cur.querySelector('.tw').innerHTML !== '';
  const open = cur.classList.contains('open');
  if (e.key === 'ArrowRight') {
    if (!hasKids) return;
    if (open) { moveTreeTo(nodes[i + 1]); return; }
    await setTreeOpen(sel, true);
    renderTree();
  } else if (open && hasKids) {   // ←
    await setTreeOpen(sel, false);
    renderTree();
    treeNodeEl(sel)?.scrollIntoView({ block: 'nearest' });
  } else {
    const p = parentSel(sel);
    if (p) moveTreeTo(treeNodeEl(p));
  }
}

// --- hľadanie čísla zákazky v strome ------------------------------------------
// Číslo bez ohľadu na úvodné nuly: 'OD21750' = 'OD00021750', '9712' = '009712',
// '100919' = zákazník '100919-Unitek…'. Vracia 'PREFIX:číslo' alebo null.
function normId(s) {
  const m = /^([a-z]*)[\s_-]*0*(\d+)$/i.exec(s.trim());
  return m ? `${m[1].toUpperCase()}:${m[2]}` : null;
}

function idMatches(term, name) {
  const t = normId(term);
  if (!t) return false;
  const n = normId(name);
  if (n === t) return true;
  // bez predpony ('21750') sedí aj na zákazku s predponou ('OD00021750')
  return t.startsWith(':') && n !== null && n.endsWith(t);
}

// --- menu zákaziek a zákazníkov pod hľadaním ----------------------------------
// Pri čísle (od 3 číslic) ukáže zákazky/zákazníkov, ktorých číslo sedí – aj staré zákazky
// u viacerých zákazníkov (000324 v OD067 aj v OD112). Enter / klik = otvoriť v strome.
// Poradie: presné číslo (bez núl a predpony) → číslo končí zadanými číslicami ('014' = 100014,
// 24014) → číslo na začiatku → kdekoľvek v názve.
const FMENU_MAX = 12;
const FMENU_CUST = 4;   // najviac zákazníkov z FMENU_MAX
let fmenu = { items: [], more: 0, cur: 0 };

function idRank(term, name) {
  if (idMatches(term, name)) return 0;
  const t = normId(term);
  const n = normId(name);
  if (t && n) {
    const [tp, td] = t.split(':');
    const [np, nd] = n.split(':');
    if (!tp || tp === np) {
      // koniec čísla s nulami tak, ako boli napísané ('014' nesedí na 1914)
      const tRaw = /\d+$/.exec(term.trim())[0];
      const nRaw = /\d+$/.exec(name.trim())[0];
      if (nRaw.endsWith(tRaw)) return 1;
      if (nd.startsWith(td)) return 2;
    }
  }
  return name.toLowerCase().includes(term.toLowerCase()) ? 3 : 9;
}

function folderHits() {
  const terms = state.similar ? [] : state.q.split(/\s+/).filter((t) => t && !/[*?]/.test(t) && /\d{3}/.test(t));
  if (!terms.length) return { items: [], more: 0 };
  const best = (name) => Math.min(...terms.map((t) => idRank(t, name)));
  // rovnaká zhoda: nové značenie (OD…) pred starým (čisté číslo), potom novšie pred staršími
  const od = (h) => (/^OD/i.test(h.name) ? 0 : 1);
  const cmp = (a, b) => a.r - b.r || od(a) - od(b)
    || ((b.j && b.j.changed) || 0) - ((a.j && a.j.changed) || 0)
    || a.name.localeCompare(b.name, 'sk', { numeric: true });
  const hits = [];
  for (const c of state.tree) {
    // zákazník podľa čísla pred pomlčkou ('100919-Unitek…'), inak časť názvu
    const rc = Math.min(best(c.name.split('-')[0]), best(c.name));
    if (rc < 9) hits.push({ kind: 'cust', r: rc, name: c.name, c });
    for (const j of c.jobs) {
      const r = best(j.name);
      if (r < 9) hits.push({ kind: 'job', r, name: j.name, c, j });
    }
  }
  hits.sort(cmp);
  // po skupinách: najprv zákazky, potom zákazníci – zákazníci majú vlastné miesta,
  // inak by ich pri krátkom čísle vytlačili desiatky zákaziek
  const jobs = hits.filter((h) => h.kind === 'job');
  const custs = hits.filter((h) => h.kind === 'cust');
  const nc = Math.min(custs.length, FMENU_CUST);
  const items = [...jobs.slice(0, FMENU_MAX - nc), ...custs.slice(0, nc)];
  return { items, more: hits.length - items.length };
}

function updateFolderMenu() {
  const { items, more } = folderHits();
  fmenu = { items, more, cur: 0 };
  if (!items.length || document.activeElement !== $('q')) { closeFolderMenu(); return; }
  renderFolderMenu();
}

function renderFolderMenu() {
  const box = $('fmenu');
  const out = [];
  let last = '';
  fmenu.items.forEach((h, i) => {
    if (h.kind !== last) {
      out.push(`<div class="fm-head">${h.kind === 'job' ? 'Zákazky' : 'Zákazníci'}</div>`);
      last = h.kind;
    }
    const yr = h.kind === 'job' && h.j.changed ? new Date(h.j.changed * 1000).getFullYear() : '';
    const sub = h.kind === 'job'
      ? `<span class="fm-sub">${esc(h.c.name)}</span><span class="fm-yr" title="Posledná zmena v zákazke: ${esc(fmtDate(h.j.changed))}">${yr}</span>${complStatus(h.j.missing)}`
      : `<span class="fm-sub">${h.c.jobs.length} ${h.c.jobs.length === 1 ? 'zákazka' : h.c.jobs.length >= 2 && h.c.jobs.length <= 4 ? 'zákazky' : 'zákaziek'}</span>`;
    out.push(`<button type="button" class="dd-item fm-item${i === fmenu.cur ? ' cur' : ''}" data-i="${i}" tabindex="-1">
      <span class="nm">${highlight(h.name)}</span>${sub}</button>`);
  });
  if (fmenu.more) out.push(`<div class="fm-more">… a ďalších ${fmenu.more} – spresni hľadanie</div>`);
  out.push('<div class="fm-hint">Enter = otvoriť v strome · ↑↓ výber · Esc zavrieť</div>');
  box.innerHTML = out.join('');
  // pod hľadaním (aspoň 460 px – číslo, zákazník, rok, úplnosť)
  const r = document.querySelector('.search').getBoundingClientRect();
  const w = Math.min(Math.max(r.width, 460), window.innerWidth - 16);
  box.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - w - 8))}px`;
  box.style.top = `${r.bottom + 4}px`;
  box.style.width = `${w}px`;
  box.hidden = false;
  box.querySelector('.fm-item.cur')?.scrollIntoView({ block: 'nearest' });
}

function closeFolderMenu() {
  $('fmenu').hidden = true;
}

// Otvorí zákazku / zákazníka z menu v strome (hľadanie sa vymaže)
async function chooseFolder(i) {
  const h = fmenu.items[i];
  if (!h) return;
  closeFolderMenu();
  clearSearchQuiet();
  if (h.kind === 'job') {
    await gotoJob(h.j.id, '');
  } else {
    state.openCust.add(h.c.id);
    await selectCustomer(h.c.id);
    renderTree();
    treeNodeEl({ cust: h.c.id, job: null, rel: '' })?.scrollIntoView({ block: 'center' });
  }
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
    items.push(['Hľadať v obsahu programov…', () => openContentSearch({ customer_id: c.id, job_id: null, label: c.name })]);
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
    items.push(['Hľadať v obsahu programov…', () => openContentSearch({ customer_id: f.cust.id, job_id: f.job.id, label: `${f.cust.name} \\ ${f.job.name}` })]);
    items.push(['Zoznam nástrojov…', () => openToolList(jobId, rel)]);
  }
  if (items.length) items.push('-');
  items.push(['Zbaliť celý strom', () => {
    state.openCust.clear();
    state.openJobs.clear();
    state.openDirs.clear();
  }]);
  showMenu(e, items, renderTree);
}

// Kontextové menu pri myši. items: [text, akcia] | {text, action, checked} | '-' | {title}
// after = čo urobiť po akcii (napr. prekresliť strom)
function showMenu(e, items, after) {
  const menu = $('ctx');
  const actions = [];
  menu.innerHTML = items.map((it) => {
    if (it === '-') return '<hr>';
    if (it.title) return `<div class="ctx-title">${esc(it.title)}</div>`;
    const [text, action, checked] = Array.isArray(it) ? it : [it.text, it.action, it.checked];
    actions.push(action);
    const chk = checked === undefined ? '' : `<span class="ctx-chk">${checked ? ICON_CHECK : ''}</span>`;
    return `<button type="button" role="menuitem" data-i="${actions.length - 1}">${chk}${esc(text)}</button>`;
  }).join('');
  menu.onclick = async (ev) => {
    const b = ev.target.closest('button');
    if (!b) return;
    hideCtx();
    await actions[Number(b.dataset.i)]();
    if (after) after();
  };
  menu.hidden = false;
  // umiestniť k myši, ale nevyliezť z okna
  const r = menu.getBoundingClientRect();
  menu.style.left = `${Math.min(e.clientX, window.innerWidth - r.width - 4)}px`;
  menu.style.top = `${Math.min(e.clientY, window.innerHeight - r.height - 4)}px`;
}

// --- súbor: ukázať v strome, odkazy .lnk, kontextové menu --------------------
// Dvojklik: súbor v strome (zákazka → priečinok, súbor označený). Odkaz .lnk → jeho cieľ.
async function revealFile(f, followLink = true) {
  if (followLink && f.target != null) { await gotoLink(f); return; }
  clearSearchQuiet();
  state.selFile = f.id;
  await gotoJob(f.job_id, f.folder || '');
}

// Odkaz .lnk na inú (starú) zákazku – skok na cieľ v strome
async function gotoLink(f) {
  const r = await api.locate(f.target || '');
  if (!r.ok) { toast(r.error); return; }
  clearSearchQuiet();
  if (r.cust_id) {
    state.openCust.add(r.cust_id);
    await selectCustomer(r.cust_id);
    renderTree();
    const node = $('tree').querySelector('.node.sel');
    if (node) node.scrollIntoView({ block: 'center' });
  } else {
    state.selFile = r.file_id;
    await gotoJob(r.job_id, r.rel);
  }
  if (!r.exact) toast(`Presný cieľ odkazu v Lupe nie je – ukazujem najbližší priečinok.\n${f.target}`);
}

async function copyText(text) {
  const r = await api.copy_text(text);
  toast(r.ok ? `Skopírované: ${text}` : r.error);
}

function onFileContext(e) {
  const el = e.target.closest('[data-id]');
  if (!el) return;
  e.preventDefault();
  const id = Number(el.dataset.id);
  const f = state.files.find((x) => x.id === id);
  if (!f) return;
  selectFile(id);
  const items = [{ title: f.name }, ['Otvoriť', () => openFile(f.id)]];
  if (f.ftype === 'NC') items.push(['Otvoriť v NC Editore', async () => { const r = await api.open_in_editor(f.id); if (r && r.ok === false) toast(r.error); else if (r && r.note) toast(r.note); }]);
  if (f.ftype === 'NC' && !f.odl) {
    items.push(['Porovnať s odladenou verziou v NC Editore', async () => {
      const r = await api.compare_with_debugged(f.id);
      if (!r.ok) { toast(r.error); return; }
      if (r.vyber) {                                                   // viac odladených verzií – opýtať sa
        showMenu({ clientX: e.clientX, clientY: e.clientY }, [{ title: 'Odladená verzia na porovnanie' },
          ...r.vyber.map((v) => [`${v.name}   [${v.folder}]`, async () => {
            const x = await api.compare_in_editor([f.id, v.id]);
            toast(x.ok ? (x.warn || `Porovnanie otvorené: ${f.name} ↔ ${v.name}`) : x.error);
          }])]);
        return;
      }
      toast(r.warn || `Porovnanie otvorené: ${f.name} ↔ ${r.b}`);
    }]);
  }
  if (f.ftype === 'NC') {
    if (cmpIds.length === 2) items.push([`Porovnať označené (A ↔ B) v NC Editore`, () => compareFiles(cmpIds)]);
    else if (cmpIds.length === 1 && cmpIds[0] !== f.id) items.push(['Porovnať s označeným (A) v NC Editore', () => compareFiles([cmpIds[0], f.id])]);
    items.push([cmpIds.includes(f.id) ? 'Zrušiť označenie na porovnanie' : 'Označiť na porovnanie (Ctrl+klik)', () => toggleCmp(f.id)]);
  }
  if (f.target != null) items.push(['Prejsť na cieľ odkazu', () => gotoLink(f)]);
  items.push(['Ukázať v strome', () => revealFile(f, false)]);
  items.push(['Otvoriť priečinok', () => openFolder(f.id)]);
  items.push('-');
  items.push(['Kopírovať cestu', () => copyText(f.path)]);
  items.push(['Kopírovať názov', () => copyText(f.name)]);
  if (f.ftype === 'PDF' && !f.query) items.push('-', ['Podobné výkresy', () => startSimilar(f)]);
  items.push('-');
  items.push(state.owner && state.owner === f.owner
    ? ['Zrušiť filter vlastníka', () => pickOwner('')]
    : [`Len vlastník ${ownerName(f.owner)}`, () => pickOwner(f.owner)]);
  showMenu(e, items);
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

// Vlastníci vo výbere (počty súborov len vo vybranej zákazke / u zákazníka, inak celé L:\)
let ownersKey = null;
async function loadOwners() {
  const p = {};
  if (!state.similar && state.scope === 'job' && state.sel) {
    if (state.sel.job) p.job_id = state.sel.job;
    else p.customer_id = state.sel.cust;
  }
  const key = JSON.stringify(p);
  if (key === ownersKey) return;
  ownersKey = key;
  const list = await api.get_owners(p);
  if (key !== ownersKey) return;   // medzitým iný výber
  state.owners = list;
  if (!$('ownerDrop').hidden) renderOwnerList();
}

// --- zoznam súborov --------------------------------------------------------
async function refresh() {
  loadOwners();
  renderViewsBtn();
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
      lists: state.lists,
      odladene: state.odladene,
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

// --- odkazy .lnk medzi zákazkami (oboma smermi) --------------------------------
// Nová zákazka: „→ Odkazuje na“ staré zákazky (klik = cieľ odkazu v strome).
// Stará zákazka: „← Odkazujú sem“ novšie zákazky (klik = samotný odkaz v novej zákazke).
const jobLinks = new Map();   // jobId -> {to: [...], from: [...]} (Api.get_links)
const ICON_ODL = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="m8 12.5 2.8 2.8L16 9.5"></path></svg>';
const ICON_LINK = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"></path><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"></path></svg>';
const LINKS_MAX = 8;

function linkCount(n) {
  return `${n} ${n === 1 ? 'odkaz' : n <= 4 ? 'odkazy' : 'odkazov'}`;
}

// Jedna položka (zákazka) v riadku odkazov
function linkItem(h, i, dir) {
  const f = h.job_id != null ? findJob(h.job_id) : null;
  if (!f) {   // cieľ mimo zákaziek v Lupe (iný disk, zmazaný…)
    const name = h.target.split('\\').filter(Boolean).pop() || h.target;
    return `<button type="button" class="bl-item out" data-dir="${dir}" data-i="${i}" title="${esc(h.target)}\nCieľ nie je v žiadnej zákazke v Lupe">` +
      `<span class="mono">${esc(name)}</span><span class="bl-yr">mimo Lupy</span></button>`;
  }
  const yr = h.changed ? new Date(h.changed * 1000).getFullYear() : '';
  const cust = f.cust.name.split('-')[0];
  const where = dir === 'to' ? h.target : `${f.cust.name} \\ ${f.job.name}${h.rel ? ' \\ ' + h.rel : ''}`;
  const tip = `${where}\n${linkCount(h.links)}${h.changed ? `\nPosledná zmena v zákazke: ${fmtDay(h.changed)}` : ''}\nKlik = ${dir === 'to' ? 'ukázať cieľ' : 'ukázať odkaz'} v strome`;
  return `<button type="button" class="bl-item" data-dir="${dir}" data-i="${i}" title="${esc(tip)}">` +
    `<span class="mono">${esc(f.job.name)}</span><span class="bl-cust">${esc(cust)}</span>` +
    `${yr ? `<span class="bl-yr">z roku ${yr}</span>` : ''}</button>`;
}

function linkRow(list, dir) {
  if (!list.length) return '';
  const label = dir === 'to' ? 'Odkazuje na:' : 'Odkazujú sem:';
  const items = list.slice(0, LINKS_MAX).map((h, i) => linkItem(h, i, dir));
  if (list.length > LINKS_MAX) items.push(`<span class="bl-more">a ďalšie ${list.length - LINKS_MAX}</span>`);
  return `<div class="bl-row ${dir}">${ICON_LINK}<span class="bl-label">${label}</span>${items.join('')}</div>`;
}

async function renderLinks(jobId) {
  const box = $('links');
  box.dataset.job = jobId || '';
  if (!jobId) { box.hidden = true; return; }
  if (!jobLinks.has(jobId)) {
    box.hidden = true;
    let r;
    try { r = await api.get_links(jobId); } catch (e) { r = null; }
    jobLinks.set(jobId, r || { to: [], from: [] });
    if (box.dataset.job !== String(jobId)) return;   // medzitým iný výber
  }
  const r = jobLinks.get(jobId);
  const lists = { to: r.to, from: r.from.filter((h) => findJob(h.job_id)) };
  const html = linkRow(lists.to, 'to') + linkRow(lists.from, 'from');
  if (!html) { box.hidden = true; return; }
  box.innerHTML = html;
  box.querySelectorAll('.bl-item').forEach((b) => {
    b.onclick = async () => {
      const h = lists[b.dataset.dir][Number(b.dataset.i)];
      if (b.dataset.dir === 'to') {
        await gotoLink({ target: h.target });   // cieľ odkazu (priečinok / súbor v starej zákazke)
      } else {
        clearSearchQuiet();
        state.selFile = h.file_id;   // označiť priamo odkaz v novej zákazke
        await gotoJob(h.job_id, h.rel);
      }
    };
  });
  box.hidden = false;
}

// --- stroje zákazky (hlavičky NC programov, Api.get_machines) ---------------------
// Štítky za úplnosťou: každý stroj raz (5× eVo 80 = jeden štítok), v bublinke počet a hlavičky.
const jobMachines = new Map();   // jobId -> [{name, n, raw, files, by_list}]
const ICON_MACHINE = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="14" rx="1.5"></rect><path d="M12 7v6M9 13h6M7 21h10M12 17v4"></path></svg>';

function machineTip(m) {
  const lines = [];
  if (m.via) lines.push(`Cez odkaz na staré heslo: ${m.via}`);
  if (m.n) {
    lines.push(`${m.n} ${m.n === 1 ? 'súbor' : m.n <= 4 ? 'súbory' : 'súborov'} (NC programy, nástrojové listy)` +
      (m.raw.length ? ` – hlavička: ${m.raw.join(' · ')}` : ''));
    lines.push(...m.files.slice(0, 5).map((n) => '  ' + n));
    if (m.n > 5) lines.push('  …');
  }
  if (m.lists.length) {
    lines.push('CNC listy:');
    lines.push(...m.lists.slice(0, 5).map((n) => '  ' + n));
    if (m.lists.length > 5) lines.push('  …');
  }
  return lines.join('\n');
}

// Cieľ odkazu skrátene: posledné dve časti cesty (OD645\000040)
function shortTarget(p) {
  return p.split('\\').filter(Boolean).slice(-2).join('\\');
}

// Stroje za vybraný priečinok s podpriečinkami (koreň = celá zákazka); pri podpriečinku aj riadok
// „V priečinku …“ s jeho úplnosťou (vnorené zákazky: zákazka \ číslo \ diel – každý diel zvlášť).
async function renderMachines(jobId, rel = '') {
  const box = $('machines');
  const dir = $('complDir');
  const key = jobId ? `${jobId}|${rel || ''}` : '';
  box.dataset.key = key;
  if (!jobId) { box.hidden = true; dir.hidden = true; return; }
  if (!jobMachines.has(key)) {
    box.hidden = true;
    dir.hidden = true;
    let r;
    try { r = await api.get_machines(jobId, rel || ''); } catch (e) { r = null; }
    jobMachines.set(key, r || { machines: [], missing: null });
    if (box.dataset.key !== key) return;   // medzitým iný výber
  }
  const { machines: list, missing } = jobMachines.get(key);
  if (missing && state.scope === 'job') {
    const name = rel.split('\\').pop();
    dir.innerHTML = `<span class="cd-label" title="Úplnosť priečinka ${esc(rel)} – jeho súbory s podpriečinkami a súbory priamo v nadradených priečinkoch">V priečinku <span class="mono">${esc(name)}</span>:</span>` +
      complCheck(missing).map((c) =>
        `<span class="${c.ok ? 'y' : 'n'}" title="${c.ok ? 'Je' : 'Chýba'} v priečinku">${c.ok ? '✓' : '✗'} ${esc(c.name)}</span>`).join('');
    dir.hidden = false;
  } else {
    dir.hidden = true;
  }
  if (!list.length) { box.hidden = true; return; }
  box.innerHTML = ICON_MACHINE +
    list.map((m) => `<span class="${m.via ? 'via' : ''}" title="${esc(machineTip({ ...m, via: m.via && shortTarget(m.via) }))}">` +
      `${esc(m.name)}${m.via ? `<small>${ICON_LINK}</small>` : ''}</span>`).join('');
  box.hidden = false;
}

// značka „odladené“ v hlavičke zákazky: počet odladených NC programov; klik zapne / vypne filter len odladených programov
function renderOdlHead(f) {
  const el = $('odlHead');
  const n = f ? f.job.odl || 0 : 0;
  if (!f || (!n && !f.job.has_nc)) { el.hidden = true; return; }       // bez NC programov nie je čo odlaďovať
  el.hidden = false;
  el.classList.toggle('none', !n);
  el.classList.toggle('on', !!n && !!state.odladene);
  el.disabled = !n;
  el.textContent = n ? `✓ Odladené ${n}` : 'Odladené 0';
  el.title = !n ? 'Zákazka nemá žiadny odladený NC program (priečinok odladené alebo Zo stroja)'
    : state.odladene ? 'Zobrazené sú len odladené programy – klik = ukázať všetko'
      : `Zákazka obsahuje ${n} ${n === 1 ? 'odladený NC program' : n >= 2 && n <= 4 ? 'odladené NC programy' : 'odladených NC programov'}`
        + (f.job.odl_cas ? ` (posledný odladený: ${fmtDay(f.job.odl_cas)})` : '') + '. Klik = ukázať len odladené programy.';
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
    heading = esc(f.job.name) + (rel ? `<span class="h-sub"> \\ ${esc(rel.split('\\').join(' \\ '))}</span>` : '');
  } else {
    heading = 'Vyber zákazku';
  }
  $('crumb').textContent = crumb;
  $('heading').innerHTML = heading;
  if ($('simClose')) $('simClose').onclick = () => exitSimilar();
  renderCompl();
  renderOdlHead(f && !state.similar && !all ? f : null);
  renderLinks(f && !state.similar && !all ? f.job.id : null);
  renderMachines(f && !state.similar && !all ? f.job.id : null, state.sel ? state.sel.rel : '');

  const n = state.total;
  let cnt = '';
  if (state.similar) {
    const k = n - 1;
    cnt = k ? `${k} ${k === 1 ? 'podobný výkres' : k >= 2 && k <= 4 ? 'podobné výkresy' : 'podobných výkresov'}`
      : 'Nenašiel sa žiadny podobný výkres';
    if (state.owner) cnt += ` · vlastník ${ownerName(state.owner)}`;
  } else if (all || state.sel) {
    cnt = `${n} ${plural(n)}`;
    if (n > state.files.length) cnt += ` · zobrazených ${state.files.length} najnovších`;
  }
  $('count').textContent = cnt;
  // meniť len text, nie celý obsah (v hlavičke je úchyt na ťahanie)
  document.querySelector('th.c-folder').firstChild.nodeValue = multiJob() ? 'Zákazka / priečinok' : 'Priečinok';
}

// zoradenie podľa stavu „odladený“: iné než NC (0) < neodladené NC (1) < odladené NC (2)
const odlRank = (f) => (f.ftype === 'NC' ? (f.odl ? 2 : 1) : 0);

function sortedFiles() {
  const k = state.sortKey;
  const dir = state.sortDir;
  const typeOrder = (t) => (state.types[t] ? state.types[t].order : 99);
  const loc = (x) => (multiJob() ? `${x.job}\\${x.folder}` : x.folder);
  return [...state.files].sort((a, b) => {
    let r;
    if (k === 'ftype') r = typeOrder(a.ftype) - typeOrder(b.ftype);
    else if (k === 'size' || k === 'created' || k === 'modified' || k === 'sim') r = (a[k] || 0) - (b[k] || 0);
    else if (k === 'odl') r = odlRank(a) - odlRank(b);
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
    const link = f.target != null;
    const nameTitle = link ? `${f.name}\nOdkaz na: ${f.target || 'cieľ sa nedá zistiť'}\nDvojklik = prejsť na cieľ` : f.name;
    return `<tr data-id="${f.id}"${f.id === state.selFile ? ' class="sel"' : ''}>
    <td class="c-type">${badge(f.ftype)}</td>
    <td class="c-odl">${f.ftype === 'NC' ? (f.odl ? '<span class="tag-odl" title="Program je v priečinku odladené / Zo stroja">✓ odladený</span>' : '<span class="odl-no">neodladený</span>') : ''}</td>
    <td class="c-sim">${simCell(f)}</td>
    <td class="c-name" title="${esc(nameTitle)}">${highlight(f.name)}${link ? `<span class="lnk-to">→ ${esc(shortPath(f.target) || '?')}</span>` : ''}</td>
    <td class="c-folder" title="${esc(locTitle)}">${esc(loc)}</td>
    <td class="c-owner">${esc(ownerName(f.owner))}</td>
    <td class="c-date k-created" title="${fmtDate(f.created)}">${fmtDay(f.created)}</td>
    <td class="c-date k-modified" title="${fmtDate(f.modified)}">${fmtDay(f.modified)}</td>
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
    const date = fmtDay(f.modified);
    const title = f.target != null ? `${f.name}\nOdkaz na: ${f.target || 'cieľ sa nedá zistiť'}` : f.name;
    return `<div class="card${f.id === state.selFile ? ' sel' : ''}" data-id="${f.id}" title="${esc(title)}">
      <div class="g-thumb" data-id="${f.id}"><span class="pv-msg"></span></div>
      <div class="g-name">${badge(f.ftype)}<span>${highlight(f.name)}</span></div>
      <div class="g-sub">${state.similar ? simTag(f) + ' · ' : ''}${esc(sub)}${sub ? ' · ' : ''}${date} · ${esc(ownerName(f.owner))}</div>
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

// Porovnanie dvoch NC programov v NC Editore: Ctrl+klik označí súbory (A, B), potom pravé tlačidlo → Porovnať.
let cmpIds = [];
function applyCmpMarks() {
  for (const box of [$('rows'), $('gallery')]) {
    for (const el of box.children) {
      const k = cmpIds.indexOf(Number(el.dataset.id));
      if (k < 0) el.removeAttribute('data-cmp'); else el.dataset.cmp = 'AB'[k];
    }
  }
}
function toggleCmp(id) {
  const k = cmpIds.indexOf(id);
  if (k >= 0) cmpIds.splice(k, 1);
  else { cmpIds.push(id); if (cmpIds.length > 2) cmpIds.shift(); }
  applyCmpMarks();
  const f = (i) => state.files.find((x) => x.id === i);
  if (cmpIds.length === 1) toast(`A: ${f(cmpIds[0])?.name || ''} – Ctrl+klik na druhý súbor a potom pravé tlačidlo → Porovnať`);
}
async function compareFiles(ids) {
  const r = await api.compare_in_editor(ids);
  toast(r.ok ? (r.warn || 'Porovnanie otvorené v NC Editore') : r.error);
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

// --- nástroje NC programu v detaile (nastroje.py) -------------------------------------------
// Klik na nástroj otvorí NC Editor na prvom volaní. Rozmery z hlavičky programu: D priemer, r polomer, Lc dĺžka rezu, L dĺžka.
let toolsTok = 0;
async function loadTools(f) {
  const tok = ++toolsTok;
  let r;
  try { r = await api.get_tools(f.id); } catch (e) { r = { ok: false, error: String(e) }; }
  const box = $('dTools');
  if (tok !== toolsTok || !box || state.selFile !== f.id) return;     // medzitým sa vybral iný súbor
  const msg = (t) => { box.innerHTML = `<div class="dt-h">Nástroje programu</div><div class="dt-msg">${esc(t)}</div>`; };
  if (!r.ok) { msg(r.error); return; }
  if (!r.nastroje.length) { msg('V programe sa nenašli volania nástrojov.'); return; }
  const maT = r.nastroje.some((n) => n.cislo);                                   // číslo T (Siemens ho nemusí mať)
  const maRozmery = r.nastroje.some((n) => n.d || n.r || n.r2 || n.lc || n.l || n.ll);
  const rozmery = (n) => [n.d && `D${n.d}`, n.r && `r${n.r}`, n.r2 && `r2 ${n.r2}`, n.lc && `Lc${n.lc}`, n.l && `L${n.l}`, n.ll && `LL${n.ll}`].filter(Boolean).join(' ');
  box.innerHTML = `<div class="dt-h">Nástroje programu (${r.nastroje.length})</div>
    <table class="dt-tbl"><thead><tr>${maT ? '<th>T</th>' : ''}<th>Názov</th>${maRozmery ? '<th>Rozmery</th>' : ''}<th class="r">Volaní</th></tr></thead><tbody>${
      r.nastroje.map((n, i) => `<tr data-i="${i}" title="Otvoriť v NC Editore na riadku ${n.prvy}">${maT ? `<td class="mono">${esc(n.cislo)}</td>` : ''}<td>${esc(n.nazov || (n.cislo ? '' : n.t))}</td>${maRozmery ? `<td class="mono">${esc(rozmery(n))}</td>` : ''}<td class="r">${n.pocet}</td></tr>`).join('')
    }</tbody></table>`;
  box.querySelector('tbody').onclick = async (e) => {
    const tr = e.target.closest('tr');
    if (!tr) return;
    const n = r.nastroje[Number(tr.dataset.i)];
    const res = await api.open_in_editor(f.id, n.prvy);
    if (res && res.ok === false) toast(res.error);
  };
}

// --- zoznam nástrojov zákazky / priečinka (Nástrojový list: text, tlač) ------------------------
// Rozsah = vybraná zákazka alebo priečinok; predvolene len odladené programy, ak ich zákazka má.
let tl = null;      // {jobId, rel, text, name}
function tlMsg(t) { $('tlText').textContent = t; $('tlSave').disabled = $('tlPrintBtn').disabled = $('tlCopy').disabled = true; }

async function openToolList(jobId, rel, odl) {
  const f = findJob(jobId);
  tl = { jobId, rel: rel || '', text: '', name: 'nastroje.txt' };
  $('tlTitle').textContent = 'Zoznam nástrojov';
  $('tlScope').textContent = (f ? `${f.cust.name} \\ ${f.job.name}` : '') + (rel ? ` \\ ${rel}` : '');
  $('tlOdl').checked = odl !== undefined ? odl : !!(f && f.job.odl);
  $('tl').hidden = false;
  await tlBuild();
}

async function tlBuild() {
  if (!tl) return;
  const mine = tl;
  tlMsg('Načítavam programy…');
  $('tlInfo').textContent = '';
  const params = { job_id: mine.jobId, rel: mine.rel, odladene: $('tlOdl').checked };
  const e = await api.tools_list_estimate(params);
  if (mine !== tl) return;
  if (!e.ok) { tlMsg(e.error); return; }
  if (!e.files) {
    tlMsg(params.odladene && e.all_files
      ? `V tomto rozsahu nie je žiadny odladený program (je tu ${e.all_files} neodladených). Vypni „Len odladené programy“.`
      : 'V tomto rozsahu nie sú žiadne NC programy.');
    return;
  }
  $('tlInfo').textContent = `Číta sa ${e.files} programov (${e.mb} MB)…`;
  const r = await api.tools_list_build(params);
  if (mine !== tl) return;
  if (!r.ok) { tlMsg(r.error); $('tlInfo').textContent = ''; return; }
  mine.text = r.text;
  mine.name = r.nazov_suboru;
  $('tlText').textContent = r.text;
  $('tlSave').disabled = $('tlPrintBtn').disabled = $('tlCopy').disabled = false;
  $('tlInfo').textContent = `${r.programov} programov` + (r.chyb ? ` · ${r.chyb} sa nedalo prečítať` : '')
    + (params.odladene ? '' : e.odl_files ? ` · z toho ${e.odl_files} odladených` : '');
}

function closeToolList() {
  $('tl').hidden = true;
  $('tlText').textContent = '';
  tl = null;
}

function bindToolList() {
  $('tlClose').onclick = closeToolList;
  $('tlOdl').addEventListener('change', tlBuild);
  $('tlSave').onclick = async () => {
    if (!tl || !tl.text) return;
    const r = await api.save_text_file(tl.text, tl.name);
    if (r.ok) toast(`Uložené: ${r.path}`);
    else if (!r.cancel) toast(r.error);
  };
  $('tlCopy').onclick = async () => {
    if (!tl || !tl.text) return;
    const r = await api.copy_text(tl.text);
    toast(r.ok ? 'Zoznam nástrojov skopírovaný' : r.error);
  };
  $('tlPrintBtn').onclick = () => {
    if (!tl || !tl.text) return;
    $('tlPrint').textContent = tl.text;
    window.print();
  };
  $('tl').addEventListener('mousedown', (e) => { if (e.target === $('tl')) closeToolList(); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('tl').hidden) { e.preventDefault(); e.stopPropagation(); closeToolList(); }
  }, true);
}

// --- rýchly náhľad (Medzerník) -----------------------------------------------------------------
// NC program a txt: čísla riadkov, komentáre sivo, kľúčové slová tučne. PDF: strana ako obrázok (← → strany).
// Word: odseky a tabuľky, Excel: tabuľka listu (← → listy). Šípky hore / dole = ďalší / predchádzajúci súbor v zozname.
// Medzerník / Esc zavrie. Presný vzhľad dokumentov to nie je (len obsah).
const QP_KW = /TOOL\s+CALL|TOOL\s+DEF|CYCL\s+DEF|CALL\s+LBL|CALL\s+PGM|BEGIN\s+PGM|END\s+PGM|\bT\s*=\s*"[^"]*"|\bM0?6\b|\bM30\b|\bM2\b|GROUP_BEGIN|CYCLE\d+/g;
const QP_TYPY = ['NC', 'TXT', 'PDF', 'DOC', 'XLS', 'OBR'];
let qpFile = null;
let qpStav = { page: 0, sheet: 0 };
let qpTok = 0;

function qpLine(t) {
  const i = t.indexOf(';');
  const code = i >= 0 ? t.slice(0, i) : t;
  let out = '';
  let last = 0;
  QP_KW.lastIndex = 0;
  for (let m; (m = QP_KW.exec(code));) {
    out += esc(code.slice(last, m.index)) + '<b>' + esc(m[0]) + '</b>';
    last = m.index + m[0].length;
  }
  out += esc(code.slice(last));
  return i >= 0 ? out + `<span class="c">${esc(t.slice(i))}</span>` : out;
}

const qpTabulka = (riadky) => `<table class="qp-tab"><tbody>${riadky.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;

function qpPatka(r) {
  if (r.kind === 'pdf') return `Strana ${r.page + 1} z ${r.pages}` + (r.pages > 1 ? ' · ← → listovanie po stranách' : '') + ' · ↑ ↓ ďalší súbor';
  if (r.kind === 'excel') return `List „${r.harky[r.harok]}“ (${r.harok + 1} z ${r.harky.length})` + (r.harky.length > 1 ? ' · ← → listy' : '')
    + (r.orezane ? ` · zobrazených prvých ${r.riadky.length} riadkov` : '') + ' · ↑ ↓ ďalší súbor';
  if (r.kind === 'word') return (r.orezane ? 'Zobrazená len časť dokumentu · ' : '') + 'Text dokumentu bez formátovania · ↑ ↓ ďalší súbor';
  if (r.kind === 'obrazok') return (r.pages > 1 ? `Strana ${r.page + 1} z ${r.pages} · ← → listovanie · ` : r.ftype === 'OBR' ? 'Obrázok · ' : 'Náhľad z Windows (prvá strana) · ') + '↑ ↓ ďalší súbor';
  return r.more ? `Zobrazených prvých ${r.limit.toLocaleString('sk-SK')} riadkov – celý program otvor v NC Editore · ↑ ↓ ďalší súbor`
    : `${r.lines.length.toLocaleString('sk-SK')} riadkov · ↑ ↓ ďalší súbor`;
}

// Načíta a vykreslí náhľad súboru f; vráti false, ak sa nedá (správa je v okne alebo toast)
async function qpLoad(f, page = 0, sheet = 0) {
  const tok = ++qpTok;
  const text = f.ftype === 'NC' || f.ftype === 'TXT';
  const r = text ? await api.get_text_preview(f.id) : await api.get_doc_preview(f.id, page, sheet);
  if (tok !== qpTok) return false;
  qpFile = f;
  qpStav = { page: r.page || 0, sheet: r.harok || 0 };
  $('qpName').textContent = f.name;
  $('qpPath').textContent = f.path;
  $('qpEditor').hidden = f.ftype !== 'NC';
  const body = $('qpBody');
  body.className = 'qp-body';
  if (!r.ok) {
    body.innerHTML = `<div class="qp-msg">${esc(r.error)}</div>`;
    $('qpFoot').textContent = '↑ ↓ ďalší súbor';
    return false;
  }
  if (r.kind === 'pdf' || r.kind === 'obrazok') {
    body.classList.add('qp-img');
    body.innerHTML = `<img src="${r.src}" alt="">`;
  } else if (r.kind === 'word') {
    body.classList.add('qp-doc');
    body.innerHTML = r.bloky.map((b) => (b.typ === 'tab' ? qpTabulka(b.riadky) : `<p>${esc(b.text) || '&nbsp;'}</p>`)).join('');
  } else if (r.kind === 'excel') {
    body.classList.add('qp-doc');
    body.innerHTML = (r.harky.length > 1 ? `<div class="qp-sheets">${r.harky.map((n, i) => `<span class="${i === r.harok ? 'on' : ''}">${esc(n)}</span>`).join('')}</div>` : '')
      + (r.riadky.length ? qpTabulka(r.riadky) : '<div class="qp-msg">List je prázdny.</div>');
  } else {
    const first = r.first || 1;
    body.innerHTML = r.lines.map((t, i) => `<div class="ln"><span class="n">${first + i}</span><span>${qpLine(t)}</span></div>`).join('');
  }
  $('qpFoot').textContent = qpPatka(r);
  body.scrollTop = 0;
  return true;
}

async function openQuickPreview() {
  const f = state.files.find((x) => x.id === state.selFile);
  if (!f || !QP_TYPY.includes(f.ftype)) return;
  $('qp').hidden = false;
  if (!(await qpLoad(f)) && $('qpBody').innerHTML === '') $('qp').hidden = true;
}

function closeQuickPreview() {
  $('qp').hidden = true;
  $('qpBody').innerHTML = '';
  qpFile = null;
  qpTok++;
}

// ↑ ↓: ďalší / predchádzajúci súbor v zozname (výber v zozname ide s ním); preskočí typy bez rýchleho náhľadu
async function qpNavigate(krok) {
  if (!qpFile) return;
  let i = state.view.findIndex((x) => x.id === qpFile.id);
  if (i < 0) return;
  for (i += krok; i >= 0 && i < state.view.length; i += krok) {
    if (QP_TYPY.includes(state.view[i].ftype)) {
      selectFile(state.view[i].id, true);
      await qpLoad(state.view[i]);
      return;
    }
  }
}

// ← →: strany PDF alebo listy Excelu
async function qpListuj(krok) {
  if (!qpFile) return;
  if (qpFile.ftype === 'PDF' || qpFile.ftype === 'OBR') await qpLoad(qpFile, Math.max(0, qpStav.page + krok));
  else if (qpFile.ftype === 'XLS') await qpLoad(qpFile, 0, Math.max(0, qpStav.sheet + krok));
}

function bindQuickPreview() {
  $('qpClose').onclick = closeQuickPreview;
  $('qpEditor').onclick = async () => {
    const f = qpFile;
    if (!f) return;
    const r = await api.open_in_editor(f.id);
    if (r && r.ok === false) toast(r.error);
  };
  $('qp').addEventListener('mousedown', (e) => { if (e.target === $('qp')) closeQuickPreview(); });
  document.addEventListener('keydown', (e) => {
    const inField = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement && document.activeElement.tagName);
    if (!$('qp').hidden) {
      if (e.key === ' ' || e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeQuickPreview(); }
      else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); e.stopPropagation(); qpNavigate(e.key === 'ArrowDown' ? 1 : -1); }
      else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { e.preventDefault(); e.stopPropagation(); qpListuj(e.key === 'ArrowRight' ? 1 : -1); }
      return;
    }
    if (e.key === ' ' && !inField && !e.ctrlKey && !e.altKey && !e.metaKey && state.selFile != null && $('aboutDlg').hidden) {
      e.preventDefault();
      openQuickPreview();
    }
  }, true);
}

// --- detail ----------------------------------------------------------------
function renderDetail() {
  const f = state.files.find((x) => x.id === state.selFile);
  if (!f) {
    $('detail').innerHTML = '<div class="detail-empty">Klikni na súbor pre detail.<br>Dvojklik ukáže súbor v strome.</div>';
    return;
  }
  const link = f.target != null;
  const t = state.types[f.ftype] || state.types.OTH;
  $('detail').innerHTML = `
    <div class="preview" id="preview" title="Dvojklik otvorí súbor">
      <span class="pv-msg">Načítavam náhľad…</span>
    </div>
    <div>${badge(f.ftype)} <span style="color:var(--muted);font-size:13px">${esc(t.label)}</span><span class="pv-pages" id="pvPages"></span></div>
    <div>
      <div class="d-name">${esc(f.name)}</div>
      <div class="d-path" title="${esc(f.path)}">${esc(f.path.slice(0, f.path.lastIndexOf('\\') + 1))}</div>
    </div>
    <dl class="d-meta">
      <dt>Zákazník</dt><dd>${esc(f.customer)}</dd>
      <dt>Zákazka</dt><dd>${esc(f.job)}${f.folder ? ' \\ ' + esc(f.folder) : ''}</dd>
      ${link ? `<dt>Odkaz na</dt><dd class="mono d-link">${esc(f.target || 'cieľ sa nedá zistiť')}</dd>` : ''}
      ${state.similar ? `<dt>Podobnosť</dt><dd>${f.query ? 'hľadaný výkres' : `${simPct(f)} %`}</dd>` : ''}
      ${f.ftype === 'NC' ? `<dt>Stav</dt><dd>${f.odl ? '<span class="tag-odl">odladený</span> (priečinok odladené / Zo stroja)' : 'neodladený'}</dd>` : ''}
      <dt>Vlastník</dt><dd><strong>${esc(ownerName(f.owner))}</strong></dd>
      <dt>Vytvorený</dt><dd>${fmtDate(f.created)}</dd>
      <dt>Zmenený</dt><dd>${fmtDate(f.modified)}</dd>
      <dt>Veľkosť</dt><dd>${fmtSize(f.size)}</dd>
    </dl>
    <div class="d-btns">
      <button type="button" class="btn primary" id="btnOpen">Otvoriť</button>
      <button type="button" class="btn" id="btnFolder">Otvoriť priečinok</button>
      ${link && f.target ? '<button type="button" class="btn" id="btnLink" style="flex-basis:100%" title="Ukáže v strome zákazku, na ktorú odkaz ukazuje">Prejsť na cieľ odkazu</button>' : ''}
      ${multiJob() ? '<button type="button" class="btn" id="btnGoto" style="flex-basis:100%">Ukázať v strome</button>' : ''}
      ${f.ftype === 'PDF' && !f.query ? `<button type="button" class="btn btn-icon" id="btnSimilar" style="flex-basis:100%" title="Nájde výkresy s podobnými pohľadmi v celom ${esc(state.meta.root)}">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="8" height="8" rx="1"></rect><rect x="13" y="13" width="8" height="8" rx="1"></rect><path d="M15 3h5a1 1 0 0 1 1 1v5M9 21H4a1 1 0 0 1-1-1v-5"></path></svg>
        Podobné výkresy</button>` : ''}
    </div>
    ${f.ftype === 'NC' ? '<div class="d-tools" id="dTools"><div class="dt-h">Nástroje programu</div><div class="dt-msg">Načítavam…</div></div>' : ''}`;
  $('btnOpen').onclick = () => openFile(f.id);
  $('preview').ondblclick = () => openFile(f.id);
  if (f.ftype === 'NC') loadTools(f);
  $('btnFolder').onclick = () => openFolder(f.id);
  if ($('btnGoto')) $('btnGoto').onclick = () => revealFile(f, false);
  if ($('btnLink')) $('btnLink').onclick = () => gotoLink(f);
  if ($('btnSimilar')) $('btnSimilar').onclick = () => startSimilar(f);
  loadThumb(f.id);
}

// Náhľad – s krátkym oneskorením, aby pri listovaní šípkami nevznikali zbytočné požiadavky
let thumbSeq = 0;
let thumbTimer;
function loadThumb(id) {
  const seq = ++thumbSeq;
  clearTimeout(thumbTimer);
  const sf = state.files.find((x) => x.id === id);
  if (sf && (sf.ftype === 'NC' || sf.ftype === 'TXT')) {       // textový náhľad je na Medzerník (rýchly náhľad)
    const b = $('preview');
    if (b) b.innerHTML = '<span class="pv-msg">Rýchly náhľad textu:<br><b>Medzerník</b></span>';
    return;
  }
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
  $('tree').addEventListener('keydown', onTreeKey);
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
  const runSearch = debounce(() => { refresh(); updateFolderMenu(); }, 200);
  $('q').addEventListener('input', () => {
    state.q = $('q').value.trim();
    $('qClear').hidden = !$('q').value;
    leaveSimilar();
    runSearch();
  });
  $('q').addEventListener('keydown', async (e) => {
    const menu = !$('fmenu').hidden;
    if (e.key === 'Escape') {
      if (menu) closeFolderMenu(); else clearSearch();   // prvé Esc zavrie menu, druhé vymaže
      e.stopPropagation();
      return;
    }
    if (!menu) return;
    // otvorené menu zákaziek: šípky a Enter patria jemu (nie zoznamu súborov)
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      e.stopPropagation();
      const n = fmenu.items.length;
      fmenu.cur = (fmenu.cur + (e.key === 'ArrowDown' ? 1 : -1) + n) % n;
      renderFolderMenu();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      e.stopPropagation();   // inak by Enter otvoril vybraný súbor
      await chooseFolder(fmenu.cur);
    }
  });
  // menu zákaziek: klik (mousedown, aby pole hľadania nestratilo fokus skôr)
  $('fmenu').addEventListener('mousedown', (e) => {
    e.preventDefault();
    const b = e.target.closest('.fm-item');
    if (b) chooseFolder(Number(b.dataset.i));
  });
  $('q').addEventListener('focus', () => { if (state.q) updateFolderMenu(); });
  $('q').addEventListener('blur', closeFolderMenu);
  window.addEventListener('resize', closeFolderMenu);
  $('qClear').addEventListener('click', () => { clearSearch(); $('q').focus(); });
  $('stReload').addEventListener('click', reloadData);

  // filtre
  bindOwnerDropdown();
  bindViews();
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
  $('listsBadge').addEventListener('click', () => {
    state.lists = false;
    renderListsChip();
    refresh();
  });
  $('bezOdlBadge').addEventListener('click', () => setBezOdl(null));
  $('odlHead').addEventListener('click', () => {
    if ($('odlHead').disabled) return;
    state.odladene = !state.odladene;
    renderListsChip();
    refresh();
  });
  $('odlBadge').addEventListener('click', () => {
    state.odladene = false;
    renderListsChip();
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
  for (const b of document.querySelectorAll('.viewsw button')) {
    b.addEventListener('click', () => setMode(b.dataset.mode));
  }
  $('gallery').addEventListener('click', (e) => {
    const c = e.target.closest('.card');
    if (c && e.ctrlKey) toggleCmp(Number(c.dataset.id));
    if (c) selectFile(Number(c.dataset.id));
  });
  // dvojklik = ukázať v strome (otvoriť: tlačidlo Otvoriť, dvojklik na náhľad, Enter, pravé tlačidlo)
  $('gallery').addEventListener('dblclick', (e) => {
    const c = e.target.closest('.card');
    const f = c && state.files.find((x) => x.id === Number(c.dataset.id));
    if (f) revealFile(f);
  });
  $('gallery').addEventListener('contextmenu', onFileContext);
  $('rows').addEventListener('contextmenu', onFileContext);
  $('tableWrap').addEventListener('scroll', hideCtx);
  $('galleryWrap').addEventListener('scroll', hideCtx);
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
    if (tr && e.ctrlKey) toggleCmp(Number(tr.dataset.id));
    if (tr) selectFile(Number(tr.dataset.id));
  });
  new MutationObserver(applyCmpMarks).observe($('rows'), { childList: true });
  new MutationObserver(applyCmpMarks).observe($('gallery'), { childList: true });
  $('rows').addEventListener('dblclick', (e) => {
    const tr = e.target.closest('tr');
    const f = tr && state.files.find((x) => x.id === Number(tr.dataset.id));
    if (f) revealFile(f);
  });
  document.querySelector('.files thead').addEventListener('contextmenu', onHeadContext);
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
    // F5 / Ctrl+R = obnoviť údaje (nie celú stránku – tá by začala od štartu)
    if (e.key === 'F5' || (e.ctrlKey && (e.key === 'r' || e.key === 'R'))) {
      e.preventDefault();
      reloadData();
      return;
    }
    // Ctrl+G = prepnúť zoznam ↔ galéria
    if (e.ctrlKey && (e.key === 'g' || e.key === 'G')) {
      e.preventDefault();
      setMode(state.mode === 'gallery' ? 'list' : 'gallery');
      return;
    }
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
  // šírky sú CSS premenné – podľa nich sa zarovnáva lišta filtrov a hľadanie (nad zoznamom)
  document.documentElement.style.setProperty(name === 'tree' ? '--tree-w' : '--detail-w', `${w}px`);
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
const COL_DEFAULTS = { ftype: 64, odl: 96, sim: 120, name: 300, folder: 200, owner: 100, created: 98, modified: 98, size: 70 };
const COL_MIN = 40;
// stĺpce, ktoré sa dajú skryť (pravé tlačidlo na hlavičke): kľúč -> [názov, CSS trieda buniek]
const COL_HIDEABLE = {
  ftype: ['Typ', 'c-type'], odl: ['Odladený', 'c-odl'], folder: ['Priečinok', 'c-folder'], owner: ['Vlastník', 'c-owner'],
  created: ['Vytvorený', 'k-created'], modified: ['Zmenený', 'k-modified'], size: ['Veľkosť', 'c-size'],
};
let colW = { ...COL_DEFAULTS };
let colHidden = new Set();
let colDragged = false; // po ťahaní potlačiť klik = triedenie

function applyCols() {
  let sum = 0;
  for (const th of document.querySelectorAll('.files th')) {
    const k = th.dataset.sort;
    if ((k !== 'sim' || state.similar) && !colHidden.has(k)) sum += colW[k];
    th.style.width = k === 'name' ? '' : `${colW[k]}px`;
  }
  document.querySelector('table.files').style.minWidth = `${sum}px`;
  $('colHide').textContent = [...colHidden].map((k) => `.files .${COL_HIDEABLE[k][1]} { display: none; }`).join('\n');
}

function saveCols() {
  lsSet('lupa.cols.v2', JSON.stringify(colW));
  lsSet('lupa.cols.hidden', JSON.stringify([...colHidden]));
}

// pravé tlačidlo na hlavičke tabuľky: zobraziť / skryť stĺpce
function onHeadContext(e) {
  e.preventDefault();
  const items = [{ title: 'Stĺpce' }];
  for (const [k, [label]] of Object.entries(COL_HIDEABLE)) {
    items.push({ text: label, checked: !colHidden.has(k), action: () => {
      colHidden.has(k) ? colHidden.delete(k) : colHidden.add(k);
      applyCols();
      saveCols();
    } });
  }
  items.push('-', ['Predvolené stĺpce', () => {
    colW = { ...COL_DEFAULTS };
    colHidden = new Set();
    applyCols();
    saveCols();
  }]);
  showMenu(e, items);
}

function bindColumns() {
  try {
    // v1.3.2 užšie dátumy a veľkosť – zo starých uložených šírok (lupa.cols) sa tieto nepreberajú
    const old = JSON.parse(lsGet('lupa.cols', 'null') || 'null');
    const saved = JSON.parse(lsGet('lupa.cols.v2', 'null') || 'null');
    if (saved) colW = { ...COL_DEFAULTS, ...saved };
    else if (old) colW = { ...COL_DEFAULTS, ...old, created: COL_DEFAULTS.created, modified: COL_DEFAULTS.modified, size: COL_DEFAULTS.size };
    const hidden = JSON.parse(lsGet('lupa.cols.hidden', '[]') || '[]');
    colHidden = new Set(hidden.filter((k) => k in COL_HIDEABLE));
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
  $('ownerList').innerHTML = items.length ? items.map((o, i) => {
    const sel = o.owner === state.owner;
    const row = `<button type="button" role="option" aria-selected="${sel}" class="dd-item${sel ? ' sel' : ''}${i === ownerCur ? ' cur' : ''}" data-i="${i}">
      <span class="chk">${sel ? ICON_CHECK : ''}</span><span class="nm">${o.owner ? esc(ownerName(o.owner)) : 'Všetci'}</span>${o.n != null ? `<span class="cnt">${o.n.toLocaleString('sk-SK')}</span>` : ''}</button>`;
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
  renderOwnerChip();
  refresh();
}

// štítok „CNC listy ✕“ nad zoznamom – len keď je zapnutý (filtrom)
function renderListsChip() {
  $('listsBadge').hidden = !state.lists;
  $('odlBadge').hidden = !state.odladene;
}

function renderOwnerChip() {
  $('ownerValue').textContent = ownerName(state.owner) || 'Všetci';
  $('ownerChip').classList.toggle('active', !!state.owner);
}

// --- moje filtre: vlastník + typy + hľadanie + rozsah + zoznam/galéria naraz ---------
// Predvolené „Moje …“ sú len počiatočný stav (kým si nikto nič neuloží) – dajú sa prepísať
// aj zmazať; „Obnoviť predvolené“ vráti chýbajúce. '@me' = prihlásený používateľ Windows,
// takže fungujú každému kolegovi bez nastavovania. Filtre sú len v tomto PC (localStorage).
const VIEWS_KEY = 'lupa.views';
const DEFAULT_VIEWS = [
  { name: 'Moje programy', owner: '@me', types: ['HMC', 'ECAM'], q: '', scope: 'all', mode: 'gallery' },
  { name: 'Moje CNC listy', owner: '@me', types: null, q: '', lists: true, scope: 'all', mode: 'gallery' },
];
// predvolený filter z 1.3.7 (len cnc_vyk*.pdf) – nahradiť novým, ak ho používateľ nemenil
const OLD_CNC_VIEW = { name: 'Moje CNC listy', owner: '@me', types: ['PDF'], q: 'cnc_vyk*.pdf', scope: 'all' };
let me = { user: '', owner: '' };   // prihlásený používateľ a jeho tvar v DB (api.whoami)

function userViews() {
  const raw = lsGet(VIEWS_KEY, null);
  if (raw === null) return DEFAULT_VIEWS.map((v) => ({ ...v }));   // ešte nič neuložené
  let list;
  try { list = JSON.parse(raw) || []; } catch (e) { return []; }
  return list.map((v) => (v.name === OLD_CNC_VIEW.name && sameView(v, OLD_CNC_VIEW) ? { ...DEFAULT_VIEWS[1] } : v));
}

function saveUserViews(list) {
  list.sort((a, b) => a.name.localeCompare(b.name, 'sk'));
  lsSet(VIEWS_KEY, JSON.stringify(list));
}

function storeView(name, view) {
  const list = userViews().filter((v) => v.name.toLowerCase() !== name.toLowerCase());
  list.push({ ...view, name });
  saveUserViews(list);
}

// vlastník v DB, ktorý patrí prihlásenému používateľovi ('' = v DB nemá súbory)
function meOwner() {
  return me.owner || '';
}

function viewSummary(v) {
  const who = v.owner === '@me' ? 'ja' : v.owner ? ownerName(v.owner) : 'všetci';
  const types = v.lists ? `CNC listy${v.types ? ` (${v.types.join(' + ')})` : ''}`
    : v.types ? v.types.join(' + ') : 'všetky typy';
  const scope = v.scope === 'all' ? $('scopeAll').textContent : 'aktuálna zákazka';
  return [who, types, v.odladene ? 'len odladené' : '', v.q ? `„${v.q}“` : '', scope, v.mode === 'gallery' ? 'galéria' : 'zoznam']
    .filter(Boolean).join(' · ');
}

function currentView() {
  const all = state.typesOn.size === state.typeKeys.length;
  return {
    owner: state.owner && state.owner === meOwner() ? '@me' : state.owner,
    types: all ? null : state.typeKeys.filter((k) => state.typesOn.has(k)),
    q: state.q, lists: !!state.lists, odladene: !!state.odladene, scope: state.scope, mode: state.mode,
  };
}

// Aktívny filter = uložený, ktorého vlastník, typy, hľadanie a rozsah sa zhodujú s aktuálnymi
// (zoznam/galéria sa nepočíta). Ručná zmena filtrov ho teda „vypne“ sama.
function sameView(a, b) {
  const t = (v) => (v.types ? [...v.types].sort().join(',') : '*');
  return (a.owner || '') === (b.owner || '') && t(a) === t(b) && (a.q || '') === (b.q || '')
    && !!a.lists === !!b.lists && !!a.odladene === !!b.odladene && (a.scope || 'job') === (b.scope || 'job');
}

function activeView() {
  if (state.similar) return null;
  const cur = currentView();
  return userViews().find((v) => sameView(v, cur)) || null;
}

function renderViewsBtn() {
  const v = activeView();
  // zapnuté masky (Len CNC listy / Len odladené programy) rozsvietia tlačidlo, aj keď nejde o uložený filter
  const masky = [state.lists && 'CNC listy', state.odladene && 'Odladené'].filter(Boolean);
  $('viewsLabel').textContent = v ? v.name : (masky.join(' · ') || 'Moje filtre');
  $('viewsBtn').classList.toggle('active', !!v || masky.length > 0);
  $('viewsBtn').title = v ? `Filter „${v.name}“: ${viewSummary(v)} – klik = vypnúť alebo vybrať iný`
    : masky.length ? `Aktívna maska: ${masky.join(' + ')} – klik = zmeniť alebo vypnúť`
      : 'Moje filtre – vlastník, typy, hľadanie, rozsah a zobrazenie naraz';
}

let beforeView = null;   // rozsah a zobrazenie pred zapnutím filtra (vráti ich vypnutie)

// Vypnutie filtra: všetci vlastníci, všetky typy, bez hľadania; rozsah a zobrazenie ako predtým
function clearView() {
  const back = beforeView || { scope: state.sel ? 'job' : 'all', mode: state.mode };
  beforeView = null;
  applyView({ owner: '', types: null, q: '', lists: false, odladene: false, scope: back.scope, mode: back.mode }, true);
}

function applyView(v, restoring = false) {
  if (!restoring && !activeView()) beforeView = { scope: state.scope, mode: state.mode };
  leaveSimilar();
  let owner = v.owner || '';
  if (owner === '@me') {
    owner = meOwner();
    if (!owner) toast(`Používateľ ${me.user || '?'} nemá v databáze žiadne súbory – ukazujem všetkých vlastníkov.`);
  }
  state.owner = owner;
  renderOwnerChip();
  state.typesOn = new Set(v.types ? v.types.filter((k) => state.typeKeys.includes(k)) : state.typeKeys);
  renderChips();
  state.lists = !!v.lists;
  state.odladene = !!v.odladene;
  renderListsChip();
  state.q = v.q || '';
  $('q').value = state.q;
  $('qClear').hidden = !state.q;
  closeFolderMenu();
  state.scope = v.scope === 'job' ? 'job' : 'all';
  renderScope();
  renderTree();
  setMode(v.mode === 'gallery' ? 'gallery' : 'list');
  refresh();
}

function openViewsMenu() {
  const r = $('viewsBtn').getBoundingClientRect();
  const at = { clientX: r.left, clientY: r.bottom + 4 };
  const list = userViews();
  const act = activeView();
  // klik na aktívny filter = vypnúť ho (zobrazí sa zase všetko)
  const items = list.map((v) => ({
    text: v.name, checked: !!act && act.name === v.name,
    action: () => (act && act.name === v.name ? clearView() : applyView(v)),
  }));
  if (items.length) items.push('-');
  // pravidlo „CNC listy“ (config.list_sql) – zapnúť/vypnúť kedykoľvek, uloží sa s filtrom
  items.push({ text: 'Len CNC listy', checked: !!state.lists, action: () => {
    state.lists = !state.lists;
    renderListsChip();
    refresh();
  } });
  // programy v priečinku odlad* (odladene.py) – zapnúť/vypnúť kedykoľvek, uloží sa s filtrom
  items.push({ text: 'Len odladené programy', checked: !!state.odladene, action: () => {
    state.odladene = !state.odladene;
    renderListsChip();
    refresh();
  } });
  items.push({ text: 'Zákazky bez odladeného programu…', checked: state.bezOdl !== null, action: () => {
    if (state.bezOdl !== null) { setBezOdl(null); return; }
    showMenu(at, [{ title: 'Strom len so zákazkami bez odladeného programu' },
      ...[[1, 'zmenené za posledný mesiac'], [3, 'za 3 mesiace'], [6, 'za 6 mesiacov'], [12, 'za rok'], [0, 'všetky (aj staré)']]
        .map(([m, t]) => [t, () => setBezOdl(m)])]);
  } });
  if (state.lists || state.odladene) {
    items.push(['Vypnúť všetky masky', () => {
      state.lists = false;
      state.odladene = false;
      renderListsChip();
      refresh();
    }]);
  }
  items.push('-');
  items.push(['Uložiť aktuálny filter…', () => openViewDialog('')]);
  if (list.length) {
    items.push(['Prepísať filter aktuálnym…', () => {
      showMenu(at, [{ title: 'Prepísať aktuálnym nastavením' }, ...list.map((v) => [v.name, () => {
        storeView(v.name, currentView());
        renderViewsBtn();
        toast(`Filter „${v.name}“ prepísaný:\n${viewSummary(currentView())}`);
      }])]);
    }]);
    items.push(['Zmazať filter…', () => {
      showMenu(at, [{ title: 'Zmazať filter' }, ...list.map((v) => [v.name, () => {
        saveUserViews(userViews().filter((x) => x.name !== v.name));
        renderViewsBtn();
        toast(`Filter „${v.name}“ zmazaný.`);
      }])]);
    }]);
  }
  const names = new Set(list.map((v) => v.name.toLowerCase()));
  const missing = DEFAULT_VIEWS.filter((v) => !names.has(v.name.toLowerCase()));
  if (missing.length) {
    items.push(['Obnoviť predvolené filtre', () => {
      saveUserViews([...userViews(), ...missing.map((v) => ({ ...v }))]);
      toast(`Obnovené: ${missing.map((v) => v.name).join(', ')}`);
    }]);
  }
  showMenu(at, items);
}

function openViewDialog(name) {
  $('viewSum').textContent = viewSummary(currentView());
  $('viewName').value = name || '';
  $('viewDlg').hidden = false;
  $('viewName').focus();
}

function closeViewDialog() {
  $('viewDlg').hidden = true;
}

function bindViews() {
  $('viewsBtn').addEventListener('click', openViewsMenu);
  $('viewCancel').addEventListener('click', closeViewDialog);
  $('viewDlg').addEventListener('mousedown', (e) => { if (e.target === $('viewDlg')) closeViewDialog(); });
  $('viewName').addEventListener('keydown', (e) => {
    e.stopPropagation();   // šípky / Enter / Esc nepatria zoznamu súborov
    if (e.key === 'Escape') closeViewDialog();
  });
  $('viewForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const name = $('viewName').value.trim();
    if (!name) { $('viewName').focus(); return; }
    storeView(name, currentView());   // rovnaký názov = prepísať
    renderViewsBtn();
    closeViewDialog();
    toast(`Filter „${name}“ uložený.`);
  });
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
  const off = m.offline
    ? `<span class="stale" title="Databáza ${esc(m.db)} nie je dostupná – Lupa ukazuje údaje z poslednej kópie v počítači">${esc(m.root)} nedostupný – údaje z lokálnej kópie</span> · `
    : '';
  if (!m.db_ok) {
    $('stRight').innerHTML = '<span class="stale">Databáza neexistuje</span>';
  } else if (s) {
    const stale = Date.now() / 1000 - s.finished > m.stale_hours * 3600;
    const txt = `Posledný sken: ${fmtDate(s.finished)}${s.errors ? ` · chyby ${s.errors}` : ''}`;
    $('stRight').innerHTML = off + (stale
      ? `<span class="stale" title="Údaje môžu byť neaktuálne – sken neprebehol viac ako ${m.stale_hours} h">${esc(txt)}</span>`
      : esc(txt));
  } else {
    $('stRight').innerHTML = off;
  }
}

// --- zvonček „Nové zákazky“ ---------------------------------------------------
// Dve záložky (Api.get_new_jobs):
//   Nové    – zákazka pribudla (vytvorenie priečinka, kto ho založil; jobs.created zo skenera 1.4.0)
//   Začaté  – v zákazke vznikol prvý HMC / PPF / CNC list / odkaz .lnk (kto ho vytvoril = kto robí)
// Číslo = zákazky, ktoré pribudli / začali po poslednom otvorení menu (obe záložky, každá raz).
// Záložka, počet dní a „len moje“ sa pamätajú v tomto PC.
const BELL_DAYS = [1, 3, 7, 14];
let bell = { ok: false, jobs: [], started: [] };
let bellShownSeen = 0;   // „nevidené“ pri otvorení menu (zvýraznené, kým je menu otvorené)

function bellDays() {
  const def = (state.meta && state.meta.bell_days) || 1;   // predvolené z nastavení (zvoncek_dni)
  const d = Number(lsGet('lupa.bell.days', def));
  return BELL_DAYS.includes(d) ? d : 1;
}

function bellSeen() {
  return Number(lsGet('lupa.bell.seen', 0)) || 0;
}

function bellTab() {
  return lsGet('lupa.bell.tab', 'new') === 'started' ? 'started' : 'new';
}

function bellMine() {
  return lsGet('lupa.bell.mine', '0') === '1' && !!me.owner;
}

// Začaté – pri „len moje“ len tie, kde prvý programový súbor vytvoril prihlásený používateľ
function bellStarted() {
  return bellMine() ? bell.started.filter((j) => j.owner === me.owner) : bell.started;
}

function bellUnseen(seen) {
  const ids = new Set();
  for (const j of bell.jobs) if (j.created > seen) ids.add(j.id);
  for (const j of bellStarted()) if (j.created > seen) ids.add(j.id);
  return ids.size;
}

async function loadBell() {
  try { bell = await api.get_new_jobs(bellDays()); } catch (e) { bell = { ok: false, jobs: [], started: [] }; }
  renderBellBtn();
  if (!$('bellMenu').hidden) renderBellMenu();
}

function daysText(d) {
  return d === 1 ? 'posledný deň' : `posledných ${d} dní`;
}

function renderBellBtn() {
  const btn = $('bell');
  btn.hidden = !(state.meta && state.meta.db_ok);
  const n = bellUnseen(bellSeen());
  $('bellN').hidden = !n;
  $('bellN').textContent = n > 99 ? '99+' : String(n);
  btn.classList.toggle('has', n > 0);
  btn.title = `Za ${daysText(bellDays())}: nové zákazky ${bell.ok ? bell.jobs.length : '–'}, ` +
    `začaté ${bellStarted().length}` + (n ? ` (nevidené ${n})` : '');
}

// Kedy: dnes / včera s časom, inak dátum
function bellWhen(ts) {
  const d = new Date(ts * 1000);
  const t = fmtDate(ts).slice(11);
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(new Date()) - day(d)) / 86400000);
  return diff === 0 ? `dnes ${t}` : diff === 1 ? `včera ${t}` : fmtDay(ts);
}

// Čím sa začalo: HMC / ECAM ako v zozname, CNC list farbou Excelu, odkaz sivo
function kindBadge(kind) {
  if (kind === 'LIST') {
    const t = state.types.XLS || state.types.OTH;
    return `<span class="badge" style="background:${t.bg};color:${t.fg}">LIST</span>`;
  }
  if (kind === 'LNK') {
    const t = state.types.OTH;
    return `<span class="badge" style="background:${t.bg};color:${t.fg}">ODKAZ</span>`;
  }
  return badge(kind);
}

const KIND_NAME = { HMC: 'hyperMILL', ECAM: 'Edgecam', LIST: 'CNC list', LNK: 'odkaz na staré heslo' };

function bellRow(j, i, seen, started) {
  const f = findJob(j.id);
  const who = started ? j.owner : j.added_by;
  const whoTxt = who && who !== '?' ? ownerName(who) : '';
  const tip = started
    ? `${j.customer} \\ ${j.name}\nZačaté ${fmtDate(j.created)} – ${KIND_NAME[j.kind] || j.kind}: ${j.rel ? j.rel + '\\' : ''}${j.file}` +
      (whoTxt ? `\nRobí ${whoTxt}` : '') + '\nKlik = otvoriť zákazku a označiť tento súbor'
    : `${j.customer} \\ ${j.name}\nPribudla ${fmtDate(j.created)}` + (whoTxt ? `, založil ${whoTxt}` : '');
  return `<button type="button" class="dd-item fm-item${j.created > seen ? ' unseen' : ''}" data-i="${i}" title="${esc(tip)}">` +
    `<span class="nm">${esc(j.name)}</span><span class="fm-sub">${esc(j.customer)}</span>` +
    (started ? `<span class="bm-kind">${kindBadge(j.kind)}</span>` : '') +
    `<span class="bm-by">${esc(whoTxt)}</span>` +
    `<span class="bm-when">${esc(bellWhen(j.created))}</span>${f ? complStatus(f.job.missing) : '<span class="st"></span>'}</button>`;
}

function renderBellMenu() {
  const box = $('bellMenu');
  const d = bellDays();
  const tab = bellTab();
  const seen = bellShownSeen;
  const started = bellStarted();
  const tabBtn = (key, label, n) =>
    `<button type="button" data-tab="${key}" class="${tab === key ? 'on' : ''}">${label}<span class="bm-cnt">${n}</span></button>`;
  const out = [
    '<div class="bm-top">' +
    `<span class="bm-seg bm-tabs">${tabBtn('new', 'Nové', bell.ok ? bell.jobs.length : '–')}${tabBtn('started', 'Začaté', started.length)}</span>` +
    '<span class="bm-seg bm-days" title="Za koľko dní dozadu">' +
    BELL_DAYS.map((x) => `<button type="button" data-days="${x}" class="${x === d ? 'on' : ''}">${x} ${x === 1 ? 'deň' : x <= 4 ? 'dni' : 'dní'}</button>`).join('') +
    '</span></div>',
  ];
  if (tab === 'started') {
    out.push('<div class="bm-sub"><span>Prvý HMC, PPF, CNC list alebo odkaz na staré heslo v zákazke</span>' +
      (me.owner ? `<button type="button" class="bm-mine${bellMine() ? ' on' : ''}" data-mine="1" title="Len zákazky, ktoré som začal ja (${esc(ownerName(me.owner))})">` +
        `<span class="ctx-chk">${bellMine() ? ICON_CHECK : ''}</span>len moje</button>` : '') + '</div>');
  } else {
    out.push('<div class="bm-sub"><span>Pribudol priečinok zákazky na disku</span></div>');
  }
  const list = tab === 'started' ? started : bell.jobs;
  if (tab === 'new' && !bell.ok) {
    out.push('<div class="bm-empty">Nové zákazky ukáže až nový skener (na PC so skenerom spusti znova ikona_skenu.bat).</div>');
  } else if (!list.length) {
    out.push(`<div class="bm-empty">Za ${daysText(d)} ${tab === 'started' ? 'sa nezačala žiadna zákazka' : 'nepribudla žiadna zákazka'}.</div>`);
  }
  list.forEach((j, i) => out.push(bellRow(j, i, seen, tab === 'started')));
  if (list.length >= 300) out.push('<div class="fm-more">… zobrazených najviac 300</div>');
  out.push('<div class="fm-hint">Klik = otvoriť v strome · Esc zavrieť</div>');
  box.innerHTML = out.join('');
  const r = $('bell').getBoundingClientRect();
  const w = Math.min(560, window.innerWidth - 16);
  box.style.width = `${w}px`;
  box.style.left = `${Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8))}px`;
  box.style.top = `${r.bottom + 6}px`;
  box.hidden = false;
}

function openBell() {
  bellShownSeen = bellSeen();
  const newest = Math.max(bellShownSeen, ...bell.jobs.map((j) => j.created || 0),
    ...bellStarted().map((j) => j.created || 0));
  lsSet('lupa.bell.seen', String(newest));   // otvorením sú všetky videné (číslo zmizne)
  $('bell').classList.add('open');
  renderBellMenu();
  renderBellBtn();
}

function closeBell() {
  $('bellMenu').hidden = true;
  $('bell').classList.remove('open');
}

function bindBell() {
  $('bell').onclick = () => ($('bellMenu').hidden ? openBell() : closeBell());
  $('bellMenu').addEventListener('click', async (e) => {
    const dd = e.target.closest('[data-days]');
    if (dd) {
      lsSet('lupa.bell.days', dd.dataset.days);
      await loadBell();
      return;
    }
    const tb = e.target.closest('[data-tab]');
    if (tb) { lsSet('lupa.bell.tab', tb.dataset.tab); renderBellMenu(); return; }
    if (e.target.closest('[data-mine]')) {
      lsSet('lupa.bell.mine', bellMine() ? '0' : '1');
      renderBellMenu();
      renderBellBtn();
      return;
    }
    const b = e.target.closest('.fm-item');
    if (!b) return;
    const started = bellTab() === 'started';
    const j = (started ? bellStarted() : bell.jobs)[Number(b.dataset.i)];
    closeBell();
    if (!findJob(j.id)) { toast('Zákazka v strome nie je – obnov údaje (F5)'); return; }
    clearSearchQuiet();
    if (started) {
      state.selFile = j.file_id;   // označiť súbor, ktorým sa začalo
      await gotoJob(j.id, j.rel || '');
    } else {
      await gotoJob(j.id, '');
    }
  });
  document.addEventListener('mousedown', (e) => {
    if (!$('bellMenu').hidden && !e.target.closest('#bellMenu, #bell')) closeBell();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('bellMenu').hidden) { e.stopPropagation(); closeBell(); }
  }, true);
  window.addEventListener('resize', closeBell);
}

// --- O programe (klik na „Lupa“ vľavo hore) -----------------------------------
let aboutText = '';

async function openAbout() {
  let a = {};
  try { a = await api.get_about(); } catch (e) { /* aspoň verzia z meta */ }
  const m = state.meta || {};
  $('aboutVer').textContent = a.version || m.version || '';
  const s = m.last_scan;
  const rows = [
    ['Zostavenie', a.build ? a.build.split('+')[1] || a.build : 'vývojová verzia (python)'],
    ['Koreň', a.root || m.root],
    ['Databáza', a.db ? `${a.db}${a.db_size ? ` (${fmtSize(a.db_size)})` : ''}` : ''],
    ['Lokálna kópia', a.local || '–'],
    ['Nastavenia', a.ini || ''],
    ['Posledný sken', s ? fmtDate(s.finished) : '–'],
    ['Používateľ', me.user ? `${me.user}${me.owner && me.owner !== me.user ? ` (v DB ${me.owner})` : ''}` : '–'],
  ];
  $('aboutTech').innerHTML = rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v || '')}</dd>`).join('');
  aboutText = [`Lupa ${a.version || m.version}`, ...rows.map(([k, v]) => `${k}: ${v || ''}`)].join('\n');
  $('aboutDlg').hidden = false;
  $('aboutClose').focus();
}

// --- hľadanie v obsahu NC programov (samostatné okno) -------------------------------------
// Výber v strome (zákazník / zákazka) sa predvyplní do poľa „Zákazník / zákazka“.
function openContentSearch(ctx) {
  let c = ctx;
  if (!c && state.sel) {
    if (state.sel.job) {
      const f = findJob(state.sel.job);
      if (f) c = { customer_id: f.cust.id, job_id: f.job.id, label: `${f.cust.name} \\ ${f.job.name}` };
    } else {
      const cu = findCust(state.sel.cust);
      if (cu) c = { customer_id: cu.id, job_id: null, label: cu.name };
    }
  }
  api.open_content_search(c || {});
}

function closeAbout() {
  $('aboutDlg').hidden = true;
}

function bindAbout() {
  $('brand').onclick = openAbout;
  $('settingsBtn').onclick = () => api.open_settings();
  $('obsahBtn').onclick = () => openContentSearch();
  bindQuickPreview();
  bindToolList();
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.shiftKey && (e.key === 'F' || e.key === 'f')) { e.preventDefault(); openContentSearch(); }
  });
  $('aboutClose').onclick = closeAbout;
  $('aboutCopy').onclick = async () => {
    const r = await api.copy_text(aboutText);
    toast(r.ok ? 'Údaje skopírované' : r.error);
  };
  $('aboutDlg').addEventListener('mousedown', (e) => { if (e.target === $('aboutDlg')) closeAbout(); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('aboutDlg').hidden) { e.stopPropagation(); closeAbout(); }
  }, true);
}

// --- obnovenie údajov bez reštartu --------------------------------------------
// Skener zverejní novú DB → kópia sa na pozadí vymení (dbcopy), strom v okne je ale zo štartu.
// Každých UPDATE_EVERY ms sa zistí, či je nová kópia (tlačidlo Obnoviť zmodrie) a či je
// na L:\_Nastroje\lupa nová verzia Lupy (upozornenie – treba ju zavrieť a spustiť znova).
const UPDATE_EVERY = 30000;
let dbTag = null;
let reloading = false;

async function checkUpdates() {
  let u;
  try { u = await api.check_updates(); } catch (e) { return; }
  const isNew = !!(dbTag && u.db && u.db !== dbTag);
  if (isNew && !$('stReload').classList.contains('new')) loadBell();   // nové zákazky hneď na zvončeku
  $('stReload').classList.toggle('new', isNew);
  $('stReloadText').textContent = isNew ? 'Nové údaje – Obnoviť' : 'Obnoviť';
  $('stReload').title = isNew ? 'Skener medzitým aktualizoval databázu – načítať nové údaje (F5)'
    : 'Načítať znova údaje z databázy (F5)';
  const ver = u.app ? u.app.split('+')[0] : '';
  $('stUpdate').textContent = u.app ? `Nová verzia Lupy ${ver} – zavri Lupu a spusti ju znova` : '';
  $('stUpdate').title = u.app ? `Na disku je zostavenie ${u.app}, beží ${state.meta.version}.` : '';
  if (state.meta && u.offline !== state.meta.offline) { state.meta.offline = u.offline; renderStatus(); }
}

// Načíta znova strom, vlastníkov, počty a zoznam; výber, rozbalenie a filtre ostanú.
async function reloadData() {
  if (reloading || !state.meta || !state.meta.db_ok) return;
  reloading = true;
  $('stReload').classList.add('busy');
  try {
    const meta = await api.get_meta();
    state.meta = meta;
    ownersKey = null;
    await loadOwners();
    state.tree = await api.get_tree();
    dbTag = (await api.check_updates()).db;
    state.positions = {};
    jobLinks.clear();
    jobMachines.clear();
    const custIds = new Set(state.tree.map((c) => c.id));
    const jobIds = new Set(state.tree.flatMap((c) => c.jobs.map((j) => j.id)));
    state.openCust = new Set([...state.openCust].filter((id) => custIds.has(id)));
    state.openJobs = new Set([...state.openJobs].filter((id) => jobIds.has(id)));
    if (state.sel && !(state.sel.job ? jobIds.has(state.sel.job) : custIds.has(state.sel.cust))) state.sel = null;
    // priečinky otvorených zákaziek (a vybranej) treba načítať z novej DB
    const need = new Set(state.openJobs);
    if (state.sel && state.sel.job) need.add(state.sel.job);
    await Promise.all([...need].map(ensurePositions));
    renderTree();
    renderScope();
    await refresh();
    renderStatus();
    loadBell();
    $('stReload').classList.remove('new');
    $('stReloadText').textContent = 'Obnoviť';
    toast(`Údaje obnovené – ${state.meta.counts ? state.meta.counts.jobs.toLocaleString('sk-SK') + ' zákaziek' : 'hotovo'}`);
  } catch (e) {
    toast(`Obnovenie zlyhalo: ${(e && (e.message || e.toString())) || 'neznáma chyba'}`);
  } finally {
    reloading = false;
    $('stReload').classList.remove('busy');
  }
}

// --- priebeh načítania pri štarte (pásik nad stavovým riadkom) --------------
// Kopírovanie DB má skutočné percentá; ostatné kroky sú jeden dotaz, tam sa pásik
// v rámci dielu kroku pomaly posúva, aby nestál.
let loadTimer = null;

function setBar(f) {
  $('stProgressBar').style.width = `${(Math.min(1, f) * 100).toFixed(1)}%`;
}

function loadText(text) {
  $('stLeft').innerHTML = `<span class="loading">${esc(text)}</span>`;
}

function loadStep(text, from, to) {
  clearInterval(loadTimer);
  $('stProgress').hidden = false;
  $('stRight').textContent = '';
  loadText(text);
  let p = from;
  setBar(p);
  loadTimer = setInterval(() => { p += (to - p) * 0.1; setBar(p); }, 200);
}

function loadDone() {
  clearInterval(loadTimer);
  setBar(1);
  setTimeout(() => { $('stProgress').hidden = true; setBar(0); }, 400);
}

// Lokálna kópia DB – kopíruje sa len po novom skene. Vráti podiel pásika, kde kopírovanie skončilo.
async function prepareDb() {
  const COPY = 0.7;   // kopírovanie = 70 % pásika (ak sa kopíruje)
  loadStep('Kontrolujem databázu…', 0, 0.03);
  let copied = false;
  let done = false;
  const poll = setInterval(async () => {
    const p = await api.db_progress();
    if (done || !p || !p.total) return;
    if (!copied) { copied = true; clearInterval(loadTimer); }
    const f = p.done / p.total;
    const mb = (b) => Math.round(b / 1048576);
    loadText(`Kopírujem databázu do počítača… ${Math.round(f * 100)} % (${mb(p.done)} / ${mb(p.total)} MB)`);
    setBar(0.03 + f * (COPY - 0.03));
  }, 150);
  try {
    const r = await api.prepare_db();
    // aj krátke kopírovanie (medzi dvoma kontrolami priebehu) = kopírovalo sa
    if (r.seconds >= 0.3) copied = true;
  } finally {
    done = true;
    clearInterval(poll);
  }
  return copied ? COPY : 0.05;
}

function clearSearch() {
  $('q').value = '';
  $('qClear').hidden = true;
  closeFolderMenu();
  if (state.q) { state.q = ''; refresh(); }
}

// Vymaže hľadanie bez obnovenia zoznamu (obnoví ho nasledujúci výber v strome)
function clearSearchQuiet() {
  $('q').value = '';
  $('qClear').hidden = true;
  closeFolderMenu();
  state.q = '';
}

// Chyba pri štarte (napr. DB sa nedá otvoriť) – ukázať v okne, nie nechať prázdne
async function init() {
  try {
    await initApp();
  } catch (e) {
    clearInterval(loadTimer);
    $('stProgress').hidden = true;
    $('stLeft').textContent = '';
    const msg = (e && (e.message || e.toString())) || 'neznáma chyba';
    $('empty').hidden = false;
    $('empty').textContent = `Lupa sa nepodarilo načítať: ${msg}`;
    $('heading').textContent = 'Chyba';
  }
}

async function initApp() {
  api = window.pywebview.api;
  // pásik: b = koniec kopírovania, potom podľa merania meta ~15 %, vlastníci ~5 %, strom ~80 %
  const b = await prepareDb();
  const at = (f) => b + (1 - b) * f;
  loadStep('Načítavam databázu…', at(0), at(0.15));
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
  if (!meta.db_ok) {
    loadDone();
    renderStatus();
    $('empty').textContent = `Databáza sa nenašla: ${meta.db} – spusti najprv scanner.py.`;
    return;
  }
  loadStep('Načítavam vlastníkov…', at(0.15), at(0.2));
  await loadOwners();
  try { me = (await api.whoami()) || me; } catch (e) { /* bez „Moje …“ */ }
  loadStep('Načítavam strom zákaziek…', at(0.2), at(0.97));
  state.tree = await api.get_tree();
  if (state.tree.length === 1) state.openCust.add(state.tree[0].id);
  renderTree();
  renderHead();
  renderFiles();
  loadDone();
  renderStatus();
  $('q').focus();
  try {   // `Lupa.exe --hladat <text>` (napr. z NC Nástrojov): vyplniť hľadanie a spustiť ho
    const start = await api.get_start();
    if (start && start.hladat) {
      $('q').value = start.hladat;
      $('q').dispatchEvent(new Event('input'));
    }
  } catch (e) { /* bez parametrov */ }
  loadBell();
  dbTag = (await api.check_updates()).db;
  checkUpdates();
  setInterval(checkUpdates, UPDATE_EVERY);
}

bind();
bindBell();
bindAbout();
bindResizers();
bindColumns();
window.addEventListener('pywebviewready', init);
