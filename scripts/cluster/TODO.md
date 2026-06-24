# End-to-end Demo Verification — DONE (partially)

Walked through `docs/amd-interview-demo.md` on 2026-06-24 against the
kind cluster from the previous cluster-bootstrap round. Most of the
orchestration works; the actual vLLM inference is blocked by hardware.

## What works (verified)

1. `make cluster-up` — 3 nodes Ready, ingress-nginx Ready,
   metrics-server Ready, `kubectl top nodes` returns data.
2. `docker build -f docker/Dockerfile.router -t router:demo .` —
   succeeds after vendoring `uv` binary and helm tarball in
   `docker/build-context/` (pypi.org / get.helm.sh aren't reachable
   from build containers in restricted networks). Uses Tsinghua PyPI
   mirror for the dep install.
3. Router image loaded into kind nodes (manual `docker save | ctr
   import` because `kind load docker-image` errors on multi-arch
   manifests under containerd v2).
4. Chart packed as `.tgz` and stored in `llm-router-chart-source`
   ConfigMap (the old `--from-file=charts/llm-inference/` only added
   2 files — kubectl doesn't recurse, and `/` isn't a valid key char).
   Init container extracts the tgz with `tar --strip-components=1`.
5. `helm install llm-router` deploys successfully; both router pods
   become Ready.
6. Router endpoints work:
   - `GET /healthz` → `{"status":"healthy"}`
   - `GET /readyz`  → `{"status":"ready"}`
   - `GET /v1/models` → `{"object":"list","data":[]}`
7. First `POST /v1/chat/completions` triggers a helm release in
   `llm-models` (release name `qwen-0-5b` — sanitized from alias
   `qwen-0.5b` which violates DNS-1035).
8. Lease lock acquired via `deploy-qwen-0-5b`; chart tgz extracted
   to `/app/charts/llm-inference/`; Deployment/Service/ServiceAccount
   rendered correctly in `llm-models`.

## What was fixed along the way

