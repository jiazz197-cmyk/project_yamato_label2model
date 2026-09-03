# 训练功能运维文档

## 架构概览

训练功能由三个进程协同工作，共享同一个 Redis 实例作为消息代理和进度推送通道。

- **Django runserver**：CRUD API、用户鉴权、数据集管理、标注结果导出
- **Celery worker**：消费 `training` 和 `default` 队列，执行训练/测试异步任务
- **FastAPI predictor 侧车**：本地模型预测服务，通过 SSE 推送训练进度

三者通过 Redis 通信：Django 将训练任务投递到 Redis broker，Celery worker 从 broker 拉取任务执行，predictor 侧车通过 Redis pub/sub 向 Django 推送实时训练进度。`.env` 中需设置 `REDIS_ENABLED=True`，broker 连接地址由 `REDIS_HOST`、`REDIS_PORT`、`REDIS_DB`（缺省 0）派生。

## 前置条件

### Redis 连接

`.env` 中必须已启用 Redis：

```ini
REDIS_ENABLED=True
REDIS_HOST=100.106.236.77
REDIS_PORT=6379
# REDIS_DB 缺省 0，无需显式设置
```

Redis 必须从运行本机可访问。当前 `.env` 配置的 Redis 地址为 `100.106.236.77:6379`，若该地址不可达，Celery worker 会持续重试连接但不会崩溃，Django 不受影响（详见故障排查章节）。

### 依赖安装

确保所有依赖已通过 Poetry 安装：

```powershell
poetry install
```

`poetry install` 会安装 `pyproject.toml` 中声明的所有依赖，包括 `torch`、`transformers`、`scikit-learn`、`joblib`、`celery`、`fastapi`、`uvicorn`、`ultralytics` 等训练相关包。

## 三进程启动

以下所有命令均在**项目根目录**、**Windows PowerShell** 中执行。三个进程各占用一个终端窗口，建议使用三个独立的 PowerShell 标签页分别启动。

### ① Django 开发服务器

```powershell
poetry run python label_studio/manage.py runserver 0.0.0.0:8080
```

启动后开放 `http://localhost:8080`，提供完整的 Web 标注界面、API 接口和用户鉴权。开发模式下 Django 自动重载代码变更。

### ② Celery Worker

```powershell
poetry run celery -A training.celery_app worker --pool=solo -Q training,default --loglevel=info
```

**重要说明：**

- Celery 4.x 起官方不再支持 Windows 平台。`--pool=solo` 是社区标准做法，使用主进程单线程顺序消费任务。
- **不要**添加 `-c` 并发参数——solo 池只支持单进程，加并发参数无效。
- solo 池下 `task_soft_time_limit`（86000 秒）不强制执行。该限制在 Linux prefork 部署时生效，Windows 上训练任务超时保护依赖训练任务内部的 epoch 级检查。
- 启动后会在日志 banner 的 `[queues]` 行中看到 `training` 和 `default` 两个队列。

### ③ FastAPI Predictor 侧车

```powershell
poetry run python label_studio/manage.py runpredictionservice --port 8990
```

> **注意：此命令需 Sub-Issue 9 实现后才可用。** 当前执行会报 `Unknown command: 'runpredictionservice'`，属于预期行为。

### 重启注意事项

修改 `.env` 后，三个进程均需重启才能使新配置生效。三者共享项目根目录作为工作目录（CWD）。

## 环境变量配置

训练功能通过以下 8 个环境变量控制行为。所有变量可在 `.env` 中设置，未设置时使用默认值。

| 环境变量 | 默认值 | 用途 |
|----------|--------|------|
| LOCAL_MODEL_ROOT | `data/models`（相对项目根） | 本地预置模型根目录；上传的模型文件与训练产物统一存放于此。生产环境建议在 `.env` 中配置为绝对 Windows 路径 |
| TRAINING_ARTIFACTS_STORAGE_PREFIX | `trained` | 训练产物子目录名。完整路径为 `LOCAL_MODEL_ROOT/<前缀>/<job_id>/` |
| TRAINING_UPLOAD_MAX_SIZE | 2147483648（2GB） | 单模型上传上限，单位字节 |
| TRAINING_UPLOAD_CHUNK_SIZE | 8388608（8MB） | 分片上传每片大小，单位字节 |
| TRAINING_SAMPLE_SIZE | 100 | Sample subset 随机取样数 |
| PREDICTOR_PORT | 8990 | FastAPI predictor 侧车监听端口 |
| TRAINING_PROGRESS_REDIS_CHANNEL | `training:progress` | Redis pub/sub 进度推送 channel 前缀 |
| TRAINING_YOLO_VAL_SPLIT | `0.2` | YOLO 数据集 train/val 切分比例；样本 <2 时退化为单 train 集 |

## 健康检查

### 依赖导入冒烟测试

