"""CNC listy – jedno pravidlo pre skener, Lupu aj skúšku (skuska_listy.py).

Súbor je CNC list, ak
1. meno sedí na listy_mena (*cnc*, *prog*list*, *pgm*list*, *poloha*)  – Word, Excel aj PDF,
2. PDF leží v priečinku (v zákazke) podľa listy_priecinky (*cnc*list*),
3. Word / Excel, ktorého meno nie je jasné, má v obsahu
   - cestu R:\\priečinok\\… (NC programy na serveri) – najistejšie, alebo
   - aspoň listy_obsah_min slov z listy_obsah (Programátor:, Názov stroja, Program-číslo: …).
   Obsah číta skener (update_doclists) a výsledok ukladá do tabuľky doclists – Lupa len pozerá do DB.
Priečinok „CNC listy“ o Worde / Exceli nerozhoduje – bývajú tam aj nástrojové listy, náčrty.
Prídavky k listu (upnutie na magnet.docx) ani poznámky (CITAJ.doc) listom nie sú – nemajú 2 slová.
Veľké/malé písmená ani diakritika nehrajú rolu. Zo súboru sa len číta.
Overené skúškou na Kuka, Bühler, Rejlek, Nedschroef (11/2026).
"""
import fnmatch
import html
import re
import unicodedata
import zipfile
import zlib
from pathlib import Path

# Pri zmene čítania obsahu alebo slov zvýš – skener dokumenty prečíta znova.
VERSION = 1

DOC_TYPES = ("DOC", "XLS")          # typy, pri ktorých sa číta obsah
ZIP_EXTS = {"docx", "docm", "xlsx", "xlsm"}
# Zo starých .doc / .xls sa číta len začiatok: text Wordu je hneď na začiatku (~3 kB), za ním fotky
# (vzorky: 0,5–4 MB, text vždy do 3 kB). V .xls môžu byť obrázky pred textom buniek – viac.
MAX_READ = {"doc": 256 * 2**10, "xls": 8 * 2**20}
# R:\100009\… (po norm(): malými) – „r:\“ samotné sa v binárnych dátach fotky nájde aj náhodou
SURE_RE = re.compile(r"r:\\[a-z0-9][a-z0-9 ._()-]{2,}[\\/]")

DEFAULTS = {
    "listy_mena": "*cnc*, *prog*list*, *pgm*list*, *poloha*",
    "listy_priecinky": "*cnc*list*",
    "listy_obsah": "Programátor:, CESTA:, Názov stroja, Výrobný príkaz:, Artikel:, Výkres:, Program-číslo:",
    "listy_obsah_min": "2",
    "listy_minutes": "10",
}


def norm(s: str) -> str:
    """malými, bez diakritiky, viac medzier = jedna"""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s)


def _split(s: str) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


class Rules:
    """Pravidlo z nastavení (lupa.ini, kľúče ako DEFAULTS)."""

    def __init__(self, ini: dict | None = None):
        ini = {**DEFAULTS, **{k: v for k, v in (ini or {}).items() if k in DEFAULTS and v is not None}}
        self.names = [p.lower() for p in _split(ini["listy_mena"])]
        self.dirs = [p.lower() for p in _split(ini["listy_priecinky"])]
        self.words = [norm(w) for w in _split(ini["listy_obsah"])]
        self.words_min = max(1, int(ini["listy_obsah_min"]))
        self.minutes = float(ini["listy_minutes"])
        # verzia záznamu v doclists: algoritmus + slová z lupa.ini – po ich zmene skener
        # dokumenty prečíta znova (mená sa do DB nezapisujú, tie Lupa vyhodnocuje sama)
        key = "|".join(self.words) + f"|{self.words_min}"
        self.version = VERSION * 100000 + zlib.crc32(key.encode("utf-8")) % 100000

    def by_name(self, name: str) -> str | None:
        """Vzor mena, na ktorý meno sedí (None = nesedí)."""
        low = name.lower()
        return next((p for p in self.names if fnmatch.fnmatch(low, p)), None)

    def in_list_dir(self, rel_dir: str) -> bool:
        d = rel_dir.lower()
        return any(fnmatch.fnmatch(d, p) for p in self.dirs)

    def by_content(self, path: str | Path) -> tuple[bool, str]:
        """(je CNC list, prečo) podľa obsahu Wordu / Excelu. Výnimka = súbor sa nedá prečítať."""
        path = Path(path)
        ext = path.suffix.lower().lstrip(".")
        raw = text_zip(path) if ext in ZIP_EXTS else text_ole(path)
        t = norm(raw)
        m = SURE_RE.search(t)
        if m:
            return True, "R:\\ " + t[m.start(): m.start() + 60].strip()
        found = [w for w in self.words if w in t]
        if len(found) >= self.words_min:
            return True, " + ".join(found)
        return False, ("len: " + " + ".join(found)) if found else ""


