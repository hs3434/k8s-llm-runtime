#!/usr/bin/env bash
# scripts/cluster/kind-up.sh — start a kind cluster
set -euo pipefail
source "$(dirname "$0")/common.sh"

CLUSTER_NAME="${CLUSTER_NAME}-kind"

if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    log "kind cluster ${CLUSTER_NAME} already exists"
else
    log "Creating kind cluster: ${CLUSTER_NAME}"
    kind create cluster --name "${CLUSTER_NAME}" \
        --config "$(dirname "$0")/kind-config.yaml"
fi

kind export kubeconfig --name "${CLUSTER_NAME}" --kubeconfig "${KUBECONFIG}"
wait_for_node_ready 120
install_ingress_nginx
install_metrics_server

log "✓ kind cluster ready. KUBECONFIG=${KUBECONFIG}"
