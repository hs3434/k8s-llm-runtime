"""Distributed lock backed by Kubernetes Lease objects."""
from __future__ import annotations

import asyncio
import os
import socket
import time
import uuid
from datetime import UTC, datetime
from typing import Optional

from kubernetes import client
from kubernetes.client.rest import ApiException

from k8s_llm_runtime import _client
from k8s_llm_runtime.errors import LockAcquireTimeoutError


def _hostname() -> str:
    return os.environ.get("POD_NAME") or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"


class K8sLeaseLock:
    """Async distributed lock via coordination.k8s.io/v1 Lease."""

    def __init__(
        self,
        key: str,
        namespace: str = "default",
        ttl: int = 60,
        acquire_timeout: float = 600,
        poll_interval: float = 2.0,
    ):
        self.key = key
        self.namespace = namespace
        self.ttl = ttl
        self.acquire_timeout = acquire_timeout
        self.poll_interval = poll_interval
        self._holder = _hostname()
        self._held = False

    async def __aenter__(self) -> K8sLeaseLock:
        await self.acquire()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.release()

    async def acquire(self) -> None:
        deadline = time.time() + self.acquire_timeout
        while True:
            if self._try_acquire_once():
                self._held = True
                return
            if time.time() >= deadline:
                raise LockAcquireTimeoutError(
                    f"Could not acquire lease {self.key} in {self.acquire_timeout}s"
                )
            await asyncio.sleep(self.poll_interval)

    async def release(self) -> None:
        if not self._held:
            return
        try:
            _client.coordination_api().delete_namespaced_lease(
                name=self.key, namespace=self.namespace,
            )
        except ApiException as exc:
            if exc.status != 404:
                raise
        finally:
            self._held = False

    def _try_acquire_once(self) -> bool:
        api = _client.coordination_api()
        try:
            existing = api.read_namespaced_lease(
                name=self.key, namespace=self.namespace,
            )
            holder = existing.spec.holder_identity
            acquired_at: Optional[datetime] = existing.spec.acquire_time
            if holder and acquired_at is not None and self._is_expired(acquired_at):
                # Stale lease: delete + recreate (replace requires resourceVersion)
                try:
                    api.delete_namespaced_lease(
                        name=self.key, namespace=self.namespace,
                    )
                except ApiException as exc:
                    if exc.status != 404:
                        raise
                api.create_namespaced_lease(
                    namespace=self.namespace,
                    body=self._build_lease(),
                )
                return True
            return False
        except ApiException as exc:
            if exc.status == 404:
                api.create_namespaced_lease(
                    namespace=self.namespace,
                    body=self._build_lease(),
                )
                return True
            raise

    def _is_expired(self, acquired_at: datetime) -> bool:
        elapsed = time.time() - acquired_at.timestamp()
        return elapsed > self.ttl

    def _build_lease(self) -> client.V1Lease:
        now = datetime.now(UTC)
        return client.V1Lease(
            api_version="coordination.k8s.io/v1",
            kind="Lease",
            metadata=client.V1ObjectMeta(name=self.key, namespace=self.namespace),
            spec=client.V1LeaseSpec(
                holder_identity=self._holder,
                acquire_time=now,
                renew_time=now,
                lease_duration_seconds=self.ttl,
            ),
        )
