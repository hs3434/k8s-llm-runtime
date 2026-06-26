"""Tests for ModelOperator."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from k8s_llm_runtime.errors import (
    ModelAliasError,
    ModelNotFoundError,
    VLLMDeployError,
    VLLMDeployTimeoutError,
    VLLMUndeployError,
)
from k8s_llm_runtime.model import (
    ChatMessage,
    ChatRequest,
    ModelOperator,
)
from k8s_llm_runtime.types import GPUResource, GPUVendor
from k8s_llm_runtime.vllm import VLLMDeployment, VLLMInferenceOperator


@pytest.fixture
def mock_vllm_op():
    op = MagicMock()
    op.get_endpoint.return_value = "http://qwen.llm-models.svc.cluster.local:8000"
    op.to_dns_label = VLLMInferenceOperator.to_dns_label
    op.get_status.return_value = VLLMDeployment(
        release_name="qwen",
        namespace="llm-models",
        model_name="",
        endpoint="http://qwen.llm-models.svc.cluster.local:8000",
        phase="ready",
        replicas_ready=1,
    )
    op.deploy = MagicMock(
        return_value=VLLMDeployment(
            release_name="qwen",
            namespace="llm-models",
            model_name="Qwen/Qwen2.5-0.5B-Instruct",
            endpoint="http://qwen.llm-models.svc.cluster.local:8000",
            phase="ready",
            replicas_ready=1,
        )
    )
    return op


@pytest.fixture
def op(mock_vllm_op):
    return ModelOperator(
        model_aliases={"qwen-0.5b": "Qwen/Qwen2.5-0.5B-Instruct"},
        vllm_op=mock_vllm_op,
        namespace="llm-models",
        default_gpu=GPUResource(vendor=GPUVendor.AMD, limit=1),
    )


def _mock_response(payload, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error",
            request=MagicMock(),
            response=resp,
        )
    return resp


def _make_lock_patch():
    """Create a patched K8sLeaseLock that works as an async context manager."""
    mock_lock = AsyncMock()
    mock_lock.__aenter__ = AsyncMock(return_value=mock_lock)
    mock_lock.__aexit__ = AsyncMock(return_value=None)
    return patch(
        "k8s_llm_runtime.model.K8sLeaseLock",
        return_value=mock_lock,
    )


def test_alias_required():
    with pytest.raises(ModelAliasError):
        ModelOperator(model_aliases={}, vllm_op=MagicMock())


def test_chat_unknown_alias_raises(op):
    req = ChatRequest(
        model="unknown-llm",
        messages=[ChatMessage(role="user", content="hi")],
    )
    with pytest.raises(ModelNotFoundError):
        asyncio.run(op.chat(req))


def test_chat_routes_to_ready_deployment(op, mock_vllm_op):
    req = ChatRequest(
        model="qwen-0.5b",
        messages=[ChatMessage(role="user", content="hi")],
    )
    payload = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "qwen-0.5b",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    with (
        _make_lock_patch(),
        patch("k8s_llm_runtime.model.httpx.AsyncClient") as mock_client_cls,
    ):
        client_instance = AsyncMock()
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=None)
        client_instance.post = AsyncMock(return_value=_mock_response(payload))
        mock_client_cls.return_value = client_instance

        resp = asyncio.run(op.chat(req))

    mock_vllm_op.deploy.assert_not_called()
    assert resp.model == "qwen-0.5b"
    assert resp.choices[0]["message"]["content"] == "hello"


def test_chat_deploys_when_not_ready(op, mock_vllm_op):
    mock_vllm_op.get_status.return_value = VLLMDeployment(
        release_name="qwen",
        namespace="llm-models",
        model_name="",
        endpoint="http://qwen.llm-models.svc.cluster.local:8000",
        phase="pending",
        replicas_ready=0,
    )
    req = ChatRequest(
        model="qwen-0.5b",
        messages=[ChatMessage(role="user", content="hi")],
    )
    payload = {
        "id": "x",
        "object": "chat.completion",
        "created": 1,
        "model": "qwen-0.5b",
        "choices": [],
        "usage": {},
    }
    with (
        _make_lock_patch(),
        patch("k8s_llm_runtime.model.httpx.AsyncClient") as mock_client_cls,
    ):
        client_instance = AsyncMock()
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=None)
        client_instance.post = AsyncMock(return_value=_mock_response(payload))
        mock_client_cls.return_value = client_instance

        asyncio.run(op.chat(req))

    mock_vllm_op.deploy.assert_called_once()


def test_chat_propagates_deploy_error(op, mock_vllm_op):
    mock_vllm_op.get_status.return_value = VLLMDeployment(
        release_name="qwen",
        namespace="llm-models",
        model_name="",
        endpoint="",
        phase="failed",
        replicas_ready=0,
    )
    mock_vllm_op.deploy.side_effect = VLLMDeployError("boom")
    req = ChatRequest(
        model="qwen-0.5b",
        messages=[ChatMessage(role="user", content="hi")],
    )
    with _make_lock_patch():
        with pytest.raises(VLLMDeployError):
            asyncio.run(op.chat(req))


def test_chat_raises_deploy_timeout(op, mock_vllm_op):
    mock_vllm_op.get_status.return_value = VLLMDeployment(
        release_name="qwen",
        namespace="llm-models",
        model_name="",
        endpoint="",
        phase="pending",
        replicas_ready=0,
    )
    mock_vllm_op.deploy.side_effect = VLLMDeployTimeoutError("timeout")
    req = ChatRequest(
        model="qwen-0.5b",
        messages=[ChatMessage(role="user", content="hi")],
    )
    with _make_lock_patch():
        with pytest.raises(VLLMDeployTimeoutError):
            asyncio.run(op.chat(req))


def test_list_models_returns_loaded(op):
    op._loaded.add("qwen-0.5b")
    assert asyncio.run(op.list_models()) == ["qwen-0.5b"]


def test_unload_calls_undeploy(op, mock_vllm_op):
    op._loaded.add("qwen-0.5b")
    asyncio.run(op.unload("qwen-0.5b"))
    mock_vllm_op.undeploy.assert_called_once_with("qwen-0-5b", "llm-models")
    assert "qwen-0.5b" not in op._loaded


def test_unload_silent_when_not_loaded(op, mock_vllm_op):
    # unload is now idempotent: it always calls helm uninstall (cluster
    # is the source of truth, not per-replica _loaded). helm uninstall
    # of a non-existent release returns "not found" which we swallow.
    mock_vllm_op.undeploy.side_effect = VLLMUndeployError("release not found")
    asyncio.run(op.unload("not-loaded"))
    mock_vllm_op.undeploy.assert_called_once_with("not-loaded", "llm-models")
