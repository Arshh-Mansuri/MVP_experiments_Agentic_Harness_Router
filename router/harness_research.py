"""Luna researches each harness from its source code and writes frozen harness profiles.

Blind by construction: the inputs are only the harness source code and package docs (Harbor's wrappers plus the
agent packages Harbor installs in the container). No task names, task text or benchmark results are given.

Sources (versions used in our runs):
  terminus-2      Harbor's built-in agent (harbor/agents/terminus_2)
  mini-swe-agent  PyPI mini-swe-agent 2.4.6 + Harbor wrapper
  pi              npm @earendil-works/pi-coding-agent 0.85.1 + Harbor wrapper
Download the packages once into ~/.cache/ilab_harness_src (see SRC_SETUP below).

usage: python router/harness_research.py [--model openai/gpt-5.6-luna]
writes router/harness_profiles.json and router/harness_profiles.md
"""
import argparse, datetime, glob, hashlib, json, os, re, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HARBOR = os.path.expanduser("~/.local/share/uv/tools/harbor/lib/python3.12/site-packages/harbor/agents")
SRC = os.path.expanduser("~/.cache/ilab_harness_src")
SRC_SETUP = """mkdir -p ~/.cache/ilab_harness_src && cd ~/.cache/ilab_harness_src
python3 -m pip download --no-deps --python-version 3.12 --only-binary=:all: mini-swe-agent==2.4.6 -d .
npm pack @earendil-works/pi-coding-agent@0.85.1
mkdir -p mswea pi && unzip -qo mini_swe_agent-2.4.6-*.whl -d mswea && tar xzf earendil-works-pi-coding-agent-0.85.1.tgz -C pi"""
HARNESSES = ["terminus-2", "mini-swe-agent", "pi"]
VERSIONS = {"terminus-2": "2.0.0 (Harbor built-in)", "mini-swe-agent": "2.4.6", "pi": "0.85.1"}

SOURCES = {
    "terminus-2": [
        f"{HARBOR}/terminus_2/terminus_2.py",
        f"{HARBOR}/terminus_2/tmux_session.py",
        f"{HARBOR}/terminus_2/templates/terminus-json-plain.txt",
        f"{HARBOR}/terminus_2/templates/timeout.txt",
    ],
    "mini-swe-agent": [
        f"{HARBOR}/installed/mini_swe_agent.py",
        f"{SRC}/mswea/mini_swe_agent-2.4.6.dist-info/METADATA",
        f"{SRC}/mswea/minisweagent/config/mini.yaml",
        f"{SRC}/mswea/minisweagent/agents/default.py",
        f"{SRC}/mswea/minisweagent/environments/local.py",
        f"{SRC}/mswea/minisweagent/run/mini.py",
    ],
    "pi": [
        f"{HARBOR}/installed/pi.py",
        f"{SRC}/pi/package/README.md",
        f"{SRC}/pi/package/dist/core/system-prompt.js",
        f"{SRC}/pi/package/dist/core/tools/bash.js",
        f"{SRC}/pi/package/dist/core/tools/read.js",
        f"{SRC}/pi/package/dist/core/tools/edit.js",
        f"{SRC}/pi/package/dist/core/tools/write.js",
        f"{SRC}/pi/package/dist/core/tools/grep.js",
        f"{SRC}/pi/package/dist/core/tools/find.js",
        f"{SRC}/pi/package/dist/core/tools/ls.js",
        f"{SRC}/pi/package/docs/compaction.md",
        f"{SRC}/pi/package/docs/usage.md",
    ],
}

FIELDS = """{
  "summary": "<2-3 sentences: what this harness is and how the model drives it>",
  "interaction_model": "<how the model's actions reach the environment: e.g. keystrokes into a persistent terminal, one subprocess per command, tool calls; what state persists between steps>",
  "tools": ["<each action/tool the model can use, with one line on what it does>"],
  "interactive_programs": "<can it drive programs that wait for input (REPLs, prompts, editors, TUIs)? how?>",
  "long_running_processes": "<can it start a server/background process and keep using it? how are timeouts handled?>",
  "file_editing": "<how files are created and edited; how well it handles large files and multi-file changes>",
  "observation": "<what the model sees after each action: full output, screen snapshot, truncated output; limits>",
  "context_and_limits": "<step limits, context management or compaction, output truncation, cost tracking, anything that ends a run>",
  "images_and_documents": "<can it inspect images or binary documents?>",
  "strengths": ["<concrete strengths grounded in the code>"],
  "weaknesses": ["<concrete weaknesses or failure modes grounded in the code>"],
  "good_for": ["<kinds of terminal tasks this harness should suit>"],
  "avoid_for": ["<kinds of terminal tasks this harness should not be used for>"]
}"""

