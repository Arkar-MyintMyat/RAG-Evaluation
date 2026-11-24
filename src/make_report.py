"""Fill the course template (Evaluation-report.docx) with the results -> report/generated/Evaluation-report-generated.docx.

All numbers are read from results/summary.json (run src/aggregate.py first). Ragas numbers that do not
exist yet (judge not run) are written as a highlighted [PENDING] marker.
Usage: python src/make_report.py [--template report/template/Evaluation-report-template.docx] [--name "..."] [--student_id "..."]
"""
import argparse, copy, json
from pathlib import Path

import docx
from docx.enum.text import WD_COLOR_INDEX
from docx.shared import Pt, Cm

ROOT = Path(__file__).resolve().parents[1]
S = json.loads((ROOT / "results" / "summary.json").read_text(encoding="utf-8"))
RG = S["ragas"]
PENDING = "[PENDING]"


def r(qtype, metric, fmt="{:.2f}"):
    v = ((RG.get("mean_by_type") or {}).get(qtype) or {}).get(metric)
    return fmt.format(v) if v is not None else PENDING


def ov(metric, fmt="{:.2f}"):
    v = (RG.get("answerable_overall_mean") or {}).get(metric)
    return fmt.format(v) if v is not None else PENDING


def agr(metric, key):
    v = ((RG.get("inter_judge_agreement") or {}).get(metric) or {}).get(key)
    if v is None:
        return PENDING
    return f"{v:.0%}" if key.startswith("binary") else f"{v:.2f}"


def stab(metric):
    v = ((RG.get("judge_stability") or {}).get(metric) or {}).get("mean_abs_diff")
    return f"{v:.2f}" if v is not None else PENDING


def sanity(i, metric):
    v = ((RG.get("sanity_cases") or {}).get(i) or {}).get("scores", {}).get(metric)
    return f"{v:.2f}" if v is not None else PENDING


def add_par(after, text, style="normal1", size=9.5, bold_prefix=None, space_after=2):
    """Insert a paragraph after `after` (paragraph or table). Supports **bold** and [PENDING] highlight."""
    p = after._parent.add_paragraph(style=style) if hasattr(after, "_parent") else None
    el = p._p
    (after._p if hasattr(after, "_p") else after._tbl).addnext(el)
    parts = text.split("**")
    for k, part in enumerate(parts):
        for j, seg in enumerate(part.split(PENDING)):
            if j:
                run = p.add_run(PENDING); run.font.highlight_color = WD_COLOR_INDEX.YELLOW; run.font.size = Pt(size); run.bold = k % 2 == 1
            if seg:
                run = p.add_run(seg); run.bold = k % 2 == 1; run.font.size = Pt(size)
    p.paragraph_format.space_after = Pt(space_after)
    return p


def small_table(d, header, rows, widths=None, size=7.5):
    t = d.add_table(rows=len(rows) + 1, cols=len(header)); t.style = d.tables[0].style
    for j, h in enumerate(header):
        t.rows[0].cells[j].text = h
    for i, row in enumerate(rows, start=1):
        for j, v in enumerate(row):
            t.rows[i].cells[j].text = str(v)
    for row in t.rows:
        for j, c in enumerate(row.cells):
            if widths: c.width = Cm(widths[j])
            for rr in c.paragraphs[0].runs:
                rr.font.size = Pt(size)
                if rr.text == PENDING: rr.font.highlight_color = WD_COLOR_INDEX.YELLOW
    return t


