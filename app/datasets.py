"""The evaluation set the router is scored on.

Design constraints:
  * Most items are deterministically checkable (exact, numeric, yes/no,
    substring), so quality is measured for free and cannot drift with a
    judge model. Open-ended items are a deliberate minority.
  * The mix spans the full difficulty range. An eval made only of easy
    lookups would let a router that always picks the cheapest model score
    perfectly, which would prove nothing.
  * It is bundled, offline and fixed, so benchmark runs are reproducible
    and nobody has to download anything on hackathon wifi.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalItem:
    id: str
    prompt: str
    answer: str | None
    kind: str  # exact | numeric | yesno | contains | open
    tag: str   # lookup | arithmetic | convert | classify | extract | reason | code | design

    def as_dict(self) -> dict:
        return {"id": self.id, "prompt": self.prompt, "kind": self.kind, "tag": self.tag}


I = EvalItem

HANDWRITTEN: list[EvalItem] = [
    # --- simple lookups: a flagship model here is pure waste ---------------
    I("f01", "What is the capital of Japan?", "Tokyo", "exact", "lookup"),
    I("f02", "What is the chemical symbol for gold?", "Au", "exact", "lookup"),
    I("f03", "In what year did the Apollo 11 moon landing occur?", "1969", "numeric", "lookup"),
    I("f04", "What is the largest ocean on Earth?", "Pacific", "contains", "lookup"),
    I("f05", "What language is primarily spoken in Brazil?", "Portuguese", "contains", "lookup"),
    I("f06", "How many sides does a hexagon have?", "6", "numeric", "lookup"),
    I("f07", "What is the boiling point of water in Celsius at sea level?", "100", "numeric", "lookup"),
    I("f08", "Who wrote the play Hamlet?", "Shakespeare", "contains", "lookup"),
    I("f09", "What is the capital of Australia?", "Canberra", "exact", "lookup"),
    I("f10", "What planet is known as the red planet?", "Mars", "exact", "lookup"),

    # --- unit conversion and one-step arithmetic --------------------------
    I("c01", "Convert 5 kilometers to meters.", "5000", "numeric", "convert"),
    I("c02", "What is 17 percent of 300?", "51", "numeric", "arithmetic"),
    I("c03", "How many minutes are in 3.5 hours?", "210", "numeric", "convert"),
    I("c04", "Convert 32 degrees Fahrenheit to Celsius.", "0", "numeric", "convert"),
    I("c05", "What is 144 divided by 12?", "12", "numeric", "arithmetic"),
    I("c06", "How many bytes are in 4 kibibytes?", "4096", "numeric", "convert"),
    I("c07", "Convert 2.5 gigabytes to megabytes, using 1000 megabytes per gigabyte.", "2500", "numeric", "convert"),
    I("c08", "What is 2 to the power of 10?", "1024", "numeric", "arithmetic"),

    # --- binary classification --------------------------------------------
    I("y01", "Is 97 a prime number? Answer yes or no.", "yes", "yesno", "classify"),
    I("y02", "Does water expand when it freezes? Answer yes or no.", "yes", "yesno", "classify"),
    I("y03", "Is HTTP status 503 a client error? Answer yes or no.", "no", "yesno", "classify"),
    I("y04", "Is TCP a connectionless protocol? Answer yes or no.", "no", "yesno", "classify"),
    I("y05", "Is 2024 a leap year? Answer yes or no.", "yes", "yesno", "classify"),
    I("y06", "In Python, is a tuple mutable? Answer yes or no.", "no", "yesno", "classify"),

    # --- extraction from noisy text ----------------------------------------
    I("e01", "Give only the HTTP status code from this log line: 10.0.0.4 - - [12/Mar/2026:08:11:03] GET /api/v1/users 503 1240", "503", "contains", "extract"),
    I("e02", "Give only the hostname from this URL: https://metrics.internal.example.com:9090/targets", "metrics.internal.example.com", "contains", "extract"),
    I("e03", "Give only the port number from this address: redis://cache-03.prod:6379/2", "6379", "contains", "extract"),
    I("e04", "Give only the exception type from this traceback line: ValueError: invalid literal for int with base 10", "ValueError", "contains", "extract"),
    I("e05", "Give only the date from this line: backup completed 2026-03-11T04:22:19Z in 412 seconds", "2026-03-11", "contains", "extract"),

    # --- multi-step quantitative reasoning ---------------------------------
    I("r01", "A server handles 1200 requests per minute. Each request costs 0.0004 dollars. What is the cost per hour in dollars?", "28.8", "numeric", "reason"),
    I("r02", "A cluster has 8 nodes with 64 GB of RAM each. 30 percent is reserved for the system. How many GB total are available for workloads?", "358.4", "numeric", "reason"),
    I("r03", "A job takes 45 minutes on one machine. Assuming perfect parallelism, how many minutes does it take on 6 machines?", "7.5", "numeric", "reason"),
    I("r04", "The p99 latency is 850 ms and must be cut by 40 percent. What is the target in milliseconds?", "510", "numeric", "reason"),
    I("r05", "A service costs 1800 dollars per month. Moving 70 percent of traffic to a tier that is 5 times cheaper. What is the new monthly cost in dollars?", "792", "numeric", "reason"),
    I("r06", "A disk fills at 3.5 GB per day and has 140 GB free. In how many days does it fill, rounded down?", "40", "numeric", "reason"),
    I("r07", "Three replicas each have 99 percent availability and fail independently. What is the probability in percent that all three are down at once? Give the number.", "0.0001", "numeric", "reason"),
    I("r08", "A queue drains at 500 jobs per second and fills at 650 per second for 20 seconds. How many jobs are backlogged at the end?", "3000", "numeric", "reason"),

    # --- code reasoning -----------------------------------------------------
    I("k01", "In Python, what does len(set([1, 2, 2, 3, 3, 3])) return?", "3", "numeric", "code"),
    I("k02", "In Python, what is the result of list(range(2, 11, 3))? Give only the list.", "[2, 5, 8]", "contains", "code"),
    I("k03", "What SQL keyword removes duplicate rows from a result set?", "DISTINCT", "contains", "code"),
    I("k04", "In Python, which exception is raised when converting the string 12a to an integer with int?", "ValueError", "contains", "code"),
    I("k05", "What is the time complexity of binary search on a sorted array? Give the big-O expression.", "log n", "contains", "code"),
    I("k06", "In git, which command creates a new branch and switches to it in one step? Give only the command.", "checkout -b", "contains", "code"),
    I("k07", "In Python, what does the bool of an empty list evaluate to?", "False", "contains", "code"),

    # --- hard analysis: genuinely needs the flagship tier --------------------
    I("h01", "A distributed lock uses wall-clock TTLs. Two nodes have clocks that differ by 4 seconds and the TTL is 3 seconds. Can both nodes hold the lock at once? Answer yes or no.", "yes", "yesno", "reason"),
    I("h02", "A cache has a 95 percent hit rate. Hits cost 2 ms and misses cost 120 ms. What is the mean latency in milliseconds?", "7.9", "numeric", "reason"),
    I("h03", "During an outage 10000 clients each send an initial request plus 3 retries with no jitter. How many total requests hit the service?", "40000", "numeric", "reason"),
    I("h04", "A read-modify-write on a shared counter runs without a transaction across 4 concurrent workers, each incrementing 1000 times. What is the minimum possible final value?", "1000", "numeric", "reason"),

    # --- long-form multi-constraint work: the escalation path exists for this -
    I("x01", "Our retry policy uses exponential backoff with a base of 2 seconds and 4 retries, and no jitter at all. During a total outage 5000 clients fail at the same instant. Explain step by step why the retry storm persists after the service recovers, then give the total number of requests the service receives including the initial attempt. Answer with only that number.", "25000", "numeric", "reason"),
    I("x02", "A read-modify-write on a shared counter runs without a transaction. First explain why the lost-update anomaly occurs, then compare optimistic and pessimistic locking as fixes, and finally name the SQL isolation level that prevents it outright. Answer with only the isolation level.", "serializable", "contains", "reason"),
    I("x03", "Here is a traceback from an async worker: TimeoutError is raised inside a finally block during shutdown, and the original ValueError disappears. Explain why the first exception is lost, then design a fix, and name the Python construct that preserves the original. Answer with only the construct.", "raise from", "contains", "code"),
    I("x04", "We serve a read-heavy API where writes must become visible within 2 seconds. Analyze the tradeoff between write-through caching and TTL-based expiry under this constraint, explain which one risks stale reads, then justify a choice. Answer with only the name of the approach you would choose.", "write-through", "contains", "design"),
    I("x05", "A service has three dependencies, each with 99.9 percent availability, called sequentially on every request with no fallback. First derive the compound availability, then explain why adding a fourth dependency is worse than it looks, and give the resulting availability as a percentage to three decimal places.", "99.700", "contains", "reason"),
    I("x06", "Our p99 latency tripled after we added a cache, while p50 improved. Explain step by step why a cache can degrade the tail, compare stampede protection against request coalescing, then name the specific pattern that prevents many clients from recomputing one expired hot key. Answer with only the pattern name.", "coalescing", "contains", "design"),
    I("x07", "A distributed lock uses wall-clock TTLs across nodes whose clocks differ by up to 4 seconds, with a 3 second TTL. Derive the window during which two holders can overlap, explain why monotonic clocks do not fully fix this, then give the overlap window in seconds. Answer with only the number.", "4", "numeric", "reason"),
    I("x08", "We batch 500 records per request against an API that rate limits at 100 requests per minute, and we must process 1.2 million records. First explain why naive parallelism makes this slower, then compute the minimum wall-clock time in minutes assuming the limit is the only constraint. Answer with only the number of minutes.", "24", "numeric", "reason"),
    I("x09", "Given a service that must not lose writes during a zone failure, compare synchronous replication against asynchronous replication with a write-ahead log, explain the recovery-point objective implied by each, then name the one that guarantees zero data loss. Answer with only that name.", "synchronous", "contains", "design"),
    I("x10", "A queue consumer processes 500 jobs per second while producers emit 650 per second for 20 seconds, then producers stop. Explain why backlog drain time is not simply the backlog divided by the production rate, then compute how many seconds after the producers stop the queue is empty. Answer with only the number.", "6", "numeric", "reason"),

    # --- open ended: graded only when the LLM judge is enabled ---------------
    I("o01", "Why can exponential backoff without jitter make an outage worse rather than better?", "Synchronised retries cluster into coordinated waves that repeatedly overwhelm the recovering service.", "open", "design"),
    I("o02", "Explain the main tradeoff between routing every request to a flagship model versus routing by difficulty.", "Flagship gives uniform quality at high cost; difficulty routing cuts cost substantially but needs a quality gate and escalation to avoid degrading hard requests.", "open", "design"),
    I("o03", "Our p50 latency is fine but p99 tripled after adding a cache. Give the most likely cause.", "Cache misses now pay both the cache lookup and the origin fetch, and lock contention or stampedes on hot keys concentrate in the tail.", "open", "design"),
    I("o04", "Why is measuring cost per completed task better than cost per API call?", "A cheaper call that needs retries, escalation or human rework can cost more per finished unit of work than one expensive call that succeeds first time.", "open", "design"),
]


def _generated_arithmetic(count: int = 12) -> list[EvalItem]:
    """Deterministic filler so the easy band is not dominated by trivia.

    Generated rather than handwritten, and labelled as such, because the point
    of these items is volume in a known difficulty band, not variety.
    """
    items = []
    for n in range(count):
        a = 13 + (n * 7) % 60
        b = 4 + (n * 3) % 18
        items.append(
            I(f"g{n:02d}", f"What is {a} multiplied by {b}?", str(a * b), "numeric", "arithmetic")
        )
    return items


ITEMS: list[EvalItem] = HANDWRITTEN + _generated_arithmetic()


def load(limit: int | None = None) -> list[EvalItem]:
    return ITEMS[:limit] if limit else list(ITEMS)


def summary() -> dict:
    from . import features

    by_tag: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    diffs = []
    for item in ITEMS:
        by_tag[item.tag] = by_tag.get(item.tag, 0) + 1
        by_kind[item.kind] = by_kind.get(item.kind, 0) + 1
        diffs.append(features.extract(item.prompt).difficulty)
    checkable = sum(1 for i in ITEMS if i.kind != "open")
    return {
        "total": len(ITEMS),
        "checkable": checkable,
        "open_ended": len(ITEMS) - checkable,
        "by_tag": by_tag,
        "by_kind": by_kind,
        "difficulty_min": round(min(diffs), 3),
        "difficulty_mean": round(sum(diffs) / len(diffs), 3),
        "difficulty_max": round(max(diffs), 3),
    }
