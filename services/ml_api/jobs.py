"""ML 侧车的 RQ 作业函数与训练入队 helper。

训练任务使用独立的 ``training`` 队列：入队时预留很长的 ``job_timeout``（默认
7 天），异常时由 ``on_training_failure`` 把 ``training_job`` 置为 Failed 并结束，
不重试、不依赖延迟任务/scheduler。真实 YOLO 训练逻辑由后续 yolo-3 issue 接入。

取消与停止：
- 排队中的 job 调 ``Job.cancel()``，从队列/registry 移除；
- 运行中的 job 发送 RQ stop 命令，由 worker 结束当前 job；
- ml-api 启动时调用 ``reconcile_running_training_jobs``，把 worker 已消失但
  DB 仍为 Running 的任务置 Failed，避免 7 天 timeout 内一直显示运行中。
"""

import logging
import os

import redis
import rq
from rq.command import send_stop_job_command
from rq.job import Job, NoSuchJobError
from sqlalchemy import select, update

from services.ml_api.db import SessionLocal
from services.ml_api.models import TrainingJob, utcnow

logger = logging.getLogger(__name__)

TRAINING_QUEUE = 'training'
TRAINING_JOB_ID_PREFIX = 'training-'
# 真实训练可能跑数小时；默认给 7 天，避免 RQ 默认 180s 误杀。
DEFAULT_TRAINING_JOB_TIMEOUT = 7 * 24 * 60 * 60
# worker 心跳超过该时长视为已死，用于启动对账；RQ worker_ttl 默认 420s。
WORKER_HEARTBEAT_MAX_AGE_SECONDS = 180


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


def rq_job_id(training_job_id: int) -> str:
    """训练 job 的 RQ id。

    RQ 的 StartedJobRegistry 使用 ``<job_id>:<execution_id>`` 组合键，因此
    job_id 本身不能包含冒号；只使用字母、数字和短横线。
    """
    return f'{TRAINING_JOB_ID_PREFIX}{int(training_job_id)}'


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


def _mark_training_job_failed(training_job_id: int, message: str) -> int:
    """条件更新失败态；Completed/Canceled 终态不会被覆盖。"""
    with SessionLocal() as session:
        result = session.execute(
            update(TrainingJob)
            .where(
                TrainingJob.id == training_job_id,
                TrainingJob.status.notin_(('Completed', 'Canceled')),
            )
            .values(
                status='Failed',
                error_message=message[:4000],
                completed_at=utcnow(),
            )
        )
        updated = result.rowcount
        session.commit()
        return updated


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
        _mark_training_job_failed(training_job_id, f'{exc_type.__name__}: {exc_value}')
    except Exception:  # noqa: BLE001 - 失败回调本身不能影响 RQ 的失败处理
        logger.exception('failed to mark training_job %s as Failed', training_job_id)


def enqueue_training_job(training_job_id: int):
    """把训练任务放入 ``training`` 队列（同一 training_job 幂等）。

    - ``job_timeout`` 默认 7 天（``TRAINING_JOB_TIMEOUT`` 可覆盖）；
    - 显式 ``retry=None``：任何异常直接结束，不重试；
    - ``on_failure`` 负责把数据库状态置 Failed；
    - 使用确定性 job_id；若同 ID 的 RQ job 已存在则直接返回，不重复入队。
    """
    # RQ job id 只含字母/数字/短横线，避免 StartedJobRegistry 组合键解析失败。
    job_id = rq_job_id(training_job_id)
    connection = get_redis_connection()
    try:
        existing = Job.fetch(job_id, connection=connection)
    except NoSuchJobError:
        existing = None
    if existing is not None:
        return existing

    queue = get_training_queue()
    return queue.enqueue(
        execute_training_job,
        int(training_job_id),
        job_timeout=training_job_timeout(),
        on_failure=on_training_failure,
        retry=None,
        job_id=job_id,
    )


def cancel_training_job(training_job_id: int) -> bool:
    """停止 RQ 中对应的训练 job；不存在时返回 False。

    - queued/deferred/scheduled：``Job.cancel()`` 移除队列并进入取消 registry；
    - started：向 worker 发送 stop 命令，由 worker 结束当前 job；
    - 其它终态不做处理。
    """
    job_id = rq_job_id(training_job_id)
    connection = get_redis_connection()
    try:
        job = Job.fetch(job_id, connection=connection)
    except NoSuchJobError:
        return False

    status = job.get_status(refresh=True)
    status = getattr(status, 'value', status)
    if status in ('queued', 'deferred', 'scheduled'):
        job.cancel()
        return True
    if status == 'started':
        send_stop_job_command(connection, job.id)
        return True
    return False


def reconcile_running_training_jobs() -> int:
    """把没有存活 worker 持有的 Running 任务置为 Failed。

    RQ 在 worker 被 SIGKILL/容器重启时不会执行 ``on_failure``；训练 timeout
    默认 7 天，不能等 RQ 的 abandoned cleanup。这里在 ml-api 启动时做一次对账，
    只处理 Redis 中没有任何当前存活 worker 持有的 job。
    """
    connection = get_redis_connection()
    try:
        workers = rq.Worker.all(connection=connection)
    except Exception:  # noqa: BLE001 - Redis 不可用时不要误伤 Running 任务
        logger.exception('skip training reconciliation: cannot list RQ workers')
        return 0

    now = utcnow()
    active_job_ids = set()
    for worker in workers:
        try:
            last_heartbeat = getattr(worker, 'last_heartbeat', None)
            if last_heartbeat is not None:
                if last_heartbeat.tzinfo is None:
                    last_heartbeat = last_heartbeat.replace(tzinfo=now.tzinfo)
                if (now - last_heartbeat).total_seconds() > WORKER_HEARTBEAT_MAX_AGE_SECONDS:
                    continue
            current_job_id = worker.get_current_job_id()
            if current_job_id:
                active_job_ids.add(current_job_id)
        except Exception:  # noqa: BLE001 - 单个 worker 退出/字段缺失不影响其他 worker
            continue

    message = '训练 worker 在任务完成前停止（启动对账）'
    reconciled = 0
    with SessionLocal() as session:
        running_jobs = session.scalars(
            select(TrainingJob).where(TrainingJob.status == 'Running')
        ).all()
        for training_job in running_jobs:
            if rq_job_id(training_job.id) in active_job_ids:
                continue
            result = session.execute(
                update(TrainingJob)
                .where(
                    TrainingJob.id == training_job.id,
                    TrainingJob.status == 'Running',
                )
                .values(
                    status='Failed',
                    error_message=message,
                    completed_at=utcnow(),
                )
            )
            reconciled += result.rowcount
        session.commit()

    if reconciled:
        logger.warning('reconciled %s orphaned running training job(s)', reconciled)
    return reconciled


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
