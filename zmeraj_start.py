"""Meranie štartu Lupy – koľko trvajú dotazy, ktoré Lupa robí pri spustení.

Spustenie:  python zmeraj_start.py [cesta k DB]      (predvolene L:\\_Lupa\\lupa.db)
Len číta (DB otvára len na čítanie). Voliteľne skopíruje DB do %TEMP% a zmeria to isté lokálne
(rozdiel = vplyv siete), kópiu potom zmaže. Stačí čistý Python, nič netreba inštalovať.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

VYSTUP = Path(__file__).with_name("zmeraj_start.txt")
_subor = open(VYSTUP, "w", encoding="utf-8")
_print = print


def print(*a, **kw):  # do okna aj do zmeraj_start.txt
    _print(*a, **kw)
    _print(*a, **kw, file=_subor, flush=True)


def ro_uri(path: Path) -> str:  # rovnaké ako db.ro_uri
    p = str(path.absolute()).replace("\\", "/")
    if p.startswith("//?/UNC/"):
        p = "//" + p[8:]
    elif p.startswith("//?/"):
        p = p[4:]
    if not p.startswith("//"):
        p = "/" + p
    return "file://" + quote(p, safe="/:") + "?mode=ro"


# dotazy presne ako app.py pri štarte (každý vlastné spojenie – tak to robí Lupa)
KROKY = [
    ("get_meta: scan_log", "SELECT finished FROM scan_log ORDER BY id DESC LIMIT 1"),
    ("get_meta: počty zákazníci/zákazky/súbory",
     "SELECT (SELECT COUNT(*) FROM customers), (SELECT COUNT(*) FROM jobs), (SELECT COUNT(*) FROM files)"),
    ("get_meta: počet odtlačkov", "SELECT COUNT(*) FROM prints WHERE views IS NOT NULL"),
    ("get_meta: počet PDF", "SELECT COUNT(*) FROM files WHERE ftype = 'PDF'"),
    ("get_owners", "SELECT owner, COUNT(*) FROM files GROUP BY owner"),
    ("get_tree: zákazníci", "SELECT id, name, path FROM customers ORDER BY name COLLATE NOCASE"),
    ("get_tree: zákazky + podpriečinky",
     "SELECT j.id, j.customer_id, j.name, j.path,"
     " (SELECT COUNT(*) FROM positions p WHERE p.job_id = j.id AND p.rel_path <> '')"
     " FROM jobs j ORDER BY j.name COLLATE NOCASE"),
    ("get_tree: úplnosť (typy v zákazkách)", "SELECT job_id, ftype, ext FROM files GROUP BY job_id, ftype, ext"),
]


def zmeraj(db: Path, nadpis: str) -> None:
    print(f"\n== {nadpis}: {db}")
    spolu = 0.0
    for meno, sql in KROKY:
        t = time.perf_counter()
        con = sqlite3.connect(ro_uri(db), uri=True)
        try:
            n = len(con.execute(sql).fetchall())
        except sqlite3.Error as e:
            n = f"chyba: {e}"
        finally:
            con.close()
        dt = time.perf_counter() - t
        spolu += dt
        print(f"  {dt:7.2f} s  {meno}  ({n} riadkov)")
    print(f"  {spolu:7.2f} s  SPOLU")


def velkosti(db: Path) -> None:
    con = sqlite3.connect(ro_uri(db), uri=True)
    try:
        rows = con.execute("SELECT name, SUM(pgsize) FROM dbstat GROUP BY name ORDER BY 2 DESC").fetchall()
    except sqlite3.Error:  # dbstat býva vypnutý – aspoň objem odtlačkov
        n, b = con.execute("SELECT COUNT(*), SUM(LENGTH(views)) FROM prints").fetchone()
        con.close()
        print(f"\n== Odtlačky: {n} záznamov, {(b or 0) / 2**20:.1f} MB dát")
        return
    con.close()
    print("\n== Veľkosť tabuliek a indexov")
    for name, size in rows[:12]:
        print(f"  {size / 2**20:8.1f} MB  {name}")


def main() -> None:
    db = Path(sys.argv[1] if len(sys.argv) > 1 else r"L:\_Lupa\lupa.db")
    if not db.exists():
        sys.exit(f"DB {db} neexistuje")
    print(f"DB {db}  {db.stat().st_size / 2**20:.0f} MB")
    zmeraj(db, "Sieť (ako Lupa)")
    velkosti(db)
    if input("\nSkopírovať DB do %TEMP% a zmerať lokálne? [a/N] ").strip().lower() == "a":
        tmp = Path(tempfile.gettempdir()) / "lupa_meranie.db"
        t = time.perf_counter()
        shutil.copyfile(db, tmp)
        dt = time.perf_counter() - t
        print(f"\nkópia: {dt:.1f} s ({db.stat().st_size / 2**20 / dt:.0f} MB/s)")
        try:
            zmeraj(tmp, "Lokálne")
        finally:
            os.remove(tmp)
    print(f"\nVýsledok je aj v súbore {VYSTUP}")
    input("Hotovo – Enter zavrie okno.")


if __name__ == "__main__":
    main()
