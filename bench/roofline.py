"""Roofline floors for LLM inference.

Given a model architecture (from config.json) and an accelerator spec (from the
vendor table), compute what the hardware can physically do. A floor is a ceiling
on performance, not a forecast: the gap between a floor and a measurement is
queueing and overhead. See docs/SLO.md for the derivations this module encodes.

A library and nothing else. The tables it used to print are bench/predictions.py
and the checks against docs/SLO.md are bench/tests/test_roofline.py -- both import
from here, neither is imported by it.

Layered in dependency order, and read that way: specs (Model, Accelerator) ->
traffic (decode_step_bytes, prefill_bytes, kv_cache_tokens) -> comparison
(roofline) -> floors (tpot_floor, ttft_floor) -> inversions
(max_num_seqs_from_slo, concurrency_ceiling, max_num_seqs) -> money
(aggregate_tokens_per_sec, cost_per_1m_tokens). Every layer is the previous one
divided by something.

Each side of a roofline is divided by its own coefficient -- eff_mem for memory,
mfu for compute -- before the max(), so the two times compared are both
achievable. Comparing a derated time against a peak time mixes bases and inflates
the ratio; SLO.md section 4 states the same convention.

TODO, in dependency order. The numbers are stable -- notes elsewhere refer to
items by number, so a finished item leaves the list rather than renumbering the
rest. Item 6, the predicted-vs-measured table, closed on 2026-08-20 as
bench/measured.py, against run 1's results.jsonl.

Not a step, but owed before quantised weights are benchmarked: widen
weight_dtype_bytes and kv_dtype_bytes from int to float. 4-bit weight
quantisation (AWQ, GPTQ) is 0.5 bytes per parameter, which int cannot express.
"""

import math
from dataclasses import dataclass
from typing import NamedTuple

FLOPS_PER_MAC = 2


@dataclass(frozen=True)
class Model:
    """Architecture, as read from config.json plus the model card.

    Two parameter counts, because they answer different questions:
    memory moves every weight, but embeddings are a table lookup, not a matmul.
    """

    name: str
    params_total: float           # memory side: all weights are read
    params_non_embedding: float   # compute side: embeddings contribute no FLOPs
    num_layers: int               # config.json: num_hidden_layers
    num_kv_heads: int             # config.json: num_key_value_heads (GQA groups)
    head_dim: int                 # config.json: head_dim
    weight_dtype_bytes: int = 2   # BF16
    kv_dtype_bytes: int = 2       # BF16 KV cache; 1 for FP8

    @property
    def weights_bytes(self) -> float:
        """Read once per forward pass, regardless of batch size."""
        return self.params_total * self.weight_dtype_bytes

    @property
    def kv_bytes_per_token(self) -> float:
        """Read once per sequence per decode step. The leading 2 is K and V."""
        return (
            2
            * self.num_kv_heads
            * self.head_dim
            * self.kv_dtype_bytes
            * self.num_layers
        )


@dataclass(frozen=True)
class Accelerator:
    """Vendor spec table, dense rows only -- never the sparsity row."""

    name: str
    memory_bytes: float
    peak_bandwidth: float         # bytes/s
    peak_flops: float             # FLOP/s, BF16 dense
    achieved_bandwidth: float     # empirical, see SLO.md section 9
    mfu: float                    # empirical, prefill

    # Where achieved_bandwidth and mfu came from, in the reader's words rather
    # than the author's: "measured (run 1, 2026-08-18)" or "prior, unvalidated".
    # It carries no arithmetic and nothing reads it but the printers -- the
    # point is that a floor printed from a prior and a floor printed from a fit
    # cannot look alike on the page. Defaults to empty, and the printers say so
    # out loud, because a default that asserted provenance would be the exact
    # failure this field exists to prevent.
    provenance: str = ""


class Roofline(NamedTuple):
    seconds: float
    bound_by: str               # "memory" | "compute"
    ratio: float                # how many times the binding side exceeds the other


