"""Worker 容器健康检查：确认指定队列至少有 N 个 RQ worker 在监听。

LS worker 用 ``RQ_HEALTHCHECK_QUEUE=default`` + 16；训练 worker 用
``RQ_HEALTHCHECK_QUEUE=training`` + 2。``rq worker-pool`` 的 worker 名字是
自动生成的，因此这里按队列成员关系计数，而不是按固定名字查找。
"""

import os
import sys

from redis import Redis
from rq import Worker


def main():
    queue_name = os.environ.get('RQ_HEALTHCHECK_QUEUE', 'training')
    minimum = int(os.environ.get('RQ_HEALTHCHECK_MIN_WORKERS', '1'))

    connection = Redis(
        host=os.environ.get('REDIS_HOST', 'redis'),
        port=int(os.environ.get('REDIS_PORT', '6379')),
        db=int(os.environ.get('REDIS_DB', '0')),
        socket_connect_timeout=3,
        socket_timeout=3,
    )

    try:
        workers = Worker.all(connection=connection)
    except Exception as exc:  # noqa: BLE001 - 健康检查失败只要非 0 退出码
        print(f'[healthcheck] 无法读取 RQ worker 列表: {exc}', file=sys.stderr)
        return 1

    listeners = []
    for worker in workers:
        try:
            if queue_name in worker.queue_names():
                listeners.append(worker.name)
        except Exception:  # noqa: BLE001 - worker 正在退出时忽略该条
            continue

    if len(listeners) >= minimum:
        return 0

    print(
        f'[healthcheck] 队列 {queue_name} 只有 {len(listeners)} 个 worker，'
        f'少于要求的 {minimum}；当前: {listeners}',
        file=sys.stderr,
    )
    return 1


if __name__ == '__main__':
    sys.exit(main())
