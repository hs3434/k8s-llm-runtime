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

# The kind ingress-nginx manifest requires nodeSelector ingress-ready=true.
# Kind only auto-applies this label when extraPortMappings is set; we don't
# expose 80/443 on the host (port-forward is enough), so label manually.
log "Labeling nodes with ingress-ready=true"
for node in $(kind get nodes --name "${CLUSTER_NAME}"); do
    kubectl label node "${node}" ingress-ready=true --overwrite
done

install_ingress_nginx
install_metrics_server

log "✓ kind cluster ready. KUBECONFIG=${KUBECONFIG}"
