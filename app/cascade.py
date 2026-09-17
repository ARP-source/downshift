"""Escalating execution: start cheap, climb only when the answer is not usable.

This is where cost and reliability meet. Two different things can push a
request up the ladder, and they are counted separately because they mean
different things to an operator:

  escalation -- the tier answered, but the answer failed the quality gate
  failover   -- the tier errored or timed out, so we moved off it

Retries within a tier handle transient errors without paying for a bigger
model. Every attempt is billed, so the wasted spend from climbing is tracked
and subtracted from nothing -- it shows up in the savings figure honestly.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import features, judge, pricing
from .config import Settings
from .providers import Completion, Provider
from .router import Router


@dataclass
class Attempt:
    tier: int
    model: str
    completion: Completion
    usable: bool
    reason: str

    def as_dict(self) -> dict:
        d = self.completion.as_dict()
        d.update({"usable": self.usable, "gate_reason": self.reason})
        return d


@dataclass
class CascadeResult:
    prompt: str
    difficulty: float
    decision_reason: str
    bucket: int
    explored: bool
    attempts: list[Attempt] = field(default_factory=list)
    answer: str = ""
    final_model: str | None = None
    ok: bool = False
    graded: bool | None = None

    cost_usd: float = 0.0
    baseline_cost_usd: float = 0.0
    wasted_cost_usd: float = 0.0
    latency_ms: float = 0.0

    escalations: int = 0
    failovers: int = 0
    retries: int = 0
    refusals: int = 0
    errors: int = 0
    simulated: bool = False

    @property
    def saved_usd(self) -> float:
        return self.baseline_cost_usd - self.cost_usd

    def as_dict(self) -> dict:
        return {
            "prompt": self.prompt,
            "difficulty": round(self.difficulty, 4),
            "bucket": self.bucket,
            "decision_reason": self.decision_reason,
            "explored": self.explored,
            "answer": self.answer,
            "final_model": self.final_model,
            "final_label": pricing.spec(self.final_model).label if self.final_model else None,
            "final_tier": pricing.tier_of(self.final_model) if self.final_model else None,
            "ok": self.ok,
            "graded": self.graded,
            "cost_usd": round(self.cost_usd, 8),
            "baseline_cost_usd": round(self.baseline_cost_usd, 8),
            "wasted_cost_usd": round(self.wasted_cost_usd, 8),
            "saved_usd": round(self.saved_usd, 8),
            "latency_ms": round(self.latency_ms, 1),
            "escalations": self.escalations,
            "failovers": self.failovers,
            "retries": self.retries,
            "refusals": self.refusals,
            "errors": self.errors,
            "simulated": self.simulated,
            "attempts": [a.as_dict() for a in self.attempts],
        }


class Cascade:
    def __init__(self, provider: Provider, router: Router, settings: Settings) -> None:
        self._provider = provider
        self._router = router
        self._settings = settings

    def run(
        self,
        prompt: str,
        *,
        expected: str | None = None,
        kind: str = "exact",
        key: str = "",
        force_model: str | None = None,
    ) -> CascadeResult:
        feats = features.extract(prompt)

        if force_model is not None:
            # Baseline mode: pin one model, no routing, no escalation. This is
            # how the benchmark measures what a naive deployment would pay.
            start_tier = pricing.tier_of(force_model)
            bucket, reason, explored = -1, f"pinned to {force_model}", False
        else:
            decision = self._router.choose(feats, key=key or prompt)
            start_tier, bucket = decision.tier, decision.bucket
            reason, explored = decision.reason, decision.explored

        result = CascadeResult(
            prompt=prompt,
            difficulty=feats.difficulty,
            decision_reason=reason,
            bucket=bucket,
            explored=explored,
        )

        meta = {"difficulty": feats.difficulty, "answer": expected}
        max_tier = start_tier if force_model is not None else pricing.MAX_TIER
        tier = start_tier
        succeeded = False

        while tier <= max_tier:
            model = pricing.model_for_tier(tier)
            tier_done = False

            for attempt_no in range(self._settings.max_attempts_per_tier):
                completion = self._provider.complete(
                    model, prompt, max_tokens=self._settings.max_tokens, meta=meta
                )
                result.cost_usd += completion.cost_usd
                result.latency_ms += completion.latency_ms
                if completion.simulated:
                    result.simulated = True

                if not completion.ok:
                    if completion.error_kind == "refusal":
                        result.refusals += 1
                    else:
                        result.errors += 1
                    result.attempts.append(
                        Attempt(tier, model, completion, False, completion.error or "error")
                    )
                    # Retry in place only for transient faults, and only if we
                    # have budget left at this tier.
                    if completion.retryable and attempt_no + 1 < self._settings.max_attempts_per_tier:
                        result.retries += 1
                        continue
                    result.failovers += 1
                    tier_done = True
                    break

                usable, why = judge.looks_usable(completion.text)
                result.attempts.append(Attempt(tier, model, completion, usable, why))
                self._record(bucket, tier, usable, expected, completion.text, kind)

                if usable:
                    result.answer = completion.text
                    result.final_model = completion.billed_model
                    result.ok = True
                    succeeded = True
                    tier_done = True
                    break

                # Answered, but not good enough. Climb.
                result.escalations += 1
                tier_done = True
                break

            if succeeded or not tier_done:
                break
            tier += 1

        # Everything except the winning call is money spent for nothing.
        if result.attempts:
            final_cost = result.attempts[-1].completion.cost_usd if result.ok else 0.0
            result.wasted_cost_usd = max(0.0, result.cost_usd - final_cost)
            # Conservative baseline: the same tokens priced at flagship rates.
            # Real flagship answers run longer, so this understates the saving.
            result.baseline_cost_usd = result.attempts[-1].completion.flagship_cost_usd

        result.graded = judge.grade_expected(expected, result.answer, kind)
        return result

    def _record(self, bucket: int, tier: int, usable: bool, expected, text: str, kind: str) -> None:
        """Feed the policy. Prefer ground truth when the item has it."""
        if bucket < 0:
            return  # pinned baseline runs must not train the policy
        verdict = judge.grade_expected(expected, text, kind)
        self._router.record(bucket, tier, usable if verdict is None else bool(verdict))
