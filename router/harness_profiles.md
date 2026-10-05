# Harness profiles (written by openai/gpt-5.6-luna, 2026-10-03T20:58:14)

Frozen input for the profile-based routers. Written from harness source code only (no task names, task text or benchmark results).

## terminus-2 (2.0.0 (Harbor built-in))

**Summary:** Terminus-2 is a language-model-driven terminal agent that asks the model for JSON or XML command objects containing shell keystrokes, sends them to a persistent tmux-backed bash session, and returns terminal output. It can record terminal activity with asciinema, maintain ATIF-style trajectories, and summarize context through additional LLM calls.

**Interaction model:** At setup, the harness creates a named tmux session running bash --login. For each model response, the selected parser extracts command objects, and _execute_commands sends their keystrokes to the same tmux pane while waiting for the requested duration. The working directory, shell state, processes, and interactive programs therefore persist across steps. Supporting operations invoke tmux through the environment rather than running each requested command with subprocess.run.

**Tools:**
- bash_command: The model emits a JSON or XML command object containing literal keystrokes and a duration; the harness sends those keystrokes to the persistent tmux shell.
- mark_task_complete: The model sets task_complete in its parsed response; the harness requests confirmation and finishes only after the model marks completion on the following turn as well.
- terminal observation: After a command batch, the harness captures tmux output and returns new terminal output or the current visible screen.
- context summarization: When enabled, the harness can make three additional LLM calls to summarize prior work, identify missing information, and answer the resulting questions.

**Interactive programs:** Yes. The model controls a real persistent tmux pane with literal keystrokes, including control keys such as C-c and C-d. It can interact with REPLs, input prompts, editors, and terminal UIs. Commands are normally sent non-blockingly, so the model may need additional polling commands to determine whether a program has finished. Large literal input can use a tmux paste buffer.

**Long running processes:** The model can start foreground or background processes in the persistent shell and use them in later turns, including servers started with shell backgrounding such as &. Command durations are capped at 60 seconds. In the normal execution path, the duration is a wait rather than a process-kill timeout; a foreground process can remain running after the observation. The separate blocking TmuxSession mode is not used by this command path, although a send_keys TimeoutError can produce a timeout observation.

**File editing:** The model edits files through shell commands, heredocs, scripts, editors, or other terminal input. Normal key payloads are limited to roughly 16,000 bytes per batch. For larger literal payloads, the harness can base64-encode and chunk the data into /tmp, load it into a tmux buffer, and paste it. Multi-file changes are possible, but the model must construct and verify them through terminal commands.

**Observation:** The harness captures tmux output with tmux capture-pane -p. It normally compares the current capture with the previous capture and returns either New Terminal Output or Current Terminal Screen; if incremental output cannot be determined, it falls back to the current screen. Each observation is limited to 10,000 UTF-8 bytes, retaining approximately the first and last halves with an omission marker. A command batch produces one resulting observation.

**Context and limits:** The default maximum is 1,000,000 episodes, but max_turns and deprecated episode settings can reduce it. The model must return valid JSON or XML; parse errors produce corrective feedback and execute no commands from the malformed response. Command durations are capped at 60 seconds. Context summarization is enabled by default and starts proactively when estimated free context falls below 8,000 tokens; on overflow, the harness attempts full, short, and terminal-screen-only fallback summarization paths. Summarization adds LLM calls and can split or reset chat and trajectory history. The harness tracks token usage, cost, request times, episode count, and optional rollout details. Execution ends when the session dies, confirmed completion succeeds, or an episode or error limit is reached. Setup can spend up to 240 seconds attempting to install tmux or asciinema, with individual installation commands capped at 120 seconds.

**Images and documents:** The harness has no native image, PDF, or binary-document inspection interface. The model can invoke terminal utilities to inspect text representations, metadata, OCR output, or converted files when such utilities are available, but observations are terminal text.

