"""Offline replay: run the watchdog over finished trajectories and score it against the known outcomes."""
import glob, json, os, sys
from concurrent.futures import ThreadPoolExecutor
import watchdog as W

HELD_OUT = {"multi-source-data-merger", "feal-linear-cryptanalysis", "protein-assembly", "cancel-async-tasks", "code-from-image",
            "torch-pipeline-parallelism", "crack-7z-hash", "path-tracing", "chess-best-move", "schemelike-metacircular-eval"}
ROOT = os.path.join(os.path.dirname(__file__), "..", "jobs")


def task_text(task):
    p = glob.glob(os.path.expanduser(f"~/.cache/harbor/tasks/packages/terminal-bench/{task}/*/instruction.md"))
    return open(p[0]).read().strip() if p else None


def one(f):
    r = json.load(open(f))
    task = r["trial_name"].rsplit("__", 1)[0]
    h = r["agent_info"]["name"]
    rew = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    tt = task_text(task)
    if task in HELD_OUT or rew is None or tt is None or h not in ("terminus-2", "mini-swe-agent", "pi"):
        return None
    steps = W.load_steps(os.path.join(os.path.dirname(f), "agent"), h)
    if not steps:
        return None
    det = W.Detector(tt, judge=True)
    for k in range(1, len(steps) + 1):
        if det.update(steps[:k]):
            break
    tot_t = sum(s.in_tok + s.out_tok for s in steps); tot_c = sum(s.cost for s in steps)
    fl = det.flag
    return {"task": task, "harness": h, "reward": rew, "steps": len(steps), "tok": tot_t, "cost": tot_c,
            "flag_step": fl and fl["steps"], "flag_tok": fl and fl["tokens"], "flag_cost": fl and fl["cost"], "why": fl and fl["why"],
            "judge_tok": det.judge_tokens, "judge_cost": det.judge_cost}


if __name__ == "__main__":
    files = [f for f in glob.glob(ROOT + "/*/*__*/result.json") if "/livetest-" not in f]
    with ThreadPoolExecutor(6) as ex:
        rows = [x for x in ex.map(one, files) if x]
    json.dump(rows, open(os.path.join(os.path.dirname(__file__), "replay_train.json"), "w"), indent=1)
    fails = [r for r in rows if r["reward"] < 1]; passes = [r for r in rows if r["reward"] >= 1]
    tp = [r for r in fails if r["flag_step"]]; fp = [r for r in passes if r["flag_step"]]
    print(f"runs={len(rows)} fails={len(fails)} passes={len(passes)}")
    print(f"fails flagged (caught) {len(tp)}/{len(fails)};  passes flagged (wrongly killed) {len(fp)}/{len(passes)}")
    sv = sum(r["tok"] - r["flag_tok"] for r in tp); svc = sum(r["cost"] - r["flag_cost"] for r in tp)
    print(f"tokens saved on caught fails: {sv:,} (${svc:.4f});  total tokens in all fails: {sum(r['tok'] for r in fails):,}")
    print(f"tokens spent on wrongly-killed passes (would be wasted): {sum(r['flag_tok'] for r in fp):,}")
    print(f"judge overhead: {sum(r['judge_tok'] for r in rows):,} tokens ${sum(r['judge_cost'] for r in rows):.4f}")
    for r in sorted(rows, key=lambda r: (r['reward'], r['task'])):
        if r["flag_step"] or r["reward"] < 1:
            print(f"  {r['task'][:24]:24} {r['harness'][:9]:9} rew={r['reward']} steps={r['steps']:3} flag@{r['flag_step']} ({r['why']}) saved={(r['tok']-r['flag_tok']) if r['flag_step'] else 0}")
