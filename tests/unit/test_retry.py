"""Tests for retry decorator."""
from kubernetes.client.rest import ApiException

from k8s_llm_runtime._retry import _is_transient, k8s_retry


def test_is_transient_returns_true_for_5xx():
    for status in (500, 502, 503, 504):
        exc = ApiException(status=status, reason="x")
        assert _is_transient(exc) is True


def test_is_transient_returns_true_for_429():
    exc = ApiException(status=429, reason="x")
    assert _is_transient(exc) is True


def test_is_transient_returns_false_for_4xx_other_than_429():
    for status in (400, 401, 403, 404, 409):
        exc = ApiException(status=status, reason="x")
        assert _is_transient(exc) is False


def test_is_transient_returns_false_for_non_api_exception():
    assert _is_transient(ValueError("x")) is False


def test_k8s_retry_succeeds_on_first_try():
    calls = []

    @k8s_retry
    def f(x):
        calls.append(x)
        return "ok"

    assert f(42) == "ok"
    assert calls == [42]


def test_k8s_retry_returns_function_result():
    @k8s_retry
    def double(x):
        return x * 2

    assert double(21) == 42