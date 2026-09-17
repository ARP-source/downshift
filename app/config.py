"""Runtime configuration, read from the environment (.env is loaded if present).

Design rule: the app must always boot. With no API key it falls back to the
deterministic mock provider rather than crashing, so the dashboard and the
benchmark are demoable before credentials exist.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict

try:  # optional at import time so modules load before `pip install`
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:  # pragma: no cover
    pass


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _num(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    return int(_num(name, default))


@dataclass(frozen=True)
class Settings:
    # --- credentials / mode ---
    has_api_key: bool
    mock: bool

    # --- request shaping ---
    max_tokens: int
    effort: str
    timeout_s: float

    # --- reliability ---
    server_fallback: bool
    max_attempts_per_tier: int

    # --- routing policy ---
    quality_floor: float
    quality_tolerance: float
    learn: bool
    slo_latency_ms: float

    # --- grading ---
    judge_enabled: bool

    def public(self) -> dict:
        """Safe to serialise to the dashboard: contains no secret material."""
        return asdict(self)


def load_settings() -> Settings:
    # The SDK resolves credentials itself (env var, then OAuth profile), so we
    # only need to know *whether* something is available to pick the default mode.
    has_key = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    return Settings(
        has_api_key=has_key,
        # No key -> mock, so `uvicorn app.main:app` always works.
        mock=_flag("MOCK", not has_key),
        max_tokens=_int("MAX_TOKENS", 512),
        # Cost routing wants short, decisive answers. Low effort is the
        # recommended lever over disabling thinking outright.
        effort=os.getenv("EFFORT", "low").strip() or "low",
        timeout_s=_num("TIMEOUT_S", 30.0),
        server_fallback=_flag("ENABLE_SERVER_FALLBACK", True),
        max_attempts_per_tier=_int("MAX_ATTEMPTS_PER_TIER", 2),
        # Absolute safety net only. If even the best tier in a bucket scores
        # below this, stop trying to save money there and use the top tier.
        quality_floor=_num("QUALITY_FLOOR", 0.50),
        # The real constraint, and it is relative: a tier is acceptable if it
        # lands within this margin of the BEST tier observed in that bucket.
        # An absolute floor is unusable because it can sit above what even the
        # flagship model achieves, which makes every tier look like a failure
        # and ratchets the whole policy to the most expensive option.
        quality_tolerance=_num("QUALITY_TOLERANCE", 0.05),
        learn=_flag("ENABLE_LEARNING", True),
        slo_latency_ms=_num("SLO_LATENCY_MS", 8000.0),
        judge_enabled=_flag("ENABLE_LLM_JUDGE", False),
    )


SETTINGS = load_settings()
