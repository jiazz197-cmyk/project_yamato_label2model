"""Yamato ML 侧车：训练编排（BaseModel / TrainingJob）+ 推理路由。

训练域从 Django training app 完整迁移到这里：
- 表结构由 Alembic 维护（``services/ml_api/migrations``），沿用原表名/列名；
- Django 只保留项目、组织、用户与鉴权，``/api/training/`` 以内部令牌转发到此；
- 真实 YOLO 训练执行仍由 yolo-3 issue 落地（``training_jobs`` 目前只做记录）。

启动命令：

    uvicorn services.ml_api.app:app --host 0.0.0.0 --port 8991
"""

import hmac
import logging
import os
from typing import Any

import redis
import rq
import sqlalchemy as sa
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from services.ml_api.db import get_session
from services.ml_api.jobs import cancel_training_job
from services.ml_api.model_files import scan_local_models
from services.ml_api.models import TRAIN_SUBSETS, BaseModel, ProjectRef, TrainingJob, utcnow
from services.ml_api.serializers import base_model_to_dict, training_job_to_dict

logger = logging.getLogger(__name__)

# 内部 API 不暴露 /docs、/redoc 与 /openapi.json，避免绕过内部令牌读取接口定义。
app = FastAPI(
    title='Yamato ML Sidecar',
    version='0.2.0',
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def get_expected_token() -> str:
    """读取内部令牌：优先 ML_API_INTERNAL_TOKEN，为空时回退 TRAINER_INTERNAL_TOKEN 兼容旧配置。"""
    return os.environ.get('ML_API_INTERNAL_TOKEN', '') or os.environ.get('TRAINER_INTERNAL_TOKEN', '')


def require_internal_token(
    x_internal_token: str | None = Header(default=None, alias='X-Internal-Token'),
) -> None:
    """校验内部调用令牌；未配置令牌时 fail-closed，避免侧车裸奔。"""
    expected_token = get_expected_token()
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='内部令牌未配置：请设置 ML_API_INTERNAL_TOKEN',
        )
    if not x_internal_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='缺少内部令牌：请在请求头 X-Internal-Token 中携带',
        )
    if not hmac.compare_digest(x_internal_token.encode('utf-8'), expected_token.encode('utf-8')):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='内部令牌无效：请求头 X-Internal-Token 与 ML_API_INTERNAL_TOKEN 不一致',
        )


def current_organization_id(
    x_organization_id: str | None = Header(default=None, alias='X-Organization-Id'),
) -> int | None:
    """从内部请求头读取当前组织；空值表示用户没有 active organization。"""
    if not x_organization_id:
        return None
    try:
        return int(x_organization_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='组织标识无效') from exc


def current_user_id(
    x_user_id: str | None = Header(default=None, alias='X-User-Id'),
) -> int | None:
    """从内部请求头读取当前用户 ID（审计字段 created_by_id 使用）。"""
    if not x_user_id:
        return None
    try:
        return int(x_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='用户标识无效') from exc


def placeholder_response(message: str) -> JSONResponse:
    """返回统一的 501 占位响应，并标记由 yolo-3 issue 接管。"""
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={'detail': message, 'todo': 'yolo-3'},
    )


def get_redis_connection() -> redis.Redis:
    """按环境变量创建 Redis 连接；带超时，避免队列接口无限挂起。"""
    return redis.Redis(
        host=os.environ.get('REDIS_HOST', 'redis'),
        port=int(os.environ.get('REDIS_PORT', '6379')),
        db=int(os.environ.get('REDIS_DB', '0')),
        socket_connect_timeout=3,
        socket_timeout=5,
    )


class FieldValidationError(Exception):
    """字段级校验失败；响应体保持 DRF 的 ``{"field": ["message"]}`` 结构。"""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(message)


@app.exception_handler(FieldValidationError)
async def field_validation_error_handler(_request, exc: FieldValidationError) -> JSONResponse:
    """把字段错误渲染为顶层字段键，避免 FastAPI 默认的 ``{"detail": ...}`` 包装。"""
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={exc.field: [exc.message]})


def _invalid_field(field: str, message: str) -> FieldValidationError:
    """构造 DRF 风格字段错误。"""
    return FieldValidationError(field, message)


def _is_ascii_digits(value: str) -> bool:
    """只接受 ASCII 数字；``str.isdigit()`` 对 ``²`` 等字符为真但 int() 会炸。"""
    return value.isascii() and value.isdigit()


