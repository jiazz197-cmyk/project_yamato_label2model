"""Training REST API 序列化器（BaseModel / TrainingJob / TestRun）。

- BaseModelSerializer：只读（列表/详情均不提供写入端点）。
- TrainingJobSerializer：写字段仅 base_model/project/train_subset/hyperparams。
- TestRunSerializer：project 必填；base_model_id 与 training_job_id 二选一（write_only）。
"""

# ============================================================================
# 【注释版】对应 commit ada930cea9e72e045e86d1c3744e8e032c280148，仅供理解，请勿提交。
# 序列化器的两条主线：
# 1) 入参方向（to_internal_value）：把客户端 JSON 解析、校验成 ORM 对象/合法值；
#    校验失败 → ValidationError → DRF 统一 400。
# 2) 出参方向（to_representation）：把 ORM 对象转成可 JSON 化的 dict/list。
# read_only 字段只走出参方向；写字段必须客户端给（required）且通过校验。
# ============================================================================

from projects.models import Project  # 项目 ORM 模型：FK 校验的 queryset 来源
from rest_framework import serializers  # DRF 序列化器基础类

from training.models import BaseModel, TestRun, TrainingJob  # 本 app 三个 ORM 模型


class BaseModelSerializer(serializers.ModelSerializer):
    # ModelSerializer：按 Meta.model 的字段自动生成对应的序列化字段。
    organization = serializers.PrimaryKeyRelatedField(read_only=True)
    # organization 是 FK → 'organizations.Organization'。
    # 若不在这里显式声明，ModelSerializer 会自动生成"可写"的 PrimaryKeyRelatedField
    # （需要一个 queryset 来校验输入）。本端点纯只读，所以显式声明 read_only：
    # 出参 = 组织 id（int 或 null），入参一律忽略。

    class Meta:
        model = BaseModel
        # 指定映射的 ORM 模型；ModelSerializer 据此推导默认字段。
        fields = [
            'id',             # 主键
            'name',           # 基模名（unique）
            'task_type',      # 任务类型（SkillNames 枚举值）
            'framework',      # 'HF' / 'SKLEARN'
            'local_path',     # 本地模型目录绝对路径
            'description',    # 描述文本（可空）
            'default_config', # 默认超参 dict（JSONField）
            'is_active',      # 是否活跃
            'organization',   # 所属组织 id；预置基模为 null（上面已声明 read_only）
            'created_at',     # 创建时间（auto_now_add）
            'updated_at',     # 更新时间（auto_now）
        ]
        # 白名单：只输出这些字段。created_by 被有意排除（审计字段不暴露）。
        # 排序即输出顺序（DRF 按 fields 顺序 dump）。
        # organization 显式 read_only；其余字段均为只读端点，此处兜底声明。
        read_only_fields = [
            'id',             # 主键只读
            'name',           # 兜底：即使将来误用于写端点也不能写
            'task_type',      # 兜底
            'framework',      # 兜底
            'local_path',     # 兜底（基模目录只能由管理员线下放置，不开放 API 写）
            'description',    # 兜底
            'default_config', # 兜底
            'is_active',      # 兜底
            'created_at',     # auto_now_add，本来就只能由 Django 写
            'updated_at',     # auto_now，本来就只能由 Django 写
        ]
        # read_only_fields：批量把这些字段设为只读（等价于逐个声明 read_only=True）。
        # 本 commit 的端点只有 GET，所以这是"防御性兜底"——
        # 保证即使有人拿这个序列化器去搭写端点，所有字段也写不进去。


class TrainingJobSerializer(serializers.ModelSerializer):
    base_model = serializers.PrimaryKeyRelatedField(queryset=BaseModel.objects.all())
    # 显式重写 base_model（FK → BaseModel）：
    # - 入参：客户端给整型 pk（如 "base_model": 3）→ DRF 用 queryset 查库解析成实例；
    #   查不到 → ValidationError → 400（测试 test_invalid_base_model_400 验证的就是它）。
    # - queryset=BaseModel.objects.all()：注意这里没按组织过滤！
    #   跨组织 base_model 的拦截不在序列化器，而在 api.py perform_create 的
    #   base_model.has_permission(user) 检查（返回 403 而非 400）。
    # - 出参：序列化成 base_model 的 pk（int）。
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all())
    # 同理：项目 FK 走 pk 输入；同样不按组织过滤（组织校验在 perform_create）。

    class Meta:
        model = TrainingJob
        fields = [
            'id',             # 主键（出参）
            'base_model',     # 写字段：客户端必给 pk（上面显式声明的 PK 字段）
            'project',        # 写字段：客户端必给 pk
            'train_subset',   # 写字段：'All'/'HasGT'/'Sample'（模型默认 HasGT，可不传）
            'hyperparams',    # 写字段：超参 dict，merge 进 base_model.default_config 用（可不传，默认 {}）
            'status',         # 只读：'Pending'…'Canceled'，服务端维护
            'metrics',        # 只读：训练指标 dict（worker 写）
            'artifact_path',  # 只读：训练产物目录（worker 写）
            'model_version',  # 只读：f"{base_model.name}__{job.id}"（worker 写）
            'celery_task_id', # 只读：入队 seam 写的任务 id（201 响应里返回它）
            'error_message',  # 只读：失败原因（worker 写）
            'created_at',     # 只读
            'started_at',     # 只读：worker 开工时间
            'completed_at',   # 只读：worker 结束时间
        ]
        # 客户端可写的只有：base_model、project、train_subset、hyperparams（模块 docstring 的说法）。
        read_only_fields = [
            'id',             # 主键
            'status',         # 状态机字段，API 不允许直接改（PATCH 走 action=cancel 命令通道）
            'metrics',        # worker 产物
            'artifact_path',  # worker 产物
            'model_version',  # worker 产物
            'celery_task_id', # 入队 seam 产物
            'error_message',  # worker 产物
            'created_at',     # auto_now_add
            'started_at',     # worker 维护
            'completed_at',   # worker 维护
        ]
        # 未列入 read_only_fields 的四个字段即可写集；organization/created_by 不在 fields 里，
        # 客户端给也会被忽略（由 perform_create 通过 save 的 kwargs 注入）。


