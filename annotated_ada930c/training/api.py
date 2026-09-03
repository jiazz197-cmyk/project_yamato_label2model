"""Training REST API 视图（Sub-Issue 4）。

参照 ml/api.py + webhooks/api.py 的模式：
- permission_required 声明视图级权限（ViewClassPermission），
  真实隔离由默认权限类 HasObjectPermission（模型级 has_permission）与
  各 get_queryset/perform_create 的组织校验共同保证。
- 未登录 → DRF NotAuthenticated(401)；跨组织访问/创建 → PermissionDenied(403)。
"""

# ============================================================================
# 【注释版】对应 commit ada930cea9e72e045e86d1c3744e8e032c280148，仅供理解，请勿提交。
# 插入注释后行号与原文件不一致，请以代码内容对照原文件。
# ============================================================================

import logging  # 标准库日志；下方按模块名取 logger（本文件目前未直接打日志，按项目惯例声明）

from core.permissions import ViewClassPermission, all_permissions
# 权限声明基础设施（见 label_studio/core/permissions.py 注释版）：
# - ViewClassPermission：pydantic 模型，按 HTTP 方法声明"本端点应要求的权限点"；
# - all_permissions：AllPermissions 单例，all_permissions.training_view 等就是权限点字符串。

from django.conf import settings  # Django 全局 settings 代理；本文件只用 settings.LOCAL_MODEL_ROOT（扫描端点）
from django.db.models import Q  # Q 对象：把"或"条件包成 ORM 过滤器（基模列表：预置 OR 本组织）
from django_filters.rest_framework import DjangoFilterBackend
# DRF 过滤后端（与上游模块保持一致的惯例声明）。
# 本 app 没有声明 filterset_fields，所以 DjangoFilterBackend 实际不产生任何过滤；
# ?project= 过滤是下面 get_queryset() 里手写的。
from projects.models import Project
# 项目 ORM 模型：两个用途——
# 1) ?project=<id> 列表过滤时按 id 取项目并核对组织；
# 2) POST 创建时核对"用户提交的项目是否属于其所在组织"。
from rest_framework import generics  # DRF 泛型视图基类：ListAPIView / RetrieveAPIView / ListCreateAPIView / RetrieveUpdateAPIView
from rest_framework.exceptions import NotFound, PermissionDenied
# DRF 业务异常：抛 NotFound → 404；抛 PermissionDenied → 403。
# 由 settings 的 EXCEPTION_HANDLER（core.utils.common.custom_exception_handler）统一转成 JSON 响应。
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
# 三种请求体解析器：JSON / urlencoded 表单 / multipart（文件上传）。
# 与 ml/api.py 等上游模块写法一致；GET 请求不会触发解析。
from rest_framework.response import Response  # DRF 响应对象；只有 LocalModelsScanAPI（裸 APIView）需要手动构造
from rest_framework.views import APIView  # 最底层的 DRF 视图基类；扫描端点不需要泛型 CRUD，直接继承它

from training.models import BaseModel, TestRun, TrainingJob  # 本 app 三个 ORM 模型（见 models.py 注释版）
from training.serializers import BaseModelSerializer, TestRunSerializer, TrainingJobSerializer
# 序列化器：负责"模型 ↔ JSON"与入参校验（见 serializers.py 注释版）
from training.tasks import enqueue_test, enqueue_training
# 入队 seam（占位实现，见 tasks.py 注释版）：本 commit 只写占位 celery_task_id；
# Sub-Issue 6/11 把函数内部换成真实 Celery .delay() 调用，这里的调用点不变。
from training.utils import scan_local_models  # 本地基模目录扫描（Sub-Issue 3 实现，纯标准库函数）

logger = logging.getLogger(__name__)
# 模块级 logger，名字是 'training.api'。本文件目前没有调用它，属于项目统一惯例。

_TRAINING_SERIALIZERS_PARSERS = (JSONParser, FormParser, MultiPartParser)
# 三个解析器打包成元组，供下面所有视图的 parser_classes 复用，避免每处重复写一遍。


