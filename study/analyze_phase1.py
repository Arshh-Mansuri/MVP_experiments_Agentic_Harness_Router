"""Analyse Phase 1 of STUDY_PLAN.md: every task x harness x repeat, model fixed to Luna.

Reads only jobs/p1-* runs. Scores single harnesses, random choice, three oracles and the routers in
router/picks_profiles.json, on pass rate, cost per pass, tokens, wall-clock time and routing overhead, with paired
bootstrap confidence intervals against the best single harness of the development set.

Oracles (PROBLEM_DEFINITION.md):
  perfect picking         stable oracle: per task the best mean pass rate over repeats, ties to the cheaper harness
  oracle: cheapest-pass   per task the cheapest harness that passed at least once (proposal definition)
  oracle: single-run      cheapest harness that passed within one repeat, averaged over repeats (in-hindsight
                          ceiling a single-run baseline would report; the gap to the stable oracle is luck)

The test set is sealed: scoring it needs --unseal, which is refused unless the harness profiles are frozen, and is
recorded in study/test_unseal_log.jsonl so every look at the test set is on record.

usage: python3 study/analyze_phase1.py [--split dev|test] [--unseal] [--count-install-failures] [--jobs-glob 'jobs/p1-*']
"""
import argparse, collections, datetime, glob, hashlib, json, os, random, re, statistics as st, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HARNESSES = ["terminus-2", "mini-swe-agent", "pi"]
MODEL = "openai/gpt-5.6-luna"
PASS_GAIN = 5.0          # points of pass rate (STUDY_PLAN.md section 2)
COST_CUT = 0.30          # fraction lower cost per pass
COST_PASS_TOLERANCE = 3.0
BOOT = 10000
STABLE_ORACLE = "perfect picking"


def minutes(r):
    a, b = r.get("started_at"), r.get("finished_at")
    if not a or not b:
        return 0.0
    f = lambda s: datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return (f(b) - f(a)).total_seconds() / 60


def load_runs(jobs_glob):
    """cells[task][harness] = list of run dicts (scored runs only); broken[task][harness] = runs without a reward."""
    cells = collections.defaultdict(lambda: collections.defaultdict(list))
    broken = collections.defaultdict(lambda: collections.defaultdict(list))
    failures = collections.Counter()
    for f in glob.glob(f"{ROOT}/{jobs_glob}/*__*/result.json"):
        r = json.load(open(f))
        a = r.get("agent_info") or {}
        if (a.get("model_info") or {}).get("name") != MODEL or a.get("name") not in HARNESSES:
            continue
        ar = r.get("agent_result") or {}
        m = re.search(r"-r(\d+)(?:-retry\d+)?$", os.path.basename(os.path.dirname(os.path.dirname(f))))
        run = {"reward": None, "cost": ar.get("cost_usd") or 0.0,
               "tokens": (ar.get("n_input_tokens") or 0) + (ar.get("n_output_tokens") or 0),
               "minutes": minutes(r), "rep": int(m.group(1)) if m else 0,
               "error": (r.get("exception_info") or {}).get("exception_type")}
        task = r["trial_name"].rsplit("__", 1)[0]
        rew = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        if rew is None:
            failures[run["error"] or "no reward"] += 1
            broken[task][a["name"]].append(run)
            continue
        run["reward"] = float(rew)
        cells[task][a["name"]].append(run)
    return cells, broken, failures


def cell(cells, task, h):
    """Mean pass, cost, tokens and minutes of a task x harness cell (pass 0 if the harness never produced a result)."""
    xs = cells[task][h]
    if not xs:
        return {"pass": 0.0, "cost": 0.0, "tokens": 0.0, "minutes": 0.0}
    return {k: st.mean(x[src] for x in xs) for k, src in
            (("pass", "reward"), ("cost", "cost"), ("tokens", "tokens"), ("minutes", "minutes"))}


def means(cells, task, h):
    c = cell(cells, task, h)
    return c["pass"], c["cost"]


def load_picks():
    p = os.path.join(ROOT, "router", "picks_profiles.json")
    if not os.path.exists(p):
        return {}
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in json.load(open(p)):
        tok = r.get("tokens") or {}
        ntok = (tok.get("in") or 0) + (tok.get("out") or 0) if isinstance(tok, dict) else 0
        by[r["router"]][r["task"]].append((r["harness"], r.get("cost") or 0.0, ntok, r.get("seconds") or 0.0))
    return by


def stable_pick(cells, t):
    return max(HARNESSES, key=lambda h: (cell(cells, t, h)["pass"], -cell(cells, t, h)["cost"]))


def cheapest_pass_pick(cells, t):
    passed = [h for h in HARNESSES if any(x["reward"] > 0 for x in cells[t][h])]
    pool = passed or HARNESSES
    return min(pool, key=lambda h: cell(cells, t, h)["cost"])


