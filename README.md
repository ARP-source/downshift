# Cascade Router

**The safety harness that makes model routing adoptable.**

Routing requests to cheaper models is not a new idea. Proving it did not cost you
anything is the part nobody ships. This is a router *and* the measurement rig that
tells you whether turning it on is safe.

Built for the MantisGrid AI Hackathon & Summit 2026, intelligent model routing track.

---

## The result

Measured on a bundled 74-item evaluation set, 70 of which are graded
deterministically (exact match, numeric tolerance, yes/no, substring) with no
judge model in the loop.

| Arm | Cost | Quality | p50 latency | Unanswered |
|---|---|---|---|---|
| All flagship (Opus 5) | $0.0444 | 91.4% | 2160 ms | 5 |
| **Cascade Router** | **$0.0161** | **91.4%** | **422 ms** | **1** |
| All cheapest (Haiku 4.5) | $0.0081 | 72.9% | 362 ms | 9 |

**63.7% cheaper than always-flagship, at 100% of its quality, 80% faster at p50.**

### Why the third row is the important one

Most routing claims are unfalsifiable because they compare against one baseline.
"We cut cost 64%" means nothing on its own -- so does deleting your expensive model.

The all-cheapest arm is the control. It saves *more* (81.8%) and keeps only
**79.7%** of flagship quality. The router gives back some of that saving and buys
back all of the quality. The gap between those two rows is the entire value of
routing, and it is the row vendors leave out.

The router also answers **more** requests than always-flagship (1 unanswered vs 5),
because escalation doubles as a failover path.

---

## How it works

1. **Score difficulty** before spending anything. A transparent weighted formula
   over cheap lexical signals -- length, code markers, arithmetic, reasoning verbs,
   multi-step structure, output constraints -- scores each prompt 0..1. No model
   call, so the router cannot cost more than it saves.
2. **Route** to the cheapest tier the policy believes can handle that difficulty band.
3. **Gate the answer** with a ground-truth-free check: empty, refusal phrasing, or a
   bare hedge means not good enough. This is what production has available; eval
   answers are not.
4. **Escalate** only on a failed gate. Transient errors retry in place; tier failures
   fail over upward. Every attempt is billed and counted, including the wasted ones.
5. **Learn.** Per (difficulty band, tier) success rates accumulate, and the policy
   moves each band to the cheapest tier within tolerance of the best tier observed
   there.

### The price ladder

| Tier | Model | Input $/1M | Output $/1M | Relative |
|---|---|---|---|---|
| 0 | `claude-haiku-4-5` | $1.00 | $5.00 | 5.0x cheaper |
| 1 | `claude-sonnet-5` | $2.00 | $10.00 | 2.5x cheaper |
| 2 | `claude-opus-5` | $5.00 | $25.00 | baseline |

### Exploration is not optional

A router only observes the tier it actually ran, so it can never discover that a
cheaper tier would have sufficed. 20% of requests deliberately probe one tier below
the policy. Those probes are the only unbiased evidence in the system, and without
them the policy is frozen at whatever prior it started with.

---

## What the policy learns

A real run, straight from the dashboard:

| Difficulty | Starts on | Haiku 4.5 | Sonnet 5 | Opus 5 |
|---|---|---|---|---|
| 0.0-0.2 | Haiku 4.5 | **95.5%** (n=176) | 50.0% (n=8) | -- |
| 0.2-0.4 | Sonnet 5 | 63.3% (n=49) | **100%** (n=21) | -- |
| 0.4-0.6 | Sonnet 5 | 100% (n=2) | 100% (n=6) | -- |
| 0.6-0.8 | Sonnet 5 | 100% (n=1) | 42.9% (n=7) | -- |
| 0.8-1.0 | Opus 5 | -- | 0.0% (n=5) | **75.9%** (n=29) |

Every routing decision is auditable against this table. Haiku holds 95.5% across
176 easy items and stays. It collapses to 63.3% one band up, where Sonnet is
perfect, so that band escalated. Sonnet scores 0 for 5 on the hardest band where
Opus reaches 75.9%.

---

## Running it

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8077
```

Open <http://localhost:8077>. With no API key it starts in **mock mode** and the
whole dashboard, benchmark and learning loop work offline with zero spend.

To measure real models:

```bash
cp .env.example .env
# put your key in .env, then set MOCK=0
```

`.env` is gitignored. The key is read by the SDK from the environment and is never
logged, echoed or committed.

Command line:

```bash
python -c "from app import bench; r=bench.run_benchmark(); bench.save(r); print(r['comparison'])"
```

---

## Honest limitations

These are real, and we would rather state them than be asked.

- **Mock-mode numbers validate the machinery, not the routing.** The mock provider
  derives correctness from the same difficulty score the router uses, so it cannot
  tell you whether that score predicts real model capability. It exercises routing,
  escalation, cost accounting and the reliability paths end to end. Only live mode
  tests the premise.
- **Non-starting tiers have biased statistics.** A tier gets sampled either by random
  exploration (unbiased) or by escalation (only after a cheaper tier already failed,
  so skewed toward the hard items in that band). The small-n cells in the policy
  table above should be read with that in mind; exploration is what keeps the
  starting-tier numbers honest.
- **The difficulty scorer is lexical and under-rates short, hard prompts.** "What is
  the minimum possible final value?" is genuinely hard and scores low. A learned
  difficulty model is the obvious next step; a keyword formula was chosen because it
  is free, explainable and auditable.
- **Single provider.** The ladder is Claude tiers. Cross-provider routing is a
  packaging problem, not a design change -- the provider interface has one method.
- **The eval set is small and skews easy** (46 of 74 items in the lowest band). That
  skew is deliberate and matches real traffic, but it means the headline is sensitive
  to the mix. The per-band table is the more robust reading.

## Prior art

Model routing is a real, occupied category -- OpenRouter's Auto Router, Martian,
NotDiamond, Unify, and the RouteLLM paper among others. Several report larger raw
savings than the number above.

What is thin on the ground is the evaluation layer: a reproducible harness with a
blunt-downgrade control arm, an auditable per-band evidence table, and explicit
accounting for the cost of escalation. Teams do not avoid routing because it does
not exist. They avoid it because they cannot prove what it costs them in quality.
That is the gap this fills, and the router here is the reference implementation
rather than the product.

---

## Layout

```
app/
  pricing.py     price ladder and all USD cost accounting
  features.py    prompt difficulty scoring
  router.py      difficulty band to tier policy, with online adaptation
  cascade.py     escalation, failover, retry
  judge.py       validity gate and deterministic grading
  providers.py   Anthropic SDK and deterministic mock behind one interface
  metrics.py     cost, quality, latency, SLO and reliability accounting
  datasets.py    the bundled evaluation set
  bench.py       three-arm benchmark
  main.py        FastAPI surface
web/             dashboard (no build step, no dependencies)
```
