"""trainer-worker 容器健康检查：确认 RQ worker 已注册到 Redis。"""

import os
import sys

from redis import Redis
from rq import Worker


def main():
    connection = Redis(
        host=os.environ.get('REDIS_HOST', 'redis'),
        port=int(os.environ.get('REDIS_PORT', '6379')),
        db=int(os.environ.get('REDIS_DB', '0')),
    )
    worker_name = os.environ.get('RQ_WORKER_NAME', 'ml-worker')
    try:
        workers = Worker.all(connection=connection)
    except Exception as exc:  # noqa: BLE001 - 健康检查失败时只要非 0 退出码
        print(f'[healthcheck] 无法读取 RQ worker 列表: {exc}', file=sys.stderr)
        return 1

    names = [worker.name for worker in workers]
    if worker_name in names:
        return 0
    print(f'[healthcheck] 未找到 RQ worker {worker_name}，当前: {names}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
