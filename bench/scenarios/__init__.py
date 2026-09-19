"""Workload definitions: what gets sent, in what shape, at what arrival pattern.

A workload here is data plus the arithmetic that turns it into token IDs. It
holds no predictions -- those are bench/predictions.py -- and no timings, which
are the harness's output. The split is the one bench/predictions.py already
states: this directory is prompts and arrival rates, not predictions about them.

The whole reason this file exists rather than a `--prompt-len` flag is the
independent variable of run 3. `docs/SLO.md` section 10 asks for a seat count
"against a known cache hit rate", and a hit rate is only known if the prompts
are built to produce it. So a Workload states a *target* h, and the arithmetic
below turns it into a shared prefix of a length the engine can actually cache:

  - vLLM hashes KV in blocks of `block_size` tokens (16 by default) and caches
    only whole blocks, so a 1 200-token prefix at h = 0.8 of a 1 500-token
    prompt is cacheable to 1 200 exactly, while 1 205 would be cacheable to
    1 200 and quietly report a lower h than the flag asked for. The prefix is
    therefore floored onto a block boundary and the *nominal* h recomputed from
    what survives, never from what was requested.
  - The nominal h is what the measured h from `vllm:prefix_cache_hits` /
    `vllm:prefix_cache_queries` is scored against. They are two independent
    routes to the same quantity, and a run where they disagree has a defect in
    the workload, not in the engine.

Prompts are token IDs (see bench/loadgen.py). The ids are drawn from a range
that is safely inside every vocabulary this repository serves and far from the
special tokens at the top of Qwen3's: what a token *means* is irrelevant to a
prefill measurement, but a stray EOS in the middle of a prompt would not be.
"""

import random
from dataclasses import dataclass

from loadgen import Request

# vLLM's default block_size. A run that overrides it must override this too --
# hence a named constant rather than 16 written into the arithmetic below.
BLOCK_SIZE = 16

# Ordinary tokens in every tokenizer this project touches; Qwen3's specials live
# at 151643+ and its vocabulary is 151 936, so this range is both valid and dull.
TOKEN_ID_MIN = 1_000
TOKEN_ID_MAX = 100_000


@dataclass(frozen=True)
class Workload:
    """One benchmark level: the prompts, the arrival pattern, the target h.

    mode is "closed" or "poisson", and exactly one of concurrency / request_rate
    means anything for each. They are separate fields rather than one `load`
    number because they are not the same quantity in different units: one is a
    number of seats held open, the other requests per second arriving whether or
    not a seat is free -- and confusing the two is how a TTFT gets compared with
    a target it cannot be compared with (docs/GLOSSARY.md, closed loop).
    """

    name: str
    prompt_tokens: int
    output_tokens: int
    num_prompts: int
    mode: str = "closed"
    concurrency: int | None = None
    request_rate: float | None = None
    hit_rate_target: float = 0.0
    num_prefixes: int = 1
    seed: int = 20260829

    def __post_init__(self) -> None:
        if self.mode not in ("closed", "poisson"):
            raise ValueError(f"unknown mode {self.mode!r}: closed or poisson")
        if self.mode == "closed" and not self.concurrency:
            raise ValueError(f"{self.name}: closed-loop levels need a concurrency")
        if self.mode == "poisson" and not self.request_rate:
            raise ValueError(f"{self.name}: open-loop levels need a request_rate")
        if not 0.0 <= self.hit_rate_target < 1.0:
            raise ValueError(f"{self.name}: h is a share of the prompt, 0 <= h < 1")
        if self.num_prefixes > self.num_prompts:
            raise ValueError(f"{self.name}: more prefixes than requests to use them")
        if self.output_tokens < 2:
            # One token has no ITL and therefore no TPOT: a level of them cannot
            # answer any question this repository asks.
            raise ValueError(f"{self.name}: output_tokens < 2 leaves no decode step")

    @property
    def prefix_tokens(self) -> int:
        """The shared prefix, floored onto a block boundary the engine can cache."""
        requested = int(self.prompt_tokens * self.hit_rate_target)
        return (requested // BLOCK_SIZE) * BLOCK_SIZE

    @property
    def nominal_hit_rate(self) -> float:
        """h the construction produces, once the prefixes are warm.

        Warm is a precondition, not an assumption: the harness sends one request
        per distinct prefix before the level's clock and its counter window
        start, so the misses that seed the cache are outside the measurement.
        Without that warmup the first request of each prefix drags h down by
        num_prefixes / num_prompts, which at 60 requests and one prefix is 1.7%
        -- small, and exactly the kind of small bias that gets attributed to the
        engine later.
        """
        return self.prefix_tokens / self.prompt_tokens

    @property
    def unique_tokens(self) -> int:
        return self.prompt_tokens - self.prefix_tokens

    def build(self) -> list[Request]:
        """The level's prompts: shared prefixes plus per-request unique bodies.

        Deterministic in `seed`, so a level can be re-sent against a changed
        server configuration and differ in nothing but the configuration.
        """
        rng = random.Random(self.seed)
        prefixes = [
            tuple(rng.randint(TOKEN_ID_MIN, TOKEN_ID_MAX)
                  for _ in range(self.prefix_tokens))
            for _ in range(self.num_prefixes)
        ]

        requests: list[Request] = []
        for index in range(self.num_prompts):
            prefix = prefixes[index % self.num_prefixes]
            body = tuple(rng.randint(TOKEN_ID_MIN, TOKEN_ID_MAX)
                         for _ in range(self.unique_tokens))
            requests.append(Request(
                index=index,
                prompt_ids=prefix + body,
                max_tokens=self.output_tokens,
                prefix_tokens=len(prefix),
            ))
        return requests

    def warmup(self) -> list[Request]:
        """One request per distinct prefix, to seed the cache before measuring.

        The body is *not* any measured request's body: it is drawn from a
        separate seed stream, so the warmup caches the prefix and nothing else.
        Reusing a measured prompt here would give that one request a full hit and
        lift the level's h above its nominal value by (1 - h) / num_prompts --
        0.3% at 60 requests, which is smaller than the measurement and still a
        bias with a known sign, removed rather than modelled.

        Negative indices, so a warmup record can never be mistaken for a measured
        one if the two ever land in the same file.
        """
        rng = random.Random(self.seed + 1)
        prefixes = [req.prompt_ids[:self.prefix_tokens]
                    for req in self.build()[:self.num_prefixes]]
        return [
            Request(index=-1 - n,
                    prompt_ids=prefix + tuple(
                        rng.randint(TOKEN_ID_MIN, TOKEN_ID_MAX)
                        for _ in range(self.unique_tokens)),
                    max_tokens=2,          # enough to prove the server answered
                    prefix_tokens=len(prefix))
            for n, prefix in enumerate(prefixes)
        ]
