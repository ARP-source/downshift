# Downshift

**Route each request to the cheapest model that can actually answer it, and prove
what that costs you in quality.**

Every number below was measured against live models on Weights & Biases Inference.
Nothing here is simulated.

Built for the MantisGrid AI Hackathon & Summit 2026, intelligent model routing track.

---

## The result that matters

Fourteen programming tasks. Each arm writes a Python function; the function is
**executed against test cases** and either passes all of them or fails. No string
matching, no marking scheme to argue about.

| Arm | Solved | Cost | p50 | Easy | Medium | **Hard** |
|---|---|---|---|---|---|---|
| All flagship (DeepSeek V4-Pro) | 12/14 | $0.019988 | 2463 ms | 5/5 | 5/5 | **2/4** |
| All cheapest (GPT-OSS 20B) | 12/14 | $0.000676 | 3357 ms | 5/5 | 5/5 | **2/4** |
| **Downshift** | **13/14** | **$0.001370** | **1921 ms** | 5/5 | 4/5 | **4/4** |

**The router solved more problems than the flagship, at 93% less cost.**

The last column is the product. On hard tasks the cheap model solves 2 of 4 — and
so does the flagship. The router solves 4 of 4, because when an answer fails the
quality gate it escalates instead of shipping it. Cheap-only looks fine in
aggregate and silently loses half your hard work.

Against always-flagship: **93.1% cheaper, 108% of its solve rate.**
Against cheap-only: **double the hard-task solve rate**, for twice the cheap
tier's cost and still 93% below flagship.

### It reproduces

The benchmark was run twice against live models. Exploration is randomised, so
the router does not take an identical path through the ladder each time.

| Arm | Hard tasks, run 1 | Hard tasks, run 2 | Solved, run 1 | Solved, run 2 |
|---|---|---|---|---|
| All flagship | 2/4 | 2/4 | 12/14 | 11/14 |
| All cheapest | 2/4 | 2/4 | 12/14 | 12/14 |
| **Router** | **4/4** | **4/4** | **13/14** | **13/14** |

Cost saving against flagship: 93.1% then 93.3%. The hard-task column, which is
the claim that carries the product, came out identical both times.

## The result that did not work, and why it is here

The same three arms over 74 short factual questions:

| Arm | Cost | Quality | p50 | Unanswered |
|---|---|---|---|---|
| All flagship | $0.045531 | 90.0% | 494 ms | 8 |
| Router | $0.015584 | 90.0% | 656 ms | 5 |
| All cheapest | $0.001573 | 90.0% | 705 ms | 5 |

All three scored identically. Cheap-only is 96.6% cheaper at the same quality, so
on this workload the honest recommendation is **do not route, just use the cheap
model**. Modern open models do not differ on short factual recall.

That is reported rather than buried because it is the whole point of owning the
measurement: the instrument is supposed to tell you when routing is not worth it.
A tool that only ever says "yes, route" is a sales deck.

It also shows where routing earns its place: **workload difficulty, not request
volume.** Cheap models fail on hard generation, not on trivia.

## Availability, measured under a real outage

Failure injected at the provider boundary; everything downstream is the real
system reacting, with real calls serving the rerouted requests.

| Scenario | Arm | Answered | Cost |
|---|---|---|---|
| Healthy | Router | 100% | $0.000396 |
| Healthy | All flagship | 100% | $0.009261 |
| **Flagship returns 503** | **Router** | **100%** | $0.000421 |
| **Flagship returns 503** | **All flagship** | **0%** | $0 |

The ladder that saves money is the same ladder that keeps answering. Escalation
and failover are one mechanism, so availability comes free with the cost work.

---

## How it works

1. **Score difficulty** from cheap lexical signals before spending anything. No
   model call, so the router cannot cost more than it saves.
2. **Route** to the cheapest tier the policy believes handles that difficulty band.
3. **Gate the answer** without ground truth: empty, refusal phrasing or a bare
   hedge means not good enough. This is what production has; eval answers are not.
4. **Escalate** on a failed gate. Transient errors retry in place, tier failures
   fail over upward. Every attempt is billed and counted, wasted ones included.
