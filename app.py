"""Streamlit UI with a live verbose agent trace.   Run: streamlit run app.py"""
import json

import streamlit as st

from agent import MODEL, MODELS, Agent, Groq
from tests import CASES, run_suite

st.set_page_config("Reasoning Agent", "🧠", layout="wide")
ICON = {"agent": "🤖", "planner": "🗺️", "executor": "⚙️", "tool": "🧮", "verifier": "🔎"}

with st.sidebar:
    st.header("⚙️ Settings")
    key = st.text_input("Groq API key", type="password", placeholder="or set GROQ_API_KEY in .env")
    model = st.selectbox("Groq model", MODELS, index=MODELS.index(MODEL) if MODEL in MODELS else 0, help="gpt-oss models reason before answering (best for math)")
    temp = st.slider("Temperature", 0.0, 1.0, 0.3, 0.05)
    retries = st.number_input("Max retries", 0, 4, 2)
try:
    agent = Agent(Groq(key or None, model, temp), int(retries))
except ValueError as e:
    st.warning(f"🔑 {e}  Get a key at https://console.groq.com/keys")
    st.stop()


def show(e, box):
    d = e["data"]
    box.markdown(f"`{e['t']:5.1f}s` · #{e['attempt']} {ICON.get(e['phase'], '•')} **{e['phase']}** · {e['title']}")
    if "output" in d:
        with box.expander("prompt · thinking · output"):
            st.caption("Prompt"); st.code(d["prompt"], language="markdown")
            if d["thinking"]:
                st.caption("Model reasoning (chain-of-thought — logs only)"); st.text(d["thinking"])
            st.caption("Output"); st.code(d["output"], language="json")
    elif d.get("calcs"):
        box.table([{k: str(v) for k, v in r.items()} for r in d["calcs"]])
    elif d.get("feedback"):
        box.warning(d["feedback"])


solve_tab, suite_tab = st.tabs(["💬 Solve", "🧪 Test suite"])

with solve_tab:
    q = st.text_area("Question", CASES[0][2], height=80)
    if st.button("🚀 Solve", type="primary", disabled=not q.strip()):
        st.session_state.run = None
        live = st.container(border=True)
        with st.spinner("Planning → executing → verifying…"):
            st.session_state.run = (q, agent.solve(q, lambda e: show(e, live)))
        st.rerun()
    if st.session_state.get("run"):
        q, r = st.session_state.run
        events = r.pop("_events", None) or st.session_state.get("events", [])
        st.session_state.events = events
        (st.success if r["status"] == "success" else st.error)(f"**{r['answer']}**")
        st.write(r["reasoning_visible_to_user"])
        m = r["metadata"]
        c = st.columns(4)
        c[0].metric("Status", r["status"]); c[1].metric("Retries", m["retries"])
        c[2].metric("LLM calls", m["llm_calls"]); c[3].metric("Time", f"{m['elapsed_s']} s")
        t1, t2 = st.tabs(["🔍 Agent trace", "🧾 JSON"])
        with t1:
            box = st.container()
            for e in events:
                show(e, box)
        with t2:
            st.json(r)

with suite_tab:
    cat = st.radio("Cases", ["all", "easy", "tricky"], horizontal=True)
    cases = [x for x in CASES if cat == "all" or x[1] == cat]
    if st.button(f"▶️ Run {len(cases)} tests", type="primary"):
        table, rows = st.empty(), []
        def on_case(x):
            rows.append({k: ("✅" if v is True else "❌" if v is False else v) for k, v in x.items() if k != "result"})
            table.table(rows)
        with st.spinner("Running…"):
            results, path = run_suite(agent, cases, on_case)
        st.success(f"Correct {sum(x['correct'] for x in results)}/{len(results)} · "
                   f"retried {sum(x['retried'] for x in results)} · log saved to `{path}`")
        st.download_button("⬇️ Download log", "\n".join(json.dumps(x, ensure_ascii=False) for x in results),
                           "test_run.jsonl")
