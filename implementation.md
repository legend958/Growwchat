# Implementation Plan — Mutual Fund FAQs (Facts-Only Q&A RAG Chatbot)

**Status:** Draft
**Companion docs:** `Prd.md`, `architecture.md`
**Last updated:** 2026-10-12

---

## How to Use This Document

This is a **phase-wise implementation plan** meant to drive Cursor (or any coding agent) in **ordered, independently verifiable phases**. Each phase has:

- **Objective** — what the phase accomplishes.
- **Inputs / Prerequisites** — what must exist first.
- **Tasks** — concrete, file-level steps.
- **Files** — what gets created or changed.
- **Deliverables** — artifacts produced.
- **Acceptance criteria** — how to confirm the phase is done.
- **Cursor prompt** — a copy-paste instruction block to hand to the agent.

**Rules for the agent:**

1. Implement **one phase at a time**. Do not start the next phase until the current phase's acceptance criteria pass.
2. Follow the module layout in `architecture.md` §9 exactly.
3. Keep the **same embedding model** for ingestion and query.
4. Never introduce third-party blogs, PII handling, or performance/return claims.
5. At the end of each phase, stop and report: files changed, commands run, results, and blockers.

---

## Phase Index

| Phase | Name | Depends on |
|-------|------|------------|
| 0 | Project Setup & Scaffolding | — |
| 1 | Ingestion — Load & Normalize Sources | Phase 0 |
| 2 | Ingestion — Chunking Strategy & Chunk Dump | Phase 1 |
| 3 | Ingestion — Embed & Store in ChromaDB | Phase 2 |
| 4 | Retrieval — Question Embedding + Top-k Search | Phase 3 |
| 5 | Generation — Prompt Builder + LLM Answer | Phase 4 |
| 6 | Guardrails — Citation, Refusal, PII, Length, Freshness | Phase 5 |
| 7 | UI — Facts-Only Chat Interface + Disclaimer | Phase 6 |
| 8 | Evaluation — Sample Q&A + Accuracy Checks | Phase 7 |
| 9 | Packaging — README, Source List, Demo | Phase 8 |

---

## Phase 0 — Project Setup & Scaffolding

### Objective
Create the repository skeleton, dependency manifest, config module, and shared constants so later phases have a stable home.

### Inputs / Prerequisites
- `Prd.md` and `architecture.md` present.

### Tasks
1. Create the folder structure from `architecture.md` §9: `data/raw/`, `ingest/`, `query/`, `ui/`, `artifacts/`.
2. Add `requirements.txt` with pinned-ish deps:
   - `sentence-transformers`
   - `chromadb`
   - `requests`
   - `beautifulsoup4`
   - `python-dotenv`
   - LLM SDK (choose in Phase 5; leave a placeholder comment)
3. Create `config.py` (or `config.yaml` + loader) with the keys from `architecture.md` §10:
   `EMBEDDING_MODEL`, `VECTOR_DB_PATH`, `COLLECTION_NAME`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, `TOP_K`, `SCORE_THRESHOLD`, `LLM_PROVIDER`, `LLM_MODEL`.
4. Add `.env.example` and `.gitignore` (ignore `chroma_db/`, `.env`, `__pycache__/`).
5. Add `__init__.py` to `ingest/` and `query/` if using packages.

### Files
- `requirements.txt`, `config.py`, `.env.example`, `.gitignore`, folder skeleton.

### Deliverables
- Installable project skeleton.

### Acceptance Criteria
- `pip install -r requirements.txt` succeeds.
- `python -c "import config; print(config.EMBEDDING_MODEL)"` prints `sentence-transformers/all-MiniLM-L6-v2`.

### Cursor Prompt
```
Create the project scaffold for this RAG chatbot following architecture.md §9 and §10.
Create the folders data/raw, ingest, query, ui, artifacts. Add requirements.txt with
sentence-transformers, chromadb, requests, beautifulsoup4, python-dotenv, and a clearly
commented placeholder for the LLM SDK. Create config.py exposing EMBEDDING_MODEL,
VECTOR_DB_PATH, COLLECTION_NAME, CHUNK_SIZE, CHUNK_OVERLAP, TOP_K, SCORE_THRESHOLD,
LLM_PROVIDER, LLM_MODEL with sane defaults. Add .env.example and .gitignore.
Do not write pipeline logic yet. Stop after scaffold.
```

