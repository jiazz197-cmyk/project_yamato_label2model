# 容器化开发技术参考（依赖 / 镜像 / 挂载 / 边界）

> 对应实现：**dev-first** 重构后的开发环境。日常使用看 [README.md](README.md)；本文记录构建阶段、依赖与缓存、挂载与 profile、前端 HMR 链路、训练架构边界、已知限制和本机验证结果。
>
> 实现以仓库中的 `Dockerfile`、`docker-compose.yml`、`Makefile`、`.env.example`、`.devcontainer/devcontainer.json` 为准；若本文与这些文件冲突，以后者为准。

## 1. 文件取舍

| 文件 | 结论 | 说明 |
|---|---|---|
| `Dockerfile` | **保留（dev-first 多阶段）** | 阶段：`web-deps` → `web` / `web-dev`；`python-deps` → `runtime` → `app` → `ml`。镜像只装依赖与工具链，源码由 compose 挂载。 |
| `docker-compose.yml` | **保留（开发编排）** | 默认 5 个服务；`ml` profile 增加 `ml-api`、`ml-worker`，共 7 个。`docker-compose.override.example.yml` 已删除，不再需要手工复制 override。 |
| `.devcontainer/devcontainer.json` | **新增** | 复用 compose 的 `app` 服务，推荐入口；细节见附录 B。 |
| `docker-compose.devcontainer.yml` | **新增** | 仅 devcontainer 叠加：把仓库根目录挂到 `/label-studio`，使 web/services/pyproject 可直接编辑。 |
| `.env.example` | **保留（可选模板）** | 不复制也能用 compose 内置开发默认值；生产必须覆盖敏感项。 |
| `Makefile` | **更新（dev-first）** | 默认目标 `dev-up`；新增 `dev-*` / `ml-*`，旧 `docker-*` 保留为别名。 |
| `services/ml_api/` | **新增** | FastAPI 训练域：`app.py`（接口）、`models.py` / `db.py`（SQLAlchemy）、`migrations/`（Alembic）、`db_bootstrap.py`、`jobs.py`（RQ 作业）、`yolo.py` / `yolo_adapter.py`（由 Django training 迁入）。 |
| `services/requirements-ml.txt` | **新增** | 仅 ml 镜像安装：`ultralytics`、`fastapi`、`uvicorn[standard]`、`SQLAlchemy`、`alembic`、`psycopg[binary]`、`httpx`；torch/torchvision 由 Dockerfile 按索引单独安装。 |
| `docker/` | **更新** | `docker-entrypoint.sh`（仅 app 执行迁移 + MinIO 初始化）、`ml-api-start.sh`（先 Alembic 引导再启动 uvicorn）、`init_minio.py`、`healthcheck-worker.py`、`ensure_admin_org.py`（为 `createsuperuser` 用户补组织）。 |
| `models/` | **保留** | 仅跟踪 `.gitkeep`；宿主机目录绑定到 `/models`，app / ml-api / ml-worker 共享。 |
| `pyproject.toml` / `poetry.lock` / `poetry.toml` | **保留（app 依赖唯一来源）** | app 依赖 + `test` 组；训练依赖已移出，改由 ml 镜像的 `requirements-ml.txt` 提供。 |
| `.dockerignore` | **保留** | 排除 `.git`、`.devcontainer`、`.env`、`docs`、`models`、`web/node_modules`、`web/dist`、运行数据与缓存。 |
| `web/` | **保留** | `web-deps` 安装 `node_modules`；`web-dev` 镜像烘焙依赖与构建配置，compose 只挂载源码目录。 |
| `training/` | **已删除** | 训练域（BaseModel / TrainingJob / API / YOLO 数据集与适配器）完整迁移到 `services/ml_api`；Django 只保留 `/api/training/` 网关。 |
| 旧 `services/trainer`、`services/predictor`、`services/requirements-trainer.txt` | **已删除** | 统一合并到 `services/ml_api` 与 `services/requirements-ml.txt`。 |

**结论**：app 使用 Poetry 安装（main + test 组）；ml 侧车在 app 镜像基础上用固定版本 requirements + torch 索引安装；源码全部通过挂载进入开发容器，镜像不随日常改代码重建。

