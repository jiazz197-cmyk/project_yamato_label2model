"""Django ``/api/training/`` 网关测试：鉴权、内部上下文头、状态码映射、降级。

训练域已在 services/ml_api；这里只验证 Django 作为鉴权网关的转发行为，
用 ``responses`` 拦截对 ml-api 的 HTTP 调用，不依赖真实侧车。
"""

import json

import pytest
import responses
from requests.exceptions import ConnectionError as RequestsConnectionError

ML_API = 'http://ml-api-test:8991'


@pytest.fixture(autouse=True)
def ml_api_env(monkeypatch):
    """固定 ml-api 地址与内部令牌。"""
    monkeypatch.setenv('ML_API_URL', ML_API)
    monkeypatch.setenv('ML_API_INTERNAL_TOKEN', 'test-token')


@pytest.mark.django_db
@responses.activate
def test_requires_authentication(client):
    """未登录请求在 Django 层被拒绝，且不会打到 ml-api。"""
    response = client.get('/api/training/base-models/')
    assert response.status_code in (401, 403)
    assert len(responses.calls) == 0


@pytest.mark.django_db
@responses.activate
def test_forwards_context_headers(business_client):
    responses.add(responses.GET, f'{ML_API}/api/training/base-models', json=[], status=200)

    response = business_client.get('/api/training/base-models/')

    assert response.status_code == 200
    request = responses.calls[0].request
    assert request.headers['X-Internal-Token'] == 'test-token'
    assert request.headers['X-User-Id'] == str(business_client.user.pk)

    business_client.user.refresh_from_db()
    expected_org = str(business_client.user.active_organization_id or '')
    assert request.headers['X-Organization-Id'] == expected_org
    assert expected_org == str(business_client.organization.pk)


@pytest.mark.django_db
@responses.activate
def test_form_hyperparams_is_parsed_to_json(business_client):
    """旧 form 客户端的 hyperparams 是 JSON 字符串，网关要转成对象。"""
    responses.add(
        responses.POST,
        f'{ML_API}/api/training/jobs',
        json={'id': 1, 'status': 'Pending'},
        status=201,
    )

    response = business_client.post(
        '/api/training/jobs/',
        data={'project': '1', 'base_model': '2', 'train_subset': 'HasGT', 'hyperparams': '{"epochs": 5}'},
    )

    assert response.status_code == 201
    body = json.loads(responses.calls[0].request.body)
    assert body['hyperparams'] == {'epochs': 5}


@pytest.mark.django_db
@responses.activate
def test_post_forwards_json_body(business_client):
    responses.add(
        responses.POST,
        f'{ML_API}/api/training/jobs',
        json={'id': 1, 'status': 'Pending'},
        status=201,
    )
    payload = {'project': 1, 'base_model': 2, 'train_subset': 'HasGT', 'hyperparams': {'epochs': 5}}

    response = business_client.post(
        '/api/training/jobs/',
        data=json.dumps(payload),
        content_type='application/json',
    )

    assert response.status_code == 201
    assert json.loads(responses.calls[0].request.body) == payload


@pytest.mark.django_db
@responses.activate
def test_fastapi_validation_mapped_to_400(business_client):
    """FastAPI 422（请求体校验失败）映射为原 DRF 的 400。"""
    responses.add(
        responses.POST,
        f'{ML_API}/api/training/jobs',
        json={'detail': [{'loc': ['body', 'project'], 'msg': 'Field required'}]},
        status=422,
    )

    response = business_client.post('/api/training/jobs/', data={}, content_type='application/json')

    assert response.status_code == 400


@pytest.mark.django_db
@responses.activate
def test_upstream_403_passthrough(business_client):
    responses.add(
        responses.GET,
        f'{ML_API}/api/training/base-models/99',
        json={'detail': 'Base model not found.'},
        status=403,
    )

    response = business_client.get('/api/training/base-models/99/')

    assert response.status_code == 403
    assert response.json()['detail'] == 'Base model not found.'


@pytest.mark.django_db
@responses.activate
def test_project_query_forwarded(business_client):
    responses.add(responses.GET, f'{ML_API}/api/training/jobs', json=[], status=200)

    response = business_client.get('/api/training/jobs/?project=7')

    assert response.status_code == 200
    assert 'project=7' in responses.calls[0].request.url


@pytest.mark.django_db
@responses.activate
def test_internal_401_mapped_to_502(business_client):
    """内部令牌失败不能以 401 返回，否则前端会误以为用户登录失效。"""
    responses.add(
        responses.GET,
        f'{ML_API}/api/training/base-models',
        json={'detail': 'missing token'},
        status=401,
    )

    response = business_client.get('/api/training/base-models/')
    assert response.status_code == 502
    assert 'ML_API_INTERNAL_TOKEN' in response.json()['detail']


@pytest.mark.django_db
@responses.activate
def test_pagination_params_forwarded(business_client):
    responses.add(responses.GET, f'{ML_API}/api/training/jobs', json=[], status=200)

    response = business_client.get('/api/training/jobs/?limit=10&offset=20')

    assert response.status_code == 200
    query = responses.calls[0].request.url
    assert 'limit=10' in query
    assert 'offset=20' in query


@pytest.mark.django_db
@responses.activate
def test_patch_cancel_forwarded(business_client):
    responses.add(
        responses.PATCH,
        f'{ML_API}/api/training/jobs/3',
        json={'id': 3, 'status': 'Canceled'},
        status=200,
    )

    response = business_client.patch(
        '/api/training/jobs/3/',
        data=json.dumps({'action': 'cancel'}),
        content_type='application/json',
    )

    assert response.status_code == 200
    assert response.json()['status'] == 'Canceled'


@pytest.mark.django_db
@responses.activate
def test_ml_api_unavailable_returns_503(business_client):
    responses.add(
        responses.GET,
        f'{ML_API}/api/training/base-models',
        body=RequestsConnectionError('ml-api down'),
    )

    response = business_client.get('/api/training/base-models/')

    assert response.status_code == 503
    assert 'ml-api' in response.json()['detail']
