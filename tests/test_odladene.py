"""Odladené programy = priečinok odlad* kdekoľvek pod zákazkou / pozíciou."""
import sqlite3
import time

import pytest

import db
import odladene


def test_je_odladene_podla_priecinka():
    p = odladene.Pravidlo()
    assert p.je_odladene("NC\\DMC 160\\odladene")
    assert p.je_odladene("odladene")
    assert p.je_odladene("Odladené\\NC")                  # pred aj za ďalšími priečinkami
    assert p.je_odladene("NC/ODLADENÉ/stare")
    assert p.je_odladene("NC\\Odladene programy")
    assert p.je_odladene("NC\\DMC 160\\Zo stroja") and p.je_odladene("zo_stroja\\x") and p.je_odladene("NC\\ZO STROJA\\nove")
    assert not p.je_odladene("NC\\zoznam") and not p.je_odladene("NC\\stroja")            # len „Zo … stroja“
    assert not p.je_odladene("NC\\neodladene")              # len priečinok odlad*, nie obsahujúci „odlad“
    assert not p.je_odladene("NC\\stare\\nove")
    assert not p.je_odladene("")
    assert not p.je_odladene(None)


def test_vlastne_vzory_z_ini():
    p = odladene.Pravidlo({"odladene_priecinky": "*overene*, OK"})
    assert p.je_odladene("NC\\Overene") and p.je_odladene("ok") and not p.je_odladene("NC\\odladene")
    assert odladene.Pravidlo({"odladene_priecinky": ""}).je_odladene("odladene")      # prázdne = predvolené


def test_sql_zhoduje_sa_s_python_pravidlom(tmp_path):
    cesty = ["", "NC", "NC\\DMC 160\\odladene", "odladene", "Odladené\\NC", "NC\\neodladene", "NC\\odladene2\\x",
             "NC\\stare", "odlad", "NC\\a_odladene", "NC\\100%odlad", "NC\\Zo stroja", "Zo_Stroja\\NC", "NC\\zoznam"]
    con = db.open_rw(tmp_path / "t.sqlite")
    con.execute("INSERT INTO customers(id, name, path) VALUES (1, 'K', 'x')")
    con.execute("INSERT INTO jobs(id, customer_id, name, path) VALUES (1, 1, 'J', 'y')")
    for i, c in enumerate(cesty, 1):
        con.execute("INSERT INTO positions(id, job_id, name, rel_path, path) VALUES (?, 1, 'n', ?, ?)", (i, c, f"p{i}"))
    con.commit()
    p = odladene.Pravidlo()
    sql, args = p.sql("p")
    z_sql = {r[0] for r in con.execute(f"SELECT rel_path FROM positions p WHERE {sql}", args)}
    z_py = {c for c in cesty if p.je_odladene(c)}
    assert z_sql == z_py == {"NC\\DMC 160\\odladene", "odladene", "Odladené\\NC", "NC\\odladene2\\x", "odlad",
                             "NC\\Zo stroja", "Zo_Stroja\\NC"}
    con.close()


def test_filter_v_hladani_v_obsahu_a_odhad(tmp_path):
    import app
    d = tmp_path / "db.sqlite"
    con = db.open_rw(d)
    con.execute("INSERT INTO customers(id, name, path) VALUES (1, 'K', 'x')")
    con.execute("INSERT INTO jobs(id, customer_id, name, path, last_change) VALUES (1, 1, 'J', 'y', ?)", (time.time(),))
    con.execute("INSERT INTO positions(id, job_id, name, rel_path, path) VALUES (1, 1, 'a', 'NC\\\\DMC\\\\odladene', 'a'),"
                " (2, 1, 'b', 'NC\\\\DMC', 'b')")
    for i, (pos, name) in enumerate([(1, "dobry.h"), (1, "dobry2.h"), (2, "skusobny.h")], 1):
        con.execute("INSERT INTO files(id, position_id, job_id, customer_id, name, ext, ftype, path, size, modified)"
                    " VALUES (?, ?, 1, 1, ?, 'h', 'NC', ?, 100, ?)", (i, pos, name, str(tmp_path / name), time.time()))
    con.commit()
    con.close()

    class Falosne:
        def _q(self, sql, args=()):
            c = db.open_ro(d)
            try:
                return [dict(r) for r in c.execute(sql, args)]
            finally:
                c.close()

        def whoami(self):
            return {"owner": ""}

    api = app.ObsahApi(Falosne(), {})
    assert api.estimate({"groups": ["heidenhain"]})["files"] == 3
    assert api.estimate({"groups": ["heidenhain"], "odladene": True})["files"] == 2
    assert api.estimate({"groups": ["heidenhain"], "odladene": False})["files"] == 3


