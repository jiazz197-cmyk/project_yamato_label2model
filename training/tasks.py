"""训练/测试任务入队 seam（Sub-Issue 4 占位实现）。

Sub-Issue 6/11 落地后，把 enqueue_training/enqueue_test 内部替换为真实
run_training.delay(job.id) / run_test.delay(test_run.id)（见 training/celery_app.py
的 task_routes），函数签名与视图调用保持不变。
"""

import uuid


def enqueue_training(job):
    """为 TrainingJob 生成占位 celery_task_id 并保持 Pending。

    Sub-Issue 6：替换为 run_training.delay(job.id)。
    """
    if not job.celery_task_id:
        job.celery_task_id = uuid.uuid4().hex
        job.save(update_fields=['celery_task_id'])


def enqueue_test(test_run):
    """为 TestRun 生成占位 celery_task_id 并保持 Pending。

    Sub-Issue 11：替换为 run_test.delay(test_run.id)。
    """
    if not test_run.celery_task_id:
        test_run.celery_task_id = uuid.uuid4().hex
        test_run.save(update_fields=['celery_task_id'])
