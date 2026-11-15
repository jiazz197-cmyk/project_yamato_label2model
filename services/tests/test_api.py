"""训练域 FastAPI 接口测试（TestClient + SQLite，无外部服务）。

覆盖：内部令牌、组织隔离、BaseModel 可见性、TrainingJob 创建/查询/取消、
项目过滤与扫描接口。真实 YOLO 执行不在本套测试范围（yolo-3）。
"""

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.ml_api.app import app
from services.ml_api.db import get_session
from services.ml_api.models import Base, BaseModel, ProjectRef, TrainingJob

ORG_A = 1
ORG_B = 2
PROJECT_A = 101
PROJECT_B = 202
PROJECT_DELETED = 303
PROJECT_GLOBAL = 404
USER_ID = 9


@pytest.fixture
def session_factory():
    """内存 SQLite：StaticPool 保证 TestClient 线程共用同一连接。"""
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


@pytest.fixture
def seed(session_factory):
    """两个组织、两个项目、四个基模（A/全局/B/停用）。"""
    with session_factory() as session:
        session.add_all(
            [
                ProjectRef(id=PROJECT_A, organization_id=ORG_A),
                ProjectRef(id=PROJECT_B, organization_id=ORG_B),
                ProjectRef(id=PROJECT_GLOBAL, organization_id=None),
                ProjectRef(
                    id=PROJECT_DELETED,
                    organization_id=ORG_A,
                    deleted_at=dt.datetime.now(dt.timezone.utc),
                ),
            ]
        )
        models = {
            'base_a': BaseModel(
                name='base-a',
                task_type='ObjectDetection',
                framework='YOLO',
                local_path='/models/a',
                default_config={'epochs': 100},
                is_active=True,
                organization_id=ORG_A,
            ),
            'base_b': BaseModel(
                name='base-b',
                task_type='ObjectDetection',
                framework='YOLO',
                local_path='/models/b',
                default_config={},
                is_active=True,
                organization_id=ORG_B,
            ),
            'base_global': BaseModel(
                name='base-global',
                task_type='InstanceSegmentation',
                framework='YOLO',
                local_path='/models/global',
                default_config={},
                is_active=True,
                organization_id=None,
            ),
            'base_inactive': BaseModel(
                name='base-inactive',
                task_type='ObjectDetection',
                framework='YOLO',
                local_path='/models/inactive',
                default_config={},
                is_active=False,
                organization_id=ORG_A,
            ),
        }
        session.add_all(models.values())
        session.commit()
        return {key: value.id for key, value in models.items()}


@pytest.fixture
def client(session_factory, monkeypatch):
    """带组织 A 上下文的内部客户端。"""
    monkeypatch.setenv('ML_API_INTERNAL_TOKEN', 'test-token')

    def override_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        test_client.headers.update(
            {
                'X-Internal-Token': 'test-token',
                'X-Organization-Id': str(ORG_A),
                'X-User-Id': str(USER_ID),
            }
        )
        yield test_client
    app.dependency_overrides.pop(get_session, None)


def _create_job(client, base_model_id, project=PROJECT_A, **overrides):
    payload = {
        'project': project,
        'base_model': base_model_id,
        'train_subset': 'HasGT',
        'hyperparams': {'epochs': 10},
    }
    payload.update(overrides)
    return client.post('/api/training/jobs', json=payload)


# ---------------------------------------------------------------------------
# 鉴权
# ---------------------------------------------------------------------------


def test_missing_or_wrong_token_401(client):
    assert client.get('/api/training/base-models', headers={'X-Internal-Token': 'wrong'}).status_code == 401
    with TestClient(app) as anonymous:
        assert anonymous.get('/api/training/base-models').status_code == 401


def test_missing_configured_token_fails_closed(monkeypatch):
    """环境里没有配置内部令牌时，接口必须 503，而不是默认放行。"""
    monkeypatch.delenv('ML_API_INTERNAL_TOKEN', raising=False)
    monkeypatch.delenv('TRAINER_INTERNAL_TOKEN', raising=False)
    with TestClient(app) as anonymous:
        response = anonymous.get('/api/training/base-models')
        assert response.status_code == 503


def test_prediction_placeholder_501(client):
    response = client.post('/api/predictions', json={})
    assert response.status_code == 501
    assert response.json()['todo'] == 'yolo-3'


# ---------------------------------------------------------------------------
# BaseModel
# ---------------------------------------------------------------------------


