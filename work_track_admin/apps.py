from django.apps import AppConfig
from django.conf import settings
import os

class WorkTrackAdminConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'work_track_admin'

    def ready(self):
        # Background desktop monitoring service is designed for client-side execution (monitor.py)
        # and should not run within the headless cloud web server.
        pass
