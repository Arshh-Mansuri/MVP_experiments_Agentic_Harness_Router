"""Table router: picks a harness from the frozen success table (router/success_table.json).

Fast path, no model call: a task listed in Table A (every task Luna has run) gets its best harness straight
away. For any other task, one call with a fixed system prompt (router/table_system_prompt.txt) that hard-codes
the successful tasks, plus a short user message with the task.

  python3 router/table_router.py --write-prompt    regenerate table_system_prompt.txt from the frozen table
  python3 router/table_router.py --explain TASK    print the step-by-step decision for one task (no model call)

Tracing: every decision returns info["trace"], the list of steps that led to it. Set ROUTER_LOG=info (or debug) to
also print those steps to stderr as they happen; it is off by default so batch replays stay quiet.
"""
import argparse, hashlib, json, logging, os, statistics as st, sys, time, urllib.request

import profile_router as pr

log = logging.getLogger("router")
if os.environ.get("ROUTER_LOG") and not log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("%(asctime)s [router] %(levelname)s %(message)s", "%H:%M:%S"))
    log.addHandler(_h)
    log.setLevel(os.environ["ROUTER_LOG"].upper())
    log.propagate = False


class Trace(list):
    """Decision steps for one pick; each step is also logged at INFO."""

    def step(self, what, **data):
        self.append({"step": what, **data})
        log.info("%s%s", what, (" | " + json.dumps(data, default=str)) if data else "")

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_PROMPT_FILE = os.path.join(HERE, "table_system_prompt.txt")
DEFAULT = "mini-swe-agent"
QWEN_ORDER = ("mini-swe-agent", "terminus-2", "pi")

SYSTEM_TEMPLATE = """You pick the agent harness that will attempt a Terminal-Bench task. The model inside the harness is always GPT-5.6-Luna; only the harness changes. Choose one of: terminus-2, mini-swe-agent, pi.

The goal is the most passes for the least cost. Most of the time the harness makes no difference, so the default is the right answer unless the evidence below says otherwise.

WHAT WE MEASURED ({n_known} tasks, 3 runs per harness)
{base_rates}
- Perfect picking per task would reach about {oracle:.0f}%, so the choice matters on some tasks, but nothing has found them from the task description: routers that picked from harness features or topic similarity did no better than always using mini-swe-agent.

RULES - apply in order and stop at the first that decides
{rules}

In "reason", name the rule number you used and the evidence (task names or Qwen result).

KNOWN TASKS - our own results. T = terminus-2, M = mini-swe-agent, P = pi; passes out of runs.
CLEAR: the listed harness beat every other by at least 2 runs. Real evidence.
{clear}
LEAN: the listed harness beat the next by 1 run. Weak; 1 run in 3 is often luck.
{lean}
TIED: two or more harnesses tied for best; the cheapest of them is listed. No single best harness, though a harness well below the others (e.g. M 0/3 next to 3/3) is worth avoiding for this task.
{tie}
UNSOLVED: no harness passed; the cheapest harness that ran is listed so failures cost less.
{unsolved}

QWEN PASSES - Qwen3-Coder, a different model, one run per harness: which of our harnesses passed. Tasks where none passed are left out. On the tasks both models ran, a harness Qwen passed with was Luna's best harness on 16 of 21.
{qwen}

CANNOT INSTALL - harnesses that failed to install in this task's container in the Qwen run, so the agent never started. On qemu-startup the same harnesses then crashed on all 9 Luna attempts. Never choose them for these tasks.
{blocked}

WHAT EACH HARNESS DOES - descriptions only. They explain a CLEAR difference; on their own they have not predicted results.
{notes}

Reply with only JSON: {{"match": "<exact | similar: task names | none>", "reason": "<rule number and evidence, one sentence>", "harness": "<terminus-2|mini-swe-agent|pi>"}}"""

USER_TEMPLATE = """Task name: {name}
Task:
\"\"\"
{task}
\"\"\""""


