"""YOLO 训练 adapter（Ultralytics，仅本地 .pt 权重）。

训练入口接收 ``job``（TrainingJob 或兼容对象）与已提取的 dataset tasks；
构造 YOLO 数据集、调用 ``model.train`` 并复制 ``best.pt``/``last.pt`` 到产物目录。
"""

import glob
import os
import shutil

try:
    from ultralytics import YOLO
except ImportError:  # 未安装时仍允许模块被导入，训练调用时会再次尝试
    YOLO = None

from training.yolo import build_yolo_dataset


def _find_pt(local_path):
    matches = sorted(glob.glob(os.path.join(str(local_path), '*.pt')))
    if not matches:
        raise FileNotFoundError(f'No .pt file found in YOLO base model directory: {local_path}')
    return os.path.abspath(matches[0])


def _job_id(job):
    if isinstance(job, dict):
        return job.get('id') or job.get('pk') or 'job'
    return getattr(job, 'id', None) or getattr(job, 'pk', None) or 'job'


def _artifact_path(job):
    existing = job.get('artifact_path') if isinstance(job, dict) else getattr(job, 'artifact_path', None)
    if existing:
        return existing
    try:
        from django.conf import settings

        root = getattr(settings, 'LOCAL_MODEL_ROOT', None)
        prefix = getattr(settings, 'TRAINING_ARTIFACTS_STORAGE_PREFIX', 'trained')
        if root:
            return os.path.join(str(root), str(prefix), str(_job_id(job)))
    except Exception:
        pass
    return os.path.abspath(os.path.join('trained', str(_job_id(job))))


def _base_model(job):
    base = getattr(job, 'base_model', None)
    if base is None and isinstance(job, dict):
        base = job.get('base_model')
    return base


def _model_name(base, job):
    name = getattr(base, 'name', None) or (base.get('name') if isinstance(base, dict) else None)
    if name:
        return f'{name}__{_job_id(job)}'
    return f'yolo__{_job_id(job)}'


def _merged_config(job, base):
    config = {}
    if base is not None:
        base_config = getattr(base, 'default_config', None) or (base.get('default_config') if isinstance(base, dict) else None)
        if isinstance(base_config, dict):
            config.update(base_config)
    hyperparams = getattr(job, 'hyperparams', None) or (job.get('hyperparams') if isinstance(job, dict) else None)
    if isinstance(hyperparams, dict):
        config.update(hyperparams)
    return config


def _copy_weight(run_dir, weight_name, artifact_dir):
    candidates = [
        os.path.join(run_dir, 'weights', weight_name),
        os.path.join(run_dir, weight_name),
        os.path.join(artifact_dir, 'weights', weight_name),
        os.path.join(artifact_dir, weight_name),
    ]
    for src in candidates:
        if os.path.isfile(src):
            dst = os.path.join(artifact_dir, weight_name)
            shutil.copyfile(src, dst)
            return dst
    return None


def _register_progress_callback(model, progress_cb):
    if progress_cb is None or not hasattr(model, 'add_callback'):
        return

    def on_train_epoch_end(trainer):
        loss = None
        if hasattr(trainer, 'loss'):
            try:
                loss = trainer.loss.item() if hasattr(trainer.loss, 'item') else trainer.loss
            except Exception:
                loss = None
        try:
            progress_cb(
                {
                    'epoch': getattr(trainer, 'epoch', None),
                    'total_epochs': getattr(trainer, 'epochs', None),
                    'loss': loss,
                }
            )
        except Exception:
            pass

    model.add_callback('on_train_epoch_end', on_train_epoch_end)


def _extract_metrics(model, result):
    metrics = {}
    # Ultralytics 训练后 model.metrics / trainer.metrics
    metric_obj = getattr(model, 'metrics', None)
    if metric_obj is None and result is not None:
        metric_obj = result.get('metrics') if isinstance(result, dict) else getattr(result, 'metrics', None)
    if metric_obj is None and isinstance(result, dict):
        metric_obj = result
    if metric_obj is not None:
        if hasattr(metric_obj, 'box'):
            box = metric_obj.box
            if box is not None:
                for key, attr in (
                    ('mAP50-95', 'map'),
                    ('mAP50', 'map50'),
                    ('precision', 'mp'),
                    ('recall', 'mr'),
                ):
                    value = getattr(box, attr, None)
                    if value is not None:
                        try:
                            metrics[key] = float(value)
                        except (TypeError, ValueError):
                            pass
        elif isinstance(metric_obj, dict):
            box = metric_obj.get('box')
            if isinstance(box, dict):
                for key, nested in (
                    ('mAP50-95', 'map'),
                    ('mAP50', 'map50'),
                    ('precision', 'mp'),
                    ('recall', 'mr'),
                ):
                    if nested in box and box[nested] is not None:
                        metrics[key] = box[nested]
            for key in ('mAP50-95', 'mAP50', 'precision', 'recall'):
                if key in metric_obj:
                    metrics[key] = metric_obj[key]
    return metrics



