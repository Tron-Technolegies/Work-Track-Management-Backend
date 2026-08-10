"""
ASGI config for work_track_project project.

It exposes the ASGI callable as a module-level variable named `application`.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "work_track_project.settings"
)

import django

django.setup()

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

from work_track_admin.websocket_urls import websocket_urlpatterns
from .jwt_middleware import JWTAuthMiddleware


django_asgi_app = get_asgi_application()


application = ProtocolTypeRouter({
    "http": django_asgi_app,

    "websocket": JWTAuthMiddleware(
        URLRouter(websocket_urlpatterns)
    ),
})