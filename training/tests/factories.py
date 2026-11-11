"""测试工厂：YOLO 基模。

``BaseModel.save()`` 对 ``is_active=True`` 会校验 ``local_path`` 目录存在且含
``*.pt`` 权重，因此工厂在创建前生成真实本地目录（含占位 ``.pt`` 文件）。

约定：优先运行时在 <repo>/.test_models/ 下新建目录；若测试进程禁止新建文件
（受限 sandbox），回落到预先置备的共享目录 <repo>/.test_models/shared/yolo。
显式传入 local_path 可覆盖。
"""

import os
import tempfile
from pathlib import Path

import factory

from training.models import BaseModel

# <repo>/training/tests/factories.py -> 上一级 x3 = 仓库根
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MODEL_ROOT = os.path.join(_REPO_ROOT, '.test_models')
_SHARED_YOLO_DIR = os.path.join(_MODEL_ROOT, 'shared', 'yolo')


def make_yolo_model_dir(parent=None):
    """创建含占位 ``.pt`` 的临时目录（通过 YOLO local_path 校验）。"""
    parent = parent or _MODEL_ROOT
    os.makedirs(parent, exist_ok=True)
    directory = tempfile.mkdtemp(prefix='bm_', dir=parent)
    Path(directory, 'yolov8n.pt').write_bytes(b'dummy')
    return directory


class BaseModelFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f'base-model-{n}')
    task_type = BaseModel.TaskType.OBJECT_DETECTION
    framework = BaseModel.Framework.YOLO
    description = factory.LazyFunction(lambda: '')
    default_config = factory.LazyFunction(dict)
    is_active = True

    class Meta:
        model = BaseModel

    @factory.lazy_attribute
    def local_path(self):
        """生成含占位 .pt 的真实临时目录（YOLO 校验通过）。"""
        try:
            return make_yolo_model_dir()
        except OSError:
            # 测试进程被禁止新建文件时使用预置的共享目录（只读校验路径）。
            return _SHARED_YOLO_DIR
