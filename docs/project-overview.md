# k8s-llm-runtime 项目说明

`k8s-llm-runtime` 是一个 Python 库 + Helm chart 工具集，用于在 Kubernetes 上部署、调度和访问 vLLM 模型服务。

项目的核心思路是：

```text
Client
  -> LLM Router FastAPI 服务
  -> Router 按需用 Helm 部署 vLLM 模型服务
  -> vLLM OpenAI-compatible Server
  -> GPU / CPU 推理
```

用户向 Router 发送 OpenAI-compatible 请求，例如 `/v1/chat/completions`，并指定模型别名，例如 `qwen-0.5b`。Router 会把别名解析成真实 Hugging Face 模型名，如果模型还没部署，就自动创建对应的 vLLM Deployment 和 Service，然后把请求转发给 vLLM。

---

## 1. 顶层文件

### `.github/workflows/ci.yml`

GitHub Actions 普通 CI 流程。

用于运行：

- lint
- type-check
- unit tests
- chart rendering tests

目的是保证代码质量和 Helm chart 渲染正确。

### `.github/workflows/integration.yml`

GitHub Actions 集成测试流程。

用于跑 kind 端到端测试，例如：

1. 启动 kind 集群
2. 部署 Router
3. 触发模型部署
4. 调用 API
5. 验证返回结果

### `.gitignore`

忽略本地开发和构建产物，例如：

```gitignore
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
kubeconfig
uv.lock
```

当前项目不再跟踪 `uv.lock`。原因是实际部署时服务会打进 Docker 镜像，镜像的运行依赖由 `docker/requirements.lock` 固定。

### `AGENTS.md`

给 AI agent 和开发者的项目规范。

包含：

- Python 编码规范
- Helm chart 规范
- 测试规范
- Git commit 规范
- 项目技术栈
- 常用命令

### `LICENSE`

项目许可证。当前是 MIT License。

### `Makefile`

常用开发命令入口。

主要命令：

```bash
make install           # 用 uv 安装开发依赖
make lint              # 运行 ruff check
make format            # 运行 ruff format
make type-check        # 运行 mypy
make test              # 运行 unit + chart tests
make test-unit         # 只运行单元测试
make test-chart        # 只运行 Helm chart 测试
make test-integration  # 运行 kind 端到端测试
make cluster-up        # 启动本地集群
make cluster-down      # 删除本地集群
make lock-runtime      # 重新生成 docker/requirements.lock
make clean             # 清理本地缓存
```

### `README.md`

项目 README，是普通用户理解和使用项目的入口。

通常包含：

- 项目简介
- 安装方式
- 使用方式
- 示例命令

### `pyproject.toml`

Python 项目配置文件。

定义内容包括：

- 包名：`k8s-llm-runtime`
- Python 版本：`>=3.11`
- 运行依赖：`kubernetes`、`pydantic`、`fastapi`、`uvicorn`、`httpx`、`structlog`、`prometheus-client`、`tenacity`、`pyyaml`
- 开发依赖：`pytest`、`ruff`、`mypy`、`openai`
- 构建后端：`hatchling`
- ruff、mypy、pytest 配置

---

## 2. Python 核心库：`src/k8s_llm_runtime/`

这是项目的核心 Python 库，被 Router 服务调用。

### `src/k8s_llm_runtime/__init__.py`

Python 包初始化文件。

### `src/k8s_llm_runtime/_client.py`

Kubernetes client 初始化工具。

主要作用：

- 在集群内运行时加载 in-cluster config
- 在本地运行时加载 kubeconfig
- 返回 Kubernetes API client 给其他模块使用

被这些模块复用：

- `job.py`
- `lock.py`
- `model.py`
- `vllm.py`

### `src/k8s_llm_runtime/_log.py`

结构化日志配置。

项目使用 `structlog` 输出结构化日志，便于记录：

- model alias
- request id
- error type
- 部署事件
- 推理事件

### `src/k8s_llm_runtime/_metrics.py`

