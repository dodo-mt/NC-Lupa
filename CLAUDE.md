# Lupa – prehliadač zákaziek

Windows aplikácia na prehliadanie a vyhľadávanie zákaziek na sieťovom disku `L:\`.
Používateľ: CNC programátor (hyperMILL, Heidenhain, Sinumerik). Komunikácia, UI aj komentáre v kóde **po slovensky**.

**Aktuálna verzia: 1.16.0** (`config.VERSION`). História verzií: `CHANGELOG.md`.
CNC znalosti (stroje, prípony, syntax NC a .pof, disky L:\ R:\, vzorky) sú v osobnom skille `cnc-programy` (`%USERPROFILE%\.claude\skills\cnc-programy`).

## Cieľ

Rýchlo nájsť súbory zákaziek a podobné diely („ako som to vtedy robil“) bez preklikávania v Prieskumníkovi.
**Princíp: jednoducho.** Rozšírenia po jednom, každé zvlášť. Podrobný popis funkcií a vzhľadu UI: `docs/FUNKCIE_A_VZHLAD.md`.

## Štruktúra disku L:\

- 1. úroveň = zákazník, 2. úroveň = zákazka. Medziúrovne nemajú pevnú hĺbku → **pozícia = skutočný priečinok**
  v zákazke (tabuľka `positions`, koreň zákazky má `rel_path = ''`). Žiadne hádanie.
- **Skener preskakuje** (zoznamy v `config.py`, pravidlo `config.is_ignored`): priečinky `POF*`, `VNC`, `STOCK`, `3DF`,
  `DEF`, `GEO`; `Thumbs.db`, `desktop.ini`, prípony `.bak .hmc_bak .hyperMILL .dwl .dwl2 .log .tmp .out .err .dep .pof
  .rsf .idx .xpr .m_p .crc .pro`, vzory `*.log.*`, `*_log.xml`, `trail.txt*`, `*.sec*`, `*.frm.*`, `*.lsl.*`, `*.inf.*`.
  `.xml` a `.ini` mimo POF ostávajú. Po zmene pravidla skener zmaže takéto súbory z DB (`drop_ignored`).
- Štruktúra `L:\<zákazník>\<zákazka>\[medziúrovne]\súbory`, staré značenie a `NC\` podľa strojov: skill `cnc-programy`. Rádovo desaťtisíce zákaziek, pribúda pár denne.

## Typy súborov (mapovanie len v `config.py`, málo štítkov je zámer)

PDF (.pdf) · MODEL (.stp .step .igs .iges .x_t .x_b .stl .catpart .catproduct .meg) · HMC (.hmc) · ECAM (.ppf) ·
NC (.h .nc .mpf .spf .wpd .eia .nd1 .nd2 .arc .dmg) · XLS (.xlsx .xlsm .xls) · DOC (.doc .docx) ·
CREO (.prt.N .drw.N .asm.N – len najvyššia verzia v priečinku, .cgm) · DWG (.dwg .dxf) · OBR (.tif .jpg .png .bmp .gif .webp .heic) ·
TXT (.txt) · MAIL (.msg .eml) · ZIP (.zip .rar .7z) · Ostatné. Farby sú v `config.py`. Nové prípony radšej do existujúcej
skupiny; zmena sa do DB prenesie pri ďalšom skene (`fix_types`).

## Architektúra

- **Python 3.11+**, Windows, `.venv`. UI: **pywebview** (HTML/CSS/JS bez frameworkov, `ui/`), DB **SQLite**.
- **Skener** (`scanner.py`, `--root L:\ --db <cesta> [--full] [--only "Zákazník"] [--auto]`): `os.scandir`, vlastník súboru
  cez `win32security` (pri chybe `?`). **Inkrementálny**: zákazka sa prečíta znova len ak je nová / zmenený `mtime` / zmena
  za `recent_days`; skenuje sa celá. `--auto` = inkrementálny + raz za 7 dní úplný. Zámok: beží len jeden sken.
  Zmazanie hlboko v starej zákazke sa prejaví až pri týždennom úplnom skene. Po úplnom skene `VACUUM` pri >5 % voľného miesta.
- **DB bez WAL** (je na sieti). Skener skenuje do pracovnej kópie `%LOCALAPPDATA%\Lupa\scan\` a cieľovú DB nahradí
  naraz (`os.replace`, opakuje pri obsadení), len keď sa niečo zmenilo. Pri chybe čítania priečinka skener **nič nemaže**
  (výpadok siete ≠ prázdny priečinok). Cesty >260 znakov: prefix `\\?\`.
- **Lupa DB otvára len na čítanie a len na dobu dotazu** (aby ju skener mohol vymeniť). **`db.ro_uri()`**: `Path.as_uri()`
  pre sieťovú cestu dá `file://server/...` (SQLite: „invalid uri authority“); správne je `file:////server/share/...`.
