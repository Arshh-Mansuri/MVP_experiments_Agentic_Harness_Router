"""Ground-truth table: task -> harness -> list of rewards, from finished trials without infrastructure errors."""
import glob, json, collections
H = ("terminus-2", "mini-swe-agent", "pi")

def build(root="jobs"):
    t = collections.defaultdict(lambda: collections.defaultdict(list))
    for f in glob.glob(f"{root}/*/*__*/result.json"):
        if "/livetest-" in f or "/wdtest-" in f:
            continue
        r = json.load(open(f))
        h = (r.get("agent_info") or {}).get("name")
        rew = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        if h in H and rew is not None:
            t[r["trial_name"].rsplit("__", 1)[0]][h].append(rew)
    return t

if __name__ == "__main__":
    t = build()
    for task in sorted(t):
        print(f"{task:28}", {h: (round(sum(v) / len(v), 2), len(v)) for h, v in t[task].items()})
