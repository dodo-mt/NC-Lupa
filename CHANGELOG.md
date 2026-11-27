# CHANGELOG – História verzií Lupy

Presunuté z CLAUDE.md bez zmeny textu, od najnovšej verzie. Aktuálna verzia je v `config.VERSION`.

**1.17.1**: **pravidlá strojov mimo hlavičky programu sú tiež zo stroje.json** (polia modelu, editor Súbor → Stroje v NC Nástrojoch): mená CNC listov (`gamma`, `gmx`, `mazak`, `wfl`…), znaky v obsahu programu (WFL), prípony, ktoré samy určujú stroj (`.eia`, `.wpd`), „rovnaký program“ (GMX → Gamma) a „všeobecný stroj“ (Mazak → J200, IG400). Správanie bez zmeny (porovnanie so starým výstupom: hlavičky, stroje zákaziek aj kombinácie listov zhodné); `[stroje_listy]` v `lupa.ini` ich ďalej prepíše. Súbor stroje.json zo staršej verzie treba doplniť (`nc_parsery.stroje.dopln_pravidla_lupy`), inak Lupa tieto pravidlá nemá.

**1.17.0**: **zoznam strojov zo spoločného `stroje.json`** (krok 5, `nc_parsery.stroje`; `L:\_Nastroje\Nastavenia\stroje.json`, bez neho lokálna kópia v `%LOCALAPPDATA%\Lupa`, inak vstavané predvolené hodnoty): predvolené pravidlá `[stroje]` (text za `STROJ:` → skratka) sa berú z modelov, `[stroje]` v `lupa.ini` ich ďalej prepíše. **Zmena správania:** `3x-HH` je skratka `3X H530` (predtým `H530 3x`), `monoBLOCK 3X` je `mono 3X` (predtým `mono H640`; model patrí do skupiny monoBLOCK H640), Kondia má vlastnú skratku, nové rozpoznanie `DMC 60` (aj `DMU 60 U` z Edgecamu) a `eVo 60` zo zápisu bez `DMU`. Ostatné (hlavičky, stroje na 19 vzorkách) bez zmeny. Pravidlá mien listov, Gmx/Gamma a Mazak ostávajú v `config.py`.

**1.16.2**: interná zmena bez zmeny správania: **parser nástrojov (`nastroje.py`), dekódovanie kódov nástrojov (`kod_nastroja.py`), čítanie riadku `STROJ:` a `dekoduj` sú presunuté do spoločného balíka `nc_parsery`** (priečinok `NC parsery` vedľa projektu, GitHub `dodo-mt/nc-parsery`; testy parsera sú tam). Lupa ho pridáva do `sys.path` cez `nc_parsery_cesta.py`, `build.py` pridáva `--paths`. V Lupe ostáva `zostav_text` (text Nástrojového listu) a testy API.

**1.16.1**: **nástroje z NTX** (Fanuc 31i, `.nd1` / `.nd2`): výmena `G0T05125505(platkovy vrtak D25 INGERSOLL-5D - NEPOHANANY)` – kód a názov v zátvorke, bez M6; predvoľba ďalšieho nástroja `G0T02105505(G0 T00000000)` (a `(G0 T…)` na samostatnom riadku) sa nepočíta. Priemer sa berie z kódu nástroja (odladený program je záväzný, poznámka z CAMu sa môže líšiť); priemer z názvu (`D10`) slúži len ako záloha, keď kód priemer nenesie (nože). Známa nejednoznačnosť: v kóde frézy sa desatiny nepoužívajú (`TK freza D2.5` má kód `40102505` = 25 mm). Na vzorke `7504.nd1`: 6 nástrojov, 8 volaní; 3 nové testy (61 spolu).

