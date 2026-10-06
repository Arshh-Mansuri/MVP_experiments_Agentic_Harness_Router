"""k-fold cross-validated replay: the main evaluation (PROBLEM_DEFINITION.md step 6).

Every strategy is scored by replaying its harness choice against the saved Phase 1 runs. Anything that learns
from outcomes (the k-NN router, the metadata tree, the lookup cache) is fitted on the training folds only and
predicts the held-out fold, so in-sample leakage cannot inflate it. The baseline "best single harness" is also
chosen per training fold. Fixed LLM routers do not learn, so their picks are the same in every fold; k-fold only
changes what they are compared against.

The development / test split stays available as a secondary check in analyze_phase1.py. Scoring test tasks here
needs --tasks all --unseal, which is logged to study/test_unseal_log.jsonl.

usage: python3 study/kfold_eval.py [--folds 5] [--seed 0] [--tasks dev|all] [--unseal]
"""
import argparse, collections, datetime, json, os, random, statistics as st, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "study"))
import analyze_phase1 as an
import task_features as tf

HARNESSES = an.HARNESSES
QWEN_ORDER = ("mini-swe-agent", "terminus-2", "pi")
DEFAULT = "mini-swe-agent"


def fold_of(tasks, folds, seed):
    order = sorted(tasks)
    random.Random(seed).shuffle(order)
    return {t: i % folds for i, t in enumerate(order)}


def best_single(train, cells):
    return max(HARNESSES, key=lambda h: st.mean(an.cell(cells, t, h)["pass"] for t in train))


def qwen_table():
    p = os.path.join(ROOT, "router", "success_table.json")
    if not os.path.exists(p):
        return {}
    return {r["task"]: r["results"] for r in json.load(open(p))["table_b"]}


def lookup_from(train, cells, qwen):
    """The lookup cache rebuilt from training tasks only: known task -> its best harness, else Qwen hint, else default."""
    known = {t: an.stable_pick(cells, t) for t in train}

    def pick(task):
        if task in known:
            return known[task]
        res = qwen.get(task) or {}
        for h in QWEN_ORDER:
            if res.get(h) == "PASS":
                return h
        return DEFAULT
    return pick


def knn_from(train, cells, texts, k=3):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.pipeline import make_pipeline
    y = [an.stable_pick(cells, t) for t in train]
    if len(set(y)) < 2:
        return lambda task: y[0]
    model = make_pipeline(TfidfVectorizer(stop_words="english", min_df=1),
                          KNeighborsClassifier(n_neighbors=min(k, len(train))))
    model.fit([texts[t] for t in train], y)
    return lambda task: model.predict([texts[task]])[0]