def train(job, dataset, progress_cb=None):
    """执行 YOLO 训练；失败时回写 Failed 状态并继续抛出异常。"""
    try:
        return _train(job, dataset, progress_cb=progress_cb)
    except Exception as exc:
        if isinstance(job, dict):
            job['status'] = 'Failed'
            job['error_message'] = str(exc)
        else:
            if hasattr(job, 'status'):
                job.status = 'Failed'
            if hasattr(job, 'error_message'):
                job.error_message = str(exc)
        raise


def _train(job, dataset, progress_cb=None):
    """执行 YOLO 训练（内部实现）。

    - ``job``: TrainingJob 或兼容对象（含 base_model、hyperparams、id）。
    - ``dataset``: 传给 ``build_yolo_dataset`` 的 tasks 列表。
    - ``progress_cb``: epoch 进度回调。
    """
    base = _base_model(job)
    local_path = getattr(base, 'local_path', None) or (base.get('local_path') if isinstance(base, dict) else None)
    if not local_path:
        raise ValueError('YOLO base model local_path is required')
    weights_path = _find_pt(local_path)

    artifact_dir = _artifact_path(job)
    os.makedirs(artifact_dir, exist_ok=True)
    dataset_dir = os.path.join(artifact_dir, 'dataset')
    os.makedirs(dataset_dir, exist_ok=True)

    project = getattr(job, 'project', None) or (job.get('project') if isinstance(job, dict) else None)
    base_task_type = base.get('task_type') if isinstance(base, dict) else getattr(base, 'task_type', None)
    task_type = getattr(job, 'task_type', None) or (job.get('task_type') if isinstance(job, dict) else None) or base_task_type
    if task_type in (None, 'ObjectDetection'):
        mode = 'detect'
    else:
        mode = 'segment'

    dataset_info = build_yolo_dataset(project, dataset, dataset_dir, mode=mode)
    if isinstance(dataset_info, dict):
        data_yaml = dataset_info['data_yaml']
    elif hasattr(dataset_info, 'data_yaml'):
        data_yaml = dataset_info.data_yaml
    else:
        data_yaml = str(dataset_info)
    if os.path.isfile(data_yaml):
        shutil.copyfile(data_yaml, os.path.join(artifact_dir, 'data.yaml'))

    config = _merged_config(job, base)
    train_params = {
        'data': data_yaml,
        'epochs': int(config.get('epochs', 100)),
        'imgsz': int(config.get('imgsz', 640)),
        'batch': int(config.get('batch', 16)),
        'device': config.get('device', ''),
        'project': artifact_dir,
        'name': 'run',
        'exist_ok': True,
    }

    if YOLO is None:
        from ultralytics import YOLO as _YOLO
        model_cls = _YOLO
    else:
        model_cls = YOLO
    model = model_cls(weights_path)
    _register_progress_callback(model, progress_cb)
    result = model.train(**train_params)

    _copy_weight(os.path.join(artifact_dir, 'run'), 'best.pt', artifact_dir)
    _copy_weight(os.path.join(artifact_dir, 'run'), 'last.pt', artifact_dir)
    # 兼容 result.save_dir 指向的自定义 run 目录
    if result is not None:
        save_dir = result.get('save_dir') if isinstance(result, dict) else getattr(result, 'save_dir', None)
        if save_dir:
            _copy_weight(str(save_dir), 'best.pt', artifact_dir)
            _copy_weight(str(save_dir), 'last.pt', artifact_dir)

    metrics = _extract_metrics(model, result)

    model_version = _model_name(base, job)
    if isinstance(job, dict):
        job['artifact_path'] = artifact_dir
        job['model_version'] = model_version
        job['metrics'] = metrics
        job['status'] = 'Completed'
    else:
        if hasattr(job, 'artifact_path'):
            job.artifact_path = artifact_dir
        if hasattr(job, 'model_version'):
            job.model_version = model_version
        if hasattr(job, 'metrics'):
            job.metrics = metrics
        if hasattr(job, 'status'):
            job.status = 'Completed'
    return metrics
