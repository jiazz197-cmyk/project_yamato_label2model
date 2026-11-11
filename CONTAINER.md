# 容器化开发参照（依赖 / 环境 / 文件取舍）

> 对应分支：training 收敛清理后。生成于 2026-11-11，依赖快照来自 `pyproject.toml` + 重新生成的 `poetry.lock`（Poetry 2.4.1）。

## 1. 现有环境管理文件还要不要

| 文件 | 结论 | 说明 |
|---|---|---|
| `pyproject.toml` | **保留（唯一依赖源）** | 60 个直接依赖（本轮删掉 sklearn/transformers/joblib）+ 构建入口/包配置；不要改成手写 requirements 为主。 |
| `poetry.toml` | **保留** | 配置了 SJTU PyPI 镜像（`https://mirror.sjtu.edu.cn/pypi/web/simple/`），容器内同样生效；网络变化时可用 `POETRY_REPOSITORIES_PYPI_URL` 覆盖。 |
| `poetry.lock` | **保留（已与 pyproject 同步）** | 旧 lock 自 `327da07`（新增 ultralytics）起就与 pyproject 不一致；现已用 Poetry 2.4.1 重新生成两轮：① 移除 celery 依赖树（10 个包）、新增 ultralytics 依赖树（13 个包）；② 移除 sklearn/transformers/joblib 直接依赖（连带删除 11 个包名：scikit-learn、transformers、scipy、tokenizers、safetensors、huggingface-hub、hf-xet、narwhals、typer、shellingham、threadpoolctl）。当前 lock：249 条目 / 245 个包名，其余包版本零漂移；`joblib` 仍作为 `label-studio-sdk -> nltk` 的传递依赖保留。 |
| `Makefile` | **保留（本地开发）** | `docker-*` target 引用的 `Dockerfile`、`docker-compose.yml`、`.env.development` 在仓库中**均不存在**，容器化时需补齐或删除这些 target。 |
| `label_studio/pytest.ini` | **保留** | 容器内跑测试/CI 需要。 |
| `.env` | **缺失，需新建** | `core/settings/label_studio.py` 启动时从**仓库根目录** `.env` 读取；建议提交一份 `.env.example`。 |
| `Dockerfile` / `docker-compose.yml` / `.dockerignore` | **缺失，需新建** | 仓库历史上没有（只有 Makefile 里的引用）。 |
| `web/dist`、`label_studio/core/static_build` | **未提交** | 前端产物不在仓库，镜像需要 Node 构建阶段（或开发时挂载预构建产物）。 |

**结论：保留 Poetry 链路**（`pyproject.toml` + `poetry.toml` + 已修复的 `poetry.lock`），容器内用：

```bash
pip install --no-cache-dir poetry==2.4.1
poetry install --no-root --no-interaction
```

如果之后想改用 pip / uv 构建镜像，不要手写 requirements，从 lock 导出（需 `poetry-plugin-export`）：

```bash
poetry self add poetry-plugin-export
poetry export --format requirements.txt --without-hashes --without-urls -o requirements.txt
# torch 的 cu128 wheel 需要额外索引（见第 3 节）
```

## 2. 依赖分组（按镜像拆分）

### A. Django 应用镜像（CPU，LS 运行时）

`pyproject.toml` 主依赖中除去 trainer 专用项后的全部内容：

- Web/框架：`Django`、`djangorestframework`、`djangorestframework-simplejwt[crypto]`、`drf-*` 系列、`django-*` 系列（`django-filter`、`django-rq`、`django-storages`、`django-environ`、`django-extensions`、`django-cors-headers`、`django-user-agents`、`django-ranged-fileresponse`、`django-annoying`、`django-debug-toolbar`、`django-csp`、`django-migration-linter`）
- 数据/IO：`lxml[html-clean]`、`defusedxml`、`numpy`、`pandas`、`pyarrow`、`psycopg[binary]`、`ijson`、`ujson`、`xmljson`、`pyyaml`
- 异步/缓存/队列：`rq`、`django-rq`、`redis`（LS 原生异步功能；训练队列改为 RQ 后 Django 侧只需调用 trainer HTTP，**不再需要 celery**）
- 基础设施/杂项：`boto3`、`botocore`、`requests`、`rules`、`pydantic`、`openai`、`sentry-sdk`、`launchdarkly-server-sdk`、`google-cloud-logging`、`python-json-logger`、`colorama`、`pyboxen`、`ordered-set`、`bleach`、`cryptography`、`python-dateutil`、`pytz`、`setuptools`、`tldextract`、`uuid-utils`、`appdirs`、`attr`、`attrs`、`wheel`
- 私有/直链：`label-studio-sdk @ https://github.com/HumanSignal/label-studio-sdk/archive/54d1aeca71fe7b572c8028e7fe82c4b54457e8f0.zip`