def score(tasks, choose, cells):
    """choose(task) -> list of (harness, routing_cost, routing_tokens, routing_seconds) alternatives, averaged."""
    per = {}
    for t in tasks:
        alts = [a if len(a) == 4 else (a[0], a[1], 0, 0.0) for a in choose(t)]
        cs = [cell(cells, t, h) if h else {"pass": 0.0, "cost": 0.0, "tokens": 0.0, "minutes": 0.0} for h, *_ in alts]
        per[t] = {"pass": st.mean(c["pass"] for c in cs),
                  "run_cost": st.mean(c["cost"] for c in cs),
                  "route_cost": st.mean(a[1] for a in alts),
                  "tokens": st.mean(c["tokens"] for c in cs),
                  "route_tokens": st.mean(a[2] for a in alts),
                  "minutes": st.mean(c["minutes"] for c in cs) + st.mean(a[3] for a in alts) / 60,
                  "route_seconds": st.mean(a[3] for a in alts)}
        per[t]["cost"] = per[t]["run_cost"] + per[t]["route_cost"]
    return per


def score_single_run(tasks, cells):
    """Single-run oracle: per repeat, the cheapest harness that passed in that repeat (its own cost and time)."""
    per = {}
    for t in tasks:
        reps = sorted({x["rep"] for h in HARNESSES for x in cells[t][h]})
        rows = []
        for rep in reps:
            runs = {h: [x for x in cells[t][h] if x["rep"] == rep] for h in HARNESSES}
            runs = {h: v[0] for h, v in runs.items() if v}
            if not runs:
                continue
            passed = {h: x for h, x in runs.items() if x["reward"] > 0}
            pool = passed or runs
            h = min(pool, key=lambda k: pool[k]["cost"])
            rows.append(pool[h])
        per[t] = {"pass": st.mean(x["reward"] for x in rows), "run_cost": st.mean(x["cost"] for x in rows),
                  "route_cost": 0.0, "tokens": st.mean(x["tokens"] for x in rows), "route_tokens": 0,
                  "minutes": st.mean(x["minutes"] for x in rows), "route_seconds": 0.0}
        per[t]["cost"] = per[t]["run_cost"]
    return per


def summary(per):
    passes = sum(p["pass"] for p in per.values())
    cost = sum(p["cost"] for p in per.values())
    return {"pass_rate": 100 * passes / len(per), "passes": passes, "cost": cost,
            "cost_per_pass": cost / passes if passes else float("inf"),
            "tokens": sum(p["tokens"] for p in per.values()),
            "minutes": sum(p["minutes"] for p in per.values()),
            "routing_cost": sum(p["route_cost"] for p in per.values()),
            "routing_tokens": sum(p["route_tokens"] for p in per.values()),
            "routing_seconds": sum(p["route_seconds"] for p in per.values())}