class BaseModelListAPI(generics.ListAPIView):
    """BaseModel 列表：服务器预置（organization 为空）+ 本组织可见的活跃基模。"""
    # 泛型 ListAPIView：只提供 GET（列表）。DRF 会把 request.method 分派到 list() 方法。

    serializer_class = BaseModelSerializer
    # 列表里每个对象都用它序列化：输出 12 个只读字段（见 serializers.py）。

    permission_required = ViewClassPermission(GET=all_permissions.training_view)
    # 声明式权限：GET 需要 'training.view' 权限点。
    # ※ 本代码库中该属性不被任何 DRF 钩子读取（见 README §4）；
    #   实际拦截 = IsAuthenticated（401）+ queryset 组织过滤。
    #   它的价值是：记录权限意图 + 与上游 Label Studio 模式保持一致。

    parser_classes = _TRAINING_SERIALIZERS_PARSERS
    # 复用上面的解析器元组（ListAPIView 只有 GET，实际用不到，纯惯例）。

    filter_backends = [DjangoFilterBackend]
    # 声明过滤后端（未配 filterset_fields，不产生实际过滤；?project= 是手写的，这里没有）。

    def get_queryset(self):
        user = self.request.user
        # 取当前请求的已登录用户。
        # 能走到这里说明已通过 IsAuthenticated（匿名用户在视图级权限阶段就被 401 拦掉），
        # 所以 user 一定是真实 User 实例，user.active_organization 一定是某个组织（FK 字段）。
        return BaseModel.objects.select_related('organization').filter(
            # select_related('organization')：JOIN 出 organization 表，
            # 序列化时读 organization 的 pk 不再额外发 SQL（避免 N+1）。
            # filter 的两个条件（注意外层 filter 的多个参数是 AND，OR 要用 Q 显式包）：
            Q(organization__isnull=True) | Q(organization=user.active_organization),
            # 条件1：organization IS NULL → 服务器预置基模（任何组织都可见）
            # 条件2：organization = 当前用户的组织 → 本组织自建基模
            # 两个条件用 |（OR）连接；别的组织的基模两者都不满足 → 直接不在结果集里（是"看不到"，不是 403）。
            is_active=True,
            # 只列活跃基模：is_active=False 的（占位/下线）不展示。
        )
    # 效果：组织 A 的用户看到的是「全部预置基模 + 组织 A 的活跃基模」。


class BaseModelDetailAPI(generics.RetrieveAPIView):
    """BaseModel 详情：对象级权限（HasObjectPermission）产出 403。"""
    # 泛型 RetrieveAPIView：只提供 GET（单对象）。

    serializer_class = BaseModelSerializer
    # 与列表同一个序列化器。

    permission_required = ViewClassPermission(GET=all_permissions.training_view)
    # 声明式权限：GET 需要 'training.view'（同上，声明性为主）。

    parser_classes = _TRAINING_SERIALIZERS_PARSERS
    # 惯例解析器元组。

    queryset = BaseModel.objects.all()
    # ★ 注意：queryset 故意是"未过滤"的全量。
    # 隔离靠对象级权限：retrieve() → get_object() 取出对象后调用
    # check_object_permissions() → 默认权限类 HasObjectPermission.has_object_permission
    # → obj.has_permission(request.user)（本次 commit 给 BaseModel 新增的方法）：
    #   - 预置基模（org 为 NULL）→ True，全员可读；
    #   - 其他组织的基模 → False → PermissionDenied → 403。
    # 与列表的"过滤掉看不到"不同，详情是"看得到对象但拒绝读"，所以返回 403 而不是 404。


