"""Stroje zákazky – na aký stroj boli robené NC programy.

Číta sa začiatok každého NC súboru zákazky (aj nástrojové listy .h / .nc) a riadok „STROJ:“:
  (STROJ: DMU 80 eVo - B/C)      ;STROJ : GMX 250L - SIEMENS 840D      Stroj: DMC 105 - H530
Text sa skráti podľa config.MACHINES (eVo 80, mono H640…), rovnaké stroje sa zlúčia.
Bez hlavičky: prípona (config.MACHINE_EXTS, .eia = Mazak) a meno CNC listu v zákazke
(config.MACHINE_HINTS – Gamma / Gmx, J200 / IG400, WFL).

Len číta (na L:\\ nič nemení). Výsledok v pamäti podľa cesty + veľkosti + času zmeny.
"""

from __future__ import annotations

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import config

HEAD_BYTES = 4096        # hlavička hyperMILL je v prvých ~10 riadkoch
MAX_FILES = 500          # zákazka s obrovským počtom programov – ďalšie sa nečítajú
WORKERS = 8              # súbežné čítanie cez sieť

_STROJ = re.compile(r"STROJ\s*:\s*(.+)", re.IGNORECASE)
_RULES = [(re.compile(p, re.IGNORECASE), name) for p, name in config.MACHINES]
_HINTS = {k: [(re.compile(p, re.IGNORECASE), name) for p, name in v] for k, v in config.MACHINE_HINTS.items()}
_HINT_EXTS = [{"xls", "xlsx", "xlsm"}, {"pdf", "doc", "docx"}]   # najprv Excel, potom ostatné

_cache: dict[tuple, str | None] = {}   # (cesta, veľkosť, zmenený) -> surový text stroja / None
_lock = threading.Lock()


def _long(p: str) -> str:
    """Prefix \\\\?\\ pre cesty dlhšie ako 260 znakov."""
    if len(p) < 250 or p.startswith("\\\\?\\"):
        return p
    return "\\\\?\\UNC\\" + p[2:] if p.startswith("\\\\") else "\\\\?\\" + p


def read_head(path: str) -> str | None:
    """Text za „STROJ:“ zo začiatku súboru (bez zátvorky), None = nie je / nedá sa čítať."""
    try:
        with open(_long(path), "rb") as fh:
            data = fh.read(HEAD_BYTES)
    except OSError:
        return None
    for line in data.decode("cp1250", errors="replace").splitlines():
        m = _STROJ.search(line)
        if m:
            txt = m.group(1).strip().rstrip(")").strip()
            return txt or None
    return None


def short_name(raw: str) -> str:
    """Text z hlavičky -> skratka stroja (neznámy ostane, ako je)."""
    for rx, name in _RULES:
        if rx.search(raw):
            return name
    return raw


def _cached_head(f: dict) -> str | None:
    key = (f["path"], f["size"], f["modified"])
    with _lock:
        if key in _cache:
            return _cache[key]
    raw = read_head(f["path"])
    with _lock:
        _cache[key] = raw
    return raw


def _hint(names: list[dict], rules: list) -> list[str]:
    """Skratky z mien dokumentov – najprv Excely; ak tam nič, PDF / Word."""
    for exts in _HINT_EXTS:
        found = [name for rx, name in rules
                 if any(d["ext"] in exts and rx.search(d["name"]) for d in names)]
        if found:
            return found
    return []


def job_machines(nc_files: list[dict], docs: list[dict]) -> list[dict]:
    """Stroje zákazky.

    nc_files: NC súbory {path, name, ext, size, modified}; docs: Excel / PDF / Word {name, ext}.
    Vracia [{name, n (počet súborov), raw (texty z hlavičiek), files (niekoľko mien)}] podľa počtu.
    """
    files = nc_files[:MAX_FILES]
    with ThreadPoolExecutor(WORKERS) as ex:
        heads = list(ex.map(_cached_head, files))
    out: dict[str, dict] = {}

    def add(name, f, raw=None):
        h = out.setdefault(name, {"name": name, "n": 0, "raw": [], "files": []})
        h["n"] += 1
        if raw and raw not in h["raw"]:
            h["raw"].append(raw)
        if len(h["files"]) < 5:
            h["files"].append(f["name"])

    for f, raw in zip(files, heads):
        if raw:
            add(short_name(raw), f, raw)
        elif f["ext"] in config.MACHINE_EXTS:
            add(config.MACHINE_EXTS[f["ext"]], f)

    # spresnenie podľa mena CNC listu (rovnaký program pre viac strojov / bez hlavičky)
    for base, rules in _HINTS.items():
        if base is None:
            for name in _hint(docs, rules):
                if name not in out:
                    out[name] = {"name": name, "n": 0, "raw": [], "files": [], "by_list": True}
            continue
        if base not in out:
            continue
        found = _hint(docs, rules)
        if found and found != [base]:
            h = out.pop(base)
            for name in found:
                if name in out:
                    out[name]["n"] += h["n"]
                else:
                    out[name] = dict(h, name=name, by_list=True)
    return sorted(out.values(), key=lambda h: -h["n"])
