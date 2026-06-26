"""Tests for Pydantic data models."""

import pytest
from pydantic import ValidationError

from k8s_llm_runtime.types import (
    ContainerSpec,
    GPUResource,
    GPUVendor,
    JobSpec,
    JobStatus,
    ResourceSpec,
)


def test_gpu_vendor_enum_values():
    assert GPUVendor.NONE == "none"
    assert GPUVendor.NVIDIA == "nvidia"
    assert GPUVendor.AMD == "amd"


def test_gpu_resource_defaults():
    g = GPUResource()
    assert g.vendor == GPUVendor.NONE
    assert g.limit == 1


def test_resource_spec_defaults():
    r = ResourceSpec()
    assert r.cpu_request == "1"
    assert r.gpu.limit == 1
    assert r.gpu.vendor == GPUVendor.NONE


def test_container_spec_requires_image():
    with pytest.raises(ValidationError):
        ContainerSpec()


def test_container_spec_minimal():
    c = ContainerSpec(image="nginx:latest")
    assert c.image == "nginx:latest"
    assert c.command is None
    assert c.env == {}


def test_job_spec_defaults():
    spec = JobSpec(name="test-job", container=ContainerSpec(image="alpine"))
    assert spec.namespace == "default"
    assert spec.ttl_seconds_after_finished == 3600
    assert spec.backoff_limit == 3
    assert spec.restart_policy == "Never"


def test_job_spec_validates_restart_policy():
    with pytest.raises(ValidationError):
        JobSpec(
            name="x",
            container=ContainerSpec(image="alpine"),
            restart_policy="Always",
        )


def test_job_status_phase_enum():
    s = JobStatus(name="x", phase="running")
    assert s.active == 0
    assert s.phase == "running"


def test_job_status_rejects_invalid_phase():
    with pytest.raises(ValidationError):
        JobStatus(name="x", phase="unknown")