class Concurrency(NamedTuple):
    """What max_num_seqs should be set to, and which constraint decided it.

    Same shape as Roofline and for the same reason: a bare min() throws away
    which side gave the minimum, and that is the fact an operator acts on. The
    two limits are kept alongside the answer because the gap between them is
    what says whether a knob is worth touching -- SLO.md section 4's last row is
    exactly this ratio, 1.08 on MI300X and 1.96 on L40S.

    "capacity", not "memory": both limits are memory limits. One is how many
    bytes the card holds, the other how many bytes per second it can move within
    the latency budget. Calling the first one "memory" hides that decode is
    bounded by the same resource twice, in two different units.
    """

    sequences: int              # what ships: the smaller of the two
    bound_by: str               # "capacity" | "latency"
    by_capacity: int            # bytes the card holds
    by_latency: int             # bytes per second, inside the TPOT target
    ratio: float                # how far apart the two limits are; inf if either is 0


QWEN3_8B = Model(
    name="Qwen3-8B",
    params_total=8.2e9,
    params_non_embedding=6.95e9,
    num_layers=36,
    num_kv_heads=8,
    head_dim=128,
)

# A second architecture, for the calculator's comparison and nothing else: this
# stack never serves it and no run here has measured it. Same head_dim, but four
# KV heads against eight and 28 layers against 36, so its KV per token is 2.6x
# smaller and the same card seats far more of it -- which is the whole point of
# having it on the page: "an 8B model" does not determine a seat count, the KV
# geometry does. Dense, GQA, full attention (`use_sliding_window: false`), so the
# formulas above hold for it as written; an architecture from the four families
# in GLOSSARY.md would need different ones, which is why this list stays short.
#
# config.json: num_hidden_layers 28, num_key_value_heads 4, and head_dim as
# hidden_size / num_attention_heads = 3584 / 28 = 128, the key being absent from
# a qwen2 config. Parameter counts from the model card, 7.61B total and 6.53B
# non-embedding -- the same convention as above, total minus the embedding table
# and the untied lm_head.
QWEN2_5_7B = Model(
    name="Qwen2.5-7B-Instruct",
    params_total=7.61e9,
    params_non_embedding=6.53e9,
    num_layers=28,
    num_kv_heads=4,
    head_dim=128,
)

MI300X = Accelerator(
    name="AMD Instinct MI300X",
    memory_bytes=192e9,
    peak_bandwidth=5.3e12,
    peak_flops=1.307e15,
    achieved_bandwidth=0.70,    # unvalidated; SLO.md section 9, not measured on this card
    mfu=0.45,                   # unvalidated; prefill figure, not measured on this card
    provenance="prior, unvalidated; no run on this card",
)

L40S = Accelerator(
    name="NVIDIA L40S",
    memory_bytes=48e9,
    peak_bandwidth=864e9,
    peak_flops=362.05e12,
    achieved_bandwidth=0.70,    # unvalidated; SLO.md section 9, not measured on this card
    mfu=0.45,                   # unvalidated; prefill figure, not measured on this card
    provenance="prior, unvalidated; the spec-sheet card, kept for contrast",
)

# The same card with the coefficients run 1 fitted (2026-08-18; SLO.md section 9
# and docs/benchmarks/l40s-baseline.md). A separate instance rather than an edit
# to L40S above, for the reason section 9 gives: a coefficient fitted to a run is
# a hypothesis until a *later* run it did not see faces it. Keeping both means a
# prediction can be printed against either, and the predicted-vs-measured table
# can say which one produced each row -- which is the whole requirement.
#
# achieved_bandwidth is the median-ITL fit across twelve levels, spread +-0.02;
# mfu is the single uncontended prefill point, one request alone on the card.
# Both are L40S x this vLLM build x BF16 KV, and neither transfers to MI300X.
L40S_RUN1 = Accelerator(
    name="NVIDIA L40S (run 1 coefficients)",
    memory_bytes=48e9,
    peak_bandwidth=864e9,
    peak_flops=362.05e12,
    achieved_bandwidth=0.83,    # measured, decode, median ITL, twelve levels
    mfu=0.439,                  # measured, prefill, one uncontended request
    provenance="measured (run 1, 2026-08-18); survived runs 2-3",
)


