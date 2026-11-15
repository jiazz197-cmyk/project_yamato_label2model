# 容器化开发技术参考（依赖 / 镜像 / 挂载 / 边界）

> 对应实现：**dev-first** 重构后的开发环境。日常使用看 [README.md](README.md)；本文记录构建阶段、依赖与缓存、挂载与 profile、前端 HMR 链路、训练架构边界、已知限制和本机验证结果。
>
> 实现以仓库中的 `Dockerfile`、`docker-compose.yml`、`Makefile`、`.env.example`、`.devcontainer/devcontainer.json` 为准；若本文与这些文件冲突，以后者为准。

## 1. 文件取舍

| 文件 | 结论 | 说明 |
|---|---|---|
| `Dockerfile` | **保留（dev-first 多阶段）** | 阶段：`web-deps` → `web` / `web-dev`；`python-deps` → `runtime` → `app` → `ml`；另有独立 `poetry-tools` 用于生成 lock。镜像只装依赖与工具链，源码由 compose 挂载。 |
| `docker-compose.yml` | **保留（开发编排）** | 默认 6 个服务；`ml` profile 增加 `ml-api`、`ml-worker`，共 8 个。`docker-compose.override.example.yml` 已删除，不再需要手工复制 override。 |
| `.devcontainer/devcontainer.json` | **新增** | 复用 compose 的 `app` 服务，推荐入口；细节见附录 B。 |
| `.env.example` | **保留（可选模板）** | 不复制也能用 compose 内置开发默认值；生产必须覆盖敏感项。 |
| `Makefile` | **更新（dev-first）** | 默认目标 `dev-up`；新增 `dev-*` / `ml-*`，旧 `docker-*` 保留为别名。 |
| `services/ml_api/` | **新增** | FastAPI 训练域：`app.py`（接口）、`models.py` / `db.py`（SQLAlchemy）、`migrations/`（Alembic）、`db_bootstrap.py`、`jobs.py`（RQ 作业）、`yolo.py` / `yolo_adapter.py`（由 Django training 迁入）。 |
| `services/requirements-ml.txt` | **新增** | 仅 ml 镜像安装：`ultralytics`、`fastapi`、`uvicorn[standard]`、`SQLAlchemy`、`alembic`、`psycopg[binary]`、`httpx`；torch/torchvision 由 Dockerfile 按索引单独安装。 |
| `docker/` | **更新** | `docker-entrypoint.sh`（仅 app 执行迁移 + MinIO 初始化）、`ml-api-start.sh`（先 Alembic 引导再启动 uvicorn）、`init_minio.py`、`healthcheck-worker.py`（按队列统计）、`rq_django_worker.py`（worker-pool 的 Django 初始化）、`ensure_admin_org.py`（为 `createsuperuser` 用户补组织）。 |
| `models/` | **保留** | 仅跟踪 `.gitkeep`；宿主机目录绑定到 `/models`，app / ml-api / ml-worker 共享。 |
| `pyproject.toml` / `poetry.lock` / `poetry.toml` | **保留（app 依赖唯一来源）** | app 依赖 + `test` 组；训练依赖已移出，改由 ml 镜像的 `requirements-ml.txt` 提供。 |
| `.dockerignore` | **保留** | 排除 `.git`、`.dsh`、`.devcontainer`、`.env*`（含 `.env.example`）、`docs`、`models`、`web/node_modules`、`web/dist`、运行数据与缓存。 |
| `web/` | **保留** | `web-deps` 安装 `node_modules`；`web-dev` 镜像烘焙依赖与构建配置，compose 只挂载源码目录。 |
| `training/` | **已删除** | 训练域（BaseModel / TrainingJob / API / YOLO 数据集与适配器）完整迁移到 `services/ml_api`；Django 只保留 `/api/training/` 网关。 |
| 旧 `services/trainer`、`services/predictor`、`services/requirements-trainer.txt` | **已删除** | 统一合并到 `services/ml_api` 与 `services/requirements-ml.txt`。 |

**结论**：app 在构建期用 Poetry 安装（main + test 组），runtime 镜像会卸载 Poetry；ml 侧车在 app 镜像基础上用固定版本 requirements + torch 索引安装；源码全部通过挂载进入开发容器，镜像不随日常改代码重建。

