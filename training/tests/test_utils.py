"""training.utils 纯单测（无 DB）：validate_local_model_path + scan_local_models + task_type_guess。"""

import json

import pytest
from django.core.exceptions import ValidationError

from training.utils import (
    FRAMEWORK_HF,
    FRAMEWORK_SKLEARN,
    TASK_TYPE_NER,
    TASK_TYPE_TEXT_CLASSIFICATION,
    scan_local_models,
    validate_local_model_path,
)


def _make_hf_dir(parent, name='hf-model', config=None, weights=True):
    """构造 HF 目录：config.json（可选内容）+ 可选空 model.safetensors。"""
    d = parent / name
    d.mkdir()
    (d / 'config.json').write_text(json.dumps(config if config is not None else {}), encoding='utf-8')
    if weights:
        (d / 'model.safetensors').write_bytes(b'dummy')
    return d


def _make_sklearn_fitted_dir(parent, name='sklearn-model'):
    """构造含真实 fitted estimator 的 sklearn 目录（classes_ 非空）。"""
    pytest.importorskip('sklearn')
    import joblib
    from sklearn.linear_model import LogisticRegression

    d = parent / name
    d.mkdir()
    est = LogisticRegression().fit([[0], [1]], [0, 1])
    joblib.dump(est, d / 'model.pkl')
    return d


# === validate：happy path ===


def test_validate_hf_ok(tmp_path):
    _make_hf_dir(tmp_path)
    validate_local_model_path(str(tmp_path / 'hf-model'), FRAMEWORK_HF)  # 不抛即通过


def test_validate_hf_ok_pytorch_model_bin(tmp_path):
    d = tmp_path / 'hf'
    d.mkdir()
    (d / 'config.json').write_text('{}', encoding='utf-8')
    (d / 'pytorch_model.bin').write_bytes(b'dummy')
    validate_local_model_path(str(d), FRAMEWORK_HF)


def test_validate_sklearn_ok(tmp_path):
    d = tmp_path / 'sk'
    d.mkdir()
    (d / 'model.pkl').write_bytes(b'dummy')
    validate_local_model_path(str(d), FRAMEWORK_SKLEARN)


# === validate：failure ===


def test_validate_hf_missing_weights(tmp_path):
    d = _make_hf_dir(tmp_path, weights=False)
    with pytest.raises(ValidationError):
        validate_local_model_path(str(d), FRAMEWORK_HF)


def test_validate_empty_dir(tmp_path):
    d = tmp_path / 'empty'
    d.mkdir()
    with pytest.raises(ValidationError):
        validate_local_model_path(str(d), FRAMEWORK_HF)


def test_validate_nonexistent_path(tmp_path):
    with pytest.raises(ValidationError):
        validate_local_model_path(str(tmp_path / 'nope'), FRAMEWORK_HF)


def test_validate_unknown_framework(tmp_path):
    d = tmp_path / 'm'
    d.mkdir()
    with pytest.raises(ValidationError):
        validate_local_model_path(str(d), 'UNKNOWN')


# === scan：happy path ===


def test_scan_mixed_models(tmp_path):
    root = tmp_path / 'models'
    root.mkdir()
    hf = _make_hf_dir(root, name='hf-model', config={'id2label': {'0': 'neg', '1': 'pos'}})
    sk = _make_sklearn_fitted_dir(root, name='sklearn-model')

    results = scan_local_models(str(root))

    assert len(results) == 2
    by_name = {r['name']: r for r in results}
    assert set(by_name) == {'hf-model', 'sklearn-model'}
    assert by_name['hf-model']['framework'] == FRAMEWORK_HF
    assert by_name['hf-model']['local_path'] == str(hf)
    assert by_name['hf-model']['task_type_guess'] == TASK_TYPE_TEXT_CLASSIFICATION
    assert by_name['sklearn-model']['framework'] == FRAMEWORK_SKLEARN
    assert by_name['sklearn-model']['task_type_guess'] == TASK_TYPE_TEXT_CLASSIFICATION


def test_scan_hf_ner(tmp_path):
    root = tmp_path / 'models'
    root.mkdir()
    _make_hf_dir(root, name='ner', config={'id2label': {'0': 'O', '1': 'B-PER', '2': 'I-PER'}})

    results = scan_local_models(str(root))

    assert len(results) == 1
    assert results[0]['task_type_guess'] == TASK_TYPE_NER


def test_scan_hf_architectures(tmp_path):
    root = tmp_path / 'models'
    root.mkdir()
    _make_hf_dir(root, name='cls', config={'architectures': ['BertForSequenceClassification']})

    results = scan_local_models(str(root))

    assert results[0]['task_type_guess'] == TASK_TYPE_TEXT_CLASSIFICATION


# === scan：failure / 边界 ===


def test_scan_empty_dir(tmp_path):
    root = tmp_path / 'models'
    root.mkdir()
    assert scan_local_models(str(root)) == []


def test_scan_no_model_subdirs(tmp_path):
    root = tmp_path / 'models'
    root.mkdir()
    (root / 'random').mkdir()
    (root / 'file.txt').write_text('x', encoding='utf-8')
    assert scan_local_models(str(root)) == []


def test_scan_nonexistent_root(tmp_path):
    assert scan_local_models(str(tmp_path / 'nope')) == []


def test_scan_skips_hidden_and_reserved(tmp_path):
    root = tmp_path / 'models'
    root.mkdir()
    _make_hf_dir(root, name='.hidden', config={'id2label': {'0': 'a', '1': 'b'}})
    _make_hf_dir(root, name='uploads', config={'id2label': {'0': 'a', '1': 'b'}})
    _make_hf_dir(root, name='trained', config={'id2label': {'0': 'a', '1': 'b'}})

    assert scan_local_models(str(root)) == []


def test_scan_hf_no_hints(tmp_path):
    root = tmp_path / 'models'
    root.mkdir()
    _make_hf_dir(root, name='hf', config={})

    results = scan_local_models(str(root))

    assert len(results) == 1
    assert results[0]['task_type_guess'] is None


def test_scan_hf_bad_json(tmp_path):
    root = tmp_path / 'models'
    root.mkdir()
    d = root / 'hf'
    d.mkdir()
    (d / 'config.json').write_text('not json', encoding='utf-8')
    (d / 'model.safetensors').write_bytes(b'dummy')

    results = scan_local_models(str(root))

    assert len(results) == 1
    assert results[0]['task_type_guess'] is None


def test_scan_sklearn_corrupt_pkl(tmp_path):
    root = tmp_path / 'models'
    root.mkdir()
    d = root / 'bad'
    d.mkdir()
    (d / 'model.pkl').write_bytes(b'not a pickle')

    results = scan_local_models(str(root))

    assert len(results) == 1
    assert results[0]['framework'] == FRAMEWORK_SKLEARN
    assert results[0]['task_type_guess'] is None


def test_scan_sklearn_no_classes(tmp_path):
    pytest.importorskip('sklearn')
    import joblib

    root = tmp_path / 'models'
    root.mkdir()
    d = root / 'nodlasses'
    d.mkdir()
    joblib.dump({'not': 'an estimator'}, d / 'model.pkl')

    results = scan_local_models(str(root))

    assert len(results) == 1
    assert results[0]['task_type_guess'] is None
