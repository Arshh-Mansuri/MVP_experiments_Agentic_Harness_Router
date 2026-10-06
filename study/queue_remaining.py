"""Queue the 44 Terminal-Bench tasks that Phase 1 did not cover, so the study spans all 89 (PROBLEM_DEFINITION.md).

These tasks join the development pool: the 18 test tasks stay sealed and are not re-queued. Run with
study/run_phase1.sh study/phase2_queue.txt, which pins the harness versions.

usage: python3 study/queue_remaining.py [--reps 3] [--seed 20260929]
"""
import argparse, json, os, random, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "study"))
import select_tasks as sel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--seed", type=int, default=20260929)
    a = ap.parse_args()

    split = json.load(open(f"{ROOT}/study/phase1_tasks.json"))
    covered = set(split["dev"]) | set(split["test"])
    rest = sorted(set(sel.all_tasks()) - covered)
    queue = [f"{t} {h} {r}" for t in rest for h in sel.HARNESSES for r in range(1, a.reps + 1)]
    random.Random(a.seed).shuffle(queue)

    json.dump({"seed": a.seed, "reps": a.reps, "harnesses": sel.HARNESSES, "tasks": rest},
              open(f"{ROOT}/study/phase2_tasks.json", "w"), indent=1)
    open(f"{ROOT}/study/phase2_queue.txt", "w").write("\n".join(queue) + "\n")
    runs = len(queue)
    print(f"{len(rest)} remaining tasks x {len(sel.HARNESSES)} harnesses x {a.reps} repeats = {runs} runs")
    print(f"Phase 1 averaged ${8.42 / 453:.3f} per run, so expect roughly ${runs * 8.42 / 453:.0f} "
          f"and {runs * 2.9 / 81:.0f} hours of wall-clock at PARALLEL=3")
    print("wrote study/phase2_queue.txt and study/phase2_tasks.json")


if __name__ == "__main__":
    main()