## 2. 构建阶段与缓存

### 2.1 阶段一览

| 阶段 | 基础镜像 | 作用 | 关键动作 / 缓存键 |
|---|---|---|---|
| `web-deps` | `node:22.19.0-bookworm-slim` | 安装前端依赖 | 校验镜像自带 yarn 1.22.22；`yarn install --frozen-lockfile` 后在同层 `yarn cache clean` + 清 `/root/.cache`；缓存键主要是 `web/package.json` + `web/yarn.lock` |
| `web` | `FROM web-deps` | 构建生产前端产物 | `COPY web/` → `yarn build`，产物 `web/dist`，供 `app` 镜像兜底 |
| `web-dev` | `FROM web-deps` | 前端 HMR 开发服务器 | `COPY web/` → 默认 `yarn dev --host 0.0.0.0`；`node_modules` 与配置烘焙在镜像中 |
| `python-deps` | `python:3.12.16-slim-bookworm` | 安装后端依赖 | Poetry 2.4.1 + `virtualenv==20.26.6`；`poetry install --no-root --only main,test`，失败自动重试 5 次；装完卸载 Poetry 并 `pip check`（runtime 不带 Poetry） |
| `poetry-tools` | `python:3.12.16-slim-bookworm` | 生成/更新 `poetry.lock` | 独立安装 Poetry + git；`ENTRYPOINT ["poetry"]`，不进入 app/ml 运行时 |
| `runtime` | 同 Python 镜像 | 运行时公共层 | 只装 `ca-certificates`、`curl`、`tini`，复制 Python 依赖 |
| `app` | `FROM runtime` | Django 运行镜像 | 复制源码与 `web/dist`、可编辑安装项目自身（`pip install -e .`）、构建期 `collectstatic`、非 root 用户 |
| `ml` | `FROM app` | 训练/推理侧车镜像 | 安装 OpenCV 所需系统库、torch/torchvision（按索引固定版本）、`services/requirements-ml.txt` |

`app` 与 `ml` 固定 Python 3.12.16；`ml-api` 与 `ml-worker` 共用 `ml` 镜像，仅启动命令不同。

构建阶段使用 `network: host`（见 compose 的 `x-*-build`），因为国内 PyPI/npm 镜像在 BuildKit 默认网络下偶发大面积超时；这仅影响构建期，运行容器仍使用 `yamato-net`。

### 2.2 依赖与源

| 项 | 值 / 说明 |
|---|---|
| Python | `3.12.16-slim-bookworm` |
| Node | `22.19.0-bookworm-slim`（镜像自带 yarn 1.22.22，构建时校验） |
| Poetry | `2.4.1`；额外固定 `virtualenv==20.26.6`，安装失败自动重试 |
| app 依赖范围 | `pyproject.toml` main 组 + test 组；build 组与 `uwsgi` extra 不安装 |
| PyPI | `pyproject.toml` 中 `tuna` source（primary）+ `poetry.toml`；Poetry 实际以 `pyproject.toml` 的 source 为准，`POETRY_PYPI_URL` 主要作为 `PIP_INDEX_URL`/环境变量，换 Poetry 源需改 `pyproject.toml` |
| npm/yarn | 默认 `YARN_REGISTRY=https://registry.npmmirror.com`；构建时替换 `yarn.lock` 中的 registry 前缀并 `yarn config set registry` |
| APT | 默认 `APT_MIRROR=http://mirrors.tuna.tsinghua.edu.cn`，构建时替换 Debian sources |
| torch / torchvision | 默认 `TORCH_INDEX_URL=https://mirrors.nju.edu.cn/pytorch/whl/cu130`；版本 `TORCH_VERSION=2.11.0`、`TORCHVISION_VERSION=0.26.0`；CPU 变体改索引并设 `REQUIRE_CUDA=0` |
| ml 额外依赖 | `ultralytics==8.4.118`、`fastapi==0.141.1`、`uvicorn[standard]==0.52.4`、`SQLAlchemy==2.0.36`、`alembic==1.14.0`、`psycopg[binary]==3.2.10`、`httpx==0.28.1` |

