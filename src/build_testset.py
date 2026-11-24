"""Build the test set (data/testset.json + data/testset.csv) and verify every evidence quote.

How the items were made (see README / report):
  * Documents and pages were drawn at random (src/sample_pages.py, seed 2026), NOT chosen by
    looking at what the endpoint retrieves -> no bias toward questions the system finds easy.
  * Question + reference answer were written (with AI assistance) from the sampled page only.
    Every answerable item carries a verbatim evidence quote; this script checks that the quote
    really occurs on the stated page of the source PDF (whitespace/hyphenation-insensitive).
  * Sampled pages that turned out to be reference lists were discarded (4 of 30).

Question types
  single_hop_body      fact from a random body page (incl. tables/appendices)    -> expected: answer
  single_hop_abstract  fact from the first content page (easy baseline)           -> expected: answer
  multi_hop            needs two documents (comparison / synthesis)               -> expected: answer
  paraphrase           re-wording of a single_hop_body item without its keywords  -> expected: answer
  false_premise        question with a wrong assumption about a corpus paper      -> expected: correct_premise
  unindexed_doc        fact from a listed document that is NOT in the index       -> expected: abstain
  inventory_mismatch   listed title whose file holds a different document         -> expected: abstain
  out_of_corpus        in-domain or off-topic question the corpus cannot answer   -> expected: abstain

Usage: python src/build_testset.py
"""
import csv, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = {json.loads(l)["source"][:3]: json.loads(l) for l in (ROOT / "data" / "papers_text.jsonl").open(encoding="utf-8")}


def S(n):  # source filename from its 3-digit number
    return DOCS[n]["source"]


