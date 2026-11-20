"""Skener Lupy – prejde koreň so zákazkami a zapíše súbory do SQLite.

Na disku so zákazkami sa nič nemení, len číta. Jediný zápis je databáza.

Použitie:
    python scanner.py [--root L:\\] [--db lupa.db] [--full] [--only "Zákazník"]
"""
import argparse
import logging
import os
import sys
import time
from pathlib import Path

import config
import db

try:
    import win32security
except ImportError:  # bez pywin32 sa vlastník nezisťuje
    win32security = None

log = logging.getLogger("lupa.scanner")


# ---------------------------------------------------------------------------
# Dlhé cesty (> 260 znakov) – prefix \\?\
# ---------------------------------------------------------------------------
def to_long(p: str) -> str:
    if p.startswith("\\\\?\\"):
        return p
    p = os.path.abspath(p)
    if p.startswith("\\\\"):  # UNC \\server\share
        return "\\\\?\\UNC\\" + p[2:]
    return "\\\\?\\" + p


def to_short(p: str) -> str:
    if p.startswith("\\\\?\\UNC\\"):
        return "\\\\" + p[8:]
    if p.startswith("\\\\?\\"):
        return p[4:]
    return p


# ---------------------------------------------------------------------------
# Vlastník súboru = „kto to robil“
# ---------------------------------------------------------------------------
class OwnerResolver:
    def __init__(self):
        self._cache: dict[str, str] = {}  # SID -> meno

    def get(self, long_path: str) -> str:
        if win32security is None:
            return "?"
        try:
            sd = win32security.GetFileSecurity(long_path, win32security.OWNER_SECURITY_INFORMATION)
            sid = sd.GetSecurityDescriptorOwner()
            key = win32security.ConvertSidToStringSid(sid)
        except Exception as e:
            log.debug("Vlastník nezistený %s: %s", long_path, e)
            return "?"
        name = self._cache.get(key)
        if name is None:
            try:
                name = win32security.LookupAccountSid(None, sid)[0]
            except Exception:
                name = key  # neznámy účet – aspoň SID
            self._cache[key] = name
        return name


# ---------------------------------------------------------------------------
# Skener
# ---------------------------------------------------------------------------
def split_ext(name: str) -> tuple[str, int | None]:
    """Vráti (prípona, verzia). '612234.prt.5' -> ('prt', 5); 'a.pdf' -> ('pdf', None)."""
    parts = name.rsplit(".", 2)
    if len(parts) == 3 and parts[2].isdigit() and parts[1].lower() in config.VERSIONED_EXTS:
        return parts[1].lower(), int(parts[2])
    return (parts[-1].lower() if len(parts) > 1 else ""), None


def drop_old_versions(cands: list) -> list:
    """Z verzovaných súborov (Creo) nechá v priečinku len najvyššiu verziu.

    cands: [(entry, ext, verzia)]
    """
    newest: dict[str, int] = {}
    for entry, _ext, ver in cands:
        if ver is not None:
            base = entry.name.rsplit(".", 1)[0].lower()
            newest[base] = max(newest.get(base, -1), ver)
    return [
        c for c in cands
        if c[2] is None or c[2] == newest[c[0].name.rsplit(".", 1)[0].lower()]
    ]


def is_dir(entry: os.DirEntry) -> bool:
    try:
        return entry.is_dir(follow_symlinks=False)
    except OSError:
        return False


