"""Give the generated tables (all except the template's own first table) compact cell margins and the
template table's look (thin grey borders, shaded header row). Usage: python src/style_tables.py report/Evaluation-report.docx"""
import sys
import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def el(tag, **attrs):
    e = OxmlElement(tag)
    for k, v in attrs.items():
        e.set(qn(k), v)
    return e


def style_table(t):
    tblPr = t._tbl.tblPr
    for old in tblPr.findall(qn("w:tblCellMar")) + tblPr.findall(qn("w:tblBorders")):
        tblPr.remove(old)
    mar = el("w:tblCellMar")
    for side, w in (("top", "15"), ("bottom", "15"), ("left", "70"), ("right", "70")):
        mar.append(el(f"w:{side}", **{"w:w": w, "w:type": "dxa"}))
    tblPr.append(mar)
    b = el("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b.append(el(f"w:{side}", **{"w:val": "single", "w:sz": "4", "w:space": "0", "w:color": "A6A6A6"}))
    tblPr.append(b)
    for c in t.rows[0].cells:
        tcPr = c._tc.get_or_add_tcPr()
        for old in tcPr.findall(qn("w:shd")):
            tcPr.remove(old)
        tcPr.append(el("w:shd", **{"w:val": "clear", "w:color": "auto", "w:fill": "EDEDED"}))
        for r in c.paragraphs[0].runs:
            r.bold = True


path = sys.argv[1] if len(sys.argv) > 1 else "report/Evaluation-report.docx"
d = docx.Document(path)
for t in d.tables[1:]:
    style_table(t)
d.save(path)
print("styled", len(d.tables) - 1, "tables in", path)
