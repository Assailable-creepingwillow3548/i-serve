"""The engine's own numbers: /metrics counters between levels, and the startup log.

The client can only measure what it can see from outside, and two of run 3's
questions are not visible from there. The prefix cache hit rate `h` is one --
vLLM's V1 engine exposes no gauge for it, only the token counters
`vllm:prefix_cache_queries` and `vllm:prefix_cache_hits`, whose ratio *over a
window* is h (docs/GLOSSARY.md). The KV pool is the other, and it is not in
/metrics at all: it is logged once at startup, and docs/SLO.md section 9 puts
that log above every derivation in this repository.

So this module does two things and nothing else: scrape counters around a level,
and read the startup log's facts out of a file. Both return plain numbers; what
they mean for a level is bench/harness.py's job.

The window discipline is the point. A hit rate averaged over a whole session
answers no question -- it mixes the cold first level with the warm last one --
which is why the open item in docs/SLO.md section 10 specifies increments *per
concurrency level*. Hence Snapshot and delta(), rather than a "read the gauge"
function that would look simpler and be wrong.
"""

import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

# Counters and gauges worth carrying. Everything else vLLM exports is left on
# the floor: a snapshot is written into the run's artefacts, and a file that
# holds a hundred series per level stops being readable evidence.
COUNTERS = (
    "vllm:prefix_cache_queries",
    "vllm:prefix_cache_hits",
    "vllm:num_preemptions",
    "vllm:prompt_tokens",
    "vllm:generation_tokens",
    "vllm:request_success",
)
GAUGES = (
    "vllm:num_requests_running",
    "vllm:num_requests_waiting",
    "vllm:gpu_cache_usage_perc",
    "vllm:gpu_prefix_cache_hit_rate",   # V0 only; absent on V1, kept as a probe
)

_SAMPLE = re.compile(r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?P<labels>\{[^}]*\})?\s+"
                     r"(?P<value>[-+0-9.eEnaN]+)\s*$")