## 2. 构建阶段与缓存

### 2.1 阶段一览

| 阶段 | 基础镜像 | 作用 | 关键动作 / 缓存键 |
|---|---|---|---|
| `web-deps` | `node:22.19.0-bookworm-slim` | 安装前端依赖 | 校验镜像自带 yarn 1.22.22；`yarn install --frozen-lockfile`；缓存键主要是 `web/package.json` + `web/yarn.lock` |
| `web` | `FROM web-deps` | 构建生产前端产物 | `COPY web/` → `yarn build`，产物 `web/dist`，供 `app` 镜像兜底 |
| `web-dev` | `FROM web-deps` | 前端 HMR 开发服务器 | `COPY web/` → 默认 `yarn dev --host 0.0.0.0`；`node_modules` 与配置烘焙在镜像中 |
| `python-deps` | `python:3.12.16-slim-bookworm` | 安装后端依赖 | Poetry 2.4.1 + `virtualenv==20.26.6`；`poetry install --no-root --only main,test`，失败自动重试 5 次 |
| `runtime` | 同 Python 镜像 | 运行时公共层 | 只装 `ca-certificates`、`curl`、`tini`，复制 Python 依赖 |
| `app` | `FROM runtime` | Django 运行镜像 | 复制源码与 `web/dist`、可编辑安装项目自身（`pip install -e .`）、构建期 `collectstatic`、非 root 用户 |
| `ml` | `FROM app` | 训练/推理侧车镜像 | 安装 OpenCV 所需系统库、torch/torchvision（按索引固定版本）、`services/requirements-ml.txt` |

`app` 与 `ml` 固定 Python 3.12.16；`ml-api` 与 `ml-worker` 共用 `ml` 镜像，仅启动命令不同。

### 2.2 依赖与源

| 项 | 值 / 说明 |
|---|---|
| Python | `3.12.16-slim-bookworm` |
| Node | `22.19.0-bookworm-slim`（镜像自带 yarn 1.22.22，构建时校验） |
| Poetry | `2.4.1`；额外固定 `virtualenv==20.26.6`，安装失败自动重试 |
| app 依赖范围 | `pyproject.toml` main 组 + test 组；build 组与 `uwsgi` extra 不安装 |
| PyPI | `pyproject.toml` 中 `tuna` source（primary）+ `poetry.toml`；Dockerfile 可用 `POETRY_PYPI_URL` 覆盖为其他索引 |
| npm/yarn | 默认 `YARN_REGISTRY=https://registry.npmmirror.com`；构建时替换 `yarn.lock` 中的 registry 前缀并 `yarn config set registry` |
| APT | 默认 `APT_MIRROR=http://mirrors.tuna.tsinghua.edu.cn`，构建时替换 Debian sources |
| torch / torchvision | 默认 `TORCH_INDEX_URL=https://mirrors.nju.edu.cn/pytorch/whl/cpu`；版本 `TORCH_VERSION=2.11.0`、`TORCHVISION_VERSION=0.26.0`；CUDA 变体改索引即可 |
| ml 额外依赖 | `ultralytics==8.4.118`、`fastapi==0.141.1`、`uvicorn[standard]==0.52.4`、`SQLAlchemy==2.0.36`、`alembic==1.14.0`、`psycopg[binary]==3.2.10`、`httpx==0.28.1` |

`torch` 安装命令使用 `--index-url ${TORCH_INDEX_URL}` + `--extra-index-url ${ML_PIP_INDEX_URL}`，因此所选 torch 索引中必须存在对应版本，其余依赖由 PyPI 镜像解析。国内网络下默认南京大学 CPU 索引；无法访问时可改回 `https://download.pytorch.org/whl/cpu` 或自建/其他镜像。

### 2.3 构建参数

