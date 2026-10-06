"""Offline fallback simulation (PROBLEM_DEFINITION.md step 5): retry on a different harness after an observable failure.

The trigger may only use what is visible while the run is happening, never the verifier reward:

  crash      the harness produced no result at all (RuntimeError, NonZeroAgentExitCodeError, AgentSetupTimeoutError,
             APIError, VerifierTimeoutError) -- 49 runs in Phase 1
  timeout    the agent hit its time limit (AgentTimeoutError) -- 18 runs, 17 of which went on to fail the tests
  slow       the run passed --slow-minutes without finishing (off by default; it needs a deployment time budget)

A crash scores as a fail without a fallback, which is what a deployment would see, so the no-fallback column here is
lower than analyze_phase1.py (which drops those runs). Each retry pays the full cost and wall-clock of the second run,
counted in the extra-cost and extra-time columns.

usage: python3 study/fallback_sim.py [--tasks dev|all] [--unseal] [--max-retries 1] [--slow-minutes 0]
"""
import argparse, collections, datetime, glob, json, os, re, statistics as st, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "study"))
import analyze_phase1 as an

HARNESSES = an.HARNESSES
CRASH = {"RuntimeError", "NonZeroAgentExitCodeError", "AgentSetupTimeoutError", "APIError", "VerifierTimeoutError"}
TIMEOUT = {"AgentTimeoutError"}


def load_all(jobs_glob="jobs/p1-*", crashes="count"):
    """runs[task][harness][repeat] = run dict, including runs that never produced a reward.

    crashes='count' keeps the first attempt of each repeat, so a crash is what a deployment would have seen and the
    fallback has to handle it. crashes='superseded' prefers the manual same-harness retry we actually ran, which
    matches analyze_phase1.py but hides the crash.

    Also returns later[task][harness][repeat] = the next attempt we ran on the same harness, which is the control for
    the fallback: most triggers are infrastructure crashes, and retrying the same harness fixes those too.
    """
    runs = collections.defaultdict(lambda: collections.defaultdict(dict))
    later = collections.defaultdict(lambda: collections.defaultdict(dict))
    for f in glob.glob(f"{ROOT}/{jobs_glob}/*__*/result.json"):
        r = json.load(open(f))
        a = r.get("agent_info") or {}
        if (a.get("model_info") or {}).get("name") != an.MODEL or a.get("name") not in HARNESSES:
            continue
        ar = r.get("agent_result") or {}
        job = os.path.basename(os.path.dirname(os.path.dirname(f)))
        m = re.search(r"-r(\d+)(?:-retry\d+)?$", job)
        attempt = int(re.search(r"-retry(\d+)$", job).group(1)) if "-retry" in job else 0
        rew = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        run = {"reward": None if rew is None else float(rew), "cost": ar.get("cost_usd") or 0.0,
               "minutes": an.minutes(r), "error": (r.get("exception_info") or {}).get("exception_type"),
               "attempt": attempt}
        task, rep = r["trial_name"].rsplit("__", 1)[0], int(m.group(1)) if m else 0
        prev = runs[task][a["name"]].get(rep)
        better = prev is None or (run["attempt"] < prev["attempt"] if crashes == "count"
                                  else prev["reward"] is None and run["reward"] is not None)
        if better:
            if prev is not None:
                later[task][a["name"]][rep] = prev
            runs[task][a["name"]][rep] = run
        elif rep not in later[task][a["name"]]:
            later[task][a["name"]][rep] = run
    return runs, later


def triggered(run, slow_minutes):
    if run["reward"] is None or run["error"] in CRASH:
        return "crash"
    if run["error"] in TIMEOUT:
        return "timeout"
    if slow_minutes and run["minutes"] > slow_minutes:
        return "slow"
    return None


