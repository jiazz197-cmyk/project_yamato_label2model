"""YOLO 数据集与标签转换（本地、不联网）。

本模块只处理 Label Studio 的 RectangleLabels（目标检测）与 PolygonLabels
（实例分割）标注，输出 Ultralytics YOLO 训练/验证所需的目录与 data.yaml。
图像来源仅限 task.data['image']：本地文件必须在 BASE_DATA_DIR 内，远程图片
必须由 Label Studio storage resolver 解析；直接 HTTP URL 一律拒绝。
"""

import logging
import os
import random
import shutil
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

_MODE_DETECT = 'detect'
_MODE_SEGMENT = 'segment'
_IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tif', '.tiff'}
logger = logging.getLogger(__name__)


class YoloDatasetInfo(str):
    """兼容字符串路径与元信息字典两种用法的 YOLO 数据集结果。"""

    def __new__(cls, data_yaml, **kwargs):
        instance = super().__new__(cls, str(data_yaml))
        instance.data_yaml = str(data_yaml)
        meta = dict(kwargs)
        meta.setdefault('data_yaml', str(data_yaml))
        instance._meta = meta
        for key, value in kwargs.items():
            setattr(instance, key, value)
        return instance

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._meta[key]
        return super().__getitem__(key)

    def get(self, key, default=None):
        return self._meta.get(key, default)

    def keys(self):
        return self._meta.keys()

    def items(self):
        return self._meta.items()

    def exists(self):
        return Path(str(self)).exists()

    def read_text(self, *args, **kwargs):
        return Path(str(self)).read_text(*args, **kwargs)

    @property
    def parent(self):
        return Path(str(self)).parent


def _fmt(value):
    """格式化归一化坐标，避免尾随 0，并保留最多 6 位小数。"""
    return f'{float(value):.6f}'.rstrip('0').rstrip('.')


def _task_data(task):
    """从 Task ORM 对象或序列化 dict 中取 data。"""
    if hasattr(task, 'data'):
        return task.data or {}
    if isinstance(task, dict):
        data = task.get('data')
        if isinstance(data, dict):
            return data
        return task
    return {}


def _task_id(task, index):
    if hasattr(task, 'id') and task.id is not None:
        return task.id
    if isinstance(task, dict) and task.get('id') is not None:
        return task['id']
    return index


def _image_filename(image, task, index):
    """从 URL/本地路径提取安全的图片文件名；无法提取时退回 task_<id>.jpg。"""
    try:
        path_part = urlparse(str(image)).path or str(image)
    except Exception:
        path_part = str(image)
    name = Path(path_part).name
    suffix = Path(name).suffix.lower()
    if name and suffix in _IMAGE_SUFFIXES:
        return name
    suffix = Path(str(image)).suffix.lower()
    if suffix not in _IMAGE_SUFFIXES:
        suffix = '.jpg'
    return f'task_{_task_id(task, index)}{suffix}'


def build_class_names(project):
    """按 label_config 出现顺序返回 RectangleLabels/PolygonLabels 的有序类名列表。

    无可用矩形/多边形控制标签时抛 ``ValueError``。
    """
    try:
        parsed = project.get_parsed_config()
    except AttributeError:
        parsed = project.get('parsed_label_config') if isinstance(project, dict) else getattr(project, 'parsed_label_config', {})

    names = []
    seen = set()
    if not isinstance(parsed, dict):
        parsed = {}
    for control_name, control in parsed.items():
        if not isinstance(control, dict):
            continue
        control_type = control.get('type') or control_name
        if control_type.lower() not in ('rectanglelabels', 'polygonlabels'):
            continue
        labels = control.get('labels') or []
        if isinstance(labels, str):
            labels = [labels]
        for label in labels:
            if label not in seen:
                names.append(label)
                seen.add(label)
    if not names:
        raise ValueError('Project has no RectangleLabels or PolygonLabels labels for YOLO training')
    return names


def _region_label(region):
    value = region.get('value') if isinstance(region.get('value'), dict) else region
    for key in ('rectanglelabels', 'polygonlabels', 'labels'):
        labels = value.get(key)
        if labels is None and key != 'labels':
            labels = region.get(key)
        if labels is None:
            continue
        if isinstance(labels, str):
            labels = [labels]
        if labels:
            return str(labels[0])
    return None


