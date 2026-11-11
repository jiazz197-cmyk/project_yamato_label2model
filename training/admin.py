from django.contrib import admin

from training.models import BaseModel, TrainingJob

admin.site.register(BaseModel)
admin.site.register(TrainingJob)
