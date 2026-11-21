"""Lokálna kópia databázy – Lupa číta DB z %LOCALAPPDATA%\\Lupa\\db, nie cez sieť.

SQLite na sieťovom disku číta súbor po malých stránkach a každé čítanie je samostatná
požiadavka – štart Lupy trval 16 s, z lokálnej kópie 0,4 s. Skopírovať celý súbor je naopak rýchle.

- Kópia má v mene veľkosť a čas zmeny zdroja → keď skener DB vymení, vznikne nová kópia.
- Pri štarte (`prepare`) sa kopíruje hneď (UI ukazuje priebeh), počas behu na pozadí –
  dotazy medzitým idú do predchádzajúcej kópie.
- Zdroj sa kontroluje najviac raz za CHECK_EVERY s. Sieťový súbor sa otvára len počas kopírovania.
- Keď L:\\ nie je dostupný, použije sa posledná kópia (`offline`).
- Staré kópie sa mažú; otvorenú (iné okno Lupy) Windows zmazať nedovolí – skúsi sa nabudúce.
"""
import hashlib
import os
import threading
import time
from pathlib import Path

import config

CHUNK = 4 * 2**20     # kopírovanie po 4 MB
CHECK_EVERY = 10.0    # s – ako často sa pozrieť, či skener DB nevymenil


class LocalCopy:
    def __init__(self, src: Path, local_dir: Path | None = None):
        self.src = src
        self.dir = local_dir or (config.LOCAL_DIR / "db")
        tag = hashlib.sha1(str(src.absolute()).lower().encode("utf-8")).hexdigest()[:10]
        self.prefix = f"lupa-{tag}-"
        self.current: Path | None = None   # kópia, do ktorej idú dotazy
        self.offline = False               # zdroj nedostupný, dotazy idú do poslednej kópie
        self.progress: tuple[int, int] | None = None  # (skopírované, spolu) počas kopírovania
        self._checked = 0.0
        self._lock = threading.Lock()
        self._bg: threading.Thread | None = None
        self._dirty = True                 # zostali staré kópie na zmazanie

    # --- verejné ------------------------------------------------------------
    def prepare(self) -> Path | None:
        """Pri štarte: kópia musí byť aktuálna hneď (kopíruje sa v tomto vlákne)."""
        return self._check(sync=True)

    def path(self) -> Path | None:
        """Kópia pre dotaz. Nová verzia zdroja sa kopíruje na pozadí, kým stačí stará kópia."""
        cur = self.current
        if cur and time.monotonic() - self._checked < CHECK_EVERY and cur.exists():
            return cur
        return self._check(sync=not (cur and cur.exists()))

    # --- vnútro -------------------------------------------------------------
    def _name(self, size: int, mtime_ns: int) -> Path:
        return self.dir / f"{self.prefix}{size}-{mtime_ns}.db"

    def _copies(self) -> list[Path]:
        """Existujúce kópie tohto zdroja, najnovšia prvá."""
        try:
            return sorted(self.dir.glob(self.prefix + "*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            return []

    def _check(self, sync: bool) -> Path | None:
        with self._lock:
            self._checked = time.monotonic()
            try:
                st = self.src.stat()
            except OSError:  # L:\ nedostupný / DB ešte neexistuje
                if not (self.current and self.current.exists()):
                    copies = self._copies()
                    self.current = copies[0] if copies else None
                self.offline = self.current is not None
                return self.current
            self.offline = False
            target = self._name(st.st_size, st.st_mtime_ns)
            if target.exists():
                if self.current != target or self._dirty:
                    self.current = target
                    self._cleanup()
                return target
            if not sync:
                if not (self._bg and self._bg.is_alive()):
                    self._bg = threading.Thread(target=self._copy_bg, daemon=True)
                    self._bg.start()
                return self.current
            try:
                self.current = self._copy()
            except OSError as e:
                # kópia zlyhala (výpadok siete) – radšej staré údaje ako žiadne
                if not (self.current and self.current.exists()):
                    copies = self._copies()
                    self.current = copies[0] if copies else None
                if not self.current:
                    raise RuntimeError(f"databázu {self.src} sa nepodarilo skopírovať ({e})") from e
                self.offline = True
                return self.current
            self._cleanup()
            return self.current

    def _copy_bg(self):
        try:
            new = self._copy()
        except OSError:
            return  # nabudúce sa skúsi znova
        with self._lock:
            self.current = new
            self._cleanup()

    def _copy(self) -> Path:
        """Skopíruje zdroj, vráti cestu ku kópii. Meno podľa otvoreného súboru (fstat),
        aby sedelo, aj keby ho skener medzi kontrolou a otvorením vymenil."""
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.src, "rb") as fi:
            st = os.fstat(fi.fileno())
            target = self._name(st.st_size, st.st_mtime_ns)
            if target.exists():
                return target
            tmp = target.with_name(f"{target.stem}.{os.getpid()}-{threading.get_ident()}.part")
            try:
                done = 0
                self.progress = (0, st.st_size)
                with open(tmp, "wb") as fo:
                    while chunk := fi.read(CHUNK):
                        fo.write(chunk)
                        done += len(chunk)
                        self.progress = (done, st.st_size)
                if done != st.st_size:
                    raise OSError(f"skopírovaných {done} z {st.st_size} B")
                try:
                    os.replace(tmp, target)
                except PermissionError:  # rovnakú kópiu medzitým urobilo iné okno Lupy
                    if not target.exists():
                        raise
            finally:
                self.progress = None
                tmp.unlink(missing_ok=True)
        return target

    def _cleanup(self):
        """Zmaže staré kópie a nedokončené .part (otvorené Windows nedovolí – skúsi sa pri ďalšej kontrole)."""
        self._dirty = False
        for p in self._copies():
            if p != self.current:
                try:
                    p.unlink()
                except OSError:
                    self._dirty = True
        try:
            for p in self.dir.glob(self.prefix + "*.part"):
                if time.time() - p.stat().st_mtime > 3600:
                    p.unlink()
        except OSError:
            pass
