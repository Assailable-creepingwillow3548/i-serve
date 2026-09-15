#!/usr/bin/env bash
#
# Bring the whole stack up on kind, in one command.
#
# This script is not the documentation. The annotated command block in
# README.md, "Running it on kind", is: it says why the two `rollout status`
# lines are load-bearing for different reasons and why the last `curl` retries.
# Every wait below is there because removing it was tried and broke something.
# A reader who wants to know what this does should read that section; this file
# only makes running it cost one command instead of eleven.
#
# It adds exactly two things to those eleven commands:
#   * a preflight, so a missing tool fails on line 1 with a sentence rather
#     than halfway through a bring-up with a shell error;
#   * an explicit --context, so an `apply` cannot land on whatever cluster
#     kubectl happened to be pointing at.
#
# Teardown is ./down.sh.

set -euo pipefail

# Every path below is relative to the repository, so go there first: without this
# the preflight passes and the first apply dies on a missing kustomize directory.
cd "$(dirname "${BASH_SOURCE[0]}")"

# Read from the cluster file rather than restating it. The name lives in exactly
# one place, and changing it there must not leave this script pointing at a
# context that no longer exists.
CLUSTER=$(awk '$1 == "name:" { print $2; exit }' deploy/kind/cluster.yaml)
: "${CLUSTER:?could not read the cluster name from deploy/kind/cluster.yaml}"
CONTEXT="kind-${CLUSTER}"
KEDA=v2.20.2                      # pinned; an unpinned release retires webhooks
# 8080 is the port kind maps in deploy/kind/cluster.yaml. Overridable only so the
# failure branches below can be exercised against a real cluster without breaking
# one -- and namespaced, because a bare ENDPOINT is a name real tooling exports,
# and inheriting it would make the "up." line a statement about someone else's
# server.
ENDPOINT="${UPSH_ENDPOINT:-http://localhost:8080/v1/models}"

say() { printf '\n=== %s\n' "$*"; }

# --- preflight ---------------------------------------------------------------
# Three tools and one daemon. The daemon is checked separately because `docker`
# on PATH says nothing about whether anything is listening, and kind's failure
# in that case is a long Go error rather than a sentence.

missing=()
for tool in kind kubectl docker curl; do
    command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
if ((${#missing[@]})); then
    echo "missing on PATH: ${missing[*]}" >&2
    echo "install them first -- prerequisites are in README.md" >&2
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    echo "docker is on PATH but the daemon is not answering." >&2
    echo "start Docker Desktop (or your engine) and run this again." >&2
    exit 1
fi

# --- 1. the cluster ----------------------------------------------------------
# Re-runnable: an existing cluster is reused rather than being an error, so a
# half-finished bring-up can be resumed by running this script again.

clusters=$(kind get clusters 2>/dev/null || true)
if printf '%s\n' "$clusters" | grep -qxF "$CLUSTER"; then
    say "cluster '$CLUSTER' already exists -- reusing it"
    echo "   (built from an older cluster.yaml? ./down.sh first -- port mappings"
    echo "    and the ingress-ready label are set at creation and never updated)"
else
    say "creating the kind cluster (control plane + two workers)"
    kind create cluster --config deploy/kind/cluster.yaml
fi

k() { kubectl --context "$CONTEXT" "$@"; }

# --- 2. the edge -------------------------------------------------------------
# The wait is not politeness. ingress-nginx sets failurePolicy: Fail on its
# admission webhook, so applying the Ingress before the webhook serves is
# rejected outright -- and the rest of that same apply succeeds, leaving a stack
# that looks up and has no edge.

say "ingress-nginx"
k apply -k deploy/ingress/overlays/kind
k -n ingress-nginx rollout status deployment/ingress-nginx-controller

# --- 3. the autoscaler -------------------------------------------------------
# The opposite failure: KEDA sets failurePolicy: Ignore, so a ScaledObject
# applied too early is admitted *unvalidated*. The wait buys validation, not
# admission.

say "KEDA ${KEDA}"
k apply --server-side -f \
    "https://github.com/kedacore/keda/releases/download/${KEDA}/keda-${KEDA#v}.yaml"
k -n keda rollout status deployment/keda-operator

# --- 4. everything that depends on the two above -----------------------------

say "Prometheus, Grafana, the stub Deployment, the ScaledObject"
k apply -k deploy/observability/prometheus
k apply -k deploy/observability/grafana
k apply -k deploy/manifests/overlays/kind
k apply -k deploy/keda/overlays/kind

say "waiting for the vllm Deployment"
k -n llm rollout status deployment/vllm

# --- 5. the proof ------------------------------------------------------------
# rollout status returns when the pod is ready, which is not when the edge
# routes to it: the controller keeps its own endpoint set, and the gap between
# the two is spent answering 503. One or two of those before the JSON are that
# window, not a fault. If the retries run out, the status code says which side
# is behind, so it is asked for and reported rather than swallowed.

say "curl through the edge (503 while the endpoint set catches up is expected)"
if curl -sS --fail --retry 5 --retry-delay 1 "$ENDPOINT"; then
    printf '\n\nup. dashboard: kubectl --context %s -n monitoring port-forward svc/grafana 3000:3000\n' "$CONTEXT"
    printf 'tear down:     ./down.sh\n'
else
    rc=$?
    echo >&2
    echo "the edge did not serve $ENDPOINT (curl exit $rc)." >&2
    # One diagnostic request: no --fail, no retry, just what is actually there.
    status=$(curl -s -o /dev/null -w '%{http_code}' "$ENDPOINT") || diag=$?
    case "$status" in
        2*)  echo "$status -- it answers now. The retries ran out first: the gap" >&2
             echo "     between a ready Pod and a routing edge is measured at up" >&2
             echo "     to ~25 s on a cold cluster (deploy/ingress/README.md)," >&2
             echo "     and this run exceeded the ~6 s the retries allow." >&2
             echo "     Nothing is wrong; run ./up.sh again to confirm." >&2 ;;
        503) echo "503 -- the route exists and has no live endpoint behind it." >&2
             echo "     the pod is not ready, or the controller has not seen it yet." >&2
             echo "     look: kubectl --context $CONTEXT -n llm get endpointslice" >&2 ;;
        404) echo "404 -- there is a route table but nothing matching this path." >&2
             echo "     look: kubectl --context $CONTEXT -n llm get ingress" >&2 ;;
        # Both of these read 000, and deploy/ingress/README.md turns on telling
        # them apart: the port mapping is a docker-level publish on the node
        # container, so the TCP connect succeeds whether or not anything inside
        # is listening. curl's own exit code is the only thing that separates
        # them, so it decides here rather than the status.
        000|"")
             if [ "${diag:-0}" -eq 52 ] || [ "$rc" -eq 52 ]; then
                 echo "empty reply -- the port is mapped and nothing is behind it." >&2
                 echo "     the ingress controller is not on the mapped node; the" >&2
                 echo "     overlay's nodeSelector is what puts it there." >&2
             else
                 echo "connection refused -- the port mapping itself is gone." >&2
                 echo "     the cluster was not built from deploy/kind/cluster.yaml." >&2
             fi
             echo "     see deploy/ingress/README.md." >&2 ;;
        *)   echo "$status -- unexpected; deploy/ingress/README.md reads the codes." >&2 ;;
    esac
    exit 1
fi
