# Assignment 2: Evaluating the LiteratureExplorer RAG endpoint

This is my code and data for Assignment 2. I evaluated XYZ Inc.'s LiteratureExplorer endpoint in two ways:

- **The answers.** I scored them with [Ragas](https://www.ragas.io/), using the Lehmus models as judges.
- **The system.** I tested it through its API: whether all papers can be found, error handling, repeatability, chat history, prompt injection, typos and other languages, and latency.

The report is in `report/Evaluation-report.docx` (a PDF copy is next to it).

## What is where

- `data/testset.csv` / `data/testset.json`: my 62 test questions. Each one has its question type, the expected behaviour, a reference answer, the source paper and page, and a quote from the paper that backs up the reference.
- `data/raw/endpoint_raw.jsonl`: every request I sent to the endpoint and the full response, with status code, latency and time. The scripts also use this file as a cache.
- `data/responses.jsonl`: just the test-set answers and their retrieved chunks, in an easier format.
- `results/`: outputs of all the scripts. This includes the Ragas scores in `results/ragas/`, the figures, and `summary.json`, which holds every number used in the report.
- `src/`: the scripts (described below).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # on Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # on Linux/macOS: cp .env.example .env
```

Then put the endpoint URL and key and the Lehmus URL and key into `.env`. The keys are never in the code, and `.env` is in `.gitignore`.

The endpoint works from anywhere. The Lehmus models only work through the university VPN. Eduroam was not enough for me; I had to use the OpenVPN profile from the university VPN portal.

## How to run it

All endpoint calls go through `src/endpoint.py`:

- It never sends the same request twice; it reads the answer from the cache file instead.
- It sends at most 2 requests at a time.
- On a 429 or 502 it waits before trying again.
- It stops at 950 requests.

Because the cache file is included, you can re-run the endpoint scripts below without sending any new requests.

Run everything from the `assignment2` folder. On Windows I used `python -X utf8` so the paper text prints correctly.

1. **Extract the paper text.** `python -X utf8 src/extract_papers.py --zip data/papers_zip/papers.zip`
   - Only needed if you want to rebuild the test set or the coverage probes.
   - It needs the 1 GB papers.zip from the assignment page, which I did not include.
   - Then run `python -X utf8 src/build_inventory.py`.
2. **Coverage test.** `python -X utf8 src/test_coverage.py`
   - Sends two copied sentences from every paper to `/v1/context` and checks whether that paper comes back.
3. **Test set.**
   - `python -X utf8 src/sample_pages.py --seed 2026` picks the random pages.
   - `python -X utf8 src/build_testset.py` writes the test set and checks every quote against the PDF.
4. **Ask the endpoint the test questions.** `python -X utf8 src/run_testset.py`
5. **System tests.** `python -X utf8 src/test_system.py`
   - Covers error handling, parameters, repeats, chat history, prompt injection, typos and other languages.
6. **Retrieval, chunk and latency analysis.** `python -X utf8 src/analyze_retrieval.py`
   - No judge needed.
7. **Ragas (needs the VPN).** `python -X utf8 src/run_all_judging.py`
   - GPT OSS 120B scores everything.
   - Gemma4 26B scores everything again, to see if the judges agree.
   - GPT OSS re-scores 12 items, to see if it gives the same scores twice.
   - Finally it rebuilds the summary and the report.
   - Judge scores are saved per item and metric in `results/ragas/scores_*.csv`, so finished scores are not requested again.
   - To score only some items or metrics: `python -X utf8 src/ragas_eval.py --judge big --ids B01,B26 --metrics faithfulness`.
8. **Rebuild only the figures and report.**
   - `python -X utf8 src/aggregate.py`
   - then `python -X utf8 src/make_report.py --name "Your Name" --student_id "123456"`
   - `make_report.py` writes to `report/generated/`, so it never overwrites my hand-edited `report/Evaluation-report.docx`.
   - To copy fresh numbers into the edited report: `python -X utf8 src/fill_pending.py`. It only replaces yellow `[PENDING]` markers.
   - `python -X utf8 src/style_tables.py` gives the added tables compact rows and borders.
9. **Make the submission ZIP.** `python -X utf8 src/make_zip.py`
   - Leaves out `.env`, `.venv` and the papers.

## Which Ragas metrics I used

- **Questions with an answer in the papers** (single paper, two papers, reworded):
  - Retrieval: context precision and context recall.
  - Answers: faithfulness, response relevancy, and factual correctness in recall mode.
  - Plus an ID-based context recall that only checks whether the right paper was retrieved. It needs no judge.
- **False-premise questions:** faithfulness, plus a yes/no AspectCritic check that asks whether the answer corrects the premise.
- **Questions the system cannot answer** (missing papers, outside the collection): a yes/no AspectCritic check that asks whether it refuses instead of making something up.

The report explains why I chose these and left out the others.

## How I made the test set

1. I picked papers and pages at random (seed 2026), mostly pages from inside the papers rather than the abstract. This was to avoid writing only questions the system would find easy.
2. For each page I wrote a question and a reference answer from that page alone, before looking at any of the system's answers.
3. `build_testset.py` checks that every evidence quote really appears on that page of the PDF.
4. 4 of the 30 random pages were reference lists, so I dropped them.

The final 62 questions:

| Questions | Type |
|---|---|
| 26 | single paper, from a body page |
| 6 | single paper, from the abstract (easy baseline) |
| 8 | need two papers |
| 6 | reworded versions of body questions, without the key terms |
| 4 | false premise |
| 5 | about listed papers that are not indexed |
| 1 | about a listed paper whose file contains a different document |
| 6 | outside the collection |

## Endpoint requests used

I used 494 of the roughly 1,000 allowed requests:

- 372 for the coverage test
- 62 for the test set
- about 60 for the system tests
- 3 manual curl tests at the start

`python -X utf8 src/endpoint.py` prints the current count.
