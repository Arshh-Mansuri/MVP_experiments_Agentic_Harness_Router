# Success table (frozen)

sha256 203bc53928de12c4, built 2026-10-07T00:21:49. Table A = Luna Phase 1 development tasks only.

## Table A: GPT-5.6-Luna, 3 runs per harness (passes/runs, average cost per run)

| task | terminus-2 | mini-swe-agent | pi | best | note |
|---|---|---|---|---|---|
| build-cython-ext | 1/3 $0.034 | 0/3 $0.024 | 3/3 $0.040 | **pi** |  |
| cancel-async-tasks | 3/3 $0.003 | 2/3 $0.005 | 2/3 $0.003 | **terminus-2** |  |
| chess-best-move | 0/3 $0.032 | 1/3 $0.011 | 0/3 $0.009 | **mini-swe-agent** |  |
| cobol-modernization | 3/3 $0.014 | 3/3 $0.012 | 3/3 $0.009 | **pi** | tie on pass rate; cheapest chosen |
| code-from-image | 3/3 $0.019 | 3/3 $0.012 | 1/3 $0.004 | **mini-swe-agent** | tie on pass rate; cheapest chosen |
| constraints-scheduling | 2/3 $0.003 | 3/3 $0.003 | 2/3 $0.002 | **mini-swe-agent** |  |
| count-dataset-tokens | 1/3 $0.010 | 2/3 $0.007 | 1/3 $0.007 | **mini-swe-agent** |  |
| crack-7z-hash | 1/3 $0.019 | 0/3 $0.057 | 2/3 $0.012 | **pi** |  |
| db-wal-recovery | 2/3 $0.006 | 1/3 $0.005 | 0/3 $0.010 | **terminus-2** |  |
| distribution-search | 3/3 $0.005 | 3/3 $0.005 | 3/3 $0.007 | **terminus-2** | tie on pass rate; cheapest chosen |
| feal-linear-cryptanalysis | 3/3 $0.013 | 2/3 $0.023 | 3/3 $0.010 | **pi** | tie on pass rate; cheapest chosen |
| financial-document-processor | 2/3 $0.023 | 2/3 $0.013 | 1/3 $0.029 | **mini-swe-agent** | tie on pass rate; cheapest chosen |
| fix-git | 3/3 $0.004 | 3/3 $0.005 | 3/3 $0.004 | **terminus-2** | tie on pass rate; cheapest chosen |
| gcode-to-text | 0/3 $0.082 | 0/3 $0.018 | 0/3 $0.025 | **mini-swe-agent** | no harness solved it; default |
| git-leak-recovery | 3/3 $0.004 | 3/3 $0.003 | 3/3 $0.003 | **pi** | tie on pass rate; cheapest chosen |
| headless-terminal | 2/3 $0.008 | 3/3 $0.009 | 1/3 $0.009 | **mini-swe-agent** |  |
| large-scale-text-editing | 2/3 $0.024 | 3/3 $0.009 | 3/3 $0.003 | **pi** | tie on pass rate; cheapest chosen |
| multi-source-data-merger | 3/3 $0.006 | 3/3 $0.007 | 3/3 $0.005 | **pi** | tie on pass rate; cheapest chosen |
| path-tracing | 1/3 $0.128 | 0/3 $0.009 | 0/3 $0.021 | **terminus-2** |  |
| polyglot-c-py | 2/3 $0.011 | 3/3 $0.024 | 1/3 $0.008 | **mini-swe-agent** |  |
| polyglot-rust-c | 3/3 $0.025 | 3/3 $0.020 | 1/3 $0.011 | **mini-swe-agent** | tie on pass rate; cheapest chosen |
| protein-assembly | 0/3 $0.045 | 0/3 $0.021 | 0/3 $0.022 | **mini-swe-agent** | no harness solved it; default |
| prove-plus-comm | 1/3 $0.004 | 3/3 $0.004 | 3/3 $0.005 | **mini-swe-agent** | tie on pass rate; cheapest chosen |
| regex-log | 3/3 $0.005 | 3/3 $0.005 | 3/3 $0.004 | **pi** | tie on pass rate; cheapest chosen |
| schemelike-metacircular-eval | 1/3 $0.038 | 1/3 $0.026 | 1/3 $0.022 | **pi** | tie on pass rate; cheapest chosen |
| torch-pipeline-parallelism | 0/3 $0.008 | 0/3 $0.009 | 1/3 $0.010 | **pi** |  |
| winning-avg-corewars | 1/3 $0.106 | 0/3 $0.025 | 0/3 $0.020 | **terminus-2** |  |

## Table B: Qwen3-Coder 480B, 1 run per harness (weak hint; OpenCode not available to us)

