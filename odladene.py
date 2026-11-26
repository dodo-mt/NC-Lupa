"""Odladené programy = NC súbor v priečinku `odlad*` (odladene, Odladené, ODLADENE …) kdekoľvek pod zákazkou / pozíciou.

Rozhoduje len cesta v zákazke (positions.rel_path), obsah súboru ani hlavička `ODLADOVAL` nie. Priečinky ako
`neodladene`, `stare` a pod. sa za odladené nepočítajú. Vzory (fnmatch, oddelené čiarkou) sú v lupa.ini
`odladene_priecinky`, predvolene `odlad*`. Veľké/malé písmená a diakritika nehrajú rolu.
"""
import fnmatch
import unicodedata

from listy import _like

PREDVOLENE = "odlad*"


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).casefold()


class Pravidlo:
    def __init__(self, ini: dict | None = None):
        raw = (ini or {}).get("odladene_priecinky", PREDVOLENE) or PREDVOLENE
        self.vzory = [_norm(p.strip()) for p in str(raw).split(",") if p.strip()] or [PREDVOLENE]

    def je_odladene(self, rel_path: str) -> bool:
        """`NC\\DMC 160\\Odladené` -> True; `NC\\neodladene` -> False (pozerá sa na celé názvy priečinkov)."""
        casti = [c for c in str(rel_path or "").replace("/", "\\").split("\\") if c]
        return any(fnmatch.fnmatchcase(_norm(c), v) for c in casti for v in self.vzory)

    def sql(self, pos: str = "p") -> tuple[str, list]:
        """SQL podmienka pre positions s aliasom `pos` + parametre (LIKE v SQLite nerozlišuje veľkosť ASCII písmen;
        vzor `odlad*` je ASCII, takže `Odladené` sedí; diakritika vo vlastnom vzore by sa rozlišovala)."""
        podm, args = [], []
        for v in self.vzory:
            lk = _like(v)
            for tvar in (lk, lk + "\\%", "%\\" + lk, "%\\" + lk + "\\%"):
                podm.append(f"{pos}.rel_path LIKE ? ESCAPE '!'")
                args.append(tvar)
        return "(" + " OR ".join(podm) + ")", args
