"""Ragas evaluation of the endpoint's outputs (LLM-as-a-judge on Lehmus AI; university VPN required).

Metric choice (see report):
  answerable questions (single_hop_body, single_hop_abstract, multi_hop, paraphrase)
    faithfulness                          answer claims supported by the retrieved chunks?   (generation, needs contexts)
    answer_relevancy  (ResponseRelevancy) does the answer address the question? (penalises "I don't know") (needs embeddings)
    llm_context_precision_with_reference  are the relevant chunks ranked high?               (retrieval)
    context_recall    (LLMContextRecall)  do the chunks contain the reference answer's claims? (retrieval)
    factual_correctness (mode=recall)     does the answer contain the reference answer's claims? (end-to-end)
       recall mode on purpose: our references are short, the endpoint's answers are longer; precision/F1
       would penalise correct extra detail. Unsupported extra detail is caught by faithfulness instead.
    id_based_context_recall/precision     gold document among the retrieved chunks? (no LLM; document ids)
  false_premise questions: faithfulness + AspectCritic 'premise_corrected'
  must-abstain questions (unindexed_doc, inventory_mismatch, out_of_corpus): AspectCritic 'appropriate_abstention'
     (faithfulness etc. are undefined / meaningless when there is no correct answer to retrieve)

Caching: every (judge, id, metric) score is stored in results/ragas/scores_<judge>.csv; already scored
combinations are skipped, so an interrupted or repeated run never re-queries the judge.

Usage:
  python src/ragas_eval.py --judge big                 # main judge: GPT OSS 120B, all items
  python src/ragas_eval.py --judge small               # second judge: Gemma4 26B, for judge agreement
  python src/ragas_eval.py --judge big --run_tag rerun2 --ids B01,B03,...   # judge stability check
  options: --metrics faithfulness,factual_correctness  --workers 4
"""
import argparse, json, os, sys, time, warnings
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

ANSWERABLE = {"single_hop_body", "single_hop_abstract", "multi_hop", "paraphrase"}
ABSTAIN = {"unindexed_doc", "inventory_mismatch", "out_of_corpus"}
ALL_METRICS = ["faithfulness", "answer_relevancy", "llm_context_precision_with_reference", "context_recall",
               "factual_correctness", "id_based_context_recall", "id_based_context_precision", "premise_corrected", "appropriate_abstention"]


def metrics_for(qtype):
    if qtype in ANSWERABLE:
        return ["faithfulness", "answer_relevancy", "llm_context_precision_with_reference", "context_recall", "factual_correctness",
                "id_based_context_recall", "id_based_context_precision"]
    if qtype == "false_premise":
        return ["faithfulness", "premise_corrected"]
    return ["appropriate_abstention"]


def build_metric(name, llm, emb):
    from ragas.metrics import (Faithfulness, ResponseRelevancy, LLMContextPrecisionWithReference, LLMContextRecall,
                               FactualCorrectness, AspectCritic, IDBasedContextRecall, IDBasedContextPrecision)
    from ragas.metrics.base import MetricType
    if name == "faithfulness": return Faithfulness(llm=llm)
    if name == "answer_relevancy": return ResponseRelevancy(llm=llm, embeddings=emb, strictness=3)
    if name == "llm_context_precision_with_reference": return LLMContextPrecisionWithReference(llm=llm)
    if name == "context_recall": return LLMContextRecall(llm=llm)
    if name == "factual_correctness": return FactualCorrectness(llm=llm, mode="recall")
    if name == "id_based_context_recall": return IDBasedContextRecall()
    if name == "id_based_context_precision": return IDBasedContextPrecision()
    if name == "premise_corrected":
        return AspectCritic(name="premise_corrected", llm=llm,
                            definition=("The user's question contains a false assumption; the reference explains why it is false. "
                                        "Return 1 if the response explicitly points out or corrects the false assumption instead of answering as if it were true. "
                                        "Return 0 if the response accepts the false premise, or only says it does not know."),
                            required_columns={MetricType.SINGLE_TURN: {"user_input", "response", "reference"}})
    if name == "appropriate_abstention":
        return AspectCritic(name="appropriate_abstention", llm=llm,
                            definition=("The question cannot be answered from the system's knowledge base. Return 1 if the response declines, "
                                        "or clearly states that it does not know / that the information is not available, without asserting any "
                                        "substantive answer. Return 0 if the response asserts an answer (even a partly hedged one)."))
    raise ValueError(name)


