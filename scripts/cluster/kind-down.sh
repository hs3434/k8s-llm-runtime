#!/usr/bin/env bash
# scripts/cluster/kind-down.sh
set -euo pipefail
source "$(dirname "$0")/common.sh"

CLUSTER_NAME="${CLUSTER_NAME}-kind"
if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    kind delete cluster --name "${CLUSTER_NAME}"
fi
rm -f "${KUBECONFIG}"
log "✓ kind cluster deleted"