# The cards by name, for anything that takes one from a command line. It lives
# here rather than in the module that first needed it (bench/harness.py, until
# 2026-09-11) for the reason the layering above states: a card is physics, and
# the load harness is not the only caller that has to name one. Adding a card is
# an edit here and nowhere else.
#
# Keys are what a --accelerator flag accepts, so they are lowercase and stable:
# a rename is a breaking change to every runsheet that prints a command.
ACCELERATORS = {
    "l40s-run1": L40S_RUN1,
    "l40s": L40S,
    "mi300x": MI300X,
}


def decode_step_bytes(model: Model, batch_size: int, context_len: int) -> float:
    """Bytes moved per decode step: weights once, KV per sequence.

    Every other decode figure derives from this one. Dividing it by batch_size
    gives bytes per generated token, which is what cost per million tokens is
    proportional to.
    """
    return (
        model.weights_bytes
        + model.kv_bytes_per_token * batch_size * context_len
    )


def kv_cache_tokens(
        model: Model, accel: Accelerator,
        gpu_memory_utilization: float) -> float:
    """Tokens of KV that fit in what is left after the weights.

    Independent of context_len and batch: a token of KV costs the same whichever
    sequence it belongs to, which is why the pool is measured in tokens and only
    then divided into sequences.

    gpu_memory_utilization has no default on purpose -- it is a server knob, not
    a property of the model or the card, and a default would put an assumption
    where no call site can see it (the same defect as the coefficients).

    This is an over-estimate: vLLM's share also holds activations and CUDA graph
    buffers, which are not modelled here. The engine logs the real figure at
    startup, and that log outranks this derivation (SLO.md section 9).
    """
    kv_space = accel.memory_bytes * gpu_memory_utilization - model.weights_bytes
    if kv_space < 0:
        # Not "zero sequences fit" but "this model cannot be served here at all":
        # a deployment error, not an operating point, so it is worth an exception
        # rather than a 0 that reads like a scheduling answer.
        raise ValueError(
            f"{model.name} weights ({model.weights_bytes / 1e9:.1f} GB) exceed "
            f"the {gpu_memory_utilization:.0%} share of {accel.name} "
            f"({accel.memory_bytes * gpu_memory_utilization / 1e9:.1f} GB): "
            f"no KV cache remains"
        )
    return kv_space / model.kv_bytes_per_token


def roofline(memory: float, compute: float) -> Roofline:
    """Compares two achievable times and returns the roofline.
    """
    if memory > compute:
        seconds, bound_by, other = memory, "memory", compute
    else:
        seconds, bound_by, other = compute, "compute", memory

    # inf rather than ZeroDivisionError. A batch of 0 makes the compute side
    # vanish while the weights are still read, and "infinitely memory-bound" is
    # the honest reading of that -- an exception here would be a crash in a
    # sweep, at the one point of the sweep that says the weights are a fixed
    # cost paid before any work is done.
    ratio = seconds / other if other > 0 else math.inf
    return Roofline(seconds, bound_by, ratio)


def tpot_floor(
        model: Model, accel: Accelerator,
        batch_size: int, context_len: int) -> Roofline:
    """Maximum Memory vs. Compute over one decode step, 
    divided by its own coefficient.
    """
    memory = decode_step_bytes(model, batch_size, context_len) / \
                (accel.peak_bandwidth * accel.achieved_bandwidth)
    compute = FLOPS_PER_MAC * model.params_non_embedding * batch_size / \
                (accel.peak_flops * accel.mfu)
    return roofline(memory, compute)


def prefill_bytes(model: Model, prompt_tokens: int) -> float:
    """Bytes moved while prefilling one prompt: weights once, KV written once.

    The KV write is the term docs/SLO.md section 4 originally omitted. It is
    small against the weights at 2 000 tokens (0.29 GB against 16.4) and not
    small at reasoning lengths (4.72 GB at 32 000), and it never flips the
    verdict on these cards -- but a byte moved is a byte moved, and the point of
    having the code is that it does not quietly agree with the document.

    Not modelled: attention re-reading the KV it has already written as the
    prompt is consumed. That is a within-phase quadratic term, second order at
    these lengths, and the first measured TTFT is what should decide whether it
    needs to be here.
    """
    return model.weights_bytes + model.kv_bytes_per_token * prompt_tokens


