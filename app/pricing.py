"""Model registry and cost accounting.

Prices are USD per 1M tokens, Anthropic first-party API rates.
The router's entire value proposition is arithmetic on this table, so it is
kept in exactly one place and every cost number in the app derives from it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# This module reads LADDER at import time, and it is imported before config.py
# in several paths -- so it cannot rely on config having loaded the .env file
# yet. Loading here too is idempotent and keeps the ladder choice honest no
# matter which module the process touches first. Without this, a LADDER set in
# .env is silently ignored and the default ladder is used instead.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:  # pragma: no cover
    pass


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
CLAUDE_MODELS: dict[str, ModelSpec] = {
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

# Second ladder: open models served through the W&B Inference endpoint, which
# is OpenAI-compatible rather than Anthropic-compatible. Prices are W&B list
# rates per million tokens. The spread here is far wider than the Claude
# ladder -- roughly 33x cheapest to flagship against 5x -- which makes the
# routing decision matter more, not less.
WANDB_MODELS: dict[str, ModelSpec] = {
    "openai/gpt-oss-20b": ModelSpec(
        model_id="openai/gpt-oss-20b",
        label="GPT-OSS 20B",
        tier=0,
        input_per_mtok=0.03,
        output_per_mtok=0.13,
        context=131_000,
        supports_effort=False,
        supports_server_fallback=False,
    ),
    "Qwen/Qwen3.6-35B-A3B": ModelSpec(
        model_id="Qwen/Qwen3.6-35B-A3B",
        label="Qwen3.6 35B",
        tier=1,
        input_per_mtok=0.25,
        output_per_mtok=1.25,
        context=262_000,
        supports_effort=False,
        supports_server_fallback=False,
    ),
    "deepseek-ai/DeepSeek-V4-Pro-0813": ModelSpec(
        model_id="deepseek-ai/DeepSeek-V4-Pro-0813",
        label="DeepSeek V4-Pro",
        tier=2,
        input_per_mtok=1.31,
        output_per_mtok=3.96,
        context=1_049_000,
        supports_effort=False,
        supports_server_fallback=False,
    ),
}

# Featherless serves open-weight models through an OpenAI-compatible endpoint
# and bills input and output separately per million tokens, but publishes the
# rate on each model page rather than in one table. These defaults are
# PLACEHOLDERS spanning three parameter-size classes; they are flagged
# unverified until overridden, because a guessed price would silently corrupt
# every number this project reports.
#
# Override with, for example:
#   FEATHERLESS_RATES="meta-llama/Llama-3.1-8B-Instruct:0.10:0.10,Qwen/Qwen3.8-27B:0.40:0.40,deepseek-ai/DeepSeek-V4.1-Flash:1.20:1.20"
FEATHERLESS_DEFAULTS = [
    ("meta-llama/Llama-3.1-8B-Instruct", "Llama 3.1 8B", 0.10, 0.10, 32_000),
    ("Qwen/Qwen3.8-27B", "Qwen3.8 27B", 0.40, 0.40, 256_000),
    ("deepseek-ai/DeepSeek-V4.1-Flash", "DeepSeek V4.1 Flash", 1.20, 1.20, 256_000),
]

RATES_VERIFIED: bool = True


def _parse_featherless_rates() -> tuple[list[tuple], bool]:
    """Read FEATHERLESS_RATES if present. Returns (rows, verified)."""
    raw = os.getenv("FEATHERLESS_RATES", "").strip()
    if not raw:
        return FEATHERLESS_DEFAULTS, False
    rows = []
    for index, chunk in enumerate(raw.split(",")):
        parts = chunk.strip().rsplit(":", 2)
        if len(parts) != 3:
            # Malformed input must not silently fall back to fake prices.
            raise ValueError(
                f"FEATHERLESS_RATES entry {index + 1} is not model:input:output -- got {chunk!r}"
            )
        model_id, inp, out = parts[0].strip(), float(parts[1]), float(parts[2])
        label = model_id.split("/")[-1]
        default_ctx = FEATHERLESS_DEFAULTS[min(index, 2)][4]
        rows.append((model_id, label, inp, out, default_ctx))
    if len(rows) != 3:
        raise ValueError(f"FEATHERLESS_RATES needs exactly 3 tiers, got {len(rows)}")
    return rows, True


_fl_rows, _fl_verified = _parse_featherless_rates()

FEATHERLESS_MODELS: dict[str, ModelSpec] = {
    model_id: ModelSpec(
        model_id=model_id,
        label=label,
        tier=tier,
        input_per_mtok=inp,
        output_per_mtok=out,
        context=ctx,
        supports_effort=False,
        supports_server_fallback=False,
    )
    for tier, (model_id, label, inp, out, ctx) in enumerate(_fl_rows)
}

_LADDERS = {
    "claude": (
        CLAUDE_MODELS,
        ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"],
        "claude-opus-5",
        "claude-haiku-4-5",
    ),
    "wandb": (
        WANDB_MODELS,
        ["openai/gpt-oss-20b", "Qwen/Qwen3.6-35B-A3B", "deepseek-ai/DeepSeek-V4-Pro-0813"],
        "deepseek-ai/DeepSeek-V4-Pro-0813",
        "openai/gpt-oss-20b",
    ),
    "featherless": (
        FEATHERLESS_MODELS,
        [row[0] for row in _fl_rows],
        _fl_rows[2][0],
        _fl_rows[0][0],
    ),
}

LADDER_NAME: str = os.getenv("LADDER", "claude").strip().lower()
if LADDER_NAME not in _LADDERS:
    LADDER_NAME = "claude"

MODELS, LADDER, FLAGSHIP, JUDGE_MODEL = _LADDERS[LADDER_NAME]

# Claude and W&B rates come from published rate cards. Featherless publishes
# per model page, so its rates count as verified only when supplied explicitly.
if LADDER_NAME == "featherless":
    RATES_VERIFIED = _fl_verified

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
