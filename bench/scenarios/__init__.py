"""Workload definitions: what gets sent, in what shape, at what arrival pattern.

Prompts and arrival rates, not predictions about them (bench/predictions.py)
and not timings (the harness's output). A Workload states a *target* h and
builds a shared prefix the engine can cache: vLLM caches KV in whole blocks
of BLOCK_SIZE, so the prefix is floored onto a block boundary and the nominal
h is recomputed from what survives, never from what was requested
(docs/GLOSSARY.md, nominal hit rate). Prompts are token IDs (bench/loadgen.py)
drawn clear of every served vocabulary's special tokens: a stray EOS mid-prompt
would end the prefill it was meant to measure.
"""

import random
from dataclasses import dataclass

from loadgen import Request

# vLLM's default block_size; a run that overrides it must override this too.
BLOCK_SIZE = 16

# Ordinary tokens in every served vocabulary; Qwen3's specials start at 151643.
TOKEN_ID_MIN = 1_000
TOKEN_ID_MAX = 100_000


@dataclass(frozen=True)
class Workload:
    """One benchmark level: the prompts, the arrival pattern, the target h.

    mode is "closed" or "poisson"; concurrency means something only for the
    first, request_rate only for the second. Two fields, not one `load`
    number: seats held open and arrivals per second are different quantities
    (docs/GLOSSARY.md, closed-loop load).
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
            # One token has no ITL, so no TPOT: such a level answers nothing.
            raise ValueError(f"{self.name}: output_tokens < 2 leaves no decode step")

    @property
    def prefix_tokens(self) -> int:
        """The shared prefix, floored onto a block boundary the engine can cache."""
        requested = int(self.prompt_tokens * self.hit_rate_target)
        return (requested // BLOCK_SIZE) * BLOCK_SIZE

    @property
    def nominal_hit_rate(self) -> float:
        """h the construction produces once every prefix is warm (see warmup)."""
        return self.prefix_tokens / self.prompt_tokens

    @property
    def unique_tokens(self) -> int:
        return self.prompt_tokens - self.prefix_tokens

    def build(self) -> list[Request]:
        """The level's prompts: shared prefixes plus per-request unique bodies.

        Deterministic in `seed`: a level re-sent against a changed server
        differs in nothing but the server.
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
        """One request per distinct prefix, sent before a level is measured.

        Skipping it drags h below nominal by num_prefixes / num_prompts; bodies
        come from a separate seed stream, or a measured prompt would get a full
        hit and lift h by (1 - h) / num_prompts. Negative indices keep warmup
        records apart from measured ones if both land in one file.
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