def _db_s_odladenymi(tmp_path):
    d = tmp_path / "t2.sqlite"
    con = db.open_rw(d)
    con.execute("INSERT INTO customers(id, name, path) VALUES (1, 'K', 'x')")
    for j in (1, 2, 3):
        con.execute("INSERT INTO jobs(id, customer_id, name, path) VALUES (?, 1, ?, ?)", (j, f"J{j}", f"y{j}"))
    # job 1: NC v odladene; job 2: odladene bez NC (len PDF); job 3: NC mimo odladene
    con.execute("INSERT INTO positions(id, job_id, name, rel_path, path) VALUES (1, 1, 'a', 'NC\\odladene', 'a'),"
                " (2, 2, 'b', 'odladene', 'b'), (3, 3, 'c', 'NC', 'c')")
    for i, (pos, job, name, ext, ft) in enumerate([(1, 1, "a.h", "h", "NC"), (2, 2, "v.pdf", "pdf", "PDF"),
                                                     (3, 3, "c.h", "h", "NC")], 1):
        con.execute("INSERT INTO files(id, position_id, job_id, customer_id, name, ext, ftype, path, size, modified)"
                    " VALUES (?, ?, ?, 1, ?, ?, ?, ?, 10, 1)", (i, pos, job, name, ext, ft, str(tmp_path / name)))
    con.commit()
    con.close()
    return d


class Falosne2:
    def __init__(self, d):
        self.d = d

    def _q(self, sql, args=()):
        c = db.open_ro(self.d)
        try:
            return [dict(r) for r in c.execute(sql, args)]
        finally:
            c.close()


def test_zakazky_s_odladenymi_programami(tmp_path):
    import app
    api = Falosne2(_db_s_odladenymi(tmp_path))
    odl = app.Api._odladene_jobs(api)
    assert set(odl) == {1} and odl[1][0] == 1                     # prázdny / bez NC priečinok odladene nestačí
    assert odl[1][1] == 1                                         # čas zmeny najnovšieho odladeného programu


def test_rychly_nahlad_textu(tmp_path):
    import app
    d = _db_s_odladenymi(tmp_path)
    (tmp_path / "a.h").write_text("\n".join(f"{i} L X{i}" for i in range(1, 6001)), encoding="utf-8")
    api = Falosne2(d)
    r = app.Api.get_text_preview(api, 1)
    assert r["ok"] and r["name"] == "a.h" and len(r["lines"]) == app.QUICK_LINES and r["more"] is True
    assert r["lines"][0] == "1 L X1"
    (tmp_path / "a.h").write_text("N1\nN2\n", encoding="utf-8")
    r = app.Api.get_text_preview(api, 1)
    assert r["lines"] == ["N1", "N2"] and r["more"] is False
    assert app.Api.get_text_preview(api, 2)["ok"] is False        # PDF – rýchly náhľad len pre text
    assert app.Api.get_text_preview(api, 99)["ok"] is False       # nie je v databáze
    (tmp_path / "a.h").unlink()
    assert "nedá prečítať" in app.Api.get_text_preview(api, 1)["error"]


NC_DMC = "NC" + chr(92) + "DMC"            # rel_path v databáze (priečinky oddelené spätným lomítkom)


