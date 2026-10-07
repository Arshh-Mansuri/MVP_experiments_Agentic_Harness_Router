"""Does the Qwen workbook predict which harness Luna needs? And does the 45-task lookup hit the oracle?

Two questions, both answered from local files only (no API key):

1. Verification. Table A now hard-codes the best harness for all 45 Luna tasks, so the lookup should equal the
   stable oracle exactly on those tasks. This asserts it, and shows what the deliberate unsealing bought by
   comparing the new lookup against the old development-only lookup on the 18 test tasks.

2. The fallback. For the 44 tasks Luna has never run, the lookup falls back to a rule over the Qwen3-Coder
   results (Table B). The current rule takes the first harness Qwen passed with, in a fixed order, which was
   never checked against evidence. This measures how much Qwen transfers to Luna at all, then scores four
   candidate fallback rules leave-one-task-out over the 45 Luna tasks.

   Each rule's last resort is "the best single harness". Two ways to set it, both reported, because they
   disagree sharply: leave-one-out fits it on the other 44 tasks, fixed uses the best over all scored tasks.
   On these 45 tasks the three harnesses are nearly tied (54.1 / 54.8 / 51.1 per cent), so the leave-one-out
   default flips between mini-swe-agent and terminus-2 depending on which task is withheld, and it flips
   against the withheld task: dropping a task mini-swe-agent solves is what lets terminus-2 win the average.
   That makes the leave-one-out reference worse than either fixed harness and flatters every Qwen rule, the
   same trap study/kfold_eval.py warns about. Claims therefore use the fixed reference.

   The Qwen half of each rule needs no fitting either way: it comes from a different model's runs.

usage: python3 study/qwen_vs_luna.py [--jobs-glob 'jobs/p1-*']
writes study/qwen_vs_luna_results.json
"""
import argparse, collections, json, os, statistics as st, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "study"))
sys.path.insert(0, os.path.join(ROOT, "router"))
import analyze_phase1 as an

HARNESSES = an.HARNESSES
QWEN_ORDER = ("mini-swe-agent", "terminus-2", "pi")   # the order the current fallback tries
SIGNAL = "PASS"


def qwen_rows():
    t = json.load(open(f"{ROOT}/router/success_table.json"))
    return {r["task"]: r["results"] for r in t["table_b"]}, t


def passers(res):
    """Our harnesses that Qwen passed. ERROR and n/a are no signal, not a failure."""
    return [h for h in HARNESSES if (res or {}).get(h) == SIGNAL]


def best_single(tasks, cells):
    return max(HARNESSES, key=lambda h: st.mean(an.cell(cells, t, h)["pass"] for t in tasks))


def rank_by_rate(tasks, cells):
    """Harnesses ordered by pass rate on the given tasks, best first (ties to the cheaper harness)."""
    rate = {h: st.mean(an.cell(cells, t, h)["pass"] for t in tasks) for h in HARNESSES}
    cost = {h: st.mean(an.cell(cells, t, h)["cost"] for t in tasks) for h in HARNESSES}
    return sorted(HARNESSES, key=lambda h: (-rate[h], cost[h]))


# Each rule: (task, qwen results for it, default harness, harness ranking) -> harness.
RULES = {
    "always the best single harness": lambda t, res, default, rank: default,
    "first Qwen pass in a fixed order (current)":
        lambda t, res, default, rank: next((h for h in QWEN_ORDER if (res or {}).get(h) == SIGNAL), default),
    "divert from default only if Qwen failed it":
        lambda t, res, default, rank: default if (not passers(res) or default in passers(res))
        else passers(res)[0],
    "best-ranked harness among Qwen passes":
        lambda t, res, default, rank: next((h for h in rank if h in passers(res)), default),
}


