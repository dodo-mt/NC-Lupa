"""Rýchly náhľad dokumentov na Medzerník: PDF (strany ako obrázok), Word a Excel (text a tabuľky z XML vo vnútri súboru).

Bez Office a bez nových knižníc: docx / xlsx sú ZIP s XML (zipfile + ElementTree), PDF kreslí PyMuPDF. Presný vzhľad
(písma, obrázky) sa nezachová – ide o rýchle pozretie obsahu. Staré binárne .doc / .xls rieši volajúci náhľadom z Windows.
Zo súborov sa len číta.
"""
import re
import zipfile
from xml.etree import ElementTree as ET

import pymupdf

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
SIRKA_OBRAZKA = 1600       # obrázky a skeny sa na náhľad zmenšia na túto šírku
MAX_BLOKOV = 3000          # Word: najviac odsekov a tabuliek
MAX_RIADKOV = 300          # Excel: najviac riadkov listu
MAX_STLPCOV = 40
MAX_XML = 40 * 1048576     # väčší XML sa nečíta (zip bomba / obrovský súbor)


def pdf_strana(path: str, strana: int = 0, sirka: int = 1100) -> tuple[bytes, int]:
    """(PNG strany, počet strán). `strana` od 0; mimo rozsahu sa zarovná."""
    with pymupdf.open(path) as doc:
        n = doc.page_count
        page = doc[max(0, min(strana, n - 1))]
        zoom = min(sirka / max(page.rect.width, 1), 4.0)
        return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).tobytes("png"), n


def _xml(z: zipfile.ZipFile, nazov: str):
    info = z.getinfo(nazov)
    if info.file_size > MAX_XML:
        raise ValueError("súbor je príliš veľký na náhľad")
    return ET.fromstring(z.read(nazov))


def _text_odseku(p) -> str:
    out = []
    for el in p.iter():
        if el.tag == W + "t" and el.text:
            out.append(el.text)
        elif el.tag == W + "tab":
            out.append("\t")
        elif el.tag in (W + "br", W + "cr"):
            out.append("\n")
    return "".join(out)


def word(path: str) -> dict:
    """{'bloky': [{'typ': 'p', 'text'} | {'typ': 'tab', 'riadky': [[bunka]]}], 'orezane'}; chyba -> ValueError."""
    with zipfile.ZipFile(path) as z:
        koren = _xml(z, "word/document.xml")
    telo = koren.find(W + "body")
    bloky, orezane = [], False
    for el in (telo if telo is not None else []):
        if len(bloky) >= MAX_BLOKOV:
            orezane = True
            break
        if el.tag == W + "p":
            bloky.append({"typ": "p", "text": _text_odseku(el)})
        elif el.tag == W + "tbl":
            riadky = [[" ".join(_text_odseku(p) for p in tc.iter(W + "p")).strip() for tc in tr.findall(W + "tc")]
                      for tr in el.iter(W + "tr")]
            bloky.append({"typ": "tab", "riadky": riadky})
    return {"bloky": bloky, "orezane": orezane}


def _stlpec(ref: str) -> int:
    """`B3` -> 1 (A = 0)."""
    n = 0
    for ch in re.match(r"[A-Za-z]+", ref).group(0).upper():
        n = n * 26 + ord(ch) - 64
    return n - 1


def _zdielane(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    return ["".join(t.text or "" for t in si.iter(S + "t")) for si in _xml(z, "xl/sharedStrings.xml").iter(S + "si")]


def _harky(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    """[(názov listu, cesta k XML v zipe)] v poradí zošita."""
    wb = _xml(z, "xl/workbook.xml")
    rels = {r.get("Id"): r.get("Target") for r in _xml(z, "xl/_rels/workbook.xml.rels")}
    out = []
    for h in wb.iter(S + "sheet"):
        cil = rels.get(h.get(R + "id"), "")
        cil = cil.lstrip("/")
        out.append((h.get("name") or "?", cil if cil.startswith("xl/") else "xl/" + cil))
    return out


def excel_harky(path: str) -> list[str]:
    with zipfile.ZipFile(path) as z:
        return [n for n, _ in _harky(z)]


def excel(path: str, harok: int = 0) -> dict:
    """{'harky': [názvy], 'harok': index, 'riadky': [[text bunky]], 'orezane'}: bunky ako zobrazený text, prázdne vľavo
    aj vpravo orezané; chyba -> ValueError / KeyError."""
    with zipfile.ZipFile(path) as z:
        harky = _harky(z)
        if not harky:
            raise ValueError("zošit nemá žiadny list")
        harok = max(0, min(harok, len(harky) - 1))
        zdielane = _zdielane(z)
        koren = _xml(z, harky[harok][1])
    riadky, orezane, max_s = [], False, 0
    for r in koren.iter(S + "row"):
        if len(riadky) >= MAX_RIADKOV:
            orezane = True
            break
        cislo = int(r.get("r") or len(riadky) + 1)
        while len(riadky) < cislo - 1 and len(riadky) < MAX_RIADKOV:
            riadky.append([])
        bunky: dict[int, str] = {}
        for c in r.findall(S + "c"):
            t, v = c.get("t"), c.find(S + "v")
            if t == "inlineStr":
                text = "".join(x.text or "" for x in c.iter(S + "t"))
            elif v is None or v.text is None:
                continue
            elif t == "s":
                text = zdielane[int(v.text)] if int(v.text) < len(zdielane) else ""
            elif t == "b":
                text = "áno" if v.text == "1" else "nie"
            else:
                text = v.text
            col = _stlpec(c.get("r") or "A1")
            if col < MAX_STLPCOV and text != "":
                bunky[col] = text
        riadok = [bunky.get(i, "") for i in range(max(bunky) + 1)] if bunky else []
        max_s = max(max_s, len(riadok))
        riadky.append(riadok)
    while riadky and not any(riadky[-1]):
        riadky.pop()                                      # prázdne riadky na konci
    return {"harky": [n for n, _ in harky], "harok": harok, "riadky": [r + [""] * (max_s - len(r)) for r in riadky],
            "orezane": orezane}