def ttft_floor(
        model: Model, accel: Accelerator, prompt_tokens: int) -> Roofline:
    """The same roofline as decode, with the prompt length as B_tokens.

    Prefill computes every prompt token at once, so the compute side scales with
    prompt_tokens where decode's scales with batch_size -- one variable
    distinguishes the two phases, and the roofline inverts as a result. Which
    side won is reported rather than assumed, even though compute wins by 10x
    here: an accelerator with a weaker matrix engine would flip it, which is the
    arithmetic that ruled out the RTX 4090 (SLO.md section 4).
    """
    memory = prefill_bytes(model, prompt_tokens) / \
                (accel.peak_bandwidth * accel.achieved_bandwidth)
    compute = FLOPS_PER_MAC * model.params_non_embedding * prompt_tokens / \
                (accel.peak_flops * accel.mfu)
    return roofline(memory, compute)


def max_num_seqs_from_slo(
        model: Model, accel: Accelerator,
        context_len: int, tpot_target: float) -> int:
    """Largest batch whose TPOT floor still fits the latency budget.

    Latency only. Whether that many sequences' KV actually fits is
    concurrency_ceiling, and the value an operator ships is max_num_seqs, the
    min() of the two.

    Returns 0 when no batch meets the target -- the weights read alone exceeds
    the budget, which is a statement about the card and not about the batch.
    """
    if context_len <= 0:
        raise ValueError(
            "context_len must be positive: with no KV to read, the memory side "
            "does not bound the batch at all and the inversion is undefined"
        )

    byte_budget = tpot_target * accel.peak_bandwidth * accel.achieved_bandwidth
    kv_per_seq = model.kv_bytes_per_token * context_len

    # by_bandwidth, not by_memory: this is the memory *bus* inside a time budget,
    # and the module already uses "memory" for the capacity limit in
    # concurrency_ceiling. Two limits, both from memory, and the names have to
    # keep them apart -- the same defect as kv_dtype_bytes standing in for
    # FLOPS_PER_MAC, where both happened to equal 2.
    by_bandwidth = (byte_budget - model.weights_bytes) / kv_per_seq

    by_compute = (tpot_target * accel.peak_flops * accel.mfu) / \
                    (FLOPS_PER_MAC * model.params_non_embedding)

    # floor, never round: the limit is 23.46 sequences and the 24th costs
    # 50.52 ms against a 50 ms target, so rounding up ships a breached SLO.
    # max(_, 0) because a target below the batch-1 floor leaves by_bandwidth
    # negative, and a negative max_num_seqs is worse than an exception: it is a
    # number that can travel as far as a config file.
    return max(math.floor(min(by_bandwidth, by_compute)), 0)


def seats_under_prefill_interference(
        model: Model, accel: Accelerator,
        context_len: int, tpot_target: float,
        interference_slope: float, interference_intercept: float,
        hit_rate: float = 0.0) -> float:
    """Seats an operator can promise once prefill lands inside decode steps.

    max_num_seqs_from_slo answers what the *hardware* permits: the decode step
    alone against the target. What a service can promise is lower, because every
    arriving request injects prefill chunks into the decode stream and stretches
    that step for every sequence in the batch. On the L40S the two answers are
    31 and 12 -- a factor of 2.6 that is entirely the scheduler
    (docs/benchmarks/l40s-baseline.md section 5).

    The interference is not derivable here: it depends on the engine, the chunk
    size and the arrival pattern. It is measured as TPOT minus median ITL and
    passed in as a line, slope and intercept in *seconds* per seat, valid only
    across the concurrency range it was fitted over. Both coefficients therefore
    belong to a run, like eff_mem and mfu, and callers name their source.

    hit_rate is the share of prompt tokens a prefix cache serves. It scales the
    interference and nothing else: caching removes prefill work, and leaves the
    bytes a decode step reads untouched (docs/SLO.md section 6).

    Returns a float, not a floor()ed int: the caller is usually comparing a
    prediction against a measured crossing that sits between two integers.
    """
    if not 0.0 <= hit_rate <= 1.0:
        raise ValueError("hit_rate is a share of prompt tokens, so 0 <= h <= 1")

    step_per_seat = (model.kv_bytes_per_token * context_len) / \
                    (accel.peak_bandwidth * accel.achieved_bandwidth)
    step_at_zero = model.weights_bytes / \
                    (accel.peak_bandwidth * accel.achieved_bandwidth)

    uncached = 1.0 - hit_rate
    # step(n) + uncached * (slope*n + intercept) = tpot_target, solved for n.
    denominator = step_per_seat + uncached * interference_slope
    if denominator <= 0:
        raise ValueError(
            "a non-positive slope means the served step does not grow with the "
            "batch, and the seat count is unbounded rather than large"
        )
    return (tpot_target - step_at_zero - uncached * interference_intercept) / denominator


