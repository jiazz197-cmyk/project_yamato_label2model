"""测试工厂（Sub-Issue 4）。

BaseModelFactory：SKLEARN + is_active=True。BaseModel.save() 对 is_active=True
校验 local_path 目录存在且含 model.pkl，因此工厂在 build 前生成真实本地目录。

约定：优先运行时在 <repo>/.test_models/ 下新建目录；若测试进程禁止新建文件
（DSH sandbox 限制子进程文件写入），回落到预先置备的共享目录
<repo>/.test_models/shared/sklearn（含占位 model.pkl）。显式传入 local_path 可覆盖。
"""

# ============================================================================
# 【注释版】对应 commit ada930cea9e72e045e86d1c3744e8e032c280148，仅供理解，请勿提交。
# 背景：为什么工厂这么"重"？
#   BaseModel.save() 在 is_active=True 时会调 utils.validate_local_model_path：
#   SKLEARN 框架要求 local_path 是真实存在的目录且里面有 model.pkl。
#   所以工厂不能只给个假路径字符串——必须真的在磁盘上造一个模型目录，
#   否则 factory.create() 在 save 阶段就会抛 ValidationError。
# ============================================================================

import os
# 标准库：路径拼接、makedirs、isdir 等文件系统操作。
import tempfile
# 标准库：mkdtemp 生成唯一临时目录名/目录。
from pathlib import Path
# pathlib：Path(d, 'model.pkl').write_bytes(...) 简洁地写文件。

import factory
# factory_boy 库：声明式测试数据工厂（声明字段 → create() 自动建 ORM 对象）。

from training.models import BaseModel
# 工厂要生产的 ORM 模型。

# <repo>/training/tests/factories.py -> 上一级 x3 = 仓库根
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 从本文件绝对路径逐级 dirname：
#   abspath(__file__) = <repo>\training\tests\factories.py
#   dirname #1 → <repo>\training\tests
#   dirname #2 → <repo>\training
#   dirname #3 → <repo>（仓库根目录）
_MODEL_ROOT = os.path.join(_REPO_ROOT, '.test_models')
# 测试临时模型目录根： <repo>/.test_models/
# （已加入 .gitignore——本 commit 的 .gitignore 改动就是为它。）
_SHARED_SKLEARN_DIR = os.path.join(_MODEL_ROOT, 'shared', 'sklearn')
# 共享回落目录：含占位 model.pkl 的预置 SKLEARN 模型目录（只读复用）。


class BaseModelFactory(factory.django.DjangoModelFactory):
    # DjangoModelFactory：factory_boy 的 Django 专用工厂，
    # 字段声明直接映射到模型属性，create() 时调 ORM save。
    name = factory.Sequence(lambda n: f'base-model-{n}')
    # Sequence：第 n 次生成得 f'base-model-{n}'（n 从 0 递增，工厂实例级计数）。
    # 作用：name 是 unique=True 字段，Sequence 保证同进程内多次 create 不撞唯一约束
    # （测试间数据库隔离时 n 重新计数，但 sqlite 测试库每个测试事务回滚，也不冲突）。
    task_type = BaseModel._meta.get_field('task_type').choices[0][0]
    # 取 task_type 字段 choices 的"第一个选项"的值：
    # _meta.get_field('task_type') → 字段对象；.choices → [(value, label), ...]；
    # [0][0] → 第一个 value（SkillNames 的第一个值，'TextClassification'）。
    # 用反射取值而不是硬编码字符串：枚举顺序将来变了工厂自动跟随。
    framework = BaseModel.Framework.SKLEARN
    # 固定用 SKLEARN 框架：校验规则最轻（只要一个 model.pkl，不用 joblib 能加载的真实模型），
    # 最适合做"占位但合法"的测试基模。
    description = factory.LazyFunction(lambda: '')
    # LazyFunction：每次 build 时调用 lambda 生成值。
    # 对不可变的 '' 其实可以直接写死，这里用 LazyFunction 是统一"动态默认值"的写法习惯。
    default_config = factory.LazyFunction(dict)
    # LazyFunction(dict)：每次 build 调 dict() 生成"新的空 dict"。
    # 必须这样写：JSONField(default=dict) 若工厂里写 default_config = {}，
    # 所有实例会共享同一个 dict 对象（可变默认值陷阱），一个实例改了会污染其他实例。
    is_active = True
    # 活跃：这会触发 save() 里的 local_path 校验（所以下面的 lazy_attribute 必须造真目录）。

    class Meta:
        model = BaseModel
        # 声明工厂对应的模型（factory_boy 必需）。

    @factory.lazy_attribute
    def local_path(self):
        """生成含空 model.pkl 的真实临时目录（SKLEARN 校验通过）。"""
        # lazy_attribute：声明"每个实例 build 时执行一次"的属性（区别于类级常量）。
        # 返回的字符串会作为 BaseModel.local_path 字段值传给 ORM。
        try:
            os.makedirs(_MODEL_ROOT, exist_ok=True)
            # 确保 <repo>/.test_models/ 存在（exist_ok=True：已存在不报错）。
            d = tempfile.mkdtemp(prefix='bm_', dir=_MODEL_ROOT)
            # 在 .test_models/ 下建唯一临时目录：bm_<随机串>/（mkdtemp 原子创建并返回路径）。
            Path(d, 'model.pkl').write_bytes(b'dummy')
            # 往目录里写一个"假 model.pkl"（内容 b'dummy'）：
            # validate_local_model_path 对 SKLEARN 只检查文件存在性（os.path.isfile），
            # 不加载内容，所以假字节流足以通过校验。
            return d
            # 返回该目录路径 → BaseModel.save() 的校验会通过。
        except OSError:
            # 测试进程被禁止新建文件时使用预置的共享目录（只读校验路径）。
            # 兜底场景：DSH sandbox 限制测试子进程的文件写入时 makedirs/mkdtemp 会抛 OSError；
            # 此时回落到预先手工置备的 .test_models/shared/sklearn/（含占位 model.pkl）。
            # 注意：若共享目录也没置备，save() 校验仍会失败——文档约定"预先置备"。
            return _SHARED_SKLEARN_DIR
    # 使用方式（test_api.py 的 base_model fixture）：
    #   BaseModelFactory.create(organization=..., created_by=...)
    # create(...) 的额外 kwargs 会覆盖工厂声明的字段（organization/created_by 未声明，
    # 由调用方显式传入；local_path 由 lazy_attribute 动态生成，也可被显式传入覆盖）。
