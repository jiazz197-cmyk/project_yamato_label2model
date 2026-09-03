from django.contrib import admin

from training.models import BaseModel, TrainingJob, TestRun

admin.site.register(BaseModel)
admin.site.register(TrainingJob)
admin.site.register(TestRun)