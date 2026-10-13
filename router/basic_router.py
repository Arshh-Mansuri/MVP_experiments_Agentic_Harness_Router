"""Basic router: one Luna call with a hand-written system prompt (router/basic_system_prompt.txt) whose rules come only
from the 89-task benchmark analysis, Qwen_89_Task_Comparison_2026-09-20.xlsx (aggregate pass rates per harness,
category, difficulty and task kind; no per-task results; router/basic_analysis.py recomputes every number). Luna's own
45-task runs and the success table are not used. The user message is the task's metadata from task.toml plus its
instruction.

  python3 router/basic_router.py <task>    print the decision as JSON (one Luna call)
"""
import glob, hashlib, json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profile_router as pr

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_PROMPT_FILE = os.path.join(HERE, "basic_system_prompt.txt")
MODEL = pr.ROUTER_MODELS["luna"]
TOML_DIRS = [os.path.expanduser("~/.cache/harbor/tasks/packages/terminal-bench/{task}/*/task.toml"),
             os.path.expanduser("~/.cache/harbor/tasks/*/{task}/task.toml")]
USER_TEMPLATE = """Task: {name}
Category: {category}
Difficulty: {difficulty}
Tags: {tags}
Agent time limit: {minutes} min

Instruction:
\"\"\"
{task}
\"\"\""""


class Trace(list):
    def step(self, what, **data):
        self.append({"step": what, **data})


def system_prompt():
    text = open(SYSTEM_PROMPT_FILE).read()
    return text, hashlib.sha256(text.encode()).hexdigest()[:16]


def task_meta(task):
    for pat in TOML_DIRS:
        p = glob.glob(pat.format(task=task))
        if p:
            s = open(p[0]).read()
            g = lambda k: (re.search(rf'^{k} = "?([^"\n]*)"?', s, re.M) or [None, None])[1]
            tags = re.search(r"^tags = \[(.*)\]", s, re.M)
            limit = re.search(r"\[agent\]\s*\ntimeout_sec = ([\d.]+)", s)
            return {"category": g("category"), "difficulty": g("difficulty"),
                    "tags": re.findall(r'"([^"]+)"', tags[1]) if tags else [],
                    "agent_minutes": round(float(limit[1]) / 60) if limit else None}
    return {"category": None, "difficulty": None, "tags": [], "agent_minutes": None}


def user_message(task):
    m = task_meta(task)
    return m, USER_TEMPLATE.format(name=task, category=m["category"] or "unknown",
                                   difficulty=m["difficulty"] or "unknown", tags=", ".join(m["tags"]) or "none",
                                   minutes=m["agent_minutes"] or "unknown", task=pr.task_text(task))


def route(task, key=None):
    """Returns (harness or None, info) in the shape the live runner and the exporter expect."""
    tr = Trace()
    system, sha = system_prompt()
    meta, user = user_message(task)
    tr.step("basic route start", task=task, model=MODEL, system_prompt_sha256=sha, **meta)
    start = time.time()
    r = pr.call(user, key or os.environ["OPENROUTER_API_KEY"], MODEL, system=system)
    txt = r["choices"][0]["message"]["content"] or ""
    d = pr.parse_json(txt)
    h = d.get("harness")
    u = r.get("usage") or {}
    info = {"underlying_model": r.get("model"), "table_sha256": None, "system_prompt_sha256": sha,
            "match": f"rule {d.get('rule')}" if d.get("rule") is not None else None, "rule": d.get("rule"),
            "reason": d.get("reason"), "raw": txt[:500], "seconds": round(time.time() - start, 2),
            "tokens": {"in": u.get("prompt_tokens"), "out": u.get("completion_tokens")}, "cost": pr.usage_cost(u),
            "byok": bool(u.get("is_byok")), "task_meta": meta, "user_message": user, "trace": tr}
    tr.step("router model replied", harness=h, rule=d.get("rule"), reason=d.get("reason"), seconds=info["seconds"],
            tokens=info["tokens"], cost=info["cost"], underlying_model=r.get("model"))
    if h not in pr.HARNESSES:
        tr.step("invalid reply: no harness returned", raw=txt[:300])
        h = None
    tr.step("decision", harness=h)
    return h, info


if __name__ == "__main__":
    h, info = route(sys.argv[1])
    info.pop("user_message")
    print(json.dumps({"harness": h, **info}, indent=1, default=str))
