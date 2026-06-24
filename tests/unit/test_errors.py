"""Tests for the typed exception hierarchy."""

import pytest

from k8s_llm_runtime.errors import (
    JobCreationError,
    JobLogRetrievalError,
    JobTimeoutError,
    K8sLLMRuntimeError,
    LockAcquireTimeoutError,
    ModelAliasError,
    ModelNotFoundError,
    VLLMDeployError,
    VLLMDeployTimeoutError,
    VLLMUndeployError,
)


def test_k8s_llm_runtime_error_is_base():
    for cls in [
        JobCreationError,
        JobTimeoutError,
        JobLogRetrievalError,
        VLLMDeployError,
        VLLMDeployTimeoutError,
        VLLMUndeployError,
        ModelNotFoundError,
        ModelAliasError,
        LockAcquireTimeoutError,
    ]:
        assert issubclass(cls, K8sLLMRuntimeError)


def test_vllm_deploy_timeout_inherits_deploy_error():
    assert issubclass(VLLMDeployTimeoutError, VLLMDeployError)


def test_job_creation_error_message():
    err = JobCreationError("test job")
    assert "test job" in str(err)
    assert isinstance(err, K8sLLMRuntimeError)


def test_model_not_found_error_carries_alias():
    err = ModelNotFoundError("qwen-99b")
    assert "qwen-99b" in str(err)


def test_lock_acquire_timeout_raises_in_caller():
    with pytest.raises(K8sLLMRuntimeError):
        raise LockAcquireTimeoutError("key=deploy-qwen")
