"""Nástroje NC programu v Lupe: parser je v spoločnom balíku `nc_parsery` (nc_parsery/nastroje.py, kod_nastroja.py), tu ostáva
len text Nástrojového listu (zoznam nástrojov zákazky / priečinka). Formáty, ktoré parser číta: Heidenhain (`TOOL CALL`), Sinumerik
(`T="…"` + M6 / `TC(`, `TLCH1` v archíve `.WPD`), Fanuc / Mazak (`T73020801 M6`, hlavička `.EIA`), NTX (`G0T…(názov)`); kódy nástrojov
sa dekódujú na typ, priemer a polomer.
"""
import nc_parsery_cesta  # noqa: F401 – pridá priečinok balíka nc_parsery do sys.path
from nc_parsery.nastroje import MAX_NASTROJOV, parsuj, rozpoznaj  # noqa: F401 – re-export (app.py, testy)


def zostav_text(hlavicka: list[tuple[str, str]], programy: list[dict]) -> str:
    """Nástrojový list ako text: zarovnaná hlavička (`Zákazka  : …`), prázdny riadok a programy; pod každým programom
    riadok na nástroj – číslo T a za ním názov (Siemens bez čísla = len názov). Poradie nástrojov = poradie prvého volania.
    hlavicka = [(názov, hodnota)], programy = [{'nazov', 'priecinok', 'nastroje': [...], 'chyba': ''}]."""
    sirka = max((len(k) for k, _ in hlavicka), default=0)
    out = ["Nástrojový list"]
    out += [f"{k.ljust(sirka)} : {v}" for k, v in hlavicka]
    for p in programy:
        out += ["", p["nazov"] + (f"   [{p['priecinok']}]" if p.get("priecinok") else "")]
        n = p.get("nastroje") or []
        if p.get("chyba"):
            out.append(f"  ({p['chyba']})")
            continue
        if not n:
            out.append("  (v programe sa nenašli volania nástrojov)")
            continue
        cisla = [("T" + x["cislo"]) if x.get("cislo") else "" for x in n]
        w = max(len(c) for c in cisla)
        for c, x in zip(cisla, n):
            nazov = x.get("nazov") or ("" if x.get("cislo") else x.get("t", ""))
            out.append(("  " + (c.ljust(w) + "  " if w else "") + nazov).rstrip())
    return "\n".join(out) + "\n"