---

## Phase 1 — Ingestion: Load & Normalize Sources

### Objective
Fetch the 5 scoped official pages and produce clean, normalized text under `data/raw/`, plus the `sources.md` source list.

### Inputs / Prerequisites
- Phase 0 scaffold complete.

### Tasks
1. Create `data/sources.md` listing the 5 scheme URLs (from `Prd.md` §4.1) with scheme name + category.
2. Implement `ingest/load.py`:
   - Read URLs from `data/sources.md` (or a URLs constant/config).
   - Fetch each page with a browser-like `User-Agent`; handle retries and timeouts.
   - Extract main content with BeautifulSoup (strip nav/scripts/styles).
   - Normalize whitespace.
3. Persist one cleaned text file per source under `data/raw/<scheme-slug>.txt`, and keep raw HTML optionally under `data/raw/html/`.
4. Log a summary table: URL → bytes fetched → cleaned chars.

### Files
- `data/sources.md`, `ingest/load.py`, `data/raw/*.txt`.

### Deliverables
- 5 cleaned source documents + source list.

### Acceptance Criteria
- Running `python -m ingest.load` writes 5 non-empty cleaned `.txt` files.
- Each file's text contains scheme-relevant terms (e.g., "expense ratio", "exit load").
- `data/sources.md` contains exactly the 5 URLs and no third-party sources.

### Cursor Prompt
```
Implement Phase 1 (Ingestion — Load & Normalize). Create data/sources.md with the 5
official scheme URLs from Prd.md §4.1 (scheme name + category + URL only, no blogs).
Implement ingest/load.py to fetch each page (browser User-Agent, timeout, retries),
extract main content with BeautifulSoup, normalize whitespace, and write one cleaned
file per scheme to data/raw/<slug>.txt. Print a summary of URL -> cleaned char count.
Public sources only. Stop and show me the summary + a sample of each cleaned file.
```

---

## Phase 2 — Ingestion: Chunking Strategy & Chunk Dump

### Objective
Inspect the loaded data, propose a chunking strategy, implement the chunker with metadata, and dump inspectable chunks.

> Per `Prd.md` §6.3, the agent **must inspect the data and propose a strategy before writing code**.

### Inputs / Prerequisites
- Phase 1 cleaned files in `data/raw/`.

### Tasks
1. **Inspect first:** summarize each source's structure (headings, sections, tables) and note where facts like expense ratio, exit load, lock-in live.
2. **Propose strategy:** state chunk size, overlap, boundary rules (semantic/section-based where headings exist), and the metadata each chunk keeps. Justify why it suits this data.
3. Implement `ingest/chunk.py`:
   - Split into chunks using the proposed strategy.
   - Attach metadata per `architecture.md` §5.1: `chunk_id`, `scheme`, `category`, `doc_type`, `source_url`, `source_title`, `last_updated`, `position`, plus `text`.
4. Write all chunks to `artifacts/chunks.txt` in a human-readable, inspectable format (chunk ID, metadata, text).
5. Print chunk count per source and average chunk size.

### Files
- `ingest/chunk.py`, `artifacts/chunks.txt`.

### Deliverables
- Inspectable chunk file + documented strategy.

### Acceptance Criteria
- `python -m ingest.chunk` writes `artifacts/chunks.txt`.
- Every chunk has a `source_url` and `scheme` (required for citations).
- Strategy (size, overlap, metadata) is documented in the agent's response and matches `architecture.md` §5.2.

### Cursor Prompt
```
Implement Phase 2 (Chunking). FIRST inspect data/raw/*.txt and report the structure.
THEN propose a chunking strategy: chunk size, overlap, boundary rules, and the exact
metadata each chunk keeps (must include source_url and scheme for citations). Justify
why it fits this data. Only after I approve the strategy, implement ingest/chunk.py to
produce chunks and write them to artifacts/chunks.txt in a readable format (id, metadata,
text). Print chunk counts per source and average length. Do not embed yet.
```

---

## Phase 3 — Ingestion: Embed & Store in ChromaDB

### Objective
Embed all chunks with `all-MiniLM-L6-v2` and upsert into a **persisted** ChromaDB collection so ingestion runs once.