5. **Learn** which tier each difficulty band needs, using deliberate downward
   exploration on 20% of traffic for counterfactual evidence.

### The ladder (W&B Inference, list rates)

| Tier | Model | In $/1M | Out $/1M | Measured spread |
|---|---|---|---|---|
| 0 | `openai/gpt-oss-20b` | $0.03 | $0.13 | 28x cheaper |
| 1 | `meta-llama/Llama-3.3-70B-Instruct` | $0.71 | $0.71 | 4x cheaper |
| 2 | `deepseek-ai/DeepSeek-V4-Pro-0813` | $1.31 | $3.96 | baseline |

A Claude ladder (Haiku 4.5 / Sonnet 5 / Opus 5) ships too; set `LADDER=claude`.

---

## Two findings that only appear when you measure live

**List price is a bad proxy for cost per answer.** Qwen3.6-35B-A3B is 3.5x cheaper
per token than the flagship, and was the original mid tier. It is a reasoning
model: it spent ~170 output tokens arriving at the word "Tokyo" against the
flagship's 19, which put its real cost per answer within 20% of the model it was
supposed to undercut. It was replaced by a dense model that answers in 3 tokens.

**Reasoning models break naive token budgets silently.** With `max_tokens=32` they
consume the entire budget on hidden reasoning and return an *empty string* with
`finish_reason: length` — not a short answer, no error. A router without a quality
gate would serve that to a user. Ours catches it and escalates.

---

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env          # add your key, set LADDER
python -m uvicorn app.main:app --port 8077
```

Open <http://localhost:8077>. With no key it runs a deterministic offline provider
and says so in place of every headline, so nothing simulated is ever presented as
measured.

```bash
python -c "from app import bench; r=bench.run_benchmark(); bench.save(r); print(r['comparison'])"
python -c "from app import codebench; r=codebench.run_codebench(); codebench.save(r); print(r['comparison'])"
```

---

## Honest limitations

- **The difficulty scorer failed its own validation.** Mean score by external task
  level came out flat: easy 0.382, medium 0.407, hard 0.404. It does not track the
  independently assigned difficulty classes. The uniform instruction wrapper on
  every code task contributed the same code and constraint signals throughout and
  washed out the differences. A learned scorer trained on the per-band outcome data
  this system already collects is the obvious replacement.
- **The router gets more attempts than the pinned arms.** Escalation means two or
  three shots at a hard task where a pinned arm gets one. That is the product
  working as designed, but a flagship arm with retries would close part of the gap,
  and the comparison should be read with that in mind.
- **The router was slower than flagship on short questions** (656 ms vs 494 ms p50),
  because the cheap tier is a reasoning model. It was faster on code generation
  (1921 ms vs 2463 ms). Latency is workload-dependent and we do not claim it as a
  general win.
- **Non-starting tiers carry selection-biased statistics**, sampled either by random
  exploration or by escalation after a cheaper tier already failed.
- **Fourteen code tasks and 74 questions is a small sample.** The hard-task column
  that carries the argument rests on four problems. It was run twice and came out
  4/4 against 2/4 both times, which is reassuring but is still four problems.

## Prior art

Model routing is an occupied category: OpenRouter's Auto Router, Martian,
NotDiamond, Unify, RouteLLM. Several report larger raw savings.

What is thin is the evaluation layer. Those are vendor benchmarks of a vendor
router on a vendor-chosen eval. This is portable, runs on your traffic, carries a
blunt-downgrade control arm, grades code by executing it, and reports the workload
where routing turned out not to be worth it.

---

## Layout

```
app/
  pricing.py     ladders, rate cards, all USD cost accounting
  features.py    prompt difficulty scoring
  router.py      difficulty band to tier policy, online adaptation
  cascade.py     escalation, failover, retry
  judge.py       validity gate and deterministic grading
  providers.py   Anthropic, OpenAI-compatible, mock and chaos wrapper
  metrics.py     cost, quality, latency, SLO, reliability accounting
  datasets.py    74 short-answer items
  codetasks.py   14 executable programming tasks, 53 assertions
  bench.py       three-arm benchmark plus outage survival
  codebench.py   code generation benchmark, graded by execution
  main.py        FastAPI surface
web/             dashboard, no build step, no dependencies
```
