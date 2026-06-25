#!/usr/bin/env bash
# scripts/cluster/kind-up.sh — start a kind cluster
set -euo pipefail
source "$(dirname "$0")/common.sh"

CLUSTER_NAME="${CLUSTER_NAME}-kind"
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
CDI_SPEC_DIR="${CDI_SPEC_DIR:-$HOME/.config/cdi}"
CDI_SPEC_FILE="${CDI_SPEC_DIR}/nvidia.yaml"
NVIDIA_HOST_LIBDIR="${NVIDIA_HOST_LIBDIR:-/opt/nvidia-driver-libs}"
NVIDIA_DRIVER_LIBS_HOST_DIR="${NVIDIA_DRIVER_LIBS_HOST_DIR:-$HOME/.cache/k8s-llm-runtime/nvidia-driver-libs}"
HF_CACHE_HOST_DIR="${HF_CACHE_HOST_DIR:-/work/run/projects/bio-24/k8s-llm-runtime/cache}"

GPU_ENABLED=0
if command -v nvidia-ctk >/dev/null 2>&1 && [[ -e /dev/nvidia0 ]]; then
    mkdir -p "${CDI_SPEC_DIR}"
    NEEDS_REGEN=0
    if [[ ! -f "${CDI_SPEC_FILE}" ]]; then
        NEEDS_REGEN=1
    elif [[ -r /proc/driver/nvidia/version && "${CDI_SPEC_FILE}" -ot /proc/driver/nvidia/version ]]; then
        NEEDS_REGEN=1
    fi
    if [[ "${NEEDS_REGEN}" -eq 1 ]]; then
        log "Generating CDI spec to ${CDI_SPEC_FILE}"
        if nvidia-ctk cdi generate --output="${CDI_SPEC_FILE}" >/dev/null 2>&1; then
            log "✓ CDI spec generated"
        else
            log "WARN: nvidia-ctk cdi generate failed; falling back to non-GPU cluster"
        fi
    fi
    if [[ -f "${CDI_SPEC_FILE}" ]]; then
        mkdir -p "${NVIDIA_DRIVER_LIBS_HOST_DIR}"
        cp -a /usr/lib/x86_64-linux-gnu/libcuda* "${NVIDIA_DRIVER_LIBS_HOST_DIR}/" 2>/dev/null || true
        cp -a /usr/lib/x86_64-linux-gnu/libnvcuvid* "${NVIDIA_DRIVER_LIBS_HOST_DIR}/" 2>/dev/null || true
        cp -a /usr/lib/x86_64-linux-gnu/libnvidia* "${NVIDIA_DRIVER_LIBS_HOST_DIR}/" 2>/dev/null || true
        cp -a /usr/lib/x86_64-linux-gnu/libEGL_nvidia* "${NVIDIA_DRIVER_LIBS_HOST_DIR}/" 2>/dev/null || true
        cp -a /usr/lib/x86_64-linux-gnu/libGLES*_nvidia* "${NVIDIA_DRIVER_LIBS_HOST_DIR}/" 2>/dev/null || true
        cp -a /usr/lib/x86_64-linux-gnu/libGLX_nvidia* "${NVIDIA_DRIVER_LIBS_HOST_DIR}/" 2>/dev/null || true
        GPU_ENABLED=1
        log "GPU passthrough enabled (CDI; host libdir remap: /usr/lib/x86_64-linux-gnu → ${NVIDIA_HOST_LIBDIR})"
    fi
else
    log "nvidia-ctk or /dev/nvidia0 not found; starting non-GPU cluster"
fi

if [[ "${GPU_ENABLED}" -eq 1 ]]; then
    KIND_CONFIG_SRC="${SCRIPTS_DIR}/kind-config-gpu.yaml"
    KIND_CONFIG_RENDERED="/tmp/kind-config-gpu-rendered.yaml"
    CDI_SPEC_RENDERED_DIR="/tmp/cdi-rendered"
    mkdir -p "${CDI_SPEC_RENDERED_DIR}"
    cp "${CDI_SPEC_FILE}" "${CDI_SPEC_RENDERED_DIR}/nvidia.yaml"
    sed -i \
        -e "s|hostPath: /usr/lib/x86_64-linux-gnu/|hostPath: ${NVIDIA_HOST_LIBDIR}/|g" \
        "${CDI_SPEC_RENDERED_DIR}/nvidia.yaml"
    export CDI_SPEC_DIR="${CDI_SPEC_RENDERED_DIR}"
    export NVIDIA_HOST_LIBDIR
    export NVIDIA_DRIVER_LIBS_HOST_DIR
    export HF_CACHE_HOST_DIR
    envsubst < "${KIND_CONFIG_SRC}" > "${KIND_CONFIG_RENDERED}"
    CONFIG_ARG="--config ${KIND_CONFIG_RENDERED}"
else
    CONFIG_ARG="--config ${SCRIPTS_DIR}/kind-config.yaml"
fi

if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    log "kind cluster ${CLUSTER_NAME} already exists"
    if [[ "${GPU_ENABLED}" -eq 1 ]]; then
        log "WARN: existing cluster was not created with GPU config. Delete it with"
        log "      'make cluster-down' and re-run if you need GPU passthrough."
    fi
else
    log "Creating kind cluster: ${CLUSTER_NAME}"
    kind create cluster --name "${CLUSTER_NAME}" ${CONFIG_ARG}
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

if [[ "${GPU_ENABLED}" -eq 1 ]]; then
    for node in $(kubectl get nodes -l k8s-llm-runtime/gpu=true -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'); do
        docker exec "${node}" bash -lc 'for f in /opt/nvidia-driver-libs/libcuda* /opt/nvidia-driver-libs/libnvcuvid* /opt/nvidia-driver-libs/libnvidia* /opt/nvidia-driver-libs/libEGL_nvidia* /opt/nvidia-driver-libs/libGLES*_nvidia* /opt/nvidia-driver-libs/libGLX_nvidia*; do [ -e "$f" ] && ln -sf "$f" "/usr/lib/x86_64-linux-gnu/$(basename "$f")"; done; true'
    done
    install_nvidia_device_plugin
fi

log "✓ kind cluster ready. KUBECONFIG=${KUBECONFIG}"
