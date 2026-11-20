"""Skener Lupy – prejde koreň so zákazkami a zapíše súbory do SQLite.

Na disku so zákazkami sa nič nemení, len číta. Jediný zápis je databáza.

Použitie:
    python scanner.py [--root L:\\] [--db lupa.db] [--full] [--only "Zákazník"]
"""
import argparse
import fnmatch
import hashlib
import json
import logging
import logging.handlers
import msvcrt
import os
import shutil
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


class ScanError(Exception):
    """Sken sa nedá vykonať (napr. koreň nie je dostupný)."""


class Scanner:
    def __init__(self, con, root: str, full: bool, only: str | None, recent_days: int, progress=None,
                 customers: list[str] | None = None, exclude: list[str] | None = None):
        self.con = con
        self.customers = customers or []  # vzory priečinkov v koreni, ktoré sú zákazníci ([] = všetky)
        self.exclude = exclude or []      # vzory priečinkov v koreni na vynechanie
        self.root = os.path.abspath(root)
        self.full = full
        self.only = only
        self.recent_cutoff = time.time() - recent_days * 86400
        self.owners = OwnerResolver()
        self.progress = progress  # callback(i, n, názov zákazníka) – pre ikonu pri hodinách
        self.files_seen = 0
        self.errors = 0
        self.jobs_scanned = 0
        self.jobs_skipped = 0
        self.jobs_changed = 0
        self.new_jobs: list[str] = []
        self.changed = False  # zmenil sa obsah DB (zákazky/súbory)? – rozhoduje o publikovaní

    def _error(self, msg: str, *args):
        self.errors += 1
        log.warning(msg, *args)

    def _scandir(self, long_path: str) -> list[os.DirEntry] | None:
        """Obsah priečinka; None pri chybe čítania (≠ prázdny priečinok!).

        Rozlíšenie je dôležité: pri výpadku siete sa nesmú z DB mazať zákazky.
        """
        try:
            with os.scandir(long_path) as it:
                return list(it)
        except OSError as e:
            self._error("Nedá sa čítať %s: %s", to_short(long_path), e)
            return None

    # --- zákazníci ---------------------------------------------------------
    def run(self):
        started = time.time()
        mode = ("full" if self.full else "incr") + (f" only={self.only}" if self.only else "")
        log.info("Sken %s, koreň %s (Lupa v%s)", mode, self.root, config.VERSION)

        fixed = self.fix_types()
        if fixed:
            log.info("Typ súboru opravený podľa config.py: %d súborov", fixed)
            self.changed = True

        known = {row[0]: row[1] for row in self.con.execute("SELECT path, id FROM customers")}
        seen = set()
        found_only = False

        entries = self._scandir(to_long(self.root))
        if entries is None:
            raise ScanError(f"Koreň {self.root} sa nedá čítať.")
        customers = []
        skipped = []
        for e in entries:
            if not is_dir(e) or e.name.lower() in config.IGNORE_ROOT_DIRS:
                continue
            if self.only:
                if e.name.lower() == self.only.lower():  # --only platí bez ohľadu na filter
                    customers.append(e)
            elif self.is_customer(e.name):
                customers.append(e)
            else:
                skipped.append(e.name)
        if skipped:
            log.info("Vynechané priečinky v koreni (customers/exclude v lupa.ini): %d – %s",
                     len(skipped), ", ".join(sorted(skipped, key=str.lower)))
        for i, entry in enumerate(customers, 1):
            if self.progress:
                self.progress(i, len(customers), entry.name)
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
                self.changed = True
            else:
                self.con.execute("UPDATE customers SET dir_mtime=? WHERE id=?", (mtime, cid))
            self.con.commit()
            self.scan_customer(cid, entry.path)

        if self.only and not found_only:
            log.error("Zákazník '%s' sa v %s nenašiel.", self.only, self.root)
        if not self.only:
            for path, cid in known.items():
                if path not in seen:
                    why = "vynechaný podľa lupa.ini" if Path(path).name in skipped else "zmizol"
                    log.info("Zákazník %s, mažem z DB: %s", why, path)
                    self.con.execute("DELETE FROM customers WHERE id=?", (cid,))
                    self.changed = True
            self.con.commit()

        finished = time.time()
        self.con.execute(
            "INSERT INTO scan_log(started, finished, mode, files_seen, errors) VALUES (?,?,?,?,?)",
            (started, finished, mode, self.files_seen, self.errors),
        )
        self.con.commit()
        log.info(
            "Hotovo za %.1f s: zákazky preskenované %d (zmenené %d), preskočené %d, súbory %d, chyby %d",
            finished - started, self.jobs_scanned, self.jobs_changed, self.jobs_skipped,
            self.files_seen, self.errors,
        )

    def fix_types(self) -> int:
        """Typ súborov v DB podľa aktuálneho mapovania v config.py (napr. po rozdelení XLS/DOC)
        – netreba úplný sken. Vracia počet opravených súborov."""
        n = 0
        for ext, ftype in self.con.execute("SELECT DISTINCT ext, ftype FROM files").fetchall():
            want = config.ftype_for_ext(ext)
            if want != ftype:
                n += self.con.execute("UPDATE files SET ftype = ? WHERE ext = ? AND ftype = ?",
                                      (want, ext, ftype)).rowcount
        self.con.commit()
        return n

    def is_customer(self, name: str) -> bool:
        low = name.lower()
        if any(fnmatch.fnmatchcase(low, p) for p in self.exclude):
            return False
        return not self.customers or any(fnmatch.fnmatchcase(low, p) for p in self.customers)

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
        entries = self._scandir(long_path)
        if entries is None:
            return  # priečinok zákazníka sa nedá čítať – v DB nič nemeniť
        for entry in entries:
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
                self.new_jobs.append(entry.name)
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
                self.changed = True
        self.con.commit()

    def scan_job(self, jid: int, cid: int, job_name: str, long_path: str, job_mtime):
        """Prejde zákazku; ak sa obsah líši od DB, zákazku v DB zmaže a zapíše nanovo.

        Vlastník sa pri nezmenených súboroch preberá z DB (GetFileSecurity cez sieť je pomalé).
        """
        last_change = job_mtime or 0
        dirs = []    # [(rel, name, path)]
        found = []   # [(rel, entry, ext)]
        stack = [(long_path, "")]
        while stack:
            dir_long, rel = stack.pop()
            dirs.append((rel, rel.rsplit("\\", 1)[-1] if rel else job_name, to_short(dir_long)))
            subdirs = []
            cands = []
            entries = self._scandir(dir_long)
            if entries is None:
                # časť zákazky sa nedá čítať – radšej nechať v DB starý stav
                log.warning("Zákazka %s sa nedala prečítať celá – ponechávam starý stav.", to_short(long_path))
                self.con.rollback()
                return
            for entry in entries:
                name = entry.name
                if is_dir(entry):
                    if name.lower() not in config.IGNORE_DIRS:
                        subdirs.append((entry.path, f"{rel}\\{name}" if rel else name))
                    continue
                ext, ver = split_ext(name)
                low = name.lower()
                if (low in config.IGNORE_FILES or ext in config.IGNORE_EXTS
                        or any(fnmatch.fnmatchcase(low, g) for g in config.IGNORE_GLOBS)):
                    continue
                cands.append((entry, ext, ver))

            for entry, ext, _ver in drop_old_versions(cands):
                try:
                    st = entry.stat()
                except OSError as e:
                    self._error("Nedá sa zistiť stat %s: %s", to_short(entry.path), e)
                    continue
                last_change = max(last_change, st.st_mtime)
                found.append((rel, entry, ext, st))
            # abecedne, aby pozície mali stabilné poradie id
            stack.extend(sorted(subdirs, reverse=True))

        self.files_seen += len(found)
        self.jobs_scanned += 1

        # porovnanie s DB: priečinky + (priečinok, názov, veľkosť, zmenený)
        old_dirs = {r[0] for r in self.con.execute("SELECT rel_path FROM positions WHERE job_id=?", (jid,))}
        old_files = {
            (r[0], r[1], r[2], r[3]): r[4]
            for r in self.con.execute(
                "SELECT p.rel_path, f.name, f.size, f.modified, f.owner FROM files f"
                " JOIN positions p ON p.id = f.position_id WHERE f.job_id=?", (jid,))
        }
        new_keys = {(rel, e.name, st.st_size, st.st_mtime) for rel, e, _x, st in found}
        # --full prepíše vždy (napr. po zmene typov v config.py)
        unchanged = not self.full and old_dirs == {d[0] for d in dirs} and set(old_files) == new_keys

        if not unchanged:
            log.info("Zákazka %s", to_short(long_path))
            self.con.execute("DELETE FROM files WHERE job_id=?", (jid,))
            self.con.execute("DELETE FROM positions WHERE job_id=?", (jid,))
            pids = {}
            for rel, name, path in dirs:
                pids[rel] = self.con.execute(
                    "INSERT INTO positions(job_id, name, rel_path, path) VALUES (?,?,?,?)",
                    (jid, name, rel, path),
                ).lastrowid
            rows = []
            for rel, e, ext, st in found:
                owner = old_files.get((rel, e.name, st.st_size, st.st_mtime)) or self.owners.get(e.path)
                rows.append((
                    pids[rel], jid, cid, e.name, ext, config.ftype_for_ext(ext), to_short(e.path),
                    st.st_size, getattr(st, "st_birthtime", st.st_ctime), st.st_mtime, owner,
                ))
            self.con.executemany(
                "INSERT INTO files(position_id, job_id, customer_id, name, ext, ftype, path,"
                " size, created, modified, owner) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            self.jobs_changed += 1
            self.changed = True
        self.con.execute(
            "UPDATE jobs SET dir_mtime=?, last_scan=?, last_change=? WHERE id=?",
            (job_mtime, time.time(), last_change, jid),
        )
        self.con.commit()


# ---------------------------------------------------------------------------
# Odtlačky výkresov (PDF) pre „Podobné výkresy“
# ---------------------------------------------------------------------------
def update_prints(con, minutes: float, customer: str | None = None, progress=None, on_change=None) -> dict:
    """Dopočíta chýbajúce / zastarané odtlačky PDF (najnovšie prvé), najviac `minutes` minút.

    Zmazaným PDF odtlačky odstráni. Vracia {'added', 'failed', 'removed', 'left'}.
    on_change(): zavolá sa pred prvým zápisom – značka „DB treba publikovať“ musí existovať skôr,
    ako sa sken môže prerušiť (ukončenie ikony, vypnutie PC).
    """
    res = {"added": 0, "failed": 0, "removed": 0, "left": 0}
    if minutes <= 0:
        return res
    try:
        import odtlacky
    except ImportError as e:
        log.warning("Odtlačky výkresov sa nepočítajú (chýba knižnica): %s", e)
        return res

    if not customer:
        res["removed"] = con.execute(
            "DELETE FROM prints WHERE path NOT IN (SELECT path FROM files WHERE ftype='PDF')").rowcount
        if res["removed"] and on_change:
            on_change()
        con.commit()

    sql = ("SELECT f.path, f.size, f.modified FROM files f LEFT JOIN prints p ON p.path = f.path"
           " WHERE f.ftype = 'PDF' AND (p.path IS NULL OR p.size IS NOT f.size"
           " OR p.modified IS NOT f.modified OR p.version IS NOT ?)")
    args = [odtlacky.VERSION]
    if customer:
        sql += " AND f.customer_id = (SELECT id FROM customers WHERE name = ? COLLATE NOCASE)"
        args.append(customer)
    todo = con.execute(sql + " ORDER BY f.modified DESC", args).fetchall()
    if not todo:
        return res

    log.info("Odtlačky výkresov: na spracovanie %d PDF (limit %g min)", len(todo), minutes)
    if on_change:
        on_change()
    deadline = time.time() + minutes * 60
    max_bytes = config.PRINTS_MAX_MB * 1024 * 1024
    processed = 0
    for i, (path, size, modified) in enumerate(todo):
        if time.time() > deadline:
            break
        processed += 1
        if progress and i % 20 == 0:
            progress(i + 1, len(todo), "odtlačky výkresov")
        blob = None
        if (size or 0) <= max_bytes:
            try:
                views = odtlacky.views(path if len(path) < 260 else to_long(path))
                blob = odtlacky.pack(views) if views else None
                res["added"] += 1
            except Exception as e:
                res["failed"] += 1
                log.debug("Odtlačok zlyhal %s: %s", path, e)
        con.execute("INSERT OR REPLACE INTO prints(path, size, modified, version, views) VALUES (?,?,?,?,?)",
                    (path, size, modified, odtlacky.VERSION, blob))
        if i % 50 == 49:
            con.commit()
    con.commit()
    res["left"] = len(todo) - processed
    log.info("Odtlačky výkresov: hotové %d, nedali sa spracovať %d, zostáva %d, zmazané %d",
             res["added"], res["failed"], res["left"], res["removed"])
    return res


LOCAL_LOG = config.LOCAL_DIR / "lupa_scan.log"


def setup_logging(shared_log: Path, verbose: bool):
    """Log lokálne (vždy, aj keď L:\\ nie je dostupný) + vedľa DB (ak sa dá). Rotácia 2 MB × 3."""
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger("lupa")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    LOCAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    for path in dict.fromkeys([LOCAL_LOG, shared_log]):
        try:
            fh = logging.handlers.RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3,
                                                      encoding="utf-8", delay=True)
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except OSError:
            pass
    if sys.stdout is not None:  # exe bez konzoly nemá stdout
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        root.addHandler(sh)


