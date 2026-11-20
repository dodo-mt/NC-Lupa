"""Zostavenie Lupy do exe (PyInstaller) – výsledok v dist\\Lupa\\ na skopírovanie na L:\\_Lupa\\.

Použitie:  .venv\\Scripts\\python.exe build.py
"""
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
OUT = ROOT / "dist" / "Lupa"
ASSETS = ROOT / "assets"
ICON = ASSETS / "lupa.ico"
ICON_SCAN = ASSETS / "lupa-scan.ico"


def make_icon(path: Path, dot: bool = False):
    """Ikona: modrá lupa na tmavom štvorci (farby z UI). ICO s PNG obrázkami.

    dot=True: s oranžovou bodkou – ikona pri hodinách počas skenu.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=256, height=256)
    shape = page.new_shape()
    shape.draw_rect(pymupdf.Rect(8, 8, 248, 248), radius=0.18)
    shape.finish(fill=(0x11 / 255, 0x18 / 255, 0x27 / 255), color=None)
    blue = (0x60 / 255, 0xA5 / 255, 0xFA / 255)
    shape.draw_circle((108, 108), 58)
    shape.finish(color=blue, width=26, fill=None)
    shape.draw_line((152, 152), (206, 206))
    shape.finish(color=blue, width=34, lineCap=1)
    if dot:
        shape.draw_circle((196, 60), 50)
        shape.finish(fill=(0xF9 / 255, 0x73 / 255, 0x16 / 255), color=(0x11 / 255, 0x18 / 255, 0x27 / 255), width=10)
    shape.commit()

    pngs = []
    for size in (256, 64, 48, 32, 16):
        pix = page.get_pixmap(matrix=pymupdf.Matrix(size / 256, size / 256), alpha=True)
        pngs.append((size, pix.tobytes("png")))

    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = len(header) + 16 * len(pngs)
    entries, data = b"", b""
    for size, png in pngs:
        s = 0 if size == 256 else size
        entries += struct.pack("<BBBBHHII", s, s, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + data)


def pyinstaller(script: str, name: str, extra: list[str]):
    cmd = [
        sys.executable, "-m", "PyInstaller", script,
        "--name", name, "--onefile", "--noconsole", "--noconfirm", "--clean",
        "--icon", str(ICON),
        "--distpath", str(OUT), "--workpath", str(BUILD / name), "--specpath", str(BUILD),
        "--exclude-module", "tkinter",
        *extra,
    ]
    print(">", " ".join(cmd[3:]))
    subprocess.run(cmd, check=True, cwd=ROOT)


def make_icons():
    make_icon(ICON)
    make_icon(ICON_SCAN, dot=True)


def main():
    shutil.rmtree(OUT, ignore_errors=True)  # žiadne zvyšky starých verzií
    make_icons()
    pyinstaller("app.py", "Lupa", ["--add-data", f"{ROOT / 'ui'};ui"])
    pyinstaller("scanner.py", "lupa-sken", [
        "--add-data", f"{ASSETS};assets",
        "--exclude-module", "pymupdf", "--exclude-module", "webview",
    ])
    # sprievodné súbory: všetko z deploy\ + vzor nastavení
    for f in (ROOT / "deploy").iterdir():
        shutil.copy2(f, OUT / f.name)
    shutil.copy2(ROOT / "lupa.ini.example", OUT / "lupa.ini.example")
    print(f"\nHotovo: {OUT}")
    for p in sorted(OUT.iterdir()):
        print(f"  {p.name:22} {p.stat().st_size / 1024 / 1024:6.1f} MB")


if __name__ == "__main__":
    main()
