# `ModelWarmup` — an architecture note, and the case against writing it

This directory holds no controller, and this note is the reason. It answers two
questions in order: **when a warm model cache is a controller's job at all**, and
**what the controller looks like if the answer is yes**. The second question is
the interesting one to design; the first is the one an interviewer asks, and the
one that decides whether any code belongs here.

The pull comes from `docs/architecture.md` §4: of the terms in the autoscaling
control loop, the model's start-up is the only one that can be *removed* rather
than tuned. What that removal is actually worth was measured on the L40S and is
in `docs/benchmarks/l40s-run3.md` §6 — cold start **69.16 s**, the same pod with
both caches warm **16.47 s**, and a floor of **~17 s** that no cache reaches.
Warming does not remove a cold start. It removes about three quarters of one.

---

## 1. Three caches, and the one that needs a GPU to build

The decomposition in `docs/benchmarks/l40s-run3.md` §6 splits start-up by time.
The design question needs it split a second way — by **what it costs to
produce** — and the two splits do not agree, which is where most of the design
lives.

| What is warmed | Size | Buys | Needs a GPU to produce? | Valid for |
|---|---|---|---|---|
| Model weights (HF cache) | 16.4 GB | 16.5 s at 7.9 Gbit/s | **No** | a model revision |
| `torch.compile` AOT artefacts | 6.0 MiB | 34.8 s | **Yes** — target architecture | one engine configuration on one GPU architecture |
| Profile, KV pool, CUDA graphs | — | — | Yes, every start | nothing; per process |

The third row cannot be pre-built at all: `docs/GLOSSARY.md` (`VLLM_CACHE_ROOT`)
records that CUDA graphs are captured into GPU memory at every start and have no
on-disk form. That is the ~14 s the floor is made of.

The middle row is the one that reorders the design. It is the largest removable
term, it is six megabytes, and — this is an **assumption, not a measurement** —
producing it requires a card of the target architecture, because Inductor
benchmarks candidate kernels on the device it is compiling for. Nothing in this
repository has tried to build that cache off-device; the test is to run one
start-up on a CPU-only host with `VLLM_CACHE_ROOT` on a volume and see whether
anything lands in it.

If that assumption holds, it settles the shape of the whole problem:

- **Warming weights is cheap and parallel.** Any node can pull 16.4 GB without a
  card. A DaemonSet or a shared volume does it.
- **Warming compilation on each node wastes the resource it is trying to
  free.** A warm-up Pod that compiles must hold a GPU for ~50 s to save ~35 s on
  a later start on that same GPU. Per node, that is a loss.
- **Therefore compilation is built once and distributed, not warmed per node.**
  One card in CI produces 6 MiB; every node receives it as an image layer or an
  artefact on a volume. The GPU is spent once per (model, engine config, GPU
  architecture), not once per node.

Which term to attack first is not a matter of taste either: the two trade places
at ~3.8 Gbit/s of download bandwidth (`docs/benchmarks/l40s-run3.md` §6). Below
that, the weights dominate and the 6 MiB is a rounding error. **Read the
cluster's network before choosing.**

---

## 2. When this is a controller

The test that decides it: **is there state that drifts, or a decision that must
be re-made without a human?** Rendering one object into several is not that —
that is a template. Four mechanisms, in increasing order of moving parts:

| Mechanism | Removes | Cost | Needs a controller |
|---|---|---|---|
| Bake weights + compile cache into the image | both cached terms | ~17 GB image; rebuild per model or per flag change; first pull per node is not free | No |
| PVC (RWX) + `initContainer` that fills it when empty | both cached terms | one shared volume; the write path needs a GPU once for the compile cache | No |
| DaemonSet pre-puller into `hostPath` | weights, per node | one Pod per node; useless for the compile cache unless every node has a card to spare | No |
| `ModelWarmup` controller | both, kept correct as the cluster changes | an operator to run, RBAC, a CRD to version | Only under the conditions below |

A controller earns its place when the warm set changes without anyone asking:

- **Nodes come and go** — cluster autoscaler, spot reclamation, drain and
  replace. A node that joins after the rollout is cold and nothing notices.
- **The cache key changes ahead of a rollout.** Change the engine configuration
  and the compile artefacts for the new configuration do not exist yet; the
  first Pod of the new version pays the full 35 s, during a canary, when the
  comparison against the old version is exactly what is being measured. The
  procedure that will own this is `docs/runbook.md`, a stub until weeks 7–8.
  Pre-building the artefact for the *next* configuration
  before traffic moves is a decision made without a human, on a schedule set by
  the rollout — that is a reconcile loop.
- **Several models or configurations compete for the same nodes**, and which
  ones should be warm is a function of routing, not of a manifest.

**On `kind`, with a fixed node set and one model, none of these hold.** The
honest recommendation for this repository is mechanism 2 — an `initContainer`
filling a volume — and no controller. The precedent is worth naming because it
was paid for: llm-d shipped a `ModelService` operator that provisioned prefill
and decode Deployments, an InferencePool and an endpoint picker from one custom
resource; the proposal to replace it with a Helm chart was accepted on 10 June
2025 and the operator deprecated. The proportions say why: the two files that
render and merge the child objects are 1485 lines, `Reconcile` itself is about
60, and what remained of genuine reconciliation was status mirroring and one
carve-out over field ownership. What they gave up is worth naming too, or it is
not a trade-off: aggregated status in one object, and drift repair when someone
deletes a child. Source read for this note: `llm-d/llm-d-model-service` at
`403e983`, `controller-runtime` v0.20.4.

---

