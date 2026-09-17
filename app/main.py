"""FastAPI surface for the router dashboard."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import bench, datasets, pricing
from .cascade import Cascade
from .config import SETTINGS
from .metrics import Metrics
from .providers import build_provider
from .router import Router

WEB = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Cascade Router")

# Long-lived objects so the live feed accumulates across requests and the
# policy keeps learning while somebody clicks around the dashboard.
_provider = build_provider(SETTINGS)
_router = Router(
    quality_floor=SETTINGS.quality_floor,
    tolerance=SETTINGS.quality_tolerance,
    learn=SETTINGS.learn,
)
_cascade = Cascade(_provider, _router, SETTINGS)
_live = Metrics(slo_latency_ms=SETTINGS.slo_latency_ms)
_feed: list[dict] = []
_last_report: dict | None = None


class Ask(BaseModel):
    prompt: str


class BenchRequest(BaseModel):
    limit: int | None = None


def _state() -> dict:
    return {
        "mode": "mock" if SETTINGS.mock else "live",
        "provider": _provider.name,
        "degraded": list(getattr(_provider, "degraded", [])),
        "settings": SETTINGS.public(),
        "ladder": pricing.ladder_table(),
        "dataset": datasets.summary(),
        "policy": _router.policy_table(),
        "adaptations": list(_router.adaptations),
        "live": _live.snapshot(),
        "feed": _feed[-40:][::-1],
        "report": _last_report,
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


@app.post("/api/bench")
def run_bench(body: BenchRequest) -> JSONResponse:
    global _last_report
    report = bench.run_benchmark(limit=body.limit, settings=SETTINGS)
    bench.save(report)
    _last_report = report
    return JSONResponse(report)


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
