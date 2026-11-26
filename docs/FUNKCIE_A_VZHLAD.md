# Lupa – podrobný popis funkcií a vzhľadu

Presunuté z CLAUDE.md bez zmeny textu (sekcie Verzia 1, Rozšírenia, Vzhľad).

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
