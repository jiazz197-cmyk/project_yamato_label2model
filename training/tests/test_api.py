"""Training REST API 测试（YOLO-only 收敛后）。

运行方式（从 label_studio/ 目录，仓库根同一 pytest.ini）：
    $env:DJANGO_DB='sqlite'
    poetry run pytest -c pytest.ini ../training/tests/test_api.py

注意：training/tests 位于 label_studio 之外（pytest rootdir 之外的 conftest 不生效），
因此本模块自行创建业务客户端 fixture，且所有 Django/DRF import 都放在
fixture / 测试函数内部（conftest 加载时 Django 尚未配置）。
"""

import pytest


@pytest.fixture
def business_client():
    """组织 A 的已登录业务客户端（APIClient + force_authenticate）。"""
    from organizations.models import Organization
    from rest_framework.test import APIClient
    from users.models import User

    user = User.objects.create(email='business@pytest.net')
    user.set_password('pytest')
    user.save()
    org = Organization.create_organization(created_by=user, title='Business Org')
    user.active_organization = org
    user.save()
    client = APIClient()
    client.force_authenticate(user=user)
    client.user = user
    client.organization = org
    return client


@pytest.fixture
def other_client():
    """组织 B 的已登录客户端（与 business_client 不同组织）。"""
    from organizations.models import Organization
    from rest_framework.test import APIClient
    from users.models import User

    user = User.objects.create(email='other@pytest.net')
    user.set_password('pytest')
    user.save()
    org = Organization.create_organization(created_by=user, title='Other Org')
    user.active_organization = org
    user.save()
    client = APIClient()
    client.force_authenticate(user=user)
    client.user = user
    client.organization = org
    return client


@pytest.fixture
def project(business_client):
    """组织 A 的项目。"""
    from projects.models import Project

    return Project.objects.create(
        title='Training Project',
        organization=business_client.organization,
        created_by=business_client.user,
    )


@pytest.fixture
def base_model(business_client):
    """组织 A 的 YOLO 基模（真实临时目录 + 占位 .pt）。"""
    from training.tests.factories import BaseModelFactory

    return BaseModelFactory.create(organization=business_client.organization, created_by=business_client.user)


@pytest.mark.django_db
def test_list_base_models(business_client, base_model):
    """GET /api/training/base-models/ → 200 且返回列表（含本组织基模）。"""
    response = business_client.get('/api/training/base-models/')
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert any(item['id'] == base_model.id for item in data)


@pytest.mark.django_db
def test_list_base_models_other_org_hidden(business_client, other_client, base_model):
    """组织 B 列表看不到组织 A 的基模（org 过滤生效）。"""
    response = other_client.get('/api/training/base-models/')
    assert response.status_code == 200
    ids = [item['id'] for item in response.json()]
    assert base_model.id not in ids


@pytest.mark.django_db
def test_cross_org_base_model_detail_403(business_client, other_client, base_model):
    """组织 B GET 组织 A 的 base-models/<pk>/ → 403（对象级权限）。"""
    response = other_client.get(f'/api/training/base-models/{base_model.id}/')
    assert response.status_code == 403


@pytest.mark.django_db
def test_create_training_job(business_client, project, base_model):
    """POST /api/training/jobs → 201、status=Pending、不再返回 celery 字段。"""
    response = business_client.post(
        '/api/training/jobs/',
        data={
            'project': project.id,
            'base_model': base_model.id,
            'train_subset': 'HasGT',
            'hyperparams': {'epochs': 10},
        },
        format='json',
    )
    assert response.status_code == 201, response.content
    data = response.json()
    assert data['status'] == 'Pending'
    assert 'celery_task_id' not in data
    assert data['artifact_path'] in (None, '')
    assert data['metrics'] == {}