## 3. If it is a controller: the design

Scope, deliberately narrow: **one `ModelWarmup` object describes one warm
artefact set for one (model revision, engine configuration, GPU architecture),
and its job is to make that artefact exist and be reachable before it is
needed.** It does not create Deployments, does not route traffic, and does not
scale anything.

### `spec`

- `modelRef` — repository and **revision**, not a floating tag; a warm cache for
  an unpinned revision is a cache for an unknown model.
- `engineConfig` — the flags that key the compile artefacts. Empirically
  `enable_prefix_caching` is *not* one of them
  (`docs/benchmarks/l40s-run3.md` §6); which flags are is the open question in §5.
- `target` — where the artefact must land: a volume claim, an image reference, or
  a node selector plus a count.
- `builder` — the pod template used to produce the compile artefact, including
  its GPU resource request. This is the only part that needs a card.
- `retain` — how long an artefact for a superseded configuration stays; a
  rollback needs the previous one to still exist.

### `status`

- `observedGeneration` — without it the status is an unfalsifiable claim: a
  reader cannot tell whether `Ready` refers to the configuration they just
  applied or the one before it. This is not optional for anything a rollout
  automates against.
- `conditions` — `Progressing`, `Ready`, `Degraded`, written with
  `meta.SetStatusCondition` so that `LastTransitionTime` marks a transition
  rather than the moment of the last reconcile. See failure mode 1.
- `warmNodes` / `artifactRef` — what actually exists, read from the cluster, not
  remembered.

### The loop

Read the object; list what exists (the artefact, the volume, the builder Job);
create what is missing; write status. Five decisions, each of which is a lesson
from reading a real controller rather than a preference:

1. **`RequeueAfter`, not a returned error, while waiting.** A builder Job that is
   still running is not a failure. Returning an error requeues with exponential
   backoff — 5 ms doubling to a 1000 s ceiling, so ~17 minutes between attempts
   after about eighteen of them — which is the wrong pacing for a job that takes
   a minute, and it hides real errors in the same metric. `RequeueAfter` also
   resets the failure counter; a returned error does not.
2. **A terminal error for anything that will not fix itself.** A model revision
   that does not exist, a builder image that will not pull, a GPU architecture
   with no node to build on: `reconcile.TerminalError`, plus a `Degraded`
   condition that says which. Retrying forever is not resilience, it is noise.
3. **A narrow watch set.** The manager caches every object of every watched type
   in the cluster; without a label selector on the cache, an operator's memory
   scales with the cluster's object count rather than with its own resources.
   Watch Jobs and Pods carrying this controller's label, nothing else.
4. **Server-Side Apply for anything with another writer.** Field ownership is
   recorded in `metadata.managedFields` and fields dropped from the desired state
   are actually removed — neither is true of a read-merge-write with override,
   which can add and change but never delete. See failure mode 2.
5. **A finalizer, unlike most controllers of this shape.** `ModelWarmup`'s state
   is outside the cluster's object graph: bytes on a node's disk, on a volume, in
   a registry. `ownerReferences` and garbage collection do not reach it, so
   deleting the object without a finalizer leaks the artefact. This is the one
   place where copying `ModelService`'s "marked for deletion, return" would be
   wrong.

---

## 4. Failure modes, each with the signal that shows it

1. **Status churn.** A condition whose value depends on the clock — a
   `LastTransitionTime: metav1.Now()` recomputed every pass — makes every
   reconcile write status, and every status write is an update event that
   triggers the next reconcile. The loop is self-sustaining and carries **no
   backoff**, because each pass returns success. Signal: status-subresource
   writes rising with no spec changes, and a reconcile rate with a zero error
   rate. Guards: `meta.SetStatusCondition`, and a generation predicate on the
   controller's own type.
2. **Two writers of one field.** If a controller renders a Deployment whose
   `spec.replicas` is also written by the HPA that KEDA drives
   (`deploy/keda/README.md`), the two do not conflict — they oscillate, each
   write waking the other. Signal: Pods created and deleted with no scaling
   event and no errors anywhere. Guards: never write the field (Server-Side Apply
   with a field manager that does not own it), or write it once at creation and
   never again — the carve-out `ModelService` calls `decoupleScaling`. The cost
   of the oscillation is not the API traffic; it is that every restarted replica
   pays a cold start.
3. **Warming what is no longer wanted.** A builder Job holds a GPU to produce a
   cache for a configuration that has since been rolled back, or warms a node
   for a burst that ended. The resource being consumed is the resource being
   optimised. Signal: builder Pods holding a GPU while queue depth is zero.
   Guard: the builder is bounded by a deadline and a single retry, and a
   superseded `ModelWarmup` cancels its builder rather than letting it finish.

---

## 5. What this note has not established

- **Whether the compile cache can be built without a GPU.** §1 assumes not. One
  CPU-only start-up with `VLLM_CACHE_ROOT` on a volume settles it, and the answer
  changes which mechanism is right, not merely how it is implemented.
- **What the compile cache key contains.** One observation says
  `enable_prefix_caching` is outside it. Model, dtype, GPU architecture and vLLM
  version are expected members and none of them varied in that run. The test is
  one flag change and a look at the directory hash
  (`docs/benchmarks/l40s-run3.md` §6).
- **Whether an image layer or a volume is the cheaper carrier** for 6 MiB across
  a node set of a given size — an image pull is cached per node, a volume read is
  not, and the crossover was not computed.
- **Anything on MI300X.** Every number behind this note is L40S, and the compile
  artefact is architecture-specific by construction, so none of it transfers.
