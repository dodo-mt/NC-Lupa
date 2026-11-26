"""Otvorenie NC programu v NC Editore (aj na konkrétnom riadku – nález z hľadania v obsahu).

NC Editor kopíruje NC Nástroje do %LOCALAPPDATA%\\NC_Nastroje\\apps\\nc_editor\\<verzia>\\ – berie sa najnovšia verzia.
Riadok sa odovzdáva ako `cesta:riadok` (NC Editor 2026.11.26-11 a novší); staršia verzia riadok nepozná,
preto sa jej cesta dáva bez riadka. Ak NC Editor nie je nainštalovaný, volajúci otvorí súbor predvoleným programom.
"""
import os
import re
import subprocess
from pathlib import Path

MIN_VERZIA_RIADOK = "2026.11.26-11"
EXE = "NCEditor.exe"


def _kluc(verzia: str) -> tuple:
    """`2026.11.26-11` -> (2026, 11, 26, 11); neznámy tvar = (0,)."""
    m = re.fullmatch(r"(\d{4})\.(\d{1,2})\.(\d{1,2})-(\d+)", verzia.strip())
    return tuple(int(x) for x in m.groups()) if m else (0,)


def apps_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "NC_Nastroje" / "apps" / "nc_editor"


def najdi_editor(koren: Path | None = None) -> tuple[Path, str] | None:
    """(cesta k NCEditor.exe, verzia) najnovšej lokálnej kópie, alebo None."""
    koren = koren or apps_dir()
    try:
        verzie = [d for d in koren.iterdir() if d.is_dir() and (d / EXE).is_file() and _kluc(d.name) != (0,)]
    except OSError:
        return None
    if not verzie:
        return None
    najnovsia = max(verzie, key=lambda d: _kluc(d.name))
    return najnovsia / EXE, najnovsia.name


def pozna_riadok(verzia: str) -> bool:
    return _kluc(verzia) >= _kluc(MIN_VERZIA_RIADOK)


def argument(path: str, riadok: int | None, verzia: str) -> str:
    """Cesta pre NC Editor – s `:riadok`, ak ho daná verzia vie."""
    return f"{path}:{int(riadok)}" if riadok and int(riadok) > 0 and pozna_riadok(verzia) else path


def otvor(path: str, riadok: int | None = None, koren: Path | None = None) -> dict:
    """Spustí NC Editor so súborom. {'ok': False, 'chyba'} ak sa to nedá (NC Editor nie je nainštalovaný)."""
    n = najdi_editor(koren)
    if n is None:
        return {"ok": False, "error": "NC Editor nie je nainštalovaný (spusti NC Nástroje, stiahne sa sám)."}
    exe, verzia = n
    verzia = os.environ.get("LUPA_NC_EDITOR_VERZIA") or verzia     # skúšanie: vývojový NC Editor už beží a prijme riadok
    try:
        subprocess.Popen([str(exe), argument(path, riadok, verzia)], cwd=str(exe.parent))
    except OSError as e:
        return {"ok": False, "error": f"NC Editor sa nepodarilo spustiť: {e.strerror or e}"}
    return {"ok": True, "line": bool(riadok) and pozna_riadok(verzia), "version": verzia}
