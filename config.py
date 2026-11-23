"""Konfigurácia Lupy – cesty, typy súborov, farby, ignorované položky.

Hodnoty ciest sa čítajú z lupa.ini (vedľa programu), inak platia predvolené.
"""
import configparser
import fnmatch
import os
import sys
from pathlib import Path

import listy

# Verzia aplikácie – zvyšovať pri každom vydaní (zobrazuje sa v UI, ikone skenu, logu a vo vlastnostiach exe)
VERSION = "1.5.0"

# Priečinok programu (pri PyInstaller exe = priečinok s exe). Lupa beží z lokálnej kópie
# v %LOCALAPPDATA% (launcher.py) – spúšťač jej v LUPA_HOME odovzdá svoj priečinok (L:\_Lupa),
# kde je lupa.ini a lupa.db.
if os.environ.get("LUPA_HOME"):
    APP_DIR = Path(os.environ["LUPA_HOME"])
elif getattr(sys, "frozen", False):
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
    # CNC listy (listy.py): listy_mena, listy_priecinky, listy_obsah, listy_obsah_min, listy_minutes
    **listy.DEFAULTS,
    "scan_minutes": "60",   # ikona skenu: bežný sken každých N minút
    "zvoncek_dni": "1",     # zvonček: predvolený počet dní (každý si ho v Lupe vie zmeniť)
    "spravca": "",          # kto smie meniť nastavenia v Lupe (mená Windows, čiarkou); prázdne = každý
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


def _num(s: str, default: float) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def _load_rules(section: str, default: list, *paths: Path) -> list[tuple[str, str]]:
    """Pravidlá strojov z lupa.ini: [section] skratka = regulárny výraz (poradie = priorita).
    Sekcia chýba / je prázdna -> default. Neplatný výraz sa vynechá (program nesmie spadnúť)."""
    import re
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str   # skratky s veľkými písmenami (eVo 80, DMC 105)
    for p in paths:
        try:
            if p.exists():
                cp.read(p, encoding="utf-8-sig")
        except (OSError, configparser.Error):
            pass
    if not cp.has_section(section) or not cp.items(section):
        return list(default)
    out = []
    for name, rx in cp.items(section):
        try:
            re.compile(rx)
        except re.error:
            continue
        if name.strip() and rx.strip():
            out.append((rx.strip(), name.strip()))
    return out or list(default)


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
        "scan_minutes": max(5, int(_num(ini["scan_minutes"], 60))),
        "prints_minutes": float(ini["prints_minutes"]),
        "customers": _patterns(ini["customers"]),
        "listy": listy.Rules(ini),
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
    "MODEL": ("3D model", ["stp", "step", "igs", "iges", "x_t", "x_b", "stl", "catpart", "catproduct", "meg"],
              "#dbeafe", "#1e3a8a"),
    "HMC": ("hyperMILL", ["hmc"], "#ffedd5", "#7c2d12"),
    "ECAM": ("Edgecam", ["ppf"], "#fef3c7", "#78350f"),
    "NC": ("NC program", ["h", "nc", "mpf", "spf", "wpd", "eia", "nd1", "nd2", "arc", "dmg"],
           "#dcfce7", "#14532d"),
    "XLS": ("Excel – CNC listy", ["xlsx", "xlsm", "xls"], "#ccfbf1", "#134e4a"),
    "DOC": ("Word", ["doc", "docx"], "#e0e7ff", "#312e81"),
    "CREO": ("Creo (cgm = zjednodušený výkres)", ["prt", "drw", "asm", "cgm"], "#f9ded3", "#8a3517"),
    "DWG": ("AutoCAD", ["dwg", "dxf"], "#ede9fe", "#4c1d95"),
    "OBR": ("Obrázok / sken", ["tif", "tiff", "jpg", "jpeg", "png", "bmp", "gif", "webp", "heic"],
            "#fce7f3", "#831843"),
    "TXT": ("Poznámky", ["txt"], "#ecfccb", "#365314"),
    "MAIL": ("E-mail", ["msg", "eml"], "#fae8ff", "#86198f"),
    "ZIP": ("Archív", ["zip", "rar", "7z"], "#e7e5e4", "#44403c"),
}

# Kontrola úplnosti zákazky: (názov, typy, prípony) – stačí ktorýkoľvek typ alebo prípona.
# LIST = CNC list (list_sql nižšie); PDF, ktoré je CNC listom, sa do „PDF“ (výkres) nepočíta.
COMPLETENESS = [
    ("Model", ["MODEL", "CREO"], []),
    ("PDF", ["PDF"], []),
    ("CAM", ["HMC", "ECAM"], []),
    ("NC", ["NC"], []),
    ("Listy", ["LIST"], []),
]


# CNC listy – pravidlo v listy.py (meno, priečinok PDF, obsah Wordu / Excelu z tabuľky doclists).
# Lupa: lupa.ini vedľa programu (na L:\_Lupa aj vedľa DB); skener: scan_settings()["listy"].
LIST_RULES = listy.Rules(_ini)


def list_sql(f: str = "f", doclists: bool = True) -> tuple[str, list]:
    """SQL podmienka „súbor je CNC list“ (listy.list_sql s pravidlom z lupa.ini)."""
    return listy.list_sql(LIST_RULES, f, doclists)