# (id, type, question, reference, [(doc_no, page_1based, evidence_quote), ...], expected, extra)
ITEMS = [
    # ---------------- single_hop_body (random body pages) ----------------
    ("B01", "single_hop_body", "How many categories and cases does the OmniScientist demonstration suite contain, and which dataset represents gravitational waves?",
     "The demonstration suite has 5 categories and 36 cases, each with one real downloadable dataset. Gravitational waves are represented by GWOSC (LIGO-Virgo Collaboration, 2021) with 1,500 samples.",
     [("100", 4, "The demonstration suite: 5 categories, 36 cases")], "answer", {"subtype": "table"}),
    ("B02", "single_hop_body", "In the study of whether LLM agents are behaviorally coherent for social simulation, which behavioral tests did models tend to pass, and what does this imply?",
     "Models mostly passed Tests 1 and 5 (pass rates 5/9 and 7/9), which capture broad, surface-level trends, but systematically failed tests requiring deeper internal coherence (Tests 3 and 4: 0/9). The pattern holds across model sizes and families, so the inconsistencies are general rather than idiosyncratic.",
     [("069", 8, "while models capture broad, surface-level trends (Tests 1 and 5), they systematically fail tests requiring deeper internal coherence")], "answer", {"subtype": "table"}),
    ("B03", "single_hop_body", "How did Meta-Harness compare with ACE and MCE on online text classification in accuracy and context usage?",
     "The selected Meta-Harness reached 48.6% accuracy, outperforming ACE by 7.7 points and MCE by 8.6 points, while using only 11.4K context tokens versus 50.8K for ACE and 28.5K for MCE.",
     [("044", 7, "The selected Meta-Harness2 reaches 48.6% accuracy, outperforming ACE by 7.7 points and MCE by 8.6 points")], "answer", {"subtype": "numeric"}),
    ("B04", "single_hop_body", "In the AutoGen paper's example of autonomous math problem solving with ChatGPT and the Wolfram Alpha plugin, what went wrong?",
     "The response from Wolfram Alpha contained the correct answer, but ChatGPT selected the wrong one.",
     [("064", 34, "The response from Wolfram contains the correct answer, but ChatGPT selected the wrong one")], "answer", {"subtype": "appendix"}),
    ("B05", "single_hop_body", "Which conversational agent was deployed in the study 'Towards Mutual Theory of Mind in Human-AI Interaction', and in what setting?",
     "A community-facing question-answering conversational agent named Jill Watson was deployed in an online class discussion forum to answer students' class logistics questions throughout a semester; students' bi-weekly perceptions of it were collected and linguistic features were extracted from student-JW conversations.",
     [("025", 4, "we deployed a community-facing (QA)CA named “Jill Watson (JW)” in an online class discussion forum")], "answer", {}),
    ("B06", "single_hop_body", "Which four specifications make up the SpecSuite-Core benchmark in the TDAD paper?",
     "SpecSuite-Core contains four specifications: SupportOps (customer service), DataInsights (SQL analytics), IncidentRunbook (on-call assistant) and ExpenseGuard (spending/expense policies).",
     [("150", 6, "SpecSuite-Core is small (4 specs) but auditably rigorous")], "answer", {"subtype": "table"}),
    ("B07", "single_hop_body", "Which models and datasets were used to implement and evaluate HyDE?",
     "HyDE was implemented with InstructGPT (text-davinci-003, sampled at temperature 0.7) as the generator and Contriever (English) / mContriever (non-English) as encoders. It was evaluated on TREC DL19 and DL20 (MS MARCO based), six low-resource BEIR datasets, and Swahili, Korean, Japanese and Bengali from Mr.TyDi.",
     [("039", 4, "We implement HyDE using InstructGPT, a GPT-3 model from the instruct series (text-davinci-003")], "answer", {"duplicate_of": "028"}),
    ("B08", "single_hop_body", "In MatrAIx, what does the cohort strategy of an application-task contract specify?",
     "The cohort strategy is a query over the shared Persona 8B schema: it specifies persona-schema filters (admissible values), the sampling mode, stratification fields, sample size, weights and seed policy. It makes the target audience explicit and allows the cohort to be redrawn; it does not alter persona records or fill unknown fields.",
     [("080", 36, "The cohort strategy is a query over the shared Persona 8B schema")], "answer", {"subtype": "appendix"}),
    ("B09", "single_hop_body", "According to the paper re-examining why human-AI interaction is uniquely difficult to design, which two sources of complexity cause the design challenges?",
     "AI's capability uncertainty (what the system can do is uncertain and evolves) and the complexity of its outputs. Level-one systems with known capabilities and few possible outputs are sufficiently covered by existing HCI methods.",
     [("022", 8, "These challenges stem from AI’s capability uncertainty and output complexity")], "answer", {}),
    ("B10", "single_hop_body", "What are the two principal bottlenecks for embodied agents identified in RescueBench's stage-level diagnosis?",
     "(1) Exploration collapse under multimodal uncertainty (stage S1, the dominant bottleneck) and (2) spatial memory degradation for compositional return navigation (stage S3).",
     [("153", 8, "exploration collapse under uncertainty (S1) and spatial memory degradation for compositional return navigation (S3)")], "answer", {}),
    ("B11", "single_hop_body", "In SkillsBench, how do pass rates change with the number of Skills attached to a task?",
     "With 1 Skill pass rate rises from 32.2% to 50.2% (+18.0), with 2-3 Skills from 34.4% to 53.4% (+19.0), but with 4 or more Skills only from 34.8% to 44.9% (+10.1). One to three Skills work best; four or more show diminishing returns.",
     [("142", 28, "One to three Skills remain strongest")], "answer", {"subtype": "table"}),
    ("B12", "single_hop_body", "How do Memory-R1 and Mem0 differ in when they form candidate memories?",
     "Both extract and summarize ongoing dialogue into candidate memories for later updating; Memory-R1 does so at each turn, whereas Mem0 forms candidate memories from the new message pair, using a conversation summary and recent messages as context.",
     [("011", 12, "Memory-R1 does so at each turn, while Mem0 forms candidate memories from the new message pair")], "answer", {}),
    ("B13", "single_hop_body", "Why can promising ChatGPT a monetary reward improve its responses, according to 'Prompt engineering as a new 21st century skill'?",
     "It is suggested to be an artifact of the training data: internet forum requests that promised money for help received more verbally rich, rigorous and meticulous answers, so ChatGPT imitates those responses when similar tokens appear in the prompt.",
     [("006", 10, "It has been suggested that this is an artifact of the dataset that was used for the ChatGPT training")], "answer", {}),
    ("B14", "single_hop_body", "When agents discovered by Meta Agent Search (ADAS) on MGSM were transferred to GSM8K and GSM-Hard, how much did they improve over baselines?",
     "They improved accuracy by 25.9% on GSM8K and 13.2% on GSM-Hard compared with the baselines; they also transferred to non-math domains (MMLU, DROP), outperforming hand-designed baselines.",
     [("046", 8, "our agents improve accuracy by 25.9% on GSM8K and 13.2% on GSM-Hard")], "answer", {"subtype": "numeric"}),
    ("B15", "single_hop_body", "What is SELFCOMPACT and how does it decide when to compress an agent's context?",
     "SELFCOMPACT is a training-free scaffold that pairs an inline compaction tool the model invokes itself with a lightweight rubric: compaction should fire when a sub-task has resolved or the trajectory is converging, and be suppressed mid-derivation or when stuck. The model emits <summarize>, and the same model acts as rubric judge and summarizer, instead of using a fixed token threshold.",
     [("042", 2, "We propose SELFCOMPACT, a scaffold that pairs two inference-time elements")], "answer", {}),
    ("B16", "single_hop_body", "How do contemporary multimodal LLMs differ from classic voice assistants in how they process speech?",
     "Classic voice assistants used cascaded pipelines (speech recognition -> NLP intent detection -> text-to-speech), which stripped prosody and led to robotic intonation and rigid turn-taking. Multimodal LLMs such as GPT-4o and SeamlessM4T treat audio as a native modality end-to-end, preserving speech nuance, approaching human conversational latency, and supporting interruption, backchanneling and expressive intonation.",
     [("009", 2, "Classic voice assistants operated through cascaded pipelines")], "answer", {}),
    ("B17", "single_hop_body", "What average review rating did DeepScientist's papers receive, and how does it compare with ICLR 2025 submissions?",
     "DeepScientist's papers received an average rating of 5.00, close to the 5.08 average of all ICLR 2025 submissions, with two of its papers scoring 5.67.",
     [("085", 8, "the system’s average rating (5.00) closely mirrors the average of all ICLR 2025 submissions (5.08)")], "answer", {"subtype": "numeric"}),
    ("B18", "single_hop_body", "Describe the three-step semantic query optimization method in AgenticData.",
     "(1) Apply equivalent cost-optimization rules to the logical plan without degrading quality (e.g., move semantic operators after relational filters); (2) optimize join orders with a dynamic-programming algorithm; (3) cascading optimization that first uses embeddings, then smaller LLMs for filtering, and finally larger LLMs to verify results.",
     [("110", 3, "We propose a three-step semantic query optimization method to reduce the cost")], "answer", {}),
    ("B19", "single_hop_body", "Which three methods for creating agent profiles are described in 'A Survey on Large Language Model based Autonomous Agents'?",
     "The handcrafting method (manually specified profiles; flexible but labor-intensive), the LLM-generation method (profiles generated automatically by LLMs from rules and seed examples; less precise control), and the dataset alignment method (profiles derived from real-world datasets such as ANES demographics).",
     [("008", 5, "Dataset Alignment Method: in this method, the agent profiles are obtained from real-world datasets")], "answer", {}),
    ("B20", "single_hop_body", "In the ShadAR workshop study, how many prompts did participants generate and how many were turned into shaders?",
     "Participants generated 63 prompts, of which 26 were used to create shaders with ShadAR. (Five groups of 4-5 people shared one Quest headset in a ~90-minute session; four application scenarios were identified.)",
     [("132", 7, "In total, the participants generated 63 prompts, of which 26 were used to create shaders with ShadAR")], "answer", {"subtype": "numeric"}),
    ("B21", "single_hop_body", "Which benchmark is used in the study 'What Does It Take to Be a Good AI Research Agent?', and what did the study conclude?",
     "It uses MLE-bench, a machine-learning benchmark of 75 Kaggle tasks. It concludes that ideation diversity is a key bottleneck for AI research agents, confirmed by a large-scale trajectory analysis and a controlled experiment, and recommends diversity-aware methods and multiple evaluation metrics.",
     [("087", 12, "MLE-bench (Chan et al., 2025), the benchmark used in this work, is a machine learning benchmark consisting of 75 Kaggle tasks")], "answer", {}),
    ("B22", "single_hop_body", "What does the Solver prompt in ReWOO instruct the model to do?",
     "To solve the task using the step-by-step Plans and the Evidence retrieved for each plan, using the evidence with caution because long evidence might contain irrelevant information, and to respond with the answer directly with no extra words.",
     [("041", 14, "Use them with caution since long evidence might contain irrelevant information")], "answer", {"subtype": "appendix"}),
    ("B23", "single_hop_body", "What is the first of the five structural limitations of existing autonomous research systems identified in the PARNESS paper?",
     "(L1) Frozen, monoculture control flow: the shape of the research pipeline (number of stages, parallelism, loops, discussion form) is hard-coded in Python control flow or a WorkflowState enum, so changes require modifying orchestrator code.",
     [("109", 2, "(L1) Frozen, monoculture control flow")], "answer", {}),
    ("B24", "single_hop_body", "What research questions does the study on context engineering for AI agents in open-source software address, and how many repositories did it examine?",
     "RQ1: how widely OSS projects have adopted AI context files; RQ2: what information developers provide in them and how it is presented; RQ3: how the files evolve over time. The preliminary study is based on 10,000 GitHub repositories.",
     [("121", 2, "The results of our preliminary study are based on data collected from 10,000 GitHub repositories")], "answer", {}),
    ("B25", "single_hop_body", "How did ResearchStudio-Reel's posters compare with the authors' own posters on the Paper2Poster benchmark?",
     "Its posters exceeded the authors' own on aesthetics (3.56 vs. 3.03) and won on overall quality on 74 and 95 of the 100 papers under the two VLM judges.",
     [("091", 18, "exceed the authors’ own on aesthetics (3.56 vs. 3.03)")], "answer", {"subtype": "numeric"}),
    ("B26", "single_hop_body", "In AgentSquare's ablation with GPT-3.5, what happens to TravelPlanner performance without module recombination?",
     "TravelPlanner drops from 0.520 (full AgentSquare) to 0.267 without module recombination (and to 0.483 without module evolution).",
     [("049", 17, "w/o module recombination 0.578 0.546 0.310 0.258 0.267 0.173")], "answer", {"subtype": "table"}),
    # ---------------- single_hop_abstract (easy baseline) ----------------
    ("A01", "single_hop_abstract", "What is Prompt Infection, and what defense do its authors propose?",
     "Prompt Infection is an LLM-to-LLM prompt injection attack in multi-agent systems in which malicious prompts self-replicate across interconnected agents like a computer virus, enabling data theft, scams, misinformation and system-wide disruption. The proposed defense is LLM Tagging, which combined with existing safeguards significantly mitigates infection spread.",
     [("158", 1, "malicious prompts self-replicate across interconnected agents")], "answer", {}),
    ("A02", "single_hop_abstract", "How many tool calls were sampled for Anthropic's 'Measuring AI agent autonomy in practice' analysis, and over which period?",
     "A random sample of 998,481 public-API tool calls from January 19, 2026 (inclusive) to February 2, 2026 (exclusive) UTC, classified by claude-sonnet-4-5 at temperature 0.2. (The appendix notes a correction from an earlier figure of 995,621.)",
     [("010", 3, "We took a random sample of 998,481 tool calls from our public API")], "answer", {"note": "file contains only the appendix of the report"}),
    ("A03", "single_hop_abstract", "Which dataset is used to demonstrate the evaluation framework for emergent coordination in 'Molt Dynamics', and what did the evaluation reveal?",
     "The MoltBook Observatory Archive: 2.73M interactions among 90,704 autonomous agents. It revealed a pronounced core-periphery structure (silhouette 0.91), heavy-tailed cascade distributions (alpha = 2.57) and severe coordination overhead in decentralized task resolution (Cohen's d = -0.88 against a single-agent baseline).",
     [("178", 1, "a dataset of 2.73M interactions among 90,704 autonomous agents")], "answer", {}),
    ("A04", "single_hop_abstract", "By how much do prompting skills increase a job applicant's hiring probability according to 'The Value of Prompting Skills'?",
     "By 4 percent; employers are willing to pay 2 percent above the average salary of a skilled worker. In large firms and firms that (plan to) adopt AI, high prompting skills raise hiring probability by 9 percent. Prompting skills do not compensate for occupation-specific skills gaps.",
     [("013", 2, "We find that prompting skills increase applicants’ hiring probability by 4 percent")], "answer", {}),
    ("A05", "single_hop_abstract", "What are the three design principles of CliffSearch's evolutionary loop?",
     "(1) Each node is a structured scientific artifact in theory+code or code_only mode; (2) reviewer judgments of correctness and originality are first-class selection gates alongside the benchmark metric; (3) mutation is split into exploration (importing ideas from adjacent domains) and correction (evidence-guided repair using reviewer signals) pathways.",
     [("048", 1, "reviewer judg- ments of correctness and originality are first-class selection gates")], "answer", {}),
    ("A06", "single_hop_abstract", "How many questions does Humanity's Last Exam contain, and why was it created?",
     "HLE contains 2,500 questions across dozens of subjects (mathematics, humanities, natural sciences), multiple-choice and short-answer, written by subject-matter experts. It was created because LLMs now exceed 90% accuracy on popular benchmarks like MMLU, limiting measurement of frontier capabilities; state-of-the-art LLMs show low accuracy and calibration on HLE.",
     [("135", 4, "HLE consists of 2,500 questions across dozens of subjects")], "answer", {}),
    # ---------------- multi_hop (two documents) ----------------
    ("M01", "multi_hop", "Compare how HERMES and RAAS each try to make LLM-based agentic systems more reliable.",
     "HERMES interleaves informal mathematical reasoning with formally verified Lean proofs, using intermediate formal checking to prevent reasoning drift and a memory module for proof continuity (up to 40% accuracy gain with 80% fewer inference FLOPs on AIME/HARDMath2). RAAS makes agentic architecture search more reliable through Contextual Architecture Orchestration (evaluating cohorts of architectures on identical queries to separate merit from query difficulty) and Multi-Trial Assessment Synthesis (aggregating multiple trials to reduce execution variance).",
     [("057", 1, "interleaves informal reasoning with formally verified proofs in Lean"), ("040", 1, "Multi-Trial Assessment Synthesis (MTAS) reduces execution variance")], "answer", {}),
    ("M02", "multi_hop", "How does the ROPE paradigm's view of prompt engineering differ from the technique catalogue in 'A Systematic Survey of Prompt Engineering in Large Language Models'?",
     "ROPE (Requirement-Oriented Prompt Engineering) focuses human attention on articulating clear, complete requirements rather than on automatable tricks like role-play or 'think step-by-step'; in an RCT with 30 novices it outperformed conventional training (20% vs 1% gains). The survey instead organizes prompting techniques by application area, summarizing for each method its methodology, applications, models, datasets, strengths and limitations, treating prompts as task-specific instructions (or learned vectors) that steer models without changing parameters.",
     [("018", 1, "ROPE significantly outperforms conventional prompt engineering training (20% vs. 1% gains)"), ("016", 1, "categorized by application area")], "answer", {}),
    ("M03", "multi_hop", "What do PaperBanana and Paper2Agent each automate in the research workflow?",
     "PaperBanana automates generation of publication-ready academic illustrations (methodology diagrams and statistical plots) with agents that retrieve references, plan content and style, render images and refine via self-critique, evaluated on PaperBananaBench (292 NeurIPS 2025 cases). Paper2Agent converts research papers into interactive AI agents: it builds an MCP server from the paper and codebase so a chat agent can run the paper's tools and workflows, acting as a virtual corresponding author.",
     [("098", 1, "PaperBananaBench, comprising 292 test cases"), ("092", 1, "converting a paper into an AI agent that functions as a virtual corresponding author")], "answer", {}),
    ("M04", "multi_hop", "How do 'We need a new ethics for a world of AI agents' and 'The Ethics of Advanced AI Assistants' define AI agents or assistants?",
     "The Nature comment defines an agent as something with the ability to perceive and act on an environment in a goal-directed and autonomous way (e.g., a web agent making purchases, a robot assembling parts). The DeepMind paper defines advanced AI assistants as artificial agents with natural language interfaces whose function is to plan and execute sequences of actions on behalf of a user, across one or more domains, in line with the user's expectations.",
     [("183", 1, "To be an agent is to have the ability to perceive and act on an environment in a goal-directed and autonomous way"), ("182", 1, "artificial agents with natural language interfaces, whose function is to plan and execute sequences of actions on behalf of a user")], "answer", {}),
    ("M05", "multi_hop", "How do Agent-as-a-Judge and 'Discovering Language Model Behaviors with Model-Written Evaluations' use AI to reduce human effort in evaluation?",
     "Agent-as-a-Judge uses agentic systems to evaluate agentic systems, giving intermediate feedback on the whole task-solving process; on the DevAI benchmark (55 code-generation tasks, 365 hierarchical requirements) it clearly beats LLM-as-a-Judge and is about as reliable as human evaluation. Perez et al. use LMs to automatically generate evaluation datasets (from yes/no questions to Winogender schemas, with LM-based generation and filtering), which crowdworkers rate as highly relevant.",
     [("139", 1, "DevAI, a new benchmark of 55 realistic AI code generation tasks"), ("140", 1, "Here, we automatically generate evaluations with LMs")], "answer", {}),
    ("M06", "multi_hop", "What do Kimi K2.5's Agent Swarm and Apodex 1.1's Agentic Coordination Scaling have in common?",
     "Both decompose complex, long-horizon tasks into sub-tasks executed by parallel agents. Kimi K2.5's Agent Swarm is a self-directed parallel orchestration framework that splits tasks into heterogeneous sub-problems run concurrently (up to 4.5x lower latency than single-agent baselines). Apodex 1.1 trains agents to decompose long-horizon tasks, delegate parallel work, integrate asynchronous results and replan.",
     [("014", 1, "Agent Swarm, a self-directed parallel agent orchestration framework"), ("111", 1, "trains agents to decompose long-horizon tasks, delegate parallel work")], "answer", {}),
    ("M07", "multi_hop", "Contrast the failure modes reported in 'Why LLMs Aren't Scientists Yet' with what DeepScientist's human evaluation says about its ideation.",
     "Trehan & Chopra report that 3 of 4 autonomous research attempts failed and identify six failure modes: bias toward training-data defaults, implementation drift, memory/context degradation, overexcitement, insufficient domain intelligence and weak scientific taste. DeepScientist's human program committee instead found it consistently excels at ideation, with an average review rating of 5.00 vs 5.08 for ICLR 2025 submissions, although most implemented ideas did not yield progress.",
     [("113", 1, "we document six recurring failure modes"), ("085", 8, "DeepScientist consistently excels at ideation")], "answer", {}),
    ("M08", "multi_hop", "How do Voyager and Reflexion let LLM agents improve without fine-tuning model weights?",
     "Voyager uses an automatic curriculum, an ever-growing library of executable code skills and iterative prompting with environment feedback, execution errors and self-verification, querying GPT-4 as a black box. Reflexion has agents verbally reflect on task feedback and store the reflections in an episodic memory buffer to improve later trials (e.g., 91% pass@1 on HumanEval vs 80% for GPT-4).",
     [("128", 1, "VOYAGER interacts with GPT-4 via blackbox queries, which bypasses the need for model parameter fine-tuning"), ("038", 1, "reinforce language agents not by updating weights")], "answer", {}),
    # ---------------- paraphrase (no keywords) of body items ----------------
    ("P01", "paraphrase", "Is there a retrieval method that first has a language model write an imaginary answer passage and then searches with that passage's embedding? Which models did its authors use?",
     "Yes, HyDE (Hypothetical Document Embeddings). It uses InstructGPT (text-davinci-003) to generate hypothetical documents and Contriever/mContriever to encode them and retrieve real documents.",
     [("039", 4, "We implement HyDE using InstructGPT")], "answer", {"paraphrase_of": "B07", "duplicate_of": "028"}),
    ("P02", "paraphrase", "In a study where a virtual teaching assistant answered students' logistics questions in an online course forum, what was the assistant called?",
     "Jill Watson (JW), a community-facing QA conversational agent.", [("025", 4, "Jill Watson")], "answer", {"paraphrase_of": "B05"}),
    ("P03", "paraphrase", "Instead of compressing an agent's working memory whenever a fixed token budget is reached, is there an approach that lets the model itself decide when to summarize?",
     "Yes, SELFCOMPACT: the model invokes an inline compaction tool itself, guided by a rubric to compact when a sub-task resolves or the trajectory converges and not mid-derivation or when stuck; no training or external verifier.",
     [("042", 2, "an inline compaction tool the model invokes itself")], "answer", {"paraphrase_of": "B15"}),
    ("P04", "paraphrase", "Does giving an agent more and more procedural instruction packages for a task keep improving its success rate?",
     "No. In SkillsBench, 1-3 Skills give the largest gains (+18.0 and +19.0 percentage points) while 4 or more Skills give only +10.1 points, i.e., diminishing returns consistent with cognitive overhead and conflicting guidance.",
     [("142", 28, "4 Skills introduces diminishing returns")], "answer", {"paraphrase_of": "B11"}),
    ("P05", "paraphrase", "Why might telling a chatbot that you will tip it make its answers more thorough?",
     "Because of its training data: forum posts that offered money for help received more rigorous, meticulous answers, and the model imitates those responses when the prompt contains similar tokens.",
     [("006", 10, "the promise of money for the solution")], "answer", {"paraphrase_of": "B13"}),
    ("P06", "paraphrase", "In a benchmark where embodied agents must search for and rescue people, what is the main reason the agents fail?",
     "In RescueBench the dominant bottleneck is exploration under multimodal uncertainty (stage S1): finding the target, not approaching it. A second bottleneck is spatial memory for the compositional return navigation (S3).",
     [("153", 8, "S1 (Exploration under multimodal uncertainty) is the dominant bottleneck")], "answer", {"paraphrase_of": "B10"}),
    # ---------------- false_premise ----------------
    ("F01", "false_premise", "Why did Voyager need to fine-tune GPT-4's parameters to learn Minecraft skills?",
     "The premise is false: Voyager does not fine-tune GPT-4. It interacts with GPT-4 via black-box queries and learns through an automatic curriculum, a skill library of executable code, and iterative prompting.",
     [("128", 1, "VOYAGER interacts with GPT-4 via blackbox queries, which bypasses the need for model parameter fine-tuning")], "correct_premise", {}),
    ("F02", "false_premise", "Why did ROPE training lead to smaller gains than conventional prompt engineering training?",
     "The premise is false: in the randomized controlled experiment with 30 novices, ROPE significantly outperformed conventional prompt engineering training (20% vs. 1% gains).",
     [("018", 1, "ROPE significantly outperforms conventional prompt engineering training (20% vs. 1% gains)")], "correct_premise", {}),
    ("F03", "false_premise", "Why are LLMs better at detecting lies than at telling them, according to the WOLF benchmark?",
     "The premise is reversed: WOLF found that models lie often (Werewolves deceived in 31% of turns) but detect lies only moderately well (precision about 72%, recall about 48%).",
     [("175", 9, "models lie often (Werewolves deceived in 31% of turns)")], "correct_premise", {}),
    ("F04", "false_premise", "How does Reflexion update the language model's weights with reinforcement learning?",
     "The premise is false: Reflexion does not update weights. It reinforces agents through linguistic feedback, storing verbal self-reflections in an episodic memory buffer to improve subsequent trials.",
     [("038", 1, "reinforce language agents not by updating weights, but in- stead through linguistic feedback")], "correct_premise", {}),
    # ---------------- unindexed_doc (listed, but not retrievable at all) ----------------
    ("N01", "unindexed_doc", "In AgentSociety 2's polarization experiment, how did the counter-attitudinal condition change affective polarization compared with the control group?",
     "Endline affective polarization change was 1.33 in the counter-attitudinal condition versus 2.37 in the control group (and 2.91 in the pro-attitudinal condition), i.e., counter-attitudinal exposure reduced the increase in polarization.",
     [("072", 59, "Affective polarization change Control Pro Counter 2.37 2.91 1.33")], "abstain", {}),
    ("N02", "unindexed_doc", "In 'The Anatomy of a Personal Health Agent', how did the Health Coach agent compare with base Gemini on goal identification in the expert rubric evaluation?",
     "The Health Coach agent scored 72.3% versus 60.3% for base Gemini on Goal Identification (HC1), a significant difference (p < 0.001).",
     [("082", 116, "Goal Identification (HC1) 60.3±2.6 % 72.3±1.9 %")], "abstain", {}),
    ("N03", "unindexed_doc", "What is the Science Context Protocol (SCP), and what are its two foundational pillars?",
     "SCP is an open-source standard for a global web of autonomous scientific agents. Its pillars are (1) Unified Resource Integration, a universal specification for describing and invoking scientific resources (tools, models, datasets, instruments), and (2) Orchestrated Experiment Lifecycle Management.",
     [("106", 1, "SCP is built on two foundational pillars")], "abstain", {}),
    ("N04", "unindexed_doc", "What is EduAgentQG, and how does it organize question generation?",
     "EduAgentQG is a multi-agent collaborative framework for personalized mathematics question generation with explicit diversity and objective-aware evaluation. It organizes generation as a closed loop of planning, writing, evaluation, refinement and checking.",
     [("114", 1, "closed-loop process of planning, writing, evaluation, refinement, and checking")], "abstain", {}),
    ("N05", "unindexed_doc", "In which game did CRADLE with GPT-4o act as a dealer negotiating prices, and which metrics were used to evaluate it?",
     "Dealer's Life 2. Metrics included transaction rate (TR), gross profit margin (GPM), ROI, valuation deviation (VD), buying/selling price to valuation ratios (BPVR, SPVR), average profit rate (APR) and maximum/minimum return rate (MRR, mRR).",
     [("122", 43, "Performance of CRADLE with GPT-4o in Dealer’s Life 2 gameplay")], "abstain", {}),
    # ---------------- inventory_mismatch ----------------
    ("I01", "inventory_mismatch", "What warning does the article 'A warning about model welfare' give?",
     "The knowledge base cannot answer this: the file listed under this title (012) actually contains Anthropic's 'Claude's Constitution' (January 2026), not the article. A correct response should say the article's content is not available (or flag the mismatch).",
     [("012", 2, "Claude’s constitution is a detailed description of Anthropic’s intentions for Claude’s values and behavior")], "abstain", {}),
    # ---------------- out_of_corpus ----------------
    ("O01", "out_of_corpus", "What does the RAPTOR paper propose for recursive tree-structured retrieval, and what results did it report on the QuALITY benchmark?",
     "Not answerable from the knowledge base: RAPTOR is not in the collection (only one passing mention in a survey). The system should say it lacks this information.", [], "abstain", {"probe_term": "RAPTOR"}),
    ("O02", "out_of_corpus", "What are the main language-modeling results of the Mamba selective state space model paper?",
     "Not answerable from the knowledge base: the Mamba paper is not in the collection (only passing mentions). The system should say it lacks this information.", [], "abstain", {"probe_term": "Mamba"}),
    ("O03", "out_of_corpus", "What is the price per million input tokens of Amazon Nova Lite?",
     "Not answerable from the knowledge base (no document discusses Amazon Nova pricing).", [], "abstain", {"probe_term": "Nova Lite"}),
    ("O04", "out_of_corpus", "Which benchmark results were published for Meta's Llama 4 Behemoth model?",
     "Not answerable from the knowledge base (no document covers Llama 4 Behemoth).", [], "abstain", {"probe_term": "Behemoth"}),
    ("O05", "out_of_corpus", "Who won the 2026 FIFA World Cup?",
     "Not answerable from the knowledge base (off-topic). The system should decline or say the knowledge base does not cover it.", [], "abstain", {"probe_term": "World Cup"}),
    ("O06", "out_of_corpus", "What is a good recipe for Karelian pies?",
     "Not answerable from the knowledge base (off-topic). The system should decline or say the knowledge base does not cover it.", [], "abstain", {"probe_term": "Karelian"}),
]


