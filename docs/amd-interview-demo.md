# AMD ROCm Python Backend Interview — Demo Guide

Target role: AMD ROCm Python 后端开发工程师 (Vincent Fang's team)

## Pre-demo setup (do once)

1. **Bring your laptop** with:
   - Docker + kind installed
   - This repo cloned
   - Python 3.11 + uv installed
   - helm v3.14+ installed
   - Built Router image: `docker build -f docker/Dockerfile.router -t router:demo .`

2. **Verify environment** (5 min):
   ```bash
   cd /work/run/projects/bio-24/my_projects/k8s-llm-runtime
   uv sync --all-extras
   make cluster-up CLUSTER=kind
   make test
   ```

## Demo script (≈ 8 minutes)

### Act 1: Show the project (1 min)

Open repo in IDE. Walk through:
- `src/k8s_llm_runtime/` — three-layer library
- `charts/` — two Helm charts
- `examples/vllm-qwen/server.py` — FastAPI entry
- `docs/architecture.md` — architecture diagram

**Talking points**:
- "Extracted K8s execution from ai-flow into a standalone library"
- "Three layers: Job → vLLM → Model routing"
- "OpenAI-compatible API + Helm-based deploy + distributed lock"

### Act 2: Live demo (5 min)

In one terminal:
```bash
cd /work/run/projects/bio-24/my_projects/k8s-llm-runtime
make cluster-up CLUSTER=kind
# (wait ~30s for kind to come up)

# Build Router image
docker build -f docker/Dockerfile.router -t k8s-llm-runtime/router:0.1.0 .

# Pin Router to a plain worker (worker2) so we only need the Router
# image there. Use docker save | ctr import — `kind load docker-image`
# can fail under rootless Docker / containerd v2.
KUBECONFIG=./kubeconfig kubectl label node k8s-llm-demo-kind-worker2 \
    k8s-llm-runtime/router=true --overwrite
docker save k8s-llm-runtime/router:0.1.0 \
    | docker exec -i k8s-llm-demo-kind-worker2 \
        ctr -n k8s.io images import --snapshotter=overlayfs -

# Pack llm-inference chart into a ConfigMap
kubectl create configmap llm-router-chart-source \
    --from-file=charts/llm-inference/ \
    --namespace=llm-system --dry-run=client -o yaml | kubectl apply -f -

# Install llm-router chart (pinned to worker2)
helm install llm-router ./charts/llm-router \
    --namespace llm-system --create-namespace --wait \
    --set nodeSelector.k8s-llm-runtime/router=true

# Wait for ready
kubectl wait --namespace llm-system \
    --for=condition=ready pod \
    --selector=app.kubernetes.io/name=llm-router \
    --timeout=120s

# Port-forward
kubectl --namespace llm-system port-forward svc/llm-router 8080:8080 &
```

In another terminal:
```bash
# 1. health check
curl http://localhost:8080/healthz
# {"status":"healthy"}

# 2. readiness (verifies K8s API + RBAC)
curl http://localhost:8080/readyz
# {"status":"ready"}

# 3. list models (none loaded yet)
curl http://localhost:8080/v1/models
# {"object":"list","data":[]}

# 4. first chat → router auto-deploys qwen-0.5b
time python examples/vllm-qwen/client.py --prompt "用一句话介绍 Kubernetes"
# (waits ~60s for first deploy + model load)
# Output: ... response from model

# 5. second chat → already deployed, fast
time python examples/vllm-qwen/client.py --prompt "再说一个"
# Output: ... ~1s

# 6. show helm state
helm list -n llm-models
# qwen-0.5b    llm-models    1    deployed    qwen-0.5b-...    0.1.0

# 7. show K8s resources
kubectl get all -n llm-models

# 8. unload
curl -X DELETE http://localhost:8080/v1/models/qwen-0.5b
# 204 No Content

# Verify gone
helm list -n llm-models
# (empty)
```

### Act 3: Architecture explanation (2 min)

Show `docs/architecture.md`. Explain:
- "Auto-deploy via Helm + K8s Lease prevents concurrent deploy of same model"
- "Each model = one Helm release = independent lifecycle"
- "GPU vendor selected via values: amd/nvidia/none"

### Act 4: Q&A prep

Expected questions and answers:

| Question | Answer |
|---|---|
| "How does multi-Router replica work?" | "K8s Lease per model alias; only one replica deploys at a time. Helm list rebuilds state on startup." |
| "Why Helm over CRD/Operator?" | "Lower complexity, standard tooling, AMD cluster has helm pre-installed. Can migrate to Operator if needed." |
| "Why Pydantic?" | "Type safety + FastAPI auto-OpenAPI schema + easy testing." |
| "How would you add auth?" | "OAuth2 Proxy in front of ingress. K8s ServiceAccount handles cluster auth." |
| "AMD ROCm support?" | "Yes — `gpu.vendor=amd` injects `amd.com/gpu` resource. Tested with MI300X nodeSelector. vLLM has ROCm images." |
| "Streaming (SSE)?" | "Reserved in `ChatRequest.stream`. v1.1 plan: StreamingResponse + httpx.stream." |
| "What's the failure mode?" | "Documented in architecture.md — 8 failure modes with detection + behavior." |
| "Compared to KServe?" | "KServe is heavier (CRD + Controller). This is a thin layer on stock K8s." |

## Teardown (after demo)

```bash
make cluster-down CLUSTER=kind
```

## Materials to bring

- This repo on laptop
- Slides with architecture diagram (export from docs/architecture.md)
- Resume with this project listed
- Printed one-pager of failure modes table

## Talking points summary

1. **Extracted** ai-flow's K8s execution into a standalone library
2. **Built** OpenAI-compatible vLLM router on top
3. **Demonstrated** auto-deploy on first request
4. **Handled** concurrency with K8s Lease
5. **Ready** for AMD ROCm (one value change)
