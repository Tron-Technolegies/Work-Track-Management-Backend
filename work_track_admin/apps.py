from django.apps import AppConfig
from django.conf import settings
import os

class WorkTrackAdminConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'work_track_admin'

    def ready(self):
        # Start background monitor worker when server starts
        if os.environ.get('RUN_MAIN') == 'true' or not settings.DEBUG:
            try:
                from .monitor_service import start_monitor_service
                start_monitor_service()
            except Exception:
                pass
