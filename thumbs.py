"""Náhľady súborov – PDF cez PyMuPDF, DXF/DWG cez vykres.py, ostatné cez Windows shell
(IShellItemImageFactory).

Náhľady sa ukladajú ako PNG do config.THUMBS_DIR. Kľúč cache = cesta + mtime + veľkosť,
takže zmenený súbor dostane nový náhľad. Zo zdrojového súboru sa len číta.
"""
import ctypes
import hashlib
import logging
import os
from ctypes import wintypes
from pathlib import Path

import pymupdf

import config
import vykres

log = logging.getLogger("lupa.thumbs")

# Veľkosti náhľadov v px: 'l' = detail (panel až ~1100 px), 's' = galéria (karta do ~400 px)
SIZES = {"l": 1000, "s": 500}


# ---------------------------------------------------------------------------
# Windows shell náhľad cez ctypes
# ---------------------------------------------------------------------------
class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, s: str):
        super().__init__()
        ctypes.oledll.ole32.CLSIDFromString(s, ctypes.byref(self))


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class _BITMAP(ctypes.Structure):
    _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG), ("bmHeight", wintypes.LONG),
                ("bmWidthBytes", wintypes.LONG), ("bmPlanes", wintypes.WORD),
                ("bmBitsPixel", wintypes.WORD), ("bmBits", ctypes.c_void_p)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


_IID_IShellItemImageFactory = _GUID("{bcc18b79-ba16-442f-80c4-8a59c30c463b}")
_SIIGBF_BIGGERSIZEOK = 0x01
_SIIGBF_ICONONLY = 0x04
_SIIGBF_THUMBNAILONLY = 0x08

_ole32 = ctypes.windll.ole32
_shell32 = ctypes.windll.shell32
_gdi32 = ctypes.windll.gdi32
_shell32.SHCreateItemFromParsingName.argtypes = [
    wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
_shell32.SHCreateItemFromParsingName.restype = ctypes.HRESULT
_gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
_gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
_gdi32.DeleteObject.argtypes = [wintypes.HANDLE]

# HRESULT GetImage(SIZE size, SIIGBF flags, HBITMAP *phbm) – 4. položka vtable
_GetImage = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, _SIZE, ctypes.c_int,
                               ctypes.POINTER(wintypes.HBITMAP))
_Release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)


def _hbitmap_to_pixmap(hbm) -> pymupdf.Pixmap:
    bm = _BITMAP()
    _gdi32.GetObjectW(hbm, ctypes.sizeof(bm), ctypes.byref(bm))
    w, h = bm.bmWidth, abs(bm.bmHeight)
    bih = _BITMAPINFOHEADER(biSize=ctypes.sizeof(_BITMAPINFOHEADER), biWidth=w, biHeight=-h,
                            biPlanes=1, biBitCount=32, biCompression=0)
    buf = ctypes.create_string_buffer(w * h * 4)
    hdc = ctypes.windll.user32.GetDC(None)
    try:
        if not _gdi32.GetDIBits(hdc, hbm, 0, h, buf, ctypes.byref(bih), 0):
            raise OSError("GetDIBits zlyhalo")
    finally:
        ctypes.windll.user32.ReleaseDC(None, hdc)
    bgra = buf.raw
    rgba = bytearray(len(bgra))
    rgba[0::4] = bgra[2::4]
    rgba[1::4] = bgra[1::4]
    rgba[2::4] = bgra[0::4]
    alpha = bgra[3::4]
    # niektoré náhľady nemajú alfa kanál (samé nuly) – vtedy plne nepriehľadné
    rgba[3::4] = alpha if any(alpha) else b"\xff" * (w * h)
    return pymupdf.Pixmap(pymupdf.csRGB, w, h, bytes(rgba), True)


def _shell_image(path: str, flags: int, px: int) -> pymupdf.Pixmap:
    _ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED; opakované volanie nevadí
    item = ctypes.c_void_p()
    _shell32.SHCreateItemFromParsingName(path, None, ctypes.byref(_IID_IShellItemImageFactory),
                                         ctypes.byref(item))
    try:
        vtbl = ctypes.cast(ctypes.cast(item, ctypes.POINTER(ctypes.c_void_p))[0],
                           ctypes.POINTER(ctypes.c_void_p))
        get_image = _GetImage(vtbl[3])
        hbm = wintypes.HBITMAP()
        get_image(item, _SIZE(px, px), flags, ctypes.byref(hbm))
        try:
            return _hbitmap_to_pixmap(hbm)
        finally:
            _gdi32.DeleteObject(hbm)
    finally:
        _Release(vtbl[2])(item)


