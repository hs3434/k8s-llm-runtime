"""Typed exception hierarchy for k8s-llm-runtime.

All exceptions inherit from K8sLLMRuntimeError so callers can catch
the entire library's errors with a single except clause.
"""


class K8sLLMRuntimeError(Exception):
    """Base class for all errors raised by this library."""


# --- K8s Job layer ---


class JobCreationError(K8sLLMRuntimeError):
    """Failed to create a Kubernetes Job."""


class JobTimeoutError(K8sLLMRuntimeError):
    """Job did not complete within the timeout."""


class JobLogRetrievalError(K8sLLMRuntimeError):
    """Failed to fetch pod logs for a Job."""


# --- vLLM layer ---


class VLLMDeployError(K8sLLMRuntimeError):
    """Base error for vLLM Helm operations."""


class VLLMDeployTimeoutError(VLLMDeployError):
    """vLLM Helm install did not become ready within the timeout."""


class VLLMUndeployError(K8sLLMRuntimeError):
    """Failed to uninstall a vLLM Helm release."""


# --- Model routing layer ---


class ModelNotFoundError(K8sLLMRuntimeError):
    """Requested model alias is not configured."""


class ModelAliasError(K8sLLMRuntimeError):
    """Model alias configuration is invalid."""


# --- Locking ---


class LockAcquireTimeoutError(K8sLLMRuntimeError):
    """Failed to acquire a distributed lease within the timeout."""