Prometheus 指标定义。

用于记录：

- 推理请求数量
- 推理延迟
- vLLM 部署耗时
- 部署失败次数
- 已加载模型数量

Router 会通过 `/metrics` 暴露这些指标。

### `src/k8s_llm_runtime/_retry.py`

重试工具。

基于 `tenacity` 封装 retry/backoff 逻辑，主要用于 Kubernetes API 或网络请求的临时失败重试。

### `src/k8s_llm_runtime/errors.py`

项目自定义异常。

用于表达不同错误类型，例如：

- vLLM 部署失败
- vLLM 卸载失败
- 模型别名不存在
- 模型部署超时
- Kubernetes 操作失败

这样 Router 可以把不同异常映射成更合适的 HTTP 错误响应。

### `src/k8s_llm_runtime/types.py`

共享类型定义。

使用 Pydantic 定义请求、响应和配置模型。

可能包含：

- GPU vendor 类型
- GPU resource 配置
- Chat request / response
- vLLM deployment 状态
- 模型配置

### `src/k8s_llm_runtime/job.py`

Kubernetes Job 管理工具。

负责：

- 创建 Job
- 等待 Job 完成
- 获取 Job 日志
- 删除 Job
- 处理 Job 失败状态

后续可以用于模型预热、benchmark、一次性维护任务等。

### `src/k8s_llm_runtime/lock.py`

基于 Kubernetes Lease 的分布式锁。

为什么需要锁？

Router 可以有多个副本。如果两个副本同时收到同一个未部署模型的请求，它们可能同时执行 `helm install`。Lease lock 可以保证同一时间只有一个 Router 副本负责部署该模型。

底层使用 Kubernetes：

```text
coordination.k8s.io/v1 Lease
```

锁名类似：

```text
deploy-qwen-0-5b
```

### `src/k8s_llm_runtime/vllm.py`

vLLM Helm 部署操作封装。

主要负责模型部署生命周期：

1. 把模型别名转换成合法 Kubernetes DNS 名称

   ```text
   qwen-0.5b -> qwen-0-5b
   ```

2. 调用 Helm：

   ```bash
   helm upgrade --install qwen-0-5b /app/charts/llm-inference ...
   ```

3. 传入模型名、GPU 类型、GPU 数量、replica 数量等参数
4. 等待 vLLM Deployment ready
5. 查询 vLLM Service endpoint
6. 卸载模型 release

它是 Python Router 逻辑和 `charts/llm-inference` Helm chart 之间的桥梁。

### `src/k8s_llm_runtime/server.py`

通用 FastAPI Router 服务入口。

这个文件是 Router 镜像的实际启动模块。`docker/Dockerfile.router` 使用下面的 Uvicorn app path 启动它：

```bash
uvicorn k8s_llm_runtime.server:app --host 0.0.0.0 --port 8080 --workers 2
```

它负责：

- 加载 `MODEL_CONFIG_PATH` 指向的模型别名配置
- 初始化 `ModelOperator`
- 初始化 `VLLMInferenceOperator`
- 注册 Prometheus `/metrics`
- 暴露 Router HTTP API

它暴露的主要接口：

- `/healthz`
- `/readyz`
- `/metrics`
- `/v1/models`
- `/v1/chat/completions`

### `src/k8s_llm_runtime/model.py`

模型路由核心逻辑。

它负责完整请求链路：

1. 接收 chat request
2. 读取模型别名
3. 找到 Hugging Face 模型名
4. 检查模型是否已经部署
5. 如果没有部署，则获取 Kubernetes Lease 锁
6. 调用 `VLLMInferenceOperator.deploy()` 部署 vLLM
7. 等待 vLLM ready
8. 把请求转发给 vLLM
9. 返回 vLLM 响应
10. 记录 metrics

---

## 3. Router 示例应用：`examples/vllm_qwen/`

这个目录只保留 Qwen 示例客户端、benchmark 和请求样例。Router 服务端入口已经移动到通用模块：

