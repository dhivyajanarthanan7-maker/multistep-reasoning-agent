"""Lightweight multi-step reasoning agent: Planner -> Executor (+Python calc) -> Verifier, with retries.

CLI:  python agent.py            interactive
      python agent.py -v         verbose trace
      python agent.py -q "..."   one question, prints JSON
Code: from agent import Agent;  Agent().solve("...")  -> dict
Needs GROQ_API_KEY in .env (see .env.example).
"""
import argparse, ast, json, operator as op, os, re, time
from pathlib import Path

import requests

import prompts as P

# Load GROQ_API_KEY etc. from a local .env file (no extra dependency)
ENV = Path(__file__).with_name(".env")
if ENV.exists():
    for line in ENV.read_text().splitlines():
        k, _, v = line.partition("=")
        if k.strip() and not k.startswith("#"):
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


# ============================================================ LLM client (swap this class for any provider)
class Groq:
    def __init__(self, api_key=None, model=MODEL, temperature=0.3):
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY missing — put it in .env or enter it in the UI sidebar.")
        self.model, self.temperature = model, temperature
        self.http = requests.Session()                       # reuse the TCP connection
        self.http.headers["Authorization"] = f"Bearer {self.api_key}"

    def chat(self, prompt, temperature=None):
        body = {"model": self.model, "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}],
                "temperature": self.temperature if temperature is None else temperature}
        for _ in range(4):
            r = self.http.post(GROQ_URL, json=body, timeout=120)
            if r.status_code == 429:                         # rate limit: wait and retry
                time.sleep(min(float(r.headers.get("retry-after", 5)), 30)); continue
            if r.status_code == 400 and "json" in r.text.lower() and "response_format" in body:
                body.pop("response_format"); continue        # JSON-mode rejected: let the parser handle it
            break
        if not r.ok:
            raise requests.HTTPError(f"Groq {r.status_code}: {r.text[:300]}")
        msg = r.json()["choices"][0]["message"]
        content, thinking = msg.get("content") or "", msg.get("reasoning") or ""
        m = re.search(r"<think>(.*?)</think>", content, re.S)
        if m:
            thinking, content = (thinking + m.group(1)).strip(), content.replace(m.group(0), "")
        return content.strip(), thinking.strip()


def parse_json(text):
    text = re.sub(r"<think>.*?</think>|```(json)?", "", text or "", flags=re.S)
    for i in (i for i, c in enumerate(text) if c == "{"):
        try:
            return json.JSONDecoder().raw_decode(text[i:])[0]
        except json.JSONDecodeError:
            pass
    raise ValueError(f"no JSON in reply: {text[:120]!r}")


# ============================================================ deterministic tools
def mins(t):
    h, m = map(int, str(t).strip().split(":"))
    if h > 23 or m > 59:
        raise ValueError(f"invalid time {t}")
    return h * 60 + m

def duration(a, b): d = mins(b) - mins(a); return d + 1440 if d < 0 else d
def fits(a, b, need): return mins(b) - mins(a) >= need
def hhmm(x): x = int(round(x)) % 1440; return f"{x // 60:02d}:{x % 60:02d}"
def add_minutes(t, n): return hhmm(mins(t) + n)

FUNCS = dict(min=min, max=max, abs=abs, round=round, sum=sum, mins=mins, duration=duration,
             fits=fits, hhmm=hhmm, add_minutes=add_minutes)
OPS = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.FloorDiv: op.floordiv,
       ast.Mod: op.mod, ast.Pow: op.pow, ast.USub: op.neg, ast.UAdd: op.pos, ast.Lt: op.lt, ast.LtE: op.le,
       ast.Gt: op.gt, ast.GtE: op.ge, ast.Eq: op.eq, ast.NotEq: op.ne}


def calc(expr, env):
    """Safe calculator: numbers, strings, + - * / ..., comparisons, whitelisted functions, earlier vars."""
    expr = re.split(r"(?<![=!<>])=(?!=)", str(expr).replace("×", "*").replace("^", "**"))[0].strip()

    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float, str)):
            return n.value
        if isinstance(n, ast.Name):
            if n.id in env: return env[n.id]
            if n.id in ("True", "False"): return n.id == "True"
            raise NameError(f"unknown name {n.id}")
        if isinstance(n, ast.BinOp):
            if isinstance(n.op, ast.Pow) and abs(ev(n.right)) > 100: raise ValueError("exponent too large")
            return OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp): return OPS[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Compare):
            return all(OPS[type(o)](ev(a), ev(b)) for o, a, b in zip(n.ops, [n.left] + n.comparators, n.comparators))
        if isinstance(n, (ast.List, ast.Tuple)): return [ev(e) for e in n.elts]
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) in FUNCS:
            return FUNCS[n.func.id](*[ev(a) for a in n.args])
        raise ValueError(f"not allowed: {type(n).__name__}")
    return ev(ast.parse(expr, mode="eval").body)


