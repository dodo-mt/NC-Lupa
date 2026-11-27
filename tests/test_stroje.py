"""Stroj z hlavičky NC programu: `STROJ:` je samostatné slovo (nie koniec slova `Nastroj:`)."""
import stroje


def hlavicka(tmp_path, text, meno="p.h"):
    f = tmp_path / meno
    f.write_text(text, encoding="cp1250")
    return stroje.read_head(str(f))


def test_stroj_z_roznych_zapisov_hlavicky(tmp_path):
    assert hlavicka(tmp_path, "0 BEGIN PGM X MM\n7 ;  (STROJ: DMU 65 monoBLOCK)\n")[0] == "DMU 65 monoBLOCK"
    assert hlavicka(tmp_path, ";STROJ : GMX 250L - SIEMENS 840D\n")[0] == "GMX 250L - SIEMENS 840D"
    assert hlavicka(tmp_path, "Stroj: DMC 105 - H530\n")[0] == "DMC 105 - H530"
    assert hlavicka(tmp_path, "  STROJ:DMU 80\n")[0] == "DMU 80"


def test_nastroj_nie_je_stroj(tmp_path):
    nastroje = "Nastrojovy list\n* Nastroj: T3025   - FRE-D50-PL-S\n* Nastroj: T2355   - FRE-D8-TK-ALU-S\n"
    assert hlavicka(tmp_path, nastroje, "Nastroje.nc") == (None, None)               # nesmie vzniknúť „stroj“ T3025 - …
    assert hlavicka(tmp_path, "; (Nastroj: VRT-D5-TK | E.3617 | L=48)\n7 ;  (STROJ: DMU 65 monoBLOCK)\n")[0] == "DMU 65 monoBLOCK"


def test_predvolene_pravidla_zo_stroje_json():
    """Predvolené pravidlá strojov sú z modelov (nc_parsery.stroje): hlavičky z hyperMILLu aj Edgecamu, prvá zhoda vyhráva."""
    import config
    assert config.STROJE.modely                                      # súbor / cache / vstavané
    assert {"3X H530", "mono 3X", "mono H640", "mono 840D", "eVo 80", "DMC 60", "WFL"} <= {n for _rx, n in config.DEFAULT_MACHINES}
    for text, skratka in [
        ("DMG DMU 65 monoBLOCK", "mono H640"), ("DMG DMU 65 monoBLOCK 3X", "mono 3X"), ("3x-HH iTNC530", "3X H530"),
        ("DMU 65 monoBLOCK - H640", "mono H640"), ("DMU 75 monoBLOCK - Sinumerik 840D", "mono 840D"),
        ("DMU 80 eVo - B/C", "eVo 80"), ("DMU 60 eVo", "eVo 60"), ("DMG DMC 60", "DMC 60"), ("DMU 60 U", "DMC 60"),
        ("DMC 80-160 - H530", "DMC 160"), ("Kaoming C4000 SV - H530", "Kaoming"), ("Mikron HPM 450U", "HPM 450"),
        ("NTX2000/SZM - Fanuc 31i", "NTX"), ("MAZAK INTEGREX J-200S - MAZATROL SmoothG (EIA/ISO)", "J200"),
    ]:
        assert stroje.short_name(text) == skratka, text
