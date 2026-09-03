# YOLO 系列模型训练与使用适配计划（父计划 / GitHub issue / 代码）

## 1. 目标与成功标准

在现有「本地基模 → 本地训练 → 预标记 → 零样本/产物测试」闭环中，把 YOLO（Ultralytics）作为与 HF、sklearn 并列的第三训练框架，支持 **目标检测（detect）** 与 **实例分割（segment）** 两类任务。

成功标准：

- `BaseModel.framework` 出现 `YOLO`；`task_type` 出现 `ObjectDetection`（RectangleLabels）与 `InstanceSegmentation`（PolygonLabels）。
- 本地预置一个 `.pt` 基模（如 `yolov8n.pt` / `yolov8n-seg.pt`）后，`scan_local_models` 能识别为 YOLO，`validate_local_model_path` 通过。
- 对含矩形框/多边形标注的 image 项目发起训练：标注被转换为 YOLO 数据集（`data.yaml` + images + labels），训练产物落盘 `<LOCAL_MODEL_ROOT>/trained/<job_id>/best.pt`，`TrainingJob.status=Completed`，`metrics` 含 `mAP50 / mAP50-95 / precision / recall`。
- 训练产物登记为 `ml/MLBackend` 后，Batch predictions 能对图像任务产出 `rectanglelabels` / `polygonlabels` 预测，`Prediction.model_version == job.model_version`。
- `TestRun`（零样本挂 BaseModel 或产物挂 TrainingJob）能对 YOLO 跑 `val` 并回写 mAP 类指标。
- 全程不联网下载预训练权重（基模一律本地 `.pt`）；Windows PowerShell 下跑通。

## 2. 已确认决策（用户）

1. YOLO 覆盖范围：**目标检测 + 实例分割**（不含 classify/pose/obb，不含 BrushLabels 位图掩码分割）。
2. 新 task_type 归属：**扩展 `ml_models.SkillNames`**（纯新增枚举项，不改既有语义）。

## 3. 现状（已勘察）

- `training/` app 已存在，Sub-Issue 1–4 已落地：三表 + migration `0001`、Celery 配置、`utils.py`（HF/sklearn 校验与扫描）、REST API。
- Sub-Issue 5–16 尚未实现：`training/dataset.py`、`training/adapters/`、`training/fastapi_app.py`、`training/predictor/`、`run_training/run_test`（`training/tasks.py` 目前是入队占位）都还不存在。
- 现状框架只有 `HF`/`SKLEARN`（`training/models.py` `BaseModel.Framework`、`training/utils.py` 常量、migration `0001` 已固化 choices）。
- `ml_models.SkillNames` 只有 `TextClassification`/`NamedEntityRecognition`。
- `pyproject.toml` 已有 `torch(CUDA)`/`transformers`/`scikit-learn`/`joblib`/`celery`/`fastapi`/`uvicorn`，**无 `ultralytics`**。
- 图像标注类型：Label Studio 用 `rectanglelabels`（value 含 `x,y,width,height,rotation,rectanglelabels`）与 `polygonlabels`（value 含 `points`，坐标为 0–100 百分比）。任务图像取 `task.data['image']`（可能为 MinIO/存储 URL 或本地路径）。

## 4. 变更分组

### 4.1 计划与 issue 工件（父计划 + GitHub issue）

- **`.omo/plans/training-app.md`**：
  - TL;DR/Scope In/Success criteria 改为「三框架（HF + sklearn + YOLO）」，任务类型补 `ObjectDetection`/`InstanceSegmentation`；明确 YOLO 仅本地 `.pt`、不做 BrushLabels/位图掩码、不联网下载。
  - 新增 **Sub-Issue 18 — YOLO 目标检测与实例分割适配**（内容即本计划 §4.2–§4.9 的可执行 todo 列表，含独立 Acceptance/QA/Commit）。
  - 在 Sub-Issue 2（依赖）、3（utils）、5（dataset）、6/7（adapter）、9（predictor）、11/12（test 指标）、14/15/16（前端/文档）标注「含 YOLO」的交叉改动点。
