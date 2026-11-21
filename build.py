"""Zostavenie Lupy do exe (PyInstaller) – výsledok v dist\\Lupa\\ na skopírovanie na L:\\_Lupa\\.

Použitie:  .venv\\Scripts\\python.exe build.py
"""
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

import pymupdf

import config

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


def version_file(name: str, desc: str) -> Path:
    """Súbor s verziou pre PyInstaller – zobrazí sa vo Vlastnostiach exe (Podrobnosti)."""
    nums = [int(x) for x in config.VERSION.split(".")] + [0]
    t = tuple(nums[:4])
    path = BUILD / f"version_{name}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041B04B0', [
      StringStruct('FileDescription', '{desc}'),
      StringStruct('FileVersion', '{config.VERSION}'),
      StringStruct('ProductName', 'Lupa'),
      StringStruct('ProductVersion', '{config.VERSION}'),
      StringStruct('OriginalFilename', '{name}.exe'),
      StringStruct('InternalName', '{name}')])]),
    VarFileInfo([VarStruct('Translation', [0x041B, 1200])])
  ]
)
""", encoding="utf-8")
    return path


def pyinstaller(script: str, name: str, desc: str, extra: list[str],
                onedir: bool = False, dist: Path = OUT, tag: str | None = None):
    """tag = meno pracovného priečinka (Lupa aj spúšťač sa volajú Lupa.exe)."""
    tag = tag or name
    cmd = [
        sys.executable, "-m", "PyInstaller", script,
        "--name", name, "--onedir" if onedir else "--onefile", "--noconsole", "--noconfirm", "--clean",
        "--icon", str(ICON), "--version-file", str(version_file(name, desc)),
        "--distpath", str(dist), "--workpath", str(BUILD / tag), "--specpath", str(BUILD / tag),
        "--exclude-module", "tkinter",
        *extra,
    ]
    print(">", " ".join(cmd[3:]))
    subprocess.run(cmd, check=True, cwd=ROOT)


# LibreDWG (GPLv3) – dwg2dxf.exe na náhľad DWG (vykres.py). Do gitu nejde (35 MB), stiahne sa
# z oficiálneho vydania a overí podľa SHA-256 (zmena verzie = nová adresa aj odtlačok).
LIBREDWG_URL = "https://github.com/LibreDWG/libredwg/releases/download/0.13.3/libredwg-0.13.3-win64.zip"
LIBREDWG_SHA256 = "b5133f8b6bd71b7e682a06ef5f99c93b40d628a791c30a31924a80d258c87173"
LIBREDWG_FILES = ["dwg2dxf.exe", "libredwg-0.dll", "libiconv-2.dll", "libpcre2-8-0.dll",
                  "libpcre2-16-0.dll", "README.txt"]


def ensure_libredwg() -> Path:
    """tools\\libredwg\\ s dwg2dxf.exe (stiahne pri prvom zostavení)."""
    import hashlib
    import io
    import urllib.request
    import zipfile

    import vykres
    dst = vykres.libredwg_dir()
    if all((dst / f).exists() for f in LIBREDWG_FILES):
        return dst
    print(f"Sťahujem LibreDWG: {LIBREDWG_URL}")
    data = urllib.request.urlopen(LIBREDWG_URL, timeout=120).read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != LIBREDWG_SHA256:
        raise SystemExit(f"LibreDWG: nesedí SHA-256 ({digest}) – súbor sa nepoužije.")
    dst.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for f in LIBREDWG_FILES:
            (dst / f).write_bytes(z.read(f))
    return dst


def make_icons():
    make_icon(ICON)
    make_icon(ICON_SCAN, dot=True)


def main():
    shutil.rmtree(OUT, ignore_errors=True)  # žiadne zvyšky starých verzií
    OUT.mkdir(parents=True)
    make_icons()
    print(f"Lupa v{config.VERSION}")
    # Lupa = onedir v app\ (štartuje rýchlo, ale zo siete nejde – spúšťa sa z lokálnej kópie),
    # Lupa.exe = spúšťač, ktorý app\ skopíruje do %LOCALAPPDATA% a spustí (launcher.py)
    pyinstaller("app.py", "Lupa", "Lupa – prehliadač zákaziek", ["--add-data", f"{ROOT / 'ui'};ui"],
                onedir=True, dist=BUILD / "onedir", tag="Lupa-app")
    shutil.move(BUILD / "onedir" / "Lupa", OUT / "app")
    shutil.copytree(ensure_libredwg(), OUT / "app" / "libredwg")   # náhľad DWG (vykres.py)
    stamp = f"{config.VERSION}+{time.strftime('%Y%m%d-%H%M%S')}"  # aj zostavenie bez novej verzie sa prenesie
    (OUT / "app" / "version.txt").write_text(stamp, encoding="utf-8")
    pyinstaller("launcher.py", "Lupa", "Lupa – prehliadač zákaziek", [
        "--exclude-module", "webview", "--exclude-module", "numpy", "--exclude-module", "pymupdf",
        "--exclude-module", "ezdxf", "--exclude-module", "PIL",
    ], tag="Lupa-spustac")
    pyinstaller("scanner.py", "lupa-sken", "Lupa – sken zákaziek", [
        "--add-data", f"{ASSETS};assets",
        "--exclude-module", "webview", "--exclude-module", "ezdxf", "--exclude-module", "PIL",
    ])
    # sprievodné súbory: všetko z deploy\ + vzor nastavení
    for f in (ROOT / "deploy").iterdir():
        shutil.copy2(f, OUT / f.name)
    shutil.copy2(ROOT / "lupa.ini.example", OUT / "lupa.ini.example")
    print(f"\nHotovo: {OUT}")
    for p in sorted(OUT.iterdir()):
        size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else p.stat().st_size
        print(f"  {p.name + ('\\' if p.is_dir() else ''):22} {size / 1024 / 1024:6.1f} MB")


if __name__ == "__main__":
    main()
