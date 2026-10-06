# Problem definition (aligned with the work, 7 Oct 2026)

**In one line:** a meta-harness that sends each Terminal-Bench task to whichever of three agent harnesses is most
likely to solve it, with the model held constant, to find out whether that routing layer pays for itself.

This file replaces the harness and model choices in the original proposal. Everything else (pipeline, metrics,
research questions) follows the proposal, with the changes listed at the end.

## Setup

| Item | Value |
|---|---|
| Benchmark | Terminal-Bench (Harbor registry `terminal-bench/<task>`, ref `latest`; exact ref to be recorded, see "Open items") |
| Tasks | 89 in the benchmark. Luna data so far: 45 tasks (27 development, 18 test), 3 repeats per task and harness |
| Model (constant) | **GPT-5.6-Luna** via OpenRouter (`openrouter/openai/gpt-5.6-luna`), the same for every run |
| Harnesses | **terminus-2** (tmux terminal, keystrokes, persistent shell), **mini-swe-agent** (one bash command per step, 30 s command timeout), **pi** (read/write/edit/bash tools, image input, no default command timeout) |
| Runner | Harbor 0.21.0, Docker, at most 3 runs in parallel |

Only the harness varies, so any difference in results is attributed to the harness.

## Pipeline

1. **Baseline:** every task x every harness. Recorded per run: reward, tokens, cost, time per stage, errors, logs
   (`study/run_phase1.sh`, export in `study/ilab_experiments.xlsx`).
2. **Oracles** (both reported):
   - **Cheapest-pass oracle** (proposal definition): per task, the cheapest harness that passed. With repeats, a
     task counts as passed by a harness if any of its runs passed; on one run per cell this is the proposal's oracle.
   - **Stable oracle** (our main ceiling): per task, the harness with the best mean pass rate over the repeats,
     ties to the cheaper one.
   - **Single-run oracle:** the cheapest-pass oracle computed on one repeat at a time. The gap between it and the
     stable oracle shows how much of the "headroom" is luck.
3. **Analysis:** where harnesses disagree, and which task features (`task.toml` difficulty, category, tags, and
   keywords in the instruction) explain it, with a shallow decision tree (`study/task_features.py`).
4. **Routers:**
   - learned: k-NN on task-text vectors (TF-IDF) and a depth-2 decision tree on task metadata. Hand-written
     keyword/regex rules were dropped on 7 Oct: the tree found no usable keyword split, so writing rules by hand
     would only be fitting 27 tasks by eye.
   - LLM classifier: one call with the task text and harness descriptions (Luna or Jev with the frozen profiles)
   - the hard-coded lookup (`router/table_router.py lookup`) is a **cache for known tasks**, not a router; it is never
     reported as a routing result
5. **Fallback:** one retry on a different harness, triggered **only by signals visible at run time**: the harness
   crashed without producing a result, or the agent hit its time limit (optionally, a run exceeding a time budget).
   The verifier's hidden tests are never used to trigger it. Extra cost and time are counted, and every fallback is
   compared against a **same-harness retry control**, because most triggers are infrastructure crashes that a plain
   retry also fixes (`study/fallback_sim.py`).
