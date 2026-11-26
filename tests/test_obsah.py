"""Hľadanie v obsahu NC programov: obsah.py (vlákna, riadky) a ObsahApi (výber z databázy)."""
import time

import pytest

import config
import db
import obsah


# ---------- obsah.py ----------
def test_najdi_riadky_text_a_regex():
    text = "N10 G0 X0\nTOOL CALL 25 Z S4500\nN30 M6\ntool call 12 Z\n"
    rx = obsah.preloz_dopyt("tool call", False, False)
    rx_m = obsah.re.compile(rx.pattern, rx.flags | obsah.re.MULTILINE)
    assert obsah.najdi_riadky(text, rx, rx_m, 50) == [(2, "TOOL CALL 25 Z S4500"), (4, "tool call 12 Z")]
    rx = obsah.preloz_dopyt("tool call", False, True)             # rozlišovať veľkosť
    assert [c for c, _ in obsah.najdi_riadky(text, rx, None, 50)] == [4]
    rx = obsah.preloz_dopyt(r"^TOOL CALL (12|25)\b", True, True)
    rx_m = obsah.re.compile(rx.pattern, rx.flags | obsah.re.MULTILINE)
    assert [c for c, _ in obsah.najdi_riadky(text, rx, rx_m, 50)] == [2]


def test_najdi_riadky_limit_na_subor_a_dlhy_riadok():
    rx = obsah.preloz_dopyt("X", False, False)
    assert len(obsah.najdi_riadky("X\n" * 100, rx, None, 7)) == 7
    assert len(obsah.najdi_riadky("X" + "a" * 1000, rx, None, 7)[0][1]) == 300


def test_chybny_regex():
    with pytest.raises(ValueError, match="regulárny"):
        obsah.preloz_dopyt("(", True, False)
    assert obsah.preloz_dopyt("(", False, False).search("a(b")      # doslovne – zátvorka nie je problém


def test_dekoduj_cp1250_a_utf8():
    assert obsah.dekoduj("žltá".encode("utf-8")) == "žltá"
    assert obsah.dekoduj("žltá".encode("cp1250")) == "žltá"


def _subory(tmp_path, n, obsah_suboru="TOOL CALL 5\n"):
    out = []
    for i in range(n):
        p = tmp_path / f"p{i}.h"
        p.write_text(obsah_suboru, encoding="utf-8")
        out.append({"id": i, "path": str(p), "name": p.name, "size": p.stat().st_size, "job_id": 1, "job": "J",
                    "customer": "C", "folder": ""})
    return out


def _pockaj(h, s=5):
    t = time.time()
    while not h.hotovo and time.time() - t < s:
        time.sleep(0.01)
    assert h.hotovo


def test_hladanie_vlakna_nalezy_a_chyby(tmp_path):
    subory = _subory(tmp_path, 40)
    subory.append({**subory[0], "id": 99, "path": str(tmp_path / "neexistuje.h")})
    h = obsah.Hladanie(subory, obsah.preloz_dopyt("tool call", False, False), max_nalezov=1000, na_subor=50, vlakna=4)
    h.start()
    _pockaj(h)
    s = h.stav()
    assert s["scanned"] == 41 and s["errors"] == 1 and len(s["hits"]) == 40 and s["files_with_hits"] == 40
    assert s["done"] and not s["limit"] and not s["stopped"]
    assert h.stav(39)["hits"] == s["hits"][39:]


def test_hladanie_limit_nalezov(tmp_path):
    h = obsah.Hladanie(_subory(tmp_path, 30), obsah.preloz_dopyt("tool", False, False), max_nalezov=10, na_subor=50,
                       vlakna=3)
    h.start()
    _pockaj(h)
    s = h.stav()
    assert len(s["hits"]) == 10 and s["limit"]


def test_hladanie_zastavenie(tmp_path):
    def pomale(path):
        time.sleep(0.05)
        return b"TOOL CALL\n"
    h = obsah.Hladanie(_subory(tmp_path, 200), obsah.preloz_dopyt("tool", False, False), max_nalezov=1000,
                       na_subor=50, vlakna=2, cita=pomale)
    h.start()
    time.sleep(0.2)
    h.stop()
    _pockaj(h)
    s = h.stav()
    assert s["stopped"] and s["scanned"] < 200


# ---------- ObsahApi (výber z databázy) ----------
class FalosneHlavne:
    """Namiesto Api: len `_q` nad dočasnou databázou."""

    def __init__(self, path):
        self.path = path

    def _q(self, sql, args=()):
        con = db.open_ro(self.path)
        try:
            return [dict(r) for r in con.execute(sql, args)]
        finally:
            con.close()

    def whoami(self):
        return {"owner": "jnovak"}


