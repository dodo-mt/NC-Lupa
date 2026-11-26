"""KonfigurĂˇcia Lupy â€“ cesty, typy sĂşborov, farby, ignorovanĂ© poloĹľky.

Hodnoty ciest sa ÄŤĂ­tajĂş z lupa.ini (vedÄľa programu), inak platia predvolenĂ©.
"""
import configparser
import fnmatch
import os
import sys
from pathlib import Path

import listy
import odladene

# Verzia aplikĂˇcie â€“ zvyĹˇovaĹĄ pri kaĹľdom vydanĂ­ (zobrazuje sa v UI, ikone skenu, logu a vo vlastnostiach exe)
VERSION = "1.14.0"

# PrieÄŤinok programu (pri PyInstaller exe = prieÄŤinok s exe). Lupa beĹľĂ­ z lokĂˇlnej kĂłpie
# v %LOCALAPPDATA% (launcher.py) â€“ spĂşĹˇĹĄaÄŤ jej v LUPA_HOME odovzdĂˇ svoj prieÄŤinok (L:\_Nastroje\lupa),
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
    "odladene_priecinky": "odlad*, zo*stroja*",   # prieÄŤinky s odladenĂ˝mi NC programami: odladenĂ©, Zo stroja (odladene.py)
    "exclude": "",
    # CNC listy (listy.py): listy_mena, listy_priecinky, listy_obsah, listy_obsah_min, listy_minutes
    **listy.DEFAULTS,
    "scan_minutes": "60",   # ikona skenu: beĹľnĂ˝ sken kaĹľdĂ˝ch N minĂşt
    "zvoncek_dni": "1",     # zvonÄŤek: predvolenĂ˝ poÄŤet dnĂ­ (kaĹľdĂ˝ si ho v Lupe vie zmeniĹĄ)
    "spravca": "",          # kto smie meniĹĄ nastavenia v Lupe (menĂˇ Windows, ÄŤiarkou); prĂˇzdne = kaĹľdĂ˝
}


# HÄľadanie v obsahu NC programov (obsah.py, okno ui/obsah.html): skupiny podÄľa PRĂŤPONY, nie stroja â€“
# .mpf / .spf sĂş Sinumerik aj Gamma GMX (rozloĹľenĂ˝ .arc), .nc je vĹˇeobecnĂ˝ program z Edgecamu.
OBSAH_SKUPINY = [
    ("heidenhain", "Heidenhain", ["h"]),
    ("sinumerik", "Sinumerik / Gamma (rozloĹľenĂ©)", ["mpf", "spf"]),
    ("gamma", "Gamma GMX archĂ­v", ["arc"]),
    ("fanuc", "Fanuc", ["nd1", "nd2"]),
    ("mazak", "Mazak", ["eia"]),
    ("wfl", "WFL", ["wpd"]),
    ("edgecam", "Edgecam (vĹˇeobecnĂ©)", ["nc"]),
]
OBSAH_MAX_MB = 50            # vĂ¤ÄŤĹˇie sĂşbory sa neprehÄľadĂˇvajĂş (hlĂˇsia sa ako preskoÄŤenĂ©)
OBSAH_MAX_NALEZOV = 2000     # koÄľko nĂˇlezov celkom
OBSAH_NA_SUBOR = 50          # koÄľko nĂˇlezov z jednĂ©ho sĂşboru
OBSAH_POTVRDIT_MB = 2048     # nad touto veÄľkosĹĄou (alebo poÄŤtom sĂşborov) sa hÄľadanie pred Ĺˇtartom potvrdzuje
OBSAH_POTVRDIT_SUBOROV = 5000
OBSAH_VLAKNA = 6             # sĂşbeĹľnĂ© ÄŤĂ­tanie (sieĹĄ)


