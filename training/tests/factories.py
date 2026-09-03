"""测试工厂（Sub-Issue 4）。

BaseModelFactory：SKLEARN + is_active=True。BaseModel.save() 对 is_active=True
校验 local_path 目录存在且含 model.pkl，因此工厂在 build 前生成真实本地目录。

约定：优先运行时在 <repo>/.test_models/ 下新建目录；若测试进程禁止新建文件
（DSH sandbox 限制子进程文件写入），回落到预先置备的共享目录
<repo>/.test_models/shared/sklearn（含占位 model.pkl）。显式传入 local_path 可覆盖。
"""

import os
import tempfile
from pathlib import Path

import factory

from training.models import BaseModel

# <repo>/training/tests/factories.py -> 上一级 x3 = 仓库根
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MODEL_ROOT = os.path.join(_REPO_ROOT, '.test_models')
_SHARED_SKLEARN_DIR = os.path.join(_MODEL_ROOT, 'shared', 'sklearn')


class BaseModelFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f'base-model-{n}')
    task_type = BaseModel._meta.get_field('task_type').choices[0][0]
    framework = BaseModel.Framework.SKLEARN
    description = factory.LazyFunction(lambda: '')
    default_config = factory.LazyFunction(dict)
    is_active = True

    class Meta:
        model = BaseModel

    @factory.lazy_attribute
    def local_path(self):
        """生成含空 model.pkl 的真实临时目录（SKLEARN 校验通过）。"""
        try:
            os.makedirs(_MODEL_ROOT, exist_ok=True)
            d = tempfile.mkdtemp(prefix='bm_', dir=_MODEL_ROOT)
            if self.framework == BaseModel.Framework.YOLO:
                Path(d, 'yolov8n.pt').write_bytes(b'dummy')
            else:
                Path(d, 'model.pkl').write_bytes(b'dummy')
            return d
        except OSError:
            # 测试进程被禁止新建文件时使用预置的共享目录（只读校验路径）。
            return _SHARED_SKLEARN_DIR
