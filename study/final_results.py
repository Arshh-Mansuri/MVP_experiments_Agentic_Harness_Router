"""Results table for the final meta-harness run (Project 16): router vs each single harness, accuracy and cost.

Reads the final batch from study/live_runs.jsonl (written by study/run_final.sh) and compares it, model held
constant, with the saved Luna baselines; nothing is run and nothing is called.

  Table A tasks (45)   Luna ran every harness 3 times in Phase 1 (jobs/p1-*), so the router is compared like for like
                       with each single harness, with and without the same-harness fallback, and with perfect picking.
                       Crashes count as fails, as a deployment would see them (study/fallback_sim.py).
                       The router answers these from the success table, so this measures the deployed system,
                       not generalisation.
  Unseen tasks (44)    no Luna baseline exists, so only the router's own score, cost and tokens are reported.
                       Qwen3-Coder's per-harness results (the 89-task Stage 1 baseline, a different model) are shown
                       for reference only and are never subtracted from Luna's.
A task's live result is its fallback attempt's if one ran, otherwise its first attempt's; a task with no reward
counts as a fail.

usage: python3 study/final_results.py [--batch final] [--tasks study/final_tasks_all.txt] [--brief]
       [--runs study/live_runs.jsonl] [--out study/final_results_<batch>.md]
"""
import argparse, collections, json, os, statistics as st, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "study"))
import analyze_phase1 as an
import fallback_sim as fs

HARNESSES = an.HARNESSES


def live(path, batch, tasks):
    """per task: first and fallback rows of the batch, the final reward (None -> 0) and summed cost and tokens."""
    rows = collections.defaultdict(dict)
    for line in open(path) if os.path.exists(path) else []:
        r = json.loads(line)
        if r.get("batch") == batch and r.get("task") in tasks:
            rows[r["task"]]["fallback" if r.get("attempt") == "fallback" else "first"] = r
    out = {}
    for t, d in rows.items():
        attempts = [r for r in (d.get("first"), d.get("fallback")) if r]
        final = d.get("fallback") or d.get("first")
        out[t] = {"harness": d["first"]["harness"] if "first" in d else final["harness"],
                  "match": (d.get("first") or final).get("match"),
                  "reward": final.get("reward"), "pass": float(final.get("reward") or 0),
                  "fallback": "fallback" in d,
                  "rescued": "fallback" in d and (d.get("first", {}).get("reward") or 0) < 1 <= (final.get("reward") or 0),
                  "cost": sum((r.get("cost_usd") or 0) + (r.get("route_cost") or 0) for r in attempts),
                  "route_cost": sum(r.get("route_cost") or 0 for r in attempts),
                  "tokens": sum((r.get("input_tokens") or 0) + (r.get("output_tokens") or 0) for r in attempts),
                  "minutes": sum(r.get("minutes") or 0 for r in attempts)}
    return out


def line(name, per, tasks, note=""):
    n = len(tasks)
    passes = sum(per[t]["pass"] for t in tasks if t in per)
    cost = sum(per[t]["cost"] for t in tasks if t in per)
    tok = sum(per[t].get("tokens") or 0 for t in tasks if t in per)
    return (f"| {name} | {100 * passes / n:.1f}% | {passes:.1f}/{n} | ${cost:.3f} | "
            f"{'$%.4f' % (cost / passes) if passes else '-'} | {tok / 1e6:.2f}M | {note} |")


