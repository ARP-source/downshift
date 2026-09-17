"""Model registry and cost accounting.

Prices are USD per 1M tokens, Anthropic first-party API rates.
The router's entire value proposition is arithmetic on this table, so it is
kept in exactly one place and every cost number in the app derives from it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    label: str
    tier: int
    input_per_mtok: float
    output_per_mtok: float
    context: int
    # output_config.effort is rejected by Haiku 4.5 and accepted by the
    # Sonnet 5 / Opus 5 tiers. Request shaping reads this, never a model id.
    supports_effort: bool
    # Server-side refusal fallback is an Opus-5-tier / Fable feature.
    supports_server_fallback: bool


# Ordered cheap -> expensive. Tier index is the routing ladder position.
MODELS: dict[str, ModelSpec] = {
    "claude-haiku-4-5": ModelSpec(
        model_id="claude-haiku-4-5",
        label="Haiku 4.5",
        tier=0,
        input_per_mtok=1.00,
        output_per_mtok=5.00,
        context=200_000,
        supports_effort=False,
        supports_server_fallback=False,
    ),
    "claude-sonnet-5": ModelSpec(
        model_id="claude-sonnet-5",
        label="Sonnet 5",
        tier=1,
        input_per_mtok=2.00,
        output_per_mtok=10.00,
        context=1_000_000,
        supports_effort=True,
        supports_server_fallback=False,
    ),
    "claude-opus-5": ModelSpec(
        model_id="claude-opus-5",
        label="Opus 5",
        tier=2,
        input_per_mtok=5.00,
        output_per_mtok=25.00,
        context=1_000_000,
        supports_effort=True,
        supports_server_fallback=True,
    ),
}

# The escalation ladder, cheapest first.
LADDER: list[str] = ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"]

# What a naive "just use the best model" deployment would pay.
FLAGSHIP: str = "claude-opus-5"

# Cheap model used for LLM-as-judge grading of open-ended items.
JUDGE_MODEL: str = "claude-haiku-4-5"

MAX_TIER: int = len(LADDER) - 1


def spec(model_id: str) -> ModelSpec:
    try:
        return MODELS[model_id]
    except KeyError as exc:
        raise KeyError(f"unknown model {model_id!r}; known: {sorted(MODELS)}") from exc


def model_for_tier(tier: int) -> str:
    """Clamp a tier index onto the ladder."""
    return LADDER[max(0, min(MAX_TIER, tier))]


def tier_of(model_id: str) -> int:
    return spec(model_id).tier


def cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Exact USD cost of one call."""
    s = spec(model_id)
    return (
        input_tokens / 1_000_000.0 * s.input_per_mtok
        + output_tokens / 1_000_000.0 * s.output_per_mtok
    )


def flagship_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """Counterfactual: what this exact token usage would have cost on flagship.

    Used for the baseline comparison. Token counts are taken from whatever the
    router actually spent, which is conservative: flagship answers to the same
    prompts are typically longer, so real baseline cost would be higher still.
    """
    return cost_usd(FLAGSHIP, input_tokens, output_tokens)


def ladder_table() -> list[dict]:
    """Serialisable price ladder for the dashboard."""
    out = []
    for mid in LADDER:
        s = spec(mid)
        flag = spec(FLAGSHIP)
        out.append(
            {
                "model": s.model_id,
                "label": s.label,
                "tier": s.tier,
                "input_per_mtok": s.input_per_mtok,
                "output_per_mtok": s.output_per_mtok,
                "context": s.context,
                # Blended 1:1 in/out relative discount vs flagship.
                "relative_cost": round(
                    (s.input_per_mtok + s.output_per_mtok)
                    / (flag.input_per_mtok + flag.output_per_mtok),
                    4,
                ),
            }
        )
    return out
