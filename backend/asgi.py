"""
ASGI config for backend project.

Supports both HTTP and WebSocket (via Django Channels).
"""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

# 先初始化 Django（必须在 import routing 之前）
django_asgi_app = get_asgi_application()

# 延迟 import routing，确保 Django apps 已加载
from core.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': URLRouter(websocket_urlpatterns),
})
