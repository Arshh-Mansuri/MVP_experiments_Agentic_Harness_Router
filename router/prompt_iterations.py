"""Compare router prompt variants offline.

Each variant asks Luna to route the 21 tasks that have outcomes for all three harnesses; a pick is scored with
the measured mean reward and mean cost of that task x harness (outcomes.py), so no Harbor runs are needed.
All variants were written before any of them was scored. Prompts stay blind: task text + harness facts only.
Stdlib only (plain HTTP to OpenRouter), so it does not depend on the router venv.

usage: python prompt_iterations.py [--reps 2]
"""
import argparse, collections, glob, json, os, re, statistics as st, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
import outcomes
from eval_routers import TRAIN, HELD
from router2 import CARDS, GUIDE, HARNESSES, DEFAULT, V1_PROMPT, task_text

HERE = os.path.dirname(os.path.abspath(__file__))
JOBS = os.path.join(HERE, "..", "jobs")
OUT = os.path.join(HERE, "prompt_iterations_results.json")
MODEL = "openai/gpt-5.6-luna"

ORIGINAL_DESCS = {
    "terminus-2": "Works interactively in a live terminal: runs commands, watches the output, and handles system administration, data recovery, file and environment tasks.",
    "mini-swe-agent": "Runs bash commands step by step in a repository; suited to reading code and making code changes or bug fixes.",
    "pi": "Uses dedicated file read, write and edit tools plus a shell; suited to writing and modifying source files.",
}

P0_ORIGINAL = """You route programming tasks to the most suitable agent harness.

Harnesses:
{descs}

Task:
\"\"\"
{task}
\"\"\"

Choose the single best harness for this task. Reply as JSON: {{"harness": "<name>"}} Reply with only the JSON."""

P2_CHECKLIST = """You are deciding which agent harness should attempt a terminal task. Do not pick a harness directly. Instead, answer four factual questions about what solving the task will require. Read the whole task, including any files, programs and outputs it mentions.

Harnesses (for context):
{descs}

Questions:
1. interactive: Will the agent need to type into a program that is waiting for input while it runs, for example a REPL, a debugger, a text editor, an installer or login prompt, a game, or a full-screen terminal UI? Running a command that finishes on its own is NOT interactive.
2. persistent: Must a process stay alive across several steps while the agent keeps working (for example a server it starts and then sends requests to), or must shell state (current directory, activated environment, exported variables) carry over between commands?
3. images: Must the agent look at an image file (a photo, a screenshot, a picture of code, a board or a chart) to get information that is not available as text?
4. heavy_editing: Is the main deliverable a substantial amount of new source code (roughly 150 lines or more), or precise edits spread across several existing files?

Answer each strictly from the task text. If the task does not clearly require it, answer false.

Task:
\"\"\"
{task}
\"\"\"

Reply with only JSON: {{"interactive": true or false, "persistent": true or false, "images": true or false, "heavy_editing": true or false}}"""

P3_PLAN_RISKS = """You route a terminal task to one of three agent harnesses. Work through the steps below before choosing.

Harnesses:
{descs}

Steps:
1. Plan: in two or three short sentences, describe the concrete steps an agent would take to solve this task: what it inspects, what it builds or edits, and how it checks the result.
2. Risks: for each harness, name the single most likely way it would fail at that plan because of its limits (for example: cannot answer an interactive prompt; clumsy at writing a long file by typing; cannot see an image; loses a background process between commands). Write "none" if there is no specific risk.
3. Choose: pick the harness whose most likely failure is least likely or least serious. If no harness has a specific risk, choose mini-swe-agent.

Task:
\"\"\"
{task}
\"\"\"

Reply with only JSON: {{"plan": "<2-3 sentences>", "risks": {{"terminus-2": "<risk>", "mini-swe-agent": "<risk>", "pi": "<risk>"}}, "harness": "<name>"}}"""

P4_FEWSHOT = """You route programming tasks to the most suitable agent harness.

Harnesses:
{descs}

""" + GUIDE + """

Worked examples (invented tasks, not from any benchmark):
- "Start the web app in /app, confirm with curl that /health returns 200 while it is running, and leave it running." -> terminus-2 (a server must stay alive while the agent keeps working)
- "Use gdb to find which input makes /app/bin crash and write it to /app/answer.txt." -> terminus-2 (drives an interactive debugger)
- "The file /app/diagram.png shows a state machine. Implement it in /app/fsm.py." -> pi (the information is only in an image)
- "Write a C program in /app/server.c implementing a small HTTP/1.1 server with routing and static files." -> pi (the main work is writing a large new source file)
- "Count the words in every .txt file under /docs and write the 10 most common to /app/top.txt." -> mini-swe-agent (non-interactive scripting)
- "The tests in /repo started failing after the last commit; find and fix the bug." -> mini-swe-agent (repository bug fix through commands)

Task:
\"\"\"
{task}
\"\"\"

Choose the single best harness for this task. Reply with only JSON: {{"harness": "<name>"}}"""


def checklist_pick(d):
    if d.get("interactive") is True or d.get("persistent") is True:
        return "terminus-2"
    if d.get("images") is True or d.get("heavy_editing") is True:
        return "pi"
    return "mini-swe-agent"


def descs(cards):
    return "\n".join(f"- {k}: {v}" for k, v in cards.items())


