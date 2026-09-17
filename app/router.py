"""Tier selection policy with an online feedback loop.

The policy is a lookup table from difficulty bucket to starting ladder tier.
It adapts while serving, which needs counterfactual data: we only observe the
tier we actually ran, so we cannot tell whether a cheaper tier would have
sufficed. That is solved with epsilon-greedy downward exploration -- a small
fraction of requests deliberately try one tier below the policy, and their
outcomes are what let the policy ratchet cost down safely.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from . import pricing
from .features import Features

# Difficulty is bucketed rather than thresholded so the policy can be read,
# logged and displayed as a small table.
N_BUCKETS = 5

# Sensible prior. Adaptation refines it from observed outcomes.
INITIAL_START_TIERS: list[int] = [0, 0, 1, 1, 2]

# Do not move a bucket on thin evidence.
MIN_SAMPLES = 6

# Share of requests that probe one tier cheaper than the policy says. This
# is the only source of counterfactual evidence -- without it the policy can
# never learn that a cheaper tier would have sufficed, because it never sees
# that tier fail or succeed. Too low and the policy is frozen at its prior.
EXPLORE_RATE = 0.20


def bucket_of(difficulty: float) -> int:
    return max(0, min(N_BUCKETS - 1, int(difficulty * N_BUCKETS)))


def bucket_label(b: int) -> str:
    lo = b / N_BUCKETS
    hi = (b + 1) / N_BUCKETS
    return f"{lo:.1f}-{hi:.1f}"


@dataclass
class CellStats:
    """Outcomes for one (difficulty bucket, tier) pair."""

    attempts: int = 0
    successes: int = 0

    @property
    def success_rate(self) -> float | None:
        return self.successes / self.attempts if self.attempts else None

    def as_dict(self) -> dict:
        return {
            "attempts": self.attempts,
            "successes": self.successes,
            "success_rate": None if not self.attempts else round(self.successes / self.attempts, 4),
        }


@dataclass
class Decision:
    bucket: int
    tier: int
    model: str
    explored: bool
    reason: str

    def as_dict(self) -> dict:
        return {
            "bucket": self.bucket,
            "bucket_label": bucket_label(self.bucket),
            "tier": self.tier,
            "model": self.model,
            "label": pricing.spec(self.model).label,
            "explored": self.explored,
            "reason": self.reason,
        }


@dataclass
class Router:
    quality_floor: float = 0.50
    tolerance: float = 0.05
    learn: bool = True
    explore_rate: float = EXPLORE_RATE
    start_tier: list[int] = field(default_factory=lambda: list(INITIAL_START_TIERS))
    stats: dict[tuple[int, int], CellStats] = field(default_factory=dict)
    adaptations: list[dict] = field(default_factory=list)
    _seen: int = 0

    # --- selection -------------------------------------------------------
    def _cell(self, bucket: int, tier: int) -> CellStats:
        return self.stats.setdefault((bucket, tier), CellStats())

    def _should_explore(self, key: str) -> bool:
        if not self.learn or self.explore_rate <= 0:
            return False
        # Deterministic per request so a replayed benchmark reproduces exactly.
        digest = hashlib.sha256(f"explore|{key}".encode()).digest()
        return int.from_bytes(digest[:8], "big") / 2**64 < self.explore_rate

    def choose(self, feats: Features, key: str = "") -> Decision:
        self._seen += 1
        b = bucket_of(feats.difficulty)
        tier = self.start_tier[b]
        explored = False
        reason = f"policy: bucket {bucket_label(b)} starts at tier {tier}"

        if tier > 0 and self._should_explore(key or str(self._seen)):
            tier -= 1
            explored = True
            reason = f"exploring tier {tier} to test whether it is good enough"

        return Decision(
            bucket=b,
            tier=tier,
            model=pricing.model_for_tier(tier),
            explored=explored,
            reason=reason,
        )

    # --- feedback --------------------------------------------------------
    def record(self, bucket: int, tier: int, success: bool) -> None:
        cell = self._cell(bucket, tier)
        cell.attempts += 1
        if success:
            cell.successes += 1

    def adapt(self) -> list[dict]:
        """Move each bucket to the cheapest tier that is good enough.

        "Good enough" is relative: within `tolerance` of the best tier actually
        observed in that bucket. Judging tiers against an absolute floor fails
        badly when the floor exceeds what the best model achieves -- every tier
        then looks like a failure and the policy ratchets to the most expensive
        option, destroying the savings it exists to produce.
        """
        if not self.learn:
            return []
        changes: list[dict] = []
        for b in range(N_BUCKETS):
            cur = self.start_tier[b]

            # Only tiers with enough evidence get a vote.
            rates = {}
            for t in range(len(pricing.LADDER)):
                cell = self.stats.get((b, t))
                if cell and cell.attempts >= MIN_SAMPLES and cell.success_rate is not None:
                    rates[t] = cell.success_rate
            if not rates:
                continue

            best_tier = max(rates, key=lambda k: rates[k])
            best_rate = rates[best_tier]

            if best_rate < self.quality_floor:
                # Nothing here works well. Stop optimising cost; take the best.
                target = max(rates, key=lambda k: (rates[k], k))
                why = f"best observed tier only reaches {best_rate:.2f}, below the absolute floor {self.quality_floor:.2f}"
            else:
                acceptable = [t for t, rate in rates.items() if rate >= best_rate - self.tolerance]
                target = min(acceptable)
                why = (
                    f"tier {target} holds {rates[target]:.2f} against best {best_rate:.2f} "
                    f"in this bucket, within tolerance {self.tolerance:.2f}"
                )

            if target != cur:
                self.start_tier[b] = target
                changes.append(
                    {
                        "bucket": b,
                        "bucket_label": bucket_label(b),
                        "from": cur,
                        "to": target,
                        "direction": "down" if target < cur else "up",
                        "why": why,
                    }
                )

        self.adaptations.extend(changes)
        return changes

    # --- introspection ---------------------------------------------------
    def policy_table(self) -> list[dict]:
        rows = []
        for b in range(N_BUCKETS):
            row = {
                "bucket": b,
                "bucket_label": bucket_label(b),
                "start_tier": self.start_tier[b],
                "start_model": pricing.spec(pricing.model_for_tier(self.start_tier[b])).label,
                "tiers": {},
            }
            for t in range(len(pricing.LADDER)):
                cell = self.stats.get((b, t))
                row["tiers"][pricing.spec(pricing.model_for_tier(t)).label] = (
                    cell.as_dict() if cell else {"attempts": 0, "successes": 0, "success_rate": None}
                )
            rows.append(row)
        return rows
