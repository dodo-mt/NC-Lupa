"""Stroje zákazky – na aký stroj boli robené NC programy.

Zdroje (všetky sa zlúčia, každý stroj raz):
  1. hlavička NC súboru (aj nástrojové listy .h / .nc), riadok „STROJ:“:
       (STROJ: DMU 80 eVo - B/C)      ;STROJ : GMX 250L - SIEMENS 840D      Stroj: DMC 105 - H530
     bez hlavičky znak v obsahu (config.MACHINE_SIGNS – WFL) alebo prípona (.eia = Mazak)
  2. meno CNC listu (config.MACHINE_NAMES – OD…_op20_GMX.xls, …_MAZAK-IG400.pdf)
  3. obsah Excelu (bunka „Názov stroja“ = WFL M40, monoBLOCK - 840D)
  4. cieľ odkazu .lnk na staré heslo – to isté v cieľovom priečinku (štítok „cez odkaz“)
Text sa skráti podľa config.MACHINES (eVo 80, mono H640…) – predvolené pravidlá z modelov v stroje.json (nc_parsery.stroje),
[stroje] v lupa.ini ich prepíše.

Len číta (na L:\\ nič nemení). Výsledok v pamäti podľa cesty + veľkosti + času zmeny.
"""

from __future__ import annotations

import html
import re
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor

import config
import listy
import nc_parsery_cesta  # noqa: F401 – pridá priečinok balíka nc_parsery do sys.path
from nc_parsery import hlavicka

HEAD_BYTES = 4096        # hlavička hyperMILL je v prvých ~10 riadkoch
MAX_FILES = 500          # zákazka s obrovským počtom programov – ďalšie sa nečítajú
MAX_EXCELS = 20          # obsah: najnovšie Excely zákazky
WORKERS = 8              # súbežné čítanie cez sieť
EXCEL_EXTS = {"xls", "xlsx", "xlsm"}

_RULES = [(re.compile(p, re.IGNORECASE), name) for p, name in config.MACHINES]
_SIGNS = [(re.compile(p, re.IGNORECASE), name) for p, name in config.MACHINE_SIGNS]
_NAMES = [(re.compile(p, re.IGNORECASE), name) for p, name in config.MACHINE_NAMES]

_cache: dict[tuple, object] = {}   # (druh, cesta, veľkosť, zmenený) -> výsledok čítania
_lock = threading.Lock()


def _long(p: str) -> str:
    """Prefix \\\\?\\ pre cesty dlhšie ako 260 znakov."""
    if len(p) < 250 or p.startswith("\\\\?\\"):
        return p
    return "\\\\?\\UNC\\" + p[2:] if p.startswith("\\\\") else "\\\\?\\" + p


def read_head(path: str) -> tuple[str | None, str | None]:
    """Zo začiatku súboru: (text za „STROJ:“ bez zátvorky, stroj podľa znaku config.MACHINE_SIGNS).
    (None, None) = nič / nedá sa čítať."""
    try:
        with open(_long(path), "rb") as fh:
            data = fh.read(HEAD_BYTES)
    except OSError:
        return None, None
    text = data.decode("cp1250", errors="replace")
    stroj = hlavicka.stroj_z_hlavicky(text)          # riadok `STROJ:` (nc_parsery.hlavicka)
    if stroj:
        return stroj, None
    for rx, name in _SIGNS:
        if rx.search(text):
            return None, name
    return None, None


def short_name(raw: str) -> str | None:
    """Text -> skratka stroja podľa config.MACHINES, None = žiadne pravidlo nesedí."""
    for rx, name in _RULES:
        if rx.search(raw):
            return name
    return None


def _cells(path: str, ext: str) -> list[str]:
    """Texty buniek Excelu (xlsx/xlsm z XML, starý .xls – úseky textu)."""
    if ext in ("xlsx", "xlsm"):
        out = []
        with zipfile.ZipFile(_long(path)) as z:
            for n in z.namelist():
                low = n.lower()
                if low.startswith(("xl/sharedstrings", "xl/worksheets/sheet")) and low.endswith(".xml"):
                    xml = z.read(n).decode("utf-8", "replace")
                    out += [html.unescape(t) for t in re.findall(r"<t[^>]*>([^<]*)</t>", xml)]
        return out
    from pathlib import Path
    return re.split(r"\s{2,}", listy.text_ole(Path(_long(path))))


def read_excel(path: str, ext: str) -> list[tuple[str, str]]:
    """Stroje v obsahu Excelu: [(skratka, text bunky)]; viac ako MACHINE_CONTENT_MAX = šablóna -> []."""
    try:
        cells = _cells(path, ext)
    except Exception:   # poškodený / zamknutý súbor – bez stroja, nepadať
        return []
    found: dict[str, str] = {}
    for t in cells:
        t = t.strip()
        if 0 < len(t) <= 60:
            n = short_name(t)
            if n and n not in found:
                found[n] = t
    if len(found) > config.MACHINE_CONTENT_MAX:
        return []
    return list(found.items())