def _db_nastrojovy_list(tmp_path):
    d = tmp_path / "tl.sqlite"
    con = db.open_rw(d)
    con.execute("INSERT INTO customers(id, name, path) VALUES (1, '101270-Firma', 'x')")
    con.execute("INSERT INTO jobs(id, customer_id, name, path) VALUES (1, 1, 'OD00021930', 'y')")
    con.execute("INSERT INTO positions(id, job_id, name, rel_path, path) VALUES (1, 1, 'a', 'NC\\DMC\\odladene', 'a'),"
                " (2, 1, 'b', 'NC\\DMC\\neodladene', 'b'), (3, 1, 'c', 'NC\\EVO', 'c')")
    obsah_h = {
        "dobry.h": "1 ; (Nastroj: FRE-D16 | | L=40 LL=90)\n2 TOOL CALL 2965 Z S1\n3 TOOL CALL 155 Z S1\n",
        "skusobny.h": "1 TOOL CALL 777 Z S1\n",
        "evo.h": "1 TOOL CALL 5 Z S1\n",
    }
    for i, (pos, name) in enumerate([(1, "dobry.h"), (2, "skusobny.h"), (3, "evo.h")], 1):
        (tmp_path / name).write_text(obsah_h[name], encoding="utf-8")
        con.execute("INSERT INTO files(id, position_id, job_id, customer_id, name, ext, ftype, path, size, modified)"
                    " VALUES (?, ?, 1, 1, ?, 'h', 'NC', ?, 100, 1)", (i, pos, name, str(tmp_path / name)))
    con.commit()
    con.close()
    return d


def _tl_api(d):
    import app

    class Stub(Falosne2):
        _tl_vyber = app.Api._tl_vyber

    return app, Stub(d)


def test_nastrojovy_list_odhad_a_filter(tmp_path):
    app, api = _tl_api(_db_nastrojovy_list(tmp_path))
    e = app.Api.tools_list_estimate(api, {"job_id": 1})
    assert (e["files"], e["odl_files"], e["all_files"]) == (3, 1, 3)
    assert app.Api.tools_list_estimate(api, {"job_id": 1, "odladene": True})["files"] == 1
    assert app.Api.tools_list_estimate(api, {"job_id": 1, "rel": NC_DMC})["files"] == 2        # priečinok a pod ním
    assert app.Api.tools_list_estimate(api, {})["ok"] is False


def test_nastrojovy_list_text(tmp_path):
    app, api = _tl_api(_db_nastrojovy_list(tmp_path))
    r = app.Api.tools_list_build(api, {"job_id": 1, "odladene": True})
    assert r["ok"] and r["programov"] == 1 and r["nazov_suboru"] == "nastroje_OD00021930.txt"
    riadky = r["text"].splitlines()
    assert riadky[0] == "Nástrojový list" and riadky[1] == "Zákazník : 101270-Firma"
    assert "Programy : len odladené, 1" in riadky
    assert "dobry.h   [" + NC_DMC + "\\odladene]" in riadky
    assert "  T2965  FRE-D16" in riadky and "  T155" in riadky
    assert "skusobny.h" not in r["text"]
    vsetko = app.Api.tools_list_build(api, {"job_id": 1, "rel": NC_DMC})
    assert vsetko["ok"] and vsetko["programov"] == 2 and "Priečinok : " + NC_DMC in vsetko["text"].splitlines()
    assert vsetko["nazov_suboru"].startswith("nastroje_OD00021930_NC")


def test_nastrojovy_list_prilis_velky_rozsah(tmp_path, monkeypatch):
    app, api = _tl_api(_db_nastrojovy_list(tmp_path))
    monkeypatch.setattr(app, "TL_MAX_SUBOROV", 2)
    r = app.Api.tools_list_build(api, {"job_id": 1})
    assert r["ok"] is False and "príliš veľký" in r["error"]