**1.16.0**: **rozpoznávanie nástrojov pre sústruhy a Mazak** (detail súboru aj zoznam nástrojov zákazky, `nastroje.py`): (1) **archív `.WPD`** (textový archív Siemens z CAM, WFL): volania `TLCH1("kód",…)`, názov z komentára za volaním, inak zo zoznamu `;  N10 - kód - názov` v hlavičke; M6 sa nehľadá. (2) **GMX / Gamma**: výmena nástroja `TC(…)` sa berie ako M6 (doteraz tieto programy ukázali 0 nástrojov), názov z komentára `;T00-neutralny noz 55st` tesne nad `T="kód"`. (3) **Mazak `.EIA`**: názvy zo zoznamu v hlavičke `( N10 | T73020801 | názov )` aj `(  N10 - 01103104 - názov )`. (4) **Priemer / polomer z kódovacej tabuľky** (nový `kod_nastroja.py`, podľa `kodovanie_viena.xls`): z osemmiestneho kódu nástroja sa doplní chýbajúci priemer (vŕtanie a závitníky v desatinách mm, frézy v celých mm) alebo polomer plátku (sústružnícke nože; rádiusové frézy `5A`…`6P` podľa písmena); chýbajúci názov alebo názov rovný kódu nahradí názov typu. Koncovka stroja (01 GMX, 02 Gamma, 03 WFL, 04 Mazak) sa nepoužíva (pri novších Mazak programoch je nespoľahlivá); typy 90 a 95 sa prekrývajú a nedekódujú sa, pri závitových nožoch a valčekovaní sa dekóduje len názov typu. Overené na skutočných vzorkách (`.WPD` 3 / 21 / 11 nástrojov, GMX `.ARC` 8, Gamma `.SPF`, Mazak `.EIA`; počet volaní `TLCH1` sedí); 6 nových testov (58 spolu).

**1.15.2**: (1) **okno Nastavenia sa otvára vycentrované v strede hlavného okna Lupy** (rovnako ako okno hľadania v obsahu; `create_settings_window(parent=…)`, veľkosť sa pamätá; pri štarte z ikony skenu `Lupa.exe --nastavenia` bez hlavného okna ostáva poloha ako doteraz). (2) **Oprava rozbitej diakritiky v `config.py`** (73 riadkov bolo uložených dvojito prekódovaných – `rozloĹľenĂ©` namiesto `rozložené`): opravené názvy skupín v okne Hľadať v obsahu („Gamma GMX archív“, „Edgecam (všeobecné)“…), popisy typov súborov a komentáre; kód sa nezmenil (porovnané tokeny pôvodného a nového súboru, 50 testov prechádza). Overené na vzorkách `.WPD`: súbory `OD…_1UP.WPD` sú textový archív Siemens (`%_N_…_MPF`, `;$PATH=/_N_WKS_DIR/…_WPD`, výmena nástroja `TLCH1(…)`, bez riadku `STROJ:`), takže `wpd` v typoch NC, skupina WFL v hľadaní v obsahu aj rozpoznanie stroja podľa obsahu ostávajú správne.

**1.15.1**: v riadku „Odkazuje na / Odkazujú sem“ je rok pri zákazke popísaný („OD684 **z roku 2018**“ namiesto samotného „2018“);
tooltip ukáže dátum poslednej zmeny v zákazke.

**1.15.0**: (1) **stĺpec „Odladený“** v zozname súborov (zelené „✓ odladený“ / sivé „neodladený“ pri NC, dá sa zoradiť a skryť; značka pri
názve zmizla); (2) **filter „Zákazky bez odladeného programu…“** v menu Moje filtre (strom ukáže len zákazky s NC programami bez
odladeného, voliteľne len zmenené za 1 / 3 / 6 / 12 mesiacov alebo všetky; štítok „Bez odladeného · N mes. ✕“ nad stromom;
len zobrazenie stromu, neukladá sa; na ostrej DB 28 921 zákaziek, 831 za 3 mesiace); (3) **dátum posledného odladeného programu** v
tooltipe značky pri zákazke aj v hlavičke (`get_tree`: `odl_cas`).