class Scanner:
    def __init__(self, con, root: str, full: bool, only: str | None, recent_days: int):
        self.con = con
        self.root = os.path.abspath(root)
        self.full = full
        self.only = only
        self.recent_cutoff = time.time() - recent_days * 86400
        self.owners = OwnerResolver()
        self.files_seen = 0
        self.errors = 0
        self.jobs_scanned = 0
        self.jobs_skipped = 0

    def _error(self, msg: str, *args):
        self.errors += 1
        log.warning(msg, *args)

    def _scandir(self, long_path: str) -> list[os.DirEntry]:
        try:
            with os.scandir(long_path) as it:
                return list(it)
        except OSError as e:
            self._error("Nedá sa čítať %s: %s", to_short(long_path), e)
            return []

    # --- zákazníci ---------------------------------------------------------
    def run(self):
        started = time.time()
        mode = ("full" if self.full else "incr") + (f" only={self.only}" if self.only else "")
        log.info("Sken %s, koreň %s", mode, self.root)

        known = {row[0]: row[1] for row in self.con.execute("SELECT path, id FROM customers")}
        seen = set()
        found_only = False

        for entry in self._scandir(to_long(self.root)):
            if not is_dir(entry) or entry.name.lower() in config.IGNORE_ROOT_DIRS:
                continue
            if self.only and entry.name.lower() != self.only.lower():
                continue
            found_only = True
            path = to_short(entry.path)
            seen.add(path)
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                mtime = None
            cid = known.get(path)
            if cid is None:
                cid = self.con.execute(
                    "INSERT INTO customers(name, path, dir_mtime) VALUES (?,?,?)",
                    (entry.name, path, mtime),
                ).lastrowid
            else:
                self.con.execute("UPDATE customers SET dir_mtime=? WHERE id=?", (mtime, cid))
            self.con.commit()
            self.scan_customer(cid, entry.path)

        if self.only and not found_only:
            log.error("Zákazník '%s' sa v %s nenašiel.", self.only, self.root)
        if not self.only:
            for path, cid in known.items():
                if path not in seen:
                    log.info("Zákazník zmizol, mažem z DB: %s", path)
                    self.con.execute("DELETE FROM customers WHERE id=?", (cid,))
            self.con.commit()

        finished = time.time()
        self.con.execute(
            "INSERT INTO scan_log(started, finished, mode, files_seen, errors) VALUES (?,?,?,?,?)",
            (started, finished, mode, self.files_seen, self.errors),
        )
        self.con.commit()
        log.info(
            "Hotovo za %.1f s: zákazky preskenované %d, preskočené %d, súbory %d, chyby %d",
            finished - started, self.jobs_scanned, self.jobs_skipped, self.files_seen, self.errors,
        )

    # --- zákazky -----------------------------------------------------------
    def scan_customer(self, cid: int, long_path: str):
        # Zoznam zákaziek sa číta vždy (lacné) – mtime zákazky porovnávame s DB.
        known = {
            row[0]: row[1:]
            for row in self.con.execute(
                "SELECT path, id, dir_mtime, last_change FROM jobs WHERE customer_id=?", (cid,)
            )
        }
        seen = set()
        for entry in self._scandir(long_path):
            if not is_dir(entry) or entry.name.lower() in config.IGNORE_DIRS:
                continue
            path = to_short(entry.path)
            seen.add(path)
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                mtime = None
            row = known.get(path)
            if row is None:
                jid = self.con.execute(
                    "INSERT INTO jobs(customer_id, name, path) VALUES (?,?,?)",
                    (cid, entry.name, path),
                ).lastrowid
                need = True
            else:
                jid, old_mtime, last_change = row
                need = (
                    self.full
                    or mtime != old_mtime
                    or (last_change or 0) >= self.recent_cutoff
                )
            if need:
                self.scan_job(jid, cid, entry.name, entry.path, mtime)
            else:
                self.jobs_skipped += 1

        for path, (jid, *_rest) in known.items():
            if path not in seen:
                log.info("Zákazka zmizla, mažem z DB: %s", path)
                self.con.execute("DELETE FROM jobs WHERE id=?", (jid,))
        self.con.commit()

    def scan_job(self, jid: int, cid: int, job_name: str, long_path: str, job_mtime):
        """Celú zákazku zmaže z DB a načíta nanovo."""
        log.info("Zákazka %s", to_short(long_path))
        self.con.execute("DELETE FROM files WHERE job_id=?", (jid,))
        self.con.execute("DELETE FROM positions WHERE job_id=?", (jid,))

        last_change = job_mtime or 0
        rows = []
        stack = [(long_path, "")]
        while stack:
            dir_long, rel = stack.pop()
            pid = self.con.execute(
                "INSERT INTO positions(job_id, name, rel_path, path) VALUES (?,?,?,?)",
                (jid, rel.rsplit("\\", 1)[-1] if rel else job_name, rel, to_short(dir_long)),
            ).lastrowid
            subdirs = []
            cands = []
            for entry in self._scandir(dir_long):
                name = entry.name
                if is_dir(entry):
                    if name.lower() not in config.IGNORE_DIRS:
                        subdirs.append((entry.path, f"{rel}\\{name}" if rel else name))
                    continue
                ext, ver = split_ext(name)
                if name.lower() in config.IGNORE_FILES or ext in config.IGNORE_EXTS:
                    continue
                cands.append((entry, ext, ver))

            for entry, ext, _ver in drop_old_versions(cands):
                name = entry.name
                try:
                    st = entry.stat()
                except OSError as e:
                    self._error("Nedá sa zistiť stat %s: %s", to_short(entry.path), e)
                    continue
                created = getattr(st, "st_birthtime", st.st_ctime)
                last_change = max(last_change, st.st_mtime)
                rows.append((
                    pid, jid, cid, name, ext, config.ftype_for_ext(ext), to_short(entry.path),
                    st.st_size, created, st.st_mtime, self.owners.get(entry.path),
                ))
            # abecedne, aby pozície mali stabilné poradie id
            stack.extend(sorted(subdirs, reverse=True))

        self.con.executemany(
            "INSERT INTO files(position_id, job_id, customer_id, name, ext, ftype, path,"
            " size, created, modified, owner) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        self.con.execute(
            "UPDATE jobs SET dir_mtime=?, last_scan=?, last_change=? WHERE id=?",
            (job_mtime, time.time(), last_change, jid),
        )
        self.con.commit()
        self.files_seen += len(rows)
        self.jobs_scanned += 1


def setup_logging(db_path: Path, verbose: bool):
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(db_path.with_name("lupa_scan.log"), encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root = logging.getLogger("lupa")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(fh)
    root.addHandler(sh)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lupa – sken zákaziek do SQLite")
    ap.add_argument("--root", default=str(config.ROOT), help="koreň so zákazkami (predvolene z lupa.ini)")
    ap.add_argument("--db", default=str(config.DB_PATH), help="cesta k databáze")
    ap.add_argument("--full", action="store_true", help="úplný sken všetkých zákaziek")
    ap.add_argument("--only", help="skenovať len jedného zákazníka (názov priečinka)")
    ap.add_argument("--recent-days", type=int, default=config.RECENT_DAYS,
                    help="inkrementálne: znova prejsť zákazky so zmenou za posledných N dní")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    db_path = Path(args.db).resolve()
    con = db.open_rw(db_path)
    setup_logging(db_path, args.verbose)
    if win32security is None:
        log.warning("pywin32 nie je nainštalovaný – vlastník súborov bude '?'")
    if not os.path.isdir(args.root):
        log.error("Koreň neexistuje: %s", args.root)
        return 2

    Scanner(con, args.root, args.full, args.only, args.recent_days).run()
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
