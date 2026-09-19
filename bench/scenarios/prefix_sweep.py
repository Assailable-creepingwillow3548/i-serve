"""Run 3's levels: the seat count against a known prefix cache hit rate.

Data only. Blocks A (seats vs h), B (goodput vs h) and C (the cost of caching at
h = 0) answer docs/SLO.md section 6; predictions and drop order are in
docs/benchmarks/runsheets/l40s-run-3.md. Output is 200 tokens everywhere, as in
runs 1 and 2, so decode steps compare without adjustment.
"""

from . import Workload

# Dense between 12 and 28, where both predicted crossings sit (docs/SLO.md
# section 6); thin outside, since an empty level still costs a minute of card.
SEATS = (8, 12, 14, 16, 20, 22, 24, 26, 28)

# If cascade attention engages, the cached crossing moves above SEATS
# (docs/benchmarks/runsheets/l40s-run-3.md section 5).
SEATS_EXTENDED = (32, 40, 48, 56)

# Offset per level: one seed makes a short level's prompts a prefix of the next
# level's, and a caching server then scores hits nominal h did not ask for
# (docs/benchmarks/l40s-run3.md). The offset is deterministic, so block C's two
# halves stay byte-identical.
SEED = 20260829

# Each block runs at the prompt length of the measurement it faces: the seat
# prediction is derived at 4 000 tokens, run 2's goodput curve at 1 500
# (docs/benchmarks/runsheets/l40s-run-3.md section 0).
SEAT_PROMPT_TOKENS = 4_000
RATE_PROMPT_TOKENS = 1_500
OUTPUT_TOKENS = 200


def _seat_level(concurrency: int, hit_rate: float) -> Workload:
    """One closed-loop level: a fixed batch, which is what a seat count means.

    Three prompts per seat, so the batch is full for at least two waves.
    """
    return Workload(
        name=f"seats-c{concurrency}-h{int(hit_rate * 100):02d}",
        prompt_tokens=SEAT_PROMPT_TOKENS,
        output_tokens=OUTPUT_TOKENS,
        num_prompts=max(24, 3 * concurrency),
        mode="closed",
        concurrency=concurrency,
        hit_rate_target=hit_rate,
        seed=SEED + concurrency,
    )


def _rate_level(rate: float, hit_rate: float) -> Workload:
    """One open-loop level: an arrival rate, which is what goodput means.

    ~90 s of arrivals, at least 30 requests: a p99 over fewer is one sample.
    """
    return Workload(
        name=f"rate-{rate:g}-h{int(hit_rate * 100):02d}",
        prompt_tokens=RATE_PROMPT_TOKENS,
        output_tokens=OUTPUT_TOKENS,
        num_prompts=max(30, int(rate * 90)),
        mode="poisson",
        request_rate=rate,
        hit_rate_target=hit_rate,
        seed=SEED + 1_000 + int(rate * 10),
    )


# Block A -- same levels, one difference: 3 200 of 4 000 prompt tokens shared
# (200 blocks of 16, so nominal h = 0.800 exactly).
SEATS_UNCACHED = tuple(_seat_level(c, 0.0) for c in SEATS)
SEATS_CACHED = tuple(_seat_level(c, 0.8) for c in SEATS)
SEATS_CACHED_EXTENDED = tuple(_seat_level(c, 0.8) for c in SEATS_EXTENDED)

# Block B -- goodput under arrivals. Lower rates overlap run 2's curve; upper
# rates reach past the predicted cached peak (~6 req/s, runsheet section 3).
RATES = (1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0)
GOODPUT_CACHED = tuple(_rate_level(r, 0.8) for r in RATES)

# Run 2's peak and collapse re-measured on this pod, so block B compares
# same-pod, not cross-pod (docs/benchmarks/l40s-run2.md section 6).
# Extension for the outcome run 3 met: nothing breached inside RATES
# (docs/benchmarks/runsheets/l40s-run-3.md section 5).
RATES_EXTENDED = (9.0, 11.0, 13.0)
GOODPUT_EXTENDED = tuple(_rate_level(r, 0.8) for r in RATES_EXTENDED)

RATES_BRIDGE = (2.5, 4.0)
GOODPUT_BRIDGE = tuple(_rate_level(r, 0.0) for r in RATES_BRIDGE)

# Block C -- prefix caching on vs off at h = 0, one level, same pod. c = 13 at
# 4 000 tokens is run 1/2's geometry, so it carries the reproducibility read too
# (docs/benchmarks/l40s-run2.md section 6: only the decode step resolves ~1%).
OVERHEAD = (
    Workload(
        name="overhead-c13-h00",
        prompt_tokens=SEAT_PROMPT_TOKENS,
        output_tokens=OUTPUT_TOKENS,
        num_prompts=39,
        mode="closed",
        concurrency=13,
        hit_rate_target=0.0,
    ),
)

# A run is a named list of levels, so the artefacts say what ran.
SCENARIOS: dict[str, tuple[Workload, ...]] = {
    "seats-uncached": SEATS_UNCACHED,
    "seats-cached": SEATS_CACHED,
    "seats-cached-extended": SEATS_CACHED_EXTENDED,
    "goodput-cached": GOODPUT_CACHED,
    "goodput-cached-extended": GOODPUT_EXTENDED,
    "goodput-bridge": GOODPUT_BRIDGE,
    "overhead": OVERHEAD,
    "smoke": (
        Workload(
            name="smoke-c2-h50",
            prompt_tokens=256,
            output_tokens=8,
            num_prompts=4,
            mode="closed",
            concurrency=2,
            hit_rate_target=0.5,
        ),
    ),
}
