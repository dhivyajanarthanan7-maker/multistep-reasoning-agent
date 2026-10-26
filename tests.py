"""Test suite: 8 easy + 5 tricky questions. Logs question, final JSON, verifier result, retries.
Run:  python tests.py            (all)
      python tests.py tricky     (one category)"""
import json, sys, time
from pathlib import Path

from agent import Agent, same

CASES = [  # (id, category, question, expected canonical final_value)
    ("E1", "easy", "If a train leaves at 14:30 and arrives at 18:05, how long is the journey?", "215"),
    ("E2", "easy", "Alice has 3 red apples and twice as many green apples as red. How many apples does she have in total?", "9"),
    ("E3", "easy", "A meeting needs 60 minutes. There are free slots: 09:00–09:30, 09:45–10:30, 11:00–12:00. Which slots can fit the meeting?", "11:00-12:00"),
    ("E4", "easy", "A shop sells pens at 12 rupees each. How much do 7 pens cost?", "84"),
    ("E5", "easy", "What is 15% of 240?", "36"),
    ("E6", "easy", "A movie starts at 19:45 and lasts 2 hours 20 minutes. At what time does it end?", "22:05"),
    ("E7", "easy", "Tom had 50 marbles, gave 18 to Sam and then bought 7 more. How many does he have now?", "39"),
    ("E8", "easy", "A car travels at 60 km/h for 2.5 hours. How far does it go in km?", "150"),
    ("T1", "tricky", "A night shift starts at 22:15 and ends at 06:40 the next morning. How long is the shift?", "505"),
    ("T2", "tricky", "A meeting needs 30 minutes. Free slots: 09:00–09:30, 10:00–10:25, 13:00–13:45. Which slots can fit it?", "09:00-09:30, 13:00-13:45"),
    ("T3", "tricky", "A bakery makes 120 cookies, sells 3/5 of them in the morning and half of the rest in the afternoon. How many are left?", "24"),
    ("T4", "tricky", "A bat and a ball cost 1.10 in total. The bat costs 1.00 more than the ball. How much does the ball cost?", "0.05"),
    ("T5", "tricky", "A 20 m straight fence has a post every 4 m, including both ends. How many posts are there?", "6"),
]


def run_suite(agent, cases=CASES, on_case=None, log_dir="logs"):
    rows = []
    for cid, cat, q, expected in cases:
        r = agent.solve(q)
        r.pop("_events", None)
        md = r["metadata"]
        row = {"id": cid, "category": cat, "question": q, "expected": expected, "final_value": md["final_value"],
               "correct": r["status"] == "success" and same(md["final_value"], expected),
               "verifier_passed": r["status"] == "success", "retried": md["retries"] > 0,
               "retries": md["retries"], "time_s": md["elapsed_s"], "result": r}
        rows.append(row)
        if on_case: on_case(row)
    Path(log_dir).mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    with open(f"{log_dir}/test_run_{stamp}.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in rows)
    return rows, f"{log_dir}/test_run_{stamp}.jsonl"


if __name__ == "__main__":
    cat = sys.argv[1] if len(sys.argv) > 1 else None
    cases = [c for c in CASES if not cat or c[1] == cat]
    yes = lambda b: "✅" if b else "❌"
    print(f"{'ID':4}{'correct':9}{'verifier':10}{'retries':9}{'time':>7}  answer")
    rows, path = run_suite(Agent(), cases, lambda x: print(
        f"{x['id']:4}{yes(x['correct']):9}{yes(x['verifier_passed']):10}{x['retries']:<9}{x['time_s']:>6}s  {x['result']['answer']}", flush=True))
    print(f"\nCorrect {sum(x['correct'] for x in rows)}/{len(rows)} · retried {sum(x['retried'] for x in rows)} · log: {path}")
