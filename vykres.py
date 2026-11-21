"""Náhľad výkresov DXF a DWG – Windows ich bez prehliadača nevykreslí.

- DXF: knižnica ezdxf (kreslenie cez PyMuPDF, ako tlač – čierne čiary na bielom).
- DWG: najprv prevod na DXF programom dwg2dxf z LibreDWG (GPLv3, samostatný exe v priečinku
  libredwg\\ vedľa Lupy; build.py ho stiahne) do dočasného súboru v %LOCALAPPDATA%\\Lupa\\tmp,
  potom ako DXF. Zo zdrojového súboru sa len číta – na L:\\ sa nič nezapisuje.
- Entita, ktorú sa nepodarí vykresliť (napr. šrafa s neplatnou krivkou zo starého DWG),
  sa vynechá, aby nezlyhal celý náhľad.
"""
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pymupdf

import config

log = logging.getLogger("lupa.vykres")

EXTS = {"dxf", "dwg"}
DWG2DXF_TIMEOUT = 60   # s – väčšie výkresy sa prevádzajú do ~10 s
BASE_DPI = 96


def libredwg_dir() -> Path:
    """Priečinok s dwg2dxf.exe – v zostavení vedľa Lupa.exe, pri vývoji tools\\libredwg."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "libredwg"
    return Path(__file__).resolve().parent / "tools" / "libredwg"


def _dwg_to_dxf(path: str) -> Path:
    exe = libredwg_dir() / "dwg2dxf.exe"
    if not exe.exists():
        raise RuntimeError(f"chýba {exe}")
    tmp_dir = config.LOCAL_DIR / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out = tmp_dir / f"dwg-{uuid.uuid4().hex}.dxf"
    r = subprocess.run([str(exe), "-y", "-o", str(out), path], cwd=str(exe.parent),
                       capture_output=True, timeout=DWG2DXF_TIMEOUT,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    if not out.exists():
        err = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(f"dwg2dxf zlyhal ({r.returncode}): {err[-1] if err else ''}")
    return out


def _load(path: Path):
    import ezdxf
    from ezdxf import recover
    try:
        return ezdxf.readfile(path)
    except ezdxf.DXFStructureError:
        doc, _ = recover.readfile(path)   # poškodené / neštandardné DXF
        return doc


def render(path: str, px: int) -> pymupdf.Pixmap:
    """Modelový priestor výkresu ako obrázok, dlhšia strana najviac px."""
    from ezdxf.addons.drawing import Frontend, RenderContext, config as dcfg, layout
    from ezdxf.addons.drawing import pymupdf as pm_backend

    class SafeFrontend(Frontend):
        skipped = 0

        def draw_entity(self, entity, properties):
            try:
                super().draw_entity(entity, properties)
            except Exception:
                self.skipped += 1

    tmp = _dwg_to_dxf(path) if path.lower().endswith(".dwg") else None
    try:
        doc = _load(tmp or Path(path))
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)
    backend = pm_backend.PyMuPdfBackend()
    cfg = dcfg.Configuration(background_policy=dcfg.BackgroundPolicy.WHITE,
                             color_policy=dcfg.ColorPolicy.BLACK,
                             lineweight_policy=dcfg.LineweightPolicy.RELATIVE)
    fe = SafeFrontend(RenderContext(doc), backend, config=cfg)
    fe.draw_layout(doc.modelspace(), finalize=True)
    if fe.skipped:
        log.info("Výkres %s: vynechaných entít %d", path, fe.skipped)
    page = layout.Page(0, 0, layout.Units.mm, margins=layout.Margins.all(2))   # veľkosť podľa výkresu
    settings = layout.Settings(fit_page=True, max_stroke_width=0.0015)
    pix = pymupdf.Pixmap(backend.get_pixmap_bytes(page, fmt="png", settings=settings, dpi=BASE_DPI))
    longest = max(pix.width, pix.height)
    if longest < px * 0.9:   # malý výkres – vykresliť ostrejšie
        dpi = int(min(BASE_DPI * px / max(longest, 1), 1200))
        pix = pymupdf.Pixmap(backend.get_pixmap_bytes(page, fmt="png", settings=settings, dpi=dpi))
        longest = max(pix.width, pix.height)
    if longest > px:
        f = px / longest
        pix = pymupdf.Pixmap(pix, max(1, int(pix.width * f)), max(1, int(pix.height * f)), None)
    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)
    return pix
