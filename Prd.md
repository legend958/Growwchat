# PRD — Mutual Fund FAQs (Facts-Only Q&A RAG Chatbot)

**Status:** Draft
**Source:** `Docs/Problemstatement.txt`
**Last updated:** 2026-10-12

---

## 1. Overview

Build a small **FAQ assistant** that answers factual questions about mutual fund schemes — expense ratio, exit load, minimum SIP, lock-in (ELSS), riskometer, benchmark, and how to download statements — using **only official public pages**. Every answer must include **one source link**. **No investment advice.**

The end output is a **RAG (Retrieval-Augmented Generation) chatbot** that answers questions using only the provided source data, following all standard RAG stages for both **data ingestion** and **data retrieval**.

### 1.1 Problem

Retail users comparing schemes and support/content teams answering repetitive mutual fund questions need fast, trustworthy, facts-only answers. Answers must be traceable to official sources and must never drift into advice.

### 1.2 Who this helps

- **Retail users** comparing mutual fund schemes.
- **Support / content teams** answering repetitive MF questions.

---

## 2. Goals

- Deliver a working facts-only Q&A assistant over a scoped corpus of official mutual fund pages.
- Guarantee a **citation link in every factual answer**.
- Reliably **refuse opinionated / portfolio questions** with a polite, facts-only message plus a relevant educational link.
- Implement the full RAG pipeline: **Ingestion (Load → Chunk → Embed → Store in Vector DB)** and **Query (Question → Embed → Retrieve top chunks → LLM → Answer)**.

## 3. Non-Goals

- No investment advice, recommendations, or portfolio guidance.
- No return computation, comparison, or performance claims.
- No handling or storage of PII (PAN, Aadhaar, account numbers, OTPs, emails, phone numbers).
- No use of third-party blogs or app back-end screenshots as sources.

---

## 4. Scope

### 4.1 AMC and Schemes

**AMC:** HDFC Mutual Fund
Pick **one AMC and 3–5 schemes** under it (e.g., one large-cap, one flexi-cap, one ELSS).

| # | Category | Scheme | Source URL |
|---|----------|--------|------------|
| 1 | Large Cap | HDFC Large Cap Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| 2 | Flexi Cap | HDFC Equity Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| 3 | ELSS | HDFC ELSS Tax Saver Fund – Direct Plan Growth | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| 4 | Small Cap | HDFC Small Cap Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth |
| 5 | Balanced Advantage (Hybrid) | HDFC Balanced Advantage Fund – Direct Growth | https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth |

### 4.2 Corpus

Collect the public pages from **AMC / SEBI / AMFI**:

- Factsheets
- KIM / SID
- Scheme FAQs
- Fee / charges pages
- Riskometer / benchmark notes
- Statement / tax-doc guides

---

## 5. Functional Requirements

### 5.1 FAQ Assistant (working prototype)

- **FR-1 — Factual query answering.** Answer factual queries only, e.g.:
  - "Expense ratio of [scheme]?"
  - "ELSS lock-in?"
  - "Minimum SIP?"
  - "Exit load?"
  - "Riskometer / benchmark?"
  - "How to download capital-gains statement?"
- **FR-2 — Citation.** Show **one clear citation link in every answer**.
- **FR-3 — Refusal.** Refuse opinionated / portfolio questions (e.g., "Should I buy/sell?") with a polite, facts-only message and a relevant educational link.
- **FR-4 — Tiny UI.** Welcome line + 3 example questions + a note: **"Facts-only. No investment advice."**

### 5.2 Answer constraints

- **FR-5** — Keep answers **≤ 3 sentences**.
- **FR-6** — Add **"Last updated from sources: "** to answers.

---

## 6. RAG Pipeline

### 6.1 Ingestion

`Load → Chunk → Embed → Store in Vector DB`

### 6.2 Query

`Question → Embed → Retrieve top chunks → LLM → Answer`

### 6.3 Tech Constraints

- **Embedding model:** `sentence-transformers/all-MiniLM-L6-v2`. Runs locally, needs **no API key**, produces **384-dimension vectors**. Use the **same model** to embed both the chunks and the user's question.
- **Chunking strategy:** decided by the AI agent (Cursor, OpenCode, or Claude Code). Before writing any code, the agent must:
  1. Inspect the data.
  2. Propose a strategy and say why it suits this data.
  3. Specify **chunk size**, **overlap**, and **what metadata each chunk keeps**.
  4. Save all chunks to a **readable `.txt` file** so they can be inspected.
- **Vector DB:** **ChromaDB**, persisted to disk, so ingestion runs **once** and not on every restart.

---

## 7. Key Constraints

- **Public sources only.** No screenshots of the app back-end; no third-party blogs as sources.
- **No PII.** Do not accept or store PAN, Aadhaar, account numbers, OTPs, emails, or phone numbers.
- **No performance claims.** Don't compute or compare returns; link to the official factsheet if asked.
- **Clarity & transparency.** Keep answers ≤ 3 sentences; add "Last updated from sources: ".

---

## 8. Deliverables

1. **Working prototype** link (app / notebook) — or a **≤ 3-min demo video** if hosting isn't possible.
2. **Source list** (CSV / MD) of the 5 URLs used.
3. **README** with setup steps, scope (AMC + schemes), and known limits.
4. **Sample Q&A file** — 5–10 queries with the assistant's answers + links.
5. **Disclaimer snippet** used in the UI (facts-only, no advice).

---

## 9. Disclaimer Snippet (UI)

> **Facts-only. No investment advice.**
> Answers are generated from official public sources and are for informational purposes only. Always refer to the linked source and official scheme documents before making any decision.

---

## 10. Success Metrics

- Answer accuracy against the scoped official sources.
- **100% of factual answers include a citation link.**
- **100% of opinionated / portfolio questions are refused** with a polish, facts-only message.
- Answers respect the ≤ 3-sentence limit and include "Last updated from sources: ".
- Ingestion persists via ChromaDB so the vector store is not rebuilt on restart.

## 11. Assumptions & Risks

- **Assumption:** The scoped source pages are publicly accessible and stable enough to scrape/collect.
- **Risk:** Source pages change over time → answers may go stale; mitigate with the "Last updated from sources" timestamp and re-ingestion.
- **Risk:** Retrieval may surface an irrelevant chunk leading to an off-scope answer → mitigate with a top-k / similarity threshold and refusal fallback.
- **Risk:** Ambiguous queries could edge toward advice → maintain a strict refusal guardrail for opinionated questions.
