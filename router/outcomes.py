"""Ground-truth table: task -> harness -> list of rewards, from finished trials without infrastructure errors.

build() returns every task it finds and is unchanged for importers. Printing is what leaks, so the command line
shows development tasks only; the 18 sealed test tasks need --unseal, which is recorded in
study/test_unseal_log.jsonl. This guard exists because an unguarded summary printed the test set once already
(see PROJECT_LOG.md, 5 Oct).

usage: python3 router/outcomes.py [--split dev|test|all] [--unseal]
"""
import argparse, datetime, glob, json, os, collections, sys
H = ("terminus-2", "mini-swe-agent", "pi")
MODEL = "openai/gpt-5.6-luna"  # the study holds the executor model fixed; other models' runs are excluded
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def build(root="jobs"):
    t = collections.defaultdict(lambda: collections.defaultdict(list))
    for f in glob.glob(f"{root}/*/*__*/result.json"):
        if "/livetest-" in f or "/wdtest-" in f:
            continue
        r = json.load(open(f))
        h = (r.get("agent_info") or {}).get("name")
        model = ((r.get("agent_info") or {}).get("model_info") or {}).get("name")
        rew = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        if h in H and model == MODEL and rew is not None:
            t[r["trial_name"].rsplit("__", 1)[0]][h].append(rew)
    return t

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    ap.add_argument("--unseal", action="store_true", help="required to print test-task rewards (logged)")
    a = ap.parse_args()

    split = json.load(open(f"{ROOT}/study/phase1_tasks.json"))
    if a.split == "dev":
        allowed = set(split["dev"])
    else:
        if not a.unseal:
            sys.exit(f"--split {a.split} would print the sealed test tasks; rerun with --unseal")
        rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "by": "outcomes.py", "split": a.split}
        with open(f"{ROOT}/study/test_unseal_log.jsonl", "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"TEST SET UNSEALED (logged): {rec}\n")
        allowed = set(split["test"]) if a.split == "test" else set(split["dev"]) | set(split["test"])

    t = build(os.path.join(ROOT, "jobs"))
    shown = [k for k in sorted(t) if k in allowed]
    for task in shown:
        print(f"{task:28}", {h: (round(sum(v) / len(v), 2), len(v)) for h, v in t[task].items()})
    held = len(t) - len(shown)
    print(f"\n{len(shown)} {a.split} tasks shown; {held} task(s) in jobs/ not printed "
          f"(sealed test tasks or tasks outside the split)")
