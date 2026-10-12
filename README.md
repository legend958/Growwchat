# HDFC Mutual Fund FAQ — Facts-Only RAG Chatbot

A retrieval-augmented (RAG) chatbot that answers **factual** questions about five
HDFC Mutual Fund schemes, using only their **official public Groww scheme
pages**. Every answer is **≤ 3 sentences**, carries **exactly one** official
citation, and ends with a `Last updated from sources:` footer.

**Facts-only. No investment advice, no return/performance claims, no PII.**

- 🔎 **Grounded** — retrieves from the 5 scheme pages; says *not found* instead of guessing.
- 🛡️ **Guarded** — refuses advice/opinion, performance/returns, and PII, with links to official pages.
- 📎 **One citation per answer** — attached deterministically, never emitted by the model.
- 💬 **Streamlit UI + CLI** — ask a question, get a cited, facts-only answer.

---

## Scope

- **AMC:** HDFC Mutual Fund
- **Schemes (Direct Plan · Growth):**

| # | Scheme | Category | Source |
|---|--------|----------|--------|
| 1 | HDFC Large Cap Fund | Large Cap | [Groww](https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth) |
| 2 | HDFC Equity Fund | Flexi Cap | [Groww](https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth) |
| 3 | HDFC ELSS Tax Saver Fund | ELSS | [Groww](https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth) |
| 4 | HDFC Small Cap Fund | Small Cap | [Groww](https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth) |
| 5 | HDFC Balanced Advantage Fund | Balanced Advantage (Hybrid) | [Groww](https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth) |

The canonical source list is [`data/sources.md`](data/sources.md) (exactly these
5 official URLs). Cleantext for each lives in `data/raw/`.

---

## How it works

```
Ingestion (run once):
  official pages → clean  → chunk (46) → embed (384-d) → ChromaDB (persisted)
Query:
  question → embed → retrieve top-k → Groq LLM → guardrails → cited answer
```

| Concern | Choice |
|---------|--------|
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (384-dim), **same model** for chunks and questions |
| Vector DB | **ChromaDB** persisted at `./chroma_db` (ingestion runs once; survives restart) |
| LLM | **Groq** `openai/gpt-oss-120b` via the OpenAI-compatible REST API (`requests`, no SDK) |
| Guardrails | pre-check (PII > opinion > performance) → retrieve/generate → post-check (one citation, ≤3 sentences, freshness footer) |

See [`architecture.md`](architecture.md) for the full design.

---

## Prerequisites

