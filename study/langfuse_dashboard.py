"""Create the iLab router dashboard in Langfuse through its MCP server (the same tools Cursor gets from
.cursor/mcp.json), so the dashboard is defined here and can be rebuilt.

  python3 study/langfuse_dashboard.py --check    run every widget's query on the last 30 days, create nothing
  python3 study/langfuse_dashboard.py            create the widgets and the dashboard (refuses if it exists)
  python3 study/langfuse_dashboard.py --replace  delete the existing dashboard and its widgets, then create again

Needs LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL in the env (set -a; . ./.env; set +a).
Widgets can break down by tags, session (= task), model, observation name and level, not by our metadata, so
router/harness come from the tags; a tags breakdown groups each run's tag set (router, harness, match) together.
Scores carry no session, so per-task results use the verify-solution observation (level WARNING = reward < 1).
"""
import argparse, base64, datetime as dt, json, os, sys, time, urllib.error, urllib.request

NAME = "iLab router: live runs"
DESCRIPTION = ("Live runs of study/run_live_router.sh: router (Luna or Jev) picks the harness, GPT-5.6-Luna solves "
               "the task. Smoke tests only; results never feed back into the router (offline rule).")


def eq(col, value):
    return {"column": col, "operator": "=", "type": "string", "value": value}


def any_of(col, values):
    return {"column": col, "operator": "any of", "type": "stringOptions", "value": values}


REWARD = [eq("name", "reward")]
ROOT = [eq("name", "solve-task")]
STAGES = ["route-task", "set-up-environment", "install-harness", "terminus-2", "mini-swe-agent", "pi", "verify-solution"]
BY_TASK = {"row_limit": 100}

# name, description, view, dimensions, metrics, filters, chart, chart config, (x, y, width, height)
WIDGETS = [
    ("Live runs", "Number of runs (one solve-task per run).",
     "observations", [], [("count", "count")], ROOT, "NUMBER", {}, (0, 0, 3, 3)),
    ("Pass rate", "Mean reward over all runs (1 = all tests passed).",
     "scores-numeric", [], [("value", "avg")], REWARD, "NUMBER", {}, (3, 0, 3, 3)),
    ("Total spend (USD)", "Router calls plus Luna's calls, all runs.",
     "observations", [], [("totalCost", "sum")], [], "NUMBER", {}, (6, 0, 3, 3)),
    ("Routing spend (USD)", "Cost of the routing decisions alone (0 when answered from the table).",
     "observations", [], [("totalCost", "sum")], [eq("name", "route-task")], "NUMBER", {}, (9, 0, 3, 3)),
    ("Pass rate by configuration", "Mean reward per router + harness + match (from the trace tags).",
     "scores-numeric", ["tags"], [("value", "avg")], REWARD, "HORIZONTAL_BAR", {"show_value_labels": True}, (0, 3, 6, 6)),
    ("Spend by model", "Who the money goes to: Luna doing the task vs the router model choosing the harness.",
     "observations", ["providedModelName"], [("totalCost", "sum")], [], "PIE", {}, (6, 3, 6, 6)),
    ("Runs by task", "How many live runs each task has had (session = task).",
     "observations", ["sessionId"], [("count", "count")], ROOT, "HORIZONTAL_BAR", BY_TASK, (0, 9, 6, 6)),
    ("Failed runs by task", "Runs whose verifier did not pass every test.",
     "observations", ["sessionId"], [("count", "count")], [eq("name", "verify-solution"), any_of("level", ["WARNING"])],
     "HORIZONTAL_BAR", BY_TASK, (6, 9, 6, 6)),
    ("Where the time goes (avg ms)", "Average duration of each stage of a run.",
     "observations", ["name"], [("latency", "avg")], [any_of("name", STAGES)], "HORIZONTAL_BAR",
     {"show_value_labels": True}, (0, 15, 6, 6)),
    ("Spend by task (USD)", "Total cost of all runs of each task.",
     "observations", ["sessionId"], [("totalCost", "sum")], [], "HORIZONTAL_BAR", BY_TASK, (6, 15, 6, 6)),
    ("Failed commands by tool", "Tool calls that returned a non-zero exit code (ERROR level).",
     "observations", ["name"], [("count", "count")], [any_of("type", ["TOOL"]), any_of("level", ["ERROR"])],
     "VERTICAL_BAR", {}, (0, 21, 6, 6)),
    ("Luna calls by configuration", "Number of Luna steps (decide-next-action) per router + harness + match.",
     "observations", ["tags"], [("count", "count")], [eq("name", "decide-next-action")], "HORIZONTAL_BAR", {},
     (6, 21, 6, 6)),
    ("Pass rate per day", "Mean reward of the runs finished each day.",
     "scores-numeric", [], [("value", "avg")], REWARD, "BAR_TIME_SERIES", {}, (0, 27, 6, 6)),
    ("Spend per day (USD)", "Total cost per day.",
     "observations", [], [("totalCost", "sum")], [], "BAR_TIME_SERIES", {}, (6, 27, 6, 6)),
    ("Luna token mix", "Tokens of Luna's calls by type: new input, cached input, output, reasoning (and their total).",
     "observations", ["usageType"], [("usageByType", "sum")], [eq("name", "decide-next-action")], "PIVOT_TABLE", {},
     (0, 33, 12, 5)),
]


