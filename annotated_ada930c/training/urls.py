# ============================================================================
# 【注释版】对应 commit ada930cea9e72e045e86d1c3744e8e032c280148，仅供理解，请勿提交。
# 路由分两层：
#   1) label_studio/core/urls.py: re_path(r'^', include('training.urls'))
#      （本 commit 新增的一行，把本文件挂到全站路由上）
#   2) 本文件：path('api/training/', include((...), namespace='api'))
#      真正的 URL 前缀 'api/training/' 在这里定义。
# 所以完整路径 = '' + 'api/training/' + 具体 pattern。
# ============================================================================

from django.urls import include, path
# Django 路由基础设施：
# - path：正则无关的字面量路由（内部自动锚定首尾，'jobs/' 只匹配 'jobs/' 本身）；
# - include：挂载子路由表，可带命名空间。

from . import api
# 相对导入本 app 的视图模块（training/api.py）。
# 注意：这里 import 的是模块而不是视图类，pattern 里用 api.XXXAPI.as_view() 惰性引用。

app_name = 'training'
# 应用级命名空间：本 app 下所有 URL name 会被包在 'training:' 前缀里。
# 与最外层 include(..., namespace='api') 叠加后，
# reverse 的完整名字形如 'training:api:job-list'。

_api_urlpatterns = [
    # 端点路由表（先下划线私有命名，表示"先攒起来，最后统一 include"）。
    path('base-models/scan/', api.LocalModelsScanAPI.as_view(), name='base-model-scan'),
    # GET 扫描端点。放在 'base-models/' 之前是"具体路径优先"的习惯写法；
    # 其实即使换序也没歧义：'base-models/<int:pk>/' 的 int 转换器匹配不了 'scan'。
    path('base-models/', api.BaseModelListAPI.as_view(), name='base-model-list'),
    # GET 基模列表。path() 是全匹配：只命中 'base-models/'，不会误吞 'base-models/3/'。
    path('base-models/<int:pk>/', api.BaseModelDetailAPI.as_view(), name='base-model-detail'),
    # GET 基模详情。<int:pk> 是路径转换器：只匹配纯数字，pk 以 str 形式进 kwargs，
    # Django/DRF 的 get_object 再按 pk 查库。
    path('jobs/', api.TrainingJobListAPI.as_view(), name='job-list'),
    # GET 列表 + POST 创建（同一个视图类，DRF 按 HTTP 方法分派）。
    path('jobs/<int:pk>/', api.TrainingJobDetailAPI.as_view(), name='job-detail'),
    # GET 详情 + PATCH 取消命令（RetrieveUpdateAPIView）。
    path('test-runs/', api.TestRunListAPI.as_view(), name='test-run-list'),
    # GET 列表 + POST 创建。
    path('test-runs/<int:pk>/', api.TestRunDetailAPI.as_view(), name='test-run-detail'),
    # GET 详情。
]
# 7 条端点，全部落在 'api/training/' 前缀之下：
#   /api/training/base-models/scan/、/api/training/base-models/、
#   /api/training/base-models/<pk>/、/api/training/jobs/、
#   /api/training/jobs/<pk>/、/api/training/test-runs/、/api/training/test-runs/<pk>/

urlpatterns = [
    path('api/training/', include((_api_urlpatterns, app_name), namespace='api')),
    # include 的三种形态之一：include((子路由表, app_name), namespace='api')
    # → 产生嵌套命名空间 'training:api'。
    # 最终 URL = 'api/training/' + 子 pattern。
]
# urlpatterns 是 Django 约定的"本模块路由表"变量名（core/urls.py include 它时按名寻找）。
# 本 app 没有其他路由（没有管理后台页、没有 HTML 页），全部是 /api/training/ 下的 JSON 端点。
