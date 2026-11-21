"""Lupa – okno prehliadača zákaziek (pywebview).

Databázu otvára len na čítanie. Na disku so zákazkami nič nemení.
"""
import base64
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import webview

import config
import db
import dbcopy
import thumbs
import winstate

if getattr(sys, "frozen", False):
    UI_DIR = Path(getattr(sys, "_MEIPASS", config.APP_DIR)) / "ui"
else:
    UI_DIR = Path(__file__).resolve().parent / "ui"

FILE_COLS = "f.id, f.name, f.ftype, f.path, f.size, f.created, f.modified, f.owner, p.rel_path AS folder"
SEARCH_LIMIT = 2000  # max. počet riadkov vo výsledku
STALE_HOURS = 24     # posledný sken starší → v stavovom riadku oranžovo
SIMILAR_LIMIT = 60   # počet podobných výkresov vo výsledku
SIMILAR_MIN = 0.3    # slabšie zhody sa neukazujú


def _like_escape(s: str) -> str:
    return s.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def _term_to_like(term: str) -> str:
    """Hľadané slovo -> LIKE vzor.

    Bez zástupných znakov = časť názvu ('3674' -> '%3674%').
    So '*' / '?' = celý názov ('cnc_vyk*.pdf' -> 'cnc!_vyk%.pdf').
    """
    if "*" in term or "?" in term:
        return _like_escape(term).replace("*", "%").replace("?", "_")
    return f"%{_like_escape(term)}%"


