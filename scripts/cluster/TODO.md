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