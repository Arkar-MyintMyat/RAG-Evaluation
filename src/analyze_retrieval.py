"""Judge-free analysis of retrieval and indexing quality (uses cached endpoint responses only).

  1. ID-based retrieval metrics per question type (document level):
       hit@5      = share of gold documents that appear among the 5 retrieved chunks
       prec@5     = share of retrieved chunks that come from a gold document
     (equivalent to Ragas IDBasedContextRecall / IDBasedContextPrecision with document ids)
  2. Chunk quality over ALL chunks the endpoint returned (test set + coverage + system tests):
       chunk length, near-duplicate chunks inside one response, chunks from duplicate files,
       bibliography/reference-list chunks, page-label accuracy (is the chunk text really on the stated page?)
  3. Retrieval score separation: are top scores for unanswerable questions lower than for answerable ones?
  4. Latency statistics per route.

Usage: python src/analyze_retrieval.py
Output: results/retrieval_analysis.json, results/retrieval_per_question.csv, results/latency.csv
"""
import json, re, statistics as st
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DOCS = {json.loads(l)["source"]: json.loads(l) for l in (ROOT / "data" / "papers_text.jsonl").open(encoding="utf-8")}
DUP_FILES = [("017", "037"), ("028", "039"), ("043", "058")]
norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
NORM_PAGES = {s: [norm(p) for p in d["pages"]] for s, d in DOCS.items()}