### B. trainer 侧车镜像（YOLO，GPU/CPU）

- `torch (>=2.11,<3)`（当前锁为 `2.11.0+cu128`，来源见第 3 节）
- `ultralytics (>=8.3,<9)`
- `fastapi`、`uvicorn[standard]`（yolo-3 的 trainer API）
- 运行时常用：`requests`、`pyyaml`、`redis`（RQ worker）

> **已确认：trainer 与 Django 共用同一套依赖环境，暂不拆分。** 因此 app/worker 镜像也会带上 `torch`(CUDA)/`ultralytics`/`fastapi`，镜像体积会明显变大（torch cu128 数 GB）；如果后续想瘦身，再把这几项挪到 `[dependency-groups] trainer` 或独立 `trainer/pyproject.toml`，然后重新 lock。

### C. 测试 / CI 组（`[tool.poetry.group.test.dependencies]`）

`pytest`、`pytest-cov`、`pytest-django`、`pytest-mock`、`pytest-env`、`pytest-xdist`、`tavern`、`fakeredis`、`responses`、`requests-mock`、`factory-boy`、`freezegun`、`mock`、`moto`、`psutil`、`pre-commit`、`s3transfer`

### D. 已移除的遗留依赖（本轮完成）

- `scikit-learn`、`transformers`：全仓库无 import，且「不做 HF/sklearn」已定，已从 pyproject 删除。
- `joblib`：直接依赖已删除；但 `label-studio-sdk -> nltk -> joblib` 的传递依赖仍会安装（不是本项目的直接依赖，无需处理）。
- `celery` 依赖树此前已随训练队列删除（不再需要）。

## 3. 特殊依赖与源（构建镜像时注意）

- **torch CUDA 源**：`pyproject.toml` 声明
  ```toml
  [[tool.poetry.source]]
  name = "pytorch-cu128"
  url = "https://mirror.sjtu.edu.cn/pytorch-wheels/cu128/"
  priority = "explicit"
  ```
  当前锁是 `torch 2.11.0+cu128`。**CPU-only 镜像**需替换/移除该 source 并重新 lock，否则会装 CUDA 版（数 GB）。
- **label-studio-sdk**：GitHub archive zip 直链依赖，构建时需要 GitHub 网络；建议在 builder 阶段缓存或配置代理。
- **PyPI 镜像**：`poetry.toml` 指向 SJTU；CI/容器网络不通时可覆盖：
  ```bash
  export POETRY_REPOSITORIES_PYPI_URL=https://pypi.org/simple/
  ```
- **二进制 wheel**：`psycopg[binary]`、`lxml`、`numpy`、`pyarrow`、`cryptography` 均有 manylinux wheel，`python:3.12-slim` 一般无需编译工具链。
- **Python**：README 要求 3.12；`requires-python = ">=3.10,<4"`，建议镜像固定 3.12。
- **前端工具链**：Node 22 + Yarn 1.22.22（`web/package.json` 的 `packageManager`），`cd web && yarn build` 产出 `web/dist`（`EDITOR_ROOT`/`REACT_APP_ROOT` 读取）。

## 4. 关键环境变量（`.env.example` 参照）

> `.env` 放在**仓库根**；`core/settings/label_studio.py` 启动时读取。以下为容器化最常用子集，完整列表见 `label_studio/core/settings/*.py`。

