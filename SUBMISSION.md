# Submission: Cascade Router

Repo: https://github.com/ARP-source/cascade-router

**Every figure below was measured against live models on W&B Inference. Nothing
is simulated.**

---

## One line

Routing that pays for itself on the requests that matter: 93% cheaper than
always using the flagship model, and it solves the hard problems the flagship
misses.

## The problem

Production LLM apps send everything to one expensive model. Most traffic does
not need it. Teams know this and do not act on it, because switching to a
cheaper model is a silent quality risk they cannot measure on their own traffic.

## The headline

Fourteen programming tasks. Each arm writes a Python function; the function is
**executed against 53 test assertions** and either passes or fails. No string
matching, no partial credit, no marking scheme to dispute.

| Arm | Solved | Cost | p50 | Easy | Medium | **Hard** |
|---|---|---|---|---|---|---|
| All flagship (DeepSeek V4-Pro) | 12/14 | $0.019988 | 2463 ms | 5/5 | 5/5 | **2/4** |
| All cheapest (GPT-OSS 20B) | 12/14 | $0.000676 | 3357 ms | 5/5 | 5/5 | **2/4** |
| **Cascade Router** | **13/14** | **$0.001370** | **1921 ms** | 5/5 | 4/5 | **4/4** |

**93.1% cheaper than the flagship, and it solved more problems than the flagship.**

The last column is the whole product. On hard tasks the cheap model gets 2 of 4.
So does the flagship. The router gets 4 of 4, because a failed quality gate
triggers escalation instead of shipping a wrong answer. Cheap-only looks fine in
aggregate and loses half your hard work without telling you.

## The result we did not want, reported anyway

The same three arms over 74 short factual questions:

| Arm | Cost | Quality | Unanswered |
|---|---|---|---|
| All flagship | $0.045531 | 90.0% | 8 |
| Router | $0.015584 | 90.0% | 5 |
| All cheapest | $0.001573 | 90.0% | 5 |

Identical quality across all three. Cheap-only is 96.6% cheaper for the same
result, so on that workload the honest recommendation is **do not route**.

We are leading with this rather than hiding it, for two reasons. It is what the
instrument is for: a measurement tool that only ever says "yes, route" is a sales
deck. And it locates the value precisely -- routing pays on **workload
difficulty, not request volume**. Cheap models fail at hard generation, not at
trivia.

## Availability comes free with it

Failure injected at the provider boundary; everything downstream is the real
system reacting, with real calls serving the rerouted requests.

| Scenario | Router answered | All-flagship answered |
|---|---|---|
| Healthy | 100% ($0.000396) | 100% ($0.009261) |
| **Flagship returns 503** | **100%** | **0%** |

The ladder that saves money is the same ladder that keeps answering. This is a
consequence of the cost architecture, not a second product.

## Why this is not just another router

Routing is an occupied category: OpenRouter Auto Router, Martian, NotDiamond,
Unify, RouteLLM. Several publish larger raw savings. We did not invent routing.

What is thin on the ground is the evaluation layer:

1. **A control arm.** "64% cheaper" is unfalsifiable without the cheap-only
   baseline next to it. Ours is there, and on one workload it beat us.
2. **Execution grading.** Code is run, not compared. There is no marking scheme
   to argue with.
3. **Portability.** Vendor benchmarks measure a vendor router on a vendor eval.
   This runs on your traffic and gives you a per-difficulty-band decision.

## Two findings that only appear live

**List price is a bad proxy for cost per answer.** Qwen3.6-35B-A3B is 3.5x
cheaper per token than the flagship and was our original mid tier. It is a
reasoning model: ~170 output tokens to reach the word "Tokyo" against the
flagship's 19, putting its real cost per answer within 20% of the model it was
meant to undercut. Replaced with a dense model that answers in 3 tokens.

**Reasoning models fail silently under naive token budgets.** At
`max_tokens=32` they spend the whole budget on hidden reasoning and return an
**empty string** with `finish_reason: length` -- not a short answer, not an
error. A router without a quality gate serves that to a user.

## Honest limitations

- **The difficulty scorer failed its own validation.** Mean score by external
  task level: easy 0.382, medium 0.407, hard 0.404 -- flat. It does not track
  the independently assigned difficulty classes. A learned scorer, trained on
  the per-band outcome data the system already collects, is the replacement.
- **The router gets more attempts than the pinned arms.** Escalation means two
  or three shots where a pinned arm gets one. That is the design, but a flagship
  arm with retries would close part of the gap.
- **Latency is workload-dependent.** Router was slower than flagship on short
  questions (656 ms vs 494 ms) and faster on code (1921 ms vs 2463 ms). We do
  not claim latency as a general win.
- **Small sample.** Fourteen code tasks; the hard-task column carrying the
  argument rests on four problems.

---

## Three-minute demo script

**0:00 - 0:20 | The waste.** Dashboard, price ladder. "Same request, 28x price
difference. Most production apps pay the top rate for everything."

**0:20 - 1:10 | The proof.** Run code benchmark. "Fourteen programming tasks.
The code gets executed against 53 assertions -- it passes or it does not."
Land on the table: "flagship solved 12, cost two cents. We solved 13, cost a
tenth of a cent. We beat the flagship for 7% of the price."

**1:10 - 1:50 | Where the value actually is.** Point at the hard column. "Easy
and medium, everything ties. Hard: the cheap model gets 2 of 4, the flagship
gets 2 of 4, we get 4 of 4. That is the product. Cheap-only looks fine on
average and loses half your hard work silently."

**1:50 - 2:20 | The result we did not want.** "On 74 trivia questions all three
arms scored identically, and cheap-only was 96% cheaper. On that workload our
own tool says do not route. We shipped that finding because an instrument that
only says yes is a sales deck -- and it tells you routing pays on difficulty,
not volume."

**2:20 - 2:45 | It stays up.** Set flagship to 503, send a request. "Same ladder
that saves money keeps answering. Always-flagship serves zero here. We serve
100%."

**2:45 - 3:00 | Close.** "Routing is not new. Being able to prove on your own
traffic whether it is safe -- including when the answer is no -- is what is
missing."

## Questions to expect

**"OpenRouter already does this."** Yes, and Martian and NotDiamond and
RouteLLM. We are not claiming novel routing. We are claiming the evaluation
layer, with a control arm and execution grading, portable to your traffic.

**"Your trivia result says routing is pointless."** On that workload it is, and
we say so in the README. That is the finding: routing pays on difficulty, not
volume. The code benchmark is where the cheap model actually fails.

**"You gave your router more attempts."** True, and it is in the limitations.
Escalation with verification is the product, not a scoring trick -- but a
retried flagship would close part of that gap and we say so.

**"Is your difficulty scoring any good?"** Measurably not good enough. It came
out flat against independently assigned difficulty labels. It is the first thing
we would replace, and the system already logs the data to train a replacement.

**"Are these real calls?"** Yes. Live W&B Inference, real token counts, real
costs. The dashboard refuses to display a live badge unless a live provider is
actually running.
