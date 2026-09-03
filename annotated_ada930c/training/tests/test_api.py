"""Training REST API 测试（Sub-Issue 4）。

运行方式（Windows，从 label_studio/ 目录）：
    $env:DJANGO_DB='sqlite'
    poetry run pytest -c pytest.ini ../training/tests/test_api.py

注意：training/tests 位于 label_studio 之外（pytest rootdir 之外的 conftest 不生效），
因此本模块自行创建业务客户端 fixture，且所有 Django/DRF import 都放在
fixture / 测试函数内部（conftest 加载时 Django 尚未配置）。
"""

# ============================================================================
# 【注释版】对应 commit ada930cea9e72e045e86d1c3744e8e032c280148，仅供理解，请勿提交。
#
# 测试矩阵（15 个用例）与 commit message 的验收路径对应：
#   200 列表/详情/scan/cancel · 201 创建 job/test-run ·
#   400 序列化校验（FK 不存在 / XOR 不满足）· 401 未登录 ·
#   403 跨组织（详情 / 创建 / 过滤 / 非法 PATCH 字段）· 404 非法 ?project= 参数
#
# 每个用例都带 @pytest.mark.django_db：告诉 pytest-django "这个用例要数据库"，
# 插件会自动为它建测试库并在用例间做事务回滚（隔离）。
# ============================================================================

import pytest
# 顶层只 import pytest 本身——这是"刻意"的：
# 模块导入（收集阶段）时 Django 可能尚未 setup，
# 所有 Django/DRF/模型 import 一律推迟到 fixture / 测试函数体内执行。


@pytest.fixture
def business_client():
    """组织 A 的已登录业务客户端（APIClient + force_authenticate）。"""
    # 作用域默认 function：每个用例独立新建一套用户/组织（配合 django_db 的事务回滚，互不污染）。
    from organizations.models import Organization
    from rest_framework.test import APIClient
    from users.models import User
    # 函数内 import（原因见模块头注释）。

    user = User.objects.create(email='business@pytest.net')
    # 直接 ORM 建用户。本项目 User 以 email 登录（users/models.py: EMAIL_FIELD='email'），
    # 所以不需要 username，email 必填即可。
    user.set_password('pytest')
    # 设置密码哈希。本测试实际用不到真实密码认证（下面 force_authenticate 绕过认证），
    # 这一步只是让账号"完整"，符合生产建用户的常规流程。
    user.save()
    org = Organization.create_organization(created_by=user, title='Business Org')
    # 建组织 A。classmethod 内部走 organizations/functions.py::create_organization：
    # 事务里同时创建 Organization + OrganizationMember（该用户成为组织成员）。
    user.active_organization = org
    # 把用户的"当前组织"指向 A。
    # active_organization 是 User 上的 FK 字段（users/models.py:145），
    # 整个 API 层的所有组织隔离都以它为基准（user.active_organization_id）。
    user.save()
    client = APIClient()
    # DRF 测试客户端：可在进程内直接向 Django 发 HTTP 请求（不经过真实 socket）。
    client.force_authenticate(user=user)
    # force_authenticate：绕过认证类，直接让后续请求的 request.user = 这个用户。
    # 效果等价于"已登录"，但跳过 session/token 校验——所以上面 set_password 形同虚设。
    # 注意：认证被绕过后，IsAuthenticated 权限类看到的就是这个真实 user → 通过。
    client.user = user
    client.organization = org
    # 把 user/org 挂到 client 对象上（DRF APIClient 允许任意属性），
    # 方便测试体里直接 business_client.user / business_client.organization 取值，
    # 不必每次重新查库。
    return client


@pytest.fixture
def other_client():
    """组织 B 的已登录客户端（与 business_client 不同组织）。"""
    # 结构完全同 business_client，只是账号/组织不同——
    # 专门用来构造"跨组织"场景（403 用例的对方）。
    from organizations.models import Organization
    from rest_framework.test import APIClient
    from users.models import User

    user = User.objects.create(email='other@pytest.net')
    # 组织 B 的用户（不同 email = 不同账号）。
    user.set_password('pytest')
    user.save()
    org = Organization.create_organization(created_by=user, title='Other Org')
    # 组织 B。
    user.active_organization = org
    user.save()
    # 当前组织 = B。
    client = APIClient()
    client.force_authenticate(user=user)
    # 已登录身份 = B 用户。
    client.user = user
    client.organization = org
    return client


