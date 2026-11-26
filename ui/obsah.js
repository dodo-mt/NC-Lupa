'use strict';
// Okno „Hľadať v obsahu programov“ – ObsahApi v app.py, hľadanie beží v obsah.py (vlákna, zastaviteľné).
// Postup: zostaví sa výber (skupiny, zákazník, obdobie, vlastník) -> odhad (koľko súborov / MB) ->
// pri veľkom výbere potvrdenie -> start -> poll každých 250 ms (nové nálezy + priebeh).

let api = null;
let init = null;
let sel = { customer_id: null, job_id: null };   // vybraný z návrhov (inak sa hľadá podľa písaného textu)
let selLabel = '';
let hits = [];
let selIdx = -1;
let next = 0;
let timer = null;
let running = false;
let estTimer = null;
let sugIdx = -1;
let sugItems = [];
let hlRx = null;

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const GKEY = 'lupa.obsah.groups';

function msg(t) { $('obMsg').textContent = t || ''; }
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function fmtMb(mb) { return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`; }
function nf(n) { return Number(n).toLocaleString('sk-SK'); }

function groupsOn() {
  return [...document.querySelectorAll('.ob-g[aria-pressed="true"]')].map((b) => b.dataset.key);
}

function params() {
  const p = {
    q: $('obQ').value.trim(),
    regex: document.querySelector('input[name="obMode"]:checked').value === 'regex',
    case: $('obCase').checked,
    groups: groupsOn(),
    days: Number($('obDays').value) || 0,
    owner: $('obMine').checked ? init.owner : '',
  };
  const text = $('obScope').value.trim();
  if (sel.job_id || sel.customer_id) {
    if (text === selLabel) { p.customer_id = sel.customer_id; p.job_id = sel.job_id; } else { p.scope_text = text; }
  } else if (text) {
    p.scope_text = text;
  }
  return p;
}

// --- skupiny ------------------------------------------------------------------
function buildGroups() {
  let on;
  try { on = JSON.parse(localStorage.getItem(GKEY) || 'null'); } catch (e) { on = null; }
  if (!Array.isArray(on) || !on.length) on = [init.groups[0].key];
  $('obGroups').innerHTML = init.groups.map((g) =>
    `<button type="button" class="ob-g" data-key="${g.key}" aria-pressed="${on.includes(g.key)}" title="Prípony: ${esc(g.exts.map((e) => '.' + e).join(' '))}">${esc(g.label)} <small>${esc(g.exts.map((e) => '.' + e).join(' '))}</small></button>`
  ).join('');
  document.querySelectorAll('.ob-g').forEach((b) => {
    b.onclick = () => {
      b.setAttribute('aria-pressed', b.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
      localStorage.setItem(GKEY, JSON.stringify(groupsOn()));
      updateEstimate();
    };
  });
}

// --- odhad -----------------------------------------------------------------------
async function updateEstimate() {
  const el = $('obEst');
  if (!groupsOn().length) { el.className = 'ob-est warn'; el.textContent = 'Vyber aspoň jednu skupinu programov.'; return null; }
  const e = await api.estimate(params());
  let t = `Prehľadá sa ${nf(e.files)} súborov (${fmtMb(e.mb)}).`;
  if (e.skipped) t += ` ${nf(e.skipped)} súborov nad ${init.max_mb} MB sa preskočí.`;
  el.className = 'ob-est' + (e.confirm ? ' warn' : '');
  el.textContent = t + (e.confirm ? ' Hľadanie môže trvať dlho – zúž ho zákazníkom.' : '');
  return e;
}
const updateEstimateSoon = debounce(updateEstimate, 250);

// --- zákazník / zákazka (návrhy) ---------------------------------------------------
function hideSug() { $('obSug').hidden = true; sugIdx = -1; }
async function showSug() {
  const q = $('obScope').value.trim();
  if (q === selLabel || q.length < 2) { hideSug(); return; }
  sugItems = await api.suggest(q);
  if (!sugItems.length) { hideSug(); return; }
  $('obSug').innerHTML = sugItems.map((s, i) => `<div data-i="${i}"><span>${esc(s.label)}</span><small>${s.kind}</small></div>`).join('');
  $('obSug').hidden = false;
  sugIdx = -1;
  $('obSug').querySelectorAll('div').forEach((d) => { d.onmousedown = (e) => { e.preventDefault(); pickSug(Number(d.dataset.i)); }; });
}
const showSugSoon = debounce(showSug, 200);
function pickSug(i) {
  const s = sugItems[i];
  if (!s) return;
  sel = { customer_id: s.customer_id, job_id: s.job_id };
  selLabel = s.label;
  $('obScope').value = s.label;
  hideSug();
  updateEstimate();
}
function moveSug(d) {
  const rows = [...$('obSug').querySelectorAll('div')];
  if (!rows.length) return;
  sugIdx = (sugIdx + d + rows.length) % rows.length;
  rows.forEach((r, i) => r.classList.toggle('on', i === sugIdx));
  rows[sugIdx].scrollIntoView({ block: 'nearest' });
}

// Kontext z hlavného okna Lupy (vybraný zákazník / zákazka v strome)
async function aplikujKontext() {
  init = await api.get_init();
  const c = init.ctx || {};
  if (c.label) {
    sel = { customer_id: c.customer_id || null, job_id: c.job_id || null };
    selLabel = c.label;
    $('obScope').value = c.label;
  }
  updateEstimate();
}
window.aplikujKontext = aplikujKontext;

// --- hľadanie ------------------------------------------------------------------------
function highlight(text) {
  const t = String(text ?? '');
  if (!hlRx) return esc(t);
  let out = '';
  let last = 0;
  hlRx.lastIndex = 0;
  let m;
  let guard = 0;
  while ((m = hlRx.exec(t)) && guard++ < 50) {
    if (m[0] === '') { hlRx.lastIndex++; continue; }
    out += esc(t.slice(last, m.index)) + '<mark>' + esc(m[0]) + '</mark>';
    last = m.index + m[0].length;
  }
  return out + esc(t.slice(last));
}

function makeHl(p) {
  try {
    hlRx = new RegExp(p.regex ? p.q : p.q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), p.case ? 'g' : 'gi');
  } catch (e) { hlRx = null; }
}

function rowHtml(h, i) {
  return `<tr data-i="${i}" title="${esc(h.path)}"><td>${esc(h.customer)}</td><td>${esc(h.job)}</td>` +
    `<td>${esc(h.name)}</td><td class="r">${h.line}</td><td class="t">${highlight(h.text)}</td></tr>`;
}

function setRunning(r) {
  running = r;
  $('obGo').disabled = r;
  $('obStop').disabled = !r;
}

async function go() {
  if (running) return;
  const p = params();
  if (!p.q) { msg('Zadaj hľadaný text.'); $('obQ').focus(); return; }
  if (!p.groups.length) { msg('Vyber aspoň jednu skupinu programov.'); return; }
  const e = await api.estimate(p);
  if (!e.files) { msg('Pre tento výber nie sú žiadne súbory.'); return; }
  if (e.confirm) {
    const ok = await confirmDlg(`Prehľadá sa <b>${nf(e.files)} súborov (${fmtMb(e.mb)})</b> priamo na sieťovom disku. Môže to trvať niekoľko minút. Hľadanie môžeš kedykoľvek zastaviť.<br><br>Chceš pokračovať?`);
    if (!ok) return;
  }
  makeHl(p);
  const r = await api.start(p);
  if (!r.ok) { msg(r.error); return; }
  hits = []; next = 0; selIdx = -1;
  $('obRows').innerHTML = '';
  $('obEmpty').hidden = true;
  $('obProg').hidden = false;
  msg('');
  enableActions();
  setRunning(true);
  poll();
}

async function poll() {
  clearTimeout(timer);
  const s = await api.poll(next);
  if (s.hits.length) {
    const start = hits.length;
    hits.push(...s.hits);
    $('obRows').insertAdjacentHTML('beforeend', s.hits.map((h, k) => rowHtml(h, start + k)).join(''));
  }
  next = s.next;
  const pct = s.total ? Math.round((s.scanned / s.total) * 100) : 100;
  $('obFill').style.width = pct + '%';
  let t = `${nf(s.scanned)} / ${nf(s.total)} súborov · ${nf(hits.length)} nálezov v ${nf(s.files_with_hits)} súboroch · ${s.seconds} s`;
  if (s.errors) t += ` · ${nf(s.errors)} súborov sa nedalo prečítať`;
  if (s.done) {
    if (s.limit) t += ` · dosiahnutý limit ${nf(init.max_hits)} nálezov, spresni hľadanie`;
    else if (s.stopped) t += ' · zastavené';
    else t += ' · hotovo';
    setRunning(false);
    if (!hits.length) { $('obEmpty').textContent = 'Nič sa nenašlo.'; $('obEmpty').hidden = false; }
  } else {
    timer = setTimeout(poll, 250);
  }
  $('obProgT').textContent = t;
}

function stop() {
  if (running) api.stop();
}

// --- výber riadka a akcie ---------------------------------------------------------------
function enableActions() {
  const on = selIdx >= 0;
  ['obEditor', 'obOpen', 'obTree', 'obFolder', 'obCopy'].forEach((id) => { $(id).disabled = !on; });
}
function selectRow(i) {
  selIdx = i;
  document.querySelectorAll('#obRows tr.sel').forEach((r) => r.classList.remove('sel'));
  const tr = document.querySelector(`#obRows tr[data-i="${i}"]`);
  if (tr) { tr.classList.add('sel'); tr.scrollIntoView({ block: 'nearest' }); }
  enableActions();
}
const cur = () => hits[selIdx];
async function act(fn) {
  const h = cur();
  if (!h) return;
  const r = await fn(h);
  if (r && r.ok === false) msg(r.error);
}

