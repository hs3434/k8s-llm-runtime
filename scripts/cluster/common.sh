#!/usr/bin/env bash
# scripts/cluster/common.sh — shared shell functions for cluster setup
#
# Requires: kind, kubectl (install via scripts/cluster/install-prereqs.sh)
set -euo pipefail

if ! command -v kubectl >/dev/null 2>&1; then
    echo "ERROR: kubectl not found. Run scripts/cluster/install-prereqs.sh first." >&2
    exit 1
fi

export KUBECONFIG="${KUBECONFIG:-./kubeconfig}"
export CLUSTER_NAME="${CLUSTER_NAME:-k8s-llm-demo}"

log() { echo "[$(date +%H:%M:%S)] $*"; }

wait_for_node_ready() {
    local timeout="${1:-120}"
    log "Waiting for node Ready (timeout=${timeout}s)"
    kubectl wait --for=condition=Ready node --all --timeout="${timeout}s"
}

preload_image_to_kind() {
    # Loads an image into every kind node's containerd.
    #   1. docker pull on host (relies on host docker daemon proxy / mirror)
    #   2. docker save | ctr import on each node
    # Avoids `kind load docker-image` which fails on multi-arch manifests when
    # the deprecated `mirrors` containerd field is in use.
    local image="$1"
    log "Pulling ${image} on host"
    if ! docker pull --platform linux/amd64 "${image}" >/dev/null 2>&1; then
        log "WARN: docker pull failed for ${image}; kind node will fall back to direct pull"
    fi
    log "Loading ${image} into kind nodes"
    for node in $(kind get nodes --name "${CLUSTER_NAME}"); do
        if ! docker save "${image}" 2>/dev/null | \
                docker exec -i "${node}" \
                    ctr -n k8s.io images import --snapshotter=overlayfs - >/dev/null 2>&1; then
            log "WARN: failed to load ${image} into ${node}"
        fi
    done
}

install_ingress_nginx() {
    log "Installing ingress-nginx"
    preload_image_to_kind "registry.k8s.io/ingress-nginx/controller:v1.10.0"
    preload_image_to_kind "registry.k8s.io/ingress-nginx/kube-webhook-certgen:v1.4.0"
    kubectl apply -f "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/manifests/ingress-nginx-kind-v1.10.0.yaml"
    kubectl wait --namespace ingress-nginx \
        --for=condition=ready pod \
        --selector=app.kubernetes.io/component=controller \
        --timeout=300s
}

install_metrics_server() {
    log "Installing metrics-server (for HPA)"
    preload_image_to_kind "registry.k8s.io/metrics-server/metrics-server:v0.8.1"
    kubectl apply -f "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/manifests/metrics-server.yaml"
    # Patch for kind: --kubelet-insecure-tls (insecure certs)
    kubectl patch deployment metrics-server -n kube-system --type=json \
        -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
    kubectl rollout status deployment metrics-server -n kube-system --timeout=300s
}

install_nvidia_device_plugin() {
    local ns=nvidia-device-plugin
    local img="nvcr.io/nvidia/k8s-device-plugin:v0.17.2"
    log "Installing nvidia-device-plugin ${img}"
    preload_image_to_kind "${img}"
    kubectl create namespace "${ns}" --dry-run=client -o yaml | kubectl apply -f -
    kubectl apply -n "${ns}" -f "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/manifests/nvidia-device-plugin.yaml"
    kubectl rollout status daemonset/nvidia-device-plugin -n "${ns}" --timeout=300s
}