### Inputs / Prerequisites
- Phase 2 chunks available (`ingest.chunk` importable).

### Tasks
1. Implement `ingest/embed.py`:
   - Load `SentenceTransformer(config.EMBEDDING_MODEL)`.
   - Encode chunk texts (batched); assert vector dim == 384.
2. Implement `ingest/store.py`:
   - Create/connect a `PersistentClient` at `config.VECTOR_DB_PATH`.
   - Create/get collection `config.COLLECTION_NAME` with cosine space.
   - Upsert documents, embeddings, metadatas, ids (idempotent — safe to rerun).
3. Add a single entrypoint (e.g., `python -m ingest.run`) that runs load → chunk → embed → store end-to-end.
4. Print: number of chunks stored, collection count.

### Files
- `ingest/embed.py`, `ingest/store.py`, `ingest/run.py`, `chroma_db/` (generated).

### Deliverables
- Persisted vector store on disk.

### Acceptance Criteria
- `python -m ingest.run` completes and creates `chroma_db/`.
- Collection count equals number of chunks from Phase 2.
- Re-running does not duplicate entries (count stable).
- A fresh process can open the collection without re-embedding.

### Cursor Prompt
```
Implement Phase 3 (Embed & Store). Create ingest/embed.py using
sentence-transformers/all-MiniLM-L6-v2 (assert 384-dim) and ingest/store.py using
ChromaDB PersistentClient at config.VECTOR_DB_PATH with collection config.COLLECTION_NAME
and cosine space. Upsert documents, embeddings, metadatas, ids idempotently. Add
ingest/run.py to run the full pipeline (load -> chunk -> embed -> store) and print stored
count. Verify re-running keeps the count stable and a new process can open the collection
without re-embedding. Stop and show the output.
```

> **Environment note (this machine, verified):** Windows Smart App Control is **enforced**
> and blocks scikit-learn's compiled DLLs. `sentence-transformers` and `transformers>=5`
> import scikit-learn on startup, so they cannot be used as-is. `ingest/embed.py` instead
> loads the **same** HF model `sentence-transformers/all-MiniLM-L6-v2` via
> `transformers==4.46.3` (pinned) + torch, with attention-mask mean pooling + L2
> normalization (identical 384-dim vector semantics; rankings unaffected for cosine
> retrieval). Do NOT swap back to `sentence-transformers` or upgrade `transformers` past
> 4.x unless Smart App Control is disabled.

---

## Phase 4 — Retrieval: Question Embedding + Top-k Search

### Objective
Given a question, embed it with the **same** model, retrieve top-k chunks above a score threshold, and return text + metadata.

### Inputs / Prerequisites
- Phase 3 persisted collection.

### Tasks
1. Implement `query/retrieve.py`:
   - Reuse the same embedding model (shared loader helper; do not fork the model).
   - Query the collection for `TOP_K` results.
   - Convert Chroma distances to similarity scores; filter by `SCORE_THRESHOLD`.
   - Return structured results: `{text, source_url, source_title, scheme, doc_type, last_updated, score}`.
2. Handle the empty-result case (nothing above threshold) explicitly (feeds Phase 6 refusal/fallback).
3. Add a small CLI: `python -m query.retrieve "Expense ratio of HDFC Large Cap Fund?"` printing ranked chunks with scores and source URLs.

### Files
- `query/retrieve.py`, shared `embed` loader (refactor if needed).

### Deliverables
- Working retrieval CLI.

### Acceptance Criteria
- Sample factual queries return relevant chunks with a `source_url`.
- Threshold filtering returns an empty set for out-of-scope queries.
- Same model used as ingestion (no separate model instance config).

### Cursor Prompt
```
Implement Phase 4 (Retrieval). Create query/retrieve.py that embeds the question with the
SAME all-MiniLM-L6-v2 model used at ingestion (extract a shared loader so there is one
source of truth), queries the ChromaDB collection for TOP_K results, converts distances to
similarity, filters by SCORE_THRESHOLD, and returns text + metadata (source_url,
source_title, scheme, doc_type, last_updated, score). Handle empty results. Add a CLI:
python -m query.retrieve "<question>" that prints ranked chunks. Test with one in-scope and
one out-of-scope question and show both outputs.
```

---

