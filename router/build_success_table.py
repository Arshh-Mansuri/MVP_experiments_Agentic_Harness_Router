"""Build the success table the table router puts in its prompt, then freeze it with a hash.

Table A: GPT-5.6-Luna Phase 1 results, development tasks only (test results are never read).
Table B: Qwen3-Coder 480B baseline on all 89 Terminal-Bench tasks (Qwen_89_Task_Comparison_2026-09-20.xlsx),
         one run per task and harness; a weak hint from a different model.

usage: python3 router/build_success_table.py
writes router/success_table.json, router/success_table.md and the table router's router/table_system_prompt.txt
"""
import datetime, glob, hashlib, json, os, re, statistics as st, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import profile_router as pr

MODEL = "openai/gpt-5.6-luna"
HARNESSES = pr.HARNESSES
QWEN_XLSX = os.path.join(ROOT, "Qwen_89_Task_Comparison_2026-09-20.xlsx")
QWEN_COLS = {"mini-SWE": "mini-swe-agent", "Terminus-2": "terminus-2", "OpenCode": "opencode", "pi": "pi"}
OUT_JSON = os.path.join(HERE, "success_table.json")
OUT_MD = os.path.join(HERE, "success_table.md")


def luna_dev_cells(dev):
    cells = {t: {h: [] for h in HARNESSES} for t in dev}
    for f in glob.glob(f"{ROOT}/jobs/p1-*/*__*/result.json"):
        task = os.path.basename(os.path.dirname(f)).rsplit("__", 1)[0]
        if task not in cells:
            continue
        r = json.load(open(f))
        a = r.get("agent_info") or {}
        if (a.get("model_info") or {}).get("name") != MODEL or a.get("name") not in HARNESSES:
            continue
        rew = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        if rew is None:
            continue
        cells[task][a["name"]].append((float(rew), (r.get("agent_result") or {}).get("cost_usd") or 0.0))
    return cells


def first_sentence(task):
    try:
        text = pr.task_text(task)
    except FileNotFoundError:
        return ""
    text = re.sub(r"\s+", " ", re.sub(r"[#*`>]", "", text)).strip()
    m = re.match(r"(.{20,200}?[.!?])(\s|$)", text)
    return (m.group(1) if m else text[:200]).strip()


def table_a(dev):
    rows = []
    for task, by_h in sorted(luna_dev_cells(dev).items()):
        stats = {}
        for h, xs in by_h.items():
            if xs:
                stats[h] = {"passes": int(sum(x[0] for x in xs)), "runs": len(xs),
                            "avg_cost": round(st.mean(x[1] for x in xs), 4)}
        rate = lambda h: stats[h]["passes"] / stats[h]["runs"]
        solved = [h for h in stats if stats[h]["passes"] > 0]
        if solved:
            best = max(solved, key=lambda h: (rate(h), -stats[h]["avg_cost"]))
            tied = [h for h in solved if rate(h) == rate(best)]
            note = "tie on pass rate; cheapest chosen" if len(tied) > 1 else ""
        else:
            best, note = "mini-swe-agent", "no harness solved it; default"
        rows.append({"task": task, "about": first_sentence(task), "results": stats, "best": best, "note": note})
    return rows


def table_b():
    from openpyxl import load_workbook
    wb = load_workbook(QWEN_XLSX, read_only=True, data_only=True)
    rows, header = [], None
    for r in wb["Results"].iter_rows(values_only=True):
        if r and r[0] == "Task":
            header = list(r)
            continue
        if not header or not r or not r[0]:
            if header and rows:
                break
            continue
        res = {}
        for col, h in QWEN_COLS.items():
            cell = r[header.index(col)]
            res[h] = str(cell).split("\n")[0].strip() if cell else "n/a"
        rows.append({"task": r[0], "results": res})
    return rows


def render_md(t):
    out = ["# Success table (frozen)", "",
           f"sha256 {t['table_sha256']}, built {t['built']}. Table A = Luna Phase 1 development tasks only.", "",
           "## Table A: GPT-5.6-Luna, 3 runs per harness (passes/runs, average cost per run)", "",
           "| task | " + " | ".join(HARNESSES) + " | best | note |", "|" + "---|" * (len(HARNESSES) + 3)]
    for r in t["table_a"]:
        cells = [f"{r['results'][h]['passes']}/{r['results'][h]['runs']} ${r['results'][h]['avg_cost']:.3f}"
                 if h in r["results"] else "-" for h in HARNESSES]
        out.append(f"| {r['task']} | " + " | ".join(cells) + f" | **{r['best']}** | {r['note']} |")
    out += ["", "## Table B: Qwen3-Coder 480B, 1 run per harness (weak hint; OpenCode not available to us)", "",
            "| task | mini-swe-agent | terminus-2 | pi | opencode |", "|---|---|---|---|---|"]
    for r in t["table_b"]:
        res = r["results"]
        out.append(f"| {r['task']} | {res['mini-swe-agent']} | {res['terminus-2']} | {res['pi']} | {res['opencode']} |")
    return "\n".join(out) + "\n"


def main():
    split = json.load(open(os.path.join(ROOT, "study", "phase1_tasks.json")))
    t = {"built": datetime.datetime.now().isoformat(timespec="seconds"),
         "sources": {"table_a": "jobs/p1-* (GPT-5.6-Luna), development tasks only",
                     "table_b": os.path.basename(QWEN_XLSX)},
         "table_a": table_a(split["dev"]), "table_b": table_b()}
    leaked = set(r["task"] for r in t["table_a"]) & set(split["test"])
    if leaked:
        raise SystemExit(f"test tasks in table A: {leaked}")
    t["table_sha256"] = hashlib.sha256(json.dumps([t["table_a"], t["table_b"]], sort_keys=True).encode()).hexdigest()[:16]
    t["frozen"] = True
    json.dump(t, open(OUT_JSON, "w"), indent=1)
    open(OUT_MD, "w").write(render_md(t))
    import table_router
    table_router.write_system_prompt()
    best = {h: sum(r["best"] == h for r in t["table_a"]) for h in HARNESSES}
    print(f"table A: {len(t['table_a'])} dev tasks, best harness counts {best}")
    print(f"table B: {len(t['table_b'])} Qwen tasks")
    print(f"frozen sha256 {t['table_sha256']} -> {os.path.relpath(OUT_JSON, ROOT)}, {os.path.relpath(OUT_MD, ROOT)}")


if __name__ == "__main__":
    main()
