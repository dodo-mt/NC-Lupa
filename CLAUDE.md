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
- **Skener preskakuje** (zoznamy v `config.py`): priečinky `POF\`, `VNC\`, `STOCK\`, `3DF\` (interné dáta hyperMILL),
  súbory `Thumbs.db`, `desktop.ini`, prípony `.bak .hmc_bak .hyperMILL .dwl .dwl2 .log .tmp`.
- NC programy bývajú v podpriečinku `NC\` (triedené po strojoch: eVo 80, monoBLOCK H640, DMC 160, monoBLOCK 840D).
- Rádovo **tisíce zákaziek**, pribúda pár denne.

## Typy súborov a farby

| Typ | Prípony | Farba (pozadie / text) |
|-----|---------|------------------------|
| PDF – výkres | .pdf | #fee2e2 / #7f1d1d |
| STP – model | .stp .step | #dbeafe / #1e3a8a |
| HMC – hyperMILL | .hmc | #ffedd5 / #7c2d12 |
| PPF – hyperMILL | .ppf | #fef3c7 / #78350f |
| NC – programy | .h .nc .mpf .spf | #dcfce7 / #14532d |
| XLS – listy | .xlsx .xls .doc .docx | #ccfbf1 / #134e4a |
| CREO – Creo | .prt.N .drw.N .asm.N (N = verzia, berie sa len najvyššia v priečinku) | #f9ded3 / #8a3517 |
| Ostatné | * | #f3f4f6 / #374151 |

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
  - Spúšťanie z príkazového riadka (neskôr cez Plánovač úloh): `python scanner.py --root L:\ --db <cesta> [--full] [--only "Zákazník"]`.
- **Aplikácia** (`app.py`): **pywebview** okno s HTML/CSS/JS rozhraním (nie prehliadač, nie server).
  - Python strana vystavuje API cez `js_api` (hľadanie, filtre, strom, otvorenie súboru).
  - Dvojklik na súbor → `os.startfile(cesta)` (otvorí v hyperMILL, Creo, PDF prehliadači…).
  - Databázu otvára **len na čítanie** (`file:...?mode=ro`, `uri=True`).
- **UI** (`ui/index.html`, `ui/style.css`, `ui/app.js`): čisté HTML/CSS/JS, bez frameworkov a buildov.
- Neskôr balenie do jedného exe cez **PyInstaller**, umiestnené na `L:\_Lupa\` pre kolegov.

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
```

- Indexy: `files(name)`, `files(owner)`, `files(ftype)`, `files(modified)`.
- Hľadanie podľa časti názvu: `LIKE '%…%'` (pri raste zvážiť FTS5).
- Odhad veľkosti: ~150 000 súborov → desiatky MB.

## Verzia 1 – rozsah (robíme TERAZ)

1. Skener + databáza, test najprv na **jednom zákazníkovi** (`--only`).
2. Okno: strom zákazník → zákazka → pozícia (vľavo).
3. Zoznam súborov zafarbený podľa typu: typ, názov, vlastník, vytvorený, zmenený, veľkosť; triedenie klikom na hlavičku.
4. Hľadanie podľa časti názvu (napr. číslo výkresu) – živé, počas písania, naprieč celým `L:\` aj v aktuálnej zákazke.
5. Filtre: vlastník, typ (farebné „chipy“), rozsah *Aktuálna zákazka / Celé L:\*.
6. Dvojklik → otvoriť súbor. Tlačidlo „Otvoriť priečinok“.

## Neskôr (postupne, každé zvlášť, až keď v1 funguje)

1. Pravý panel s detailom a **náhľadmi** (PDF cez PyMuPDF; ostatné cez Windows shell náhľady `IShellItemImageFactory`), cache náhľadov lokálne v `%LOCALAPPDATA%\Lupa\thumbs`.
2. **Galéria** – mriežka veľkých náhľadov (napr. „moje PDF za posledné 2 roky“), posuvník veľkosti.
3. Kontrola **úplnosti pozície** (STP / PDF / HMC / NC / listy) – ikonky v strome.
4. Exe na `L:\_Lupa\`, nočný sken cez Plánovač úloh.
5. **Nájdi podobné výkresy** – offline obrazové „odtlačky“ PDF (orezať rám a pečiatku), neskôr kombinácia s rozmermi zo STP.

## Vzhľad

Schválený návrh UI (maketa): https://claude.ai/artifact/MHEAKvNtdfXvU9EaucAA1w

- Tmavá horná lišta (#111827) s názvom „Lupa“, hľadaním a prepínačom Zoznam / Galéria.
- Biela lišta filtrov pod ňou.
- Rozloženie: strom vľavo (~260 px), zoznam v strede, detail vpravo (~360 px).
- Písmo Inter (UI) a JetBrains Mono (názvy súborov, cesty) – ak nie sú offline dostupné, použi `Segoe UI` / `Consolas`.
- Akcentová farba #1d4ed8. Bez emoji v UI, ikony ako inline SVG.

## Súvisiace nástroje používateľa

Triedič NC (tray app), Nástrojový list, Setup list, TNC sync, NC editor – Lupa sa s nimi zatiaľ neprepája,
neskôr možno (napr. „otvoriť v NC editore“).

## Spôsob práce

- Pred väčšou zmenou krátko popíš plán, potom implementuj.
- Malé kroky, po každom kroku nech sa dá aplikácia spustiť a vyskúšať.
- `requirements.txt` udržuj aktuálny (pywebview, pywin32; neskôr PyMuPDF).
- Konfigurácia (cesta k `L:\`, cesta k DB) v `config.py` / `lupa.ini`, nie natvrdo v kóde.
  Vzor: `lupa.ini.example`; lokálny `lupa.ini` (mimo gitu) ukazuje pri vývoji na `vzorky`.
- Pracuj **len v adresári projektu**. Testovacie dáta sú v `vzorky\` (kópia štruktúry `L:\`, **nikdy na git**).
- Python v `.venv` (`.venv\Scripts\python.exe`).
