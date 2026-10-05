"""Export all iLab experiment data to one Excel workbook plus a CSV of the Phase 1 runs.

Test-set rewards stay hidden ("sealed") unless --unseal is passed, which is logged to
study/test_unseal_log.jsonl in the same way as analyze_phase1.py.

Usage:
  python3 study/export_experiments.py            # dev results visible, test rewards sealed
  python3 study/export_experiments.py --unseal   # everything visible (logged)
"""
import argparse
import collections
import csv
import datetime
import glob
import hashlib
import json
import os
import re
import statistics as st

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESSES = ["terminus-2", "mini-swe-agent", "pi"]
MODEL = "openai/gpt-5.6-luna"
SET_ASIDE_DIR = "jobs_set_aside"
OUT_XLSX = os.path.join(ROOT, "study", "ilab_experiments.xlsx")
OUT_CSV = os.path.join(ROOT, "study", "ilab_phase1_runs.csv")
SEALED = "sealed"
PASS_GAIN = 5.0


def load_json(path):
    with open(path) as f:
        return json.load(f)


def minutes(block):
    block = block or {}
    a, b = block.get("started_at"), block.get("finished_at")
    if not a or not b:
        return None
    t0 = datetime.datetime.fromisoformat(a.replace("Z", "+00:00"))
    t1 = datetime.datetime.fromisoformat(b.replace("Z", "+00:00"))
    return round((t1 - t0).total_seconds() / 60, 2)


def parse_p1_job(job):
    """p1-<harness>-<task>-r<rep>[-retryN] -> (harness, task, rep, attempt)."""
    m = re.match(r"^p1-(.+)-r(\d+)(?:-retry(\d+))?$", job)
    if not m:
        return None
    rest, rep, retry = m.group(1), int(m.group(2)), int(m.group(3) or 0)
    for h in HARNESSES:
        if rest.startswith(h + "-"):
            return h, rest[len(h) + 1:], rep, retry
    return None


def run_row(result_path):
    r = load_json(result_path)
    a = r.get("agent_info") or {}
    ar = r.get("agent_result") or {}
    exc = r.get("exception_info") or {}
    reward = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    msg_lines = (exc.get("exception_message") or "").strip().splitlines()
    return {
        "trial": r.get("trial_name"),
        "task": (r.get("task_id") or {}).get("name") or (r.get("trial_name") or "").rsplit("__", 1)[0],
        "agent": a.get("name"),
        "agent_version": a.get("version"),
        "model": (a.get("model_info") or {}).get("name"),
        "reward": reward,
        "error_type": exc.get("exception_type"),
        "error_message": msg_lines[0][:300] if msg_lines else None,
        "input_tokens": ar.get("n_input_tokens"),
        "cached_tokens": ar.get("n_cache_tokens"),
        "output_tokens": ar.get("n_output_tokens"),
        "cost_usd": ar.get("cost_usd"),
        "started_at": r.get("started_at"),
        "finished_at": r.get("finished_at"),
        "total_min": minutes(r),
        "env_setup_min": minutes(r.get("environment_setup")),
        "agent_setup_min": minutes(r.get("agent_setup")),
        "agent_run_min": minutes(r.get("agent_execution")),
        "verifier_min": minutes(r.get("verifier")),
    }


def collect_phase1(split, unsealed):
    dev, test = set(split["dev"]), set(split["test"])
    paths = [(p, "") for p in glob.glob(f"{ROOT}/jobs/p1-*/*__*/result.json")]
    paths += [(p, os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(p)))))
              for p in glob.glob(f"{ROOT}/{SET_ASIDE_DIR}/*/p1-*/*__*/result.json")]
    rows = []
    for path, aside in paths:
        job = os.path.basename(os.path.dirname(os.path.dirname(path)))
        parsed = parse_p1_job(job)
        if not parsed:
            continue
        harness, task, rep, attempt = parsed
        row = run_row(path)
        split_name = "dev" if task in dev else "test" if task in test else "other"
        counted, why = True, ""
        if row["model"] != MODEL:
            counted, why = False, f"executor was {row['model']}, not Luna"
        elif aside:
            counted, why = False, f"set aside ({aside})"
        elif row["reward"] is None:
            counted, why = False, "no reward (run broke before grading)"
        elif task == "qemu-startup":
            counted, why = False, "qemu-startup dropped from scoring (pi/mini-swe-agent cannot install)"
        sealed = split_name == "test" and not unsealed
        rows.append({
            "job": job, "split": split_name, "task": task, "harness": harness, "repeat": rep,
            "attempt": "first" if attempt == 0 else f"retry {attempt}",
            **{k: v for k, v in row.items() if k not in ("task", "agent")},
            "reward": SEALED if sealed and row["reward"] is not None else row["reward"],
            "counted_in_scoring": "yes" if counted else "no",
            "not_counted_reason": why,
        })
    rows.sort(key=lambda x: (x["split"], x["task"], x["harness"], x["repeat"], x["attempt"]))
    return rows


