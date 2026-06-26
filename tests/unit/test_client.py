"""Tests for kubernetes-client singleton."""

from unittest.mock import patch

import pytest
from kubernetes.config import ConfigException

from k8s_llm_runtime import _client


@pytest.fixture(autouse=True)
def reset_singletons():
    _client._batch_api = None
    _client._core_api = None
    _client._config_loaded = False
    yield
    _client._batch_api = None
    _client._core_api = None
    _client._config_loaded = False


def test_load_kube_config_uses_explicit_path(tmp_path):
    cfg_file = tmp_path / "kubeconfig"
    cfg_file.write_text("apiVersion: v1\nclusters: []\n")
    with patch("kubernetes.config.load_kube_config") as mock_load:
        _client.load_config(str(cfg_file))
        mock_load.assert_called_once()
        args, kwargs = mock_load.call_args
        assert (args and args[0] == str(cfg_file)) or kwargs.get("config_file") == str(cfg_file)
        assert _client._config_loaded is True


def test_load_kube_config_falls_back_to_incluster():
    with (
        patch("kubernetes.config.load_kube_config", side_effect=ConfigException("no kubeconfig")),
        patch("kubernetes.config.load_incluster_config") as mock_incluster,
    ):
        _client.load_config(None)
        mock_incluster.assert_called_once()
        assert _client._config_loaded is True


def test_batch_api_lazy_loads():
    with patch.object(_client, "load_config") as mock_load:
        _client.batch_api()
        mock_load.assert_called_once()
        _client.batch_api()  # second call
        mock_load.assert_called_once()


def test_core_api_lazy_loads():
    with patch.object(_client, "load_config") as mock_load:
        _client.core_api()
        mock_load.assert_called_once()


def test_get_batch_api_returns_client_instance():
    with patch.object(_client, "load_config"):
        api = _client.batch_api()
        assert api is not None
