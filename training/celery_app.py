"""Celery 应用（训练/测试异步任务）。

独立入口：`celery -A training.celery_app worker ...`
先引导 Django（补 label_studio/ 路径 + DJANGO_SETTINGS_MODULE），
broker/result backend 复用 core/settings/label_studio.py 的
CELERY_BROKER_URL（即 .env 中与 RQ 相同的 Redis）。
"""

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LABEL_STUDIO_DIR = os.path.join(_PROJECT_ROOT, 'label_studio')
if _LABEL_STUDIO_DIR not in sys.path:
    sys.path.insert(0, _LABEL_STUDIO_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.label_studio')

import django  # noqa: E402

django.setup()  # 幂等：Django 进程内重复调用安全

from celery import Celery  # noqa: E402
from django.conf import settings  # noqa: E402
from kombu import Queue  # noqa: E402

_DEFAULT_BROKER = 'redis://localhost:6379/0'

app = Celery(
    'label_studio_training',
    broker=getattr(settings, 'CELERY_BROKER_URL', _DEFAULT_BROKER),
    backend=getattr(settings, 'CELERY_BROKER_URL', _DEFAULT_BROKER),
)

app.conf.update(
    task_queues=[Queue('training'), Queue('default')],
    task_routes={
        'training.run_training': {'queue': 'training'},
        'training.run_test': {'queue': 'default'},
    },
    task_default_queue='default',
    task_soft_time_limit=86000,
    broker_connection_retry_on_startup=True,
)