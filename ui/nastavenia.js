'use strict';
// Okno Nastavenia – hodnoty z lupa.ini (SettingsApi v app.py, nastavenia.py).
// Polia podľa skupín, pravidlá strojov ako riadky „skratka = výraz“ (poradie = priorita).
// Uloží sa len zmenené; kde sa zmena prejaví, povie správa dole.

let api = null;
let data = null;       // z api.get()
let rules = {};        // sekcia -> [{name, rx}] (upravované)
let closing = false;   // druhé „Zavrieť“ pri neuložených zmenách = zahodiť

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ICON_UP = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m18 15-6-6-6 6"></path></svg>';
const ICON_DOWN = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"></path></svg>';
const ICON_X = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"></path></svg>';

function cloneRules(list) {
  return list.map((r) => ({ name: r.name, rx: r.rx }));
}

function fieldValues() {
  const out = {};
  document.querySelectorAll('[data-key]').forEach((el) => { out[el.dataset.key] = el.value; });
  return out;
}

function isDirty() {
  if (!data) return false;
  const v = fieldValues();
  if (data.fields.some((f) => f.kind !== 'ro' && String(v[f.key] ?? '').trim() !== String(f.value ?? '').trim())) return true;
  const norm = (l) => JSON.stringify(l.filter((r) => r.name.trim() || r.rx.trim()).map((r) => [r.name.trim(), r.rx.trim()]));
  return data.rules.some((r) => norm(rules[r.section]) !== norm(r.items));
}

function updateDirty() {
  const dirty = isDirty();
  $('stSave').disabled = !data || !data.can_edit || !dirty;
  document.querySelectorAll('.st-field').forEach((el) => {
    const f = data.fields.find((x) => x.key === el.dataset.field);
    const inp = el.querySelector('input');
    el.classList.toggle('changed', !!f && f.kind !== 'ro' && inp.value.trim() !== String(f.value ?? '').trim());
  });
  if (dirty) { closing = false; msg('Neuložené zmeny', 'warn'); } else if ($('stMsg').classList.contains('warn')) msg('');
}

function msg(text, cls = '') {
  $('stMsg').innerHTML = text;
  $('stMsg').className = `st-msg ${cls}`;
}

function render() {
  const groups = [];
  for (const f of data.fields) {
    let g = groups.find((x) => x.name === f.group);
    if (!g) groups.push(g = { name: f.group, fields: [] });
    g.fields.push(f);
  }
  const ro = !data.can_edit;
  const out = groups.map((g) => `<section class="st-card"><h2>${esc(g.name)}</h2>` +
    g.fields.map((f) => `<div class="st-field" data-field="${f.key}">
      <label for="f_${f.key}">${esc(f.label)}</label>
      <div class="st-inp">
        <input type="text" id="f_${f.key}" data-key="${f.key}" class="${f.kind === 'int' ? 'num' : ''}${f.key === 'root' || f.key === 'db' ? ' mono' : ''}"
          value="${esc(f.value)}" spellcheck="false" autocomplete="off" ${f.kind === 'ro' || ro ? 'disabled' : ''}
          ${f.key === 'spravca' && !f.value ? `placeholder="napr. ${esc(data.user)}"` : ''}>
        <div class="st-h">${esc(f.help)}</div>
        ${f.effect ? `<div class="st-eff">Prejaví sa: ${esc(f.effect)}</div>` : ''}
        <div class="st-err" id="e_${f.key}"></div>
      </div></div>`).join('') + '</section>');
  for (const r of data.rules) out.push(rulesCard(r, ro));
  $('stMain').innerHTML = out.join('');
  document.querySelectorAll('[data-key]').forEach((el) => el.addEventListener('input', updateDirty));
  for (const r of data.rules) bindRules(r.section, ro);
}

function rulesCard(r, ro) {
  return `<section class="st-card" id="card_${r.section}"><h2>${esc(r.title)}</h2>
    <div class="st-help">${esc(r.help)}</div>
    <div class="st-rule-head"><span></span><span>Skratka</span><span>Výraz</span><span></span></div>
    <div class="st-rules" id="rules_${r.section}"></div>
    ${ro ? '' : `<div class="st-row-btns">
      <button type="button" class="btn" data-add="${r.section}">+ Pridať pravidlo</button>
      <button type="button" class="btn" data-def="${r.section}" title="Vrátiť predvolené pravidlá (uloží sa až tlačidlom Uložiť)">Predvolené</button>
    </div>`}
    <div class="st-try"><span>Vyskúšať:</span>
      <input type="text" id="try_${r.section}" spellcheck="false" placeholder="${r.section === 'stroje' ? 'napr. DMU 80 eVo - B/C' : 'napr. OD00019870_op20_MAZAK-IG400.xls'}">
      <span class="st-try-out none" id="tryOut_${r.section}">–</span></div>
  </section>`;
}

function renderRules(section, ro) {
  const list = rules[section];
  const box = $(`rules_${section}`);
  box.innerHTML = list.map((r, i) => `<div class="st-rule" data-i="${i}">
      <span class="st-no">${i + 1}.</span>
      <input type="text" class="nm" value="${esc(r.name)}" spellcheck="false" ${ro ? 'disabled' : ''} aria-label="Skratka">
      <input type="text" class="rx" value="${esc(r.rx)}" spellcheck="false" ${ro ? 'disabled' : ''} aria-label="Výraz">
      <span class="st-rule-tools">${ro ? '' : `
        <button type="button" class="iconbtn" data-act="up" title="Vyššie (skôr)" ${i === 0 ? 'disabled' : ''}>${ICON_UP}</button>
        <button type="button" class="iconbtn" data-act="down" title="Nižšie" ${i === list.length - 1 ? 'disabled' : ''}>${ICON_DOWN}</button>
        <button type="button" class="iconbtn" data-act="del" title="Zmazať">${ICON_X}</button>`}</span>
      <div class="st-rule-err" id="e_${section}.${i}"></div>
    </div>`).join('');
  tryRule(section);
}