def load_table():
    t = json.load(open(os.path.join(HERE, "success_table.json")))
    digest = hashlib.sha256(json.dumps([t["table_a"], t["table_b"]], sort_keys=True).encode()).hexdigest()[:16]
    if not t.get("frozen") or digest != t.get("table_sha256"):
        raise RuntimeError("success_table.json is not frozen or was edited after freezing")
    return t, digest


EXACT_RULE = "Task name listed in KNOWN TASKS: answer its listed harness, whatever group it is in."
RULES = [
    "Task listed in CANNOT INSTALL: remove those harnesses from every later rule. This rule never decides by itself.",
    "Task listed in QWEN PASSES: if mini-swe-agent is among its harnesses, answer mini-swe-agent; otherwise answer the "
    "first harness listed.",
    "A CLEAR known task, or two or more LEAN known tasks that agree, do the same kind of work as this one: answer "
    "their harness. Same kind of work means the thing that separates harnesses - a live interactive program or "
    "terminal, commands that run longer than 30 seconds (big builds, training), reading images, or many careful file "
    "edits - not the same topic or language. Two git tasks or two Python tasks are not similar for this purpose. "
    "TIED and UNSOLVED tasks do not count here.",
    "Otherwise answer mini-swe-agent. Do not pick terminus-2 because a task looks hard: it costs about {t2x:.1f}x as "
    "much in total and does not pass more.",
]
SHORT = 120


def strength(r):
    """clear / lean / tie / unsolved, from the gap between the best and second-best harness on a Table A row."""
    rates = sorted((s["passes"] / s["runs"] for s in r["results"].values()), reverse=True)
    if rates[0] == 0:
        return "unsolved"
    if len(rates) > 1 and rates[0] == rates[1]:
        return "tie"
    return "clear" if rates[0] - (rates[1] if len(rates) > 1 else 0) > 0.5 else "lean"


def build_system_prompt(t, profiles, drop=(), exact=True):
    """drop: Table A tasks to leave out (the held-out fold); exact=False removes the exact-match rule."""
    rows = [r for r in t["table_a"] if r["task"] not in drop]
    short = {"terminus-2": "T", "mini-swe-agent": "M", "pi": "P"}
    groups = {"clear": [], "lean": [], "tie": [], "unsolved": []}
    for r in rows:
        scores = " ".join(f"{short[h]} {r['results'][h]['passes']}/{r['results'][h]['runs']}" if h in r["results"]
                          else f"{short[h]} never ran" for h in pr.HARNESSES)
        about = r["about"] if len(r["about"]) <= SHORT else r["about"][:SHORT].rsplit(" ", 1)[0] + "..."
        groups[strength(r)].append(f"- {r['task']} -> {r['best']} ({scores}): {about}")

    rate = {h: st.mean(r["results"][h]["passes"] / r["results"][h]["runs"] if h in r["results"] else 0 for r in rows)
            for h in pr.HARNESSES}
    spend = {h: sum(r["results"][h]["avg_cost"] for r in rows if h in r["results"]) for h in pr.HARNESSES}
    oracle = 100 * st.mean(max(s["passes"] / s["runs"] for s in r["results"].values()) for r in rows)
    base = "\n".join(f"- {h}: {100 * rate[h]:.0f}% passed, {spend[h] / spend[DEFAULT]:.1f}x mini-swe-agent's total "
                     f"cost" + (" (the default)" if h == DEFAULT else "") for h in pr.HARNESSES)

    rules = ([EXACT_RULE] if exact else []) + [r.format(t2x=spend["terminus-2"] / spend[DEFAULT]) for r in RULES]
    qwen = []
    for r in t["table_b"]:
        passed = [h for h in QWEN_ORDER if r["results"].get(h) == "PASS"]
        if passed:
            qwen.append(f"- {r['task']}: {', '.join(passed)}")
    try:
        import difficulty
        blocked = [f"- {k}: {', '.join(h for h in v['qwen_setup_failed'] if h in pr.HARNESSES)}"
                   for k, v in sorted(difficulty.load()["tasks"].items())
                   if set(v.get("qwen_setup_failed") or ()) & set(pr.HARNESSES)]
    except FileNotFoundError:
        blocked = []
    none = "- (none)"
    return SYSTEM_TEMPLATE.format(
        n_known=len(rows), base_rates=base, oracle=oracle,
        rules="\n".join(f"{i}. {r}" for i, r in enumerate(rules, 1)),
        clear="\n".join(groups["clear"]) or none, lean="\n".join(groups["lean"]) or none,
        tie="\n".join(groups["tie"]) or none, unsolved="\n".join(groups["unsolved"]) or none,
        qwen="\n".join(qwen) or none, blocked="\n".join(blocked) or none,
        notes="\n".join(f"- {h}: {profiles[h]['choose_when']}" for h in pr.HARNESSES))


