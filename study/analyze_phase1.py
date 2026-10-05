"""Analyse Phase 1 of STUDY_PLAN.md: every task x harness x repeat, model fixed to Luna.

Reads only jobs/p1-* runs. Scores single harnesses, random choice, perfect picking (oracle on repeat means) and the
routers in router/picks_profiles.json, on pass rate and cost per pass, with paired bootstrap confidence intervals
against the best single harness of the development set.

The test set is sealed: scoring it needs --unseal, which is refused unless the harness profiles are frozen, and is
recorded in study/test_unseal_log.jsonl so every look at the test set is on record.

usage: python3 study/analyze_phase1.py [--split dev|test] [--unseal] [--jobs-glob 'jobs/p1-*']
"""
import argparse, collections, datetime, glob, hashlib, json, os, random, statistics as st, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HARNESSES = ["terminus-2", "mini-swe-agent", "pi"]
MODEL = "openai/gpt-5.6-luna"
PASS_GAIN = 5.0          # points of pass rate (STUDY_PLAN.md section 2)
COST_CUT = 0.30          # fraction lower cost per pass
COST_PASS_TOLERANCE = 3.0
BOOT = 10000


def load_runs(jobs_glob):
    cells = collections.defaultdict(lambda: collections.defaultdict(list))
    failures = collections.Counter()
    for f in glob.glob(f"{ROOT}/{jobs_glob}/*__*/result.json"):
        r = json.load(open(f))
        a = r.get("agent_info") or {}
        if (a.get("model_info") or {}).get("name") != MODEL or a.get("name") not in HARNESSES:
            continue
        rew = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        if rew is None:
            failures[(r.get("exception_info") or {}).get("exception_type") or "no reward"] += 1
            continue
        task = r["trial_name"].rsplit("__", 1)[0]
        cells[task][a["name"]].append((float(rew), (r.get("agent_result") or {}).get("cost_usd") or 0.0))
    return cells, failures


def means(cells, task, h):
    xs = cells[task][h]
    return st.mean(x[0] for x in xs), st.mean(x[1] for x in xs)


def load_picks():
    p = os.path.join(ROOT, "router", "picks_profiles.json")
    if not os.path.exists(p):
        return {}
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in json.load(open(p)):
        by[r["router"]][r["task"]].append((r["harness"], r.get("cost") or 0.0))
    return by


def score(tasks, choose, cells):
    """choose(task) -> list of (harness, routing_cost) alternatives, averaged. Returns per-task pass and cost."""
    per = {}
    for t in tasks:
        alts = choose(t)
        p = st.mean(means(cells, t, h)[0] if h else 0.0 for h, _ in alts)
        c = st.mean((means(cells, t, h)[1] if h else 0.0) + rc for h, rc in alts)
        per[t] = (p, c)
    return per


def summary(per):
    passes = sum(p for p, _ in per.values())
    cost = sum(c for _, c in per.values())
    return {"pass_rate": 100 * passes / len(per), "passes": passes, "cost": cost,
            "cost_per_pass": cost / passes if passes else float("inf")}