def agreement(tasks, cells, qwen):
    """Per harness: Luna's pass rate split by what Qwen did with that same harness."""
    rows, pooled = {}, {"pass": [], "fail": []}
    for h in HARNESSES:
        buckets = collections.defaultdict(list)
        for t in tasks:
            verdict = (qwen.get(t) or {}).get(h)
            key = {"PASS": "pass", "FAIL": "fail"}.get(verdict, "no signal")
            buckets[key].append(an.cell(cells, t, h)["pass"])
            if key in pooled:
                pooled[key].append(an.cell(cells, t, h)["pass"])
        rows[h] = {k: {"tasks": len(v), "luna_pass_rate": 100 * st.mean(v) if v else None}
                   for k, v in sorted(buckets.items())}
    lift = None
    if pooled["pass"] and pooled["fail"]:
        lift = 100 * (st.mean(pooled["pass"]) - st.mean(pooled["fail"]))
    return rows, lift, {k: len(v) for k, v in pooled.items()}


def best_harness_hit(tasks, cells, qwen):
    """When Qwen passes with exactly one of our harnesses, is that Luna's best harness?"""
    out = {"one_passer": [0, 0], "any_passer": [0, 0], "no_passer": 0}
    for t in tasks:
        ps = passers(qwen.get(t))
        best = an.stable_pick(cells, t)
        if not ps:
            out["no_passer"] += 1
            continue
        out["any_passer"][1] += 1
        out["any_passer"][0] += best in ps
        if len(ps) == 1:
            out["one_passer"][1] += 1
            out["one_passer"][0] += ps[0] == best
    return out


def references(tasks, cells, mode):
    """The default harness and harness ranking each rule falls back on, per task."""
    if mode == "fixed":
        d, r = best_single(tasks, cells), rank_by_rate(tasks, cells)
        return {t: d for t in tasks}, {t: r for t in tasks}
    out_d, out_r = {}, {}
    for t in tasks:
        others = [x for x in tasks if x != t]
        out_d[t] = best_single(others, cells)
        out_r[t] = rank_by_rate(others, cells)
    return out_d, out_r


def score_rules(tasks, cells, qwen, defaults, ranks):
    picks = {name: {} for name in RULES}
    for t in tasks:
        for name, fn in RULES.items():
            picks[name][t] = fn(t, qwen.get(t), defaults[t], ranks[t])
    return picks


def report(label, tasks, cells, picks, baseline_name):
    base = an.score(tasks, lambda t: [(picks[baseline_name][t], 0.0)], cells)
    bs = an.summary(base)
    print(f"\n{label} ({len(tasks)} tasks), reference = {baseline_name}: "
          f"{bs['pass_rate']:.1f}% pass, ${bs['cost_per_pass']:.4f} per pass")
    print(f"  {'rule':44} {'pass %':>7} {'diff (95% CI)':>24} {'$/pass':>8} {'diverts':>8}")
    out = {}
    for name in RULES:
        per = an.score(tasks, lambda t, p=picks[name]: [(p[t], 0.0)], cells)
        s = an.summary(per)
        diffs = [100 * (per[t]["pass"] - base[t]["pass"]) for t in tasks]
        lo, hi = an.boot_ci(diffs)
        diverts = sum(picks[name][t] != picks[baseline_name][t] for t in tasks)
        print(f"  {name:44} {s['pass_rate']:7.1f} {st.mean(diffs):+7.1f} [{lo:+6.1f}, {hi:+6.1f}] "
              f"{s['cost_per_pass']:8.4f} {diverts:8d}")
        out[name] = {"tasks": len(tasks), "pass_rate": s["pass_rate"], "cost_per_pass": s["cost_per_pass"],
                     "diff_vs_reference_pts": st.mean(diffs), "ci95": [lo, hi], "diverts": diverts}
    return out, bs


