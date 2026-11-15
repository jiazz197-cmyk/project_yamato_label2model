"""db_bootstrap legacy schema 校验测试。"""

import pytest

from services.ml_api import db_bootstrap


class FakeInspector:
    def __init__(self, tables):
        self.tables = tables

    def get_table_names(self):
        return list(self.tables)

    def get_columns(self, table):
        return [{'name': name} for name in self.tables[table]]


def _tables():
    return {
        'training_base_model': db_bootstrap._BASE_MODEL_COLUMNS,
        'training_job': db_bootstrap._TRAINING_JOB_COLUMNS,
    }


def test_complete_legacy_schema_passes():
    db_bootstrap._validate_legacy_schema(FakeInspector(_tables()))


def test_missing_table_rejected():
    tables = _tables()
    tables.pop('training_job')
    with pytest.raises(RuntimeError, match='不完整'):
        db_bootstrap._validate_legacy_schema(FakeInspector(tables))


def test_missing_column_rejected():
    tables = _tables()
    tables['training_job'] = tables['training_job'] - {'created_at'}
    with pytest.raises(RuntimeError, match='created_at'):
        db_bootstrap._validate_legacy_schema(FakeInspector(tables))