```text
src/k8s_llm_runtime/server.py
```

### `examples/__init__.py`

Python 包标记文件。

### `examples/vllm_qwen/__init__.py`

Qwen 示例包标记文件。

### `examples/vllm_qwen/client.py`

测试客户端。

可以用 HTTP 或 OpenAI SDK 调用 Router。

示例：

```bash
python examples/vllm_qwen/client.py \
  --base-url http://127.0.0.1:18080/v1 \
  --model qwen-0.5b \
  --prompt "Hello"
```

### `examples/vllm_qwen/benchmark.py`

简单 benchmark 工具。

用于重复请求 Router/vLLM，观察延迟和吞吐。

### `examples/vllm_qwen/test_request.json`

示例请求体。

可以配合 curl 使用。

---

## 4. Router Helm chart：`charts/llm-router/`

这个 chart 用于把 Router 服务部署到 Kubernetes。

### `charts/llm-router/Chart.yaml`

Router Helm chart 元数据。

### `charts/llm-router/values.yaml`

Router 默认配置。

关键字段：

```yaml
replicaCount: 2
image:
  repository: k8s-llm-runtime/router
  tag: "0.1.0"
models:
  aliases:
    qwen-0.5b: Qwen/Qwen2.5-0.5B-Instruct
    qwen-7b: Qwen/Qwen2.5-7B-Instruct
  defaultGpu:
    vendor: none
    limit: 1
targetNamespace: llm-models
vllmHelmExtraArgs: ""
```

作用：

- 配置 Router 镜像
- 配置模型别名
- 配置默认 GPU 类型
- 配置 vLLM 部署目标 namespace
- 配置额外 Helm 参数

### `charts/llm-router/templates/_helpers.tpl`

Helm helper 模板。

定义通用命名和 label 函数，例如：

- chart name
- full name
- labels
- selector labels
- chart source ConfigMap name

### `charts/llm-router/templates/configmap.yaml`

生成 Router 模型配置 ConfigMap。

Router 会把它挂载为：

```text
/app/config/models.yaml
```

内容包括：

- 模型别名
- 默认 GPU 配置
- idle timeout
- deploy lock TTL

### `charts/llm-router/templates/deployment.yaml`

Router Deployment 模板。

定义：

- Router 容器镜像
- 8080 端口
- 环境变量
- 模型配置挂载
- chart bundle 挂载
- init container
- health/readiness probes

其中 init container 会从 `llm-router-chart-source` ConfigMap 中解包 `llm-inference` chart 到：

```text
/app/charts/llm-inference
```

Router 后续才能动态执行 Helm 部署 vLLM。

### `charts/llm-router/templates/service.yaml`

Router 的 ClusterIP Service。

用于集群内访问和本地 port-forward。

### `charts/llm-router/templates/serviceaccount.yaml`

Router Pod 使用的 ServiceAccount。

### `charts/llm-router/templates/role.yaml`

Router 使用的 ClusterRole。

Router 运行在 `llm-system`，但模型服务部署在 `llm-models`，所以需要跨 namespace 权限。

权限包括：

- Deployments
- ReplicaSets
- Services
- Pods
- ConfigMaps
- ServiceAccounts
- Secrets
- Leases
- Namespaces

其中 Secrets 是 Helm release metadata 需要的，Leases 是分布式锁需要的。

### `charts/llm-router/templates/rolebinding.yaml`

ClusterRoleBinding。

把 Router ServiceAccount 绑定到 ClusterRole。

### `charts/llm-router/templates/ingress.yaml`

可选 Ingress。

默认关闭。

### `charts/llm-router/templates/hpa.yaml`

可选 HPA。

默认关闭。

### `charts/llm-router/templates/servicemonitor.yaml`

可选 Prometheus ServiceMonitor。

默认关闭。

---

## 5. vLLM 推理 Helm chart：`charts/llm-inference/`

这个 chart 用于部署一个具体模型的 vLLM 服务。

同一个 chart 可以被 Router 多次安装，每个模型一个 Helm release。

