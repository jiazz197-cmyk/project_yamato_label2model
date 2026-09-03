# ============================================================================
# 【注释版】对应 commit ada930cea9e72e045e86d1c3744e8e032c280148，仅供理解，请勿提交。
# 本 commit 对该文件的改动 = 三个模型各加一个 has_permission 方法（★ 处）。
# 为便于理解，这里把整文件都注释了（含 commit 之前就存在的字段）。
# ============================================================================

from django.conf import settings
# Django 全局 settings 代理：下面用它取 AUTH_USER_MODEL（本项目自定义的 User 模型）。
from django.db import models
# Django ORM 模型字段/基类。
from ml_models.models import SkillNames
# 复用 ml_models app 的任务类型枚举（TextClassification / NamedEntityRecognition 等），
# 保证 training 的 task_type 与既有 ML 侧枚举值一致。
# （commit 顺手修正了一处 import 顺序：models 与 SkillNames 之间的空行位置。）

from training.utils import validate_local_model_path
# 本地基模目录校验函数（Sub-Issue 3 实现，见 training/utils.py 注释说明）：
# HF 要求 config.json + 权重文件；SKLEARN 要求 model.pkl；失败抛 ValidationError。


class BaseModel(models.Model):
    """本地预置基模（事先下载好，不联网）"""
    # 平台上的"基础模型"登记项：指向本地磁盘上已经下好的模型目录。
    # 训练任务基于它做微调/测试，全程离线。

    class Framework(models.TextChoices):
        # TextChoices：枚举常量，值=存储值，标签=展示名（Django 4+ 风格）。
        HUGGINGFACE = 'HF', 'HuggingFace Transformers'
        # 库内存 'HF'，admin/表单显示 'HuggingFace Transformers'。
        SKLEARN = 'SKLEARN', 'scikit-learn'
        # 库内存 'SKLEARN'。

    name = models.CharField(max_length=255, unique=True)
    # 基模显示名，全局唯一（unique → 数据库唯一索引）。
    task_type = models.CharField(
        max_length=255,
        choices=SkillNames.choices,
    )
    # 任务类型：取值来自 SkillNames 枚举（如 'TextClassification'）。
    # choices 只是"合法值清单 + 展示标签"，数据库层不强制，靠应用层约束。
    framework = models.CharField(max_length=16, choices=Framework.choices)
    # 框架：'HF' 或 'SKLEARN'（决定目录校验规则，见 validate_local_path）。
    local_path = models.CharField(
        max_length=1024,
        help_text='本地模型目录绝对路径（事先下载，不联网）',
    )
    # 模型目录的绝对路径（如 C:\...\models\bert-base）。
    # 校验在 save() 里做（见下），不是字段级 validator。
    description = models.TextField(blank=True, null=True)
    # 自由文本描述；blank=True（表单可不填）+ null=True（库里存 NULL）。
    default_config = models.JSONField(default=dict, help_text='默认超参')
    # 默认超参 dict（如 {'max_iter': 100}）；训练时与用户 hyperparams 做 merge。
    # default=dict：注意传的是可调用对象（每次 new 一个 dict），不是共享的 {}。
    is_active = models.BooleanField(default=True)
    # 是否活跃：False 表示下线/占位，列表 API 不展示（api.py 里 filter is_active=True）。

    # 审计
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
    )
    # 创建人：指向 settings 配置的 User 模型（字符串延迟解析，避免循环 import）。
    # SET_NULL + null=True：用户被删时置 NULL，不级联删基模。
    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.CASCADE, null=True,
    )
    # ★ 所属组织：null=True 是关键设计——
    # organization 为 NULL 表示"服务器预置基模"（对全员可见，has_permission 据此特判）。
    # CASCADE：组织被删，其下基模一并删除。
    created_at = models.DateTimeField(auto_now_add=True)
    # 创建时间，插入时自动填，之后不变。
    updated_at = models.DateTimeField(auto_now=True)
    # 更新时间，每次 save 自动刷新。

    def validate_local_path(self):
        """校验 local_path 存在且含框架期望文件（委托 utils.validate_local_model_path）。"""
        validate_local_model_path(self.local_path, self.framework)
        # 纯委托：目录不存在 / 缺 config.json / 缺 model.pkl 等 → 抛 ValidationError。

    def save(self, *args, **kwargs):
        """保存前校验：仅 is_active=True 时校验本地路径（is_active=False 可先存占位再补文件）。"""
        if self.is_active:
            self.validate_local_path()
            # 活跃基模必须"目录真实可用"才能落库。
            # is_active=False 时跳过 → 允许先登记一条占位记录，文件放好再激活。
            # （注意：通过 ORM 直接 update is_active=True 不会重新走 save 的校验路径
            #   时是有的——save 就是 save；但 query .update() 不经过 save()，
            #   那种改法会绕过校验，属于使用约定。）
        super().save(*args, **kwargs)
        # 校验通过（或跳过）后，交给 Django 正常落库。

    def has_permission(self, user):
        """服务器预置（organization 为空）基模全员可见；其余仅同组织成员。"""
        # ★★★ 本次 commit 新增。被两处调用：
        # 1) HasObjectPermission.has_object_permission → 详情端点对象级拦截（403）；
        # 2) api.py TrainingJobListAPI.perform_create → 创建任务时校验基模可见性。
        return self.organization_id is None or user.active_organization_id == self.organization_id
        # 短路求值：
        # - 预置基模（organization_id 为 None）→ 直接 True，不看用户（全员可用）；
        # - 组织基模 → 比较"用户当前组织"与"基模所属组织"的 pk。
        # 用 _id 属性（Django 把 FK 的 pk 缓存在 <field>_id 上）→ 不触发额外 SQL。
        # （能走到这里的 user 一定是已登录用户——匿名请求早被 IsAuthenticated 401。）

    def __str__(self):
        return f'{self.name} ({self.framework})'
        # 人类可读表示（admin / repr / 日志里用），如 'bert-base (HF)'。

    class Meta:
        db_table = 'training_base_model'
        # 显式指定物理表名（Django 默认会生成 'training_baseModel' 之类的驼峰表名，
        # 这里统一成小写下划线风格）。


