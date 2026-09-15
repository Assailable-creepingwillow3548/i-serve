"""Run 3's levels: the seat count against a known prefix cache hit rate.

Data only. What each block is for, and what it is predicted to produce, is
`docs/SLO.md` section 6 and `docs/benchmarks/runsheets/l40s-run-3.md` -- the
numbers in the comments here are reminders, with the derivation living where
they point.

The three blocks answer the three open items `docs/SLO.md` section 10 opened on
2026-08-26, in the order that makes each one interpretable:

  A  seats(h)      the measurement the section predicts: 13-14 seats at h = 0,
                   24 +- 2 at h = 0.8, on a card whose decode step alone permits
                   31. Two closed-loop sweeps over the same concurrencies, one
                   with unique prompts and one behind a shared prefix.
  B  goodput(h)    the same question asked the way a customer experiences it,
                   under Poisson arrivals: run 2 measured the goodput peak at
                   1.87 req/s uncached, and section 6's claim is that removing
                   prefill work moves that peak rather than the decode step.
  C  h = 0 cost    prefix caching switched on against a workload that never
                   repeats -- hashing and block bookkeeping with nothing to
                   reuse. Both earlier runs had the feature off, so the repo has
                   no figure for what it costs when it buys nothing.

Prompt length is 4 000 tokens in blocks A and C and 1 500 in block B, and the
split is the point rather than an inconsistency: a block runs at the length of
the measurement it has to face. See SEAT_PROMPT_TOKENS below. Output is 200
tokens everywhere, matching both earlier runs, so a decode step measured here is
comparable with the 33.80 ms of run 1 without an adjustment.
"""

from . import Workload

# Concurrencies to sweep. Dense between 12 and 28 because that is where both
# predicted crossings sit -- 13/14 uncached, 24 +- 2 at h = 0.8 -- and thin
# outside it, since a level that answers nothing still costs a minute of card.
SEATS = (8, 12, 14, 16, 20, 22, 24, 26, 28)

# The conditional extension, for one outcome decided in advance: if cascade
# attention engages, the shared prefix is read once per step instead of once per
# sequence, the decode step at n = 24 falls from 43.1 ms to 28.0, and the cached
# crossing moves from 24 to 54 -- above every level in SEATS, which would report
# "seats: >= 28" and answer nothing. Written here rather than typed on a rented
# card (docs/benchmarks/runsheets/l40s-run-3.md section 5).
SEATS_EXTENDED = (32, 40, 48, 56)

# The per-level seed offset. A single constant seed across levels makes the
# prompts of a short level a byte-identical prefix of the next one's, which on a
# server with prefix caching ON turns every earlier level into cache hits for the
# later one: run 3 measured h = 0.664 / 0.854 / 0.872 on uncached levels whose
# nominal h was 0, and 24/36, 36/42, 42/48 is exactly what those numbers are.
# Offsetting the seed per level makes each level's prompts its own, so the only
# hits a level can score are the ones its own construction asks for. The offset
# is deterministic, so block C's control and treatment -- the same level against
# two server configurations -- remain byte-identical to each other.
SEED = 20260829

# Two prompt lengths, because the two questions have two controls, and a single
# constant here was the defect the run-3 runsheet caught before the card was
# rented (docs/benchmarks/runsheets/l40s-run-3.md section 0).
#
# The seat blocks answer docs/SLO.md section 6, whose prediction -- 13/14 seats
# uncached against 24 +- 2 at h = 0.8 -- is derived at 4 000-token prompts, from
# an interference model fitted at 4 000-token prompts, against a control measured
# three times at 4 000-token prompts (33.79 / 33.71 / 33.80 ms). At 1 500 tokens
# each request injects 131.2 ms of prefill instead of 349.8, so the interference
# term is 0.375x as large and both crossings move to 31 and 61 seats -- outside
# SEATS, which is the grid section 6's own numbers chose.
#
# The goodput block answers run 2, whose curve is at 1 500 tokens -- the only
# length this card serves inside the interactive TTFT budget at all
# (docs/benchmarks/l40s-run2.md section 3). Same reasoning, pointing the other
# way: a block is run at the length of the measurement it has to face.
SEAT_PROMPT_TOKENS = 4_000
RATE_PROMPT_TOKENS = 1_500
OUTPUT_TOKENS = 200