def text_zip(path: Path) -> str:
    """docx / xlsx: text z XML vnútri (dokument, hlavičky, bunky, textové polia, vlastnosti)."""
    parts = []
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            low = n.lower()
            if (low.startswith(("word/document", "word/header", "word/footer", "xl/sharedstrings",
                                "xl/worksheets/sheet", "xl/drawings/drawing", "docprops/core",
                                "docprops/app"))
                    and low.endswith(".xml")):
                xml = z.read(n).decode("utf-8", "replace")
                parts.append(re.sub(r"<[^>]+>", " ", xml))
    return html.unescape(" ".join(parts))


def text_ole(path: Path) -> str:
    """Starý .doc / .xls (binárny): úseky čitateľného textu – UTF-16 aj 8-bit (cp1250)."""
    with open(path, "rb") as f:
        d = f.read(MAX_READ.get(path.suffix.lower().lstrip("."), 256 * 2**10))
    # UTF-16: latinka (xx 00) a slovenské znaky z Latin Extended-A (xx 01) – aj č/Č/ď/Ď, ktorých
    # dolný bajt je 0x0C–0x0F (inak by sa „Program-číslo:“ rozpadlo na „Program-“ + „íslo:“)
    u = [m.decode("utf-16le", "replace")
         for m in re.findall(rb"(?:[\x20-\x7e\xa0-\xff]\x00|[\x00-\xff]\x01){4,}", d)]
    a = [m.decode("cp1250", "replace") for m in re.findall(rb"[\x20-\x7e\x8a-\xfe\t]{4,}", d)]
    return " ".join(u + a)


# ---------------------------------------------------------------------------
# SQL pre Lupu (podmienka „súbor je CNC list“ nad files f)
# ---------------------------------------------------------------------------
def _like(pattern: str) -> str:
    """fnmatch vzor -> SQL LIKE s ESCAPE '!' (LIKE v SQLite nerozlišuje veľké/malé pri ASCII)."""
    out = []
    for ch in pattern:
        if ch in "!%_":
            out.append("!" + ch)
        elif ch == "*":
            out.append("%")
        elif ch == "?":
            out.append("_")
        else:
            out.append(ch)
    return "".join(out)


def list_sql(rules: Rules, f: str = "f", doclists: bool = True) -> tuple[str, list]:
    """SQL podmienka „súbor je CNC list“ pre files s aliasom f + parametre.

    Word / Excel: meno, inak obsah z tabuľky doclists (len platný záznam – sedí veľkosť a zmenený;
    verziu pravidla stráži skener, Lupa ju nekontroluje – lupa.ini v inom PC ju nesmie zmiasť;
    doclists=False pre starú DB bez tabuľky). PDF: meno, inak priečinok.
    CASE sa vyhodnocuje postupne – priečinok / doclists sa dohľadá len keď meno nesedí.
    """
    names = [_like(p) for p in rules.names]
    dirs = [_like(p) for p in rules.dirs]
    name = " OR ".join([f"{f}.name LIKE ? ESCAPE '!'"] * len(names)) or "0"
    folder = " OR ".join(["rel LIKE ? ESCAPE '!'"] * len(dirs)) or "0"
    content = (f"EXISTS (SELECT 1 FROM doclists d WHERE d.path = {f}.path AND d.is_list = 1"
               f" AND d.size IS {f}.size AND d.modified IS {f}.modified)"
               if doclists else "0")
    sql = (f"(CASE WHEN {f}.ftype NOT IN ('PDF', 'DOC', 'XLS') THEN 0"
           f" WHEN {name} THEN 1"
           f" WHEN {f}.ftype <> 'PDF' THEN {content}"
           f" ELSE EXISTS (SELECT 1 FROM (SELECT rel_path AS rel FROM positions WHERE id = {f}.position_id)"
           f" WHERE {folder}) END)")
    return sql, [*names, *dirs]
