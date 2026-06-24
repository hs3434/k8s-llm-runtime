#!/usr/bin/env bash
# scripts/cluster/common.sh — shared shell functions for cluster setup
set -euo pipefail

export KUBECONFIG="${KUBECONFIG:-./kubeconfig}"
export CLUSTER_NAME="${CLUSTER_NAME:-k8s-llm-demo}"

log() { echo "[$(date +%H:%M:%S)] $*"; }

wait_for_node_ready() {
    local timeout="${1:-120}"
    log "Waiting for node Ready (timeout=${timeout}s)"
    kubectl wait --for=condition=Ready node --all --timeout="${timeout}s"
}

install_ingress_nginx() {
    log "Installing ingress-nginx"
    kubectl apply -f \
        https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.0/deploy/static/provider/kind/deploy.yaml
    kubectl wait --namespace ingress-nginx \
        --for=condition=ready pod \
        --selector=app.kubernetes.io/component=controller \
        --timeout=120s
}

install_metrics_server() {
    log "Installing metrics-server (for HPA)"
    kubectl apply -f \
        https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
    # Patch for kind: --kubelet-insecure-tls (insecure certs)
    kubectl patch deployment metrics-server -n kube-system --type=json \
        -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
}
