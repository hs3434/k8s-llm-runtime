"""Pydantic models shared across the library."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class GPUVendor(str, Enum):
    """GPU vendor selector for resource and node affinity configuration."""

    NONE = "none"
    NVIDIA = "nvidia"
    AMD = "amd"


class GPUResource(BaseModel):
    """GPU resource request."""

    vendor: GPUVendor = GPUVendor.NONE
    limit: int = Field(default=1, ge=1, le=8)


class ResourceSpec(BaseModel):
    """CPU, memory, and GPU resource requests/limits."""

    cpu_request: str = "1"
    cpu_limit: str = "2"
    memory_request: str = "1Gi"
    memory_limit: str = "2Gi"
    gpu: GPUResource = GPUResource()


class ContainerSpec(BaseModel):
    """Single container definition for a Job."""

    image: str
    command: Optional[list[str]] = None
    args: Optional[list[str]] = None
    env: dict[str, str] = Field(default_factory=dict)
    resources: ResourceSpec = ResourceSpec()
    ports: list[int] = Field(default_factory=list)


class JobSpec(BaseModel):
    """Kubernetes Job specification."""

    name: str
    namespace: str = "default"
    container: ContainerSpec
    service_account: Optional[str] = None
    ttl_seconds_after_finished: int = Field(default=3600, ge=0)
    backoff_limit: int = Field(default=3, ge=0)
    restart_policy: Literal["Never", "OnFailure"] = "Never"


class JobStatus(BaseModel):
    """Observed status of a Kubernetes Job."""

    name: str
    phase: Literal["pending", "running", "succeeded", "failed"]
    active: int = 0
    succeeded: int = 0
    failed: int = 0
    start_time: Optional[datetime] = None
    completion_time: Optional[datetime] = None