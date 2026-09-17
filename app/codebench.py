"""Generate code with each arm, then run it against test cases.

Grading here is execution, not comparison: the model writes a function, we call
it with known inputs and check the outputs. There is no marking scheme to
dispute and no partial credit.

Safety note. Model-generated code is executed, so it runs in a separate
process, in a temporary directory, under a wall-clock timeout, and its result
comes back as one line of JSON on stdout. It is never exec'd in this process.
That is isolation, not a sandbox: it can still touch the filesystem the user
can touch. Acceptable for algorithm exercises produced by mainstream models on
a machine you control; it is not a control for hostile code.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import codetasks, pricing
from .cascade import Cascade
from .config import SETTINGS, Settings
from .metrics import Metrics
from .providers import build_provider
from .router import Router

ARMS = ("flagship", "cheapest", "router")
EXEC_TIMEOUT_S = 8

_FENCE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)

HARNESS = '''
import json, math, sys

{code}

def _same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-9)
        except (TypeError, ValueError):
            return False
    return a == b

_tests = {tests!r}
_passed = 0
_errors = []
for _args, _expected in _tests:
    try:
        _got = {func}(*_args)
        if _same(_got, _expected):
            _passed += 1
        else:
            _errors.append("got {{!r}} want {{!r}}".format(_got, _expected))
    except Exception as exc:
        _errors.append("{{}}: {{}}".format(type(exc).__name__, exc))
print(json.dumps({{"passed": _passed, "total": len(_tests), "errors": _errors[:3]}}))
'''


def extract_code(text: str) -> str:
    """Pull a function definition out of whatever the model returned."""
    if not text:
        return ""
    fenced = _FENCE.search(text)
    if fenced:
        return fenced.group(1).strip()
    # Unfenced: drop any prose before the first def / import line.
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(("def ", "import ", "from ", "class ")):
            return "\n".join(lines[index:]).strip()
    return text.strip()


def run_tests(code: str, func: str, tests: list[tuple]) -> dict:
    """Execute the candidate in a separate process. Never raises."""
    if not code.strip():
        return {"passed": 0, "total": len(tests), "errors": ["no code produced"]}

    workdir = Path(tempfile.mkdtemp(prefix="downshift_code_"))
    try:
        script = workdir / "candidate.py"
        script.write_text(HARNESS.format(code=code, tests=tests, func=func), encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                timeout=EXEC_TIMEOUT_S,
                cwd=str(workdir),
            )
        except subprocess.TimeoutExpired:
            return {"passed": 0, "total": len(tests), "errors": ["timed out"]}

        out = (proc.stdout or "").strip().splitlines()
        if not out:
            err = (proc.stderr or "").strip().splitlines()
            return {
                "passed": 0,
                "total": len(tests),
                "errors": [err[-1][:160]] if err else ["no output"],
            }
        try:
            return json.loads(out[-1])
        except json.JSONDecodeError:
            return {"passed": 0, "total": len(tests), "errors": ["unparseable result"]}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _run_arm(name: str, tasks: list, settings: Settings) -> dict:
    provider = build_provider(settings)
    router = Router(
        quality_floor=settings.quality_floor,
        tolerance=settings.quality_tolerance,
        learn=(name == "router"),
    )
    cascade = Cascade(provider, router, settings)
    meter = Metrics(slo_latency_ms=settings.slo_latency_ms)
    forced = {"flagship": pricing.FLAGSHIP, "cheapest": pricing.LADDER[0], "router": None}[name]

    rows = []
    solved = 0
    for task in tasks:
        result = cascade.run(
            task.prompt,
            expected=None,  # nothing to string-match; execution is the grade
            kind="open",
            key=task.id,
            force_model=forced,
        )
        meter.record(result)
        graded = run_tests(extract_code(result.answer), task.func, task.tests)
        ok = graded["total"] > 0 and graded["passed"] == graded["total"]
        solved += 1 if ok else 0
        rows.append(
            {
                "id": task.id,
                "title": task.title,
                "level": task.level,
                "difficulty": round(result.difficulty, 3),
                "model": result.final_model,
                "label": pricing.spec(result.final_model).label if result.final_model else None,
                "solved": ok,
                "passed": graded["passed"],
                "total": graded["total"],
                "errors": graded.get("errors", []),
                "cost_usd": round(result.cost_usd, 8),
                "baseline_cost_usd": round(result.baseline_cost_usd, 8),
                "latency_ms": round(result.latency_ms, 1),
                "escalations": result.escalations,
            }
        )

    snap = meter.snapshot()
    by_level: dict[str, dict] = {}
    for row in rows:
        bucket = by_level.setdefault(row["level"], {"solved": 0, "total": 0, "cost_usd": 0.0})
        bucket["total"] += 1
        bucket["solved"] += 1 if row["solved"] else 0
        bucket["cost_usd"] = round(bucket["cost_usd"] + row["cost_usd"], 8)

    return {
        "arm": name,
        "solved": solved,
        "tasks": len(tasks),
        "solve_rate": round(solved / len(tasks), 4) if tasks else 0.0,
        "cost_usd": round(snap["total_cost_usd"], 8),
        "p50_latency_ms": snap["p50_latency_ms"],
        "calls": snap["calls"],
        "by_level": by_level,
        "rows": rows,
        "policy": router.policy_table() if name == "router" else None,
    }


def run_codebench(limit: int | None = None, settings: Settings = SETTINGS) -> dict:
    tasks = codetasks.load(limit)
    started = time.time()
    arms = {name: _run_arm(name, tasks, settings) for name in ARMS}

    flagship, cheapest, router = arms["flagship"], arms["cheapest"], arms["router"]

    def drop(new: float, old: float) -> float:
        return 0.0 if not old else (old - new) / old * 100.0

    # Does our difficulty score line up with the externally assigned level?
    # If it does not, the score is arbitrary and should be called so.
    level_difficulty: dict[str, list[float]] = {}
    for row in router["rows"]:
        level_difficulty.setdefault(row["level"], []).append(row["difficulty"])
    alignment = {
        level: round(sum(vals) / len(vals), 3) for level, vals in level_difficulty.items()
    }

    return {
        "tasks": len(tasks),
        "provider": "mock" if settings.mock else "live",
        "elapsed_s": round(time.time() - started, 1),
        "dataset": codetasks.summary(),
        "arms": arms,
        "comparison": {
            "cost_saving_vs_flagship_pct": round(drop(router["cost_usd"], flagship["cost_usd"]), 2),
            "solve_rate_router": router["solve_rate"],
            "solve_rate_flagship": flagship["solve_rate"],
            "solve_rate_cheapest": cheapest["solve_rate"],
            "solve_rate_retained_pct": (
                None
                if not flagship["solve_rate"]
                else round(router["solve_rate"] / flagship["solve_rate"] * 100.0, 1)
            ),
            "cheapest_cost_saving_pct": round(drop(cheapest["cost_usd"], flagship["cost_usd"]), 2),
            "cheapest_solve_rate_retained_pct": (
                None
                if not flagship["solve_rate"]
                else round(cheapest["solve_rate"] / flagship["solve_rate"] * 100.0, 1)
            ),
            "mean_difficulty_by_level": alignment,
        },
    }


def save(report: dict, name: str = "code") -> Path:
    from .bench import OUT_DIR

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"bench_{name}.json"
    path.write_text(json.dumps(report, indent=2))
    return path