| build arg | 默认 | 用途 |
|---|---|---|
| `APP_UID` / `APP_GID` | `1000` | 容器内 `app` 用户；与宿主机 `./models` 属主匹配 |
| `POETRY_PYPI_URL` | 清华 PyPI | Poetry 安装索引 |
| `ML_PIP_INDEX_URL` | 清华 PyPI | ml 镜像 pip 安装索引 |
| `YARN_REGISTRY` | npmmirror | 前端依赖 registry |
| `APT_MIRROR` | 清华 APT 镜像 | 系统包加速；置空则用默认源 |
| `TORCH_INDEX_URL` | 南京大学 CPU 索引 | torch/torchvision 索引；CUDA 示例 `https://download.pytorch.org/whl/cu128` |
| `TORCH_VERSION` / `TORCHVISION_VERSION` | `2.11.0` / `0.26.0` | 固定训练框架版本 |
| `PYTHON_IMAGE` / `NODE_IMAGE` | 固定版本镜像 | 基础镜像替换入口 |

app 镜像构建期执行 `collectstatic`（临时 sqlite、跳过 MinIO，不依赖数据库），运行期由 `runserver` 的 staticfiles 服务提供静态文件；ml 阶段 `RUN_STARTUP_TASKS=0`，不会执行 Django 迁移或 MinIO 初始化。ml-api 启动脚本会单独执行训练域 Alembic 引导（见 5.2）。

### 2.4 镜像体积（本机构建结果）

| 镜像 | 体积 | 说明 |
|---|---|---|
| `yamato/label-studio-app:dev` | ≈ 1.52 GB | Django + Python 依赖 + `web/dist` + 静态文件 |
| `yamato/label-studio-ml:dev` | ≈ 3.65 GB | app 基础 + CPU 版 torch/torchvision + ultralytics 等 |
| `yamato/label-studio-web-dev:dev` | ≈ 9.66 GB | `node_modules` 烘焙在镜像中，启动即 HMR，体积偏大 |

体积会随依赖版本与构建缓存变化，以上为本机 `docker images` 显示值。`web-dev` 的瘦身方向是把 `node_modules` 改为命名卷缓存，但会牺牲「启动即可用」，暂未实施。

### 2.5 缓存与重建的关系

- 依赖层位于 `COPY` 源码之前：只改源码不会使 `web-deps` / `python-deps` 层失效，重建主要复用缓存。
- 开发时源码通过 bind mount 覆盖镜像内副本，因此**镜像内的源码副本不是日常开发输入**；它只用于没有挂载的场景（如 `web/dist` 兜底）。
- `app` 镜像包含项目自身（可编辑安装）与 `web/dist`；改前端后若想让「回退静态资源」也更新，需要重建 `app`。
- `.dockerignore` 排除了 `models`、`web/node_modules`、`web/dist`、`.devcontainer` 等，构建上下文较小。

## 3. 挂载与 profile 拓扑

### 3.1 默认开发栈（5 个服务）

```bash
docker compose up -d        # 或 make dev-up / make
```

| 服务 | 启动命令 | 端口 | 挂载 | 健康检查 |
|---|---|---|---|---|
| `postgres` | 官方镜像默认入口 | 5432 | `pgdata` | `pg_isready` |
| `redis` | `redis-server --appendonly yes` | 6379 | `redisdata` | `redis-cli ping` |
| `minio` | `server /data --console-address :9001` | 9000 / 9001 | `miniodata` | `/minio/health/live` |
| `app` | `python label_studio/manage.py runserver 0.0.0.0:8080` | 8080 | `appdata`、`./models`、`./label_studio` | `curl /health/` |
| `web` | `yarn dev --host 0.0.0.0` | 8010 | `./web/apps`、`libs`、`tools`、`scripts` | `node fetch /react-app/` |

`app` 启动时由 entrypoint 自动迁移并幂等创建 MinIO bucket；`web` 首次启动需要编译，健康检查 `start_period` 为 300 秒。

### 3.2 ml profile（额外 2 个服务）

```bash
docker compose --profile ml up -d     # 或 make ml-up（带 --build）
```

| 服务 | 启动命令 | 端口 | 挂载 | 依赖 |
|---|---|---|---|---|
| `ml-api` | `ml-api-start.sh --reload --reload-dir /label-studio/services`（脚本先执行 `python -m services.ml_api.db_bootstrap`，再启动 uvicorn） | 8991 | `./services`、`./models` | postgres + redis healthy |
| `ml-worker` | `rq worker training --url redis://redis:6379/0 --name ml-worker` | — | `./services`、`./models` | redis + ml-api healthy |

