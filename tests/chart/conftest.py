"""Fixtures for chart rendering tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def chart_paths():
    return {
        "inference": REPO_ROOT / "charts" / "llm-inference",
        "router": REPO_ROOT / "charts" / "llm-router",
    }


@pytest.fixture
def helm_template(chart_paths):
    """Return a function that renders the chart with given --set values."""

    def _render(*args, chart: str = "inference", set_values: list[str] | None = None) -> str:
        if args:
            if isinstance(args[0], str):
                chart = args[0]
                set_values = args[1] if len(args) > 1 else set_values
            elif isinstance(args[0], list):
                set_values = args[0]
        cmd = [
            "helm",
            "template",
            "test-release",
            str(chart_paths[chart]),
            "--namespace",
            "test-ns",
        ]
        for v in set_values or []:
            cmd.extend(["--set", v])
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout

    return _render
