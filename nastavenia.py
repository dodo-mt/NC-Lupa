"""Nastavenia Lupy v okne – čítanie a uloženie lupa.ini (L:\\_Nastroje\\lupa\\lupa.ini, spoločné pre všetkých).

Okno (ui/nastavenia.html) otvára koliesko v Lupe alebo ikona skenu („Nastavenia…“ = Lupa.exe
--nastavenia). Ukladá sa len to, čo sa zmenilo; komentáre a poradie v súbore ostanú, pred zápisom
sa urobí záloha lupa.ini.bak. Meniť smie správca (spravca v lupa.ini) a ikona skenu (beží len
u neho); ostatní vidia nastavenia len na čítanie – ochrana pred omylom, nie zabezpečenie.
"""

from __future__ import annotations

import configparser
import os
import re
import shutil
import time
from pathlib import Path

import config

# Kde sa zmena prejaví
SCAN = "skener – pri ďalšom skene"
TRAY = "ikona skenu – od ďalšieho skenu"
LUPA = "Lupa – po reštarte (u každého)"
BOTH = "skener pri ďalšom skene, Lupa po reštarte (u každého)"

# (kľúč, skupina, popis, druh, nápoveda, kde sa prejaví)
# druh: ro = len na čítanie, int, text
FIELDS = [
    ("root", "Disk a databáza", "Koreň so zákazkami", "ro", "Mení sa len priamo v lupa.ini.", ""),
    ("db", "Disk a databáza", "Databáza", "ro", "Relatívna cesta = voči priečinku s Lupou.", ""),
    ("scan_minutes", "Sken", "Sken každých (min)", "int",
     "Ako často ikona pri hodinách spustí sken. Najmenej 5.", TRAY),
    ("recent_days", "Sken", "Znova skenovať zmeny za (dní)", "int",
     "Inkrementálny sken prejde znova zákazky so zmenou za posledných N dní.", SCAN),
    ("prints_minutes", "Sken", "Odtlačky výkresov (min na sken)", "int",
     "Podobné výkresy: najviac N minút výpočtu na jeden sken. 0 = vypnuté.", SCAN),
    ("listy_minutes", "Sken", "Obsah CNC listov (min na sken)", "int",
     "Čítanie obsahu Wordu / Excelu: najviac N minút na jeden sken. 0 = vypnuté.", SCAN),
    ("customers", "Zákazníci", "Zákazníci (priečinky v koreni)", "text",
     "Vzory oddelené čiarkou: * = čokoľvek, ? = jeden znak, [0-9] = číslica. Prázdne = všetky. "
     "Vynechaný zákazník sa pri ďalšom skene z databázy odstráni (na disku sa nič nemení).", SCAN),
    ("exclude", "Zákazníci", "Vynechať", "text", "Vzory ako vyššie, napr. skryté priečinky a koše.", SCAN),
    ("listy_mena", "CNC listy", "Meno súboru", "text",
     "Word, Excel aj PDF s takýmto menom je CNC list. Vzory oddelené čiarkou.", BOTH),
    ("listy_priecinky", "CNC listy", "PDF v priečinku", "text",
     "PDF v priečinku s takýmto menom je CNC list.", BOTH),
    ("listy_obsah", "CNC listy", "Slová v obsahu", "text",
     "Word / Excel s nejasným menom: aspoň „minimum“ z týchto slov (alebo cesta R:\\…) = CNC list.", SCAN),
    ("listy_obsah_min", "CNC listy", "Minimum slov", "int", "Koľko slov z obsahu musí sedieť.", SCAN),
    ("odladene_priecinky", "Lupa", "Odladené programy – priečinok", "text",
     "NC súbor v priečinku s takýmto menom (kdekoľvek pod zákazkou / pozíciou) je odladený program. "
     "Vzory oddelené čiarkou, predvolene odlad*, zo*stroja* (odladené, Zo stroja).", BOTH),
    ("zvoncek_dni", "Lupa", "Zvonček – predvolené dni", "int",
     "Počiatočná voľba v menu Nové zákazky (1, 3, 7 alebo 14). Každý si ju vie zmeniť.", LUPA),
    ("spravca", "Lupa", "Správca nastavení", "text",
     "Mená Windows oddelené čiarkou – len oni menia nastavenia v Lupe (ikona skenu vždy). "
     "Prázdne = každý.", LUPA),
]
RULES = [
    ("stroje", "Stroje – hlavička programu",
     "Text za „STROJ:“ v hlavičke NC programu (aj obsah Excelu) -> skratka. Prvé pravidlo, ktoré sedí; "
     "výraz je regulárny (\\s = medzera, | = alebo, veľké/malé písmená nehrajú rolu).",
     config.DEFAULT_MACHINES),
    ("stroje_listy", "Stroje – meno CNC listu",
     "Vzor v mene CNC listu (OD…_op20_GMX.xls) -> skratka.", config.DEFAULT_MACHINE_NAMES),
]
RULE_COMMENT = {
    "stroje": "; skratka = regulárny výraz v texte za „STROJ:“ (prvé pravidlo, ktoré sedí) – okno Nastavenia",
    "stroje_listy": "; skratka = regulárny výraz v mene CNC listu – okno Nastavenia",
}
_KEYS = {f[0] for f in FIELDS}