例如：

```text
qwen-0-5b release -> qwen-0-5b Deployment + Service
qwen-7b release   -> qwen-7b Deployment + Service
```

### `charts/llm-inference/Chart.yaml`

vLLM 推理 chart 元数据。

### `charts/llm-inference/values.yaml`

vLLM 默认配置。

关键字段：

```yaml
image:
  repository: vllm/vllm-openai
  tag: latest
model:
  name: Qwen/Qwen2.5-0.5B-Instruct
  hfTokenSecret: ""
  hfEndpoint: https://hf-mirror.com
  hfCachePath: ""
gpu:
  vendor: none
  limit: 1
resources:
  requests:
    cpu: "1"
    memory: "2Gi"
  limits:
    cpu: "4"
    memory: "4Gi"
```

### `charts/llm-inference/templates/_helpers.tpl`

Helm 命名和 label helper。

### `charts/llm-inference/templates/deployment.yaml`

vLLM Deployment 模板。

核心启动参数：

```yaml
args:
  - --model
  - Qwen/Qwen2.5-0.5B-Instruct
  - --port
  - "8000"
```

支持：

- `HF_ENDPOINT`，默认 `https://hf-mirror.com`
- 可选 `HF_TOKEN` Secret
- 可选本地模型缓存 `model.hfCachePath`
- NVIDIA GPU：`nvidia.com/gpu`
- AMD GPU：`amd.com/gpu`
- nodeSelector / tolerations / affinity

当设置：

```yaml
model:
  hfCachePath: /work/run/projects/bio-24/k8s-llm-runtime/cache/Qwen2.5-0.5B-Instruct
```

会渲染：

```yaml
env:
  - name: HF_HUB_CACHE
    value: <cache path>
  - name: HF_HUB_OFFLINE
    value: "1"
volumeMounts:
  - name: hf-cache
    mountPath: <cache path>
    readOnly: true
volumes:
  - name: hf-cache
    hostPath:
      path: <cache path>
      type: DirectoryOrCreate
```

### `charts/llm-inference/templates/service.yaml`

vLLM Service。

Router 通过这个 Service 调用 vLLM：

```text
http://qwen-0-5b.llm-models.svc.cluster.local:8000/v1/chat/completions
```

### `charts/llm-inference/templates/serviceaccount.yaml`

vLLM Pod 使用的 ServiceAccount。

### `charts/llm-inference/templates/ingress.yaml`

可选 Ingress。

通常关闭，因为 vLLM 一般不直接暴露给外部用户，而是由 Router 调用。

### `charts/llm-inference/templates/hpa.yaml`

可选 HPA。

### `charts/llm-inference/templates/servicemonitor.yaml`

可选 Prometheus ServiceMonitor。

---

## 6. Docker 文件：`docker/`

### `docker/Dockerfile.router`

构建 Router 镜像。

镜像内容包括：

- Python 运行时依赖
- Helm CLI
- 项目 Python 源码
- FastAPI Router server
- Helm charts

构建时使用：

```text
docker/requirements.lock
```

最终启动命令：

```bash
uvicorn k8s_llm_runtime.server:app --host 0.0.0.0 --port 8080 --workers 2
```

### `docker/requirements.lock`

Router 镜像运行依赖锁文件。

它替代了原来的仓库级 `uv.lock`。

生成命令：

```bash
make lock-runtime
```

### `docker/mock-vllm/Dockerfile`

构建 mock vLLM 镜像。

用于 CPU-only 测试，不需要真实 GPU，也不需要下载庞大的 vLLM 镜像。

### `docker/mock-vllm/server.py`

OpenAI-compatible mock server。

用于模拟 vLLM 的关键接口，例如：

- `/v1/chat/completions`
- `/v1/models`
- `/healthz`
- `/readyz`

### `docker/mock-vllm/entrypoint.sh`

mock-vLLM 容器启动脚本。

### `docker/mock-vllm/values-mock.yaml`

Helm values override。