- **Lokálna kópia DB** (`dbcopy.py`): číta sa z `%LOCALAPPDATA%\Lupa\db\`, nie cez SMB (štart 16 s → 0,4 s). Pri štarte sa
  kopíruje hneď (pásik %), potom na pozadí. L:\ nedostupný → posledná kópia + upozornenie.
- **Moduly**: `odtlacky.py` (odtlačky PDF pre podobné výkresy; po zmene algoritmu zvýš `odtlacky.VERSION`), `listy.py`
  (CNC listy podľa mena aj obsahu, tabuľka `doclists`), `stroje.py` (stroje zákazky, počíta Lupa pri kliku), `obsah.py`
  (hľadanie v NC naživo), `nastroje.py` (nástroje NC programov) + `kod_nastroja.py` (dekódovanie osemmiestnych kódov nástrojov: typ, priemer, polomer; skill `cnc-programy`), `odladene.py`, `nahlad.py`, `vykres.py` (DXF/DWG),
  `editor.py` (NC Editor), `winstate.py`, `nastavenia.py`, `tray.py`.
- **Balenie**: `python build.py` → `dist\Lupa\`: `app\` (onedir + `version.txt`), `Lupa.exe` = spúšťač (`launcher.py`,
  onefile), `lupa-sken.exe` (onefile), `deploy\`, `lupa.ini.example`. Celý priečinok → `L:\_Nastroje\lupa\`
  (DB `lupa.db` a spoločný `lupa.ini` tam). Po kopírovaní zavrieť bežiacu Lupu (aj na lište).
  `build.py` stiahne LibreDWG (`tools\libredwg\`, mimo gitu) a overí SHA-256.
- **Spúšťač**: **onedir zo siete nejde** (.NET pywebview odmieta DLL zo sieťového disku), onefile je pomalý. Preto spúšťač
  kopíruje `app\` do `%LOCALAPPDATA%\Lupa\app\<verzia>\` (len po novej verzii, staré zmaže) a spustí s `LUPA_HOME`
  = priečinok spúšťača (`config.APP_DIR`).
- **Jedno hlavné okno**: mutex `Local\NC_Lupa_hlavne_okno`, druhý štart len vyvolá okno bežiacej Lupy (výnimka `--hladat`).
  pywebview pri `private_mode=False` servíruje UI z pevného portu **42001**; `_volny_port()` vezme 42001 alebo voľný port.
  Druhé okno za behu sa vytvára `hidden=True` (`winstate.show_centered`).
- **Ikona skenu** (`lupa-sken.exe --tray`, len pywin32): sken každú hodinu, beží na PC používateľa z `%LOCALAPPDATA%\Lupa\bin`
  (inštalácia `deploy\ikona_skenu.bat`, po novom skeneri ju treba spustiť znova). Log lokálne aj vedľa DB (rotácia 2 MB × 3).
- **Nastavenia**: `lupa.ini` (`customers`, `exclude`, `recent_days`, `prints_minutes`, `listy_*`, `odladene_priecinky`, `spravca`…);
  skener číta ini vedľa programu a potom vedľa DB. Pravidlá strojov v `[stroje]` / `[stroje_listy]`.
- **NC Editor**: nález / porovnanie sa otvára cez `NCEditor.exe cesta:riadok` / `--porovnaj A B` (od NC Editora
  2026.11.26-11 / -12; staršiemu sa riadok nepošle). Skúšanie: `LUPA_NC_EDITOR_VERZIA=<verzia>`.
- **Launcher NC Nástroje** spúšťa Lupu priamo z `L:\_Nastroje\lupa`; `Lupa.exe --hladat <text>` otvorí hľadanie.
- **Skúška na zákazke**: vždy `--only "Zákazník"` alebo `vzorky\`, nie celý `L:\`.

### Pravidlá

- **Na `L:\` sa NIKDY nič nemení ani nemaže.** Lupa len číta. Jediný zápis je vlastná databáza (a `lupa.ini` cez Nastavenia).
- Žiadne admin práva, inštalácia, server/porty (okrem lokálneho portu pywebview) – IT nesmie mať dôvod namietať.
- Chyby prístupu, dlhé cesty, divné znaky v názvoch → zalogovať a pokračovať.
- Žiadna výnimka nesmie zhodiť UI; sieť nikdy neblokuje UI.

## Databáza (SQLite)

```sql
customers(id, name, path, dir_mtime)
jobs(id, customer_id, name, path, dir_mtime, last_scan, last_change, created, added_by)
positions(id, job_id, name, rel_path, path)
files(id, position_id, job_id, customer_id, name, ext, ftype, path,
      size, created, modified, owner, target)
