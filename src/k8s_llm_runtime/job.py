"""Low-level K8s Job lifecycle management."""

from __future__ import annotations

import time
from typing import Literal, Optional, cast

from kubernetes.client import (
    V1Container,
    V1EnvVar,
    V1Job,
    V1JobSpec,
    V1ObjectMeta,
    V1PodSpec,
    V1PodTemplateSpec,
    V1ResourceRequirements,
)

from k8s_llm_runtime import _client
from k8s_llm_runtime._client import batch_api, core_api
from k8s_llm_runtime._retry import k8s_retry
from k8s_llm_runtime.errors import (
    JobCreationError,
    JobLogRetrievalError,
    JobTimeoutError,
)
from k8s_llm_runtime.types import ContainerSpec, GPUVendor, JobSpec, JobStatus


class K8sJobOperator:
    """Manages Kubernetes Jobs: create, query, wait, delete."""

    def __init__(self, namespace: str = "default", kubeconfig: Optional[str] = None):
        self.namespace = namespace
        self.kubeconfig = kubeconfig
        if kubeconfig is not None:
            try:
                _client.load_config(kubeconfig)
            except Exception:
                pass

    @k8s_retry
    def create(self, spec: JobSpec) -> str:
        try:
            job = self._build_job(spec)
            batch_api().create_namespaced_job(
                namespace=self.namespace,
                body=job,
            )
            return spec.name
        except Exception as exc:
            raise JobCreationError(f"Failed to create job {spec.name}: {exc}") from exc

    @k8s_retry
    def get_status(self, job_name: str) -> JobStatus:
        job = batch_api().read_namespaced_job(
            name=job_name,
            namespace=self.namespace,
        )
        s = job.status
        active = s.active or 0
        succeeded = s.succeeded or 0
        failed = s.failed or 0
        phase = self._infer_phase(active=active, succeeded=succeeded, failed=failed)
        return JobStatus(
            name=job_name,
            phase=phase,
            active=active,
            succeeded=succeeded,
            failed=failed,
            start_time=s.start_time,
            completion_time=s.completion_time,
        )

    @k8s_retry
    def get_logs(self, job_name: str, tail_lines: int = 200) -> str:
        try:
            pods = core_api().list_namespaced_pod(
                namespace=self.namespace,
                label_selector=f"job-name={job_name}",
            )
            if not pods.items:
                return ""
            pod_name = pods.items[0].metadata.name
            return cast(
                str,
                core_api().read_namespaced_pod_log(
                    name=pod_name,
                    namespace=self.namespace,
                    tail_lines=tail_lines,
                ),
            )
        except Exception as exc:
            raise JobLogRetrievalError(f"Failed to get logs for {job_name}: {exc}") from exc

    @k8s_retry
    def delete(self, job_name: str) -> None:
        batch_api().delete_namespaced_job(
            name=job_name,
            namespace=self.namespace,
        )

    def wait_for_completion(
        self,
        job_name: str,
        timeout: int = 3600,
        poll_interval: int = 10,
    ) -> JobStatus:
        start = time.time()
        while time.time() - start < timeout:
            status = self.get_status(job_name)
            if status.phase in ("succeeded", "failed"):
                return status
            time.sleep(poll_interval)
        raise JobTimeoutError(f"Job {job_name} did not complete within {timeout}s")

    def _build_job(self, spec: JobSpec) -> V1Job:
        container = self._build_container(spec.container)
        pod_spec = V1PodSpec(
            containers=[container],
            restart_policy=spec.restart_policy,
            service_account_name=spec.service_account,
        )
        template = V1PodTemplateSpec(
            metadata=V1ObjectMeta(labels={"app": spec.name}),
            spec=pod_spec,
        )
        job_spec = V1JobSpec(
            template=template,
            ttl_seconds_after_finished=spec.ttl_seconds_after_finished,
            backoff_limit=spec.backoff_limit,
        )
        return V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=V1ObjectMeta(name=spec.name, namespace=self.namespace),
            spec=job_spec,
        )

    def _build_container(self, cs: ContainerSpec) -> V1Container:
        limits: dict[str, str] = {
            "cpu": cs.resources.cpu_limit,
            "memory": cs.resources.memory_limit,
        }
        if cs.resources.gpu.vendor == GPUVendor.AMD:
            limits["amd.com/gpu"] = str(cs.resources.gpu.limit)
        elif cs.resources.gpu.vendor == GPUVendor.NVIDIA:
            limits["nvidia.com/gpu"] = str(cs.resources.gpu.limit)

        resources = V1ResourceRequirements(
            requests={
                "cpu": cs.resources.cpu_request,
                "memory": cs.resources.memory_request,
            },
            limits=limits,
        )

        return V1Container(
            name="main",
            image=cs.image,
            command=cs.command,
            args=cs.args,
            env=[V1EnvVar(name=k, value=v) for k, v in cs.env.items()],
            resources=resources,
            ports=[{"containerPort": p} for p in cs.ports],
        )

    @staticmethod
    def _infer_phase(
        active: int,
        succeeded: int,
        failed: int,
    ) -> Literal["pending", "running", "succeeded", "failed"]:
        if succeeded > 0:
            return "succeeded"
        if failed > 0:
            return "failed"
        if active > 0:
            return "running"
        return "pending"
