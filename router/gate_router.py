"""Gate router: TF-IDF + Logistic Regression harness picker, trained on the
Qwen 89-task baseline (Qwen_89_Task_Comparison_2026-09-20.xlsx).

Deterministic, zero-LLM-cost routing mode for router.py (--router gate).

Per the leave-one-out CV in cv_gate.py, this pipeline scores 31.5% on the
89-task set -- identical to always picking mini-swe-agent (the best fixed
harness), with oracle at 40.4%. It is expected to output mini-swe-agent for
nearly every new task; it is provided as an inspectable, cheap routing mode
for future use if a larger/cleaner task set arrives, not because it has been
shown to beat the fixed baseline.
"""
import glob, os
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

HARNESSES = ["mini-swe-agent", "terminus-2", "opencode", "pi"]
FALLBACK = "mini-swe-agent"  # matches router.py's FALLBACK
TASK_ROOT = os.path.expanduser("~/.cache/harbor/tasks")
XLSX = os.path.join(os.path.dirname(__file__), "..", "Qwen_89_Task_Comparison_2026-09-20.xlsx")


def load_reward_table():
    df = pd.read_excel(XLSX, sheet_name="Trial details", header=6)
    df["reward"] = pd.to_numeric(df["reward"], errors="coerce").fillna(0.0)
    pivot = df.pivot_table(index="task", columns="harness", values="reward", aggfunc="first")
    return pivot[HARNESSES]


def load_task_text(task):
    hits = glob.glob(f"{TASK_ROOT}/*/{task}/instruction.md")
    if not hits:
        raise FileNotFoundError(task)
    return open(hits[0]).read().strip()


def make_pipeline():
    """Shared vectorizer/classifier construction, used both here and by cv_gate.py's LOOCV."""
    vec = TfidfVectorizer(max_features=2000, stop_words="english", ngram_range=(1, 2))
    clf = LogisticRegression(max_iter=2000, class_weight="balanced")
    return vec, clf


_state = {}  # lazy singleton: {"vec": ..., "clf": ...}


def _fit():
    if _state:
        return _state["vec"], _state["clf"]
    pivot = load_reward_table()
    tasks = list(pivot.index)
    texts = [load_task_text(t) for t in tasks]
    y = pivot.idxmax(axis=1).values
    vec, clf = make_pipeline()
    X = vec.fit_transform(texts)
    clf.fit(X, y)
    _state["vec"], _state["clf"] = vec, clf
    return vec, clf


def pick(task_text: str):
    """Returns (predicted_harness, {harness: probability}). Falls back to FALLBACK on any failure."""
    if not task_text or not task_text.strip():
        return FALLBACK, {}
    try:
        vec, clf = _fit()
        x = vec.transform([task_text])
        proba = clf.predict_proba(x)[0]
        classes = list(clf.classes_)
        dist = {h: round(float(proba[classes.index(h)]), 4) if h in classes else 0.0 for h in HARNESSES}
        pred = clf.predict(x)[0]
        return pred, dist
    except Exception:
        return FALLBACK, {}


if __name__ == "__main__":
    import sys
    for t in sys.argv[1:]:
        try:
            text = load_task_text(t)
        except FileNotFoundError:
            print(f"{t}: instruction.md not found")
            continue
        h, proba = pick(text)
        print(f"{t}: {h}  {proba}")