**1.14.0**: za odladený sa berie aj priečinok **„Zo stroja“** (predvolené `odladene_priecinky` = `odlad*, zo*stroja*`; sedí na `ZO STROJA`,
`zo stroja`, `zo stroja dmc80`, `ZO_STROJA` …). Na ostrej DB: zákaziek s odladeným programom 2852 → 3396, odladených NC súborov
10 693 → 20 176. Platí všade (filter, štítky, nástrojový list, porovnanie s odladenou verziou). Vlastný vzor v `lupa.ini` ho prepíše.

**1.13.2**: štítok „Odladené“ v hlavičke zákazky je hneď **za štítkami úplnosti** (Model, PDF, CAM, NC, Listy) a má ich tvar (4 px, 12/600):
zelený „✓ Odladené 8“ (klik = filter odladených programov, zapnutý = plne zelený), **sivý „Odladené 0“** pri zákazke s NC programami bez
odladeného (`Api.get_tree`: `has_nc`), bez NC programov sa nezobrazí.

**1.13.1**: oprava štítkov strojov: regulárny výraz `STROJ:` sedel aj na konci slova `Nastroj:` (nástrojový list `Nastroje.nc` z hyperMILLu
má riadky `* Nastroj: T3025   - FRE-D50-PL-S`), takže pri zákazke vznikol falošný „stroj“ s textom nástroja. `STROJ:` je teraz
samostatné slovo (`stroje._STROJ`, test `tests/test_stroje.py`).

**1.13.0**: **rýchly náhľad (Medzerník) aj pre obrázky a skeny** (typ OBR; PyMuPDF zmenší na `nahlad.SIRKA_OBRAZKA` = 1600 px, viacstranové TIFF
sa listujú ← →; webp / heic cez náhľad z Windows, inak správa) a **značka „odladené“ v hlavičke zákazky** (štítok s počtom odladených
NC programov; klik zapne / vypne filter odladených; `Api._odladene_jobs` teraz vracia {zákazka: počet}, počet je aj v tooltipe značky
v strome). `get_doc_preview` už nikdy nevyhodí výnimku.

**1.12.0**: **rýchly náhľad (Medzerník) aj pre PDF, Word a Excel** (`nahlad.py`, `Api.get_doc_preview`): PDF = strany ako obrázok
(← → strany), .docx/.docm = odseky a tabuľky (text z XML), .xlsx/.xlsm = tabuľka listu (← → listy, najviac 300 × 40), starý .doc/.xls =
náhľad z Windows, ak existuje (všeobecná ikona sa nepočíta), inak správa. Bez Office, bez nových knižníc. **↑ ↓ v náhľade = ďalší /
predchádzajúci súbor v zozname** (preskočí typy bez náhľadu, výber v zozname ide s ním). Overené na ostrých súboroch (PDF, docx, xlsx).

**1.11.0**: **Porovnať s odladenou verziou** (kontextové menu NC súboru mimo priečinka odlad*, `Api.compare_with_debugged`: v tej istej
zákazke program s rovnakým menom, inak rovnakým menom bez prípony, v priečinku odlad*; viac nálezov = výber; porovnanie v NC Editore
A = tento, B = odladený) a **Medzerník v okne hľadania v obsahu** (rýchly náhľad okna `QUICK_LINES` riadkov okolo nálezu so
zvýraznením nálezu a hľadaného textu, `ObsahApi.preview`, `Api.get_text_preview(file_id, line)` číta celý súbor do `OBSAH_MAX_MB`).

