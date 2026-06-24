# k8s-llm-runtime

> 基于 Kubernetes 的 vLLM 模型服务网关（Model Serving Router）

从 [ai-flow](https://github.com/example/ai-flow) 抽出 K8s 执行能力，构建独立的 Python 库 + Helm chart 工具集，对外提供 OpenAI 兼容的推理 API，内部按需调度 K8s 部署模型。

## 核心特性

- **OpenAI 兼容**：用户发 `POST /v1/chat/completions`，无需了解 K8s
- **按需部署**：首次请求某模型 → 自动 helm install；闲置超时 → 自动 undeploy
- **多模型并存**：同时跑 Qwen / Llama / Mistral，靠 alias 路由
- **GPU 灵活**：CPU / AMD ROCm / NVIDIA 三种模式，values.yaml 切换
- **生产级**：Helm chart + RBAC 最小权限 + Prometheus 指标 + 分布式锁

## 快速开始

```bash
# 1. 起本地 K8s 集群（默认 kind）
make cluster-up

# 2. 部署 Router
helm install llm-router ./charts/llm-router -n llm-system --create-namespace --wait

# 3. 端口转发
kubectl -n llm-system port-forward svc/llm-router 8080:8080 &

# 4. 调推理（首次会自动部署模型）
python examples/vllm_qwen/client.py --prompt "Hello"
```

## 文档

- [架构设计](docs/architecture.md)
- [AMD 面试 demo 步骤](docs/amd-interview-demo.md)
- [设计稿](../learning-journey/docs/superpowers/specs/2026-06-24-k8s-llm-runtime-design.md)
- [实施计划](../learning-journey/docs/superpowers/plans/)

## 安装依赖

```bash
uv sync --all-extras
```

## 开发命令

```bash
make test              # 跑单元测试 + chart 测试
make lint              # ruff check
make format            # ruff format
make type-check        # mypy --strict
make cluster-up        # 起 kind 集群
make cluster-down      # 停 kind 集群
make demo              # 部署 demo
make test-integration  # 跑 kind e2e
```

## Python 库 API（3 层）

```python
from k8s_llm_runtime import (
    # Low level: K8s Jobs
    K8sJobOperator, JobSpec, ContainerSpec, GPUResource, GPUVendor,

    # Mid level: Helm deploy vLLM
    VLLMInferenceOperator, VLLMDeployment,

    # High level: Model serving router
    ModelOperator, K8sLeaseLock,
    ChatMessage, ChatRequest, ChatResponse,
)
```

## 项目状态

🚧 v1.0 完成 — 仓库骨架完整，所有 Phase 已提交。

## 许可证

MIT
