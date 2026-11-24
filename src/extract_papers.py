"""Extract the source ZIP and dump per-page text of every PDF to data/papers_text.jsonl.
Only used to write the test set (reference answers) and to check document coverage.
Usage: python src/extract_papers.py --zip data/papers_zip/papers.zip --out data/papers_text.jsonl
"""
import argparse, json, zipfile, io, sys
from pypdf import PdfReader

ap = argparse.ArgumentParser()
ap.add_argument("--zip", default="data/papers_zip/papers.zip")
ap.add_argument("--out", default="data/papers_text.jsonl")
a = ap.parse_args()
z = zipfile.ZipFile(a.zip)
with open(a.out, "w", encoding="utf-8") as f:
    for name in sorted(n for n in z.namelist() if n.lower().endswith(".pdf")):
        fn = name.split("/")[-1]
        try:
            r = PdfReader(io.BytesIO(z.read(name)))
            pages = [(p.extract_text() or "").encode("utf-8", "replace").decode("utf-8") for p in r.pages]
        except Exception as e:
            print("FAIL", fn, e, file=sys.stderr); pages = []
        f.write(json.dumps({"source": fn, "n_pages": len(pages), "n_chars": sum(map(len, pages)), "pages": pages}, ensure_ascii=False) + "\n")
        print(fn, len(pages), sum(map(len, pages)), flush=True)