**1.10.0**: **zoznam nástrojov zákazky / priečinka (Nástrojový list)**: pravý klik na zákazku alebo priečinok v strome → „Zoznam
nástrojov…“ (`Api.tools_list_estimate` / `tools_list_build`, `nastroje.zostav_text`, najviac `TL_MAX_SUBOROV` = 400 programov, čítanie
vo vláknach). Text: `Nástrojový list`, zarovnaná hlavička (Zákazník, Zákazka, [Priečinok], Programy, Dátum), prázdny riadok a programy;
pod programom riadok na nástroj `T<číslo>  <názov>` (Siemens bez čísla len názov), poradie = prvé volanie. Predvolene len odladené
programy, ak ich zákazka má (prepínač v okne). Výstup: Uložiť ako text (dialóg, predvolene Plocha, súbor sa otvorí; `Api.save_text_file`,
UTF-8 s BOM), Vytlačiť (`window.print()` + tlačový štýl, A4), Kopírovať. Overené na ostrej DB (zákazka s odladenými programami).

**1.9.1**: tlačidlo **Moje filtre svieti na modro** aj pri zapnutej maske (Len CNC listy / Len odladené programy) – text „CNC listy“,
„Odladené“ alebo „CNC listy · Odladené“, tooltip vysvetlí; v menu pribudla položka „Vypnúť všetky masky“.

**1.9.0**: **značka „odladené“ pri zákazke v strome** (zelená fajka; zákazka s NC súborom v priečinku odlad*, `Api._odladene_jobs`,
jeden dopyt pri načítaní stromu; klik na značku vyberie zákazku a zapne filter odladených programov – na ostrej DB 2852 zákaziek)
a **rýchly náhľad textu na Medzerník** (NC program a txt, `Api.get_text_preview`, prvých 5000 riadkov, čísla riadkov, komentáre sivo,
kľúčové slová tučne, Medzerník / Esc zavrie; tlačidlo Otvoriť v NC Editore). Textový náhľad z detailu súboru zmizol (ostáva
náhľad PDF a obrázkov); galéria bez zmeny. Značka sa v hlavičke zákazky zatiaľ nezobrazuje, len v strome.

**1.8.0**: **odladené programy** (`odladene.py`, `config.ODLADENE`, lupa.ini `odladene_priecinky`, predvolene `odlad*`): odladený =
NC súbor v priečinku `odlad*` kdekoľvek pod zákazkou / pozíciou (pred aj za ďalšími priečinkami; `neodladene` nie je odladený;
hlavička `ODLADOVAL` sa nepoužíva – vypĺňa sa zriedka). Filter „Len odladené programy“ v menu Moje filtre (štítok „Odladené ✕“,
ukladá sa s filtrom), políčko v okne hľadania v obsahu (zúži výber pred čítaním), zelená značka „odladený“ pri NC súboroch
v zozname a riadok Stav v detaile. Hotové: A. Naplánované: B – zoznam nástrojov zákazky / priečinka (pravý klik v strome, text:
hlavička „Nástrojový list“, prázdny riadok, potom programy a v každom riadku číslo nástroja + názov; výstup text aj tlač).

**1.7.0**: **nástroje NC programu v detaile súboru** (`nastroje.py`, `Api.get_tools`, sekcia „Nástroje programu“ pod
tlačidlami): rozpoznanie podľa obsahu – Heidenhain (`TOOL CALL`, názov z komentára tesne NAD volaním `; (Nastroj: NÁZOV | … | L=… LL=…)` (name končí pri ` | ` alebo ` L=`),
inak z `;  (NÁZOV)` za volaním, D/r/Lc/L z hlavičkových
komentárov `; T2965 D50 r2.5 Lc8.7 L40 - NÁZOV`, `TOOL DEF` sa nepočíta; L / LL aj z komentára `Nastroj:`), Sinumerik z hyperMILLu
(rovnaký komentár `Nastroj:` nad `T="NÁZOV"` + `M6` do 4 riadkov; číslo T a R/R2/LCUT z hlavičky `; T933 NÁZOV | R=2.5 R2=0. LCUT=35`
alebo z textu operácie `GROUP_BEGIN(0,"1590 : T933 M6 - …")`; texty v úvodzovkách sa pri hľadaní volania ignorujú, inak by
`MSG ("T933 M6")` dalo falošný nástroj), Fanuc/Mazak (`T73020801 … M6`, bez výkladu čísla). Tabuľka T / názov / rozmery / počet
volaní, klik = NC Editor na prvom volaní. Súbory nad `OBSAH_MAX_MB` (**50 MB**, od 1.7.1; platí aj pre hľadanie v obsahu) sa
nečítajú. Vzory: anonymizované programy v NC Editore (`tests/data`, `vzorky`). NTX (`fanuc_ntx.nc`) zatiaľ nič nenájde.

