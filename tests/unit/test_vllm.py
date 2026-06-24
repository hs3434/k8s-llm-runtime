"""Tests for VLLMInferenceOperator."""
from unittest.mock import MagicMock, patch

import pytest

from k8s_llm_runtime.types import GPUResource, GPUVendor
from k8s_llm_runtime.vllm import VLLMDeployment, VLLMInferenceOperator


@pytest.fixture
def op(tmp_path):
    chart = tmp_path / "fake-chart"
    chart.mkdir()
    (chart / "Chart.yaml").write_text("apiVersion: v2\nname: llm-inference\nversion: 0.1.0\n")
    return VLLMInferenceOperator(chart_path=str(chart), kubeconfig="/tmp/fake")


def _helm_ok(stdout: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    m.stderr = ""
    return m


def _helm_fail(stderr: str = "release already exists") -> MagicMock:
    m = MagicMock()
    m.returncode = 1
    m.stdout = ""
    m.stderr = stderr
    return m


def test_deploy_renders_and_installs(op):
    with patch("subprocess.run") as mock_run, \
         patch.object(op, "_wait_for_ready", return_value=VLLMDeployment(
             release_name="qwen", namespace="llm-models",
             model_name="Qwen/...", endpoint="http://qwen.llm-models:8000",
             phase="ready", replicas_ready=1,
         )):
        mock_run.return_value = _helm_ok()
        result = op.deploy(
            "qwen", "Qwen/Qwen2.5-0.5B-Instruct", "llm-models",
            gpu=GPUResource(vendor=GPUVendor.AMD, limit=1),
        )
    assert result.release_name == "qwen"
    assert result.phase == "ready"
    cmd = mock_run.call_args_list[0].args[0]
    assert cmd[:4] == ["helm", "upgrade", "--install", "qwen"]


def test_deploy_passes_gpu_vendor_to_values(op):
    with patch("subprocess.run") as mock_run, \
         patch.object(op, "_wait_for_ready", return_value=VLLMDeployment(
             release_name="x", namespace="ns", model_name="m",
             endpoint="e", phase="ready", replicas_ready=1,
         )):
        mock_run.return_value = _helm_ok()
        op.deploy("x", "Qwen/0.5B", "ns", gpu=GPUResource(vendor=GPUVendor.AMD, limit=2))
    cmd = mock_run.call_args_list[0].args[0]
    assert any("gpu.vendor=amd" in a for a in cmd)
    assert any("gpu.limit=2" in a for a in cmd)


def test_deploy_propagates_helm_error(op):
    from k8s_llm_runtime.errors import VLLMDeployError
    with patch("subprocess.run", return_value=_helm_fail("bad chart")), \
         patch.object(op, "_wait_for_ready"):
        with pytest.raises(VLLMDeployError) as exc:
            op.deploy("x", "Qwen/0.5B", "ns")
    assert "bad chart" in str(exc.value)


def test_undeploy_calls_helm_uninstall(op):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = _helm_ok()
        op.undeploy("qwen", "llm-models")
    cmd = mock_run.call_args.args[0]
    assert cmd[:3] == ["helm", "uninstall", "qwen"]
    assert "llm-models" in cmd


def test_undeploy_propagates_error(op):
    from k8s_llm_runtime.errors import VLLMUndeployError
    with patch("subprocess.run", return_value=_helm_fail("release not found")):
        with pytest.raises(VLLMUndeployError):
            op.undeploy("qwen", "llm-models")


def test_get_endpoint_builds_internal_url(op):
    assert op.get_endpoint("qwen-7b", "llm-models") == \
        "http://qwen-7b.llm-models.svc.cluster.local:8000"


def test_run_helm_sets_kubeconfig_env(op):
    with patch("subprocess.run", return_value=_helm_ok()) as mock_run:
        op._run_helm(["version"])
    assert mock_run.call_args.kwargs["env"].get("KUBECONFIG") == "/tmp/fake"


def test_run_helm_returns_stdout(op):
    with patch("subprocess.run", return_value=_helm_ok("release-list-output")):
        out = op._run_helm(["list"])
    assert out == "release-list-output"


def test_get_status_pending_when_no_release(op):
    with patch("subprocess.run", return_value=_helm_ok("[]")):
        status = op.get_status("missing", "llm-models")
    assert status.phase == "pending"
    assert status.replicas_ready == 0
