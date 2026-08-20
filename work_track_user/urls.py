from django.urls import path
from . import views

urlpatterns = [
    path("clock-in/", views.clock_in, name="clock_in"),
    path("clock-out/", views.clock_out, name="clock_out"),
    path("current-session/", views.current_session, name="current_session"),
    path("monitor-status/", views.monitor_status, name="monitor_status"),
    path("upload-screenshot/",views.upload_screenshot),
    path("my-screenshots/",views.my_screenshots),
    path("monitoring-settings/",views.monitoring_settings,name="monitoring_settings"),
    path("blocked-apps/",views.blocked_apps,name="blocked_apps"),
    path("start-idle/",views.start_idle,name="start_idle"),
    path("end-idle/",views.end_idle,name="end_idle"),
    path("my-idle-sessions/",views.my_idle_sessions,name="my_idle_sessions"),
    path("start-application/",views.start_application,name="start_application"),
    path("end-application/",views.end_application,name="end_application"),
    path("my-application-usage/",views.my_application_usage,name="my_application_usage"),
    path("start-website/",views.start_website,name="start_website"),
    path("end-website/",views.end_website,name="end_website"),
    path("my-websites/",views.my_websites,name="my_websites"),
    path("leave-request/", views.apply_leave),
    path("my-leave-requests/", views.my_leave_requests),
    path("cancel-leave/<int:pk>/", views.cancel_leave),
]
