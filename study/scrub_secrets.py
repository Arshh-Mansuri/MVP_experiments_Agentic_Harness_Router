"""Redact credentials that the agents dumped into their own run artefacts.

Harbor passes OPENROUTER_API_KEY into the environment of container-installed agents (mini-swe-agent,
pi), so when a task tells the agent to hunt for a password it runs `env` and the key lands in the
transcript we commit. terminus-2 runs on the host and never saw the key.

Secrets are matched two ways: the literal values in .env, so our own credentials are caught whatever
shape they have, and known credential formats, so a rotated or third-party key is caught too. The
format patterns require a non-token character on both sides, because agent logs are full of long
random identifiers that contain "hf_" or "ghp_" in the middle.

.env and .claude/ are skipped: they are gitignored stores where a credential belongs, so rewriting
them would break a working setup without taking anything out of the repository.

usage:
  python3 study/scrub_secrets.py                  dry run over the whole repo, exit 1 if anything is found
  python3 study/scrub_secrets.py --apply          rewrite the affected files in place
  python3 study/scrub_secrets.py path [path ...]  limit the scan (the pre-commit hook passes staged files)
"""
import argparse, os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# .claude holds local tool config that legitimately stores credentials, like .env; both are gitignored,
# so redacting them would break a working setup without removing anything from the repository.
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache", ".claude"}

# Only high-confidence formats: a false positive here would corrupt research data.
EDGE = (rb"(?<![A-Za-z0-9_-])", rb"(?![A-Za-z0-9_-])")
FORMATS = {
    "OPENROUTER_API_KEY": rb"sk-or-v1-[A-Za-z0-9]{32,}",
    "ANTHROPIC_API_KEY": rb"sk-ant-(?:api03-)?[A-Za-z0-9_-]{32,}",
    "OPENAI_API_KEY": rb"sk-proj-[A-Za-z0-9_-]{32,}",
    "GITHUB_TOKEN": rb"gh[pousr]_[A-Za-z0-9]{36}",
    "HF_TOKEN": rb"hf_[A-Za-z0-9]{34}",
    "AWS_ACCESS_KEY_ID": rb"AKIA[0-9A-Z]{16}",
    "LANGFUSE_PUBLIC_KEY": rb"pk-lf-[A-Za-z0-9-]{20,}",
    "LANGFUSE_SECRET_KEY": rb"sk-lf-[A-Za-z0-9-]{20,}",
}


def env_values(path):
    """Literal secrets from .env, longest first so a prefix never shadows a longer value."""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, "rb") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith(b"#") or b"=" not in line:
                continue
            name, _, value = line.partition(b"=")
            value = value.strip().strip(b'"').strip(b"'")
            if len(value) >= 20:
                out[value] = name.strip().decode("ascii", "replace")
    return dict(sorted(out.items(), key=lambda kv: -len(kv[0])))


def rules(env_path):
    literals = env_values(env_path)
    patterns = [(re.compile(re.escape(v)), n) for v, n in literals.items()]
    patterns += [(re.compile(EDGE[0] + p + EDGE[1]), n) for n, p in FORMATS.items()]
    return patterns


def scrub(data, patterns):
    hits = {}
    for rx, name in patterns:
        data, n = rx.subn(b"<REDACTED:" + name.encode() + b">", data)
        if n:
            hits[name] = hits.get(name, 0) + n
    return data, hits


def walk(paths):
    for p in paths:
        if os.path.isfile(p):
            yield p
            continue
        for base, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                yield os.path.join(base, f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", default=None)
    ap.add_argument("--apply", action="store_true", help="rewrite files instead of only reporting")
    ap.add_argument("--env", default=os.path.join(ROOT, ".env"))
    a = ap.parse_args()

    patterns = rules(a.env)
    # .env itself is the legitimate home of these values and is gitignored; never rewrite it.
    env_real = os.path.realpath(a.env)
    found, totals = {}, {}

    for path in walk(a.paths or [ROOT]):
        if os.path.realpath(path) == env_real or os.path.basename(path).startswith(".env"):
            continue
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        clean, hits = scrub(data, patterns)
        if not hits:
            continue
        found[os.path.relpath(path, ROOT)] = hits
        for k, v in hits.items():
            totals[k] = totals.get(k, 0) + v
        if a.apply:
            with open(path, "wb") as fh:
                fh.write(clean)

    if not found:
        print("no credentials found")
        return 0

    verb = "redacted" if a.apply else "found"
    for path, hits in sorted(found.items()):
        print(f"  {path}: " + ", ".join(f"{n} x {k}" for k, n in sorted(hits.items())))
    print(f"\n{verb} {sum(totals.values())} occurrence(s) in {len(found)} file(s): "
          + ", ".join(f"{k} x{v}" for k, v in sorted(totals.items())))
    if not a.apply:
        print("re-run with --apply to rewrite these files")
        return 1
    print("rotate any credential that was committed: redaction does not undo a push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