**1.6.3**: **porovnanie dvoch NC programov v NC Editore** – Ctrl+klik označí súbor (A, potom B; tretí nahradí najstarší,
fialový pásik a písmeno), pravé tlačidlo na NC súbore → „Porovnať označené“ / „Porovnať s označeným“ (zoznam aj galéria);
v okne hľadania v obsahu Ctrl+klik na dva nálezy + tlačidlo „Porovnať v NC Editore“ (kurzor sa nastaví na nájdené riadky).
`editor.otvor_porovnanie` spustí `NCEditor.exe --porovnaj A B` (od NC Editora 2026.11.26-12; staršiemu sa nič nepošle),
rôzne prípony = len upozornenie. `Api.compare_in_editor`. Skúšanie: `LUPA_NC_EDITOR_VERZIA=2026.11.26-12` + vývojový NC Editor.

**1.6.2**: **kontext nálezu** – pod zoznamom nálezov panel s ±5 riadkami okolo vybraného nálezu (`ObsahApi.context`,
`obsah.kontext`; posledný prečítaný súbor v pamäti, nálezy v ňom sú hneď; zvýraznený nález a ostatné zhody).

**1.6.1**: nález z hľadania v obsahu sa otvorí **v NC Editore na riadku** (`editor.py`: najnovšia lokálna kópia
`%LOCALAPPDATA%\NC_Nastroje\apps\nc_editor\<verzia>\NCEditor.exe`, argument `cesta:riadok`; riadok len od NC Editora
2026.11.26-11, staršiemu sa cesta dá bez riadka; bez NC Editora sa súbor otvorí predvoleným programom). Enter / dvojklik
v okne hľadania a v kontextovom menu NC súborov „Otvoriť v NC Editore“. Skúšanie s vývojovým NC Editorom:
`LUPA_NC_EDITOR_VERZIA=2026.11.26-11` (nainštalovaný starý exe pošle `cesta:riadok` už bežiacemu vývojovému oknu).

**1.6.0 (26.11.2026)**: **hľadanie v obsahu NC programov** – samostatné okno (`ui/obsah.html`, tlačidlo `</>` vľavo od
koliesko nastavení, Ctrl+Shift+F, menu stromu „Hľadať v obsahu programov…“ s predvyplneným zákazníkom / zákazkou).
Hľadá **naživo** na disku (`obsah.py`, 6 vlákien, zastaviteľné), nie cez index (NC súbory = ~34 GB). Výber súborov robí DB:
skupiny podľa PRÍPONY (`config.OBSAH_SKUPINY`: Heidenhain `.h`, Sinumerik/Gamma `.mpf .spf`, Gamma GMX `.arc`, Fanuc
`.nd1 .nd2`, Mazak `.eia`, WFL `.wpd`, Edgecam `.nc`), zákazník / zákazka, obdobie zmeny, „len moje“. Pred štartom odhad
(súbory / MB), nad `OBSAH_POTVRDIT_*` potvrdenie; limity `OBSAH_MAX_MB` (súbory väčšie sa preskočia), `OBSAH_MAX_NALEZOV`,
`OBSAH_NA_SUBOR`. Režimy text a regulárny výraz. Okno sa otvára v strede hlavného okna (`winstate.show_centered`; druhé
okno za behu sa vytvára `hidden=True`, lebo `before_show` prebehne skôr, než sa dá napojiť) a zatvorí sa s hlavným oknom.
Testy: `.venv\Scripts\python.exe -m pytest tests` (pytest je len vo vývojovom .venv).

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

