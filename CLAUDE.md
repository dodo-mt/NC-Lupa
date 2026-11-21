# Lupa – prehliadač zákaziek

Windows aplikácia na prehliadanie a vyhľadávanie zákaziek na sieťovom disku `L:\`.
Používateľ: CNC programátor (hyperMILL, Heidenhain, Sinumerik). Komunikácia, UI aj komentáre v kóde **po slovensky**.

## Cieľ

Rýchlo nájsť súbory zákaziek a podobné diely („ako som to vtedy robil“) bez preklikávania v Prieskumníkovi.
Dnes sa to robí tak, že sa v Prieskumníkovi vyfiltrujú moje PDF / HMC / PPF a hľadá sa podobný kus – Lupa to má nahradiť.

**Princíp: jednoducho. Najprv funkčný základ (verzia 1), rozšírenia až postupne, po jednom.**

## Štruktúra disku L:\

```
L:\<Zákazník>\<Zákazka>\[voliteľne 1+ medziúrovne: pozícia / číslo / text]\súbory
```

- 1. úroveň = zákazník, 2. úroveň = zákazka.
- Medziúrovne nemajú pevnú hĺbku a pomenovanie je rôzne (`DVA KUSY`, `OP20`, `POLOTOVAR`, `21750-1A`, `3DF`…)
  → **pozícia = skutočný priečinok** v zákazke (tabuľka `positions`, koreň zákazky má `rel_path = ''`).
  Žiadne hádanie, čo je „pozícia“; strom ukazuje reálne podpriečinky. Klik na zákazku ukáže všetky jej súbory.
- **Skener preskakuje** (zoznamy v `config.py`): priečinky (vzory) `POF*` (POF111, pof2…), `VNC`, `STOCK`,
  `3DF`, `DEF`, `GEO` (interné dáta hyperMILL – `config.is_ignored_dir`),
  súbory `Thumbs.db`, `desktop.ini`, prípony `.bak .hmc_bak .hyperMILL .dwl .dwl2 .log .tmp .out .err .dep
  .pof .rsf .idx .xpr .m_p .crc .pro` (`.H.T.DEP` Heidenhain, `std.err/out`, `config.pro` Creo),
  vzory `*.log.*` a `*_log.xml` (logy z exportu Creo), `trail.txt*`, `*.sec`, `*.sec.*`, `*.frm.*`,
  `*.lsl.*`, `*.inf.*` (Creo s číslom verzie). `.xml` a `.ini` mimo POF ostávajú (môžu byť užitočné).
  Pravidlo = `config.is_ignored`; po jeho zmene skener pri ďalšom skene zmaže takéto súbory
  aj priečinky z DB (`drop_ignored`). „Zobraziť všetko“ zámerne nie – DB by narástla, na to je Prieskumník.
- Staré značenie: zákazník môže byť aj v starom tvare (napr. `OD067` = dnešný `100020`) a zákazky v ňom
  majú čísla ako `009712`. Lupa ich berie bežne ako zákazník → zákazka.
- NC programy bývajú v podpriečinku `NC\` (triedené po strojoch: eVo 80, monoBLOCK H640, DMC 160, monoBLOCK 840D).
- Rádovo **tisíce zákaziek**, pribúda pár denne.

## Typy súborov a farby

| Typ | Prípony | Farba (pozadie / text) |
|-----|---------|------------------------|
| PDF – výkres | .pdf | #fee2e2 / #7f1d1d |
| MODEL – 3D model | .stp .step .igs .iges .x_t .x_b .stl .catpart .catproduct .meg | #dbeafe / #1e3a8a |
| HMC – hyperMILL | .hmc | #ffedd5 / #7c2d12 |
| ECAM – Edgecam | .ppf | #fef3c7 / #78350f |
| NC – programy | .h .nc .mpf .spf .wpd .eia .nd1 .nd2 .arc .dmg | #dcfce7 / #14532d |
| XLS – Excel (CNC listy) | .xlsx .xlsm .xls (všetky Excely – väčšinou CNC listy) | #ccfbf1 / #134e4a |
| DOC – Word | .doc .docx | #e0e7ff / #312e81 |
| CREO – Creo | .prt.N .drw.N .asm.N (N = verzia, berie sa len najvyššia v priečinku), .cgm (zjednodušený výkres) | #f9ded3 / #8a3517 |
| DWG – AutoCAD | .dwg .dxf | #ede9fe / #4c1d95 |
| OBR – obrázok / sken | .tif .tiff .jpg .jpeg .png .bmp .gif .webp .heic | #fce7f3 / #831843 |
| TXT – poznámky | .txt (náhľad ako text) | #ecfccb / #365314 |
| MAIL – e-mail | .msg .eml | #fae8ff / #86198f |
| ZIP – archív | .zip .rar .7z | #e7e5e4 / #44403c |
| Ostatné | * | #f3f4f6 / #374151 |

Málo štítkov je zámer (jeden riadok filtrov) – nové prípony radšej do existujúcej skupiny.
Zmena mapovania sa do DB prenesie pri ďalšom skene (`fix_types`), netreba úplný sken.

Mapovanie drž na jednom mieste (`config.py`), aby sa dalo ľahko rozšíriť.

## Architektúra

- **Python 3.11+**, Windows.
- **Skener** (`scanner.py`): prejde `L:\`, zapíše do **SQLite** databázy.
  - `os.scandir` (rýchle), žiadne `os.walk` so `stat` navyše.
  - **Vlastník súboru** = „kto to robil“: `win32security.GetFileSecurity(... OWNER_SECURITY_INFORMATION)` → `LookupAccountSid` → doménové meno (napr. `pnovak`). Pri chybe práv ulož `?`, nepadaj.
  - **Inkrementálny sken**: ulož `mtime` priečinkov; zoznam zákaziek každého zákazníka sa číta vždy (lacné),
    znova sa skenujú len zákazky nové, so zmeneným `mtime` alebo so zmenou za posledných N dní (`jobs.last_change`, `recent_days` v `lupa.ini`).
    Zákazka sa skenuje vždy celá (zmaž + vlož nanovo). Prepínač `--full` pre úplný sken (raz týždenne).
  - Databáza **bez WAL** (bude na sieťovom disku). Log skenera: `lupa_scan.log` vedľa DB.
  - **Pracovná kópia**: skener skenuje do `%LOCALAPPDATA%\Lupa\scan\lupa-<hash>.db` a cieľovú DB nahradí
    naraz (`os.replace`, opakuje pri obsadení) – len keď sa niečo zmenilo (značka `.pending`).
    Pri nezmenenej zákazke sa nič neprepisuje a vlastník sa preberá z DB (GetFileSecurity cez sieť je pomalé).
  - `--auto` = inkrementálny, raz za 7 dní úplný (pre Plánovač úloh). Zámok – súbežne beží len jeden sken.
  - Zmazanie / premenovanie hlboko v starej zákazke nezmení `mtime` zákazky → v DB do týždenného úplného
    skenu. Po úplnom skene `VACUUM`, ak je v DB >5 % voľného miesta (DB sa kopíruje do každého PC).
  - **Odtlačky výkresov** (`odtlacky.py`, tabuľka `prints`, kľúč = cesta + veľkosť + mtime + `odtlacky.VERSION`):
    po skene súborov sa dopočítajú chýbajúce (najnovšie PDF prvé), najviac `prints_minutes` min na sken
    (`lupa.ini`, 0 = vypnuté) – prvý prechod L:\ sa rozloží do viacerých skenov. Pri zmene algoritmu zvýš `VERSION`.
- Aplikácia otvára DB **len na dobu dotazu** (nedrží súbor), aby ho skener mohol vymeniť.
  - **Lokálna kópia DB** (`dbcopy.py`): Lupa číta z `%LOCALAPPDATA%\Lupa\db\lupa-<hash>-<veľkosť>-<mtime>.db`,
    nie cez sieť (SQLite cez SMB: štart 16 s, lokálne 0,4 s; kópia 246 MB ~1–3 s). Pri štarte sa kopíruje
    hneď (pásik v stavovom riadku s %), počas behu na pozadí (kontrola zdroja raz za 10 s).
    L:\ nedostupný → posledná kópia + upozornenie v stavovom riadku. Staré kópie sa mažú.
  - Spúšťanie z príkazového riadka (neskôr cez Plánovač úloh): `python scanner.py --root L:\ --db <cesta> [--full] [--only "Zákazník"]`.
- **Aplikácia** (`app.py`): **pywebview** okno s HTML/CSS/JS rozhraním (nie prehliadač, nie server).
  - Python strana vystavuje API cez `js_api` (hľadanie, filtre, strom, otvorenie súboru).
  - Dvojklik na súbor → `os.startfile(cesta)` (otvorí v hyperMILL, Creo, PDF prehliadači…).
  - Databázu otvára **len na čítanie** (`file:...?mode=ro`, `uri=True`).
- **UI** (`ui/index.html`, `ui/style.css`, `ui/app.js`): čisté HTML/CSS/JS, bez frameworkov a buildov.
- **Balenie**: `python build.py` → `dist\Lupa\`: `app\` (Lupa onedir + `version.txt` = verzia + čas
  zostavenia), `Lupa.exe` = spúšťač (`launcher.py`, onefile), `lupa-sken.exe` (onefile), + súbory
  z `deploy\` a `lupa.ini.example`. Celý priečinok sa skopíruje na `L:\_Lupa\`. Predvolene root = `L:\`,
  DB = `lupa.db` vedľa exe.
  - **Spúšťač**: onedir zo siete nejde (.NET pywebview odmieta DLL zo sieťového disku), onefile je pomalý
    (rozbaľuje sa pri každom štarte). Spúšťač skopíruje `app\` do `%LOCALAPPDATA%\Lupa\app\<verzia>\`
    (len po novej verzii; každá verzia zvlášť, bežiacu nejde prepísať; staré sa zmažú) a spustí ju
    s `LUPA_HOME` = priečinok spúšťača → `config.APP_DIR` (lupa.ini, lupa.db na L:\_Lupa).
- **Automatický sken = ikona pri hodinách** (`tray.py`, `lupa-sken.exe --tray`): sken každú hodinu
  (prvý 2 min po štarte), menu (Skenovať teraz, Úplný sken, Otvoriť Lupu, Otvoriť log, Ukončiť),
  upozornenia Windows (L:\ nedostupný – až pri 2. neúspechu, chyby, nezverejnená DB, nové zákazky,
  výsledok ručného skenu). Len pywin32 (Shell_NotifyIcon), žiadne ďalšie knižnice.
  Inštalácia `deploy\ikona_skenu.bat`: kópia exe do `%LOCALAPPDATA%\Lupa\bin` (L:\ pri prihlásení ešte
  nemusí byť pripojený) + odkaz v Po spustení s `--root`/`--db`. Beží na PC používateľa.
- Log skenera: vždy lokálne `%LOCALAPPDATA%\Lupa\lupa_scan.log` + vedľa DB (rotácia 2 MB × 3).
- Skener pri chybe čítania priečinka **nič nemaže** (výpadok siete ≠ prázdny priečinok).
- **Zákazníci v koreni**: `customers` / `exclude` v `lupa.ini` (vzory fnmatch, čiarkou). Skener číta
  `lupa.ini` vedľa programu a potom vedľa DB (`config.scan_settings`) – ikona skenu beží z kópie
  v `%LOCALAPPDATA%`, spoločné nastavenia sú v `L:\_Lupa\lupa.ini`. `--only` filter obchádza.
- DB sa otvára cez `db.ro_uri()` – `Path.as_uri()` pre sieťovú cestu dá `file://server/...`,
  čo SQLite odmietne („invalid uri authority“); správne je `file:////server/share/...`.

