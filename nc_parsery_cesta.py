"""Zapojenie spoločného balíka `nc_parsery` (priečinok `NC parsery` vedľa projektu) do sys.path.

Rovnaká konvencia ako `cnc_vykresy_spolocne` v ostatných projektoch; pri zostavení exe (build.py) sa pridáva `--paths`.
Importuje sa pred `from nc_parsery import …` (stačí `import nc_parsery_cesta`).
"""
import sys
from pathlib import Path

_BALIK = Path(__file__).resolve().parent.parent / "NC parsery"
if _BALIK.is_dir() and str(_BALIK) not in sys.path:
    sys.path.insert(0, str(_BALIK))
