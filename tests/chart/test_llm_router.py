"""Tests for llm-router chart rendering."""


def test_default_values_render(helm_template):
    manifest = helm_template(chart="router")
    assert "kind: Deployment" in manifest
    assert "kind: Service" in manifest
    assert "kind: ServiceAccount" in manifest
    assert "kind: Role" in manifest
    assert "kind: RoleBinding" in manifest
    assert "kind: ConfigMap" in manifest


def test_router_has_metrics_endpoint(helm_template):
    manifest = helm_template(chart="router")
    assert "/healthz" in manifest
    assert "/readyz" in manifest


def test_router_uses_in_cluster_service_account(helm_template):
    manifest = helm_template(chart="router")
    assert "serviceAccountName:" in manifest
    assert "POD_NAME" in manifest


def test_router_rbac_includes_leases(helm_template):
    manifest = helm_template(chart="router")
    assert "coordination.k8s.io" in manifest
    assert "leases" in manifest


def test_router_configmap_contains_aliases(helm_template):
    manifest = helm_template(chart="router")
    assert "aliases:" in manifest
    assert "qwen-7b" in manifest
    assert "Qwen/Qwen2.5-7B-Instruct" in manifest


def test_hpa_enabled_when_set(helm_template):
    manifest = helm_template(
        chart="router",
        set_values=["autoscaling.enabled=true", "autoscaling.maxReplicas=10"],
    )
    assert "kind: HorizontalPodAutoscaler" in manifest


def test_ingress_disabled_by_default(helm_template):
    manifest = helm_template(chart="router")
    assert "kind: Ingress" not in manifest


def test_replicas_configurable(helm_template):
    manifest = helm_template(chart="router", set_values=["replicaCount=5"])
    assert "replicas: 5" in manifest