def task_harness_table(rows, unsealed):
    cells = collections.defaultdict(list)
    for r in rows:
        if r["counted_in_scoring"] == "yes" and (r["split"] == "dev" or unsealed):
            cells[(r["split"], r["task"], r["harness"])].append(r)
    out = []
    for (sp, task, h), rs in sorted(cells.items()):
        out.append({
            "split": sp, "task": task, "harness": h, "valid_runs": len(rs),
            "passes": sum(r["reward"] for r in rs),
            "pass_rate": round(st.mean(r["reward"] for r in rs), 3),
            "avg_cost_usd": round(st.mean(r["cost_usd"] or 0 for r in rs), 4),
            "avg_total_min": round(st.mean(r["total_min"] or 0 for r in rs), 1),
            "same_result_every_repeat": "yes" if len({r["reward"] for r in rs}) == 1 else "no",
        })
    return out


def strategy_rows(unsealed):
    out = []
    for sp in (["dev", "test"] if unsealed else ["dev"]):
        path = f"{ROOT}/study/phase1_results_{sp}.json"
        if not os.path.exists(path):
            continue
        res = load_json(path)
        base = res["results"][f"always {res['baseline']}"]["pass_rate"]
        for name, s in res["results"].items():
            out.append({
                "split": sp, "strategy": name, "baseline": res["baseline"], "tasks_scored": len(res["tasks"]),
                "pass_rate_pct": round(s["pass_rate"], 1), "passes": round(s["passes"], 2),
                "total_cost_usd": round(s["cost"], 4), "cost_per_pass_usd": round(s["cost_per_pass"], 4),
                "diff_vs_baseline_pts": round(s["diff_mean"], 1),
                "ci95_low": round(s["ci"][0], 1), "ci95_high": round(s["ci"][1], 1),
                "cost_per_pass_change_pct": round(100 * s["cost_per_pass_change"], 1),
                "meets_pass_criterion": s["meets_pass_criterion"], "meets_cost_criterion": s["meets_cost_criterion"],
            })
        if sp == "dev" and "perfect picking" in res["results"]:
            gap = res["results"]["perfect picking"]["pass_rate"] - base
            out.append({"split": sp, "strategy": "GO / NO-GO",
                        "baseline": res["baseline"],
                        "diff_vs_baseline_pts": round(gap, 1),
                        "meets_pass_criterion": "GO" if gap >= PASS_GAIN else "NO-GO"})
    return out


def pick_rows():
    path = f"{ROOT}/router/picks_profiles.json"
    if not os.path.exists(path):
        return []
    rows = []
    for r in load_json(path):
        tok = r.get("tokens")
        rows.append({
            "router": r.get("router"), "task": r.get("task"), "repeat": r.get("rep"),
            "picked_harness": r.get("harness"), "underlying_model": r.get("underlying_model"),
            "reason": r.get("reason"),
            "tokens": json.dumps(tok) if isinstance(tok, dict) else tok,
            "cost_usd": r.get("cost"), "seconds": r.get("seconds"),
            "profiles_sha256": r.get("profiles_sha256"),
        })
    return sorted(rows, key=lambda x: (x["router"] or "", x["task"] or "", x["repeat"] or 0))


def failure_rows(rows):
    counts = collections.Counter()
    attempts = collections.Counter()
    for r in rows:
        attempts[r["harness"]] += 1
        if r["reward"] is None:
            counts[(r["harness"], r["error_type"] or "no reward")] += 1
    out = [{"harness": h, "error_type": e, "attempts_failed": n,
            "share_of_harness_attempts_pct": round(100 * n / attempts[h], 1)}
           for (h, e), n in sorted(counts.items())]
    for h in HARNESSES:
        broke = sum(n for (hh, _), n in counts.items() if hh == h)
        out.append({"harness": h, "error_type": "TOTAL (any error)", "attempts_failed": broke,
                    "share_of_harness_attempts_pct": round(100 * broke / attempts[h], 1) if attempts[h] else None})
    return out


def older_rows():
    rows = []
    for path in glob.glob(f"{ROOT}/jobs/*/*__*/result.json"):
        job = os.path.basename(os.path.dirname(os.path.dirname(path)))
        if job.startswith("p1-"):
            continue
        try:
            row = run_row(path)
        except (json.JSONDecodeError, OSError):
            continue
        rows.append({"job": job, "status": "pre-study (not part of Phase 1)", **row})
    return sorted(rows, key=lambda x: (x["started_at"] or "", x["job"]))