def _parse_pk(payload: dict[str, Any], field: str) -> int:
    """解析整型外键；缺失/非法按 DRF 序列化器行为返回 400。

    只接受 int 或纯 ASCII 数字字符串；bool/float 一律拒绝，避免 ``int(1.9)`` 被
    静默截断成 1。
    """
    value = payload.get(field)
    if value is None:
        raise _invalid_field(field, 'This field is required.')
    if isinstance(value, bool):
        raise _invalid_field(field, f'Incorrect type. Expected pk value, received {value!r}.')
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _is_ascii_digits(value):
        return int(value)
    raise _invalid_field(field, f'Incorrect type. Expected pk value, received {value!r}.')


def _validate_hyperparams(hyperparams: dict[str, Any]) -> None:
    """校验当前 adapter 实际使用的超参；未知键保留给后续扩展。

    - epochs: 1..100000
    - imgsz: 32..16384
    - batch: -1（自动）或 1..4096
    - device: 字符串或非负整数（如 ``cpu``、``0``、``0,1``）
    """
    checks = (
        ('epochs', 1, 100000),
        ('imgsz', 32, 16384),
    )
    for key, minimum, maximum in checks:
        if key not in hyperparams:
            continue
        value = hyperparams[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise _invalid_field('hyperparams', f'{key} must be an integer.')
        if not minimum <= value <= maximum:
            raise _invalid_field('hyperparams', f'{key} must be between {minimum} and {maximum}.')

    if 'batch' in hyperparams:
        value = hyperparams['batch']
        if isinstance(value, bool) or not isinstance(value, int):
            raise _invalid_field('hyperparams', 'batch must be an integer.')
        if value != -1 and not 1 <= value <= 4096:
            raise _invalid_field('hyperparams', 'batch must be -1 or between 1 and 4096.')

    if 'device' in hyperparams:
        value = hyperparams['device']
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise _invalid_field('hyperparams', 'device must be a string or integer.')
        if isinstance(value, int) and value < 0:
            raise _invalid_field('hyperparams', 'device must be a non-negative integer.')
        if isinstance(value, str) and len(value) > 64:
            raise _invalid_field('hyperparams', 'device is too long.')


def get_visible_project(session: Session, project_id: int) -> ProjectRef | None:
    """读取未软删的 Django 项目。

    Django 的 ``Project.objects`` 默认 manager 会过滤 ``deleted_at``；训练域
    只读映射 ``project`` 表，必须自己加同样的过滤条件，否则软删项目仍可建
    训练任务。
    """
    return session.scalars(
        sa.select(ProjectRef).where(
            ProjectRef.id == project_id,
            ProjectRef.deleted_at.is_(None),
        )
    ).first()


@app.get('/health')
def health() -> dict[str, str]:
    """健康检查接口；不参与内部令牌校验。"""
    return {'status': 'UP', 'service': 'ml-api'}


# ---------------------------------------------------------------------------
# BaseModel
# ---------------------------------------------------------------------------


@app.get('/api/training/base-models/scan', dependencies=[Depends(require_internal_token)])
def scan_base_models() -> list[dict[str, Any]]:
    """扫描 LOCAL_MODEL_ROOT 下的一级子目录，返回可识别的 YOLO 基模候选。"""
    return scan_local_models(os.environ.get('LOCAL_MODEL_ROOT', ''))


@app.get('/api/training/base-models', dependencies=[Depends(require_internal_token)])
def list_base_models(
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    organization_id: int | None = Depends(current_organization_id),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """服务器预置（organization 为空）+ 本组织可见的活跃基模。"""
    statement = sa.select(BaseModel).where(BaseModel.is_active.is_(True))
    if organization_id is None:
        statement = statement.where(BaseModel.organization_id.is_(None))
    else:
        statement = statement.where(
            sa.or_(
                BaseModel.organization_id.is_(None),
                BaseModel.organization_id == organization_id,
            )
        )
    statement = statement.order_by(BaseModel.id).offset(offset).limit(limit)
    return [base_model_to_dict(model) for model in session.scalars(statement)]


@app.get('/api/training/base-models/{base_model_id}', dependencies=[Depends(require_internal_token)])
def get_base_model(
    base_model_id: int,
    organization_id: int | None = Depends(current_organization_id),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """BaseModel 详情：停用或跨组织访问按不可见处理。"""
    model = session.get(BaseModel, base_model_id)
    if model is None or not model.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Base model not found.')
    if not model.has_permission(organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Base model not found.')
    return base_model_to_dict(model)


# ---------------------------------------------------------------------------
# TrainingJob
# ---------------------------------------------------------------------------


@app.get('/api/training/jobs', dependencies=[Depends(require_internal_token)])
def list_training_jobs(
    project: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    organization_id: int | None = Depends(current_organization_id),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """TrainingJob 列表：可选 ``?project=<id>``、``limit/offset`` 过滤。"""
    statement = sa.select(TrainingJob)
    if organization_id is None:
        statement = statement.where(TrainingJob.organization_id.is_(None))
    else:
        statement = statement.where(TrainingJob.organization_id == organization_id)

    if project is not None and project != '':
        if not _is_ascii_digits(project):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Project not found.')
        project_id = int(project)
        ref = get_visible_project(session, project_id)
        if ref is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Project not found.')
        if ref.organization_id != organization_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Project not found.')
        statement = statement.where(TrainingJob.project_id == project_id)

    statement = (
        statement.order_by(TrainingJob.created_at.desc(), TrainingJob.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return [training_job_to_dict(job) for job in session.scalars(statement)]


@app.post(
    '/api/training/jobs',
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_internal_token)],
)
def create_training_job(
    payload: dict[str, Any] | None = Body(default=None),
    organization_id: int | None = Depends(current_organization_id),
    user_id: int | None = Depends(current_user_id),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """创建训练任务记录（真实训练执行由 yolo-3 issue 接入）。"""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='请求体必须是 JSON 对象')

    project_id = _parse_pk(payload, 'project')
    base_model_id = _parse_pk(payload, 'base_model')

    train_subset = payload.get('train_subset', 'HasGT')
    if train_subset not in TRAIN_SUBSETS:
        raise _invalid_field('train_subset', f'"{train_subset}" is not a valid choice.')

    hyperparams = payload.get('hyperparams', {})
    if hyperparams is None:
        hyperparams = {}
    if not isinstance(hyperparams, dict):
        raise _invalid_field('hyperparams', 'Expected a JSON object.')
    _validate_hyperparams(hyperparams)

    project_ref = get_visible_project(session, project_id)
    if project_ref is None:
        raise _invalid_field('project', f'Invalid pk "{project_id}" - object does not exist.')
    if project_ref.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Project not found.')

    base_model = session.get(BaseModel, base_model_id)
    if base_model is None or not base_model.is_active:
        raise _invalid_field('base_model', f'Invalid pk "{base_model_id}" - object does not exist.')
    if not base_model.has_permission(organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Base model not found.')

    job = TrainingJob(
        base_model_id=base_model.id,
        project_id=project_ref.id,
        train_subset=train_subset,
        hyperparams=hyperparams,
        status='Pending',
        organization_id=organization_id,
        created_by_id=user_id,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return training_job_to_dict(job)


@app.get('/api/training/jobs/{job_id}', dependencies=[Depends(require_internal_token)])
def get_training_job(
    job_id: int,
    organization_id: int | None = Depends(current_organization_id),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """训练任务详情：跨组织访问返回 403。"""
    job = session.get(TrainingJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Training job not found.')
    if not job.has_permission(organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Training job not found.')
    return training_job_to_dict(job)


@app.patch('/api/training/jobs/{job_id}', dependencies=[Depends(require_internal_token)])
def update_training_job(
    job_id: int,
    payload: dict[str, Any] | None = Body(default=None),
    organization_id: int | None = Depends(current_organization_id),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """训练任务 PATCH：目前只支持 ``{"action": "cancel"}``。"""
    job = session.get(TrainingJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Training job not found.')
    if not job.has_permission(organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Training job not found.')
    if not isinstance(payload, dict) or payload.get('action') != 'cancel':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Only action=cancel is supported.',
        )

    # 原子更新：并发完成/失败不会把终态覆盖成 Canceled。
    result = session.execute(
        sa.update(TrainingJob)
        .where(
            TrainingJob.id == job_id,
            TrainingJob.status.in_(('Pending', 'Running')),
        )
        .values(status='Canceled', completed_at=utcnow())
    )
    updated = result.rowcount
    session.commit()
    session.refresh(job)

    if updated:
        try:
            cancel_training_job(job.id)
        except Exception:  # noqa: BLE001 - Redis/RQ 偶发失败不能阻塞取消落库
            logger.exception('failed to stop RQ job for training_job %s', job.id)
    return training_job_to_dict(job)


@app.get('/api/training/queue', dependencies=[Depends(require_internal_token)])
def get_training_queue() -> JSONResponse:
    """读取 RQ training 队列长度；Redis 连接或查询失败时返回 503。"""
    try:
        queue = rq.Queue('training', connection=get_redis_connection())
        count = len(queue)
    except Exception:  # noqa: BLE001 - 只记录内部错误，不把 Redis 细节回显给调用方
        logger.exception('training queue is unavailable')
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={'detail': '训练队列暂时不可用'},
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content={'queue': 'training', 'count': count})


@app.post('/api/predictions', dependencies=[Depends(require_internal_token)])
def create_prediction(payload: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
    """预标注推理占位接口（原 predictor 路由合并至此）；真实实现由 yolo-3 issue 接管。"""
    return placeholder_response('预标注推理接口尚未实现，将由 yolo-3 issue 接管')
