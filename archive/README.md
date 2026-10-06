# Archive

Files kept for the record but no longer part of the study. Nothing here is imported or called by live code, and
nothing here should be trusted as a current result. Live scripts are listed in
[`../STUDY_PLAN.md`](../STUDY_PLAN.md) section 6.

| File | What it was | Why it is here |
|---|---|---|
| `run_wd.sh`, `run_router_wd.sh` | Watchdog experiment runners | Pass `--watchdog`, which `router/router.py` no longer accepts, so argparse rejects them. They also hardcode `TB_TASK_DIR=/Users/arsh/.claude/jobs/9d4d6856/...`, a temporary path that no longer exists. The watchdog experiment was dropped. |
| `finish_phase1.sh`, `finish_phase1 2.sh` | One-shot "wait for Phase 1, retry failures, commit" script | Phase 1 finished on 5 Oct. The script ends in `git add -A` and an automatic commit, so running it now would produce a surprise commit. The two copies are byte-identical (an iCloud duplicate). |
| `eval_routers.py` | Offline evaluation of the September Luna router variants | Hardcodes the 15/10-task train/held split from September, reads `picks_cache.json` for picks made with a prompt we no longer use, resolves `jobs/` by the relative path `../jobs`, and carries two `if False` dead branches inside one expression. Superseded by `study/analyze_phase1.py` and `study/kfold_eval.py`, which score 453 runs with confidence intervals. |
| `picks_cache.json` | Router picks cached by `eval_routers.py` | Made with the old prompt; reusing it would silently evaluate a router that no longer exists. |
| `router_log 2.jsonl` | Routing decision log | 20 lines duplicating the start of `router/router_log_gemma.jsonl` (an iCloud duplicate). |
| `Qwen_89_Task_Comparison_2026-09-20.xlsx` | Qwen3-Coder 89-task baseline | Byte-identical duplicate (sha1 `9c4070fc...`) of the copy at the repository root, which is the one `router/gate_router.py` and `router/build_success_table.py` read. |
| `pilot.out`, `wd.out`, `wd_rerun.out`, `router_wd.out`, `queue_wd.txt`, `queue_router_wd.txt` | Scratch stdout and queues from September runs | Committed by accident; superseded by `study/logs/` and `study/phase1_run.log`. |
