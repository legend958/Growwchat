"""Phase 7 — Facts-Only Chat Interface (Streamlit).

Wires the guarded query pipeline (Phase 6) into a tiny chat UI:

* Welcome line.
* 3 clickable example questions (buttons prefill the input box).
* Persistent note **"Facts-only. No investment advice."** + the PRD §9
  disclaimer (kept in the sidebar so it stays visible while chatting).
* Answer panel showing the body, **exactly one clickable citation link**,
  and "Last updated from sources:".
* Refusals (advice / performance / PII) and not-found answers rendered
  distinctly. No PII is ever collected or displayed.

Run
---
    streamlit run ui/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the repo root importable regardless of how streamlit launches the script.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st  # noqa: E402

from query.guardrails import not_found_message  # noqa: E402
from query.pipeline import ask  # noqa: E402

WELCOME = (
    "This assistant answers questions **only from the official HDFC scheme "
    "documents** (5 mutual fund schemes sourced from Groww). I share facts — "
    "never advice, opinions, or performance claims."
)

DISCLAIMER = (
    "**Facts-only. No investment advice.**  \n"
    "Answers are generated from official public sources and are for "
    "informational purposes only. Always refer to the linked source and "
    "official scheme documents before making any decision."
)

EXAMPLE_QUESTIONS = [
    "What is the expense ratio of HDFC Small Cap Fund?",
    "How long is the lock-in period for HDFC ELSS Tax Saver Fund?",
    "What is the benchmark of HDFC Large Cap Fund?",
]

st.set_page_config(
    page_title="HDFC MF FAQ – Facts-Only Assistant",
    page_icon="\U0001F4CA",  # 📊
)


@st.cache_data(show_spinner=False, max_entries=64)
def answer_question(question: str):
    """Cached wrapper: identical questions don't re-call retrieval + LLM."""
    return ask(question)


def render_answer(question: str) -> None:
    answer = answer_question(question)
    if answer.refusal:
        st.warning(answer.refusal)
        return
    if not answer.found:
        st.info(not_found_message(question))
        return

    # The guarded answer is "body\n\nSource: <url>\nLast updated from sources: <date>".
    # Show the body, then ONE clickable source link + the freshness footer.
    body, _, _ = answer.answer.partition("\n\nSource: ")
    st.markdown(body)
    st.markdown(f"**Source:** [{answer.source_url}]({answer.source_url})")
    st.caption(f"Last updated from sources: {answer.last_updated}")


st.title("HDFC Mutual Fund FAQ")
st.write(WELCOME)

with st.sidebar:
    st.markdown(DISCLAIMER)

st.markdown("**Try an example:**")
for example in EXAMPLE_QUESTIONS:
    if st.button(example):
        st.session_state.question = example

question = st.text_input(
    "Ask a question about the official HDFC scheme documents",
    placeholder="e.g. What is the exit load of HDFC Equity Fund?",
    key="question",
)

if question and question.strip():
    st.markdown("---")
    st.markdown(f"**You asked:** {question}")
    with st.spinner("Searching the official sources…"):
        render_answer(question.strip())

st.markdown("---")
st.markdown(DISCLAIMER)