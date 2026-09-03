# 逐行注释版 —— commit `ada930cea9e72e045e86d1c3744e8e032c280148`

> **用途**：辅助理解该 commit 的代码，**不参与运行、请勿提交**。
> 本目录是原文件的"加注释副本"，代码本体与原文件逐字一致，只是插入了 `#` 注释
> （因此行号与原文件不一致，请以代码内容对照）。

## 1. 这个 commit 做了什么

Sub-Issue 4：为 `training` app 增加 REST API 层（仅 DRF 视图 + 权限 + 序列化器 + 入队占位），
不碰 Celery 任务体 / FastAPI / SSE。

新增端点（前缀 `/api/training/`）：

| 方法 | 路径 | 视图类 | 说明 |
|---|---|---|---|
| GET | `base-models/` | `BaseModelListAPI` | 预置（org 为空）+ 本组织活跃基模 |
| GET | `base-models/<pk>/` | `BaseModelDetailAPI` | 详情，对象级权限，跨组织 403 |
| GET | `base-models/scan/` | `LocalModelsScanAPI` | 扫描 `LOCAL_MODEL_ROOT` 候选基模 |
| GET/POST | `jobs/` | `TrainingJobListAPI` | 列表（`?project=` 过滤）/ 创建（201） |
| GET/PATCH | `jobs/<pk>/` | `TrainingJobDetailAPI` | 详情；PATCH 仅 `action=cancel` |
| GET/POST | `test-runs/` | `TestRunListAPI` | 列表（`?project=` 过滤）/ 创建（二选一） |
| GET | `test-runs/<pk>/` | `TestRunDetailAPI` | 详情 |

### 文件清单（与目录结构对应）

| 注释副本 | 原始文件 | commit 改动 |
|---|---|---|
| `training/api.py` | `training/api.py` | **新增**（176 行，7 个视图） |
| `training/serializers.py` | `training/serializers.py` | **新增**（125 行，3 个序列化器） |
| `training/tasks.py` | `training/tasks.py` | **新增**（28 行，入队 seam） |
| `training/urls.py` | `training/urls.py` | **新增**（19 行，路由） |
| `training/models.py` | `training/models.py` | 改动（3 个 `has_permission` 方法）——为便于理解注释了整文件 |
| `training/tests/factories.py` | `training/tests/factories.py` | **新增**（46 行） |
| `training/tests/test_api.py` | `training/tests/test_api.py` | **新增**（315 行，15 个用例） |
| `label_studio/core/permissions.py` | 同名 | 改动（+3 权限点）——为便于理解注释了整文件 |
| `label_studio/core/urls.py` | 同名 | 改动（+1 行 include）——为便于理解注释了整文件 |
| （见下文 §6） | `.gitignore` | 改动（+`.test_models/`） |

## 2. 一次请求的完整生命周期（以 `POST /api/training/jobs/` 为例）

```
浏览器/客户端
   │  POST /api/training/jobs/  {project, base_model, train_subset, hyperparams}
   ▼
Django URL 路由
   core/urls.py: re_path(r'^', include('training.urls'))     ← 本次 commit 新增的一行
   training/urls.py: path('api/training/', include((...)))   → jobs/ → TrainingJobListAPI
   ▼
DRF APIView 初始化（每个请求新建视图实例）
   ▼
① 认证 authentication_classes（settings 默认）
   TokenAuthenticationPhaseout / SessionAuthentication
   未登录 → request.user = AnonymousUser
   ▼
② 视图级权限 permission_classes（settings 默认，REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES）
   - core.api_permissions.HasObjectPermission
     （只定义了 has_object_permission，视图级恒 True）
   - rest_framework.permissions.IsAuthenticated
     未登录 → NotAuthenticated → 401
   ▼
③ 类属性 permission_required = ViewClassPermission(GET=..., POST=all_permissions.training_create)
   ※ 声明式约定（沿用上游 Label Studio 模式），见 §4 的重要说明
   ▼
④ 泛型视图 dispatch：POST → create()
   - serializer = TrainingJobSerializer(data=request.data)
   - serializer.is_valid(raise_exception=True)
     · base_model=999999 → PrimaryKeyRelatedField 查库失败 → 400
     · TestRun 的 XOR 校验（validate()）→ 400
   ▼
⑤ perform_create(serializer)（本 commit 自定义的组织隔离核心）
   - project.organization != 用户组织 → PermissionDenied → 403
   - base_model.has_permission(user) 为 False → 403
   - serializer.save(organization=用户组织, created_by=user, status=Pending)
     ※ organization/created_by/status 在序列化器里是 read_only，
       客户端无法伪造，只能通过 save 的 kwargs 注入
   ▼
⑥ enqueue_training(job)（seam：写占位 celery_task_id，job 保持 Pending）
   Sub-Issue 6 替换为 run_training.delay(job.id)，视图零改动
   ▼
201 Created + 序列化后的 job（含 celery_task_id）
```

### GET 详情（`GET /api/training/jobs/<pk>/`）的生命周期

```
认证 → 视图级权限（IsAuthenticated）→ RetrieveUpdateAPIView.retrieve()
  → get_object()
      queryset = TrainingJob.objects.all()   ← 注意：未做组织过滤！
      取到对象后 check_object_permissions(request, obj)
        → HasObjectPermission.has_object_permission
          → obj.has_permission(request.user)   ← 模型方法，本次 commit 新增
            跨组织 → False → PermissionDenied → 403
```