# ---------------------------------------------------------------------------
# Pracovná kópia DB a publikovanie
# ---------------------------------------------------------------------------
# Skener pracuje s lokálnou kópiou (rýchle, žiadne pomalé zápisy cez sieť) a cieľovú
# DB (napr. L:\_Lupa\lupa.db) nahradí naraz – čitatelia nikdy nevidia rozpracovaný stav.
# Lupa drží DB otvorenú len počas dotazu, takže výmena súboru prejde.

def work_path(target: Path) -> Path:
    tag = hashlib.sha1(str(target).lower().encode("utf-8")).hexdigest()[:10]
    return config.LOCAL_DIR / "scan" / f"lupa-{tag}.db"


def prepare_work(target: Path, work: Path):
    """Ak je cieľová DB novšia ako pracovná kópia (alebo kópia chýba), stiahne ju."""
    work.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and (not work.exists() or target.stat().st_mtime > work.stat().st_mtime + 1):
        log.info("Kopírujem DB %s -> %s", target, work)
        shutil.copy2(target, work)


def publish(work: Path, target: Path, attempts: int = 30):
    """Nahradí cieľovú DB pracovnou kópiou (cez dočasný súbor a os.replace)."""
    tmp = target.with_name(target.name + ".new")
    shutil.copy2(work, tmp)
    for i in range(attempts):
        try:
            os.replace(tmp, target)
            log.info("Publikované: %s", target)
            return True
        except PermissionError:
            time.sleep(2)  # niekto práve číta – skúsiť znova
    log.error("DB sa nepodarilo nahradiť (obsadená): %s", target)
    return False


