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