// NC Editor na nájdenom riadku (bez NC Editora sa súbor otvorí predvoleným programom)
async function openEditor() {
  const h = cur();
  if (!h) return;
  const r = await api.open_in_editor(h.file_id, h.line);
  if (r.ok === false) msg(r.error);
  else if (r.note) msg(r.note + ' Súbor sa otvoril predvoleným programom.');
  else if (!r.line) msg('Tento NC Editor ešte nevie otvoriť riadok – súbor sa otvoril od začiatku (aktualizuj NC Editor).');
  else msg(`Otvorené v NC Editore, riadok ${h.line}`);
}

// --- potvrdzovací dialóg ------------------------------------------------------------------
function confirmDlg(html) {
  return new Promise((resolve) => {
    $('obDlgM').innerHTML = html;
    $('obDlg').hidden = false;
    $('obDlgYes').focus();
    const done = (v) => { $('obDlg').hidden = true; resolve(v); };
    $('obDlgYes').onclick = () => done(true);
    $('obDlgNo').onclick = () => done(false);
  });
}

async function boot() {
  api = window.pywebview.api;
  init = await api.get_init();
  buildGroups();
  const c = init.ctx || {};
  if (c.label) {
    sel = { customer_id: c.customer_id || null, job_id: c.job_id || null };
    selLabel = c.label;
    $('obScope').value = c.label;
  }
  $('obQ').addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
  $('obGo').onclick = go;
  $('obStop').onclick = stop;
  $('obScope').addEventListener('input', () => {
    if ($('obScope').value.trim() !== selLabel) { sel = { customer_id: null, job_id: null }; }
    showSugSoon();
    updateEstimateSoon();
  });
  $('obScope').addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); moveSug(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); moveSug(-1); }
    else if (e.key === 'Enter') {
      if (!$('obSug').hidden && sugIdx >= 0) { e.preventDefault(); pickSug(sugIdx); } else { hideSug(); go(); }
    } else if (e.key === 'Escape' && !$('obSug').hidden) { e.stopPropagation(); hideSug(); }
  });
  $('obScope').addEventListener('blur', () => setTimeout(hideSug, 150));
  ['obDays', 'obMine'].forEach((id) => $(id).addEventListener('change', updateEstimate));
  document.querySelectorAll('input[name="obMode"]').forEach((r) => r.addEventListener('change', () => { $('obQ').placeholder = r.value === 'regex' && r.checked ? 'Regulárny výraz, napr. TOOL CALL (12|13)' : 'Hľadaný text v NC programoch, napr. TOOL CALL 25 alebo M6'; }));
  $('obRows').addEventListener('click', (e) => { const tr = e.target.closest('tr'); if (tr) selectRow(Number(tr.dataset.i)); });
  $('obRows').addEventListener('dblclick', (e) => { const tr = e.target.closest('tr'); if (tr) { selectRow(Number(tr.dataset.i)); openEditor(); } });
  $('obEditor').onclick = openEditor;
  $('obOpen').onclick = () => act((h) => api.open_file(h.file_id));
  $('obTree').onclick = () => act((h) => api.show_in_tree(h.file_id));
  $('obFolder').onclick = () => act((h) => api.open_folder(h.file_id));
  $('obCopy').onclick = () => act(async (h) => { const r = await api.copy_text(h.path); msg(r.ok ? 'Cesta skopírovaná' : r.error); return r; });
  $('obClose').onclick = () => api.close();
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('obDlg').hidden) { $('obDlgNo').click(); return; }
    if (e.key === 'Escape') { if (running) stop(); else api.close(); return; }
    const inField = ['INPUT', 'SELECT'].includes(document.activeElement.tagName);
    if (!inField && hits.length) {
      if (e.key === 'ArrowDown') { e.preventDefault(); selectRow(Math.min(hits.length - 1, selIdx + 1)); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); selectRow(Math.max(0, selIdx - 1)); }
      else if (e.key === 'Enter' && selIdx >= 0) openEditor();
    }
  });
  $('obQ').focus();
  updateEstimate();
}

window.addEventListener('pywebviewready', boot);
