"""BaseModel.save() 校验行为（@pytest.mark.django_db）。"""

import pytest
from django.core.exceptions import ValidationError

from training.models import BaseModel


def _make_sklearn_dir(tmp_path):
    d = tmp_path / 'm'
    d.mkdir()
    (d / 'model.pkl').write_bytes(b'dummy')
    return d


@pytest.mark.django_db
def test_save_valid_active(tmp_path):
    d = _make_sklearn_dir(tmp_path)
    bm = BaseModel(
        name='valid-active',
        task_type='TextClassification',
        framework=BaseModel.Framework.SKLEARN,
        local_path=str(d),
        is_active=True,
    )
    bm.save()
    assert BaseModel.objects.filter(pk=bm.pk).exists()


@pytest.mark.django_db
def test_save_invalid_active(tmp_path):
    bm = BaseModel(
        name='invalid-active',
        task_type='TextClassification',
        framework=BaseModel.Framework.SKLEARN,
        local_path=str(tmp_path / 'does-not-exist'),
        is_active=True,
    )
    with pytest.raises(ValidationError):
        bm.save()


@pytest.mark.django_db
def test_save_invalid_inactive(tmp_path):
    bm = BaseModel(
        name='invalid-inactive',
        task_type='TextClassification',
        framework=BaseModel.Framework.SKLEARN,
        local_path=str(tmp_path / 'does-not-exist'),
        is_active=False,
    )
    bm.save()
    assert BaseModel.objects.filter(pk=bm.pk).exists()