用于让 `llm-inference` chart 使用 mock-vLLM 镜像。

---

## 7. 集群脚本：`scripts/cluster/`

### `scripts/cluster/common.sh`

集群脚本共享函数。

负责：

- 日志输出
- 等待节点 ready
- 安装 ingress-nginx
- 安装 metrics-server
- 安装 NVIDIA device plugin
- 加载镜像到 kind 节点

### `scripts/cluster/install-prereqs.sh`

安装或检查本地依赖，例如：

- kubectl
- kind
- helm
- Docker
- minikube

### `scripts/cluster/kind-up.sh`

启动本地 kind 集群。

主要逻辑：

1. 检查 NVIDIA GPU 和 `nvidia-ctk`
2. 生成 CDI spec
3. 复制 NVIDIA driver libraries
4. 渲染 GPU 或非 GPU kind 配置
5. 创建 kind 集群
6. 导出 kubeconfig
7. 安装 ingress-nginx
8. 安装 metrics-server
9. 如果是 GPU 模式，安装 NVIDIA device plugin

### `scripts/cluster/kind-down.sh`

删除 kind 集群。

### `scripts/cluster/kind-config.yaml`

普通非 GPU kind 配置。

### `scripts/cluster/kind-config-gpu.yaml`

GPU kind 配置。

它创建三个节点：

- control-plane
- GPU worker
- 普通 worker

只给 GPU worker 挂载：

- CDI spec
- NVIDIA 工具
- NVIDIA driver libraries
- `/dev/nvidia*` 设备
- Hugging Face 模型缓存目录

并开启 containerd CDI：

```toml
[plugins."io.containerd.grpc.v1.cri"]
  enable_cdi = true
```

### `scripts/cluster/minikube-up.sh`

启动 minikube 集群。

### `scripts/cluster/minikube-down.sh`

删除 minikube 集群。

### `scripts/cluster/TODO.md`

开发过程记录。

记录内容包括：

- e2e demo 验证过程
- 遇到的问题
- 已修复的问题
- mock-vLLM 方案
- GPU kind 方案
- 后续计划

### `scripts/cluster/manifests/ingress-nginx-kind-v1.10.0.yaml`

kind 使用的 ingress-nginx 安装 manifest。

### `scripts/cluster/manifests/metrics-server.yaml`

metrics-server 安装 manifest。

用于支持：

```bash
kubectl top nodes
kubectl top pods
```

### `scripts/cluster/manifests/nvidia-device-plugin.yaml`

NVIDIA device plugin DaemonSet。

它向 Kubernetes 注册扩展资源：

```text
nvidia.com/gpu
```

并使用 CDI annotations，让 containerd 根据 CDI spec 把 GPU 注入到 Pod。

---

## 8. 文档目录：`docs/`

### `docs/architecture.md`

架构文档。

说明主要组件、模型生命周期、Kubernetes 资源、metrics、扩缩容和故障处理。

### `docs/amd-interview-demo.md`

AMD 面试 demo 文档。

最初面向 AMD GPU 场景，但其中也包含通用的集群启动、Router 部署和请求流程。

### `docs/project-overview.md`

本文档。

用于说明项目整体结构和每个文件的作用。

---

## 9. 测试目录：`tests/`

### `tests/unit/`

Python 单元测试。

#### `tests/unit/test_client.py`

测试 Kubernetes client 初始化逻辑。

#### `tests/unit/test_errors.py`

测试自定义异常。

#### `tests/unit/test_job.py`

测试 Kubernetes Job 管理逻辑。

#### `tests/unit/test_lock.py`

测试 Kubernetes Lease 分布式锁。

#### `tests/unit/test_model.py`

测试模型路由逻辑，包括模型别名、自动部署、DNS 名称转换和请求转发。

#### `tests/unit/test_retry.py`

测试 retry 工具。

#### `tests/unit/test_server.py`

测试 FastAPI Router 接口。

#### `tests/unit/test_types.py`

测试 Pydantic 类型和校验逻辑。