@pytest.fixture
def api(tmp_path):
    import app
    d = tmp_path / "db.sqlite"
    con = db.open_rw(d)
    teraz = time.time()
    con.execute("INSERT INTO customers(id, name, path) VALUES (1, '101270-Kuka Robotics', 'L:\\\\k'), (2, '100020-Iny', 'L:\\\\i')")
    con.execute("INSERT INTO jobs(id, customer_id, name, path, last_change) VALUES (1, 1, 'OD00021930', 'L:\\\\k\\\\a', ?),"
                " (2, 2, 'OD00000123', 'L:\\\\i\\\\b', ?)", (teraz, teraz))
    con.execute("INSERT INTO positions(id, job_id, name, rel_path, path) VALUES (1, 1, 'NC', 'NC', 'x'), (2, 2, 'NC', 'NC', 'y')")
    subory = [  # id, pozícia, zákazka, zákazník, názov, prípona, veľkosť, vek v dňoch, vlastník
        (1, 1, 1, 1, "a.h", "h", 1000, 1, "jnovak"), (2, 1, 1, 1, "b.mpf", "mpf", 2000, 1, "jnovak"),
        (3, 2, 2, 2, "c.h", "h", 3000, 500, "pkovac"), (4, 2, 2, 2, "d.eia", "eia", 4000, 1, "pkovac"),
        (5, 1, 1, 1, "velky.h", "h", 50 * 1048576, 1, "jnovak"), (6, 1, 1, 1, "e.pdf", "pdf", 10, 1, "jnovak"),
    ]
    for i, pos, job, cust, name, ext, size, vek, owner in subory:
        con.execute("INSERT INTO files(id, position_id, job_id, customer_id, name, ext, ftype, path, size, modified, owner)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (i, pos, job, cust, name, ext, "NC" if ext != "pdf" else "PDF", str(tmp_path / name), size,
                     teraz - vek * 86400, owner))
    con.commit()
    con.close()
    for _, _, _, _, name, *_ in subory:
        (tmp_path / name).write_text("TOOL CALL 25\n", encoding="utf-8")
    return app.ObsahApi(FalosneHlavne(d), {"label": "x"})


def test_odhad_podla_skupin_zakaznika_obdobia(api):
    assert api.estimate({"groups": ["heidenhain"]})["files"] == 2          # a.h + c.h (velky.h sa preskočí)
    assert api.estimate({"groups": ["heidenhain"]})["skipped"] == 1
    assert api.estimate({"groups": ["heidenhain", "sinumerik", "mazak"]})["files"] == 4
    assert api.estimate({"groups": ["heidenhain"], "customer_id": 1})["files"] == 1
    assert api.estimate({"groups": ["heidenhain", "mazak"], "scope_text": "kuka"})["files"] == 1
    assert api.estimate({"groups": ["heidenhain", "mazak"], "scope_text": "00000123"})["files"] == 2
    assert api.estimate({"groups": ["heidenhain"], "days": 30})["files"] == 1
    assert api.estimate({"groups": ["heidenhain", "mazak"], "owner": "pkovac"})["files"] == 2
    assert api.estimate({"groups": []})["files"] == 0
    assert api.estimate({"groups": ["heidenhain"], "job_id": 2})["files"] == 1


def test_potvrdenie_pri_velkom_vybere(api, monkeypatch):
    assert api.estimate({"groups": ["heidenhain"]})["confirm"] is False
    monkeypatch.setattr(config, "OBSAH_POTVRDIT_SUBOROV", 1)
    assert api.estimate({"groups": ["heidenhain", "mazak"]})["confirm"] is True


def test_start_poll_a_chyby(api):
    assert not api.start({"q": "", "groups": ["heidenhain"]})["ok"]
    assert "regulárny" in api.start({"q": "(", "regex": True, "groups": ["heidenhain"]})["error"]
    r = api.start({"q": "tool call", "groups": ["heidenhain", "mazak"]})
    assert r["ok"] and r["total"] == 3
    t = time.time()
    while not api.poll(0)["done"] and time.time() - t < 5:
        time.sleep(0.02)
    s = api.poll(0)
    assert len(s["hits"]) == 3 and {h["name"] for h in s["hits"]} == {"a.h", "c.h", "d.eia"}
    assert s["hits"][0]["line"] == 1 and "TOOL CALL" in s["hits"][0]["text"]


def test_navrhy_zakaznika_a_zakazky(api):
    n = api.suggest("kuk")
    assert n[0]["kind"] == "zákazník" and n[0]["customer_id"] == 1
    z = api.suggest("21930")
    assert z[0]["kind"] == "zákazka" and z[0]["job_id"] == 1 and "\\" in z[0]["label"]
    assert api.suggest("k") == []
