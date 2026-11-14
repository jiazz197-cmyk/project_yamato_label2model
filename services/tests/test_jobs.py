"""训练入队 helper 与失败回调的纯单测（SQLite，无 Redis）。"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.ml_api import jobs
from services.ml_api.models import Base, TrainingJob


@pytest.fixture
def session_factory():
    engine = create_engine(
        'sqlite+pysqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    engine.dispose()


def _make_job(factory, status='Running'):
    with factory() as session:
        job = TrainingJob(
            base_model_id=1,
            project_id=1,
            train_subset='HasGT',
            hyperparams={},
            status=status,
            organization_id=1,
            created_by_id=1,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.id


def test_training_job_timeout_default(monkeypatch):
    monkeypatch.delenv('TRAINING_JOB_TIMEOUT', raising=False)
    assert jobs.training_job_timeout() == 7 * 24 * 60 * 60


@pytest.mark.parametrize('raw', ['86400', ' 3600 '])
def test_training_job_timeout_from_env(monkeypatch, raw):
    monkeypatch.setenv('TRAINING_JOB_TIMEOUT', raw)
    assert jobs.training_job_timeout() == int(raw)


@pytest.mark.parametrize('raw', ['abc', '0', '-1'])
def test_training_job_timeout_invalid_falls_back(monkeypatch, raw):
    monkeypatch.setenv('TRAINING_JOB_TIMEOUT', raw)
    assert jobs.training_job_timeout() == 7 * 24 * 60 * 60


def test_enqueue_uses_long_timeout_and_no_retry(monkeypatch):
    captured = {}

    class FakeQueue:
        def enqueue(self, func, *args, **kwargs):
            captured['args'] = args
            captured.update(kwargs)
            return 'job-1'

    monkeypatch.delenv('TRAINING_JOB_TIMEOUT', raising=False)
    monkeypatch.setattr(jobs, 'get_training_queue', lambda: FakeQueue())

    assert jobs.enqueue_training_job(42) == 'job-1'
    assert captured['args'] == (42,)
    assert captured['job_timeout'] == 7 * 24 * 60 * 60
    assert captured['retry'] is None
    assert captured['on_failure'] is jobs.on_training_failure
    assert captured['job_id'] == 'training:42'


def test_failure_callback_marks_job_failed(session_factory, monkeypatch):
    job_id = _make_job(session_factory, status='Running')
    monkeypatch.setattr(jobs, 'SessionLocal', session_factory)

    class FakeJob:
        args = (job_id,)

    jobs.on_training_failure(FakeJob(), None, ValueError, ValueError('boom'), None)

    with session_factory() as session:
        job = session.get(TrainingJob, job_id)
        assert job.status == 'Failed'
        assert 'ValueError: boom' in job.error_message
        assert job.completed_at is not None


def test_failure_callback_keeps_terminal_status(session_factory, monkeypatch):
    job_id = _make_job(session_factory, status='Canceled')
    monkeypatch.setattr(jobs, 'SessionLocal', session_factory)

    class FakeJob:
        args = (job_id,)

    jobs.on_training_failure(FakeJob(), None, ValueError, ValueError('boom'), None)

    with session_factory() as session:
        assert session.get(TrainingJob, job_id).status == 'Canceled'


def test_failure_callback_ignores_missing_args(session_factory, monkeypatch):
    monkeypatch.setattr(jobs, 'SessionLocal', session_factory)

    class FakeJob:
        args = ()

    jobs.on_training_failure(FakeJob(), None, ValueError, ValueError('boom'), None)
