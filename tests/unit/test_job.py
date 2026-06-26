"""Tests for K8sJobOperator."""

from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client import V1Job

from k8s_llm_runtime.job import K8sJobOperator
from k8s_llm_runtime.types import (
    ContainerSpec,
    GPUResource,
    GPUVendor,
    JobSpec,
    ResourceSpec,
)


@pytest.fixture
def op():
    return K8sJobOperator(namespace="test-ns", kubeconfig="/tmp/fake")


def _mock_job_status(active=0, succeeded=0, failed=0):
    status = MagicMock()
    status.active = active
    status.succeeded = succeeded
    status.failed = failed
    status.start_time = None
    status.completion_time = None
    return status


def test_create_builds_and_submits_job(op):
    fake_batch = MagicMock()
    fake_batch.create_namespaced_job.return_value = V1Job()
    with patch("k8s_llm_runtime.job.batch_api", return_value=fake_batch):
        spec = JobSpec(name="hello", container=ContainerSpec(image="alpine:3.19"))
        returned = op.create(spec)
    assert returned == "hello"
    fake_batch.create_namespaced_job.assert_called_once()
    call = fake_batch.create_namespaced_job.call_args
    assert call.kwargs["namespace"] == "test-ns"
    body = call.kwargs["body"]
    assert body.metadata.name == "hello"
    assert body.metadata.namespace == "test-ns"


def test_create_sets_amd_gpu_resource():
    op = K8sJobOperator(namespace="ns")
    fake_batch = MagicMock()
    fake_batch.create_namespaced_job.return_value = V1Job()
    with patch("k8s_llm_runtime.job.batch_api", return_value=fake_batch):
        spec = JobSpec(
            name="gpu",
            container=ContainerSpec(
                image="rocm/pytorch",
                resources=ResourceSpec(gpu=GPUResource(vendor=GPUVendor.AMD, limit=2)),
            ),
        )
        op.create(spec)
    body = fake_batch.create_namespaced_job.call_args.kwargs["body"]
    container = body.spec.template.spec.containers[0]
    assert "amd.com/gpu" in container.resources.limits
    assert container.resources.limits["amd.com/gpu"] == "2"


def test_create_sets_nvidia_gpu_resource():
    op = K8sJobOperator(namespace="ns")
    fake_batch = MagicMock()
    fake_batch.create_namespaced_job.return_value = V1Job()
    with patch("k8s_llm_runtime.job.batch_api", return_value=fake_batch):
        spec = JobSpec(
            name="gpu",
            container=ContainerSpec(
                image="nvidia/cuda",
                resources=ResourceSpec(gpu=GPUResource(vendor=GPUVendor.NVIDIA, limit=1)),
            ),
        )
        op.create(spec)
    body = fake_batch.create_namespaced_job.call_args.kwargs["body"]
    container = body.spec.template.spec.containers[0]
    assert "nvidia.com/gpu" in container.resources.limits
    assert container.resources.limits["nvidia.com/gpu"] == "1"


def test_create_omits_gpu_resources_when_vendor_none():
    op = K8sJobOperator(namespace="ns")
    fake_batch = MagicMock()
    fake_batch.create_namespaced_job.return_value = V1Job()
    with patch("k8s_llm_runtime.job.batch_api", return_value=fake_batch):
        spec = JobSpec(name="cpu", container=ContainerSpec(image="alpine"))
        op.create(spec)
    body = fake_batch.create_namespaced_job.call_args.kwargs["body"]
    container = body.spec.template.spec.containers[0]
    assert "amd.com/gpu" not in container.resources.limits
    assert "nvidia.com/gpu" not in container.resources.limits


def test_get_status_parses_response(op):
    fake_job = MagicMock()
    fake_job.status = _mock_job_status(active=1)
    fake_batch = MagicMock()
    fake_batch.read_namespaced_job.return_value = fake_job
    with patch("k8s_llm_runtime.job.batch_api", return_value=fake_batch):
        status = op.get_status("hello")
    assert status.name == "hello"
    assert status.phase == "running"
    assert status.active == 1


def test_get_status_succeeded_phase(op):
    fake_job = MagicMock()
    fake_job.status = _mock_job_status(succeeded=1)
    fake_batch = MagicMock()
    fake_batch.read_namespaced_job.return_value = fake_job
    with patch("k8s_llm_runtime.job.batch_api", return_value=fake_batch):
        status = op.get_status("hello")
    assert status.phase == "succeeded"


def test_get_status_failed_phase(op):
    fake_job = MagicMock()
    fake_job.status = _mock_job_status(failed=1)
    fake_batch = MagicMock()
    fake_batch.read_namespaced_job.return_value = fake_job
    with patch("k8s_llm_runtime.job.batch_api", return_value=fake_batch):
        status = op.get_status("hello")
    assert status.phase == "failed"


def test_delete_submits_delete_request(op):
    fake_batch = MagicMock()
    with patch("k8s_llm_runtime.job.batch_api", return_value=fake_batch):
        op.delete("hello")
    fake_batch.delete_namespaced_job.assert_called_once()
    call = fake_batch.delete_namespaced_job.call_args
    assert call.kwargs["name"] == "hello"
    assert call.kwargs["namespace"] == "test-ns"


def test_get_logs_fetches_first_pod_logs(op):
    fake_pod = MagicMock()
    fake_pod.metadata.name = "hello-abc"
    fake_core = MagicMock()
    fake_core.list_namespaced_pod.return_value.items = [fake_pod]
    fake_core.read_namespaced_pod_log.return_value = "line1\nline2\n"
    with patch("k8s_llm_runtime.job.core_api", return_value=fake_core):
        logs = op.get_logs("hello")
    assert logs == "line1\nline2\n"
    assert fake_core.list_namespaced_pod.call_args.kwargs["label_selector"] == "job-name=hello"


def test_wait_for_completion_returns_status(op):
    fake_job = MagicMock()
    fake_job.status = _mock_job_status(succeeded=1)
    fake_batch = MagicMock()
    fake_batch.read_namespaced_job.return_value = fake_job
    with (
        patch("k8s_llm_runtime.job.batch_api", return_value=fake_batch),
        patch("k8s_llm_runtime.job.time.sleep"),
    ):
        status = op.wait_for_completion("hello", timeout=10, poll_interval=1)
    assert status.phase == "succeeded"