- **`.omo/issues/00-parent.md`**：背景/范围/技术决策/验收标准补三框架与两类新 task_type。
- **`.omo/issues/create-issues.md`**：新增一个 `create_child "[training-18] YOLO 目标检测与实例分割适配"`（子 issue 数 16→17），并同步 `00-parent.md`。
- **GitHub 线上 issue**（执行阶段用 `gh`）：`gh issue edit <父#10>` 更新 body；`gh issue create` 新增 `[training-18]` 子 issue（body 含 `Part of #父issue`）。**注**：仓库内可确认父 issue 为 #10、`training-1` 为 #11，其余 #12–#27 为推断，执行前用 `gh issue list --repo <owner/repo>` 核对实际编号。

### 4.2 依赖与配置

- `pyproject.toml`：`[project] dependencies` 新增 `ultralytics (>=8.3,<9.0) ; python_version >= "3.11"`（与现有训练依赖标记风格一致）；`poetry add ultralytics` 更新 `poetry.lock`。
- 依赖风险：ultralytics 会引入 `opencv-python`/`pillow`/`pyyaml`（pyyaml 已有），需确认与现有 `numpy>=2.2,<3`、`torch>=2.11,<3` 兼容；若冲突，锁到 ultralytics 兼容版本并记录。
- 可选 setting（`label_studio/core/settings/label_studio.py` 文件尾，与现有 7 个 training settings 并列）：`TRAINING_YOLO_VAL_SPLIT = float(get_env('TRAINING_YOLO_VAL_SPLIT', 0.2))`（train/val 切分比例，样本 <2 时退化为单 train 集）。

### 4.3 SkillNames + 模型/migration/utils

- `label_studio/ml_models/models.py` `SkillNames`：新增
  - `OBJECT_DETECTION = 'ObjectDetection', _('ObjectDetection')`
  - `INSTANCE_SEGMENTATION = 'InstanceSegmentation', _('InstanceSegmentation')`
  （纯新增，`TextClassification`/`NamedEntityRecognition` 不变。）
- `training/utils.py`：
  - 常量新增 `FRAMEWORK_YOLO = 'YOLO'`、`TASK_TYPE_OBJECT_DETECTION = 'ObjectDetection'`、`TASK_TYPE_INSTANCE_SEGMENTATION = 'InstanceSegmentation'`。
  - `_has_yolo_weights(path)` → `glob('*.pt')` 非空。
  - `validate_local_model_path`：`YOLO` 分支校验目录含 `*.pt`（只查存在，不加载）。
  - `_detect_framework` 顺序：`config.json`→HF，否则 `model.pkl`→SKLEARN，否则 `*.pt`→YOLO，否则 None。
  - `scan_local_models`：YOLO 的 `task_type_guess` 返回 `None`（避免扫描期加载 torch 判断 detect/segment；由用户在创建/上传时选择）。
- `training/models.py` `BaseModel.Framework`：新增 `YOLO = 'YOLO', 'Ultralytics YOLO'`。
- 迁移：`makemigrations` 生成
  - `training/migrations/0002_alter_basemodel_framework_and_more.py`（framework 与 task_type 的 choices 变更，仅 choices，无 schema 变更）；
  - `ml_models` 因 `ModelInterface.skill_name` 用 `SkillNames.choices` 也会产生一个 choices-only 迁移（属预期副作用，一并提交）。
- `training/serializers.py`：无需改结构（`task_type`/`framework` 为只读自动带出新 choices）；Sub-Issue 17 的 `complete` 上传接口在 YOLO 场景下必须允许用户显式传入 `task_type`（`ObjectDetection`/`InstanceSegmentation`）。

### 4.4 YOLO 数据集与标签转换（新模块 `training/yolo.py`）

- `build_class_names(project)`：从 `project.get_parsed_config()` 取 `RectangleLabels`/`PolygonLabels` 控制标签，按 label_config 出现顺序产出有序 `names` 列表（并据此建立 label→class idx 映射）。无矩形/多边形标签 → 抛清晰错误。
- `materialize_image(task, project, dst)`：解析 `task.data['image']`（复用 `Task.resolve_storage_uri`/storage 生成可下载 URL，或本地路径直接复制），把字节/文件落到训练目录；失败返回 None（调用方 skip + 计数）。
- `annotation_to_yolo(annotation, class_map, mode)`：
  - detect：`type=='rectanglelabels'` → `class_idx cx cy w h`（归一化 0–1，`cx=(x+w/2)/100` 等）。
  - segment：`type=='polygonlabels'` → `class_idx x1 y1 … xn yn`（点 0–100 除以 100）。
  - 忽略其它 region 类型与不在 class_map 中的 label。
