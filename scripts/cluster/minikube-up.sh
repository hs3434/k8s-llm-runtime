#!/usr/bin/env bash
# scripts/cluster/minikube-up.sh — start a minikube cluster
set -euo pipefail
source "$(dirname "$0")/common.sh"

CLUSTER_NAME="${CLUSTER_NAME}-minikube"

if minikube status -p "${CLUSTER_NAME}" >/dev/null 2>&1; then
    log "minikube profile ${CLUSTER_NAME} already exists"
else
    log "Creating minikube profile: ${CLUSTER_NAME}"
    minikube start -p "${CLUSTER_NAME}" \
        --driver=docker \
        --cpus=4 --memory=4g --disk-size=20g
    minikube addons enable ingress -p "${CLUSTER_NAME}"
    minikube addons enable metrics-server -p "${CLUSTER_NAME}"
fi

minikube update-context -p "${CLUSTER_NAME}" --kubeconfig "${KUBECONFIG}"
wait_for_node_ready 180

log "✓ minikube cluster ready. KUBECONFIG=${KUBECONFIG}"