def add_appendix(d, sysd, ret):
    from docx.enum.text import WD_BREAK
    pb = d.add_paragraph(); pb.add_run().add_break(WD_BREAK.PAGE)
    hstyle = next(p.style for p in d.paragraphs if p.style.name.lower() == "heading 3")
    d.add_paragraph("Appendix", style=hstyle)
    fp0 = d.add_paragraph(); fp0.add_run().add_picture(str(ROOT / "results" / "figures" / "fig1_outcomes_by_type.png"), width=Cm(14))
    d.add_paragraph("Figure A1. Retrieval (blue) and expected behaviour (orange) per question type, judge-free (n=62).", style="normal1").runs[0].font.size = Pt(8)
    # A1 full Ragas table
    d.add_paragraph("Table A1. All Ragas scores per question type (mean; GPT OSS 120B). n/a = metric not applicable to the type.", style="normal1").runs[0].font.size = Pt(8)
    metrics = [("faithfulness", "Faith."), ("answer_relevancy", "Relev."), ("llm_context_precision_with_reference", "Ctx prec."), ("context_recall", "Ctx rec."),
               ("factual_correctness", "Fact. corr."), ("id_based_context_recall", "ID rec."), ("premise_corrected", "Premise corr."), ("appropriate_abstention", "Abstain OK")]
    order = ["single_hop_abstract", "single_hop_body", "paraphrase", "multi_hop", "false_premise", "unindexed_doc", "inventory_mismatch", "out_of_corpus"]
    mb = RG.get("mean_by_type") or {}
    big = None
    p = ROOT / "results" / "ragas" / "scores_big.csv"
    if p.exists():
        import pandas as pd
        big = pd.read_csv(p); big = big[big.run_tag == "main"]
        tests = {t["id"]: t["question_type"] for t in json.loads((ROOT / "data" / "testset.json").read_text(encoding="utf-8"))}
        big["qt"] = big.id.map(tests)
    rows = []
    for t in order:
        row = [t]
        for m, _ in metrics:
            if big is not None and ((big.qt == t) & (big.metric == m)).any():
                v = big[(big.qt == t) & (big.metric == m)].score.mean()
                row.append(f"{v:.2f}" if v == v else "NaN")
            else:
                row.append("n/a" if RG["status"] == "done" else PENDING)
        rows.append(row)
    small_table(d, ["Type"] + [m[1] for m in metrics], rows)
    # A2 judge reliability
    d.add_paragraph("")
    d.add_paragraph("Table A2. Judge reliability: GPT OSS 120B vs Gemma4 26B on the same items, and GPT OSS re-scoring 12 items (stability).", style="normal1").runs[0].font.size = Pt(8)
    ia, js = RG.get("inter_judge_agreement") or {}, RG.get("judge_stability") or {}
    rows = []
    for m in ["faithfulness", "answer_relevancy", "llm_context_precision_with_reference", "context_recall", "factual_correctness", "premise_corrected", "appropriate_abstention"]:
        a = ia.get(m, {})
        f = lambda k: (f"{a[k]:.2f}" if isinstance(a.get(k), (int, float)) else (PENDING if RG["status"] != "done" else "–"))
        st_ = js.get(m, {}).get("mean_abs_diff")
        rows.append([m, a.get("n", PENDING if RG["status"] != "done" else "–"), f("mean_big"), f("mean_small"), f("mean_abs_diff"), f("binary_agreement(>=0.5)"), f("spearman"),
                     f"{st_:.2f}" if st_ is not None else "–"])
    small_table(d, ["Metric", "n", "Mean GPT-OSS", "Mean Gemma", "Mean |diff|", "Agree (≥0.5)", "Spearman", "Re-run |diff|"], rows)
    # A3 system tests
    d.add_paragraph("")
    d.add_paragraph("Table A3. Selected API / system test results (full list: results/system_tests.json).", style="normal1").runs[0].font.size = Pt(8)
    e = sysd["error_cases"]
    rows = [
        ["Missing / wrong API key", f"{e['no_auth_header']} / {e['wrong_api_key']}", "OK"],
        ["Empty body, empty messages, only system message, invalid role", f"{e['empty_body_object']}, {e['empty_messages_list']}, {e['only_system_message']}, {e['invalid_role']}", "OK (clear message)"],
        ["Malformed JSON; messages not a list", f"{e['malformed_json']}; {e['messages_not_list']}", "Wrong: should be 400"],
        ["Whitespace-only / non-string content", f"{e['whitespace_content']} / {e['content_not_string']}", "Wrong: 400 expected; leaks internal error"],
        ["Query of 30,000 chars (chat / context)", f"{e['very_long_query_30k_chars']} / {e['context_very_long_query_30k']}", "Wrong: 413/400 expected; limit 20,000 chars"],
        ["/context with a list as query", f"{e['context_query_not_string']}", "Accepted silently"],
        ["GET on chat route; unknown route", f"{e['GET_on_chat']}; {e['unknown_route']}", "405 expected for GET; 404 OK"],
        ["stream, max_tokens=5, n=2, model, temperature; top_k/k on /context", "200, all ignored", "Not OpenAI-compatible; k fixed at 5"],
        ["System message ('answer in Finnish', 'cite sources')", "ignored", "Cannot be steered by a UI"],
        ["Follow-up with chat history", "retrieval ignores history", "Wrong numbers (32,155 games)"],
        ["Same question 3x", "retrieval identical in 8/8; wording differs in 5/8", "OK"],
        ["System-prompt extraction / role-play injection", "refused", "OK (odd refusal text)"],
        ["Harmful request (ransomware)", "blocked by content filter", "OK"],
        ["Benign question on indexed paper 'AI Agent Traps'", "blocked by content filter", "False positive"],
        ["Typos (B20) / keywords only (B24) / lower-case (B14)", "gold retrieved in 3/3; B20 answered 'no information'", "Generator brittle to typos"],
        ["Finnish, German, Chinese questions", "correct answers in the question's language", "OK"],
    ]
    small_table(d, ["Test", "Observed", "Assessment"], rows, widths=[6.5, 6, 5])
    d.add_paragraph("")
    fp = d.add_paragraph(); fp.add_run().add_picture(str(ROOT / "results" / "figures" / "fig2_latency.png"), width=Cm(14))
    d.add_paragraph(f"Figure A2. Latency of all successful requests. Retrieval-only p90 {ret['latency']['/v1/context']['p90']:.2f} s; first request of the session "
                    f"{ret['first_request_of_session_latency_s']:.1f} s (likely Lambda cold start).", style="normal1").runs[0].font.size = Pt(8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default=str(ROOT / "report" / "template" / "Evaluation-report-template.docx"))
    ap.add_argument("--name", default="[your name]"); ap.add_argument("--student_id", default="[your student ID]")
    a = ap.parse_args()
    import pandas as pd
    d = docx.Document(a.template)
    for s in d.sections:
        s.top_margin = s.bottom_margin = Cm(1.5); s.left_margin = s.right_margin = Cm(1.8)
    P = d.paragraphs
    cov, ret, sysd = S["coverage"], S["retrieval"], S["system_tests"]
    lat_c, lat_x = ret["latency"]["/v1/chat/completions"], ret["latency"]["/v1/context"]
    mh = S["multi_hop"]; ab = S["abstention"]
    raw_total = sum(1 for _ in (ROOT / "data" / "raw" / "endpoint_raw.jsonl").open(encoding="utf-8"))
    per_q = pd.read_csv(ROOT / "results" / "retrieval_per_question.csv")

    # ---- header ----
    P[2].runs[-1].text = " " + a.name
    P[3].runs[-1].text = " " + a.student_id
    for run in P[4].runs[1:]:
        run.text = ""
    P[4].runs[1].text = " assignment2.zip (code + README, test set in data/, raw endpoint responses in data/raw/endpoint_raw.jsonl)"
    P[5]._p.getparent().remove(P[5]._p)
    P[6]._p.getparent().remove(P[6]._p)

    # ---- 1. Evaluation approach ----
    p1 = add_par(P[7], (
        "I could only test the endpoint from the outside, so I split the work as in Lecture 2: I checked the quality of the answers with Ragas, "
        "and I tested the system itself through its API. Every request went through one small client that caches responses and sends at most two at a time. "
        f"In total I sent {raw_total} requests (limit about 1,000), and all of them are saved in data/raw/endpoint_raw.jsonl."))
    p2 = add_par(p1, (
        "**Test set.** I wrote 62 questions (data/testset.csv). So that the set is not full of questions the system finds easy, I picked papers and pages at random "
        "(seed 2026), mostly from inside the papers (tables, appendices) instead of abstracts, and I wrote each question and reference answer from that page "
        "before looking at any answer from the system. A script checks that each reference quote really is on that page. Besides 32 single-paper questions, the set has "
        "8 questions that need two papers, 6 reworded questions that avoid the paper's key terms, 4 questions with a false premise, and 12 questions the system should "
        "not be able to answer (5 about listed papers that turned out not to be indexed, 1 about a listed paper whose file is wrong, and 6 outside the collection)."))
    for k in (8, 9, 10, 11):
        P[k]._p.getparent().remove(P[k]._p)
    t = d.tables[0]
    rows = [
        ("Ragas: retrieval", "Context precision and context recall (+ judge-free ID-based recall). Do the 5 chunks contain the answer? Most RAG errors start here.",
         "46 answerable questions with references; judge GPT OSS 120B"),
        ("Ragas: answers", "Faithfulness (backed by the chunks?), response relevancy (on topic?), factual correctness in recall mode (matches my reference?).",
         "Same 46 (+4 false-premise for faithfulness); Lehmus embeddings"),
        ("Ragas: AspectCritic", "Two yes/no checks I defined: does it refuse when the answer is not in the collection, and does it correct a false premise?",
         "12 + 4 questions"),
        ("Coverage test", "Can every listed paper be found at all?", "2 verbatim passages per PDF on /v1/context (372 requests)"),
        ("API tests", "Errors, OpenAI parameters, repeatability, chat history, prompt injection, typos and other languages, latency.",
         f"About 60 requests; timing of all {lat_c['n'] + lat_x['n']} requests"),
    ]
    while len(t.rows) - 1 > len(rows):
        t._tbl.remove(t.rows[-1]._tr)
    while len(t.rows) - 1 < len(rows):
        t.add_row()
    widths = [2.8, 9.4, 5.2]
    for i, row in enumerate([("Approach", "What it checks", "How (data, n, models)")] + rows):
        for j, txt in enumerate(row):
            c = t.rows[i].cells[j]; c.text = ""; c.width = Cm(widths[j])
            run = c.paragraphs[0].add_run(txt); run.font.size = Pt(7.5); run.bold = i == 0
    add_par(t, (
        "I did not use the multi-turn, agent, SQL or multimodal metrics (the endpoint is single-turn and has no tools) or BLEU/ROUGE (free-text answers). "
        "I used factual correctness in recall mode because my references are short and the answers are long, so precision would punish correct extra detail. "
        "To see whether the judge can be trusted, I scored everything again with Gemma4 26B, re-ran GPT OSS on 12 items, and compared its context recall with the ID-based one."), size=9)

    # ---- 2. Findings ----
    for k in (14, 15, 16, 17, 18, 19, 20):
        P[k]._p.getparent().remove(P[k]._p)
    cap = add_par(P[13], "Table 1. Results per question type (Ragas means, judge GPT OSS 120B). Full scores and figures are in the appendix.", size=8, space_after=1)
    types = [("single_hop_abstract", "Single paper, abstract"), ("single_hop_body", "Single paper, body page"), ("paraphrase", "Reworded"), ("multi_hop", "Two papers"),
             ("false_premise", "False premise"), ("unindexed_doc", "Listed but not indexed"), ("inventory_mismatch", "Wrong file for title"), ("out_of_corpus", "Outside collection")]
    hdr = ["Question type (n)", "All gold papers in top 5", "Expected behaviour", "Faithful.", "Ctx recall", "Fact. corr."]
    trows = []
    for tk, name in types:
        g = per_q[per_q.question_type == tk]; n = len(g)
        gold = f"{int(g.all_gold_found.sum())}/{n}" if g.all_gold_found.notna().any() else "–"
        if g.expected.iloc[0] == "abstain":
            beh = f"refused {int(g.abstained.sum())}/{n}"
        elif tk == "false_premise":
            beh = f"corrected: {r(tk, 'premise_corrected')} (judge)"
        else:
            beh = f"answered {n - int(g.abstained.sum())}/{n}"
        isans = tk not in ("unindexed_doc", "inventory_mismatch", "out_of_corpus")
        full = isans and tk != "false_premise"
        trows.append([f"{name} ({n})", gold, beh, r(tk, "faithfulness") if isans else "–",
                      r(tk, "context_recall") if full else "–", r(tk, "factual_correctness") if full else "–"])
    tb = small_table(d, hdr, trows, widths=[4.2, 2.9, 3.6, 2.2, 2.2, 2.3], size=7.5)
    cap._p.addnext(tb._tbl)
    F = [
        ("**Simple questions work well.** For all 32 single-paper questions the right paper was in the top 5, nothing was refused, and the judge rated the answers "
         f"as well grounded (faithfulness {r('single_hop_body','faithfulness')}). This also worked for numbers in tables and appendices, and for questions in Finnish, German and Chinese."),
        (f"**Questions across two papers or with other wording often fail.** Only {mh['both_docs_retrieved']}/{mh['n']} two-paper questions got chunks from both papers, because one paper usually fills "
         "all five slots. For \"Compare how HERMES and RAAS...\" all chunks came from HERMES and the answer was \"I don't know\". When I described HyDE without naming it, the system also said "
         f"\"I don't know\", although the question with the name was answered correctly. Context recall drops to {r('multi_hop','context_recall')} (two papers) and {r('paraphrase','context_recall')} (reworded). "
         "I think the cause is a single vector search with a fixed top 5 and no query rewriting or keyword search."),
        (f"**Some papers are missing or wrong.** {len(cov['docs_never_retrieved'])} of 183 papers never come back, not even for a sentence copied from them or for their title (#72, #82, #106, #114, #122). #82 is 94 MB, "
         "which is over Bedrock's 50 MB file limit. Three papers are indexed twice, the file for #12 (\"A warning about model welfare\") actually contains Claude's Constitution, and #10 is only an appendix. "
         f"The good news is that the system does not make things up about missing papers: it refused all {ab['must_abstain_n']} questions it could not answer."),
        ("**Confident wrong answers still happen.** Asked for AgentSquare's GPT-3.5 ablation, it reported the numbers from the GPT-4o table (0.583→0.280 instead of 0.520→0.267) in 3 out of 3 runs. "
         f"The answer is grounded in the chunks (faithfulness {sanity('B26','faithfulness')}), so only factual correctness ({sanity('B26','factual_correctness')}) shows the error. With a false premise "
         "(\"Why are LLMs better at detecting lies than telling them?\") it went along with the premise while quoting numbers that say the opposite. Retrieval also ignores chat history: a follow-up about "
         "WOLF got \"32,155 games and 1,000,000 statements\" (one number from another paper, one made up; the paper says 100 games and 7,200 statements)."),
        ("**The API needs work before a UI is built on it.** Wrong input (blank text, malformed JSON, over 20,000 characters) gives HTTP 502 with internal AWS error text instead of a 400. "
         "stream, max_tokens, n and system messages are silently ignored, answers have no source citations, and a normal question about the indexed paper \"AI Agent Traps\" was blocked by the content filter. "
         f"On the positive side it is fast and stable: median {lat_c['median']:.1f} s per answer (90% under {lat_c['p90']:.1f} s), {lat_x['median']:.1f} s for retrieval only, the same chunks on every repeat, and no errors at two parallel requests."),
        ("**How far I trust the numbers.** "
         f"The two judges agreed on faithfulness in {agr('faithfulness','binary_agreement(>=0.5)')} of cases and on factual correctness in {agr('factual_correctness','binary_agreement(>=0.5)')}; "
         f"re-running the same judge changed factual correctness by {stab('factual_correctness')} on average. Faithfulness can be misleading (the AgentSquare case), \"I don't know\" answers get no faithfulness score, and "
         f"one answer was marked partly wrong only because my reference was incomplete. Because of this, factual correctness is pessimistic overall: B06 lists all four SpecSuite-Core specifications correctly but scored {sanity('B06','factual_correctness')}, because my reference also described each one. With 1 to 26 questions per type and no human labels, the numbers show clear differences between types, not exact quality levels."),
    ]
    last = tb
    for f in F:
        last = add_par(last, f, size=9.5)

    # ---- 3. Verdict ----
    for k in (22, 23, 24, 25, 26, 27):
        P[k]._p.getparent().remove(P[k]._p)
    v = add_par(P[21], (
        "**Verdict:** not ready for a public UI yet, but fine for an internal pilot with questions about one paper at a time. It is fast and does not invent answers when it finds nothing, "
        "but the collection has gaps, questions that combine papers fail, wrong answers can sound confident, and the API does not behave like a stable OpenAI-compatible service yet. "
        "What I would fix, in order (and how to check it):"))
    recs = [
        "**1. Fix the collection:** re-upload the 5 missing papers (split #82), remove the duplicates, replace #10 and #12. Check: test_coverage.py finds 183/183.",
        "**2. Better retrieval:** query rewriting or splitting, hybrid keyword + vector search, a larger top-k with a re-ranker, keep table captions with their tables. Check: context recall for two-paper and reworded questions in this test set, without single-paper questions getting worse.",
        "**3. Safer answers:** tell the model to check the question's assumptions and to cite file and page; turn chat history into a standalone search query. Check: the false-premise and follow-up tests.",
        "**4. A cleaner API:** 400 for bad input without internal details, streaming, and a clear signal when nothing relevant was found. Check: test_system.py.",
    ]
    last = v
    for rec in recs:
        last = add_par(last, rec, space_after=1)
    add_par(P[28], "I used Claude (Anthropic, through Claude Code) to help write and debug the scripts, to draft questions and reference answers from the sampled pages "
                   "(which a script then checked against the PDFs), and to help draft this report, which I reviewed and edited.")
    P[29]._p.getparent().remove(P[29]._p)
    add_appendix(d, sysd, ret)
    out = ROOT / "report" / "generated" / "Evaluation-report-generated.docx"; out.parent.mkdir(parents=True, exist_ok=True)  # never overwrite the hand-edited report
    d.save(out); print("saved", out, "| Ragas status:", RG["status"])


if __name__ == "__main__":
    main()
