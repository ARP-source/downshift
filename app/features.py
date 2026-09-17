"""Prompt difficulty estimation.

This runs *before* any model call -- it has to be nearly free, or the router
costs more than it saves. So it is deliberately a transparent weighted formula
over cheap lexical signals rather than a classifier model.

Being explainable is a feature, not a compromise: every routing decision can
show the operator exactly which signals pushed a request up or down the ladder.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Weights sum to 1.0 so `difficulty` reads as a 0..1 score.
WEIGHTS: dict[str, float] = {
    "length": 0.15,
    "code": 0.20,
    "math": 0.15,
    "reasoning": 0.25,
    "multistep": 0.15,
    "constraint": 0.10,
}

CODE_MARKERS = (
    "```", "def ", "class ", "function ", "=>", "select ", "import ",
    "regex", "traceback", "stack trace", "compile", "segfault", "null pointer",
    "async ", "await ", "git ", "docker", "kubectl", "sql", "api call",
)
REASONING_MARKERS = (
    "why", "explain", "prove", "derive", "compare", "trade-off", "tradeoff",
    "design", "architect", "analyz", "implication", "justify", "evaluate",
    "critique", "root cause", "reason about", "what would happen",
    "pros and cons", "should i", "best approach",
)
MULTISTEP_MARKERS = (
    "then ", "after that", "finally", "first ", "second ", "third ",
    "step by step", "and also", "as well as", "followed by", "next ",
)
CONSTRAINT_MARKERS = (
    "must ", "exactly", "only ", "in json", "as json", "valid json", "schema",
    "no more than", "at most", "at least", "format", "table", "bullet",
    "one word", "yes or no", "without using",
)
SIMPLE_MARKERS = (
    "what is the capital", "who is", "when did", "what year", "translate",
    "convert ", "how many days", "spell ", "define ", "what does",
    "abbreviation", "capital of",
)

# Observed signal mass tops out near 0.6 even for genuinely hard prompts,
# because a prompt can be hard while triggering only one signal family. This
# gain stretches that range onto the full 0..1 scale so the upper half is
# usable for routing. It is the one number to re-tune if the traffic mix
# changes; it is monotone, so it never reorders two prompts.
CALIBRATION_GAIN = 1.6

_MATH_OPS = re.compile(r"[+\-*/^%=<>]|\b(sum|product|average|mean|median|percent|sqrt|log|integral|derivative|factorial|modulo)\b")
_DIGITS = re.compile(r"\d")
_SENTENCE = re.compile(r"[.!?]+")
_NUMBERED = re.compile(r"(^|\n)\s*(\d+[.)]|[-*])\s+")


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _hits(text: str, markers: tuple[str, ...]) -> list[str]:
    return [m.strip() for m in markers if m in text]


@dataclass
class Features:
    difficulty: float
    contributions: dict[str, float] = field(default_factory=dict)
    signals: dict[str, list[str]] = field(default_factory=dict)
    word_count: int = 0
    simple_discount: float = 0.0

    def top_reasons(self, n: int = 3) -> list[str]:
        """Human-readable drivers of the score, strongest first."""
        ranked = sorted(self.contributions.items(), key=lambda kv: -kv[1])
        out = []
        for name, val in ranked[:n]:
            if val <= 0.001:
                continue
            hit = self.signals.get(name) or []
            detail = f" ({', '.join(hit[:3])})" if hit else ""
            out.append(f"{name} +{val:.2f}{detail}")
        if self.simple_discount > 0.001:
            out.append(f"simple-lookup -{self.simple_discount:.2f}")
        return out or ["no strong signals -- treated as routine"]

    def as_dict(self) -> dict:
        return {
            "difficulty": round(self.difficulty, 4),
            "contributions": {k: round(v, 4) for k, v in self.contributions.items()},
            "signals": self.signals,
            "word_count": self.word_count,
            "simple_discount": round(self.simple_discount, 4),
            "reasons": self.top_reasons(),
        }


def extract(prompt: str) -> Features:
    """Score a prompt's difficulty in 0..1 from cheap lexical signals."""
    raw = prompt or ""
    low = raw.lower()
    words = raw.split()
    wc = len(words)

    # --- sub-scores, each clamped to 0..1 ---
    length = _clamp(wc / 120.0)

    code_hits = _hits(low, CODE_MARKERS)
    code = _clamp(len(code_hits) / 3.0)

    digit_density = len(_DIGITS.findall(raw)) / max(1, len(raw))
    math_hits = _MATH_OPS.findall(low)
    math = _clamp(len(math_hits) / 4.0 + digit_density * 4.0)

    reason_hits = _hits(low, REASONING_MARKERS)
    reasoning = _clamp(len(reason_hits) / 2.5)

    step_hits = _hits(low, MULTISTEP_MARKERS)
    sentences = len([s for s in _SENTENCE.split(raw) if s.strip()])
    bullets = len(_NUMBERED.findall(raw))
    multistep = _clamp(len(step_hits) / 2.5 + max(0, sentences - 1) / 5.0 + bullets / 5.0)

    con_hits = _hits(low, CONSTRAINT_MARKERS)
    constraint = _clamp(len(con_hits) / 2.5)

    subs = {
        "length": length,
        "code": code,
        "math": math,
        "reasoning": reasoning,
        "multistep": multistep,
        "constraint": constraint,
    }
    contributions = {k: WEIGHTS[k] * v for k, v in subs.items()}
    score = sum(contributions.values())

    # A recognised simple-lookup shape discounts the score: these are exactly
    # the requests that should never touch a flagship model.
    simple_hits = _hits(low, SIMPLE_MARKERS)
    discount = 0.0
    if simple_hits and wc < 40:
        discount = 0.35 * _clamp(len(simple_hits) / 1.5)
        score *= 1.0 - discount

    return Features(
        difficulty=_clamp(score * CALIBRATION_GAIN),
        contributions=contributions,
        signals={
            "code": code_hits,
            "math": [str(m) for m in math_hits[:4]],
            "reasoning": reason_hits,
            "multistep": step_hits,
            "constraint": con_hits,
            "simple": simple_hits,
        },
        word_count=wc,
        simple_discount=discount,
    )