`torch` 安装命令使用 `--index-url ${TORCH_INDEX_URL}` + `--extra-index-url ${ML_PIP_INDEX_URL}`，因此所选 torch 索引中必须存在对应版本，其余依赖由 PyPI 镜像解析。默认南京大学 cu130 索引；ml 阶段先升级 pip>=26，并用 `--resume-retries 50 --timeout 30` 处理大 wheel 断流。

### 2.3 构建参数

| build arg | 默认 | 用途 |
|---|---|---|
| `APP_UID` / `APP_GID` | `1000` | 容器内 `app` 用户；与宿主机 `./models` 属主匹配 |
| `POETRY_PYPI_URL` | 清华 PyPI | Poetry 安装索引 |
| `ML_PIP_INDEX_URL` | 阿里云 PyPI | ml 镜像 pip 安装索引 |
| `YARN_REGISTRY` | npmmirror | 前端依赖 registry |
| `APT_MIRROR` | 清华 APT 镜像 | 系统包加速；置空则用默认源 |
| `TORCH_INDEX_URL` | 南京大学 cu130 索引 | torch/torchvision 索引；CPU 示例 `https://mirrors.nju.edu.cn/pytorch/whl/cpu` |
| `TORCH_VERSION` / `TORCHVISION_VERSION` | `2.11.0` / `0.26.0` | 固定训练框架版本 |
| `PYTHON_IMAGE` / `NODE_IMAGE` | 固定版本镜像 | 基础镜像替换入口 |

app 镜像构建期执行 `collectstatic`（临时 sqlite、跳过 MinIO，不依赖数据库），运行期由 `runserver` 的 staticfiles 服务提供静态文件；ml 阶段 `RUN_STARTUP_TASKS=0`，不会执行 Django 迁移或 MinIO 初始化。ml-api 启动脚本会单独执行训练域 Alembic 引导（见 5.2）。

### 2.4 镜像体积（本机构建结果）

| 镜像 | 体积 | 说明 |
|---|---|---|
| `yamato/label-studio-app:dev` | ≈ 1.51 GB | Django + Python 依赖 + `web/dist` + 静态文件 |
| `yamato/label-studio-ml:dev` | ≈ 10.2 GB | app 基础 + CUDA 13.0 torch/torchvision + ultralytics 等 |
| `yamato/label-studio-web-dev:dev` | ≈ 2.6 GB | `node_modules` 烘焙在镜像中；构建时清理 yarn/root 缓存，保留启动即 HMR |

体积会随依赖版本与构建缓存变化，以上为清理缓存后的目标值。`web-dev` 仍以 root 运行（已确认取舍）；如需彻底避免 root 写挂载目录，需要另开改动切 node 用户。

### 2.5 缓存与重建的关系

- 依赖层位于 `COPY` 源码之前：只改源码不会使 `web-deps` / `python-deps` 层失效，重建主要复用缓存。
- 开发时源码通过 bind mount 覆盖镜像内副本，因此**镜像内的源码副本不是日常开发输入**；它只用于没有挂载的场景（如 `web/dist` 兜底）。
- `app` 镜像包含项目自身（可编辑安装）与 `web/dist`；改前端后若想让「回退静态资源」也更新，需要重建 `app`。
- `.dockerignore` 排除了 `models`、`web/node_modules`、`web/dist`、`.devcontainer` 等，构建上下文较小。

## 3. 挂载与 profile 拓扑

### 3.1 默认开发栈（6 个服务）

```bash
docker compose up -d        # 或 make dev-up / make
```

| 服务 | 启动命令 | 端口 | 挂载 | 健康检查 |
|---|---|---|---|---|
| `postgres` | 官方镜像默认入口 | 5432 | `pgdata` | `pg_isready` |
| `redis` | `redis-server --appendonly yes` | 6379 | `redisdata` | `redis-cli ping` |
| `minio` | `server /data --console-address :9001` | 9000 / 9001 | `miniodata` | `/minio/health/live` |
| `app` | `python label_studio/manage.py runserver 0.0.0.0:8080` | 8080 | `.`（整个仓库 → `/label-studio`）、`appdata`、`./models` | `curl /health/` |
| `web` | `yarn dev --host 0.0.0.0` | 8010 | `./web/apps`、`libs`、`tools`、`scripts` | `node fetch /react-app/` |
| `worker` | `rq worker-pool -n 16 -w docker.rq_django_worker.DjangoWorker critical high default low` | — | `.`、`appdata` | 按队列计数（见 `docker/healthcheck-worker.py`） |

