"""Table router: picks a harness from the frozen success table (router/success_table.json).

Fast path, no model call: a task listed in Table A (Luna, dev) gets its best harness straight away.
For any other task, one call with a fixed system prompt (router/table_system_prompt.txt) that hard-codes the
successful tasks, plus a short user message with the task.

  python3 router/table_router.py --write-prompt    regenerate table_system_prompt.txt from the frozen table
"""
import argparse, hashlib, json, os, time, urllib.request

import profile_router as pr

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_PROMPT_FILE = os.path.join(HERE, "table_system_prompt.txt")
DEFAULT = "mini-swe-agent"
QWEN_ORDER = ("mini-swe-agent", "terminus-2", "pi")

SYSTEM_TEMPLATE = """You choose which agent harness should attempt a terminal task. GPT-5.6-Luna runs inside every harness; only the harness differs. Harnesses: terminus-2, mini-swe-agent, pi.

Rules, in order:
{rules}

Harness notes:
{notes}

KNOWN TASKS (GPT-5.6-Luna, best of 3 harnesses x 3 runs; "unsolved" = no harness passed):
{known}

QWEN PASSES (Qwen3-Coder, which of our harnesses passed; tasks where none passed are omitted):
{qwen}

Reply with only JSON: {{"match": "<exact | similar: task names | none>", "reason": "<one sentence>", "harness": "<terminus-2|mini-swe-agent|pi>"}}"""

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


RULES = [
    "If the task name is in KNOWN TASKS, answer with its harness.",
    "Otherwise find KNOWN TASKS that involve similar work (tools, languages, interactivity, file types, long builds, images) and lean towards their harness.",
    "QWEN PASSES is a weak hint (different model, one run each): use it only to break ties.",
    "If nothing is clearly similar, answer mini-swe-agent (best overall pass rate, low cost).",
]


def build_system_prompt(t, profiles, drop=(), exact=True):
    """drop: Table A tasks to leave out (the held-out fold); exact=False removes the exact-match rule."""
    rules = RULES if exact else ["Find KNOWN TASKS" + RULES[1][len("Otherwise find KNOWN TASKS"):]] + RULES[2:]
    notes = "\n".join(f"- {h}: {profiles[h]['choose_when']}" for h in pr.HARNESSES)
    known = []
    for r in t["table_a"]:
        if r["task"] in drop:
            continue
        res = r["results"]
        score = f"{res[r['best']]['passes']}/3" if r["best"] in res and res[r["best"]]["passes"] else "unsolved"
        known.append(f"- {r['task']} -> {r['best']} ({score}): {r['about']}")
    qwen = []
    for r in t["table_b"]:
        passed = [h for h in QWEN_ORDER if r["results"].get(h) == "PASS"]
        if passed:
            qwen.append(f"- {r['task']}: {', '.join(passed)}")
    return SYSTEM_TEMPLATE.format(rules="\n".join(f"{i}. {r}" for i, r in enumerate(rules, 1)),
                                  notes=notes, known="\n".join(known), qwen="\n".join(qwen))


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


def lookup(name):
    """Hard-coded pick, no model call.

    1. Task in Table A (Luna, dev): its best harness.
    2. Task in Table B (Qwen): mini-swe-agent if Qwen passed with it, else the first of our harnesses Qwen passed with.
    3. Otherwise mini-swe-agent.
    """
    t, digest = load_table()
    best = {r["task"]: r["best"] for r in t["table_a"]}
    qwen = {r["task"]: r["results"] for r in t["table_b"]}
    if name in best:
        h, match, reason = best[name], "luna", "Table A best harness (Luna)"
    elif name in qwen and any(qwen[name].get(x) == "PASS" for x in QWEN_ORDER):
        h = next(x for x in QWEN_ORDER if qwen[name].get(x) == "PASS")
        match, reason = "qwen", "not in Table A; harness that passed in the Qwen run"
    else:
        h, match, reason = DEFAULT, "none", "no Luna or Qwen pass; default"
    return h, {"underlying_model": None, "table_sha256": digest, "match": match, "reason": reason,
               "seconds": 0.0, "tokens": {"in": 0, "out": 0}, "cost": 0.0}


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
            time.sleep(2 * (attempt + 1))
    raise err


def pick(name, text, router="jev", key=None, exact=True, drop=()):
    """Returns (harness or None, info). Known Table A tasks skip the model call.

    For evaluation use exact=False with drop = the held-out tasks, so the router is judged only on analogy.
    """
    t, digest = load_table()
    best = {r["task"]: r["best"] for r in t["table_a"]}
    if exact and name in best:
        return best[name], {"underlying_model": None, "table_sha256": digest, "match": "exact",
                            "reason": "known task (hard-coded cache)", "seconds": 0.0,
                            "tokens": {"in": 0, "out": 0}, "cost": 0.0}
    if exact and not drop:
        system = load_system_prompt(digest)
    else:
        profiles, _ = pr.load_profiles()
        system = build_system_prompt(t, profiles, drop=set(drop) | {name}, exact=False)
    key = key or os.environ["OPENROUTER_API_KEY"]
    start = time.time()
    r = call(system, USER_TEMPLATE.format(name=name, task=text), key, pr.ROUTER_MODELS[router])
    txt = r["choices"][0]["message"]["content"] or ""
    d = pr.parse_json(txt)
    h = d.get("harness")
    u = r.get("usage") or {}
    info = {"underlying_model": r.get("model"), "table_sha256": digest, "match": d.get("match"),
            "reason": d.get("reason"), "raw": txt[:500], "seconds": round(time.time() - start, 2),
            "tokens": {"in": u.get("prompt_tokens"), "out": u.get("completion_tokens")}, "cost": u.get("cost") or 0.0}
    return (h if h in pr.HARNESSES else None), info


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-prompt", action="store_true")
    if ap.parse_args().write_prompt:
        digest, text = write_system_prompt()
        print(f"wrote {os.path.relpath(SYSTEM_PROMPT_FILE)} for table {digest}: {len(text)} chars (~{len(text) // 4} tokens)")
