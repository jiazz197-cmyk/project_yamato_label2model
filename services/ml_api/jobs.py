'''ML 侧车的 RQ 作业函数（占位实现）。

本模块刻意保持不依赖 torch / 深度学习推理框架，确保 RQ worker 在占位阶段也能正常
导入并消费 ping 作业。真实 YOLO 训练逻辑由后续 yolo-3 issue 接入；worker 按
'services.ml_api.jobs' 模块路径导入作业函数。
'''


def ping(*args, **kwargs) -> str:
    '''探活作业：返回 pong，用于确认 worker 已连接 training 队列。'''
    return 'pong'


def execute_training_job(training_job_id, **kwargs):
    '''训练执行占位。

    真实 YOLO 训练（数据准备、训练执行、指标上报）由 yolo-3 issue 实现；当前调用
    即抛出 NotImplementedError，避免占位阶段误跑真实任务。
    '''
    raise NotImplementedError('YOLO 训练执行由 yolo-3 issue 实现')