- **Python 3.12.x** (pinned via `.python-version`; needed for prebuilt wheels)
- A **Groq API key** (https://console.groq.com/keys)

> **Why not `sentence-transformers`?** On Windows with Smart App Control enforced,
> it imports scikit-learn's compiled DLLs, which are blocked. We load the *same* HF
> model via `transformers==4.46.3` + `torch` with attention-mask mean pooling and
> L2 normalization (identical 384-dim semantics). Keep `transformers` on 4.x.

---

## Setup

```bash
git clone https://github.com/legend958/Growwchat.git
cd Growwchat

python -m venv .venv
# Windows (PowerShell):  .\.venv\Scripts\Activate.ps1
# macOS/Linux:           source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env          # then edit .env and set GROQ_API_KEY
```

---

## Run

### 1. Ingestion — run once (build the vector store)

```bash
python -m ingest.run --no-fetch     # reuse the committed data/raw/*.txt
# python -m ingest.run              # (optional) re-fetch the 5 official pages first
```

Expected: `46 chunks → 46 vectors → collection count = 46` under `./chroma_db`.
This is idempotent — re-running keeps the count stable.

Inspect chunks/embeddings with `python -m ingest.dump` →
`artifacts/chunks_with_embeddings.txt`.

### 2. Ask questions

**CLI:**

```bash
python -m query.pipeline "What is the expense ratio of HDFC Large Cap Fund?"
python -m query.pipeline "How long is the ELSS lock-in period?"
python -m query.retrieve "exit load" --top-k 3     # retrieval only (no LLM)
```

**UI (Streamlit):**

```bash
streamlit run ui/app.py
# open http://localhost:8501
```

### 3. Tests & evaluation

```bash
python -m tests.test_guardrails    # detector + post-check regression → 37/37
python -m tests.eval_sample_qa     # end-to-end accuracy + retrieval    → 15/15
```

The evaluated sample Q&A (10 factual + 5 negative cases, with a retrieval-sanity
table and known limits) is in [`sample_qa.md`](sample_qa.md).

---

## Configuration

All settings live in [`config.py`](config.py) and can be overridden by environment
variables (see [`.env.example`](.env.example)). In production, set them as real
env vars (no `.env` file).

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `GROQ_API_KEY` | ✅ | — | Groq key; read as `LLM_API_KEY or GROQ_API_KEY` |
| `LLM_MODEL` | | `openai/gpt-oss-120b` | model name on Groq |
| `LLM_BASE_URL` | | `https://api.groq.com/openai/v1` | OpenAI-compatible endpoint |
| `SCORE_THRESHOLD` | | `0.30` | retrieval similarity cutoff |
| `TOP_K` | | `5` | chunks retrieved |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | | `…/all-MiniLM-L6-v2` / `384` | |
| `VECTOR_DB_PATH` | | `./chroma_db` | persisted store |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | | `700` / `100` | |

---

## Deploy (Render)

The app runs as a Render **Web Service** from this repo.

| Setting | Value |
|---------|-------|
| Runtime | **Python 3.12.x** (also pinned by `.python-version`) |
| Root Directory | *(empty — repo root)* |
| Build Command | `pip install --index-url https://download.pytorch.org/whl/cpu torch && pip install -r requirements.txt && python -m ingest.run --no-fetch` |
| Start Command | `python -m streamlit run ui/app.py --server.address 0.0.0.0 --server.port $PORT --server.headless true --browser.gatherUsageStats false` |

**Environment variables:** `GROQ_API_KEY` (required, secret).
Optional: `LLM_MODEL`, `SCORE_THRESHOLD`, `PYTHONUNBUFFERED=1`. Do **not** set `PORT`.

The vector store is rebuilt during the build (`ingest.run --no-fetch`), so it
ships inside the image.

---

## Demo

- **Hosted prototype:** `https://<your-service>.onrender.com` — Streamlit UI on Render.
- **Local:** `streamlit run ui/app.py` → http://localhost:8501.
- **Recorded evidence:** [`sample_qa.md`](sample_qa.md) shows a factual answer with its
  single citation **and** an opinion refusal, plus 5 guardrail cases.

---

## Known limits

1. **Out-of-scope topics return *not found*** — statement/account downloads, KYC,
   redemption process, "how to invest/buy", and tax questions are not in the 5
   scheme pages.
2. **NFO-risk source quirk** — pages list both `Riskometer (risk grade): Very High`
   and `NFO risk: Moderately High`; the assistant reports the risk grade.
3. **Cosmetic non-breaking hyphen** (U+2011) can appear in some answers (e.g. "lock‑in").
4. **Freshness footer = ingestion date**; NAV carries the source's own "as of" date.
5. **Direct-plan growth schemes only**; other plans/AMCs are out of scope.
6. Refusals and not-found responses **short-circuit before the LLM** (instant, no cost).

---

## Disclaimer

> **Facts-only. No investment advice.**
> Answers are generated from official public sources and are for informational
> purposes only. Always refer to the linked source and official scheme documents
> before making any decision.

---

## Project structure

```
Growwchat/
├─ config.py              # one source of truth (env-overridable)
├─ ingest/                # load → chunk → embed → store (+ dump)
├─ query/                 # retrieve → generate → guardrails → pipeline
├─ ui/app.py              # Streamlit facts-only chat UI
├─ tests/                 # guardrail regression + evaluation harness
├─ data/
│  ├─ sources.md          # the 5 official URLs
│  └─ raw/*.txt           # cleaned scheme documents (+ html/ cache)
├─ artifacts/             # chunks.txt, chunks_with_embeddings.txt (generated)
├─ chroma_db/             # persisted vector store (generated)
├─ Prd.md · architecture.md · implementation.md
├─ sample_qa.md           # evaluated sample Q&A
└─ requirements.txt · .python-version · .env.example
```

## Deliverables (`Prd.md` §8)

| Deliverable | Where |
|-------------|-------|
| Working prototype / demo | Streamlit app (`ui/app.py`) + Render deploy + `sample_qa.md` |
| Source list (5 URLs) | [`data/sources.md`](data/sources.md) |
| README (setup, scope, limits) | this file |
| Sample Q&A file | [`sample_qa.md`](sample_qa.md) |
| Disclaimer snippet in UI | `ui/app.py` (sidebar + footer) |
