"""RQ worker class that initializes Django before running Label Studio jobs.

``rq worker-pool`` spawns plain ``rq.worker.Worker`` processes.  Unlike
django-rq's ``rqworker`` management command, those workers do not call
``django.setup()``, so Label Studio job functions that import Django models
would fail with ``AppRegistryNotReady``.  This subclass performs the setup in
each worker process before the first job is executed.
"""

import os
import sys

import django
from rq.worker import Worker

# manage.py 依赖 sys.path[0] = label_studio/；rq CLI 从仓库根启动，
# 需要显式把 label_studio/ 加进来，core.settings 才能被导入。
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_DIR = os.path.join(PROJECT_ROOT, 'label_studio')
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)


class DjangoWorker(Worker):
    """Worker that bootstraps Django before consuming Label Studio queues."""

    def bootstrap(self, *args, **kwargs):
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.label_studio')
        django.setup()
        super().bootstrap(*args, **kwargs)
