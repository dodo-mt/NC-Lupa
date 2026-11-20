"""Konfigurácia Lupy – cesty, typy súborov, farby, ignorované položky.

Hodnoty ciest sa čítajú z lupa.ini (vedľa programu), inak platia predvolené.
"""
import configparser
import os
import sys
from pathlib import Path

# Verzia aplikácie – zvyšovať pri každom vydaní (zobrazuje sa v UI, ikone skenu, logu a vo vlastnostiach exe)
VERSION = "1.3.1"

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
    "customers": "",
    "exclude": "",
}


def _load_ini(*paths: Path) -> dict:
    """Predvolené hodnoty prepísané súbormi v poradí (neskorší má prednosť)."""
    cp = configparser.ConfigParser(interpolation=None)
    cp.read_dict({"lupa": _DEFAULTS})
    for p in paths:
        try:
            if p.exists():
                # utf-8-sig: Poznámkový blok / PowerShell môžu uložiť súbor s BOM
                cp.read(p, encoding="utf-8-sig")
        except (OSError, configparser.Error):
            # sieťový disk nedostupný / pokazený súbor – platí to, čo sa načítalo (program nesmie spadnúť)
            pass
    return dict(cp["lupa"])


_ini = _load_ini(INI_PATH)


def _patterns(s: str) -> list[str]:
    """'[0-9]*, OD*' -> ['[0-9]*', 'od*'] (vzory pre fnmatch, malými písmenami)."""
    return [p.strip().lower() for p in s.split(",") if p.strip()]


def scan_settings(db_path: Path) -> dict:
    """Nastavenia skenu: lupa.ini vedľa programu, prepísané lupa.ini vedľa databázy.

    Ikona skenu beží z kópie v %LOCALAPPDATA%\\Lupa\\bin – spoločné nastavenia sú preto
    v L:\\_Lupa\\lupa.ini vedľa DB.
    """
    ini = _load_ini(INI_PATH, db_path.parent / "lupa.ini")
    return {
        "recent_days": int(ini["recent_days"]),
        "prints_minutes": float(ini["prints_minutes"]),
        "customers": _patterns(ini["customers"]),
        "exclude": _patterns(ini["exclude"]),
    }


def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (APP_DIR / path)


# Lokálne dáta používateľa (nie na sieti): cache náhľadov, poloha okien, pracovná kópia DB skenera
LOCAL_DIR = Path(os.environ.get("LOCALAPPDATA", str(APP_DIR))) / "Lupa"
THUMBS_DIR = LOCAL_DIR / "thumbs"

ROOT = _resolve(_ini["root"])
DB_PATH = _resolve(_ini["db"])
# recent_days, prints_minutes, customers, exclude: pre skener cez scan_settings() (aj lupa.ini vedľa DB)
PRINTS_MAX_MB = 100  # odtlačky výkresov: väčšie PDF sa preskočia (obrovské skeny)
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
    "XLS": ("Excel", ["xlsx", "xls"], "#ccfbf1", "#134e4a"),
    "DOC": ("Word", ["doc", "docx"], "#e0e7ff", "#312e81"),
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
    ("Listy", ["XLS", "DOC"], []),
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