def _cached(kind: str, f: dict, fn):
    key = (kind, f["path"], f["size"], f["modified"])
    with _lock:
        if key in _cache:
            return _cache[key]
    val = fn()
    with _lock:
        _cache[key] = val
    return val


def _by_name(docs: list[dict]) -> dict[str, list[str]]:
    """Stroje z mien listov {skratka: [mená]} – Excel aj PDF / Word. Pri spore o rovnaký
    program (Gmx / Gamma) rozhoduje Excel: PDF s Gamma sa neberie, keď Excel hovorí GMX."""
    xls: dict[str, list[str]] = {}
    other: dict[str, list[str]] = {}
    for d in docs:
        found = xls if d["ext"] in EXCEL_EXTS else other
        for rx, name in _NAMES:
            if rx.search(d["name"]):
                found.setdefault(name, []).append(d["name"])
    for base, specs in config.MACHINE_SAME_PROGRAM.items():
        group = {base, *specs}
        if group & xls.keys():
            for name in group - xls.keys():
                other.pop(name, None)
    for name, names in other.items():
        xls.setdefault(name, []).extend(names)
    return xls


def machines(nc_files: list[dict], docs: list[dict], pool: ThreadPoolExecutor) -> dict[str, dict]:
    """Stroje z NC súborov a listov jedného miesta (zákazka / cieľ odkazu).

    nc_files: NC súbory {path, name, ext, size, modified}; docs: Excel / PDF / Word (to isté).
    Vracia {skratka: {name, n (NC súborov), raw (hlavičky), files (NC), lists (listy)}}.
    """
    files = nc_files[:MAX_FILES]
    excels = [d for d in docs if d["ext"] in EXCEL_EXTS][:MAX_EXCELS]
    heads = pool.map(lambda f: _cached("h", f, lambda: read_head(f["path"])), files)
    contents = pool.map(lambda d: _cached("x", d, lambda: read_excel(d["path"], d["ext"])), excels)
    out: dict[str, dict] = {}

    def entry(name):
        return out.setdefault(name, {"name": name, "n": 0, "raw": [], "files": [], "lists": []})

    def add_list(name, doc):
        h = entry(name)
        if doc not in h["lists"]:
            h["lists"].append(doc)

    for f, (raw, sign) in zip(files, heads):
        name = (short_name(raw) or raw) if raw else sign or config.MACHINE_EXTS.get(f["ext"])
        if not name:
            continue
        h = entry(name)
        h["n"] += 1
        if raw and raw not in h["raw"]:
            h["raw"].append(raw)
        if len(h["files"]) < 5:
            h["files"].append(f["name"])

    from_lists: set[str] = set()
    for name, names in _by_name(docs).items():
        for d in names:
            add_list(name, d)
        from_lists.add(name)
    for d, found in zip(excels, contents):
        for name, txt in found:
            add_list(name, f"{d['name']} ({txt})")
            from_lists.add(name)

    # GMX v hlavičke, ale listy hovoria len Gamma -> Gamma (rovnaký program)
    for base, specs in config.MACHINE_SAME_PROGRAM.items():
        hit = [s for s in specs if s in from_lists]
        if base in out and hit and base not in from_lists:
            h = out.pop(base)
            for s in hit:
                out[s]["n"] += h["n"]
                out[s]["raw"] += h["raw"]
                out[s]["files"] += h["files"][:5]
    # Mazak (.eia) + list MAZAK-IG400 -> len IG400
    for base, specs in config.MACHINE_GENERIC.items():
        hit = [s for s in specs if s in out]
        if base in out and hit:
            h = out.pop(base)
            if len(hit) == 1:
                s = out[hit[0]]
                s["n"] += h["n"]
                s["files"] += h["files"][:5]
                s["lists"] += [d for d in h["lists"] if d not in s["lists"]]
    return out


def job_machines(own: tuple[list, list], links: list[tuple[str, list, list]]) -> list[dict]:
    """Stroje zákazky: own = (NC súbory, listy) zákazky, links = [(cieľ odkazu, NC súbory, listy)].
    Stroj len z cieľa odkazu má via = cieľ (v UI bledší). Poradie: vlastné podľa počtu, potom odkazy."""
    with ThreadPoolExecutor(WORKERS) as pool:
        out = machines(*own, pool)
        for target, nc, docs in links:
            for name, h in machines(nc, docs, pool).items():
                if name not in out:
                    out[name] = dict(h, via=target)
    return sorted(out.values(), key=lambda h: (bool(h.get("via")), -h["n"], -len(h["lists"])))
