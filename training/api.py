"""Training REST API 视图（Sub-Issue 4）。

参照 ml/api.py + webhooks/api.py 的模式：
- permission_required 声明视图级权限（ViewClassPermission），
  真实隔离由默认权限类 HasObjectPermission（模型级 has_permission）与
  各 get_queryset/perform_create 的组织校验共同保证。
- 未登录 → DRF NotAuthenticated(401)；跨组织访问/创建 → PermissionDenied(403)。
"""

import logging

from core.permissions import ViewClassPermission, all_permissions
from django.conf import settings
from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from projects.models import Project
from rest_framework import generics
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from training.models import BaseModel, TestRun, TrainingJob
from training.serializers import BaseModelSerializer, TestRunSerializer, TrainingJobSerializer
from training.tasks import enqueue_test, enqueue_training
from training.utils import scan_local_models

logger = logging.getLogger(__name__)

_TRAINING_SERIALIZERS_PARSERS = (JSONParser, FormParser, MultiPartParser)


class BaseModelListAPI(generics.ListAPIView):
    """BaseModel 列表：服务器预置（organization 为空）+ 本组织可见的活跃基模。"""

    serializer_class = BaseModelSerializer
    permission_required = ViewClassPermission(GET=all_permissions.training_view)
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
    permission_required = ViewClassPermission(GET=all_permissions.training_view)
    parser_classes = _TRAINING_SERIALIZERS_PARSERS
    queryset = BaseModel.objects.all()


class TrainingJobListAPI(generics.ListCreateAPIView):
    """TrainingJob 列表/创建：可选 ?project=<id> 过滤。"""

    serializer_class = TrainingJobSerializer
    permission_required = ViewClassPermission(
        GET=all_permissions.training_view,
        POST=all_permissions.training_create,
    )
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
        job = serializer.save(
            organization=user.active_organization,
            created_by=user,
            status=TrainingJob.Status.PENDING,
        )
        enqueue_training(job)


class TrainingJobDetailAPI(generics.RetrieveUpdateAPIView):
    """TrainingJob 详情；PATCH 仅支持 action=cancel（Sub-Issue 8 补 revoke）。"""

    serializer_class = TrainingJobSerializer
    permission_required = ViewClassPermission(
        GET=all_permissions.training_view,
        PATCH=all_permissions.training_cancel,
    )
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


class TestRunListAPI(generics.ListCreateAPIView):
    """TestRun 列表/创建：可选 ?project=<id> 过滤；base_model 与 training_job 二选一。"""

    serializer_class = TestRunSerializer
    permission_required = ViewClassPermission(
        GET=all_permissions.training_view,
        POST=all_permissions.training_create,
    )
    parser_classes = _TRAINING_SERIALIZERS_PARSERS
    filter_backends = [DjangoFilterBackend]

    def get_queryset(self):
        user = self.request.user
        qs = TestRun.objects.select_related('project').filter(organization=user.active_organization)
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
        project = serializer.validated_data.get('project')
        if project.organization_id != user.active_organization_id:
            raise PermissionDenied('Project not found.')
        target = serializer.validated_data.get('base_model') or serializer.validated_data.get('training_job')
        if target is not None and not target.has_permission(user):
            raise PermissionDenied('Test target not found.')
        test_run = serializer.save(
            organization=user.active_organization,
            created_by=user,
            status=TestRun.Status.PENDING,
        )
        enqueue_test(test_run)


class TestRunDetailAPI(generics.RetrieveAPIView):
    """TestRun 详情：对象级权限（HasObjectPermission）产出 403。"""

    serializer_class = TestRunSerializer
    permission_required = ViewClassPermission(GET=all_permissions.training_view)
    parser_classes = _TRAINING_SERIALIZERS_PARSERS
    queryset = TestRun.objects.all()


class LocalModelsScanAPI(APIView):
    """扫描 LOCAL_MODEL_ROOT 下的一级子目录，返回可识别的基模候选。"""

    permission_required = ViewClassPermission(GET=all_permissions.training_view)

    def get(self, request, *args, **kwargs):
        return Response(scan_local_models(settings.LOCAL_MODEL_ROOT))
