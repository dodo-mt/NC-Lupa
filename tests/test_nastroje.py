"""Nástroje NC programu: rozpoznanie riadenia a čítanie volaní (vzory podľa anonymizovaných programov z NC Editora)."""
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

SINU = """; program
N10 G54
T="FRE-D32-PL-S"
M6
N20 G0 X0
T="VRT-D16"
N30 G1 X5
N31 G1 X6
N32 G1 X7
N33 G1 X8
N34 G1 X9
N35 G1 X9
T="FRE-D32-PL-S" ;predvolenie
M6
N40 M30
"""

FANUC = """O0001
T73020801(T000) M6
G0 X0
T01 M06
T73020801 M6
T5 (len predvolenie)
M30
"""


def podla_kluca(vysledok):
    return {n["t"]: n for n in vysledok["nastroje"]}


def test_rozpoznanie():
    assert nastroje.parsuj(HEID)["typ"] == "heidenhain"
    assert nastroje.parsuj(SINU)["typ"] == "sinumerik"
    assert nastroje.parsuj(FANUC)["typ"] == "fanuc"
    assert nastroje.parsuj("G1 X1\nG1 Y2\n") == {"typ": "", "nastroje": [], "riadkov": 2}
    assert nastroje.parsuj("")["nastroje"] == []


def test_heidenhain_nazov_rozmery_pocet_a_prvy_riadok():
    v = nastroje.parsuj(HEID)
    n = podla_kluca(v)
    assert [x["t"] for x in v["nastroje"]] == ["2965", "1973", "SONDA", "Q50"]
    assert n["2965"]["pocet"] == 2 and n["2965"]["prvy"] == 6 and n["2965"]["nazov"] == "FRE-RYCH-D50"
    assert (n["2965"]["d"], n["2965"]["r"], n["2965"]["lc"], n["2965"]["l"]) == ("50", "2.5", "8.7", "40")
    assert n["1973"]["pocet"] == 1 and n["1973"]["nazov"] == "FRE-D12-TK-HRUB-S"          # názov z hlavičky
    assert n["1973"]["prvy"] == 10                                                         # TOOL DEF sa nepočíta
    assert n["SONDA"]["nazov"] == "SONDA" and n["SONDA"]["pocet"] == 1


def test_sinumerik_pocita_len_t_s_m6():
    v = nastroje.parsuj(SINU)
    n = podla_kluca(v)
    assert [x["t"] for x in v["nastroje"]] == ["FRE-D32-PL-S"]            # VRT-D16 nemá M6 v dosahu
    assert n["FRE-D32-PL-S"]["pocet"] == 2 and n["FRE-D32-PL-S"]["prvy"] == 3


def test_fanuc_mazak():
    v = nastroje.parsuj(FANUC)
    n = podla_kluca(v)
    assert set(n) == {"73020801", "01"} and n["73020801"]["pocet"] == 2 and n["73020801"]["prvy"] == 2
    assert "5" not in n                                                    # T5 bez M6 je len komentár / predvolenie


def test_limit_poctu_nastrojov():
    text = "\n".join(f"{i} TOOL CALL {i} Z S1" for i in range(1, 900))
    assert len(nastroje.parsuj(text)["nastroje"]) == nastroje.MAX_NASTROJOV


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


def test_heidenhain_nazov_z_komentara_nad_volanim():
    n = podla_kluca(nastroje.parsuj(HEID_NASTROJ))
    assert n["2965"]["nazov"] == "FRE-RYCH-D16-R1.6-PL-ZCC-CT-S"          # `|` a `L=` sa odrežú
    assert n["155"]["nazov"] == "HVIE-D10-TK"                              # koncová zátvorka preč
    assert n["1973"]["nazov"] == "FRE-D12-TK-HRUB-S" and n["1973"]["pocet"] == 2
    assert n["3000"]["nazov"] == "FRE-RYCH-D50-R2.5-PL-ZCCT-S-XMR01-050-A22-SD09-04C"
    assert n["4000"]["nazov"] == ""                                        # komentár platí len pre najbližšie volanie
    assert n["2965"]["prvy"] == 4


def test_komentar_nad_volanim_ma_prednost_pred_zatvorkou_za_volanim():
    text = "1 ; (Nastroj: HLAVNY-NAZOV)\n2 TOOL CALL 7 Z S1 ;  (INY-NAZOV)\n"
    assert podla_kluca(nastroje.parsuj(text))["7"]["nazov"] == "HLAVNY-NAZOV"


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


def cislo_riadka(riadok):
    return SIEMENS_HYPERMILL.splitlines().index(riadok) + 1


def test_siemens_hypermill_cislo_nazov_rozmery_a_texty_v_uvodzovkach():
    v = nastroje.parsuj(SIEMENS_HYPERMILL)
    n = podla_kluca(v)
    assert v["typ"] == "sinumerik"
    assert set(n) == {"VRT-D5-TK", "FRE-D16-TK"}                         # `T933 M6` v MSG / GROUP_BEGIN nie je volanie
    vrt = n["VRT-D5-TK"]
    assert (vrt["cislo"], vrt["nazov"], vrt["pocet"], vrt["prvy"]) == ("933", "VRT-D5-TK", 1, cislo_riadka('N26 T="VRT-D5-TK"'))
    assert (vrt["r"], vrt["r2"], vrt["lc"], vrt["l"], vrt["ll"]) == ("2.5", "0", "35", "48", "168")
    fre = n["FRE-D16-TK"]
    assert (fre["cislo"], fre["l"], fre["ll"], fre["prvy"]) == ("101", "53", "148", cislo_riadka('N62 T="FRE-D16-TK"'))


def test_heidenhain_l_a_ll_z_komentara_nastroj():
    text = "1 ; (Nastroj: FRE-D12-TK | E.7676 | L=36 LL=156)\n2 TOOL CALL 1973 Z S1\n"
    n = podla_kluca(nastroje.parsuj(text))["1973"]
    assert (n["nazov"], n["l"], n["ll"], n["cislo"]) == ("FRE-D12-TK", "36", "156", "1973")


def test_cislo_a_retazce_vo_fanuc_nie_su_volanie():
    text = 'G0 X0\nMSG ("T55 M6 hlaska")\nT73020801(T000) M6\n'
    assert [x["t"] for x in nastroje.parsuj(text)["nastroje"]] == ["73020801"]


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
