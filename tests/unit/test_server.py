"""Tests for the FastAPI Router server."""
import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from k8s_llm_runtime.errors import ModelNotFoundError, VLLMDeployTimeoutError
from k8s_llm_runtime.model import ChatResponse


@pytest.fixture
def mock_op():
    op = MagicMock()
    op.chat = AsyncMock(return_value=ChatResponse(
        id="chatcmpl-1",
        object_type="chat.completion",
        created=1,
        model="qwen-0.5b",
        choices=[{"message": {"role": "assistant", "content": "hello"}}],
        usage={"total_tokens": 1},
    ))
    op.list_models = AsyncMock(return_value=["qwen-0.5b"])
    op.unload = AsyncMock()
    return op


@pytest.fixture
def client(mock_op):
    with patch("examples.vllm_qwen.server.load_model_aliases",
               return_value={"qwen-0.5b": "Qwen/Qwen2.5-0.5B-Instruct"}), \
         patch("k8s_llm_runtime.ModelOperator") as mock_cls:
        mock_cls.return_value = mock_op
        import examples.vllm_qwen.server as srv
        importlib.reload(srv)
        srv.app.state.op = mock_op
        with TestClient(srv.app) as c:
            yield c


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "LLM Router" in r.json()["message"]


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_chat_completions(client, mock_op):
    r = client.post("/v1/chat/completions", json={
        "model": "qwen-0.5b",
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 200
    assert r.json()["model"] == "qwen-0.5b"
    mock_op.chat.assert_called_once()


def test_chat_unknown_model_returns_404(client, mock_op):
    mock_op.chat.side_effect = ModelNotFoundError("foo")
    r = client.post("/v1/chat/completions", json={
        "model": "foo",
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 404
    assert "foo" in r.text


def test_chat_deploy_timeout_returns_503(client, mock_op):
    mock_op.chat.side_effect = VLLMDeployTimeoutError("timeout")
    r = client.post("/v1/chat/completions", json={
        "model": "qwen-0.5b",
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 503


def test_list_models(client):
    r = client.get("/v1/models")
    assert r.status_code == 200
    assert r.json()["data"][0]["id"] == "qwen-0.5b"


def test_unload_model(client, mock_op):
    r = client.delete("/v1/models/qwen-0.5b")
    assert r.status_code == 204
    mock_op.unload.assert_called_once_with("qwen-0.5b")


def test_request_id_header_echoed(client):
    r = client.post(
        "/v1/chat/completions",
        json={"model": "qwen-0.5b",
              "messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Request-ID": "test-rid-123"},
    )
    assert r.headers.get("X-Request-ID") == "test-rid-123"


def test_request_id_generated_when_absent(client):
    r = client.post(
        "/v1/chat/completions",
        json={"model": "qwen-0.5b",
              "messages": [{"role": "user", "content": "hi"}]},
    )
    rid = r.headers.get("X-Request-ID")
    assert rid is not None
    assert len(rid) > 10
