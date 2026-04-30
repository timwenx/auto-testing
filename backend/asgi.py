"""
ASGI config for backend project.

Supports both HTTP and WebSocket (via Django Channels).
"""

import os
import logging

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

logger = logging.getLogger(__name__)


class ShutdownGuardMiddleware:
    """捕获解释器关闭期间的请求，返回 503 而不是让 asgiref 抛出异常。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        try:
            await self.app(scope, receive, send)
        except RuntimeError as e:
            if 'shutdown' in str(e):
                logger.warning("请求在解释器关闭期间被拒绝: %s", e)
                if scope['type'] == 'http':
                    await send({'type': 'http.response.start', 'status': 503,
                                'headers': [[b'content-type', b'application/json']]})
                    await send({'type': 'http.response.body',
                                'body': b'{"error":"Server is restarting, please retry"}'})
            else:
                raise


# 先初始化 Django（必须在 import routing 之前）
django_asgi_app = get_asgi_application()

# 延迟 import routing，确保 Django apps 已加载
from core.routing import websocket_urlpatterns  # noqa: E402

application = ShutdownGuardMiddleware(
    ProtocolTypeRouter({
        'http': django_asgi_app,
        'websocket': URLRouter(websocket_urlpatterns),
    })
)
