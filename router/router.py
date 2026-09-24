"""Gemma-3-270M harness router (LangChain + LangGraph).

Blind by design: the prompt contains only the task text and generic harness
descriptions. No prior benchmark results are used anywhere in this file.
"""
import argparse, collections, glob, itertools, json, os, subprocess, sys, time
from typing import TypedDict, Optional
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, START, END

TASK_ROOT = os.path.expanduser("~/.cache/harbor/tasks/packages/terminal-bench")
LOG = os.path.join(os.path.dirname(__file__), "router_log.jsonl")
MODEL = "openrouter/openai/gpt-5.6-luna"
HARNESSES = ["terminus-2", "mini-swe-agent", "pi"]
FALLBACK = "terminus-2"  # harbor's default agent; used only if Gemma output is invalid

HARNESS_DESCRIPTIONS = {
    "terminus-2": "Works interactively in a live terminal: runs commands, watches the output, and handles system administration, data recovery, file and environment tasks.",
    "mini-swe-agent": "Runs bash commands step by step in a repository; suited to reading code and making code changes or bug fixes.",
    "pi": "Uses dedicated file read, write and edit tools plus a shell; suited to writing and modifying source files.",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "harness": {"type": "string", "enum": HARNESSES},
    },
    "required": ["harness"],
}

PROMPT = """You route programming tasks to the most suitable agent harness.

Harnesses:
{descs}

Task:
\"\"\"
{task}
\"\"\"

Choose the single best harness for this task. Reply as JSON: {{"harness": "<name>"}}"""


class S(TypedDict, total=False):
    task: str
    task_text: str
    raw: str
    votes: dict
    harness: str
    valid: bool
    classify_s: float
    run: Optional[dict]
    execute: bool
    force: str
    tag: str
    router: str
    router_tokens: dict
    router_cost: float
    cwd: str


def load_task(s: S) -> S:
    p = glob.glob(f"{TASK_ROOT}/{s['task']}/*/instruction.md") or glob.glob(os.path.join(os.environ.get("TB_TASK_DIR", "/nonexistent"), s["task"], "instruction.md"))
    if not p:
        sys.exit(f"instruction.md not found for {s['task']}")
    return {"task_text": open(p[0]).read().strip()[:3000]}


def classify(s: S) -> S:
    if s.get("force"):
        return {"raw": "forced", "votes": {s["force"]: 1}, "classify_s": 0.0}
    if s.get("router") == "gate":
        from gate_router import pick as gate_pick
        t = time.time()
        h, proba = gate_pick(s["task_text"])
        if h not in HARNESSES:  # gate_router also knows opencode (from the Qwen study); this pipeline only runs the 3 above
            h = max(HARNESSES, key=lambda k: proba.get(k, 0.0))
        return {"raw": json.dumps(proba), "votes": {h: 1}, "classify_s": round(time.time() - t, 3)}
    if s.get("router") == "luna":
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model="openai/gpt-5.6-luna", base_url="https://openrouter.ai/api/v1",
                         api_key=os.environ["OPENROUTER_API_KEY"], timeout=60, max_retries=2, extra_body={"usage": {"include": True}})
        descs = "\n".join(f"- {k}: {v}" for k, v in HARNESS_DESCRIPTIONS.items())
        t = time.time()
        out = llm.invoke(PROMPT.format(descs=descs, task=s["task_text"]) + " Reply with only the JSON.")
        u = out.usage_metadata or {}
        tu = (out.response_metadata or {}).get("token_usage", {})
        try:
            h = json.loads(out.content.strip().strip("`").removeprefix("json").strip()).get("harness")
        except Exception:
            h = None
        v = {h: 1} if h in HARNESSES else {}
        return {"raw": out.content, "votes": v, "classify_s": round(time.time() - t, 3),
                "router_tokens": {"in": u.get("input_tokens"), "out": u.get("output_tokens"), "total": u.get("total_tokens")},
                "router_cost": tu.get("cost")}
    llm = ChatOllama(model="gemma3:270m", temperature=0, format=SCHEMA)
    t = time.time()
    votes, raws = collections.Counter(), []
    for order in itertools.permutations(HARNESSES):  # vote over all list orderings to cancel position bias
        descs = "\n".join(f"- {k}: {HARNESS_DESCRIPTIONS[k]}" for k in order)
        out = llm.invoke(PROMPT.format(descs=descs, task=s["task_text"])).content
        raws.append(out)
        try:
            h = json.loads(out).get("harness")
        except Exception:
            h = None
        if h in HARNESSES:
            votes[h] += 1
    return {"raw": json.dumps({"votes": dict(votes)}), "votes": dict(votes), "classify_s": round(time.time() - t, 3)}


def validate(s: S) -> S:
    v = s.get("votes") or {}
    top = sorted(v.items(), key=lambda kv: -kv[1])
    ok = bool(top) and (len(top) == 1 or top[0][1] > top[1][1])  # unique plurality winner
    return {"harness": top[0][0] if ok else FALLBACK, "valid": ok}


def dispatch(s: S) -> S:
    if not s.get("execute"):
        return {"run": None}
    job = f"routed-{s.get('router','gemma')}-{s['task']}-{s.get('tag','r')}-{int(time.time())}"
    if s.get("force"):
        job = f"direct-{s['harness']}-{s['task']}-{s.get('tag','r')}"
    cmd = ["harbor", "run", "-t", f"terminal-bench/{s['task']}", "--model", MODEL, "--agent", s["harness"], "--job-name", job]
    t = time.time()
    p = subprocess.run(cmd, env=dict(os.environ), cwd=s["cwd"], capture_output=True, text=True)
    return {"run": {"rc": p.returncode, "wall_s": round(time.time() - t, 1), "job": job, "tail": p.stdout[-600:]}}


def log(s: S) -> S:
    rec = {k: s.get(k) for k in ("task", "router", "raw", "harness", "valid", "classify_s", "router_tokens", "router_cost", "run")}
    rec["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    open(LOG, "a").write(json.dumps(rec) + "\n")
    return {}


def build():
    g = StateGraph(S)
    for n, f in [("load_task", load_task), ("classify", classify), ("validate", validate), ("dispatch", dispatch), ("log", log)]:
        g.add_node(n, f)
    g.add_edge(START, "load_task"); g.add_edge("load_task", "classify")
    g.add_edge("classify", "validate"); g.add_edge("validate", "dispatch")
    g.add_edge("dispatch", "log"); g.add_edge("log", END)
    return g.compile()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks", nargs="+")
    ap.add_argument("--execute", action="store_true", help="actually run harbor with the chosen harness")
    ap.add_argument("--router", default="gemma", choices=["gemma", "luna", "gate"])
    ap.add_argument("--force", default="", choices=["", "terminus-2", "mini-swe-agent", "pi"], help="skip routing, use this harness")
    ap.add_argument("--tag", default="r")
    ap.add_argument("--cwd", default=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    a = ap.parse_args()
    app = build()
    for t in a.tasks:
        r = app.invoke({"task": t, "execute": a.execute, "router": a.router, "tag": a.tag, "force": a.force, "cwd": a.cwd})
        print(f"{t}: {r['harness']} (valid={r['valid']}, {r['classify_s']}s) tokens={r.get('router_tokens')} cost={r.get('router_cost')} raw={r['raw']}")
