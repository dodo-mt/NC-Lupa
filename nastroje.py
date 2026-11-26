"""Zoznam nástrojov NC programu pre detail súboru v Lupe (čítané na požiadanie, bez indexu v databáze).

Rozpoznanie podľa obsahu (nie podľa prípony – `.nc` z Edgecamu môže byť čokoľvek). Programy z hyperMILLu majú pri
volaní nástroja rovnaké komentáre pre Heidenhain aj Siemens:
  `; (Nastroj: FRE-D12-TK-HRUB-S | E.7676HL.1.1200 | L=36 LL=156)`   (tesne NAD volaním; za názvom ` | ` alebo ` L=`)
  `; (Upinac: …)`, `; (Predlzenie: …)`
  Heidenhain: `16 TOOL CALL 3025 Z S891 F1000` – číslo; názov z komentára `Nastroj:` nad volaním, inak v zátvorke za
              volaním (`;  (FRE-D50-PL-S)`); z hlavičkových komentárov `; T2965 D50 r2.5 Lc8.7 L40 - NÁZOV` sa doplní
              D, r, Lc, L (párovanie podľa čísla T); `TOOL DEF` je len predvolenie, nepočíta sa.
  Sinumerik:  `T="FRE-D32-PL-S"` (alebo `T=12`, `T12`) a `M6` v tom istom alebo v nasledujúcich riadkoch. Číslo T je
              v hlavičke `; T933 VRT-D5-TK | R=2.5 R2=0. LCUT=35` (podľa názvu) alebo v texte operácie
              (`GROUP_BEGIN(0,"1590 : T933 M6 - vrtat",…)`, `MSG(…)`). Texty v úvodzovkách sa pri hľadaní volania ignorujú.
  Fanuc/Mazak: `T73020801(T000) M6` – len číslo (výklad osemmiestneho čísla zatiaľ nepoznáme).
"""
import re

MAX_NASTROJOV = 500
M6_DOHLAD = 4            # Sinumerik: M6 sa hľadá v riadku s T a v nasledujúcich N riadkoch
NAD_VOLANIM = 8          # komentár `Nastroj:` platí pre volanie najviac o toľko riadkov nižšie (pod ním je Upinac, Predlzenie)

_HEID_CALL = re.compile(r"^\s*(?:\d+\s+)?TOOL\s+CALL\s+(\d+|\"[^\"]*\"|Q\d+)(.*)$", re.IGNORECASE)
_HEID_NAME = re.compile(r";\s*\(([^)]*)\)")
_NASTROJ = re.compile(r"^\s*(?:N?\d+\s+)?;\s*\(?\s*N[aá]stroj\s*:\s*(.*)$", re.IGNORECASE)
_HEID_HEAD = re.compile(r"^\s*(?:\d+\s+)?;\s*T(\d+)\s+(.*?)\s+-\s+(\S.*)$")
_SINU_HEAD = re.compile(r"^\s*(?:N?\d+\s+)?;\s*T(\d+)\s+([^|]+?)\s*\|\s*(.*)$")
_PAR = {  # D priemer, r polomer, R2 polomer rohu, Lc / LCUT dĺžka rezu, L dĺžka, LL celková dĺžka
    "d": re.compile(r"(?<![A-Za-z])D\s*=?\s*(\d+(?:\.\d*)?)"),
    "r": re.compile(r"(?<![A-Za-z0-9])r\s*=?\s*(\d+(?:\.\d*)?)", re.IGNORECASE),
    "r2": re.compile(r"(?<![A-Za-z0-9])R2\s*=\s*(\d+(?:\.\d*)?)", re.IGNORECASE),
    "lc": re.compile(r"(?<![A-Za-z])(?:Lc|LCUT)\s*=?\s*(\d+(?:\.\d*)?)", re.IGNORECASE),
    "l": re.compile(r"(?<![A-Za-z])L\s*=?\s*(\d+(?:\.\d*)?)"),
    "ll": re.compile(r"(?<![A-Za-z])LL\s*=\s*(\d+(?:\.\d*)?)"),
}
_SINU_T = re.compile(r"(?<![A-Za-z0-9_$])T\s*=\s*(?:\"([^\"]*)\"|(\d+))|(?<![A-Za-z0-9_$])T(\d+)(?![0-9A-Za-z_])")
_RETAZCE = re.compile(r"(T\s*=\s*\"[^\"]*\")|\"[^\"]*\"")
_OP_T = re.compile(r"(?<![A-Za-z0-9_$])T(\d+)\s+M0?6")
_M6 = re.compile(r"(?<![A-Za-z0-9_])M0?6(?![0-9])")
_FANUC_T = re.compile(r"(?<![A-Za-z0-9_$])T(\d{1,8})(?![0-9A-Za-z_])")


