"""Aggregation of one level's records into the numbers a run reports.

Pure functions over bench/loadgen.py's Records: no sockets, clock or files, so
the arithmetic is testable without a card. Every metric is defined in
docs/GLOSSARY.md and computed as `vllm bench serve` computes it, so levels
from this harness compare with the earlier runs. What this module adds is a
validity flag: a number that cannot legally face a target -- a closed loop's
TTFT, a TTFT below the prefill floor -- is marked where it is computed.
"""

import math
from dataclasses import dataclass, field

from loadgen import Record


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile, matching numpy's default method.

    Written out because numpy is not on the pod. Matching numpy matters: the
    earlier runs came from `vllm bench serve`, which uses np.percentile, and a
    nearest-rank convention differs by one sample at exactly the SLO tails.
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
    """The promise a level is scored against, in seconds.

    Defaults are the interactive class (docs/SLO.md section 2); the batch class
    is another pair against the same code, hence an argument, not a constant.
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
        # A single-token response has no TPOT to breach; it is good if TTFT was.
        if tpot is not None and tpot > self.tpot:
            return False
        if self.e2el is not None and rec.latency > self.e2el:
            return False
        return True


def max_concurrent(records: list[Record]) -> int:
    """The largest number of requests in flight at once, by a sweep line.

    An output in an open-loop run: how deep the server let the queue get,
    checked against the engine's own num_requests_running.
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

    Seconds here; milliseconds only in as_vllm_json, so a level reads like
    docs/benchmarks/raw/l40s-2026-08-23/machine/*.json.
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
        """TPOT p50 minus median ITL, the independent variable of
        seats_under_prefill_interference() (SLO.md section 6).
        """
        return self.tpot["p50"] - self.itl["p50"]

    @property
    def tpot_over_median_itl(self) -> float:
        """How unevenly prefill is spread, not how much of it there is.

        Collapses to 1.0 once prefill lands in nearly every step
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

    Failures are counted, never dropped: 5 of 60 failed is a different fact
    from a level of 55.
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
        # A closed loop's TTFT is the generator's queue (docs/GLOSSARY.md): kept
        # as a relative figure between levels, but labelled before it leaves.
        invalid.append("ttft-not-a-service-metric: closed loop")

    if failed:
        warnings.append(f"{len(failed)} of {len(records)} requests failed")

    max_lateness = max((r.lateness for r in records), default=0.0)
    if mode != "closed" and max_lateness > 0.050:
        # More than a decode step behind its own arrivals: drifting toward a
        # closed loop, so part of this TTFT is the harness's.
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

    LevelStats is frozen: a later check (prefill floor, hit rate, pool gate)
    produces a new level rather than editing a measurement.
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

    Same keys and units (milliseconds), so one loader reads run 2's files and
    this harness's alike. Harness-only fields are namespaced `harness_` so
    nothing can mistake one for a vLLM output.
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