@pytest.fixture
def project(business_client):
    """组织 A 的项目。"""
    from projects.models import Project
    # 依赖 business_client → 隐含依赖链：该 fixture 被用到时 business_client 先就位。
    return Project.objects.create(
        title='Training Project',
        organization=business_client.organization,
        created_by=business_client.user,
    )
    # 直接在 ORM 层建组织 A 下的项目（不走 API，测试只关心 training 端点）。
    # 注意：Project 自身的创建权限不在本 app 测试范围内，ORM 直建即可。


@pytest.fixture
def base_model(business_client):
    """组织 A 的基模（SKLEARN，真实临时目录）。"""
    from training.tests.factories import BaseModelFactory
    # 工厂见 factories.py 注释版：会真造一个含 model.pkl 的临时目录，
    # 保证 BaseModel.save() 的 is_active=True 校验通过。
    return BaseModelFactory.create(organization=business_client.organization, created_by=business_client.user)
    # create(organization=A, created_by=A用户)：
    # 建一个"组织 A 自有"的活跃 SKLEARN 基模——
    # 注意它是组织模型而非预置模型（organization 非空），
    # 所以正好能触发"跨组织不可见"的隔离路径。


@pytest.mark.django_db
def test_list_base_models(business_client, base_model):
    """GET /api/training/base-models/ → 200 且返回列表（含本组织基模）。"""
    # 需要数据库（建了 user/org/基模）→ django_db 标记。
    response = business_client.get('/api/training/base-models/')
    # 组织 A 用户请求基模列表。
    assert response.status_code == 200
    # 已登录 → 通过 IsAuthenticated；queryset 过滤正常 → 200。
    data = response.json()
    # 解析 JSON 响应体。
    assert isinstance(data, list)
    # ListAPIView 直接返回数组（settings 未开分页，PAGE_SIZE=100 但无 pagination 类）。
    assert any(item['id'] == base_model.id for item in data)
    # 核心断言：刚建的"组织 A 基模"必须出现在列表里
    # （命中 get_queryset 的 Q(organization=user.active_organization) 分支）。


@pytest.mark.django_db
def test_list_base_models_other_org_hidden(business_client, other_client, base_model):
    """组织 B 列表看不到组织 A 的基模（org 过滤生效）。"""
    response = other_client.get('/api/training/base-models/')
    # 换成组织 B 用户请求同一端点。
    assert response.status_code == 200
    # 列表端点对跨组织是 200 + 过滤掉，而不是 403（"看不到" 优于 "拒绝读"）。
    ids = [item['id'] for item in response.json()]
    assert base_model.id not in ids
    # 核心断言：组织 A 的基模 id 不在组织 B 的结果里
    # （get_queryset 的 OR 条件两个分支都不满足 → 被过滤）。


@pytest.mark.django_db
def test_create_training_job(business_client, project, base_model):
    """POST /api/training/jobs → 201、status=Pending、celery_task_id 非空。"""
    response = business_client.post(
        '/api/training/jobs/',
        data={
            'project': project.id,
            # 组织 A 的项目 pk → 通过 perform_create 的组织校验。
            'base_model': base_model.id,
            # 组织 A 自有基模 pk → has_permission(user)=True（同组织）。
            'train_subset': 'HasGT',
            # 合法枚举值（'All'/'HasGT'/'Sample' 之一）。
            'hyperparams': {'max_iter': 100},
            # 超参 dict（JSONField 直接收 dict）。
        },
        format='json',
    )
    # format='json' → APIClient 序列化为 JSON 请求体 + Content-Type: application/json
    # → 由 JSONParser 解析。
    assert response.status_code == 201, response.content
    # 201 Created（ListCreateAPIView 创建成功默认码）。
    # 断言失败时附带 response.content 方便排错。
    data = response.json()
    assert data['status'] == 'Pending'
    # perform_create 注入的初始状态确实落库并回显。
    assert data['celery_task_id']
    # enqueue_training seam 写入了占位任务 id（32 位 hex，非空即真值）。
    # 这证明"创建即入队（占位）"的链路通了。


