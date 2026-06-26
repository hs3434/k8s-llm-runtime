"""Integration test fixtures (kind cluster)."""

import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
KUBECONFIG = REPO_ROOT / "kubeconfig"


@pytest.fixture(scope="session")
def kubeconfig():
    return str(KUBECONFIG)


@pytest.fixture(scope="session", autouse=True)
def kind_cluster():
    """Bring up kind cluster for the whole test session."""
    if not KUBECONFIG.exists():
        subprocess.run(
            ["make", "cluster-up", "CLUSTER=kind"],
            cwd=REPO_ROOT,
            check=True,
            env={**os.environ},
        )
    os.environ["KUBECONFIG"] = str(KUBECONFIG)
    yield
    # Don't teardown by default; CI does it separately.
    # To force teardown: subprocess.run(["make", "cluster-down", "CLUSTER=kind"])


@pytest.fixture(scope="session")
def router_port_forward(kind_cluster, kubeconfig):
    """Install llm-router chart + port-forward to localhost."""
    # Router image bundles charts/llm-inference at /app/charts/llm-inference,
    # so no manual ConfigMap is needed.

    # Install llm-router chart
    subprocess.run(
        [
            "helm",
            "install",
            "llm-router",
            str(REPO_ROOT / "charts" / "llm-router"),
            "--namespace",
            "llm-system",
            "--create-namespace",
            "--kubeconfig",
            kubeconfig,
            "--wait",
            "--timeout",
            "180s",
        ],
        check=True,
    )

    # Wait for ready
    subprocess.run(
        [
            "kubectl",
            "wait",
            "--namespace",
            "llm-system",
            "--for=condition=ready",
            "pod",
            "--selector=app.kubernetes.io/name=llm-router",
            "--timeout",
            "120s",
            "--kubeconfig",
            kubeconfig,
        ],
        check=True,
    )

    # Port-forward
    proc = subprocess.Popen(
        [
            "kubectl",
            "--namespace",
            "llm-system",
            "port-forward",
            "svc/llm-router",
            "18080:8080",
            "--kubeconfig",
            kubeconfig,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        try:
            r = httpx.get("http://localhost:18080/healthz", timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(1)
    yield "http://localhost:18080"
    proc.terminate()
    proc.wait(timeout=5)
    subprocess.run(
        [
            "helm",
            "uninstall",
            "llm-router",
            "--namespace",
            "llm-system",
            "--kubeconfig",
            kubeconfig,
        ],
        check=False,
    )