def _load_ini(*paths: Path) -> dict:
    """PredvolenĂ© hodnoty prepĂ­sanĂ© sĂşbormi v poradĂ­ (neskorĹˇĂ­ mĂˇ prednosĹĄ)."""
    cp = configparser.ConfigParser(interpolation=None)
    cp.read_dict({"lupa": _DEFAULTS})
    for p in paths:
        try:
            if p.exists():
                # utf-8-sig: PoznĂˇmkovĂ˝ blok / PowerShell mĂ´Ĺľu uloĹľiĹĄ sĂşbor s BOM
                cp.read(p, encoding="utf-8-sig")
        except (OSError, configparser.Error):
            # sieĹĄovĂ˝ disk nedostupnĂ˝ / pokazenĂ˝ sĂşbor â€“ platĂ­ to, ÄŤo sa naÄŤĂ­talo (program nesmie spadnĂşĹĄ)
            pass
    return dict(cp["lupa"])


_ini = _load_ini(INI_PATH)


def _num(s: str, default: float) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def _load_rules(section: str, default: list, *paths: Path) -> list[tuple[str, str]]:
    """PravidlĂˇ strojov z lupa.ini: [section] skratka = regulĂˇrny vĂ˝raz (poradie = priorita).
    Sekcia chĂ˝ba / je prĂˇzdna -> default. NeplatnĂ˝ vĂ˝raz sa vynechĂˇ (program nesmie spadnĂşĹĄ)."""
    import re
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str   # skratky s veÄľkĂ˝mi pĂ­smenami (eVo 80, DMC 105)
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
    """'[0-9]*, OD*' -> ['[0-9]*', 'od*'] (vzory pre fnmatch, malĂ˝mi pĂ­smenami)."""
    return [p.strip().lower() for p in s.split(",") if p.strip()]


