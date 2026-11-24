"""Join the shared document list (data/document_list.csv) with the PDF files in the ZIP.
The shared list numbers two documents as #92, so files 093-183 correspond to list rows 93-183.
Mapping is positional (row order == file order); title similarity is reported as a sanity check. Output: data/inventory.csv
Usage: python src/build_inventory.py
"""
import json, re, difflib
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
lst = pd.read_csv(ROOT / "data" / "document_list.csv").reset_index(drop=True)
docs = [json.loads(l) for l in (ROOT / "data" / "papers_text.jsonl").open(encoding="utf-8")]
norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower())
rows = []
for d in docs:
    t = re.sub(r"^\d+ - ", "", d["source"]).rsplit(".", 1)[0]
    i = d_no = int(d["source"][:3]) - 1  # positional: list row order == file order
    sims = {i: difflib.SequenceMatcher(None, norm(t), norm(lst.Title[i])).ratio()}
    rows.append({"source": d["source"], "file_no": int(d["source"][:3]), "list_num": int(lst.Num[i]), "title": lst.Title[i],
                 "category": lst.Category[i], "title_match": round(sims[i], 2), "n_pages": d["n_pages"], "n_chars": d["n_chars"]})
inv = pd.DataFrame(rows)
inv.to_csv(ROOT / "data" / "inventory.csv", index=False)
print(inv.title_match.describe()); print(inv.sort_values("title_match").head(5)[["source", "title", "title_match"]].to_string())
print("list rows matched more than once:", inv.list_num.duplicated().sum(), "| unmatched list rows:", len(lst) - inv.title.nunique())
