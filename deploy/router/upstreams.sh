#!/usr/bin/env bash
#
# Fill the router's `-upstreams` flag from the engine's EndpointSlice, and
# restart the router so it takes it.
#
# This script is the flag's bill, made payable. The router's replica set is a
# start-up flag (`../../router/README.md` §8), so the fleet it routes over is
# whatever was true at the moment this ran. Every event that changes the fleet
# -- a KEDA scale-out, a scale-in, a Pod rescheduled onto another node, a
# rollout -- invalidates it, and nothing in the cluster notices. Run it again.
#
# That is not a defect to be patched here. `setUpstreams` is already safe to
# call while requests are in flight, which is the whole reason the ring is
# built the way it is; what is missing is the thing that calls it, and the
# thing that calls it is a Pod watch. This script is the placeholder shaped
# exactly like the hole.

set -euo pipefail

# Paths are relative to the repository root, so go there first.
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

# The cluster name has one home, and it is not this file (see ../../up.sh).
CLUSTER=$(awk '$1 == "name:" { print $2; exit }' deploy/kind/cluster.yaml)
: "${CLUSTER:?could not read the cluster name from deploy/kind/cluster.yaml}"
CONTEXT="kind-${CLUSTER}"

# The engine's container port, named `http` in
# deploy/manifests/base/deployment.yaml. Read from the Service rather than
# repeated, so a port move cannot leave this script pointing at the old one.
k() { kubectl --context "$CONTEXT" -n llm "$@"; }
PORT=$(k get service vllm -o jsonpath='{.spec.ports[?(@.name=="http")].port}')
: "${PORT:?service/vllm has no port named http -- is the stack up?}"

if ! k get configmap router-upstreams >/dev/null 2>&1; then
    echo "configmap/router-upstreams is missing." >&2
    echo "apply the router first: kubectl apply -k deploy/router/kind" >&2
    exit 1
fi

# Ready endpoints only. An endpoint that exists but is not ready is a Pod the
# Service would not send traffic to either, and routing a prefix to it would
# be affinity to a replica that answers 503.
#
# EndpointSlice and not Endpoints: the latter is deprecated, and the former is
# what the Service's own consumers -- including ingress-nginx -- read.
addrs=$(k get endpointslices -l "kubernetes.io/service-name=vllm" -o jsonpath="
{range .items[*].endpoints[?(@.conditions.ready==true)]}http://{.addresses[0]}:${PORT},{end}")
addrs=$(printf '%s' "$addrs" | tr -d '\n ')
addrs=${addrs%,}

if [ -z "$addrs" ]; then
    echo "no ready endpoints behind service/vllm." >&2
    echo "look: kubectl --context $CONTEXT -n llm get pods -l app.kubernetes.io/name=vllm" >&2
    exit 1
fi

n=$(printf '%s' "$addrs" | awk -F, '{print NF}')

# A merge patch rather than a re-create: the object keeps its labels and its
# place in the kustomization, and only the one value moves.
k patch configmap router-upstreams --type merge \
    -p "{\"data\":{\"upstreams\":\"${addrs}\"}}" >/dev/null

# An env-sourced ConfigMap is read once, at container start. Changing it does
# nothing to a running Pod -- unlike a mounted one, which the kubelet
# refreshes. So the restart is not a convenience; it is how the new value
# reaches the process at all.
k rollout restart deployment/prefix-router >/dev/null
k rollout status deployment/prefix-router --timeout=60s

printf '\n%d upstream(s): %s\n' "$n" "$addrs"
printf 'stale the moment the fleet changes. run this again after any scale event.\n'