### Pravidlá

- **Na `L:\` sa NIKDY nič nemení ani nemaže.** Lupa len číta. Jediný zápis je vlastná databáza.
- Žiadne admin práva, žiadna inštalácia, žiadny server/porty (IT oddelenie nesmie mať dôvod namietať).
- Chyby prístupu, dlhé cesty, divné znaky v názvoch → zalogovať a pokračovať.
- Cesty dlhšie ako 260 znakov: použi prefix `\\?\` pri skenovaní.

## Databáza (SQLite) – návrh

```sql
customers(id, name, path, dir_mtime)
jobs(id, customer_id, name, path, dir_mtime, last_scan)
positions(id, job_id, name, rel_path, path)
files(id, position_id, job_id, customer_id, name, ext, ftype, path,
      size, created, modified, owner)
scan_log(id, started, finished, mode, files_seen, errors)
prints(path, size, modified, version, views)   -- odtlačky PDF, views = odtlacky.pack()
```

- Indexy: `files(name)`, `files(owner)`, `files(ftype)`, `files(modified)`.
- Hľadanie podľa časti názvu: `LIKE '%…%'` (pri raste zvážiť FTS5).
- Odhad veľkosti: ~150 000 súborov → desiatky MB.

## Stav projektu (aktuálne 1.3.6)

Hotové: verzia 1 (nižšie) + náhľady, galéria, NC/TXT náhľad, kontrola úplnosti, exe, ikona skenu
pri hodinách, stavový riadok, kontextové menu stromu, podobné výkresy, filter zákazníkov v `lupa.ini`,
hľadanie čísla zákazky v strome, typy XLS/DOC zvlášť,
lokálna kópia DB, spúšťač, nové typy, odkazy .lnk, menu zákaziek pod hľadaním (1.3.2).
Vydania = git tagy `v1.0`, `v1.1.0`, `v1.2.0`, `v1.3.0`, `v1.3.1`, `v1.3.2`, `v1.3.3`, `v1.3.4` (pushnuté na GitHub `origin/main`).

**Ostré nasadenie (20.11.2026)**: DB `L:\_Lupa\lupa.db` na sieťovom disku (~180 MB).
Prvý úplný sken L:\ (ešte skener 1.0 na inom PC) – ~1 h, 33 600+ zákaziek / 237 zákazníkov, bez chýb.
Lupa 1.2.0 tam mala prázdne okno (DB na sieti – `db.ro_uri`), opravené v 1.3.0 a overené používateľom.

**21.11.2026**: v noci prebehol úplný sken L:\ aj so všetkými odtlačkami PDF (DB ~250 MB, 42 000 zákaziek,
328 zákazníkov, 63 000 odtlačkov). Spúšťač + lokálna kópia DB overené používateľom na L:\ („vyzerá fajn“).

**Vydaná 1.3.2 (21.11.2026)** – tag `v1.3.2`, build v `dist\Lupa\`. Obsahuje: lokálna kópia DB + pásik,
spúšťač (onedir v `app\`), nové typy (MODEL, OBR, MAIL, ZIP, ECAM, XLS aj xlsm), skryté súbory/priečinky
+ upratanie DB + VACUUM, odkazy .lnk, dvojklik = ukázať v strome, kontextové menu súborov, stĺpce,
vlastníci, strom šípkami, menu zákaziek pod hľadaním.
**1.3.3 (21.11.2026)**: menu zákaziek – koniec čísla (`014` = `100014`) pred „začína na“, zákazníci
majú vlastné 4 miesta.
**1.3.4**: menu zákaziek – `OD…` pred starými, novšie skôr, rok zmeny pri zákazke.
**1.3.5** (len build, bez tagu): tlačidlo Obnoviť (F5), upozornenie na novú verziu Lupy, „Odkazujú sem“.
**1.3.6**: odkazy .lnk oboma smermi + ikonka v strome, náhľady DXF a DWG (`vykres.py`).
Pozor: po kopírovaní na L:\ zavrieť bežiacu Lupu (aj na lište), inak ostane stará.
Potom u používateľa: `dist\Lupa\` → `L:\_Lupa\` (celý priečinok, aj `app\`), na PC so skenerom znova
`ikona_skenu.bat` (nový skener preradí typy, vyhodí skryté súbory, doplní ciele .lnk – bez úplného skenu).
Overiť: ciele odkazov .lnk na sieťovom L:\ (lokálne netestovateľné), menu zákaziek pri `324` na ostrých dátach.

**Podobné výkresy** (bod 5): odtlačky v skeneri + UI hotové (tlačidlo v detaile PDF, výsledok
v zozname/galérii so stĺpcom Podobnosť, Esc = späť; `Api.similar`, index v pamäti do zmeny DB).
Slabé miesto: náš `drw0001` ↔ výkres zákazníka (iné rozloženie pohľadov) – neskôr kombinácia s STP.

**Ďalšie možné kroky**: STL – v práci ho Windows už ukazuje (doplnok), vlastné netreba.
**Náhľad STP – odložené** (skúška 21.11.2026 mimo projektu): gmsh/OpenCascade načítal STP a rozmery,
ale vykreslil len 17/47 vzoriek (zlyháva sieť trojuholníkov hlavne pri dieloch z Crea, pády,
limity), +86 MB. Ak znova: priamo OpenCascade (`cadquery-ocp`, BRepMesh – spoľahlivejšie, ~+150 MB);
rozmery zo STP by sa hodili k podobným výkresom.

**Na rade (21.11.2026)**:
- Pomalý štart (16 s cez sieť – meranie `zmeraj_start.py`: počet odtlačkov 8,3 s, úplnosť 4,7 s) →
  lokálna kópia DB + pásik priebehu (overené, ~5 s – zvyšok bol štart onefile exe) → spúšťač + onedir
  (overené na L:\).
- ✅ Filter vlastníka: počty súborov len vo vybranej zákazke / u zákazníka (`get_owners(params)`).
- ✅ Odkazy .lnk – fáza 2: pri starej zákazke „Odkazujú sem: zákazky X, Y“ (1.3.5).

## Verzia 1 – rozsah (hotové)

1. Skener + databáza, test najprv na **jednom zákazníkovi** (`--only`).
2. Okno: strom zákazník → zákazka → pozícia (vľavo).
3. Zoznam súborov zafarbený podľa typu: typ, názov, vlastník, vytvorený, zmenený, veľkosť; triedenie klikom na hlavičku.
4. Hľadanie podľa časti názvu (napr. číslo výkresu) – živé, počas písania, naprieč celým `L:\` aj v aktuálnej zákazke.
5. Filtre: vlastník, typ (farebné „chipy“), rozsah *Aktuálna zákazka / Celé L:\*.
6. Dvojklik → otvoriť súbor. Tlačidlo „Otvoriť priečinok“.

## Rozšírenia (postupne, každé zvlášť)

1. ✅ Pravý panel s detailom a **náhľadmi** (PDF cez PyMuPDF; ostatné cez Windows shell `IShellItemImageFactory`; NC/TXT ako text), cache v `%LOCALAPPDATA%\Lupa\thumbs`.
   **DXF / DWG** (`vykres.py`, 1.3.6): ezdxf → PyMuPDF (čierne na bielom ako tlač; entita, ktorá
   zlyhá, sa vynechá). DWG najprv `dwg2dxf.exe` z LibreDWG 0.13.3 (GPLv3, samostatný exe, `app\libredwg\`;
   `build.py` ho stiahne do `tools\libredwg\` – mimo gitu – a overí SHA-256) do `%LOCALAPPDATA%\Lupa\tmp`.
   Kreslí sa len veľký náhľad, galéria dostane zmenšeninu; veľký výkres aj ~15 s (potom z cache).
   Nevykreslený výkres → náhľad/ikona z Windows. Vo vzorkách 17/17 (aj staré DWG R14).
2. ✅ **Galéria** – mriežka náhľadov, posuvník veľkosti, triedenie.
3. ✅ Kontrola **úplnosti zákazky** (Model / PDF / CAM / NC / Listy) – stav v strome + štítky.
4. ✅ Exe na `L:\_Lupa\` (`build.py`) + ikona skenu pri hodinách (namiesto Plánovača úloh).
5. ✅ **Nájdi podobné výkresy** – offline obrazové „odtlačky“ PDF (orezať rám a pečiatku), neskôr kombinácia s rozmermi zo STP.
   Metóda: list → pohľady (zhluky čiar) → mriežka 16×16, porovnanie v 8 symetriách, slabší z oboch smerov.
   Na vzorkách: rovnaký výkres / sken / revízia = 1. miesto; náš `drw0001` ↔ výkres zákazníka zatiaľ slabé.

## Vzhľad

Schválený návrh UI (maketa): https://claude.ai/artifact/MHEAKvNtdfXvU9EaucAA1w

- Tmavá horná lišta (#111827) s názvom „Lupa“, hľadaním a prepínačom Zoznam / Galéria. Verzia v názve okna („Lupa 1.2.0“).
- Biela lišta filtrov pod ňou (vlastník ako štítok, chipy typov, všetky/žiadne, rozsah).
- **Zarovnanie**: hľadanie aj filtre začínajú nad zoznamom súborov – ľavý stĺpec má šírku stromu
  (CSS premenná `--tree-w`, mení ju ťahanie). Nad stromom: „Zákazníci“ + Rozbaliť/Zbaliť všetko.
- **Stavový riadok** dole (nenápadný): vľavo koreň + počty z DB, vpravo „Posledný sken“
  (oranžovo, ak je starší ako 24 h). Čas skenu z `lupa_scan.json` vedľa DB – skener ho zapisuje
  pri každom skene, aj keď DB nepublikuje.
  **Obnoviť** (vpravo, F5 / Ctrl+R) = načíta znova strom, vlastníkov, počty a zoznam, výber ostane.
  Každých 30 s `Api.check_updates`: nová kópia DB (skener zverejnil) → tlačidlo zmodrie „Nové údaje –
  Obnoviť“; iná `L:\_Lupa\app\version.txt` ako spustená → oranžovo „Nová verzia Lupy – zavri a spusti znova“.
- Strom: klik na zákazníka = súbory všetkých jeho zákaziek; pravé tlačidlo = rozbaliť/zbaliť, otvoriť priečinok.
  Klávesnica (fokus v strome): ↑/↓ posun (súbory po 250 ms), ← zbaliť / na nadradený, → rozbaliť /
  na prvý podriadený, Home/End. Otvorený zákazník sa pri rolovaní drží hore (`.cgroup`, sticky).
- **Dvojklik na súbor = ukázať v strome** (zákazka → priečinok, súbor označený, hľadanie sa vymaže).
  Otvoriť: tlačidlo Otvoriť, dvojklik na náhľad, Enter, pravé tlačidlo (menu: Otvoriť, Ukázať v strome,
  Otvoriť priečinok, Kopírovať cestu/názov, Podobné výkresy, Len vlastník X). Menu cez `showMenu()`.
- **Odkazy .lnk** (z nových zákaziek na staré): skener číta cieľ (`lnk.py`, bez COM, záloha IShellLink)
  do `files.target` (UNC koreňa → `L:\`; '' = nezistiteľný). V zozname „→ cieľ“, dvojklik / „Prejsť
  na cieľ odkazu“ = `Api.locate` → skok v strome (najbližší priečinok, ak presný cieľ v DB nie je).
  Pod nadpisom zákazky (`Api.get_links`, index odkazov v pamäti raz na kópiu DB, cieľ → zákazka
  = najbližší nadradený priečinok, ktorý je zákazkou): **→ Odkazuje na** (staré zákazky; klik = cieľ
  odkazu cez `locate`, cieľ mimo zákaziek sivo „mimo Lupy“) a **← Odkazujú sem** (novšie zákazky;
  klik = samotný odkaz). Číslo, zákazník, rok; novšie prvé, najviac 8. Ikonka reťaze v strome
  pri zákazkách s odkazom ktorýmkoľvek smerom (`jobs[].linked` v `get_tree`).
- Vlastník sa zobrazuje s veľkým začiatočným písmenom (`ownerName`), v DB pôvodný tvar.
- Stĺpce: dátumy bez času (čas v bublinke a v detaile), pravé tlačidlo na hlavičke = zobraziť/skryť
  stĺpce (`lupa.cols.v2`, `lupa.cols.hidden` v localStorage).
- Rozloženie: strom vľavo (~260 px), zoznam v strede, detail vpravo (~360 px).
- Písmo Inter (UI) a JetBrains Mono (názvy súborov, cesty) – ak nie sú offline dostupné, použi `Segoe UI` / `Consolas`.
- Akcentová farba #1d4ed8. Bez emoji v UI, ikony ako inline SVG.
- **Každé okno** si pamätá polohu, veľkosť, maximalizáciu a monitor, kde sa zavrelo (`winstate.attach(window, "<meno>")`,
  uložené v `%LOCALAPPDATA%\Lupa\window.json`). Ak monitor chýba, otvorí sa v predvolenej polohe.
- Panely sú ťahateľné (viditeľný úchyt s bodkami), šírka sa pamätá. Tabuľky sa nezmačkávajú – radšej vodorovný posuvník.
- Hľadanie: viac slov = AND; slovo s `*` / `?` je vzor na celý názov (`cnc_vyk*.pdf`), inak časť názvu.
- Hľadanie čísla (od 3 číslic) otvorí **menu zákaziek a zákazníkov** pod poľom hľadania (`fmenu`):
  presné číslo bez núl a predpony (`324` = `000324` = `OD00000324`) → koniec čísla tak, ako je napísaný
  (`014` = `100014`, nie `1914`) → číslo na začiatku → kdekoľvek; pri rovnakej zhode nové značenie `OD…`
  pred starým (`000324`), potom novšie (`jobs.last_change`); pri zákazke zákazník, rok zmeny + úplnosť,
  najviac 12 položiek, z toho najviac 4 zákazníci (aby ich nevytlačili zákazky). ↑↓ výber, Enter / klik = otvoriť v strome
  (hľadanie sa vymaže), Esc zavrie menu, druhé Esc vymaže hľadanie. Strom sa pri písaní nemení.
  Pozície (podpriečinky) v menu nie sú – opakujú sa.

## Súvisiace nástroje používateľa

Triedič NC (tray app), Nástrojový list, Setup list, TNC sync, NC editor – Lupa sa s nimi zatiaľ neprepája,
neskôr možno (napr. „otvoriť v NC editore“).

## Spôsob práce

- Pred väčšou zmenou krátko popíš plán, potom implementuj.
- Malé kroky, po každom kroku nech sa dá aplikácia spustiť a vyskúšať.
- **Verzia** je v `config.VERSION` (zobrazí sa v UI, menu ikony skenu, logu a vo vlastnostiach exe).
  Pri vydaní novej verzie pre `L:\_Lupa\` ju zvýš a pridaj git tag `vX.Y.Z`.
- `requirements.txt` udržuj aktuálny (pywebview, pywin32, PyMuPDF, numpy, ezdxf, pillow).
- Konfigurácia (cesta k `L:\`, cesta k DB) v `config.py` / `lupa.ini`, nie natvrdo v kóde.
  Vzor: `lupa.ini.example`; lokálny `lupa.ini` (mimo gitu) ukazuje pri vývoji na `vzorky`.
- Pracuj **len v adresári projektu**. Testovacie dáta sú v `vzorky\` (kópia štruktúry `L:\`, **nikdy na git**).
- Python v `.venv` (`.venv\Scripts\python.exe`).
