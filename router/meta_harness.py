"""The meta-harness as a Harbor agent: routes each task to one of three established harnesses and runs it there.

Nothing is built or modified: setup() asks the router (router/meta_route.py, the frozen success table plus Luna)
which harness to use, then creates that harness's own Harbor agent (terminus-2, mini-swe-agent or pi, pinned
versions) with the same model, and setup/run are delegated to it. The chosen harness writes its logs and trajectory
to this agent's log directory exactly as it would on its own; the decision is saved next to them as route.json.

usage (from the repo root; Harbor runs under its own Python 3.12):
  PYTHONPATH=router harbor run -t terminal-bench/<task> --model openrouter/openai/gpt-5.6-luna \
      --agent meta_harness:MetaHarness [--ak router=luna|jev] [--ak force_harness=<h> --ak trigger=<why> --ak first_job=<job>]

force_harness is the fallback attempt: the same harness again, with no routing call. The fallback itself is
decided outside Harbor (study/run_final.sh), because Harbor's agent timeout cancels the whole agent and leaves no
time to retry inside it.
"""
import asyncio, datetime, json, os, sys

from harbor.agents.base import BaseAgent
from harbor.agents.factory import AgentFactory
from harbor.models.agent.name import AgentName

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import meta_route

FORWARD = ("logger", "mcp_servers", "skills_dir", "extra_env", "load_trajectory")


class MetaHarness(BaseAgent):
    def __init__(self, logs_dir, model_name=None, router="luna", force_harness=None, trigger=None, first_job=None,
                 task=None, **kwargs):
        self._forward = {k: kwargs[k] for k in FORWARD if kwargs.get(k) is not None}
        super().__init__(logs_dir, model_name, **kwargs)
        self.router, self.force_harness = str(router), (str(force_harness) if force_harness else None)
        self.trigger, self.first_job, self.task = trigger, first_job, task
        self.harness = self.harness_version = self.inner = None

    @staticmethod
    def name():
        return "meta-harness"

    def version(self):
        return f"{self.harness}@{self.harness_version}" if self.harness else None

    async def setup(self, environment):
        task = self.task or (self.session_id or "").split("__")[0]
        h, ver, info = await asyncio.to_thread(meta_route.route, task, self.router, self.force_harness,
                                               self.trigger, self.first_job)
        self.harness, self.harness_version = h, ver
        os.makedirs(self.logs_dir, exist_ok=True)
        with open(os.path.join(self.logs_dir, "route.json"), "w") as f:
            json.dump({"routed_at": datetime.datetime.now().isoformat(timespec="seconds"), "task": task,
                       "router": self.router, "harness": h, "version": ver, **info}, f, indent=1, default=str)
        self.logger.info(f"meta-harness: {task} -> {h} {ver} ({info.get('match')}: {info.get('reason')})")
        self.inner = AgentFactory.create_agent_from_name(AgentName(h), logs_dir=self.logs_dir,
                                                         model_name=self.model_name, version=ver, **self._forward)
        self.inner.session_id, self.inner.context_id = self.session_id, self.context_id
        await self.inner.setup(environment)

    async def run(self, instruction, environment, context):
        await self.inner.run(instruction=instruction, environment=environment, context=context)

    def populate_context_post_run(self, context):
        if self.inner is not None:
            self.inner.populate_context_post_run(context)