6. **Evaluation:** offline replay of router choices against the saved runs with **k-fold cross-validation**
   (`study/kfold_eval.py`, the main evaluation; anything learned from data is fitted on the training folds only),
   the development / test split as a secondary check (`study/analyze_phase1.py`), then one live run through Harbor
   (`study/run_live_router.sh`).

   The baseline is reported two ways. `--baseline fold` re-picks the best single harness inside each training fold,
   which is what a deployment would do but is itself unstable (it picks terminus-2 on some folds and mini-swe-agent
   on others, landing at 59.3% against mini-swe-agent's 61.7%). `--baseline fixed` holds the overall best single
   harness, which is the fair comparison for claiming a router beat it. Claims use `fixed`.

## Metrics

Resolve rate; oracle headroom recovered = (router − best single) / (oracle − best single); total tokens; cost and
cost per pass; routing overhead (router tokens, cost, latency); wall-clock time. Each with a 95% bootstrap CI over
tasks. Resolve rate is reported both with and without tasks where a harness cannot install (`qemu-startup`).

## Research questions

- **RQ1:** how do the harnesses differ per task?
- **RQ2:** does rule-based or LLM routing beat the best single harness on the performance–resource trade-off?
- **RQ3:** do the gains justify the overhead?

A negative result is a valid outcome.

## Answers so far (27 development tasks, 3 repeats, Luna fixed)

**RQ1 — the harnesses do differ.** Perfect picking reaches 75.3% against 61.7% for always-mini-swe-agent,
+13.6 points [+4.9, +23.5], so there is real headroom. But the differences are not stable: only 50 of 81
task x harness cells give the same result on all three repeats, and the single-run oracle reads 81.5%, i.e. 6.2
points of the apparent headroom is luck rather than a property of the harness.

**RQ2 — no router captures it.** Under 5-fold cross-validation against a fixed mini-swe-agent baseline, every
router lands at or below it, and the ordering is stable across seeds 0, 1 and 2:

| Strategy | Pass % | vs mini-swe-agent (95% CI) | Cost per pass |
|---|---|---|---|
| always mini-swe-agent (baseline) | 61.7 | — | $0.022 |
| lookup cache, k-fold (Qwen hint on unseen tasks) | 64.2 | +2.5 [−2.5, +8.6] | −15% |
| decision tree on metadata | 58.0–61.7 | −3.7 to +0.0 | +2% to +36% |
| LLM router (Luna, frozen profiles) | 58.0 | −3.7 [−13.6, +8.6] | +15% |
| LLM router (Jev, frozen profiles) | 56.8 | −4.9 [−16.0, +7.4] | +59% |
| k-NN on task text (TF-IDF) | 51.9–55.6 | −6.2 to −9.9 | +16% to +22% |

Task metadata carries almost no signal: a depth-2 tree predicting the best harness gets 52% leave-one-out accuracy
against 41% for always answering mini-swe-agent, and predicting *whether* the harnesses disagree does worse than
guessing (48% against a 70% majority). Nothing meets the +5-point criterion with a CI excluding zero.

**RQ3 — the overhead is not the binding problem; the accuracy is.** Routing costs little ($0.004–$0.17 over 27
tasks, 0–107 s), but since no router beats the baseline there is no gain to justify. Fallback is a clearer win and
has nothing to do with routing: retrying after an observable failure lifts always-terminus-2 from 51.9% to 61.7%
and always-pi from 49.4% to 54.3% for about $0.02 per extra pass — but the same-harness retry control gains just as
much (+8.6 and +4.9), and more than switching for mini-swe-agent (+2.5 against +1.2). The gain is crash recovery,
not harness choice.

**Standing recommendation:** ship always-mini-swe-agent plus a same-harness retry on crash or timeout. The open
routing question worth testing next is a mini-swe-agent-first router that only diverts on strong evidence, since
every router here loses by over-diverting.

## Changes from the original proposal, and why

| Proposal | Now | Why |
|---|---|---|
| OpenCode, OpenHands, Goose | terminus-2, mini-swe-agent, pi | The team kept the harnesses already benchmarked; 453 Luna runs exist for these three |
| Model not frozen (Luna, MiMo-V2.5, Qwen3-Coder) | GPT-5.6-Luna | All study data uses Luna; mixing models would break "only the harness varies" |
| 1 run per task and harness | 3 repeats | Only 50 of 81 development cells give the same result on every repeat, so single runs overstate the oracle |
| Oracle = cheapest harness that passed | Both that and the stable oracle | Comparability with the proposal plus a noise-robust ceiling |
| Fallback "if the first choice fails" | Triggered only by run-time signals | Using the hidden tests to decide on a retry would not be possible in real use |

## Open items

- OpenRouter key returns 401 since 7 Oct; budget and UTS HPC access unconfirmed (spend so far about $9.1).
- Remaining 44 tasks need Luna runs for full 89-task coverage (`study/phase2_queue.txt`).
- Confirm that registry `latest` is Terminal-Bench 2.1 and record the ref.
- Schedule: proposal says presentation 11 Oct and report 18 Oct; the charter says 4, 18 and 25 Oct.
