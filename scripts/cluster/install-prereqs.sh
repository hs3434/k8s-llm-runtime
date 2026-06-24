#!/usr/bin/env bash
# scripts/cluster/install-prereqs.sh — install kind and kubectl
#
# Run once before scripts/cluster/kind-up.sh.
# Both tools are installed to ~/.local/bin (no sudo required).
#
# Honors env vars:
#   KUBECTL_VERSION       (default: v1.35.0)
#   KIND_VERSION          (default: v0.27.0)
#   KUBECTL_DOWNLOAD_URL  (override mirror for kubectl)
#   KIND_DOWNLOAD_URL     (override mirror for kind)
#   INSTALL_DIR           (default: ~/.local/bin)
set -euo pipefail

KUBECTL_VERSION="${KUBECTL_VERSION:-v1.35.0}"
KIND_VERSION="${KIND_VERSION:-v0.27.0}"
INSTALL_DIR="${INSTALL_DIR:-${HOME}/.local/bin}"

case "$(uname -m)" in
    x86_64)  arch=amd64 ;;
    aarch64) arch=arm64 ;;
    *) echo "ERROR: unsupported arch $(uname -m)" >&2; exit 1 ;;
esac

log() { echo "[$(date +%H:%M:%S)] $*"; }

# Use proxychains4 if available (faster from networks where direct DNS is slow)
PROXY=""
if command -v proxychains4 >/dev/null 2>&1; then
    PROXY="proxychains4 -q"
    log "proxychains4 detected — downloads will route through configured proxy"
fi

mkdir -p "${INSTALL_DIR}"

# --- kubectl ---
if command -v kubectl >/dev/null 2>&1; then
    log "kubectl already installed: $(kubectl version --client --short 2>/dev/null || kubectl version --client)"
else
    log "Installing kubectl ${KUBECTL_VERSION} to ${INSTALL_DIR}"
    url="${KUBECTL_DOWNLOAD_URL:-https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${arch}/kubectl}"
    if ! ${PROXY} curl -fsSL --connect-timeout 10 --max-time 600 -o "${INSTALL_DIR}/kubectl" "${url}"; then
        echo "ERROR: kubectl download failed. Set KUBECTL_DOWNLOAD_URL to an accessible mirror." >&2
        exit 1
    fi
    chmod +x "${INSTALL_DIR}/kubectl"
    log "kubectl installed: $("${INSTALL_DIR}/kubectl" version --client --short 2>/dev/null || "${INSTALL_DIR}/kubectl" version --client)"
fi

# --- kind ---
if command -v kind >/dev/null 2>&1; then
    log "kind already installed: $(kind version)"
else
    log "Installing kind ${KIND_VERSION} to ${INSTALL_DIR}"
    url="${KIND_DOWNLOAD_URL:-https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-${arch}}"
    if ! ${PROXY} curl -fsSL --connect-timeout 10 --max-time 600 -o "${INSTALL_DIR}/kind" "${url}"; then
        echo "ERROR: kind download failed. Set KIND_DOWNLOAD_URL to an accessible mirror." >&2
        exit 1
    fi
    chmod +x "${INSTALL_DIR}/kind"
    log "kind installed: $("${INSTALL_DIR}/kind" version)"
fi

# --- PATH hint ---
if [[ ":${PATH}:" != *":${INSTALL_DIR}:"* ]]; then
    log ""
    log "Add to your shell rc:"
    log "  export PATH=\"\${HOME}/.local/bin:\${PATH}\""
    log "(or run commands with full path: ${INSTALL_DIR}/kind)"
fi

log ""
log "✓ Prereqs ready. Next: scripts/cluster/kind-up.sh"