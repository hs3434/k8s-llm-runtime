"""Tests for llm-inference chart rendering."""


def test_default_values_render(helm_template):
    manifest = helm_template()
    assert "kind: Deployment" in manifest
    assert "kind: Service" in manifest
    assert "kind: ServiceAccount" in manifest


def test_ingress_disabled_by_default(helm_template):
    assert "kind: Ingress" not in helm_template()


def test_hpa_disabled_by_default(helm_template):
    assert "kind: HorizontalPodAutoscaler" not in helm_template()


def test_servicemonitor_disabled_by_default(helm_template):
    assert "kind: ServiceMonitor" not in helm_template()


def test_amd_gpu_resource_in_limits(helm_template):
    manifest = helm_template(["gpu.vendor=amd", "gpu.limit=2"])
    assert 'amd.com/gpu: "2"' in manifest
    assert "nvidia.com/gpu" not in manifest


def test_nvidia_gpu_resource_in_limits(helm_template):
    manifest = helm_template(["gpu.vendor=nvidia", "gpu.limit=1"])
    assert 'nvidia.com/gpu: "1"' in manifest
    assert "amd.com/gpu" not in manifest


def test_cpu_mode_has_no_gpu_resources(helm_template):
    manifest = helm_template(["gpu.vendor=none"])
    assert "amd.com/gpu" not in manifest
    assert "nvidia.com/gpu" not in manifest


def test_ingress_enabled_when_set(helm_template):
    manifest = helm_template(["ingress.enabled=true", "ingress.host=llm.example.com"])
    assert "kind: Ingress" in manifest
    assert "llm.example.com" in manifest


def test_hpa_enabled_when_set(helm_template):
    manifest = helm_template(["autoscaling.enabled=true", "autoscaling.maxReplicas=5"])
    assert "kind: HorizontalPodAutoscaler" in manifest


def test_image_repository_and_tag(helm_template):
    manifest = helm_template(["image.repository=my/vllm", "image.tag=v0.5"])
    assert "my/vllm:v0.5" in manifest


def test_model_name_passed_as_arg(helm_template):
    manifest = helm_template(["model.name=Qwen/Qwen2.5-7B-Instruct"])
    assert "Qwen/Qwen2.5-7B-Instruct" in manifest


def test_hf_token_secret_injected(helm_template):
    manifest = helm_template(["model.hfTokenSecret=hf-secret"])
    assert "secretKeyRef:" in manifest
    assert "name: hf-secret" in manifest
    assert "key: token" in manifest


def test_node_selector_propagates(helm_template):
    manifest = helm_template(['nodeSelector."amd\\.com/gpu\\.product"=MI300X'])
    assert "amd.com/gpu.product" in manifest
    assert "MI300X" in manifest


def test_hf_endpoint_default_uses_mirror(helm_template):
    manifest = helm_template()
    assert "HF_ENDPOINT" in manifest
    assert "hf-mirror.com" in manifest


def test_hf_endpoint_override(helm_template):
    manifest = helm_template(["model.hfEndpoint=https://huggingface.co"])
    assert '"https://huggingface.co"' in manifest


def test_hf_cache_path_default_off(helm_template):
    manifest = helm_template()
    assert "HF_HUB_CACHE" not in manifest
    assert "hostPath" not in manifest


def test_hf_cache_path_mounts_hostpath_and_env(helm_template):
    manifest = helm_template(["model.hfCachePath=/srv/models"])
    assert "HF_HUB_CACHE" in manifest
    assert '"/srv/models"' in manifest
    assert "hostPath:" in manifest
    assert 'path: "/srv/models"' in manifest
    assert "hostPath:" in manifest