#### `tests/unit/test_vllm.py`

测试 vLLM Helm operator，包括 Helm 参数、状态查询和 endpoint 生成。

### `tests/chart/`

Helm chart 渲染测试。

#### `tests/chart/conftest.py`

提供 `helm_template` fixture，用于执行 `helm template` 并检查渲染结果。

#### `tests/chart/test_llm_inference.py`

测试 `charts/llm-inference` 渲染。

覆盖：

- 默认资源渲染
- AMD GPU 资源
- NVIDIA GPU 资源
- CPU mode
- HF token Secret
- HF endpoint
- 本地 HF cache hostPath
- nodeSelector
- ingress
- HPA
- ServiceMonitor

#### `tests/chart/test_llm_router.py`

测试 `charts/llm-router` 渲染。

覆盖：

- Router Deployment / Service / ServiceAccount
- 模型 ConfigMap
- ClusterRole / ClusterRoleBinding
- Lease 权限
- replica 配置
- ingress
- HPA
- 移除无用的 `vllm-helm-extra` ConfigMap 挂载

### `tests/integration/`

端到端集成测试。

#### `tests/integration/conftest.py`

集成测试 fixture。

负责 kind 集群、Router 安装和 port-forward 等测试准备工作。

#### `tests/integration/test_e2e.py`

端到端测试。

验证 Router 是否可以：

1. 响应健康检查
2. 列出模型
3. 触发模型部署
4. 返回 chat completion

---

## 10. 运行时请求流程

一次 GPU 推理请求大致如下：

```text
1. Client 调用 Router /v1/chat/completions，model=qwen-0.5b。
2. Router 把 qwen-0.5b 映射到 Qwen/Qwen2.5-0.5B-Instruct。
3. Router 把 qwen-0.5b 转成合法 K8s 名称 qwen-0-5b。
4. Router 获取 Kubernetes Lease：deploy-qwen-0-5b。
5. Router 执行 helm upgrade --install qwen-0-5b charts/llm-inference。
6. Helm 创建 vLLM Deployment 和 Service。
7. vLLM Pod 请求 nvidia.com/gpu: "1"。
8. NVIDIA device plugin 分配 GPU。
9. containerd 根据 CDI spec 注入 GPU 设备和驱动库。
10. vLLM 从本地模型缓存或 hf-mirror.com 加载模型。
11. Router 把请求转发给 vLLM。
12. Router 把 OpenAI-compatible 响应返回给 Client。
```

---

## 11. 关键设计决策

### 按需部署模型

模型不是一开始全部启动，而是在首次请求时才部署。

好处：

- 节省 GPU
- 节省内存
- 避免不常用模型长期占资源

### 每个模型一个 Helm release

每个模型 alias 对应一组独立资源：

```text
qwen-0-5b
  -> Deployment
  -> Service
  -> ServiceAccount
```

这样每个模型可以独立部署、升级和删除。

### 使用 Lease 防止并发部署

多个 Router 副本同时收到同一个模型请求时，Kubernetes Lease 保证只有一个副本执行部署。

### 使用 CDI 支持 rootless GPU

rootless Docker 下传统 NVIDIA runtime 不好用。

CDI 让 containerd 能根据 CDI spec 标准化注入 GPU 设备和驱动库。

### 支持本地 Hugging Face 模型缓存

模型权重可以提前下载到：

```text
/work/run/projects/bio-24/k8s-llm-runtime/cache
```

GPU worker 通过 kind `extraMounts` 只读挂载该目录，vLLM Pod 再用 hostPath 挂载它。

配合：

```text
HF_HUB_CACHE
HF_HUB_OFFLINE=1
```

可以避免每次 Pod 启动都重新下载模型。

### Docker 专用依赖锁

项目不再跟踪仓库级 `uv.lock`。

Router 镜像依赖由下面文件固定：

```text
docker/requirements.lock
```

好处：

- 仓库更小
- 避免本地 mirror 污染 lockfile
- 镜像构建仍然可复现
