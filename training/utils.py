"""本地预置基模目录校验与扫描。

轻依赖：只 import 标准库 + ``django.core.exceptions.ValidationError``。
``joblib`` 仅在 sklearn 任务类型推导时惰性导入；不 import ``ml_models``，
使 ``validate_local_model_path`` / ``scan_local_models`` 可脱离 Django ORM
做纯单测。task_type 用本地常量（与 ``ml_models.models.SkillNames`` 值一致）。
"""

import glob
import json
import os

from django.core.exceptions import ValidationError

TASK_TYPE_TEXT_CLASSIFICATION = 'TextClassification'
TASK_TYPE_NER = 'NamedEntityRecognition'
TASK_TYPE_OBJECT_DETECTION = 'ObjectDetection'
TASK_TYPE_INSTANCE_SEGMENTATION = 'InstanceSegmentation'
FRAMEWORK_HF = 'HF'
FRAMEWORK_SKLEARN = 'SKLEARN'
FRAMEWORK_YOLO = 'YOLO'

# scan_local_models 跳过的保留目录名：Sub-Issue 17 上传暂存目录、Sub-Issue 6 训练产物目录，均非基模。
_SKIP_DIR_NAMES = {'uploads', 'trained'}


def _has_hf_weights(path):
    """HF 权重文件是否存在。

    精确名优先：``pytorch_model.bin`` / ``model.safetensors``；
    再宽松通配：``*.safetensors`` 与 ``pytorch_model*.bin``（覆盖分片模型）。
    """
    if os.path.isfile(os.path.join(path, 'pytorch_model.bin')):
        return True
    if os.path.isfile(os.path.join(path, 'model.safetensors')):
        return True
    if glob.glob(os.path.join(path, '*.safetensors')):
        return True
    if glob.glob(os.path.join(path, 'pytorch_model*.bin')):
        return True
    return False


def _has_yolo_weights(path):
    """YOLO 权重文件是否存在：目录含 ``*.pt`` 即视为存在（只查文件，不加载）。"""
    return bool(glob.glob(os.path.join(path, '*.pt')))


def validate_local_model_path(path, framework):
    """校验 ``path`` 为存在的目录且含框架期望文件；失败抛 ``ValidationError``。

    - ``HF``：目录含 ``config.json`` 且存在权重文件（``pytorch_model.bin`` 或
      ``model.safetensors``，含分片通配）。
    - ``SKLEARN``：目录含 ``model.pkl``（只查存在性，不加载内容）。
    - ``YOLO``：目录含 ``*.pt``（只查存在性，不加载内容）。
    - 其他 framework：抛 ``ValidationError``。
    """
    if not path or not os.path.isdir(path):
        raise ValidationError(f'Local model path does not exist or is not a directory: {path}')

    if framework == FRAMEWORK_HF:
        if not os.path.isfile(os.path.join(path, 'config.json')):
            raise ValidationError(f'HF model missing config.json in: {path}')
        if not _has_hf_weights(path):
            raise ValidationError(
                f'HF model missing weight file (pytorch_model.bin / model.safetensors) in: {path}'
            )
    elif framework == FRAMEWORK_SKLEARN:
        if not os.path.isfile(os.path.join(path, 'model.pkl')):
            raise ValidationError(f'sklearn model missing model.pkl in: {path}')
    elif framework == FRAMEWORK_YOLO:
        if not _has_yolo_weights(path):
            raise ValidationError(f'YOLO model missing .pt file in: {path}')
    else:
        raise ValidationError(f'Unknown framework: {framework}')


def _detect_framework(dirpath):
    """探测一级子目录的框架：``config.json`` → HF，否则 ``model.pkl`` → SKLEARN，否则 ``*.pt`` → YOLO。"""
    if os.path.isfile(os.path.join(dirpath, 'config.json')):
        return FRAMEWORK_HF
    if os.path.isfile(os.path.join(dirpath, 'model.pkl')):
        return FRAMEWORK_SKLEARN
    if glob.glob(os.path.join(dirpath, '*.pt')):
        return FRAMEWORK_YOLO
    return None


def _guess_hf_task_type(config_path):
    """读 ``config.json`` 推导 task_type；解析失败返回 None，不抛错。

    1. ``architectures`` 优先：任一含 ``TokenClassification`` → NER；
       任一含 ``SequenceClassification`` → TextClassification。
    2. 否则看 ``id2label``（dict 且非空）：任一 label 以 ``B-``/``I-`` 开头 → NER；
       否则去重后 >1 类 → TextClassification。
    3. 都无 → None。
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as fh:
            config = json.load(fh)
    except (OSError, ValueError):
        return None

    architectures = config.get('architectures')
    if isinstance(architectures, (list, tuple)):
        arch_text = ' '.join(str(a) for a in architectures)
        if 'TokenClassification' in arch_text:
            return TASK_TYPE_NER
        if 'SequenceClassification' in arch_text:
            return TASK_TYPE_TEXT_CLASSIFICATION

    id2label = config.get('id2label')
    if isinstance(id2label, dict) and id2label:
        labels = list(id2label.values())
        if any(str(label).startswith(('B-', 'I-')) for label in labels):
            return TASK_TYPE_NER
        if len({label for label in labels}) > 1:
            return TASK_TYPE_TEXT_CLASSIFICATION

    return None


def _guess_sklearn_task_type(pkl_path):
    """惰性 ``joblib.load`` 并读 ``classes_`` 推导 task_type；全程兜底返回 None，不抛错。

    Pipeline 自带 ``classes_``（指向 final estimator）；多输出（list/tuple）取第一个。
    ``len(classes) > 1`` → TextClassification；否则 None。pkl 损坏 / 非 estimator /
    无 ``classes_`` → None。
    """
    try:
        import joblib

        obj = joblib.load(pkl_path)
        classes = getattr(obj, 'classes_', None)
        if isinstance(classes, (list, tuple)):
            classes = classes[0]
        if classes is not None and len(classes) > 1:
            return TASK_TYPE_TEXT_CLASSIFICATION
    except Exception:
        return None
    return None


def scan_local_models(root):
    """扫描 ``root`` 一级子目录，返回可识别的基模列表（按名字排序）。

    - ``root`` 空 / 非目录 → 返回 ``[]``。
    - 不递归，按名字排序，跳过隐藏目录（``.`` 开头）与保留名 ``uploads``/``trained``。
    - 每项：``{name, framework, local_path, task_type_guess}``；无法识别框架的目录跳过。
    - YOLO 目录不推断 task_type（避免加载 torch），``task_type_guess`` 返回 ``None``。
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
        framework = _detect_framework(dirpath)
        if framework is None:
            continue

        if framework == FRAMEWORK_HF:
            task_type_guess = _guess_hf_task_type(os.path.join(dirpath, 'config.json'))
        elif framework == FRAMEWORK_SKLEARN:
            task_type_guess = _guess_sklearn_task_type(os.path.join(dirpath, 'model.pkl'))
        else:  # FRAMEWORK_YOLO：扫描期不加载 torch，task_type 由用户显式选择
            task_type_guess = None

        results.append(
            {
                'name': name,
                'framework': framework,
                'local_path': dirpath,
                'task_type_guess': task_type_guess,
            }
        )

    results.sort(key=lambda item: item['name'])
    return results
