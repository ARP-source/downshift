"""FastAPI surface for the router dashboard."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import bench, codebench, codetasks, datasets, features, judge, pricing
from .cascade import Cascade
from .config import SETTINGS
from .metrics import Metrics
from .providers import ChaosProvider, build_provider
from .router import Router

WEB = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Cascade Router")

# Long-lived objects so the live feed accumulates across requests and the
# policy keeps learning while somebody clicks around the dashboard.
# Wrapped so failures can be injected live without restarting anything.
_provider = ChaosProvider(build_provider(SETTINGS))
_router = Router(
    quality_floor=SETTINGS.quality_floor,
    tolerance=SETTINGS.quality_tolerance,
    learn=SETTINGS.learn,
)
_cascade = Cascade(_provider, _router, SETTINGS)
_live = Metrics(slo_latency_ms=SETTINGS.slo_latency_ms)
_feed: list[dict] = []
def _load_saved(name: str) -> dict | None:
    """Rehydrate a previous run so the dashboard opens with real results.

    Demoing should not depend on a live benchmark completing in front of an
    audience. Saved reports carry their own provider field, so a restored run
    cannot silently be presented as something it was not.
    """
    path = bench.OUT_DIR / f"bench_{name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


_last_report: dict | None = _load_saved("live") or _load_saved("latest")
_last_brownout: dict | None = None
_last_code: dict | None = _load_saved("code")


class Ask(BaseModel):
    prompt: str


class BenchRequest(BaseModel):
    limit: int | None = None


class Compare(BaseModel):
    prompt: str


class Chaos(BaseModel):
    mode: str


class BrownoutRequest(BaseModel):
    limit: int | None = 30


class CodeBenchRequest(BaseModel):
    limit: int | None = None


def _state() -> dict:
    return {
        # Derived from the provider actually running, never from the config
        # flag. Setting MOCK=0 without a usable key falls back to the mock
        # provider, and a dashboard that then claims "live" would be presenting
        # simulated numbers as measured ones -- the worst failure this project
        # could have.
        "mode": "mock" if _provider.is_mock else "live",
        "requested_live": not SETTINGS.mock,
        "provider": _provider.name,
        "ladder_name": pricing.LADDER_NAME,
        "chaos_mode": _provider.mode,
        "chaos_modes": list(ChaosProvider.MODES),
        "rates_verified": pricing.RATES_VERIFIED,
        "degraded": list(getattr(_provider, "degraded", [])),
        "settings": SETTINGS.public(),
        "ladder": pricing.ladder_table(),
        "dataset": datasets.summary(),
        "policy": _router.policy_table(),
        "adaptations": list(_router.adaptations),
        "live": _live.snapshot(),
        "feed": _feed[-40:][::-1],
        "report": _last_report,
        "brownout": _last_brownout,
        "code": _last_code,
        "code_tasks": codetasks.summary(),
    }


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((WEB / "index.html").read_text(encoding="utf-8"))


@app.get("/app.js")
def appjs() -> FileResponse:
    return FileResponse(WEB / "app.js", media_type="application/javascript")


@app.get("/api/state")
def state() -> JSONResponse:
    return JSONResponse(_state())


@app.post("/api/ask")
def ask(body: Ask) -> JSONResponse:
    prompt = (body.prompt or "").strip()
    if not prompt:
        return JSONResponse({"error": "empty prompt"}, status_code=400)
    result = _cascade.run(prompt, key=prompt)
    _live.record(result)
    _router.adapt()
    payload = result.as_dict()
    _feed.append(payload)
    return JSONResponse({"result": payload, "live": _live.snapshot(), "policy": _router.policy_table()})


@app.post("/api/chaos")
def chaos(body: Chaos) -> JSONResponse:
    """Inject a provider-side failure so degradation can be demonstrated."""
    mode = _provider.set_mode((body.mode or "off").strip())
    return JSONResponse({"chaos_mode": mode, "provider": _provider.name})


@app.post("/api/compare")
def compare(body: Compare) -> JSONResponse:
    """Run one prompt on every tier at once, without routing.

    This exists so a sceptic can test the premise with their own input instead
    of taking our eval set on trust: on an easy prompt the cheap tier matches
    the flagship, on a hard one it visibly does not, and the price difference
    is right there next to both answers.
    """
    prompt = (body.prompt or "").strip()
    if not prompt:
        return JSONResponse({"error": "empty prompt"}, status_code=400)

    feats = features.extract(prompt)
    decision = _router.choose(feats, key=prompt)

    tiers = []
    for model in pricing.LADDER:
        completion = _provider.complete(
            model,
            prompt,
            max_tokens=SETTINGS.max_tokens,
            meta={"difficulty": feats.difficulty},
        )
        usable, why = judge.looks_usable(completion.text)
        row = completion.as_dict()
        row.update(
            {
                "usable": usable,
                "gate_reason": why,
                "would_route_here": pricing.tier_of(model) == decision.tier,
            }
        )
        tiers.append(row)

    flagship = next((t for t in tiers if t["model"] == pricing.FLAGSHIP), None)
    chosen = next((t for t in tiers if t["would_route_here"]), None)
    saving = None
    if flagship and chosen and flagship["cost_usd"] > 0:
        saving = round(
            (flagship["cost_usd"] - chosen["cost_usd"]) / flagship["cost_usd"] * 100.0, 1
        )

    return JSONResponse(
        {
            "prompt": prompt,
            "features": feats.as_dict(),
            "decision": decision.as_dict(),
            "tiers": tiers,
            "saving_pct": saving,
        }
    )


@app.post("/api/bench")
def run_bench(body: BenchRequest) -> JSONResponse:
    global _last_report
    report = bench.run_benchmark(limit=body.limit, settings=SETTINGS)
    bench.save(report)
    _last_report = report
    return JSONResponse(report)


@app.post("/api/brownout")
def brownout(body: BrownoutRequest) -> JSONResponse:
    global _last_brownout
    _last_brownout = bench.run_brownout(limit=body.limit or 30, settings=SETTINGS)
    return JSONResponse(_last_brownout)


@app.post("/api/codebench")
def run_codebench(body: CodeBenchRequest) -> JSONResponse:
    global _last_code
    _last_code = codebench.run_codebench(limit=body.limit, settings=SETTINGS)
    codebench.save(_last_code)
    return JSONResponse(_last_code)


@app.get("/api/report")
def report() -> JSONResponse:
    if _last_report is not None:
        return JSONResponse(_last_report)
    path = bench.OUT_DIR / "bench_latest.json"
    if path.exists():
        return JSONResponse(json.loads(path.read_text()))
    return JSONResponse({"error": "no benchmark has been run yet"}, status_code=404)


@app.get("/api/samples")
def samples() -> JSONResponse:
    """A few eval prompts across the difficulty range, for the ask box."""
    picks = ["f01", "c02", "e01", "r01", "h02", "x01", "x03", "x06"]
    by_id = {i.id: i for i in datasets.ITEMS}
    return JSONResponse(
        [by_id[p].as_dict() for p in picks if p in by_id]
    )
