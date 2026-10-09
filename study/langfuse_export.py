"""Send one live router run to Langfuse as one trace.

Built from the files a run leaves behind (study/logs/<job>.trace.jsonl, jobs/<job>/*/result.json, the agent's
trajectory.json or pi session log, verifier/ctrf.json), so it changes nothing about the run. Spans go to Langfuse's
OpenTelemetry endpoint because it is the only ingestion path that keeps the original start and end times; scores go
through the SDK. Trace-wide context (trace name, session, tags, environment, task/router/harness/match) is copied
onto every span so child observations can be filtered too.

Langfuse v4 does not deduplicate a span sent twice, so each job is sent once and recorded in
study/logs/langfuse_sent.jsonl; running again prints the existing link. --replace deletes the previous trace and
sends the job again under new ids (use it after changing this exporter).

Trace layout. Names are stable on purpose (dashboards and evaluators key on them); router, harness and match are tags.
  solve-task (chain)                       input: task instruction; output: harness, reward, tests, cost
    route-task (retriever | generation)    the table lookup, or the router model call with its prompt and reply
    set-up-environment (span)
    <harness> (agent)                      terminus-2 / mini-swe-agent / pi, running GPT-5.6-Luna
      install-harness (span)
      decide-next-action (generation)      one per model call: new messages in; reply, thinking and tool calls out
      <tool name> (tool)                   one per tool name per model call (calls grouped, metadata.calls = n),
                                           sibling of the generation that requested it
    verify-solution (evaluator)            per-test results from the verifier
  logs (last 8,000 chars, colour codes stripped, scrubbed) as metadata, so they cost no extra units:
    solve-task: log_harbor (Harbor's job.log + trial.log), log_exception; harness agent: log_console (terminus-2
    pane or mini-swe-agent output); verify-solution: log_pytest
  scores: reward, tests_passed
  session: the task name, so every live run of one task lines up in the Sessions view

Timing inside the agent comes from step boundaries: the logs record when each step finished, not when its model
call ended and its tool started, so a generation spans from the previous step to its own timestamp and its tool
calls are placed at its end.

usage: ~/.venvs/ilab-obs/bin/python study/langfuse_export.py jobs/<job> [--dry-run | --replace]
Needs langfuse==4.17.0 (Python >= 3.10) and LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL in the env.
"""
import argparse, base64, datetime as dt, glob, hashlib, json, os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path[:0] = [os.path.join(ROOT, "study"), os.path.join(ROOT, "router")]
import scrub_secrets  # noqa: E402
import profile_router as pr  # noqa: E402

CLIP = 20000
LOG_KEEP = 8000
ENVIRONMENT = "live"
SENT = os.path.join(ROOT, "study", "logs", "langfuse_sent.jsonl")
SECRETS = scrub_secrets.rules(os.path.join(ROOT, ".env"))


def clean(value):
    """JSON text of value with credentials redacted and long text clipped."""
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > CLIP:
        text = text[:CLIP] + f"... [clipped, {len(text)} chars]"
    data, _ = scrub_secrets.scrub(text.encode("utf-8", "replace"), SECRETS)
    return data.decode("utf-8", "replace")


ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][0-9A-Za-z]|\r")


def log_tail(paths, keep=LOG_KEEP, drop=()):
    """The end of one or more log files as plain text: colour codes and lines matching drop removed."""
    text = ""
    for p in paths:
        if os.path.exists(p):
            lines = ANSI.sub("", open(p, errors="replace").read()).splitlines()
            text += "".join(l + "\n" for l in lines if not any(d in l for d in drop))
    if not text.strip():
        return None
    return text if len(text) <= keep else f"[... first {len(text) - keep} chars omitted]\n" + text[-keep:]


