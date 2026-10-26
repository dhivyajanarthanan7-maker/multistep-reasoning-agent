"""All prompts. Static instructions + examples come FIRST and the question comes LAST,
so the provider can reuse the cached prompt prefix between calls (faster, cheaper).
Examples use different questions from the test suite (no answer leakage)."""

FORMATS = 'number | minutes (for durations) | HH:MM (for clock times) | comma-separated list | yes/no'

PLANNER = r"""You are the PLANNER of a word-problem agent. Do NOT solve the problem.
Write 3-6 short steps, note any assumptions, and choose the answer format: """ + FORMATS + r""".
Return ONLY JSON: {"steps": ["..."], "assumptions": ["..."], "answer_format": "..."}

Example: "A bus leaves at 08:50 and arrives at 11:20. How long is the trip?"
{"steps": ["Convert both times to minutes", "Subtract departure from arrival (wrap 24h if negative)", "Report minutes"], "assumptions": ["same day, 24h clock"], "answer_format": "minutes"}

Example: "Ben has 4 blue pens and 3 times as many black pens. How many pens in total?"
{"steps": ["blue = 4", "black = 3 x blue", "total = blue + black"], "assumptions": ["only blue and black pens"], "answer_format": "number"}
{feedback}
QUESTION: {question}"""

EXECUTOR = r"""You are the EXECUTOR. Follow the plan step by step. Python re-checks every "calc",
so write each numeric step as an expression. Allowed in calc:
  + - * / // % ** ( ), min max abs round sum,
  duration("HH:MM","HH:MM") -> minutes (wraps past midnight),
  fits("start","end",minutes) -> True/False (equal length fits),
  mins("HH:MM") -> minutes since midnight, hhmm(minutes) -> "HH:MM", add_minutes("HH:MM", n) -> "HH:MM".
Use earlier "var" names. Always quote clock times. Non-numeric steps: "calc": null.
final_value must follow the plan's answer_format.
Return ONLY JSON: {"steps": [{"desc": "...", "calc": "...", "var": "...", "result": "..."}], "final_value": "...", "answer": "one short sentence", "explanation": "1-2 sentences"}

Example: bus leaves 08:50, arrives 11:20, trip length?
{"steps": [{"desc": "trip length", "calc": "duration(\"08:50\", \"11:20\")", "var": "trip", "result": "150"}], "final_value": "150", "answer": "The trip takes 2 h 30 min (150 minutes).", "explanation": "08:50 to 11:20 is 150 minutes."}

Example: a 45-minute call, free slots 13:00-13:30, 14:00-15:00, 15:15-16:00. Which fit?
{"steps": [{"desc": "slot 1", "calc": "fits(\"13:00\", \"13:30\", 45)", "var": "s1", "result": "False"}, {"desc": "slot 2", "calc": "fits(\"14:00\", \"15:00\", 45)", "var": "s2", "result": "True"}, {"desc": "slot 3, exactly 45 min", "calc": "fits(\"15:15\", \"16:00\", 45)", "var": "s3", "result": "True"}], "final_value": "14:00-15:00, 15:15-16:00", "answer": "The 14:00-15:00 and 15:15-16:00 slots fit.", "explanation": "The slots last 30, 60 and 45 minutes; 45 or more fits."}
{feedback}
QUESTION: {question}
PLAN: {plan}"""

VERIFIER = r"""You are the VERIFIER. Solve the question yourself, from scratch; you have NOT seen any other answer.
Watch for traps: crossing midnight, inclusive boundaries, fence-posts, percentages applied one after another,
"X more than" vs "X times". Return ONLY JSON: {"final_value": "...", "reason": "one sentence"}

Example: "A flight departs at 23:10 and lands at 01:45. How long is it?" (format: minutes)
{"final_value": "155", "reason": "50 min to midnight + 105 min after."}

Example: "Ben has 4 blue pens and 3 times as many black pens. How many pens in total?" (format: number)
{"final_value": "16", "reason": "4 + 3 x 4 = 16."}

QUESTION: {question} (format: {answer_format})"""

JSON_FIX = "\n\nYour previous reply was not valid JSON. Reply with ONLY the JSON object."


def fill(template: str, **kw) -> str:
    """str.replace instead of .format, so JSON braces in prompts don't need escaping."""
    for k, v in kw.items():
        template = template.replace("{" + k + "}", str(v))
    return template