class TrainingJob(models.Model):
    """一次训练任务"""
    # 语义：用某基模（base_model）对某项目的标注数据（project）做一次训练。

    class TrainSubset(models.TextChoices):
        # 训练数据子集策略枚举。
        ALL = 'All', 'All tasks'
        # 全量任务（含未标注）。
        HAS_GT = 'HasGT', 'Tasks with ground truth annotations'
        # 只有带人工标注（ground truth）的任务——默认值。
        SAMPLE = 'Sample', 'Random sample of annotated tasks'
        # 已标注任务的随机抽样。

    class Status(models.TextChoices):
        # 任务状态机取值（本 commit 的 API 只会产生 Pending / Canceled；
        # Running/Completed/Failed 由将来的 Celery worker 写入）。
        PENDING = 'Pending'
        # 已入队等待执行。
        RUNNING = 'Running'
        # worker 执行中。
        COMPLETED = 'Completed'
        # 成功结束。
        FAILED = 'Failed'
        # 执行失败（error_message 有值）。
        CANCELED = 'Canceled'
        # 用户取消（本 commit 的 PATCH action=cancel 会写这个值）。

    base_model = models.ForeignKey(BaseModel, on_delete=models.CASCADE, related_name='training_jobs')
    # 基于哪个基模训练。CASCADE：基模被删 → 其下任务全删。
    # related_name='training_jobs'：反向访问 base_model.training_jobs.all()。
    project = models.ForeignKey('projects.Project', on_delete=models.CASCADE, related_name='training_jobs')
    # 用哪个项目的标注数据训练。'projects.Project' 用字符串声明（跨 app 引用，避免 import 循环）。
    train_subset = models.CharField(max_length=16, choices=TrainSubset.choices, default=TrainSubset.HAS_GT)
    # 数据子集策略；客户端不传时默认 HasGT。
    hyperparams = models.JSONField(default=dict, help_text='用户覆盖的超参，merge 到 base_model.default_config')
    # 用户提交的超参覆盖 dict；训练时与基模 default_config 合并（用户值优先）。

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    # 当前状态；落库默认 Pending。
    metrics = models.JSONField(default=dict, help_text='训练指标：{epoch, loss, acc, ...}')
    # 训练指标 dict；本 commit 恒为 {}，worker（Sub-Issue 6）执行后填写。
    artifact_path = models.CharField(max_length=1024, blank=True, null=True, help_text='训练产物本地目录绝对路径')
    # 训练出的模型产物目录；worker 填写。
    model_version = models.CharField(max_length=255, blank=True, help_text='写入 Prediction.model_version，格式 f"{base_model.name}__{job.id}"')
    # 产物的"版本号"字符串，将来写进 Prediction 记录，可追溯"哪次训练的产物"。
    celery_task_id = models.CharField(max_length=255, blank=True, null=True)
    # Celery 任务 id：本 commit 由 tasks.py 的 seam 写占位 uuid4().hex；
    # Sub-Issue 6 后换成 run_training.delay() 返回的真实 id。
    error_message = models.TextField(blank=True, null=True)
    # 失败原因；worker 填写。

    # 审计
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
    )
    # 创建人（用户删除 → NULL）。
    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.CASCADE, null=True,
    )
    # 所属组织：API 创建路径由 perform_create 强制注入用户当前组织；
    # null=True 只是 schema 宽松（ORM 直建理论上可为空，API 不会）。
    created_at = models.DateTimeField(auto_now_add=True)
    # 创建时间。
    started_at = models.DateTimeField(null=True, blank=True)
    # worker 开始执行时间（本 commit 恒 NULL）。
    completed_at = models.DateTimeField(null=True, blank=True)
    # worker 结束时间（本 commit 恒 NULL）。

    def has_permission(self, user):
        """仅同组织成员可访问。"""
        # ★★★ 本次 commit 新增。详情端点对象级拦截的唯一依据（403 的判据）。
        return user.active_organization_id == self.organization_id
        # 纯相等比较：用户当前组织 pk == 任务组织 pk。
        # 注意没有"预置豁免"（与 BaseModel 不同）：训练任务严格私有到组织。
        # _id 形式 → 无额外 SQL。

    def __str__(self):
        return f'TrainingJob #{self.id} ({self.base_model.name} -> {self.project})'
        # 如 'TrainingJob #7 (bert-base -> 情感分析项目)'。
        # 注意：str 里访问 self.base_model.name 会触发一次 FK 查询
        # （除非实例已 select_related 缓存）——只在展示场景用，无所谓。

    class Meta:
        db_table = 'training_job'
        # 物理表名。
        ordering = ['-created_at']
        # 默认排序：创建时间倒序（新任务在前）。
        # API 列表 queryset 未显式指定 order_by → 自动套用这个默认序。