**Strengths:**
- Persistent interactive Linux shell with preserved cwd, environment, shell state, REPLs, and background processes.
- Direct tmux keystroke control for prompts, editors, terminal UIs, and control-key sequences.
- Command batching, configurable waits, pane-history capture, and incremental-output detection.
- Large literal file writes through the chunked base64 and tmux paste-buffer fallback.
- Two-step completion confirmation and optional terminal recordings, trajectories, accounting, and context compaction.

**Weaknesses:**
- Every action must be encoded as valid JSON or XML; malformed responses require a correction turn.
- Normal execution is non-blocking, so inaccurate durations can produce observations before commands finish and require explicit polling.
- Terminal observations are limited to 10,000 bytes and may fall back to only the visible screen.
- There is no native visual understanding of images, graphical applications, PDFs, or binary documents.
- Context summarization consumes additional LLM calls and may lose detail or alter the retained chat and trajectory history.
- Foreground processes are not automatically killed when a normal command wait expires.
- tmux or asciinema setup may require package-manager or source-build prerequisites and can consume setup time.

**Good for:**
- Interactive shell workflows involving REPLs, editors, password or input prompts, curses programs, or terminal UIs.
- Repository tasks requiring persistent cwd, shell variables, virtual-environment state, background servers, or multiple shell-dependent steps.
- Software builds, tests, and debugging sessions where processes continue across turns and can be polled.
- Large heredoc or generated-file edits delivered through terminal input.
- Tasks that need terminal recordings, detailed trajectories, or automatic context summarization.

**Avoid for:**
- Direct interpretation of screenshots, graphical applications, scanned documents, PDFs, or binary files without command-line conversion tools.
- Foreground jobs requiring reliable automatic cancellation at a precise timeout.
- Tasks whose important output routinely exceeds 10,000 bytes and cannot be redirected or inspected in chunks.
- Tasks requiring precise completion synchronization without allowing polling turns.
- Environments where tmux cannot be installed or built and is not already available.

**Choose when:** Choose Terminus-2 over mini-swe-agent or Pi when the task depends on a persistent shell, direct keystrokes, interactive terminal programs, or processes that must remain available across turns. It is also preferable when large terminal-delivered file contents, pane-history observations, recordings, or context summarization are important.

## mini-swe-agent (2.4.6)

**Summary:** mini-swe-agent 2.4.6 is a minimal bash-only coding agent. The model emits bash actions, and the harness executes each action in the task environment. The Harbor wrapper invokes it with a task, model, trajectory path, and noninteractive settings, then converts its trajectory to ATIF.

**Interaction model:** The model acts through bash tool calls represented as command dictionaries. Each action runs independently through LocalEnvironment using subprocess.Popen(shell=True) in a new shell. Filesystem changes persist, but cwd changes, shell variables, aliases, functions, and other shell-session state do not persist unless the command explicitly persists them. The wrapper uses --yolo and --exit-immediately, redirects its stdin from /dev/null, and logs output with tee.

**Tools:**
- bash: Executes an arbitrary shell command and returns combined stdout and stderr, a return code, and possible exception information.

**Interactive programs:** The harness is not designed to drive interactive REPLs, prompts, editors, or terminal UIs. There is no persistent terminal or keystroke interface, and the top-level process receives stdin from /dev/null. Interactive behavior can only be approximated with noninteractive flags, scripts, files, or background processes.

**Long running processes:** LocalEnvironment gives each command a default 30-second timeout. On POSIX timeout, the process group is killed with SIGKILL and remaining output is collected. A command can start a background process that outlives it if the command returns before the timeout, but the harness provides no persistent terminal or explicit process-management facility for that process.

**File editing:** The model creates and edits files with shell commands such as heredocs, sed, Python scripts, or noninteractive editor invocations. Files persist across independent commands, so multi-file changes are supported. Command output is limited to 10,000 characters, represented for larger output by a 5,000-character head and tail.

**Observation:** After each action, the model receives a structured observation containing the return code and merged stdout and stderr. Output below 10,000 characters is returned in full; larger output is represented by output_head, output_tail, elided_chars, and an Output too long warning. Exceptions include exception information and return code -1. The agent retains a linear message history of model messages and formatted observations.

