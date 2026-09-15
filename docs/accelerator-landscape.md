# Accelerator landscape — who competes with NVIDIA, and on which term

**As of 2026-08-23.** This file is a snapshot of a market that moves in weeks, and
it is written to decay visibly: every figure carries its date and its source, and
§8 says what to re-check before quoting any of it.

Why this file exists: [SLO.md](SLO.md) derives what *one* accelerator can do, and
[benchmarks/](benchmarks/) measures it. Neither answers the operator's next
question — *is this the right card at all*. That question is not a spec comparison.
It is the observation that decode and prefill are two different limits
([model-anatomy.md](model-anatomy.md) level 1), that a GPU sells both in one
bundle, and that every credible challenger is refusing to pay for one of the two.

**What this file does not hold.** No formula is derived here — the roofline,
`bytes_moved` and the floors live in [SLO.md](SLO.md) §4, the vocabulary in
[GLOSSARY.md](GLOSSARY.md). Nothing here is a measurement made by this repo; the
only measured card in this repo is the L40S, and its numbers are in
[benchmarks/l40s-baseline.md](benchmarks/l40s-baseline.md).

---

## 1. The frame: one equation, four ways to attack it

Decode time per token is bounded by bytes moved over achieved bandwidth
([SLO.md](SLO.md) §4):

```
bytes_moved  = weights + batch × context × kv_per_token
TPOT_floor   = bytes_moved / achieved_bandwidth
```

Everything a vendor can sell is one of the three quantities in that expression, or
the fabric that lets several accelerators share one of them. Hence four attack
surfaces, and every company below sits on exactly one:

| | The move | Who |
|---|---|---|
| **A. Raise the denominator** | drop HBM, hold weights in SRAM — bandwidth up ~4 orders of magnitude | Cerebras, Groq (until Dec 2025) |
| **B. Lower the cost of the numerator** | buy capacity on cheap memory, accept low bandwidth | Qualcomm; SambaNova's DDR tier |
| **C. Change the buyer, not the chip** | the seller and the customer are the same company, so the comparison is TCO, not specs | Google, AWS |
| **D. Sell the same shape for less** | same HBM-plus-matmul bundle, more memory or better perf/W | AMD, FuriosaAI, Etched |

**The single most important fact of 2026 is that NVIDIA split its own card along
this seam.** Rubin CPX is a prefill-only accelerator on GDDR7 with no NVLink — HBM
removed because prefill is compute-bound and does not need it. And in December
2025 NVIDIA licensed Groq's LPU architecture (~$20 bn, non-exclusive) and hired its
leadership; the resulting LP30 ships in Q3 2026 as a **decode co-processor** inside
the Vera Rubin platform. A monolithic HBM GPU is the wrong shape for both phases,
and the incumbent said so with money. That simultaneously validates the
challengers' physics and removes their differentiation.

---

## 2. The one ratio that makes the table readable

Capacity and bandwidth are quoted separately by every vendor, and neither alone
predicts decode. Their **ratio** does:

```
sweep_rate  = memory_bandwidth / memory_capacity        [1/s]
sweep_time  = 1 / sweep_rate                            [s]
```

`sweep_time` is the time to read the accelerator's entire memory once — i.e. the
decode step time if `bytes_moved` exactly filled the device. It is a **derived**
quantity, not a measurement, and it is deliberately crude: it ignores `eff_mem`,
assumes the memory is full of decode-relevant bytes, and says nothing about
prefill, scale-up or price. What it is good for is that it collapses two vendor
numbers into one, and it is **scale-invariant** — a rack of 576 identical chips has
the same ratio as one chip, so it compares memory *technologies* rather than boxes.

All figures dense, from vendor tables ([GLOSSARY.md](GLOSSARY.md), *FLOPS, dense vs
sparse*). Sorted by `sweep_time`.

