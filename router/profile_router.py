"""Profile-based harness router: a router model picks the harness from Luna's frozen harness profiles.

The prompt holds only the frozen profiles (router/harness_profiles.json, written from harness source code by
harness_research.py) and the task text. No hand-written rules, no default harness, no benchmark results.
Standard library only, so it runs without the router venv.
"""
import glob, hashlib, json, os, re, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESSES = ["terminus-2", "mini-swe-agent", "pi"]
# typesafe/jev-router is not used: it forwards each request to some other model (DeepSeek, GPT-6.1-Sol), so its
# answers were never Jev's. Jev itself is table_router.decide().
ROUTER_MODELS = {"luna": "openai/gpt-5.6-luna"}
MAX_TOKENS = 4000  # bounds the cost of one pick
TASK_DIRS = [os.path.expanduser("~/.cache/harbor/tasks/packages/terminal-bench/{task}/*/instruction.md"),
             os.path.expanduser("~/.cache/harbor/tasks/*/{task}/instruction.md")]

PROMPT = """You choose which agent harness should attempt a terminal task. The same language model will work inside whichever harness you choose; only the harness differs. Below are profiles of the three harnesses, written from their source code.

{profiles}

Task:
\"\"\"
{task}
\"\"\"

Think about what the task requires (interactive programs, long-running processes, shell state, file editing, images, output size, time limits) and which harness's mechanisms fit it best.

Reply with only JSON: {{"reason": "<one or two sentences>", "harness": "<terminus-2|mini-swe-agent|pi>"}}"""


def load_profiles():
    p = json.load(open(os.path.join(HERE, "harness_profiles.json")))
    digest = hashlib.sha256(json.dumps(p["profiles"], sort_keys=True).encode()).hexdigest()[:16]
    if not p.get("frozen") or digest != p.get("profiles_sha256"):
        raise RuntimeError("harness_profiles.json is not frozen or was edited after freezing")
    return p["profiles"], digest


def render(profiles):
    out = []
    for h in HARNESSES:
        out.append(f"### {h}")
        for k, v in profiles[h].items():
            label = k.replace("_", " ")
            out.append(f"- {label}: " + ("; ".join(v) if isinstance(v, list) else str(v)))
        out.append("")
    return "\n".join(out)


def task_text(task):
    for pat in TASK_DIRS:
        p = glob.glob(pat.format(task=task))
        if p:
            return open(p[0]).read().strip()[:3000]
    raise FileNotFoundError(f"instruction.md not found for {task}")


def call(prompt, key, model, system=None):
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body = json.dumps({"model": model, "messages": messages, "temperature": 0,
                       "max_tokens": MAX_TOKENS, "usage": {"include": True}}).encode()
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


def parse_json(txt):
    m = re.search(r"\{.*\}", txt or "", re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except Exception:
        return {}


# GPT-5.6-Luna list prices, $ per million tokens. New prompt tokens are priced as cache writes: on Phase 1 this
# reproduces the cost OpenRouter reported for terminus-2 and mini-swe-agent to within about 0.4% (median). The
# >272k-token prompt tier is ignored.
LUNA_PRICE = {"new_input": 0.25, "cached": 0.02, "output": 1.20}


def list_cost(n_in, n_cached, n_out):
    p = LUNA_PRICE
    return round(((n_in - n_cached) * p["new_input"] + n_cached * p["cached"] + n_out * p["output"]) / 1e6, 8)


def agent_cost(harness, n_in, n_cached, n_out, reported):
    """Agent cost at list price. With BYOK, OpenRouter (and so litellm in terminus-2 and mini-swe-agent) reports
    only its fee; pi prices tokens itself, so its own figure stands."""
    if harness == "pi" or n_in is None or n_out is None:
        return reported
    return list_cost(n_in, n_cached or 0, n_out)


def usage_cost(u):
    """Total cost of one call. With BYOK, OpenRouter's 'cost' is only its fee; the provider's charge is separate."""
    up = (u.get("cost_details") or {}).get("upstream_inference_cost") if u.get("is_byok") else None
    return (u.get("cost") or 0.0) + (up or 0.0)


def pick(text, router="luna", key=None):
    """Returns (harness or None, info). info records the underlying model that answered, tokens and cost."""
    profiles, digest = load_profiles()
    key = key or os.environ["OPENROUTER_API_KEY"]
    t = time.time()
    r = call(PROMPT.format(profiles=render(profiles), task=text), key, ROUTER_MODELS[router])
    txt = r["choices"][0]["message"]["content"] or ""
    d = parse_json(txt)
    h = d.get("harness")
    u = r.get("usage") or {}
    info = {"router": router, "underlying_model": r.get("model"), "profiles_sha256": digest,
            "reason": d.get("reason"), "raw": txt[:500], "seconds": round(time.time() - t, 2),
            "tokens": {"in": u.get("prompt_tokens"), "out": u.get("completion_tokens")}, "cost": usage_cost(u),
            "byok": bool(u.get("is_byok"))}
    return (h if h in HARNESSES else None), info