`ml-api` 的健康检查是 `GET /health`；`ml-worker` 的健康检查用 `docker/healthcheck-worker.py` 确认名为 `ml-worker` 的 RQ worker 已注册。`make ml-down` 只停止这两个服务，默认 5 个服务不受影响。

### 3.3 网络与数据

- 全部服务在 bridge 网络 `yamato-net` 上，服务名即 DNS（`web` 容器用 `http://app:8080` 代理 Django）。
- 命名卷：`pgdata`、`miniodata`、`appdata`、`redisdata`；`docker compose down` 保留，`down -v` 删除。
- 宿主机 `./models` 绑定到 `/models`，`down -v` 不会删除；基模与训练产物都放这里。
- `app` 启动时执行 Django 迁移（`RUN_STARTUP_TASKS=1`）；`ml-api` 启动时执行训练域 Alembic 引导（新库建表 / 旧库 stamp），`ml-worker` 的 `RUN_STARTUP_TASKS=0`，不执行任何迁移。

## 4. 前端 HMR 链路

### 4.1 环境变量与数据流

| 变量 | 默认 | 作用 |
|---|---|---|
| `FRONTEND_HMR` | `1` | `app` 是否把前端资源指向 dev server；置 `0` 则使用镜像内 `web/dist` |
| `FRONTEND_HOSTNAME` | `http://localhost:8010` | **浏览器**访问 HMR 资源的地址，Django 模板用它拼接 `/react-app/...` |
| `DJANGO_HOSTNAME` | `http://app:8080` | **web 容器内部** webpack-dev-server 的代理目标，不是浏览器地址 |
| `WEB_PORT` | `8010` | `web` 服务宿主机端口 |
| `HOST` | `http://localhost:8080` | Django 自身对外地址（登录跳转、绝对 URL 等） |

链路：

1. 浏览器打开 8080 的 Django 页面，模板引用 `FRONTEND_HOSTNAME/react-app/*`。
2. 浏览器从 8010 拉取 webpack dev server 资源，`publicPath` 为 `/react-app/`。
3. 前端请求 `/api/...` 由 webpack dev server 代理到 `http://app:8080/api/...`；其他请求代理到 `http://app:8080`。
4. 修改挂载目录内的前端源码，webpack 自动重新编译，HMR 推送到浏览器。

### 4.2 远程 / 局域网访问

- `FRONTEND_HOSTNAME` 必须是**浏览器可达**的地址；跨机访问时改成 `http://<宿主机IP>:8010`，同时把 `HOST` 改成 `http://<宿主机IP>:8080`。
- `DJANGO_HOSTNAME` 保持容器内部地址 `http://app:8080`，不要用外网地址覆盖。
- VS Code Dev Containers 会把 8080/8010/8991/9000/9001/5432/6379 转发到本机，使用 `localhost` 即可。

### 4.3 为什么 web 配置改动要重建

`web` 服务只挂载了 `web/apps`、`web/libs`、`web/tools`、`web/scripts`。以下文件来自 `web-dev` 镜像，修改后必须重建 `web`：

- `web/package.json`、`web/yarn.lock`（依赖）
- `web/webpack.config.js`、`web/nx.json`、`web/tsconfig*.json` 等构建配置
- 其他未列入挂载的 `web/` 根目录文件

```bash
docker compose build web
docker compose up -d web
```

## 5. 训练架构边界

### 5.1 职责划分

| 组件 | 职责 | 状态 |
|---|---|---|
| Django `app` | 标注、项目、用户/组织、鉴权、页面渲染；`/api/training/` 只做薄网关 | 正常 |
| `services/ml_api`（8991） | 训练域唯一实现：BaseModel / TrainingJob 模型与接口、Alembic 迁移、YOLO 数据集/适配器 | CRUD 可用；训练执行与推理为 501 占位 |
| RQ `ml-worker` | 消费 `training` 队列 | `ping` 可用；训练执行为 `NotImplementedError` |
| 原 `predictor` | 预标注推理 | 已合并进 `ml-api`，旧服务已删除 |
| 旧 Django `training/` app | 原训练模型/API/数据集代码 | **已删除**，代码迁入 `services/ml_api` |

### 5.2 数据与表结构

