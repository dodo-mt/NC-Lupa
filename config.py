"""Konfigurácia Lupy – cesty, typy súborov, farby, ignorované položky.

Hodnoty ciest sa čítajú z lupa.ini (vedľa programu), inak platia predvolené.
"""
import configparser
import os
import sys
from pathlib import Path

# Verzia aplikácie – zvyšovať pri každom vydaní (zobrazuje sa v UI, ikone skenu, logu a vo vlastnostiach exe)
VERSION = "1.2.0"

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
    "prints_minutes": "30",
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


# Lokálne dáta používateľa (nie na sieti): cache náhľadov, poloha okien, pracovná kópia DB skenera
LOCAL_DIR = Path(os.environ.get("LOCALAPPDATA", str(APP_DIR))) / "Lupa"
THUMBS_DIR = LOCAL_DIR / "thumbs"

ROOT = _resolve(_ini["root"])
DB_PATH = _resolve(_ini["db"])
RECENT_DAYS = int(_ini["recent_days"])
# Odtlačky výkresov (podobné výkresy): najviac N minút výpočtu na jeden sken, 0 = vypnuté.
# Prvý prechod celého L:\ sa tak rozloží do viacerých skenov.
PRINTS_MINUTES = float(_ini["prints_minutes"])
PRINTS_MAX_MB = 100  # väčšie PDF sa preskočia (obrovské skeny)
FULL_EVERY_DAYS = 7  # scanner --auto: úplný sken, ak posledný bol pred viac ako N dňami

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
    "DWG": ("AutoCAD", ["dwg", "dxf"], "#ede9fe", "#4c1d95"),
    "STL": ("Sieťový model", ["stl"], "#e0f2fe", "#0c4a6e"),
    "TIF": ("Obrázok / sken", ["tif", "tiff"], "#fce7f3", "#831843"),
    "TXT": ("Poznámky", ["txt"], "#ecfccb", "#365314"),
}

# Kontrola úplnosti zákazky: (názov, typy, prípony) – stačí ktorýkoľvek typ alebo prípona
COMPLETENESS = [
    ("Model", ["STP", "CREO"], ["catpart"]),
    ("PDF", ["PDF"], []),
    ("CAM", ["HMC", "PPF"], []),
    ("NC", ["NC"], []),
    ("Listy", ["XLS"], []),
]


def missing_parts(ftypes: set, exts: set) -> list[str]:
    """Názvy položiek úplnosti, ktoré v zákazke chýbajú."""
    return [
        name for name, types, ex in COMPLETENESS
        if not (ftypes & set(types) or exts & set(ex))
    ]

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
IGNORE_EXTS = {"bak", "hmc_bak", "hypermill", "dwl", "dwl2", "log", "tmp", "out"}
# Vzory názvov (fnmatch, malými písmenami) – logy z exportu Creo a pod.
IGNORE_GLOBS = ["*.log.*", "*_log.xml"]
