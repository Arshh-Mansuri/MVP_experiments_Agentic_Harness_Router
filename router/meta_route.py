"""The meta-harness routing decision, shared by the Harbor agent (router/meta_harness.py) and the live runner's
dry run (study/run_live_router.sh). Standard library only, Python 3.9+.

route(task, router, force) -> (harness, version, info)
  router 'luna' (default): table_router.pick(); 'jev': table_router.decide(). Either answers a Table A task from the
  frozen success table with no model call.
  force: a harness name for the fallback attempt (same-harness retry); no routing call is made.
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import table_router, profile_router as pr

VERSIONS = {"terminus-2": os.environ.get("V_TERMINUS2", "2.0.0"), "mini-swe-agent": os.environ.get("V_MINI", "2.4.6"),
            "pi": os.environ.get("V_PI", "1.0.1")}


def route(task, router="luna", force=None, trigger=None, first_job=None):
    if force in VERSIONS:
        h = force
        info = {"match": "fallback", "reason": f"same-harness retry after {trigger or 'failure'} in {first_job}",
                "cost": 0.0, "seconds": 0.0,
                "trace": [{"step": "fallback: no routing call", "harness": h, "trigger": trigger,
                           "first_attempt": first_job}]}
    elif router == "luna":
        h, info = table_router.pick(task, pr.task_text(task), "luna")
    elif router == "jev":
        h, info = table_router.decide(task, pr.task_text(task))
    else:
        raise ValueError(f"unknown router '{router}': use luna or jev")
    if h not in VERSIONS:
        raise RuntimeError(f"router '{router}' returned '{h}', which is not one of our three harnesses")
    return h, VERSIONS[h], info
