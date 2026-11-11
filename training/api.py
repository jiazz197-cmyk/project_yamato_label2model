"""Training REST API 视图。

参照 ml/api.py 的模式：
- 视图级权限走 DRF 全局默认（IsAuthenticated + HasObjectPermission），
  不再声明 ``permission_required``；
- 真实隔离由默认权限类 HasObjectPermission（模型级 has_permission）与
  各 get_queryset/perform_create 的组织校验共同保证。
- 未登录 → DRF NotAuthenticated(401)；跨组织访问/创建 → PermissionDenied(403)。
"""

import logging

from django.conf import settings
from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from projects.models import Project
from rest_framework import generics
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from training.models import BaseModel, TrainingJob
from training.serializers import BaseModelSerializer, TrainingJobSerializer
from training.utils import scan_local_models

logger = logging.getLogger(__name__)

_TRAINING_SERIALIZERS_PARSERS = (JSONParser, FormParser, MultiPartParser)


class BaseModelListAPI(generics.ListAPIView):
    """BaseModel 列表：服务器预置（organization 为空）+ 本组织可见的活跃基模。"""

    serializer_class = BaseModelSerializer
    parser_classes = _TRAINING_SERIALIZERS_PARSERS
    filter_backends = [DjangoFilterBackend]

    def get_queryset(self):
        user = self.request.user
        return BaseModel.objects.select_related('organization').filter(
            Q(organization__isnull=True) | Q(organization=user.active_organization),
            is_active=True,
        )


class BaseModelDetailAPI(generics.RetrieveAPIView):
    """BaseModel 详情：对象级权限（HasObjectPermission）产出 403。"""

    serializer_class = BaseModelSerializer
    parser_classes = _TRAINING_SERIALIZERS_PARSERS
    queryset = BaseModel.objects.all()


class TrainingJobListAPI(generics.ListCreateAPIView):
    """TrainingJob 列表/创建：可选 ?project=<id> 过滤。"""

    serializer_class = TrainingJobSerializer
    parser_classes = _TRAINING_SERIALIZERS_PARSERS
    filter_backends = [DjangoFilterBackend]

    def get_queryset(self):
        user = self.request.user
        qs = TrainingJob.objects.select_related('base_model', 'project').filter(
            organization=user.active_organization
        )
        project_pk = self.request.query_params.get('project')
        if project_pk:
            if not str(project_pk).isdigit():
                raise NotFound('Project not found.')
            project = generics.get_object_or_404(Project, pk=project_pk)
            if project.organization_id != user.active_organization_id:
                raise PermissionDenied('Project not found.')
            qs = qs.filter(project=project)
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        base_model = serializer.validated_data.get('base_model')
        project = serializer.validated_data.get('project')
        if project.organization_id != user.active_organization_id:
            raise PermissionDenied('Project not found.')
        if not base_model.has_permission(user):
            raise PermissionDenied('Base model not found.')
        serializer.save(
            organization=user.active_organization,
            created_by=user,
            status=TrainingJob.Status.PENDING,
        )


class TrainingJobDetailAPI(generics.RetrieveUpdateAPIView):
    """TrainingJob 详情；PATCH 仅支持 action=cancel。"""

    serializer_class = TrainingJobSerializer
    parser_classes = _TRAINING_SERIALIZERS_PARSERS
    queryset = TrainingJob.objects.all()

    def partial_update(self, request, *args, **kwargs):
        job = self.get_object()
        action = request.data.get('action')
        if action != 'cancel':
            raise PermissionDenied('Only action=cancel is supported.')
        job.status = TrainingJob.Status.CANCELED
        job.save(update_fields=['status'])
        return Response(self.get_serializer(job).data)


class LocalModelsScanAPI(APIView):
    """扫描 LOCAL_MODEL_ROOT 下的一级子目录，返回可识别的 YOLO 基模候选。"""

    def get(self, request, *args, **kwargs):
        return Response(scan_local_models(settings.LOCAL_MODEL_ROOT))