def concurrency_ceiling(
        model: Model, accel: Accelerator,
        context_len: int, gpu_memory_utilization: float) -> int:
    """Sequences whose KV fits, at a fixed context length.

    Capacity only: it knows nothing about the latency budget, exactly as
    max_num_seqs_from_slo knows nothing about the memory. context_len here is
    the length *reserved* per sequence, so this is the steady-state seat count,
    not what fits while the sequences are still short.

    Returns 0 when less than one sequence fits -- a real answer (the card is too
    small for this context length), unlike the weights not fitting at all, which
    kv_cache_tokens raises on.
    """
    if context_len <= 0:
        raise ValueError(
            "context_len must be positive: at zero reserved context every "
            "sequence is free and the seat count is unbounded"
        )
    return math.floor(kv_cache_tokens(model, accel, gpu_memory_utilization) / context_len)


def max_num_seqs(
        model: Model, accel: Accelerator,
        context_len: int, tpot_target: float,
        gpu_memory_utilization: float) -> Concurrency:
    """The number an operator actually sets, and which constraint set it.

    Five arguments rather than a struct, deliberately: they come from three
    different places -- context_len is workload, tpot_target is a promise
    (SLO.md section 2), gpu_memory_utilization is a server knob -- and a struct
    that mixes the three would have to be filled from three sources by every
    caller.
    """
    by_latency = max_num_seqs_from_slo(model, accel, context_len, tpot_target)
    by_capacity = concurrency_ceiling(model, accel, context_len, gpu_memory_utilization)

    # A tie is reported as latency-bound: the SLO is the promise that was made,
    # and when both constraints land on the same number that is the one to quote.
    bound_by = "capacity" if by_capacity < by_latency else "latency"
    sequences = min(by_capacity, by_latency)

    # Computed from the shipped integers rather than from the unfloored limits,
    # because the gap an operator can act on is the gap between seats they can
    # actually fill. The cost is a wobble at small counts: MI300X at 32 000
    # context prints 1.06 where the continuous gap is the same 1.08 as at 4 000.
    #
    # inf rather than a ZeroDivisionError: nothing can be served at this
    # operating point, and how far apart the limits are is not a question with
    # an answer there.
    ratio = max(by_capacity, by_latency) / sequences if sequences > 0 else math.inf

    return Concurrency(sequences, bound_by, by_capacity, by_latency, ratio)


def aggregate_tokens_per_sec(
        model: Model, accel: Accelerator,
        batch_size: int, context_len: int) -> float:
    """Output tokens per second across all sequences, at a decode operating point.

    One decode step emits exactly one token per sequence, so the aggregate rate
    is batch_size / TPOT -- which is why batching multiplies throughput while
    dividing per-user speed. A floor divided by a batch is still a floor: this is
    the most tokens per second the card can emit, never a forecast.
    """
    return batch_size / tpot_floor(model, accel, batch_size, context_len).seconds


def cost_per_1m_tokens(
        aggregate_tokens_per_sec: float, hourly_rate: float) -> float:
    """SLO.md section 7, verbatim: rate divided by tokens delivered per hour.

    hourly_rate stays a parameter rather than a field on Accelerator, because it
    is the one input that comes from a contract rather than from physics -- the
    same card is two different cost lines on two providers, and on reserved
    capacity against on-demand.

    Takes the throughput as a number rather than deriving it, so the identical
    function prices a measured run and a predicted one. Which of the two a figure
    came from is the whole point of the section 9 table.
    """
    return hourly_rate / (aggregate_tokens_per_sec * 3600) * 1e6
