"""YOLO 数据集安全与 annotation 选择测试（纯本地，不联网）。"""

import pytest

from services.ml_api import yolo
from services.ml_api import yolo_adapter


def test_direct_http_image_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(
        yolo.requests,
        'get',
        lambda *args, **kwargs: pytest.fail('direct http image must not be fetched'),
    )
    task = {'data': {'image': 'http://169.254.169.254/latest/meta-data/'}}
    assert yolo.materialize_image(task, None, tmp_path / 'x.jpg') is None


def test_local_image_outside_base_data_dir_is_rejected(monkeypatch, tmp_path):
    base = tmp_path / 'data'
    base.mkdir()
    outside = tmp_path / 'etc-passwd'
    outside.write_bytes(b'root:x:0:0')
    monkeypatch.setenv('BASE_DATA_DIR', str(base))

    task = {'data': {'image': str(outside)}}
    assert yolo.materialize_image(task, None, tmp_path / 'copy.bin') is None


def test_local_image_inside_base_data_dir_is_copied(monkeypatch, tmp_path):
    base = tmp_path / 'data'
    base.mkdir()
    source = base / 'image.jpg'
    source.write_bytes(b'jpeg-bytes')
    monkeypatch.setenv('BASE_DATA_DIR', str(base))
    monkeypatch.setenv('TRAINING_IMAGE_MAX_BYTES', '1024')

    task = {'data': {'image': str(source)}}
    dst = tmp_path / 'out' / 'copy.jpg'
    assert yolo.materialize_image(task, None, dst) == str(dst)
    assert dst.read_bytes() == b'jpeg-bytes'


def test_local_image_over_limit_is_rejected(monkeypatch, tmp_path):
    base = tmp_path / 'data'
    base.mkdir()
    source = base / 'big.jpg'
    source.write_bytes(b'x' * 32)
    monkeypatch.setenv('BASE_DATA_DIR', str(base))
    monkeypatch.setenv('TRAINING_IMAGE_MAX_BYTES', '8')

    task = {'data': {'image': str(source)}}
    assert yolo.materialize_image(task, None, tmp_path / 'big.jpg') is None


def test_latest_non_cancelled_annotation_wins():
    task = {
        'annotations': [
            {
                'id': 1,
                'updated_at': '2026-01-01T00:00:00Z',
                'result': [{'type': 'rectanglelabels', 'value': {'rectanglelabels': ['old']}}],
            },
            {'id': 2, 'updated_at': '2026-01-03T00:00:00Z', 'was_cancelled': True, 'result': []},
            {
                'id': 3,
                'updated_at': '2026-01-02T00:00:00Z',
                'result': [{'type': 'rectanglelabels', 'value': {'rectanglelabels': ['new']}}],
            },
        ]
    }
    regions = list(yolo._iter_annotation_regions(task))
    assert len(regions) == 1
    assert regions[0]['value']['rectanglelabels'] == ['new']


def test_no_annotation_returns_nothing():
    assert list(yolo._iter_annotation_regions({'annotations': []})) == []
    assert list(
        yolo._iter_annotation_regions(
            {'annotations': [{'id': 1, 'was_cancelled': True, 'result': [{'type': 'rectanglelabels'}]}]}
        )
    ) == []


def test_model_name_truncated_to_column_width():
    class Base:
        name = 'x' * 400

    version = yolo_adapter._model_name(Base(), {'id': 123})
    assert len(version) <= 255
    assert version.endswith('__123')


def test_require_int_rejects_bool_and_float():
    with pytest.raises(ValueError):
        yolo_adapter._require_int({'epochs': True}, 'epochs', 100, 1, 1000)
    with pytest.raises(ValueError):
        yolo_adapter._require_int({'epochs': 1.5}, 'epochs', 100, 1, 1000)
    assert yolo_adapter._require_int({'epochs': '5'}, 'epochs', 100, 1, 1000) == 5


def test_train_without_project_fails_clearly(monkeypatch, tmp_path):
    model_dir = tmp_path / 'base'
    model_dir.mkdir()
    (model_dir / 'best.pt').write_bytes(b'not-a-real-weight')
    monkeypatch.setenv('LOCAL_MODEL_ROOT', str(tmp_path))

    job = {
        'id': 7,
        'base_model': {'name': 'base', 'local_path': str(model_dir), 'task_type': 'ObjectDetection'},
        'hyperparams': {},
    }
    with pytest.raises(ValueError, match='project'):
        yolo_adapter.train(job, [])
