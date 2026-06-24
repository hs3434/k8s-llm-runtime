"""Fixtures for chart rendering tests."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def chart_path():
    return REPO_ROOT / "charts" / "llm-inference"


@pytest.fixture
def helm_template(chart_path):
    """Return a function that renders the chart with given --set values."""

    def _render(set_values: list[str] | None = None) -> str:
        cmd = [
            "helm", "template", "test-release", str(chart_path),
            "--namespace", "test-ns",
        ]
        for v in set_values or []:
            cmd.extend(["--set", v])
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout

    return _render
