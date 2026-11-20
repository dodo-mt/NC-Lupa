"""Obrazové odtlačky výkresov (PDF) – základ pre „Nájdi podobné výkresy“.

Postup pre 1. stranu PDF:
  1. vykresliť v odtieňoch sivej, prah -> čierne/biele (pri skenoch prispôsobivý),
  2. nájsť rám (dlhé čiary) a orezať okraj, zamaskovať pečiatku (tabuľky pri pravom okraji dole),
  3. rozdeliť na pohľady (súvislé zhluky čiar), každý zmenšiť na mriežku VGRID×VGRID (hustota čiar).

Odtlačok listu = zoznam pohľadov (váha podľa plochy, VGRID² bajtov). Porovnanie pohľadov =
kosínusová podobnosť v 8 symetriách (otočenie, zrkadlenie – skeny bývajú otočené),
podobnosť listov = vážený priemer najlepších zhôd pohľadov, berie sa slabší z oboch smerov
(hľadaný -> výkres aj výkres -> hľadaný), aby listy s mnohými pohľadmi nevyhrávali všade.

Zo zdrojového súboru sa len číta.
Test na vzorkách:  python odtlacky.py --test vzorky
"""
import logging

import numpy as np
import pymupdf

log = logging.getLogger("lupa.odtlacky")

RENDER_PX = 1600      # dlhšia strana vykreslenia
VERSION = 1           # zvýšiť pri zmene algoritmu (staré odtlačky sa prepočítajú)


# ---------------------------------------------------------------------------
# Vykreslenie a prah
# ---------------------------------------------------------------------------
def _render(path: str) -> tuple[np.ndarray, bool]:
    """1. strana ako pole sivej (H×W, uint8) + či ide o sken (bez vektorov a textu)."""
    with pymupdf.open(path) as doc:
        page = doc[0]
        r = page.rect
        zoom = RENDER_PX / max(r.width, r.height, 1)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False)
        words = page.get_text("words")
        is_scan = not words and not page.get_drawings()
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width].copy()
        # skutočný text (poznámky, kóty) vymazať – rušil by porovnanie geometrie
        mat = page.rotation_matrix * pymupdf.Matrix(zoom, zoom)
        for w in words:
            r = (pymupdf.Rect(w[:4]) * mat).irect & pymupdf.IRect(0, 0, pix.width, pix.height)
            if not r.is_empty:
                img[r.y0:r.y1, r.x0:r.x1] = 255
    return img, is_scan


def _binarize(gray: np.ndarray, is_scan: bool) -> np.ndarray:
    if not is_scan:
        return gray < 235
    # sken: pozadie býva sivé a čiary bledé -> prah podľa pozadia
    bg = float(np.percentile(gray, 60))
    ink = gray < bg - 35
    # odstrániť osamotené body (šum skenu): bod ostane, ak má aspoň 2 susedov
    n = np.zeros(ink.shape, dtype=np.uint8)
    p = np.pad(ink, 1)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            if dy != 1 or dx != 1:
                n += p[dy:dy + ink.shape[0], dx:dx + ink.shape[1]]
    return ink & (n >= 2)