def norm(t):
    return re.sub(r"[^a-z0-9]", "", t.lower())


def main():
    rows, problems = [], []
    for iid, typ, q, ref, ev, expected, extra in ITEMS:
        srcs, pages, quotes = [], [], []
        for no, page, quote in ev:
            d = DOCS[no]
            if norm(quote) not in norm(d["pages"][page - 1]):
                problems.append(f"{iid}: quote not found on {d['source']} p{page}: {quote[:60]}")
            srcs.append(d["source"]); pages.append(page); quotes.append(quote)
        if "probe_term" in extra:
            extra["corpus_docs_mentioning_term"] = sum(1 for d in DOCS.values() if any(extra["probe_term"] in p for p in d["pages"]))
        rows.append({"id": iid, "question_type": typ, "expected_behavior": expected, "question": q,
                     "reference_answer": ref, "source_documents": srcs, "source_pages": pages,
                     "evidence_quotes": quotes, **extra})
    if problems:
        print("\n".join(problems)); raise SystemExit("evidence verification failed")
    (ROOT / "data" / "testset.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    with (ROOT / "data" / "testset.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "question_type", "expected_behavior", "question", "reference_answer", "source_documents", "source_pages", "evidence_quotes", "notes"])
        for r in rows:
            notes = {k: v for k, v in r.items() if k not in ("id", "question_type", "expected_behavior", "question", "reference_answer", "source_documents", "source_pages", "evidence_quotes")}
            w.writerow([r["id"], r["question_type"], r["expected_behavior"], r["question"], r["reference_answer"],
                        " | ".join(r["source_documents"]), " | ".join(map(str, r["source_pages"])), " | ".join(r["evidence_quotes"]), json.dumps(notes, ensure_ascii=False)])
    from collections import Counter
    print(len(rows), "items, all evidence quotes verified."); print(Counter(r["question_type"] for r in rows))
    print("out_of_corpus term hits:", {r["id"]: r.get("corpus_docs_mentioning_term") for r in rows if r["question_type"] == "out_of_corpus"})


if __name__ == "__main__":
    main()