**Context and limits:** DefaultAgent continues until an exit message, submission, or a configured limit. It supports step_limit, cost_limit, wall_time_limit_seconds, and max_consecutive_format_errors. The packaged configuration sets step_limit and wall time to 0, max consecutive format errors to 3, and cost_limit to 3.0, but Harbor's run command supplies a cost_limit default of 0, normally disabling that configured cost limit unless overridden. There is no context compaction or history summarization; the complete linear history is passed onward. The agent saves its trajectory after each step and stops on repeated format errors, limits, exceptions, or a successful command whose first non-whitespace output line is exactly COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT. Harbor separately totals usage and cost from the trajectory.

**Images and documents:** The harness has no image, PDF, document-parsing, or visual-screen tool. The model can invoke installed command-line utilities or scripts to inspect files, but binary content is not automatically interpreted or supplied as multimodal input.

**Strengths:**
- Simple bash-only control flow with arbitrary shell commands.
- Persistent filesystem changes without persistent hidden shell-session state.
- Explicit per-command timeout and POSIX process-group termination on timeout.
- Structured return codes, merged output, exception information, and bounded output.
- A software-engineering workflow suited to code inspection, reproduction, editing, testing, and submission.
- Trajectory, token, cache, reasoning-token, and cost accounting.

**Weaknesses:**
- No persistent shell, so cwd, variables, aliases, functions, and activation state disappear after each action.
- No direct keystrokes or terminal-screen interface for REPLs, prompts, editors, password entry, or TUIs.
- The default 30-second command timeout limits long foreground jobs.
- Output over 10,000 characters is reduced to head and tail.
- There is no built-in file, patch, search, test, or structured editing API; all such operations use commands.
- There is no context compaction, so the linear history can exhaust the model context.
- Three consecutive format errors can terminate the run by default.
- The wrapper requires a suitable API key and runs noninteractively.
- The shown MCP support only adds server descriptions to the task prompt and does not define an MCP action tool.

**Good for:**
- Repository bug fixes and feature work performed with noninteractive shell commands.
- Code search, scripted reproduction, multi-file edits, unit tests, and command-line validation.
- Sandboxed benchmark tasks that can be completed through independent bash commands.
- Refactors where filesystem persistence matters but persistent cwd or interactive terminal state does not.
- Tasks where explicit timeout and process-group cleanup are more important than long-running execution.

**Avoid for:**
- REPLs, terminal UIs, curses programs, interactive editors, password prompts, or installers requiring keystrokes.
- Workflows requiring persistent cwd, activated environments, exported variables, aliases, or shell functions across commands.
- Foreground builds, test suites, servers, or data-processing jobs that exceed the 30-second timeout.
- Tasks requiring complete logs or command output whose important content may fall in the elided middle.
- Image, PDF, or binary-document inspection without suitable command-line tools.
- Tasks requiring browser interaction, dedicated tool APIs, parallel interactive sessions, or direct terminal control.

**Choose when:** Choose mini-swe-agent over Terminus-2 or Pi for straightforward, noninteractive repository changes that fit within independent bash commands and benefit from a strict 30-second process-group timeout. It is the simplest choice when no persistent shell state, direct file API, image input, or interactive process control is needed.

## pi (0.85.1)

**Summary:** Pi is an extensible coding-agent harness that runs the Pi CLI as a noninteractive JSON-printing agent in the target environment. The model uses Pi tools, primarily read, bash, edit, and write, with optional grep, find, ls, and extensions.

**Interaction model:** The harness starts one Pi process through exec_as_agent using pi --print --mode json --session-dir ... . Pi makes tool calls in the current working directory. Each built-in bash call spawns a new shell with child_process.spawn, so cd and exported variables do not persist between calls unless the command uses an external persistence mechanism such as tmux. Pi sessions are stored as JSONL and can be resumed with --continue.

