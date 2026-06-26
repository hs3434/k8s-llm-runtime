"""End-to-end tests against kind cluster.

Skipped unless KUBECONFIG points to a live cluster.
"""

import os

import httpx
import pytest


def _skip_unless_cluster():
    return not os.environ.get("KUBECONFIG") or not os.path.exists(os.environ["KUBECONFIG"])


@pytest.mark.skipif(
    _skip_unless_cluster,
    reason="KUBECONFIG not set or cluster not running",
)
def test_healthz(router_port_forward):
    r = httpx.get(f"{router_port_forward}/healthz", timeout=5)
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


@pytest.mark.skipif(
    _skip_unless_cluster,
    reason="KUBECONFIG not set or cluster not running",
)
def test_readyz(router_port_forward):
    r = httpx.get(f"{router_port_forward}/readyz", timeout=5)
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


@pytest.mark.skipif(
    _skip_unless_cluster,
    reason="KUBECONFIG not set or cluster not running",
)
@pytest.mark.slow
def test_first_chat_auto_deploys_model(router_port_forward):
    """End-to-end: first request triggers vLLM deploy."""
    r = httpx.post(
        f"{router_port_forward}/v1/chat/completions",
        json={
            "model": "qwen-0.5b",
            "messages": [{"role": "user", "content": "hi"}],
        },
        timeout=300,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "qwen-0.5b"
    assert len(body["choices"]) > 0
