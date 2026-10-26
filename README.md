# 🧠 Multi-Step Reasoning Agent (Groq)

Planner → Executor (+ Python calculator) → Verifier, with retries. Uses the **Groq API**
(default `openai/gpt-oss-120b`), with a Streamlit UI that shows every agent / LLM / tool call live.

```
Question → 🗺️ Planner → ⚙️ Executor → 🧮 Python re-check → 🔎 Verifier ──pass──► JSON answer
               ▲                                              │
               └──────── fail: retry with the reasons ────────┘   (max 2 retries, then status=failed)
```

## Setup
1. Get a key: https://console.groq.com/keys
2. `cp .env.example .env` and paste it: `GROQ_API_KEY=gsk_...`
   (or paste it into the UI sidebar)
3. Run:
```bash
pip install -r requirements.txt
streamlit run app.py              # UI with live trace
python agent.py -v                # CLI, verbose   (-q "..." one question, --model llama-3.3-70b-versatile)
python tests.py                   # 13-question test suite -> logs/test_run_*.jsonl
```
In code: `from agent import Agent; Agent().solve("What is 15% of 240?")`

## Files
| File | What |
|---|---|
| `agent.py` | Groq client, safe calculator, Planner / Executor / Verifier, retry loop, CLI |
| `prompts.py` | **All prompts** (planner, executor, verifier), 2 few-shot examples each |
| `app.py` | Streamlit UI |
| `tests.py` | 8 easy + 5 tricky questions; logs question, JSON, verifier result, retries |
| `.env.example` | where your API key goes |

Models (sidebar or `GROQ_MODEL`): `openai/gpt-oss-120b` (reasoning, most accurate), `openai/gpt-oss-20b`,
`llama-3.3-70b-versatile`, `llama-3.1-8b-instant` (fastest). To use another provider, write a class with
`chat(prompt, temperature) -> (content, reasoning)` and pass it to `Agent(llm)`.

## Verification
| Check | How |
|---|---|
| `has_answer` | final value + answer present |
| `arithmetic_recheck` | every step's `calc` re-run in Python; must equal what the model wrote |
| `non_negative` | no negative counts/durations (unless the question allows it) |
| `independent_resolve` | LLM solves again **without seeing** the first answer; values must match |

If a code check fails, the independent LLM call is skipped and the agent retries with the failure
reasons added to the prompts. A wrong key / API outage fails immediately (no pointless retries).

## Efficiency
- 3 LLM calls per attempt, 2 when a code check already failed.
- JSON mode (`response_format: json_object`) + tolerant parser + one "JSON only" repair.
- Rate limits (HTTP 429): waits `retry-after` and retries automatically.
- Static prompt first, question last (prefix caching); one reused HTTP session.
- Arithmetic and time maths done by Python (`duration`, `fits`, …), not by the model.

## Output
```json
{"answer": "The journey takes 3 h 35 min (215 minutes).",
 "status": "success",
 "reasoning_visible_to_user": "14:30 to 18:05 is 215 minutes.",
 "metadata": {"plan": "...", "checks": [...], "retries": 0, "final_value": "215",
              "model": "openai/gpt-oss-120b", "llm_calls": 3, "elapsed_s": 4.1, "trace_file": "logs/traces/....json"}}
```
The model's reasoning (chain-of-thought) never appears in `answer` / `reasoning_visible_to_user`;
it goes to `logs/traces/` and the UI's trace view.

## Prompt design notes
- **Why:** planner only plans and picks a canonical answer format (minutes / HH:MM / number / list)
  so answers can be compared by code. Executor writes expressions; Python does the maths. Verifier
  re-solves blind, so it doesn't just agree with the first answer.
- **What tends not to work:** asking a model to "check its own answer" (it agrees with itself); prose
  arithmetic (looks right, numbers wrong); free-form answers ("3h 35m" vs "215") causing false mismatches.
  *Add your own findings after running `python tests.py`.*
- **With more time:** majority vote over several executor samples; ask a clarifying question on real
  ambiguity; a stronger model just for the verifier.

## Assumptions
24-hour clock; an end time earlier than the start wraps past midnight; a slot fits if it is at least
as long as needed; slots are not combined; durations compared in minutes.
