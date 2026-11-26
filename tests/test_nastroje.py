"""Nástroje NC programu v Lupe: API a text Nástrojového listu. Parser je v balíku nc_parsery (jeho testy sú tam)."""
import nastroje

HEID = """0 BEGIN PGM VZOR MM
1 ; ZAKAZNIK/ARTIKEL: anonym
2 ; T2965 D50 r2.5 Lc8.7 L40 - FRE-RYCH-D50-R2.5-XMR01
3 ; T1973 D12 r0 Lc26 L36 - FRE-D12-TK-HRUB-S
4 TOOL DEF 1973
5 TOOL CALL 2965 Z S1400 F1000 ;  (FRE-RYCH-D50)
6 L X+0 Y+0 FMAX
7 TOOL CALL 2965 Z S1400
8 TOOL DEF 1973
9 TOOL CALL 1973 Z S2000
10 TOOL CALL "SONDA" Z
11 TOOL CALL Q50 Z
12 END PGM VZOR MM
"""

def test_api_get_tools(tmp_path, monkeypatch):
    import app
    f = tmp_path / "p.h"
    f.write_text(HEID, encoding="utf-8")

    class Falosne:
        _known_file = lambda self, i: {1: str(f), 2: str(tmp_path / "nie.h")}.get(i)

    api = Falosne()
    r = app.Api.get_tools(api, 1)
    assert r["ok"] and r["typ"] == "heidenhain" and len(r["nastroje"]) == 4
    assert app.Api.get_tools(api, 2)["ok"] is False and app.Api.get_tools(api, 9)["ok"] is False
    monkeypatch.setattr(app.config, "OBSAH_MAX_MB", 0)
    assert "príliš veľký" in app.Api.get_tools(api, 1)["error"]


HEID_NASTROJ = """1 ; (Nastroj: FRE-RYCH-D16-R1.6-PL-ZCC-CT-S |  | L=40 LL=90)
2 ; (Upinac: Upinac frez. hlav D22 L050 - 606305-22 )
3 ; (Predlzenie:  )
4 TOOL CALL 2965 Z S1400
5 L X+0 FMAX
6 ; (Nastroj: HVIE-D10-TK)
7 ; (Upinac: )
8 TOOL CALL 155 Z S4500 DR-2.5
9 ; (Nastroj: FRE-D12-TK-HRUB-S | E.7676HL.1.1200 | L=36 LL=156)
10 TOOL CALL 1973 Z S3001
11 TOOL CALL 1973 Z S3001
12 ; (Nastroj: FRE-RYCH-D50-R2.5-PL-ZCCT-S-XMR01-050-A22-SD09-04C  L=40~
13 TOOL CALL 3000 Z S1
14 TOOL CALL 4000 Z S1
"""


SIEMENS_HYPERMILL = """; (Nastroj: zoznam)
; T933 VRT-D5-TK | R=2.5 R2=0. LCUT=35
; T101 FRE-D16-TK | R=0. R2=0. LCUT=40
N1 G40 G90 G17 G71
N20 GROUP_BEGIN(0,"1590 : T933 M6 - vrtat",0,0)
N21 MSG ("1590 : T933 M6 - vrtat")
N22 ; (Poznamka: )
N23 ; (Nastroj: VRT-D5-TK | E.3617.1.0500 | L=48. LL=168.)
N24 ; (Upinac: Tepelny D06 L120 3st slim | 606351-31)
N25 ; (Predlzenie:  | )
N26 T="VRT-D5-TK"
N27 M6
N28 L_39(0,0) ; (DL,DR)
N29 MSG ("1590: T933 M6 - vrtat")
N30 S5730
N31 M3
N50 GROUP_BEGIN(0,"1600 : T933 M6 - vrtat",0,0)
N51 MSG ("1600: T933 M6 - vrtat")
N52 G1 X1
N53 G1 X2
N54 G1 X3
N55 G1 X4
N56 G1 X5
N57 G1 X6
N58 G1 X7
N60 GROUP_BEGIN(0,"1700 : T101 M6 - frezovat",0,0)
N61 ; (Nastroj: FRE-D16-TK | | L=53 LL=148)
N62 T="FRE-D16-TK"
N63 M6
"""


def test_zostav_text_nastrojoveho_listu():
    heid = nastroje.parsuj(HEID_NASTROJ)["nastroje"]
    sin = nastroje.parsuj(SIEMENS_HYPERMILL)["nastroje"]
    text = nastroje.zostav_text(
        [("Zákazník", "101270-Firma"), ("Zákazka", "OD00021930"), ("Dátum", "26.11.2026")],
        [{"nazov": "a.h", "priecinok": "NC\DMC\odladene", "nastroje": heid},
         {"nazov": "b.mpf", "priecinok": "", "nastroje": sin},
         {"nazov": "c.h", "priecinok": "NC", "nastroje": []},
         {"nazov": "d.h", "priecinok": "NC", "nastroje": [], "chyba": "súbor sa nedá prečítať"}])
    riadky = text.splitlines()
    assert riadky[0] == "Nástrojový list"
    assert riadky[1:4] == ["Zákazník : 101270-Firma", "Zákazka  : OD00021930", "Dátum    : 26.11.2026"]   # zarovnané ':'
    assert riadky[4] == "" and riadky[5] == "a.h   [NC\DMC\odladene]"
    assert riadky[6] == "  T2965  FRE-RYCH-D16-R1.6-PL-ZCC-CT-S"
    assert "  T155   HVIE-D10-TK" in riadky                                    # čísla zarovnané do stĺpca
    assert "  T933  VRT-D5-TK" in riadky and "  T101  FRE-D16-TK" in riadky    # Siemens: číslo z hlavičky
    assert "  (v programe sa nenašli volania nástrojov)" in riadky and "  (súbor sa nedá prečítať)" in riadky
    assert text.endswith("\n")
    bez_cisla = nastroje.zostav_text([("Zákazka", "X")], [{"nazov": "s.mpf", "nastroje": [
        {"t": "FRE-D32", "cislo": "", "nazov": "FRE-D32"}, {"t": "VRT", "cislo": "", "nazov": "VRT"}]}]).splitlines()
    assert bez_cisla[-2:] == ["  FRE-D32", "  VRT"]                        # bez čísel len názov
