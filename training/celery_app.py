"""Celery 应用（训练/测试异步任务）。

独立入口：`celery -A training.celery_app worker ...`
先引导 Django（补 label_studio/ 路径 + DJANGO_SETTINGS_MODULE），
broker/result backend 复用 core/settings/label_studio.py 的
CELERY_BROKER_URL（即 .env 中与 RQ 相同的 Redis）。
"""

import os
import sys

# 计算项目根目录：本文件位于 <项目根>/training/celery_app.py，
# 向上两级（dirname 两次）即项目根（与 label_studio/ 同级）。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# label_studio/ 目录路径——其中的 core.settings 才是 Django 的 settings 包。
_LABEL_STUDIO_DIR = os.path.join(_PROJECT_ROOT, 'label_studio')
# 把 label_studio/ 加入 sys.path，使 `import core.settings...` 可解析。
# （与 manage.py 顶部 sys.path.insert 同理；celery CLI 从项目根启动时
#  只能保证 `training` 包可导入，core 包需要此显式路径补齐。）
if _LABEL_STUDIO_DIR not in sys.path:
    sys.path.insert(0, _LABEL_STUDIO_DIR)

# 设置 Django settings 模块（与 manage.py:8 同一目标）；
# setdefault 保证在 Django 进程内被 import 时不会覆盖已设置的值。
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.label_studio')

import django  # noqa: E402

# 初始化 Django（加载 settings、注册 app）。
# 幂等：Django 进程内重复调用安全；celery 作为独立进程启动时则完成首次初始化。
django.setup()  # 幂等：Django 进程内重复调用安全

from celery import Celery  # noqa: E402
from django.conf import settings  # noqa: E402
from kombu import Queue  # noqa: E402

# 兜底 broker：当 REDIS_ENABLED=False（settings 中未定义 CELERY_BROKER_URL）时
# 保证 Celery app 仍可被 import，避免 Django 启动/测试被 broker 配置拖垮。
_DEFAULT_BROKER = 'redis://localhost:6379/0'

# 创建 Celery 实例。
# - 第一个参数是 app 名称（worker banner 中显示为 label_studio_training）。
# - broker：任务队列消息代理，复用 settings.CELERY_BROKER_URL
#   （由 .env 的 REDIS_HOST/PORT/DB 派生，与既有 RQ 共用同一个 Redis）。
# - backend：任务结果存储，与 broker 同址（便于 inspect/result 查询）。
# - getattr 兜底：REDIS_ENABLED=False 时退回 localhost，保证 app 可 import。
app = Celery(
    'label_studio_training',
    broker=getattr(settings, 'CELERY_BROKER_URL', _DEFAULT_BROKER),
    backend=getattr(settings, 'CELERY_BROKER_URL', _DEFAULT_BROKER),
)

# 统一更新 Celery 运行时配置（避免逐个属性赋值）。
app.conf.update(
    # 声明 worker 消费的两个队列：training（长训练任务）与 default（短任务/测试）。
    # 启动 worker 时须用 `-Q training,default` 显式指定消费这两个队列。
    task_queues=[Queue('training'), Queue('default')],
    # 路由规则：按任务显式 name 分发。
    # - training.run_training（Sub-Issue 6 定义的训练任务）-> training 队列（长任务专用）。
    # - training.run_test（Sub-Issue 11 定义的测试任务）-> default 队列。
    # 键名必须与 @app.task(bind=True, name='training.run_training') 的 name 完全一致，
    # 否则路由失效（任务会落入默认队列）。
    task_routes={
        'training.run_training': {'queue': 'training'},
        'training.run_test': {'queue': 'default'},
    },
    # 兜底队列：任何未匹配路由的任务都进入 default（worker 消费的队列之一），
    # 防止路由键拼写漂移导致任务进入无人消费的 'celery' 默认队列而滞留。
    task_default_queue='default',
    # 训练长任务的软超时（秒，约 24 小时）：达到后任务抛 SoftTimeLimitExceeded。
    # 注意：Windows 上 --pool=solo 不强制此限制（Celery 文档：time limits 仅
    # prefork/gevent 池实现）；Linux prefork 部署时生效。
    task_soft_time_limit=86000,
    # celery>=5.3 推荐：启动时连接 broker 失败则持续重试（而非直接退出或告警）。
    broker_connection_retry_on_startup=True,
)