@pytest.mark.django_db
def test_create_test_run_with_base_model(business_client, project, base_model):
    """POST /api/training/test-runs（base_model_id 零样本）→ 201。"""
    response = business_client.post(
        '/api/training/test-runs/',
        data={
            'project': project.id,
            'base_model_id': base_model.id,
            # 注意字段名是 base_model_id（序列化器 write_only 输入名），
            # source='base_model' 把解析结果映射到模型 FK。
            'test_subset': 'Sample',
        },
        format='json',
    )
    assert response.status_code == 201, response.content
    # XOR 满足（只给了 base_model_id）→ 校验通过 → 201。
    data = response.json()
    assert data['status'] == 'Pending'
    assert data['celery_task_id']
    # enqueue_test seam 同样写入了占位 id。


@pytest.mark.django_db
def test_create_test_run_with_training_job(business_client, project, base_model):
    """POST /api/training/test-runs（training_job_id 训练产物测试）→ 201。"""
    from training.models import TrainingJob
    # 函数内 import。
    job = TrainingJob.objects.create(
        base_model=base_model,
        project=project,
        organization=business_client.organization,
        created_by=business_client.user,
    )
    # ORM 直建一个组织 A 的训练任务（默认 status=Pending）作为"被测试的产物"。
    # 直建绕过了 API，所以 organization 等字段手动填齐。
    response = business_client.post(
        '/api/training/test-runs/',
        data={
            'project': project.id,
            'training_job_id': job.id,
            # 只给 training_job_id（XOR 的另一分支）。
            'test_subset': 'All',
        },
        format='json',
    )
    assert response.status_code == 201, response.content
    # perform_create 里 target = training_job（base_model 为 None，or 选中它），
    # target.has_permission(user)=True（同组织）→ 201。


@pytest.mark.django_db
def test_unauthenticated_post_401(business_client, project, base_model):
    """未登录 POST → 401（DRF NotAuthenticated）。"""
    from rest_framework.test import APIClient
    anon = APIClient()
    # 不 force_authenticate 的裸客户端 = 匿名请求（request.user=AnonymousUser）。
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
    # 断言要点：未登录是 401 而不是 403——
    # DRF 的 IsAuthenticated 对匿名用户抛 NotAuthenticated（401，带 WWW-Authenticate 头），
    # 403 留给"已登录但无权"。commit message 特别纠正了父计划里"未登录 403"的宽松说法。
    # （business_client/project/base_model 三个 fixture 只用来准备数据，匿名客户端本身不用它们。）


@pytest.mark.django_db
def test_invalid_base_model_400(business_client, project):
    """base_model 不存在 → 400。"""
    response = business_client.post(
        '/api/training/jobs/',
        data={
            'project': project.id,
            'base_model': 999999,
            # 不存在的基模 pk。
            'train_subset': 'HasGT',
        },
        format='json',
    )
    assert response.status_code == 400
    # 拦截点在序列化器：PrimaryKeyRelatedField 用 queryset 查 999999 查不到
    # → ValidationError → 400（还没走到 perform_create 的组织校验）。
    # 注意不是 404：DRF 对"写端点引用了不存在的对象"的约定是 400（入参非法），
    # 404 留给"读端点按 pk 找对象"（如 ?project=999999）。


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
    # 组织 A 的训练任务。
    response = other_client.get(f'/api/training/jobs/{job.id}/')
    # 组织 B 用户直接按 pk 请求详情。
    assert response.status_code == 403
    # 拦截链路：queryset=objects.all() 取到对象 →
    # check_object_permissions → HasObjectPermission.has_object_permission
    # → job.has_permission(B用户)：B组织id != A组织id → False → PermissionDenied(403)。
    # 这是本次 commit 新增 has_permission 的核心验收用例。
    # 注意：跨组织详情是 403 而非 404（对象"存在但无权读"）。


@pytest.mark.django_db
def test_cross_org_post_job_403(business_client, other_client, project, base_model):
    """组织 B POST 使用组织 A 的 project → 403。"""
    response = other_client.post(
        '/api/training/jobs/',
        data={
            'project': project.id,
            # project 属于组织 A。
            'base_model': base_model.id,
            # base_model 也属于组织 A（顺带验证：即使 project 校验过了，
            # base_model.has_permission 这关也拦得住）。
            'train_subset': 'HasGT',
        },
        format='json',
    )
    assert response.status_code == 403
    # 拦截点在 perform_create 第一关：project.organization(A) != B用户组织 → 403。
    # 消息是 'Project not found.'（故意模糊，不泄露项目存在）。