def verify_lookup(cells, split, table):
    """The 45-task lookup must equal the stable oracle; the old dev-only lookup is the comparison."""
    best = {r["task"]: r["best"] for r in table["table_a"]}
    dev_only = {r["task"]: r["best"] for r in table["table_a"] if r["split"] == "dev"}
    qwen = {r["task"]: r["results"] for r in table["table_b"]}
    default = "mini-swe-agent"

    def old_lookup(t):
        if t in dev_only:
            return dev_only[t]
        return next((h for h in QWEN_ORDER if (qwen.get(t) or {}).get(h) == SIGNAL), default)

    out = {}
    for label, tasks in (("all 45 Luna tasks", sorted(best)), ("18 test tasks only", sorted(split["test"]))):
        tasks = [t for t in tasks if an.ran(cells, t)]
        oracle = an.summary(an.score(tasks, lambda t: [(an.stable_pick(cells, t), 0.0)], cells))
        new = an.summary(an.score(tasks, lambda t: [(best[t], 0.0)], cells))
        old = an.summary(an.score(tasks, lambda t: [(old_lookup(t), 0.0)], cells))
        mini = an.summary(an.score(tasks, lambda t: [("mini-swe-agent", 0.0)], cells))
        per_new = an.score(tasks, lambda t: [(best[t], 0.0)], cells)
        per_old = an.score(tasks, lambda t: [(old_lookup(t), 0.0)], cells)
        diffs = [100 * (per_new[t]["pass"] - per_old[t]["pass"]) for t in tasks]
        lo, hi = an.boot_ci(diffs)
        assert abs(new["pass_rate"] - oracle["pass_rate"]) < 1e-9, \
            f"{label}: lookup {new['pass_rate']} != stable oracle {oracle['pass_rate']}"
        print(f"\n{label} ({len(tasks)} scored)")
        print(f"  stable oracle (best of 3 harnesses)   {oracle['pass_rate']:6.1f}%  ${oracle['cost_per_pass']:.4f}/pass")
        print(f"  lookup, 45 tasks hard-coded           {new['pass_rate']:6.1f}%  ${new['cost_per_pass']:.4f}/pass"
              f"   == oracle (verified)")
        print(f"  lookup, development-only (previous)   {old['pass_rate']:6.1f}%  ${old['cost_per_pass']:.4f}/pass")
        print(f"  always mini-swe-agent                 {mini['pass_rate']:6.1f}%  ${mini['cost_per_pass']:.4f}/pass")
        print(f"  unsealing gains {st.mean(diffs):+.1f} points over the development-only lookup [{lo:+.1f}, {hi:+.1f}]")
        out[label] = {"tasks": len(tasks), "stable_oracle_pass_rate": oracle["pass_rate"],
                      "lookup45_pass_rate": new["pass_rate"], "lookup45_cost_per_pass": new["cost_per_pass"],
                      "lookup_dev_only_pass_rate": old["pass_rate"],
                      "always_mini_pass_rate": mini["pass_rate"],
                      "unsealing_gain_pts": st.mean(diffs), "unsealing_ci95": [lo, hi],
                      "equals_oracle": True}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs-glob", default="jobs/p1-*")
    a = ap.parse_args()
    split = json.load(open(f"{ROOT}/study/phase1_tasks.json"))
    cells, _, _ = an.load_runs(a.jobs_glob)
    qwen, table = qwen_rows()
    if not table.get("includes_test"):
        sys.exit("router/success_table.json has no test tasks; run: python3 router/build_success_table.py --include-test")

    tasks = sorted(t for t in split["dev"] + split["test"] if an.ran(cells, t))
    overlap = [t for t in tasks if t in qwen]
    print(f"Luna tasks with runs: {len(tasks)}; also in the Qwen workbook: {len(overlap)}")

    print("\n=== 1. Verification: does the hard-coded lookup reach the best of 3 harnesses? ===")
    verification = verify_lookup(cells, split, table)

    print("\n=== 2. Does Qwen predict Luna? ===")
    rows, lift, pooled = agreement(overlap, cells, qwen)
    print(f"  {'harness':16} " + " ".join(f"{k:>22}" for k in ("Qwen PASS", "Qwen FAIL", "no signal")))
    for h in HARNESSES:
        cellsrow = []
        for k in ("pass", "fail", "no signal"):
            v = rows[h].get(k)
            cellsrow.append(f"{v['luna_pass_rate']:5.1f}% (n={v['tasks']:2d})" if v and v["luna_pass_rate"] is not None
                            else f"{'-':>13}")
        print(f"  {h:16} " + " ".join(f"{x:>22}" for x in cellsrow))
    print(f"  pooled over harness-task pairs: Luna passes {lift:+.1f} points more often when Qwen passed "
          f"(n={pooled['pass']} pass, {pooled['fail']} fail)")

    hit = best_harness_hit(overlap, cells, qwen)
    chance = 1 / len(HARNESSES)
    for key, label in (("one_passer", "Qwen passed with exactly one harness"), ("any_passer", "Qwen passed with any harness")):
        got, n = hit[key]
        print(f"  {label}: it is Luna's best harness {got}/{n}"
              + (f" ({100 * got / n:.0f}%, chance {100 * chance:.0f}%)" if n else ""))
    print(f"  Qwen passed with none of our harnesses on {hit['no_passer']}/{len(overlap)} tasks "
          f"(the fallback cannot act on these)")

    print("\n=== 3. Candidate fallback rules ===")
    baseline = "always the best single harness"
    acted = [t for t in tasks if passers(qwen.get(t))]
    modes = {}
    for mode in ("fixed", "loto"):
        defaults, ranks = references(tasks, cells, mode)
        spread = collections.Counter(defaults.values())
        picks = score_rules(tasks, cells, qwen, defaults, ranks)
        label = f"default = best single harness, {mode}"
        if mode == "loto" and len(spread) > 1:
            label += f" - UNSTABLE, flips {dict(spread)}; treat as a sensitivity check, not the claim"
        print(f"\n--- {label} ---")
        all_rules, _ = report("all Luna tasks", tasks, cells, picks, baseline)
        acted_rules, _ = report("only tasks where Qwen passed something", acted, cells, picks, baseline)
        same = {n for n in RULES if n != baseline and picks[n] == picks["first Qwen pass in a fixed order (current)"]}
        if len(same) == len(RULES) - 1:
            print("  (the three Qwen rules are one rule here: with a mini-swe-agent-first default and ranking, "
                  "'first in order', 'divert only if the default failed' and 'best-ranked passer' agree everywhere)")
        modes[mode] = {"default_counts": dict(spread), "rules_all_tasks": all_rules,
                       "rules_qwen_acted": acted_rules, "qwen_rules_identical": len(same) == len(RULES) - 1,
                       "picks": picks}

    claim = modes["fixed"]["rules_all_tasks"]
    beats = {n: v for n, v in claim.items()
             if n != baseline and v["diff_vs_reference_pts"] > 0 and v["ci95"][0] > 0}
    if beats:
        winner = max(beats, key=lambda n: beats[n]["diff_vs_reference_pts"])
        print(f"\nwinner on the fixed reference: {winner} "
              f"({claim[winner]['diff_vs_reference_pts']:+.1f} points, CI [{claim[winner]['ci95'][0]:+.1f}, "
              f"{claim[winner]['ci95'][1]:+.1f}] excludes 0)")
    else:
        winner = baseline
        print(f"\nwinner: {baseline} - no Qwen rule beats it with a confidence interval that excludes 0, "
              f"so the fallback should stay the plain default")

    out = {"luna_tasks": len(tasks), "qwen_overlap": len(overlap), "verification": verification,
           "agreement": rows, "pooled_lift_pts": lift, "best_harness_hit": hit,
           "qwen_acted_tasks": len(acted), "baseline_rule": baseline, "modes": modes, "winner": winner}
    p = f"{ROOT}/study/qwen_vs_luna_results.json"
    json.dump(out, open(p, "w"), indent=1)
    print(f"\nwrote {os.path.relpath(p, ROOT)}")


if __name__ == "__main__":
    main()
