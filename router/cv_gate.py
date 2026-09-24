"""Cheap-classifier gate: is there any exploitable task-text -> harness signal
in the Qwen 89-task baseline, before spending money on a hosted fine-tune?

Method: TF-IDF over each task's instruction.md -> logistic regression predicting
the best-scoring harness for that task, evaluated with leave-one-out cross-validation
(no single train/held-out split, which is what made the earlier n=21 Luna router
study noisy). Compared against best-fixed-harness, random-routing and oracle
baselines computed directly from the same reward table.

Fully offline: no API calls, no Harbor runs. Costs nothing, runs in seconds.
"""
import collections
import numpy as np
from sklearn.neighbors import KNeighborsClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import LeaveOneOut
from sklearn.dummy import DummyClassifier
from gate_router import HARNESSES, load_reward_table, load_task_text, make_pipeline


def main():
    pivot = load_reward_table()
    tasks = list(pivot.index)
    texts = [load_task_text(t) for t in tasks]
    y = pivot.idxmax(axis=1).values          # best harness per task (ties -> first column, mini-swe-agent)
    R = pivot.values                          # n_tasks x n_harnesses reward matrix
    n = len(tasks)

    # --- baselines, computed directly from the reward table ---
    fixed = pivot.mean()
    best_fixed_name, best_fixed_rate = fixed.idxmax(), fixed.max()
    oracle_rate = pivot.max(axis=1).mean()
    random_rate = pivot.mean(axis=1).mean()

    # --- LOOCV for the TF-IDF + logistic regression router, kNN variants, and dummy ---
    loo = LeaveOneOut()
    K_VALUES = [1, 3, 5, 7, 9, 15]
    router_hits = []
    dummy_hits = []  # majority-class baseline, to sanity check the classifier isn't just guessing
    knn_hits = {k: [] for k in K_VALUES}
    knn_picks = {k: [] for k in K_VALUES}  # track diversity of picks, separately from hit rate
    rf_hits, rf_picks = [], []
    for train_idx, test_idx in loo.split(texts):
        i = test_idx[0]
        vec, clf = make_pipeline()
        Xtr = vec.fit_transform([texts[j] for j in train_idx])
        Xte = vec.transform([texts[i]])
        ytr = [y[j] for j in train_idx]

        clf.fit(Xtr, ytr)
        lr_pick = clf.predict(Xte)[0]
        router_hits.append(R[i, HARNESSES.index(lr_pick)])

        dummy = DummyClassifier(strategy="most_frequent").fit(Xtr, ytr)
        dpick = dummy.predict(Xte)[0]
        dummy_hits.append(R[i, HARNESSES.index(dpick)])

        for k in K_VALUES:
            knn = KNeighborsClassifier(n_neighbors=min(k, len(train_idx)), metric="cosine")
            knn.fit(Xtr, ytr)
            kpick = knn.predict(Xte)[0]
            knn_hits[k].append(R[i, HARNESSES.index(kpick)])
            knn_picks[k].append(kpick)

        rf = RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=0)
        rf.fit(Xtr, ytr)
        rpick = rf.predict(Xte)[0]
        rf_hits.append(R[i, HARNESSES.index(rpick)])
        rf_picks.append(rpick)

    router_rate = float(np.mean(router_hits))
    dummy_rate = float(np.mean(dummy_hits))
    knn_rates = {k: float(np.mean(v)) for k, v in knn_hits.items()}
    rf_rate = float(np.mean(rf_hits))

    print(f"Tasks: {n}\n")
    print("Fixed-harness pass rates:")
    for h, v in fixed.sort_values(ascending=False).items():
        print(f"  {h:16} {v:.3f}  ({int(round(v*n))}/{n})")
    print(f"\nBest fixed harness:      {best_fixed_rate:.3f}  ({best_fixed_name})")
    print(f"Random routing:          {random_rate:.3f}")
    print(f"Majority-class dummy (LOOCV): {dummy_rate:.3f}")
    print(f"TF-IDF+LR router (LOOCV):     {router_rate:.3f}  ({sum(router_hits):.1f}/{n})")
    for k in K_VALUES:
        picks = collections.Counter(knn_picks[k])
        print(f"TF-IDF+kNN(k={k:<2}) router (LOOCV): {knn_rates[k]:.3f}  ({sum(knn_hits[k]):.1f}/{n})  picks={dict(picks)}")
    rf_pick_counts = collections.Counter(rf_picks)
    print(f"TF-IDF+RandomForest router (LOOCV): {rf_rate:.3f}  ({sum(rf_hits):.1f}/{n})  picks={dict(rf_pick_counts)}")
    print(f"Oracle (perfect routing):     {oracle_rate:.3f}  ({sum(pivot.max(axis=1)):.1f}/{n})")
    print(f"\nHeadroom (oracle - best fixed): {(oracle_rate-best_fixed_rate)*100:.1f} pts = {(oracle_rate-best_fixed_rate)*n:.1f} tasks")
    best_knn_k = max(knn_rates, key=knn_rates.get)
    best_knn_rate = knn_rates[best_knn_k]
    print(f"LR lift over best fixed:            {(router_rate-best_fixed_rate)*100:+.1f} pts")
    print(f"Best kNN (k={best_knn_k}) lift over best fixed:    {(best_knn_rate-best_fixed_rate)*100:+.1f} pts")
    print(f"RandomForest lift over best fixed:  {(rf_rate-best_fixed_rate)*100:+.1f} pts")

    best_overall = max(router_rate, best_knn_rate, rf_rate)
    verdict = "SIGNAL FOUND" if best_overall > best_fixed_rate + 0.03 else "NO RELIABLE SIGNAL"
    print(f"\nGate verdict: {verdict}")


if __name__ == "__main__":
    main()