def boot_ci(diffs, seed=0):
    rng = random.Random(seed)
    n = len(diffs)
    ms = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(BOOT))
    return ms[int(0.025 * BOOT)], ms[int(0.975 * BOOT)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "test"])
    ap.add_argument("--unseal", action="store_true", help="required to score the test set")
    ap.add_argument("--count-install-failures", action="store_true",
                    help="keep tasks where a harness never produced a result, scoring that harness as a fail")
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

    cells, broken, failures = load_runs(a.jobs_glob)
    tasks_all = split[a.split]
    if a.count_install_failures:
        tasks = [t for t in tasks_all if any(cells[t][h] for h in HARNESSES)]
    else:
        tasks = [t for t in tasks_all if all(cells[t][h] for h in HARNESSES)]
    reps = {t: {h: len(cells[t][h]) for h in HARNESSES} for t in tasks_all}
    full = sum(all(reps[t][h] >= split["reps"] for h in HARNESSES) for t in tasks_all)
    print(f"{a.split}: {len(tasks)}/{len(tasks_all)} tasks scored"
          f"{' (install failures counted as fails)' if a.count_install_failures else ' (tasks missing a harness dropped)'}; "
          f"{full} have all {split['reps']} repeats")
    print(f"runs without a reward (not counted): {dict(failures) or 0}")
    if not tasks:
        return

    print(f"\n{'task':32} " + " ".join(f"{h:>18}" for h in HARNESSES))
    for t in tasks:
        row = []
        for h in HARNESSES:
            c = cell(cells, t, h)
            row.append(f"{c['pass']:4.2f} n={len(cells[t][h])} ${c['cost']:5.3f}")
        print(f"{t:32} " + " ".join(f"{x:>18}" for x in row))

    multi = [(t, h) for t in tasks for h in HARNESSES if len(cells[t][h]) > 1]
    agree = sum(len({x["reward"] for x in cells[t][h]}) == 1 for t, h in multi)
    print(f"\nrepeat agreement: {agree}/{len(multi)} task x harness cells give the same result on every repeat")

    strategies = {f"always {h}": (lambda t, h=h: [(h, 0.0)]) for h in HARNESSES}
    strategies["random"] = lambda t: [(h, 0.0) for h in HARNESSES]
    strategies[STABLE_ORACLE] = lambda t: [(stable_pick(cells, t), 0.0)]
    strategies["oracle: cheapest-pass"] = lambda t: [(cheapest_pass_pick(cells, t), 0.0)]
    strategies["oracle: single-run"] = None
    picks = load_picks()
    for rt, by_task in picks.items():
        if all(t in by_task for t in tasks):
            # lookup is built from the dev results, so on dev it is perfect picking by construction
            label = ("cache: lookup (in-sample, not a router)" if a.split == "dev" else "cache: lookup") \
                if rt == "lookup" else f"router: {rt}"
            strategies[label] = lambda t, b=by_task: b[t]

    # best single harness is chosen on the development set, then held fixed for the test set
    dev_tasks = [t for t in split["dev"] if all(cells[t][h] for h in HARNESSES)]
    best = max(HARNESSES, key=lambda h: summary(score(dev_tasks, lambda t: [(h, 0.0)], cells))["pass_rate"]) if dev_tasks else HARNESSES[1]
    base = score(tasks, lambda t: [(best, 0.0)], cells)
    bs = summary(base)
    oracle_rate = summary(score(tasks, strategies[STABLE_ORACLE], cells))["pass_rate"]

    print(f"\nbaseline = best single harness on the development set: {best}")
    print("headroom recovered = (strategy - baseline) / (stable oracle - baseline)")
    print(f"{'strategy':40} {'pass %':>6} {'diff vs base (95% CI)':>24} {'headroom':>8} {'cost':>7} {'$/pass':>7} "
          f"{'cpp vs base':>11} {'Mtok':>6} {'hours':>6} {'route $':>8} {'route s':>8}")
    results = {}
    for name, choose in strategies.items():
        per = score_single_run(tasks, cells) if choose is None else score(tasks, choose, cells)
        s = summary(per)
        diffs = [100 * (per[t]["pass"] - base[t]["pass"]) for t in tasks]
        lo, hi = boot_ci(diffs)
        cpp = (s["cost_per_pass"] / bs["cost_per_pass"] - 1) if bs["passes"] else float("nan")
        gap = oracle_rate - bs["pass_rate"]
        headroom = (s["pass_rate"] - bs["pass_rate"]) / gap if gap > 0 else float("nan")
        routes = name.startswith("router:")  # criteria apply to routers only, not fixed harnesses/oracles/cache
        meets_pass = routes and st.mean(diffs) >= PASS_GAIN and lo > 0
        meets_cost = routes and cpp <= -COST_CUT and s["pass_rate"] >= bs["pass_rate"] - COST_PASS_TOLERANCE
        flag = " PASS-CRITERION" if meets_pass else (" COST-CRITERION" if meets_cost else "")
        print(f"{name:40} {s['pass_rate']:6.1f} {st.mean(diffs):+7.1f} [{lo:+6.1f}, {hi:+6.1f}] {100 * headroom:+7.0f}% "
              f"{s['cost']:7.3f} {s['cost_per_pass']:7.3f} {100 * cpp:+10.0f}% {s['tokens'] / 1e6:6.1f} "
              f"{s['minutes'] / 60:6.1f} {s['routing_cost']:8.3f} {s['routing_seconds']:8.0f}{flag}")
        results[name] = {**s, "diff_mean": st.mean(diffs), "ci": [lo, hi], "cost_per_pass_change": cpp,
                         "headroom_recovered": headroom,
                         "meets_pass_criterion": meets_pass, "meets_cost_criterion": meets_cost}

    if a.split == "dev":
        gap = results[STABLE_ORACLE]["pass_rate"] - bs["pass_rate"]
        verdict = "GO" if gap >= PASS_GAIN else "NO-GO for the pass-rate criterion (focus on cost)"
        print(f"\ngo/no-go: perfect picking is {gap:+.1f} points over {best} -> {verdict}")
        luck = results["oracle: single-run"]["pass_rate"] - results[STABLE_ORACLE]["pass_rate"]
        print(f"single-run oracle minus stable oracle: {luck:+.1f} points (the part of a single-run 'headroom' that is luck)")

    if a.jobs_glob != "jobs/p1-*":
        return
    suffix = "_with_install_failures" if a.count_install_failures else ""
    out = f"{ROOT}/study/phase1_results_{a.split}{suffix}.json"
    json.dump({"split": a.split, "tasks": tasks, "baseline": best, "results": results,
               "failures": dict(failures)}, open(out, "w"), indent=1)
    print(f"\nwrote {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