def annotation_to_yolo(annotation, class_map, mode):
    """将单个 Label Studio region 转换为一行 YOLO 标签。

    返回字符串（如 ``0 0.5 0.5 0.2 0.2``）；忽略不支持/不在 class_map 的 region
    时返回 ``None``。``annotation`` 也可传入完整 annotation（含 ``result`` 列表），
    此时返回所有可转换行组成的列表（供批量数据集构造复用）。
    """
    if isinstance(class_map, (list, tuple)):
        class_map = {name: idx for idx, name in enumerate(class_map)}

    if not isinstance(annotation, dict):
        # 兼容 ORM Annotation / SimpleNamespace 等对象
        result = getattr(annotation, 'result', None)
        if isinstance(result, (list, tuple)):
            lines = []
            for region in result:
                line = annotation_to_yolo(region, class_map, mode)
                if line:
                    lines.append(line)
            return lines
        region_type = getattr(annotation, 'type', None)
        value = getattr(annotation, 'value', None)
        if region_type is not None:
            annotation = {'type': region_type, 'value': value or {}}
        else:
            return None
    if 'result' in annotation and isinstance(annotation.get('result'), (list, tuple)):
        lines = []
        for region in annotation['result']:
            line = annotation_to_yolo(region, class_map, mode)
            if line:
                lines.append(line)
        return lines
    if annotation.get('type') not in ('rectanglelabels', 'polygonlabels'):
        return None
    region_type = annotation['type']
    value = annotation.get('value') or {}
    if not isinstance(value, dict):
        return None

    label = _region_label(annotation)
    if label is None or label not in class_map:
        return None
    class_idx = int(class_map[label])

    if mode == _MODE_DETECT and region_type == 'rectanglelabels':
        try:
            x = float(value.get('x', 0)) / 100.0
            y = float(value.get('y', 0)) / 100.0
            width = float(value.get('width', 0)) / 100.0
            height = float(value.get('height', 0)) / 100.0
        except (TypeError, ValueError):
            return None
        cx = x + width / 2.0
        cy = y + height / 2.0
        return f'{class_idx} {_fmt(cx)} {_fmt(cy)} {_fmt(width)} {_fmt(height)}'

    if mode == _MODE_SEGMENT and region_type == 'polygonlabels':
        points = value.get('points')
        if not points or len(points) < 3:
            return None
        normalized = []
        try:
            for point in points:
                normalized.extend((float(point[0]) / 100.0, float(point[1]) / 100.0))
        except (TypeError, ValueError, IndexError):
            return None
        coords = ' '.join(_fmt(v) for v in normalized)
        return f'{class_idx} {coords}'

    return None


def _annotation_value(annotation, key, default=None):
    """同时兼容 ORM Annotation 与序列化 dict。"""
    if isinstance(annotation, dict):
        return annotation.get(key, default)
    return getattr(annotation, key, default)


def _annotation_sort_key(annotation):
    """按 updated_at / created_at / id 排序，取最新一份 annotation。"""
    updated = _annotation_value(annotation, 'updated_at')
    created = _annotation_value(annotation, 'created_at')
    identifier = _annotation_value(annotation, 'id')
    timestamp = updated or created or ''
    return (str(timestamp), str(identifier or ''))


def _iter_annotation_regions(task):
    """从 Task 序列化 dict/ORM 对象中产出**最新一份未取消** annotation 的 region。

    Label Studio 一个 task 可能有多份 annotation（多人标注/多轮修订）。训练只应
    使用最终结果，否则同一目标会被写成多个正样本。这里按 updated_at/created_at
    取最新，跳过 ``was_cancelled=True`` 的草稿。
    """
    if isinstance(task, dict):
        annotations = task.get('annotations') or []
    else:
        annotations = getattr(task, 'annotations', None)
        if annotations is None:
            return
        # ORM related manager / list-like
        try:
            annotations = annotations.all()
        except AttributeError:
            pass

    candidates = []
    for annotation in annotations:
        if _annotation_value(annotation, 'was_cancelled', False):
            continue
        candidates.append(annotation)
    if not candidates:
        return

    annotation = max(candidates, key=_annotation_sort_key)
    if isinstance(annotation, dict):
        if 'result' in annotation:
            results = annotation.get('result') or []
            for result in results:
                yield result
        elif annotation.get('type') and annotation.get('value') is not None:
            yield annotation
    else:
        results = getattr(annotation, 'result', None) or []
        for result in results:
            yield result


