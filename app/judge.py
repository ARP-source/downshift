"""Answer grading and the validity gate.

Three distinct jobs, deliberately kept apart:

  looks_usable()       Free, always on. The cascade uses this to decide whether
                       to escalate. It needs no ground truth, which is the only
                       thing available in production.

  grade_expected()     Deterministic grading against an eval item answer.
                       Free and exact; this is what the benchmark scores on.

  LLMJudge             Grades open-ended items with the cheap tier. Costs money,
                       so its spend is reported separately and never netted out
                       of the router savings figure.
"""
from __future__ import annotations

import re

from . import pricing
from .providers import Completion, Provider

# Phrases that mean the model declined or gave up. Cheap tiers do this more,
# and it must count as a failure or savings are measured against nothing.
REFUSAL_MARKERS = (
    "i cannot", "i can not", "i can't", "i am unable", "i'm unable",
    "as an ai", "i do not have access", "i don't have access",
    "cannot help with", "unable to help",
)
GIVEUP_MARKERS = (
    "i don't know", "i do not know", "unclear", "not sure", "cannot determine",
    "insufficient information", "it depends",
)

_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def _floats(text: str) -> list[float]:
    out = []
    for raw in _NUM.findall(text or ""):
        try:
            out.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return out


def looks_usable(text: str, min_chars: int = 1) -> tuple[bool, str]:
    """Ground-truth-free quality gate. Returns (usable, reason)."""
    if text is None:
        return False, "no text"
    t = text.strip()
    if len(t) < min_chars:
        return False, "empty response"
    low = t.lower()
    for marker in REFUSAL_MARKERS:
        if marker in low:
            return False, f"refusal phrase: {marker}"
    # A short answer that is only a hedge is a non-answer. A long answer that
    # happens to contain "it depends" is fine.
    if len(t) < 60:
        for marker in GIVEUP_MARKERS:
            if low == marker or low.startswith(marker):
                return False, f"gave up: {marker}"
    return True, "ok"


def grade_expected(expected: str, got: str, kind: str = "exact", tolerance: float = 0.01) -> bool | None:
    """Deterministic grading. Returns None when the item is not checkable."""
    if expected is None or kind == "open":
        return None
    got = (got or "").strip()
    exp = str(expected).strip()
    if not got:
        return False

    if kind == "numeric":
        want = _floats(exp)
        have = _floats(got)
        if not want:
            return None
        if not have:
            return False
        target = want[0]
        # Accept the target anywhere in the answer, within relative tolerance.
        scale = max(1e-9, abs(target))
        return any(abs(h - target) / scale <= tolerance for h in have)

    if kind == "yesno":
        low = got.lower()
        want = exp.lower()
        first = low.split()[0].strip(".,!:;") if low.split() else ""
        truthy = {"yes", "true", "correct"}
        falsy = {"no", "false", "incorrect"}
        if want in truthy:
            return first in truthy
        if want in falsy:
            return first in falsy
        return want in low

    if kind == "contains":
        return exp.lower() in got.lower()

    # exact: forgiving about surrounding punctuation and case, strict on content
    norm = lambda s: re.sub(r"[^a-z0-9.]+", " ", s.lower()).strip()
    return norm(exp) == norm(got) or norm(exp) in norm(got)


JUDGE_PROMPT = (
    "You are grading one answer. Reply with exactly one word: PASS or FAIL.\n\n"
    "Question:\n{question}\n\n"
    "Reference answer:\n{reference}\n\n"
    "Candidate answer:\n{candidate}\n\n"
    "Reply PASS if the candidate is factually consistent with the reference and "
    "actually answers the question. Reply FAIL otherwise. One word only."
)


class LLMJudge:
    """Grades open-ended items using the cheapest tier."""

    def __init__(self, provider: Provider, model: str = pricing.JUDGE_MODEL) -> None:
        self._provider = provider
        self._model = model
        self.cost_usd = 0.0
        self.calls = 0

    def grade(self, question: str, reference: str, candidate: str) -> tuple[bool | None, Completion | None]:
        if not candidate or not candidate.strip():
            return False, None
        prompt = JUDGE_PROMPT.format(
            question=question, reference=reference or "(none given)", candidate=candidate
        )
        # The mock provider needs an oracle; PASS keeps mock judging neutral so
        # it never invents quality the router did not earn.
        completion = self._provider.complete(
            self._model, prompt, max_tokens=8, meta={"difficulty": 0.1, "answer": "PASS"}
        )
        self.calls += 1
        self.cost_usd += completion.cost_usd
        if not completion.ok:
            return None, completion
        verdict = completion.text.strip().upper()
        if verdict.startswith("PASS"):
            return True, completion
        if verdict.startswith("FAIL"):
            return False, completion
        return None, completion