def _user() -> str:
    import getpass
    try:
        return getpass.getuser()
    except Exception:
        return ""


def _read_ini(path: Path) -> dict:
    return config._load_ini(path)   # predvolené + súbor


def read(path: Path, from_tray: bool) -> dict:
    """Hodnoty pre okno + či smie meniť."""
    ini = _read_ini(path)
    admins = [a.strip().lower() for a in ini.get("spravca", "").split(",") if a.strip()]
    user = _user()
    can = from_tray or not admins or user.lower() in admins
    rules = {sec: [{"name": n, "rx": rx} for rx, n in config._load_rules(sec, default, path)]
             for sec, _t, _h, default in RULES}
    return {
        "path": str(path), "exists": path.exists(), "user": user, "can_edit": can,
        "admins": ini.get("spravca", ""),
        "fields": [{"key": k, "group": g, "label": lab, "kind": kind, "help": h, "effect": eff,
                    "value": ini.get(k, "")} for k, g, lab, kind, h, eff in FIELDS],
        "rules": [{"section": sec, "title": t, "help": h, "items": rules[sec],
                   "default": [{"name": n, "rx": rx} for rx, n in default]}
                  for sec, t, h, default in RULES],
    }


def validate(values: dict, rules: dict, from_tray: bool) -> dict:
    """Chyby {kľúč / sekcia: text}."""
    err = {}
    for k, _g, _l, kind, _h, _e in FIELDS:
        if kind != "int" or k not in values:
            continue
        v = str(values[k]).strip()
        if not re.fullmatch(r"\d+", v):
            err[k] = "Zadaj celé číslo."
            continue
        n = int(v)
        if k == "scan_minutes" and n < 5:
            err[k] = "Najmenej 5 minút."
        elif k == "listy_obsah_min" and n < 1:
            err[k] = "Najmenej 1."
        elif k == "zvoncek_dni" and n not in (1, 3, 7, 14):
            err[k] = "Len 1, 3, 7 alebo 14."
    if "spravca" in values and not from_tray:
        admins = [a.strip().lower() for a in str(values["spravca"]).split(",") if a.strip()]
        if admins and _user().lower() not in admins:
            err["spravca"] = f"Nie si v zozname ({_user()}) – po uložení by si nastavenia v Lupe už nezmenil."
    for sec, items in rules.items():
        seen = set()
        for i, it in enumerate(items):
            name, rx = it.get("name", "").strip(), it.get("rx", "").strip()
            if not name and not rx:
                continue
            where = f"{sec}.{i}"
            if not name or not rx:
                err[where] = "Vyplň skratku aj výraz."
            elif re.search(r"[=:\[\];#]", name) or name.startswith(" "):
                err[where] = "Skratka nesmie obsahovať = : [ ] ; #"
            elif name.lower() in seen:
                err[where] = f"Skratka „{name}“ je dvakrát – spoj výrazy cez |."
            else:
                try:
                    re.compile(rx)
                except re.error as e:
                    err[where] = f"Neplatný výraz: {e}"
            seen.add(name.lower())
    return err


