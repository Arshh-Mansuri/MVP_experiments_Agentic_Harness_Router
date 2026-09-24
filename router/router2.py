"""Router v2 pick functions (Luna via OpenRouter). Prompts hold task text + factual harness capability cards only."""
import glob, json, os, sys
from langchain_openai import ChatOpenAI

HARNESSES = ["terminus-2", "mini-swe-agent", "pi"]
DEFAULT = "terminus-2"   # harbor's own default agent; used on ties / low confidence
TASK_ROOT = os.path.expanduser("~/.cache/harbor/tasks/packages/terminal-bench")
TB_FALLBACK = os.environ.get("TB_TASK_DIR", "")

CARDS = {
    "terminus-2": "Drives one persistent tmux terminal by sending keystrokes and reading the raw screen. Terminal state (cwd, env vars, running programs) persists between steps. Suited to interactive programs, long-running commands and tasks that depend on live terminal state.",
    "mini-swe-agent": "Runs every bash command in a fresh subprocess, so no terminal state persists; files are edited through shell commands. Suited to self-contained scripting, data processing and repository bug fixes.",
    "pi": "Has dedicated file read, write and edit tools plus a bash tool, and can view images. Suited to creating or editing files and tasks involving images or documents.",
}

V1_PROMPT = """You route programming tasks to the most suitable agent harness.

Harnesses:
{descs}

Task:
\"\"\"
{task}
\"\"\"

Choose the single best harness for this task. Reply as JSON: {{"harness": "<name>"}}"""

V2_PROMPT = """You choose which agent harness should attempt a terminal task. Rate how well each harness fits the task from 1 (poor) to 5 (excellent), based on what the task requires and what each harness can do.

Harnesses:
{descs}

Task:
\"\"\"
{task}
\"\"\"

Reply with only JSON: {{"reason": "<one short sentence about what the task needs>", "terminus-2": <1-5>, "mini-swe-agent": <1-5>, "pi": <1-5>}}"""


def task_text(task):
    p = glob.glob(f"{TASK_ROOT}/{task}/*/instruction.md") or glob.glob(os.path.join(TB_FALLBACK, task, "instruction.md"))
    return open(p[0]).read().strip()[:3000]


_llm = None
def _call(prompt):
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(model="openai/gpt-5.6-luna", base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"],
                          temperature=0, timeout=60, max_retries=2, extra_body={"usage": {"include": True}})
    out = _llm.invoke(prompt)
    u = out.usage_metadata or {}
    cost = (out.response_metadata or {}).get("token_usage", {}).get("cost") or 0.0
    txt = out.content.strip().strip("`").removeprefix("json").strip()
    try:
        return json.loads(txt), u.get("total_tokens", 0), cost
    except Exception:
        return None, u.get("total_tokens", 0), cost


def pick_v1(task):
    descs = "\n".join(f"- {k}: {v}" for k, v in CARDS.items())
    d, tok, cost = _call(V1_PROMPT.format(descs=descs, task=task_text(task)) + " Reply with only the JSON.")
    h = (d or {}).get("harness")
    return (h if h in HARNESSES else DEFAULT), {"tokens": tok, "cost": cost}


def scores(task):
    descs = "\n".join(f"- {k}: {v}" for k, v in CARDS.items())
    d, tok, cost = _call(V2_PROMPT.format(descs=descs, task=task_text(task)))
    try:
        sc = {h: int(d[h]) for h in HARNESSES}
    except Exception:
        sc = {h: 3 for h in HARNESSES}
    return sc, (d or {}).get("reason", ""), {"tokens": tok, "cost": cost}


def pick_from_scores(sc, margin=1):
    """argmax; the default wins ties, and another harness must beat the default's score by `margin` to override it."""
    best = max(sc, key=lambda h: (sc[h], h == DEFAULT))
    return best if sc[best] - sc[DEFAULT] >= margin else DEFAULT
