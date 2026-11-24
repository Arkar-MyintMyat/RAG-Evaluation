"""Fill the [PENDING] placeholders in a hand-edited report with the numbers from the generated report.

Only the highlighted [PENDING] runs are changed (text replaced, highlight removed); all other wording and
formatting of the edited document stays as it is.
  * paragraphs: each edited paragraph is matched to the most similar generated paragraph, and the two
    texts are aligned character by character (difflib), so the value that sits where [PENDING] was is
    taken over even if the surrounding words were edited.
  * tables: matched by table index and cell position.
Anything that cannot be matched safely is left as [PENDING] and listed at the end.

Usage: python src/fill_pending.py --edited report/Evaluation-report.docx
                                  --generated report/generated/Evaluation-report-generated.docx
                                  --out report/Evaluation-report.docx
"""
import argparse, difflib, re
from pathlib import Path

import docx
from docx.enum.text import WD_COLOR_INDEX

PH = "[PENDING]"


def norm(t):
    return re.sub(r"\s+", " ", t).strip()


def values_by_alignment(edited_text, gen_text):
    """Return the generated substrings aligned with each [PENDING] in edited_text (None if unclear)."""
    sm = difflib.SequenceMatcher(None, edited_text, gen_text, autojunk=False)
    ops = sm.get_opcodes()
    vals = []
    for m in re.finditer(re.escape(PH), edited_text):
        a0, a1 = m.start(), m.end()
        # map edited positions a0 and a1 to generated positions via the opcodes
        def map_pos(a, left):
            for tag, i1, i2, j1, j2 in ops:
                if i1 <= a <= i2:
                    if tag == "equal":
                        return j1 + (a - i1)
                    return j1 if left else j2
            return None
        b0, b1 = map_pos(a0, True), map_pos(a1, False)
        v = gen_text[b0:b1].strip() if b0 is not None and b1 is not None and b1 >= b0 else None
        if v is not None and (not v or PH in v or len(v) > 12):
            v = None
        vals.append(v)
    return vals


def fill_runs(paragraph, values, misses, where):
    k = 0
    for run in paragraph.runs:
        while PH in run.text and k < len(values):
            v = values[k]; k += 1
            if v is None:
                misses.append(where); break
            run.text = run.text.replace(PH, v, 1)
            if PH not in run.text:
                run.font.highlight_color = None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edited", default="report/Evaluation-report.docx")
    ap.add_argument("--generated", default="report/generated/Evaluation-report-generated.docx")
    ap.add_argument("--out", default="report/Evaluation-report.docx")
    a = ap.parse_args()
    E, G = docx.Document(a.edited), docx.Document(a.generated)
    misses, filled = [], 0
    gen_pars = [norm(p.text) for p in G.paragraphs]
    for p in E.paragraphs:
        if PH not in p.text:
            continue
        et = norm(p.text)
        key = et.replace(PH, "")
        best = max(range(len(gen_pars)), key=lambda i: difflib.SequenceMatcher(None, key, gen_pars[i], autojunk=False).ratio())
        score = difflib.SequenceMatcher(None, key, gen_pars[best], autojunk=False).ratio()
        if score < 0.6:
            misses.append(f"paragraph (no match): {et[:70]}"); continue
        vals = values_by_alignment(et, gen_pars[best])
        before = p.text.count(PH)
        fill_runs(p, vals, misses, f"paragraph: {et[:70]}")
        filled += before - p.text.count(PH)
    if len(E.tables) != len(G.tables):
        print(f"warning: {len(E.tables)} tables in edited vs {len(G.tables)} generated; matching by index anyway")
    for ti, (te, tg) in enumerate(zip(E.tables, G.tables)):
        for ri, (re_, rg) in enumerate(zip(te.rows, tg.rows)):
            for ci, (ce, cg) in enumerate(zip(re_.cells, rg.cells)):
                if PH in ce.text:
                    gtxt = norm(cg.text)
                    if not gtxt or PH in gtxt:
                        misses.append(f"table {ti} r{ri} c{ci}"); continue
                    vals = values_by_alignment(norm(ce.text), gtxt) if norm(ce.text) != PH else [gtxt]
                    for p in ce.paragraphs:
                        before = p.text.count(PH)
                        fill_runs(p, vals, misses, f"table {ti} r{ri} c{ci}")
                        filled += before - p.text.count(PH)
    E.save(a.out)
    left = sum(p.text.count(PH) for p in E.paragraphs) + sum(c.text.count(PH) for t in E.tables for r in t.rows for c in r.cells)
    print(f"filled {filled} placeholders, {left} left -> {a.out}")
    for m in misses:
        print("  could not fill:", m)


if __name__ == "__main__":
    main()