- ORM：SQLAlchemy 2.0；表名/列名完全沿用 Django 版本：`training_base_model`、`training_job`，存量库无需搬数据。
- 迁移：Alembic，版本文件在 `services/ml_api/migrations/versions/`。
- 启动引导：`docker/ml-api-start.sh` 先执行 `python -m services.ml_api.db_bootstrap`，再启动 uvicorn。
  - 全新库：执行 `alembic upgrade head` 建表；
  - 旧库（已有 `training_base_model`、但没有 `alembic_version`）：`alembic stamp head`，不重建、不丢数据；
  - 已有 `alembic_version`：正常 `upgrade head`。
- `project_id` / `organization_id` / `created_by_id` 是跨域引用，按整数保存，不加数据库外键（由 API 层用 `project` 表只读映射校验组织）。
- 组织隔离：Django 网关把 `X-User-Id`、`X-Organization-Id` 传给 ml-api；ml-api 按组织过滤并在跨组织详情/创建时返回 403。

### 5.3 ml-api 接口

| 方法/路径 | 鉴权 | 现状 |
|---|---|---|
| `GET /health` | 不需要 | `{"status":"UP","service":"ml-api"}` |
| `GET /api/training/base-models` | `X-Internal-Token` | 本组织 + 服务器预置的活跃基模列表 |
| `GET /api/training/base-models/{id}` | `X-Internal-Token` | 详情；跨组织 403 |
| `GET /api/training/base-models/scan` | `X-Internal-Token` | 扫描 `LOCAL_MODEL_ROOT` 下的 YOLO 目录 |
| `GET /api/training/jobs` | `X-Internal-Token` | 本组织任务列表；支持 `?project=<id>` |
| `POST /api/training/jobs` | `X-Internal-Token` | 201 创建任务记录（`status=Pending`） |
| `GET /api/training/jobs/{id}` | `X-Internal-Token` | 详情；跨组织 403 |
| `PATCH /api/training/jobs/{id}` | `X-Internal-Token` | 仅支持 `{"action":"cancel"}` |
| `GET /api/training/queue` | `X-Internal-Token` | 200：`{"queue":"training","count":<int>}`；Redis 不可用 503 |
| `POST /api/predictions` | `X-Internal-Token` | 501 占位（原 predictor 路由合并至此） |

- 令牌环境变量为 `ML_API_INTERNAL_TOKEN`；为空时回退 `TRAINER_INTERNAL_TOKEN`；两者都为空则关闭校验（仅便于本地开发）。
- `/docs`、`/redoc`、`/openapi.json` 均关闭，避免绕过内部令牌读取接口定义。
- 任务创建后只落库，不会自动入队执行；真实训练执行由 yolo-3 接入。

### 5.4 Django 网关

- `label_studio/core/training_api.py`：保留 `/api/training/` 原路径与响应结构，前端/调用方无需改动。
- 鉴权仍由 Django 负责：未登录在 Django 层被拒绝（401/403）；登录后带内部令牌与用户/组织头转发。
- FastAPI 的 422（请求体校验失败）在网关映射为原 DRF 的 400；ml-api 不可达时返回 503 并提示启动 ml profile。

### 5.5 与旧实现的差异

| 旧实现 | 现在 |
|---|---|
| 源码烘焙进镜像，改代码需重建 | 源码 bind mount，改代码即时生效；只有依赖/配置变化才重建 |
| 默认 4 个服务（postgres/redis/minio/app） | 默认 5 个（增加 `web` HMR 服务） |
| `trainer` / `trainer-worker` / `predictor` 三个侧车 | `ml-api` / `ml-worker` 两个服务，共用 ml 镜像；predictor 合并 |
| Django `training/` app 持有模型、API 与迁移 | 训练域全部迁入 FastAPI + SQLAlchemy/Alembic；Django 仅剩网关 |
| `services/requirements-trainer.txt` | `services/requirements-ml.txt` |
| `docker-compose.override.example.yml` 用于源码挂载 | 已删除；compose 默认即挂载源码 |
| `docker-*` 为唯一 Make 命令 | `dev-*` / `ml-*` 为主，旧 `docker-*` 作为别名 |

