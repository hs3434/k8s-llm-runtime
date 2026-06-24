# k8s-llm-runtime — Developer Guidelines

## 项目概述

独立的 Python 库 + Helm chart 工具集，提供 Kubernetes 上 vLLM 模型服务的部署与调度能力。

## 开发规范

### 问题处理流程

1. **问题确认**：明确具体表现和影响范围
2. **问题重现**：尽可能重现，确保有明确复现步骤
3. **原因分析**：通过日志、监控数据等手段分析
4. **解决方案**：提出方案并评估可行性
5. **补充测试**：修复 / 新增功能时补对应测试
6. **提交 git**：commit 前跑 lint
7. **应用更新**：必要时重启 / `helm upgrade`

### 代码规范

| 规范 | 说明 |
|---|---|
| **Python** | PEP 8，类型提示必须 |
| **类型检查** | 库代码 `mypy --strict`；demo 代码宽松 |
| **单文件长度** | 单脚本建议 < 300 行；超过 500 行分模块 |
| **命名** | Python `snake_case`，YAML `camelCase` (Helm 习惯) |
| **格式化** | `ruff format` |
| **Lint** | `ruff check` |

### 测试规范

| 规范 | 说明 |
|---|---|
| **覆盖率** | `src/k8s_llm_runtime/` ≥ 80% |
| **金字塔** | unit / chart / integration / lint 四层 |
| **执行环境** | unit + chart 容器外跑；integration 在 kind 内 |

### Helm chart 规范

| 规范 | 说明 |
|---|---|
| **API 版本** | `apiVersion: v2`（Helm 3）|
| **资源命名** | `{{ include "<chart>.fullname" . }}` |
| **Labels** | 至少含 `app.kubernetes.io/{name,instance,managed-by}` |
| **可选组件** | 全部走 `enabled: false` 默认关 |
| **资源限制** | 生产默认 requests/limits 都设 |

### Git 规范

| 规范 | 说明 |
|---|---|
| **分支** | feature → main（无 develop，简化）|
| **Commit** | `type(scope): description` |
| **类型** | `feat`, `fix`, `docs`, `refactor`, `test`, `chore` |

## 技术栈

| 技术 | 用途 |
|---|---|
| Python 3.11+ | 主语言 |
| uv | 包管理 |
| kubernetes (官方 client) | K8s API |
| helm | Chart 包管理 |
| pydantic v2 | 数据模型 |
| fastapi + uvicorn | Router Web |
| structlog | JSON 日志 |
| prometheus_client | 指标 |
| tenacity | 重试 |

## 相关文档

- 设计稿：`learning-journey/docs/superpowers/specs/2026-06-24-k8s-llm-runtime-design.md`
- 实施计划：`learning-journey/docs/superpowers/plans/`（待生成）
- AMD 面试 demo 步骤：`docs/amd-interview-demo.md`（待生成）
