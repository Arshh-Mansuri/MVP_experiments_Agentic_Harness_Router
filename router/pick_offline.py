"""Make profile-based picks for every Phase 1 task without running Harbor.

Both routers see the same frozen profiles and task text; only the picking model differs:
  jev           typesafe/jev-router (the router under test)
  luna-profiles openai/gpt-5.6-luna (comparison, isolates the effect of the profiles from the effect of Jev)
  luna-cards    the existing Luna router: hand-written cards + rules (router2.V1_PROMPT), no profiles
  jev-table     Jev with the frozen success table (table_router.py): Luna dev results + Qwen 89 as a weak hint
  luna-table    Luna with the same success table
  lookup        hard-coded: Table A best harness for known tasks, mini-swe-agent otherwise (no model call)

usage: python router/pick_offline.py [--routers jev luna-profiles] [--reps 2] [--split dev|test|all]
writes router/picks_profiles.json (appends new picks; existing (router, task, rep) entries are kept)
"""
import argparse, json, os, sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import profile_router as pr

NAMES = {"jev": "jev", "luna-profiles": "luna", "luna-cards": "luna", "jev-table": "jev", "luna-table": "luna",
         "lookup": None}
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
    a = ap.parse_args()
    split = json.load(open(os.path.join(HERE, "..", "study", "phase1_tasks.json")))
    tasks = split["dev"] + split["test"] if a.split == "all" else split[a.split]
    key = os.environ["OPENROUTER_API_KEY"]

    rows = json.load(open(OUT)) if os.path.exists(OUT) else []
    have = {(r["router"], r["task"], r["rep"]) for r in rows if r.get("harness")}
    jobs = [(rt, t, rep) for rt in a.routers for t in tasks for rep in range(1, a.reps + 1) if (rt, t, rep) not in have]
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
                h, info = table_router.pick(t, pr.task_text(t), NAMES[rt], key)
            else:
                h, info = pr.pick(pr.task_text(t), NAMES[rt], key)
            return {**info, "router": rt, "task": t, "rep": rep, "harness": h}
        except Exception as e:
            return {"router": rt, "task": t, "rep": rep, "harness": None, "error": repr(e)[:300], "cost": 0.0}

    with ThreadPoolExecutor(6) as ex:
        new = list(ex.map(one, jobs))
    rows = [r for r in rows if (r["router"], r["task"], r["rep"]) not in {(n["router"], n["task"], n["rep"]) for n in new}] + new
    json.dump(rows, open(OUT, "w"), indent=1)

    for rt in a.routers:
        rs = [r for r in rows if r["router"] == rt]
        counts = {h: sum(r["harness"] == h for r in rs) for h in pr.HARNESSES}
        bad = sum(r["harness"] is None for r in rs)
        models = sorted({r.get("underlying_model") or "-" for r in rs})
        print(f"{rt:14} picks {counts} invalid {bad}  cost ${sum(r['cost'] for r in rs):.4f}  models {models}")


if __name__ == "__main__":
    main()
