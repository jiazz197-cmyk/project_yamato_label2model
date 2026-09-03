"""训练/测试任务入队 seam（Sub-Issue 4 占位实现）。

Sub-Issue 6/11 落地后，把 enqueue_training/enqueue_test 内部替换为真实
run_training.delay(job.id) / run_test.delay(test_run.id)（见 training/celery_app.py
的 task_routes），函数签名与视图调用保持不变。
"""

# ============================================================================
# 【注释版】对应 commit ada930cea9e72e045e86d1c3744e8e032c280148，仅供理解，请勿提交。
#
# "seam（接缝）"设计：api.py 只依赖这两个函数的签名，不依赖其内部实现。
# 本 commit（Sub-Issue 4）阶段 Celery 任务体还不存在，于是：
#   - 现在：生成占位 task id，任务留在 Pending（没有任何 worker 会动它们）；
#   - 将来（Sub-Issue 6/11）：函数体换成真实 .delay() 投递，
#     真正的 task id 由 Celery 返回后写回模型。
# 这样后续替换时 api.py 一行都不用改。
# ============================================================================

import uuid
# 标准库 uuid：生成 32 位随机十六进制串，冒充"任务 id"的形状
# （真实 Celery task id 也是 UUID 字符串，下游解析逻辑可以按同一形状处理）。


def enqueue_training(job):
    """为 TrainingJob 生成占位 celery_task_id 并保持 Pending。

    Sub-Issue 6：替换为 run_training.delay(job.id)。
    """
    # 入参 job：api.py perform_create 里刚 save 落库的 TrainingJob 实例
    # （status='Pending'，celery_task_id 为空）。
    if not job.celery_task_id:
        # 幂等保护：已有 task id（例如被重复调用）就不覆盖。
        # 将来换成 .delay() 后，这行判断的语义仍是"防止重复入队"。
        job.celery_task_id = uuid.uuid4().hex
        # 占位任务 id：uuid4 → 128 位随机数 → .hex 去掉连字符 → 32 个十六进制字符。
        # 注意：这只是个"形状正确"的假 id，队列里并没有对应任务；
        # 前端拿着它做状态轮询时，Sub-Issue 6 之前永远查不到真实进度。
        job.save(update_fields=['celery_task_id'])
        # 只 UPDATE celery_task_id 一列（单列写，干净且无副作用）。
        # 任务状态保持 'Pending'：本 commit 没有 worker，谁也不会把它改成 Running。
    # 函数无返回值。api.py 调用后不依赖返回；
    # 将来真实版本里通常是 task_id = run_training.delay(job.id) 再写回，
    # 对外签名 enqueue_training(job) 不变。


def enqueue_test(test_run):
    """为 TestRun 生成占位 celery_task_id 并保持 Pending。

    Sub-Issue 11：替换为 run_test.delay(test_run.id)。
    """
    # 入参 test_run：perform_create 刚落库的 TestRun 实例（status='Pending'）。
    if not test_run.celery_task_id:
        # 同样的幂等保护。
        test_run.celery_task_id = uuid.uuid4().hex
        # 占位任务 id（同 enqueue_training）。
        test_run.save(update_fields=['celery_task_id'])
        # 单列写回；TestRun 保持 Pending。
