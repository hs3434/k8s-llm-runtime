# k8s-llm-runtime 使用说明

本文档介绍如何在本地 kind/minikube 集群上部署和验证 `k8s-llm-runtime`：通过 Router 按需部署 vLLM 模型服务，并提供 OpenAI-compatible API。

本项目当前支持：

- CPU / mock-vLLM
- AMD GPU：`amd.com/gpu`
- NVIDIA GPU：`nvidia.com/gpu`

---

## 1. 部署前准备

### 本地工具

确认机器上已经安装：

- Docker
- kind
- kubectl
- Helm v3.14+
- Python 3.11+
- uv

### 进入项目目录

```bash
cd /work/run/projects/bio-24/my_projects/k8s-llm-runtime
```

Router 服务运行在 Docker 镜像里，不依赖宿主机 Python 环境。宿主机只需要能运行示例客户端；如果客户端依赖缺失，再按需安装即可。

### 构建 Router 镜像

```bash
docker build -f docker/Dockerfile.router -t k8s-llm-runtime/router:0.1.0 .
```

### 启动本地集群

```bash
make cluster-up CLUSTER=kind
```

如果机器上有 NVIDIA GPU 且 `nvidia-ctk` 可用，`kind-up.sh` 会自动使用 GPU kind 配置。

---

## 2. 项目结构说明

建议先打开项目目录，按下面顺序介绍：

| 路径 | 说明 |
|---|---|
| `src/k8s_llm_runtime/` | Python 核心库，包含 Job、Lease、vLLM 部署、模型路由、Router server |
| `charts/llm-router/` | Router 服务 Helm chart |
| `charts/llm-inference/` | vLLM 模型服务 Helm chart |
| `scripts/cluster/` | 本地 kind/minikube 集群启动脚本 |
| `docker/Dockerfile.router` | Router 镜像构建文件 |
| `docker/mock-vllm/` | CPU-only e2e 测试用 mock vLLM |
| `examples/vllm_qwen/` | Qwen 示例客户端、benchmark、请求样例 |
| `docs/architecture.md` | 架构说明 |
| `docs/project-overview.md` | 项目文件说明 |

讲解重点：

- Router 对外提供 OpenAI-compatible API
- Router 根据模型别名按需部署 vLLM
- 每个模型对应一个 Helm release
- Kubernetes Lease 防止并发部署冲突
- GPU 类型通过 Helm values 配置

---

## 3. 本地部署与验证流程

### 3.1 启动 kind 集群

```bash
make cluster-up CLUSTER=kind
```

检查节点：

```bash
KUBECONFIG=./kubeconfig kubectl get nodes
```

检查基础组件：

```bash
KUBECONFIG=./kubeconfig kubectl -n ingress-nginx get pods
KUBECONFIG=./kubeconfig kubectl -n kube-system get pods -l k8s-app=metrics-server
```

如果是 NVIDIA GPU 集群，检查 GPU 资源：

```bash
KUBECONFIG=./kubeconfig kubectl describe node | grep -A5 nvidia.com/gpu
```

### 3.2 构建并导入 Router 镜像

构建：

```bash
docker build -f docker/Dockerfile.router -t k8s-llm-runtime/router:0.1.0 .
```

由于 Router 是手动部署的，我们把 Router 固定到一个普通 worker 节点（例如 `worker2`），从而避免把镜像导入所有节点。

给目标 worker 打 label：

```bash
KUBECONFIG=./kubeconfig kubectl label node k8s-llm-demo-kind-worker2 \
  k8s-llm-runtime/router=true --overwrite
```

在 rootless Docker、containerd v2、或镜像 manifest 兼容性不佳的环境里，`kind load docker-image` 可能失败，常见表现是镜像导入报错或节点 containerd 中看不到镜像。为了避免这类问题，推荐直接用 `docker save | ctr import` 把 Router 镜像只导入目标 worker：

```bash
docker save k8s-llm-runtime/router:0.1.0 \
  | docker exec -i k8s-llm-demo-kind-worker2 \
      ctr -n k8s.io images import --snapshotter=overlayfs -
```

导入后可以检查：

```bash
docker exec k8s-llm-demo-kind-worker2 \
  ctr -n k8s.io images ls | grep k8s-llm-runtime/router
```

