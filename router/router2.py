"""Router v2 pick functions (Luna via OpenRouter). Prompts hold task text + factual harness capability cards only."""
import glob, json, os, sys

HARNESSES = ["terminus-2", "mini-swe-agent", "pi"]
DEFAULT = "mini-swe-agent"   # best fixed harness on the Qwen 89-task baseline; used on ties / low confidence
TASK_ROOT = os.path.expanduser("~/.cache/harbor/tasks/packages/terminal-bench")
TB_FALLBACK = os.environ.get("TB_TASK_DIR", "")

CARDS = {
    "terminus-2": "Controls one persistent tmux terminal by typing keystrokes and reading the screen. The shell session, working directory, environment variables and background processes persist between steps, and it can answer prompts inside running programs (REPLs, debuggers, editors, installers, password or y/n prompts, full-screen TUIs). Writing long files by typing is clumsy, and it only sees what is currently on screen.",
    "mini-swe-agent": "Runs each bash command in a fresh subprocess and reads its full output. Nothing carries over between commands except files on disk (no cd, exported variables or background jobs), and it cannot interact with programs that wait for input. Creates and edits files with shell commands (heredocs, sed, python). Simple and predictable for non-interactive work.",
    "pi": "Has dedicated tools to read, write and precisely edit files, plus a bash tool, and can view image files. Suited to creating or changing several source files, making targeted edits in large files, and tasks whose inputs include images or documents that must be inspected.",
}

GUIDE = """How to decide:
- Default to mini-swe-agent. It handles non-interactive work done through commands: scripting, data processing, building and installing software, running tests, and fixing bugs in an existing repository.
- Choose terminus-2 instead only when the task clearly depends on live terminal state: driving an interactive program or prompt, keeping a server or long-running process alive while testing it, or relying on the same shell session (cwd, environment, activated tools) across steps.
- Choose pi instead only when the task clearly requires looking at images, or its main work is writing or editing substantial source files (new programs, multi-file changes, precise edits to large files).
- When unsure, choose mini-swe-agent."""

V1_PROMPT = """You route programming tasks to the most suitable agent harness.

Harnesses:
{descs}

""" + GUIDE + """

Task:
\"\"\"
{task}
\"\"\"

Choose the single best harness for this task. Reply as JSON: {{"harness": "<name>"}}"""

V2_PROMPT = """You choose which agent harness should attempt a terminal task. Rate how well each harness fits the task from 1 (poor) to 5 (excellent), based on what the task requires and what each harness can do.

Harnesses:
{descs}

""" + GUIDE + """

Task:
\"\"\"
{task}
\"\"\"

Reply with only JSON: {{"reason": "<one short sentence naming the hardest part of the task>", "terminus-2": <1-5>, "mini-swe-agent": <1-5>, "pi": <1-5>}}"""


def task_text(task):
    p = glob.glob(f"{TASK_ROOT}/{task}/*/instruction.md") or glob.glob(os.path.join(TB_FALLBACK, task, "instruction.md"))
    return open(p[0]).read().strip()[:3000]


_llm = None
def _call(prompt):
    global _llm
    if _llm is None:
        from langchain_openai import ChatOpenAI
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
