"""Prometheus metric definitions."""

from prometheus_client import Counter, Gauge, Histogram

# --- K8s operations ---
JOBS_CREATED = Counter(
    "k8s_jobs_created_total",
    "K8s Jobs created",
    labelnames=("vendor", "result"),
)

# --- vLLM deploy ---
VLLM_DEPLOY_DURATION = Histogram(
    "vllm_deploy_duration_seconds",
    "vLLM Helm deploy duration",
    labelnames=("model_alias",),
)

VLLM_DEPLOY_FAILURES = Counter(
    "vllm_deploy_failures_total",
    "vLLM deploy failures",
    labelnames=("model_alias", "reason"),
)

# --- Inference routing ---
INFERENCE_REQUESTS = Counter(
    "inference_requests_total",
    "Inference requests",
    labelnames=("model_alias", "status"),
)

INFERENCE_LATENCY = Histogram(
    "inference_latency_seconds",
    "Inference request latency",
    labelnames=("model_alias",),
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)

MODELS_LOADED = Gauge(
    "models_loaded",
    "Currently loaded model count",
    labelnames=("model_alias",),
)
