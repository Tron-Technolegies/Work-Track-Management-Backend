from channels.auth import AuthMiddlewareStack
from channels.routing import URLRouter
from work_track_admin.websocket_urls import websocket_urlpatterns

application = AuthMiddlewareStack(
    URLRouter(
        websocket_urlpatterns
    )
)