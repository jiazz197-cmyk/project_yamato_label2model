"""本地预置 YOLO 基模目录校验与扫描。

轻依赖：只 import 标准库 + ``django.core.exceptions.ValidationError``。
不 import 训练适配器/模型，使 ``validate_local_model_path`` / ``scan_local_models``
可脱离 Django ORM 做纯单测。
"""

import glob
import os

from django.core.exceptions import ValidationError

FRAMEWORK_YOLO = 'YOLO'

# scan_local_models 跳过的保留目录名：模型上传暂存目录、训练产物目录，均非基模。
_SKIP_DIR_NAMES = {'uploads', 'trained'}


def _has_yolo_weights(path):
    """YOLO 权重文件是否存在：目录含 ``*.pt`` 即视为存在（只查文件，不加载）。"""
    return bool(glob.glob(os.path.join(path, '*.pt')))


def validate_local_model_path(path):
    """校验 ``path`` 为存在的目录且含 YOLO 权重（``*.pt``）；失败抛 ``ValidationError``。

    只查文件存在性，不加载权重内容。
    """
    if not path or not os.path.isdir(path):
        raise ValidationError(f'Local model path does not exist or is not a directory: {path}')

    if not _has_yolo_weights(path):
        raise ValidationError(f'YOLO model missing .pt file in: {path}')


def scan_local_models(root):
    """扫描 ``root`` 一级子目录，返回可识别的 YOLO 基模候选列表（按名字排序）。

    - ``root`` 空 / 非目录 → 返回 ``[]``。
    - 不递归，按名字排序，跳过隐藏目录（``.`` 开头）与保留名 ``uploads``/``trained``。
    - 每项：``{name, framework, local_path}``；无法识别为 YOLO（不含 ``*.pt``）的目录跳过。
    """
    if not root or not os.path.isdir(root):
        return []

    try:
        entries = list(os.scandir(root))
    except OSError:
        return []

    results = []
    for entry in entries:
        name = entry.name
        if name.startswith('.') or name in _SKIP_DIR_NAMES:
            continue
        if not entry.is_dir(follow_symlinks=False):
            continue

        dirpath = os.path.abspath(entry.path)
        if not _has_yolo_weights(dirpath):
            continue

        results.append(
            {
                'name': name,
                'framework': FRAMEWORK_YOLO,
                'local_path': dirpath,
            }
        )

    results.sort(key=lambda item: item['name'])
    return results