**Tools:**
- read: Reads text files or supported images, with optional line offset and limit; large text results are truncated by built-in limits.
- bash: Executes a shell command in the current working directory, capturing stdout and stderr, with optional timeout and abort handling.
- edit: Performs exact, unique, non-overlapping text replacements in one file and returns a diff.
- write: Creates parent directories and creates or overwrites a file.
- grep: Searches file contents with ripgrep using regex or literal matching, globs, context, case options, and a match limit.
- find: Searches paths by glob using fd by default, respecting git-ignore behavior and a result limit.
- ls: Lists directory entries, including dotfiles, sorted alphabetically and marking directories with /.
- Extensions and installed Pi packages can add tools or other behavior; the supplied harness does not explicitly install or select extensions.
- The harness exposes a --thinking flag with off, minimal, low, medium, high, and xhigh levels.

**Interactive programs:** Pi is not a direct keystroke-driven persistent terminal. Its stdin is redirected from /dev/null, and bash normally runs with ignored stdin, so REPLs, editors, password prompts, and full-screen TUIs cannot generally be driven directly. The model can indirectly operate a persistent program by starting it under tmux or another external multiplexer and using later bash calls for commands such as tmux send-keys and capture commands.

**Long running processes:** A bash call waits for its spawned shell and streams stdout and stderr. It has no default timeout, although a caller may provide one subject to the implementation's maximum; on timeout or abort, Pi calls killProcessTree on the child. A command can launch a server or other process in the background, preferably under tmux, so it can be inspected or controlled by later bash calls. There is no built-in background-job manager.

**File editing:** The model can create or replace files with write, which creates missing parent directories. Existing files are best changed with edit, whose oldText must match exactly once; it preserves BOM and line-ending style and returns a diff. Multiple disjoint replacements can be made in one edit call, but only within one file. Large files require offset/limit reads or repeated searches, and a complete rewrite requires supplying the full content to write.

**Observation:** Pi runs in JSON mode. The harness filters out message_update events, records remaining JSON events through tee, and later parses message_end assistant events for usage. Tool results and assistant events are provided to the model rather than terminal-screen snapshots. Bash output is streamed and bounded by configured maximum lines and bytes; truncated output is saved to a temporary file and its path is reported. read, grep, find, and ls also impose their respective line, match, result, entry, or byte limits and report truncation or continuation information.

**Context and limits:** Pi sessions are JSONL trees supporting resume and branching. Automatic compaction is enabled by default when context exceeds the context window minus a reserve, with a default reserve of 16,384 tokens; it retains roughly 20,000 recent tokens by default, summarizes older content, and keeps the full session on disk. Tool outputs are truncated before being shown to the model, and compaction serialization truncates tool results to 2,000 characters. The supplied harness does not impose a visible fixed step count; execution ends when Pi exits, the command fails or is aborted, or an outer limit terminates it. The harness aggregates input, cache-read, output, cache, and reported total cost from message_end events; cost is null when no positive cost is reported.

**Images and documents:** The built-in read tool supports JPG, PNG, GIF, WebP, and BMP images and can send image data as an attachment when possible. If the selected model lacks image support, read reports that the image will be omitted. There is no specialized PDF, office-document, archive, or other binary-document tool; such files require bash utilities or extensions.

**Strengths:**
- Dedicated read, write, exact edit, grep, find, ls, and bash tools for repository work.
- Exact replacement editing with uniqueness validation, BOM and line-ending preservation, and returned diffs.
- No default bash timeout, allowing commands longer than mini-swe-agent's default when they complete normally.
- Persistent session history, resume, branching, and automatic context compaction.
- Image reading for supported image types when the selected model supports image input.
- Structured JSON event logging and usage aggregation.
- Extensibility through TypeScript extensions, skills, prompt templates, themes, and Pi packages.