def when(v):
    """datetime (UTC-aware) from an ISO string (naive = local time) or epoch milliseconds."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return dt.datetime.fromtimestamp(v / 1000, dt.timezone.utc)
    d = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
    return d.astimezone(dt.timezone.utc) if d.tzinfo else d.astimezone().astimezone(dt.timezone.utc)


def node(name, kind, start, end, **kw):
    end = end or start
    return {"name": name, "type": kind, "start": start, "end": max(start, end) if start and end else end,
            "children": [], **kw}


def luna(model):
    return model.split("openrouter/", 1)[-1] if model else model


def tool_call(cid, name, args):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}}


# ---- agent steps -------------------------------------------------------------------------------------------------

def group_tools(steps):
    """One tool observation per tool name per model call: each observation is a billed Langfuse unit, and
    terminus-2 sends a command batch per keystroke group (32 calls in 11 steps on one fix-git run)."""
    out = []
    for n in steps:
        last = out[-1] if out else None
        if n["type"] != "tool" or not (last and last["type"] == "tool" and last["name"] == n["name"]):
            out.append(n)
            continue
        if not last.get("calls"):
            last["calls"] = 1
            last["input"], last["output"] = [last["input"]], [last["output"]]
        last["calls"] += 1
        last["input"].append(n["input"])
        last["output"].append(n["output"])
        last["start"], last["end"] = min(last["start"], n["start"]), max(last["end"], n["end"])
        if n.get("level") == "ERROR":
            last["level"] = "ERROR"
    for n in out:
        if n.get("calls"):
            n["metadata"] = {**(n.get("metadata") or {}), "calls": n.pop("calls")}
    return out


def atif_steps(path, run_start, run_end):
    """terminus-2 and mini-swe-agent: Harbor's ATIF trajectory."""
    t = json.load(open(path))
    out, pending, prev = [], [], run_start
    for s in t.get("steps") or []:
        ts = when(s.get("timestamp")) or prev
        if s.get("source") != "agent":
            pending.append({"role": s.get("source"), "content": s.get("message")})
            continue
        m = s.get("metrics") or {}
        extra = m.get("extra") or {}
        cached = (extra.get("prompt_tokens_details") or {}).get("cached_tokens") or m.get("cached_tokens") or 0
        reasoning = (extra.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
        usage = {"input": (m.get("prompt_tokens") or 0) - cached, "output": (m.get("completion_tokens") or 0) - reasoning}
        if cached:
            usage["input_cached_tokens"] = cached
        if reasoning:
            usage["output_reasoning_tokens"] = reasoning
        calls = s.get("tool_calls") or []
        reply = {"role": "assistant", "content": s.get("message") or "",
                 "tool_calls": [tool_call(c.get("tool_call_id"), c.get("function_name"), c.get("arguments")) for c in calls]}
        if s.get("reasoning_content"):
            reply["reasoning_content"] = s["reasoning_content"]
        out.append(node("decide-next-action", "generation", prev, ts, input=pending, output=reply,
                        model=luna(s.get("model_name")), usage=usage,
                        cost={"total": m["cost_usd"]} if m.get("cost_usd") is not None else None,
                        metadata={"step_id": s.get("step_id"), "llm_calls": s.get("llm_call_count", 1)}))
        results = ((s.get("observation") or {}).get("results")) or []
        by_id = {r.get("source_call_id"): r for r in results if r.get("source_call_id")}
        pending = []
        for i, c in enumerate(calls):
            r = by_id.get(c.get("tool_call_id")) or (results[i] if i < len(results) else {})
            content = r.get("content")
            level = None
            try:
                rc = json.loads(content).get("returncode") if isinstance(content, str) and content.startswith("{") else None
                level = "ERROR" if rc not in (None, 0) else None
            except (ValueError, AttributeError):
                pass
            out.append(node(c.get("function_name") or "tool", "tool", ts, ts, input=c.get("arguments"),
                            output=content, level=level))
            pending.append({"role": "tool", "tool_call_id": c.get("tool_call_id"), "content": content})
        prev = ts
    return out


def pi_steps(path, run_start, run_end):
    """pi: its own session log (one JSON event per line)."""
    msgs = []
    for line in open(path, errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") == "message_end" and d.get("message"):
            msgs.append(d["message"])
    out, pending, args = [], [], {}
    for i, m in enumerate(msgs):
        role, ts = m.get("role"), when(m.get("timestamp")) or run_start
        if role == "toolResult":
            text = "\n".join(c.get("text", "") for c in m.get("content") or [] if c.get("type") == "text")
            out.append(node(m.get("toolName") or "tool", "tool", ts, ts, input=args.get(m.get("toolCallId")),
                            output=text, level="ERROR" if m.get("isError") else None))
            pending.append({"role": "tool", "tool_call_id": m.get("toolCallId"), "content": text})
            continue
        if role != "assistant":
            content = m.get("content")
            if isinstance(content, list):
                content = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
            if content or role != "system":
                pending.append({"role": role, "content": content or json.dumps(m.get("sections"))})
            continue
        parts = m.get("content") or []
        calls = [c for c in parts if c.get("type") == "toolCall"]
        for c in calls:
            args[c.get("id")] = c.get("arguments")
        end = next((when(n.get("timestamp")) for n in msgs[i + 1:] if n.get("timestamp")), None) or run_end
        u = m.get("usage") or {}
        usage = {"input": u.get("input", 0), "output": u.get("output", 0)}
        if u.get("cacheRead"):
            usage["input_cached_tokens"] = u["cacheRead"]
        if u.get("cacheWrite"):
            usage["input_cache_write_tokens"] = u["cacheWrite"]
        reply = {"role": "assistant",
                 "content": "\n".join(c.get("text", "") for c in parts if c.get("type") == "text"),
                 "tool_calls": [tool_call(c.get("id"), c.get("name"), c.get("arguments")) for c in calls]}
        thinking = "\n".join(c.get("thinking", "") for c in parts if c.get("type") == "thinking")
        if thinking:
            reply["reasoning_content"] = thinking
        out.append(node("decide-next-action", "generation", ts, end, input=pending, output=reply,
                        model=m.get("model"), usage=usage,
                        cost={"total": (u.get("cost") or {}).get("total")} if u.get("cost") else None,
                        metadata={"provider": m.get("provider"), "stop_reason": m.get("stopReason"),
                                  "reasoning_tokens": u.get("reasoning")}))
        pending = []
    return out


# ---- the whole run -----------------------------------------------------------------------------------------------

def load(job_dir):
    job = os.path.basename(os.path.normpath(job_dir))
    trials = glob.glob(os.path.join(job_dir, "*__*", "result.json"))
    if not trials:
        raise SystemExit(f"no result.json under {job_dir}")
    r = json.load(open(trials[0]))
    events = {}
    trace_file = os.path.join(ROOT, "study", "logs", f"{job}.trace.jsonl")
    if os.path.exists(trace_file):
        for line in open(trace_file):
            e = json.loads(line)
            events[e["event"]] = e
    else:
        # runs from before per-run trace files: rebuild start/route from the live_runs.jsonl summary line
        row = next((json.loads(l) for l in open(os.path.join(ROOT, "study", "live_runs.jsonl"))
                    if json.loads(l).get("job") == job), None)
        if not row:
            raise SystemExit(f"no trace file or live_runs.jsonl line for {job}")
        events["start"] = {"ts": r["started_at"], "task": row["task"], "router": row["router"],
                           "model": r["config"]["agent"]["model_name"]}
        events["route"] = {"ts": r["started_at"], "harness": row["harness"], "version": row["version"],
                           "match": row.get("match") or ("luna" if row["router"] == "lookup" else None),
                           "reason": row.get("reason") or "(not recorded: run predates route logging)",
                           "route_cost": 0.0, "route_seconds": 0.0, "trace": []}
    return job, events, os.path.dirname(trials[0]), r


def route_node(events, task):
    start, route = events["start"], events["route"]
    end = when(route["ts"])
    begin = end - dt.timedelta(seconds=route.get("route_seconds") or 0)
    steps = route.get("trace") or []
    reply = {"harness": route.get("harness"), "match": route.get("match"), "reason": route.get("reason")}
    meta = {"router": start["router"], "decision_steps": steps}
    called = next((s for s in steps if s["step"] in ("router model replied", "Jev replied")), None)
    if not called:
        return node("route-task", "retriever", begin, end, input={"task": task}, output=reply, metadata=meta)
    tokens = called.get("tokens") or {}
    model = called.get("underlying_model") or called.get("model")
    sha = next((s.get("system_prompt_sha256") for s in steps if s.get("system_prompt_sha256")), None)
    prompt_file = os.path.join(ROOT, "router", "table_system_prompt.txt")
    system = open(prompt_file).read().split("\n", 1)[1].strip()
    if hashlib.sha256(system.encode()).hexdigest()[:16] != sha:
        system = f"(prompt {sha} no longer on disk)"
    import table_router
    user = table_router.USER_TEMPLATE.format(name=task, task=pr.task_text(task))
    if called["step"] == "Jev replied":
        reply["probabilities"], reply["confidence"] = called.get("probabilities"), called.get("confidence")
        prompt = {"state": system + "\n\n" + user, "question": "choice between terminus-2, mini-swe-agent, pi"}
    else:
        prompt = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if route.get("raw"):
            reply["raw"] = route["raw"]
    return node("route-task", "generation", begin, end, input=prompt, output=reply, model=model,
                usage={"input": tokens.get("in") or 0, "output": tokens.get("out") or 0},
                cost={"total": called.get("cost") or 0.0}, metadata=meta)


def build(job_dir):
    job, events, trial, r = load(job_dir)
    start, route, result = events["start"], events["route"], events.get("result", {})
    task, harness = start["task"], route["harness"]
    stage = {k: (when((r.get(k) or {}).get("started_at")), when((r.get(k) or {}).get("finished_at")))
             for k in ("environment_setup", "agent_setup", "agent_execution", "verifier")}
    env_ready = bool(stage["environment_setup"][1])
    # A run that stops early (build failure, agent crash) has no times for the stages it never reached; every
    # observation still needs a start, so those collapse onto the last known time.
    last = when(r.get("started_at")) or when(start["ts"])
    for k, (s, e) in stage.items():
        s = s or last
        stage[k] = (s, e or s)
        last = stage[k][1]
    instruction = pr.task_text(task)
    reward = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    exc = r.get("exception_info") or {}

    tests = []
    ctrf = os.path.join(trial, "verifier", "ctrf.json")
    if os.path.exists(ctrf):
        tests = [{"name": t.get("name"), "status": t.get("status"), "message": (t.get("message") or "")[:500]}
                 for t in (json.load(open(ctrf)).get("results") or {}).get("tests") or []]
    passed = sum(t["status"] == "passed" for t in tests)

    run_start, run_end = stage["agent_execution"]
    if os.path.exists(os.path.join(trial, "agent", "trajectory.json")):
        steps = atif_steps(os.path.join(trial, "agent", "trajectory.json"), run_start, run_end)
    elif os.path.exists(os.path.join(trial, "agent", "pi.txt")):
        steps = pi_steps(os.path.join(trial, "agent", "pi.txt"), run_start, run_end)
    else:
        steps = []
    steps = group_tools(steps)
    final = next((s["output"].get("content") for s in reversed(steps) if s["type"] == "generation"), None)
    agent_cost = (r.get("agent_result") or {}).get("cost_usd")

    agent = node(harness, "agent", stage["agent_setup"][0] or run_start, run_end, input=instruction, output=final,
                 metadata={"harness_version": route.get("version"), "model": start.get("model"),
                           "cost_usd": agent_cost, "agent_steps": sum(s["type"] == "generation" for s in steps),
                           "timing": "step boundaries; tool calls placed at the end of their generation",
                           "log_console": log_tail([os.path.join(trial, "agent", f)
                                                    for f in ("terminus_2.pane", "mini-swe-agent.txt")])})
    installed = (r.get("agent_info") or {}).get("version")
    agent["children"] = [node("install-harness", "span", *stage["agent_setup"],
                              input={"harness": harness, "version": route.get("version")},
                              output={"installed": installed} if installed else None)] + steps
    verify = node("verify-solution", "evaluator", *stage["verifier"], input={"tests": [t["name"] for t in tests]},
                  output={"reward": reward, "passed": passed, "failed": len(tests) - passed, "tests": tests},
                  metadata={"log_pytest": log_tail([os.path.join(trial, "verifier", "test-stdout.txt")], keep=4000)},
                  level="WARNING" if reward is not None and reward < 1 else None)

    exc_line = ((exc.get("exception_message") or "").strip().splitlines() or [""])[0]
    root = node("solve-task", "chain", when(start["ts"]), max(filter(None, [when(r.get("finished_at")),
                when((events.get("harbor_end") or {}).get("ts")), last])),
                input=instruction,
                output={"harness": harness, "reward": reward, "tests": f"{passed}/{len(tests)} passed",
                        "cost_usd": {"routing": route.get("route_cost"), "agent": agent_cost}},
                level="ERROR" if exc else None,
                status=clean(f"{exc.get('exception_type')}: {exc_line}") if exc else None,
                metadata={"job": job, "task": task, "router": start["router"], "harness": harness,
                          "harness_version": route.get("version"), "model": start.get("model"),
                          "match": route.get("match"), "harbor_exit_code": (events.get("harbor_end") or {}).get("exit_code"),
                          "trial_dir": os.path.relpath(trial, ROOT),
                          "log_harbor": log_tail([os.path.join(job_dir, "job.log"), os.path.join(trial, "trial.log")],
                                                 drop=("Trajectory dumped to",)),
                          "log_exception": log_tail([os.path.join(trial, "exception.txt")], keep=4000)})
    env = (r.get("config") or {}).get("environment") or {}
    root["children"] = [route_node(events, task),
                        node("set-up-environment", "span", *stage["environment_setup"],
                             input={"task": task, "environment": env.get("type")},
                             output={"ready": env_ready}),
                        agent, verify]
    trace = {"job": job, "name": "solve-task", "session": task,
             "tags": [f"router:{start['router']}", f"harness:{harness}", f"match:{route.get('match')}"]
                     + ([f"batch:{start['batch']}"] if start.get("batch") else [])
                     + (["attempt:fallback"] if start.get("fallback_of") else []),
             "metadata": {"task": task, "router": start["router"], "harness": harness, "match": route.get("match"),
                          "batch": start.get("batch"), "fallback_of": start.get("fallback_of")},
             "scores": [s for s in [
                 {"name": "reward", "value": reward, "comment": f"{passed}/{len(tests)} tests passed"}
                 if reward is not None else None,
                 {"name": "tests_passed", "value": passed / len(tests)} if tests else None] if s]}
    return trace, root


# ---- sending -----------------------------------------------------------------------------------------------------

def walk(n, depth=0):
    yield n, depth
    for c in n["children"]:
        yield from walk(c, depth + 1)


def send(trace, root):
    from langfuse import get_client
    from opentelemetry import trace as otel
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.id_generator import IdGenerator

    class Fixed(IdGenerator):
        """Ids derived from the trace id and the span's place in the tree."""
        span_id = 0

        def generate_trace_id(self):
            return int(trace["id"], 16)

        def generate_span_id(self):
            return self.span_id

    base = (os.environ.get("LANGFUSE_BASE_URL") or os.environ["LANGFUSE_HOST"]).rstrip("/")
    auth = base64.b64encode(f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()).decode()
    ids = Fixed()
    provider = TracerProvider(resource=Resource.create({"service.name": "ilab-router"}), id_generator=ids)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
        endpoint=f"{base}/api/public/otel/v1/traces",
        headers={"Authorization": f"Basic {auth}", "x-langfuse-ingestion-version": "4"})))
    tracer = provider.get_tracer("ilab-router")
    ns = lambda d: int(d.timestamp() * 1e9)

    def emit(n, ctx, path):
        ids.span_id = int(hashlib.sha256(f"{trace['id']}/{path}".encode()).hexdigest()[:16], 16)
        span = tracer.start_span(n["name"], context=ctx, start_time=ns(n["start"]))
        a = span.set_attribute
        a("langfuse.observation.type", n["type"])
        a("langfuse.environment", ENVIRONMENT)
        a("langfuse.trace.name", trace["name"])
        a("langfuse.session.id", trace["session"])
        a("langfuse.trace.tags", trace["tags"])
        for k, v in trace["metadata"].items():
            if v is not None:
                a(f"langfuse.trace.metadata.{k}", v)
        for key, attr in (("input", "input"), ("output", "output"), ("level", "level"), ("status", "status_message")):
            if n.get(key) is not None:
                a(f"langfuse.observation.{attr}", n[key] if key in ("level", "status") else clean(n[key]))
        for k, v in (n.get("metadata") or {}).items():
            if v is not None:
                a(f"langfuse.observation.metadata.{k}", v if isinstance(v, (bool, int, float)) else clean(v))
        if n["type"] == "generation":
            if n.get("model"):
                a("langfuse.observation.model.name", n["model"])
            if n.get("usage"):
                a("langfuse.observation.usage_details", json.dumps(n["usage"]))
            if n.get("cost") and n["cost"].get("total") is not None:
                a("langfuse.observation.cost_details", json.dumps(n["cost"]))
        child_ctx = otel.set_span_in_context(span)
        for i, c in enumerate(n["children"]):
            emit(c, child_ctx, f"{path}/{i}:{c['name']}")
        span.end(end_time=ns(n["end"]))

    emit(root, None, "root")
    provider.force_flush()
    provider.shutdown()

    lf = get_client()
    for s in trace["scores"]:
        lf.create_score(name=s["name"], value=float(s["value"]), trace_id=trace["id"], data_type="NUMERIC",
                        comment=s.get("comment"), score_id=hashlib.sha256(f"{trace['id']}/{s['name']}".encode()).hexdigest()[:32])
    lf.flush()
    return lf.get_trace_url(trace_id=trace["id"])