class TrainingJobListAPI(generics.ListCreateAPIView):
    """TrainingJob 列表/创建：可选 ?project=<id> 过滤。"""
    # 泛型 ListCreateAPIView：GET（列表）+ POST（创建）两个方法。

    serializer_class = TrainingJobSerializer
    # POST 用它解析/校验入参并构造对象；GET 用它序列化列表项。

    permission_required = ViewClassPermission(
        GET=all_permissions.training_view,   # GET 需要 'training.view'
        POST=all_permissions.training_create,  # POST 需要 'training.create'（本次 commit 在 core/permissions.py 新增）
    )
    # 声明式权限：按方法分别声明。实际拦截见 README §4。

    parser_classes = _TRAINING_SERIALIZERS_PARSERS
    # POST 的 JSON 请求体由 JSONParser 解析。

    filter_backends = [DjangoFilterBackend]
    # 惯例声明（未配 filterset_fields，无实际过滤）。

    def get_queryset(self):
        user = self.request.user
        # 当前已登录用户（匿名已被 401 拦截）。
        qs = TrainingJob.objects.select_related('base_model', 'project').filter(
            # select_related 双 JOIN：序列化时读 base_model.name / project 不额外发 SQL。
            organization=user.active_organization
            # ★ 与 BaseModel 不同：训练任务没有"预置"概念，
            # 严格只返回本组织的任务（别的组织的直接查不到 → 列表层面天然隔离）。
        )
        project_pk = self.request.query_params.get('project')
        # 读可选查询参数 ?project=<id>；没有则返回 None（.get 而不是 []，不会 KeyError）。
        if project_pk:
            # 提供了过滤参数：
            if not str(project_pk).isdigit():
                # query_params.get 返回的本来就是 str，str() 只是防御性写法。
                # 非纯数字（'abc'、'1.5'、'-1'、'' 等）直接 404：
                # 若放任 'abc' 进 ORM 的 pk 过滤，Django 会抛 ValueError → 变 500，
                # 这里显式转成 404（"Project not found."）。
                raise NotFound('Project not found.')
            project = generics.get_object_or_404(Project, pk=project_pk)
            # 按 pk 取项目；不存在 → 抛 NotFound → 404。
            # （get_object_or_404 是 DRF 对 django.shortcuts 的同名再导出。）
            if project.organization_id != user.active_organization_id:
                # 项目存在但不属于当前用户的组织 → 403。
                # 消息故意写成 'Project not found.'：状态码 403 已表达"无权"，
                # 文案不泄露"该项目确实存在"，避免给跨组织探测留下信息差。
                raise PermissionDenied('Project not found.')
            qs = qs.filter(project=project)
            # 通过双重校验后，才把项目过滤条件叠加到 queryset 上。
        return qs
    # 组合效果：GET /api/training/jobs/ → 本组织全部任务；
    # GET /api/training/jobs/?project=5 → 本组织下、项目 5 的任务（非数字 404 / 不存在 404 / 跨组织 403）。

    def perform_create(self, serializer):
        # DRF 泛型视图的钩子：POST 时，在 serializer.is_valid() 之后、写库之前被调用。
        # 这里是"创建路径"上组织隔离的核心（序列化器只校验字段存在/合法，不校验组织归属）。
        user = self.request.user
        # 当前已登录用户。
        base_model = serializer.validated_data.get('base_model')
        project = serializer.validated_data.get('project')
        # 从校验后的数据取出两个已解析为 ORM 实例的 FK：
        # 序列化器的 PrimaryKeyRelatedField 已把客户端给的整型 pk 查库转成真实对象
        # （查不到早已在 is_valid 阶段 400，所以这里一定是存在的实例）。
        if project.organization_id != user.active_organization_id:
            # 提交的 project 不属于用户所在组织 → 403（消息同样故意模糊）。
            # 例：组织 B 的用户带组织 A 的 project id 来创建任务 → 拒绝。
            raise PermissionDenied('Project not found.')
        if not base_model.has_permission(user):
            # 校验基模可见性，复用模型方法（与详情端点同一套规则）：
            # - 预置基模（org NULL）→ True（任何组织可用公共基模建任务）；
            # - 其他组织的基模 → False → 403（消息故意写成 'Base model not found.'）。
            raise PermissionDenied('Base model not found.')
        job = serializer.save(
            organization=user.active_organization,
            created_by=user,
            status=TrainingJob.Status.PENDING,
        )
        # serializer.save(**kwargs) = validated_data + 这里的 kwargs 一起传给模型构造/保存。
        # 这三个字段在序列化器里都是 read_only：客户端 JSON 里写了也会被忽略，
        # 只能由服务端在此注入 → 防止伪造 created_by / 篡改 status。
        # 此时任务落库：status='Pending'，celery_task_id 还是空。
        enqueue_training(job)
        # 调用入队 seam（tasks.py）：写入占位 celery_task_id，任务保持 Pending。
        # Sub-Issue 6 后这里换成真实 Celery 任务投递，本行代码不变。
        # perform_create 无返回值 → 泛型视图 create() 接着用序列化器 dump 刚保存的
        # 对象，返回 201 Created + {id, status: 'Pending', celery_task_id: '...'}。