## Phase 5 — Generation: Prompt Builder + LLM Answer

### Objective
Turn retrieved chunks into a grounded, factual answer using a configurable LLM, with the citation available in the response.

### Inputs / Prerequisites
- Phase 4 retrieval returning structured chunks.

### Tasks
1. Implement `query/generate.py`:
   - Build a prompt that (a) restricts the model to the provided chunks, (b) forbids advice/performance claims, (c) requires ≤3 sentences, and (d) requires referencing the single source link.
   - Call the configured LLM (`LLM_PROVIDER` / `LLM_MODEL`).
   - Return a structured answer object: `{answer, source_url, source_title, last_updated}`.
2. If retrieval is empty, return a "not found in sources" signal (Phase 6 formats the refusal).
3. Wire `retrieve → generate` into a `query.pipeline` function returning the structured answer.

### Files
- `query/generate.py`, `query/pipeline.py`.

### Deliverables
- Grounded answer generation with source metadata attached.

### Acceptance Criteria
- Factual question → answer ≤3 sentences citing one official URL.
- Prompt explicitly forbids advice, comparisons, and return claims.
- No chunk → "not found in sources" signal, not a hallucinated answer.

### Cursor Prompt
```
Implement Phase 5 (Generation). Create query/generate.py that builds a grounded prompt
using only the retrieved chunks; the prompt must forbid investment advice, return
comparisons, and performance claims, and must require <=3 sentences referencing the single
source link. Call the configured LLM (LLM_PROVIDER/LLM_MODEL) and return
{answer, source_url, source_title, last_updated}. If retrieval is empty, return a
not-found-in-sources signal. Create query/pipeline.py chaining retrieve -> generate.
Show me answers for 2 factual questions and 1 out-of-scope question.
```

> **Environment note (this machine, verified):** Groq provider is **`openai/gpt-oss-120b`**
> (the account's `GET /models` list no longer includes `llama-3.3-70b-versatile`; available:
> `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`, `allam-2-7b`). The LLM is
> called through the OpenAI-compatible REST API via `requests` (no SDK); key in `GROQ_API_KEY`
> inside `.env` (gitignored). The generation prompt forbids advice/return claims, requires ≤3
> sentences, and instructs the model **not** to emit URLs; the single `Source: <url>` line and
> `Last updated from sources: <date>` footer are attached deterministically by
> `query.generate.format_answer` (exactly one citation).

---

## Phase 6 — Guardrails: Citation, Refusal, PII, Length, Freshness

### Objective
Enforce the `architecture.md` §7 guardrails around the generation output so answers are always citable, facts-only, concise, and fresh.

### Inputs / Prerequisites
- Phase 5 pipeline.

### Tasks
1. Implement `query/guardrails.py` with functions:
   - **Pre-check:** detect opinionated/portfolio intent ("should I buy/sell", "best fund", "recommend") and PII patterns (PAN, Aadhaar, account no., OTP, email, phone) → short-circuit.
   - **Post-check:** ensure exactly one citation, cap to ≤3 sentences, append "Last updated from sources: {last_updated}".
   - **Refusal formatter:** polite facts-only message + a relevant **educational** link.
   - **Not-found formatter:** "I couldn't find that in the official sources" (no fabrication).
2. Integrate guardrails into `query/pipeline.py` (pre before retrieval, post after generation).
3. Define the educational links list (official AMC/AMFI/SEBI educational pages only).

### Files
- `query/guardrails.py`, updated `query/pipeline.py`.

### Deliverables
- Guarded answer pipeline.

### Acceptance Criteria
- Factual answer: exactly one citation + "Last updated from sources:" + ≤3 sentences.
- "Should I buy X?" → polite refusal + educational link, no advice.
- PII in the question is not stored or echoed back.
- Return/performance question → links to official factsheet, no computed returns.

### Cursor Prompt
```
Implement Phase 6 (Guardrails) per architecture.md §7. Create query/guardrails.py with
(a) a pre-check for opinionated/portfolio intent and PII patterns (PAN, Aadhaar, account
number, OTP, email, phone) that short-circuits with a polite facts-only refusal plus an
educational official link; (b) a post-check enforcing exactly one citation, <=3 sentences,
and appending "Last updated from sources: {last_updated}"; (c) not-found formatting when
retrieval is empty. Integrate into query/pipeline.py. Use only official AMC/AMFI/SEBI
educational links. Test: 3 factual, 2 opinionated, 1 PII, 1 performance question. Show all.
```

