#!/usr/bin/env bash
#
# Delete the kind cluster ./up.sh created, and with it everything that ran on
# it. Nothing outside the cluster is touched: no image is removed, no file is
# written, and a cluster of another name is left alone.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

# One source for the name, the same one up.sh reads.
CLUSTER=$(awk '$1 == "name:" { print $2; exit }' deploy/kind/cluster.yaml)
: "${CLUSTER:?could not read the cluster name from deploy/kind/cluster.yaml}"

# Absent tooling is not a failure here: there is then provably nothing to tear
# down, and exiting non-zero would make `./up.sh || ./down.sh` misreport.
if ! command -v kind >/dev/null 2>&1; then
    echo "kind is not on PATH, so there is no kind cluster to delete."
    exit 0
fi

# Checked separately, for the reason up.sh gives: kind's failure against a dead
# daemon is a long Go error rather than a sentence.
if ! docker info >/dev/null 2>&1; then
    echo "docker is not answering, so the cluster cannot be deleted." >&2
    echo "start the daemon and run this again." >&2
    exit 1
fi

clusters=$(kind get clusters 2>/dev/null || true)
if printf '%s\n' "$clusters" | grep -qxF "$CLUSTER"; then
    kind delete cluster --name "$CLUSTER"
else
    echo "no kind cluster named '$CLUSTER' -- nothing to delete."
fi