`app` 启动时由 entrypoint 自动迁移并幂等创建 MinIO bucket；`web` 首次启动需要编译，健康检查 `start_period` 为 300 秒。`worker` 等 `app` healthy 后启动，避免在迁移完成前消费任务。

### 3.2 ml profile（额外 2 个服务）

```bash
docker compose --profile ml up -d     # 或 make ml-up（带 --build）
```

| 服务 | 启动命令 | 端口 | 挂载 | 依赖 |
|---|---|---|---|---|
| `ml-api` | `ml-api-start.sh --reload --reload-dir /label-studio/services`（脚本先执行 `python -m services.ml_api.db_bootstrap`，再启动 uvicorn） | 8991 | `./services`、`./models` | postgres + redis healthy |
| `ml-worker` | `rq worker-pool -n 2 -u redis://redis:6379/0 training`（`gpus: all`） | — | `./services`、`./models` | postgres + redis + ml-api healthy |

`ml-api` 的健康检查是 `GET /health`；`ml-worker` 的健康检查用 `docker/healthcheck-worker.py` 按 `training` 队列统计本容器 hostname、心跳新鲜的 worker 数（默认要求 ≥2）。`worker` / `ml-worker` 的 `stop_grace_period` 默认 5m / 30s，可用 `LS_WORKER_STOP_GRACE` / `ML_WORKER_STOP_GRACE` 覆盖。`make ml-down` 只停止这两个服务，默认 6 个服务不受影响。

### 3.3 网络与数据

- 全部服务在 bridge 网络 `yamato-net` 上，服务名即 DNS（`web` 容器用 `http://app:8080` 代理 Django）。
- 命名卷：`pgdata`、`miniodata`、`appdata`、`redisdata`；`docker compose down` 保留，`down -v` 删除。
- 宿主机 `./models` 绑定到 `/models`，`down -v` 不会删除；基模与训练产物都放这里。
- `app` 启动时执行 Django 迁移（`RUN_STARTUP_TASKS=1`）；`ml-api` 启动时执行训练域 Alembic 引导（新库建表 / 旧库 stamp），`ml-worker` 的 `RUN_STARTUP_TASKS=0`，不执行任何迁移。

### 3.4 GPU 与训练并发

- 宿主机需要安装 **NVIDIA Container Toolkit**，并让 Docker 识别 `nvidia` runtime；验证：
  ```bash
  docker info --format '{{json .Runtimes}}' | grep nvidia
  docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi
  ```
- `ml-worker` 使用 `gpus: all`，并以 `rq worker-pool -n ${ML_WORKER_CONCURRENCY:-2}` 启动；当前单张 RTX 4090（48GB）上 2 个训练进程共享该卡，不承诺线性加速。
- 训练镜像按 cu130 构建；容器内验证：
  ```bash
  docker run --rm --gpus all yamato/label-studio-ml:dev \
    python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
  ```
- 显存碎片用 `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` 缓解；显存不足时任务失败属预期，应降低并发或 batch。

## 4. 前端 HMR 链路

### 4.1 环境变量与数据流

| 变量 | 默认 | 作用 |
|---|---|---|
| `FRONTEND_HMR` | `1` | `app` 是否把前端资源指向 dev server；置 `0` 前需在宿主机构建 `web/dist` |
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
  - 旧库（已有 `training_base_model`/`training_job`、但没有 `alembic_version`）：校验表/列完整后 `stamp 0001` 再 `upgrade head`，由 0002 幂等补索引，不重建、不丢数据；
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

- 令牌环境变量为 `ML_API_INTERNAL_TOKEN`；为空时回退 `TRAINER_INTERNAL_TOKEN`；两者都为空时 **fail-closed**：接口返回 503，不会关闭校验。
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
| 默认 4 个服务（postgres/redis/minio/app） | 默认 6 个（增加 `web` HMR 服务与 LS `worker`） |
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

