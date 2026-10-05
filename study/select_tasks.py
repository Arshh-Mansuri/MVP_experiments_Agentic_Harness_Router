"""Select Phase 1 tasks and the development / test split (see STUDY_PLAN.md).

Test tasks are drawn only from tasks with no earlier runs in jobs/, so their outcomes are unseen.
Development tasks are the previously studied tasks, topped up with unseen ones.

usage: python study/select_tasks.py [--n 45] [--test-frac 0.4] [--reps 3] [--seed 20260929]
"""
import argparse, glob, json, os, random

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TASK_CACHE = os.path.expanduser("~/.cache/harbor/tasks")
HARNESSES = ["terminus-2", "mini-swe-agent", "pi"]


def all_tasks():
    return sorted({os.path.basename(os.path.dirname(p)) for p in glob.glob(f"{TASK_CACHE}/*/*/instruction.md")})


def seen_tasks():
    seen = set()
    for f in glob.glob(f"{ROOT}/jobs/*/*__*/result.json"):
        seen.add(json.load(open(f))["trial_name"].rsplit("__", 1)[0])
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=45)
    ap.add_argument("--test-frac", type=float, default=0.4)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--seed", type=int, default=20260929)
    a = ap.parse_args()
    rng = random.Random(a.seed)

    tasks = all_tasks()
    seen = sorted(set(tasks) & seen_tasks())
    unseen = sorted(set(tasks) - set(seen))
    n_test = round(a.n * a.test_frac)
    n_dev = a.n - n_test
    if n_test > len(unseen):
        raise SystemExit(f"only {len(unseen)} unseen tasks, need {n_test} for the test set")

    test = sorted(rng.sample(unseen, n_test))
    rest = sorted(set(unseen) - set(test))
    dev = sorted(rng.sample(seen, min(n_dev, len(seen))))
    dev += sorted(rng.sample(rest, n_dev - len(dev)))

    out = {"seed": a.seed, "reps": a.reps, "harnesses": HARNESSES, "dev": sorted(dev), "test": test}
    json.dump(out, open(os.path.join(ROOT, "study", "phase1_tasks.json"), "w"), indent=1)

    queue = [f"{t} {h} {r}" for t in dev + test for h in HARNESSES for r in range(1, a.reps + 1)]
    rng.shuffle(queue)
    open(os.path.join(ROOT, "study", "phase1_queue.txt"), "w").write("\n".join(queue) + "\n")

    print(f"{len(tasks)} tasks available, {len(seen)} previously run, {len(unseen)} unseen")
    print(f"dev {len(dev)} ({len(set(dev) & set(seen))} previously run) / test {len(test)} (all unseen)")
    print(f"queue: {len(queue)} runs -> study/phase1_queue.txt")


if __name__ == "__main__":
    main()
