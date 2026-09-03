"""This file and its contents are licensed under the Apache License 2.0. Please see the included NOTICE for copyright information and LICENSE for a copy of the license.

URL Configurations

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

# ============================================================================
# 【注释版】对应 commit ada930cea9e72e045e86d1c3744e8e032c280148，仅供理解，请勿提交。
# 本 commit 对该文件的改动只有一行（★ 处）：include('training.urls')。
# 为便于理解，整文件都做了注释。
# ============================================================================

from core import views
# 下方路由到的 core/views.py 里的视图函数（main / health / 版本页 / 静态伺服等）。
from core.utils.static_serve import serve
# 静态文件伺服视图（serve 静态资源目录）。
from django.conf import settings
# 全局 settings：下面取 EDITOR_ROOT / DM_ROOT / REACT_APP_ROOT / STATIC_ROOT。
# （这些前端根路径在 core/settings/base.py 里用相对路径 ../../web/dist/... 硬编码，
#   所以 label_studio/ 与 web/ 必须保持同级——见 AGENTS.md 目录结构约束。）
from django.conf.urls import include
# include()：挂载子 URLconf（django.conf.urls 版本，与 django.urls.include 行为一致）。
from django.contrib import admin
# Django 自带 admin（下方挂载到 /admin/）。
from django.http import HttpResponseRedirect
# 302 重定向响应：旧 swagger 地址 / docs 兼容入口的重定向目标。
from django.urls import path, re_path
# path：字面量路由；re_path：正则路由。本文件两种都用了。
from django.views.generic.base import RedirectView
# 类视图形式的重定向（favicon、/docs/ 用）。
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularJSONAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
    SpectacularYAMLAPIView,
)
# drf-spectacular 的 OpenAPI 文档视图（下方 docs/api 一节挂载）。

urlpatterns = [
    # Django 约定的主路由表：自上而下按顺序匹配，先命中先生效。
    re_path(r'^$', views.main, name='main'),
    # 根路径 '/' → main()：已登录 → 业务首页/项目列表；未登录 → 登录页（见 core/views.py）。
    re_path(r'^sw\.js$', views.static_file_with_host_resolver('js/sw.js', content_type='text/javascript')),
    # Service Worker 注册脚本（内容里的 {{HOSTNAME}} 会被替换成 settings.HOSTNAME）。
    re_path(
        r'^sw-fallback\.js$',
        views.static_file_with_host_resolver('js/sw-fallback.js', content_type='text/javascript'),
    ),
    # SW 的离线兜底脚本，同上。
    re_path(r'^favicon\.ico$', RedirectView.as_view(url='/static/images/favicon.ico', permanent=True)),
    # 站点图标 → 301 永久重定向到静态文件（permanent=True = 301）。
    re_path(
        r'^label-studio-frontend/(?P<path>.*)$',
        serve,
        kwargs={'document_root': settings.EDITOR_ROOT, 'show_indexes': True},
    ),
    # 标注编辑器前端（React 构建产物）的静态伺服：/label-studio-frontend/<任意路径>。
    re_path(r'^dm/(?P<path>.*)$', serve, kwargs={'document_root': settings.DM_ROOT, 'show_indexes': True}),
    # 数据管理器前端（Data Manager）静态伺服。
    re_path(
        r'^react-app/(?P<path>.*)$',
        serve,
        kwargs={
            'document_root': settings.REACT_APP_ROOT,
            'show_indexes': True,
            'manifest_asset_prefix': 'react-app',
        },
    ),
    # 新 React 应用（组织/用户等新前端）静态伺服；manifest_asset_prefix 用于
    # 从 webpack manifest 解析带 content hash 的真实文件名。
    re_path(r'^static/(?P<path>.*)$', serve, kwargs={'document_root': settings.STATIC_ROOT, 'show_indexes': True}),
    # collectstatic 收集后的静态文件伺服（CSS/图片/JS 等）。
    re_path(r'^', include('organizations.urls')),
    # ★ 以下一大片 re_path(r'^', include(...)) 是各业务 app 的 API 路由挂载点。
    # r'^' 前缀 = "从请求路径开头开始尝试匹配子路由表"，
    # 各 app 的真实前缀（如 'api/projects/'、'api/training/'）定义在各自的 urls.py 里。
    # 顺序敏感：Django 自上而下逐个尝试，直到某个子路由表命中。
    re_path(r'^', include('projects.urls')),
    re_path(r'^', include('data_import.urls')),
    re_path(r'^', include('data_manager.urls')),
    re_path(r'^', include('data_export.urls')),
    re_path(r'^', include('users.urls')),
    re_path(r'^', include('tasks.urls')),
    re_path(r'^', include('io_storages.urls')),
    re_path(r'^', include('ml.urls')),
    re_path(r'^', include('training.urls')),
    # ★★★ 本次 commit 新增的一行：挂载 training app 的路由。
    # training/urls.py 内部再挂 'api/training/' 前缀，
    # 所以 training 端点最终是 /api/training/base-models/ 等（见该文件注释版）。
    # 位置放在 ml 与 webhooks 之间：这些 app 的前缀互不重叠，放哪都能命中，
    # 这里只是按"业务 app 分组"的惯例顺序插入。
    re_path(r'^', include('webhooks.urls')),
    re_path(r'^', include('labels_manager.urls')),
    re_path(r'^', include('fsm.urls')),
    # 状态机历史 app（为 Project/Task/Annotation 等提供 FSM 审计表，不可删——见 AGENTS.md）。
    re_path(r'version/', views.version_page, name='version'),  # html page
    # /version/ → 版本信息 HTML 页（superuser 额外带 settings 全量输出）。
    re_path(r'api/version/', views.version_page, name='api-version'),  # json response
    # /api/version/ → 同一个视图，JSON 响应（前端轮询版本用）。
    re_path(r'health/', views.health, name='health'),
    # 健康检查：恒 200 + {"status": "UP"}（容器/探针用）。
    re_path(r'metrics/', views.metrics, name='metrics'),
    # 指标占位端点：恒返回空响应。
    re_path(r'trigger500/', views.TriggerAPIError.as_view(), name='metrics'),
    # 故意抛异常的端点（测试异常页/告警链路用；name 与上一行重名，上游原样保留）。
    re_path(r'samples/time-series.csv', views.samples_time_series, name='static_time_series'),
    # 示例数据：生成时间序列 CSV（前端示例项目用）。
    re_path(r'samples/paragraphs.json', views.samples_paragraphs, name='samples_paragraphs'),
    # 示例数据：段落 JSON（前端示例项目用）。
    # Legacy swagger URLs redirect to new drf-spectacular URLs
    # 旧 swagger 地址 → 新 OpenAPI 文档地址（302 重定向，保持老集成不断链）：
    re_path(r'^swagger\.json$', lambda request: HttpResponseRedirect('/docs/api/schema/json/'), name='schema-json'),
    re_path(r'^swagger\.yaml$', lambda request: HttpResponseRedirect('/docs/api/schema/yaml/'), name='schema-yaml'),
    re_path(
        r'^swagger/$', lambda request: HttpResponseRedirect('/docs/api/schema/swagger-ui/'), name='schema-swagger-ui'
    ),
    # Again for legacy reasons, docs/api?format=openapi redirects to docs/api/schema/json/
    # 兼容入口 /docs/api/：带 ?format=openapi 时 302 到 json schema，
    # 否则 302 到 redoc 文档页（见下方 docs/api/schema/ 各端点）。
    path(
        'docs/api/',
        lambda request: (
            HttpResponseRedirect('/docs/api/schema/json/')
            if request.GET.get('format') == 'openapi'
            else HttpResponseRedirect('/docs/api/schema/redoc/')
        ),
        name='docs-api',
    ),
    path(
        'docs/',
        RedirectView.as_view(url='/static/docs/public/guide/introduction.html', permanent=False),
        name='docs-redirect',
    ),
    # /docs/ → 302 到静态托管的用户指南首页（permanent=False = 302 临时重定向）。
    path('admin/', admin.site.urls),
    # Django admin 后台。
    path('django-rq/', include('django_rq.urls')),
    # django-rq 的 RQ 任务队列管理界面（/django-rq/ 看板；
    # 本项目已迁移 Celery，此路由保留但队列未使用）。
    path('feature-flags/', views.feature_flags, name='feature_flags'),
    # 功能开关（feature flags）调试页：未登录 403，登录用户返回 flags + 系统信息。
    path('heidi-tips/', views.heidi_tips, name='heidi_tips'),
    # 拉取上游 GitHub 上的 HeidiTips 文案（带 5s 超时，失败降级为 404）。
    path('__lsa/', views.collect_metrics, name='collect_metrics'),
    # 前端遥测上报端点（恒 204，仅 COLLECT_ANALYTICS 时前端才调用）。
    re_path(r'^api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    # DRF 自带的 /api-auth/ 登录/登出/密码重置表单路由。
    re_path(r'^', include('jwt_auth.urls')),
    # JWT 认证相关路由（token 颁发/验证等，见 jwt_auth app）。
    re_path(r'^', include('session_policy.urls')),
    # 会话策略路由（如组织切换 / 会话过期处理）。
    path('docs/api/schema/', SpectacularAPIView.as_view(), name='schema'),
    # OpenAPI 3 schema（默认 YAML 输出）主端点，下面各 UI 视图都 url_name 指回它。
    path('docs/api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    # Swagger UI 交互文档页。
    path('docs/api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    # ReDoc 风格文档页。
    path('docs/api/schema/json/', SpectacularJSONAPIView.as_view(), name='schema-json'),
    # OpenAPI 3 JSON 版（上方 swagger 重定向的落点）。
    path('docs/api/schema/yaml/', SpectacularYAMLAPIView.as_view(), name='schema-yaml'),
    # OpenAPI 3 YAML 版。
]
# 全表结束。请求处理顺序：
#   中间件链（认证/CSRF/JWT 等，见 settings MIDDLEWARE）→ 本路由表 → 视图。
# API 请求（/api/...）进入 DRF 视图后还要再走一遍
# 认证 → permission_classes（IsAuthenticated / HasObjectPermission）→ 视图方法。

if settings.DEBUG:
    # 仅 DEBUG 模式：尝试挂载 Django Debug Toolbar（/__debug__/ 面板）。
    try:
        import debug_toolbar
        # 函数内 import：未安装该包时不会让 urls 模块整体报错。
        urlpatterns = [path('__debug__/', include(debug_toolbar.urls))] + urlpatterns
        # 把 debug toolbar 路由插到表头（优先匹配）。
    except ImportError:
        # 生产环境通常没装 debug_toolbar → 安静跳过。
        pass
