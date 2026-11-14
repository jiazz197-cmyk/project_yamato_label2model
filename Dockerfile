# syntax=docker/dockerfile:1.7
#
# 容器化开发镜像定义（多阶段）。
#   web-deps   —— Node 22 安装前端依赖（web / web-dev 共用）
#   web        —— 构建生产用 web/dist（app 镜像兜底使用）
#   web-dev    —— 前端 HMR 开发服务器（docker compose 的 web 服务）
#   python-deps—— Poetry 安装 Django app 依赖（不含 torch/ultralytics）
#   app        —— Django + 前端静态产物
#   ml         —— FROM app，额外安装 CUDA 13.0 (cu130) torch/torchvision + ultralytics + FastAPI
#
# 开发时源码通过 docker-compose bind mount 覆盖镜像内副本；
# 只有依赖清单 / Dockerfile 变化才需要重建镜像。

ARG PYTHON_IMAGE=python:3.12.16-slim-bookworm
ARG NODE_IMAGE=node:22.19.0-bookworm-slim

# ---------------------------------------------------------------------------
# 1) 前端依赖层（web / web-dev 共用，源码通过 volume 覆盖）
# ---------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS web-deps

ARG YARN_VERSION=1.22.22
# yarn 1 直接使用 yarn.lock 里的 registry.yarnpkg.com 地址；
# 传入该参数时把锁文件中的 registry 前缀替换为镜像地址，加速国内安装。
ARG YARN_REGISTRY=https://registry.npmmirror.com
ARG APT_MIRROR=http://mirrors.tuna.tsinghua.edu.cn

ENV NX_DAEMON=false \
    NODE_OPTIONS=--max-old-space-size=8192

WORKDIR /build

RUN if [ -n "${APT_MIRROR}" ]; then \
        sed -i \
            -e "s#http://deb.debian.org/debian-security#${APT_MIRROR}/debian-security#g" \
            -e "s#http://deb.debian.org/debian#${APT_MIRROR}/debian#g" \
            /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && test "$(yarn --version)" = "${YARN_VERSION}"

# web/release.js 会读取仓库根目录的 pyproject.toml 获取版本号
COPY pyproject.toml ./
COPY web/package.json web/yarn.lock ./web/

WORKDIR /build/web
RUN if [ -n "${YARN_REGISTRY}" ]; then \
        sed -i "s#https://registry.yarnpkg.com#${YARN_REGISTRY}#g" yarn.lock \
        && yarn config set registry "${YARN_REGISTRY}"; \
    fi

RUN yarn install --frozen-lockfile --network-timeout 600000

# ---------------------------------------------------------------------------
# 2) 前端生产构建（app 镜像内的 web/dist）
# ---------------------------------------------------------------------------
FROM web-deps AS web

ENV CI=true

COPY web/ ./
RUN yarn build

# ---------------------------------------------------------------------------
# 3) 前端 HMR 开发服务器（compose 的 web 服务，node_modules 已烘焙）
# ---------------------------------------------------------------------------
FROM web-deps AS web-dev

COPY web/ ./

EXPOSE 8010

CMD ["yarn", "dev", "--host", "0.0.0.0"]

# ---------------------------------------------------------------------------
# 4) Python 依赖层
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS python-deps

ARG POETRY_VERSION=2.4.1
ARG POETRY_PYPI_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG APT_MIRROR=http://mirrors.tuna.tsinghua.edu.cn

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=${POETRY_PYPI_URL} \
    POETRY_REPOSITORIES_PYPI_URL=${POETRY_PYPI_URL} \
    PIP_TIMEOUT=120 \
    PIP_RETRIES=10 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

RUN if [ -n "${APT_MIRROR}" ]; then \
        sed -i \
            -e "s#http://deb.debian.org/debian-security#${APT_MIRROR}/debian-security#g" \
            -e "s#http://deb.debian.org/debian#${APT_MIRROR}/debian#g" \
            /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}" "virtualenv==20.26.6"

WORKDIR /label-studio
COPY pyproject.toml poetry.toml poetry.lock ./
# --only main,test：不安装 build 组；test 组保留，便于容器内跑 pytest
RUN for attempt in 1 2 3 4 5; do \
        echo "poetry install attempt ${attempt}"; \
        poetry install --no-root --no-interaction --only main,test && exit 0; \
        echo "poetry install failed (attempt ${attempt}), retrying..."; \
        sleep 10; \
    done; \
    exit 1

# ---------------------------------------------------------------------------
# 5) 运行时公共层
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

ARG APT_MIRROR=http://mirrors.tuna.tsinghua.edu.cn

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN if [ -n "${APT_MIRROR}" ]; then \
        sed -i \
            -e "s#http://deb.debian.org/debian-security#${APT_MIRROR}/debian-security#g" \
            -e "s#http://deb.debian.org/debian#${APT_MIRROR}/debian#g" \
            /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=python-deps /usr/local /usr/local