如果环境确认 `kind load docker-image` 可用，也可以一次性导入所有节点：

```bash
kind load docker-image k8s-llm-runtime/router:0.1.0 --name k8s-llm-demo-kind
```

### 3.3 导入 vLLM 镜像

真实推理需要 `vllm/vllm-openai:latest` 镜像。这个镜像很大，建议提前在宿主机拉取：

```bash
docker pull vllm/vllm-openai:latest
```

vLLM Pod 只会调度到 GPU worker，所以只需要把镜像导入 GPU worker 的 containerd，不要重复导入到所有节点：

```bash
docker save vllm/vllm-openai:latest \
  | docker exec -i k8s-llm-demo-kind-worker \
      ctr -n k8s.io images import --snapshotter=overlayfs -
```

检查镜像是否已在 GPU worker 中：

```bash
docker exec k8s-llm-demo-kind-worker \
  ctr -n k8s.io images ls | grep 'vllm/vllm-openai'
```

如果只是跑 CPU-only mock demo，可以跳过这一步，改用 `docker/mock-vllm` 镜像和 `docker/mock-vllm/values-mock.yaml`。

### 3.4 准备 `llm-inference` chart-source ConfigMap

Router 动态部署 vLLM 时，需要在容器内访问 `charts/llm-inference`。

先把 chart 打包：

```bash
helm package charts/llm-inference -d /tmp
```

再放入 ConfigMap：

```bash
KUBECONFIG=./kubeconfig kubectl create namespace llm-system --dry-run=client -o yaml | KUBECONFIG=./kubeconfig kubectl apply -f -

KUBECONFIG=./kubeconfig kubectl -n llm-system create configmap llm-router-chart-source \
  --from-file=chart=/tmp/llm-inference-0.1.0.tgz \
  --dry-run=client -o yaml | KUBECONFIG=./kubeconfig kubectl apply -f -
```

Router Pod 的 initContainer 会解压这个 chart 到：

```text
/app/charts/llm-inference
```

### 3.5 安装 Router

所有环境都建议用 nodeSelector 把 Router 固定到 `worker2`，避免 Router Pod 漂到其它节点后因为镜像缺失而启动失败。

CPU / mock 环境：

```bash
KUBECONFIG=./kubeconfig helm upgrade --install llm-router ./charts/llm-router \
  --namespace llm-system \
  --create-namespace \
  --wait \
  --set nodeSelector.k8s-llm-runtime/router=true
```

NVIDIA GPU 环境：

```bash
KUBECONFIG=./kubeconfig helm upgrade --install llm-router ./charts/llm-router \
  --namespace llm-system \
  --create-namespace \
  --wait \
  --set nodeSelector.k8s-llm-runtime/router=true \
  --set models.defaultGpu.vendor=nvidia \
  --set models.defaultGpu.limit=1
```

AMD GPU 环境：

```bash
KUBECONFIG=./kubeconfig helm upgrade --install llm-router ./charts/llm-router \
  --namespace llm-system \
  --create-namespace \
  --wait \
  --set nodeSelector.k8s-llm-runtime/router=true \
  --set models.defaultGpu.vendor=amd \
  --set models.defaultGpu.limit=1
```

检查 Router：

```bash
KUBECONFIG=./kubeconfig kubectl -n llm-system get pods -o wide
KUBECONFIG=./kubeconfig kubectl -n llm-system logs deployment/llm-router --tail=50
```

### 3.6 Port-forward Router

```bash
KUBECONFIG=./kubeconfig kubectl -n llm-system port-forward svc/llm-router 18080:8080
```

另开一个终端验证：

```bash
curl http://127.0.0.1:18080/healthz
curl http://127.0.0.1:18080/readyz
curl http://127.0.0.1:18080/v1/models
```

预期：

```json
{"status":"healthy"}
{"status":"ready"}
{"object":"list","data":[]}
```

### 3.7 触发模型部署

```bash
python examples/vllm_qwen/client.py \
  --base-url http://127.0.0.1:18080/v1 \
  --model qwen-0.5b \
  --prompt "用一句话介绍 Kubernetes"
```

第一次请求会触发：

