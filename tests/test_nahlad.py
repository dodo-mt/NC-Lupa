"""Rýchly náhľad PDF, Wordu a Excelu (nahlad.py, Api.get_doc_preview)."""
import zipfile

import pymupdf
import pytest

import db
import nahlad

NS_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
NS_S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
NS_R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def vyrob_docx(cesta, odseky=("Programový list", "Druhý odsek"), tabulka=(("A", "B"), ("1", "2"))):
    telo = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in odseky)
    tab = "<w:tbl>" + "".join(
        "<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in r) + "</w:tr>" for r in tabulka
    ) + "</w:tbl>"
    with zipfile.ZipFile(cesta, "w") as z:
        z.writestr("word/document.xml", f'<w:document {NS_W}><w:body>{telo}{tab}<w:p/></w:body></w:document>')


def vyrob_xlsx(cesta, harky=(("Hárok1", [["Stroj", "DMC 160"], ["", "x"]]), ("Druhy", [["a"]]))):
    z = zipfile.ZipFile(cesta, "w")
    spolocne, retazce = [], {}

    def ss(t):
        if t not in retazce:
            retazce[t] = len(spolocne)
            spolocne.append(t)
        return retazce[t]

    sheets, rels = "", ""
    for i, (nazov, riadky) in enumerate(harky, 1):
        sheets += f'<sheet name="{nazov}" sheetId="{i}" r:id="rId{i}"/>'
        rels += f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml"/>'
        xml = ""
        for ri, r in enumerate(riadky, 1):
            bunky = "".join(f'<c r="{"ABCDEFGH"[ci]}{ri}" t="s"><v>{ss(t)}</v></c>' for ci, t in enumerate(r) if t != "")
            xml += f'<row r="{ri}">{bunky}</row>'
        z.writestr(f"xl/worksheets/sheet{i}.xml", f"<worksheet {NS_S}><sheetData>{xml}</sheetData></worksheet>")
    z.writestr("xl/workbook.xml", f"<workbook {NS_S} {NS_R}><sheets>{sheets}</sheets></workbook>")
    z.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="x">{rels}</Relationships>')
    z.writestr("xl/sharedStrings.xml", f"<sst {NS_S}>" + "".join(f"<si><t>{t}</t></si>" for t in spolocne) + "</sst>")
    z.close()


def vyrob_pdf(cesta, strany=3):
    doc = pymupdf.open()
    for i in range(strany):
        doc.new_page(width=300, height=400).insert_text((50, 100), f"Strana {i + 1}")
    doc.save(cesta)
    doc.close()


def test_word_odseky_a_tabulky(tmp_path):
    vyrob_docx(tmp_path / "a.docx")
    r = nahlad.word(str(tmp_path / "a.docx"))
    assert [b["typ"] for b in r["bloky"]] == ["p", "p", "tab", "p"] and r["bloky"][0]["text"] == "Programový list"
    assert r["bloky"][2]["riadky"] == [["A", "B"], ["1", "2"]] and not r["orezane"]


def test_excel_harky_riadky_a_prazdne_bunky(tmp_path):
    vyrob_xlsx(tmp_path / "a.xlsx")
    assert nahlad.excel_harky(str(tmp_path / "a.xlsx")) == ["Hárok1", "Druhy"]
    r = nahlad.excel(str(tmp_path / "a.xlsx"))
    assert r["harok"] == 0 and r["riadky"] == [["Stroj", "DMC 160"], ["", "x"]]
    assert nahlad.excel(str(tmp_path / "a.xlsx"), 1)["riadky"] == [["a"]]
    assert nahlad.excel(str(tmp_path / "a.xlsx"), 99)["harok"] == 1           # mimo rozsahu sa zarovná


def test_excel_orezanie_riadkov(tmp_path, monkeypatch):
    vyrob_xlsx(tmp_path / "b.xlsx", harky=(("H", [[str(i)] for i in range(1, 50)]),))
    monkeypatch.setattr(nahlad, "MAX_RIADKOV", 10)
    r = nahlad.excel(str(tmp_path / "b.xlsx"))
    assert len(r["riadky"]) == 10 and r["orezane"]


def test_pdf_strany(tmp_path):
    vyrob_pdf(tmp_path / "a.pdf")
    png, n = nahlad.pdf_strana(str(tmp_path / "a.pdf"), 1, 400)
    assert n == 3 and png[:8] == b"\x89PNG\r\n\x1a\n"
    assert nahlad.pdf_strana(str(tmp_path / "a.pdf"), 99)[1] == 3              # mimo rozsahu = posledná strana


def test_pokazeny_subor_nie_je_vynimka(tmp_path):
    (tmp_path / "zly.docx").write_bytes(b"nie zip")
    with pytest.raises(zipfile.BadZipFile):
        nahlad.word(str(tmp_path / "zly.docx"))


def _api(tmp_path):
    import app
    d = tmp_path / "n.sqlite"
    con = db.open_rw(d)
    con.execute("INSERT INTO customers(id, name, path) VALUES (1, 'K', 'x')")
    con.execute("INSERT INTO jobs(id, customer_id, name, path) VALUES (1, 1, 'J', 'y')")
    con.execute("INSERT INTO positions(id, job_id, name, rel_path, path) VALUES (1, 1, 'a', '', 'a')")
    subory = [(1, "a.pdf", "pdf", "PDF"), (2, "a.docx", "docx", "DOC"), (3, "a.xlsx", "xlsx", "XLS"), (4, "z.docx", "docx", "DOC"),
              (5, "m.dwg", "dwg", "DWG")]
    for i, name, ext, ft in subory:
        con.execute("INSERT INTO files(id, position_id, job_id, customer_id, name, ext, ftype, path, size, modified)"
                    " VALUES (?, 1, 1, 1, ?, ?, ?, ?, 10, 1)", (i, name, ext, ft, str(tmp_path / name)))
    con.commit()
    con.close()
    vyrob_pdf(tmp_path / "a.pdf")
    vyrob_docx(tmp_path / "a.docx")
    vyrob_xlsx(tmp_path / "a.xlsx")
    (tmp_path / "z.docx").write_bytes(b"nie zip")

    class Falosne:
        def _q(self, sql, args=()):
            c = db.open_ro(d)
            try:
                return [dict(r) for r in c.execute(sql, args)]
            finally:
                c.close()

    return app, Falosne()


def test_api_get_doc_preview(tmp_path):
    app, api = _api(tmp_path)
    r = app.Api.get_doc_preview(api, 1, 2)
    assert r["ok"] and r["kind"] == "pdf" and r["pages"] == 3 and r["page"] == 2 and r["src"].startswith("data:image/png;base64,")
    r = app.Api.get_doc_preview(api, 2)
    assert r["ok"] and r["kind"] == "word" and r["bloky"][0]["text"] == "Programový list"
    r = app.Api.get_doc_preview(api, 3, 0, 1)
    assert r["ok"] and r["kind"] == "excel" and r["harok"] == 1 and r["harky"] == ["Hárok1", "Druhy"]
    assert "nepodarilo" in app.Api.get_doc_preview(api, 4)["error"]            # pokazený docx
    assert app.Api.get_doc_preview(api, 5)["ok"] is False                       # DWG nemá rýchly náhľad
    assert app.Api.get_doc_preview(api, 99)["ok"] is False
