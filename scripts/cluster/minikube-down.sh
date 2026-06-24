#!/usr/bin/env bash
# scripts/cluster/minikube-down.sh
set -euo pipefail
source "$(dirname "$0")/common.sh"

CLUSTER_NAME="${CLUSTER_NAME}-minikube"
if minikube status -p "${CLUSTER_NAME}" >/dev/null 2>&1; then
    minikube delete -p "${CLUSTER_NAME}"
fi
rm -f "${KUBECONFIG}"
log "✓ minikube cluster deleted"