> **Environment note (this machine, verified):** `query/guardrails.py` implements the §7
> guardrails. Pre-check priority is **PII > opinion > performance** and short-circuits before
> retrieval/LLM (PII is never echoed or stored). Opinion/performance refusals link to an
> official AMC/AMFI/SEBI educational page or, when the question names a scheme, to that
> scheme's official Groww page (base-name matching strips the " – Direct Growth" plan suffix;
> e.g. "What returns did HDFC Large Cap Fund give last year?" → official scheme/factsheet
> URL). Post-check strips stray URLs and `Source:` labels anywhere (not just line-start),
> caps the body at ≤3 sentences, and attaches exactly one `Source: <url>` line plus the
> `Last updated from sources:` footer. Word-level detectors must stay multi-word (e.g.
> "should i buy|sell|invest…") so factual uses of "buy", "portfolio", "growth", or "phone
> number" are not blocked — the 17-case detector test passes with 0 false triggers, and the
> 3-sentence/1-citation post-check suite passes.

---

## Phase 7 — UI: Facts-Only Chat Interface + Disclaimer

### Objective
Build the tiny UI: welcome line, 3 example questions, disclaimer, and an answer panel showing one citation link.

### Inputs / Prerequisites
- Phase 6 guarded pipeline callable as a function.

### Tasks
1. Implement `ui/app.py` (Streamlit, Gradio, or notebook — pick one):
   - **Welcome line.**
   - **3 example questions** as clickable buttons.
   - Persistent note: **"Facts-only. No investment advice."**
   - Answer area showing the answer, the **single citation link**, and "Last updated from sources:".
   - Refusal state rendered distinctly (facts-only message + educational link).
2. Wire the UI to `query.pipeline`.
3. Show the disclaimer snippet from `Prd.md` §9 in the UI.

### Files
- `ui/app.py` (and `ui/__init__.py` if needed).

### Deliverables
- Runnable prototype UI.

### Acceptance Criteria
- UI shows welcome line, 3 examples, and the disclaimer.
- A factual query renders answer + exactly one clickable source link.
- An opinionated query renders the polite refusal + educational link.
- No PII field anywhere in the UI.

### Cursor Prompt
```
Implement Phase 7 (UI). Create ui/app.py (use a lightweight framework, e.g. Streamlit)
with: a welcome line, 3 clickable example questions, the persistent note "Facts-only. No
investment advice.", and an answer panel showing the answer, ONE clickable citation link,
and "Last updated from sources:". Render refusals distinctly. Wire it to query.pipeline and
include the disclaimer snippet from Prd.md §9. Add no PII fields. Give me the run command
and confirm the three example questions work.
```