def boot_ci(diffs, seed=0):
    rng = random.Random(seed)
    n = len(diffs)
    ms = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(BOOT))
    return ms[int(0.025 * BOOT)], ms[int(0.975 * BOOT)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "test"])
    ap.add_argument("--unseal", action="store_true", help="required to score the test set")
    ap.add_argument("--jobs-glob", default="jobs/p1-*", help="which job folders to read (default: Phase 1 only)")
    a = ap.parse_args()
    split = json.load(open(f"{ROOT}/study/phase1_tasks.json"))

    if a.split == "test":
        prof = json.load(open(f"{ROOT}/router/harness_profiles.json"))
        if not a.unseal:
            sys.exit("the test set is sealed; rerun with --unseal once all routers are frozen")
        if not prof.get("frozen"):
            sys.exit("harness profiles are not frozen")
        picks_file = f"{ROOT}/router/picks_profiles.json"
        rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
               "profiles_sha256": prof.get("profiles_sha256"),
               "picks_sha256": hashlib.sha256(open(picks_file, "rb").read()).hexdigest()[:16] if os.path.exists(picks_file) else None}
        open(f"{ROOT}/study/test_unseal_log.jsonl", "a").write(json.dumps(rec) + "\n")
        print(f"TEST SET UNSEALED (logged): {rec}\n")

    cells, failures = load_runs(a.jobs_glob)
    tasks_all = split[a.split]
    tasks = [t for t in tasks_all if all(cells[t][h] for h in HARNESSES)]
    reps = {t: {h: len(cells[t][h]) for h in HARNESSES} for t in tasks_all}
    full = sum(all(reps[t][h] >= split["reps"] for h in HARNESSES) for t in tasks_all)
    print(f"{a.split}: {len(tasks)}/{len(tasks_all)} tasks have all 3 harnesses; {full} have all {split['reps']} repeats")
    print(f"runs without a reward (not counted): {dict(failures) or 0}")
    if not tasks:
        return

    print(f"\n{'task':32} " + " ".join(f"{h:>18}" for h in HARNESSES))
    for t in tasks:
        row = []
        for h in HARNESSES:
            p, c = means(cells, t, h)
            row.append(f"{p:4.2f} n={len(cells[t][h])} ${c:5.3f}")
        print(f"{t:32} " + " ".join(f"{x:>18}" for x in row))

    multi = [(t, h) for t in tasks for h in HARNESSES if len(cells[t][h]) > 1]
    agree = sum(len({x[0] for x in cells[t][h]}) == 1 for t, h in multi)
    print(f"\nrepeat agreement: {agree}/{len(multi)} task x harness cells give the same result on every repeat")

    strategies = {f"always {h}": (lambda t, h=h: [(h, 0.0)]) for h in HARNESSES}
    strategies["random"] = lambda t: [(h, 0.0) for h in HARNESSES]
    strategies["perfect picking"] = lambda t: [(max(HARNESSES, key=lambda h: (means(cells, t, h)[0], -means(cells, t, h)[1])), 0.0)]
    picks = load_picks()
    for rt, by_task in picks.items():
        if all(t in by_task for t in tasks):
            strategies[f"router: {rt}"] = lambda t, b=by_task: b[t]

    # best single harness is chosen on the development set, then held fixed for the test set
    dev_tasks = [t for t in split["dev"] if all(cells[t][h] for h in HARNESSES)]
    best = max(HARNESSES, key=lambda h: summary(score(dev_tasks, lambda t: [(h, 0.0)], cells))["pass_rate"]) if dev_tasks else HARNESSES[1]
    base = score(tasks, lambda t: [(best, 0.0)], cells)
    bs = summary(base)

    print(f"\nbaseline = best single harness on the development set: {best}")
    print(f"{'strategy':28} {'pass %':>7} {'diff vs base (95% CI)':>26} {'cost':>8} {'$/pass':>8} {'cost/pass vs base':>18}")
    results = {}
    for name, choose in strategies.items():
        per = score(tasks, choose, cells)
        s = summary(per)
        diffs = [100 * (per[t][0] - base[t][0]) for t in tasks]
        lo, hi = boot_ci(diffs)
        cpp = (s["cost_per_pass"] / bs["cost_per_pass"] - 1) if bs["passes"] else float("nan")
        meets_pass = st.mean(diffs) >= PASS_GAIN and lo > 0
        meets_cost = cpp <= -COST_CUT and s["pass_rate"] >= bs["pass_rate"] - COST_PASS_TOLERANCE
        flag = " PASS-CRITERION" if meets_pass else (" COST-CRITERION" if meets_cost else "")
        print(f"{name:28} {s['pass_rate']:7.1f} {st.mean(diffs):+8.1f} [{lo:+6.1f}, {hi:+6.1f}]   {s['cost']:8.3f} {s['cost_per_pass']:8.3f} {100 * cpp:+17.0f}%{flag}")
        results[name] = {**s, "diff_mean": st.mean(diffs), "ci": [lo, hi], "cost_per_pass_change": cpp,
                         "meets_pass_criterion": meets_pass, "meets_cost_criterion": meets_cost}

    if a.split == "dev":
        gap = results["perfect picking"]["pass_rate"] - bs["pass_rate"]
        verdict = "GO" if gap >= PASS_GAIN else "NO-GO for the pass-rate criterion (focus on cost)"
        print(f"\ngo/no-go: perfect picking is {gap:+.1f} points over {best} -> {verdict}")

    if a.jobs_glob != "jobs/p1-*":
        return
    out = f"{ROOT}/study/phase1_results_{a.split}.json"
    json.dump({"split": a.split, "tasks": tasks, "baseline": best, "results": results,
               "failures": dict(failures)}, open(out, "w"), indent=1)
    print(f"\nwrote {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