| Accelerator | Memory | Capacity | Bandwidth | `sweep_time` |
|---|---|---:|---:|---:|
| Cerebras WSE-3 Turbo | SRAM (on-wafer) | 44 GB | 43.2 PB/s | 0.0010 ms |
| Cerebras WSE-3 | SRAM (on-wafer) | 44 GB | 21 PB/s | 0.0021 ms |
| Groq LPU (original) | SRAM | 0.23 GB | 80 TB/s | 0.0029 ms |
| NVIDIA LP30 LPU | SRAM | 0.512 GB | 150 TB/s | 0.0034 ms |
| NVIDIA VR200 (Rubin) | HBM4 | 288 GB | ~22 TB/s | 13.1 ms |
| AMD MI455X | HBM4 | 432 GB | 23.3 TB/s | 18.5 ms |
| NVIDIA H100 SXM | HBM3 | 80 GB | 3.35 TB/s | 23.9 ms |
| Google TPU v7 (Ironwood) | HBM3E | 192 GB | 7.38 TB/s | 26.0 ms |
| AWS Trainium3 | HBM3E | 144 GB | 4.9 TB/s | 29.4 ms |
| Etched Sohu *(claimed, 2024)* | HBM3E | 144 GB | ~4.8 TB/s | 30.0 ms |
| FuriosaAI RNGD | HBM3 | 48 GB | 1.5 TB/s | 32.0 ms |
| NVIDIA GB300 / AMD MI355X | HBM3E | 288 GB | 8.0 TB/s | 36.0 ms |
| NVIDIA L40S *(this repo's card)* | GDDR6 | 48 GB | 864 GB/s | 55.6 ms |
| NVIDIA Rubin CPX | GDDR7 | 128 GB | 2.0 TB/s | 64.0 ms |
| Qualcomm Cloud AI 100 Ultra | LPDDR4X | 128 GB | 548 GB/s | 233.6 ms |

Three things fall out of the column, and they are the whole argument:

1. **The HBM parts are all within ~3× of each other**, from H100 to Rubin. Three
   generations and four vendors, and the ratio barely moves — because capacity and
   bandwidth are bought from the same three suppliers and scale together. Nobody
   wins decode by choosing a different HBM part.
2. **SRAM is ~4 orders of magnitude away, not 3×.** This is the only genuine
   discontinuity in the table, and it is why Cerebras can make `batch = 1`
   economical — the regime a GPU cannot serve, because a GPU needs batching to
   raise arithmetic intensity ([SLO.md](SLO.md) §5).
3. **LPDDR is 4× worse than this repo's L40S**, which is itself the slowest HBM-less
   card anyone deploys. Qualcomm is not competing on decode latency and is not
   pretending to.

The L40S row is worth keeping in view: everything measured in
[benchmarks/l40s-baseline.md](benchmarks/l40s-baseline.md) sits near the bottom of
this table by construction, which is a fact about the rental budget, not about the
physics.

---

## 3. What SRAM actually costs

`sweep_time` flatters the SRAM parts, because it is a ratio and hides the
numerator. Capacity is where the bill arrives.

The Groq LPU held **230 MB per chip and no HBM at all**. Serving Llama-2 70B at
BF16 needs ~140 GB of weights, so `140e9 / 230e6 ≈ 609` chips — the published
figure is **576**, consistent once the sharding overhead is accounted for.
Cerebras is the same arithmetic one order kinder: 44 GB per wafer means a 70B model
at BF16 needs ~4 wafers *just to hold the weights*, and WSE-3 Turbo doubled
bandwidth while leaving capacity at 44 GB.

So the fleet-level question is never bandwidth. It is **bandwidth per dollar**, and
SRAM is roughly two orders of magnitude more expensive per byte than HBM. That
inverts the picture: the architecture that wins any single-stream latency
comparison needs an enormous, highly-utilised deployment of one narrow model
catalogue before the capex per token closes. It is also why long context is the
SRAM architectures' blind spot — the `batch × context × kv_per_token` term grows
into memory that costs 100× more per byte than the memory the term was designed
around.

Groq is the finished experiment: best-in-industry denominator, and the business
did not survive the numerator.

---

## 4. The vendors

Format: **niche → edge → what it pays**. Vendor claims are marked as such.

### C — captive workload (structurally the strongest position)

**Google — TPU v7 "Ironwood".** 192 GB HBM3E, 7.38 TB/s, 4 614 TFLOPS FP8 dense,
pods to 9 216 chips on a 3D torus with optical switching; GA April 2026. The edge
is not the spec sheet — TPU does not beat Rubin on the ratio above — it is that
Google does not pay NVIDIA's gross margin. Claim: 44% lower TCO than GB200
*(vendor)*. Bernstein projects TPU at ~70% of the whole custom-ASIC market by 2027
*(analyst)*. Pays: JAX is the first-class path and PyTorch/XLA still trails;
vLLM-TPU had open gaps on XL-MoE and MLA at the unified-backend launch; **no public
list price for Ironwood**, so no outsider can verify the TCO claim; hardware sales
outside GCP began only in 2026 and only to a "select group".

**AWS — Trainium / Inferentia.** Inferentia is effectively frozen at Inf2 (32 GB
per chip, 2023 silicon) and all new inference work is steered to Trainium.
Trainium3, GA December 2025: 144 GB HBM3E, 4.9 TB/s, 2.52 PFLOPS FP8 dense,
UltraServers to 144 chips. Claim: 30–40% better price-performance than the
H200-class EC2 instances *(vendor, for Trn2)*. The real niche is one anchor tenant —
Project Rainier, >1 M Trainium2 chips for Anthropic. Pays: the Neuron SDK trails
(logical-NeuronCore support landed mid-2026), first-generation scale-up over PCIe
switches with cross-rack bandwidth under 10% of in-rack, and none of it exists
outside AWS — zero portability.

> The lesson of tier C: there is no technical moat. The moat is that the invoice is
> written to yourself.

### D — the same shape, cheaper

**AMD — Instinct.** The only vendor attacking NVIDIA in its own form factor.
MI355X: 288 GB HBM3E, 8.0 TB/s, 5.0 PFLOPS FP8 dense. MI455X (announced July 2026):
432 GB HBM4, 23.3 TB/s, 20.1 PFLOPS FP8 dense, in the 72-GPU Helios rack — on paper
ahead of Rubin on both capacity and bandwidth. Roughly 14 GW of publicly committed
deployments (OpenAI 6 GW, Meta 6 GW, Anthropic 2 GW). The weakness is no longer
"ROCm" as a slogan: SemiAnalysis upgraded AMD's odds in July 2026, and vLLM/SGLang
run on ROCm. It is **composability** — individual optimisations land, but
disaggregated prefill/decode *plus* wide expert parallelism *plus* FP4 together is
still behind. Pays: Helios is AMD's *first* rack-scale generation (before it, the
scale-up domain was 8 GPUs against NVL72's 72); MI455X was absent from the ROCm
7.14 support list at time of writing; and 432 GB of HBM4 per GPU is an aggressive
bet in a year when all three memory suppliers are sold out.

**FuriosaAI — RNGD.** 48 GB HBM3, 1.5 TB/s, 512 TFLOPS FP8, **180 W, air-cooled**.
The niche is stated honestly and is real: five servers fit a standard 15 kW
air-cooled rack, so the product is *not having to rebuild the datacenter*. LG AI
Research reports 2.25× perf/W and 3.75× tokens per rack against comparable GPUs in
production *(customer-run, vendor-published)*. In mass production since January
2026; turned down an ~$800 M Meta offer in 2025. Pays: 1.5 TB/s is H100-class
bandwidth in 2026, so every latency-critical comparison is lost up front; the
**scale-up domain stops at 8 accelerators** with no NVLink-class fabric; volumes are
~4 000 chips shipped against a 20 000 target *(vendor)*; customer concentration on
LG and Samsung.

**Etched — Sohu.** The thesis was the transformer burned into silicon,
programmability discarded. A0 silicon back from TSMC N4P in H1 2026, first rack
delivered July 2026 to a single customer (Jane Street — who also led the following
round). Two observations matter more than the specs. First, **there is not one
independent benchmark**: the widely-quoted throughput figures date from the 2024
launch and have not been re-affirmed against shipped silicon. Second, the pitch has
moved from "hardwired transformer" to LVI (sub-half-voltage compute blocks) and CSM
(a cluster-wide shared HBM/SRAM pool aimed at decode), and the company now claims
MoE *and* Mamba support — if it runs Mamba it is less of an ASIC than the thesis
required, and the efficiency edge over a GPU narrows accordingly. The founder's own
risk statement stands: if transformers go away, the company dies.

### A — SRAM instead of HBM

**Cerebras — WSE-3 / CS-4.** 900 000 cores on one wafer, 44 GB of on-wafer SRAM,
21 PB/s (43.2 PB/s on WSE-3 Turbo). Publicly verified throughput records
(gpt-oss-120B at ~3 000 tok/s, confirmed by Artificial Analysis) and the only
architecture in this file for which single-stream decode is economically sensible.
IPO'd on Nasdaq 14 May 2026 — the largest semiconductor IPO on record — and traded
roughly half off its debut peak by August. Pays: everything in §3, plus deployment
velocity (wafer-scale needs purpose-built power and cooling, and Q2 2026 gross
margin took a hit from renting compute back), plus extreme customer concentration —
86% of 2025 revenue from two Abu Dhabi entities, replaced in 2026 by dependence on
OpenAI.

**Groq — no longer a chip company.** 230 MB SRAM, 80 TB/s, zero HBM, and a fully
deterministic compile-time schedule with no caches or runtime arbitration — which
removes tail-latency variance by construction and turns multi-chip scaling into a
static scheduling problem. NVIDIA licensed the architecture and hired the team in
December 2025; Groq continues as an inference cloud on other people's hardware, at
$3.5 bn against $6.9 bn a year earlier. Read it as the market's verdict on §3, and
note the two structural weaknesses that verdict encodes: chips-per-model capex, and
a KV cache that has nowhere to live once SRAM is full of weights.

### B — capacity instead of bandwidth

**Qualcomm — Cloud AI 100 Ultra / AI200 / AI250.** Ultra ships today: 128 GB
LPDDR4X at 548 GB/s. AI200 (availability 2H 2026) carries **768 GB of LPDDR per
card**. The bet is explicit and not unreasonable — holding a very large MoE, or a
dozen models, resident without sharding is a real GPU pain point, and capacity per
watt is where LPDDR wins. Pays: the bottom row of the table. This is hardware for
batch-heavy, latency-tolerant serving and explicitly not for interactive decode.
AI250's ">10× effective bandwidth" via near-memory computing is workload-dependent
by construction — near-memory pays off on high data reuse, and decode is streaming
with almost none. Track record is the other problem: Centriq was abandoned, Cloud
AI 100 has existed since 2020, and its largest cited win six years later is 1 024
cards in Saudi Arabia.

**SambaNova — RDU.** SN40L, published at ISSCC and Hot Chips, so this is
peer-reviewed silicon: three memory tiers per socket — 520 MB SRAM / 64 GB HBM /
~1.5 TB DDR. The DDR tier is the genuinely clever part; it holds MoE expert
checkpoints and alternate model weights on-socket, so a node switches models or
reaches a cold expert without going to the host. That targets multi-tenant serving
of many models, which is a real operator problem no GPU vendor solves cheaply.
Survived a training→inference pivot with layoffs (April 2025) and an abandoned
Intel acquisition, then raised at $11 bn in July 2026. Pays: the smallest ecosystem
here, almost no independent measurement, headline claims ("5× faster", "3× lower
TCO") published **without a named comparison part**, and SN50 not yet shipped.

---

## 5. Where NVIDIA's moat actually is now

Not CUDA, at the inference layer specifically. vLLM and SGLang have become the
serving interface, they abstract the model API away from the kernel language, and
NVIDIA's own response was to make itself the best-optimised backend *under* them —
Dynamo orchestrates vLLM and SGLang as first-class backends, and TensorRT-LLM
optimisations are upstreamed into them.

What replaced it is a **systems moat**, and it is harder to copy:

- **The scale-up domain.** NVL72 puts 72 GPUs in one NVLink domain at 1.8 TB/s per
  GPU (3.6 TB/s on Rubin). This is not a vanity number. A model routing each token
  to 8 of 256 experts needs on the order of 64 GPUs in one domain just to hold the
  routed experts during decode; spill that across nodes and the all-to-all falls
  back to Ethernet at a fraction of the bandwidth. Wide expert parallelism also
  frees HBM per GPU for KV cache, which raises the batch, which improves decode
  economics — the chain runs straight back through [SLO.md](SLO.md) §5.
- **Composed optimisation.** Disaggregated prefill/decode, wide EP, FP4 and
  multi-token prediction each help; the moat is that they work *together* on one
  platform first. Competitors reach parity on individual pieces and lose on the
  composition.

NVIDIA's named vulnerabilities are, in order of how often credible analysts raise
them: memory as a rising share of rack BOM against a three-supplier oligopoly;
power per rack (GB300 NVL72 up to 142 kW, Vera Rubin higher) making facilities the
binding constraint; price/performance on pure decode, where an expensive
HBM+NVLink+FLOPS bundle is sold to a workload that only needs one of the three; and
a growth mix shifting toward inference, which is exactly where buyers are most
price-sensitive and least locked in.

---

## 6. What this means for the numbers in this repo

- **A calibrated roofline is a statement about a card; an SLO is a statement about
  a service.** That was run 1's finding at the scale of one L40S
  ([benchmarks/l40s-baseline.md](benchmarks/l40s-baseline.md)), and it is the same
  finding at the scale of the market: Groq had the best denominator in the industry
  and lost at the level of the fleet.
- **`sweep_time` is not a purchasing criterion.** Nothing in §2 accounts for
  `eff_mem`, scheduling, the scale-up domain, or price. A vendor comparison that
  stops at a ratio makes the same error as quoting `max_num_seqs` from a startup
  log without dividing.
- **The dense/sparse discipline is not pedantry here.** Half the figures in this
  market are published as the sparsity row, and the two most-quoted numbers of 2026
  (Rubin's "50 PF" and AMD's headline FP16) are both sparse. Every figure above is
  dense.

---

## 7. Sources

Primary and named-analyst only; aggregator sites were excluded.

- NVIDIA: [Blackwell Ultra architecture](https://developer.nvidia.com/blog/inside-nvidia-blackwell-ultra-the-chip-powering-the-ai-factory-era/) ·
  [Vera Rubin platform](https://nvidianews.nvidia.com/news/nvidia-vera-rubin-platform) ·
  [GB200 NVL72 + Dynamo for MoE inference](https://developer.nvidia.com/blog/how-nvidia-gb200-nvl72-and-nvidia-dynamo-boost-inference-performance-for-moe-models) ·
  [LPX / LP30](https://www.nvidia.com/en-us/data-center/lpx/) ·
  [SemiAnalysis — Rubin CPX](https://newsletter.semianalysis.com/p/another-giant-leap-the-rubin-cpx-specialized-accelerator-rack)
- AMD: [MI455X datasheet](https://www.amd.com/content/dam/amd/en/documents/products/accelerators/instinct/amd-instinct-mi455x_brochure.pdf) ·
  [MI355X](https://www.amd.com/en/products/accelerators/instinct/mi350/mi355x.html) ·
  [Helios](https://newsroom.amd.com/news/aai-2026-helios-update/) ·
  [SemiAnalysis — Can AMD Break the CUDA Moat?](https://newsletter.semianalysis.com/p/can-amd-break-the-cuda-moat-amd-advancing)
- Google: [TPU7x documentation](https://docs.cloud.google.com/tpu/docs/tpu7x) ·
  [Ironwood codesigned stack](https://cloud.google.com/blog/products/compute/inside-the-ironwood-tpu-codesigned-ai-stack)
- AWS: [Trn3 UltraServers GA](https://aws.amazon.com/about-aws/whats-new/2025/12/amazon-ec2-trn3-ultraservers/) ·
  [Inf2 instances](https://aws.amazon.com/ec2/instance-types/inf2/) ·
  [Project Rainier](https://www.aboutamazon.com/news/aws/aws-project-rainier-ai-trainium-chips-compute-cluster)
- Cerebras: [Q2 2026 results](https://investors.cerebras.ai/news-releases/news-release-details/cerebras-systems-fast-inference-cloud-business-nearly-quadruples) ·
  [WSE-3 Turbo and CS-4](https://www.servethehome.com/cerebras-intros-faster-wse-3-turbo-processor-and-first-rack-scale-cs-4-system/) ·
  [Nasdaq debut](https://www.cnbc.com/2026/05/14/cerebras-cbrs-stock-trade-nasdaq-ipo.html)
- Groq: [Licensing agreement with NVIDIA](https://groq.com/newsroom/groq-and-nvidia-enter-non-exclusive-inference-technology-licensing-agreement-to-accelerate-ai-inference-at-global-scale) ·
  [CNBC on the ~$20 bn deal](https://www.cnbc.com/2025/12/24/nvidia-buying-ai-chip-startup-groq-for-about-20-billion-biggest-deal.html) ·
  [The Groq LPU explained](https://groq.com/blog/the-groq-lpu-explained)
- SambaNova: [SN40L at Hot Chips 2024 (PDF)](https://hc2024.hotchips.org/assets/program/conference/day1/48_HC2024.Sambanova.Prabhakar.final-withoutvideo.pdf) ·
  [Series F at $11 bn](https://techcrunch.com/2026/07/08/sambanova-draws-1b-at-11b-valuation-in-series-f-first-close/)
- Etched: [Series D, first Jane Street delivery](https://www.globenewswire.com/news-release/2026/08/18/3347095/0/en/etched-raises-700m-at-a-21b-valuation-and-completes-first-customer-delivery-to-jane-street.html)
- FuriosaAI: [RNGD mass production](https://furiosa.ai/blog/rngd-enters-mass-production-the-high-performance-ai-accelerator-for-any-data-center) ·
  [LG AI Research 2.25× perf/W](https://furiosa.ai/blog/lg-ai-research-taps-furiosaai-to-achieve-2-25x-better-llm-inference-in-production-vs-gpus) ·
  [RNGD developer docs](https://developer.furiosa.ai/latest/en/overview/rngd.html)
- Qualcomm: [Cloud AI 100 architecture](https://quic.github.io/cloud-ai-sdk-pages/latest/Getting-Started/Architecture/) ·
  [AI200 / AI250 launch](https://www.datacenterdynamics.com/en/news/qualcomm-launches-ai200-and-ai250-chip-offering-targeting-inferencing-workloads-at-rack-scale/)
- Market structure: [TrendForce — 2026 AI server mix](https://www.trendforce.com/presscenter/news/20260120-12887.html)

---

## 8. Decay

This file is a snapshot, and the parts of it rot at different rates.

| Rots in | What | Re-check |
|---|---|---|
| weeks | funding rounds, valuations, who acquired whom | before quoting any company's status |
| months | shipping status, availability dates, software support matrices | before claiming a part is deployable |
| ~a year | published specs of shipped silicon, the `sweep_time` table | against the vendor table, dense row |
| slowly | §1's frame and §5's argument | these are structural and survive a product cycle |

Two claims here are load-bearing and unverified by anyone independent, and should
be labelled as vendor claims whenever repeated: Etched's throughput figures (no
third-party benchmark exists on shipped silicon) and Qualcomm's AI250 "effective
bandwidth" multiplier.