def parse_prometheus(text: str) -> dict[str, float]:
    """Sum every series of a metric into one number per metric name.

    Summing across label sets is correct for what this harness reads and would
    be wrong for what it does not read. vLLM labels these counters with
    model_name, and one server serves one model here, so the sum is the series;
    a histogram's _bucket lines would not survive this treatment, which is why
    no histogram is in COUNTERS or GAUGES.

    Counter suffixes (_total) are folded onto the base name, because the client
    library adds them and the documentation, the glossary and docs/SLO.md all
    speak of `vllm:prefix_cache_hits` without one.
    """
    out: dict[str, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _SAMPLE.match(line)
        if not match:
            continue
        name = match.group("name")
        if name.endswith("_total"):
            name = name[: -len("_total")]
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        out[name] = out.get(name, 0.0) + value
    return out


@dataclass(frozen=True)
class Snapshot:
    """Everything /metrics said at one instant, plus when that instant was."""

    at: float
    values: dict[str, float]

    def get(self, name: str) -> float | None:
        return self.values.get(name)


def scrape(host: str = "127.0.0.1", port: int = 8000,
           timeout: float = 5.0) -> Snapshot:
    """One GET /metrics, parsed. A plain blocking call, urllib and nothing else.

    Blocking is right for what this is -- a step between levels, not part of one
    -- but it must never run *on* the event loop: while the loop is blocked on a
    socket it cannot timestamp an arriving token, so a scrape in the wrong place
    lands in the ITL distribution as a stall the server never produced. The
    harness therefore calls it through asyncio.to_thread, which is also what
    lets the whole thing be tested against an in-process fake server.
    """
    url = f"http://{host}:{port}/metrics"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        text = response.read().decode("utf-8", "replace")
    return Snapshot(at=time.perf_counter(), values=parse_prometheus(text))


def delta(before: Snapshot, after: Snapshot) -> dict[str, float]:
    """Counter increments across a window. Gauges are taken from `after`.

    A counter that went *down* means the server restarted mid-level, and that is
    raised rather than clamped: every comparison across levels assumes one
    engine process, and a silent 0 would hide the one event that invalidates the
    whole sweep.
    """
    out: dict[str, float] = {}
    for name in COUNTERS:
        start, end = before.values.get(name), after.values.get(name)
        if start is None or end is None:
            continue
        if end < start:
            raise ValueError(
                f"{name} fell from {start:.0f} to {end:.0f}: the engine restarted "
                f"during this level, so no counter increment across it is meaningful"
            )
        out[name] = end - start
    for name in GAUGES:
        if name in after.values:
            out[name] = after.values[name]
    return out


def hit_rate(increments: dict[str, float]) -> float | None:
    """`h` over the window: hit tokens divided by queried tokens.

    Returns None rather than 0.0 when nothing was queried. The two are different
    findings -- "the cache served none of it" against "prefix caching is off, so
    the counters do not exist" -- and a level that reports 0.0 for the second
    would look like a measurement of the first.
    """
    queries = increments.get("vllm:prefix_cache_queries")
    hits = increments.get("vllm:prefix_cache_hits")
    if not queries:
        return None
    return hits / queries if hits is not None else None


# --- the startup log ---------------------------------------------------------
#
# Wording taken from run 2's own log, docs/benchmarks/raw/l40s-2026-08-23/
# startup-lines.txt. It changes between vLLM versions, which is exactly why
# these patterns live in one place with the file that produced them named: when
# a future version renames a line, one regex fails loudly instead of a gate
# quietly passing on a missing value.

_LOG_PATTERNS = {
    "kv_cache_tokens": re.compile(r"GPU KV cache size:\s*([\d,]+)\s*tokens", re.I | re.S),
    "kv_cache_gib": re.compile(r"kv cache memory in use is\s*([\d.]+)\s*GiB", re.I),
    "max_concurrency": re.compile(r"Maximum concurrency[\s\S]*?([\d.]+)x", re.I),
    "max_num_batched_tokens": re.compile(r"max_num_batched_tokens[=:]\s*([\d]+)"),
    "max_num_seqs": re.compile(r"max_num_seqs[=:]\s*([\d]+)"),
    "enable_prefix_caching": re.compile(r"enable_prefix_caching[=:]\s*'?(True|False)'?"),
    "kv_cache_dtype": re.compile(r"kv_cache_dtype[=:]\s*'?([\w]+)'?"),
    "attention_backend": re.compile(r"Using (\w+) attention", re.I),
}


def read_startup_log(path: str) -> dict[str, float | str]:
    """Pull the facts a run is gated on out of a vLLM startup log.

    The four that matter, and why each is here rather than assumed:
    the KV pool in tokens, because two launches of one identical config differed
    by 4.2% and every seat count divides by it; prefix caching's actual state,
    because a run measuring the cache against a server that has it off is the
    most expensive possible way to measure nothing; the KV dtype and the
    attention backend, because run 2 found one flag changing both
    (docs/benchmarks/l40s-run2.md section 5).
    """
    with open(path, encoding="utf-8", errors="replace") as handle:
        text = handle.read()

    found: dict[str, float | str] = {}
    for key, pattern in _LOG_PATTERNS.items():
        match = pattern.search(text)
        if not match:
            continue
        raw = match.group(1)
        if key in ("enable_prefix_caching", "kv_cache_dtype", "attention_backend"):
            found[key] = raw
        else:
            found[key] = float(raw.replace(",", ""))
    return found


def unread_startup_facts(facts: dict[str, float | str]) -> tuple[str, ...]:
    """Which of the gated facts the log did not yield.

    read_startup_log returns only what matched, which is the right contract for
    a parser and the wrong one for an operator: a renamed log line then removes a
    gate instead of failing, and nothing says so. bench/harness.py gates the KV
    pool only `if "kv_cache_tokens" in facts`, so a version that renames that
    line runs the whole sweep ungated and prints nothing about it.

    Run 2 met this failure twice in one session -- VLLM_ATTENTION_BACKEND
    accepted and ignored, and `--help` no longer listing flags, both of which
    looked like an absent feature rather than a changed name
    (docs/benchmarks/runsheets/l40s-run-2.md, postscript items 3 and 4). This
    function is that lesson as code: the misses are returned so the caller can print them,
    and the operator learns in the first minute rather than never.
    """
    return tuple(key for key in _LOG_PATTERNS if key not in facts)


def pool_gate(logged_tokens: float, reference_tokens: float,
              tolerance: float = 0.05) -> tuple[bool, str]:
    """Is this pod's KV pool the same one the reference run measured?

    The tolerance is 5% and it is not a round number chosen for comfort: two
    launches of one identical configuration moved the logged pool by 4.2%
    (docs/benchmarks/l40s-run2.md section 6). A tighter gate would fail on the
    platform's own noise, which is the defect run 2's checkpoint gate had -- it
    asked for +-0.3% of a quantity that moves 4.2%.
    """
    ratio = logged_tokens / reference_tokens
    ok = abs(ratio - 1.0) <= tolerance
    verdict = (
        f"KV pool {logged_tokens:,.0f} tokens against reference {reference_tokens:,.0f} "
        f"({ratio:.3f}x, gate +-{tolerance:.0%}): {'PASS' if ok else 'FAIL'}"
    )
    return ok, verdict
