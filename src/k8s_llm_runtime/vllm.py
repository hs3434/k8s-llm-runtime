"""Mid-level vLLM deployment via Helm CLI."""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Literal, Optional

from kubernetes.client.rest import ApiException

from k8s_llm_runtime._client import core_api
from k8s_llm_runtime.errors import (
    VLLMDeployError,
    VLLMDeployTimeoutError,
    VLLMUndeployError,
)
from k8s_llm_runtime.types import GPUResource


@dataclass
class VLLMDeployment:
    """Observed state of a vLLM Helm release."""

    release_name: str
    namespace: str
    model_name: str
    endpoint: str
    phase: Literal["pending", "deploying", "ready", "failed"]
    message: Optional[str] = None
    replicas_ready: int = 0


class VLLMInferenceOperator:
    """Deploy/undeploy/query vLLM via Helm chart."""

    DEFAULT_PORT = 8000

    def __init__(self, chart_path: str = "./charts/llm-inference",
                 kubeconfig: Optional[str] = None):
        self.chart_path = chart_path
        self.kubeconfig = kubeconfig

    def deploy(
        self,
        release_name: str,
        model_name: str,
        namespace: str = "default",
        gpu: Optional[GPUResource] = None,
        replicas: int = 1,
        timeout: int = 600,
    ) -> VLLMDeployment:
        """Helm install/upgrade vLLM with the given model. Idempotent."""
        if gpu is None:
            gpu = GPUResource()
        args = [
            "helm", "upgrade", "--install", release_name, self.chart_path,
            "--namespace", namespace, "--create-namespace",
            "--wait", "--timeout", f"{timeout}s",
            "--set", f"model.name={model_name}",
            "--set", f"gpu.vendor={gpu.vendor.value}",
            "--set", f"gpu.limit={gpu.limit}",
            "--set", f"replicaCount={replicas}",
            "--set", f"fullnameOverride={release_name}",
        ]
        self._run_helm(args)
        return self._wait_for_ready(release_name, namespace, model_name, timeout=timeout)

    def undeploy(self, release_name: str, namespace: str) -> None:
        """Helm uninstall a release."""
        try:
            self._run_helm(["helm", "uninstall", release_name, "--namespace", namespace])
        except VLLMDeployError as exc:
            raise VLLMUndeployError(str(exc)) from exc

    def get_status(self, release_name: str, namespace: str) -> VLLMDeployment:
        """Inspect helm release status and pod readiness."""
        out = self._run_helm([
            "helm", "list", "--namespace", namespace,
            "--filter", f"^{release_name}$",
            "--output", "json",
        ])
        try:
            releases = json.loads(out)
        except json.JSONDecodeError:
            return VLLMDeployment(
                release_name=release_name, namespace=namespace,
                model_name="", endpoint="", phase="pending",
            )
        if not releases:
            return VLLMDeployment(
                release_name=release_name, namespace=namespace,
                model_name="", endpoint="", phase="pending",
            )
        helm_status = releases[0].get("status", "unknown")
        phase: Literal["pending", "deploying", "ready", "failed"] = (
            "ready" if helm_status == "deployed" else "deploying"
        )

        replicas_ready = 0
        try:
            pods = core_api().list_namespaced_pod(
                namespace=namespace,
                label_selector=f"app.kubernetes.io/instance={release_name}",
            )
            for p in pods.items:
                if p.status and p.status.conditions:
                    if any(c.type == "Ready" and c.status == "True"
                           for c in p.status.conditions):
                        replicas_ready += 1
        except ApiException:
            pass

        if phase == "ready" and replicas_ready == 0:
            phase = "deploying"

        return VLLMDeployment(
            release_name=release_name, namespace=namespace,
            model_name="",
            endpoint=self.get_endpoint(release_name, namespace),
            phase=phase,
            replicas_ready=replicas_ready,
        )

    def get_endpoint(self, release_name: str, namespace: str) -> str:
        """Internal cluster DNS endpoint for the vLLM service."""
        return (
            f"http://{release_name}.{namespace}.svc.cluster.local:"
            f"{self.DEFAULT_PORT}"
        )

    # --- Internal helpers ---

    def _run_helm(self, args: list[str]) -> str:
        env = os.environ.copy()
        if self.kubeconfig:
            env["KUBECONFIG"] = self.kubeconfig
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=180, env=env,
        )
        if result.returncode != 0:
            raise VLLMDeployError(
                f"helm command failed (rc={result.returncode}): {result.stderr}"
            )
        return result.stdout

    def _wait_for_ready(
        self,
        release_name: str,
        namespace: str,
        model_name: str,
        timeout: int = 600,
        poll_interval: int = 5,
    ) -> VLLMDeployment:
        start = time.time()
        while time.time() - start < timeout:
            status = self.get_status(release_name, namespace)
            if status.phase == "ready" and status.replicas_ready > 0:
                return VLLMDeployment(
                    release_name=release_name, namespace=namespace,
                    model_name=model_name,
                    endpoint=status.endpoint,
                    phase="ready",
                    replicas_ready=status.replicas_ready,
                )
            time.sleep(poll_interval)
        raise VLLMDeployTimeoutError(
            f"vLLM {release_name} did not become ready within {timeout}s"
        )