```text
Router
  -> 获取 Lease
  -> helm upgrade --install qwen-0-5b charts/llm-inference
  -> 创建 vLLM Deployment + Service
  -> 等待 vLLM ready
  -> 转发请求
```

检查模型 release：

```bash
KUBECONFIG=./kubeconfig helm list -n llm-models
KUBECONFIG=./kubeconfig kubectl get all -n llm-models
```

第二次请求会复用已经部署的 vLLM 服务，延迟会明显降低。

### 3.8 卸载模型

```bash
curl -X DELETE http://127.0.0.1:18080/v1/models/qwen-0.5b
```

预期返回：

```text
204 No Content
```

验证：

```bash
KUBECONFIG=./kubeconfig helm list -n llm-models
KUBECONFIG=./kubeconfig kubectl get all -n llm-models
```

---

## 4. 本地模型缓存使用

如果模型已经提前下载到：

```text
/work/run/projects/bio-24/k8s-llm-runtime/cache/Qwen2.5-0.5B-Instruct
```

可以通过 `model.hfCachePath` 让 vLLM 离线读取：

```bash
KUBECONFIG=./kubeconfig helm upgrade --install llm-router ./charts/llm-router \
  --namespace llm-system \
  --create-namespace \
  --wait \
  --set nodeSelector.k8s-llm-runtime/router=true \
  --set models.defaultGpu.vendor=nvidia \
  --set models.defaultGpu.limit=1 \
  --set-string 'vllmHelmExtraArgs=--set model.hfCachePath=/work/run/projects/bio-24/k8s-llm-runtime/cache/Qwen2.5-0.5B-Instruct'
```

这会让 vLLM Pod 使用：

```text
HF_HUB_CACHE=/work/run/projects/bio-24/k8s-llm-runtime/cache/Qwen2.5-0.5B-Instruct
HF_HUB_OFFLINE=1
```

---

## 5. 关键设计说明

### Router 为什么动态部署模型

大模型长期占用 GPU 成本高。按需部署可以节省 GPU 和内存资源。

### 为什么每个模型一个 Helm release

每个模型有独立的 Deployment、Service 和生命周期，方便升级、删除和排查。

### 为什么用 Kubernetes Lease

多 Router 副本同时收到同一模型请求时，Lease 可以保证只有一个副本执行部署。

### 为什么用 Helm 而不是 Operator

Helm 足够轻量，部署、升级、回滚、卸载能力成熟，不需要额外 CRD 和 Controller。

### GPU 资源如何区分厂商

`llm-inference` chart 根据：

```yaml
gpu:
  vendor: amd
  limit: 1
```

渲染：

```yaml
resources:
  limits:
    amd.com/gpu: "1"
```

如果使用 NVIDIA，则渲染：

```yaml
resources:
  limits:
    nvidia.com/gpu: "1"
```

---

## 6. 常见问题

| 问题 | 回答 |
|---|---|
| 多个 Router 副本如何避免重复部署？ | 使用 Kubernetes Lease，每个模型 alias 一个锁。 |
| 为什么不用 KServe？ | KServe 更重，需要 CRD 和 Controller。本项目用 Helm 保持轻量。 |
| 为什么用 Pydantic？ | 类型安全、请求校验、FastAPI OpenAPI schema 自动生成。 |
| 怎么加鉴权？ | 可以在 Ingress 前加 OAuth2 Proxy，或在 FastAPI 层加 Bearer token/OIDC。 |
| 怎么支持 AMD ROCm？ | chart 通过 `gpu.vendor=amd` 注入 `amd.com/gpu` 资源。 |
| 怎么支持 NVIDIA？ | chart 通过 `gpu.vendor=nvidia` 注入 `nvidia.com/gpu` 资源。 |
| 模型部署失败怎么办？ | Router 返回明确错误；失败模式记录在 `docs/architecture.md`。 |
| 首次请求为什么慢？ | 首次请求需要部署 vLLM、加载模型、可能下载权重。后续请求复用服务。 |

---

## 7. 清理环境

```bash
make cluster-down CLUSTER=kind
```

如果手动安装过 Router：

```bash
KUBECONFIG=./kubeconfig helm uninstall llm-router -n llm-system
KUBECONFIG=./kubeconfig kubectl delete namespace llm-models
```