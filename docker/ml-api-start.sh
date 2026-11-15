#!/bin/sh
# ml-api 启动脚本：先确保训练域表结构（Alembic），再对账遗留 Running 任务，
# 最后启动 FastAPI。额外参数会透传给 uvicorn，例如 --reload --reload-dir /label-studio/services。
set -eu

python -m services.ml_api.db_bootstrap
python -m services.ml_api.reconcile

exec uvicorn services.ml_api.app:app \
    --host 0.0.0.0 \
    --port "${ML_API_PORT:-8991}" \
    "$@"
