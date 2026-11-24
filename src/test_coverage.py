"""System test: coverage of the document collection (retrieval-only route).

For every PDF in the source collection, we send two /v1/context probes:
  - 'early': a verbatim ~250-char passage from the first content page (title/abstract area)
  - 'late' : a verbatim passage from the page at ~60% of the document (body text)
A document counts as retrievable if it appears among the returned chunks for the probe.
A verbatim passage is the easiest possible query, so a miss strongly suggests the document
(or that part of it) is missing from the index, badly parsed, or drowned out by duplicates.
Docs that miss both probes get a third probe with their title.

Usage: python src/test_coverage.py   (cost: ~2 requests per document, cached)
Output: results/coverage.csv, results/coverage_summary.json
"""
import json, re, sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import endpoint as ep

ROOT = ep.ROOT


def clean(t):
    return re.sub(r"\s+", " ", t).strip()


def passage(page_text, start_frac=0.35, n=250):
    t = clean(page_text)
    if len(t) < 400:
        return None
    s = int(len(t) * start_frac)
    s = t.find(" ", s) + 1  # start at a word boundary
    return t[s:s + n].rsplit(" ", 1)[0]


def pick_pages(pages):
    good = [i for i, p in enumerate(pages) if len(clean(p)) > 1500 and not re.search(r"^\s*references\b", clean(p)[:200], re.I)]
    if not good:
        good = [i for i, p in enumerate(pages) if len(clean(p)) > 400]
    early = good[0]
    target = int(len(pages) * 0.6)
    late = min(good, key=lambda i: abs(i - target))
    return early, late


def title_of(source):
    return re.sub(r"^\d+ - ", "", source).rsplit(".", 1)[0]


def main():
    docs = [json.loads(l) for l in (ROOT / "data" / "papers_text.jsonl").open(encoding="utf-8")]
    jobs = []
    for d in docs:
        e, l = pick_pages(d["pages"])
        jobs.append((d["source"], "early", e, passage(d["pages"][e], 0.3)))
        jobs.append((d["source"], "late", l, passage(d["pages"][l], 0.4)))

    def run(j):
        src, kind, page, q = j
        r = ep.context(q, tag=f"coverage:{kind}")
        ctx = r["body"].get("contexts", []) if isinstance(r["body"], dict) else []
        srcs = [c.get("source") for c in ctx]
        rank = srcs.index(src) + 1 if src in srcs else None
        return {"source": src, "probe": kind, "pdf_page_idx": page, "n_pages": None, "query": q,
                "status": r["status"], "latency_s": r["latency_s"], "hit": rank is not None, "rank": rank,
                "top_source": srcs[0] if srcs else None, "top_score": ctx[0]["score"] if ctx else None,
                "returned_pages": [c.get("page") for c in ctx if c.get("source") == src],
                "n_returned": len(ctx), "n_distinct_sources": len(set(srcs))}

    rows = ep.run_parallel(run, jobs)
    df = pd.DataFrame(rows)
    npages = {d["source"]: d["n_pages"] for d in docs}
    df["n_pages"] = df.source.map(npages)

    # third probe: title, only for docs missed by both passage probes
    per = df.groupby("source").hit.any()
    missed = per[~per].index.tolist()
    trows = []
    for src in missed:
        r = ep.context(title_of(src), tag="coverage:title")
        ctx = r["body"].get("contexts", []) if isinstance(r["body"], dict) else []
        srcs = [c.get("source") for c in ctx]
        trows.append({"source": src, "probe": "title", "query": title_of(src), "status": r["status"],
                      "latency_s": r["latency_s"], "hit": src in srcs, "rank": srcs.index(src) + 1 if src in srcs else None,
                      "top_source": srcs[0] if srcs else None, "top_score": ctx[0]["score"] if ctx else None,
                      "n_pages": npages[src], "n_returned": len(ctx), "n_distinct_sources": len(set(srcs))})
    df = pd.concat([df, pd.DataFrame(trows)], ignore_index=True)
    df.to_csv(ROOT / "results" / "coverage.csv", index=False)

    any_hit = df.groupby("source").hit.any()
    seen = set()
    for r in ep._cache.values():
        b = r["body"]
        if isinstance(b, dict):
            seen |= {c.get("source") for c in b.get("contexts", [])}
    summary = {
        "n_documents": len(docs),
        "early_probe_hit_rate": float(df[df.probe == "early"].hit.mean()),
        "late_probe_hit_rate": float(df[df.probe == "late"].hit.mean()),
        "docs_retrievable_by_any_probe": int(any_hit.sum()),
        "docs_never_retrieved": sorted(any_hit[~any_hit].index.tolist()),
        "docs_early_hit_late_miss": sorted(set(df[(df.probe == "early") & df.hit].source) & set(df[(df.probe == "late") & ~df.hit].source)),
        "distinct_sources_seen_in_all_responses": len(seen - {None}),
        "sources_seen_not_in_collection": sorted((seen - {None}) - {d["source"] for d in docs}),
        "endpoint_requests_sent_total": ep.requests_sent(),
    }
    (ROOT / "results" / "coverage_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