def status_path(db_path: Path) -> Path:
    return db_path.with_name("lupa_scan.json")


def write_status(db_path: Path, res: dict):
    """Malý súbor vedľa DB s časom posledného skenu – aktualizuje sa pri každom skene,
    aj keď sa DB nepublikuje (bez zmien). Lupa z neho ukazuje „Posledný sken“."""
    data = {"finished": time.time(), "errors": res["errors"], "full": res["full"],
            "jobs": res["jobs"], "files": res["files"], "version": config.VERSION}
    try:
        status_path(db_path).write_text(json.dumps(data), encoding="utf-8")
    except OSError as e:
        log.warning("Stav skenu sa nedá zapísať: %s", e)


def need_full(con) -> bool:
    """--auto: úplný sken, ak posledný úplný bol pred viac ako FULL_EVERY_DAYS dňami."""
    row = con.execute("SELECT MAX(finished) FROM scan_log WHERE mode = 'full'").fetchone()
    return not row[0] or row[0] < time.time() - config.FULL_EVERY_DAYS * 86400


class SingleInstance:
    """Zámok – ak už sken beží (napr. hodinový + pri prihlásení), druhý sa nespustí."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(path, "a+b")
        try:
            msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
            self.ok = True
        except OSError:
            self.ok = False

    def release(self):
        try:
            if self.ok:
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.f.close()


def run_scan(root: str, db_path: Path, full=False, auto=False, only=None,
             recent_days=None, progress=None, prints_minutes=None) -> dict:
    """Jeden sken vrátane publikovania. Vracia súhrn pre CLI aj ikonu pri hodinách.

    status: 'ok' | 'busy' (už beží iný sken) | 'no_root' (koreň nedostupný) | 'error'
    """
    res = {"status": "ok", "full": False, "jobs": 0, "changed": 0, "files": 0, "errors": 0,
           "new_jobs": [], "published": None, "seconds": 0.0, "message": ""}
    lock = SingleInstance(config.LOCAL_DIR / "scan" / "scan.lock")
    if not lock.ok:
        log.info("Sken už beží – končím.")
        res["status"] = "busy"
        return res
    t0 = time.time()
    try:
        if win32security is None:
            log.warning("pywin32 nie je nainštalovaný – vlastník súborov bude '?'")
        if not os.path.isdir(root):
            log.error("Koreň neexistuje / nie je dostupný: %s", root)
            res.update(status="no_root", message=f"{root} nie je dostupný.")
            return res

        work = work_path(db_path)
        pending = work.with_suffix(".pending")
        prepare_work(db_path, work)
        con = db.open_rw(work)
        try:
            res["full"] = full = full or (auto and not only and need_full(con))
            st = config.scan_settings(db_path)   # lupa.ini vedľa programu aj vedľa DB
            if recent_days is None:
                recent_days = st["recent_days"]
            if prints_minutes is None:
                prints_minutes = st["prints_minutes"]
            sc = Scanner(con, root, full, only, recent_days, progress, st["customers"], st["exclude"])
            sc.run()
            # značka „čaká na publikovanie“ hneď – ak sa sken preruší počas odtlačkov,
            # zmeny súborov sa zverejnia pri ďalšom skene (pracovná kópia sa zachová)
            if sc.changed:
                pending.touch()
            try:
                pr = update_prints(con, prints_minutes, only, progress, on_change=pending.touch)
                res["prints"] = pr
                if pr["added"] or pr["failed"] or pr["removed"]:
                    sc.changed = True
            except Exception:  # odtlačky nesmú pokaziť sken súborov
                log.exception("Odtlačky výkresov zlyhali")
                con.rollback()
        finally:
            con.close()
        res.update(jobs=sc.jobs_scanned + sc.jobs_skipped, changed=sc.jobs_changed,
                   files=sc.files_seen, errors=sc.errors, new_jobs=sc.new_jobs)

        # značka „čaká na publikovanie“ – ak publikovanie zlyhá, skúsi sa pri ďalšom skene
        if sc.changed:
            pending.touch()
        if pending.exists() or not db_path.exists():
            try:
                res["published"] = publish(work, db_path)
            except OSError as e:
                log.error("Publikovanie zlyhalo: %s", e)
                res["published"] = False
            if res["published"]:
                pending.unlink(missing_ok=True)
        else:
            log.info("Bez zmien – DB sa nepublikuje.")
        write_status(db_path, res)
    except ScanError as e:
        log.error("%s", e)
        res.update(status="no_root", message=str(e))
    except Exception as e:  # sken nesmie zhodiť ikonu pri hodinách
        log.exception("Sken zlyhal")
        res.update(status="error", message=str(e))
    finally:
        lock.release()
        res["seconds"] = time.time() - t0
    return res


def norm_root(root: str) -> str:
    """Upraví koreň z príkazového riadka: bez úvodzoviek, 'L:' -> 'L:\\'.

    Pozor na Windows: --root "L:\\" príde ako  L:"  (\\" je escape úvodzovky).
    """
    r = root.strip().strip('"').strip()
    if len(r) == 2 and r[1] == ":":
        r += "\\"
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lupa – sken zákaziek do SQLite")
    ap.add_argument("--root", default=str(config.ROOT), help="koreň so zákazkami (predvolene z lupa.ini)")
    ap.add_argument("--db", default=str(config.DB_PATH), help="cesta k databáze")
    ap.add_argument("--full", action="store_true", help="úplný sken všetkých zákaziek")
    ap.add_argument("--auto", action="store_true",
                    help=f"inkrementálny, raz za {config.FULL_EVERY_DAYS} dní úplný (pre Plánovač úloh)")
    ap.add_argument("--only", help="skenovať len jedného zákazníka (názov priečinka)")
    ap.add_argument("--recent-days", type=int, default=None,
                    help="inkrementálne: znova prejsť zákazky so zmenou za posledných N dní (predvolene z lupa.ini)")
    ap.add_argument("--prints-minutes", type=float, default=None,
                    help="odtlačky výkresov: najviac N minút na sken, 0 = vypnuté (predvolene z lupa.ini)")
    ap.add_argument("--tray", action="store_true",
                    help="ikona pri hodinách: sken každú hodinu, menu, upozornenia")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args.root = norm_root(args.root)
    target = Path(args.db.strip().strip('"')).resolve()
    setup_logging(target.with_name("lupa_scan.log"), args.verbose)

    if args.tray:
        import tray
        return tray.run(args.root, target)

    res = run_scan(args.root, target, args.full, args.auto, args.only, args.recent_days,
                   prints_minutes=args.prints_minutes)
    return {"ok": 0, "busy": 0, "no_root": 2}.get(res["status"], 1)


if __name__ == "__main__":
    sys.exit(main())