# Stroje zákazky (stroje.py): text za „STROJ:“ v hlavičke NC programu / nástrojového listu
# -> skratka. Prvé pravidlo, ktoré sedí (regulárny výraz, veľké písmená nerozhodujú).
# Neznámy stroj sa ukáže tak, ako je v hlavičke – doplň pravidlo.
# Platí [stroje] v lupa.ini (okno Nastavenia, skratka = výraz); bez nej tieto predvolené.
DEFAULT_MACHINES = [
    (r"DMU\s*75|monoBLOCK.*840D", "mono 840D"),
    (r"DMU\s*65|monoBLOCK", "mono H640"),
    (r"DMU\s*(80|85)\s*eVo", "eVo 80"),
    (r"DMU\s*60\s*eVo", "eVo 60"),
    (r"DMC\s*(80\s*-\s*)?160", "DMC 160"),
    (r"DMC\s*105", "DMC 105"),
    (r"3x-HH", "H530 3x"),
    (r"Kaoming", "Kaoming"),
    (r"HPM\s*450", "HPM 450"),
    (r"GMX", "Gmx"),
    (r"NTX", "NTX"),
    (r"J-?200", "J200"),
    (r"IG-?400|i-?400", "IG400"),
    (r"Mazak|Integrex", "Mazak"),
    (r"WFL", "WFL"),
]
# Program bez riadku STROJ: -> stroj podľa obsahu začiatku súboru (prvé pravidlo, ktoré sedí)
# WFL (Edgecam, Siemens): ;$PATH=/_N_WKS_DIR/…_WPD, výmena nástroja TLCH1(…)
MACHINE_SIGNS = [
    (r"_N_WKS_DIR|TLCH1\s*\(", "WFL"),
]
# NC prípony bez hlavičky aj bez znaku vyššie -> stroj
MACHINE_EXTS = {"eia": "Mazak", "wpd": "WFL"}
# Stroj podľa mena CNC listu v zákazke (Excel aj PDF / Word): (vzor v mene, skratka)
# Platí [stroje_listy] v lupa.ini; bez nej tieto predvolené.
DEFAULT_MACHINE_NAMES = [
    (r"gamma", "Gamma"),
    (r"(?<![a-z])gmx", "Gmx"),
    (r"j-?200", "J200"),
    (r"ig-?400", "IG400"),
    (r"mazak", "Mazak"),
    (r"(?<![a-z])wfl(?![a-z])", "WFL"),
]
MACHINES = _load_rules("stroje", DEFAULT_MACHINES, INI_PATH)
MACHINE_NAMES = _load_rules("stroje_listy", DEFAULT_MACHINE_NAMES, INI_PATH)
BELL_DAYS = int(_num(_ini["zvoncek_dni"], 1))
ADMINS = [a.strip().lower() for a in _ini["spravca"].split(",") if a.strip()]
# Všeobecný stroj sa vynechá, keď je v zákazke presnejší (Mazak .eia + list MAZAK-IG400 = IG400)
MACHINE_GENERIC = {"Mazak": ["J200", "IG400"]}
# Rovnaký program pre viac strojov: hlavička GMX, ale listy hovoria len Gamma -> Gamma
MACHINE_SAME_PROGRAM = {"Gmx": ["Gamma"]}
NEW_JOBS_OWNER_DAYS = 60  # skener: kto pridal zákazku (vlastník priečinka) len pri mladších zákazkách
MACHINE_CONTENT_MAX = 3   # Excel s viac strojmi v obsahu = šablóna / zoznam, nepočíta sa


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
# Priečinky kdekoľvek v zákazke – interné dáta hyperMILL (POF111, pof2…). Vzory fnmatch, malými.
IGNORE_DIRS = ["pof*", "vnc", "stock", "3df", "def", "geo"]
# Priečinky na 1. úrovni koreňa, ktoré nie sú zákazníci
IGNORE_ROOT_DIRS = {"_lupa", "$recycle.bin", "system volume information"}
# Konkrétne názvy súborov
IGNORE_FILES = {"thumbs.db", "desktop.ini"}
# Prípony súborov (dep = Heidenhain PROG.H.T.DEP, err/out = std.err/std.out,
# pof/rsf/idx/xpr/m_p/crc = hyperMILL a pod., pro = lokálna konfigurácia Creo)
IGNORE_EXTS = {"bak", "hmc_bak", "hypermill", "dwl", "dwl2", "log", "tmp", "out", "err", "dep",
               "pof", "rsf", "idx", "xpr", "m_p", "crc", "pro"}
# Vzory názvov (fnmatch, malými písmenami) – logy z exportu Creo, trail, sekcie a ďalšie
# pomocné súbory Creo s číslom verzie (s2d0001.sec.1, xx.frm.1, gen3.lsl.2, global_intf.inf.6)
IGNORE_GLOBS = ["*.log.*", "*_log.xml", "trail.txt*", "*.sec", "*.sec.*", "*.frm.*", "*.lsl.*", "*.inf.*"]


def is_ignored(name: str, ext: str) -> bool:
    """Súbor, ktorý skener preskakuje (aj upratovanie DB po zmene týchto pravidiel)."""
    low = name.lower()
    return (low in IGNORE_FILES or ext in IGNORE_EXTS
            or any(fnmatch.fnmatchcase(low, g) for g in IGNORE_GLOBS))


def is_ignored_dir(name: str) -> bool:
    """Priečinok v zákazke, ktorý skener preskakuje (aj s obsahom)."""
    low = name.lower()
    return any(fnmatch.fnmatchcase(low, g) for g in IGNORE_DIRS)
