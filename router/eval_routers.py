import json, os, sys, statistics as st
import outcomes, router2 as R

TRAIN = "fix-git cobol-modernization git-leak-recovery prove-plus-comm polyglot-c-py db-wal-recovery winning-avg-corewars count-dataset-tokens build-cython-ext large-scale-text-editing headless-terminal gcode-to-text distribution-search constraints-scheduling".split()
HELD = "multi-source-data-merger feal-linear-cryptanalysis protein-assembly cancel-async-tasks code-from-image torch-pipeline-parallelism crack-7z-hash path-tracing chess-best-move schemelike-metacircular-eval".split()
CACHE = os.path.join(os.path.dirname(__file__), "picks_cache.json")


def evaluate(tasks, label):
    O = outcomes.build("../jobs")
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    tasks = [t for t in tasks if all(O[t].get(h) for h in R.HARNESSES)]  # only tasks with all 3 harness outcomes
    res = {}
    for t in tasks:
        if t not in cache:
            p1, c1 = R.pick_v1(t); sc, why, c2 = R.scores(t)
            cache[t] = {"v1": p1, "scores": sc, "why": why, "cost_v1": c1, "cost_v2": c2}
    json.dump(cache, open(CACHE, "w"), indent=1)
    mean = lambda t, h: st.mean(O[t][h])
    rows = {
        "fixed terminus-2": [mean(t, "terminus-2") for t in tasks],
        "fixed mini-swe-agent": [mean(t, "mini-swe-agent") for t in tasks],
        "fixed pi": [mean(t, "pi") for t in tasks],
        "random": [st.mean(mean(t, h) for h in R.HARNESSES) for t in tasks],
        "oracle (best in hindsight)": [max(mean(t, h) for h in R.HARNESSES) for t in tasks],
        "router v1 (single pick, factual cards)": [mean(t, cache[t]["v1"]) for t in tasks],
        "router v2 (score, margin 0 / ties->default)": [mean(t, R.pick_from_scores(cache[t]["scores"], 0 + 0) if False else R.pick_from_scores(cache[t]["scores"], 1) if False else max(R.HARNESSES, key=lambda h: (cache[t]["scores"][h], h == R.DEFAULT))) for t in tasks],
        "router v3 (score, override default only if +1)": [mean(t, R.pick_from_scores(cache[t]["scores"], 1)) for t in tasks],
        "router v4 (score, override default only if +2)": [mean(t, R.pick_from_scores(cache[t]["scores"], 2)) for t in tasks],
    }
    print(f"\n== {label}: {len(tasks)} tasks with all 3 harness outcomes")
    for k, v in rows.items():
        print(f"  {k:48} {sum(v):5.2f}/{len(v)}  ({100*st.mean(v):.0f}%)")
    print("  picks (v1 | v2 scores):")
    for t in tasks:
        print(f"   {t[:26]:26} v1={cache[t]['v1'][:9]:9} scores={cache[t]['scores']} truth={ {h: round(mean(t,h),2) for h in R.HARNESSES} }")
    tot = sum(cache[t]['cost_v1']['cost'] + cache[t]['cost_v2']['cost'] for t in tasks)
    print(f"  routing cost for both methods over {len(tasks)} tasks: ${tot:.4f}")


if __name__ == "__main__":
    evaluate(TRAIN if sys.argv[1] == "train" else HELD, sys.argv[1])
