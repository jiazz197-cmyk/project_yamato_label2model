"""Legacy Django 训练域（BaseModel / TrainingJob + /api/training REST API）。

训练/推理编排正在迁移到 FastAPI 侧车 ``services.ml_api``（ml-api + ml-worker）；
本包暂时保留以兼容现有模型/迁移/测试，后续阶段完成数据与 API 迁移后删除。
新增训练功能请优先放在 ``services/ml_api``，不要继续扩展本包。
"""