def simulate(tasks, runs, later, first, order, max_retries, slow_minutes, same_harness=False):
    """first(task) -> primary harness; order(task, tried) -> next harness. same_harness retries the same harness
    instead, which is the control: it fixes crashes without any routing."""
    per, fires = {}, collections.Counter()
    get = lambda t, h, rep: runs[t][h].get(rep) or next(iter(runs[t][h].values()), None)
    for t in tasks:
        reps = sorted({rep for h in HARNESSES for rep in runs[t][h]})
        rows = []
        for rep in reps:
            tried, cost, mins, chain = [], 0.0, 0.0, []
            h = first(t)
            run, outcome = get(t, h, rep), 0.0
            for attempt in range(max_retries + 1):
                if run is None:
                    break
                tried.append(h)
                cost += run["cost"]
                mins += run["minutes"]
                why = triggered(run, slow_minutes)
                chain.append(f"{h}:{why or 'finished'}")
                outcome = run["reward"] or 0.0
                if why is None:
                    break
                fires[why] += 1
                if run["reward"]:
                    fires["fired after a pass"] += 1  # a timed-out run can still pass; the retry was wasted
                if attempt == max_retries:
                    break
                if same_harness:
                    run = later[t][h].get(rep)
                else:
                    nxt = order(t, tried)
                    if nxt is None:
                        break
                    h, run = nxt, get(t, nxt, rep)
            rows.append({"pass": outcome, "cost": cost, "minutes": mins, "attempts": len(tried), "chain": chain})
        if not rows:
            continue
        per[t] = {"pass": st.mean(r["pass"] for r in rows), "cost": st.mean(r["cost"] for r in rows),
                  "minutes": st.mean(r["minutes"] for r in rows),
                  "attempts": st.mean(r["attempts"] for r in rows),
                  "chains": [r["chain"] for r in rows]}
    return per, fires


