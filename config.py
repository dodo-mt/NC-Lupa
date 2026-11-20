"""Konfigurácia Lupy – cesty, typy súborov, farby, ignorované položky.

Hodnoty ciest sa čítajú z lupa.ini (vedľa programu), inak platia predvolené.
"""
import configparser
import os
import sys
from pathlib import Path

# Priečinok programu (pri PyInstaller exe = priečinok s exe)
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent

INI_PATH = APP_DIR / "lupa.ini"

_DEFAULTS = {
    "root": "L:\\",
    "db": "lupa.db",
    "recent_days": "14",
}


def _load_ini() -> dict:
    cp = configparser.ConfigParser()
    cp.read_dict({"lupa": _DEFAULTS})
    if INI_PATH.exists():
        cp.read(INI_PATH, encoding="utf-8")
    return dict(cp["lupa"])


_ini = _load_ini()


def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (APP_DIR / path)


# Cache náhľadov – lokálne u používateľa, nie na sieti
THUMBS_DIR = Path(os.environ.get("LOCALAPPDATA", str(APP_DIR))) / "Lupa" / "thumbs"

ROOT = _resolve(_ini["root"])
DB_PATH = _resolve(_ini["db"])
RECENT_DAYS = int(_ini["recent_days"])

# ---------------------------------------------------------------------------
# Typy súborov: kľúč -> (popis, prípony, farba pozadia, farba textu)
# Poradie = poradie chipov vo filtri. Prípony malými písmenami, bez bodky.
# ---------------------------------------------------------------------------
FILE_TYPES = {
    "PDF": ("Výkres", ["pdf"], "#fee2e2", "#7f1d1d"),
    "STP": ("Model", ["stp", "step"], "#dbeafe", "#1e3a8a"),
    "HMC": ("hyperMILL", ["hmc"], "#ffedd5", "#7c2d12"),
    "PPF": ("hyperMILL", ["ppf"], "#fef3c7", "#78350f"),
    "NC": ("NC program", ["h", "nc", "mpf", "spf"], "#dcfce7", "#14532d"),
    "XLS": ("Listy", ["xlsx", "xls", "doc", "docx"], "#ccfbf1", "#134e4a"),
    "CREO": ("Creo", ["prt", "drw", "asm"], "#f9ded3", "#8a3517"),
}

# Prípony s číslom verzie na konci (Creo: 612234.prt.5, drw0001.drw.2).
# Skener z nich berie len najvyššiu verziu v priečinku, ext sa ukladá bez verzie.
VERSIONED_EXTS = {"prt", "drw", "asm"}
OTHER_TYPE = ("OTH", "Ostatné", "#f3f4f6", "#374151")

_EXT_TO_TYPE = {ext: key for key, (_, exts, _, _) in FILE_TYPES.items() for ext in exts}


def ftype_for_ext(ext: str) -> str:
    """Prípona (bez bodky, malými) -> kľúč typu."""
    return _EXT_TO_TYPE.get(ext, OTHER_TYPE[0])


# ---------------------------------------------------------------------------
# Čo skener preskakuje (porovnáva sa bez ohľadu na veľkosť písmen)
# ---------------------------------------------------------------------------
# Priečinky kdekoľvek v strome (interné dáta hyperMILL a pod.)
IGNORE_DIRS = {"pof", "vnc", "stock", "3df"}
# Priečinky na 1. úrovni koreňa, ktoré nie sú zákazníci
IGNORE_ROOT_DIRS = {"_lupa", "$recycle.bin", "system volume information"}
# Konkrétne názvy súborov
IGNORE_FILES = {"thumbs.db", "desktop.ini"}
# Prípony súborov
IGNORE_EXTS = {"bak", "hmc_bak", "hypermill", "dwl", "dwl2", "log", "tmp"}