**Weaknesses:**
- No persistent shell session or direct keystroke and screen interface; interactive programs require indirect mechanisms such as tmux.
- stdin is redirected to /dev/null, so programs requiring terminal input are unsuitable unless separately multiplexed.
- Bash cwd and shell variables do not persist automatically between calls.
- Tool and file-inspection results are bounded by truncation limits, requiring follow-up reads or searches for large data.
- edit handles only exact textual replacements in one file and fails for missing, ambiguous, overlapping, or non-unique oldText.
- There is no built-in sub-agent, plan mode, background bash manager, permission popup, or MCP tool in the supplied harness.
- message_update events are filtered out of the recorded pi.txt log.

**Good for:**
- Repository inspection, code search, targeted refactoring, and tests using the dedicated file and search tools.
- Tasks needing exact edits, returned diffs, BOM or line-ending preservation, and multi-step file inspection.
- Long-running noninteractive shell commands that do not need mini-swe-agent's explicit 30-second default timeout.
- Image-aware code or asset inspection for supported image types with a model that accepts image input.
- Server or watcher workflows that can be managed through tmux or another shell-accessible multiplexer.
- Long coding sessions that benefit from resumable JSONL history and automatic context compaction.

**Avoid for:**
- Direct interactive keystrokes into foreground REPLs, editors, installers, password prompts, or full-screen terminal UIs.
- Tasks requiring shell state to persist naturally across many bash calls without scripts or tmux.
- Very large-file transformations where exact replacement payloads or repeated truncated reads are impractical.
- PDF, office-document, archive, or other binary-document analysis without suitable utilities or extensions.
- Workflows requiring built-in multi-agent delegation, plan mode, interactive permissions, MCP actions, or a dedicated background-process API.

**Choose when:** Choose Pi over mini-swe-agent when repository work benefits from dedicated read/search/list tools, exact diff-producing edits, image input, commands without mini-swe-agent's default 30-second timeout, or resumable context-compacted sessions. Choose it over Terminus-2 when direct terminal interactivity is unnecessary and structured file operations or image inspection are more valuable than a persistent tmux shell.

## Sources

- `harbor/agents/terminus_2/terminus_2.py` sha256:c6b72b8c6289809b
- `harbor/agents/terminus_2/tmux_session.py` sha256:38642b794c335880
- `harbor/agents/terminus_2/templates/terminus-json-plain.txt` sha256:89a3dc3a15752b74
- `harbor/agents/terminus_2/templates/timeout.txt` sha256:32bf9aa7b157a6a0
- `harbor/agents/installed/mini_swe_agent.py` sha256:6458398cc58f2d44
- `mswea/mini_swe_agent-2.4.6.dist-info/METADATA` sha256:70969b3842773841
- `mswea/minisweagent/config/mini.yaml` sha256:b539a8965f5bf41d
- `mswea/minisweagent/agents/default.py` sha256:e8ef8aa365942d73
- `mswea/minisweagent/environments/local.py` sha256:01dd33ae6be89745
- `mswea/minisweagent/run/mini.py` sha256:ae9c82013afbc8e0
- `harbor/agents/installed/pi.py` sha256:17304778a023e2f2
- `pi/package/README.md` sha256:a63ba45d9c16ad63
- `pi/package/dist/core/system-prompt.js` sha256:4a57f022a27f2ae2
- `pi/package/dist/core/tools/bash.js` sha256:5f5bc414757f2b48
- `pi/package/dist/core/tools/read.js` sha256:c3d1fa1994c44541
- `pi/package/dist/core/tools/edit.js` sha256:ed04b10ad4583427
- `pi/package/dist/core/tools/write.js` sha256:86bdd1c8a7cd7d4f
- `pi/package/dist/core/tools/grep.js` sha256:641ae520a88c7eb8
- `pi/package/dist/core/tools/find.js` sha256:cbb5e3a76e962899
- `pi/package/dist/core/tools/ls.js` sha256:8e06f1a42e48fcf4
- `pi/package/docs/compaction.md` sha256:b6aff7cab195cd78
- `pi/package/docs/usage.md` sha256:588896ba21944ff0