def summary(per):
    passes = sum(p["pass"] for p in per.values())
    cost = sum(p["cost"] for p in per.values())
    return {"pass_rate": 100 * passes / len(per), "passes": passes, "cost": cost,
            "cost_per_pass": cost / passes if passes else float("inf"),
            "hours": sum(p["minutes"] for p in per.values()) / 60,
            "retries": sum(p["attempts"] - 1 for p in per.values())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="dev", choices=["dev", "all"])
    ap.add_argument("--unseal", action="store_true")
    ap.add_argument("--max-retries", type=int, default=1)
    ap.add_argument("--slow-minutes", type=float, default=0, help="also retry a run that passed this many minutes")
    ap.add_argument("--crashes", default="count", choices=["count", "superseded"],
                    help="count: use the first attempt, so crashes reach the fallback (deployment view); "
                         "superseded: use our manual same-harness retry (matches analyze_phase1.py)")
    a = ap.parse_args()

    split = json.load(open(f"{ROOT}/study/phase1_tasks.json"))
    pool = split["dev"] if a.tasks == "dev" else split["dev"] + split["test"]
    if a.tasks == "all":
        if not a.unseal:
            sys.exit("--tasks all scores the sealed test tasks; rerun with --unseal")
        rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "by": "fallback_sim.py"}
        open(f"{ROOT}/study/test_unseal_log.jsonl", "a").write(json.dumps(rec) + "\n")
        print(f"TEST SET UNSEALED (logged): {rec}\n")

    runs, later = load_all(crashes=a.crashes)
    cells, _, _ = an.load_runs("jobs/p1-*")
    tasks = sorted(t for t in pool if all(runs[t][h] for h in HARNESSES))
    crashed = sum(1 for t in tasks for h in HARNESSES for r in runs[t][h].values() if triggered(r, 0) == "crash")
    mean_cost = {h: st.mean([r["cost"] for t in tasks for r in runs[t][h].values()]) for h in HARNESSES}
    cheap_first = sorted(HARNESSES, key=lambda h: mean_cost[h])
    print(f"{a.tasks}: {len(tasks)} tasks; mean cost per run " +
          ", ".join(f"{h} ${mean_cost[h]:.3f}" for h in cheap_first))
    print(f"retry order after a trigger: cheapest untried harness ({' -> '.join(cheap_first)}), "
          f"up to {a.max_retries} retry(ies); crash mode {a.crashes} leaves {crashed} crashed runs in the data")

    def order(t, tried):
        return next((h for h in cheap_first if h not in tried), None)

    starts = {f"always {h}": (lambda t, h=h: h) for h in HARNESSES}
    label = "cache: lookup (k-fold, honest)"
    kf = f"{ROOT}/study/kfold_results_dev_fixed.json"
    picks = json.load(open(kf))["picks"].get(label) or {} if os.path.exists(kf) else {}
    missing = [t for t in tasks if t not in picks]
    if not missing:
        starts[label] = lambda t, p=picks: p[t]
    else:
        print(f"\nnote: no k-fold lookup picks for {len(missing)} of {len(tasks)} tasks, so '{label}' is not "
              f"simulated. Run this first: python3 study/kfold_eval.py --baseline fixed")

    print(f"\n{'start harness':34} {'retries':>8} {'pass % no fb':>12} {'pass % fb':>10} {'gain':>6} "
          f"{'same-h':>8} {'$ no fb':>8} {'$ fb':>7} {'extra $':>8} {'h no fb':>8} {'h fb':>6} {'$/pass fb':>10}")
    print(f"{'':34} {'':8} {'':12} {'':10} {'':6} {'control':>8}")
    out = {}
    for name, first in starts.items():
        off, _ = simulate(tasks, runs, later, first, order, 0, 0)
        on, fires = simulate(tasks, runs, later, first, order, a.max_retries, a.slow_minutes)
        ctl, _ = simulate(tasks, runs, later, first, order, a.max_retries, a.slow_minutes, same_harness=True)
        so, sn, sc = summary(off), summary(on), summary(ctl)
        print(f"{name:34} {sn['retries']:8.1f} {so['pass_rate']:12.1f} {sn['pass_rate']:10.1f} "
              f"{sn['pass_rate'] - so['pass_rate']:+6.1f} {sc['pass_rate'] - so['pass_rate']:+8.1f} "
              f"{so['cost']:8.3f} {sn['cost']:7.3f} "
              f"{sn['cost'] - so['cost']:+8.3f} {so['hours']:8.1f} {sn['hours']:6.1f} {sn['cost_per_pass']:10.3f}")
        gained = sn["passes"] - so["passes"]
        out[name] = {"no_fallback": so, "fallback": sn, "same_harness_retry": sc, "triggers": dict(fires),
                     "passes_gained": gained, "passes_gained_same_harness": sc["passes"] - so["passes"],
                     "extra_cost_per_gained_pass": (sn["cost"] - so["cost"]) / gained if gained > 0.01 else None,
                     "extra_hours_per_gained_pass": (sn["hours"] - so["hours"]) / gained if gained > 0.01 else None}
        bits = ", ".join(f"{k} {v}" for k, v in sorted(fires.items()))
        print(f"{'':34} triggers: {bits or 'none'}; passes gained {gained:+.2f}" +
              (f"; extra ${out[name]['extra_cost_per_gained_pass']:.3f} and "
               f"{out[name]['extra_hours_per_gained_pass']:.2f} h per extra pass" if out[name]["extra_cost_per_gained_pass"] else ""))

    best = max(HARNESSES, key=lambda h: an.summary(an.score(
        [t for t in split["dev"] if all(cells[t][h2] for h2 in HARNESSES)], lambda t: [(h, 0.0)], cells))["pass_rate"])
    print(f"\nfor reference, analyze_phase1.py scores always {best} at "
          f"{an.summary(an.score(tasks, lambda t: [(best, 0.0)], cells))['pass_rate']:.1f}% because it drops crashed runs "
          f"instead of counting them as fails")
    p = f"{ROOT}/study/fallback_results_{a.tasks}.json"
    json.dump({"tasks": tasks, "max_retries": a.max_retries, "slow_minutes": a.slow_minutes,
               "retry_order": cheap_first, "results": out}, open(p, "w"), indent=1)
    print(f"wrote {os.path.relpath(p, ROOT)}")


if __name__ == "__main__":
    main()
