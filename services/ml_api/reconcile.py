"""启动对账入口：把 worker 已消失但数据库仍为 Running 的训练任务置 Failed。

由 ``docker/ml-api-start.sh`` 在 Alembic 引导之后、uvicorn 启动之前执行。
Redis 不可用时只记录日志，不会误伤任务。
"""

import logging

from services.ml_api.jobs import reconcile_running_training_jobs

logging.basicConfig(level=logging.INFO, format='[ml-api] %(levelname)s %(message)s')


def main() -> None:
    """执行一次训练任务对账。"""
    reconciled = reconcile_running_training_jobs()
    print(f'[ml-api] training running reconciliation: {reconciled} job(s) marked Failed')


if __name__ == '__main__':
    main()
