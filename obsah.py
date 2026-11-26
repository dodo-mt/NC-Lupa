"""Hľadanie textu v obsahu NC programov (naživo, na pozadí, zastaviteľné).

Súbory vyberá Api (databáza + filtre), tento modul ich len číta a hľadá riadky. Na disku L: nič nemení.
Súbory sa čítajú vo viacerých vláknach (sieť), výsledky sa postupne zbierajú a UI si ich pýta cez `stav`.
"""
import re
import threading
import time


def preloz_dopyt(text: str, regex: bool, rozlisovat: bool) -> re.Pattern:
    """Text (doslovne) alebo regulárny výraz -> vzor. ValueError s čitateľnou správou pri chybnom výraze."""
    flags = 0 if rozlisovat else re.IGNORECASE
    try:
        return re.compile(text if regex else re.escape(text), flags)
    except re.error as e:
        raise ValueError(f"Chybný regulárny výraz: {e}") from e


def dekoduj(data: bytes) -> str:
    """NC programy bývajú ASCII, komentáre UTF-8 alebo cp1250 – nikdy nevyhodí výnimku."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1250", errors="replace")


def najdi_riadky(text: str, rx: re.Pattern, rx_viac: re.Pattern | None, na_subor: int, max_znakov: int = 300):
    """[(číslo riadku od 1, text riadku)] – najviac `na_subor`. Rýchla kontrola celého textu, až potom po riadkoch."""
    if rx_viac is not None and not rx_viac.search(text):
        return []
    out = []
    for i, riadok in enumerate(text.splitlines(), 1):
        if rx.search(riadok):
            out.append((i, riadok.strip()[:max_znakov]))
            if len(out) >= na_subor:
                break
    return out


def kontext(text: str, riadok: int, okolo: int = 5, max_znakov: int = 400) -> dict:
    """Riadky okolo nálezu: {'line', 'first', 'total', 'lines': [(číslo, text)]}; riadok mimo súboru = prázdny zoznam."""
    riadky = text.splitlines()
    if not 1 <= riadok <= len(riadky):
        return {"line": riadok, "first": riadok, "total": len(riadky), "lines": []}
    od, do = max(1, riadok - okolo), min(len(riadky), riadok + okolo)
    return {"line": riadok, "first": od, "total": len(riadky),
            "lines": [(i, riadky[i - 1].rstrip()[:max_znakov]) for i in range(od, do + 1)]}


class Hladanie:
    """Jedno bežiace hľadanie. subory: [{id, path, name, size, job_id, job, customer, folder}]."""

    def __init__(self, subory: list[dict], rx: re.Pattern, *, max_nalezov: int, na_subor: int, vlakna: int = 6,
                 cita=None):
        self._subory, self._rx = subory, rx
        self._rx_viac = re.compile(rx.pattern, rx.flags | re.MULTILINE)
        self._max, self._na_subor = max_nalezov, na_subor
        self._cita = cita or self._precitaj
        self._zamok = threading.Lock()
        self._dalsi = 0
        self.nalezy: list[dict] = []
        self.hotovych = self.chyb = self.suborov_s_nalezom = 0
        self.zastavene = self.limit = self.hotovo = False
        self._stop = threading.Event()
        self._vlakna = [threading.Thread(target=self._prac, daemon=True) for _ in range(max(1, vlakna))]
        self.zaciatok = time.monotonic()
        self.trvanie = 0.0

    @staticmethod
    def _precitaj(path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    def start(self):
        for v in self._vlakna:
            v.start()
        threading.Thread(target=self._dohliadaj, daemon=True).start()

    def stop(self):
        self.zastavene = True
        self._stop.set()

    def _dohliadaj(self):
        for v in self._vlakna:
            v.join()
        self.trvanie = time.monotonic() - self.zaciatok
        self.hotovo = True

    def _prac(self):
        while not self._stop.is_set():
            with self._zamok:
                if self._dalsi >= len(self._subory):
                    return
                f = self._subory[self._dalsi]
                self._dalsi += 1
            try:
                riadky = najdi_riadky(dekoduj(self._cita(f["path"])), self._rx, self._rx_viac, self._na_subor)
            except OSError:
                riadky = None
            with self._zamok:
                self.hotovych += 1
                if riadky is None:
                    self.chyb += 1
                    continue
                if riadky:
                    self.suborov_s_nalezom += 1
                for cislo, text in riadky:
                    if len(self.nalezy) >= self._max:
                        self.limit = True
                        self._stop.set()
                        break
                    self.nalezy.append({"file_id": f["id"], "name": f["name"], "customer": f["customer"],
                                        "job": f["job"], "job_id": f["job_id"], "folder": f["folder"],
                                        "path": f["path"], "line": cislo, "text": text})

    def stav(self, od: int = 0) -> dict:
        """Nové nálezy od poradia `od` a priebeh."""
        with self._zamok:
            return {"hits": self.nalezy[od:], "next": len(self.nalezy), "scanned": self.hotovych,
                    "total": len(self._subory), "errors": self.chyb, "files_with_hits": self.suborov_s_nalezom,
                    "done": self.hotovo, "stopped": self.zastavene, "limit": self.limit,
                    "seconds": round(self.trvanie or (time.monotonic() - self.zaciatok), 1)}