def _image_max_bytes() -> int:
    """单张图片允许的最大字节数；默认 50MB。"""
    raw = os.environ.get('TRAINING_IMAGE_MAX_BYTES', '')
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 50 * 1024 * 1024
    return value if value > 0 else 50 * 1024 * 1024


def _download_image(url: str, dst_path: Path) -> str | None:
    """下载 storage resolver 返回的图片；禁止重定向并限制大小。"""
    parsed = urlparse(str(url))
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        logger.warning('reject non-http image url from storage resolver: scheme=%s', parsed.scheme)
        return None

    max_bytes = _image_max_bytes()
    tmp_path = dst_path.with_name(f'{dst_path.name}.part')
    try:
        with requests.get(
            str(url),
            stream=True,
            timeout=(5, 30),
            allow_redirects=False,
        ) as response:
            if int(getattr(response, 'status_code', 0)) != 200:
                logger.warning(
                    'storage image download failed: host=%s status=%s',
                    parsed.hostname,
                    getattr(response, 'status_code', None),
                )
                return None
            content_length = getattr(response, 'headers', {}).get('Content-Length')
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        logger.warning('storage image too large: host=%s', parsed.hostname)
                        return None
                except (TypeError, ValueError):
                    pass

            written = 0
            with tmp_path.open('wb') as handle:
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > max_bytes:
                        logger.warning('storage image exceeded size limit: host=%s', parsed.hostname)
                        handle.close()
                        tmp_path.unlink(missing_ok=True)
                        return None
                    handle.write(chunk)
        tmp_path.replace(dst_path)
        return str(dst_path)
    except Exception as exc:  # noqa: BLE001 - 单张图片失败只跳过该样本
        logger.warning('storage image download error: host=%s error=%s', parsed.hostname, type(exc).__name__)
        tmp_path.unlink(missing_ok=True)
        return None


def materialize_image(task, project, dst):
    """把 task 图片落到 ``dst``（文件路径或目录）。

    安全约束：
    - 只接受 Label Studio storage resolver 返回的 http(s) URL；
    - task.data['image'] 直接写 http(s) 一律拒绝（避免 SSRF）；
    - 本地文件必须位于 ``BASE_DATA_DIR`` 内（避免任意文件读取）；
    - 单文件默认上限 50MB（``TRAINING_IMAGE_MAX_BYTES``）。

    成功返回写入后的路径字符串；无法解析/下载/复制时返回 ``None``。
    """
    data = _task_data(task)
    image = data.get('image')
    if not image:
        return None
    if not isinstance(image, str):
        image = str(image)

    dst_path = Path(dst)
    if dst_path.exists() and dst_path.is_dir():
        dst_path = dst_path / _image_filename(image, task, 0)
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    resolved_url = None
    # 优先走 Label Studio storage 解析，拿到可下载 URL（MinIO/S3/本地存储代理）。
    resolver = None
    if hasattr(task, 'resolve_storage_uri'):
        resolver = task.resolve_storage_uri
    elif hasattr(project, 'resolve_storage_uri'):
        resolver = project.resolve_storage_uri
    if resolver is not None:
        try:
            resolved = resolver(image)
            if isinstance(resolved, dict) and resolved.get('url'):
                resolved_url = str(resolved['url'])
        except Exception:
            resolved_url = None

    if resolved_url:
        return _download_image(resolved_url, dst_path)

    if image.startswith(('http://', 'https://')):
        logger.warning('reject direct remote image url; import it through Label Studio storage first')
        return None

    src = Path(image)
    if not src.is_file():
        return None

    base_dir = os.environ.get('BASE_DATA_DIR', '')
    if not base_dir:
        logger.warning('reject local image without BASE_DATA_DIR: %s', src.name)
        return None
    try:
        src_resolved = src.resolve()
        base_resolved = Path(base_dir).resolve()
        src_resolved.relative_to(base_resolved)
    except (OSError, ValueError):
        logger.warning('reject local image outside BASE_DATA_DIR: %s', src.name)
        return None

    try:
        if src_resolved.stat().st_size > _image_max_bytes():
            logger.warning('local image too large: %s', src.name)
            return None
        shutil.copyfile(src_resolved, dst_path)
        return str(dst_path)
    except OSError as exc:
        logger.warning('local image copy failed: %s (%s)', src.name, type(exc).__name__)
        return None

