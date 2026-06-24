"""FastAPI LLM Router.

OpenAI-compatible chat completion API. Auto-deploys vLLM models on demand
via the ModelOperator.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import structlog
import yaml
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from k8s_llm_runtime import (
    GPUResource,
    GPUVendor,
    ModelOperator,
    VLLMInferenceOperator,
)
from k8s_llm_runtime._log import configure_logging, get_logger
from k8s_llm_runtime.errors import (
    K8sLLMRuntimeError,
    LockAcquireTimeoutError,
    ModelAliasError,
    ModelNotFoundError,
    VLLMDeployError,
    VLLMDeployTimeoutError,
    VLLMUndeployError,
)
from k8s_llm_runtime.model import ChatRequest

configure_logging()
logger = get_logger(__name__)


def load_model_aliases(path: Path) -> dict[str, str]:
    if not path.exists():
        logger.warning("model_aliases_file_not_found", path=str(path))
        return {}
    with path.open() as f:
        cfg = yaml.safe_load(f) or {}
    aliases = cfg.get("aliases", {})
    if not aliases:
        raise ModelAliasError(f"No aliases found in {path}")
    return aliases


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg_path = Path(os.environ.get("MODEL_CONFIG_PATH", "/app/config/models.yaml"))
    aliases = load_model_aliases(cfg_path)

    chart_path = os.environ.get("CHART_PATH", "/app/charts/llm-inference")
    vllm_op = VLLMInferenceOperator(chart_path=chart_path)

    op = ModelOperator(
        model_aliases=aliases,
        vllm_op=vllm_op,
        namespace=os.environ.get("TARGET_NAMESPACE", "llm-models"),
        default_gpu=GPUResource(
            vendor=GPUVendor(os.environ.get("GPU_VENDOR", "amd")),
            limit=int(os.environ.get("GPU_LIMIT", "1")),
        ),
        idle_timeout_seconds=int(os.environ.get("IDLE_TIMEOUT", "600")),
    )
    app.state.op = op
    logger.info("router_started", aliases=list(aliases.keys()))
    yield
    logger.info("router_stopping")


app = FastAPI(
    title="LLM Router",
    version="0.1.0",
    description="OpenAI-compatible vLLM model serving on Kubernetes",
    lifespan=lifespan,
)
app.mount("/metrics", make_asgi_app())


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    rid = request.headers.get("X-Request-ID", str(uuid4()))
    structlog.contextvars.bind_contextvars(request_id=rid)
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    structlog.contextvars.clear_contextvars()
    return response


ERROR_MAP: dict[type, tuple[int, str]] = {
    ModelNotFoundError: (404, "Unknown model alias"),
    ModelAliasError: (400, "Invalid alias config"),
    VLLMDeployError: (500, "vLLM deploy failed"),
    VLLMDeployTimeoutError: (503, "vLLM deploy timeout"),
    VLLMUndeployError: (500, "vLLM undeploy failed"),
    LockAcquireTimeoutError: (503, "Deploy lock timeout"),
}


@app.exception_handler(K8sLLMRuntimeError)
async def handle_lib_error(request: Request, exc: K8sLLMRuntimeError):
    status_code, msg = ERROR_MAP.get(type(exc), (500, "Internal error"))
    logger.error("lib_error", error_type=type(exc).__name__, message=str(exc))
    return JSONResponse(
        status_code=status_code,
        content={"error": {"type": type(exc).__name__, "message": f"{msg}: {exc}"}},
    )


@app.get("/")
async def root():
    return {"message": "LLM Router", "version": "0.1.0"}


@app.get("/healthz")
async def healthz():
    return {"status": "healthy"}


@app.get("/readyz")
async def readyz():
    try:
        from k8s_llm_runtime import _client
        _client.core_api().list_namespace(limit=1)
    except Exception as exc:
        raise HTTPException(503, f"K8s API unreachable: {exc}") from exc
    return {"status": "ready"}


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    return await app.state.op.chat(req)


@app.get("/v1/models")
async def list_models():
    aliases = await app.state.op.list_models()
    return {
        "object": "list",
        "data": [
            {"id": a, "object": "model", "owned_by": "k8s-llm-runtime"}
            for a in aliases
        ],
    }


@app.get("/v1/models/{alias}")
async def get_model(alias: str):
    aliases = await app.state.op.list_models()
    if alias not in aliases:
        raise HTTPException(404, f"Model {alias} not loaded")
    return {"id": alias, "object": "model", "owned_by": "k8s-llm-runtime"}


@app.delete("/v1/models/{alias}", status_code=status.HTTP_204_NO_CONTENT)
async def unload_model(alias: str):
    await app.state.op.unload(alias)
    return None
