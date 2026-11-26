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
  z `deploy\` a `lupa.ini.example`. Celý priečinok sa skopíruje na `L:\_Nastroje\lupa\`. Predvolene root = `L:\`,
  DB = `lupa.db` vedľa exe.
  - **Spúšťač**: onedir zo siete nejde (.NET pywebview odmieta DLL zo sieťového disku), onefile je pomalý
    (rozbaľuje sa pri každom štarte). Spúšťač skopíruje `app\` do `%LOCALAPPDATA%\Lupa\app\<verzia>\`
    (len po novej verzii; každá verzia zvlášť, bežiacu nejde prepísať; staré sa zmažú) a spustí ju
    s `LUPA_HOME` = priečinok spúšťača → `config.APP_DIR` (lupa.ini, lupa.db na L:\_Nastroje\lupa).
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
  v `%LOCALAPPDATA%`, spoločné nastavenia sú v `L:\_Nastroje\lupa\lupa.ini`. `--only` filter obchádza.
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

## Stav projektu (aktuálne 1.6.0)

Hotové: verzia 1 (nižšie) + náhľady, galéria, NC/TXT náhľad, kontrola úplnosti, exe, ikona skenu
pri hodinách, stavový riadok, kontextové menu stromu, podobné výkresy, filter zákazníkov v `lupa.ini`,
hľadanie čísla zákazky v strome, typy XLS/DOC zvlášť,
lokálna kópia DB, spúšťač, nové typy, odkazy .lnk, menu zákaziek pod hľadaním (1.3.2).
Vydania = git tagy `v1.0`, `v1.1.0`, `v1.2.0`, `v1.3.0`, `v1.3.1`, `v1.3.2`, `v1.3.3`, `v1.3.4`, `v1.3.6`, `v1.3.7`, `v1.3.9`, `v1.4.0`, `v1.4.1`, `v1.5.0`, `v1.5.1` (pushnuté na GitHub `origin/main`).

**Ostré nasadenie (20.11.2026)**: DB `L:\_Nastroje\lupa\lupa.db` na sieťovom disku (~180 MB).
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
**1.3.7**: Moje filtre (fajka, vypnutie klikom, predvolené upraviteľné), Zoznam/Galéria nad zoznamom
+ Ctrl+G, hľadanie presne nad zoznamom, v detaile len priečinok.
**1.3.8** (len build, vydané v 1.3.9): CNC listy – pravidlo `config.list_sql`
(štítok Listy, PDF = len výkres, filter „Moje CNC listy“ so štítkom „CNC listy ✕“).
**1.3.9**: CNC listy podľa obsahu Wordu / Excelu (skener, `listy.py`, tabuľka `doclists`) – v práci
treba znova `ikona_skenu.bat` (nový skener); kým neprejde dokumenty, platí len meno.
Pozor: po kopírovaní na L:\ zavrieť bežiacu Lupu (aj na lište), inak ostane stará.
Potom u používateľa: `dist\Lupa\` → `L:\_Nastroje\lupa\` (celý priečinok, aj `app\`), na PC so skenerom znova
`ikona_skenu.bat` (nový skener preradí typy, vyhodí skryté súbory, doplní ciele .lnk – bez úplného skenu).
**Umiestnenie (24.11.2026)**: Lupa sa presunula z `L:\_Lupa` do `L:\_Nastroje\lupa` (patrí k NC Nástrojom, launcher ju spúšťa
priamo odtiaľ). Staré odkazy na `L:\_Lupa\Lupa.exe` treba prepísať; `root` v `lupa.ini` je `L:\`, takže skener sa nemení.
Overiť: ciele odkazov .lnk na sieťovom L:\ (lokálne netestovateľné), menu zákaziek pri `324` na ostrých dátach.

**Podobné výkresy** (bod 5): odtlačky v skeneri + UI hotové (tlačidlo v detaile PDF, výsledok
v zozname/galérii so stĺpcom Podobnosť, Esc = späť; `Api.similar`, index v pamäti do zmeny DB).
Slabé miesto: náš `drw0001` ↔ výkres zákazníka (iné rozloženie pohľadov) – neskôr kombinácia s STP.

**1.6.0 (26.11.2026)**: **hľadanie v obsahu NC programov** – samostatné okno (`ui/obsah.html`, tlačidlo `</>` vľavo od
koliesko nastavení, Ctrl+Shift+F, menu stromu „Hľadať v obsahu programov…“ s predvyplneným zákazníkom / zákazkou).
Hľadá **naživo** na disku (`obsah.py`, 6 vlákien, zastaviteľné), nie cez index (NC súbory = ~34 GB). Výber súborov robí DB:
skupiny podľa PRÍPONY (`config.OBSAH_SKUPINY`: Heidenhain `.h`, Sinumerik/Gamma `.mpf .spf`, Gamma GMX `.arc`, Fanuc
`.nd1 .nd2`, Mazak `.eia`, WFL `.wpd`, Edgecam `.nc`), zákazník / zákazka, obdobie zmeny, „len moje“. Pred štartom odhad
(súbory / MB), nad `OBSAH_POTVRDIT_*` potvrdenie; limity `OBSAH_MAX_MB` (súbory väčšie sa preskočia), `OBSAH_MAX_NALEZOV`,
`OBSAH_NA_SUBOR`. Režimy text a regulárny výraz. Okno sa otvára v strede hlavného okna (`winstate.show_centered`; druhé
okno za behu sa vytvára `hidden=True`, lebo `before_show` prebehne skôr, než sa dá napojiť) a zatvorí sa s hlavným oknom.
Testy: `.venv\Scripts\python.exe -m pytest tests` (pytest je len vo vývojovom .venv).

**1.6.1**: nález z hľadania v obsahu sa otvorí **v NC Editore na riadku** (`editor.py`: najnovšia lokálna kópia
`%LOCALAPPDATA%\NC_Nastroje\apps\nc_editor\<verzia>\NCEditor.exe`, argument `cesta:riadok`; riadok len od NC Editora
2026.11.26-11, staršiemu sa cesta dá bez riadka; bez NC Editora sa súbor otvorí predvoleným programom). Enter / dvojklik
v okne hľadania a v kontextovom menu NC súborov „Otvoriť v NC Editore“. Skúšanie s vývojovým NC Editorom:
`LUPA_NC_EDITOR_VERZIA=2026.11.26-11` (nainštalovaný starý exe pošle `cesta:riadok` už bežiacemu vývojovému oknu).

**Ďalšie možné kroky**: STL – v práci ho Windows už ukazuje (doplnok), vlastné netreba.
**Náhľad STP – odložené** (skúška 21.11.2026 mimo projektu): gmsh/OpenCascade načítal STP a rozmery,
ale vykreslil len 17/47 vzoriek (zlyháva sieť trojuholníkov hlavne pri dieloch z Crea, pády,
limity), +86 MB. Ak znova: priamo OpenCascade (`cadquery-ocp`, BRepMesh – spoľahlivejšie, ~+150 MB);
rozmery zo STP by sa hodili k podobným výkresom.

**Rozpracované (23.11.2026)**: náhľady Word / Excel (`dokument.py`, `thumbs.py`) – len lokálne, necommitnuté,
používateľ ich skúša v práci. Návrh na neskôr (neschválený): celá strana Wordu = prvá strana PDF s rovnakým
menom v tom istom priečinku (ak existuje), inak súčasný obrázok; vykresľovanie cez Word COM radšej nie.

**1.4.0 (23.11.2026)**: **stroje zákazky** (`stroje.py`, `Api.get_machines`) – štítky za úplnosťou
(každý stroj raz, bublinka = počet súborov, hlavička, listy). Číta Lupa pri kliknutí na zákazku (cache
v pamäti), nie skener. Zdroje: 1. hlavička NC (prvé 4 kB, riadok `STROJ:`), bez nej znak WFL
(`MACHINE_SIGNS`: `_N_WKS_DIR`, `TLCH1(`) alebo prípona (`.eia` = Mazak, `.wpd` = WFL);
2. meno CNC listu (`MACHINE_NAMES`, Excel aj PDF/Word – pri spore Gmx/Gamma rozhoduje Excel);
3. obsah Excelu (bunka, ktorá sedí na `MACHINES` – „Názov stroja: WFL M40“; viac ako 3 stroje = šablóna);
4. cieľ odkazu .lnk na staré heslo (to isté v cieľovom priečinku, štítok bledý s reťazou).
Skratky `config.MACHINES` (eVo 80, mono H640, mono 840D, DMC 160/105, H530 3x, Kaoming, HPM 450, Gmx,
NTX, J200, IG400, Mazak, WFL); `MACHINE_GENERIC` (Mazak + IG400 = IG400), `MACHINE_SAME_PROGRAM`
(hlavička GMX + listy len Gamma = Gamma). Neznámy stroj = text z hlavičky.
Oprava: riadok odkazov `.links[hidden]` ostával viditeľný pri zákazke bez odkazov.
**Zvonček „Nové zákazky“** (vpravo v hornej lište): `jobs.created` = vytvorenie priečinka zákazky,
`jobs.added_by` = jeho vlastník (skener, len zákazky mladšie ako `NEW_JOBS_OWNER_DAYS` = 60 dní –
GetFileSecurity cez sieť). `Api.get_new_jobs(days)`; menu 1 / 3 / 7 / 14 dní (`lupa.bell.days`),
číslo = nevidené (`lupa.bell.seen` = najnovšia videná, otvorením menu zmizne). Po zverejnení novej DB
sa zvonček načíta hneď. Záložka „Nové“ potrebuje nový skener (`ikona_skenu.bat`).
**1.4.1**: záložka **„Začaté“** (zákazku založí jeden, robí sa neskôr / iný človek):
prvý HMC / PPF / CNC list (`list_sql`) / odkaz .lnk v zákazke vznikol v okne – `files.created`
a `files.owner` toho súboru = kedy a kto robí (`Api._started_jobs`: súbory v okne, potom vylúčiť
zákazky, kde taký súbor vznikol skôr = rozrobené). Ide aj so starou DB. Štítok druhu (HMC / ECAM /
LIST / ODKAZ), klik = zákazka + označený ten súbor, „len moje“ (`lupa.bell.mine`, len pri Začaté),
posledná záložka `lupa.bell.tab`. Číslo na zvončeku = nevidené z oboch záložiek, zákazka raz.
**1.5.2**: oprava druhého štartu Lupy (UI bez CSS/skriptov): pywebview pri `private_mode=False` servíruje UI z pevného portu 42001, druhá Lupa ho nezískala. Teraz je hlavné okno jedinečné (mutex `Local\NC_Lupa_hlavne_okno`, druhý štart len vyvolá okno bežiacej Lupy; výnimka `--hladat` otvorí nové okno) a `_volny_port()` vyberie 42001 alebo, ak je obsadený, voľný port (aj pre okno Nastavenia).
**1.5.1**: parameter príkazového riadku `Lupa.exe --hladat <text>` (z NC Nástrojov: pole zákazky / Hľadať v Lupe) – po načítaní okna
vyplní hľadanie a spustí ho (`Api.get_start`, `start_hladat` v `app.py`, `initApp` v `ui/app.js`). V NC Nástrojoch stačí v `apps.json`
pri `lupa` `"argumenty_hladat": "--hladat {text}"`.
**1.5.0**:
- **Vnorené zákazky** (Rejlek: `ON000` = staré číslo zákazníka, skutočná zákazka `00055`, diely
  `101UP7`) – plán A bez zásahu do skenera: stroje za vybraný priečinok s podpriečinkami
  (`get_machines(job_id, rel)`), pri podpriečinku riadok „V priečinku X:“ s úplnosťou (`_dir_missing`:
  podstrom + súbory priamo v nadradených priečinkoch). Úplnosť zákazky ostáva za celú zákazku.
  Plán B (zákazka o úroveň hlbšie podľa ini) používateľ nechce.
- **O programe** (klik na „Lupa“ vľavo hore): verzia, autor Jozef Duchoň, Claude (Anthropic), cesty,
  Kopírovať údaje.
- **Okno Nastavenia** (`nastavenia.py`, `ui/nastavenia.html/.js/.css`, `SettingsApi` v app.py):
  koliesko v Lupe (druhé okno) alebo ikona skenu „Nastavenia…“ = `Lupa.exe --nastavenia` (len okno).
  Edituje `config.INI_PATH` (= `L:\_Nastroje\lupa\lupa.ini`, spoločné): uloží len zmenené, komentáre ostanú,
  záloha `lupa.ini.bak`. Meniť smie `spravca` (mená Windows) alebo ikona skenu; inak len na čítanie
  (ochrana pred omylom, nie zabezpečenie). Nové kľúče: `scan_minutes` (ikona skenu, platí od ďalšieho
  skenu), `zvoncek_dni`, `spravca`. Pravidlá strojov v `[stroje]` / `[stroje_listy]` (skratka = výraz,
  poradie = priorita; bez sekcie `config.DEFAULT_MACHINES` / `DEFAULT_MACHINE_NAMES`), v okne riadky
  s ↑↓✕, Predvolené a „Vyskúšať“ (JS RegExp). Lupa číta nastavenia pri štarte (zmena = reštart).

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
   **Word / Excel** (`dokument.py`): náhľad = obrázok vložený v dokumente (CNC listy majú fotky upnutia
   a snímky z CAM). .docx/.xlsx z ZIP-u (`media/`), staré .doc/.xls – PNG/JPEG nájdené v súbore (JPEG:
   prvý dekódovateľný koniec FF D9). Vyberie sa obrázok s najviac farebného modelu (logo – široký nízky –
   a ikony von); snímka obrazovky sa oreže na model: najväčšia svetlá jednoliata plocha (políčka 12 px)
   = 3D okno CAM-u, v nej najväčší zhluk (+15 % okraj). Vo Worde je orez len nastavenie, súbor má celú
   snímku (aj 2 monitory 3840×1080) – tá sa skúša aj **po monitoroch** (model býva len na jednom);
   neorezaný monitor / celá snímka majú malú váhu (0,15 / 0,1). Do skóre sa nepočíta „systémová“ modrá
   (plocha Windows, panely Wordu: R < 70, B − R > 80) – inak by vyhrala plocha s kalkulačkou.
   Výrez: `set_origin(0, 0)`, inak ďalší orez / zmenšenie číta mimo (šum). Vzorky: model/nákres 40/46,
   snímka obrazovky bez modelu → ikona (4), hlavička listu na stránke Wordu ostáva (3, od nákresu na
   bielom sa nedá odlíšiť); ~0,65 s na dokument (najviac 1,8 s),
   potom cache (kľúč `o3`). Bez obrázka → ikona z Windows.
2. ✅ **Galéria** – mriežka náhľadov, posuvník veľkosti, triedenie.
3. ✅ Kontrola **úplnosti zákazky** (Model / PDF / CAM / NC / Listy) – stav v strome + štítky.
   **CNC list** (`listy.py` – jedno pravidlo pre skener, Lupu aj `skuska_listy.py`; štítok Listy aj
   filter „Moje CNC listy“): 1. meno `listy_mena` (`*cnc*, *prog*list*, *pgm*list*, *poloha*`) – Word,
   Excel aj PDF; 2. PDF v priečinku `listy_priecinky` (`*cnc*list*`); 3. Word / Excel s nejasným menom
   podľa **obsahu**: cesta `R:\priečinok\…` (NC programy na serveri) alebo aspoň 2 slová z `listy_obsah`
   (Programátor:, CESTA:, Názov stroja, Výrobný príkaz:, Artikel:, Výkres:, Program-číslo: – sústruh).
   Priečinok „CNC listy“ o Worde / Exceli nerozhoduje (nástrojové listy, náčrty). Prídavky
   (`upnutie na magnet.docx`) a poznámky (`CITAJ.doc`) listom nie sú. Takéto PDF sa do „PDF“ nepočíta.
   Obsah číta **skener** (`update_doclists`, pred odtlačkami, `listy_minutes` min na sken, najnovšie
   prvé) do tabuľky `doclists` (cesta, veľkosť, zmenený, verzia = algoritmus + slová z ini, is_list, why);
   staré .doc len prvých 256 kB (text je na začiatku, za ním fotky), .xls 8 MB; UTF-16 aj s č/Č/ď/Ď
   (dolný bajt 0x0C–0x0F – chyba v skúške). Lupa: SQL `listy.list_sql` – meno, inak `doclists`
   (sedí veľkosť + zmenený; verziu nekontroluje), stará DB bez tabuľky = len meno.
   Skúška (`skuska_listy.exe`, 11/2026): Kuka 1120 dok., Bühler 2333, Rejlek 1291, Nedschroef 1085 –
   ~80 % podľa mena, 5–10 % podľa obsahu; za 14–80 s na zákazníka cez sieť.
   „Moje CNC listy“ = ja · CNC listy · celé L:\ · galéria (starý predvolený `cnc_vyk*.pdf` sa nahradí).
   Na lište filtrov tlačidlo nie je – zapína sa filtrom alebo položkou „Len CNC listy“ (fajka) v menu
   Moje filtre; keď je zapnuté, nad zoznamom je štítok
   „CNC listy ✕“ (klik = vypnúť). Hľadanie to nenahradí: len meno (nie priečinok), slová = AND.
4. ✅ Exe na `L:\_Nastroje\lupa\` (`build.py`) + ikona skenu pri hodinách (namiesto Plánovača úloh).
5. ✅ **Nájdi podobné výkresy** – offline obrazové „odtlačky“ PDF (orezať rám a pečiatku), neskôr kombinácia s rozmermi zo STP.
   Metóda: list → pohľady (zhluky čiar) → mriežka 16×16, porovnanie v 8 symetriách, slabší z oboch smerov.
   Na vzorkách: rovnaký výkres / sken / revízia = 1. miesto; náš `drw0001` ↔ výkres zákazníka zatiaľ slabé.

## Vzhľad

Schválený návrh UI (maketa): https://claude.ai/artifact/MHEAKvNtdfXvU9EaucAA1w

- Tmavá horná lišta (#111827): vľavo „Lupa“, **hľadanie presne nad zoznamom** (stredný panel –
  od `--tree-w` po `--detail-w`, naťahuje sa s panelmi; menu zákaziek pod ním, aspoň 460 px). Prepínač Zoznam / Galéria = ikonky nad
  zoznamom vpravo pri počte súborov (Ctrl+G prepína). Verzia v názve okna („Lupa 1.2.0“).
- Biela lišta filtrov pod ňou (vlastník ako štítok, chipy typov, všetky/žiadne, rozsah).
- **Moje filtre** (tlačidlo vľavo v lište filtrov): nastavia naraz vlastníka, typy, hľadanie, rozsah a
  zoznam/galériu. Predvolené „Moje programy“ (ja · HMC + ECAM · celé L:\ · galéria) a „Moje CNC listy“
  (ja · PDF · `cnc_vyk*.pdf` · celé L:\ · galéria); „ja“ = prihlásený používateľ Windows
  (`Api.whoami` → jeho tvar vo `files.owner`). Predvolené sú len počiatočný stav (dajú sa prepísať / zmazať, „Obnoviť predvolené
  filtre“ vráti chýbajúce). Uložiť aktuálny filter…, Prepísať filter aktuálnym…, Zmazať filter… –
  len v tomto PC (`lupa.views` v localStorage). Aktívny filter (zhoda vlastníka, typov, hľadania
  a rozsahu – `sameView`) má v menu fajku a jeho meno je na tlačidle; klik naň ho vypne (všetci,
  všetky typy, bez hľadania; rozsah a zobrazenie ako pred zapnutím). Hlavný spôsob práce: nájsť svoj podobný kus.
- Detail súboru: pod názvom len priečinok (celá cesta v bublinke).
- **Zarovnanie**: filtre začínajú nad zoznamom súborov – ľavý stĺpec má šírku stromu
  (CSS premenná `--tree-w`, mení ju ťahanie); hľadanie končí nad detailom (`--detail-w`). Nad stromom: „Zákazníci“ + Rozbaliť/Zbaliť všetko.
- **Stavový riadok** dole (nenápadný): vľavo koreň + počty z DB, vpravo „Posledný sken“
  (oranžovo, ak je starší ako 24 h). Čas skenu z `lupa_scan.json` vedľa DB – skener ho zapisuje
  pri každom skene, aj keď DB nepublikuje.
  **Obnoviť** (vpravo, F5 / Ctrl+R) = načíta znova strom, vlastníkov, počty a zoznam, výber ostane.
  Každých 30 s `Api.check_updates`: nová kópia DB (skener zverejnil) → tlačidlo zmodrie „Nové údaje –
  Obnoviť“; iná `L:\_Nastroje\lupa\app\version.txt` ako spustená → oranžovo „Nová verzia Lupy – zavri a spusti znova“.
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
  Pri vydaní novej verzie pre `L:\_Nastroje\lupa\` ju zvýš a pridaj git tag `vX.Y.Z`.
- `requirements.txt` udržuj aktuálny (pywebview, pywin32, PyMuPDF, numpy, ezdxf, pillow).
- Konfigurácia (cesta k `L:\`, cesta k DB) v `config.py` / `lupa.ini`, nie natvrdo v kóde.
  Vzor: `lupa.ini.example`; lokálny `lupa.ini` (mimo gitu) ukazuje pri vývoji na `vzorky`.
- Pracuj **len v adresári projektu**. Testovacie dáta sú v `vzorky\` (kópia štruktúry `L:\`, **nikdy na git**).
- Python v `.venv` (`.venv\Scripts\python.exe`).