HEAD = ["| Strategy | Pass rate | Passes | Cost | Cost per pass | Tokens | Note |", "|---|---|---|---|---|---|---|"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default="final")
    ap.add_argument("--tasks", default=os.path.join(ROOT, "study", "final_tasks_all.txt"))
    ap.add_argument("--runs", default=os.path.join(ROOT, "study", "live_runs.jsonl"))
    ap.add_argument("--out")
    ap.add_argument("--brief", action="store_true", help="print the batch summary only")
    a = ap.parse_args()

    tasks = [l.split()[0] for l in open(a.tasks) if l.strip() and not l.lstrip().startswith("#")]
    table = json.load(open(os.path.join(ROOT, "router", "success_table.json")))
    seen = [t for t in tasks if t in {r["task"] for r in table["table_a"]}]
    unseen = [t for t in tasks if t not in seen]
    run = live(a.runs, a.batch, set(tasks))

    done = [t for t in tasks if t in run]
    scored = [t for t in done if run[t]["reward"] is not None]
    passed = sum(run[t]["pass"] for t in done)
    fb = [t for t in done if run[t]["fallback"]]
    summary = [
        f"batch '{a.batch}': {len(done)} of {len(tasks)} tasks run, {len(scored)} scored, {passed:.0f} passed "
        f"({100 * passed / max(len(tasks), 1):.1f}% of all {len(tasks)}; unrun or unscored count as fails)",
        f"fallbacks: {len(fb)} fired, {sum(run[t]['rescued'] for t in fb)} turned a fail into a pass",
        f"cost ${sum(run[t]['cost'] for t in done):.3f} (routing ${sum(run[t]['route_cost'] for t in done):.4f}), "
        f"{sum(run[t]['tokens'] for t in done) / 1e6:.2f}M tokens, {sum(run[t]['minutes'] for t in done) / 60:.1f} "
        f"run-hours",
        "harness picks: " + ", ".join(f"{h} {c}" for h, c in
                                      collections.Counter(run[t]["harness"] for t in done).most_common())]
    unscored = [t for t in done if run[t]["reward"] is None]
    if len(done) < len(tasks):
        summary.append(f"{len(tasks) - len(done)} not run yet (rerun study/run_final.sh to continue)")
    if unscored:
        summary.append(f"{len(unscored)} ran but got no reward (counted as fails): " + " ".join(unscored))
    print("\n".join(summary))
    if a.brief:
        return

    md = [f"# Final run results: batch `{a.batch}`", "",
          "Model held constant: GPT-5.6-Luna executes every run; Luna routes. Generated by `study/final_results.py`.",
          "", "```", *summary, "```", ""]

    if seen:
        runs, later = fs.load_all()
        cells, _, _ = an.load_runs("jobs/p1-*")
        md += [f"## Table A tasks ({len(seen)}): router vs each single harness, Luna", "",
               "Single harnesses: Phase 1, 3 repeats per task, crashes count as fails. The router's live result is "
               "one run per task, so expect about ±7 points of run-to-run noise on 45 tasks.", "", *HEAD]
        md.append(line("**Meta-harness (live: router + same-harness fallback)**", run, seen,
                       f"{sum(1 for t in seen if t in run)} of {len(seen)} run"))
        for h in HARNESSES:
            for retries, label in ((0, ""), (1, " + same-harness fallback")):
                per, _ = fs.simulate(seen, runs, later, lambda t, h=h: h, None, retries, 0, same_harness=True)
                for t in per:
                    per[t]["tokens"] = an.cell(cells, t, h)["tokens"]
                md.append(line(f"always {h}{label}", per, seen))
        per, _ = fs.simulate(seen, runs, later, lambda t: an.stable_pick(cells, t), None, 0, 0, same_harness=True)
        for t in per:
            per[t]["tokens"] = an.cell(cells, t, an.stable_pick(cells, t))["tokens"]
        md.append(line("perfect picking (oracle, no fallback)", per, seen, "ceiling"))
        base, _ = fs.simulate(seen, runs, later, lambda t: "mini-swe-agent", None, 1, 0, same_harness=True)
        both = [t for t in seen if t in run and t in base]
        if both:
            diffs = [run[t]["pass"] - base[t]["pass"] for t in both]
            lo, hi = an.boot_ci(diffs)
            md += ["", f"Meta-harness minus always mini-swe-agent + fallback, paired over {len(both)} tasks: "
                       f"{100 * st.mean(diffs):+.1f} points [{100 * lo:+.1f}, {100 * hi:+.1f}] (95% bootstrap CI)."]
        md.append("")

    if unseen:
        qwen = {r["task"]: r["results"] for r in table["table_b"]}
        md += [f"## Unseen tasks ({len(unseen)}): router only (no Luna baseline)", "", *HEAD,
               line("**Meta-harness (live)**", run, unseen, f"{sum(1 for t in unseen if t in run)} of {len(unseen)} run"),
               "", "Reference only, different model (Qwen3-Coder 480B, 1 run per harness, Stage 1 baseline):", "",
               "| Harness | Qwen pass rate on these tasks |", "|---|---|"]
        for h in HARNESSES + ["opencode"]:
            n = sum(1 for t in unseen if t in qwen)
            p = sum(1 for t in unseen if (qwen.get(t) or {}).get(h) == "PASS")
            md.append(f"| {h} | {100 * p / max(n, 1):.1f}% ({p}/{n}) |")
        md.append("")

    qwen_all = table["table_b"]
    md += ["## Stage 1 baseline: Qwen3-Coder 480B on all 89 tasks (reference)", "",
           "| Harness | Pass | Error |", "|---|---|---|"]
    for h in HARNESSES + ["opencode"]:
        md.append(f"| {h} | {sum(r['results'].get(h) == 'PASS' for r in qwen_all)}/{len(qwen_all)} | "
                  f"{sum(r['results'].get(h) == 'ERROR' for r in qwen_all)} |")

    md += ["", "## Per task", "", "| Task | Set | Harness | How chosen | Reward | Fallback | Cost |", "|---|---|---|---|---|---|---|"]
    for t in tasks:
        r = run.get(t)
        md.append(f"| {t} | {'A' if t in seen else 'unseen'} | " + (
            f"{r['harness']} | {r['match']} | {r['reward']} | {'yes' if r['fallback'] else ''} | ${r['cost']:.4f} |"
            if r else "not run | | | | |"))

    out = a.out or os.path.join(ROOT, "study", f"final_results_{a.batch}.md")
    open(out, "w").write("\n".join(md) + "\n")
    print(f"\nwritten {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
