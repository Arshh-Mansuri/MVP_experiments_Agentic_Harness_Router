"""How hard a Terminal-Bench task is likely to be for Luna, gauged from the Qwen3-Coder 89-task workbook.

Qwen ran every Terminal-Bench task once on four harnesses, so it gives a difficulty reading for tasks Luna has never
run. Two readings per task:

  tier    from Qwen's results alone, no fitting, over the harnesses whose trial produced a result:
            easy        Qwen passed with at least 3 in 4 of them
            medium      Qwen passed with at least one
            hard        Qwen passed with none, but averaged at least half the tests
            very hard   Qwen passed with none and averaged under half the tests
            unknown     fewer than two harnesses produced a result
          A crashed trial (ERROR) is no evidence about the task: setup failures such as qemu-alpine-ssh never started
          the agent. The exception is an ERROR that still earned a reward (kv-store-grpc on pi passed 7/7 tests),
          which counts as a pass, the same rule Luna's runs are scored by.
          On the 44 tasks Luna has scored, Luna's pass rate falls with every tier: 94%, 56%, 47%, 36%.
  score   0 = easiest, 1 = hardest: the mean of Qwen's pass share, Qwen's partial credit and Terminal-Bench's own
          easy/medium/hard label, equally weighted (nothing fitted). Ranks Luna's tasks a little better than the tier
          (Spearman 0.53 against 0.46) and separates tasks within a tier.

Plus a size estimate: Qwen's token use tracks Luna's cost closely (Spearman 0.74), so expected_cost_per_run scales
Qwen's median tokens by Luna's dollars per Qwen token over the scored tasks. Treat it as a budget figure; it was
off by 28% on a split-half check.

This is a prior from a different model's single runs. It says how hard a task is, not which harness to use
(study/qwen_deep.py: Qwen cannot pick the harness).

  python3 router/difficulty.py --build        rebuild router/difficulty_table.json from the workbook and Luna runs
  python3 router/difficulty.py fix-git        gauge one task
  python3 router/difficulty.py --list         all 89 tasks, hardest first
"""
import argparse
import datetime
import hashlib
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TABLE = os.path.join(HERE, "difficulty_table.json")
TIERS = ("easy", "medium", "hard", "very hard", "unknown")
LABEL = {"easy": 0.0, "medium": 0.5, "hard": 1.0}
SETUP_FAILURE = "Setup exit 100"  # the harness could not install in the task's container; the agent never started


def tier_of(passes, valid, partial):
    if valid < 2:
        return "unknown"
    if passes / valid >= 0.75:
        return "easy"
    if passes >= 1:
        return "medium"
    return "hard" if partial >= 0.5 else "very hard"


def build():
    sys.path.insert(0, os.path.join(ROOT, "study"))
    import qwen_deep as qd
    q, L = qd.load_qwen(), qd.load_luna()
    tasks = sorted({t for t, _ in q})
    luna = {}
    for t in tasks:
        rs = [qd.mean(L[(t, h)]["rewards"]) for h in qd.OURS if L[(t, h)]["rewards"]]
        if rs:
            luna[t] = st.mean(rs)
    luna_cost = {t: st.mean([qd.mean(L[(t, h)]["cost"]) for h in qd.OURS if L[(t, h)]["cost"]]) for t in luna}
    def toks(t):
        xs = [q[(t, h)]["tokens"] for h in qd.OURS if q[(t, h)]["tokens"]]
        return st.median(xs) if xs else None
    qtok = {t: toks(t) for t in tasks}
    per_token = sum(luna_cost[t] for t in luna if qtok[t]) / sum(qtok[t] for t in luna if qtok[t])

    rows = {}
    for t in tasks:
        ok = [h for h in qd.ALL4 if q[(t, h)]["status"] != "ERROR" or (q[(t, h)]["reward"] or 0) > 0]
        passes = sum((q[(t, h)]["reward"] or 0) > 0 for h in ok)
        partial = st.mean(q[(t, h)]["frac"] for h in ok) if ok else 0.0
        label = q[(t, qd.DEFAULT)]["difficulty"]
        share = passes / len(ok) if ok else 0.0
        score = 1 - (share + partial + (1 - LABEL[label])) / 3
        rows[t] = {"tier": tier_of(passes, len(ok), partial), "score": round(score, 3),
                   "qwen_passes": passes, "qwen_harnesses_with_result": len(ok),
                   "qwen_crashed": [h for h in qd.ALL4 if h not in ok],
                   "qwen_setup_failed": [h for h in qd.ALL4 if q[(t, h)]["error_summary"] == SETUP_FAILURE],
                   "qwen_partial_credit": round(partial, 3), "tb_label": label,
                   "category": q[(t, qd.DEFAULT)]["category"],
                   "expected_cost_per_run": round(per_token * qtok[t], 4) if qtok[t] else None,
                   "luna_pass": round(luna[t], 3) if t in luna else None}

    calib = {}
    for tr in TIERS:
        xs = [luna[t] for t in luna if rows[t]["tier"] == tr]
        calib[tr] = {"luna_tasks": len(xs), "luna_pass": round(st.mean(xs), 3) if xs else None,
                     "all_tasks": sum(r["tier"] == tr for r in rows.values())}
    src = hashlib.sha256(open(qd.XLSX, "rb").read()).hexdigest()[:16]
    out = {"built": datetime.datetime.now().isoformat(timespec="seconds"), "source_workbook_sha256": src,
           "luna_tasks_used_for_calibration": len(luna), "dollars_per_qwen_token": per_token,
           "tiers": calib, "tasks": rows}
    with open(TABLE, "w") as f:
        json.dump(out, f, indent=1)
    return out