class MCP:
    def __init__(self):
        self.url = os.environ["LANGFUSE_BASE_URL"].rstrip("/") + "/api/public/mcp"
        key = f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}"
        self.headers = {"Authorization": "Basic " + base64.b64encode(key.encode()).decode(),
                        "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        self.n = 0

    def tool(self, name, args):
        self.n += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self.n, "method": "tools/call",
                           "params": {"name": name, "arguments": args}}).encode()
        for attempt in range(6):
            try:
                text = urllib.request.urlopen(urllib.request.Request(self.url, body, self.headers), timeout=60).read().decode()
                break
            except urllib.error.HTTPError as e:
                if e.code != 429 or attempt == 5:
                    raise
                time.sleep(int(e.headers.get("Retry-After") or 0) or 5 * (attempt + 1))
        if "data:" in text:
            text = [l[5:].strip() for l in text.splitlines() if l.startswith("data:")][-1]
        r = json.loads(text)
        if "error" in r:
            raise RuntimeError(f"{name}: {r['error'].get('message')}")
        out = "".join(c.get("text", "") for c in r["result"].get("content", []))
        if r["result"].get("isError"):
            raise RuntimeError(f"{name}: {out[:300]}")
        try:
            return json.loads(out)
        except ValueError:
            return out


def query_args(view, dims, metrics, filters, config):
    now = dt.datetime.now(dt.timezone.utc)
    q = {"view": view, "dimensions": [{"field": d} for d in dims], "filters": filters,
         "metrics": [{"measure": m, "aggregation": a} for m, a in metrics],
         "fromTimestamp": (now - dt.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "toTimestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    if "sessionId" in dims:
        q["orderBy"] = [{"field": f"{metrics[0][1]}_{metrics[0][0]}", "direction": "desc"}]
        q["config"] = {"row_limit": config["row_limit"]}
    return q


def existing(mcp):
    found = mcp.tool("listDashboards", {})
    rows = found.get("data", found) if isinstance(found, dict) else found
    return [d for d in rows if d.get("name") == NAME]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="run each widget's query, create nothing")
    ap.add_argument("--replace", action="store_true", help="delete the existing dashboard and its widgets first")
    a = ap.parse_args()
    mcp = MCP()

    if a.check:
        for name, _, view, dims, metrics, filters, _, config, _ in WIDGETS:
            try:
                data = mcp.tool("queryMetrics", query_args(view, dims, metrics, filters, config)).get("data")
                print(f"ok   {name}: {json.dumps(data)[:160]}")
            except RuntimeError as e:
                print(f"FAIL {name}: {e}")
        return

    for d in existing(mcp):
        if not a.replace:
            sys.exit(f"dashboard '{NAME}' already exists ({d.get('id')}); use --replace")
        full = mcp.tool("getDashboard", {"dashboardId": d["id"]})
        placed = [p.get("widgetId") for p in (full.get("definition") or {}).get("widgets", []) if p.get("widgetId")]
        mcp.tool("deleteDashboard", {"dashboardId": d["id"]})
        for w in placed:
            mcp.tool("deleteDashboardWidget", {"widgetId": w})
        print(f"deleted dashboard {d['id']} and {len(placed)} widgets")

    dash = mcp.tool("createDashboard", {"name": NAME, "description": DESCRIPTION, "definition": {"widgets": []}})
    dash_id = dash.get("id") or dash.get("dashboard", {}).get("id")
    for name, desc, view, dims, metrics, filters, chart, config, (x, y, w, h) in WIDGETS:
        cfg = dict(config, type=chart)
        if "sessionId" in dims:
            cfg["defaultSort"] = {"column": f"{metrics[0][1]}_{metrics[0][0]}", "order": "DESC"}
        widget = mcp.tool("createDashboardWidget", {
            "name": name, "description": desc, "view": view, "dimensions": [{"field": d} for d in dims],
            "metrics": [{"measure": m, "agg": ag} for m, ag in metrics], "filters": filters, "chartType": chart,
            "chartConfig": cfg})
        wid = widget.get("id") or widget.get("widget", {}).get("id")
        mcp.tool("addDashboardPlacement", {"dashboardId": dash_id, "type": "widget", "widgetId": wid,
                                           "x": x, "y": y, "width": w, "height": h})
        print(f"added {name}")
    print(dash.get("url") or dash_id)


if __name__ == "__main__":
    main()