- **`web-dev` 镜像约 2.6 GB**：`node_modules` 烘焙在镜像中换取启动即 HMR；构建时已清理 yarn/root 缓存，web 仍以 root 运行。
- **HMR 依赖 `app` + `web` 两个服务同时运行**：8080 的页面、8010 的资源、容器内 `app:8080` 代理三者缺一不可。
- **app 挂载整个仓库后，镜像内 `web/dist` 被遮住**：默认 `FRONTEND_HMR=1` 不受影响；若要 `FRONTEND_HMR=0` 的静态回退，需先在宿主机构建 `web/dist`。
- **真实 YOLO 训练/推理未实现**：训练域 CRUD 已可用，但任务创建后不会入队执行；`/api/predictions` 与训练执行仍是 501 占位。yolo-3 入队使用 `services.ml_api.jobs.enqueue_training_job()`：默认 `job_timeout=7 天`（`TRAINING_JOB_TIMEOUT` 可覆盖）、`retry=None`，同 ID job 幂等返回；异常由 `on_training_failure` 原子置 `Failed`，不覆盖 `Completed/Canceled`。取消会移除排队 job 或发送 stop 命令；ml-api 启动对账把无存活 worker 的 `Running` 置 `Failed`，不依赖 scheduler。
- **训练域表结构由 Alembic 维护**：旧库首次启动先校验表/列，再 `stamp 0001` + `upgrade head`；若曾手工改过 `training_*` 表结构，会拒绝启动并给出缺失列，需对齐后再升级。
- **老库/新库约束不同（有意为之）**：旧库保留 Django training 的 `project/organization/created_by` 外键；新库只有 `base_model` 外键，跨域引用由 API 校验。软删除项目由 `ProjectRef.deleted_at` 过滤，行为与 Django `Project.objects` 一致；若后续要补外键，需要同时调整 `db_bootstrap` 的 stamp 逻辑和 ml-api 的启动顺序。
- **训练镜像默认 CUDA 13.0（cu130）**：宿主机需要 NVIDIA Container Toolkit；`ml-worker` 使用 `gpus: all`。当前单张 RTX 4090 配 2 个训练 worker，两个任务共享同一张卡，不保证线性加速，显存不足会失败。
- **开发默认凭据仅限本机**：数据库、MinIO、`ML_API_INTERNAL_TOKEN` 等默认值只适合单机；共享/生产必须通过 `.env` 覆盖。
- **只有开发 compose**：无反向代理/TLS/多副本；生产编排、反向代理与 GPU 发布流水线属于 infra-3。
- **端口只绑 `127.0.0.1`**：远程访问必须通过 VS Code Ports / SSH 转发 8080 与 8010；若需局域网/Tailscale 直连，要同时改 compose 的绑定地址与 `.env` 的 `HOST`/`FRONTEND_HOSTNAME`。
- **镜像源假设**：默认使用国内 PyPI/APT/npm 与 NJU cu130 torch 镜像；ml 阶段使用 pip>=26 的 `--resume-retries`，网络环境不同时通过 build args 覆盖。

## 8. 验证结果（本机开发环境实测记录）

> 以下为本机开发环境实际跑通的结果，供复验参考；最终验收由项目负责人核对。

