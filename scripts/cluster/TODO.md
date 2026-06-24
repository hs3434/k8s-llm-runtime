# Cluster Bootstrap — DONE (2026-06-24)

`make cluster-up` now runs end-to-end without manual intervention
(assuming the host has docker daemon configured to reach `registry.k8s.io`,
e.g. via the HTTP_PROXY drop-in noted below).

## Verification log (latest run)

```
[19:57:23] ✓ kind cluster deleted
[19:58:34] Installing ingress-nginx
...
pod/ingress-nginx-controller-57bf4898db-t5pvx condition met
[19:58:34] Installing metrics-server (for HPA)
...
deployment "metrics-server" successfully rolled out
[20:00:39] ✓ kind cluster ready. KUBECONFIG=./kubeconfig
```

Final state (verified):

- 3 nodes Ready (control-plane + 2 workers)
- `ingress-nginx-controller` 1/1 Running
- `metrics-server` 1/1 Running
- `kubectl top nodes` returns CPU/memory data

## What was wrong (recap of debugging)

Three independent blockers combined to make the previous `make cluster-up`
fail at the ingress-nginx step:

### 1. `nodeSelector ingress-ready=true` on ingress-nginx controller

The official `kind` deploy.yaml requires this label, but kind only
auto-applies it when the node has `extraPortMappings`. We don't expose
80/443 on the host (the project uses `kubectl port-forward`), so the
label is missing.

**Fix**: `kind-up.sh` now labels every node with `ingress-ready=true`
right after `wait_for_node_ready`. Could also be solved by adding
`extraPortMappings` to `kind-config.yaml` but the manual label is
explicit and doesn't bind host ports.

### 2. Deprecated `mirrors` field ignored by containerd v2

`kindest/node:v1.32.2` ships with `containerd v2.0.2`, where
`[plugins."io.containerd.grpc.v1.cri".registry.mirrors]` is **deprecated**
and silently ignored when `config_path` is also set (which it is by
default). Result: image pulls inside kind nodes go directly to
`registry.k8s.io`, hit network restrictions, and hang.

**Fix (chosen)**: pre-load images into kind nodes from the host before
applying the manifest. New `preload_image_to_kind` helper in `common.sh`:

```bash
docker pull --platform linux/amd64 <image>
docker save <image> | docker exec -i <node> \
    ctr -n k8s.io images import --snapshotter=overlayfs -
```

Note: `kind load docker-image` was tried first but fails on multi-arch
manifests with `rpc error: code = NotFound desc = content digest ...: not found`.
The `docker save | ctr import` pipe sidesteps that.

Alternative long-term fix: migrate `kind-config.yaml` to the new
`config_path` syntax (`/etc/containerd/certs.d/<host>/hosts.toml` with
`extraMounts`). Not done yet because the daocloud mirror only caches
core K8s images (coredns, etcd, kube-apiserver, ...) — `ingress-nginx/controller`,
`kube-webhook-certgen`, and `metrics-server` all return **403** from
`k8s.m.daocloud.io`. The pre-load path is more reliable for our image
set.

### 3. Host docker can't reach `registry.k8s.io` directly

`registry.k8s.io` resolves to IPv6 (`asia-east1-docker.pkg.dev`) which
times out from this network.

**Fix (host-level, NOT in repo)**: `systemd` drop-in for docker daemon:

```
# /etc/systemd/system/docker.service.d/http-proxy.conf
[Service]
Environment="HTTP_PROXY=http://127.0.0.1:10809"
Environment="HTTPS_PROXY=http://127.0.0.1:10809"
Environment="NO_PROXY=localhost,127.0.0.1,::1,.svc,.cluster.local"
```

Where `127.0.0.1:10809` is the local HTTP proxy (xray in this
environment; substitute your own). The proxy config belongs on the
host, not in the repo — different networks will use different proxies.

The repo only requires that *some* mechanism on the host makes
`docker pull registry.k8s.io/...` work.

### 4. `kubectl apply -f https://github.com/...` hangs

`github.com` direct downloads time out (TLS handshake). The kind
ingress-nginx and metrics-server manifests are now bundled in
`scripts/cluster/manifests/` and applied from local files.

## Files changed in this round

- `scripts/cluster/common.sh` — `preload_image_to_kind` helper,
  `install_metrics_server` uses `kubectl rollout status` instead of
  `kubectl wait` (which races against old pods during rollout)
- `scripts/cluster/kind-up.sh` — labels nodes with `ingress-ready=true`
- `scripts/cluster/manifests/ingress-nginx-kind-v1.10.0.yaml` (new)
- `scripts/cluster/manifests/metrics-server.yaml` (new)

## Still pending (from original TODO)

- Plan ahead for vLLM 15 GB image pull — same pre-load pattern will
  apply (host pulls via docker daemon proxy, then load into kind).
  See `docs/architecture.md` when Phase 6 is reached.
- README — should mention the host docker daemon proxy prerequisite
  (separate PR).