def test_list_base_models_includes_global_and_own_org(client, seed):
    response = client.get('/api/training/base-models')
    assert response.status_code == 200
    ids = {item['id'] for item in response.json()}
    assert seed['base_a'] in ids
    assert seed['base_global'] in ids
    assert seed['base_b'] not in ids
    assert seed['base_inactive'] not in ids


def test_list_base_models_without_organization_only_global(client, seed):
    response = client.get('/api/training/base-models', headers={'X-Organization-Id': ''})
    assert response.status_code == 200
    assert {item['id'] for item in response.json()} == {seed['base_global']}


def test_cross_org_base_model_detail_403(client, seed):
    response = client.get(f"/api/training/base-models/{seed['base_b']}")
    assert response.status_code == 403


def test_global_base_model_detail_visible(client, seed):
    response = client.get(f"/api/training/base-models/{seed['base_global']}")
    assert response.status_code == 200
    payload = response.json()
    assert payload['name'] == 'base-global'
    assert payload['organization'] is None


def test_missing_base_model_404(client):
    assert client.get('/api/training/base-models/999999').status_code == 404


def test_scan_local_models(client, tmp_path, monkeypatch):
    model_dir = tmp_path / 'yolov8'
    model_dir.mkdir()
    (model_dir / 'yolov8n.pt').write_bytes(b'dummy')
    monkeypatch.setenv('LOCAL_MODEL_ROOT', str(tmp_path))

    response = client.get('/api/training/base-models/scan')
    assert response.status_code == 200
    assert response.json() == [
        {'name': 'yolov8', 'framework': 'YOLO', 'local_path': str(model_dir)}
    ]


# ---------------------------------------------------------------------------
# TrainingJob
# ---------------------------------------------------------------------------


def test_create_training_job(client, seed, session_factory):
    response = _create_job(client, seed['base_a'])
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload['status'] == 'Pending'
    assert payload['train_subset'] == 'HasGT'
    assert payload['hyperparams'] == {'epochs': 10}
    assert payload['metrics'] == {}
    assert payload['artifact_path'] is None
    assert payload['model_version'] == ''
    assert payload['base_model'] == seed['base_a']
    assert payload['project'] == PROJECT_A

    with session_factory() as session:
        job = session.get(TrainingJob, payload['id'])
        assert job is not None
        assert job.organization_id == ORG_A
        assert job.created_by_id == USER_ID


def test_create_job_invalid_base_model_400(client, seed):
    response = _create_job(client, 999999)
    assert response.status_code == 400


def test_create_job_invalid_project_400(client, seed):
    response = _create_job(client, seed['base_a'], project=999999)
    assert response.status_code == 400
    # 保持 DRF 的字段级错误结构（不是 FastAPI 的 {"detail": ...}）
    assert list(response.json()) == ['project']


def test_create_job_for_deleted_project_400(client, seed):
    """Django Project 软删除后，训练任务不能再引用它。"""
    response = _create_job(client, seed['base_a'], project=PROJECT_DELETED)
    assert response.status_code == 400
    assert list(response.json()) == ['project']


def test_jobs_list_deleted_project_404(client, seed):
    response = client.get('/api/training/jobs', params={'project': PROJECT_DELETED})
    assert response.status_code == 404


@pytest.mark.parametrize('invalid_pk', [1.5, True])
def test_create_job_rejects_non_integer_pk(client, seed, invalid_pk):
    """bool 是 int 的子类、float 会被 int() 截断；这里必须按 DRF 拒绝。"""
    response = _create_job(client, invalid_pk)
    assert response.status_code == 400
    assert list(response.json()) == ['base_model']


def test_create_job_invalid_train_subset_400(client, seed):
    response = _create_job(client, seed['base_a'], train_subset='Nope')
    assert response.status_code == 400


def test_cross_org_project_403(client, seed):
    response = _create_job(client, seed['base_a'], project=PROJECT_B)
    assert response.status_code == 403


def test_cross_org_base_model_in_job_403(client, seed):
    response = _create_job(client, seed['base_b'])
    assert response.status_code == 403


def test_get_job_detail(client, seed):
    job_id = _create_job(client, seed['base_a']).json()['id']
    response = client.get(f'/api/training/jobs/{job_id}')
    assert response.status_code == 200
    assert response.json()['id'] == job_id


def test_cross_org_job_detail_403(client, seed):
    job_id = _create_job(client, seed['base_a']).json()['id']
    response = client.get(f'/api/training/jobs/{job_id}', headers={'X-Organization-Id': str(ORG_B)})
    assert response.status_code == 403


