# label2model

基于 [Label Studio](https://github.com/HumanSignal/label-studio)（Apache-2.0）二次开发的数据标注 + YOLO 训练平台：保留 Label Studio 的标注、项目管理与用户鉴权能力，并用独立的 FastAPI 服务承接训练/推理编排。

> **dev-first**
>
> 默认 `docker compose up -d` 只启动 **6 个服务**：`postgres`、`redis`、`minio`、`app`、`web`、`worker`。源码通过 bind mount 挂进容器，**改代码即时生效**（Django `runserver` 自动重载 + webpack dev server HMR），不需要重建镜像。只有依赖清单、Dockerfile 或前端构建配置变化时才需要重建。
>
> 训练/推理侧车在 `ml` profile 中按需启动（`docker compose --profile ml up -d`），共 **8 个服务**：再加 `ml-api`、`ml-worker`。训练域（BaseModel / TrainingJob / `/api/training/`）已完整迁移到 FastAPI：Django 只保留登录态与组织上下文并转发请求，表结构由 ml-api 启动时的 Alembic 引导维护；真实 YOLO 训练执行与推理仍由 yolo-3 落地（对应接口返回 501）。
>
> 推荐使用 **VS Code Dev Containers**：打开仓库后执行 `Dev Containers: Reopen in Container`，环境、端口和扩展一次配好；命令行方式作为备选。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Django 5.1 + DRF，Python 3.12 |
| 数据与中间件 | PostgreSQL 16、Redis 7（django-rq / RQ 队列）、MinIO（S3 兼容对象存储） |
| 前端 | React 18 + TypeScript + Nx monorepo（`web/`）；webpack dev server HMR |
| 训练/推理编排 | FastAPI（`services/ml_api`，端口 8991）+ SQLAlchemy/Alembic + RQ worker（`ml-worker`）；Ultralytics YOLO（torch / torchvision） |
| 运行方式 | Docker Engine + Docker Compose v2；根目录单 Dockerfile 多阶段构建；可选 VS Code Dev Containers |

## 快速开始（推荐：VS Code Dev Containers）

前置：Linux/macOS/Windows（WSL2），安装 Docker Engine + Docker Compose v2，以及 VS Code 的 **Dev Containers** 扩展。宿主机**不需要**安装 Python、Node、yarn、PostgreSQL、Redis 或 MinIO。

1. 在 VS Code 中打开仓库目录。
2. 按 `F1`，执行 **Dev Containers: Reopen in Container**（或右下角提示「Reopen in Container」）。
3. 首次会构建/启动 `postgres`、`redis`、`minio`、`app`、`web`、`worker` 六个服务；`app` 的 entrypoint 会自动执行数据库迁移，需要等待几分钟到更久（首次构建前端依赖与 Python 依赖）。
4. 打开 <http://localhost:8080> 进入标注平台；前端 HMR 资源由 <http://localhost:8010/react-app/> 提供。
5. 创建管理员：直接在登录页 **Sign up**（会自动创建组织），或使用命令行方式（见下）。浏览器端 `localhost` 能生效是因为 devcontainer 已把 8080/8010/8991/9000/9001/5432/6379 转发到本机。

devcontainer 详情见 [`.devcontainer/devcontainer.json`](.devcontainer/devcontainer.json)：复用 `docker-compose.yml` 的 `app` 服务，工作目录 `/label-studio`，以 `app` 用户运行，预装 Python / Pylance / Ruff / ESLint / Prettier / Biome 扩展。

### 创建管理员（两种方式）

**方式 A（推荐）**：浏览器打开 <http://localhost:8080>，点击 **Sign up** 注册，注册流程会自动创建组织，可直接登录。

**方式 B（命令行）**：`manage.py createsuperuser` 不会自动创建组织，需要再执行一次补组织脚本。在 devcontainer 终端（工作目录 `/label-studio`）中直接运行：

```bash
python label_studio/manage.py createsuperuser
python docker/ensure_admin_org.py <你的邮箱>
```

或从宿主机运行：

```bash
docker compose exec app python label_studio/manage.py createsuperuser
docker compose exec app python docker/ensure_admin_org.py <你的邮箱>
```

也可以直接用 Makefile（宿主机仓库根目录）：

```bash
make docker-createsuperuser
make docker-admin-org EMAIL=<你的邮箱>
```

## 快速开始（命令行备选）

1. 克隆仓库并进入目录：

   ```bash
   git clone git@github.com:jiazz197-cmyk/project_yamato_label2model.git
   cd project_yamato_label2model
   ```

2. （可选）复制环境模板；不复制也能用 compose 内置的开发默认值：

   ```bash
   cp .env.example .env
   ```

3. 首次构建并启动默认开发栈：

   ```bash
   docker compose up -d --build
   # 或 make dev-up-build
   ```

   首次构建需要下载 Node 依赖、Python 依赖；耗时从几分钟到数十分钟不等，后续增量构建会快很多。构建使用 compose 的 `network: host`（仅构建期），避免国内镜像在 BuildKit 默认网络下超时；运行容器仍使用 `yamato-net`。

4. 等待服务健康：

   ```bash
   docker compose ps
   # 或 make dev-ps
   ```

   预期 6 个服务全部 `healthy`（`web` 首次启动最长约 5 分钟；`app` 首次启动约 1–2 分钟）。

5. 需要训练/推理侧车时，再加 ml profile：

   ```bash
   docker compose --profile ml up -d
   # 或 make ml-up
   ```

6. 打开页面：

   - 标注平台：<http://localhost:8080>
   - 前端 HMR：<http://localhost:8010/react-app/>
   - MinIO Console：<http://localhost:9001>（开发默认凭据见 `.env.example` / `docker-compose.yml`）
   - ml-api 健康检查：<http://localhost:8991/health>（仅 ml profile）

## 服务、端口与 profile

| 服务 | profile | 宿主机端口（默认） | 镜像 | 作用 |
|---|---|---|---|---|
| `postgres` | 默认 | 5432（`POSTGRES_PORT`） | `postgres:16.15-alpine` | 应用数据库 |
| `redis` | 默认 | 6379（`REDIS_PORT`） | `redis:7.4.12-alpine` | django-rq / RQ 队列 broker（LS + 训练） |
| `minio` | 默认 | 9000（`MINIO_PORT`）/ 9001（`MINIO_CONSOLE_PORT`） | `pgsty/minio:RELEASE.2026-08-04T00-00-00Z` | S3 兼容对象存储 / Web Console |
| `app` | 默认 | 8080（`APP_PORT`） | `yamato/label-studio-app:dev` | Django + DRF，`runserver` 自动重载；挂载源码 |
| `web` | 默认 | 8010（`WEB_PORT`） | `yamato/label-studio-web-dev:dev` | webpack dev server，前端 HMR；挂载 `web/apps`、`libs`、`tools`、`scripts` |
| `worker` | 默认 | — | `yamato/label-studio-app:dev` | Label Studio RQ worker（critical/high/default/low），默认 16 进程可调 |
| `ml-api` | `ml` | 8991（`ML_API_PORT`） | `yamato/label-studio-ml:dev` | FastAPI 训练/推理编排入口，`uvicorn --reload` |
| `ml-worker` | `ml` | — | 同 ml 镜像 | RQ worker-pool，消费 `training`，默认 2 进程，GPU |

- 全部服务在自定义 bridge 网络 `yamato-net` 上，服务名即 DNS（例如 `web` 容器内通过 `http://app:8080` 访问 Django）。
- 默认 `docker compose up -d` 只启动 6 个；`docker compose --profile ml up -d` 启动全部 8 个。
- 宿主机端口全部绑定 `127.0.0.1`；远程访问必须通过 VS Code Ports / SSH 转发，直接访问局域网或 Tailscale IP 不可用。
- `ml-worker` 没有对外端口；`ml-api` 与 `ml-worker` 共用同一个 ml 镜像，仅启动命令不同。

### GPU / CUDA 训练镜像

训练镜像默认按 **CUDA 13.0（cu130）** 构建，适配本机 `RTX 4090 48GB / 驱动 596.36 / CUDA 13.2`：

- `TORCH_INDEX_URL` 默认 `https://mirrors.nju.edu.cn/pytorch/whl/cu130`
- `ML_PIP_INDEX_URL` 默认 `https://mirrors.aliyun.com/pypi/simple/`
- torch / torchvision 为 `2.11.0` / `0.26.0`；Dockerfile 内升级到 pip>=26 并用 `--resume-retries 50`，大 wheel 断流可续传
- 宿主机需要 NVIDIA Container Toolkit；`ml-worker` 通过 `gpus: all` 获取 GPU
- 训练并发默认 2（`ML_WORKER_CONCURRENCY`），两个进程共享同一张 GPU；单卡不承诺线性加速

构建与验证：

```bash
docker compose build ml-api
docker run --rm --gpus all yamato/label-studio-ml:dev \
  python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

预期输出包含 `2.11.0+cu130 13.0 True NVIDIA GeForce RTX 4090`。

### 源码挂载与数据卷

| 服务 | 挂载 |
|---|---|
| `app` | `.` → `/label-studio`（整个仓库）；`appdata` → `/label-studio/data`；`./models` → `/models` |
| `web` | `./web/apps`、`./web/libs`、`./web/tools`、`./web/scripts` → 对应容器目录（`node_modules` 与构建配置来自镜像） |
| `worker` | `.` → `/label-studio`；`appdata` → `/label-studio/data` |
| `ml-api` | `./services` → `/label-studio/services`；`./models` → `/models` |
| `ml-worker` | 同 `ml-api` |
| `postgres` | 命名卷 `pgdata` → `/var/lib/postgresql/data` |
| `redis` | 命名卷 `redisdata` → `/data` |
| `minio` | 命名卷 `miniodata` → `/data` |

## 改什么 / 是否重建

| 改动 | 是否需要重建镜像 | 生效方式 |
|---|---|---|
| `label_studio/` 下的 Python 源码 | 否 | `app` 的 `runserver` 自动重载（日志出现 `Watching for file changes with StatReloader`） |
| Django 模板、静态资源 | 否 | 由 `runserver` 直接服务 |
| `web/apps`、`web/libs`、`web/tools`、`web/scripts` 下的前端源码 | 否 | `web` 容器 HMR 自动编译，刷新或热更新即可 |
| `services/` 下的 ml-api / jobs / 迁移源码 | 否 | `ml-api` 的 `uvicorn --reload` 自动重载；Alembic 迁移改动需重启 `ml-api` 触发引导；`ml-worker` 需重启容器以加载新代码 |
| `web/package.json`、`web/yarn.lock` | **是** | 重建 `web`（以及 `app`，因为 app 内含 `web/dist`） |
| `web/webpack.config.js`、`nx.json`、`tsconfig*.json` 等前端构建配置 | **是** | 重建 `web`；这些文件不在挂载范围内 |
| `pyproject.toml`、`poetry.lock`、`poetry.toml` | **是** | `make dev-rebuild`（构建 `app` + `web`） |
| `services/requirements-ml.txt` | **是** | `make ml-rebuild`，再 `make ml-up` |
| `Dockerfile`、`docker/` 下的启动脚本 | **是** | 重建受影响镜像（`make dev-rebuild` / `make ml-rebuild`） |
| `docker-compose.yml`、`.env` 的运行时变量 | 否 | `docker compose up -d` 重建容器 |
| `.env` 中构建参数（`YARN_REGISTRY`、`POETRY_PYPI_URL`、`TORCH_*`、`APT_MIRROR` 等） | **是** | 重建对应镜像（`make dev-rebuild` / `make ml-rebuild`） |
| `.devcontainer/devcontainer.json` | 否 | VS Code 重新 Reopen in Container |
| `./models` 下的基模/产物 | 否 | 直接挂载可见 |
| Django 表结构（`label_studio/*/migrations`） | 否 | `app` 启动时自动 `migrate`，或 `make docker-migrate-dev` |
| 训练域表结构（`services/ml_api/migrations`） | 否 | `ml-api` 启动时自动执行 Alembic 引导（新库建表 / 旧库 stamp） |

常用重建命令：

```bash
make dev-rebuild   # docker compose build app web
make ml-rebuild    # docker compose --profile ml build
docker compose build web   # 只重建 web
```

## 前端 HMR 与 devcontainer 说明

### HMR 数据流

- `app` 容器设置了 `FRONTEND_HMR=1`、`FRONTEND_HOSTNAME=http://localhost:8010`，Django 模板会把前端资源指向 8010 的 `/react-app/`。
- `web` 容器（webpack dev server）监听 8010，`publicPath` 为 `/react-app/`；它把 `/api` 代理到 `http://app:8080/api`，其余请求代理到 `http://app:8080`。
- `web` 容器的 `DJANGO_HOSTNAME` 是**容器内部代理目标** `http://app:8080`，不是浏览器访问地址；浏览器侧地址由 `FRONTEND_HOSTNAME` 控制。
- 修改 `web/apps`、`web/libs` 等挂载目录下的源码会触发 HMR；`web` 的依赖与配置（`package.json`、`yarn.lock`、`webpack.config.js`、`tsconfig` 等）烘焙在镜像中，修改后必须重建。
- 把 `FRONTEND_HMR` 设为 `0` 可回退到静态资源；但 `app` 现在挂载整个仓库，镜像内的 `web/dist` 被宿主机目录遮住，回退前需要先在宿主机执行 `cd web && yarn build` 生成 `web/dist`。

### 远程 / 局域网访问

默认配置假设浏览器就在本机，或通过 VS Code Ports / SSH 转发访问。所有宿主机端口只绑 `127.0.0.1`；Remote-SSH 需要同时转发 **8080 和 8010**，Dev Containers 模式由 `.devcontainer` 的 `forwardPorts` 自动处理。

若确实需要局域网/Tailscale 直连，必须同时把 `docker-compose.yml` 里对应端口的绑定地址从 `127.0.0.1` 改成具体网卡 IP，并把 `.env` 中的 `HOST` 与 `FRONTEND_HOSTNAME` 改成该地址；只改 `.env` 不够。`DJANGO_HOSTNAME` 始终是容器内部地址 `http://app:8080`，不要改成外网地址。

### devcontainer 说明

- 配置文件：`.devcontainer/devcontainer.json`；复用 `docker-compose.yml`，进入 `app` 服务。
- 默认启动 `postgres`、`redis`、`minio`、`app`、`web`、`worker`（不含 ml profile），并执行 `python label_studio/manage.py migrate --noinput`。
- 工作区**整个仓库** bind mount 到 `/label-studio`（基础 compose 里的 `.:/label-studio`），因此 `label_studio/`、`web/`、`services/`、`pyproject.toml` 都能直接在 VS Code 里改；命令行 `docker compose up -d` 与 devcontainer 使用同一套挂载。
- 远程用户 `app`；`overrideCommand: false` 表示沿用 compose 中 app 的启动命令（`runserver`）。
- VS Code 终端就在 `app` 容器内，可以直接跑 `python label_studio/manage.py ...`、`pytest`；**compose 命令请在宿主机终端执行**（devcontainer 未挂载 Docker socket）。
- 依赖或 Dockerfile 变化后：宿主机执行 `make dev-rebuild`（必要时 `make ml-rebuild`），再在 VS Code 执行 **Dev Containers: Rebuild Container**。
- 需要 ml profile 时，在**宿主机终端**执行 `docker compose --profile ml up -d`；devcontainer 不默认启动 ml 服务。
- `shutdownAction: stopCompose`：关闭 VS Code 窗口时会停止这套 compose，数据卷与 `./models` 保留。

## 训练 / 推理架构

- **Django（`app`）**：只负责标注、项目、用户/组织、鉴权与页面渲染。`/api/training/` 保留原 URL 与响应结构，但只做**薄网关**：带上 `X-Internal-Token`、`X-User-Id`、`X-Organization-Id` 转发给 ml-api，不再直接读写训练表，也没有训练模型/序列化器。
- **`services/ml_api`（FastAPI，8991）**：训练域唯一入口，`ml-api` 与 `ml-worker` 共用 ml 镜像。
  - `GET /health`：健康检查，无需鉴权。
  - `GET /api/training/base-models`、`GET /api/training/base-models/{id}`、`GET /api/training/base-models/scan`：基模列表/详情/本地目录扫描。
  - `GET/POST /api/training/jobs`、`GET/PATCH /api/training/jobs/{id}`：任务查询/创建/取消（`PATCH {"action":"cancel"}`）；列表保持数组响应，支持可选 `limit/offset`（默认 200、最大 1000）；旧 form 提交的 `hyperparams` JSON 字符串由网关解析，保持兼容。
  - `GET /api/training/queue`：`training` 队列长度。
  - `POST /api/predictions`：预标注推理占位，返回 501（yolo-3）。
  - 内部鉴权头 `X-Internal-Token`（对应 `ML_API_INTERNAL_TOKEN`，为空时回退 `TRAINER_INTERNAL_TOKEN`；两者都为空时 fail-closed 返回 503，不会关闭校验）；`/docs`、`/redoc`、`/openapi.json` 关闭。
- **持久化**：训练域使用 SQLAlchemy + Alembic，表名/列名沿用原 Django 表（`training_base_model`、`training_job`），存量库无需搬数据。`ml-api` 启动脚本 `docker/ml-api-start.sh` 先执行 `services/ml_api/db_bootstrap.py`：新库 `upgrade head` 建表；已有表但没有 `alembic_version` 的旧库先校验表/列，再 `stamp 0001` 后 `upgrade head`，由 0002 幂等补索引，不重建、不丢数据。
- **`worker`（Label Studio 异步任务）**：app 镜像，`rq worker-pool -n 16 -w docker.rq_django_worker.DjangoWorker critical high default low`；消费数据导入/导出、Webhook、迁移回填等任务，默认 16 进程（`LS_WORKER_CONCURRENCY` 可调）。
- **`ml-worker`**：RQ worker-pool，队列 `training`，默认 2 进程（`ML_WORKER_CONCURRENCY`），通过 `gpus: all` 使用单张 RTX 4090；当前注册 `services.ml_api.jobs.ping`（返回 `pong`）与占位的 `execute_training_job`（调用即 `NotImplementedError`）。
- **真实 YOLO 训练/推理未实现**：任务创建后只落库为 `Pending`，不会自动入队执行；执行链路由 yolo-3 接入。原 `training/yolo.py`、`training/adapters/yolo_adapter.py` 已迁入 `services/ml_api/`，不再依赖 Django。yolo-3 入队时使用 `services.ml_api.jobs.enqueue_training_job()`：默认 `job_timeout=7 天`（`TRAINING_JOB_TIMEOUT` 可覆盖）、`retry=None`，异常由 `on_training_failure` 把 `training_job` 置为 `Failed` 并结束；同 ID job 已存在时幂等返回，不重复入队；不使用延迟任务，因此不依赖 scheduler。
- **取消与停机语义**：取消会原子置 `Canceled`，排队中的 job 从队列移除，运行中的 job 发送 RQ stop 命令；`worker` / `ml-worker` 的 `stop_grace_period` 默认 5 分钟 / 30 秒。容器停止或异常退出导致训练中断时，`ml-api` 启动对账会把没有存活 worker 持有的 `Running` 任务置 `Failed`，避免一直显示运行中。
- **原 `predictor` 已合并进 `ml-api`**；`trainer` / `trainer-worker` / `predictor` 服务均已删除。

模型与产物目录：宿主机 `./models` 绑定到容器 `/models`，由 `app`、`ml-api`、`ml-worker` 共享；基模放 `./models/<模型名>/*.pt`，训练产物默认写到 `/models/trained/<job_id>/`（即宿主机 `./models/trained/<job_id>/`）。

## 验收自检

以下命令在仓库根目录执行；`<...>` 替换为实际值。验收结果由项目负责人最终核对，本文只给出可复现的检查清单。

### 1. 默认开发栈（6 个服务）

```bash
docker compose config -q

docker compose up -d --build

docker compose ps
# 预期：postgres / redis / minio / app / web / worker 全部 healthy

docker compose exec app python label_studio/manage.py migrate
# 预期：No migrations to apply.

curl -fsS http://localhost:8080/health/
# 预期：{"status": "UP"}

curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost:8080/user/login/
# 预期：200

curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost:8010/react-app/
# 预期：200（webpack dev server）
```

### 2. 后端热重载（无需重建）

```bash
docker compose logs app | grep -i "Watching for file changes"
# 预期：能看到 Django StatReloader 的日志

# 可选：临时修改 label_studio/core/views.py 的 health 返回内容，
# 保存后再次 curl http://localhost:8080/health/ 应立即看到新内容；验证后还原文件。
```

### 3. 前端 HMR（无需重建）

```bash
docker compose logs -f web
# 预期：能看到 webpack 编译完成的日志

# 可选：修改 web/apps 下主应用的 src/index.html（例如页面 title），
# 保存后 web 容器自动重新编译，刷新 http://localhost:8010/react-app/ 即可看到新内容；验证后还原。
```

### 4. 测试

```bash
make docker-test
# 预期：84 passed
```

### 5. ml profile（8 个服务）

```bash
docker compose --profile ml up -d
docker compose --profile ml ps
# 预期：在默认 6 个之外增加 ml-api、ml-worker，共 8 个 healthy

curl -fsS http://localhost:8991/health
# 预期：{"status":"UP","service":"ml-api"}

TOKEN=$(docker compose --profile ml exec -T ml-api printenv ML_API_INTERNAL_TOKEN)
curl -fsS -H "X-Internal-Token: $TOKEN" http://localhost:8991/api/training/queue
# 预期：{"queue":"training","count":<queued_count>}（无排队任务时 count 为 0）

curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8991/api/training/queue
# 预期：401

curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST -H "X-Internal-Token: $TOKEN" -H 'Content-Type: application/json' -d '{}' \
  http://localhost:8991/api/predictions
# 预期：501

训练域端到端（Django 网关 → ml-api，需 ml profile 已启动；下面用第一个超级用户的 API Token）：

```bash
docker compose exec -T app python label_studio/manage.py shell -c "
from django.test import Client
from users.models import User
from organizations.models import Organization
user = User.objects.filter(is_superuser=True).first()
org = Organization.objects.get(pk=user.active_organization_id)
org.jwt.legacy_api_tokens_enabled = True
org.jwt.save()
client = Client(HTTP_AUTHORIZATION=f'Token {user.reset_token().key}')
print('base-models', client.get('/api/training/base-models/').status_code)
print('scan', client.get('/api/training/base-models/scan/').status_code)
"
# 预期：两个请求均 200；若 ml profile 未启动，网关返回 503
```

RQ 入队 ping 并取结果（`ml-worker` 已在 ml profile 中运行）：

```bash
docker compose exec -T app python - <<'PY'
import os
import time

from redis import Redis
from rq import Queue

connection = Redis(
    host=os.environ.get('REDIS_HOST', 'redis'),
    port=int(os.environ.get('REDIS_PORT', '6379')),
    db=int(os.environ.get('REDIS_DB', '0')),
)
queue = Queue('training', connection=connection)
job = queue.enqueue('services.ml_api.jobs.ping', job_timeout=30)

for _ in range(20):
    job.refresh()
    if job.is_finished or job.is_failed:
        break
    time.sleep(0.5)

print({'id': job.id, 'status': job.get_status(refresh=True), 'result': job.result})
PY
# 预期：status 为 finished，result 为 pong

docker compose --profile ml logs --tail=50 ml-worker
# 预期：worker 正常监听 training 队列，无 Redis 连接报错
```

### 6. 持久化

```bash
docker compose --profile ml down   # 连 ml 侧车一起停；保留命名卷与 ./models
docker compose up -d

# PostgreSQL 数据仍在
docker compose exec -T postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select count(*) from htx_user;"'

# MinIO 对象仍在
docker compose exec -T app python - <<'PY'
import os
import boto3

s3 = boto3.client(
    's3',
    endpoint_url=os.environ['MINIO_STORAGE_ENDPOINT'],
    aws_access_key_id=os.environ['MINIO_STORAGE_ACCESS_KEY'],
    aws_secret_access_key=os.environ['MINIO_STORAGE_SECRET_KEY'],
)
bucket = os.environ['MINIO_STORAGE_BUCKET_NAME']
resp = s3.list_objects_v2(Bucket=bucket)
print('bucket:', bucket, 'objects:', resp.get('KeyCount', 0))
PY

# 宿主机模型目录仍在
ls models/
```

`docker compose --profile ml down -v` 会删除命名卷（`pgdata`/`miniodata`/`appdata`/`redisdata`），但不会删除 `./models`。`down` 会中断正在跑的训练；下次启动 ml-api 时对账会把遗留 `Running` 置 `Failed`。

> 本机开发环境已跑通的关键结果见 [CONTAINER.md](CONTAINER.md) 的「验证结果」一节；最终验收以项目负责人核对为准。

## 常用 Make 命令

`make` 默认目标是 `dev-up`。以下 target 已由仓库 `Makefile` 提供：

| 命令 | 作用 |
|---|---|
| `make` / `make dev-up` | `docker compose up -d`，启动默认 6 个服务 |
| `make dev-up-build` | `docker compose up -d --build`，构建并启动（首次） |
| `make dev-down` | `docker compose --profile ml down`，停止全部服务并保留数据 |
| `make dev-down-clean` | `docker compose --profile ml down -v`，停止并删除命名卷（不可恢复） |
| `make dev-ps` | `docker compose ps` |
| `make dev-logs` | 跟随全部服务日志 |
| `make web-logs` | 只跟随 `web` 服务日志 |
| `make worker-logs` | 只跟随 Label Studio `worker` 日志 |
| `make workers-logs` | 同时跟随 LS `worker` 与 `ml-worker` 日志 |
| `make dev-rebuild` | 重建 `app` 与 `web` 镜像 |
| `make dev-shell` | 进入 `app` 容器 bash |
| `make ml-up` | `docker compose --profile ml up -d --build`，启动 ml 侧车 |
| `make ml-down` | 停止 `ml-api` 与 `ml-worker` |
| `make ml-logs` | 跟随 ml 侧车日志 |
| `make ml-rebuild` | 重建 ml 侧车相关镜像（`docker compose --profile ml build`，会处理所有可构建服务） |
| `make docker-migrate-dev` | 在 `app` 内执行迁移 |
| `make docker-makemigrations-dev` | 在 `app` 内生成迁移 |
| `make docker-collectstatic-dev` | 在 `app` 内收集静态文件 |
| `make docker-createsuperuser` | 在 `app` 内创建超级用户 |
| `make docker-admin-org EMAIL=<邮箱>` | 为超级用户补组织（命令行创建后必须执行） |
| `make docker-shell` | 在 `app` 内进入 Django shell_plus |
| `make docker-test` | 在 ml 镜像内运行训练域（FastAPI/SQLAlchemy）测试 |
| `make docker-test-gateway` | 在 `app` 内运行 Django `/api/training/` 网关测试 |
| `make docker-config` | `docker compose config -q` 校验编排文件 |

旧命令名 `docker-build` / `docker-up` / `docker-up-build` / `docker-down` / `docker-down-clean` / `docker-ps` / `docker-logs` 仍作为别名保留。

## 常见问题

### 什么时候需要重建镜像？

只改 `label_studio/`、`services/`、`web/apps`、`web/libs` 等**挂载目录内的源码**时不需要重建；改依赖清单、Dockerfile、`web/package.json`/`yarn.lock`、`webpack.config.js`/`tsconfig` 等**烘焙进镜像的文件**时需要重建。完整矩阵见上文「改什么 / 是否重建」。

### HMR 不生效 / 页面样式没更新

1. 确认 `web` 容器 healthy：`docker compose ps web`；首次启动 `web` 需要编译，最长可能约 5 分钟。
2. 确认浏览器打开的是 <http://localhost:8080>，且前端资源来自 `http://localhost:8010/react-app/`；直接打开 8010 只用于验证前端。
3. `docker compose logs -f web` 看是否有编译错误；用 `docker compose exec app printenv FRONTEND_HMR FRONTEND_HOSTNAME` 确认 Django 拿到的 HMR 配置。
4. 如果改的是 `web/webpack.config.js`、`tsconfig` 等配置文件，需要 `docker compose build web` 后重启（这些文件不在挂载范围）。
5. 远程/局域网访问时，`FRONTEND_HOSTNAME` 必须是浏览器可访问的地址，否则浏览器会去请求错误的 HMR 地址。

### 新增前端依赖后页面报模块找不到

修改 `web/package.json` 后先更新 `web/yarn.lock`（二选一）：

```bash
# 宿主机有 Node/corepack（本机 Node 22 自带 corepack）
cd web && corepack yarn install

# 或者用 web-dev 镜像生成 lock（会把 node_modules 装到宿主机 web/）
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD/web":/build/web -w /build/web \
  --entrypoint yarn yamato/label-studio-web-dev:dev install
```

然后重建镜像：

```bash
docker compose build web app
docker compose up -d
```

`node_modules` 烘焙在 `web-dev` 镜像里，而不是宿主机挂载目录；只改 `package.json`、不更新 `yarn.lock` 或不重建，都不会生效。

### 后端 / ml 依赖变更

- `pyproject.toml` 变化：先更新 `poetry.lock`，再 `make dev-rebuild`（重建 app + web），必要时 `make ml-rebuild`。

  ```bash
  # 宿主机没装 Poetry 时，用独立 poetry-tools 镜像生成 lock（runtime 不再包含 Poetry）
  docker build --network=host --target poetry-tools -t yamato/label-studio-poetry:dev .
  docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$PWD":/label-studio -w /label-studio \
    yamato/label-studio-poetry:dev lock
  # 或直接 make poetry-lock
  ```

- `services/requirements-ml.txt`、`TORCH_*` / `ML_PIP_INDEX_URL` 等构建参数变化：`make ml-rebuild` 后 `make ml-up`。
- 只改 Python 源码、不新增依赖时不需要重建；不要用 `docker compose down -v`，那会清空数据库和 MinIO 数据。

### 镜像太大 / 磁盘占用高

清理缓存后本机镜像体积量级：`app` ≈ 1.5 GB，`ml` ≈ 10.2 GB（cu130），`web-dev` ≈ 2.6 GB。`web-dev` 仍把 `node_modules` 烘焙进镜像换取启动即 HMR，但构建时会执行 `yarn cache clean` 并清理 `/root/.cache`，不再把约 4.7GB 的包缓存留在镜像里；web 仍以 root 运行（已知取舍）。清理不再使用的构建缓存：

```bash
docker image prune
docker builder prune
```

### Windows / WSL2

不建议在原生 Windows 文件系统上运行：bind mount 性能差，文件权限与 UID/GID 容易不一致。请在 WSL2 的 Linux 文件系统中克隆仓库，并把 Docker Desktop 的 WSL2 集成打开；Dev Containers 同样建议从 WSL2 中打开仓库。

宿主 UID/GID 不是 1000 时，bind mount 的文件在容器内可能不可写。先在仓库根目录创建 `.env` 并写入：

```bash
APP_UID=$(id -u)
APP_GID=$(id -g)
```

再执行 `make dev-up-build` 或 Reopen in Container；`app` / `worker` 会使用该 UID/GID 构建。

### 已知限制（已确认取舍）

- **无组织历史数据**：没有 active organization 的用户仍可见 `organization_id IS NULL` 的历史训练任务/项目（沿用旧 DRF 的 `None == None` 行为）；多用户实例如需收紧，应另开 issue 加 `created_by` 过滤。
- **web 容器仍以 root 运行**：`web-dev` 镜像默认 root，只挂载源码目录；如宿主机出现 root 属主文件，用 `sudo chown -R "$(id -u):$(id -g)" web/apps web/libs web/tools web/scripts` 修正。彻底解决需要改 node 用户，本次未做。
- **跨域不建外键**：`project_id` / `organization_id` / `created_by_id` 仍是普通整数列，由 API/启动脚本校验；存量库保留原 Django 外键，新库不建，这是已确认的设计。

### MinIO 官方镜像拉取失败

官方 `minio/minio` 镜像当前在 Docker Hub 不可用，本项目默认使用 `pgsty/minio:RELEASE.2026-08-04T00-00-00Z`。可在 `.env` 中设置 `MINIO_IMAGE` 换成其他可用镜像后重新 `docker compose up -d`。

### 命令行创建的管理员登录后看不到项目 / 提示没有组织

`createsuperuser` 不会自动建组织。请在创建后执行：

```bash
make docker-admin-org EMAIL=<你的邮箱>
# 或 docker compose exec app python docker/ensure_admin_org.py <你的邮箱>
```

浏览器 Sign up 注册的用户会自动建组织，不需要这一步。

### 默认只启动了 6 个服务，ml-api 访问不到

`ml-api` / `ml-worker` 属于 `ml` profile，默认不启动。执行 `docker compose --profile ml up -d`（或 `make ml-up`）后再访问 <http://localhost:8991/health>。不需要时用 `make ml-down` 停掉即可。

### 端口被占用

在 `.env` 中改对应变量后 `docker compose up -d`：`APP_PORT`、`WEB_PORT`、`ML_API_PORT`、`POSTGRES_PORT`、`REDIS_PORT`、`MINIO_PORT`、`MINIO_CONSOLE_PORT`。改端口后如果浏览器访问异常，同步调整 `HOST` / `FRONTEND_HOSTNAME`。

### 完全重置

```bash
docker compose --profile ml down -v   # 删除所有命名卷（数据库/MinIO/appdata/Redis）
rm -rf models/trained                 # 可选：清空训练产物，保留基模
docker compose up -d --build
```

`down -v` 不可恢复；`./models` 是宿主机目录，不会被删除。

### 修改数据卷后凭据不一致

如果已经初始化过 PostgreSQL / MinIO 数据卷，再修改 `POSTGRES_*` 或 `MINIO_ROOT_*` 凭据，旧卷里的用户/密钥不会自动更新，容器会连接失败。开发环境可直接重建数据卷：

```bash
docker compose --profile ml down -v
docker compose up -d --build
```

## 附录：非容器本地开发（备选）

仅在不想使用容器时参考。前置：Python 3.12 + Poetry 2.x、Node 22 + Yarn 1.22.22，以及本机可访问的 PostgreSQL / Redis / MinIO。

```bash
# 1. 后端依赖（含测试组；训练依赖不在 app 环境）
poetry install --no-root --only main,test

# 2. 按本机中间件修改 .env（HOST、POSTGRE_*、REDIS_*、MINIO_* 等）
cp .env.example .env

# 3. 前端
cd web && yarn install --frozen-lockfile && yarn build && cd ..

# 4. 迁移、静态文件、管理员（管理员需补组织，见上文）
python label_studio/manage.py migrate
python label_studio/manage.py collectstatic --noinput --no-default-ignore
python label_studio/manage.py createsuperuser
python docker/ensure_admin_org.py <你的邮箱>

# 5. 启动
python label_studio/manage.py runserver 0.0.0.0:8080
```

说明：app 依赖不再包含 torch/ultralytics/fastapi/uvicorn；需要本地调试 ml-api / ml-worker / 训练域测试时，额外安装 `services/requirements-ml.txt` 与对应 torch，或直接使用容器。训练域已不在 Django 侧，Django 只保留 `/api/training/` 网关。

## 致谢

本项目基于 [HumanSignal](https://humansignal.com/) 开源的 Label Studio 二次开发，保留了其核心标注、数据管理、导出和用户鉴权功能。感谢 Label Studio 团队的开源贡献。

- 原项目：<https://github.com/HumanSignal/label-studio>
- License：Apache-2.0（见仓库根目录 `LICENSE`）
