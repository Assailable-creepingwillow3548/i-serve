# Layout

The map of the tree, not a route: one row per component, what it is and how
far it got. Directories map one-to-one onto the components the platform is
built from. The routes are in [../README.md](../README.md).

| Path | What | State |
|---|---|---|
| `up.sh`, `down.sh` | The eleven commands of [running-on-kind.md](running-on-kind.md) as one entry point | brings the stack up and tears it down |
| `docs/SLO.md` | Targets, floors, concurrency ceiling, and how each was derived | ✅ |
| `docs/GLOSSARY.md` | Vocabulary and notation | ✅ |
| `docs/model-anatomy.md` | The served model at five zoom levels | ✅ |
| `docs/accelerator-landscape.md` | Which term of the decode equation each vendor attacks | ✅ snapshot, dated 2026-08-23 |
| `docs/architecture.md` | Request path from ingress to GPU | ✅ drawn from the running objects |
| `docs/runbook.md` | Canary rollout, SLO-breach tree, morning triage, OOM | canary run once on `kind`; the OOM procedure not written |
| `docs/symptom-map.md`, `.json` | The operator's decision tree, and the checked subset the site evaluates | 69 nodes; the JSON's 37 nodes held equal by a test |
| `docs/running-on-kind.md` | The eleven commands, the two load-bearing waits, the stub contract | ✅ |
| `docs/adding-a-run.md` | Why runs are what accumulate here, and the checklist | the MI300X run is its first user |
| `docs/benchmarks/` | Load test reports, cost figures, and the chart above | runs 1–3 written up, raw evidence committed |
| `docs/benchmarks/runsheets/` | The sheet written **before** each run | five sheets for runs 1–3; one for a MI300X run not yet made |
| `docs/instrument-vllm-bench-sweep.md` | What `vllm bench sweep` does at `v0.27.1` | verified off-card against that tag |
| `bench/` | Load harness, `roofline.py`, the chart generator, the site export; tests in `bench/tests/` | model calibrated; the harness ran run 3 on a card |
| `site/` | The calculator and the advisor as one static page for Pages | live; parity 211/211 rows |
| `.github/workflows/` | Tests on Python 3.10 and 3.14, the quick-start commands, the chart, the parity check | installs nothing, which is the claim it tests |
| `.githooks/` | A pre-commit hook that regenerates the chart and `site/data/`, and three refusals — a status glyph on the map, non-English content, a credential in any file | opt-in: `git config core.hooksPath .githooks`; CI runs the three on a branch no hook saw |
| `deploy/kind/` | Local CPU-only cluster for logic debugging | control plane + two workers |
| `deploy/manifests/` | vLLM as Deployment, Service and Ingress; a `kind` overlay swaps in a stub | base is the GPU artefact; a canary overlay splits `/v1` by weight |
| `deploy/ingress/` | ingress-nginx overlay: the edge in front of the Service | route live on `kind`; edge timeout derived and measured |
| `deploy/helm/vllm/` | vLLM chart | empty |
| `deploy/keda/` | Queue-depth autoscaling on `vllm:num_requests_waiting` | watched scaling 1→4→1 on `kind` |
| `deploy/observability/` | Prometheus rules, Grafana dashboards as code | queue alert watched firing; histogram panels dark until a card |
| `deploy/router/` | The router on `kind`: manifests, the fleet-filling script, and what the flag costs | routing watched over three replicas; the staleness priced |
| `deploy/terraform/` | GPU node provisioning | one MI300X droplet; validated, never applied |
| `router/` | Go: a prefix-aware router, choosing the replica that already holds the prompt | binary and tests; on `kind` it serves a second host in front of the stub Pods |
| `controllers/modelwarmup/` | Go operator: warm a model before it joins routing | architecture note only, and it argues against the code |