def _cislo(x: str) -> str:
    """`48.` -> `48`, `2.50` -> `2.5` (hlavičky z CAMu píšu čísla aj s bodkou na konci)."""
    return x.rstrip("0").rstrip(".") if "." in x else x


def _udaje(text: str, kluce) -> dict:
    out = {}
    for k in kluce:
        m = _PAR[k].search(text)
        if m:
            out[k] = _cislo(m.group(1))
    return out


def _nazov_z_komentara(zvysok: str) -> str:
    """`FRE-D12-TK-HRUB-S | E.7676HL.1.1200 | L=36 LL=156)` -> `FRE-D12-TK-HRUB-S`; `HVIE-D10-TK)` -> `HVIE-D10-TK`."""
    t = re.sub(r"\)\s*$", "", zvysok.strip())
    return re.split(r"\s+\|\s*|\s+L\s*=", t, maxsplit=1)[0].strip()


def rozpoznaj(text: str) -> str:
    """'heidenhain' | 'sinumerik' | 'fanuc' | '' (v programe sa nenašlo nič, čo by sa dalo čítať ako nástroj)."""
    if re.search(r"^\s*(?:\d+\s+)?TOOL\s+CALL\s", text, re.IGNORECASE | re.MULTILINE):
        return "heidenhain"
    if re.search(r"(?<![A-Za-z0-9_$])T\s*=\s*\"", text) or re.search(r"(?m)^[^;\n]*(?<![A-Za-z0-9_$])T\s*=\s*\d", text):
        return "sinumerik"
    if re.search(r"(?m)^[^;(\n]*(?<![A-Za-z0-9_$])T\d{1,8}(?![0-9A-Za-z_])[^;\n]*M0?6", text):
        return "fanuc"
    return ""


def _zaznam(kluc: str, nazov: str = "") -> dict:
    return {"t": kluc, "cislo": "", "nazov": nazov, "d": "", "r": "", "r2": "", "lc": "", "l": "", "ll": "",
            "pocet": 0, "prvy": 0}


def _pridaj(zoznam: dict, kluc: str, riadok: int, nazov: str = "", udaje: dict | None = None) -> None:
    z = zoznam.get(kluc)
    if z is None:
        if len(zoznam) >= MAX_NASTROJOV:
            return
        z = zoznam[kluc] = _zaznam(kluc, nazov)
        z["prvy"] = riadok
    if nazov and not z["nazov"]:
        z["nazov"] = nazov
    for k, v in (udaje or {}).items():
        if not z[k]:
            z[k] = v
    z["pocet"] += 1


def _heidenhain(riadky: list[str]) -> list[dict]:
    zoznam: dict[str, dict] = {}
    hlavicky: dict[str, dict] = {}
    nad = (0, "", {})                                # (riadok, názov, L / LL) posledného komentára `Nastroj: …`
    for i, riadok in enumerate(riadky, 1):
        mn = _NASTROJ.match(riadok)
        if mn:
            nad = (i, _nazov_z_komentara(mn.group(1)), _udaje(mn.group(1), ("l", "ll")))
            continue
        m = _HEID_CALL.match(riadok)
        if m:
            raw = m.group(1)
            nm = _HEID_NAME.search(m.group(2))
            kluc = raw.strip('"')
            ma_nad = nad[1] and 0 < i - nad[0] <= NAD_VOLANIM
            _pridaj(zoznam, kluc, i,
                    nad[1] if ma_nad else (nm.group(1).strip() if nm else (kluc if raw.startswith('"') else "")),
                    nad[2] if ma_nad else None)
            nad = (0, "", {})
            continue
        h = _HEID_HEAD.match(riadok)
        if h and h.group(1) not in hlavicky:
            hlavicky[h.group(1)] = {**_udaje(h.group(2), ("d", "r", "lc", "l")), "nazov": h.group(3).strip()}
    for kluc, z in zoznam.items():
        z["cislo"] = kluc if kluc.isdigit() else ""
        h = hlavicky.get(kluc)
        if h:
            for k in ("d", "r", "lc", "l"):
                z[k] = z[k] or h.get(k, "")
            z["nazov"] = z["nazov"] or h["nazov"]
    return list(zoznam.values())