def scan_settings(db_path: Path) -> dict:
    """Nastavenia skenu: lupa.ini vedÄľa programu, prepĂ­sanĂ© lupa.ini vedÄľa databĂˇzy.

    Ikona skenu beĹľĂ­ z kĂłpie v %LOCALAPPDATA%\\Lupa\\bin â€“ spoloÄŤnĂ© nastavenia sĂş preto
    v L:\\_Nastroje\\lupa\\lupa.ini vedÄľa DB.
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


# LokĂˇlne dĂˇta pouĹľĂ­vateÄľa (nie na sieti): cache nĂˇhÄľadov, poloha okien, pracovnĂˇ kĂłpia DB skenera
LOCAL_DIR = Path(os.environ.get("LOCALAPPDATA", str(APP_DIR))) / "Lupa"
THUMBS_DIR = LOCAL_DIR / "thumbs"

ROOT = _resolve(_ini["root"])
DB_PATH = _resolve(_ini["db"])
# recent_days, prints_minutes, customers, exclude: pre skener cez scan_settings() (aj lupa.ini vedÄľa DB)
PRINTS_MAX_MB = 100  # odtlaÄŤky vĂ˝kresov: vĂ¤ÄŤĹˇie PDF sa preskoÄŤia (obrovskĂ© skeny)
FULL_EVERY_DAYS = 7  # scanner --auto: ĂşplnĂ˝ sken, ak poslednĂ˝ bol pred viac ako N dĹami

# ---------------------------------------------------------------------------
# Typy sĂşborov: kÄľĂşÄŤ -> (popis, prĂ­pony, farba pozadia, farba textu)
# Poradie = poradie chipov vo filtri. PrĂ­pony malĂ˝mi pĂ­smenami, bez bodky.
# ---------------------------------------------------------------------------
FILE_TYPES = {
    "PDF": ("VĂ˝kres", ["pdf"], "#fee2e2", "#7f1d1d"),
    "MODEL": ("3D model", ["stp", "step", "igs", "iges", "x_t", "x_b", "stl", "catpart", "catproduct", "meg"],
              "#dbeafe", "#1e3a8a"),
    "HMC": ("hyperMILL", ["hmc"], "#ffedd5", "#7c2d12"),
    "ECAM": ("Edgecam", ["ppf"], "#fef3c7", "#78350f"),
    "NC": ("NC program", ["h", "nc", "mpf", "spf", "wpd", "eia", "nd1", "nd2", "arc", "dmg"],
           "#dcfce7", "#14532d"),
    "XLS": ("Excel â€“ CNC listy", ["xlsx", "xlsm", "xls"], "#ccfbf1", "#134e4a"),
    "DOC": ("Word", ["doc", "docx"], "#e0e7ff", "#312e81"),
    "CREO": ("Creo (cgm = zjednoduĹˇenĂ˝ vĂ˝kres)", ["prt", "drw", "asm", "cgm"], "#f9ded3", "#8a3517"),
    "DWG": ("AutoCAD", ["dwg", "dxf"], "#ede9fe", "#4c1d95"),
    "OBR": ("ObrĂˇzok / sken", ["tif", "tiff", "jpg", "jpeg", "png", "bmp", "gif", "webp", "heic"],
            "#fce7f3", "#831843"),
    "TXT": ("PoznĂˇmky", ["txt"], "#ecfccb", "#365314"),
    "MAIL": ("E-mail", ["msg", "eml"], "#fae8ff", "#86198f"),
    "ZIP": ("ArchĂ­v", ["zip", "rar", "7z"], "#e7e5e4", "#44403c"),
}

# Kontrola Ăşplnosti zĂˇkazky: (nĂˇzov, typy, prĂ­pony) â€“ staÄŤĂ­ ktorĂ˝koÄľvek typ alebo prĂ­pona.
# LIST = CNC list (list_sql niĹľĹˇie); PDF, ktorĂ© je CNC listom, sa do â€žPDFâ€ś (vĂ˝kres) nepoÄŤĂ­ta.
COMPLETENESS = [
    ("Model", ["MODEL", "CREO"], []),
    ("PDF", ["PDF"], []),
    ("CAM", ["HMC", "ECAM"], []),
    ("NC", ["NC"], []),
    ("Listy", ["LIST"], []),
]


# CNC listy â€“ pravidlo v listy.py (meno, prieÄŤinok PDF, obsah Wordu / Excelu z tabuÄľky doclists).
# Lupa: lupa.ini vedÄľa programu (na L:\_Nastroje\lupa aj vedÄľa DB); skener: scan_settings()["listy"].
LIST_RULES = listy.Rules(_ini)
ODLADENE = odladene.Pravidlo(_ini)


def list_sql(f: str = "f", doclists: bool = True) -> tuple[str, list]:
    """SQL podmienka â€žsĂşbor je CNC listâ€ś (listy.list_sql s pravidlom z lupa.ini)."""
    return listy.list_sql(LIST_RULES, f, doclists)


# Stroje zĂˇkazky (stroje.py): text za â€žSTROJ:â€ś v hlaviÄŤke NC programu / nĂˇstrojovĂ©ho listu
# -> skratka. PrvĂ© pravidlo, ktorĂ© sedĂ­ (regulĂˇrny vĂ˝raz, veÄľkĂ© pĂ­smenĂˇ nerozhodujĂş).
# NeznĂˇmy stroj sa ukĂˇĹľe tak, ako je v hlaviÄŤke â€“ doplĹ pravidlo.
# PlatĂ­ [stroje] v lupa.ini (okno Nastavenia, skratka = vĂ˝raz); bez nej tieto predvolenĂ©.
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
# Program bez riadku STROJ: -> stroj podÄľa obsahu zaÄŤiatku sĂşboru (prvĂ© pravidlo, ktorĂ© sedĂ­)
# WFL (Edgecam, Siemens): ;$PATH=/_N_WKS_DIR/â€¦_WPD, vĂ˝mena nĂˇstroja TLCH1(â€¦)
MACHINE_SIGNS = [
    (r"_N_WKS_DIR|TLCH1\s*\(", "WFL"),
]
# NC prĂ­pony bez hlaviÄŤky aj bez znaku vyĹˇĹˇie -> stroj
MACHINE_EXTS = {"eia": "Mazak", "wpd": "WFL"}
# Stroj podÄľa mena CNC listu v zĂˇkazke (Excel aj PDF / Word): (vzor v mene, skratka)
# PlatĂ­ [stroje_listy] v lupa.ini; bez nej tieto predvolenĂ©.
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
# VĹˇeobecnĂ˝ stroj sa vynechĂˇ, keÄŹ je v zĂˇkazke presnejĹˇĂ­ (Mazak .eia + list MAZAK-IG400 = IG400)
MACHINE_GENERIC = {"Mazak": ["J200", "IG400"]}
# RovnakĂ˝ program pre viac strojov: hlaviÄŤka GMX, ale listy hovoria len Gamma -> Gamma
MACHINE_SAME_PROGRAM = {"Gmx": ["Gamma"]}
NEW_JOBS_OWNER_DAYS = 60  # skener: kto pridal zĂˇkazku (vlastnĂ­k prieÄŤinka) len pri mladĹˇĂ­ch zĂˇkazkĂˇch
MACHINE_CONTENT_MAX = 3   # Excel s viac strojmi v obsahu = ĹˇablĂłna / zoznam, nepoÄŤĂ­ta sa


def missing_parts(ftypes: set, exts: set) -> list[str]:
    """NĂˇzvy poloĹľiek Ăşplnosti, ktorĂ© v zĂˇkazke chĂ˝bajĂş."""
    return [
        name for name, types, ex in COMPLETENESS
        if not (ftypes & set(types) or exts & set(ex))
    ]

# PrĂ­pony s ÄŤĂ­slom verzie na konci (Creo: 612234.prt.5, drw0001.drw.2).
# Skener z nich berie len najvyĹˇĹˇiu verziu v prieÄŤinku, ext sa ukladĂˇ bez verzie.
VERSIONED_EXTS = {"prt", "drw", "asm"}
OTHER_TYPE = ("OTH", "OstatnĂ©", "#f3f4f6", "#374151")

_EXT_TO_TYPE = {ext: key for key, (_, exts, _, _) in FILE_TYPES.items() for ext in exts}


def ftype_for_ext(ext: str) -> str:
    """PrĂ­pona (bez bodky, malĂ˝mi) -> kÄľĂşÄŤ typu."""
    return _EXT_TO_TYPE.get(ext, OTHER_TYPE[0])


# ---------------------------------------------------------------------------
# ÄŚo skener preskakuje (porovnĂˇva sa bez ohÄľadu na veÄľkosĹĄ pĂ­smen)
# ---------------------------------------------------------------------------
# PrieÄŤinky kdekoÄľvek v zĂˇkazke â€“ internĂ© dĂˇta hyperMILL (POF111, pof2â€¦). Vzory fnmatch, malĂ˝mi.
IGNORE_DIRS = ["pof*", "vnc", "stock", "3df", "def", "geo"]
# PrieÄŤinky na 1. Ăşrovni koreĹa, ktorĂ© nie sĂş zĂˇkaznĂ­ci
IGNORE_ROOT_DIRS = {"_lupa", "$recycle.bin", "system volume information"}
# KonkrĂ©tne nĂˇzvy sĂşborov
IGNORE_FILES = {"thumbs.db", "desktop.ini"}
# PrĂ­pony sĂşborov (dep = Heidenhain PROG.H.T.DEP, err/out = std.err/std.out,
# pof/rsf/idx/xpr/m_p/crc = hyperMILL a pod., pro = lokĂˇlna konfigurĂˇcia Creo)
IGNORE_EXTS = {"bak", "hmc_bak", "hypermill", "dwl", "dwl2", "log", "tmp", "out", "err", "dep",
               "pof", "rsf", "idx", "xpr", "m_p", "crc", "pro"}
# Vzory nĂˇzvov (fnmatch, malĂ˝mi pĂ­smenami) â€“ logy z exportu Creo, trail, sekcie a ÄŹalĹˇie
# pomocnĂ© sĂşbory Creo s ÄŤĂ­slom verzie (s2d0001.sec.1, xx.frm.1, gen3.lsl.2, global_intf.inf.6)
IGNORE_GLOBS = ["*.log.*", "*_log.xml", "trail.txt*", "*.sec", "*.sec.*", "*.frm.*", "*.lsl.*", "*.inf.*"]


def is_ignored(name: str, ext: str) -> bool:
    """SĂşbor, ktorĂ˝ skener preskakuje (aj upratovanie DB po zmene tĂ˝chto pravidiel)."""
    low = name.lower()
    return (low in IGNORE_FILES or ext in IGNORE_EXTS
            or any(fnmatch.fnmatchcase(low, g) for g in IGNORE_GLOBS))


def is_ignored_dir(name: str) -> bool:
    """PrieÄŤinok v zĂˇkazke, ktorĂ˝ skener preskakuje (aj s obsahom)."""
    low = name.lower()
    return any(fnmatch.fnmatchcase(low, g) for g in IGNORE_DIRS)