RESEARCH_PROMPT = """You are studying an AI agent harness: the scaffolding that lets a language model act inside a Linux terminal environment to complete a task. The same model will be used inside every harness; only the harness differs. Your notes will later be used to decide which harness should attempt a given terminal task.

Harness: {name} (version {version})

Below is its source code and documentation. Read it carefully and describe how the harness actually works, based only on this material. Be concrete and cite mechanisms from the code (e.g. "each command runs via subprocess.run with a timeout", "keystrokes are sent with tmux send-keys"). Do not guess about benchmark scores.

{sources}

Reply with only JSON in this shape:
{fields}"""

COMPARE_PROMPT = """You wrote the three harness profiles below, each from its own source code. The same language model is used inside every harness. These profiles will be the only information a separate router model gets when choosing which harness should attempt a terminal task, so the differences between harnesses must be clear and accurate.

{profiles}

Revise the three profiles so that:
- statements are accurate to the profiles' own evidence (remove anything speculative);
- the differences that matter for choosing a harness are explicit (interaction model, persistence of shell state, interactive programs, long-running processes, file editing, observation, limits, images);
- "good_for" and "avoid_for" are concrete task types, not generic praise;
- each profile also gets "choose_when": one or two sentences saying when this harness is the better choice than the other two.

Reply with only JSON: {{"terminus-2": {{...}}, "mini-swe-agent": {{...}}, "pi": {{...}}}} using the same fields as the input plus "choose_when"."""


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def bundle(name):
    parts = []
    for p in SOURCES[name]:
        rel = p.replace(HARBOR, "harbor/agents").replace(SRC + "/", "")
        parts.append(f"===== FILE: {rel} =====\n{open(p, errors='replace').read()}")
    return "\n\n".join(parts)


def call(prompt, key, model, max_tokens=16000):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0,
                       "max_tokens": max_tokens, "usage": {"include": True}}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", body,
                                 {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.load(r)
        except Exception as e:
            err = e
            time.sleep(5 * (attempt + 1))
    raise err


def parse(txt):
    m = re.search(r"\{.*\}", txt or "", re.S)
    return json.loads(m.group(0))


def to_md(out):
    lines = [f"# Harness profiles (written by {out['model']}, {out['created']})", "",
             "Frozen input for the profile-based routers. Written from harness source code only "
             "(no task names, task text or benchmark results).", ""]
    for h in HARNESSES:
        p = out["profiles"][h]
        lines += [f"## {h} ({VERSIONS[h]})", ""]
        for k, v in p.items():
            label = k.replace("_", " ").capitalize()
            if isinstance(v, list):
                lines += [f"**{label}:**", *[f"- {x}" for x in v], ""]
            else:
                lines += [f"**{label}:** {v}", ""]
    lines += ["## Sources", ""] + [f"- `{f}` sha256:{s}" for f, s in out["source_hashes"].items()]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="openai/gpt-5.6-luna")
    a = ap.parse_args()
    missing = [p for ps in SOURCES.values() for p in ps if not os.path.exists(p)]
    if missing:
        sys.exit("missing sources:\n  " + "\n  ".join(missing) + "\n\nset them up with:\n" + SRC_SETUP)
    key = os.environ["OPENROUTER_API_KEY"]

    drafts, calls = {}, []
    for h in HARNESSES:
        src = bundle(h)
        print(f"researching {h}: {len(src):,} chars of source", flush=True)
        r = call(RESEARCH_PROMPT.format(name=h, version=VERSIONS[h], sources=src, fields=FIELDS), key, a.model)
        drafts[h] = parse(r["choices"][0]["message"]["content"])
        calls.append({"step": f"research {h}", "model": r.get("model"), **{k: (r.get("usage") or {}).get(k) for k in ("prompt_tokens", "completion_tokens", "cost")}})

    print("comparing the three profiles", flush=True)
    r = call(COMPARE_PROMPT.format(profiles=json.dumps(drafts, indent=1)), key, a.model)
    final = parse(r["choices"][0]["message"]["content"])
    calls.append({"step": "compare", "model": r.get("model"), **{k: (r.get("usage") or {}).get(k) for k in ("prompt_tokens", "completion_tokens", "cost")}})
    if set(final) != set(HARNESSES):
        sys.exit(f"compare step returned keys {list(final)}")

    out = {
        "model": a.model,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "frozen": False,
        "versions": VERSIONS,
        "source_hashes": {p.replace(HARBOR, "harbor/agents").replace(SRC + "/", ""): sha(p) for ps in SOURCES.values() for p in ps},
        "calls": calls,
        "cost_usd": round(sum(c.get("cost") or 0 for c in calls), 4),
        "drafts": drafts,
        "profiles": final,
    }
    json.dump(out, open(os.path.join(HERE, "harness_profiles.json"), "w"), indent=1)
    open(os.path.join(HERE, "harness_profiles.md"), "w").write(to_md(out))
    print(f"done: cost ${out['cost_usd']}; wrote router/harness_profiles.json and .md")


if __name__ == "__main__":
    main()