scan_log(id, started, finished, mode, files_seen, errors)
prints(path, size, modified, version, views)   -- odtlačky PDF
doclists(path, size, modified, version, is_list, why)   -- CNC listy podľa obsahu
```

Indexy: `files(name)`, `files(owner)`, `files(ftype)`, `files(modified)`. Hľadanie `LIKE '%…%'`. DB ~250 MB, ~42 000 zákaziek.

## Testy, build, spustenie

- Testy: `.venv\Scripts\python.exe -m pytest tests` (pytest je len vo vývojovom `.venv`).
- Vývoj: lokálny `lupa.ini` (mimo gitu) ukazuje na `vzorky\` (kópia štruktúry `L:\`, **nikdy na git**).
- Build: `python build.py` → `dist\Lupa\` → kopírovať na `L:\_Nastroje\lupa\`.
- `requirements.txt` udržuj aktuálny (pywebview, pywin32, PyMuPDF, numpy, ezdxf, pillow).

## Spôsob práce

- Pred väčšou zmenou krátko popíš plán, potom implementuj. Malé kroky, po každom sa dá aplikácia spustiť.
- **Verzia** je v `config.VERSION`; pri vydaní pre `L:\_Nastroje\lupa\` ju zvýš, pridaj záznam do `CHANGELOG.md` a git tag `vX.Y.Z`.
- Konfigurácia v `config.py` / `lupa.ini`, nie natvrdo v kóde. Pracuj len v adresári projektu.

## Rozpracované / ďalšie kroky

- Náhľady Word / Excel (`dokument.py`, `thumbs.py`) – len lokálne, necommitnuté, skúša sa v práci (stav k 23.11.2026).
- Overiť na ostrých dátach: ciele odkazov .lnk na sieťovom `L:\`, menu zákaziek pri `324`.
- Náhľad STP – odložené (gmsh nespoľahlivý, 17/47 vzoriek); ak znova, tak OpenCascade (`cadquery-ocp`).
- Podobné výkresy: slabé pri našom `drw0001` ↔ výkres zákazníka; neskôr kombinácia s rozmermi zo STP.

História verzií: CHANGELOG.md