def load():
    with open(TABLE) as f:
        return json.load(f)


def gauge(task, table=None):
    """Difficulty reading for a task, or None if Qwen never ran it (e.g. a task outside Terminal-Bench).

    expected_luna_pass is the tier's pass rate over the Luna tasks used for calibration; for a task that is itself
    one of those, luna_pass is its real result and the tier figure is partly fitted to it."""
    t = table or load()
    r = t["tasks"].get(task)
    if r is None:
        return None
    return {**r, "expected_luna_pass": t["tiers"][r["tier"]]["luna_pass"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task", nargs="?")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.build:
        t = build()
        print(f"wrote {os.path.relpath(TABLE, ROOT)}: {len(t['tasks'])} tasks, calibrated on "
              f"{t['luna_tasks_used_for_calibration']} Luna tasks")
        for tr, c in t["tiers"].items():
            lp = f"Luna passes {100 * c['luna_pass']:.0f}% over the {c['luna_tasks']} it has run" \
                if c["luna_pass"] is not None else "Luna has run none"
            print(f"  {tr:10} {c['all_tasks']:2} tasks; {lp}")
    t = load()
    if a.task:
        g = gauge(a.task, t)
        if g is None:
            sys.exit(f"{a.task}: not in the Qwen workbook, no difficulty reading")
        exp = g["expected_luna_pass"]
        exp = f"expect Luna to pass about {100 * exp:.0f}%" if exp is not None else "no Luna calibration for this tier"
        seen = f", Luna actually {100 * g['luna_pass']:.0f}%" if g["luna_pass"] is not None else ", no scored Luna runs"
        print(f"{a.task}: {g['tier']} (score {g['score']:.2f}/1) - {exp}{seen}")
        print(f"  Qwen passed {g['qwen_passes']}/{g['qwen_harnesses_with_result']} harnesses that produced a result, "
              f"{100 * g['qwen_partial_credit']:.0f}% of tests on average; Terminal-Bench label {g['tb_label']}; "
              f"category {g['category']}")
        if g["qwen_crashed"]:
            print(f"  WARNING Qwen crashed on {', '.join(g['qwen_crashed'])} - check it can even start there")
        c = g["expected_cost_per_run"]
        print(f"  expected Luna cost " + (f"about ${c:.3f} per run" if c is not None else "unknown (no Qwen token data)"))
    if a.list:
        rows = sorted(t["tasks"].items(), key=lambda kv: -kv[1]["score"])
        print(f"{'task':34}{'tier':11}{'score':>6}{'Qwen':>6}{'tests':>7}{'label':>8}{'$/run':>8}{'Luna':>7}  crashed")
        for name, r in rows:
            lp = f"{100 * r['luna_pass']:.0f}%" if r["luna_pass"] is not None else "-"
            c = f"{r['expected_cost_per_run']:8.3f}" if r["expected_cost_per_run"] is not None else "       -"
            print(f"{name:34}{r['tier']:11}{r['score']:6.2f}{r['qwen_passes']:>4}/{r['qwen_harnesses_with_result']}"
                  f"{100 * r['qwen_partial_credit']:6.0f}%{r['tb_label']:>8}{c}{lp:>7}  {', '.join(r['qwen_crashed'])}")


if __name__ == "__main__":
    main()