## 6. 重建矩阵（技术视角）

| 变更 | 影响的镜像/阶段 | 命令 |
|---|---|---|
| Python 源码、Django 模板、前端源码 | 无（挂载） | 无需操作 |
| `web/package.json` / `web/yarn.lock` | `web-deps` 及其下游 `web`、`web-dev`、`app`（`web/dist`） | `docker compose build app web` |
| 前端构建配置（webpack/nx/tsconfig） | `web` / `web-dev` | `docker compose build web` |
| `pyproject.toml` / `poetry.lock` / `poetry.toml` | `python-deps` → `app` → `ml` | `make dev-rebuild`（app/web）；`make ml-rebuild` |
| `services/requirements-ml.txt` | `ml` | `make ml-rebuild` |
| `services/ml_api/models.py`、`migrations/`、`db_bootstrap.py` | 无（挂载） | 重启 `ml-api` 触发引导/重载 |
| `docker/ml-api-start.sh` | `app` / `ml` | `make dev-rebuild` + `make ml-rebuild` |
| torch 版本/索引相关 build args | `ml` | 改 `.env` 后 `make ml-rebuild` |
| `Dockerfile` | 所有构建阶段 | `make dev-rebuild` + `make ml-rebuild` |
| `docker/docker-entrypoint.sh`、`init_minio.py` | `app` / `ml` | `make dev-rebuild` + `make ml-rebuild` |
| `docker-compose.yml`、`.env` 的运行时变量 | 无 | `docker compose up -d` 重建容器 |
| `.env` 的构建参数（`YARN_REGISTRY`、`POETRY_PYPI_URL`、`TORCH_*`、`APT_MIRROR`） | 对应构建阶段 | 重建对应镜像 |
| `.devcontainer/devcontainer.json` | 无 | VS Code 重新 Reopen in Container |

## 7. 已知限制

- **`web-dev` 镜像约 9.66 GB**：`node_modules` 烘焙在镜像中换取启动即 HMR；后续可改为命名卷缓存以瘦身。
- **HMR 依赖 `app` + `web` 两个服务同时运行**：8080 的页面、8010 的资源、容器内 `app:8080` 代理三者缺一不可。
- **真实 YOLO 训练/推理未实现**：训练域 CRUD 已可用，但任务创建后不会入队执行；`/api/predictions` 与训练执行仍是 501 占位。
- **训练域表结构由 Alembic 维护**：旧库首次启动会 `stamp head`；若曾手工改过 `training_*` 表结构，需要自行对齐后再升级。
- **开发默认凭据仅限本机**：数据库、MinIO、`ML_API_INTERNAL_TOKEN` 等默认值只适合单机；共享/生产必须通过 `.env` 覆盖。
- **只有开发 compose**：无反向代理/TLS/多副本；生产编排、反向代理与 GPU 发布流水线属于 infra-3。
- **端口直接发布**：PostgreSQL/Redis/MinIO 的宿主机端口默认开放，方便调试，不适合直接暴露到公网。
- **镜像源假设**：默认使用国内 PyPI/APT/npm/南京大学 torch 镜像；网络环境不同时通过 build args 覆盖。

## 8. 验证结果（本机开发环境实测记录）

> 以下为本机开发环境实际跑通的结果，供复验参考；最终验收由项目负责人核对。