class TestRunSerializer(serializers.ModelSerializer):
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all())
    # 项目 FK：必填（required 是默认值）；pk 不存在 → 400。
    # ※ commit message 特别指出：这是"对父计划的修正"——
    #   TestRun.project 是必填 FK，父计划漏列了它，这里补上。
    base_model_id = serializers.PrimaryKeyRelatedField(
        source='base_model', queryset=BaseModel.objects.all(), required=False, write_only=True
    )
    # 三个关键参数：
    # - source='base_model'：字段名叫 base_model_id（对客户端的 API 契约），
    #   但解析结果写入 attrs['base_model']（与模型 FK 名一致，save 时直接用）。
    # - queryset：pk → 实例的解析来源；查不到 → 400。
    # - required=False：允许不传（因为与 training_job_id 二选一）。
    # - write_only=True：只在入参方向存在——响应 JSON 里不会有 base_model_id 键
    #   （模型本身有 base_model FK，但 fields 白名单里列的是 'base_model_id'，
    #   它被 write_only 屏蔽后，出参就没有任何"测试对象"信息，见 README）。
    training_job_id = serializers.PrimaryKeyRelatedField(
        source='training_job', queryset=TrainingJob.objects.all(), required=False, write_only=True
    )
    # 与上一个对称：写训练产物测试时给 training_job_id。

    class Meta:
        model = TestRun
        fields = [
            'id',             # 主键（出参）
            'project',        # 写字段：必给 pk
            'base_model_id',  # 写字段（write_only）：零样本测试目标，二选一之一
            'training_job_id',# 写字段（write_only）：训练产物测试目标，二选一之一
            'test_subset',    # 写字段：'All'/'HasGT'/'Sample'（默认 HasGT，可不传）
            'status',         # 只读
            'metrics',        # 只读：{accuracy, f1, precision, recall, confusion_matrix, total, correct, skipped}
            'celery_task_id', # 只读：入队 seam 产物
            'error_message',  # 只读
            'created_at',     # 只读
            'started_at',     # 只读
            'completed_at',   # 只读
        ]
        read_only_fields = [
            'id',             # 主键
            'status',         # 状态机字段
            'metrics',        # worker 产物
            'celery_task_id', # 入队 seam 产物
            'error_message',  # worker 产物
            'created_at',     # auto_now_add
            'started_at',     # worker 维护
            'completed_at',   # worker 维护
        ]
        # 可写集 = project、base_model_id、training_job_id、test_subset。
        # organization/created_by 不在白名单 → 由 perform_create 注入。

    def validate(self, attrs):
        # DRF 序列化器级钩子：所有字段各自的校验都通过后、save 之前调用。
        # attrs 的键是 source 重映射后的名字（'base_model' / 'training_job'，不是 * _id）。
        """base_model_id 与 training_job_id 必须二选一。"""
        base_model = attrs.get('base_model')
        training_job = attrs.get('training_job')
        # 没传的键是 required=False → 不在 attrs 里，.get 返回 None。
        if (base_model is None) == (training_job is None):
            # XOR 逻辑的真值表：
            #   base=None, job=None → (True) == (True) → True  → 抛错（都不给）
            #   base=实例, job=None → (False)== (True) → False → 通过（零样本）
            #   base=None, job=实例 → (True) == (False)→ False → 通过（训练产物）
            #   base=实例, job=实例 → (False)== (False)→ True  → 抛错（都给）
            raise serializers.ValidationError('base_model_id 和 training_job_id 必须二选一')
            # 抛错 → DRF 捕获 → 400（测试 test_test_run_xor_validation 验证）。
        return attrs
        # 必须原样返回 attrs（DRF 约定：validate 的返回值会替换后续使用的数据）。
        # ※ 为什么不在模型 clean() 里做？DRF 默认不调用模型 full_clean()，
        #   所以 API 路径上必须靠序列化器 validate()；模型 clean() 是留给
        #   纯 ORM 用法（admin / shell）的第二道防线，两处规则保持一致。
