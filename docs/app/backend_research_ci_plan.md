# Backend Research CI 与 Go 后端迁移计划

## 结论

当前应新增轻量 Backend Research CI，但不做完整 Python 生产后端 CI/CD。

该 CI 的定位是保护现有 Python Advisor 后端、科研脚本、知识库数据与测试基线在 Go 后端迁移前不腐化。未来 Go 后端进入主线后，生产质量门禁应逐步迁移到 Go CI；Python CI 降级为 research/data baseline。

## 背景

前端已经有云端 CI，覆盖安装、lint、typecheck、test 与 build。当前后端仍以 Python Advisor API、RAG、模型路由、安全层、schema 校验与知识库数据为核心，但仓库尚无对应 GitHub Actions 门禁。

未来生产后端计划引入 Go 替换 Python，因此当前不应过度投入 Python 生产部署级 CI。但在替换完成前，Python 后端仍是：

- 当前前端联调与本地服务的事实基线。
- Go rewrite 的行为参考实现。
- 科研、RAG、知识库与评测数据的可复现载体。

## 分支策略

### 当前阶段

- `main`：稳定主线，包含前端、Python Advisor baseline、科研数据与文档。
- `ci/backend-research`：新增轻量 Backend Research CI 的工作分支，完成验证后通过 PR 或合并进入 `main`。

### Go 后端迁移阶段

- `feat/go-backend-skeleton` 或 `go-backend-migration`：Go 后端开发分支。
- Go 后端达到可对齐现有 API 后，加入 Go CI 与 Python/Go contract tests。
- Go 后端稳定后合并回 `main`。

### 生产发布阶段

- `production` 分支可选，仅作为部署门禁分支，不作为长期开发主线。
- 推荐流向：feature branches → `main` → release tag / `production` → deploy。

## 当前 Backend Research CI 范围

### 必须覆盖

- Python 语法检查：`python -m compileall scripts tests`。
- 后端关键 import smoke test：
  - `scripts.advisor.api.main`
  - `scripts.advisor.api.routes.chat`
  - `scripts.advisor.api.routes.models_routes`
  - `scripts.advisor.api.routes.knowledge`
- 轻量 pytest：
  - `tests/test_advisor_router_properties.py`
- 专用 smoke 脚本：
  - `scripts/advisor/backend_research_ci.py`
- Public JSONL 数据格式检查：
  - `advisor_out/knowledge/**/*.jsonl`
  - `scripts/advisor/*_eval_set.jsonl`

### 明确不覆盖

- 真实 API key。
- 本地大模型加载。
- 模型权重下载。
- 真实外部 LLM 调用。
- FAISS/BGE 重型向量构建。
- 生产部署、Docker 发布或数据库迁移。

## 成功标准

- GitHub Actions 在 `main` push 与 PR 上自动运行 Backend Research CI。
- CI 在无私有 secrets、无本地模型、无外部服务的云端环境中通过。
- 本地可用 `conda run -n wechatDHA` 复现等价检查。
- 后续 Python 后端、schema、router、知识库数据或核心测试被改坏时，CI 能变红。

## 迁移后的调整

Go 后端进入主线后：

- 新增 Go CI：`go test ./...`、`go vet ./...`、lint 与 API contract tests。
- Python Backend Research CI 继续保留一段时间，用作行为 baseline。
- Go 完成生产接管后，Python CI 可降级为 research/data CI，仅保留数据格式、脚本语法和关键科研测试。

## 当前执行计划

1. 创建 `ci/backend-research` 分支。
2. 新增 `.github/workflows/backend-research-ci.yml`。
3. 新增轻量 smoke 与 JSONL 格式检查脚本。
4. 本地运行 CI 等价命令。
5. 提交并推送分支。
6. 等云端 CI 通过后再合并或发起 PR。
