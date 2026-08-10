from django.contrib import admin

# Register your models here.
from .models import MonitoringSettings

admin.site.register(MonitoringSettings)