```powershell
poetry run python -c "import torch, transformers, sklearn, joblib, celery, fastapi, uvicorn, ultralytics"
```

无输出即表示所有依赖包可正常导入。

### Django 系统检查

```powershell
poetry run python label_studio/manage.py check
```

### Worker 启动确认

Celery worker 启动后，日志中应出现以下标志：

- 连接成功：`Connected to redis://100.106.236.77:6379/0`
- 启动 banner 的 `[queues]` 行包含 `default` 和 `training` 两个队列
- 示例 banner 输出：

```
 -------------- celery@HOSTNAME v5.6.3 (recovery)
--- ***** -----
-- ******* ---- Linux-... [concurrency: 16 (solo)]
- *** --- * ---
- ** ---------- [queues]
- ** ---------- .> training        exchange=training(direct) key=training
- ** ---------- .> default         exchange=default(direct) key=default
- *** --- * ---
--- ***** -----
```

## YOLO 系列模型

YOLO（Ultralytics）作为第三训练框架，支持目标检测（detect）与实例分割（segment）。

### 基模目录结构

服务器预置 YOLO 基模以**目录**形式放在 `LOCAL_MODEL_ROOT` 下，目录内直接放置一个或多个 `.pt` 文件：

```text
<LOCAL_MODEL_ROOT>/
└── yolov8n/
    ├── yolov8n.pt
    └── yolov8n-seg.pt
```

`scan_local_models` 会自动把含 `*.pt` 的目录识别为 `YOLO`；由于扫描期不加载 torch，
`task_type_guess` 返回 `None`，创建/上传模型时需由用户显式选择 `ObjectDetection` 或
`InstanceSegmentation`。

### 标注类型与 class 映射

- 目标检测：Label Studio `RectangleLabels`，region value 为 `x/y/width/height`（0–100 百分比）。
- 实例分割：Label Studio `PolygonLabels`，region value 的 `points` 为 0–100 百分比。
- class 映射来自 label_config 中 `RectangleLabels`/`PolygonLabels` 的 `<Label value=...>` 出现顺序。
- 不支持 BrushLabels/位图掩码、旋转框（OBB）、分类/关键点/姿态。

### 训练与测试

- 训练入口通过 `training.adapters.yolo_adapter.train` 调用 `YOLO(<本地目录>/*.pt)`，
  只传本地绝对路径，严禁传 `yolov8n.pt` 等在线权重名。
- 训练数据由 `training.yolo.build_yolo_dataset` 转为 `data.yaml + images/ + labels/`。
- 训练产物保留在 `<LOCAL_MODEL_ROOT>/trained/<job_id>/`，含 `best.pt`、`last.pt`、`data.yaml`。
- 测试与预测从产物 `best.pt`（或零样本基模目录内 `.pt`）加载，不联网。

### 指标

- 训练/测试回写 `mAP50`、`mAP50-95`、`precision`、`recall`。
- YOLO 检测/分割不做文本分类式 2D `confusion_matrix`。

### Windows PowerShell 健康检查

```powershell
poetry run python -c "import ultralytics"
```

## 故障排查

### Broker 不可达

**症状：** Celery worker 启动后持续输出如下错误，Django 不受影响。

```
Cannot connect to redis://100.106.236.77:6379/0: Error 10061 connecting to 100.106.236.77:6379.
Trying again in 2.00 seconds... (1/100)
```

**原因：** Redis 未启动，或 `.env` 中 `REDIS_HOST`/`REDIS_PORT` 配置的地址从运行机不可达。

**CELERY_BROKER_URL 派生规则：** broker URL 由 `.env` 中的 Redis 配置自动拼接：`redis://<REDIS_HOST>:<REDIS_PORT>/<REDIS_DB>`，其中 `REDIS_DB` 未设置时默认为 `0`。该 URL 在 `label_studio/core/settings/label_studio.py` 的 `REDIS_ENABLED=True` 条件块中生成，无需手动配置。

**处理：**

1. 确认 Redis 服务已启动且网络可达：`poetry run python -c "import redis; redis.Redis(host='100.106.236.77', port=6379, socket_connect_timeout=3).ping()"`
2. 确认 `.env` 中 `REDIS_ENABLED=True` 且 `REDIS_HOST`/`REDIS_PORT` 值正确
3. 修改 `.env` 后重启所有三个进程

### 三进程未全部启动

- **Django 未启动**：无法访问 Web 界面、API 不可用、无法创建训练任务
- **Celery worker 未启动**：训练任务停留在 Pending 状态，不会被消费执行
- **Predictor 侧车未启动**：预标记功能不可用，训练进度无法实时推送

### Windows 平台注意事项

- Celery worker 在 Windows 上必须使用 `--pool=solo`。`prefork` 池（默认）在 Windows 下不可用。
- PowerShell 脚本中不要包含中文字符，避免编码问题。
- 所有命令已在 Windows PowerShell 5.1 环境下验证。