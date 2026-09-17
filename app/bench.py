"""Benchmark: the router against two pinned baselines, on identical items.

Three arms, so the claim is bracketed from both sides:

  flagship  every request to Opus 5. What a naive deployment pays, and the
            quality ceiling the router must not fall below.
  cheapest  every request to Haiku 4.5, no escalation. The floor: shows what
            naive cost-cutting does to quality.
  router    difficulty routing with escalation and online adaptation.

Reporting only the router against flagship would hide whether the routing is
doing anything a blunt downgrade could not.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import datasets, pricing
from .cascade import Cascade
from .config import SETTINGS, Settings
from .metrics import Metrics
from .providers import build_provider
from .router import Router

ARMS = ("flagship", "cheapest", "router")
ADAPT_EVERY = 10
# The router sees the traffic mix repeatedly, as it would in production.
# One pass is not enough for any policy to learn anything: each bucket
# would only ever observe the single tier its prior already chose.
ROUTER_EPOCHS = 4

OUT_DIR = Path(__file__).resolve().parent.parent / "bench_out"


def _run_arm(name: str, items: list, settings: Settings, on_event=None, epochs: int = 1) -> dict:
    provider = build_provider(settings)
    is_router = name == "router"
    router = Router(
        quality_floor=settings.quality_floor,
        tolerance=settings.quality_tolerance,
        learn=is_router,
    )
    cascade = Cascade(provider, router, settings)
    meter = Metrics(slo_latency_ms=settings.slo_latency_ms)

    forced = {
        "flagship": pricing.FLAGSHIP,
        "cheapest": pricing.LADDER[0],
        "router": None,
    }[name]

    # Policy state persists across epochs; measurement resets each epoch so the
    # learning curve is visible instead of being averaged away.
    epoch_reports = []
    for epoch in range(epochs):
        meter = Metrics(slo_latency_ms=settings.slo_latency_ms)
        for index, item in enumerate(items):
            result = cascade.run(
                item.prompt,
                expected=item.answer,
                kind=item.kind,
                # Vary the exploration seed per epoch, or the same requests get
                # probed every pass and the evidence stays lopsided.
                key=f"{item.id}#{epoch}",
                force_model=forced,
            )
            meter.record(result)
            if is_router and (index + 1) % ADAPT_EVERY == 0:
                router.adapt()
            if on_event:
                on_event(name, index, item, result, meter)
        if is_router:
            router.adapt()
        epoch_reports.append(meter.snapshot())

    return {
        "arm": name,
        # Headline is steady state, after the policy has had a chance to learn.
        "metrics": epoch_reports[-1],
        "epochs": epoch_reports,
        "policy": router.policy_table() if is_router else None,
        "adaptations": list(router.adaptations) if is_router else [],
    }


def run_benchmark(limit: int | None = None, settings: Settings = SETTINGS, on_event=None) -> dict:
    items = datasets.load(limit)
    started = time.time()
    arms = {
        name: _run_arm(
            name, items, settings, on_event,
            epochs=ROUTER_EPOCHS if name == "router" else 1,
        )
        for name in ARMS
    }

    flagship = arms["flagship"]["metrics"]
    cheapest = arms["cheapest"]["metrics"]
    router = arms["router"]["metrics"]

    def pct_drop(new: float, old: float) -> float:
        return 0.0 if not old else (old - new) / old * 100.0

    comparison = {
        # Measured against a real flagship run, not an estimate.
        "cost_saving_vs_flagship_pct": round(
            pct_drop(router["total_cost_usd"], flagship["total_cost_usd"]), 2
        ),
        "quality_router": router["quality"],
        "quality_flagship": flagship["quality"],
        "quality_cheapest": cheapest["quality"],
        "quality_retained_pct": (
            None
            if not flagship["quality"]
            else round(router["quality"] / flagship["quality"] * 100.0, 2)
        ),
        # The honest counterweight: what blunt cost-cutting costs you.
        "cheapest_cost_saving_pct": round(
            pct_drop(cheapest["total_cost_usd"], flagship["total_cost_usd"]), 2
        ),
        "cheapest_quality_retained_pct": (
            None
            if not flagship["quality"]
            else round(cheapest["quality"] / flagship["quality"] * 100.0, 2)
        ),
        "latency_p50_change_pct": round(
            pct_drop(router["p50_latency_ms"], flagship["p50_latency_ms"]), 2
        ),
        "projected_monthly_savings_usd": router["projected_monthly_savings_usd"],
        "router_epochs": ROUTER_EPOCHS,
        "learning_curve": [
            {
                "epoch": i + 1,
                "savings_pct": round(pct_drop(e["total_cost_usd"], flagship["total_cost_usd"]), 2),
                "quality": e["quality"],
                "tier_counts": e["tier_counts"],
            }
            for i, e in enumerate(arms["router"]["epochs"])
        ],
    }

    return {
        "items": len(items),
        "provider": "mock" if settings.mock else "anthropic",
        "simulated": router.get("simulated", False),
        "quality_floor": settings.quality_floor,
        "elapsed_s": round(time.time() - started, 2),
        "dataset": datasets.summary(),
        "arms": arms,
        "comparison": comparison,
    }


def save(report: dict, name: str = "latest") -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"bench_{name}.json"
    path.write_text(json.dumps(report, indent=2))
    return path