VARIANTS = {
    "p0_original": (P0_ORIGINAL, ORIGINAL_DESCS, lambda d: d.get("harness")),
    "p1_rules": (V1_PROMPT + " Reply with only the JSON.", CARDS, lambda d: d.get("harness")),
    "p2_checklist": (P2_CHECKLIST, CARDS, checklist_pick),
    "p3_plan_risks": (P3_PLAN_RISKS, CARDS, lambda d: d.get("harness")),
    "p4_fewshot": (P4_FEWSHOT, CARDS, lambda d: d.get("harness")),
}


def call(prompt, key, model):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0,
                       "usage": {"include": True}}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", body,
                                 {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as e:
            err = e
            time.sleep(2 * (attempt + 1))
    raise err


def parse(txt):
    m = re.search(r"\{.*\}", txt or "", re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None


def route(job, key, model):
    variant, rep, task = job
    tmpl, cards, pick = VARIANTS[variant]
    try:
        r = call(tmpl.format(descs=descs(cards), task=task_text(task)), key, model)
        txt = r["choices"][0]["message"]["content"]
        d = parse(txt)
        h = pick(d) if d else None
        u = r.get("usage") or {}
        return {"variant": variant, "rep": rep, "task": task, "model": r.get("model"), "raw": d, "pick": h if h in HARNESSES else DEFAULT,
                "valid": h in HARNESSES, "tokens": u.get("total_tokens", 0), "cost": u.get("cost") or 0.0}
    except Exception as e:
        return {"variant": variant, "rep": rep, "task": task, "raw": None, "pick": DEFAULT, "valid": False,
                "tokens": 0, "cost": 0.0, "error": repr(e)[:200]}


def cost_table():
    t = collections.defaultdict(lambda: collections.defaultdict(list))
    for f in glob.glob(f"{JOBS}/*/*__*/result.json"):
        if "/livetest-" in f or "/wdtest-" in f:
            continue
        r = json.load(open(f))
        h = (r.get("agent_info") or {}).get("name")
        model = ((r.get("agent_info") or {}).get("model_info") or {}).get("name")
        rew = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        c = (r.get("agent_result") or {}).get("cost_usd")
        if h in HARNESSES and model == outcomes.MODEL and rew is not None and c is not None:
            t[r["trial_name"].rsplit("__", 1)[0]][h].append(c)
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--variants", nargs="+", default=list(VARIANTS), choices=list(VARIANTS))
    ap.add_argument("--model", default=MODEL, help="OpenRouter model that does the routing")
    a = ap.parse_args()
    out = OUT if len(a.variants) == len(VARIANTS) else OUT.replace(".json", f"_{'_'.join(a.variants)}.json")
    if a.model != MODEL:
        out = out.replace(".json", f"_{a.model.split('/')[-1]}.json")
    key = os.environ["OPENROUTER_API_KEY"]
    O, C = outcomes.build(JOBS), cost_table()
    tasks = [t for t in TRAIN + HELD if all(O[t].get(h) for h in HARNESSES)]
    rew = lambda t, h: st.mean(O[t][h])
    cost = lambda t, h: st.mean(C[t][h]) if C[t].get(h) else 0.0

    jobs = [(v, r, t) for v in a.variants for r in range(a.reps) for t in tasks]
    with ThreadPoolExecutor(8) as ex:
        rows = list(ex.map(lambda j: route(j, key, a.model), jobs))
    json.dump(rows, open(out, "w"), indent=1)

    splits = {"train": [t for t in tasks if t in TRAIN], "held": [t for t in tasks if t in HELD], "all": tasks}
    print(f"router model {a.model}; {len(tasks)} tasks ({len(splits['train'])} train / {len(splits['held'])} held-out), {a.reps} reps per variant\n")
    print(f"{'strategy':22} {'train':>7} {'held':>7} {'all':>7} {'exec $':>8}  picks (t2/mini/pi)   invalid  route $")

    def line(name, picks, extra=""):
        s = {k: sum(rew(t, picks[t]) for t in ts) for k, ts in splits.items()}
        c = sum(cost(t, picks[t]) for t in tasks)
        n = collections.Counter(picks[t] for t in tasks)
        print(f"{name:22} {s['train']:7.2f} {s['held']:7.2f} {s['all']:7.2f} {c:8.3f}  "
              f"{n['terminus-2']:2}/{n['mini-swe-agent']:2}/{n['pi']:2}{extra}")

    for h in HARNESSES:
        line(f"fixed {h}", {t: h for t in tasks})
    line("oracle", {t: max(HARNESSES, key=lambda h: (rew(t, h), -cost(t, h))) for t in tasks})
    rnd = {k: sum(st.mean(rew(t, h) for h in HARNESSES) for t in ts) for k, ts in splits.items()}
    print(f"{'random (expected)':22} {rnd['train']:7.2f} {rnd['held']:7.2f} {rnd['all']:7.2f}")
    print()
    for v in a.variants:
        for r in range(a.reps):
            rs = [x for x in rows if x["variant"] == v and x["rep"] == r]
            picks = {x["task"]: x["pick"] for x in rs}
            line(f"{v} rep{r}", picks, f"          {sum(not x['valid'] for x in rs):3}    {sum(x['cost'] for x in rs):.4f}")
        if a.reps > 1:
            by = collections.defaultdict(set)
            for x in rows:
                if x["variant"] == v:
                    by[x["task"]].add(x["pick"])
            print(f"{'':22} picks identical across reps on {sum(len(s) == 1 for s in by.values())}/{len(tasks)} tasks")
    print(f"\ntotal routing cost: ${sum(x['cost'] for x in rows):.4f}; raw results in {os.path.basename(out)}")


if __name__ == "__main__":
    main()