| 项 | 结果 |
|---|---|
| 默认栈 `docker compose up -d` | `app`、`web`、`postgres`、`redis`、`minio` 共 5 个全部 healthy |
| 默认栈 URL | `GET /health/` 200（`{"status":"UP"}`）、登录页 `/user/login/` 200、HMR 资源 `http://localhost:8010/react-app/` 200 |
| 后端热重载 | 修改源码后无需重建，`runserver` 日志出现 `Watching for file changes with StatReloader`，health 接口立即返回新内容（测试改动已还原） |
| 前端 HMR | 修改主应用 `src/index.html` 后 webpack dev server 自动重新编译，8010 取到新内容（测试改动已还原） |
| ml profile | `docker compose --profile ml up -d` 后共 7 个服务全部 healthy；`ml-api /health` UP |
| ml-api 队列/鉴权 | `/api/training/queue` 带 token 正常返回；`/api/predictions` 带 token 返回 501，无 token 返回 401 |
| RQ 链路 | 入队 `services.ml_api.jobs.ping` 返回 `pong`；`ml-worker` 日志无 Redis 错误 |
| 训练域测试 | `pytest -c services/pytest.ini services/tests`：41 passed（在 ml 镜像内） |
| Django 网关测试 | `pytest --import-mode=importlib tests/test_training_proxy.py`：8 passed |
| 训练域表结构引导 | 存量库启动日志 `stamped existing training tables`，`alembic_version=0001_training_domain`；另建空库验证 `upgraded` 并生成两张表 |
| 训练域端到端 | Django 网关（Token 鉴权）→ ml-api：`LIST 200` / `SCAN 200` / `CREATE 201 Pending` / `DETAIL 200` / `CANCEL 200 Canceled` / 未登录 `401` |
| 网关降级 | ml-api 不可达时返回 503；FastAPI 422 在网关映射为 400（单测覆盖） |
| 持久化 | `docker compose down`（保留卷）后重新 `up`：PostgreSQL 用户/项目、MinIO 对象、`./models` 文件仍在 |
| 镜像体积 | `app` ≈ 1.52 GB、`ml` ≈ 3.65 GB、`web-dev` ≈ 9.66 GB（本机 `docker images`） |

## 附录 A：Makefile

`make` 默认目标为 `dev-up`（启动默认 5 个服务）。常用 target 分三类：

**容器化开发**

| target | 实际命令 |
|---|---|
| `dev-up` | `docker compose up -d` |
| `dev-up-build` | `docker compose up -d --build` |
| `dev-down` / `dev-down-clean` | `docker compose down` / `down -v` |
| `dev-ps` / `dev-logs` / `web-logs` | `docker compose ps` / 全量日志 / 仅 web 日志 |
| `dev-rebuild` | `docker compose build app web` |
| `dev-shell` | `docker compose exec app bash` |

**ml profile**

| target | 实际命令 |
|---|---|
| `ml-up` | `docker compose --profile ml up -d --build` |
| `ml-down` | `docker compose --profile ml stop ml-api ml-worker` |
| `ml-logs` | `docker compose --profile ml logs -f --tail=100 ml-api ml-worker` |
| `ml-rebuild` | `docker compose --profile ml build`（会构建所有带 build 的服务） |

**管理与兼容命令**

`docker-migrate-dev`、`docker-makemigrations-dev`、`docker-collectstatic-dev`、`docker-createsuperuser`、`docker-admin-org EMAIL=<邮箱>`、`docker-shell`、`docker-test`、`docker-config` 仍保留；旧 `docker-build` / `docker-up` / `docker-up-build` / `docker-down` / `docker-down-clean` / `docker-ps` / `docker-logs` 作为新 target 的别名。本地 Poetry/Yarn target（`run-dev`、`frontend-*` 等）保留作非容器备选。

## 附录 B：devcontainer 配置要点

| 配置 | 值 |
|---|---|
| `dockerComposeFile` | `../docker-compose.yml` + `../docker-compose.devcontainer.yml`（后者把仓库根目录挂到 `/label-studio`，让 web/services/pyproject 可直接编辑） |
| `service` | `app` |
| `runServices` | `postgres`、`redis`、`minio`、`app`、`web`（默认不含 ml profile） |
| `workspaceFolder` | `/label-studio` |
| `remoteUser` | `app` |
| `overrideCommand` | `false`（沿用 compose 中 app 的 `runserver` 命令） |
| `shutdownAction` | `stopCompose` |
| `forwardPorts` | 8080、8010、8991、9000、9001、5432、6379 |
| `postCreateCommand` | `python label_studio/manage.py migrate --noinput` |
| VS Code 扩展 | `ms-python.python`、`ms-python.vscode-pylance`、`charliermarsh.ruff`、`dbaeumer.vscode-eslint`、`esbenp.prettier-vscode`、`biomejs.biome` |

需要 ml profile 时，在宿主机终端执行 `docker compose --profile ml up -d`；devcontainer 会复用同一个 compose 项目，无需改动配置文件。compose 命令也都在宿主机执行（devcontainer 内没有 Docker socket）。
