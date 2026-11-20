"""SQLite databáza Lupy – schéma a otváranie."""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    path      TEXT NOT NULL UNIQUE,
    dir_mtime REAL
);

CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    path        TEXT NOT NULL UNIQUE,
    dir_mtime   REAL,
    last_scan   REAL,
    last_change REAL          -- najnovší mtime súboru/priečinka v zákazke
);

-- pozícia = skutočný priečinok v zákazke; koreň zákazky má rel_path ''
CREATE TABLE IF NOT EXISTS positions (
    id       INTEGER PRIMARY KEY,
    job_id   INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    name     TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    path     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY,
    position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    job_id      INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    ext         TEXT NOT NULL,
    ftype       TEXT NOT NULL,
    path        TEXT NOT NULL,
    size        INTEGER,
    created     REAL,
    modified    REAL,
    owner       TEXT
);

CREATE TABLE IF NOT EXISTS scan_log (
    id         INTEGER PRIMARY KEY,
    started    REAL,
    finished   REAL,
    mode       TEXT,
    files_seen INTEGER,
    errors     INTEGER
);

-- obrazové odtlačky PDF (odtlacky.py) – kľúč je cesta, nie files.id (zákazka sa prepisuje nanovo);
-- záznam platí, kým sedí veľkosť, zmenený a verzia algoritmu
CREATE TABLE IF NOT EXISTS prints (
    path     TEXT PRIMARY KEY,
    size     INTEGER,
    modified REAL,
    version  INTEGER,
    views    BLOB            -- odtlacky.pack(); NULL = PDF sa nedalo spracovať / bez obsahu
);

CREATE INDEX IF NOT EXISTS ix_jobs_customer   ON jobs(customer_id);
CREATE INDEX IF NOT EXISTS ix_positions_job   ON positions(job_id);
CREATE INDEX IF NOT EXISTS ix_files_name      ON files(name);
CREATE INDEX IF NOT EXISTS ix_files_owner     ON files(owner);
CREATE INDEX IF NOT EXISTS ix_files_ftype     ON files(ftype);
CREATE INDEX IF NOT EXISTS ix_files_modified  ON files(modified);
CREATE INDEX IF NOT EXISTS ix_files_job       ON files(job_id);
CREATE INDEX IF NOT EXISTS ix_files_position  ON files(position_id);
"""


def open_rw(path: Path) -> sqlite3.Connection:
    """Otvorí (a prípadne vytvorí) databázu na zápis – len pre skener."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    # Žiadny WAL – DB bude neskôr na sieťovom disku, kde WAL nefunguje.
    con.executescript(SCHEMA)
    return con


def open_ro(path: Path) -> sqlite3.Connection:
    """Otvorí databázu len na čítanie – pre aplikáciu."""
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con