def _section_ranges(lines: list[str]) -> dict[str, tuple[int, int]]:
    """{sekcia (malými): (riadok hlavičky, koniec – výlučne)}"""
    out, cur, start = {}, None, 0
    for i, line in enumerate(lines):
        m = re.match(r"\s*\[([^\]]+)\]\s*$", line)
        if m:
            if cur is not None:
                out[cur] = (start, i)
            cur, start = m.group(1).strip().lower(), i
    if cur is not None:
        out[cur] = (start, len(lines))
    return out


def _set_key(lines: list[str], key: str, value: str):
    rng = _section_ranges(lines)
    if "lupa" not in rng:
        lines[0:0] = ["[lupa]", f"{key} = {value}", ""]
        return
    a, b = rng["lupa"]
    rx = re.compile(rf"\s*{re.escape(key)}\s*[=:]", re.IGNORECASE)
    for i in range(a + 1, b):
        if rx.match(lines[i]):
            lines[i] = f"{key} = {value}"
            return
    # nový kľúč na koniec sekcie (pred prázdne riadky na konci)
    j = b
    while j > a + 1 and not lines[j - 1].strip():
        j -= 1
    lines.insert(j, f"{key} = {value}")


def _set_rules(lines: list[str], section: str, items: list[dict]):
    body = [f"{it['name'].strip()} = {it['rx'].strip()}" for it in items
            if it.get("name", "").strip() and it.get("rx", "").strip()]
    rng = _section_ranges(lines)
    if section in rng:
        a, b = rng[section]
        keep = [l for l in lines[a + 1:b] if l.strip().startswith((";", "#"))][:3] or [RULE_COMMENT[section]]
        lines[a:b] = [f"[{section}]", *keep, *body, ""]
    else:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", f"[{section}]", RULE_COMMENT[section], *body, ""]


def save(path: Path, values: dict, rules: dict, from_tray: bool) -> dict:
    """Uloží zmenené hodnoty. Vracia {ok, errors, changed: [(popis, kde sa prejaví)], backup}."""
    data = read(path, from_tray)
    if not data["can_edit"]:
        return {"ok": False, "errors": {"_": "Nastavenia mení len správca."}}
    values = {k: str(v).strip() for k, v in values.items() if k in _KEYS}
    err = validate(values, rules, from_tray)
    if err:
        return {"ok": False, "errors": err}
    old = {f["key"]: f["value"] for f in data["fields"]}
    changed_keys = [k for k, _g, _l, kind, _h, _e in FIELDS
                    if kind != "ro" and k in values and values[k] != str(old.get(k, "")).strip()]
    clean = lambda items: [{"name": i["name"].strip(), "rx": i["rx"].strip()} for i in items   # noqa: E731
                           if i.get("name", "").strip() and i.get("rx", "").strip()]
    old_rules = {r["section"]: r["items"] for r in data["rules"]}
    changed_rules = [sec for sec in rules if sec in old_rules and clean(rules[sec]) != clean(old_rules[sec])]
    if not changed_keys and not changed_rules:
        return {"ok": True, "changed": [], "backup": None}

    try:
        text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    except OSError as e:
        return {"ok": False, "errors": {"_": f"lupa.ini sa nedá čítať: {e}"}}
    lines = text.splitlines()
    if not lines:
        lines = ["; Nastavenia Lupy – mení sa v okne Nastavenia (alebo tu). Vzor: lupa.ini.example", ""]
    for k in changed_keys:
        _set_key(lines, k, values[k])
    for sec in changed_rules:
        _set_rules(lines, sec, clean(rules[sec]))

    backup = None
    try:
        if path.exists():
            backup = path.with_name("lupa.ini.bak")
            shutil.copy2(path, backup)
        tmp = path.with_name(f"lupa.ini.{os.getpid()}.tmp")
        tmp.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
        for i in range(5):   # súbor môže na chvíľu čítať skener / iná Lupa
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if i == 4:
                    raise
                time.sleep(0.3)
    except OSError as e:
        return {"ok": False, "errors": {"_": f"lupa.ini sa nedá zapísať: {e}"}}

    labels = {f[0]: (f[2], f[5]) for f in FIELDS}
    titles = {r[0]: r[1] for r in RULES}
    changed = [labels[k] for k in changed_keys] + [(titles[s], LUPA) for s in changed_rules]
    return {"ok": True, "changed": changed, "backup": str(backup) if backup else None}
