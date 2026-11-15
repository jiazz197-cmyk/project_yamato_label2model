"""训练入队 helper 与失败回调的纯单测（SQLite，无 Redis）。"""

import re

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


def test_training_job_id_is_rq_safe():
    job_id = jobs.rq_job_id(42)
    assert job_id == 'training-42'
    assert re.fullmatch(r'[A-Za-z0-9_-]+', job_id)


def test_enqueue_uses_long_timeout_and_no_retry(monkeypatch):
    captured = {}

    class FakeQueue:
        def enqueue(self, func, *args, **kwargs):
            captured['args'] = args
            captured.update(kwargs)
            return 'job-1'

    class NoExistingJob:
        @staticmethod
        def fetch(*args, **kwargs):
            raise jobs.NoSuchJobError()

    monkeypatch.delenv('TRAINING_JOB_TIMEOUT', raising=False)
    monkeypatch.setattr(jobs, 'Job', NoExistingJob)
    monkeypatch.setattr(jobs, 'get_training_queue', lambda: FakeQueue())

    assert jobs.enqueue_training_job(42) == 'job-1'
    assert captured['args'] == (42,)
    assert captured['job_timeout'] == 7 * 24 * 60 * 60
    assert captured['retry'] is None
    assert captured['on_failure'] is jobs.on_training_failure
    assert captured['job_id'] == 'training-42'


def test_enqueue_returns_existing_job_without_duplicating(monkeypatch):
    existing = object()

    class ExistingJob:
        @staticmethod
        def fetch(*args, **kwargs):
            return existing

    monkeypatch.setattr(jobs, 'Job', ExistingJob)
    monkeypatch.setattr(
        jobs,
        'get_training_queue',
        lambda: pytest.fail('must not enqueue when job already exists'),
    )

    assert jobs.enqueue_training_job(42) is existing


def test_cancel_queued_job(monkeypatch):
    class FakeJob:
        id = 'training-42'
        cancelled = False

        def get_status(self, refresh=False):
            return 'queued'

        def cancel(self):
            self.cancelled = True

    fake_job = FakeJob()

    class FakeJobClass:
        @staticmethod
        def fetch(*args, **kwargs):
            return fake_job

    monkeypatch.setattr(jobs, 'Job', FakeJobClass)
    monkeypatch.setattr(jobs, 'get_redis_connection', lambda: object())

    assert jobs.cancel_training_job(42) is True
    assert fake_job.cancelled is True


def test_cancel_running_job_sends_stop(monkeypatch):
    calls = []

    class FakeJob:
        id = 'training-42'

        def get_status(self, refresh=False):
            return 'started'

    class FakeJobClass:
        @staticmethod
        def fetch(*args, **kwargs):
            return FakeJob()

    monkeypatch.setattr(jobs, 'Job', FakeJobClass)
    monkeypatch.setattr(jobs, 'get_redis_connection', lambda: object())
    monkeypatch.setattr(jobs, 'send_stop_job_command', lambda connection, job_id: calls.append(job_id))

    assert jobs.cancel_training_job(42) is True
    assert calls == ['training-42']


def test_reconcile_marks_orphaned_running_job(session_factory, monkeypatch):
    job_id = _make_job(session_factory, status='Running')

    class FakeWorker:
        @staticmethod
        def all(connection=None):
            return []

    monkeypatch.setattr(jobs, 'SessionLocal', session_factory)
    monkeypatch.setattr(jobs.rq, 'Worker', FakeWorker)
    monkeypatch.setattr(jobs, 'get_redis_connection', lambda: object())

    assert jobs.reconcile_running_training_jobs() == 1
    with session_factory() as session:
        job = session.get(TrainingJob, job_id)
        assert job.status == 'Failed'
        assert job.completed_at is not None
        assert '对账' in job.error_message


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
