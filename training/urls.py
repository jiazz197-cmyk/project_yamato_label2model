from django.urls import include, path

from . import api

app_name = 'training'

_api_urlpatterns = [
    path('base-models/scan/', api.LocalModelsScanAPI.as_view(), name='base-model-scan'),
    path('base-models/', api.BaseModelListAPI.as_view(), name='base-model-list'),
    path('base-models/<int:pk>/', api.BaseModelDetailAPI.as_view(), name='base-model-detail'),
    path('jobs/', api.TrainingJobListAPI.as_view(), name='job-list'),
    path('jobs/<int:pk>/', api.TrainingJobDetailAPI.as_view(), name='job-detail'),
    path('test-runs/', api.TestRunListAPI.as_view(), name='test-run-list'),
    path('test-runs/<int:pk>/', api.TestRunDetailAPI.as_view(), name='test-run-detail'),
]

urlpatterns = [
    path('api/training/', include((_api_urlpatterns, app_name), namespace='api')),
]
