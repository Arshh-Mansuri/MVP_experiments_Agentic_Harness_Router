"""Watchdog: reads a running harbor trial's agent log and flags runs that look stuck.

Modes: shadow (record what it WOULD do, never interrupts) and active (kills the trial).
Blind by design: sees only the task text and the agent's own recent steps.
"""
import glob, json, os, re, signal, subprocess, time
from dataclasses import dataclass, field, asdict

JUDGE_MODEL = "openai/gpt-5.6-luna"
MIN_STEPS = 8          # never flag before this many steps
CHECK_EVERY = 3        # run the LLM judge every N new steps
LOOP_WINDOW, LOOP_REPEATS = 8, 4
STUCK_VOTES = 3        # consecutive judge "stuck" verdicts needed to flag
ERR_RE = re.compile(r"traceback|error|not found|no such file|permission denied|failed|exit code [1-9]|returncode\": [1-9]", re.I)


@dataclass
class Step:
    action: str
    obs: str = ""
    in_tok: int = 0
    out_tok: int = 0
    cost: float = 0.0


def _norm(a: str) -> str:
    return re.sub(r"\s+", " ", a).strip()[:200]


def parse_terminus(path):
    t = json.load(open(path))
    steps = []
    for s in t.get("steps", []):
        if s.get("source") != "agent" or "metrics" not in s:
            continue
        m = s["metrics"] or {}
        calls = s.get("tool_calls") or []
        act = " ; ".join(str((c.get("arguments") or {}).get("keystrokes", "")) for c in calls) or s.get("message", "")[:300]
        res = ((s.get("observation") or {}).get("results") or [])
        obs = " ".join(str(r.get("content", "")) for r in res)
        steps.append(Step(act, obs, m.get("prompt_tokens", 0), m.get("completion_tokens", 0), m.get("cost_usd", 0.0) or 0.0))
    return steps


def parse_mini(path):
    ms = json.load(open(path)).get("messages", [])
    steps = []
    for i, m in enumerate(ms):
        if m.get("role") != "assistant":
            continue
        ex = m.get("extra") or {}
        acts = ex.get("actions") or []
        act = " ; ".join(a.get("command", "") for a in acts) or str(m.get("content", ""))[:300]
        obs = ""
        j = i + 1
        while j < len(ms) and ms[j].get("role") == "tool":
            obs += str(ms[j].get("content", "")) + " "
            j += 1
        u = (ex.get("response") or {}).get("usage") or {}
        steps.append(Step(act, obs, u.get("prompt_tokens", 0), u.get("completion_tokens", 0), u.get("cost", 0.0) or 0.0))
    return steps


def parse_pi(path):
    steps, cur = [], None
    for line in open(path, errors="ignore"):
        if not line.startswith("{"):
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        t = e.get("type")
        if t == "message_end" and (e.get("message") or {}).get("role") == "assistant":
            m = e["message"]
            u = m.get("usage") or {}
            calls = [c for c in m.get("content", []) if c.get("type") == "toolCall"]
            act = " ; ".join(json.dumps(c.get("arguments", {}))[:300] for c in calls) or "(no tool call)"
            cur = Step(act, "", (u.get("input", 0) or 0) + (u.get("cacheRead", 0) or 0) + (u.get("cacheWrite", 0) or 0),
                       u.get("output", 0) or 0, ((u.get("cost") or {}).get("total", 0.0)) or 0.0)
            steps.append(cur)
        elif t == "tool_execution_end" and cur is not None:
            cur.obs += " ".join(str(c.get("text", "")) for c in (e.get("result") or {}).get("content", []) if c.get("type") == "text")
    return steps


def load_steps(agent_dir, harness):
    try:
        if harness == "terminus-2":
            return parse_terminus(os.path.join(agent_dir, "trajectory.json"))
        if harness == "mini-swe-agent":
            return parse_mini(os.path.join(agent_dir, "mini-swe-agent.trajectory.json"))
        if harness == "pi":
            return parse_pi(os.path.join(agent_dir, "pi.txt"))
    except Exception:  # file mid-write; try again next poll
        return None
    return None


def heuristics(steps):
    recent = [_norm(s.action) for s in steps[-LOOP_WINDOW:]]
    loop = bool(recent) and max(recent.count(a) for a in set(recent)) >= LOOP_REPEATS
    last = steps[-6:]
    err_streak = len(last) == 6 and all(ERR_RE.search(s.obs[-600:] or "") for s in last)
    return {"loop": loop, "err_streak": err_streak}


JUDGE_PROMPT = """You monitor an AI agent working on a terminal task. Decide whether the agent is STUCK.

Only answer "stuck" if the most recent steps clearly repeat the same action or the same error with no new information and no change of approach. Trying variations, debugging, exploring, installing tools, writing or refining a solution, and verifying results are all normal progress, even when they are slow or hit occasional errors. When unsure, answer "progressing".

Task:
\"\"\"
{task}
\"\"\"

Progress so far: {n} steps{elapsed}.
Most recent steps (oldest first):
{steps}

Reply with only JSON: {{"status": "progressing" or "stuck", "reason": "<one short sentence>"}}"""