**1.4.1**: záložka **„Začaté“** (zákazku založí jeden, robí sa neskôr / iný človek):
prvý HMC / PPF / CNC list (`list_sql`) / odkaz .lnk v zákazke vznikol v okne – `files.created`
a `files.owner` toho súboru = kedy a kto robí (`Api._started_jobs`: súbory v okne, potom vylúčiť
zákazky, kde taký súbor vznikol skôr = rozrobené). Ide aj so starou DB. Štítok druhu (HMC / ECAM /
LIST / ODKAZ), klik = zákazka + označený ten súbor, „len moje“ (`lupa.bell.mine`, len pri Začaté),
posledná záložka `lupa.bell.tab`. Číslo na zvončeku = nevidené z oboch záložiek, zákazka raz.

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

**Umiestnenie (24.11.2026)**: Lupa sa presunula z `L:\_Lupa` do `L:\_Nastroje\lupa` (patrí k NC Nástrojom, launcher ju spúšťa
priamo odtiaľ). Staré odkazy na `L:\_Lupa\Lupa.exe` treba prepísať; `root` v `lupa.ini` je `L:\`, takže skener sa nemení.
Overiť: ciele odkazov .lnk na sieťovom L:\ (lokálne netestovateľné), menu zákaziek pri `324` na ostrých dátach.

**1.3.9**: CNC listy podľa obsahu Wordu / Excelu (skener, `listy.py`, tabuľka `doclists`) – v práci
treba znova `ikona_skenu.bat` (nový skener); kým neprejde dokumenty, platí len meno.
Pozor: po kopírovaní na L:\ zavrieť bežiacu Lupu (aj na lište), inak ostane stará.
Potom u používateľa: `dist\Lupa\` → `L:\_Nastroje\lupa\` (celý priečinok, aj `app\`), na PC so skenerom znova
`ikona_skenu.bat` (nový skener preradí typy, vyhodí skryté súbory, doplní ciele .lnk – bez úplného skenu).

**1.3.8** (len build, vydané v 1.3.9): CNC listy – pravidlo `config.list_sql`
(štítok Listy, PDF = len výkres, filter „Moje CNC listy“ so štítkom „CNC listy ✕“).

**1.3.7**: Moje filtre (fajka, vypnutie klikom, predvolené upraviteľné), Zoznam/Galéria nad zoznamom
+ Ctrl+G, hľadanie presne nad zoznamom, v detaile len priečinok.

**1.3.6**: odkazy .lnk oboma smermi + ikonka v strome, náhľady DXF a DWG (`vykres.py`).

**1.3.5** (len build, bez tagu): tlačidlo Obnoviť (F5), upozornenie na novú verziu Lupy, „Odkazujú sem“.

**1.3.4**: menu zákaziek – `OD…` pred starými, novšie skôr, rok zmeny pri zákazke.

**1.3.3 (21.11.2026)**: menu zákaziek – koniec čísla (`014` = `100014`) pred „začína na“, zákazníci
majú vlastné 4 miesta.

**Vydaná 1.3.2 (21.11.2026)** – tag `v1.3.2`, build v `dist\Lupa\`. Obsahuje: lokálna kópia DB + pásik,
spúšťač (onedir v `app\`), nové typy (MODEL, OBR, MAIL, ZIP, ECAM, XLS aj xlsm), skryté súbory/priečinky
+ upratanie DB + VACUUM, odkazy .lnk, dvojklik = ukázať v strome, kontextové menu súborov, stĺpce,
vlastníci, strom šípkami, menu zákaziek pod hľadaním.

**21.11.2026**: v noci prebehol úplný sken L:\ aj so všetkými odtlačkami PDF (DB ~250 MB, 42 000 zákaziek,
328 zákazníkov, 63 000 odtlačkov). Spúšťač + lokálna kópia DB overené používateľom na L:\ („vyzerá fajn“).

**Ostré nasadenie (20.11.2026)**: DB `L:\_Nastroje\lupa\lupa.db` na sieťovom disku (~180 MB).
Prvý úplný sken L:\ (ešte skener 1.0 na inom PC) – ~1 h, 33 600+ zákaziek / 237 zákazníkov, bez chýb.
Lupa 1.2.0 tam mala prázdne okno (DB na sieti – `db.ro_uri`), opravené v 1.3.0 a overené používateľom.

**Podobné výkresy** (bod 5): odtlačky v skeneri + UI hotové (tlačidlo v detaile PDF, výsledok
v zozname/galérii so stĺpcom Podobnosť, Esc = späť; `Api.similar`, index v pamäti do zmeny DB).
Slabé miesto: náš `drw0001` ↔ výkres zákazníka (iné rozloženie pohľadov) – neskôr kombinácia s STP.

**Na rade (21.11.2026)**:
- Pomalý štart (16 s cez sieť – meranie `zmeraj_start.py`: počet odtlačkov 8,3 s, úplnosť 4,7 s) →
  lokálna kópia DB + pásik priebehu (overené, ~5 s – zvyšok bol štart onefile exe) → spúšťač + onedir
  (overené na L:\).
- ✅ Filter vlastníka: počty súborov len vo vybranej zákazke / u zákazníka (`get_owners(params)`).
- ✅ Odkazy .lnk – fáza 2: pri starej zákazke „Odkazujú sem: zákazky X, Y“ (1.3.5).

## Pôvodný úvod sekcie „Stav projektu“ (súhrn a git tagy)

Hotové: verzia 1 (nižšie) + náhľady, galéria, NC/TXT náhľad, kontrola úplnosti, exe, ikona skenu
pri hodinách, stavový riadok, kontextové menu stromu, podobné výkresy, filter zákazníkov v `lupa.ini`,
hľadanie čísla zákazky v strome, typy XLS/DOC zvlášť,
lokálna kópia DB, spúšťač, nové typy, odkazy .lnk, menu zákaziek pod hľadaním (1.3.2).
Vydania = git tagy `v1.0`, `v1.1.0`, `v1.2.0`, `v1.3.0`, `v1.3.1`, `v1.3.2`, `v1.3.3`, `v1.3.4`, `v1.3.6`, `v1.3.7`, `v1.3.9`, `v1.4.0`, `v1.4.1`, `v1.5.0`, `v1.5.1` (pushnuté na GitHub `origin/main`).

## Pôvodné poznámky o ďalších krokoch a rozpracovanom

**Ďalšie možné kroky**: STL – v práci ho Windows už ukazuje (doplnok), vlastné netreba.
**Náhľad STP – odložené** (skúška 21.11.2026 mimo projektu): gmsh/OpenCascade načítal STP a rozmery,
ale vykreslil len 17/47 vzoriek (zlyháva sieť trojuholníkov hlavne pri dieloch z Crea, pády,
limity), +86 MB. Ak znova: priamo OpenCascade (`cadquery-ocp`, BRepMesh – spoľahlivejšie, ~+150 MB);
rozmery zo STP by sa hodili k podobným výkresom.

**Rozpracované (23.11.2026)**: náhľady Word / Excel (`dokument.py`, `thumbs.py`) – len lokálne, necommitnuté,
používateľ ich skúša v práci. Návrh na neskôr (neschválený): celá strana Wordu = prvá strana PDF s rovnakým
menom v tom istom priečinku (ak existuje), inak súčasný obrázok; vykresľovanie cez Word COM radšej nie.