| Symptom | Fix |
|---|---|
| `/readyz` returns 503 (RBAC) | `Role` → `ClusterRole` (router deploys to `llm-models` namespace, cross-namespace access required) |
| `helm install` fails: `secrets is forbidden` | added `secrets: get,list,watch,create,update,patch,delete` |
| `helm install` fails: `namespaces is forbidden` | added `namespaces: create` |
| `helm install` fails: `serviceaccounts is forbidden` | added `serviceaccounts: get,list,watch,create,update,patch,delete` |
| Stale lease (old pod) → 422 on replace | `_try_acquire_once` now delete + recreate instead of `replace_namespaced_lease` (the latter requires `resourceVersion`) |
| Service "qwen-0.5b" invalid (DNS-1035) | added `VLLMInferenceOperator.to_dns_label()`; release name and helm `fullnameOverride` use sanitized name; lock key uses sanitized name too |
| `MANIFEST: empty` after init (templates missing) | chart source ConfigMap must be a `.tgz` (kubectl `--from-file=DIR` doesn't recurse into subdirs, and `templates/deployment.yaml` key with `/` is invalid) |
| Chart tarball extraction | init container: `tar -xzf /chart-source/chart --strip-components=1 -C /app/charts/llm-inference` |

## What's blocked

The vLLM pod itself can't run on this kind cluster:

1. **No AMD GPU resource.** Default `gpu.vendor=amd` injects
   `amd.com/gpu` resource request. Workaround for demo:
   `--set models.defaultGpu.vendor=none`.
2. **Memory insufficient.** Default chart values request 8Gi memory /
   16Gi limit; kind nodes have ~4Gi available for pods. Lowered
   defaults in `charts/llm-inference/values.yaml` to 2Gi/4Gi — small
   enough for kind, but `qwen-0.5b` itself needs more for inference.
3. **Image pull fails.** `vllm/vllm-openai:latest` is a ~5GB image.
   No working mirror found for it (registry.k8s.io via
   `k8s.m.daocloud.io` doesn't have it; direct pulls time out).
4. **No GPU even if pod scheduled.** Without actual AMD ROCm hardware
   the model can't load weights.

This means the actual `qwen-0.5b` chat-completion smoke test cannot
run on this kind cluster. The orchestration (router → chart load →
helm release → K8s resources created) is fully verified.

## What was changed in this round

- `charts/llm-router/templates/role.yaml`, `rolebinding.yaml` —
  ClusterRole/ClusterRoleBinding + extra resource verbs
- `charts/llm-router/templates/deployment.yaml` — init container
  extracts chart tgz
- `charts/llm-inference/values.yaml` — default resources lowered
  to fit kind
- `docker/Dockerfile.router` — vendored `uv` + helm tarball,
  Tsinghua PyPI mirror
- `docker/build-context/{uv, helm-v3.14.0-linux-amd64.tar.gz}` —
  new vendored deps
- `src/k8s_llm_runtime/vllm.py` — `to_dns_label` helper; release
  name sanitization
- `src/k8s_llm_runtime/lock.py` — delete + recreate stale leases
- `src/k8s_llm_runtime/model.py` — uses sanitized lock key + status
  lookups; `discover_existing` maps back via to_dns_label
- `tests/unit/test_lock.py`, `tests/unit/test_model.py` — updated
  for the new code paths
- `tests/chart/test_llm_router.py` — updated for ClusterRole

All tests pass (`make test`: 21/21), `ruff check` clean, `mypy
--strict` clean.

## Next: when there's a real AMD machine

1. Provision a node with `amd.com/gpu` resource
2. Override chart `image.repository` to a known mirror, or pre-pull
   on the host and use `kind load docker-image` once the
   `kind load` multi-arch issue is fixed (or just keep using the
   `docker save | ctr import` workaround)
3. Add a `nodeSelector` for `amd.com/gpu` (or remove the
   auto-applied taint on the control-plane so the vLLM pod can
   land there)
---

# Mock vLLM for CPU-only CI — DONE (2026-06-25)

To run the e2e demo without GPU hardware or the 5 GB `vllm/vllm-openai`
image, `docker/mock-vllm/` ships a 225 MB FastAPI app that mimics
OpenAI-compatible `/v1/chat/completions` (echoes the user's last
message with a `[mock] ` prefix).

## End-to-end cycle (verified on kind, 8 GB nodes, no GPU)

```
1. fresh /v1/models                          → []
2. POST /v1/chat/completions                 → 2.4s, mock echo
3. helm list -n llm-models                   → qwen-0-5b deployed
4. pod qwen-0-5b-...                         → 1/1 Running
5. second chat                               → 130ms (cached)
6. DELETE /v1/models/qwen-0.5b               → 204
7. helm list -n llm-models after DELETE      → empty
8. pods after DELETE                         → none
```

## How to use

```bash
# Build the mock image (one-time)
docker build -t mock-vllm:demo docker/mock-vllm/

# Load into kind
for node in $(kind get nodes); do
  docker save mock-vllm:demo | docker exec -i "$node" \
    ctr -n k8s.io images import --snapshotter=overlayfs -
done

# Install llm-router pointing helm at the mock values file
helm install llm-router ./charts/llm-router \
    --namespace llm-system --create-namespace \
    --set image.repository=router,image.tag=demo \
    --set vllmHelmExtraArgs="-f /etc/vllm-extra/values-mock.yaml"

# Pack mock values into a ConfigMap so the router can mount it
kubectl -n llm-system create configmap llm-router-vllm-extra \
    --from-file=docker/mock-vllm/values-mock.yaml
```

The mock values file overrides the chart's `image.repository` from
`vllm/vllm-openai` to `mock-vllm`. The mock image's `entrypoint.sh`
parses and discards `--model` / `--port` args that the chart passes.

## Defaults

- `charts/llm-router/values.yaml` — `models.defaultGpu.vendor` is
  `none` (was `amd`) so the chart deploys on any cluster. AMD ROCm
  is the AMD-interview target; flip via
  `--set models.defaultGpu.vendor=amd`.
- `examples/vllm_qwen/server.py` — `GPU_VENDOR` env default is
  `none` (was `amd`). Same override applies.
- `charts/llm-inference/values.yaml` — resources lowered from
  8Gi/16Gi to 2Gi/4Gi so the vLLM pod fits on kind workers. Real
  AMD/CUDA deployments should override.

## What was added

- `docker/mock-vllm/{Dockerfile,entrypoint.sh,server.py,values-mock.yaml}`
  — mock OpenAI-compatible server + Helm values override
- `charts/llm-router/templates/_helpers.tpl` — `llm-router.chartSourceName`
  helper (used by deployment.yaml for the chart-source ConfigMap)
- `charts/llm-router/templates/deployment.yaml` — env var
  `VLLM_HELM_EXTRA_ARGS` and optional `vllm-helm-extra` ConfigMap
  volume
- `charts/llm-router/values.yaml` — `vllmHelmExtraArgs` setting
- `src/k8s_llm_runtime/vllm.py` — `VLLMInferenceOperator` reads
  `VLLM_HELM_EXTRA_ARGS` and appends to the helm install args
- `src/k8s_llm_runtime/model.py` — `unload` is now idempotent: it
  always calls `helm uninstall` (cluster is the source of truth,
  not per-replica `_loaded`) and swallows "not found" errors
- Tests updated for the new behavior

## Caveats

- `mock-vllm` is for orchestration testing only. It does not run any
  real model. The chart's resource limits + GPU settings still
  apply — set `gpu.vendor=amd` + real ROCm nodeSelector for an
  actual interview demo.
- The router has 2 replicas and each keeps its own `_loaded` set.
  `list_models()` may return stale info on a different replica than
  the one that ran the chat. The cluster state (helm release) is
  always correct, and `unload` is now idempotent so DELETE works
  from any replica. A shared state (CRD or external store) is the
  real fix for `list_models` accuracy.
