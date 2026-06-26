"""Singleton wrapper around the official kubernetes Python client.

Lazy-loads config and clients on first use. Honors `KUBECONFIG` env var
if `kubeconfig_path` is None.
"""

from __future__ import annotations

import os
from typing import Optional

from kubernetes import client, config
from kubernetes.config import ConfigException

_batch_api: Optional[client.BatchV1Api] = None
_core_api: Optional[client.CoreV1Api] = None
_coordination_api: Optional[client.CoordinationV1Api] = None
_config_loaded: bool = False


def load_config(kubeconfig_path: Optional[str] = None) -> None:
    """Load kubernetes config from explicit path or env or in-cluster."""
    global _config_loaded
    if _config_loaded:
        return

    path = kubeconfig_path or os.environ.get("KUBECONFIG")

    try:
        if path:
            config.load_kube_config(config_file=path)
        else:
            config.load_kube_config()  # default ~/.kube/config
    except ConfigException:
        config.load_incluster_config()

    _config_loaded = True


def batch_api() -> client.BatchV1Api:
    """Lazy-initialize and return the BatchV1Api client."""
    global _batch_api
    if _batch_api is None:
        load_config()
        _batch_api = client.BatchV1Api()
    return _batch_api


def core_api() -> client.CoreV1Api:
    """Lazy-initialize and return the CoreV1Api client."""
    global _core_api
    if _core_api is None:
        load_config()
        _core_api = client.CoreV1Api()
    return _core_api


def coordination_api() -> client.CoordinationV1Api:
    """Lazy-initialize and return the CoordinationV1Api client."""
    global _coordination_api
    if _coordination_api is None:
        load_config()
        _coordination_api = client.CoordinationV1Api()
    return _coordination_api