- `build_yolo_dataset(project, tasks, workdir, mode, val_split)`：产出 YOLO 目录 `images/{train,val}/`、`labels/{train,val}/`、`data.yaml`（含 `names`、`train`/`val` 路径、`nc`）。样本 <2 时 `val` 缺省（或 `val=False`）。
- 产物目录约定：`<LOCAL_MODEL_ROOT>/trained/<job_id>/` 下保留 `best.pt`、`last.pt`、`data.yaml`（predictor/测试复用 class 映射）与 `dataset/`（可选保留，用于复现）。

### 4.5 YOLO 训练 adapter（新 `training/adapters/yolo_adapter.py`）

- `train(job, dataset, progress_cb)`：
  - `from ultralytics import YOLO`；加载 `YOLO(<base_model.local_path>/*.pt)`（**显式本地路径，绝不传在线权重名**，避免触发自动下载）。
  - `build_yolo_dataset(...)`；`model.train(data=data.yaml, epochs=..., imgsz=..., batch=..., device=..., project=..., name=..., exist_ok=True)`，hyperparams 覆盖 `base_model.default_config`。
  - 进度：`model.add_callback('on_train_epoch_end', cb)` → `progress_cb({epoch, total_epochs, loss, ...})`。
  - 产物：把 ultralytics run 目录里的 `best.pt`/`last.pt` 复制到 `artifact_path`，回写 `metrics`（`mAP50`、`mAP50-95`、`precision`、`recall`）、`model_version=f"{base_model.name}__{job.id}"`。
- 失败 → `status=Failed + error_message`（模型损坏/无 `.pt`/无有效训练样本/无矩形或边形标注）。

### 4.6 任务分发（`training/tasks.py`，随 Sub-Issue 6/7/11 落地）

- `run_training` 的 framework 分发增加 `FRAMEWORK_YOLO → yolo_adapter.train`。
- `run_test` 对 YOLO：`build_yolo_dataset(...)` → `model.val(data=data.yaml)` 得到指标；零样本挂 BaseModel 时从 `base_model.local_path/*.pt` 加载，产物测试从 `artifact_path/best.pt` 加载。

### 4.7 predictor 预测服务（随 Sub-Issue 9 落地）

- 在计划中的 `training/fastapi_app.py` + `training/predictor/` 增加 YOLO 分支：`/predict/<job_id>` 对 `framework==YOLO` 的任务加载 `YOLO(artifact_path/best.pt)`，逐任务 `materialize_image` 后推理，转换为 Label Studio 结果：
  - detect → `{'from_name','to_name','type':'rectanglelabels','value':{'x','y','width','height','rotation':0,'rectanglelabels':[name]}}`（百分比 0–100）+ score。
  - segment → `{'type':'polygonlabels','value':{'points':[[x,y]...],'polygonlabels':[name]}}`（ultralytics `masks.xy` 归一化 0–1 → 百分比）+ score。
  - 返回 `{'results': [{'result': [...], 'score': ..., 'model_version': job.model_version}]}`，严格对齐 `ml/api_connector.py` 期望。
- `from_name/to_name` 从 `data.yaml`/label_config 的矩形/多边形控制标签名解析；`names` 列表存于 `data.yaml` 供反向映射。

### 4.8 测试指标（随 Sub-Issue 12 落地）

- YOLO 测试回写 `TestRun.metrics = {mAP50, mAP50-95, precision, recall, per_class, total, skipped}`（`skipped` 记录图片无法落地/无标注的 task）。
- **明确偏离父计划**：YOLO 不做文本分类式 2D `confusion_matrix`（检测/分割无等价单标签混淆矩阵）；若需要可留空或放 per-class TP/FP，验收以 mAP 为准。

### 4.9 前端与文档

- 前端（Sub-Issue 14/15/17）：framework 展示 YOLO；YOLO 上传/创建时必选 `task_type`（检测/分割）；训练/测试指标卡片展示 `mAP50/mAP50-95`；上传接受 `.pt` 文件（zip 内含 `.pt`）。
- `docs/training.md`：新增「YOLO」章节——预置 `.pt` 目录结构、标注类型要求（RectangleLabels/PolygonLabels）、class 映射来源、训练/预测/测试流程、指标说明、Windows PowerShell 命令；健康检查命令补 `import ultralytics`。

