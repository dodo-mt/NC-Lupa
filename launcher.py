"""Spúšťač Lupy (L:\\_Lupa\\Lupa.exe) – skopíruje Lupu do počítača a spustí ju odtiaľ.

Lupa (onedir, priečinok L:\\_Lupa\\app\\) sa zo sieťového disku spustiť nedá – Windows .NET
(okno pywebview) odmieta načítať knižnice zo siete. Zostavenie onefile sa síce spustí, ale pri
každom štarte rozbaľuje ~45 MB, čo je pomalé.

- Verzia = app\\version.txt (verzia + čas zostavenia). Kópia: %LOCALAPPDATA%\\Lupa\\app\\<verzia>\\.
- Kopíruje sa len po novej verzii; každá verzia má vlastný priečinok, lebo spustenú starú
  Lupu nejde prepísať. Staré verzie sa zmažú, keď už nebežia.
- Nedokončená kópia (.part) sa pri ďalšom štarte urobí znova.
- Lupa dostane v LUPA_HOME priečinok spúšťača – lupa.ini a lupa.db sú tam (config.APP_DIR).
Len štandardná knižnica – spúšťač má byť malý a štartovať rýchlo.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
SRC = HOME / "app"
LOCAL = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Lupa" / "app"
EXE = "Lupa.exe"


def chyba(text: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, "Lupa", 0x10)  # MB_ICONERROR


def verzia() -> str:
    raw = (SRC / "version.txt").read_text(encoding="utf-8-sig").strip()
    return "".join(ch if ch.isalnum() or ch in ".-_" else "_" for ch in raw)


def priprav(ver: str) -> Path:
    """Lokálna kópia danej verzie (skopíruje, ak ešte nie je celá)."""
    dst = LOCAL / ver
    if (dst / ".ok").exists():
        return dst
    LOCAL.mkdir(parents=True, exist_ok=True)
    tmp = LOCAL / f"{ver}.{os.getpid()}.part"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(SRC, tmp)
    (tmp / ".ok").write_text(ver, encoding="utf-8")
    shutil.rmtree(dst, ignore_errors=True)        # zvyšok nedokončenej kópie
    try:
        os.replace(tmp, dst)
    except OSError:                               # rovnakú verziu medzitým skopíroval iný štart
        shutil.rmtree(tmp, ignore_errors=True)
        if not (dst / ".ok").exists():
            raise
    return dst


def uprac(ver: str) -> None:
    """Zmaže staré verzie. Spustená verzia sa premenovať nedá (otvorené súbory) – ostane do budúcna."""
    for p in LOCAL.iterdir():
        if p.name == ver or not p.is_dir():
            continue
        try:
            # .part môže práve kopírovať iný štart – mazať až starú
            if p.name.endswith(".part") and time.time() - p.stat().st_mtime < 3600:
                continue
            if not p.name.endswith(".del"):
                p = p.rename(p.with_name(p.name + ".del"))  # zlyhá, ak tá verzia ešte beží
        except OSError:
            continue
        shutil.rmtree(p, ignore_errors=True)


def main() -> None:
    try:
        ver = verzia()
    except OSError as e:
        chyba(f"Lupa nie je úplná – chýba {SRC / 'version.txt'}.\n\n{e}")
        return
    try:
        dst = priprav(ver)
    except OSError as e:
        chyba(f"Lupu sa nepodarilo skopírovať do počítača:\n{LOCAL / ver}\n\n{e}")
        return
    env = dict(os.environ, LUPA_HOME=str(HOME))
    subprocess.Popen([str(dst / EXE), *sys.argv[1:]], env=env, cwd=str(dst))
    try:
        uprac(ver)
    except OSError:
        pass


if __name__ == "__main__":
    main()