# ---------------------------------------------------------------------------
# Dlhé čiary, rám, pečiatka
# ---------------------------------------------------------------------------
def _runs(ink: np.ndarray, minlen: int) -> list[tuple[int, int, int]]:
    """Vodorovné behy čierneho dlhé aspoň minlen: (riadok, x0, x1) – x1 výlučne."""
    h, w = ink.shape
    p = np.zeros((h, w + 2), dtype=np.int8)
    p[:, 1:-1] = ink
    d = np.diff(p.ravel())
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    keep = (ends - starts) >= minlen
    w2 = w + 2
    return [(int(s // w2), int(s % w2), int(e % w2)) for s, e in zip(starts[keep], ends[keep])]


def _thicken(ink: np.ndarray, across: int, along: int) -> np.ndarray:
    """Zhrubnúť vodorovné čiary – aby mierne šikmé a prerušené čiary skenu dali dlhé behy."""
    out = ink.copy()
    for d in range(1, across + 1):
        out[d:] |= ink[:-d]
        out[:-d] |= ink[d:]
    base = out.copy()
    for d in range(1, along + 1):
        out[:, d:] |= base[:, :-d]
        out[:, :-d] |= base[:, d:]
    return out


def _frame(hr, vr, h, w) -> tuple[int, int, int, int] | None:
    """Vnútorný rám (x0, y0, x1, y1) z dlhých čiar, alebo None."""
    lefts = [x for x, y0, y1 in vr if x < w * 0.2 and y1 - y0 > h * 0.5]
    rights = [x for x, y0, y1 in vr if x > w * 0.8 and y1 - y0 > h * 0.5]
    tops = [y for y, x0, x1 in hr if y < h * 0.2 and x1 - x0 > w * 0.5]
    bots = [y for y, x0, x1 in hr if y > h * 0.8 and x1 - x0 > w * 0.5]
    if not (lefts and rights and tops and bots):
        return None
    return max(lefts), max(tops), min(rights), min(bots)


def clean(path: str) -> np.ndarray:
    """Čierno-biely obraz výkresu bez rámu a pečiatky (bool H×W)."""
    gray, is_scan = _render(path)
    ink = _binarize(gray, is_scan)
    h, w = ink.shape
    minlen = int(min(h, w) * 0.08)
    hr = _runs(_thicken(ink, 3, 1), minlen)                   # (y, x0, x1)
    vr = _runs(_thicken(ink.T, 3, 1), minlen)                 # (x, y0, y1)

    fr = _frame(hr, vr, h, w)
    if fr:
        x0, y0, x1, y1 = fr
        m = max(3, int(min(h, w) * 0.004))   # odsadenie, aby zmizli aj čiary rámu
        out = np.zeros_like(ink)
        out[y0 + m:y1 - m, x0 + m:x1 - m] = ink[y0 + m:y1 - m, x0 + m:x1 - m]
        ink = out
        tol = int(w * 0.02)
        # pečiatka a tabuľky: vodorovné čiary dolnej časti, ktoré končia na pravom okraji rámu
        for y, a, b in hr:
            if y > y0 + (y1 - y0) * 0.45 and abs(b - x1) <= tol and a > x0 + tol:
                ink[y - 2:, a - 2:] = False
        # pečiatka postavená zvislo (otočené výkresy): zvislé čiary vpravo, končiace dole
        for x, a, b in vr:
            if x > x0 + (x1 - x0) * 0.55 and abs(b - y1) <= tol and a > y0 + tol:
                ink[a - 2:, x - 2:] = False
    # zvyšné veľmi dlhé čiary (napr. rám bez druhej čiary) zmazať
    for y, a, b in hr:
        if b - a > w * 0.6:
            ink[max(0, y - 1):y + 2, a:b] = False
    for x, a, b in vr:
        if b - a > h * 0.6:
            ink[a:b, max(0, x - 1):x + 2] = False
    return ink


# ---------------------------------------------------------------------------
# Pohľady – list sa rozdelí na súvislé zhluky čiar, každý má vlastný odtlačok
# ---------------------------------------------------------------------------
VGRID = 16            # mriežka odtlačku pohľadu (hrubšia = tolerantnejšia ku kótam)
MAX_VIEWS = 8
COARSE = 300          # rozlíšenie hrubej mapy na hľadanie zhlukov (dlhšia strana)
DILATE = 1            # o koľko buniek sa zhluky rozširujú (spájajú blízke čiary)


def _maxpool(ink: np.ndarray, f: int) -> np.ndarray:
    h, w = ink.shape
    hh, ww = -(-h // f), -(-w // f)
    p = np.zeros((hh * f, ww * f), dtype=bool)
    p[:h, :w] = ink
    return p.reshape(hh, f, ww, f).any(axis=(1, 3))


def _dilate(m: np.ndarray, r: int) -> np.ndarray:
    out = m.copy()
    for _ in range(r):
        p = np.pad(out, 1)
        out = p[1:-1, 1:-1] | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
    return out


def _components(m: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Ohraničenia súvislých oblastí (x0, y0, x1, y1) v hrubej mape."""
    h, w = m.shape
    seen = np.zeros_like(m)
    out = []
    ys, xs = np.nonzero(m)
    for sy, sx in zip(ys.tolist(), xs.tolist()):
        if seen[sy, sx]:
            continue
        seen[sy, sx] = True
        stack = [(sy, sx)]
        x0 = x1 = sx
        y0 = y1 = sy
        while stack:
            y, x = stack.pop()
            x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and m[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        out.append((x0, y0, x1 + 1, y1 + 1))
    return out


def _grid(crop: np.ndarray, n: int) -> np.ndarray:
    """Obsah doplnený na štvorec a zmenšený priemerom na n×n (float 0..1)."""
    h, w = crop.shape
    s = max(h, w)
    sq = np.zeros((s, s), dtype=np.float32)
    oy, ox = (s - h) // 2, (s - w) // 2
    sq[oy:oy + h, ox:ox + w] = crop
    edges = np.linspace(0, s, n + 1).astype(int)
    cs = np.pad(sq.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    a, b = edges[:-1], edges[1:]
    tot = cs[b][:, b] - cs[a][:, b] - cs[b][:, a] + cs[a][:, a]
    g = np.sqrt(tot / np.maximum(np.outer(b - a, b - a), 1))
    return g / max(float(g.max()), 1e-6)


def views_from_ink(ink: np.ndarray) -> list[tuple[float, bytes]]:
    """Pohľady listu: [(váha = podiel plochy, odtlačok VGRID² bajtov)], najväčšie prvé."""
    h, w = ink.shape
    f = max(1, max(h, w) // COARSE)
    coarse = _maxpool(ink, f)
    m = _dilate(coarse, DILATE)
    comps = []
    for x0, y0, x1, y1 in _components(m):
        bw, bh = x1 - x0, y1 - y0
        if bw * bh < coarse.size * 0.004:               # drobnosti (text, značky)
            continue
        if max(bw, bh) / max(min(bw, bh), 1) > 15:       # pásiky tabuliek, osamotené čiary
            continue
        crop = ink[y0 * f:y1 * f, x0 * f:x1 * f]
        if crop.sum() < 200:
            continue
        comps.append((bw * bh, crop))
    comps.sort(key=lambda c: -c[0])
    comps = comps[:MAX_VIEWS]
    total = sum(a for a, _ in comps) or 1
    return [(a / total, (_grid(c, VGRID) * 255).astype(np.uint8).tobytes()) for a, c in comps]


VIEW_BYTES = 1 + VGRID * VGRID   # váha (0..255) + mriežka


def pack(views: list[tuple[float, bytes]]) -> bytes:
    """Pohľady -> BLOB do DB."""
    return b"".join(bytes([max(1, min(255, round(w * 255)))]) + fp for w, fp in views)


def unpack(blob: bytes) -> list[tuple[float, bytes]]:
    """BLOB z DB -> pohľady."""
    return [(blob[i] / 255, blob[i + 1:i + VIEW_BYTES]) for i in range(0, len(blob), VIEW_BYTES)]


def _blur(g: np.ndarray) -> np.ndarray:
    """Jemné rozmazanie mriežok (..., VGRID, VGRID), aby malý posun nevadil."""
    p = np.pad(g, [(0, 0)] * (g.ndim - 2) + [(1, 1), (1, 1)], mode="edge")
    return (p[..., :-2, 1:-1] + p[..., 2:, 1:-1] + p[..., 1:-1, :-2] + p[..., 1:-1, 2:] + 4 * g) / 8


def _norm_rows(m: np.ndarray) -> np.ndarray:
    """Riadky matice: odčítať priemer a normovať na dĺžku 1 (kosínusová podobnosť = súčin)."""
    m = m - m.mean(axis=1, keepdims=True)
    return m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-6)


def _grids(blob: bytes) -> tuple[np.ndarray, np.ndarray]:
    """BLOB -> (váhy V, mriežky V×VGRID×VGRID float32)."""
    raw = np.frombuffer(blob, dtype=np.uint8).reshape(-1, VIEW_BYTES)
    return raw[:, 0].astype(np.float32) / 255, raw[:, 1:].reshape(-1, VGRID, VGRID).astype(np.float32)


class ViewIndex:
    """Všetky pohľady všetkých výkresov v jednej matici – rýchle hľadanie podobných.

    blobs: odtlačky (pack()) – každý aspoň jeden pohľad. Matica je v int8 s mierkou pre každý
    riadok (štvrtina pamäte oproti float32), počíta sa po blokoch vo float32.
    """
    CHUNK = 32768

    def __init__(self, blobs: list[bytes]):
        self.n = len(blobs)
        counts = np.array([len(b) // VIEW_BYTES for b in blobs], dtype=np.int64)
        self.starts = np.concatenate([[0], np.cumsum(counts)[:-1]]) if self.n else np.zeros(0, np.int64)
        weight, grids = _grids(b"".join(blobs)) if self.n else (np.zeros(0, np.float32), None)
        self.weight = weight
        self.mat = np.zeros((len(weight), VGRID * VGRID), np.int8)
        self.scale = np.zeros(len(weight), np.float32)
        for a in range(0, len(weight), self.CHUNK):   # po blokoch – menej dočasnej pamäte
            g = _blur(grids[a:a + self.CHUNK])
            v = _norm_rows(g.reshape(len(g), -1))
            sc = np.maximum(np.abs(v).max(axis=1), 1e-6) / 127
            self.mat[a:a + self.CHUNK] = np.round(v / sc[:, None]).astype(np.int8)
            self.scale[a:a + self.CHUNK] = sc

    def search(self, blob: bytes) -> np.ndarray:
        """Podobnosť (0..1) hľadaného listu (pack()) ku každému výkresu v indexe."""
        if not blob or not self.n:
            return np.zeros(self.n, np.float32)
        qw, qg = _grids(blob)
        nq = len(qw)
        g = _blur(qg)
        syms = [np.rot90(x, k, axes=(1, 2)) for x in (g, g[:, :, ::-1]) for k in range(4)]
        q = _norm_rows(np.stack(syms, axis=1).reshape(nq * 8, -1)).T.astype(np.float32)  # D × (Q*8)
        s = np.empty((len(self.weight), nq), np.float32)
        for a in range(0, len(s), self.CHUNK):
            part = (self.mat[a:a + self.CHUNK].astype(np.float32) @ q) * self.scale[a:a + self.CHUNK, None]
            s[a:a + self.CHUNK] = part.reshape(len(part), nq, 8).max(axis=2)
        np.clip(s, 0, 1, out=s)
        # smer hľadaný -> výkres: pre každý hľadaný pohľad najlepší pohľad výkresu
        fwd = np.maximum.reduceat(s, self.starts, axis=0) @ qw
        # smer výkres -> hľadaný: každý pohľad výkresu má mať pár v hľadanom
        back = np.add.reduceat(s.max(axis=1) * self.weight, self.starts)
        return np.minimum(fwd, back)


def views(path: str) -> list[tuple[float, bytes]]:
    """Pohľady PDF – viď views_from_ink."""
    return views_from_ink(clean(path))


# ---------------------------------------------------------------------------
# Test na vzorkách
# ---------------------------------------------------------------------------
def _test(root: str):
    import time
    from pathlib import Path

    pdfs = sorted(Path(root).rglob("*.pdf"))
    items, names, t = [], [], time.perf_counter()
    for p in pdfs:
        try:
            v = views(str(p))
        except Exception as e:
            print(f"CHYBA {p}: {e}")
            continue
        if v:
            items.append(pack(v))
            names.append(p)
    print(f"Spolu {len(items)} výkresov za {time.perf_counter() - t:.1f}s\n")
    idx = ViewIndex(items)
    for i, n in enumerate(names):
        sim = idx.search(items[i])
        sim[i] = -9
        best = np.argsort(-sim)[:4]
        print(f"{i:2d} {n.name[:38]:38s} -> " + "  ".join(f"{j}:{sim[j]:.2f}" for j in best))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Odtlačky výkresov – test")
    ap.add_argument("--test", required=True, help="priečinok s PDF (napr. vzorky)")
    _test(ap.parse_args().test)
