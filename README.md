# k8s-llm-runtime

> 基于 Kubernetes 的 vLLM 模型服务网关（Model Serving Router）

`k8s-llm-runtime` 是一个 Python 库 + Helm chart 工具集，用于在 Kubernetes 上部署、调度和访问 vLLM 模型服务。Router 服务对外提供 OpenAI 兼容的推理 API，对内按需调度 Kubernetes 部署模型。

## 核心特性

- **OpenAI 兼容**：用户发 `POST /v1/chat/completions`，无需了解 K8s
- **按需部署**：首次请求某模型 → 自动 helm install；闲置超时 → 自动 undeploy
- **多模型并存**：同时跑 Qwen / Llama / Mistral，靠 alias 路由
- **GPU 灵活**：CPU / AMD ROCm / NVIDIA 三种模式，values.yaml 切换
- **Kubernetes 原生**：Helm chart + RBAC 最小权限 + Prometheus 指标 + Lease 分布式锁

## 架构概览

```text
Client
  -> LLM Router (FastAPI / Pod)
    -> Lease lock + Helm install
      -> vLLM Inference Pod
        -> NVIDIA / AMD GPU
```

详细说明参见 [`docs/architecture.md`](docs/architecture.md)。

## 快速开始（本地 kind 集群）

```bash
# 1. 起本地 K8s 集群
make cluster-up CLUSTER=kind

# 2. 构建并导入 Router 镜像（镜像内已自带 charts/llm-inference）
docker build -f docker/Dockerfile.router -t k8s-llm-runtime/router:0.1.0 .
docker save k8s-llm-runtime/router:0.1.0 \
  | docker exec -i k8s-llm-demo-kind-worker2 \
      ctr -n k8s.io images import --snapshotter=overlayfs -

# 3. 部署 Router（kind config 已预置 k8s-llm-runtime/router=true label）
KUBECONFIG=./kubeconfig helm upgrade --install llm-router ./charts/llm-router \
  --namespace llm-system --create-namespace --wait \
  --set-string nodeSelector.k8s-llm-runtime/router=true

# 4. Port-forward
KUBECONFIG=./kubeconfig kubectl -n llm-system port-forward svc/llm-router 18080:8080 &

# 5. 调推理（首次会自动部署模型）
python examples/vllm_qwen/client.py \
  --base-url http://127.0.0.1:18080/v1 \
  --model qwen-0.5b \
  --prompt "Hello"
```

GPU 推理还需要把 vLLM 运行时镜像导入到 GPU worker：

```bash
# 宿主机先拉一次
docker pull vllm/vllm-openai:latest

# 只导入 GPU worker，不重复导入到其它节点
docker save vllm/vllm-openai:latest \
  | docker exec -i k8s-llm-demo-kind-worker \
      ctr -n k8s.io images import --snapshotter=overlayfs -
```

如果只想测 Router / Helm 编排流程，不想拉这个大镜像，可以用 CPU-only mock：

```bash
docker build -f docker/mock-vllm/Dockerfile -t mock-vllm:latest docker/mock-vllm/
docker save mock-vllm:latest \
  | docker exec -i k8s-llm-demo-kind-worker \
      ctr -n k8s.io images import --snapshotter=overlayfs -

KUBECONFIG=./kubeconfig helm upgrade --install llm-router ./charts/llm-router \
  --namespace llm-system --create-namespace --wait \
  --set-string nodeSelector.k8s-llm-runtime/router=true \
  --set-string vllmHelmExtraArgs=-f\ /etc/mock/values-mock.yaml
```

完整步骤见 [`docs/usage.md`](docs/usage.md)。

## 文档

- [架构设计](docs/architecture.md)
- [本地部署与使用](docs/usage.md)

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
make test-integration  # 跑 kind e2e
make lock-runtime      # 更新 docker/requirements.lock
```

## Python 库结构

```python
from k8s_llm_runtime import (
    # Kubernetes Job
    K8sJobOperator, JobSpec, ContainerSpec, GPUResource, GPUVendor,

    # Helm-based vLLM deploy
    VLLMInferenceOperator, VLLMDeployment,

    # Model routing
    ModelOperator, K8sLeaseLock,
    ChatMessage, ChatRequest, ChatResponse,
)
```

## 项目布局

```text
src/k8s_llm_runtime/         # Python 核心库
charts/llm-router/            # Router Helm chart
charts/llm-inference/         # vLLM 模型服务 Helm chart（被 Router 动态部署）
docker/                       # Router 镜像构建
docker/mock-vllm/             # CPU-only 测试用 mock vLLM
examples/vllm_qwen/           # 示例客户端
scripts/cluster/              # 本地 kind/minikube 集群启动脚本
docs/                         # 架构与使用文档
tests/                        # 单元测试 + chart 渲染测试 + 集成测试
```

## 许可证

MIT