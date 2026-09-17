"""Running measurement of what the router is actually doing.

Every headline number the demo claims is computed here from observed token
counts and the price table -- nothing is asserted that was not measured.

Two accounting rules worth stating plainly:
  * Escalation is not free. When a cheap attempt fails and we retry higher,
    the wasted cheap call is still billed and still counted.
  * Judge cost is tracked separately and never netted out of savings.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import pricing


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(round((q / 100.0) * (len(ordered) - 1)))
    return ordered[max(0, min(len(ordered) - 1, idx))]


@dataclass
class Metrics:
    slo_latency_ms: float = 8000.0

    requests: int = 0
    graded: int = 0
    correct: int = 0

    # Cost, in USD, from measured tokens.
    actual_cost_usd: float = 0.0
    baseline_cost_usd: float = 0.0
    judge_cost_usd: float = 0.0
    wasted_cost_usd: float = 0.0

    # Reliability / behaviour counters.
    calls: int = 0
    escalations: int = 0
    failovers: int = 0
    refusals: int = 0
    errors: int = 0
    explorations: int = 0
    unresolved: int = 0
    slo_met: int = 0

    latencies_ms: list[float] = field(default_factory=list)
    tier_counts: dict[str, int] = field(default_factory=dict)
    simulated: bool = False

    def record(self, result) -> None:
        """Absorb one CascadeResult."""
        self.requests += 1
        self.actual_cost_usd += result.cost_usd
        self.baseline_cost_usd += result.baseline_cost_usd
        self.wasted_cost_usd += result.wasted_cost_usd
        self.calls += len(result.attempts)
        self.escalations += result.escalations
        self.failovers += result.failovers
        self.refusals += result.refusals
        self.errors += result.errors
        self.latencies_ms.append(result.latency_ms)
        if result.latency_ms <= self.slo_latency_ms:
            self.slo_met += 1
        if result.explored:
            self.explorations += 1
        if not result.ok:
            self.unresolved += 1
        if result.simulated:
            self.simulated = True

        label = pricing.spec(result.final_model).label if result.final_model else "none"
        self.tier_counts[label] = self.tier_counts.get(label, 0) + 1

        if result.graded is not None:
            self.graded += 1
            if result.graded:
                self.correct += 1

    def add_judge_cost(self, usd: float) -> None:
        self.judge_cost_usd += usd

    @property
    def total_cost_usd(self) -> float:
        """What the deployment really pays, judging included."""
        return self.actual_cost_usd + self.judge_cost_usd

    @property
    def savings_pct(self) -> float:
        if self.baseline_cost_usd <= 0:
            return 0.0
        return (self.baseline_cost_usd - self.actual_cost_usd) / self.baseline_cost_usd * 100.0

    @property
    def savings_pct_with_judge(self) -> float:
        if self.baseline_cost_usd <= 0:
            return 0.0
        return (self.baseline_cost_usd - self.total_cost_usd) / self.baseline_cost_usd * 100.0

    @property
    def quality(self) -> float | None:
        return self.correct / self.graded if self.graded else None

    def projected_savings_usd(self, volume: int = 1_000_000) -> float:
        """Extrapolate the measured per-request delta to a monthly volume."""
        if self.requests <= 0:
            return 0.0
        per_request = (self.baseline_cost_usd - self.total_cost_usd) / self.requests
        return per_request * volume

    def snapshot(self) -> dict:
        return {
            "requests": self.requests,
            "calls": self.calls,
            "calls_per_request": round(self.calls / self.requests, 3) if self.requests else 0,
            "actual_cost_usd": round(self.actual_cost_usd, 6),
            "baseline_cost_usd": round(self.baseline_cost_usd, 6),
            "judge_cost_usd": round(self.judge_cost_usd, 6),
            "wasted_cost_usd": round(self.wasted_cost_usd, 6),
            "total_cost_usd": round(self.total_cost_usd, 6),
            "savings_pct": round(self.savings_pct, 2),
            "savings_pct_with_judge": round(self.savings_pct_with_judge, 2),
            "quality": None if self.quality is None else round(self.quality, 4),
            "graded": self.graded,
            "correct": self.correct,
            "p50_latency_ms": round(percentile(self.latencies_ms, 50), 1),
            "p95_latency_ms": round(percentile(self.latencies_ms, 95), 1),
            "slo_latency_ms": self.slo_latency_ms,
            "slo_pct": round(self.slo_met / self.requests * 100.0, 2) if self.requests else 0.0,
            "escalations": self.escalations,
            "failovers": self.failovers,
            "refusals": self.refusals,
            "errors": self.errors,
            "explorations": self.explorations,
            "unresolved": self.unresolved,
            "tier_counts": dict(self.tier_counts),
            "projected_monthly_savings_usd": round(self.projected_savings_usd(), 2),
            "simulated": self.simulated,
        }
