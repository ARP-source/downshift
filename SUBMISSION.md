# Submission: Downshift

Repo: https://github.com/ARP-source/downshift

**Every figure below was measured against live models on W&B Inference. Nothing
is simulated.**

---

## One line

Start cheap, check the answer, escalate only on failure: 96% cheaper than
always using the flagship model, and it solves more problems than the flagship
does. We also ran the experiment that showed our own difficulty classifier was
not what produced that result, and shipped the simpler thing instead.

## The problem

Production LLM apps send everything to one expensive model. Most traffic does
not need it. Teams know this and do not act on it, because switching to a
cheaper model is a silent quality risk they cannot measure on their own traffic.

## The headline

Fourteen programming tasks. Each arm writes a Python function; the function is
**executed against 53 test assertions** and either passes every one or fails.
No string matching, no partial credit. Four independent runs on live models.

| Strategy | Solved | Cost | p50 |
|---|---|---|---|
| Always the flagship model | 10-12 / 14 | $0.0204 | 2405 ms |
| Always the cheapest model | 11-13 / 14 | $0.0006 | 2622 ms |
| Route by predicted difficulty | 12-13 / 14 | $0.0014 | **1377 ms** |
| **Verify and escalate, no prediction** | **13-14 / 14** | **$0.0008** | 2824 ms |

**96% cheaper than always-flagship, and it solves more, not fewer.**

The mechanism is one sentence: start on the cheapest tier, check the answer
against a quality gate, escalate only when it fails.

## We deleted our own classifier and the system got better

This project began as difficulty routing: score the prompt, pick the tier. That
scorer then failed its own validation, coming out flat against independently
assigned task levels (0.382 / 0.407 / 0.404 for easy / medium / hard). Which
raised a question we could not answer by looking at the headline: was the
classifier contributing anything, or was the verification loop doing all the
work?

So we added an arm with the classifier deleted. Same ladder, same quality gate,
same escalation -- it just always starts at the cheapest tier.

It won. Across two runs it solved **one task more** than the routed arm while
costing **61-95% less**. Prediction did buy something real: roughly **2x lower
latency**, because it skips the failed cheap attempt on hard work. That is a
genuine trade for interactive traffic, and the classifier stays in the repo
behind a flag. But it is not what we are selling, because the measurement says
it should not be.

The finding generalises past this project: **checking the answer beats
predicting which model you need.** Verification is cheap, and it is correct by
construction in a way a classifier never is.

### The routed arm is stable, which is how we trusted the comparison

The benchmark was run twice against live models before the ablation. Exploration is randomised, so
the router does not take an identical path through the ladder each time.

| Arm | Hard tasks, run 1 | Hard tasks, run 2 | Solved, run 1 | Solved, run 2 |
|---|---|---|---|---|
| All flagship | 2/4 | 2/4 | 12/14 | 11/14 |
| All cheapest | 2/4 | 2/4 | 12/14 | 12/14 |
| **Router** | **4/4** | **4/4** | **13/14** | **13/14** |

Cost saving against flagship for the routed arm: 93.1% then 93.3%. Its hard-task
column came out identical both times, which is why we trusted it enough to test
it against the ablation -- where it then lost to having no classifier at all, at
96% saving. The 93% figures describe the routed arm, not what we ship.

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
  argument rests on four problems. Two independent runs both gave 4/4 against
  2/4, which is reassuring but is still four problems.

---

## Three-minute demo script

**0:00 - 0:20 | The waste.** Dashboard, price ladder. "Same request, 28x price
difference. Most production apps pay the top rate for everything."

**0:20 - 1:10 | The proof.** Run code benchmark. "Fourteen programming tasks.
The code gets executed against 53 assertions -- it passes or it does not."
Land on the table: "the flagship solves 10 to 12 of 14 and costs two cents. We
solve 13 to 14 and cost eight hundredths of a cent. Cheaper and better, not
cheaper or better."

**1:10 - 1:50 | The experiment we ran on ourselves.** "We built difficulty
routing. Then we deleted the classifier and ran it again. It got better --
one more task solved, 61 to 95 percent cheaper, twice. Prediction bought us
2x latency and nothing else. So we shipped verification and kept the classifier
behind a flag. Checking the answer beats guessing which model you need."

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

**"Did that reproduce?"** Yes. Two runs, randomised exploration, hard tasks
4/4 both times against 2/4 for both baselines. Run 2 was the stronger one:
the flagship dropped to 11/14 while the router held 13/14.

**"You gave your router more attempts."** True, and it is in the limitations.
Escalation with verification is the product, not a scoring trick -- but a
retried flagship would close part of that gap and we say so.

**"Is your difficulty scoring any good?"** Measurably not good enough. It came
out flat against independently assigned difficulty labels. It is the first thing
we would replace, and the system already logs the data to train a replacement.

**"Are these real calls?"** Yes. Live W&B Inference, real token counts, real
costs. The dashboard refuses to display a live badge unless a live provider is
actually running.