| 项 | 结果 |
|---|---|
| 默认栈 `docker compose up -d` | `app`、`web`、`worker`、`postgres`、`redis`、`minio` 共 6 个全部 healthy |
| 默认栈 URL | `GET /health/` 200（`{"status":"UP"}`）、登录页 `/user/login/` 200、HMR 资源 `http://localhost:8010/react-app/` 200 |
| 端口绑定 | 所有宿主机端口只监听 `127.0.0.1`；容器间仍通过 `yamato-net` 服务名互通 |
| LS worker | `worker-pool` 注册 16 个 worker；`rq:queue:default` / `low` 积压消费到 0，无新增 failed |
| 后端热重载 | 修改源码后无需重建，`runserver` 日志出现 `Watching for file changes with StatReloader`，health 接口立即返回新内容（测试改动已还原） |
| 前端 HMR | 修改主应用 `src/index.html` 后 webpack dev server 自动重新编译，8010 取到新内容（测试改动已还原） |
| ml profile | `docker compose --profile ml up -d` 后共 8 个服务全部 healthy；`ml-api /health` UP |
| GPU | `docker run --rm --gpus all yamato/label-studio-ml:dev python -c ...` 输出 `2.11.0+cu130 13.0 True NVIDIA GeForce RTX 4090` |
| 训练 worker | `worker-pool` 注册 2 个 worker；健康检查按 `training` 队列计数通过 |
| ml-api 队列/鉴权 | `/api/training/queue` 带 token 正常返回；`/api/predictions` 带 token 返回 501，无 token 返回 401 |
| RQ 链路 | 入队 `services.ml_api.jobs.ping` 返回 `pong`；`ml-worker` 日志无 Redis 错误 |
| 训练域测试 | `pytest -c services/pytest.ini services/tests`：84 passed（在 ml 镜像内） |
| Django 网关测试 | `pytest --import-mode=importlib tests/test_training_proxy.py`：11 passed |
| 训练域表结构引导 | 存量库先校验表/列，`stamp 0001` 后 `upgrade head`，`alembic_version=0002_training_indexes`；0002 幂等补索引；空库 `upgrade` 生成两张表与全部索引 |
| 训练域端到端 | Django 网关（Token 鉴权）→ ml-api：`LIST 200` / `SCAN 200` / `CREATE 201 Pending` / `DETAIL 200` / `CANCEL 200 Canceled` / 未登录 `401` |
| 网关降级 | ml-api 不可达时返回 503；FastAPI 422 在网关映射为 400（单测覆盖） |
| 持久化 | `docker compose --profile ml down`（保留卷）后重新 `up`：PostgreSQL 用户/项目、MinIO 对象、`./models` 文件仍在 |
| 镜像体积 | `app` ≈ 1.51 GB、`ml` ≈ 10.2 GB（cu130）、`web-dev` ≈ 2.6 GB（清理缓存后） |

## 附录 A：Makefile

`make` 默认目标为 `dev-up`（启动默认 6 个服务）。常用 target 分三类：

**容器化开发**

| target | 实际命令 |
|---|---|
| `dev-up` | `docker compose up -d` |
| `dev-up-build` | `docker compose up -d --build` |
| `dev-down` / `dev-down-clean` | `docker compose --profile ml down` / `--profile ml down -v` |
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
| `poetry-lock` | 构建独立 `poetry-tools` 镜像并生成 `poetry.lock` |

**管理与兼容命令**

`docker-migrate-dev`、`docker-makemigrations-dev`、`docker-collectstatic-dev`、`docker-createsuperuser`、`docker-admin-org EMAIL=<邮箱>`、`docker-shell`、`docker-test`、`docker-config` 仍保留；旧 `docker-build` / `docker-up` / `docker-up-build` / `docker-down` / `docker-down-clean` / `docker-ps` / `docker-logs` 作为新 target 的别名。本地 Poetry/Yarn target（`run-dev`、`frontend-*` 等）保留作非容器备选。

## 附录 B：devcontainer 配置要点

| 配置 | 值 |
|---|---|
| `dockerComposeFile` | `../docker-compose.yml`（基础 compose 已把整个仓库挂到 `/label-studio`，devcontainer 与命令行挂载一致） |
| `service` | `app` |
| `runServices` | `postgres`、`redis`、`minio`、`app`、`web`、`worker`（默认不含 ml profile） |
| `workspaceFolder` | `/label-studio` |
| `remoteUser` | `app` |
| `overrideCommand` | `false`（沿用 compose 中 app 的 `runserver` 命令） |
| `shutdownAction` | `stopCompose` |
| `forwardPorts` | 8080、8010、8991、9000、9001、5432、6379 |
| `postCreateCommand` | 无（迁移由 `app` entrypoint 执行，避免重复 migrate） |
| VS Code 扩展 | `ms-python.python`、`ms-python.vscode-pylance`、`charliermarsh.ruff`、`dbaeumer.vscode-eslint`、`esbenp.prettier-vscode`、`biomejs.biome` |

需要 ml profile 时，在宿主机终端执行 `docker compose --profile ml up -d`；devcontainer 会复用同一个 compose 项目，无需改动配置文件。compose 命令也都在宿主机执行（devcontainer 内没有 Docker socket）。
