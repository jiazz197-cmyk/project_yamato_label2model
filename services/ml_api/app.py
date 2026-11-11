'''Yamato ML 侧车占位服务（训练编排 + 推理路由）。

训练任务提交/查询/取消与预标注推理目前均返回 501 占位，真实 YOLO 实现由后续
yolo-3 issue 落地；training 队列长度查询已可用。启动命令：

    uvicorn services.ml_api.app:app --host 0.0.0.0 --port 8991
'''

import hmac
import os
from typing import Any

import redis
import rq
from fastapi import Body, Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse

# 占位服务不暴露 /docs、/redoc 与 /openapi.json，避免绕过内部令牌读取接口定义。
app = FastAPI(
    title='Yamato ML Sidecar',
    version='0.1.0',
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def get_expected_token() -> str:
    '''读取内部令牌：优先 ML_API_INTERNAL_TOKEN，为空时回退 TRAINER_INTERNAL_TOKEN 兼容旧配置。'''
    return os.environ.get('ML_API_INTERNAL_TOKEN', '') or os.environ.get('TRAINER_INTERNAL_TOKEN', '')


def require_internal_token(
    x_internal_token: str | None = Header(default=None, alias='X-Internal-Token'),
) -> None:
    '''校验内部调用令牌；两个环境变量均为空时关闭校验（便于本地开发）。'''
    expected_token = get_expected_token()
    if not expected_token:
        return
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


def placeholder_response(message: str) -> JSONResponse:
    '''返回统一的 501 占位响应，并标记由 yolo-3 issue 接管。'''
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={'detail': message, 'todo': 'yolo-3'},
    )


def get_redis_connection() -> redis.Redis:
    '''按环境变量创建 Redis 连接；仅在请求处理中调用，避免模块导入时连接失败。'''
    return redis.Redis(
        host=os.environ.get('REDIS_HOST', 'redis'),
        port=int(os.environ.get('REDIS_PORT', '6379')),
        db=int(os.environ.get('REDIS_DB', '0')),
    )


@app.get('/health')
def health() -> dict[str, str]:
    '''健康检查接口；不参与内部令牌校验。'''
    return {'status': 'UP', 'service': 'ml-api'}


@app.post('/api/training/jobs', dependencies=[Depends(require_internal_token)])
def create_training_job(payload: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
    '''提交训练任务占位接口；接收任意 JSON 对象，避免空 body 触发 422。'''
    return placeholder_response('训练任务提交接口尚未实现，将由 yolo-3 issue 接管')


@app.get('/api/training/jobs/{job_id}', dependencies=[Depends(require_internal_token)])
def get_training_job(job_id: str) -> JSONResponse:
    '''查询训练任务占位接口。'''
    return placeholder_response('训练任务状态查询接口尚未实现，将由 yolo-3 issue 接管')


@app.post('/api/training/jobs/{job_id}/cancel', dependencies=[Depends(require_internal_token)])
def cancel_training_job(job_id: str) -> JSONResponse:
    '''取消训练任务占位接口。'''
    return placeholder_response('训练任务取消接口尚未实现，将由 yolo-3 issue 接管')


@app.get('/api/training/queue', dependencies=[Depends(require_internal_token)])
def get_training_queue() -> JSONResponse:
    '''读取 RQ training 队列长度；Redis 连接或查询失败时返回 503。'''
    try:
        queue = rq.Queue('training', connection=get_redis_connection())
        count = len(queue)
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={'detail': f'训练队列不可用：{exc}'},
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content={'queue': 'training', 'count': count})


@app.post('/api/predictions', dependencies=[Depends(require_internal_token)])
def create_prediction(payload: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
    '''预标注推理占位接口（原 predictor 路由合并至此）；接收任意 JSON 对象，避免空 body 触发 422。'''
    return placeholder_response('预标注推理接口尚未实现，将由 yolo-3 issue 接管')