def _seat_level(concurrency: int, hit_rate: float) -> Workload:
    """One closed-loop level: a fixed batch, which is what a seat count means.

    num_prompts is three per seat so that the level contains at least three full
    waves: the first wave is still filling the batch, and a decode step measured
    while the batch is filling is not the step at that concurrency.
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

    Sized for roughly 90 seconds of arrivals, with a floor of 30 requests: a
    p99 over fewer than 30 samples is the largest sample, and reporting it as a
    percentile would dress one request up as a distribution.
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


# Block A -- the seat count, cached against uncached. Same concurrencies, same
# prompts, one difference: whether 3 200 of the 4 000 prompt tokens are shared.
# 3 200 / 16 = 200 blocks exactly, so nominal h is 0.800 and not a rounded 0.798.
SEATS_UNCACHED = tuple(_seat_level(c, 0.0) for c in SEATS)
SEATS_CACHED = tuple(_seat_level(c, 0.8) for c in SEATS)
SEATS_CACHED_EXTENDED = tuple(_seat_level(c, 0.8) for c in SEATS_EXTENDED)

# Block B -- goodput under arrivals. The lower rates overlap run 2's measured
# curve so the two can be compared level for level; the upper three exist
# because at h = 0.8 the card is predicted to hold TPOT p50 under 50 ms until
# about 6 req/s, and a sweep that stops at 4.0 would report a peak that is only
# the top of its own grid. Run 2's 0.5 and 1.0 are dropped for the same reason
# in reverse: at h = 0.8 they are far inside every target.
RATES = (1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0)
GOODPUT_CACHED = tuple(_rate_level(r, 0.8) for r in RATES)

# Two uncached levels at run 2's peak and its collapse, on *this* pod. Run 2's
# curve is the published control, but it was measured on another pod with the
# feature off, and the logged KV pool moves 4.2% between two launches of one
# identical config (docs/benchmarks/l40s-run2.md section 6). These two turn a
# cross-run comparison into a same-pod one for the price of five minutes, and
# they are first in the runsheet's drop order because the published curve stands
# in if the clock runs out.
# The conditional extension of block B, for the outcome run 3 met: at h = 0.8
# the cached curve never breached a single SLO inside RATES and reported its own
# top level back. Same rule as SEATS_EXTENDED -- a sweep whose crossing is above
# its grid answers nothing
# (docs/benchmarks/runsheets/l40s-run-3.md section 5).
RATES_EXTENDED = (9.0, 11.0, 13.0)
GOODPUT_EXTENDED = tuple(_rate_level(r, 0.8) for r in RATES_EXTENDED)

RATES_BRIDGE = (2.5, 4.0)
GOODPUT_BRIDGE = tuple(_rate_level(r, 0.0) for r in RATES_BRIDGE)

# Block C -- what the feature costs when it buys nothing. One level, run twice:
# once on a server with prefix caching off and once with it on, differing in the
# flag and in nothing else. c = 13 with 4 000-token unique prompts is run 1's and
# run 2's exact geometry, so the same level also carries the reproducibility read
# (33.79 / 33.71 / 33.80 ms measured across three launches). The comparison is
# the decode step, the one quantity reproducible to 0.25% across launches
# (docs/benchmarks/l40s-run2.md section 6), so it is the only one that can carry
# a difference this small -- and running both halves on one pod is what keeps a
# 1% effect from being read against a 4% instrument.
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

# What the CLI accepts. A run is a named list of levels, so that what was
# executed is recoverable from the artefacts by name rather than by a shell
# history that lives on a pod which no longer exists.
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
