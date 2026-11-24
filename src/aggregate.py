"""Aggregate all results into results/summary.json and figures (results/figures/*.png).

Reads (whatever exists): results/coverage_summary.json, results/retrieval_per_question.csv,
results/retrieval_analysis.json, results/system_tests.json, results/ragas/scores_big.csv, scores_small.csv.
Ragas parts are skipped (marked 'pending') if the judge has not been run yet.

Judge reliability checks (computed when the scores exist):
  * agreement between the two judges (GPT OSS 120B vs Gemma4 26B): Spearman rho, mean |diff|, binary agreement
  * stability: GPT OSS 120B re-scoring a subset (run_tag 'rerun2'): mean |diff| between runs
  * LLM context recall vs ID-based (judge-free) context recall: agreement on 'gold doc retrieved'
  * known-answer sanity cases (e.g. B26 faithful-but-wrong, 'I don't know' answers)
Usage: python src/aggregate.py
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
FIG = RES / "figures"; FIG.mkdir(parents=True, exist_ok=True)
TYPE_ORDER = ["single_hop_abstract", "single_hop_body", "paraphrase", "multi_hop", "false_premise", "unindexed_doc", "inventory_mismatch", "out_of_corpus"]
LLM_METRICS = ["faithfulness", "answer_relevancy", "llm_context_precision_with_reference", "context_recall", "factual_correctness", "premise_corrected", "appropriate_abstention"]
SANITY = {"B06": "fully correct list of 4 specs; reference adds descriptions: recall-mode factual_correctness is pessimistic",
          "B26": "faithful but wrong condition (GPT-4o table reported as GPT-3.5): expect high faithfulness, low factual_correctness",
          "A04": "answer '4% to 5%' is supported by p.15 but reference says '4 percent': reference incompleteness",
          "M01": "'I don't know' although one gold doc retrieved: expect answer_relevancy ~0",
          "P01": "'I don't know', gold doc not retrieved: expect context_recall ~0",
          "F03": "accepts reversed premise: expect premise_corrected = 0"}


def load_json(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def ragas_block(tests):
    out = {"status": "pending"}
    big_p, small_p = RES / "ragas" / "scores_big.csv", RES / "ragas" / "scores_small.csv"
    if not big_p.exists():
        return out, None
    big = pd.read_csv(big_p)
    main = big[big.run_tag == "main"].copy()
    main["question_type"] = main.id.map(lambda i: tests[i]["question_type"])
    if not set(LLM_METRICS) & set(main.metric):
        return out, None
    out = {"status": "done", "judge_main": "GPT OSS 120B (azsydsttjnlbfjbgqnwd)"}
    piv = main.pivot_table(index="question_type", columns="metric", values="score", aggfunc="mean").reindex([t for t in TYPE_ORDER if t in set(main.question_type)])
    cnt = main.pivot_table(index="question_type", columns="metric", values="score", aggfunc="count")
    out["mean_by_type"] = piv.round(3).where(piv.notna(), None).to_dict(orient="index")
    out["n_scored_by_type"] = cnt.to_dict(orient="index")
    ans = main[main.question_type.isin(["single_hop_abstract", "single_hop_body", "paraphrase", "multi_hop"])]
    out["answerable_overall_mean"] = ans.groupby("metric").score.mean().round(3).to_dict()
    out["answerable_overall_median"] = ans.groupby("metric").score.median().round(3).to_dict()
    out["nan_counts"] = main[main.score.isna()].groupby("metric").id.apply(list).to_dict()
    # faithfulness on answers that are 'I don't know'
    resp = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "data" / "responses.jsonl").open(encoding="utf-8")}
    idk = [i for i, r in resp.items() if (r["answer"] or "").strip().lower().startswith(("i don't know", "sorry, i don't know"))]
    out["scores_on_idk_answers"] = main[main.id.isin(idk) & main.metric.isin(["faithfulness", "answer_relevancy", "factual_correctness"])].groupby("metric").score.apply(lambda s: [None if pd.isna(x) else round(x, 3) for x in s]).to_dict()
    out["sanity_cases"] = {i: {"expectation": e, "scores": main[main.id == i].set_index("metric").score.round(3).to_dict()} for i, e in SANITY.items()}
    # LLM context recall vs ID-based recall
    m = main.pivot_table(index="id", columns="metric", values="score")
    if {"context_recall", "id_based_context_recall"} <= set(m.columns):
        mm = m[["context_recall", "id_based_context_recall"]].dropna()
        out["llm_vs_id_context_recall"] = {"n": len(mm), "agreement_on_binary(>=0.5)": round(((mm.context_recall >= .5) == (mm.id_based_context_recall >= .5)).mean(), 3),
                                           "spearman": round(mm.corr(method="spearman").iloc[0, 1], 3)}
    # stability
    rr = big[big.run_tag == "rerun2"]
    if len(rr):
        j = rr.merge(main, on=["id", "metric"], suffixes=("_rerun", "_main"))
        out["judge_stability"] = {met: {"n": len(g), "mean_abs_diff": round((g.score_rerun - g.score_main).abs().mean(), 3),
                                        "identical_share": round(((g.score_rerun - g.score_main).abs() < 1e-9).mean(), 3)} for met, g in j.groupby("metric")}
    # inter-judge agreement
    if small_p.exists():
        sm = pd.read_csv(small_p); sm = sm[sm.run_tag == "main"]
        j = sm.merge(main, on=["id", "metric"], suffixes=("_small", "_big")).dropna(subset=["score_small", "score_big"])
        agr = {}
        for met, g in j.groupby("metric"):
            if met.startswith("id_based"):
                continue
            d = {"n": len(g), "mean_big": round(g.score_big.mean(), 3), "mean_small": round(g.score_small.mean(), 3),
                 "mean_abs_diff": round((g.score_big - g.score_small).abs().mean(), 3),
                 "binary_agreement(>=0.5)": round(((g.score_big >= .5) == (g.score_small >= .5)).mean(), 3)}
            if len(g) > 3 and g.score_big.nunique() > 1 and g.score_small.nunique() > 1:
                d["spearman"] = round(g[["score_big", "score_small"]].corr(method="spearman").iloc[0, 1], 3)
            agr[met] = d
        out["inter_judge_agreement"] = agr
    return out, piv


def fig_outcomes(per_q, premise_scores=None):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    BLUE, ORANGE, INK, INK2, GRID, SURF = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    labels = {"single_hop_abstract": "Single-hop (abstract)", "single_hop_body": "Single-hop (body page)", "paraphrase": "Paraphrase (no keywords)",
              "multi_hop": "Multi-hop (2 papers)", "false_premise": "False premise", "unindexed_doc": "Listed doc, not indexed",
              "inventory_mismatch": "Wrong file for title", "out_of_corpus": "Out of corpus"}
    types = [t for t in TYPE_ORDER if t in set(per_q.question_type)]
    ret, outc = [], []
    for t in types:
        g = per_q[per_q.question_type == t]
        ret.append(g.all_gold_found.mean() if g.all_gold_found.notna().any() else float("nan"))
        if g.expected.iloc[0] == "abstain":
            outc.append(g.abstained.mean())
        elif t == "false_premise":  # needs the judge (premise_corrected); n/a until Ragas has run
            outc.append(premise_scores if premise_scores is not None else float("nan"))
        else:
            outc.append(1 - g.abstained.mean())
    n = [int((per_q.question_type == t).sum()) for t in types]
    fig, ax = plt.subplots(figsize=(6.6, 3.1), dpi=200)
    fig.patch.set_facecolor(SURF); ax.set_facecolor(SURF)
    y = range(len(types)); h = 0.36
    for k, (vals, col, lab) in enumerate([(ret, BLUE, "All gold documents retrieved (top-5)"), (outc, ORANGE, "Expected behaviour: answered (answerable) / abstained (must-abstain)")]):
        ys = [i - h / 2 - 0.02 + k * (h + 0.04) for i in y]
        for yy, v in zip(ys, vals):
            if v == v:
                ax.barh(yy, v, height=h, color=col, edgecolor=SURF, linewidth=1)
                ax.text(v + 0.01, yy, f"{v:.0%}", va="center", fontsize=6.5, color=INK2)
            else:
                ax.text(0.01, yy, "n/a", va="center", fontsize=6.5, color=INK2)
    ax.set_yticks(list(y)); ax.set_yticklabels([f"{labels[t]}  (n={c})" for t, c in zip(types, n)], fontsize=7, color=INK)
    ax.invert_yaxis(); ax.set_xlim(0, 1.12); ax.set_xticks([0, .25, .5, .75, 1]); ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"], fontsize=7, color=INK2)
    ax.xaxis.grid(True, color=GRID, linewidth=0.6); ax.set_axisbelow(True)
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(length=0)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=BLUE, label="All gold documents retrieved (top-5)"),
                       Patch(color=ORANGE, label="Expected behaviour: answered / abstained / premise corrected (judge)")], loc="lower center", bbox_to_anchor=(0.42, 1.0), ncol=1, fontsize=6.5, frameon=False, labelcolor=INK)
    fig.tight_layout()
    fig.savefig(FIG / "fig1_outcomes_by_type.png", facecolor=SURF); plt.close(fig)


def fig_latency():
    """Small multiples: latency distribution per route (successful requests), shared x-axis."""
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    BLUE, INK, INK2, GRID, SURF = "#2a78d6", "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    lat = pd.read_csv(RES / "latency.csv"); lat = lat[lat.status == 200]
    routes = [("/v1/chat/completions", "Retrieval + generation"), ("/v1/context", "Retrieval only")]
    fig, axes = plt.subplots(2, 1, figsize=(6.6, 2.8), dpi=200, sharex=True)
    fig.patch.set_facecolor(SURF)
    bins = [i * 0.1 for i in range(0, 36)]
    for ax, (route, name) in zip(axes, routes):
        x = lat[lat.route == route].latency_s.clip(upper=3.5)
        ax.set_facecolor(SURF)
        ax.hist(x, bins=bins, color=BLUE, edgecolor=SURF, linewidth=1)
        med = x.median()
        ax.axvline(med, color=INK, linewidth=1, linestyle=(0, (3, 2)))
        ax.text(med + 0.12, ax.get_ylim()[1] * 0.85, f"median {med:.2f} s", fontsize=6.5, color=INK2)
        ax.set_title(f"{name}  (n={len(x)})", fontsize=7.5, color=INK, loc="left")
        ax.yaxis.grid(True, color=GRID, linewidth=0.6); ax.set_axisbelow(True)
        for s in ax.spines.values(): s.set_visible(False)
        ax.tick_params(length=0, labelsize=6.5, colors=INK2)
        ax.set_ylabel("requests", fontsize=6.5, color=INK2)
    axes[-1].set_xlabel("client-side latency (s), values above 3.5 s shown at 3.5", fontsize=6.5, color=INK2)
    fig.tight_layout()
    fig.savefig(FIG / "fig2_latency.png", facecolor=SURF); plt.close(fig)


def main():
    tests = {t["id"]: t for t in json.loads((ROOT / "data" / "testset.json").read_text(encoding="utf-8"))}
    per_q = pd.read_csv(RES / "retrieval_per_question.csv")
    s = {"coverage": load_json(RES / "coverage_summary.json"), "retrieval": load_json(RES / "retrieval_analysis.json"),
         "system_tests_raw": "results/system_tests.json"}
    s["abstention"] = {"must_abstain_n": int((per_q.expected == "abstain").sum()), "must_abstain_abstained": int(per_q[per_q.expected == "abstain"].abstained.sum()),
                       "answerable_n": int((per_q.expected == "answer").sum()), "answerable_false_abstentions": per_q[(per_q.expected == "answer") & per_q.abstained].id.tolist(),
                       "false_premise_abstained": per_q[(per_q.question_type == "false_premise") & per_q.abstained].id.tolist()}
    multi = per_q[per_q.question_type == "multi_hop"]
    s["multi_hop"] = {"both_docs_retrieved": int(multi.all_gold_found.sum()), "n": len(multi), "mean_distinct_docs_in_top5": round(multi.n_distinct_docs.mean(), 2)}
    s["ragas"], _ = ragas_block(tests)
    sysr = load_json(RES / "system_tests.json")
    if sysr:
        s["system_tests"] = {
            "error_cases": {k: v["status"] for k, v in sysr["errors"].items()},
            "params_ignored": all(v.get("n_choices", 1) == 1 and (v.get("usage") or {}).get("completion_tokens", 99) == 99 for k, v in sysr["params"].items() if k in ("stream_true", "max_tokens_5", "n_2")),
            "determinism": {k: {x: y for x, y in v.items() if x != "runs"} for k, v in sysr["determinism"].items()},
            "multiturn": {k: v.get("answer") for k, v in sysr["multiturn"].items()},
            "security": {k: (v.get("answer") or "")[:200] for k, v in sysr["security"].items()},
            "robustness": {k: {"gold_retrieved": v.get("gold_source_retrieved"), "answer": (v.get("answer") or "")[:160]} for k, v in sysr["robustness"].items()},
        }
    (RES / "summary.json").write_text(json.dumps(s, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    prem = (s["ragas"].get("mean_by_type") or {}).get("false_premise", {}).get("premise_corrected") if s["ragas"]["status"] == "done" else None
    fig_outcomes(per_q, prem)
    fig_latency()
    print("ragas:", s["ragas"]["status"]); print(json.dumps(s["ragas"], indent=1, default=str)[:3000])
    print("wrote results/summary.json and results/figures/")


if __name__ == "__main__":
    main()