def write_system_prompt():
    t, digest = load_table()
    profiles, _ = pr.load_profiles()
    text = build_system_prompt(t, profiles)
    with open(SYSTEM_PROMPT_FILE, "w") as f:
        f.write(f"# table_sha256: {digest}\n{text}\n")
    return digest, text


def load_system_prompt(digest):
    with open(SYSTEM_PROMPT_FILE) as f:
        header, text = f.read().split("\n", 1)
    if header.strip() != f"# table_sha256: {digest}":
        raise RuntimeError("table_system_prompt.txt is out of date; run: python3 router/table_router.py --write-prompt")
    return text.strip()


def setup_failures(name):
    """Harnesses that could not even install in this task's container in the Qwen run (router/difficulty_table.json).
    On qemu-startup the same harnesses then crashed on all 9 of Luna's attempts, so this transfers across models."""
    try:
        import difficulty
        return set((difficulty.gauge(name) or {}).get("qwen_setup_failed") or ())
    except FileNotFoundError:
        return set()


def lookup(name, use_qwen=True):
    """Hard-coded pick, no model call.

    1. Task in Table A (every task Luna has run): its best harness. With the table built by
       build_success_table.py --include-test this covers all 45 Phase 1 tasks, and the pick is the stable
       oracle by construction: 70.4% pass on those tasks against 54.8% for always mini-swe-agent.
    2. Otherwise, leave out any harness that could not install for this task in the Qwen run, then take the
       first remaining harness Qwen passed with (mini-swe-agent, terminus-2, pi order).
    3. Otherwise the default harness if it can install, else the first one that can.

    Step 2 is on by decision (7 Oct), not on proof. When Qwen passes at all its harness is Luna's best one 76% of
    the time against 33% by chance, and on the 45 run tasks the rule gained 2.2 points, CI [-2.2, +7.4], at a lower
    cost per pass (study/qwen_vs_luna.py). Over the 44 unrun tasks it changes 2 picks and the setup check 1.
    use_qwen=False keeps only the setup check.
    """
    tr = Trace()
    t, digest = load_table()
    tr.step("lookup start", task=name, use_qwen=use_qwen, table_sha256=digest)
    best = {r["task"]: r for r in t["table_a"]}
    qwen = {r["task"]: r["results"] for r in t["table_b"]}
    if name in best:
        row = best[name]
        h, match, reason = row["best"], "luna", "Table A best harness (Luna)"
        tr.step("rule 1: in Table A, use Luna's best harness", harness=h, evidence=strength(row),
                results={k: f"{v['passes']}/{v['runs']} passed, ${v.get('avg_cost')}/run"
                         for k, v in row["results"].items()},
                why=row.get("note") or "highest pass rate")
    else:
        tr.step("rule 1: not in Table A (Luna has not run this task)")
        blocked = setup_failures(name)
        usable = [x for x in QWEN_ORDER if x not in blocked] or list(QWEN_ORDER)
        tr.step("rule 2: setup check", could_not_install=sorted(blocked & set(QWEN_ORDER)), usable=usable)
        q = qwen.get(name)
        passed = [x for x in usable if (q or {}).get(x) == "PASS"]
        tr.step("rule 3: Qwen results", in_qwen_workbook=q is not None, qwen=q or {}, passed_and_usable=passed,
                enabled=use_qwen)
        skip = f"; skipped {', '.join(sorted(blocked & set(QWEN_ORDER)))} (could not install in the Qwen run)" \
            if blocked & set(QWEN_ORDER) else ""
        if use_qwen and passed:
            h, match, reason = passed[0], "qwen", "not in Table A; harness that passed in the Qwen run" + skip
            tr.step("rule 3 decides: first Qwen pass in order " + " > ".join(QWEN_ORDER), harness=h)
        elif DEFAULT in usable:
            h, match, reason = DEFAULT, "none", "not in Table A; default harness" + skip
            tr.step("rule 4 decides: default harness", harness=h)
        else:
            h, match, reason = usable[0], "none", "not in Table A; first harness that can install" + skip
            tr.step("rule 4 decides: default cannot install, first usable harness", harness=h)
    tr.step("decision", harness=h, match=match)
    return h, {"underlying_model": None, "table_sha256": digest, "match": match, "reason": reason,
               "seconds": 0.0, "tokens": {"in": 0, "out": 0}, "cost": 0.0, "trace": tr}


