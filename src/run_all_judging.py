"""One command for everything that needs the Lehmus judge (university VPN required), then refresh outputs.
Steps (each cached / resumable; re-running never re-scores what is already done):
  1. GPT OSS 120B ('big') scores all items with all applicable metrics       (main results)
  2. Gemma4 26B ('small') scores all items                                     (inter-judge agreement)
  3. GPT OSS 120B re-scores 12 answerable items on faithfulness + factual_correctness (judge stability)
  4. aggregate.py (tables, figure, summary.json) and make_report.py (report/Evaluation-report.docx)
Usage: python src/run_all_judging.py [--skip_small] [--workers 4]
"""
import argparse, subprocess, sys
from pathlib import Path

HERE = Path(__file__).parent
STABILITY_IDS = "B01,B03,B07,B11,B15,B19,B23,B26,A02,A05,M03,M06"

ap = argparse.ArgumentParser(); ap.add_argument("--skip_small", action="store_true"); ap.add_argument("--workers", default="4"); a = ap.parse_args()
py = [sys.executable, "-X", "utf8"]
steps = [[*py, str(HERE / "ragas_eval.py"), "--judge", "big", "--workers", a.workers]]
if not a.skip_small:
    steps.append([*py, str(HERE / "ragas_eval.py"), "--judge", "small", "--workers", a.workers])
steps += [[*py, str(HERE / "ragas_eval.py"), "--judge", "big", "--run_tag", "rerun2", "--ids", STABILITY_IDS, "--metrics", "faithfulness,factual_correctness", "--workers", a.workers],
          [*py, str(HERE / "aggregate.py")], [*py, str(HERE / "make_report.py")]]
for s in steps:
    print(">>", " ".join(s[3:]), flush=True)
    if subprocess.run(s).returncode != 0:
        sys.exit(f"step failed: {' '.join(s[3:])}")
print("All done. Open report/Evaluation-report.docx and review the Ragas paragraphs (search for [PENDING] - there should be none).")