def _db_porovnanie(tmp_path):
    d = tmp_path / "cmp.sqlite"
    con = db.open_rw(d)
    con.execute("INSERT INTO customers(id, name, path) VALUES (1, 'K', 'x')")
    con.execute("INSERT INTO jobs(id, customer_id, name, path) VALUES (1, 1, 'J1', 'y'), (2, 1, 'J2', 'z')")
    con.execute("INSERT INTO positions(id, job_id, name, rel_path, path) VALUES (1, 1, 'a', 'NC', 'a'),"
                " (2, 1, 'b', 'NC\\odladene', 'b'), (3, 1, 'c', 'NC\\neodladene', 'c'), (4, 2, 'd', 'odladene', 'd'),"
                " (5, 1, 'e', 'NC\\odladene2', 'e')")
    subory = [  # id, pozícia, zákazka, meno
        (1, 1, 1, "Dobry.H"), (2, 2, 1, "dobry.h"), (3, 3, 1, "dobry.h"), (4, 4, 2, "dobry.h"),
        (5, 1, 1, "iny.h"), (6, 2, 1, "iny.mpf"), (7, 1, 1, "dva.h"), (8, 2, 1, "dva.h"), (9, 5, 1, "dva.h"),
        (10, 2, 1, "bezpara.h"), (11, 1, 1, "bezpara2.h")]
    for i, pos, job, name in subory:
        con.execute("INSERT INTO files(id, position_id, job_id, customer_id, name, ext, ftype, path, size, modified)"
                    " VALUES (?, ?, ?, 1, ?, ?, 'NC', ?, 10, ?)", (i, pos, job, name, name.rsplit('.', 1)[1].lower(),
                                                                 str(tmp_path / f"{i}_{name}"), i))
    con.commit()
    con.close()
    return d


def test_porovnat_s_odladenou_verziou(tmp_path, monkeypatch):
    import app

    class Stub(Falosne2):
        compare_in_editor = lambda self, ids, lines=None: {"ok": True, "ids": ids}

    api = Stub(_db_porovnanie(tmp_path))
    r = app.Api.compare_with_debugged(api, 1)                     # Dobry.H ↔ dobry.h v NC\odladene (nie J2, nie neodladene)
    assert r["ok"] and r["ids"] == [1, 2] and r["b"] == "dobry.h" and r["folder"].endswith("odladene")
    r = app.Api.compare_with_debugged(api, 5)                     # iny.h ↔ rovnaké meno bez prípony: iny.mpf
    assert r["ok"] and r["ids"] == [5, 6]
    r = app.Api.compare_with_debugged(api, 7)                     # dva.h má dve odladené verzie -> výber
    assert r["ok"] and {v["id"] for v in r["vyber"]} == {8, 9} and "ids" not in r
    assert "nenašiel" in app.Api.compare_with_debugged(api, 11)["error"]
    assert "už v odladenom" in app.Api.compare_with_debugged(api, 2)["error"]      # sám je v odladenom priečinku
    assert app.Api.compare_with_debugged(api, 999)["ok"] is False


def test_nahlad_okolo_nalezu(tmp_path):
    import app
    d = _db_porovnanie(tmp_path)
    (tmp_path / "5_iny.h").write_text("\n".join(f"L{i}" for i in range(1, 12001)), encoding="utf-8")
    api = Falosne2(d)
    r = app.Api.get_text_preview(api, 5)                                  # bez riadka: začiatok
    assert r["first"] == 1 and r["lines"][0] == "L1" and len(r["lines"]) == app.QUICK_LINES
    r = app.Api.get_text_preview(api, 5, 9000)                            # nález ďaleko od začiatku
    assert r["first"] > 1 and r["more"] and r["lines"][9000 - r["first"]] == "L9000"
    r = app.Api.get_text_preview(api, 5, 12000)                           # nález na konci
    assert r["lines"][-1] == "L12000" and r["lines"][12000 - r["first"]] == "L12000"
    r = app.Api.get_text_preview(api, 5, 10)                              # nález na začiatku
    assert r["first"] == 1 and r["lines"][9] == "L10"