def call(system, user, key, model):
    body = json.dumps({"model": model, "temperature": 0, "max_tokens": pr.MAX_TOKENS, "usage": {"include": True},
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", body,
                                 {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception as e:
            err = e
            log.warning("router model call failed (attempt %d of 3): %s: %s", attempt + 1, type(e).__name__, e)
            time.sleep(2 * (attempt + 1))
    log.error("router model call gave up after 3 attempts")
    raise err


def pick(name, text, router="luna", key=None, exact=True, drop=()):
    """Returns (harness or None, info).

    exact=True is the deployment path: a task listed in Table A is answered from the table with no model call, and
    the frozen system prompt is used for everything else.
    exact=False is the evaluation path: the exact-match rule and the task's own row are removed, so the pick is a
    real routing decision by analogy. Pass drop = the rest of the held-out fold as well.

    drop only applies when exact=False; asking for both is a contradiction and is refused rather than silently
    downgraded, because the two produce very different numbers.
    """
    if drop and exact:
        raise ValueError("drop is an evaluation-only argument; pass exact=False with it")
    tr = Trace()
    t, digest = load_table()
    tr.step("pick start", task=name, router=router, model=pr.ROUTER_MODELS[router],
            mode="deployment" if exact else "evaluation (analogy only)", held_out=len(drop))
    best = {r["task"]: r["best"] for r in t["table_a"]}
    if exact:
        if name in best:
            tr.step("in Table A: answered from the table, no model call", harness=best[name])
            return best[name], {"underlying_model": None, "table_sha256": digest, "match": "exact",
                                "reason": "known task (hard-coded cache)", "seconds": 0.0,
                                "tokens": {"in": 0, "out": 0}, "cost": 0.0, "trace": tr}
        system = load_system_prompt(digest)
    else:
        profiles, _ = pr.load_profiles()
        system = build_system_prompt(t, profiles, drop=set(drop) | {name}, exact=False)
    prompt_sha = hashlib.sha256(system.encode()).hexdigest()[:16]
    tr.step("calling router model", system_prompt_sha256=prompt_sha, system_chars=len(system), task_chars=len(text))
    log.debug("system prompt:\n%s", system)
    key = key or os.environ["OPENROUTER_API_KEY"]
    start = time.time()
    r = call(system, USER_TEMPLATE.format(name=name, task=text), key, pr.ROUTER_MODELS[router])
    txt = r["choices"][0]["message"]["content"] or ""
    log.debug("raw reply: %s", txt)
    d = pr.parse_json(txt)
    h = d.get("harness")
    u = r.get("usage") or {}
    info = {"underlying_model": r.get("model"), "table_sha256": digest, "system_prompt_sha256": prompt_sha,
            "match": d.get("match"), "reason": d.get("reason"), "raw": txt[:500],
            "seconds": round(time.time() - start, 2),
            "tokens": {"in": u.get("prompt_tokens"), "out": u.get("completion_tokens")}, "cost": u.get("cost") or 0.0,
            "trace": tr}
    tr.step("router model replied", harness=h, match=d.get("match"), reason=d.get("reason"),
            seconds=info["seconds"], tokens=info["tokens"], cost=info["cost"], underlying_model=r.get("model"))
    if h not in pr.HARNESSES:
        log.warning("router reply has no valid harness (%r); raw reply: %s", h, txt[:300])
        tr.step("invalid reply: no harness returned", raw=txt[:300])
        h = None
    tr.step("decision", harness=h)
    return h, info


JEV_DECIDE_MODEL = "~typesafe/jev-latest"


def decide(name, text, key=None):
    """Like pick(), but asks Jev itself through OpenRouter's decisions endpoint (one choice question) instead of a
    chat model. Jev returns a probability per harness, not text, so no other model answers. The state is the same
    frozen system prompt and task message pick() sends; the per-option criteria are the harness descriptions that
    prompt already contains."""
    tr = Trace()
    t, digest = load_table()
    tr.step("decide start", task=name, model=JEV_DECIDE_MODEL)
    best = {r["task"]: r["best"] for r in t["table_a"]}
    if name in best:
        tr.step("in Table A: answered from the table, no model call", harness=best[name])
        return best[name], {"underlying_model": None, "table_sha256": digest, "match": "exact",
                            "reason": "known task (hard-coded cache)", "seconds": 0.0,
                            "tokens": {"in": 0, "out": 0}, "cost": 0.0, "trace": tr}
    system = load_system_prompt(digest)
    state = system + "\n\n" + USER_TEMPLATE.format(name=name, task=text)
    profiles, _ = pr.load_profiles()
    body = {"model": JEV_DECIDE_MODEL, "state": state,
            "questions": {"harness": {"type": "choice",
                                      "criteria": {h: profiles[h]["choose_when"] for h in pr.HARNESSES},
                                      "instructions": "Answer as the instructions in the state say."}}}
    tr.step("calling Jev decisions endpoint", system_prompt_sha256=hashlib.sha256(system.encode()).hexdigest()[:16],
            state_chars=len(state))
    req = urllib.request.Request("https://openrouter.ai/api/alpha/decisions", json.dumps(body).encode(),
                                 {"Authorization": f"Bearer {key or os.environ['OPENROUTER_API_KEY']}",
                                  "Content-Type": "application/json"})
    start = time.time()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.load(r)
            break
        except Exception as e:
            log.warning("Jev decisions call failed (attempt %d of 3): %s: %s", attempt + 1, type(e).__name__, e)
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    a = (d.get("answers") or {}).get("harness") or {}
    u = d.get("usage") or {}
    h = a.get("choice")
    info = {"underlying_model": d.get("model"), "provider": d.get("provider"), "table_sha256": digest,
            "match": "none", "reason": f"Jev choice; probabilities {a.get('probabilities')}",
            "probabilities": a.get("probabilities"), "confidence": a.get("confidence"),
            "seconds": round(time.time() - start, 2),
            "tokens": {"in": u.get("input_tokens"), "out": u.get("output_tokens")}, "cost": u.get("cost") or 0.0,
            "trace": tr}
    tr.step("Jev replied", harness=h, probabilities=a.get("probabilities"), confidence=a.get("confidence"),
            model=d.get("model"), provider=d.get("provider"), seconds=info["seconds"], tokens=info["tokens"],
            cost=info["cost"])
    if h not in pr.HARNESSES:
        log.warning("Jev reply has no valid harness: %s", json.dumps(d)[:300])
        h = None
    tr.step("decision", harness=h)
    return h, info


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-prompt", action="store_true")
    ap.add_argument("--explain", metavar="TASK", help="print the lookup decision for TASK step by step")
    a = ap.parse_args()
    if a.write_prompt:
        digest, text = write_system_prompt()
        print(f"wrote {os.path.relpath(SYSTEM_PROMPT_FILE)} for table {digest}: {len(text)} chars (~{len(text) // 4} tokens)")
    if a.explain:
        h, info = lookup(a.explain)
        for i, s in enumerate(info["trace"], 1):
            data = {k: v for k, v in s.items() if k != "step"}
            print(f"{i}. {s['step']}" + (f"\n     {json.dumps(data, default=str)}" if data else ""))
        print(f"=> {h}  ({info['reason']})")