# ---------------------------------------------------------------------------
# 6) Django app 镜像
# ---------------------------------------------------------------------------
FROM runtime AS app

ARG APP_UID=1000
ARG APP_GID=1000

ENV DJANGO_SETTINGS_MODULE=core.settings.label_studio \
    DJANGO_DB=postgresql \
    BASE_DATA_DIR=/label-studio/data \
    LOCAL_MODEL_ROOT=/models \
    HOST=http://localhost:8080 \
    DEBUG=1 \
    RUN_STARTUP_TASKS=1 \
    PYTHONPATH=/label-studio

RUN set -eu; \
    if ! getent group "${APP_GID}" >/dev/null; then groupadd -g "${APP_GID}" app; fi; \
    if ! getent passwd "${APP_UID}" >/dev/null; then useradd -m -u "${APP_UID}" -g "${APP_GID}" -s /bin/bash app; fi

WORKDIR /label-studio

COPY --chown=app:app . .
COPY --from=web --chown=app:app /build/web/dist ./web/dist
COPY --chown=app:app docker/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY --chown=app:app docker/ml-api-start.sh /usr/local/bin/ml-api-start.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh /usr/local/bin/ml-api-start.sh \
    && mkdir -p data /models \
    && chown app:app /label-studio \
    && chown -R app:app data /models

# 项目自身以 editable 方式安装：label_studio/__init__.py 依赖 importlib.metadata
# 读取 label-studio 包元数据，因此不能只装依赖不装项目本身。
RUN pip install --no-cache-dir --no-deps --no-build-isolation -e .

# 构建期收集 Django 静态文件；开发时源码挂载后由 runserver 的 staticfiles 服务
RUN DJANGO_DB=sqlite \
    BASE_DATA_DIR=/tmp/label-studio-build-data \
    LOCAL_MODEL_ROOT=/tmp/label-studio-build-models \
    MINIO_SKIP=1 \
    python label_studio/manage.py collectstatic --noinput --no-default-ignore \
    && rm -rf /tmp/label-studio-build-data /tmp/label-studio-build-models \
    && chown -R app:app label_studio/core/static_build

USER app

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8080/health/ || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "label_studio/manage.py", "runserver", "0.0.0.0:8080", "--noreload"]

# ---------------------------------------------------------------------------
# 7) ML 镜像：app 基础 + torch / ultralytics / FastAPI
#    训练与推理合并到 services.ml_api，由 ml-api / ml-worker 共用。
#    默认 CPU；CUDA 变体通过 TORCH_INDEX_URL / TORCH_VERSION / TORCHVISION_VERSION 覆盖。
# ---------------------------------------------------------------------------
FROM app AS ml

ARG ML_PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG TORCH_INDEX_URL=https://mirrors.nju.edu.cn/pytorch/whl/cu130
ARG TORCH_VERSION=2.11.0
ARG TORCHVISION_VERSION=0.26.0
# 可选 apt 镜像前缀（如 http://mirrors.tuna.tsinghua.edu.cn），用于加速系统依赖安装
ARG APT_MIRROR=

# 侧车服务不执行 Django 迁移
ENV RUN_STARTUP_TASKS=0

USER root

# OpenCV（ultralytics 依赖）与 torch CPU 运行时所需的系统库
RUN if [ -n "${APT_MIRROR}" ]; then \
        sed -i \
            -e "s#http://deb.debian.org/debian-security#${APT_MIRROR}/debian-security#g" \
            -e "s#http://deb.debian.org/debian#${APT_MIRROR}/debian#g" \
            /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade "pip>=26.0" \
        --index-url "${ML_PIP_INDEX_URL}" \
        --timeout 120 --retries 10

# pip>=26 的 --resume-retries 会在读超时后从断点续传；大 wheel（cudnn 366MB）
# 在国内镜像上偶尔会断流，没有这个参数会导致整个 ml 层构建失败。
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout 30 --retries 10 --resume-retries 50 \
        --index-url "${TORCH_INDEX_URL}" \
        --extra-index-url "${ML_PIP_INDEX_URL}" \
        "torch==${TORCH_VERSION}" "torchvision==${TORCHVISION_VERSION}"

COPY --chown=app:app services/requirements-ml.txt /tmp/requirements-ml.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout 30 --retries 10 --resume-retries 50 \
        --index-url "${ML_PIP_INDEX_URL}" \
        -r /tmp/requirements-ml.txt \
    && rm -f /tmp/requirements-ml.txt

RUN python -c "import torch, torchvision; print('torch', torch.__version__, '/ torchvision', torchvision.__version__)"

USER app

EXPOSE 8991

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8991/health || exit 1

# 先执行 Alembic 表结构引导，再启动 FastAPI（见 docker/ml-api-start.sh）
CMD ["ml-api-start.sh"]
