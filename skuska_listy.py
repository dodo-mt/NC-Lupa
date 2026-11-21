"""Skúška: ktoré Word / Excel dokumenty sú CNC listy – podľa mena a ak nie je jasné, podľa obsahu.

Samostatný nástroj na overenie pravidla pred zapracovaním do skenera. Len číta (na L:\\ nič
nezapisuje); výsledok uloží do %LOCALAPPDATA%\\Lupa\\skuska_listy.html a otvorí ho.

Použitie:  skuska_listy.exe "L:\\100020"      (alebo bez parametra – opýta sa na priečinok)
           skuska_listy.exe "L:\\100020" --obsah   (obsah aj pri listoch podľa mena – overenie)

Pravidlo je v listy.py (to isté používa skener a Lupa) – nastavenia z lupa.ini vedľa programu.
"""
import html
import os
import sys
import time
import webbrowser
from pathlib import Path

import config
import listy

RULES = config.LIST_RULES
EXTS = {"doc", "docx", "docm", "xls", "xlsx", "xlsm"}


def by_name(name: str, rel_dir: str = "") -> str | None:
    p = RULES.by_name(name)
    return f"meno {p}" if p else None


def in_list_dir(rel_dir: str) -> bool:
    return RULES.in_list_dir(rel_dir)


def by_content(path: Path) -> tuple[bool, str]:
    ok, why = RULES.by_content(path)
    if ok:
        return True, "obsah " + why
    return False, ("len 1 slovo: " + why[5:]) if why.startswith("len: ") and "+" not in why \
        else (why or "nič z kľúčových slov")


def walk(root: Path):
    """Word / Excel v priečinku (preskakuje POF*, 3DF… ako skener)."""
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    if not config.is_ignored_dir(e.name) and not e.name.startswith("."):
                        stack.append(Path(e.path))
                elif e.name.rsplit(".", 1)[-1].lower() in EXTS and not e.name.startswith("~$"):
                    yield Path(e.path)
            except OSError:
                continue


ALL = False   # --obsah: obsah čítať aj pri listoch, ktoré spoznalo meno (overenie pravidla)


def main():
    global ALL
    args = [a for a in sys.argv[1:] if a != "--obsah"]
    ALL = "--obsah" in sys.argv
    if args:
        root = Path(args[0])
    else:
        root = Path(input("Priečinok na skúšku (napr. L:\\100020): ").strip().strip('"'))
    if not root.is_dir():
        input(f"Priečinok {root} neexistuje. Enter = koniec.")
        return
    rows = []
    t0 = time.perf_counter()
    for i, p in enumerate(walk(root), 1):
        rel_dir = str(p.parent.relative_to(root)) if p.parent != root else ""
        t = time.perf_counter()
        why = by_name(p.name, rel_dir)
        if why and ALL:   # kontrola pravidla podľa obsahu aj na listoch, ktoré spoznalo meno
            try:
                ok, c = by_content(p)
                why += f"  ·  obsah: {'ÁNO' if ok else 'nie'} ({c})"
            except Exception as e:
                why += f"  ·  obsah: chyba {type(e).__name__}"
        if why:
            res, how = "list", why
        else:
            try:
                ok, how = by_content(p)
                res = "list – obsah" if ok else "nie"
            except Exception as e:   # zamknutý / poškodený / zaheslovaný súbor
                res, how = "chyba", f"{type(e).__name__}: {e}"
        if in_list_dir(rel_dir):
            how += "  ·  (v priečinku CNC listy)"
        rows.append((res, str(p.relative_to(root)), how, time.perf_counter() - t))
        if i % 25 == 0:
            print(f"  {i} súborov…")
    total = time.perf_counter() - t0

    order = {"list – obsah": 0, "nie": 1, "chyba": 2, "list": 3}
    rows.sort(key=lambda r: (order[r[0]], r[1].lower()))
    counts = {k: sum(1 for r in rows if r[0] == k) for k in order}
    color = {"list": "#dcfce7", "list – obsah": "#bbf7d0", "nie": "#f3f4f6", "chyba": "#fee2e2"}
    out = config.LOCAL_DIR / "skuska_listy.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(
        f"<tr style='background:{color[r]}'><td>{html.escape(r)}</td><td class=m>{html.escape(f)}</td>"
        f"<td>{html.escape(h)}</td><td class=n>{s:.2f}</td></tr>" for r, f, h, s in rows)
    out.write_text(f"""<!doctype html><meta charset="utf-8"><title>Skúška CNC listov</title>
<style>body{{font:14px Segoe UI,sans-serif;margin:24px;color:#111827}}table{{border-collapse:collapse;width:100%}}
td,th{{padding:4px 8px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top}}
.m{{font-family:Consolas,monospace;font-size:12px}}.n{{text-align:right;color:#6b7280}}</style>
<h2>Skúška CNC listov – {html.escape(str(root))}</h2>
<p>{len(rows)} dokumentov (Word / Excel) za {total:.0f} s ·
<b>podľa mena {counts['list']}</b> · <b>podľa obsahu {counts['list – obsah']}</b> ·
nie {counts['nie']} · chyby {counts['chyba']}</p>
<p>Pravidlo (listy.py, verzia {listy.VERSION}): meno {', '.join(RULES.names)};
inak obsah: cesta „R:\\…\\“ alebo aspoň {RULES.words_min} z: {', '.join(RULES.words)}.
Priečinok „CNC listy“ nerozhoduje (len poznámka).</p>
<table><tr><th>Výsledok</th><th>Súbor</th><th>Prečo</th><th>s</th></tr>{body}</table>""", encoding="utf-8")
    print(f"\nHotovo: {len(rows)} dokumentov za {total:.0f} s. Správa: {out}")
    webbrowser.open(out.as_uri())
    if len(sys.argv) <= 1:
        input("Enter = koniec.")


if __name__ == "__main__":
    main()
