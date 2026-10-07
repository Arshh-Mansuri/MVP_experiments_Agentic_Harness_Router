"""Make picks for every Phase 1 task without running Harbor.

  luna-profiles openai/gpt-5.6-luna with Luna's frozen harness profiles
  luna-cards    the existing Luna router: hand-written cards + rules (router2.V1_PROMPT), no profiles
  luna-table    Luna with the frozen success table (table_router.py): Luna dev results + Qwen 89 as a weak hint
  lookup        hard-coded: Table A best harness for known tasks, mini-swe-agent otherwise (no model call)
typesafe/jev-router is not used (it forwards to other models); picks_profiles.json still holds its old 'jev'/'jev-table' rows.

On a development task the table router answers straight from the table, so those picks are cache hits rather than
routing decisions. --analogy-only removes the task's own row and the exact-match rule, which is the only form worth
scoring as a router; such picks are stored under a separate name (luna-table-analogy) so the two can never be mixed.

usage: python router/pick_offline.py [--routers luna-profiles lookup] [--reps 2] [--split dev|test|all] [--analogy-only]
writes router/picks_profiles.json (appends new picks; existing (router, task, rep) entries are kept)
"""
import argparse, json, os, sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import profile_router as pr

NAMES = {"luna-profiles": "luna", "luna-cards": "luna", "luna-table": "luna", "lookup": None}
OUT = os.path.join(HERE, "picks_profiles.json")


def pick_cards(text, key):
    from router2 import CARDS, V1_PROMPT
    descs = "\n".join(f"- {k}: {v}" for k, v in CARDS.items())
    r = pr.call(V1_PROMPT.format(descs=descs, task=text) + " Reply with only the JSON.", key, pr.ROUTER_MODELS["luna"])
    d = pr.parse_json(r["choices"][0]["message"]["content"])
    u = r.get("usage") or {}
    h = d.get("harness")
    return (h if h in pr.HARNESSES else None), {"underlying_model": r.get("model"), "reason": None,
                                               "tokens": {"in": u.get("prompt_tokens"), "out": u.get("completion_tokens")},
                                               "cost": u.get("cost") or 0.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--routers", nargs="+", default=list(NAMES), choices=list(NAMES))
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--split", default="all", choices=["dev", "test", "all"])
    ap.add_argument("--analogy-only", action="store_true",
                    help="table routers: drop the task's own row and the exact-match rule, so the pick is a real "
                         "routing decision; saved under '<router>-analogy'")
    a = ap.parse_args()
    split = json.load(open(os.path.join(HERE, "..", "study", "phase1_tasks.json")))
    tasks = split["dev"] + split["test"] if a.split == "all" else split[a.split]
    # lookup is hard-coded and makes no request, so it must stay runnable without a key
    key = os.environ.get("OPENROUTER_API_KEY")
    paid = [rt for rt in a.routers if rt != "lookup"]
    if paid and not key:
        sys.exit(f"OPENROUTER_API_KEY is not set; it is needed for {', '.join(paid)} (only lookup runs without it)")

    name_of = lambda rt: f"{rt}-analogy" if a.analogy_only and rt.endswith("-table") else rt
    rows = json.load(open(OUT)) if os.path.exists(OUT) else []
    have = {(r["router"], r["task"], r["rep"]) for r in rows if r.get("harness")}
    jobs = [(rt, t, rep) for rt in a.routers for t in tasks for rep in range(1, a.reps + 1)
            if (name_of(rt), t, rep) not in have]
    print(f"{len(jobs)} picks to make ({len(have)} already done)", flush=True)

    def one(job):
        rt, t, rep = job
        try:
            if rt == "luna-cards":
                h, info = pick_cards(pr.task_text(t), key)
            elif rt == "lookup":
                import table_router
                h, info = table_router.lookup(t)
            elif rt.endswith("-table"):
                import table_router
                h, info = table_router.pick(t, pr.task_text(t), NAMES[rt], key,
                                            exact=not a.analogy_only)
            else:
                h, info = pr.pick(pr.task_text(t), NAMES[rt], key)
            return {**info, "router": name_of(rt), "task": t, "rep": rep, "harness": h}
        except Exception as e:
            return {"router": name_of(rt), "task": t, "rep": rep, "harness": None, "error": repr(e)[:300], "cost": 0.0}

    with ThreadPoolExecutor(6) as ex:
        new = list(ex.map(one, jobs))
    rows = [r for r in rows if (r["router"], r["task"], r["rep"]) not in {(n["router"], n["task"], n["rep"]) for n in new}] + new
    json.dump(rows, open(OUT, "w"), indent=1)

    for rt in map(name_of, a.routers):
        rs = [r for r in rows if r["router"] == rt]
        counts = {h: sum(r["harness"] == h for r in rs) for h in pr.HARNESSES}
        bad = sum(r["harness"] is None for r in rs)
        models = sorted({r.get("underlying_model") or "-" for r in rs})
        print(f"{rt:14} picks {counts} invalid {bad}  cost ${sum(r['cost'] for r in rs):.4f}  models {models}")


if __name__ == "__main__":
    main()
