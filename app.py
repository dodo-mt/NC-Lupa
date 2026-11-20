"""Lupa – okno prehliadača zákaziek (pywebview).

Databázu otvára len na čítanie. Na disku so zákazkami nič nemení.
"""
import base64
import os
import subprocess
import sys
from pathlib import Path

import webview

import config
import db
import thumbs
import winstate

if getattr(sys, "frozen", False):
    UI_DIR = Path(getattr(sys, "_MEIPASS", config.APP_DIR)) / "ui"
else:
    UI_DIR = Path(__file__).resolve().parent / "ui"

FILE_COLS = "f.id, f.name, f.ftype, f.path, f.size, f.created, f.modified, f.owner, p.rel_path AS folder"
SEARCH_LIMIT = 2000  # max. počet riadkov vo výsledku


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
        self._db_path = db_path

    def _q(self, sql: str, args=()) -> list[dict]:
        # Spojenie len na dobu dotazu – Lupa nedrží súbor DB otvorený, aby ho skener
        # mohol na zdieľanom disku vymeniť za novú verziu.
        if not self._db_path.exists():
            return []
        con = db.open_ro(self._db_path)
        try:
            return [dict(r) for r in con.execute(sql, args)]
        finally:
            con.close()

    # --- údaje pre UI ------------------------------------------------------
    def get_meta(self) -> dict:
        types = [
            {"key": k, "label": label, "bg": bg, "fg": fg}
            for k, (label, _exts, bg, fg) in config.FILE_TYPES.items()
        ]
        key, label, bg, fg = config.OTHER_TYPE
        types.append({"key": key, "label": label, "bg": bg, "fg": fg})
        last = self._q("SELECT finished, mode, files_seen, errors FROM scan_log ORDER BY id DESC LIMIT 1")
        return {
            "completeness": [n for n, _t, _e in config.COMPLETENESS],
            "root": str(config.ROOT),
            "db": str(self._db_path),
            "db_ok": self._db_path.exists(),
            "types": types,
            "last_scan": last[0] if last else None,
        }

    def get_tree(self) -> list[dict]:
        """Zákazníci so zákazkami (bez priečinkov – tie sa načítajú pri rozbalení)."""
        customers = self._q("SELECT id, name FROM customers ORDER BY name COLLATE NOCASE")
        jobs = self._q(
            "SELECT j.id, j.customer_id, j.name,"
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

    def get_job(self, job_id: int) -> dict | None:
        rows = self._q(
            "SELECT j.id, j.name, j.path, c.name AS customer FROM jobs j"
            " JOIN customers c ON c.id = j.customer_id WHERE j.id = ?",
            (job_id,),
        )
        return rows[0] if rows else None

    def get_owners(self) -> list[dict]:
        return self._q(
            "SELECT owner, COUNT(*) AS n FROM files GROUP BY owner ORDER BY owner COLLATE NOCASE"
        )

    def search(self, params: dict) -> dict:
        """Hľadanie + filtre.

        params: q (text, slová sa AND-ujú), owner ('' = všetci), types (zoznam kľúčov,
        prázdny/None = všetky), scope ('job' | 'all'), job_id, rel (priečinok v zákazke).
        """
        q = (params.get("q") or "").strip()
        owner = params.get("owner") or ""
        types = params.get("types")
        scope = params.get("scope") or "job"
        job_id = params.get("job_id")
        rel = params.get("rel") or ""

        where: list[str] = []
        args: list = []
        if scope == "job":
            if not job_id:
                return {"rows": [], "total": 0, "limit": SEARCH_LIMIT}
            where.append("f.job_id = ?")
            args.append(job_id)
            if rel:
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
            f"SELECT {FILE_COLS}, f.job_id, j.name AS job, c.name AS customer"
            + base + " ORDER BY f.modified DESC LIMIT ?",
            args + [SEARCH_LIMIT],
        )
        return {"rows": rows, "total": total[0]["n"] if total else 0, "limit": SEARCH_LIMIT}

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
                "SELECT 1 FROM positions WHERE path = ? UNION SELECT 1 FROM jobs WHERE path = ?",
                (folder, folder),
            )
            if not known or not os.path.isdir(folder):
                return {"ok": False, "error": "Priečinok neexistuje."}
            os.startfile(folder)
            return {"ok": True}
        return {"ok": False, "error": "Nič na otvorenie."}


def main():
    api = Api(config.DB_PATH)
    window = webview.create_window(
        "Lupa",
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
        storage_path=str(config.LOCAL_DIR / "webview"),
    )


if __name__ == "__main__":
    main()