def test_cancel_training_job(client, seed, session_factory):
    job_id = _create_job(client, seed['base_a']).json()['id']
    response = client.patch(f'/api/training/jobs/{job_id}', json={'action': 'cancel'})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'Canceled'

    with session_factory() as session:
        assert session.get(TrainingJob, job_id).status == 'Canceled'


def test_cancel_rejects_other_fields(client, seed):
    job_id = _create_job(client, seed['base_a']).json()['id']
    response = client.patch(f'/api/training/jobs/{job_id}', json={'status': 'Running'})
    assert response.status_code == 400


def test_cancel_terminal_job_is_noop(client, seed, session_factory):
    """已完成/已失败的任务不能被 cancel 反向改成 Canceled。"""
    job_id = _create_job(client, seed['base_a']).json()['id']
    with session_factory() as session:
        job = session.get(TrainingJob, job_id)
        job.status = 'Completed'
        session.commit()

    response = client.patch(f'/api/training/jobs/{job_id}', json={'action': 'cancel'})
    assert response.status_code == 200
    assert response.json()['status'] == 'Completed'


def test_null_org_job_matches_legacy_permission(client, seed):
    """null-org 历史任务保持旧 DRF 的 None == None 行为。"""
    payload = {
        'project': PROJECT_GLOBAL,
        'base_model': seed['base_global'],
        'train_subset': 'HasGT',
        'hyperparams': {},
    }
    headers = {'X-Organization-Id': ''}
    response = client.post('/api/training/jobs', json=payload, headers=headers)
    assert response.status_code == 201, response.text
    assert response.json()['id'] > 0

    job_id = response.json()['id']
    assert client.get(f'/api/training/jobs/{job_id}', headers=headers).status_code == 200


def test_jobs_list_project_filter(client, seed):
    job_a = _create_job(client, seed['base_a']).json()['id']
    response = client.get('/api/training/jobs', params={'project': PROJECT_A})
    assert response.status_code == 200
    assert [item['id'] for item in response.json()] == [job_a]


def test_jobs_list_invalid_project_param_404(client, seed):
    response = client.get('/api/training/jobs', params={'project': 'abc'})
    assert response.status_code == 404


def test_jobs_list_project_filter_other_org_403(client, seed):
    response = client.get('/api/training/jobs', params={'project': PROJECT_B})
    assert response.status_code == 403


def test_removed_test_run_routes_404(client):
    assert client.get('/api/training/test-runs/').status_code == 404
    assert client.get('/api/training/test-runs/1/').status_code == 404


def test_jobs_list_pagination(client, seed):
    first = _create_job(client, seed['base_a']).json()['id']
    second = _create_job(client, seed['base_a'], train_subset='All').json()['id']
    response = client.get('/api/training/jobs', params={'limit': 1})
    assert response.status_code == 200
    assert [item['id'] for item in response.json()] == [second]
    response = client.get('/api/training/jobs', params={'limit': 1, 'offset': 1})
    assert [item['id'] for item in response.json()] == [first]


def test_base_models_pagination(client, seed):
    response = client.get('/api/training/base-models', params={'limit': 1})
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_hyperparams_invalid_type_400(client, seed):
    response = _create_job(client, seed['base_a'], hyperparams={'epochs': 'fast'})
    assert response.status_code == 400
    assert 'hyperparams' in response.json()


def test_hyperparams_batch_range_400(client, seed):
    response = _create_job(client, seed['base_a'], hyperparams={'batch': 0})
    assert response.status_code == 400


def test_inactive_base_model_detail_404(client, seed):
    response = client.get(f"/api/training/base-models/{seed['base_inactive']}")
    assert response.status_code == 404


def test_inactive_base_model_create_400(client, seed):
    response = _create_job(client, seed['base_inactive'])
    assert response.status_code == 400


def test_unicode_digit_project_param_404(client, seed):
    response = client.get('/api/training/jobs', params={'project': '\u00b2'})
    assert response.status_code == 404


def test_patch_invalid_action_400(client, seed):
    job_id = _create_job(client, seed['base_a']).json()['id']
    response = client.patch(f'/api/training/jobs/{job_id}', json={'action': 'resume'})
    assert response.status_code == 400


def test_queue_endpoint(client, monkeypatch):
    """队列接口在 Redis 不可用时返回 503（不依赖真实 Redis）。"""
    monkeypatch.setenv('REDIS_HOST', '127.0.0.1')
    monkeypatch.setenv('REDIS_PORT', '1')
    response = client.get('/api/training/queue')
    assert response.status_code == 503
