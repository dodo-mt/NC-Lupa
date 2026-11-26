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


def test_porovnanie_len_pre_novsiu_verziu(tmp_path, monkeypatch):
    monkeypatch.delenv("LUPA_NC_EDITOR_VERZIA", raising=False)
    volane = []
    monkeypatch.setattr(editor.subprocess, "Popen", lambda args, cwd=None: volane.append(args))
    _verzia(tmp_path, "2026.11.26-11")
    r = editor.otvor_porovnanie(r"L:\a.h", r"L:\b.h", None, None, tmp_path)
    assert r["ok"] is False and "ešte nevie porovnanie" in r["error"] and not volane
    _verzia(tmp_path, "2026.11.26-12")
    r = editor.otvor_porovnanie(r"L:\a.h", r"L:\b.h", 5, 7, tmp_path)
    assert r["ok"] and volane[0][1:] == ["--porovnaj", r"L:\a.h:5", r"L:\b.h:7"]
    assert editor.otvor_porovnanie("a", "b", None, None, tmp_path / "prazdno")["ok"] is False


def test_api_compare_in_editor(tmp_path, monkeypatch):
    import app
    a, b, c = tmp_path / "a.h", tmp_path / "b.mpf", tmp_path / "c.h"
    for f in (a, b, c):
        f.write_text("x")
    cesty = {1: str(a), 2: str(b), 3: str(c), 4: str(a)}

    class Falosne:
        _known_file = lambda self, i: cesty.get(i)

    volane = []
    monkeypatch.setattr(app.editor, "otvor_porovnanie",
                        lambda x, y, la, lb: volane.append((x, y, la, lb)) or {"ok": True})
    api = Falosne()
    assert app.Api.compare_in_editor(api, [1])["ok"] is False
    assert app.Api.compare_in_editor(api, [1, 1])["ok"] is False
    assert app.Api.compare_in_editor(api, [1, 4])["ok"] is False                     # tá istá cesta pod iným id
    assert app.Api.compare_in_editor(api, [1, 99])["ok"] is False
    r = app.Api.compare_in_editor(api, [1, 2], [10, 20])
    assert r["ok"] and "rôzne typy" in r["warn"] and volane[-1] == (str(a), str(b), 10, 20)
    r = app.Api.compare_in_editor(api, [1, 3])
    assert r["ok"] and "warn" not in r
