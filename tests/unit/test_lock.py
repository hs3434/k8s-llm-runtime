"""Tests for K8sLeaseLock."""
import asyncio
import itertools
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.rest import ApiException

from k8s_llm_runtime.errors import LockAcquireTimeoutError
from k8s_llm_runtime.lock import K8sLeaseLock


@pytest.fixture
def mock_coord_api():
    api = MagicMock()
    api.create_namespaced_lease = MagicMock()
    api.read_namespaced_lease = MagicMock()
    api.replace_namespaced_lease = MagicMock()
    api.delete_namespaced_lease = MagicMock()
    return api


def _make_spec(holder="other-pod", acquired_at=0):
    spec = MagicMock()
    spec.holder_identity = holder
    spec.acquire_time = MagicMock()
    spec.acquire_time.timestamp = MagicMock(return_value=acquired_at)
    spec.renew_time = MagicMock()
    return spec


def test_acquire_succeeds_when_lease_free(mock_coord_api):
    mock_coord_api.read_namespaced_lease.side_effect = ApiException(status=404, reason="not found")
    mock_coord_api.create_namespaced_lease.return_value = None
    lock = K8sLeaseLock(key="deploy-qwen", namespace="ns", ttl=60)

    with patch(
        "k8s_llm_runtime.lock._client.coordination_api",
        return_value=mock_coord_api,
    ):
        asyncio.run(lock.acquire())

    mock_coord_api.create_namespaced_lease.assert_called_once()


def test_acquire_replaces_expired_lease(mock_coord_api):
    mock_lease = MagicMock()
    mock_lease.spec = _make_spec(holder="other-pod", acquired_at=0)
    mock_coord_api.read_namespaced_lease.return_value = mock_lease
    mock_coord_api.delete_namespaced_lease.return_value = None
    mock_coord_api.create_namespaced_lease.return_value = None
    lock = K8sLeaseLock(key="deploy-qwen", namespace="ns", ttl=60)

    with (
        patch(
            "k8s_llm_runtime.lock._client.coordination_api",
            return_value=mock_coord_api,
        ),
        patch("k8s_llm_runtime.lock.time.time", return_value=1000),
    ):
        asyncio.run(lock.acquire())

    # Stale lease is replaced by delete + create (replace requires resourceVersion)
    mock_coord_api.delete_namespaced_lease.assert_called_once()
    mock_coord_api.create_namespaced_lease.assert_called_once()


def test_acquire_raises_when_held_by_other(mock_coord_api):
    mock_lease = MagicMock()
    mock_lease.spec = _make_spec(holder="other-pod", acquired_at=0)
    mock_coord_api.read_namespaced_lease.return_value = mock_lease
    lock = K8sLeaseLock(
        key="deploy-qwen",
        namespace="ns",
        ttl=60,
        acquire_timeout=0.1,
        poll_interval=0.05,
    )

    with (
        patch(
            "k8s_llm_runtime.lock._client.coordination_api",
            return_value=mock_coord_api,
        ),
        patch("k8s_llm_runtime.lock.time.time", side_effect=itertools.count().__next__),
    ):
        with pytest.raises(LockAcquireTimeoutError):
            asyncio.run(lock.acquire())


def test_release_deletes_lease(mock_coord_api):
    lock = K8sLeaseLock(key="deploy-qwen", namespace="ns", ttl=60)
    lock._held = True

    with patch(
        "k8s_llm_runtime.lock._client.coordination_api",
        return_value=mock_coord_api,
    ):
        asyncio.run(lock.release())

    mock_coord_api.delete_namespaced_lease.assert_called_once()


def test_release_silently_ignores_404(mock_coord_api):
    mock_coord_api.delete_namespaced_lease.side_effect = ApiException(status=404, reason="gone")
    lock = K8sLeaseLock(key="k", namespace="ns", ttl=60)
    lock._held = True

    with patch(
        "k8s_llm_runtime.lock._client.coordination_api",
        return_value=mock_coord_api,
    ):
        asyncio.run(lock.release())


def test_release_noop_when_not_held(mock_coord_api):
    lock = K8sLeaseLock(key="k", namespace="ns", ttl=60)
    with patch(
        "k8s_llm_runtime.lock._client.coordination_api",
        return_value=mock_coord_api,
    ):
        asyncio.run(lock.release())
    mock_coord_api.delete_namespaced_lease.assert_not_called()


@pytest.mark.asyncio
async def test_async_context_manager(mock_coord_api):
    mock_coord_api.read_namespaced_lease.side_effect = ApiException(status=404, reason="nf")
    mock_coord_api.create_namespaced_lease.return_value = None
    mock_coord_api.delete_namespaced_lease.return_value = None
    lock = K8sLeaseLock(key="k", namespace="ns", ttl=60)

    with patch(
        "k8s_llm_runtime.lock._client.coordination_api",
        return_value=mock_coord_api,
    ):
        async with lock:
            mock_coord_api.create_namespaced_lease.assert_called_once()
        mock_coord_api.delete_namespaced_lease.assert_called_once()
