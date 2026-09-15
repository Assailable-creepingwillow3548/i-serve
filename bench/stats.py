"""Aggregation of one level's records into the numbers a run reports.

Pure functions over the Records that bench/loadgen.py produces: no sockets, no
clock, no files. That is what makes the arithmetic testable on a laptop, with no
card and no server, and what keeps a change to the HTTP client from touching the
definition of TPOT.

Every metric here is defined in docs/GLOSSARY.md and computed the way
`vllm bench serve` computes it, deliberately: this repository already holds 22
levels measured with that tool, and a harness whose TPOT means something
slightly different would silently break every comparison with run 1 and run 2.
The three definitions that matter, restated so the code can be checked against
them without opening another file:

  TPOT        mean ITL *of one request*, undefined below two output tokens
  median ITL  the median over all inter-token gaps of all requests, pooled
  goodput     completed requests meeting *every* stated threshold, per second

The one thing this module adds to that tool's output is a validity flag. A
number that cannot legally be compared to a target -- a TTFT from a closed loop,
a TTFT below the prefill floor -- is marked at the point where it is computed,
not in the prose of a write-up later.
"""

import math
from dataclasses import dataclass, field

from loadgen import Record


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile, matching numpy's default `linear` method.

    Written out rather than imported because numpy is not installed on the pod
    and this is nine lines. Matching numpy is not vanity: run 1 and run 2's
    figures came from `vllm bench serve`, which uses np.percentile, and a
    harness that used the nearest-rank convention instead would differ from them
    by one sample at exactly the tail percentiles the SLO is written against.
    """
    if not values:
        return math.nan
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (q / 100.0) * (len(ordered) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


@dataclass(frozen=True)
class SLOTargets:
    """The promise a level is scored against, in seconds (SI, per section 7).

    Defaults are the interactive class of docs/SLO.md section 2. The batch class
    is a different pair of numbers against the same code, which is the whole
    reason this is an argument rather than a constant.
    """

    ttft: float = 0.300
    tpot: float = 0.050
    e2el: float | None = None

    def met_by(self, rec: Record) -> bool:
        if not rec.ok or rec.latency is None:
            return False
        if rec.ttft > self.ttft:
            return False
        tpot = rec.tpot
        # A single-token response has no TPOT to breach. It counts as good if it
        # met TTFT: refusing to count it would let a level's goodput fall for a
        # reason no user could perceive.
        if tpot is not None and tpot > self.tpot:
            return False
        if self.e2el is not None and rec.latency > self.e2el:
            return False
        return True


def max_concurrent(records: list[Record]) -> int:
    """The largest number of requests in flight at once, by a sweep line.

    Reported because in an open-loop run it is an *output*: it is how deep the
    server actually let the queue get, and comparing it with the engine's own
    num_requests_running is the cheapest check that client and server agree on
    what was happening.
    """
    events: list[tuple[float, int]] = []
    for rec in records:
        if rec.latency is None:
            continue
        events.append((rec.sent, +1))
        events.append((rec.sent + rec.latency, -1))
    events.sort(key=lambda e: (e[0], -e[1]))
    peak = live = 0
    for _, delta in events:
        live += delta
        peak = max(peak, live)
    return peak


@dataclass(frozen=True)
class LevelStats:
    """One benchmark level, aggregated. Field names mirror `vllm bench serve`.

    Times are seconds here and converted to milliseconds only in as_vllm_json,
    which exists so a level of this harness can be read by the same eyes and the
    same loaders as docs/benchmarks/raw/l40s-2026-08-23/machine/*.json.
    """

    label: str
    mode: str                      # "closed" | "poisson"
    duration: float
    completed: int
    failed: int
    total_input_tokens: int
    total_output_tokens: int

    ttft: dict[str, float]         # mean/p50/p90/p99
    tpot: dict[str, float]
    itl: dict[str, float]
    e2el: dict[str, float]

    request_throughput: float
    output_throughput: float
    total_token_throughput: float
    goodput: float
    max_concurrent_requests: int
    max_lateness: float

    invalid: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    extra: dict[str, float] = field(default_factory=dict)

    @property
    def prefill_interference(self) -> float:
        """TPOT p50 minus median ITL: the quantity SLO.md section 6 extrapolates.

        Not a derived convenience -- it is the independent variable of
        seats_under_prefill_interference(), so it is computed here once rather
        than by every caller that wants to fit the line again.
        """
        return self.tpot["p50"] - self.itl["p50"]

    @property
    def tpot_over_median_itl(self) -> float:
        """How *unevenly* prefill is spread, not how much of it there is.

        Run 1 read this ratio as the amount of interference and run 2 corrected
        it: it collapses to 1.0 once prefill lands in nearly every step, which is
        also the point where the median stops being a decode step at all
        (docs/benchmarks/l40s-run2.md section 6).
        """
        return self.tpot["p50"] / self.itl["p50"] if self.itl["p50"] > 0 else math.inf


def _spread(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": math.nan, "p50": math.nan, "p90": math.nan, "p99": math.nan}
    return {
        "mean": sum(values) / len(values),
        "p50": percentile(values, 50),
        "p90": percentile(values, 90),
        "p99": percentile(values, 99),
    }


def summarize(
        label: str, mode: str, records: list[Record], duration: float,
        targets: SLOTargets) -> LevelStats:
    """Turn one level's records into its row of the report.

    Failures are counted, never dropped silently and never retried upstream: a
    level where 5 of 60 requests failed is a different fact from a level of 55
    requests, and only the count keeps the two apart.
    """
    ok = [r for r in records if r.ok and r.latency is not None]
    failed = [r for r in records if not r.ok]

    ttfts = [r.ttft for r in ok]
    tpots = [r.tpot for r in ok if r.tpot is not None]
    itls = [gap for r in ok for gap in r.itls]      # pooled, as vllm does
    e2els = [r.latency for r in ok]

    output_tokens = sum(r.output_tokens for r in ok)
    input_tokens = sum(r.prompt_tokens for r in ok)
    good = sum(1 for r in ok if targets.met_by(r))

    invalid: list[str] = []
    warnings: list[str] = []

    if mode == "closed":
        # docs/GLOSSARY.md, closed loop: the queue this TTFT measures belongs to
        # the generator, so the number may never be compared with a target. It is
        # still computed -- it is a useful *relative* figure between levels of the
        # same shape -- but it leaves this function already labelled.
        invalid.append("ttft-not-a-service-metric: closed loop")

    if failed:
        warnings.append(f"{len(failed)} of {len(records)} requests failed")

    max_lateness = max((r.lateness for r in records), default=0.0)
    if mode != "closed" and max_lateness > 0.050:
        # The generator fell behind its own arrival process by more than a
        # decode step's worth of time, so the level is drifting toward a closed
        # loop and its TTFT is partly the harness's.
        warnings.append(f"generator lateness up to {max_lateness * 1e3:.0f} ms")

    return LevelStats(
        label=label,
        mode=mode,
        duration=duration,
        completed=len(ok),
        failed=len(failed),
        total_input_tokens=input_tokens,
        total_output_tokens=output_tokens,
        ttft=_spread(ttfts),
        tpot=_spread(tpots),
        itl=_spread(itls),
        e2el=_spread(e2els),
        request_throughput=len(ok) / duration if duration > 0 else math.nan,
        output_throughput=output_tokens / duration if duration > 0 else math.nan,
        total_token_throughput=(input_tokens + output_tokens) / duration
                                if duration > 0 else math.nan,
        goodput=good / duration if duration > 0 else math.nan,
        max_concurrent_requests=max_concurrent(ok),
        max_lateness=max_lateness,
        invalid=tuple(invalid),
        warnings=tuple(warnings),
    )


def with_flag(stats: LevelStats, *, invalid: str = "", warning: str = "",
              extra: dict[str, float] | None = None) -> LevelStats:
    """Return the level with one more flag or a few more fields attached.

    LevelStats is frozen because a measurement should not be edited after the
    fact; a check that runs later (the prefill floor, the hit rate, the KV pool
    gate) therefore produces a *new* level rather than mutating one. The
    provenance stays visible in the code that did it.
    """
    from dataclasses import replace
    merged = dict(stats.extra)
    if extra:
        merged.update(extra)
    return replace(
        stats,
        invalid=stats.invalid + ((invalid,) if invalid else ()),
        warnings=stats.warnings + ((warning,) if warning else ()),
        extra=merged,
    )


def as_vllm_json(stats: LevelStats) -> dict:
    """The level in `vllm bench serve`'s own JSON shape, plus this run's extras.

    Same keys, same units (milliseconds), so measured_run3.py can load a level
    from this harness with the loader written for run 2's files, and so a figure
    quoted in docs/benchmarks/ can be found in either kind of artefact by the
    same name. The harness-only fields are namespaced under `harness_` for the
    opposite reason: nothing should be able to mistake one for a vLLM output.
    """
    ms = 1e3
    out = {
        "label": stats.label,
        "duration": stats.duration,
        "completed": stats.completed,
        "failed": stats.failed,
        "total_input_tokens": stats.total_input_tokens,
        "total_output_tokens": stats.total_output_tokens,
        "request_throughput": stats.request_throughput,
        "request_goodput": stats.goodput,
        "output_throughput": stats.output_throughput,
        "total_token_throughput": stats.total_token_throughput,
        "max_concurrent_requests": stats.max_concurrent_requests,
    }
    for name, spread in (("ttft", stats.ttft), ("tpot", stats.tpot),
                         ("itl", stats.itl), ("e2el", stats.e2el)):
        out[f"mean_{name}_ms"] = spread["mean"] * ms
        out[f"p50_{name}_ms"] = spread["p50"] * ms
        out[f"median_{name}_ms"] = spread["p50"] * ms
        out[f"p90_{name}_ms"] = spread["p90"] * ms
        out[f"p99_{name}_ms"] = spread["p99"] * ms

    out["harness_mode"] = stats.mode
    out["harness_prefill_interference_ms"] = stats.prefill_interference * ms
    out["harness_tpot_over_median_itl"] = stats.tpot_over_median_itl
    out["harness_max_lateness_ms"] = stats.max_lateness * ms
    out["harness_invalid"] = list(stats.invalid)
    out["harness_warnings"] = list(stats.warnings)
    out.update({f"harness_{k}": v for k, v in stats.extra.items()})
    return out
