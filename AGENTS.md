# AGENTS.md

基于 Label Studio 1.24 (Apache-2.0) 的数据标注平台。保留标注、数据集导出、用户鉴权功能。

## 环境加载机制（关键改动）

`label_studio/core/settings/label_studio.py` 顶部（`from core.settings.base import *` 之前）插入了早期 `.env` 加载逻辑：项目根目录的 `.env` 通过 `django-environ` 读入 `os.environ`，使得 `base.py` 中的 `get_env('POSTGRE_*')`、`get_env('MINIO_*')`、`BASE_DATA_DIR` 等都能从 `.env` 取到值。

原版 LS 在 `base.py` 执行完后才加载 `.env`（通过 `secret_key.py`），导致 `base.py` 内求值的配置读不到 `.env`。本项目修复了此时序问题。

`.env` 在 `.gitignore` 中，但已通过 `git add -f` 提交到仓库（私有部署）。

## 目录结构约束

`label_studio/` 和 `web/` 必须保持为同级目录。`base.py:570-574` 中 `EDITOR_ROOT`、`DM_ROOT`、`REACT_APP_ROOT` 使用硬编码相对路径 `../../web/dist/...`（从 `label_studio/core/settings/` 出发）。

## 数据库

- `DJANGO_DB=default` 在 `.env` 中设置，映射到 PostgreSQL（`base.py:188` 中 `DATABASES_ALL['default'] = DATABASES_ALL[DJANGO_DB_POSTGRESQL]`）
- 原 LS 社区版默认 SQLite（`label_studio.py:19` 中 `get_env('DJANGO_DB', DJANGO_DB_SQLITE)`），本项目通过 `.env` 覆盖为 `default`

## Redis（自定义启用）

`label_studio.py:75-88` 添加了 Redis 启用逻辑。原 LS OSS 版 `base.py:357` 硬编码 `REDIS_ENABLED = False`。设置 `REDIS_ENABLED=True` 后，`RQ_QUEUES` 从 `REDIS_HOST`/`REDIS_PORT` 环境变量构建。

## MinIO

通过 `.env` 中 `MINIO_STORAGE_ENDPOINT` 启用。`base.py:753-764` 检测到此变量后切换 `STORAGES['default']['BACKEND']` 为 `S3Boto3Storage`，上传文件存 MinIO 而非本地磁盘。标注结果仍存 PostgreSQL。

## FSM app 不可删除

`fsm/` app 被 5 个核心模型类继承（`Project`、`Task`、`Annotation`、`TaskLock`、`AnnotationDraft` 继承 `FsmHistoryStateModel`）。删除会导致 Django 无法启动。`ml/`、`ml_models/`、`ml_model_providers/`、`webhooks/` 保留但未使用。

## 开发命令

```bash
# 前端构建（web/dist/ 不存在时必须先构建）
cd web && yarn install --frozen-lockfile && yarn build

# 后端依赖
poetry install

# 数据库迁移 + 静态文件收集
python label_studio/manage.py migrate
python label_studio/manage.py collectstatic --no-default-ignore

# 启动开发服务器
python label_studio/manage.py runserver 0.0.0.0:8080

# 测试（使用 SQLite）
cd label_studio && DJANGO_DB=sqlite pytest -v -m "not integration_tests"
```

`DJANGO_SETTINGS_MODULE` 默认为 `core.settings.label_studio`（`manage.py:8` 设置）。

Makefile 中的 `make run-dev` / `make migrate-dev` 等目标使用 SQLite + `LOG_DIR=tmp`，与 `.env` 中的 PostgreSQL 配置无关。

## WSL 注意事项

项目位于 `/mnt/c/`（Windows 文件系统）。从 Windows 路径复制的文件可能带 CRLF 行尾符，导致 git 显示大量假修改。修复：`find . -type f -name "*.py" -not -path "./.git/*" -exec sed -i 's/\r$//' {} +`。修复后需 `git add -u && git reset` 刷新 stat 缓存。