class TestRun(models.Model):
    """一次测试任务（零样本 or 训练产物）"""
    # 语义：拿一个"模型"（预置基模本身 = 零样本，或某次训练的产物 = 微调后）
    # 在某项目的测试子集上跑评估，产出指标。

    class TestSubset(models.TextChoices):
        # 测试数据子集策略（取值与 TrainingJob.TrainSubset 完全相同，独立定义便于各自演进）。
        ALL = 'All', 'All tasks'
        HAS_GT = 'HasGT', 'Tasks with ground truth annotations'
        SAMPLE = 'Sample', 'Random sample of annotated tasks'

    class Status(models.TextChoices):
        # 状态机取值（与 TrainingJob.Status 相同的一套，独立定义）。
        PENDING = 'Pending'
        RUNNING = 'Running'
        COMPLETED = 'Completed'
        FAILED = 'Failed'
        CANCELED = 'Canceled'

    # 二选一：training_job（训练产物测试）或 base_model（零样本测试）
    training_job = models.ForeignKey(
        TrainingJob, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='test_runs',
        help_text='训练产物测试（与 base_model 二选一）',
    )
    # 指向"训练产物"：测某次训练练出来的模型。
    # SET_NULL + null：对应任务被删时置 NULL（测试记录保留，但 target 丢了）。
    base_model = models.ForeignKey(
        BaseModel, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='test_runs',
        help_text='零样本测试（与 training_job 二选一）',
    )
    # 指向"基模本身"：不做训练直接测（zero-shot）。同样 SET_NULL。
    # 两个 FK 都是可空——"二选一"约束由应用层保证：
    #   模型 clean()（纯 ORM 路径）+ 序列化器 validate()（API 路径，见 serializers.py）。
    project = models.ForeignKey('projects.Project', on_delete=models.CASCADE, related_name='test_runs')
    # 在哪个项目的数据上测。CASCADE：项目删 → 测试记录删。
    test_subset = models.CharField(max_length=16, choices=TestSubset.choices, default=TestSubset.HAS_GT)
    # 测试子集策略；默认 HasGT。

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    # 当前状态；API 创建即 Pending。
    metrics = models.JSONField(default=dict, help_text='测试指标：{accuracy, f1, precision, recall, confusion_matrix, total, correct, skipped}')
    # 评估指标 dict（本 commit 恒 {}，worker 填写）。
    celery_task_id = models.CharField(max_length=255, blank=True, null=True)
    # Celery 任务 id（本 commit 为 seam 占位 uuid）。
    error_message = models.TextField(blank=True, null=True)
    # 失败原因。

    # 审计
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
    )
    # 创建人（用户删除 → NULL）。
    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.CASCADE, null=True,
    )
    # 所属组织（API 创建路径强制注入）。
    created_at = models.DateTimeField(auto_now_add=True)
    # 创建时间。
    started_at = models.DateTimeField(null=True, blank=True)
    # worker 开始时间（本 commit 恒 NULL）。
    completed_at = models.DateTimeField(null=True, blank=True)
    # worker 结束时间（本 commit 恒 NULL）。

    def clean(self):
        """校验 training_job 与 base_model 二选一"""
        from django.core.exceptions import ValidationError
        # 函数内 import：避免模块顶部再引入一个依赖（Django 惯例，成本忽略不计）。
        if self.training_job and self.base_model:
            raise ValidationError('training_job 和 base_model 不能同时设置（二选一）')
            # 两个都设 → 违反 XOR。
        if not self.training_job and not self.base_model:
            raise ValidationError('training_job 和 base_model 必须设置其一（二选一）')
            # 两个都没设 → 违反 XOR。
        # ※ DRF 默认不调用 full_clean()/clean()，所以 API 路径上这道防线不生效，
        #   真正生效的是 TestRunSerializer.validate()（规则相同，两处保持一致）；
        #   clean() 服务 admin、shell、ORM 直建等场景。

    def has_permission(self, user):
        """仅同组织成员可访问。"""
        # ★★★ 本次 commit 新增。详情端点对象级拦截依据（跨组织 403）。
        return user.active_organization_id == self.organization_id
        # 与 TrainingJob.has_permission 同规则：严格同组织，无预置豁免。

    def __str__(self):
        target = self.training_job or self.base_model
        # XOR 保证两者恰好一个非 None（正常数据下），or 取到"测试对象"。
        return f'TestRun #{self.id} ({target} -> {self.project})'
        # 如 'TestRun #3 (TrainingJob #7 -> 项目)'。

    class Meta:
        db_table = 'training_test_run'
        # 物理表名（避免 Django 默认 'training_testrun' 之外的歧义，统一风格）。
        ordering = ['-created_at']
        # 默认排序：新记录在前（API 列表直接受益）。