@pytest.mark.django_db
def test_unauthenticated_post_401(business_client, project, base_model):
    """未登录 POST → 401（DRF 默认 IsAuthenticated）。"""
    from rest_framework.test import APIClient

    anon = APIClient()
    response = anon.post(
        '/api/training/jobs/',
        data={
            'project': project.id,
            'base_model': base_model.id,
            'train_subset': 'HasGT',
        },
        format='json',
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_invalid_base_model_400(business_client, project):
    """base_model 不存在 → 400。"""
    response = business_client.post(
        '/api/training/jobs/',
        data={
            'project': project.id,
            'base_model': 999999,
            'train_subset': 'HasGT',
        },
        format='json',
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_cross_org_job_detail_403(business_client, other_client, project, base_model):
    """组织 B GET 组织 A 的 jobs/<pk>/ → 403。"""
    from training.models import TrainingJob

    job = TrainingJob.objects.create(
        base_model=base_model,
        project=project,
        organization=business_client.organization,
        created_by=business_client.user,
    )
    response = other_client.get(f'/api/training/jobs/{job.id}/')
    assert response.status_code == 403


@pytest.mark.django_db
def test_cross_org_post_job_403(business_client, other_client, project, base_model):
    """组织 B POST 使用组织 A 的 project → 403。"""
    response = other_client.post(
        '/api/training/jobs/',
        data={
            'project': project.id,
            'base_model': base_model.id,
            'train_subset': 'HasGT',
        },
        format='json',
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_cross_org_base_model_in_job_403(business_client, other_client, project):
    """组织 A POST 使用组织 B 的 base_model → 403。"""
    from training.tests.factories import BaseModelFactory

    other_base_model = BaseModelFactory.create(
        organization=other_client.organization, created_by=other_client.user
    )
    response = business_client.post(
        '/api/training/jobs/',
        data={
            'project': project.id,
            'base_model': other_base_model.id,
            'train_subset': 'HasGT',
        },
        format='json',
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_cancel_training_job(business_client, project, base_model):
    """PATCH action=cancel → 200 且 status=Canceled。"""
    from training.models import TrainingJob

    response = business_client.post(
        '/api/training/jobs/',
        data={
            'project': project.id,
            'base_model': base_model.id,
            'train_subset': 'HasGT',
        },
        format='json',
    )
    job_id = response.json()['id']
    response = business_client.patch(
        f'/api/training/jobs/{job_id}/',
        data={'action': 'cancel'},
        format='json',
    )
    assert response.status_code == 200, response.content
    assert response.json()['status'] == 'Canceled'
    assert TrainingJob.objects.get(pk=job_id).status == TrainingJob.Status.CANCELED


@pytest.mark.django_db
def test_cancel_reject_other_fields(business_client, project, base_model):
    """PATCH 非 action=cancel 字段 → 403。"""
    response = business_client.post(
        '/api/training/jobs/',
        data={
            'project': project.id,
            'base_model': base_model.id,
            'train_subset': 'HasGT',
        },
        format='json',
    )
    job_id = response.json()['id']
    response = business_client.patch(
        f'/api/training/jobs/{job_id}/',
        data={'status': 'Running'},
        format='json',
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_jobs_list_invalid_project_param_404(business_client):
    """GET jobs?project=<非数字> → 404（避免 pk 转换抛 ValueError 变 500）。"""
    response = business_client.get('/api/training/jobs/?project=abc')
    assert response.status_code == 404


@pytest.mark.django_db
def test_jobs_list_project_filter_other_org_403(business_client, other_client, project):
    """组织 B GET jobs?project=<组织 A 项目> → 403。"""
    response = other_client.get(f'/api/training/jobs/?project={project.id}')
    assert response.status_code == 403


@pytest.mark.django_db
def test_scan_local_models(business_client):
    """GET /api/training/base-models/scan/ → 200（返回 LOCAL_MODEL_ROOT 扫描结果列表）。"""
    response = business_client.get('/api/training/base-models/scan/')
    assert response.status_code == 200, response.content
    assert isinstance(response.json(), list)


@pytest.mark.django_db
def test_test_run_endpoints_removed(business_client):
    """TestRun 清理后，test-runs 路由不再存在 → 404。"""
    assert business_client.get('/api/training/test-runs/').status_code == 404
    assert business_client.get('/api/training/test-runs/1/').status_code == 404


def test_no_training_permission_points():
    """core.permissions 中不再新增 training.* 权限点。"""
    from core.permissions import AllPermissions

    names = {name for name, _ in AllPermissions()}
    assert not any(name.startswith('training_') for name in names)