DUP = {"017": "037", "037": "017", "028": "039", "039": "028", "043": "058", "058": "043"}


def make_sample(t, r):
    from ragas.dataset_schema import SingleTurnSample
    ret_ids = [c["source"][:3] for c in r["contexts"]]
    ref_ids = [s[:3] for s in t["source_documents"]]
    # a retrieved duplicate copy of a gold document counts as that document
    ret_ids = [next((g for g in ref_ids if DUP.get(x) == g), x) for x in ret_ids]
    return SingleTurnSample(user_input=t["question"], response=r["answer"] or "", reference=t["reference_answer"],
                            retrieved_contexts=[c["text"] for c in r["contexts"]] or [""],
                            retrieved_context_ids=ret_ids, reference_context_ids=ref_ids or ["none"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", choices=["big", "small"], default="big")
    ap.add_argument("--ids", default="", help="comma-separated item ids (default: all)")
    ap.add_argument("--metrics", default="", help="comma-separated subset of metrics")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--run_tag", default="main", help="label; use a new tag to deliberately re-score (stability check)")
    a = ap.parse_args()

    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import evaluate, EvaluationDataset, RunConfig
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper

    model = os.environ["JUDGE_MODEL"] if a.judge == "big" else os.environ["SMALL_MODEL"]
    llm = LangchainLLMWrapper(ChatOpenAI(model=model, base_url=os.environ["LEHMUS_BASE_URL"], api_key=os.environ["LEHMUS_API_KEY"],
                                         temperature=0, max_tokens=8192, timeout=300, max_retries=2))
    emb = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model=os.environ["EMBED_MODEL"], base_url=os.environ["LEHMUS_BASE_URL"],
                                                      api_key=os.environ["LEHMUS_API_KEY"], check_embedding_ctx_length=False))

    tests = {t["id"]: t for t in json.loads((ROOT / "data" / "testset.json").read_text(encoding="utf-8"))}
    resp = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "data" / "responses.jsonl").open(encoding="utf-8")}
    ids = [i for i in (a.ids.split(",") if a.ids else tests) if i in resp]
    want = set(a.metrics.split(",")) if a.metrics else set(ALL_METRICS)

    out_dir = ROOT / "results" / "ragas"; out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"scores_{a.judge}.csv"
    done = pd.read_csv(out) if out.exists() else pd.DataFrame(columns=["run_tag", "id", "metric", "score"])
    done_keys = set(zip(done.run_tag, done.id, done.metric))

    for metric in ALL_METRICS:
        if metric not in want:
            continue
        todo = [i for i in ids if metric in metrics_for(tests[i]["question_type"]) and (a.run_tag, i, metric) not in done_keys]
        if not todo:
            continue
        print(f"[{a.judge}] {metric}: scoring {len(todo)} items", flush=True)
        ds = EvaluationDataset(samples=[make_sample(tests[i], resp[i]) for i in todo])
        t0 = time.time()
        res = evaluate(ds, metrics=[build_metric(metric, llm, emb)], run_config=RunConfig(max_workers=a.workers, timeout=600, max_retries=3),
                       show_progress=False, raise_exceptions=False)
        df = res.to_pandas()
        col = [c for c in df.columns if c not in ("user_input", "response", "reference", "retrieved_contexts", "retrieved_context_ids", "reference_context_ids")][-1]
        rows = pd.DataFrame({"run_tag": a.run_tag, "id": todo, "metric": metric, "score": df[col].values,
                             "judge_model": model, "seconds": round(time.time() - t0, 1)})
        done = pd.concat([done, rows], ignore_index=True)
        done.to_csv(out, index=False)  # save after every metric
        print(f"   mean={rows.score.mean():.3f}  NaN={rows.score.isna().sum()}  ({time.time() - t0:.0f}s)", flush=True)
    print("saved", out)


if __name__ == "__main__":
    main()