| task | mini-swe-agent | terminus-2 | pi | opencode |
|---|---|---|---|---|
| adaptive-rejection-sampler | FAIL | FAIL | FAIL | FAIL |
| bn-fit-modify | FAIL | FAIL | FAIL | FAIL |
| break-filter-js-from-html | FAIL | FAIL | FAIL | FAIL |
| build-cython-ext | FAIL | FAIL | FAIL | FAIL |
| build-pmars | PASS | PASS | FAIL | PASS |
| build-pov-ray | FAIL | FAIL | FAIL | ERROR |
| caffe-cifar-10 | FAIL | FAIL | FAIL | ERROR |
| cancel-async-tasks | FAIL | PASS | FAIL | PASS |
| chess-best-move | FAIL | FAIL | FAIL | FAIL |
| circuit-fibsqrt | FAIL | FAIL | FAIL | FAIL |
| cobol-modernization | PASS | PASS | PASS | PASS |
| code-from-image | PASS | FAIL | FAIL | ERROR |
| compile-compcert | FAIL | FAIL | PASS | FAIL |
| configure-git-webserver | PASS | PASS | FAIL | PASS |
| constraints-scheduling | PASS | PASS | FAIL | FAIL |
| count-dataset-tokens | FAIL | PASS | FAIL | PASS |
| crack-7z-hash | FAIL | FAIL | PASS | FAIL |
| custom-memory-heap-crash | PASS | FAIL | FAIL | PASS |
| db-wal-recovery | FAIL | FAIL | FAIL | FAIL |
| distribution-search | FAIL | FAIL | FAIL | FAIL |
| dna-assembly | FAIL | FAIL | FAIL | FAIL |
| dna-insert | FAIL | FAIL | FAIL | FAIL |
| extract-elf | PASS | PASS | PASS | FAIL |
| extract-moves-from-video | FAIL | FAIL | FAIL | FAIL |
| feal-differential-cryptanalysis | FAIL | FAIL | FAIL | FAIL |
| feal-linear-cryptanalysis | FAIL | FAIL | FAIL | FAIL |
| filter-js-from-html | FAIL | FAIL | FAIL | FAIL |
| financial-document-processor | FAIL | FAIL | FAIL | FAIL |
| fix-code-vulnerability | PASS | PASS | FAIL | ERROR |
| fix-git | PASS | PASS | PASS | PASS |
| fix-ocaml-gc | PASS | FAIL | FAIL | ERROR |
| gcode-to-text | FAIL | FAIL | FAIL | FAIL |
| git-leak-recovery | PASS | PASS | PASS | PASS |
| git-multibranch | PASS | FAIL | PASS | FAIL |
| gpt2-codegolf | FAIL | FAIL | FAIL | FAIL |
| headless-terminal | PASS | ERROR | FAIL | FAIL |
| hf-model-inference | PASS | PASS | FAIL | PASS |
| install-windows-3.11 | ERROR | FAIL | FAIL | FAIL |
| kv-store-grpc | FAIL | FAIL | ERROR | FAIL |
| large-scale-text-editing | FAIL | FAIL | FAIL | FAIL |
| largest-eigenval | PASS | FAIL | FAIL | FAIL |
| llm-inference-batching-scheduler | FAIL | FAIL | FAIL | ERROR |
| log-summary-date-ranges | PASS | FAIL | PASS | PASS |
| mailman | ERROR | PASS | FAIL | ERROR |
| make-doom-for-mips | FAIL | FAIL | FAIL | FAIL |
| make-mips-interpreter | FAIL | FAIL | FAIL | FAIL |
| mcmc-sampling-stan | FAIL | FAIL | FAIL | ERROR |
| merge-diff-arc-agi-task | PASS | FAIL | FAIL | FAIL |
| model-extraction-relu-logits | FAIL | FAIL | PASS | PASS |
| modernize-scientific-stack | PASS | PASS | PASS | PASS |
| mteb-leaderboard | FAIL | FAIL | FAIL | FAIL |
| mteb-retrieve | FAIL | FAIL | FAIL | FAIL |
| multi-source-data-merger | PASS | PASS | PASS | PASS |
| nginx-request-logging | PASS | PASS | PASS | PASS |
| openssl-selfsigned-cert | PASS | PASS | PASS | FAIL |
| overfull-hbox | FAIL | FAIL | FAIL | FAIL |
| password-recovery | FAIL | FAIL | FAIL | FAIL |
| path-tracing | FAIL | FAIL | FAIL | FAIL |
| path-tracing-reverse | ERROR | FAIL | FAIL | FAIL |
| polyglot-c-py | FAIL | FAIL | FAIL | FAIL |
| polyglot-rust-c | PASS | FAIL | FAIL | PASS |
| portfolio-optimization | PASS | FAIL | FAIL | PASS |
| protein-assembly | FAIL | FAIL | FAIL | ERROR |
| prove-plus-comm | PASS | PASS | PASS | PASS |
| pypi-server | PASS | PASS | PASS | FAIL |
| pytorch-model-cli | FAIL | FAIL | FAIL | FAIL |
| pytorch-model-recovery | PASS | PASS | ERROR | PASS |
| qemu-alpine-ssh | ERROR | FAIL | ERROR | ERROR |
| qemu-startup | ERROR | FAIL | ERROR | ERROR |
| query-optimize | PASS | PASS | FAIL | FAIL |
| raman-fitting | FAIL | FAIL | FAIL | FAIL |
| regex-chess | FAIL | FAIL | FAIL | FAIL |
| regex-log | FAIL | FAIL | FAIL | FAIL |
| reshard-c4-data | FAIL | FAIL | FAIL | ERROR |
| rstan-to-pystan | FAIL | FAIL | ERROR | FAIL |
| sam-cell-seg | FAIL | FAIL | FAIL | FAIL |
| sanitize-git-repo | FAIL | FAIL | FAIL | ERROR |
| schemelike-metacircular-eval | FAIL | FAIL | FAIL | FAIL |
| sparql-university | FAIL | FAIL | FAIL | FAIL |
| sqlite-db-truncate | FAIL | FAIL | FAIL | FAIL |
| sqlite-with-gcov | PASS | PASS | FAIL | ERROR |
| torch-pipeline-parallelism | FAIL | FAIL | FAIL | FAIL |
| torch-tensor-parallelism | FAIL | FAIL | FAIL | FAIL |
| train-fasttext | FAIL | ERROR | FAIL | ERROR |
| tune-mjcf | FAIL | FAIL | FAIL | FAIL |
| video-processing | FAIL | FAIL | FAIL | FAIL |
| vulnerable-secret | FAIL | PASS | PASS | FAIL |
| winning-avg-corewars | FAIL | FAIL | FAIL | FAIL |
| write-compressor | FAIL | FAIL | FAIL | FAIL |