```dotenv
# --- 基础 ---
# 默认 postgresql；用 sqlite 时显式 DJANGO_DB=sqlite
DJANGO_DB=postgresql
# 默认 appdirs 的 ~/.local/share/label-studio，容器内务必显式指到挂载卷
BASE_DATA_DIR=/label-studio/data
# HOST 必须带 scheme；影响 CORS/前端 URL
HOST=http://localhost:8080
DEBUG=0
LOG_LEVEL=INFO
COLLECT_ANALYTICS=0

# --- PostgreSQL ---
POSTGRE_HOST=postgres
POSTGRE_PORT=5432
POSTGRE_USER=labelstudio
POSTGRE_PASSWORD=changeme
POSTGRE_NAME=labelstudio

# --- Redis / RQ（LS 原生异步 + trainer 队列共用）---
REDIS_ENABLED=1
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0
RQ_DEFAULT_TIMEOUT=180
# 长任务超时（导入/导出等）
RQ_LONG_JOB_TIMEOUT=86400

# --- MinIO / 对象存储（若沿用远程中间件可不填）---
# MINIO_STORAGE_ENDPOINT=http://minio:9000
# MINIO_STORAGE_BUCKET_NAME=labelstudio
# MINIO_STORAGE_ACCESS_KEY=minioadmin
# MINIO_STORAGE_SECRET_KEY=minioadmin
# 不需要 MinIO 时显式跳过
MINIO_SKIP=1

# --- 训练 / trainer 侧车 ---
# 本地模型与训练产物根目录；app 与 trainer 必须共享该卷
LOCAL_MODEL_ROOT=/label-studio/data/models
TRAINING_ARTIFACTS_STORAGE_PREFIX=trained
TRAINING_UPLOAD_MAX_SIZE=2147483648
TRAINING_UPLOAD_CHUNK_SIZE=8388608
TRAINING_SAMPLE_SIZE=100
TRAINING_PROGRESS_REDIS_CHANNEL=training:progress
TRAINING_YOLO_VAL_SPLIT=0.2
PREDICTOR_PORT=8990

# --- 可选 ---
# SENTRY_DSN=
# FRONTEND_SENTRY_DSN=
# ENABLE_LOCAL_FILES_STORAGE=0
# LOCAL_FILES_DOCUMENT_ROOT=/label-studio/data
# USE_ENFORCE_CSRF_CHECKS=1
```

## 5. 推荐容器拓扑

| 服务 | 作用 | 备注 |
|---|---|---|
| `app` | Django/DRF + 静态资源 | dev 可用 `runserver 0.0.0.0:8080`；prod 建议 gunicorn/uwsgi |
| `worker` | Label Studio 原生 RQ worker | 由 `django-rq` 提供：`python label_studio/manage.py rqworker`（队列名见 `RQ_QUEUES`：critical/high/default/low） |
| `trainer` | FastAPI + RQ worker（yolo-3） | GPU；监听 `PREDICTOR_PORT`，与 app 共享 `LOCAL_MODEL_ROOT` 与同一 Redis；**可直接复用 app 镜像**（同一 lock/依赖环境），用 GPU + 不同启动命令 |
| `postgres` | 数据库 | |
| `redis` | RQ 队列 + pub/sub 进度 | |
| `minio` | 对象存储（可选） | README 说明中间件已在远程部署，可复用远程实例 |

共享卷：`BASE_DATA_DIR`（media/sqlite/export/trained）、`LOCAL_MODEL_ROOT`；`web/dist` 只读挂载或构建进 app 镜像。

## 6. 常用命令

```bash
# 依赖（pyproject 变更后必跑）
poetry lock
poetry install --no-root

# 前端（Node 22 + Yarn 1.22）
cd web && yarn install --frozen-lockfile && yarn build && cd ..

# 后端
python label_studio/manage.py migrate
python label_studio/manage.py collectstatic --no-default-ignore
python label_studio/manage.py runserver 0.0.0.0:8080

# 检查/测试
python label_studio/manage.py check
python label_studio/manage.py makemigrations --check --dry-run
cd label_studio && DJANGO_DB=sqlite pytest -c pytest.ini ../training/tests
```

## 7. 容器化待补文件清单

1. `Dockerfile`（app）：多阶段 → Node 构建 `web/dist` → 安装 Python 依赖 → 精简 runtime（非 root 用户；`BASE_DATA_DIR` 卷）
2. trainer 服务：**复用 app 镜像**（依赖共用，已确认不分拆），compose 里加 GPU 资源 + 不同启动命令即可；若以后想瘦身再单独 `Dockerfile.trainer`
3. `docker-compose.yml`：app / worker / trainer / postgres / redis[/minio] + volumes
4. `.dockerignore`：至少排除 `.git`、`node_modules`、`data/`、`mydata/`、`tmp/`、`.venv`、`.tools`、`__pycache__`、`*.pyc`、`label_studio.sqlite3`、`web/dist` 之外的本地产物
5. `.env.example`：按第 4 节整理
6. 清理/修复 `Makefile` 的 `docker-*` target（当前引用的 Dockerfile/compose/`.env.development` 都不存在）

## 附：Makefile 说明（target / 缺失前置文件）

### 它是什么

`Makefile` 是 GNU make 的任务脚本，不是 C 项目的编译文件。它把一长串开发命令（poetry / yarn / docker compose）封装成短命令：

