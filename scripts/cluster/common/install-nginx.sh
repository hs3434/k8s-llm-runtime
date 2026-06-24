#!/usr/bin/env bash
# scripts/cluster/common/install-nginx.sh
set -euo pipefail
source "$(dirname "$0")/../common.sh"
install_ingress_nginx
