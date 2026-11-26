"""Osemmiestny kód nástroja (kódovanie Viena) -> typ, priemer, polomer plátku.

Zdroj: Excel `kodovanie_viena.xls` (vzorky/), overené na skutočných programoch (.WPD, GMX/Gamma, Mazak). Dve rozloženia kódu:
  A) nepoháňané sústružnícke nože:     TT NN RR SS   RR = polomer plátku v desatinách mm (73020803 -> R0,8)
  D) vŕtanie, závitníky, vyvŕtavanie:   TT N DDD SS   DDD = priemer v DESATINÁCH mm (02212582 -> Ø12,5)
  M) frézy:                             TT N DDD SS   DDD = priemer v CELÝCH mm (40102053 -> Ø20)
TT = typ nástroja, N / NN = poradové číslo, SS = koncové dvojčíslie stroja (01 GMX, 02 Gamma, 03 WFL, 04 Mazak – pri novších
Mazak programoch nespoľahlivé, preto sa tu NEPOUŽÍVA). Typ `5X` / `6X` (rádiusová fréza): písmeno X = polomer (A = 0,5 … P = 8 mm).
Typy 90 a 95 sa prekrývajú (nepoháňaný navrtávač / kotúčová fréza, špeciálny nástroj / iný druh frézy) – nedekódujú sa.
Za kódom môže byť písmeno (`74020202R`) – ignoruje sa (význam nie je známy). Typy závitových nožov a valčekovania nemajú
zdokumentovaný význam RR – dekóduje sa len názov typu.
"""
import re

# typ -> (názov, rozloženie): "A" polomer, "D" priemer v desatinách mm, "M" priemer v mm, "" bez rozmeru
TYPY = {
    # nepoháňané – vonkajšie obrábanie
    "70": ("vonkajší hrubovací nôž pravý", "A"), "71": ("vonkajší hrubovací nôž ľavý", "A"),
    "72": ("vonkajší závitový nôž", ""), "73": ("neutrálny nástroj", "A"),
    "74": ("vonkajší zapichovák radiálny", "A"), "75": ("vonkajší zapichovák axiálny", "A"),
    "76": ("vonkajší pravý hladiaci nožík", "A"), "77": ("vonkajší ľavý hladiaci nožík", "A"),
    # nepoháňané – vnútorné obrábanie / vŕtanie
    "80": ("vnútorný hrubovací nôž pravý", "A"), "81": ("vnútorný hrubovací nôž ľavý", "A"),
    "82": ("vnútorný závitový nôž", ""), "83": ("nástroj na valčekovanie", ""),
    "84": ("vnútorný zapichovací nôž", "A"), "85": ("vnútorný hladiaci nôž pravý", "A"), "86": ("vnútorný hladiaci nôž ľavý", "A"),
    "87": ("plátkový vrták nepoháňaný", "D"), "88": ("HSS alebo tvrdokovový vrták nepoháňaný", "D"),
    "89": ("závitník nepoháňaný", "D"),
    "96": ("špeciálny nástroj vnútorný", ""), "97": ("oporný hrot", ""), "99": ("meracia sonda", ""),
    # poháňané – vŕtanie, závitníky, vyvŕtavanie
    "01": ("NC navrtávač", "D"), "02": ("HSS alebo tvrdokovový vrták", "D"), "03": ("vrták s rovným dnom", "D"),
    "04": ("stupňovitý vrták", "D"), "05": ("plátkový vrták", "D"),
    "10": ("metrický závitník", "D"), "11": ("metrický závitník s jemným stúpaním", "D"), "12": ("rúrkový závitník", "D"),
    "13": ("NPTF závitník", "D"), "14": ("iný druh závitníka", "D"),
    "20": ("vyvŕtavacia tyč hrubovacia", "D"), "21": ("mikrometrická hlavička dokončovacia", "D"),
    "22": ("výstružník", "D"), "23": ("výhrubník", "D"),
    # poháňané – frézovanie
    "30": ("HSS alebo tvrdokovový drážkovač", "M"), "31": ("plátkový drážkovač", "M"),
    "32": ("HSS alebo tvrdokovový zrážač hrán 90°", "M"), "33": ("plátkový zrážač hrán 90°", "M"),
    "34": ("plátkový zrážač hrán nastaviteľný", "M"), "35": ("HSS alebo tvrdokovový zrážač hrán s iným uhlom", "M"),
    "36": ("plátkový zrážač hrán s iným uhlom", "M"),
    "40": ("HSS alebo tvrdokovová valcová fréza", "M"), "41": ("plátková valcová fréza", "M"),
    "42": ("plátková valcová fréza s viacerými radmi", "M"), "43": ("HSS alebo tvrdokovová guľová fréza", "M"),
    "44": ("plátková guľová fréza", "M"), "45": ("HSS alebo tvrdokovová uhlová fréza 90°", "M"),
    "46": ("plátková uhlová fréza 90°", "M"), "47": ("HSS alebo tvrdokovová uhlová fréza s iným uhlom", "M"),
    "48": ("plátková uhlová fréza s iným uhlom", "M"), "49": ("frézovacia hlava", "M"),
    "50": ("fréza na rýchlostné frézovanie", "M"),
    "91": ("korunková fréza", "M"), "92": ("fréza na výrobu závitov", "M"), "93": ("štvrťková fréza", "M"),
    "94": ("gravírovacia ihla", "M"),
}
_KOD = re.compile(r"^(\d\d|[56][A-P])(\d{6})[A-Z]?$")


def je_kod(s: str) -> bool:
    """Má reťazec tvar osemmiestneho kódu nástroja (aj s písmenom `5A`…`6P` na začiatku a písmenom na konci)?"""
    return bool(_KOD.match(s or ""))


def _fmt(x: float) -> str:
    """0.8 -> `0.8`, 40.0 -> `40`, 0 -> `` (nulový rozmer sa nezobrazuje)."""
    return f"{x:.1f}".rstrip("0").rstrip(".") if x else ""


def dekoduj(kod: str) -> dict | None:
    """{'typ': názov typu, 'd': priemer mm, 'r': polomer mm} (rozmery môžu byť prázdne); None = nie je to známy kód."""
    m = _KOD.match(kod or "")
    if not m:
        return None
    tt, zv = m.groups()
    if tt[0] in "56" and tt[1].isalpha():                       # rádiusová fréza: písmeno = polomer, priemer v celých mm
        nazov = "HSS alebo tvrdokovová rádiusová fréza" if tt[0] == "5" else "plátková rádiusová fréza"
        return {"typ": nazov, "d": _fmt(int(zv[1:4])), "r": _fmt(0.5 * (ord(tt[1]) - 64))}
    typ = TYPY.get(tt)
    if not typ:
        return None
    nazov, rozlozenie = typ
    out = {"typ": nazov, "d": "", "r": ""}
    if rozlozenie == "A":
        out["r"] = _fmt(int(zv[2:4]) / 10)
    elif rozlozenie == "D":
        out["d"] = _fmt(int(zv[1:4]) / 10)
    elif rozlozenie == "M":
        out["d"] = _fmt(int(zv[1:4]))
    return out