**要点**：详情视图靠"未过滤 queryset + 对象级 `has_permission`"产生 403；
列表视图靠"`get_queryset` 直接按组织过滤"产生"看不到"（而不是 403）。两种隔离手段并存。

## 3. 状态码速查

| 状态码 | 触发条件 | 抛出的异常 / 机制 |
|---|---|---|
| 401 | 未登录访问任何端点 | DRF `IsAuthenticated` → `NotAuthenticated` |
| 403 | 跨组织 GET 详情（jobs/test-runs/base-models 的 org 模型） | `HasObjectPermission` → `obj.has_permission` 为 False |
| 403 | 跨组织 POST（project 或 base_model 属于别的组织） | `perform_create` 显式校验 |
| 403 | `?project=<别的组织的项目>` 列表过滤 | `get_queryset` 显式校验 |
| 403 | PATCH 携带非 `action=cancel` 的字段 | `partial_update` 覆盖方法显式拒绝 |
| 404 | `?project=<不存在的 id>` | `generics.get_object_or_404` |
| 404 | `?project=abc`（非数字） | 显式 `raise NotFound`（防止 `pk='abc'` 转换抛 `ValueError` 变 500） |
| 400 | 序列化器校验失败（FK 不存在、XOR 不满足、缺 project） | DRF `ValidationError` |
| 201 | 创建成功（jobs / test-runs） | 泛型视图默认 |
| 200 | 列表 / 详情 / PATCH cancel / scan | 默认 |

## 4. 重要说明：`permission_required` 在本代码库中是"声明式"的

代码里每个视图都写着：

```python
permission_required = ViewClassPermission(GET=all_permissions.training_view, ...)
```

这是**沿用上游 Label Studio 的写法约定**，逐方法记录"该端点应当要求哪个权限点"。
但经过全库检索（`grep -r "permission_required"` 与 `BasePermission`）确认：

1. 本代码库**没有任何 DRF 钩子读取 `view.permission_required`**（上游的 rules 执行链路
   在这个裁剪版里没有保留消费端）；
2. `core/permissions.py` 底部的循环把每个权限点注册进 `rules` 库
   （谓词一律是 `rules.is_authenticated`），但全库**没有任何地方调用 `rules.has_permission`**；
3. 真正生效的拦截是 `core/settings/base.py` 的
   `REST_FRAMEWORK['DEFAULT_PERMISSION_CLASSES'] = [HasObjectPermission, IsAuthenticated]`
   加上各视图手写的组织过滤。

commit message 本身也是这么说的："真实隔离由默认权限类 HasObjectPermission（模型级
has_permission）与各 get_queryset/perform_create 的组织校验共同保证"。

理解时把它当作**自文档化的权限意图声明**即可：`training.view/create/cancel` 三个权限点
目前对"任何已登录用户"都成立（rules 谓词 = `is_authenticated`），未来若要做角色级
细粒度授权（如"只有 org owner 能 cancel"），扩展点就在这个声明 + 注册谓词上。

## 5. 三个模型 `has_permission` 的语义差异

| 模型 | 规则 | 原因 |
|---|---|---|
| `BaseModel` | `organization_id is None or user.active_organization_id == self.organization_id` | `organization` 为 NULL = 服务器预置基模，全员可见（任何组织都能拿来训练/测试） |
| `TrainingJob` | `user.active_organization_id == self.organization_id` | 严格同组织 |
| `TestRun` | `user.active_organization_id == self.organization_id` | 严格同组织 |

注意都使用了 `xxx_id` 形式（Django 把 FK 的 pk 缓存在 `<field>_id` 属性上），
比较时不会触发额外 SQL。

## 6. `.gitignore` 的改动

```diff
 training/tests/__pycache__/
+
+# 本地模型测试临时目录（training/tests/factories.py 运行时生成）
+.test_models/
```

`BaseModelFactory` 运行时在 `<仓库根>/.test_models/` 下建临时模型目录（含占位
`model.pkl`），忽略掉避免 `git status` 污染。顺带修复了文件末尾缺换行符的问题。

## 7. 测试怎么跑（与 commit message 一致，Windows PowerShell）

```powershell
cd label_studio
$env:DJANGO_DB='sqlite'
poetry run pytest -c pytest.ini ../training/tests/test_api.py
```

- `pytest.ini` 提供 `DJANGO_SETTINGS_MODULE=core.settings.label_studio` 与
  `pythonpath=..`（让 `training` 包可被 import）。
- `training/tests/` 不在 `label_studio/` 内，`label_studio/conftest.py` 不会作用于它，
  所以 `test_api.py` 自带了客户端 fixture，且 Django 相关 import 都放在函数/fixture 内。
- 15 个用例覆盖 200 / 201 / 400 / 401 / 403 / 404 全部验收路径。

## 8. Seam（占位接缝）设计

`training/tasks.py` 的 `enqueue_training` / `enqueue_test` 是**有意留的空壳**：

- 现在：生成 `uuid4().hex` 占位 `celery_task_id`，任务保持 `Pending`（没有任何 worker）；
- Sub-Issue 6：`enqueue_training` 内部换成 `run_training.delay(job.id)`；
- Sub-Issue 11：`enqueue_test` 内部换成 `run_test.delay(test_run.id)`；
- Sub-Issue 8：`PATCH action=cancel` 目前只改库里的 status 字段，届时补上
  Celery `revoke`（真正让 worker 停手）。

好处：函数签名与调用点（`api.py` 的 `perform_create`）完全不变，后续替换是
"换内脏不换接口"。
