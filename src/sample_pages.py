"""Randomly sample (document, page) pairs to write test questions from (seeded, reproducible).
Questions are written from the sampled page, NOT from whatever the endpoint returns, so the
test set is not biased toward content the system retrieves easily.
- 'abstract' items use page 1 (easy baseline); 'body' items use a random page in the first 80%
  of the document (skipping reference pages and near-empty pages).
- 'missing' items are drawn from the documents that the coverage test found not to be indexed.
Usage: python src/sample_pages.py --seed 2026 --n_body 30 --n_abstract 6 --n_pair 8
Output: data/testset_build/sampled_pages.json
"""
import argparse, json, random, re
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument("--seed", type=int, default=2026)
ap.add_argument("--n_body", type=int, default=30)
ap.add_argument("--n_abstract", type=int, default=6)
ap.add_argument("--n_pair", type=int, default=8)
a = ap.parse_args()
rng = random.Random(a.seed)
docs = {json.loads(l)["source"]: json.loads(l) for l in (ROOT / "data" / "papers_text.jsonl").open(encoding="utf-8")}
inv = pd.read_csv(ROOT / "data" / "inventory.csv").set_index("source")
missing = set(json.loads((ROOT / "results" / "coverage_summary.json").read_text())["docs_never_retrieved"])
indexed = sorted(set(docs) - missing)
clean = lambda t: re.sub(r"\s+", " ", t).strip()

def body_page(src):
    pg = docs[src]["pages"]
    cand = [i for i in range(1, max(2, int(len(pg) * 0.8)))
            if i < len(pg) and len(clean(pg[i])) > 1800 and not re.match(r"\s*(references|bibliography)\b", clean(pg[i])[:120], re.I)]
    return rng.choice(cand) if cand else 0

out = []
pool = indexed[:]; rng.shuffle(pool)
for s in pool[:a.n_body]:
    p = body_page(s); out.append({"kind": "body", "source": s, "page_idx": p, "category": inv.category[s], "text": clean(docs[s]["pages"][p])[:3800]})
for s in pool[a.n_body:a.n_body + a.n_abstract]:
    out.append({"kind": "abstract", "source": s, "page_idx": 0, "category": inv.category[s], "text": clean(docs[s]["pages"][0])[:2500]})
rest = pool[a.n_body + a.n_abstract:]
for k in range(a.n_pair):  # pairs for multi-hop / comparison questions, from the same category when possible
    s1 = rest[k]; same = [x for x in rest[a.n_pair:] if inv.category[x] == inv.category[s1] and x != s1]
    s2 = rng.choice(same) if same else rng.choice(rest[a.n_pair:])
    for s in (s1, s2):
        out.append({"kind": f"pair{k}", "source": s, "page_idx": 0, "category": inv.category[s], "text": clean(docs[s]["pages"][0])[:2000]})
for s in sorted(missing):
    p = body_page(s); out.append({"kind": "missing", "source": s, "page_idx": p, "category": inv.category[s], "text": clean(docs[s]["pages"][p])[:3000]})
(ROOT / "data" / "testset_build" / "sampled_pages.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print(len(out), "sampled items")
for o in out: print(o["kind"], o["page_idx"], o["source"][:90], "|", o["category"])