# ============================================================ value comparison
TIME, NUM = re.compile(r"(\d{1,2}):(\d{2})"), re.compile(r"-?\d+(?:\.\d+)?")

def signature(v):
    s = str(v).lower()
    return (sorted(f"{int(h):02d}:{m}" for h, m in TIME.findall(s)),
            sorted(round(float(x), 4) for x in NUM.findall(TIME.sub(" ", s.replace(",", " ")))))

def same(a, b):
    """'215' == '215 minutes', '11:00–12:00' == '11:00-12:00', order of list items ignored."""
    sa, sb = signature(a), signature(b)
    if sa == sb == ([], []):
        return str(a).strip().lower() == str(b).strip().lower()
    return sa == sb

def matches(stated, value):
    if stated in (None, ""): return True
    if isinstance(value, bool): return str(stated).strip().lower() in (("true", "yes") if value else ("false", "no"))
    if isinstance(value, (int, float)):
        n = NUM.findall(TIME.sub(" ", str(stated)))
        return bool(n) and abs(float(n[0]) - value) <= 0.005 + 1e-6 * abs(value)
    return same(stated, value)


# ============================================================ agent
class Agent:
    def __init__(self, llm=None, max_retries=2, log_dir="logs"):
        self.llm, self.max_retries, self.log_dir = llm or Groq(), max_retries, log_dir

    def _ask(self, role, prompt, log, temperature=None):
        for i in range(2):                                   # one repair retry on bad JSON
            t0 = time.time()
            content, thinking = self.llm.chat(prompt if i == 0 else prompt + P.JSON_FIX, temperature)
            log(role, f"LLM call {time.time() - t0:.1f}s", prompt=prompt, thinking=thinking, output=content)
            try:
                return parse_json(content)
            except ValueError as e:
                log(role, f"invalid JSON ({e})")
        raise ValueError(f"{role} returned invalid JSON twice")

    # ---- phase 1
    def plan(self, q, feedback, log):
        p = self._ask("planner", P.fill(P.PLANNER, question=q, feedback=feedback), log)
        p["steps"] = [str(s) for s in p.get("steps") or []] or ["Solve the question"]
        p.setdefault("answer_format", "number")
        log("planner", "plan: " + " → ".join(p["steps"]), plan=p)
        return p

    # ---- phase 2
    def execute(self, q, plan, feedback, log):
        plan_txt = "; ".join(plan["steps"]) + f" | assumptions: {plan.get('assumptions')} | answer_format: {plan['answer_format']}"
        s = self._ask("executor", P.fill(P.EXECUTOR, question=q, plan=plan_txt, feedback=feedback), log)
        env, rows = {}, []
        for i, st in enumerate(s.get("steps") or [], 1):
            if not isinstance(st, dict) or st.get("calc") in (None, "", "null"):
                continue
            row = {"step": i, "calc": st["calc"], "model_said": st.get("result"), "python": "", "ok": False}
            try:
                val = calc(st["calc"], env)
                row.update(python=val, ok=matches(st.get("result"), val))
                if str(st.get("var", "")).isidentifier():
                    env[st["var"]] = val
            except Exception as e:                           # bad expression = failed check
                row["python"] = f"error: {e}"
            rows.append(row)
        s["_calcs"] = rows
        log("tool", f"python re-ran {len(rows)} calc(s), {sum(not r['ok'] for r in rows)} problem(s)", calcs=rows)
        return s

    # ---- phase 3
    def verify(self, q, plan, sol, log):
        checks = []
        def add(name, ok, details):
            checks.append({"check_name": name, "passed": bool(ok), "details": details})
            log("verifier", f"{'✅' if ok else '❌'} {name}: {details}", check=checks[-1])

        fv = str(sol.get("final_value", "")).strip()
        add("has_answer", fv and sol.get("answer"), f"final_value={fv!r}")
        bad = [r for r in sol["_calcs"] if not r["ok"]]
        add("arithmetic_recheck", not bad, "all calcs match Python" if not bad else
            "; ".join(f"step {r['step']}: {r['calc']} → {r['python']} (model said {r['model_said']})" for r in bad))
        n = signature(fv)[1]
        neg_ok = re.search(r"negative|below zero|loss|debt|owe|temperature", q, re.I)
        add("non_negative", neg_ok or not n or min(n) >= 0, "no impossible negative values")
        if not all(c["passed"] for c in checks):             # already failed: skip the costly LLM call
            return checks
        ind = self._ask("verifier", P.fill(P.VERIFIER, question=q, answer_format=plan["answer_format"]), log,
                        temperature=0.7)
        iv = str(ind.get("final_value", ""))
        add("independent_resolve", same(fv, iv), f"proposed {fv!r} vs independent {iv!r}")
        return checks

    # ---- loop
    def solve(self, question, on_event=None):
        t0, events, cur = time.time(), [], {"attempt": 1}

        def log(phase, title, **data):
            e = {"t": round(time.time() - t0, 1), "attempt": cur["attempt"], "phase": phase, "title": title, "data": data}
            events.append(e)
            if on_event: on_event(e)

        plan, sol, checks, feedback = {}, {}, [], ""
        for attempt in range(self.max_retries + 1):
            cur["attempt"] = attempt + 1
            log("agent", f"attempt {attempt + 1}/{self.max_retries + 1}", feedback=feedback)
            try:
                plan = self.plan(question, feedback, log)
                sol = self.execute(question, plan, feedback, log)
                checks = self.verify(question, plan, sol, log)
            except requests.RequestException as e:           # backend down: retrying won't help
                checks = [{"check_name": "llm_backend", "passed": False, "details": f"Groq API error: {e}"}]
                log("agent", f"backend error: {e}")
                break
            except ValueError as e:
                checks = [{"check_name": "json_format", "passed": False, "details": str(e)}]
                log("agent", str(e))
            if all(c["passed"] for c in checks):
                break
            feedback = "\nPREVIOUS ATTEMPT FAILED VERIFICATION, fix:\n" + "\n".join(
                f"- {c['check_name']}: {c['details']}" for c in checks if not c["passed"])

        ok = bool(checks) and all(c["passed"] for c in checks)
        failed = "; ".join(f"{c['check_name']} ({c['details']})" for c in checks if not c["passed"])
        result = {
            "answer": sol.get("answer") if ok else "Could not produce a verified answer.",
            "status": "success" if ok else "failed",
            "reasoning_visible_to_user": sol.get("explanation", "") if ok else
                f"Verification failed after {cur['attempt']} attempt(s): {failed}."
                + (f" Unverified candidate: {sol['answer']}" if sol.get("answer") else ""),
            "metadata": {"plan": " → ".join(plan.get("steps", [])), "checks": checks, "retries": cur["attempt"] - 1,
                         "final_value": sol.get("final_value"), "model": getattr(self.llm, "model", "?"),
                         "llm_calls": sum(e["title"].startswith("LLM call") for e in events),
                         "elapsed_s": round(time.time() - t0, 1)},
        }
        try:                                                 # full chain-of-thought goes to logs only
            path = Path(self.log_dir, "traces", time.strftime("%Y%m%d-%H%M%S") + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"question": question, "result": result, "events": events}, indent=1, default=str))
            result["metadata"]["trace_file"] = str(path)
        except OSError:
            pass
        result["_events"] = events                           # for the UI; strip before showing JSON
        return result


# ============================================================ CLI
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-q", "--question"); ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--model", default=MODEL, help=f"one of {MODELS}")
    a = ap.parse_args()
    agent = Agent(Groq(model=a.model))
    show = (lambda e: print(f"[{e['t']:6.1f}s] #{e['attempt']} {e['phase']:9} {e['title'][:150]}")) if a.verbose else None

    def run(q):
        r = agent.solve(q, show); r.pop("_events")
        print(json.dumps(r, indent=2, ensure_ascii=False))

    if a.question:
        return run(a.question)
    print(f"Reasoning agent ({a.model}). Type 'exit' to quit.")
    while (q := input("\n❓ ").strip()).lower() not in ("exit", "quit"):
        if q: run(q)


if __name__ == "__main__":
    main()
