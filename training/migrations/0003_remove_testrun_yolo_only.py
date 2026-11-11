# Handwritten migration: 收敛为 YOLO-only 训练应用。
#
# - 删除 TestRun（测试任务模型整体下线）
# - TrainingJob 去掉 celery_task_id（异步执行链已移除）
# - BaseModel.framework 只剩 YOLO；task_type 收敛为本地 TaskType 的两项
#
# 必须与 training/models.py 的最终状态逐字一致，否则 `makemigrations --check` 会失败。

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('training', '0002_alter_basemodel_framework_and_more'),
    ]

    operations = [
        migrations.DeleteModel(
            name='TestRun',
        ),
        migrations.RemoveField(
            model_name='trainingjob',
            name='celery_task_id',
        ),
        migrations.AlterField(
            model_name='basemodel',
            name='framework',
            field=models.CharField(choices=[('YOLO', 'Ultralytics YOLO')], max_length=16),
        ),
        migrations.AlterField(
            model_name='basemodel',
            name='task_type',
            field=models.CharField(choices=[('ObjectDetection', 'ObjectDetection'), ('InstanceSegmentation', 'InstanceSegmentation')], max_length=255),
        ),
    ]
