#!/bin/sh
# 容器启动入口。
# 只有在 RUN_STARTUP_TASKS=1（app 服务）时才执行数据库迁移与 MinIO 初始化，
# ml-api / ml-worker 复用同一镜像但不执行这些启动任务。
set -eu

if [ "${RUN_STARTUP_TASKS:-0}" = "1" ]; then
    echo '[entrypoint] 执行数据库迁移...'
    python label_studio/manage.py migrate --noinput

    if [ -n "${MINIO_STORAGE_ENDPOINT:-}" ]; then
        echo '[entrypoint] 确保 MinIO bucket 存在...'
        python docker/init_minio.py
    fi
fi

exec "$@"