> **Environment note (this machine, verified):** `ui/app.py` is a **Streamlit** app
> (`streamlit==1.65.0`; its pandas/pyarrow/altair imports all pass under Smart App Control).
> Run with `streamlit run ui/app.py` from the repo root (server defaults to
> http://localhost:8501). The app adds the repo root to `sys.path` so `config`/`query`
> import regardless of launch directory; an `@st.cache_data` wrapper caches answers per
> question so unrelated UI reruns don't re-call the LLM. The clickable citation is rendered
> by splitting the guarded `body\n\nSource: <url>\nLast updated from sources: <date>` answer
> (`st.markdown(body)` + `**Source:** [url](url)` + `st.caption` footer); refusals render as
> `st.warning`, not-found as `st.info`. Acceptance was verified headlessly with
> `streamlit.testing.v1.AppTest` (assertions in `tests/`-style temp script): welcome + 3
> example buttons + Prd §9 disclaimer render; clicking an example prefilled the input and
> returned a grounded answer with one clickable citation and the freshness footer; an
> opinionated question rendered the warning refusal; an out-of-scope question rendered the
> not-found info block.

---

## Phase 8 — Evaluation: Sample Q&A + Accuracy Checks

### Objective
Produce the **sample Q&A** deliverable (5–10 queries with answers + links) and verify guardrail behavior and retrieval quality.

### Inputs / Prerequisites
- Phase 7 working UI / pipeline.

### Tasks
1. Create `sample_qa.md` with 5–10 queries spanning: expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer/benchmark, statement download — each with the answer + its source link + "Last updated from sources:".
2. Add negative tests: opinionated questions → refusals; performance question → factsheet link; out-of-scope → not-found.
3. Record retrieval sanity: for each query, the top chunk's source matches the expected scheme.
4. Note any failures and fix or document as known limits.

### Files
- `sample_qa.md`, optional `tests/` scripts.

### Deliverables
- Sample Q&A file + evaluation notes.

### Acceptance Criteria
- `sample_qa.md` has 5–10 entries, each with a citation link.
- All refusal/performance/out-of-scope tests behave as specified.
- Known limits documented.

### Cursor Prompt
```
Implement Phase 8 (Evaluation). Generate sample_qa.md with 5-10 factual queries
(expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer/benchmark, statement
download) each showing the answer, its source link, and "Last updated from sources:".
Add negative tests: opinionated -> refusal, performance -> factsheet link, out-of-scope ->
not-found. For each query, report the retrieved top chunk's source vs expected scheme.
List any failures as known limits. Show me sample_qa.md.
```

---

## Phase 9 — Packaging: README, Source List, Demo

### Objective
Finalize the remaining deliverables: README, confirmed source list, and a runnable demo (hosted prototype or ≤3-min video).

### Inputs / Prerequisites
- Phases 0–8 complete.

### Tasks
1. Write `README.md`: setup steps, scope (AMC + schemes), how to run ingestion once, how to run the query/UI, known limits, disclaimer.
2. Confirm `data/sources.md` (or a CSV) lists exactly the 5 official URLs.
3. Provide the demo path: a hosted prototype link, or a recording ≤3 minutes showing factual answers, citations, and a refusal.
4. Freeze `requirements.txt` and verify a clean install → ingest → query works from scratch.

### Files
- `README.md`, `data/sources.md` (final), demo artifact/link.

### Deliverables
- README, source list, demo.

### Acceptance Criteria
- A new user can follow README to set up, ingest once, and query successfully.
- Source list = 5 official URLs.
- Demo shows: factual answer + citation, and a refusal.
- All `Prd.md` §8 deliverables present.

### Cursor Prompt
```
Implement Phase 9 (Packaging). Write README.md with setup steps, scope (HDFC AMC + the 5
schemes), how to run ingestion once, how to run the query CLI and UI, known limits, and the
disclaimer. Confirm data/sources.md has exactly the 5 official URLs. Ensure requirements.txt
supports a clean install. Summarize where the hosted prototype or <=3-min demo lives.
Then verify a from-scratch install -> ingest -> query works. Stop and report.
```

---

## Cross-Phase Checklist

- [ ] Same embedding model at ingestion and query (`all-MiniLM-L6-v2`, 384-dim).
- [ ] ChromaDB persisted; ingestion runs once and survives restart.
- [ ] Every factual answer has **exactly one** official citation.
- [ ] Opinionated/portfolio questions refused with an educational link.
- [ ] No PII accepted or stored.
- [ ] No performance/return claims; link to official factsheet instead.
- [ ] Answers ≤3 sentences with "Last updated from sources:".
- [ ] Public sources only (AMC/SEBI/AMFI); no blogs or back-end screenshots.
- [ ] `artifacts/chunks.txt` inspectable.
- [ ] Deliverables from `Prd.md` §8 all present.

## Deliverables Traceability

| `Prd.md` §8 deliverable | Produced in phase |
|-------------------------|-------------------|
| Working prototype / demo video | Phase 7 + Phase 9 |
| Source list (CSV/MD) | Phase 1 + Phase 9 |
| README (setup, scope, limits) | Phase 9 |
| Sample Q&A file | Phase 8 |
| Disclaimer snippet in UI | Phase 7 |

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Source pages change | "Last updated from sources:" + explicit re-ingestion. |
| Irrelevant retrieval | `TOP_K` + `SCORE_THRESHOLD` + not-found fallback. |
| Query edges toward advice | Pre-check refusal guardrail (Phase 6). |
| LLM hallucination | Grounded prompt restricted to retrieved chunks; cite one source. |
| Model mismatch | Single shared embedding loader; assert 384-dim at ingest. |