class TrainingJobDetailAPI(generics.RetrieveUpdateAPIView):
    """TrainingJob 详情；PATCH 仅支持 action=cancel（Sub-Issue 8 补 revoke）。"""
    # 泛型 RetrieveUpdateAPIView：GET（详情）+ PUT/PATCH（更新）。
    # 这里只重写了 PATCH 路径（partial_update），PUT 未重写——
    # 但 TrainingJobSerializer 的字段几乎全是 read_only，PUT 全量更新实际改不了任何字段。

    serializer_class = TrainingJobSerializer
    # GET 用它序列化输出；PATCH 本覆盖方法里只用来 dump 结果（不做字段校验）。

    permission_required = ViewClassPermission(
        GET=all_permissions.training_view,      # GET 需要 'training.view'
        PATCH=all_permissions.training_cancel,  # PATCH 需要 'training.cancel'（本次 commit 新增权限点）
    )
    # 声明式权限：cancel 单独一个权限点，为将来"谁能取消"做细粒度授权留扩展位。

    parser_classes = _TRAINING_SERIALIZERS_PARSERS
    # PATCH 的 JSON 请求体（{"action": "cancel"}）由 JSONParser 解析。

    queryset = TrainingJob.objects.all()
    # ★ 与 BaseModelDetailAPI 同理：未过滤的全量 queryset，
    # 隔离靠 get_object() → check_object_permissions → TrainingJob.has_permission(user)：
    # 跨组织 → 403（本次 commit 新增的模型方法）。

    def partial_update(self, request, *args, **kwargs):
        # 覆盖 DRF 的 PATCH 分派方法（GenericAPIView.partial_update）。
        # 注意：这不是标准"字段级更新"，而是把 PATCH 当作"命令通道"：
        # 请求体形如 {"action": "cancel"}，服务端执行固定动作。
        job = self.get_object()
        # 走 DRF 标准取对象流程：queryset 按 pk 取 + check_object_permissions
        # → 跨组织用户在这里就 403，到不了后面。
        action = request.data.get('action')
        # 取命令名；请求体没有 action 键 → None。
        if action != 'cancel':
            # 只认 'cancel'：
            # - 空请求体 {} → None → 403；
            # - {"status": "Running"} 之类的"想改字段" → 'status' 不是 action → 403
            #   （测试 test_cancel_reject_other_fields 验证的正是这条）；
            # - 大小写敏感：'Cancel' 也会被拒。
            # 用 PermissionDenied(403) 而不是 ValidationError(400)：
            # 语义是"你不允许做这个操作"，而非"参数格式错"（作者选择，测试按 403 断言）。
            raise PermissionDenied('Only action=cancel is supported.')
        job.status = TrainingJob.Status.CANCELED
        # 直接把状态改成 'Canceled'。
        # ※ 注意没有状态机守卫：Completed/Failed 的任务也能被"cancel"（本 commit 是 seam 级别），
        #   也没有去真的叫停 worker——Celery revoke 留给 Sub-Issue 8。
        job.save(update_fields=['status'])
        # 只 UPDATE status 一列：
        # - 不触发其他字段的意外写入；
        # - 与序列化器完全解耦（整个方法没有调 is_valid，read_only 规则在这里不适用）。
        return Response(self.get_serializer(job).data)
        # 手动构造 200 响应，body 是更新后任务的序列化结果（status='Canceled'）。
        # （DRF 默认 partial_update 也是 200，这里等价但更可控。）