class Detector:
    def __init__(self, task_text, timeout_s=None, judge=True):
        self.task, self.timeout_s, self.use_judge = task_text[:2500], timeout_s, judge
        self.last_checked = 0
        self.stuck_run = 0
        self.checks = []
        self.judge_tokens = 0
        self.judge_cost = 0.0
        self.flag = None
        self._llm = None

    def _judge(self, steps, elapsed):
        if self._llm is None:
            from langchain_openai import ChatOpenAI
            self._llm = ChatOpenAI(model=JUDGE_MODEL, base_url="https://openrouter.ai/api/v1",
                                   api_key=os.environ["OPENROUTER_API_KEY"], extra_body={"usage": {"include": True}})
        recent = steps[-10:]
        txt = "\n".join(f"[{len(steps) - len(recent) + i + 1}] ACTION: {_norm(s.action)[:250]}\n    RESULT: {_norm(s.obs)[-250:]}"
                        for i, s in enumerate(recent))
        el = f", {int(elapsed)}s elapsed" + (f" of a {int(self.timeout_s)}s limit" if self.timeout_s else "") if elapsed is not None else ""
        out = self._llm.invoke(JUDGE_PROMPT.format(task=self.task, n=len(steps), elapsed=el, steps=txt))
        u = out.usage_metadata or {}
        self.judge_tokens += u.get("total_tokens", 0) or 0
        self.judge_cost += ((out.response_metadata or {}).get("token_usage", {}).get("cost")) or 0.0
        try:
            d = json.loads(out.content.strip().strip("`").removeprefix("json").strip())
            return d.get("status") if d.get("status") in ("progressing", "stuck") else "progressing", d.get("reason", "")
        except Exception:
            return "progressing", "unparseable"  # fail safe: never kill on a bad judge reply

    def update(self, steps, elapsed=None):
        """Feed the current step list; returns the flag dict the first time the run is flagged."""
        n = len(steps)
        if self.flag or n < MIN_STEPS or n - self.last_checked < CHECK_EVERY:
            return None
        self.last_checked = n
        h = heuristics(steps)
        status, reason = ("progressing", "")
        if self.use_judge:
            status, reason = self._judge(steps, elapsed)
        self.stuck_run = self.stuck_run + 1 if status == "stuck" else 0
        tok = sum(s.in_tok + s.out_tok for s in steps)
        cost = sum(s.cost for s in steps)
        ck = {"steps": n, "tokens": tok, "cost": round(cost, 6), "elapsed": None if elapsed is None else round(elapsed),
              **h, "judge": status, "reason": reason}
        self.checks.append(ck)
        if h["loop"] or self.stuck_run >= STUCK_VOTES:
            self.flag = {**ck, "why": "loop" if h["loop"] else "judge_stuck_x%d" % STUCK_VOTES}
            return self.flag
        return None


def find_agent_dir(job_name, jobs_dir):
    d = glob.glob(os.path.join(jobs_dir, job_name, "*__*", "agent"))
    return d[0] if d else None


def task_timeout(task):
    p = glob.glob(os.path.expanduser(f"~/.cache/harbor/tasks/packages/terminal-bench/{task}/*/task.toml"))
    if p:
        m = re.search(r"\[agent\][^\[]*?timeout_sec\s*=\s*([\d.]+)", open(p[0]).read(), re.S)
        if m:
            return float(m.group(1))
    return None


def supervise(cmd, cwd, job_name, harness, task, task_text, mode, poll=8, env=None):
    """Run harbor `cmd` under the watchdog. mode: 'off' | 'shadow' | 'active'."""
    jobs_dir = os.path.join(cwd, "jobs")
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    t0 = time.time()
    det = Detector(task_text, task_timeout(task), judge=True) if mode != "off" else None
    killed = None
    while p.poll() is None:
        time.sleep(poll)
        if det is None or det.flag:
            continue
        ad = find_agent_dir(job_name, jobs_dir)
        steps = load_steps(ad, harness) if ad else None
        if not steps:
            continue
        flag = det.update(steps, None)
        if flag and mode == "active":
            os.killpg(p.pid, signal.SIGINT)  # lets harbor tear down the container
            try:
                p.wait(timeout=90)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
            killed = flag
    rc = p.wait()
    out = {"rc": rc, "wall_s": round(time.time() - t0, 1), "mode": mode, "killed": bool(killed)}
    if det:
        out.update({"flag": det.flag, "checks": det.checks, "judge_tokens": det.judge_tokens, "judge_cost": round(det.judge_cost, 6)})
    return out
