"""Retry decorator for transient kubernetes API errors."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from kubernetes.client.rest import ApiException
from tenacity import (
    Retrying,
    before_sleep_log,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def _is_transient(exc: BaseException) -> bool:
    """Return True if the ApiException is retryable (5xx or 429)."""
    if isinstance(exc, ApiException):
        return exc.status in (429, 500, 502, 503, 504)
    return isinstance(exc, (TimeoutError, ConnectionError))


def k8s_retry(fn: Callable[P, R]) -> Callable[P, R]:
    """Decorator: retry transient K8s API errors with exponential backoff."""

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return Retrying(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            retry=retry_if_exception(_is_transient),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )(fn, *args, **kwargs)

    return wrapper