@pytest.mark.django_db
def test_test_run_xor_validation(business_client, project, base_model):
    """base_model_id 与 training_job_id 同给或都不给 → 400。"""
    # 都不给
    response = business_client.post(
        '/api/training/test-runs/',
        data={'project': project.id, 'test_subset': 'HasGT'},
        # 两个 write_only 字段都没传（required=False，单看字段不报错）。
        format='json',
    )
    assert response.status_code == 400
    # 拦截点在 TestRunSerializer.validate()：(None is None) == (None is None) → True → 400。

    # 都给
    from training.models import TrainingJob
    job = TrainingJob.objects.create(
        base_model=base_model,
        project=project,
        organization=business_client.organization,
        created_by=business_client.user,
    )
    response = business_client.post(
        '/api/training/test-runs/',
        data={
            'project': project.id,
            'base_model_id': base_model.id,
            'training_job_id': job.id,
            # 两个都传（都是合法存在的 pk——字段级校验都过，XOR 不过）。
            'test_subset': 'HasGT',
        },
        format='json',
    )
    assert response.status_code == 400
    # (False) == (False) → True → 400。
    # 两个断言合起来把 XOR 的两种非法形态都覆盖了（合法形态见前两个 test-run 用例）。


@pytest.mark.django_db
def test_cancel_training_job(business_client, project, base_model):
    """PATCH action=cancel → 200 且 status=Canceled（Sub-Issue 4 cancel seam）。"""
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
    # 先正常创建一个任务（201，status=Pending）。
    job_id = response.json()['id']
    response = business_client.patch(
        f'/api/training/jobs/{job_id}/',
        data={'action': 'cancel'},
        format='json',
    )
    # PATCH 命令通道：{"action": "cancel"}。
    # 流程：get_object（同组织 → 对象级权限通过）→ action=='cancel' →
    # job.status=CANCELED → save(update_fields=['status']) → 200 + 序列化结果。
    assert response.status_code == 200, response.content
    assert response.json()['status'] == 'Canceled'
    # 响应体回显新状态。
    assert TrainingJob.objects.get(pk=job_id).status == TrainingJob.Status.CANCELED
    # 再查库确认状态真的落库了（不只看响应）。


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
        # 试图直接改状态字段（绕过 cancel 命令通道）。
        format='json',
    )
    assert response.status_code == 403
    # partial_update 里 request.data.get('action') → None ≠ 'cancel' → 403。
    # 设计意图：status 是服务端状态机字段，API 不开放任意字段更新，
    # 只开放"取消"这一个命令（将来 Sub-Issue 8 补 revoke 语义）。


@pytest.mark.django_db
def test_jobs_list_invalid_project_param_404(business_client):
    """GET jobs?project=<非数字> → 404（避免 pk 转换抛 ValueError 变 500）。"""
    response = business_client.get('/api/training/jobs/?project=abc')
    # 非数字过滤参数。
    assert response.status_code == 404
    # get_queryset 里 str(project_pk).isdigit() 为 False → 显式 raise NotFound → 404。
    # 若不拦截，'abc' 进 ORM pk 过滤会抛 ValueError → 500。这是"防御坏参数"的验收。


@pytest.mark.django_db
def test_jobs_list_project_filter_other_org_403(business_client, other_client, project):
    """组织 B GET jobs?project=<组织 A 项目> → 403。"""
    response = other_client.get(f'/api/training/jobs/?project={project.id}')
    # 组织 B 用户用组织 A 的项目 id 过滤。
    assert response.status_code == 403
    # get_queryset：项目存在（过 get_object_or_404）→
    # project.organization(A) != B用户组织 → PermissionDenied → 403。
    # 与列表"跨组织任务看不到"（200+过滤）不同：
    # 显式拿别人的 project 名来过滤是"主动探测"，直接 403。


@pytest.mark.django_db
def test_scan_local_models(business_client):
    """GET /api/training/base-models/scan/ → 200（返回 LOCAL_MODEL_ROOT 扫描结果列表）。"""
    response = business_client.get('/api/training/base-models/scan/')
    # 已登录用户请求扫描端点（纯文件系统探测，与组织数据无关）。
    assert response.status_code == 200, response.content
    assert isinstance(response.json(), list)
    # scan_local_models 恒返回 list（根目录不存在 → 空列表），所以永远 200 + 数组。
    # 用例只验证端点通路与返回形状；扫描内容细节由 utils 的专项单测（Sub-Issue 3）覆盖。
