# Cluster Bootstrap — TODO (in progress)

Carried over from session on 2026-06-24. See git history for context
(commit `0bf3a3a`).

## Goal

Get `make cluster-up` running end-to-end against a kind cluster whose
nodes can pull images without manual intervention.

## Known remaining work

### 1. Verify `containerdConfigPatches` don't break kubelet

The first attempt with `containerdConfigPatches` (including `tls.insecure_skip_verify`)
caused `kubeadm init` to fail: `kubelet-check` timed out after 4m
("The kubelet is not healthy after 4m0s").

After removing the `tls.insecure_skip_verify` blocks, the user aborted
the rebuild — needs verification.

**Next step**: `make cluster-down && make cluster-up` and watch for
kubelet readiness within ~30s of node container start. If still failing:

- Check containerd logs inside the control-plane container:
  `docker exec k8s-llm-demo-kind-control-plane journalctl -u containerd`
- Confirm the TOML patches parse (containerd will fail to start if not).
- Try one registry first (only `registry.k8s.io` → `k8s.m.daocloud.io`)
  before adding all five mirrors.

### 2. Verify ingress-nginx pods actually become Ready

Once the cluster is healthy, `install_ingress_nginx` should pull
`registry.k8s.io/ingress-nginx/controller:v1.10.0` via the mirror.

Sanity check:

```bash
kubectl -n ingress-nginx get pods
# Expected: controller pod Running, admission jobs Completed
```

### 3. Verify metrics-server

Same flow — pull `registry.k8s.io/metrics-server/metrics-server:v0.x`
via mirror, check `kubectl top nodes` works.

### 4. README — document the bootstrap flow

`README.md` should tell new users:

```bash
# One-time prereqs install (kind + kubectl to ~/.local/bin)
./scripts/cluster/install-prereqs.sh

# Per-session: put tools on PATH
export PATH="$HOME/.local/bin:$PATH"

# Bring up the cluster
make cluster-up
```

Also mention:

- `KUBECTL_VERSION` / `KIND_VERSION` / `*_DOWNLOAD_URL` env vars
- `proxychains4` is auto-detected by `install-prereqs.sh`
- Required system packages: `docker` (for kind), `curl` or `wget`,
  `bash` ≥ 4 (for `set -euo pipefail`)

### 5. Plan ahead: vLLM image is ~15 GB

When Phase 5 reaches the e2e demo with vLLM, the container image
pull will be large. Two paths:

- **Mirror path**: add `rocm-docker.m.daocloud.io` mirror for
  `rocm.docker.amd.com` (ROCm images) — needs verification that
  DaoCloud mirrors these.
- **Preload path**: build vLLM into a local image, push to kind via
  `kind load docker-image vllm-qwen:latest --name k8s-llm-demo-kind`.

Whichever path is chosen, document it in `docs/architecture.md` during
Phase 6.

### 6. Cleanup: existing in-progress cluster

`kind get clusters` after the aborted rebuild may show a half-built
cluster. Run `make cluster-down` (or `kind delete cluster --name
k8s-llm-demo-kind`) before the next `make cluster-up`.

## Current branch / commit state

- Branch: `main`
- Tracking: `origin/main` at https://github.com/hs3434/k8s-llm-runtime
- Latest commit: `0bf3a3a refactor(cluster): separate kubectl/kind install + add registry mirror`

## Environment notes

- `proxychains4` available at `/usr/local/bin/proxychains4` —
  ~10x speedup for direct downloads to Google CDN.
- `kubectl` already installed at `~/.local/bin/kubectl` (v1.35.0).
- No sudo available — install scripts target `~/.local/bin` only.
- Mirror that works for `registry.k8s.io`: `k8s.m.daocloud.io`
  (verified `ImagePullBackOff` resolves; ~1.5s per 273 MB image).