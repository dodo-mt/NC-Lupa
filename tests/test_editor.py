"""Otvorenie nálezu v NC Editore: výber najnovšej lokálnej verzie, riadok len ak ho verzia pozná."""
import editor


def _verzia(koren, nazov, exe=True):
    d = koren / nazov
    d.mkdir(parents=True)
    if exe:
        (d / editor.EXE).write_bytes(b"x")


def test_najde_najnovsiu_verziu(tmp_path):
    for v in ("2026.11.24-8", "2026.11.26-11", "2026.11.9-3", "2026.11.26-2"):
        _verzia(tmp_path, v)
    _verzia(tmp_path, "2026.12.01-1", exe=False)          # bez exe sa preskočí
    _verzia(tmp_path, "docasna.tmp")
    exe, v = editor.najdi_editor(tmp_path)
    assert v == "2026.11.26-11" and exe == tmp_path / "2026.11.26-11" / editor.EXE


def test_bez_editora(tmp_path):
    assert editor.najdi_editor(tmp_path) is None
    assert editor.najdi_editor(tmp_path / "neexistuje") is None
    r = editor.otvor(r"L:\x\p.h", 5, tmp_path)
    assert r["ok"] is False and "nie je nainštalovaný" in r["error"]


def test_riadok_len_pre_novsiu_verziu():
    assert editor.pozna_riadok("2026.11.26-11") and editor.pozna_riadok("2026.12.01-1")
    assert not editor.pozna_riadok("2026.11.24-8") and not editor.pozna_riadok("2026.11.26-10")
    assert editor.argument(r"L:\x\p.h", 40, "2026.11.26-11") == r"L:\x\p.h:40"
    assert editor.argument(r"L:\x\p.h", 40, "2026.11.24-8") == r"L:\x\p.h"
    assert editor.argument(r"L:\x\p.h", None, "2026.11.26-11") == r"L:\x\p.h"
    assert editor.argument(r"L:\x\p.h", 0, "2026.11.26-11") == r"L:\x\p.h"


def test_otvor_spusti_exe_s_argumentom(tmp_path, monkeypatch):
    _verzia(tmp_path, "2026.11.26-11")
    volane = []
    monkeypatch.setattr(editor.subprocess, "Popen", lambda args, cwd=None: volane.append((args, cwd)))
    r = editor.otvor(r"L:\x\p.h", 1250, tmp_path)
    assert r == {"ok": True, "line": True, "version": "2026.11.26-11"}
    assert volane[0][0][1] == r"L:\x\p.h:1250"