# ---------------------------------------------------------------------------
# Verejné API
# ---------------------------------------------------------------------------
def _cache_path(path: str, st: os.stat_result, px: int) -> Path:
    # DXF/DWG: vlastná verzia kľúča – staršie Lupy pre ne uložili len ikonu z Windows
    ver = "d1" if Path(path).suffix.lower().lstrip(".") in vykres.EXTS else "v2"
    key = f"{path.lower()}|{st.st_mtime_ns}|{st.st_size}|{px}|{ver}"
    return config.THUMBS_DIR / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".png")


def _render_pdf(path: str, px: int) -> tuple[pymupdf.Pixmap, int]:
    with pymupdf.open(path) as doc:
        page = doc[0]
        zoom = min(px / max(page.rect.width, 1), 4.0)
        return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False), doc.page_count


def _render_drawing(path: str, st: os.stat_result, px: int) -> pymupdf.Pixmap:
    """DXF / DWG (vykres.py). Kreslenie je pomalšie ako PDF (veľký výkres aj desiatky sekúnd),
    preto sa vždy kreslí len veľký náhľad a galéria dostane jeho zmenšeninu."""
    big = SIZES["l"]
    lcache = _cache_path(path, st, big)
    if lcache.exists():
        pix = pymupdf.Pixmap(str(lcache))
    else:
        pix = vykres.render(path, big)
        if px < big:   # veľký náhľad uložiť hneď (detail ho potom nekreslí znova)
            config.THUMBS_DIR.mkdir(parents=True, exist_ok=True)
            pix.save(str(lcache))
            lcache.with_suffix(".txt").write_text("drawing|0", encoding="ascii")
    longest = max(pix.width, pix.height)
    if px < big and longest > px:
        f = px / longest
        pix = pymupdf.Pixmap(pix, max(1, int(pix.width * f)), max(1, int(pix.height * f)), None)
    return pix


TEXT_EXTS = {"txt"}    # okrem typu NC sa ako text ukazujú aj tieto prípony
TEXT_MAX_BYTES = 64 * 1024
TEXT_MAX_LINES = 200


def get_text(path: str, max_lines: int = TEXT_MAX_LINES) -> dict:
    """Začiatok textového súboru (NC program, txt) – {'ok', 'kind': 'text', 'text', 'more'}."""
    max_bytes = min(TEXT_MAX_BYTES, max_lines * 200)
    try:
        with open(path, "rb") as f:
            raw = f.read(max_bytes + 1)
    except OSError:
        return {"ok": False, "error": "Súbor sa nedá prečítať."}
    more = len(raw) > max_bytes
    raw = raw[:max_bytes]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1250", errors="replace")
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines, more = lines[:max_lines], True
    return {"ok": True, "kind": "text", "text": "\n".join(lines), "more": more}


def get_thumb(path: str, ftype: str, size: str = "l") -> dict:
    """Vráti {'ok', 'file' (PNG v cache), 'kind': 'pdf'|'shell'|'icon', 'pages'} alebo {'ok': False, 'error'}.

    size: 'l' = detail, 's' = galéria (menší, rýchlejší).
    """
    px = SIZES.get(size, SIZES["l"])
    try:
        st = os.stat(path)
    except OSError:
        return {"ok": False, "error": "Súbor neexistuje."}

    cache = _cache_path(path, st, px)
    meta = cache.with_suffix(".txt")  # druh náhľadu + počet strán
    if cache.exists() and meta.exists():
        kind, _, pages = meta.read_text(encoding="ascii").partition("|")
        return {"ok": True, "file": str(cache), "kind": kind, "pages": int(pages or 0)}

    pages = 0
    pix = None
    try:
        if ftype == "PDF":
            pix, pages = _render_pdf(path, px)
            kind = "pdf"
        elif Path(path).suffix.lower().lstrip(".") in vykres.EXTS:
            try:
                pix = _render_drawing(path, st, px)
                kind = "drawing"
            except Exception as e:   # nevykreslený výkres – aspoň náhľad / ikona z Windows (nižšie)
                log.warning("Výkres sa nepodarilo vykresliť %s: %s", path, e)
        if pix is None:
            try:
                pix = _shell_image(path, _SIIGBF_BIGGERSIZEOK | _SIIGBF_THUMBNAILONLY, px // 2)
                kind = "shell"
            except OSError:
                pix = _shell_image(path, _SIIGBF_BIGGERSIZEOK | _SIIGBF_ICONONLY, 256)
                kind = "icon"
    except Exception as e:
        log.warning("Náhľad zlyhal %s: %s", path, e)
        return {"ok": False, "error": "Náhľad nie je k dispozícii."}

    config.THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    pix.save(str(cache))
    meta.write_text(f"{kind}|{pages}", encoding="ascii")
    return {"ok": True, "file": str(cache), "kind": kind, "pages": pages}