def pct(xs, q):
    xs = sorted(xs); return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def locate(chunk):
    """Return the 1-based pages of its source PDF that contain a snippet from the middle of the chunk."""
    t = norm(chunk["text"])
    if len(t) < 120 or chunk["source"] not in NORM_PAGES:
        return None
    for off in (len(t) // 2, len(t) // 4, 3 * len(t) // 4):
        snip = t[off:off + 60]
        found = [i + 1 for i, p in enumerate(NORM_PAGES[chunk["source"]]) if snip in p]
        if found:
            return found
    return []


def is_bibliography(text):
    return len(re.findall(r"arXiv|et al\.|Proceedings|URL https?://|doi\.org|\(\d{4}\)\.|, \d{4}\.", text)) >= 6


def main():
    tests = {t["id"]: t for t in json.loads((ROOT / "data" / "testset.json").read_text(encoding="utf-8"))}
    resp = [json.loads(l) for l in (ROOT / "data" / "responses.jsonl").open(encoding="utf-8")]
    raw = [json.loads(l) for l in (ROOT / "data" / "raw" / "endpoint_raw.jsonl").open(encoding="utf-8")]

    # ---- 1. ID-based retrieval metrics ----
    rows = []
    for r in resp:
        t = tests[r["id"]]
        gold = {g[:3] for g in t["source_documents"]}
        for a, b in DUP_FILES:  # a duplicate file of a gold doc also counts
            if a in gold or b in gold:
                gold |= {a, b}
        ret = [c["source"][:3] for c in r["contexts"]]
        golds_needed = {g[:3] for g in t["source_documents"]}
        hit = (sum(1 for g in golds_needed if g in ret or any(g in d and o in ret for d in DUP_FILES for o in d)) / len(golds_needed)) if golds_needed else None
        rows.append({"id": r["id"], "question_type": r["question_type"], "expected": t["expected_behavior"],
                     "hit_at_5": hit, "all_gold_found": (hit == 1.0) if hit is not None else None,
                     "prec_at_5": (sum(x in gold for x in ret) / len(ret)) if (gold and ret) else None,
                     "n_distinct_docs": len(set(ret)), "top_score": r["contexts"][0]["score"] if r["contexts"] else None,
                     "mean_score": st.mean(c["score"] for c in r["contexts"]) if r["contexts"] else None,
                     "abstained": bool(re.search(r"\bI don'?t know\b|don't have information|does not provide|not (?:contain|provide|available)|blocked by our content filters", r["answer"] or "", re.I)),
                     "latency_s": r["latency_s"], "completion_tokens": (r.get("usage") or {}).get("completion_tokens")})
    df = pd.DataFrame(rows)
    df.to_csv(ROOT / "results" / "retrieval_per_question.csv", index=False)
    by_type = df.groupby("question_type").agg(n=("id", "count"), hit_at_5=("hit_at_5", "mean"), all_gold_found=("all_gold_found", "mean"),
                                              prec_at_5=("prec_at_5", "mean"), distinct_docs=("n_distinct_docs", "mean"),
                                              top_score=("top_score", "mean"), abstain_rate=("abstained", "mean")).round(3)

    # ---- 2. chunk quality over all returned chunks ----
    chunks, per_resp_dups, n_resp = {}, 0, 0
    dup_file_in_same_resp = 0
    for rec in raw:
        b = rec["body"]
        if not (isinstance(b, dict) and b.get("contexts")):
            continue
        n_resp += 1
        ctx = b["contexts"]
        seen = []
        for c in ctx:
            key = (c["source"], norm(c["text"])[:200])
            chunks.setdefault(key, c)
            s = set(re.findall(r"\w+", c["text"].lower()))
            if any(len(s & o) / max(1, len(s | o)) > 0.8 for o in seen):
                per_resp_dups += 1
            seen.append(s)
        srcs = {c["source"][:3] for c in ctx}
        if any(a in srcs and b_ in srcs for a, b_ in DUP_FILES):
            dup_file_in_same_resp += 1
    uniq = list(chunks.values())
    lens = [len(c["text"]) for c in uniq]
    page_ok = page_off = page_unk = page_span = 0
    off_examples = []
    for c in uniq:
        pages = locate(c)
        if not pages:
            page_unk += 1
        elif c["page"] in pages:
            page_ok += 1
        elif 0 < c["page"] <= len(NORM_PAGES[c["source"]]) and norm(c["text"])[:50] in NORM_PAGES[c["source"]][c["page"] - 1]:
            page_span += 1  # chunk starts on the stated page and continues on the next one: label is fine
        else:
            page_off += 1
            if len(off_examples) < 5:
                off_examples.append({"source": c["source"], "reported_page": c["page"], "found_on_pages": pages})
    bib = [c for c in uniq if is_bibliography(c["text"])]

    # ---- 3. score separation ----
    ans = df[df.expected == "answer"].top_score.tolist()
    una = df[df.expected == "abstain"].top_score.tolist()
    thresholds = {}
    for th in (0.45, 0.5, 0.55, 0.6):
        thresholds[str(th)] = {"answerable_kept": round(sum(x >= th for x in ans) / len(ans), 3), "unanswerable_blocked": round(sum(x < th for x in una) / len(una), 3)}

    # ---- 4. latency ----
    lat = pd.DataFrame([{"route": r["route"], "tag": r["tag"].split(":")[0], "status": r["status"], "latency_s": r["latency_s"], "ts": r["ts"]} for r in raw])
    lat.to_csv(ROOT / "results" / "latency.csv", index=False)
    latency = {}
    for route, g in lat[lat.status == 200].groupby("route"):
        x = g.latency_s.tolist()
        latency[route] = {"n": len(x), "median": round(st.median(x), 3), "p10": round(pct(x, .1), 3), "p90": round(pct(x, .9), 3), "p99": round(pct(x, .99), 3), "max": round(max(x), 3)}
    chat_tests = df.dropna(subset=["completion_tokens"])
    corr = round(chat_tests[["latency_s", "completion_tokens"]].corr().iloc[0, 1], 3)

    out = {
        "retrieval_by_question_type": by_type.reset_index().to_dict(orient="records"),
        "answerable_overall": {"n": int((df.expected == "answer").sum()), "hit_at_5": round(df[df.expected == "answer"].hit_at_5.mean(), 3),
                               "all_gold_found": round(df[df.expected == "answer"].all_gold_found.mean(), 3)},
        "chunks": {"responses_with_contexts": n_resp, "k_always_5": all(len(r["contexts"]) == 5 for r in resp), "unique_chunks": len(uniq),
                   "chunk_chars_median": st.median(lens), "chunk_chars_p10": pct(lens, .1), "chunk_chars_p90": pct(lens, .9), "chunk_chars_max": max(lens),
                   "near_duplicate_chunks_within_response": per_resp_dups, "near_duplicate_rate_per_chunk": round(per_resp_dups / (5 * n_resp), 3),
                   "responses_containing_both_copies_of_a_duplicate_file": dup_file_in_same_resp,
                   "bibliography_chunks": len(bib), "bibliography_rate": round(len(bib) / len(uniq), 3),
                   "page_label_correct": page_ok, "page_label_chunk_spans_next_page": page_span, "page_label_wrong": page_off, "page_label_unverifiable": page_unk, "page_label_wrong_examples": off_examples},
        "score_threshold_simulation": thresholds,
        "top_score_answerable_mean": round(st.mean(ans), 3), "top_score_unanswerable_mean": round(st.mean(una), 3),
        "latency": latency, "corr_latency_vs_completion_tokens_testset": corr,
        "first_request_of_session_latency_s": float(lat.sort_values("ts").latency_s.iloc[0]),
    }
    (ROOT / "results" / "retrieval_analysis.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print(by_type.to_string()); print(json.dumps({k: v for k, v in out.items() if k != "retrieval_by_question_type"}, indent=1, default=float))


if __name__ == "__main__":
    main()