def notes_rows(split, rows, unsealed):
    prof_path = f"{ROOT}/router/harness_profiles.json"
    prof = load_json(prof_path) if os.path.exists(prof_path) else {}
    luna = [r for r in rows if r["model"] == MODEL]
    return [
        ("Generated", datetime.datetime.now().isoformat(timespec="seconds")),
        ("Test set", "UNSEALED (logged)" if unsealed else "SEALED: test-set rewards are hidden"),
        ("Executor model", f"openrouter/{MODEL} (fixed for every run)"),
        ("Harnesses compared", ", ".join(HARNESSES)),
        ("Design", f"{len(split['dev'])} dev + {len(split['test'])} test tasks x {len(HARNESSES)} harnesses x "
                   f"{split['reps']} repeats = {(len(split['dev']) + len(split['test'])) * len(HARNESSES) * split['reps']} slots"),
        ("Task selection seed", split.get("seed")),
        ("Phase 1 attempts in this file", f"{len(rows)} ({len(luna)} with Luna)"),
        ("Retries", "A slot that broke before grading is retried up to 2 more times; broken attempts are not scored."),
        ("Scoring", "Pass rate = mean reward over valid repeats per task, then averaged over tasks. "
                    "Baseline = best single harness on the dev set. 95% CIs from 10,000 paired bootstrap resamples over tasks."),
        ("Success criteria", "Router beats baseline by >= 5 points with CI above 0, or cuts cost per pass by >= 30% "
                             "while staying within 3 points."),
        ("Routers", "jev = Jev Router picks using Luna's frozen harness profiles; luna-profiles = Luna picks using the same "
                    "profiles; luna-cards = Luna picks using the earlier hand-written harness cards."),
        ("Harness profiles", f"frozen={prof.get('frozen')}, sha256={prof.get('profiles_sha256')}"),
        ("Decision: qemu-startup", "Dropped from scoring (decided before unsealing): pi and mini-swe-agent fail their own "
                                   "install step in that task's container; only terminus-2 runs."),
        ("Decision: sleep-affected runs", "3 runs in progress while the laptop slept (5 Oct, 00:46-09:49) were set aside "
                                          "in jobs_set_aside/ and rerun. They are listed but not counted."),
        ("Withdrawn", "The earlier Jev-as-picker study (29 Sep) was withdrawn and is not in this file."),
        ("Sheets", "Phase1 runs: one row per attempt | Task x harness: per-cell pass rates | Strategies: analysis output | "
                   "Router picks: every pick with reason | Failures: broken attempts by harness | Older runs: pre-study jobs"),
        ("Column: reward", "1 = task solved, 0 = not solved, blank = run broke before grading, 'sealed' = hidden test result"),
        ("Column: times", "Minutes. env_setup = container start, agent_setup = harness install, agent_run = the agent "
                          "working, verifier = grading."),
    ]


HEADER_FILL = PatternFill("solid", fgColor="1F3D36")
HEADER_FONT = Font(bold=True, color="FFFFFF")


def add_sheet(wb, title, rows, widths=None):
    ws = wb.create_sheet(title)
    if not rows:
        ws.append(["(no data yet)"])
        return ws
    cols = list(dict.fromkeys(k for r in rows for k in r))
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c) for c in cols])
    for i, c in enumerate(cols, 1):
        cell = ws.cell(row=1, column=i)
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        width = (widths or {}).get(c) or min(60, max(len(c), *(len(str(r.get(c) or "")) for r in rows[:300])) + 2)
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unseal", action="store_true", help="show test-set rewards (logged)")
    a = ap.parse_args()
    split = load_json(f"{ROOT}/study/phase1_tasks.json")

    if a.unseal:
        prof = load_json(f"{ROOT}/router/harness_profiles.json")
        if not prof.get("frozen"):
            raise SystemExit("harness profiles are not frozen")
        picks = f"{ROOT}/router/picks_profiles.json"
        rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "by": "export_experiments.py",
               "profiles_sha256": prof.get("profiles_sha256"),
               "picks_sha256": hashlib.sha256(open(picks, "rb").read()).hexdigest()[:16] if os.path.exists(picks) else None}
        with open(f"{ROOT}/study/test_unseal_log.jsonl", "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"TEST SET UNSEALED (logged): {rec}")

    runs = collect_phase1(split, a.unseal)

    wb = Workbook()
    ws = wb.active
    ws.title = "Notes"
    for k, v in notes_rows(split, runs, a.unseal):
        ws.append([k, v])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
        ws.cell(row=ws.max_row, column=2).alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 110

    add_sheet(wb, "Phase1 runs", runs, {"error_message": 60})
    add_sheet(wb, "Task x harness", task_harness_table(runs, a.unseal))
    add_sheet(wb, "Strategies", strategy_rows(a.unseal))
    add_sheet(wb, "Router picks", pick_rows(), {"reason": 80})
    add_sheet(wb, "Failures", failure_rows(runs))
    add_sheet(wb, "Older runs", older_rows(), {"error_message": 60})
    wb.save(OUT_XLSX)

    if runs:
        with open(OUT_CSV, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in runs for k in r)))
            w.writeheader()
            w.writerows(runs)

    print(f"wrote {os.path.relpath(OUT_XLSX, ROOT)} and {os.path.relpath(OUT_CSV, ROOT)}: "
          f"{len(runs)} Phase 1 attempts ({'test unsealed' if a.unseal else 'test rewards sealed'})")


if __name__ == "__main__":
    main()
