"""training.utils 纯单测（无 DB）：validate_local_model_path + scan_local_models（YOLO-only）。"""

import pytest
from django.core.exceptions import ValidationError

from training.utils import FRAMEWORK_YOLO, scan_local_models, validate_local_model_path


def _make_yolo_dir(parent, name='yolo-model'):
    """构造含占位 .pt 的 YOLO 目录。"""
    directory = parent / name
    directory.mkdir()
    (directory / 'yolov8n.pt').write_bytes(b'dummy')
    return directory


def _make_non_yolo_dir(parent, name='other-model'):
    """构造不含 .pt 的目录（HF/sklearn 残留形态，应被忽略）。"""
    directory = parent / name
    directory.mkdir()
    (directory / 'config.json').write_text('{}', encoding='utf-8')
    (directory / 'model.pkl').write_bytes(b'dummy')
    return directory


# === validate ===


def test_validate_yolo_ok(tmp_path):
    validate_local_model_path(str(_make_yolo_dir(tmp_path)))  # 不抛即通过


def test_validate_nonexistent_path(tmp_path):
    with pytest.raises(ValidationError):
        validate_local_model_path(str(tmp_path / 'nope'))


def test_validate_empty_dir(tmp_path):
    directory = tmp_path / 'empty'
    directory.mkdir()
    with pytest.raises(ValidationError):
        validate_local_model_path(str(directory))


def test_validate_path_is_file(tmp_path):
    file_path = tmp_path / 'weights.pt'
    file_path.write_bytes(b'dummy')
    with pytest.raises(ValidationError):
        validate_local_model_path(str(file_path))


def test_validate_none_path():
    with pytest.raises(ValidationError):
        validate_local_model_path(None)


# === scan ===


def test_scan_yolo_models(tmp_path):
    root = tmp_path / 'models'
    root.mkdir()
    yolo = _make_yolo_dir(root, name='yolov8')

    results = scan_local_models(str(root))

    assert results == [
        {
            'name': 'yolov8',
            'framework': FRAMEWORK_YOLO,
            'local_path': str(yolo),
        }
    ]


def test_scan_sorted_by_name(tmp_path):
    root = tmp_path / 'models'
    root.mkdir()
    _make_yolo_dir(root, name='b-model')
    _make_yolo_dir(root, name='a-model')

    results = scan_local_models(str(root))

    assert [item['name'] for item in results] == ['a-model', 'b-model']


def test_scan_skips_non_yolo_dirs_and_files(tmp_path):
    root = tmp_path / 'models'
    root.mkdir()
    _make_non_yolo_dir(root)
    (root / 'random').mkdir()
    (root / 'file.txt').write_text('x', encoding='utf-8')

    assert scan_local_models(str(root)) == []


def test_scan_empty_dir(tmp_path):
    root = tmp_path / 'models'
    root.mkdir()
    assert scan_local_models(str(root)) == []


def test_scan_nonexistent_root(tmp_path):
    assert scan_local_models(str(tmp_path / 'nope')) == []


def test_scan_none_root():
    assert scan_local_models(None) == []


def test_scan_skips_hidden_and_reserved(tmp_path):
    root = tmp_path / 'models'
    root.mkdir()
    _make_yolo_dir(root, name='.hidden')
    _make_yolo_dir(root, name='uploads')
    _make_yolo_dir(root, name='trained')

    assert scan_local_models(str(root)) == []
