"""Model invocation behind a single interface.

Two implementations:

  AnthropicProvider -- real calls through the official Anthropic SDK.
  MockProvider      -- deterministic offline stand-in so the router, the
                       dashboard and the benchmark all run with no API key and
                       no spend. Its latency and correctness are *simulated*;
                       every Completion it returns is flagged simulated=True
                       and the UI labels those numbers accordingly.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Protocol

from . import pricing
from .config import Settings

SYSTEM_PROMPT = (
    "You are a precise assistant inside an automated pipeline. "
    "Reply with the final answer only: no preamble, no restatement of the "
    "question, no explanation unless the question explicitly asks for one. "
    "If the question has a short factual answer, reply with only that answer."
)

# Error kinds worth retrying or failing over to another tier. A refusal or a
# malformed request is not in here -- retrying those just burns money.
RETRYABLE = frozenset({"timeout", "rate_limit", "transport", "server"})


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass
class Completion:
    model: str
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    ok: bool = True
    error: str | None = None
    error_kind: str | None = None
    stop_reason: str | None = None
    # Populated when server-side fallback served a different model than asked.
    served_by: str | None = None
    simulated: bool = False

    @property
    def billed_model(self) -> str:
        return self.served_by or self.model

    @property
    def cost_usd(self) -> float:
        return pricing.cost_usd(self.billed_model, self.input_tokens, self.output_tokens)

    @property
    def flagship_cost_usd(self) -> float:
        """What these same tokens would have cost on the flagship model."""
        return pricing.flagship_cost_usd(self.input_tokens, self.output_tokens)

    @property
    def retryable(self) -> bool:
        return (not self.ok) and (self.error_kind in RETRYABLE)

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "billed_model": self.billed_model,
            "label": pricing.spec(self.billed_model).label,
            "tier": pricing.tier_of(self.billed_model),
            "text": self.text,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": round(self.latency_ms, 1),
            "cost_usd": self.cost_usd,
            "flagship_cost_usd": self.flagship_cost_usd,
            "ok": self.ok,
            "error": self.error,
            "error_kind": self.error_kind,
            "stop_reason": self.stop_reason,
            "simulated": self.simulated,
        }


class Provider(Protocol):
    name: str

    def complete(
        self, model: str, prompt: str, *, max_tokens: int, meta: dict | None = None
    ) -> Completion: ...


class AnthropicProvider:
    """Real inference. One call per complete(); the cascade owns retry policy."""

    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        import anthropic  # imported lazily so the app boots without the package

        self._sdk = anthropic
        # The SDK resolves credentials itself (ANTHROPIC_API_KEY, then an
        # "ant auth login" profile), so we never handle the key directly.
        # max_retries=1: the cascade decides when to escalate vs retry.
        self._client = anthropic.Anthropic(timeout=settings.timeout_s, max_retries=1)
        self._settings = settings
        self._server_fallback = settings.server_fallback

    def _kwargs(self, model: str, prompt: str, max_tokens: int) -> dict:
        spec = pricing.spec(model)
        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        }
        # Haiku 4.5 rejects output_config.effort; the Sonnet 5 / Opus 5 tiers
        # accept it. Low effort is the cost lever here, in preference to
        # disabling thinking outright.
        if spec.supports_effort:
            kwargs["output_config"] = {"effort": self._settings.effort}
        return kwargs

    def _fail(self, model: str, t0: float, kind: str, exc: Exception) -> Completion:
        return Completion(
            model=model,
            ok=False,
            error=f"{type(exc).__name__}: {exc}"[:300],
            error_kind=kind,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )

    def complete(
        self, model: str, prompt: str, *, max_tokens: int, meta: dict | None = None
    ) -> Completion:
        kwargs = self._kwargs(model, prompt, max_tokens)
        spec = pricing.spec(model)
        want_fallback = self._server_fallback and spec.supports_server_fallback
        t0 = time.perf_counter()

        try:
            if want_fallback:
                try:
                    # Server-side refusal fallback: the API routes around a
                    # refusal instead of handing back a dead turn.
                    resp = self._client.beta.messages.create(
                        betas=["server-side-fallback-2026-07-01"],
                        fallbacks="default",
                        **kwargs,
                    )
                except self._sdk.BadRequestError:
                    # Beta not enabled for this account. Stop asking for it.
                    self._server_fallback = False
                    resp = self._client.messages.create(**kwargs)
            else:
                resp = self._client.messages.create(**kwargs)
        # Most specific first: NotFoundError and RateLimitError subclass
        # APIStatusError, and APITimeoutError subclasses APIConnectionError.
        except self._sdk.NotFoundError as exc:
            return self._fail(model, t0, "not_found", exc)
        except self._sdk.RateLimitError as exc:
            return self._fail(model, t0, "rate_limit", exc)
        except self._sdk.APITimeoutError as exc:
            return self._fail(model, t0, "timeout", exc)
        except self._sdk.APIStatusError as exc:
            status = getattr(exc, "status_code", 0) or 0
            return self._fail(model, t0, "server" if status >= 500 else "api", exc)
        except self._sdk.APIConnectionError as exc:
            return self._fail(model, t0, "transport", exc)

        latency = (time.perf_counter() - t0) * 1000.0
        usage = getattr(resp, "usage", None)
        in_tok = int(getattr(usage, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        stop = getattr(resp, "stop_reason", None)

        # Refusals come back HTTP 200. Check stop_reason before touching
        # content, or you read an empty block and report it as an answer.
        if stop == "refusal":
            details = getattr(resp, "stop_details", None)
            category = getattr(details, "category", None)
            return Completion(
                model=model,
                ok=False,
                error=f"refusal ({category})",
                error_kind="refusal",
                stop_reason=stop,
                input_tokens=in_tok,
                output_tokens=out_tok,
                latency_ms=latency,
            )

        text = "".join(
            getattr(b, "text", "")
            for b in getattr(resp, "content", [])
            if getattr(b, "type", None) == "text"
        ).strip()

        # If server-side fallback served another model, bill that one -- but
        # only trust the id if it is one we have a price for.
        reported = getattr(resp, "model", None)
        served = reported if reported in pricing.MODELS and reported != model else None

        return Completion(
            model=model,
            text=text,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=latency,
            ok=bool(text),
            error=None if text else "empty response",
            error_kind=None if text else "empty",
            stop_reason=stop,
            served_by=served,
        )


class MockProvider:
    """Deterministic offline provider.

    Correctness is modelled as a function of (tier capability - difficulty), so
    cheap tiers genuinely fail hard prompts and the escalation path gets
    exercised. Same prompt plus same model always yields the same outcome, so
    benchmark runs are reproducible.
    """

    name = "mock"

    # Competence of each ladder tier, on the same calibrated 0..1 scale as
    # features.difficulty. Flagship exceeds 1.0 so that it still answers the
    # hardest items most of the time rather than capping the whole system's
    # achievable quality. Retuned together with features.CALIBRATION_GAIN.
    CAPABILITY = (0.40, 0.72, 1.05)
    BASE_LATENCY_MS = (350.0, 900.0, 2100.0)
    # Bigger models are more verbose, which makes the flagship baseline
    # genuinely more expensive rather than only nominally so.
    VERBOSITY = (1.0, 1.35, 1.8)
    TRANSIENT_RATE = 0.015

    def __init__(self, settings: Settings, speed: float = 0.03) -> None:
        self._settings = settings
        # Wall-clock sleep is scaled down so a 60-item benchmark finishes in
        # seconds while the dashboard still animates. Reported latency is the
        # full simulated figure.
        self._speed = speed

    @staticmethod
    def _u(seed: str, salt: str) -> float:
        digest = hashlib.sha256(f"{salt}|{seed}".encode()).digest()
        return int.from_bytes(digest[:8], "big") / 2**64

    def _sleep(self, latency_ms: float) -> None:
        if self._speed > 0:
            time.sleep(latency_ms / 1000.0 * self._speed)

    def _wrong(self, answer: str, seed: str) -> str:
        t = answer.strip()
        try:
            val = float(t.replace(",", ""))
        except ValueError:
            pass
        else:
            delta = 1 + int(self._u(seed, "delta") * 9)
            if float(int(val)) == val:
                return str(int(val) + delta)
            return f"{val * (1 + 0.1 * delta):.2f}"
        flip = {"yes": "no", "no": "yes", "true": "false", "false": "true"}
        if t.lower() in flip:
            return flip[t.lower()]
        return "unclear"

    def complete(
        self, model: str, prompt: str, *, max_tokens: int, meta: dict | None = None
    ) -> Completion:
        meta = meta or {}
        tier = pricing.tier_of(model)
        difficulty = float(meta.get("difficulty", 0.4))
        answer = meta.get("answer")
        seed = f"{model}|{prompt}"

        if self._u(seed, "fail") < self.TRANSIENT_RATE:
            kind = "timeout" if self._u(seed, "kind") < 0.5 else "rate_limit"
            latency = self.BASE_LATENCY_MS[tier] * 1.5
            self._sleep(latency)
            return Completion(
                model=model,
                ok=False,
                error=f"simulated {kind}",
                error_kind=kind,
                latency_ms=latency,
                simulated=True,
            )

        p_correct = _clamp(0.5 + (self.CAPABILITY[tier] - difficulty) * 1.4, 0.02, 0.99)
        correct = self._u(seed, "correct") < p_correct

        if answer is None:
            text = f"[mock tier-{tier} answer]"
        else:
            text = str(answer) if correct else self._wrong(str(answer), seed)

        in_tok = int(len(prompt.split()) * 1.35) + 48
        out_tok = max(4, int(len(text.split()) * 1.4 * self.VERBOSITY[tier]) + 6)
        latency = self.BASE_LATENCY_MS[tier] * (0.7 + 0.6 * self._u(seed, "lat"))
        self._sleep(latency)

        return Completion(
            model=model,
            text=text,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=latency,
            ok=True,
            stop_reason="end_turn",
            simulated=True,
        )


def build_provider(settings: Settings) -> Provider:
    """Pick a provider. Falls back to mock rather than failing to start."""
    if settings.mock:
        return MockProvider(settings)
    try:
        return AnthropicProvider(settings)
    except ModuleNotFoundError:
        print("[providers] anthropic SDK not installed -- using mock provider")
        return MockProvider(settings)
