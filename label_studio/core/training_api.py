"""训练 REST API 网关：Django 只做登录态/组织上下文，训练域由 FastAPI ml-api 负责。

保留原有 ``/api/training/`` 路径与响应结构，前端/调用方无需改动；真实数据与
训练编排逻辑在 ``services/ml_api``。内部请求头：

- ``X-Internal-Token``：与 ml-api 共享的 ``ML_API_INTERNAL_TOKEN``；
- ``X-User-Id`` / ``X-Organization-Id``：当前用户与 active organization。
"""

import os

import requests
from django.http import QueryDict
from django.urls import path
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

DEFAULT_ML_API_URL = 'http://ml-api:8991'


def ml_api_url() -> str:
    """ml-api 基地址；每次请求读取环境变量，便于测试与本地覆盖。"""
    return os.environ.get('ML_API_URL', DEFAULT_ML_API_URL).rstrip('/')


def ml_api_timeout() -> float:
    """调用 ml-api 的超时时间（秒）。"""
    try:
        return float(os.environ.get('ML_API_TIMEOUT', '10'))
    except (TypeError, ValueError):
        return 10.0


def internal_headers(request) -> dict[str, str]:
    """构造内部调用头：令牌 + 当前用户/组织。"""
    headers = {'X-Internal-Token': os.environ.get('ML_API_INTERNAL_TOKEN', '')}
    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated:
        headers['X-User-Id'] = str(user.pk)
        organization_id = getattr(user, 'active_organization_id', None)
        headers['X-Organization-Id'] = str(organization_id) if organization_id else ''
    return headers


def forward(request, method: str, path: str, params=None, json_body=None) -> Response:
    """转发到 ml-api，并把 FastAPI 422 映射回 DRF 的 400。"""
    try:
        response = requests.request(
            method,
            f'{ml_api_url()}{path}',
            headers=internal_headers(request),
            params=params,
            json=json_body,
            timeout=ml_api_timeout(),
        )
    except requests.RequestException:
        return Response(
            {'detail': '训练服务不可用，请确认 ml-api 已启动（docker compose --profile ml up -d）'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        payload = response.json()
    except ValueError:
        payload = {'detail': response.text}

    status_code = response.status_code
    if status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
        status_code = status.HTTP_400_BAD_REQUEST
    return Response(payload, status=status_code)


def _json_body(request):
    """DRF request.data 可能是 QueryDict，统一成普通 dict。"""
    data = request.data
    if isinstance(data, QueryDict):
        return data.dict()
    return data


class BaseModelListAPI(APIView):
    """BaseModel 列表。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return forward(request, 'GET', '/api/training/base-models')


class BaseModelDetailAPI(APIView):
    """BaseModel 详情。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        return forward(request, 'GET', f'/api/training/base-models/{pk}')


class LocalModelsScanAPI(APIView):
    """扫描 ml-api 侧 LOCAL_MODEL_ROOT 下的 YOLO 基模候选。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return forward(request, 'GET', '/api/training/base-models/scan')


class TrainingJobListAPI(APIView):
    """TrainingJob 列表/创建。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        params = {}
        project = request.query_params.get('project')
        if project is not None:
            params['project'] = project
        return forward(request, 'GET', '/api/training/jobs', params=params)

    def post(self, request):
        return forward(request, 'POST', '/api/training/jobs', json_body=_json_body(request))


class TrainingJobDetailAPI(APIView):
    """TrainingJob 详情/取消。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        return forward(request, 'GET', f'/api/training/jobs/{pk}')

    def patch(self, request, pk):
        return forward(request, 'PATCH', f'/api/training/jobs/{pk}', json_body=_json_body(request))


app_name = 'training'

urlpatterns = [
    path('api/training/base-models/scan/', LocalModelsScanAPI.as_view(), name='base-model-scan'),
    path('api/training/base-models/', BaseModelListAPI.as_view(), name='base-model-list'),
    path('api/training/base-models/<int:pk>/', BaseModelDetailAPI.as_view(), name='base-model-detail'),
    path('api/training/jobs/', TrainingJobListAPI.as_view(), name='job-list'),
    path('api/training/jobs/<int:pk>/', TrainingJobDetailAPI.as_view(), name='job-detail'),
]