def build_yolo_dataset(project, tasks, workdir, mode, val_split=None):
    """构造 YOLO 数据集目录并返回数据集元信息。

    - ``mode``: ``'detect'`` 或 ``'segment'``。
    - ``val_split``: train/val 比例；``None`` 时读取环境变量
      ``TRAINING_YOLO_VAL_SPLIT``，默认 0.2。
    - 样本 < 2 时不生成 val 集。
    """
    if mode not in (_MODE_DETECT, _MODE_SEGMENT):
        raise ValueError(f'Unsupported YOLO mode: {mode}')

    names = build_class_names(project)
    class_map = {name: idx for idx, name in enumerate(names)}

    if val_split is None:
        try:
            val_split = float(os.environ.get('TRAINING_YOLO_VAL_SPLIT', '0.2'))
        except (TypeError, ValueError):
            val_split = 0.2
    val_split = float(val_split)

    workdir = Path(workdir)
    images_dir = workdir / 'images'
    labels_dir = workdir / 'labels'
    train_images = images_dir / 'train'
    val_images = images_dir / 'val'
    train_labels = labels_dir / 'train'
    val_labels = labels_dir / 'val'
    train_images.mkdir(parents=True, exist_ok=True)
    train_labels.mkdir(parents=True, exist_ok=True)

    tasks = list(tasks)
    if len(tasks) < 2 or val_split <= 0:
        train_tasks = tasks
        val_tasks = []
    else:
        n_val = max(1, int(round(len(tasks) * val_split)))
        if n_val >= len(tasks):
            n_val = max(1, len(tasks) - 1)
        shuffled = list(tasks)
        random.Random(0).shuffle(shuffled)
        val_tasks = shuffled[:n_val]
        train_tasks = shuffled[n_val:]
        val_images.mkdir(parents=True, exist_ok=True)
        val_labels.mkdir(parents=True, exist_ok=True)

    skipped = 0
    train_count = 0
    val_count = 0

    for split_name, split_tasks in (('train', train_tasks), ('val', val_tasks)):
        if not split_tasks:
            continue
        split_images = train_images if split_name == 'train' else val_images
        split_labels = train_labels if split_name == 'train' else val_labels
        used_filenames = set()
        for index, task in enumerate(split_tasks):
            data = _task_data(task)
            image = data.get('image') if isinstance(data, dict) else None
            if not image:
                skipped += 1
                continue
            filename = _image_filename(image, task, index)
            if filename in used_filenames:
                stem, suffix = os.path.splitext(filename)
                filename = f'{stem}_{_task_id(task, index)}{suffix}'
            used_filenames.add(filename)
            image_dst = split_images / filename
            if materialize_image(task, project, str(image_dst)) is None:
                skipped += 1
                continue

            lines = []
            for region in _iter_annotation_regions(task):
                line = annotation_to_yolo(region, class_map, mode)
                if line:
                    lines.append(line)
            if not lines:
                # 有图但无有效矩形/多边形标注：保留计数为 skipped，并移除无效图。
                try:
                    image_dst.unlink()
                except OSError:
                    pass
                skipped += 1
                continue

            label_dst = split_labels / f'{image_dst.stem}.txt'
            label_dst.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            if split_name == 'train':
                train_count += 1
            else:
                val_count += 1

    data = {
        'path': str(workdir),
        'train': 'images/train',
        'nc': len(names),
        'names': names,
    }
    if val_count > 0:
        data['val'] = 'images/val'

    data_yaml = workdir / 'data.yaml'
    data_yaml.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding='utf-8')

    return YoloDatasetInfo(
        str(data_yaml),
        dataset_dir=str(workdir),
        images_dir=str(images_dir),
        labels_dir=str(labels_dir),
        train_count=train_count,
        val_count=val_count,
        skipped=skipped,
    )
