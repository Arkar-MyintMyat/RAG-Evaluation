"""Send every test-set question to the endpoint (retrieval + generation) and save the responses.
The chat route returns the answer AND the retrieved chunks ('contexts'), so Ragas evaluates exactly
the context the generator saw (no second /v1/context call needed).
Usage: python src/run_testset.py [--testset data/testset.json]
Output: data/responses.jsonl (one line per question; raw HTTP records are in data/raw/endpoint_raw.jsonl)
"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import endpoint as ep

ap = argparse.ArgumentParser(); ap.add_argument("--testset", default=str(ep.ROOT / "data" / "testset.json")); a = ap.parse_args()
items = json.loads(Path(a.testset).read_text(encoding="utf-8"))

def run(it):
    r = ep.chat(it["question"], tag=f"testset:{it['id']}")
    b = r["body"] if isinstance(r["body"], dict) else {}
    msg = (b.get("choices") or [{}])[0].get("message", {})
    return {"id": it["id"], "question_type": it["question_type"], "question": it["question"], "status": r["status"],
            "latency_s": r["latency_s"], "answer": msg.get("content"), "finish_reason": (b.get("choices") or [{}])[0].get("finish_reason"),
            "contexts": b.get("contexts", []), "usage": b.get("usage"), "request_key": r["key"]}

out = ep.run_parallel(run, items)
with (ep.ROOT / "data" / "responses.jsonl").open("w", encoding="utf-8") as f:
    for o in out: f.write(json.dumps(o, ensure_ascii=False) + "\n")
print(len(out), "responses; statuses:", {s: sum(o["status"] == s for o in out) for s in {o["status"] for o in out}}, "| endpoint requests so far:", ep.requests_sent())