def _sinumerik(riadky: list[str]) -> list[dict]:
    zoznam: dict[str, dict] = {}
    podla_nazvu: dict[str, tuple[str, dict]] = {}    # názov -> (číslo T, rozmery) z hlavičky `; T933 NÁZOV | R=… LCUT=…`
    for r in riadky:
        h = _SINU_HEAD.match(r)
        if h and h.group(2).strip() not in podla_nazvu:
            podla_nazvu[h.group(2).strip()] = (h.group(1), _udaje(h.group(3), ("r", "r2", "lc")))
    bez = [_RETAZCE.sub(lambda m: m.group(1) or '""', r.split(";", 1)[0]) for r in riadky]   # bez komentárov a textov
    nad = (0, "", {})
    prve: dict[str, int] = {}                                    # kľúč -> index riadka prvého volania
    for i, riadok in enumerate(riadky):
        mn = _NASTROJ.match(riadok)
        if mn:
            nad = (i + 1, _nazov_z_komentara(mn.group(1)), _udaje(mn.group(1), ("l", "ll")))
            continue
        for m in _SINU_T.finditer(bez[i]):
            if not any(_M6.search(bez[j]) for j in range(i, min(len(bez), i + 1 + M6_DOHLAD))):
                continue                                             # len predvolenie nástroja (T bez M6)
            nazov_t, cislo_t, cislo = m.group(1), m.group(2), m.group(3)
            kluc = nazov_t if nazov_t is not None else (cislo_t or cislo)
            ma_nad = nad[1] and 0 < i + 1 - nad[0] <= NAD_VOLANIM
            _pridaj(zoznam, kluc, i + 1, (nad[1] if ma_nad else (nazov_t or "")), nad[2] if ma_nad else None)
            prve.setdefault(kluc, i)
            nad = (0, "", {})
            break
    for kluc, z in zoznam.items():
        if kluc.isdigit():
            z["cislo"] = kluc
        hlav = podla_nazvu.get(z["nazov"] or kluc)
        if hlav:
            z["cislo"] = z["cislo"] or hlav[0]
            for k, v in hlav[1].items():
                z[k] = z[k] or v
        if not z["cislo"]:                                           # číslo z textu operácie tesne nad volaním
            for r in riadky[max(0, prve[kluc] - NAD_VOLANIM):prve[kluc] + 1]:
                mo = _OP_T.search(r)
                if mo:
                    z["cislo"] = mo.group(1)
    return list(zoznam.values())


def _fanuc(riadky: list[str]) -> list[dict]:
    zoznam: dict[str, dict] = {}
    for i, r in enumerate(riadky, 1):
        bez = re.sub(r"\([^)]*\)", " ", _RETAZCE.sub('""', r)).split(";", 1)[0]
        if not _M6.search(bez):
            continue
        m = _FANUC_T.search(bez)
        if m:
            _pridaj(zoznam, m.group(1), i)
    for kluc, z in zoznam.items():
        z["cislo"] = kluc
    return list(zoznam.values())


def parsuj(text: str) -> dict:
    """{'typ': 'heidenhain' | 'sinumerik' | 'fanuc' | '', 'nastroje': [...], 'riadkov': počet riadkov}."""
    riadky = text.splitlines()
    typ = rozpoznaj(text)
    fn = {"heidenhain": _heidenhain, "sinumerik": _sinumerik, "fanuc": _fanuc}.get(typ)
    return {"typ": typ, "nastroje": fn(riadky) if fn else [], "riadkov": len(riadky)}
