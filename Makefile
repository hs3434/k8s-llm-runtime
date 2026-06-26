.PHONY: help install lint format type-check test test-unit test-chart test-integration cluster-up cluster-down clean lock-runtime

CLUSTER ?= kind
KUBECONFIG ?= ./kubeconfig

help:
	@echo "Targets:"
	@echo "  install         - Install dev deps via uv"
	@echo "  lint            - Run ruff check"
	@echo "  format          - Run ruff format"
	@echo "  type-check      - Run mypy strict"
	@echo "  test            - Run unit + chart tests"
	@echo "  test-integration- Run kind e2e tests"
	@echo "  lock-runtime   - Refresh Docker runtime dependency lock"
	@echo "  cluster-up      - Start $$(CLUSTER) cluster"

install:
	uv sync --all-extras

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests

type-check:
	uv run mypy src/k8s_llm_runtime

test: test-unit test-chart

test-unit:
	uv run pytest tests/unit -v

test-chart:
	uv run pytest tests/chart -v

test-integration:
	uv run pytest tests/integration -v

lock-runtime:
	uv pip compile pyproject.toml -o docker/requirements.lock

cluster-up:
	@./scripts/cluster/$(CLUSTER)-up.sh

cluster-down:
	@./scripts/cluster/$(CLUSTER)-down.sh

clean:
	rm -rf .venv .pytest_cache .mypy_cache .ruff_cache htmlcov *.egg-info dist
	find . -type d -name __pycache__ -exec rm -rf {} +