- **target（目标）**：形如 `名字:` 的一行，下面用 **Tab 缩进**写要执行的命令。`make 名字` 就会运行那段命令。
- **依赖**：`名字: 依赖1 依赖2` 表示先执行依赖 target 再执行自己的命令（例如 `docker-dev-setup: env-dev-setup docker-dev-override`、`frontend-build: frontend-setup`）。
- 不带参数跑 `make` 会执行**第一个 target**（本文件是 `run-dev`）。
- `make -n <target>` 只打印要执行的命令、不真正执行，适合先检查。
- 本文件所有 target 都是「伪目标」（不对应真实文件），但**没有声明 `.PHONY`**——如果哪天仓库里出现和 target 同名的文件，make 会认为"已是最新"而跳过。建议后续补上 `.PHONY:` 列表。

### 现有 target 一览

| target | 作用 | 前置条件 | 当前仓库可用性 |
|---|---|---|---|
| `run-dev` | 本地 Django dev server（sqlite） | poetry 环境 | 本容器无依赖，跑不了；有 poetry 环境的主机可用 |
| `migrate-dev` | 跑 migration（sqlite） | poetry 环境 | 同上 |
| `makemigrations-dev` | 生成 migration | poetry 环境 | 同上 |
| `shell-dev` | Django shell_plus | poetry 环境 | 同上 |
| `env-dev-setup` | 若无 `.env` 则从 `.env.development` 复制 | `.env.development` | ❌ 文件缺失 |
| `docker-dev-override` | 若无 override 则复制模板 | `docker-compose.override.example.yml` | ❌ 文件缺失 |
| `docker-dev-setup` | = `env-dev-setup` + `docker-dev-override` | 上面两个文件 | ❌ |
| `docker-run-dev` | `docker compose up --build` | `docker-compose.yml`、`Dockerfile` | ❌ 都缺失 |
| `docker-migrate-dev` | `docker compose run app ... migrate` | 同上 | ❌ |
| `docker-collectstatic-dev` | `docker compose run app ... collectstatic` | 同上 | ❌ |
| `frontend-install` / `frontend-setup` | `cd web && yarn install --frozen-lockfile` | node + yarn + 网络 | ❌ 本容器没有 yarn |
| `frontend-dev` | `yarn run dev`（HMR） | `web/node_modules` | ❌ 需先 install |
| `frontend-watch` | `yarn run watch` | `web/node_modules` | ❌ |
| `frontend-build` | = `frontend-setup` + `yarn run build` | 同上；产物 `web/dist` | ❌ |
| `frontend-storybook-serve` | = `frontend-setup` + `yarn run ui:serve` | 同上 | ❌ |
| `test` | `cd label_studio && pytest -v -m "not integration_tests"` | poetry 环境 + test 组依赖 | ❌ 本容器无依赖 |
| `build-testing-image` | 构建 app / testing 镜像 | `Dockerfile`、`Dockerfile.testing` | ❌ 都缺失 |
| `docker-testing-shell` | 起测试镜像交互 shell | 先 `build-testing-image` | ❌ |
| `update-urls` | `manage.py show_urls` 重写 `label_studio/core/all_urls.json` | poetry 环境 | ❌ 本容器；有环境时可用 |
| `generate-swagger` | `manage.py generate_swagger swagger.json` | poetry 环境 | ❌ 本容器 |
| `fmt` / `fmt-all` | pre-commit 手动格式化 | `pre-commit` 命令 + `.pre-commit-dev.yaml` | ❌ 都缺失 |
| `fmt-check` / `fmt-check-all` | pre-commit pre-push 检查 | `pre-commit` + `.pre-commit-config.yaml` | ❌ 都缺失 |
| `configure-hooks` | 安装 pre-push hook | 同上 | ❌ |

### Makefile 引用但仓库缺失的文件（均未在本仓库 git 历史中出现过）

`Makefile` 是从上游 Label Studio 继承的，但初始导入时没带上下列文件：

| 缺失文件 | 影响的 target |
|---|---|
| `.env.development` | `env-dev-setup`、`docker-dev-setup` |
| `docker-compose.yml` | `docker-run-dev`、`docker-migrate-dev`、`docker-collectstatic-dev` |
| `docker-compose.override.example.yml` | `docker-dev-override`、`docker-dev-setup` |
| `Dockerfile` | `docker-run-dev`、`build-testing-image` |
| `Dockerfile.testing` | `build-testing-image` |
| `.dockerignore` | 无 target 直接依赖，但缺了会把整个仓库塞进构建上下文 |
| `.pre-commit-dev.yaml` | `fmt`、`fmt-all` |
| `.pre-commit-config.yaml` | `fmt-check`、`fmt-check-all`、`configure-hooks` |

其他未安装项（不是文件）：`pre-commit` 命令、`yarn`、poetry 环境、`web/node_modules`。`swagger.json` 是 `generate-swagger` 的输出产物，无需预先存在。
