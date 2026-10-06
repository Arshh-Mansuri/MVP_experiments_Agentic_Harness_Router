"""Task features for RQ1 analysis and the rule-based routers.

From task.toml: difficulty, category, tags, expert/junior time estimates, agent timeout, memory.
From instruction.md: keyword flags (regex), e.g. image, interactive, server, build, git, database, crypto, ML.

usage:
  python3 study/task_features.py            write study/task_features.csv and fit a shallow decision tree on the
                                            development tasks (which harness is best; do harnesses disagree)
  python3 study/task_features.py --unseal   include the test tasks in the tree (logged)
"""
import argparse, csv, datetime, glob, json, os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TASK_ROOT = os.path.expanduser("~/.cache/harbor/tasks/packages/terminal-bench")
OUT = os.path.join(ROOT, "study", "task_features.csv")

KEYWORDS = {
    "kw_image": r"\.(png|jpe?g|gif)\b|\bimage\b|screenshot",
    "kw_interactive": r"interactive|\bvim\b|\btmux\b|\brepl\b|curses|keystroke|terminal (ui|emulator)|headless",
    "kw_server": r"\bserver\b|\bport \d+|\bhttp\b|daemon|\blisten|\bservice\b|grpc|webserver",
    "kw_build": r"\bcompile|\bbuild\b|\bmake\b|cmake|\bgcc\b|cargo|makefile|\binstall\b",
    "kw_git": r"\bgit\b|commit|branch|repository",
    "kw_database": r"sqlite|database|\bsql\b|\bwal\b|postgres",
    "kw_crypto": r"crypt|\bhash\b|cipher|\b7z\b|password|secret",
    "kw_ml": r"torch|\bmodel\b|train|neural|dataset|huggingface|tokens?\b",
    "kw_long": r"hours?\b|long[- ]running|background|minutes",
    "kw_python": r"python|\.py\b|pip\b|numpy|pandas",
    "kw_c": r"\bc\b|\.c\b|\bc\+\+|\.cpp\b|\bgcc\b|clang",
    "kw_rust": r"\brust\b|cargo",
    "kw_docs": r"\.pdf\b|\.csv\b|\.json\b|document|report",
    "kw_math": r"probabilit|distribution|statistic|sampl|optimi[sz]",
}


def _field(text, key):
    m = re.search(rf"^{key}\s*=\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else None


def task_files(task):
    toml = sorted(glob.glob(f"{TASK_ROOT}/{task}/*/task.toml"))
    instr = sorted(glob.glob(f"{TASK_ROOT}/{task}/*/instruction.md"))
    return (toml[0] if toml else None), (instr[0] if instr else None)


def features(task):
    toml_path, instr_path = task_files(task)
    toml = open(toml_path).read() if toml_path else ""
    instr = open(instr_path).read() if instr_path else ""
    agent = re.search(r"\[agent\][^\[]*?timeout_sec\s*=\s*([\d.]+)", toml, re.S)
    tags = re.findall(r'"([^"]+)"', _field(toml, "tags") or "")
    f = {
        "task": task,
        "difficulty": (_field(toml, "difficulty") or "unknown").strip('"'),
        "category": (_field(toml, "category") or "unknown").strip('"'),
        "tags": ";".join(tags),
        "expert_min": float(_field(toml, "expert_time_estimate_min") or 0),
        "junior_min": float(_field(toml, "junior_time_estimate_min") or 0),
        "agent_timeout_sec": float(agent.group(1)) if agent else 0.0,
        "memory_mb": float(_field(toml, "memory_mb") or 0),
        "instruction_chars": len(instr),
    }
    low = instr.lower()
    for k, pat in KEYWORDS.items():
        f[k] = int(bool(re.search(pat, low)))
    return f, instr


def one_hot(rows, cats=("difficulty", "category")):
    """Numeric feature matrix (list of dicts) for sklearn: one-hot difficulty/category/tags + numeric + keywords."""
    vocab = {c: sorted({r[c] for r in rows}) for c in cats}
    tagv = sorted({t for r in rows for t in r["tags"].split(";") if t})
    out = []
    for r in rows:
        x = {f"{c}={v}": int(r[c] == v) for c in cats for v in vocab[c]}
        x.update({f"tag={t}": int(t in r["tags"].split(";")) for t in tagv})
        x.update({k: r[k] for k in ("expert_min", "junior_min", "agent_timeout_sec", "memory_mb", "instruction_chars")})
        x.update({k: r[k] for k in KEYWORDS})
        out.append(x)
    return out


def tree_analysis(tasks, cells, depth=2):
    sys.path.insert(0, os.path.join(ROOT, "study"))
    import analyze_phase1 as an
    from sklearn.tree import DecisionTreeClassifier, export_text
    from sklearn.model_selection import LeaveOneOut, cross_val_predict

    rows = [features(t)[0] for t in tasks]
    X_dicts = one_hot(rows)
    names = list(X_dicts[0])
    X = [[d[n] for n in names] for d in X_dicts]
    best = [an.stable_pick(cells, t) for t in tasks]
    spread = [max(an.cell(cells, t, h)["pass"] for h in an.HARNESSES) -
              min(an.cell(cells, t, h)["pass"] for h in an.HARNESSES) for t in tasks]
    disagree = [int(s >= 2 / 3 - 1e-9) for s in spread]

    for label, y in (("best harness (stable oracle)", best), ("harnesses disagree (pass-rate spread >= 2/3)", disagree)):
        clf = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=3, random_state=0).fit(X, y)
        pred = cross_val_predict(DecisionTreeClassifier(max_depth=depth, min_samples_leaf=3, random_state=0), X, y,
                                 cv=LeaveOneOut())
        acc = sum(p == t for p, t in zip(pred, y)) / len(y)
        maj = max(set(y), key=y.count)
        base = y.count(maj) / len(y)
        print(f"\n== Decision tree: {label} ({len(y)} tasks)")
        print(f"leave-one-out accuracy {acc:.0%} vs always '{maj}' {base:.0%}")
        print(export_text(clf, feature_names=names))
    print(f"tasks where harnesses disagree: {sum(disagree)}/{len(disagree)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unseal", action="store_true", help="include test tasks in the tree (logged)")
    a = ap.parse_args()
    split = json.load(open(os.path.join(ROOT, "study", "phase1_tasks.json")))
    all_tasks = split["dev"] + split["test"]
    rows = [features(t)[0] for t in all_tasks]
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {os.path.relpath(OUT, ROOT)}: {len(rows)} tasks (features only, no results)")

    sys.path.insert(0, os.path.join(ROOT, "study"))
    import analyze_phase1 as an
    cells, _, _ = an.load_runs("jobs/p1-*")
    tasks = split["dev"]
    if a.unseal:
        with open(os.path.join(ROOT, "study", "test_unseal_log.jsonl"), "a") as f:
            f.write(json.dumps({"ts": datetime.datetime.now().isoformat(timespec="seconds"), "by": "task_features.py"}) + "\n")
        tasks = all_tasks
    tasks = [t for t in tasks if all(cells[t][h] for h in an.HARNESSES)]
    tree_analysis(tasks, cells)


if __name__ == "__main__":
    main()
