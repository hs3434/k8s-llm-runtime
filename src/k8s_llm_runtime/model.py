"""High-level model serving router."""
from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from k8s_llm_runtime import _metrics
from k8s_llm_runtime._log import get_logger
from k8s_llm_runtime.errors import (
    ModelAliasError,
    ModelNotFoundError,
    VLLMDeployError,
    VLLMUndeployError,
)
from k8s_llm_runtime.lock import K8sLeaseLock
from k8s_llm_runtime.types import GPUResource
from k8s_llm_runtime.vllm import VLLMInferenceOperator

logger = get_logger(__name__)


# --- OpenAI-compatible Pydantic models ---


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """OpenAI-compatible chat completion request."""

    model: str  # alias, e.g. "qwen-0.5b"
    messages: list[ChatMessage]
    temperature: float = 1.0
    max_tokens: int = 1024
    stream: bool = False  # reserved for v1.1


class ChatResponse(BaseModel):
    """OpenAI-compatible response; allows extra fields from vLLM."""

    model_config = ConfigDict(extra="allow")

    id: str
    object_type: str = Field(default="chat.completion", alias="object")
    created: int
    model: str
    choices: list[dict[str, object]]
    usage: dict[str, object]


# --- Operator ---


class ModelOperator:
    """Routes user requests to deployed vLLM pods, auto-deploying on demand."""

    def __init__(
        self,
        model_aliases: dict[str, str],
        vllm_op: VLLMInferenceOperator,
        namespace: str = "llm-models",
        default_gpu: GPUResource | None = None,
        default_replicas: int = 1,
        idle_timeout_seconds: int = 0,
        deploy_lock_ttl: int = 600,
        deploy_timeout: int = 600,
        request_timeout: float = 300.0,
    ):
        if not model_aliases:
            raise ModelAliasError("model_aliases cannot be empty")
        self.model_aliases = model_aliases
        self.vllm_op = vllm_op
        self.namespace = namespace
        self.default_gpu = default_gpu if default_gpu is not None else GPUResource()
        self.default_replicas = default_replicas
        self.idle_timeout_seconds = idle_timeout_seconds
        self.deploy_lock_ttl = deploy_lock_ttl
        self.deploy_timeout = deploy_timeout
        self.request_timeout = request_timeout
        self._loaded: set[str] = set()
        self._last_used: dict[str, float] = {}

    async def chat(self, req: ChatRequest) -> ChatResponse:
        """Route chat request. Auto-deploys model if not yet ready."""
        hf_model = self.model_aliases.get(req.model)
        if not hf_model:
            raise ModelNotFoundError(
                f"Unknown model alias: {req.model}. "
                f"Available: {list(self.model_aliases.keys())}"
            )

        start = time.time()
        safe_name = self.vllm_op.to_dns_label(req.model)
        lock = K8sLeaseLock(
            key=f"deploy-{safe_name}",
            namespace=self.namespace,
            ttl=self.deploy_lock_ttl,
            acquire_timeout=self.deploy_timeout,
        )

        try:
            async with lock:
                status = self.vllm_op.get_status(safe_name, self.namespace)
                if status.phase != "ready" or status.replicas_ready == 0:
                    logger.info("deploying_model", alias=req.model, hf_model=hf_model)
                    with _metrics.VLLM_DEPLOY_DURATION.labels(
                        model_alias=req.model,
                    ).time():
                        try:
                            status = self.vllm_op.deploy(
                                release_name=req.model,
                                model_name=hf_model,
                                namespace=self.namespace,
                                gpu=self.default_gpu,
                                replicas=self.default_replicas,
                                timeout=self.deploy_timeout,
                            )
                        except VLLMDeployError:
                            _metrics.VLLM_DEPLOY_FAILURES.labels(
                                model_alias=req.model, reason="deploy_error",
                            ).inc()
                            raise
                self._loaded.add(req.model)

            # Forward request (outside lock)
            endpoint = status.endpoint or self.vllm_op.get_endpoint(
                safe_name, self.namespace,
            )
            payload = req.model_dump(exclude_none=True)
            payload["model"] = hf_model  # forward HF model name to vLLM

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{endpoint}/v1/chat/completions",
                    json=payload,
                    timeout=self.request_timeout,
                )
                resp.raise_for_status()
                body = resp.json()

            self._last_used[req.model] = time.time()
            _metrics.INFERENCE_LATENCY.labels(model_alias=req.model).observe(
                time.time() - start,
            )
            _metrics.INFERENCE_REQUESTS.labels(
                model_alias=req.model, status="ok",
            ).inc()
            _metrics.MODELS_LOADED.labels(model_alias=req.model).set(1)
            return ChatResponse.model_validate(body)

        except httpx.HTTPError:
            _metrics.INFERENCE_REQUESTS.labels(
                model_alias=req.model, status="error",
            ).inc()
            raise

    async def list_models(self) -> list[str]:
        return sorted(self._loaded)

    async def unload(self, alias: str) -> None:
        # Don't trust per-replica _loaded — with multiple router pods,
        # any pod might receive the DELETE. Helm is the cluster's source
        # of truth. helm uninstall is idempotent (returns 1 if missing,
        # which we also treat as success).
        safe_name = self.vllm_op.to_dns_label(alias)
        try:
            self.vllm_op.undeploy(safe_name, self.namespace)
        except VLLMUndeployError as exc:
            if "not found" not in str(exc).lower():
                raise
        self._loaded.discard(alias)
        self._last_used.pop(alias, None)
        _metrics.MODELS_LOADED.labels(model_alias=alias).set(0)

    async def discover_existing(self) -> None:
        """Rebuild loaded-set from current helm releases in namespace."""
        env = os.environ.copy()
        kubeconfig = self.vllm_op.kubeconfig
        if kubeconfig:
            env["KUBECONFIG"] = kubeconfig
        result = subprocess.run(  # noqa: ASYNC221
            ["helm", "list", "--namespace", self.namespace, "--output", "json"],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            return
        try:
            releases = json.loads(result.stdout)
        except json.JSONDecodeError:
            return
        # Helm release names are DNS-safe versions of the alias.
        alias_by_safe = {
            self.vllm_op.to_dns_label(a): a for a in self.model_aliases
        }
        for release in releases:
            safe_name = release.get("name")
            alias = alias_by_safe.get(safe_name)
            if alias:
                self._loaded.add(alias)
                _metrics.MODELS_LOADED.labels(model_alias=alias).set(1)