class Api:
    """Metódy volané z JS cez window.pywebview.api.*

    Atribúty začínajúce '_' pywebview do JS nevystavuje.
    """

    def __init__(self, db_path: Path):
        self._db_path = db_path           # DB na sieti (L:\_Lupa\lupa.db) – len sa z nej kopíruje
        self._copy = dbcopy.LocalCopy(db_path)
        self._idx = None                  # (značka DB, ViewIndex, cesty) – podobné výkresy
        self._idx_lock = threading.Lock()
        self._cols = (None, "")           # (kópia DB, stĺpce súborov) – stará DB nemá files.target

    def _file_cols(self) -> str:
        """Stĺpce súborov pre UI; files.target (cieľ .lnk) má len DB od skenera 1.3.2."""
        path = self._copy.path()
        if self._cols[0] != path:
            has = any(r["name"] == "target" for r in self._q("PRAGMA table_info(files)"))
            self._cols = (path, FILE_COLS + (", f.target" if has else ", NULL AS target"))
        return self._cols[1]

    def _q(self, sql: str, args=()) -> list[dict]:
        # Dotazy idú do lokálnej kópie (dbcopy) – cez sieť je SQLite ~40× pomalšie.
        # Spojenie len na dobu dotazu, aby sa stará kópia dala po obnovení zmazať.
        path = self._copy.path()
        if not path:
            return []
        try:
            con = db.open_ro(path)
        except sqlite3.Error as e:  # do UI s cestou, aby bolo jasné, čo sa nedá otvoriť
            raise RuntimeError(f"databáza {path} sa nedá otvoriť ({e})") from e
        try:
            return [dict(r) for r in con.execute(sql, args)]
        finally:
            con.close()

    # --- lokálna kópia DB (štart) ------------------------------------------
    def prepare_db(self) -> dict:
        """Pri štarte: skopíruje DB zo siete, ak sa zmenila. Priebeh cez db_progress()."""
        t = time.perf_counter()
        path = self._copy.prepare()
        return {"ok": path is not None, "offline": self._copy.offline,
                "seconds": round(time.perf_counter() - t, 1)}

    def db_progress(self) -> dict | None:
        p = self._copy.progress
        return {"done": p[0], "total": p[1]} if p else None

    # --- údaje pre UI ------------------------------------------------------
    def get_meta(self) -> dict:
        types = [
            {"key": k, "label": label, "bg": bg, "fg": fg}
            for k, (label, _exts, bg, fg) in config.FILE_TYPES.items()
        ]
        key, label, bg, fg = config.OTHER_TYPE
        types.append({"key": key, "label": label, "bg": bg, "fg": fg})
        last = self._q("SELECT finished, mode, files_seen, errors FROM scan_log ORDER BY id DESC LIMIT 1")
        # lupa_scan.json vedľa DB sa zapisuje pri každom skene (aj bez zmien) – presnejší čas
        try:
            st = json.loads(self._db_path.with_name("lupa_scan.json").read_text(encoding="utf-8"))
            if not last or st.get("finished", 0) > last[0]["finished"]:
                last = [{"finished": st["finished"], "errors": st.get("errors", 0)}]
        except (OSError, ValueError, KeyError):
            pass
        counts = self._q(
            "SELECT (SELECT COUNT(*) FROM customers) AS customers, (SELECT COUNT(*) FROM jobs) AS jobs,"
            " (SELECT COUNT(*) FROM files) AS files"
        )
        if counts:
            try:  # stará DB tabuľku prints nemá
                counts[0].update(self._q(
                    "SELECT (SELECT COUNT(*) FROM prints WHERE views IS NOT NULL) AS prints,"
                    " (SELECT COUNT(*) FROM files WHERE ftype = 'PDF') AS pdfs")[0])
            except Exception:
                pass
        return {
            "version": config.VERSION,
            "completeness": [n for n, _t, _e in config.COMPLETENESS],
            "root": str(config.ROOT),
            "db": str(self._db_path),
            "db_ok": self._copy.current is not None,
            "offline": self._copy.offline,     # L:\ nedostupný – údaje z poslednej lokálnej kópie
            "types": types,
            "last_scan": last[0] if last else None,
            "counts": counts[0] if counts else None,
            "stale_hours": STALE_HOURS,
        }

    def get_tree(self) -> list[dict]:
        """Zákazníci so zákazkami (bez priečinkov – tie sa načítajú pri rozbalení)."""
        customers = self._q("SELECT id, name, path FROM customers ORDER BY name COLLATE NOCASE")
        # changed = posledná zmena v zákazke (menu zákaziek: novšie skôr, rok pri zákazke)
        has_lc = any(r["name"] == "last_change" for r in self._q("PRAGMA table_info(jobs)"))
        jobs = self._q(
            "SELECT j.id, j.customer_id, j.name, j.path,"
            f" {'COALESCE(j.last_change, j.dir_mtime)' if has_lc else 'j.dir_mtime'} AS changed,"
            " (SELECT COUNT(*) FROM positions p WHERE p.job_id = j.id AND p.rel_path <> '') AS subdirs"
            " FROM jobs j ORDER BY j.name COLLATE NOCASE"
        )
        # kontrola úplnosti: typy a prípony súborov v každej zákazke
        jtypes: dict[int, set] = {}
        jexts: dict[int, set] = {}
        for r in self._q("SELECT job_id, ftype, ext FROM files GROUP BY job_id, ftype, ext"):
            jtypes.setdefault(r["job_id"], set()).add(r["ftype"])
            jexts.setdefault(r["job_id"], set()).add(r["ext"])
        by_cust: dict[int, list] = {}
        for j in jobs:
            j["missing"] = config.missing_parts(jtypes.get(j["id"], set()), jexts.get(j["id"], set()))
            by_cust.setdefault(j.pop("customer_id"), []).append(j)
        for c in customers:
            c["jobs"] = by_cust.get(c["id"], [])
        return customers

    def get_positions(self, job_id: int) -> list[dict]:
        """Priečinky zákazky (rel_path, počet súborov priamo v nich)."""
        return self._q(
            "SELECT p.id, p.name, p.rel_path, p.path,"
            " (SELECT COUNT(*) FROM files f WHERE f.position_id = p.id) AS files"
            " FROM positions p WHERE p.job_id = ? AND p.rel_path <> ''"
            " ORDER BY p.rel_path COLLATE NOCASE",
            (job_id,),
        )

    def get_customer_positions(self, cust_id: int) -> dict:
        """Priečinky všetkých zákaziek zákazníka naraz {job_id: [pozície]} – pre „Rozbaliť všetko“."""
        rows = self._q(
            "SELECT p.job_id, p.id, p.name, p.rel_path, p.path,"
            " (SELECT COUNT(*) FROM files f WHERE f.position_id = p.id) AS files"
            " FROM positions p JOIN jobs j ON j.id = p.job_id"
            " WHERE j.customer_id = ? AND p.rel_path <> ''"
            " ORDER BY p.rel_path COLLATE NOCASE",
            (cust_id,),
        )
        out: dict[str, list] = {}
        for r in rows:
            out.setdefault(str(r.pop("job_id")), []).append(r)
        return out

    def get_job(self, job_id: int) -> dict | None:
        rows = self._q(
            "SELECT j.id, j.name, j.path, c.name AS customer FROM jobs j"
            " JOIN customers c ON c.id = j.customer_id WHERE j.id = ?",
            (job_id,),
        )
        return rows[0] if rows else None

    def get_owners(self, params: dict | None = None) -> list[dict]:
        """Vlastníci s počtom súborov – vo vybranej zákazke / u zákazníka, inak v celom koreni."""
        p = params or {}
        where, args = "", ()
        if p.get("job_id"):
            where, args = " WHERE job_id = ?", (p["job_id"],)
        elif p.get("customer_id"):
            where, args = " WHERE customer_id = ?", (p["customer_id"],)
        return self._q(
            f"SELECT owner, COUNT(*) AS n FROM files{where} GROUP BY owner ORDER BY owner COLLATE NOCASE", args
        )

    def locate(self, path: str) -> dict:
        """Kde je cesta (cieľ odkazu .lnk) v strome: súbor, priečinok zákazky alebo zákazník.
        Ak cesta v DB nie je (napr. preskakovaný súbor), berie sa najbližší nadradený priečinok.

        Vracia {'ok', 'job_id', 'rel', 'file_id', 'cust_id', 'exact'} alebo {'ok': False, 'error'}.
        """
        if not path:
            return {"ok": False, "error": "Cieľ odkazu sa nepodarilo zistiť."}
        f = self._q("SELECT f.id, f.job_id, p.rel_path FROM files f JOIN positions p ON p.id = f.position_id"
                    " WHERE f.path = ? COLLATE NOCASE LIMIT 1", (path,))
        if f:
            return {"ok": True, "job_id": f[0]["job_id"], "rel": f[0]["rel_path"], "file_id": f[0]["id"],
                    "exact": True}
        cur = path.rstrip("\\")
        while cur:
            pos = self._q("SELECT job_id, rel_path FROM positions WHERE path = ? COLLATE NOCASE LIMIT 1", (cur,))
            if pos:
                return {"ok": True, "job_id": pos[0]["job_id"], "rel": pos[0]["rel_path"], "file_id": None,
                        "exact": cur == path.rstrip("\\")}
            c = self._q("SELECT id FROM customers WHERE path = ? COLLATE NOCASE LIMIT 1", (cur,))
            if c:
                return {"ok": True, "cust_id": c[0]["id"], "exact": cur == path.rstrip("\\")}
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
        if not os.path.exists(path):
            return {"ok": False, "error": f"Cieľ odkazu neexistuje:\n{path}"}
        return {"ok": False, "error": f"Cieľ odkazu nie je v Lupe (mimo zákaziek):\n{path}"}

    def copy_text(self, text: str) -> dict:
        """Do schránky Windows (clipboard API prehliadača v okne nemusí byť povolené)."""
        try:
            import win32clipboard
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": f"Kopírovanie zlyhalo: {e}"}

    def search(self, params: dict) -> dict:
        """Hľadanie + filtre.

        params: q (text, slová sa AND-ujú), owner ('' = všetci), types (zoznam kľúčov,
        prázdny/None = všetky), scope ('job' = výber v strome | 'all'),
        customer_id (vybraný zákazník), job_id, rel (priečinok v zákazke).
        """
        q = (params.get("q") or "").strip()
        owner = params.get("owner") or ""
        types = params.get("types")
        scope = params.get("scope") or "job"
        cust_id = params.get("customer_id")
        job_id = params.get("job_id")
        rel = params.get("rel") or ""

        where: list[str] = []
        args: list = []
        if scope == "job":
            if not job_id and not cust_id:
                return {"rows": [], "total": 0, "limit": SEARCH_LIMIT}
            if not job_id:
                where.append("f.customer_id = ?")
                args.append(cust_id)
            else:
                where.append("f.job_id = ?")
                args.append(job_id)
            if job_id and rel:
                where.append("(p.rel_path = ? OR p.rel_path LIKE ? ESCAPE '!')")
                args += [rel, _like_escape(rel) + "\\%"]
        for term in q.split():
            where.append("f.name LIKE ? ESCAPE '!'")
            args.append(_term_to_like(term))
        if owner:
            where.append("f.owner = ?")
            args.append(owner)
        if types:
            where.append(f"f.ftype IN ({','.join('?' * len(types))})")
            args += list(types)

        base = (
            " FROM files f JOIN positions p ON p.id = f.position_id"
            " JOIN jobs j ON j.id = f.job_id JOIN customers c ON c.id = f.customer_id"
            + (" WHERE " + " AND ".join(where) if where else "")
        )
        total = self._q("SELECT COUNT(*) AS n" + base, args)
        rows = self._q(
            f"SELECT {self._file_cols()}, f.job_id, j.name AS job, c.name AS customer"
            + base + " ORDER BY f.modified DESC LIMIT ?",
            args + [SEARCH_LIMIT],
        )
        return {"rows": rows, "total": total[0]["n"] if total else 0, "limit": SEARCH_LIMIT}

    # --- podobné výkresy ----------------------------------------------------
    def _prints_index(self):
        """Index odtlačkov (odtlacky.ViewIndex, cesty) – v pamäti, znova sa načíta po výmene DB."""
        import odtlacky
        stamp = (self._copy.path(), odtlacky.VERSION)  # meno kópie sa mení s každou verziou DB
        with self._idx_lock:
            if self._idx and self._idx[0] == stamp:
                return self._idx[1], self._idx[2]
            rows = self._q("SELECT path, views FROM prints WHERE views IS NOT NULL AND version = ?",
                           (odtlacky.VERSION,))
            idx = odtlacky.ViewIndex([r["views"] for r in rows])
            paths = [r["path"] for r in rows]
            self._idx = (stamp, idx, paths)
            return idx, paths

    def similar(self, file_id: int, owner: str = "") -> dict:
        """Najpodobnejšie výkresy k PDF. Prvý riadok je hľadaný výkres (query=True).

        Vracia {'ok', 'rows' (s 'sim' 0..1), 'indexed' (počet výkresov s odtlačkom)} alebo {'ok': False, 'error'}.
        """
        import odtlacky
        if not self._copy.path():
            return {"ok": False, "error": "Databáza neexistuje."}
        me = self._q("SELECT path, ftype FROM files WHERE id = ?", (file_id,))
        if not me or me[0]["ftype"] != "PDF":
            return {"ok": False, "error": "Podobné výkresy sa hľadajú len k PDF."}
        path = me[0]["path"]
        try:
            pr = self._q("SELECT views, version FROM prints WHERE path = ?", (path,))
        except Exception:  # DB zo staršieho skenera – tabuľka prints chýba
            return {"ok": False, "error": "Databáza ešte nemá odtlačky výkresov – treba novší skener (lupa-sken.exe)."}
        if not pr or pr[0]["version"] != odtlacky.VERSION:
            return {"ok": False, "error": "Tento výkres ešte nemá odtlačok – skener ho spracuje "
                                          "pri niektorom z ďalších skenov."}
        if pr[0]["views"] is None:
            return {"ok": False, "error": "Z tohto PDF sa odtlačok nedá urobiť (prázdne alebo poškodené)."}
        try:
            idx, paths = self._prints_index()
        except Exception as e:  # napr. chýba numpy
            return {"ok": False, "error": f"Podobné výkresy nie sú k dispozícii: {e}"}
        scores = idx.search(pr[0]["views"])
        # kandidátov viac, filter vlastníka sa uplatní až na riadkoch súborov
        order = scores.argsort()[::-1][:SIMILAR_LIMIT * (5 if owner else 1) + 1]
        sim = {paths[i]: float(scores[i]) for i in order if scores[i] >= SIMILAR_MIN and paths[i] != path}
        sim[path] = 1.0
        rows = []
        keys = list(sim)
        for a in range(0, len(keys), 500):   # SQLite má limit počtu parametrov
            part = keys[a:a + 500]
            rows += self._q(
                f"SELECT {self._file_cols()}, f.job_id, j.name AS job, c.name AS customer"
                " FROM files f JOIN positions p ON p.id = f.position_id"
                " JOIN jobs j ON j.id = f.job_id JOIN customers c ON c.id = f.customer_id"
                f" WHERE f.path IN ({','.join('?' * len(part))})", part)
        for r in rows:
            r["sim"] = sim[r["path"]]
            r["query"] = r["id"] == file_id
        rows = [r for r in rows if r["query"] or not owner or r["owner"] == owner]
        rows.sort(key=lambda r: (not r["query"], -r["sim"]))
        return {"ok": True, "rows": rows[:SIMILAR_LIMIT + 1], "indexed": idx.n}

    # --- akcie -------------------------------------------------------------
    def _known_file(self, file_id: int) -> str | None:
        rows = self._q("SELECT path FROM files WHERE id = ?", (file_id,))
        return rows[0]["path"] if rows else None

    def get_thumb(self, file_id: int, size: str = "l") -> dict:
        """Náhľad súboru ako data URI (PNG) – z cache alebo novo vygenerovaný.

        size: 'l' = detail, 's' = galéria. Pri NC/txt vráti text.
        """
        rows = self._q("SELECT path, ftype, ext FROM files WHERE id = ?", (file_id,))
        if not rows:
            return {"ok": False, "error": "Súbor nie je v databáze."}
        f = rows[0]
        if f["ftype"] == "NC" or f["ext"] in thumbs.TEXT_EXTS:
            return thumbs.get_text(f["path"], 30 if size == "s" else thumbs.TEXT_MAX_LINES)
        r = thumbs.get_thumb(f["path"], f["ftype"], size)
        if r["ok"]:
            data = Path(r.pop("file")).read_bytes()
            r["src"] = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        return r

    def open_file(self, file_id: int) -> dict:
        path = self._known_file(file_id)
        if not path:
            return {"ok": False, "error": "Súbor nie je v databáze."}
        if not os.path.exists(path):
            return {"ok": False, "error": f"Súbor už neexistuje:\n{path}"}
        try:
            os.startfile(path)
            return {"ok": True}
        except OSError as e:
            return {"ok": False, "error": str(e)}

    def open_folder(self, file_id: int | None = None, folder: str | None = None) -> dict:
        """Otvorí Prieskumník – pri súbore ho v priečinku označí."""
        if file_id is not None:
            path = self._known_file(file_id)
            if not path or not os.path.exists(path):
                return {"ok": False, "error": "Súbor neexistuje."}
            subprocess.Popen(["explorer", "/select,", path])
            return {"ok": True}
        if folder:
            known = self._q(
                "SELECT 1 FROM positions WHERE path = ? UNION SELECT 1 FROM jobs WHERE path = ?"
                " UNION SELECT 1 FROM customers WHERE path = ?",
                (folder, folder, folder),
            )
            if not known or not os.path.isdir(folder):
                return {"ok": False, "error": "Priečinok neexistuje."}
            os.startfile(folder)
            return {"ok": True}
        return {"ok": False, "error": "Nič na otvorenie."}


WEB_STORAGE = config.LOCAL_DIR / "webview"


def clear_web_cache(storage: Path = WEB_STORAGE):
    """Zmaže HTTP cache WebView2 (nie localStorage s nastaveniami).

    pywebview servíruje UI vždy z rovnakej adresy (127.0.0.1:42001), takže po aktualizácii
    by WebView2 mohol použiť starý app.js / style.css z cache.
    """
    for sub in ("Cache", "Code Cache", "GPUCache"):
        for base in storage.glob("EBWebView/*/"):
            shutil.rmtree(base / sub, ignore_errors=True)


def main():
    clear_web_cache()
    api = Api(config.DB_PATH)
    window = webview.create_window(
        f"Lupa {config.VERSION}",
        str(UI_DIR / "index.html"),
        js_api=api,
        width=1440,
        height=900,
        min_size=(900, 560),
        background_color="#eef1f5",
    )
    winstate.attach(window, "main")
    # private_mode=False, aby sa pamätali nastavenia UI (šírky panelov) medzi spusteniami
    webview.start(
        debug="--debug" in sys.argv,
        private_mode=False,
        storage_path=str(WEB_STORAGE),
    )


if __name__ == "__main__":
    main()