def last_sent(job):
    if not os.path.exists(SENT):
        return None
    return next((rec for rec in reversed([json.loads(l) for l in open(SENT) if l.strip()]) if rec["job"] == job), None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job_dir")
    ap.add_argument("--dry-run", action="store_true", help="print the trace tree instead of sending it")
    ap.add_argument("--replace", action="store_true", help="delete the trace already sent for this job, send it again")
    a = ap.parse_args()
    trace, root = build(a.job_dir)
    prev = last_sent(trace["job"])
    revision = prev["revision"] + 1 if prev else 0
    trace["id"] = hashlib.sha256(f"{trace['job']}#{revision}".encode() if revision else trace["job"].encode()).hexdigest()[:32]
    if a.dry_run:
        nodes = list(walk(root))
        for n, depth in nodes:
            extra = {k: n[k] for k in ("model", "usage", "cost", "level") if n.get(k)}
            secs = (n["end"] - n["start"]).total_seconds()
            print(f"{'  ' * depth}{n['name']} ({n['type']}) {secs:.1f}s" + (f" {json.dumps(extra)}" if extra else ""))
        redacted = sum(scrub_secrets.scrub(json.dumps([n for n, _ in nodes], default=str).encode(), SECRETS)[1].values())
        print(f"trace {trace['id']} name={trace['name']} session={trace['session']} tags={trace['tags']}")
        print(f"scores {trace['scores']}; {len(nodes)} observations + {len(trace['scores'])} scores + 1 trace = "
              f"{len(nodes) + len(trace['scores']) + 1} units; credentials found before scrubbing: {redacted}")
        return
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        print("skipped: LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set")
        return
    if prev and not a.replace:
        print(f"already sent (revision {prev['revision']}); use --replace to send it again", file=sys.stderr)
        print(prev["url"])
        return
    if prev:
        from langfuse import get_client
        try:
            get_client().api.trace.delete(prev["trace_id"])
        except Exception as e:
            print(f"could not delete the previous trace {prev['trace_id']}: {e}", file=sys.stderr)
    url = send(trace, root)
    with open(SENT, "a") as f:
        f.write(json.dumps({"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "job": trace["job"],
                            "revision": revision, "trace_id": trace["id"], "url": url}) + "\n")
    print(url)


if __name__ == "__main__":
    main()
