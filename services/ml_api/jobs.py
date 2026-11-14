"""ML 侧车的 RQ 作业函数与训练入队 helper。

训练任务使用独立的 ``training`` 队列：入队时预留很长的 ``job_timeout``（默认
7 天），异常时由 ``on_training_failure`` 把 ``training_job`` 置为 Failed 并结束，
不重试、不依赖延迟任务/scheduler。真实 YOLO 训练逻辑由后续 yolo-3 issue 接入。
"""

import logging
import os

import redis
import rq

from services.ml_api.db import SessionLocal
from services.ml_api.models import TrainingJob, utcnow

logger = logging.getLogger(__name__)

TRAINING_QUEUE = 'training'
# 真实训练可能跑数小时；默认给 7 天，避免 RQ 默认 180s 误杀。
DEFAULT_TRAINING_JOB_TIMEOUT = 7 * 24 * 60 * 60


def training_job_timeout() -> int:
    """训练任务的 job_timeout（秒）；非法/非正值回退到默认 7 天。"""
    raw = os.environ.get('TRAINING_JOB_TIMEOUT')
    if raw is None or raw == '':
        return DEFAULT_TRAINING_JOB_TIMEOUT
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TRAINING_JOB_TIMEOUT
    return value if value > 0 else DEFAULT_TRAINING_JOB_TIMEOUT


def get_redis_connection() -> redis.Redis:
    """创建 RQ 使用的 Redis 连接；带超时，避免入队无限挂起。"""
    return redis.Redis(
        host=os.environ.get('REDIS_HOST', 'redis'),
        port=int(os.environ.get('REDIS_PORT', '6379')),
        db=int(os.environ.get('REDIS_DB', '0')),
        socket_connect_timeout=3,
        socket_timeout=5,
    )


def get_training_queue() -> rq.Queue:
    """``training`` 队列；队列默认 timeout 也设成长值，避免漏传时被 180s 杀掉。"""
    return rq.Queue(
        TRAINING_QUEUE,
        connection=get_redis_connection(),
        default_timeout=training_job_timeout(),
    )


def on_training_failure(job, connection, exc_type, exc_value, traceback) -> None:
    """RQ 失败回调：把对应 training_job 置 Failed 并结束，不做重试。

    RQ 默认不会自动重试；这里显式更新业务表，避免任务在 Redis 里 failed、数据库
    里却一直 Running。Completed/Canceled 的终态不覆盖。
    """
    try:
        training_job_id = int(job.args[0])
    except (AttributeError, IndexError, TypeError, ValueError):
        logger.warning('training failure callback received job without training_job id: %r', job)
        return

    try:
        with SessionLocal() as session:
            training_job = session.get(TrainingJob, training_job_id)
            if training_job is None:
                logger.warning('training_job %s not found for failure callback', training_job_id)
                return
            if training_job.status in ('Completed', 'Canceled'):
                return
            training_job.status = 'Failed'
            message = f'{exc_type.__name__}: {exc_value}'
            training_job.error_message = message[:4000]
            training_job.completed_at = utcnow()
            session.commit()
    except Exception:  # noqa: BLE001 - 失败回调本身不能影响 RQ 的失败处理
        logger.exception('failed to mark training_job %s as Failed', training_job_id)


def enqueue_training_job(training_job_id: int):
    """把训练任务放入 ``training`` 队列。

    - ``job_timeout`` 默认 7 天（``TRAINING_JOB_TIMEOUT`` 可覆盖）；
    - 显式 ``retry=None``：任何异常直接结束，不重试；
    - ``on_failure`` 负责把数据库状态置 Failed；
    - 使用确定性 job_id，便于调用方做幂等/去重。
    """
    queue = get_training_queue()
    return queue.enqueue(
        execute_training_job,
        int(training_job_id),
        job_timeout=training_job_timeout(),
        on_failure=on_training_failure,
        retry=None,
        job_id=f'training:{int(training_job_id)}',
    )


def ping(*args, **kwargs) -> str:
    """探活作业：返回 pong，用于确认 worker 已连接 training 队列。"""
    return 'pong'


def execute_training_job(training_job_id, **kwargs):
    """训练执行占位。

    真实 YOLO 训练（数据准备、训练执行、指标上报）由 yolo-3 issue 实现；通过
    ``enqueue_training_job`` 入队后，任何异常都会触发 ``on_training_failure``，
    任务直接失败结束，不会重试。
    """
    raise NotImplementedError('YOLO 训练执行由 yolo-3 issue 实现')