## 5. 边界情况与失败模式

- 图片 URL 无法解析/下载、本地文件缺失 → 跳过该 task 并计入 `skipped`，不中断整批。
- project 无 RectangleLabels/PolygonLabels 标签 → `build_class_names` 抛清晰错误，训练/测试 `status=Failed`。
- 矩形框带 `rotation` → YOLO detect 标准模式不支持旋转框：忽略 rotation 按轴对齐框转换（并记录日志）；若需旋转框（obb）明确 Out of scope。
- polygon 点坐标为 0–100 百分比 → 除以 100 归一化；异常点数（<3 点）跳过该 region。
- label 不在 class_map → 跳过该 region（不映射为未知类）。
- `.pt` 缺失/损坏 → `validate_local_model_path`/训练/预测失败 → `status=Failed`。
- 训练样本 <2 → 不切 val（`val=False`），避免 ultralytics 报空 val。
- 严禁联网：所有 `YOLO(...)` 调用只传本地绝对路径；adapter 不调用 `YOLO('yolov8n.pt')` 这类会触发自动下载的写法。
- Windows 路径：统一 `os.path.join`/`pathlib`，不得出现 `/mnt/c`。
- 设备：`device` 从 `default_config` 读取，缺省 `''`（ultralytics 自动选 CPU/CUDA），文档说明。

## 6. 测试与验收

- `training/tests/test_utils.py` 扩展：YOLO 目录含 `.pt` → validate 通过/scan 识别为 YOLO；空目录/无 `.pt` → 抛错/跳过。
- `training/tests/test_models.py` 扩展：`framework='YOLO'` + 有效 `.pt` 目录保存成功。
- 新增 `training/tests/test_yolo.py`（`pytest.importorskip('ultralytics')` 兜底重依赖）：
  - rectanglelabels→YOLO detect 行、polygonlabels→YOLO segment 行（含坐标归一化）；
  - `build_class_names` 顺序与映射；
  - `build_yolo_dataset` 生成 `data.yaml`/images/labels 且 class 正确；
  - `materialize_image`（mock storage URL 与本地路径两条）。
- 集成（`@pytest.mark.training` / `integration_tests`，无 GPU 时 skip）：小样本合成数据集训练 1 epoch → Completed + mAP 指标非空；predictor `/predict` 返回可被 `Prediction.prepare_prediction_result` 接受的 rectanglelabels/polygonlabels。
- 手动 QA（Windows）：预置 `yolov8n.pt` 与 `yolov8n-seg.pt` 各一 → 启动三进程 → 训练/预测/测试全流程。
- 验收以 §1 成功标准为准，且 `ruff check` / `manage.py check` / SQLite pytest 冒烟通过。

## 7. 明确假设

- YOLO 基模以**目录**形式预置（目录内放一个或多个 `.pt`），与 `BaseModel.local_path` 的「目录」约定一致；不做「单个 `.pt` 文件即 local_path」。
- 目标检测=RectangleLabels、实例分割=PolygonLabels；BrushLabels/位图掩码不在本期。
- 训练数据只取 `task.data['image']` 单个图像字段（多图/多页任务首个 image，其余列为后续）。
- 运行环境已具备 torch（CUDA）与 GPU 或 CPU；ultralytics 依赖冲突由 poetry 锁版本解决。
- GitHub 线上 issue 的实际编号以 `gh issue list` 为准（父 #10、`training-1` #11 已确认，其余为推断）。

## 8. 实施顺序与依赖

1. 计划/issue 工件更新（§4.1）与依赖（§4.2）可先行、并行。
2. SkillNames + 常量 + 模型 + 迁移 + utils（§4.3）→ 生成两个 choices-only 迁移。
3. `training/yolo.py`（§4.4）→ `training/adapters/yolo_adapter.py`（§4.5）→ `run_training/run_test` 分发（§4.6，与既有 Sub-Issue 6/7/11 一并实现）。
4. predictor（§4.7）与测试指标（§4.8）依赖 adapter 与 dataset。
5. 前端 + 文档（§4.9）最后收口。