function bindRules(section, ro) {
  renderRules(section, ro);
  const box = $(`rules_${section}`);
  box.addEventListener('input', (e) => {
    const row = e.target.closest('.st-rule');
    if (!row) return;
    const r = rules[section][Number(row.dataset.i)];
    if (e.target.classList.contains('nm')) r.name = e.target.value; else r.rx = e.target.value;
    updateDirty();
    tryRule(section);
  });
  box.addEventListener('click', (e) => {
    const b = e.target.closest('[data-act]');
    if (!b) return;
    const list = rules[section];
    const i = Number(b.closest('.st-rule').dataset.i);
    if (b.dataset.act === 'del') list.splice(i, 1);
    else if (b.dataset.act === 'up' && i > 0) [list[i - 1], list[i]] = [list[i], list[i - 1]];
    else if (b.dataset.act === 'down' && i < list.length - 1) [list[i + 1], list[i]] = [list[i], list[i + 1]];
    renderRules(section, ro);
    updateDirty();
  });
  const card = $(`card_${section}`);
  card.querySelector('[data-add]')?.addEventListener('click', () => {
    rules[section].push({ name: '', rx: '' });
    renderRules(section, ro);
    box.querySelector('.st-rule:last-child .nm').focus();
    updateDirty();
  });
  card.querySelector('[data-def]')?.addEventListener('click', () => {
    rules[section] = cloneRules(data.rules.find((r) => r.section === section).default);
    renderRules(section, ro);
    updateDirty();
  });
  $(`try_${section}`).addEventListener('input', () => tryRule(section));
}

// Skúška pravidiel priamo v okne (JavaScript – rovnaké výrazy ako v Pythone pre bežné prípady)
function tryRule(section) {
  const text = $(`try_${section}`).value.trim();
  const out = $(`tryOut_${section}`);
  if (!text) { out.textContent = '–'; out.className = 'st-try-out none'; return; }
  for (const r of rules[section]) {
    if (!r.name.trim() || !r.rx.trim()) continue;
    let rx;
    try { rx = new RegExp(r.rx, 'i'); } catch (e) { continue; }
    if (rx.test(text)) { out.textContent = `→ ${r.name}`; out.className = 'st-try-out'; return; }
  }
  out.textContent = section === 'stroje' ? 'žiadne pravidlo – ukáže sa text, ako je' : 'žiadne pravidlo';
  out.className = 'st-try-out none';
}

async function load() {
  data = await api.get();
  rules = {};
  for (const r of data.rules) rules[r.section] = cloneRules(r.items);
  $('stPath').textContent = `${data.path}${data.exists ? '' : '  (súbor zatiaľ neexistuje – vytvorí sa pri uložení)'}`;
  if (!data.can_edit) {
    $('stNote').hidden = false;
    $('stNote').textContent = `Len na čítanie – nastavenia mení správca (${data.admins}). Prihlásený: ${data.user}.`;
  } else if (data.from_tray) {
    $('stNote').hidden = true;
  }
  render();
  updateDirty();
}

async function save() {
  document.querySelectorAll('.st-err, .st-rule-err').forEach((el) => { el.textContent = ''; });
  document.querySelectorAll('input.bad').forEach((el) => el.classList.remove('bad'));
  $('stSave').disabled = true;
  msg('Ukladám…');
  let r;
  try {
    r = await api.save(fieldValues(), rules);
  } catch (e) {
    r = { ok: false, errors: { _: String(e && (e.message || e)) } };
  }
  if (!r.ok) {
    const errs = r.errors || {};
    for (const [k, v] of Object.entries(errs)) {
      const el = $(`e_${k}`);
      if (el) {
        el.textContent = v;
        const inp = $(`f_${k}`) || el.closest('.st-rule')?.querySelector('input');
        inp?.classList.add('bad');
      }
    }
    msg(errs._ ? esc(errs._) : 'Oprav chyby vyznačené červenou – nič sa neuložilo.', 'bad');
    document.querySelector('.st-err:not(:empty), .st-rule-err:not(:empty)')?.scrollIntoView({ block: 'center' });
    updateDirty();
    return;
  }
  const changed = r.changed || [];
  await load();
  if (!changed.length) { msg('Nič sa nezmenilo.'); return; }
  const where = [...new Set(changed.map((c) => c[1]))];
  msg(`Uložené: ${changed.map((c) => esc(c[0])).join(', ')}.<br>Prejaví sa: ${where.map(esc).join('; ')}.` +
    (r.backup ? ' Záloha: lupa.ini.bak.' : ''), 'ok');
}

function close() {
  if (isDirty() && !closing) {
    closing = true;
    msg('Neuložené zmeny – klikni na Zavrieť ešte raz a zahodia sa, alebo Uložiť.', 'warn');
    return;
  }
  api.close();
}

async function init() {
  api = window.pywebview.api;
  $('stSave').onclick = save;
  $('stClose').onclick = close;
  $('stIni').onclick = async () => {
    const r = await api.open_ini();
    if (!r.ok) msg(`lupa.ini sa nedá otvoriť: ${esc(r.error)}`, 'bad');
  };
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey && e.key.toLowerCase() === 's') && !$('stSave').disabled) { e.preventDefault(); save(); }
    if (e.key === 'Escape') close();
  });
  try {
    await load();
  } catch (e) {
    $('stMain').innerHTML = `<div class="st-loading">Nastavenia sa nepodarilo načítať: ${esc(e && (e.message || e))}</div>`;
  }
}

window.addEventListener('pywebviewready', init);
