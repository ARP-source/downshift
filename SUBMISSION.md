# Submission: Cascade Router

Repo: https://github.com/ARP-source/cascade-router

---

## One line

A model router that escalates instead of guessing, shipped with the measurement
rig that proves what routing costs you in quality.

## The problem

Production LLM apps send everything to one flagship model. Most traffic is easy --
lookups, conversions, classification, extraction -- and a model 5x to 33x cheaper
answers those identically. Teams know this. They do not act on it, because nobody
can tell them what routing will cost them in quality on *their* traffic.

## What it does

Scores each prompt's difficulty from free lexical signals, routes to the cheapest
tier likely to succeed, checks the answer against a quality gate, and escalates
only on failure. Transient errors retry in place; tier failures fail over upward.
A policy learns per-difficulty-band which tier is actually needed, using
deliberate downward exploration on 20% of traffic to generate the counterfactual
evidence a router otherwise never sees.

## Results

Bundled 74-item eval, 70 graded deterministically, no judge model.

**Claude ladder** (Haiku 4.5 / Sonnet 5 / Opus 5, 5x spread):

| Arm | Cost | Quality | p50 | Unanswered |
|---|---|---|---|---|
| All flagship | $0.0444 | 91.4% | 2160 ms | 5 |
| **Router** | **$0.0161** | **91.4%** | **422 ms** | **1** |
| All cheapest | $0.0081 | 72.9% | 362 ms | 9 |

**63.7% cheaper at 100% of flagship quality, 80% faster.**

**W&B Inference ladder** (GPT-OSS 20B / Qwen3.6 35B / DeepSeek V4-Pro, 33x spread):

**81.1% cheaper at 90.9% quality retained**, against a blunt-cheapest control
that saves 97.7% but keeps only 78.8%.

### The row that matters

The all-cheapest arm is the control, and it is what makes the headline falsifiable.
It saves *more* and keeps far less quality. The gap between those two rows is the
entire value of routing. A single-baseline comparison cannot distinguish "routing
works" from "the cheap model was fine all along."

The router also answers **more** requests than always-flagship (1 unanswered vs 5),
because the escalation path doubles as failover.

## Why this is not just another router

Model routing is an occupied category: OpenRouter Auto Router, Martian, NotDiamond,
Unify, RouteLLM. Several publish larger raw savings. We are not claiming to have
invented routing.

Those are vendor benchmarks of a vendor router on a vendor-chosen eval. They are
marketing artifacts, not instruments. Three things here are genuinely different:

1. **Portable evaluation with a control arm.** Point it at your own traffic and get
   a decision for your distribution, not a score for someone's product.
2. **Auditable decisions.** Every route names the signals that produced it, and the
   per-band evidence table shows the success rate behind every choice. Commercial
   routers use learned classifiers you cannot inspect -- a problem for the
   infrastructure buyers in this room.
3. **Routing and reliability are the same mechanism.** Escalation is failover. The
   measured result is a router that is more available than always-flagship.

## Honest limitations

- Mock-provider numbers validate the machinery, not the premise: mock correctness
  derives from the same difficulty score the router uses, so it cannot tell you
  whether that score predicts real capability. Live mode is a one-line change and
  the code path is built for both wire protocols.
- Non-starting tiers have selection-biased statistics, because they are sampled
  either by random exploration or by escalation after a cheaper tier already failed.
- The difficulty scorer is lexical and under-rates short, hard prompts. A learned
  scorer is the obvious next step; a formula was chosen because it is free and
  inspectable.
- The eval is small and skews easy, deliberately, to match real traffic shape.

## Run it

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8077
```

Works offline with zero spend. `LADDER=wandb` switches ladders; a key in `.env`
switches to live models.

---

## Three-minute demo script

**0:00 - 0:25 | The waste.** Open the dashboard. Point at the price ladder:
"same request, 5x price difference on Claude tiers, 33x on open models. Most
production apps pay the top rate for every request, including 'what is the capital
of Japan'."

**0:25 - 1:10 | The proof.** Hit Run benchmark. While it runs: "three arms, same
74 items. Always-flagship, always-cheapest, and our router." Land on the two
charts: "on cost, the router bar is a third of flagship. On quality, it is the same
length. The green bar is the control -- it saves more and loses a fifth of its
quality. That contrast is the whole argument."

**1:10 - 1:50 | It is evidence-driven, not vibes.** Scroll to the policy table.
"Haiku holds 95.5% across 176 easy items, so that band stays cheap. One band up it
collapses to 63%, where Sonnet is perfect -- so the policy escalated. On the hardest
band Sonnet scores zero for five and the flagship earns its price. Every route is
auditable against this table."

**1:50 - 2:20 | It learns.** Point at the learning curve. "Four passes over the
same traffic. Quality climbs 85.7 to 91.4 as it discovers which band needs which
tier. It gives back three points of savings to buy six points of quality, because
20% of requests deliberately probe one tier cheaper -- that is the only way to learn
you are being too conservative."

**2:20 - 2:50 | Reliability.** "Escalation is also failover. The router left one
request unanswered. Always-flagship left five. Cheaper *and* more available."

**2:50 - 3:00 | Close.** "Routing is not new. Being able to prove it is safe on
your own traffic is what is missing. That is what this is."

## Questions to expect

**"OpenRouter already does this."** Yes, and Martian and NotDiamond and RouteLLM.
We are not claiming novel routing. We are claiming the evaluation layer -- portable,
with a control arm, auditable per band. Their benchmarks measure their router on
their eval; this measures any router on your traffic.

**"Your savings are lower than RouteLLM's."** Correct, and we constrain on quality
retention. We report the control arm that would have shown a bigger number, and
chose not to take it.

**"Are these real model calls?"** On the numbers shown, no -- the provider is mocked
and labelled as such in the UI, because the inference credit available is W&B and
that ladder was built late. The live code path exists for both the Anthropic and
OpenAI-compatible wire formats. We would rather show a labelled simulation than an
unlabelled guess.

**"How does difficulty scoring not cost more than it saves?"** It is a lexical
formula, no model call, microseconds per request.

**"What breaks first at scale?"** The lexical scorer on short hard prompts. It is
the first thing we would replace with a learned model, trained on exactly the
per-band outcome data this system already collects.
