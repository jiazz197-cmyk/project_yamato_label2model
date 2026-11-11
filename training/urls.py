from django.urls import include, path

from . import api

app_name = 'training'

_api_urlpatterns = [
    path('base-models/scan/', api.LocalModelsScanAPI.as_view(), name='base-model-scan'),
    path('base-models/', api.BaseModelListAPI.as_view(), name='base-model-list'),
    path('base-models/<int:pk>/', api.BaseModelDetailAPI.as_view(), name='base-model-detail'),
    path('jobs/', api.TrainingJobListAPI.as_view(), name='job-list'),
    path('jobs/<int:pk>/', api.TrainingJobDetailAPI.as_view(), name='job-detail'),
]

urlpatterns = [
    path('api/training/', include((_api_urlpatterns, app_name), namespace='api')),
]
