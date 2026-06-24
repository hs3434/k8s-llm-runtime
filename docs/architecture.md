# Architecture

## Overview

k8s-llm-runtime is a Kubernetes-based vLLM model serving router. Users send
OpenAI-compatible chat completion requests to a FastAPI service. The service
transparently deploys vLLM inference Pods on demand, forwards requests, and
cleans up idle deployments.

## High-level flow

```
                    user
                     │
        POST /v1/chat/completions
                     │
                     ▼
        ┌────────────────────────────┐
        │   FastAPI Router (Pod)     │   ◄── llm-router chart
        │                            │
        │  ┌──────────────────────┐  │
        │  │ ModelOperator        │  │
        │  │  ├─ alias resolve    │  │
        │  │  ├─ lease acquire    │  │
        │  │  ├─ helm deploy      │  │
        │  │  └─ http forward     │  │
        │  └──────────────────────┘  │
        └────────────┬───────────────┘
                     │
        helm install / helm upgrade --install
                     │
                     ▼
        ┌────────────────────────────┐
        │   vLLM Inference Pod       │   ◄── llm-inference chart
        │   (one release per model)  │
        └────────────────────────────┘
```

## Components

### Python library (`src/k8s_llm_runtime/`)

Three layers with one clear responsibility each:

| Layer | Module | Purpose |
|---|---|---|
| Low | `job.py` | K8s Job CRUD via kubernetes-client |
| Mid | `vllm.py` | Helm-based vLLM deploy/undeploy |
| Mid | `lock.py` | K8s Lease-based distributed lock |
| High | `model.py` | Routing + auto-deploy + OpenAI-compat |

Other modules:
- `types.py` — Pydantic models (JobSpec, GPUResource, ChatRequest/Response)
- `errors.py` — typed exception hierarchy
- `_client.py` — kubernetes-client singleton
- `_retry.py` — tenacity wrapper for transient K8s API errors
- `_log.py` — structlog JSON config
- `_metrics.py` — Prometheus metric definitions

### Helm charts (`charts/`)

| Chart | Deploys | Replicas |
|---|---|---|
| `llm-inference` | vLLM Pod + Service | One Helm release per model |
| `llm-router` | FastAPI Router Deployment + RBAC | Single release, HPA 2-5 |

### Namespaces

| Namespace | Contents |
|---|---|
| `llm-system` | Router Deployment + ServiceAccount + RBAC |
| `llm-models` | One Helm release per loaded model |

## Request lifecycle (auto-deploy path)

1. User → POST `/v1/chat/completions` with `model: "qwen-7b"`
2. Router resolves alias → HuggingFace model `Qwen/Qwen2.5-7B-Instruct`
3. Router acquires K8s Lease `deploy-qwen-7b` (prevents concurrent deploy)
4. Router checks `helm list -n llm-models` for existing release
5. If missing or not Ready → `helm upgrade --install` with values
6. Wait for vLLM Pod to reach Ready state (default 600s timeout)
7. Forward original request to `http://qwen-7b.llm-models:8000/v1/chat/completions`
8. Release lease
9. Update metrics: `INFERENCE_LATENCY`, `INFERENCE_REQUESTS{status=ok}`, `MODELS_LOADED`
10. Return OpenAI-formatted response

## Concurrency model

- Multiple Router replicas can run simultaneously (HPA 2-5)
- Lease per model prevents concurrent deploy of same model
- Each model runs as its own Helm release (independent lifecycle)
- K8s Service auto-routes client requests within `llm-models` namespace

## GPU resource handling

`gpu.vendor` in values drives resource injection in chart templates:

| `gpu.vendor` | `limits` | nodeSelector example |
|---|---|---|
| `none` | (no GPU) | (any node) |
| `amd` | `amd.com/gpu: N` | `amd.com/gpu.product=MI300X` |
| `nvidia` | `nvidia.com/gpu: N` | `nvidia.com/gpu.product=A100` |

Python library mirrors this in `K8sJobOperator._build_container`.

## Failure modes

| Failure | Detection | Behavior |
|---|---|---|
| Unknown model alias | alias lookup | 404 + clear message |
| Helm install fails | non-zero rc | 500 + helm stderr |
| Helm install timeout | elapsed > 600s | 503 + timeout msg |
| vLLM pod OOMKilled | pod status | HPA + retry next request |
| Lease held by other | poll timeout | 503 + retry-after |
| K8s API unreachable | `/readyz` probe | 503 + readiness fails |
| Helm release drift | start-up scan | `discover_existing` rebuilds state |

## Why this design

- **3-layer Python lib** keeps each unit testable and replaceable
- **Helm chart per workload** = standard K8s deployment, no custom controllers
- **OpenAI-compatible API** = drop-in for any OpenAI client
- **Distributed Lease** = safe multi-replica Router without complex CRDs
- **Pydantic everywhere** = IDE hints + automatic OpenAPI for FastAPI

## Not in scope (YAGNI)

- LLM training pipelines (LoRA etc.)
- KServe / Knative integration (too heavy)
- Multi-modal (vision) models
- Streaming responses (SSE) — `ChatRequest.stream` reserved for v1.1
- Authentication — to be added at ingress layer