class TestRunListAPI(generics.ListCreateAPIView):
    """TestRun 列表/创建：可选 ?project=<id> 过滤；base_model 与 training_job 二选一。"""
    # GET（列表）+ POST（创建）。结构与 TrainingJobListAPI 几乎对称，差异在 perform_create。

    serializer_class = TestRunSerializer
    # 创建校验的 XOR（base_model_id 与 training_job_id 必须且只能给一个）
    # 就在这个序列化器的 validate() 里（见 serializers.py 注释版）。

    permission_required = ViewClassPermission(
        GET=all_permissions.training_view,
        POST=all_permissions.training_create,
    )
    # 声明式权限（同 jobs 列表）。

    parser_classes = _TRAINING_SERIALIZERS_PARSERS
    # 惯例解析器。

    filter_backends = [DjangoFilterBackend]
    # 惯例声明（无实际过滤）。

    def get_queryset(self):
        user = self.request.user
        # 当前已登录用户。
        qs = TestRun.objects.select_related('project').filter(organization=user.active_organization)
        # 严格本组织过滤（TestRun 无"预置"概念）；select_related('project') 防序列化 N+1。
        # 注：TestRun 的 base_model/training_job 两个 FK 是 SET_NULL 且序列化器里 write_only，
        # 列表响应并不输出它们，所以这里无需 select_related。
        project_pk = self.request.query_params.get('project')
        # 可选 ?project=<id>。
        if project_pk:
            if not str(project_pk).isdigit():
                raise NotFound('Project not found.')
                # 非数字 → 404（防止 500），与 jobs 列表同一套路。
            project = generics.get_object_or_404(Project, pk=project_pk)
            # 不存在 → 404。
            if project.organization_id != user.active_organization_id:
                raise PermissionDenied('Project not found.')
                # 跨组织 → 403（消息故意模糊）。
            qs = qs.filter(project=project)
            # 叠加项目过滤。
        return qs

    def perform_create(self, serializer):
        # POST 创建路径（序列化器 is_valid 已通过：project 必填且存在、XOR 满足）。
        user = self.request.user
        project = serializer.validated_data.get('project')
        # 已解析的项目实例。
        if project.organization_id != user.active_organization_id:
            raise PermissionDenied('Project not found.')
            # 跨组织项目 → 403。
        target = serializer.validated_data.get('base_model') or serializer.validated_data.get('training_job')
        # 取"测试对象"：序列化器 validate() 已保证两者恰好一个非 None，
        # 所以 or 一定能选中那个被设置的（零样本测试 → base_model；训练产物测试 → training_job）。
        if target is not None and not target.has_permission(user):
            # 对测试对象做对象级权限检查（复用模型方法）：
            # - base_model：预置全员可用；org 模型需同组织；
            # - training_job：必须同组织。
            # 跨组织 → 403（'Test target not found.'，消息同样模糊化）。
            raise PermissionDenied('Test target not found.')
        test_run = serializer.save(
            organization=user.active_organization,
            created_by=user,
            status=TestRun.Status.PENDING,
        )
        # 服务端注入 read_only 的审计/状态字段，落库为 Pending。
        enqueue_test(test_run)
        # 入队 seam：占位 celery_task_id（Sub-Issue 11 换 run_test.delay）。
        # 随后泛型视图返回 201 + 序列化结果。


class TestRunDetailAPI(generics.RetrieveAPIView):
    """TestRun 详情：对象级权限（HasObjectPermission）产出 403。"""
    # 只提供 GET。

    serializer_class = TestRunSerializer
    # 注意：TestRunSerializer 的 base_model_id/training_job_id 是 write_only，
    # 所以详情响应里不会出现这两个键（只有 id/project/test_subset/status/metrics/
    # celery_task_id/error_message/created_at/started_at/completed_at）。

    permission_required = ViewClassPermission(GET=all_permissions.training_view)
    # 声明式权限（同其他详情端点）。

    parser_classes = _TRAINING_SERIALIZERS_PARSERS
    # 惯例解析器。

    queryset = TestRun.objects.all()
    # 未过滤全量；隔离靠 get_object → HasObjectPermission → TestRun.has_permission(user)
    # → 跨组织 403（本次 commit 新增的模型方法）。


class LocalModelsScanAPI(APIView):
    """扫描 LOCAL_MODEL_ROOT 下的一级子目录，返回可识别的基模候选。"""
    # 不用泛型视图：它不是对某个模型的 CRUD，而是"文件系统探测"，
    # 直接继承 APIView 手写 get() 最干净。

    permission_required = ViewClassPermission(GET=all_permissions.training_view)
    # 声明式权限：需要 'training.view'。
    # 实际拦截 = IsAuthenticated（未登录 401）。

    def get(self, request, *args, **kwargs):
        # GET /api/training/base-models/scan/ 入口。
        return Response(scan_local_models(settings.LOCAL_MODEL_ROOT))
        # settings.LOCAL_MODEL_ROOT：.env 里 LOCAL_MODEL_ROOT 或默认 <BASE_DATA_DIR>/models
        #   （core/settings/label_studio.py:98，启动时还会 os.makedirs 确保存在）。
        # scan_local_models（utils.py，Sub-Issue 3）：
        #   - 只扫一级子目录，不递归；跳过隐藏目录与保留名 uploads/trained；
        #   - 每个子目录探测框架（config.json → HF；model.pkl → SKLEARN），识别不了就跳过；
        #   - 尽力推导 task_type（HF 读 config.json；SKLEARN 惰性 joblib.load 读 classes_），失败为 None；
        #   - 按目录名排序返回 [{name, framework, local_path, task_type_guess}, ...]。
        # 根目录不存在/不可读时返回 []，端点永远 200。
        # 用途：给管理界面/前端提供"服务器上还躺着哪些基模"的候选清单。