def tree_from(train, cells, feats, depth=2):
    """The one-hot vocabulary is fitted on the training fold only, so a category or tag that appears solely in the
    held-out fold cannot create a column; it encodes as all-zeros instead."""
    from sklearn.tree import DecisionTreeClassifier
    y = [an.stable_pick(cells, t) for t in train]
    if len(set(y)) < 2:
        return lambda task: y[0]
    vocab = tf.one_hot_vocab([feats[t] for t in train])
    X = tf.one_hot_apply([feats[t] for t in train], vocab)
    names = list(X[0])
    clf = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=3, random_state=0)
    clf.fit([[d[n] for n in names] for d in X], y)

    def predict(task):
        d = tf.one_hot_apply([feats[task]], vocab)[0]
        return clf.predict([[d[n] for n in names]])[0]
    return predict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tasks", default="dev", choices=["dev", "all"])
    ap.add_argument("--baseline", default="fold", choices=["fold", "fixed"],
                    help="fold: best single harness per training fold (deployment-realistic, but unstable); "
                         "fixed: best single harness over all scored tasks (stable reference)")
    ap.add_argument("--unseal", action="store_true", help="required for --tasks all (logged)")
    a = ap.parse_args()

    split = json.load(open(f"{ROOT}/study/phase1_tasks.json"))
    cells, _, failures = an.load_runs("jobs/p1-*")
    pool = split["dev"] if a.tasks == "dev" else split["dev"] + split["test"]
    if a.tasks == "all":
        if not a.unseal:
            sys.exit("--tasks all scores the sealed test tasks; rerun with --unseal")
        rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "by": "kfold_eval.py",
               "folds": a.folds, "seed": a.seed}
        open(f"{ROOT}/study/test_unseal_log.jsonl", "a").write(json.dumps(rec) + "\n")
        print(f"TEST SET UNSEALED (logged): {rec}\n")
    tasks = sorted(t for t in pool if all(cells[t][h] for h in HARNESSES))
    folds = fold_of(tasks, a.folds, a.seed)

    extracted = {t: tf.features(t) for t in tasks}
    texts = {t: v[1] for t, v in extracted.items()}
    feats = {t: v[0] for t, v in extracted.items()}  # encoded per fold, not up front
    qwen = qwen_table()

    # learned strategies: fitted on the training folds, predicting the held-out fold
    learners = {"learned: k-NN on task text (TF-IDF)": lambda tr: knn_from(tr, cells, texts),
                "learned: decision tree on metadata": lambda tr: tree_from(tr, cells, feats),
                "cache: lookup (k-fold, honest)": lambda tr: lookup_from(tr, cells, qwen)}
    picks = {name: {} for name in learners}
    baseline_pick = {}
    for f in range(a.folds):
        train = [t for t in tasks if folds[t] != f]
        held = [t for t in tasks if folds[t] == f]
        if not train or not held:
            continue
        b = best_single(train, cells)
        for t in held:
            baseline_pick[t] = b
        for name, make in learners.items():
            fn = make(train)
            for t in held:
                picks[name][t] = fn(t)

    fold_baselines = collections.Counter(baseline_pick.values())
    if a.baseline == "fixed":
        fixed = best_single(tasks, cells)
        baseline_pick = {t: fixed for t in tasks}
    chosen_baselines = collections.Counter(baseline_pick.values())
    print(f"{a.tasks}: {len(tasks)} tasks, {a.folds} folds (seed {a.seed}), baseline mode {a.baseline}")
    print(f"runs without a reward (not counted): {dict(failures) or 0}")
    print(f"best single harness per training fold (tasks it was applied to): {dict(fold_baselines)}")
    if len(fold_baselines) > 1 and a.baseline == "fold":
        print("  NOTE: the best single harness is not stable across folds, so this baseline is itself noisy; "
              "compare with --baseline fixed before claiming a router beats it")

    strategies = {f"always {h}": (lambda t, h=h: [(h, 0.0, 0, 0.0)]) for h in HARNESSES}
    strategies["random"] = lambda t: [(h, 0.0, 0, 0.0) for h in HARNESSES]
    strategies[an.STABLE_ORACLE] = lambda t: [(an.stable_pick(cells, t), 0.0, 0, 0.0)]
    strategies["oracle: cheapest-pass"] = lambda t: [(an.cheapest_pass_pick(cells, t), 0.0, 0, 0.0)]
    for name, by_task in picks.items():
        strategies[name] = lambda t, b=by_task: [(b[t], 0.0, 0, 0.0)]
    for rt, by_task in an.load_picks().items():
        if rt == "lookup":
            continue  # in-sample by construction; the honest k-fold version is above
        if all(t in by_task for t in tasks):
            strategies[f"router: {rt} (no training)"] = lambda t, b=by_task: b[t]

    base = an.score(tasks, lambda t: [(baseline_pick[t], 0.0, 0, 0.0)], cells)
    bs = an.summary(base)
    oracle_rate = an.summary(an.score(tasks, strategies[an.STABLE_ORACLE], cells))["pass_rate"]
    gap = oracle_rate - bs["pass_rate"]

    label = "per training fold" if a.baseline == "fold" else f"fixed = {chosen_baselines.most_common(1)[0][0]}"
    print(f"\nbaseline = best single harness, {label}: {bs['pass_rate']:.1f}% pass, "
          f"${bs['cost_per_pass']:.3f} per pass")
    print(f"{'strategy':40} {'pass %':>6} {'diff vs base (95% CI)':>24} {'headroom':>8} {'cost':>7} {'$/pass':>7} "
          f"{'cpp vs base':>11} {'route $':>8}")
    results = {}
    for name, choose in strategies.items():
        per = an.score(tasks, choose, cells)
        s = an.summary(per)
        diffs = [100 * (per[t]["pass"] - base[t]["pass"]) for t in tasks]
        lo, hi = an.boot_ci(diffs)
        cpp = (s["cost_per_pass"] / bs["cost_per_pass"] - 1) if bs["passes"] else float("nan")
        headroom = (s["pass_rate"] - bs["pass_rate"]) / gap if gap > 0 else float("nan")
        routes = name.startswith(("learned:", "router:", "cache:"))  # criteria apply to routing only, not references
        meets_pass = routes and st.mean(diffs) >= an.PASS_GAIN and lo > 0
        meets_cost = routes and cpp <= -an.COST_CUT and s["pass_rate"] >= bs["pass_rate"] - an.COST_PASS_TOLERANCE
        flag = " PASS-CRITERION" if meets_pass else (" COST-CRITERION" if meets_cost else "")
        print(f"{name:40} {s['pass_rate']:6.1f} {st.mean(diffs):+7.1f} [{lo:+6.1f}, {hi:+6.1f}] {100 * headroom:+7.0f}% "
              f"{s['cost']:7.3f} {s['cost_per_pass']:7.3f} {100 * cpp:+10.0f}% {s['routing_cost']:8.3f}{flag}")
        results[name] = {**s, "diff_mean": st.mean(diffs), "ci": [lo, hi], "cost_per_pass_change": cpp,
                         "headroom_recovered": headroom, "meets_pass_criterion": meets_pass,
                         "meets_cost_criterion": meets_cost}

    out = f"{ROOT}/study/kfold_results_{a.tasks}_{a.baseline}.json"
    json.dump({"tasks": tasks, "folds": a.folds, "seed": a.seed, "baseline_mode": a.baseline,
               "baseline_per_fold": dict(fold_baselines), "stable_oracle_pass_rate": oracle_rate,
               "results": results, "picks": picks}, open(out, "w"), indent=1)
    print(f"\nwrote {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
