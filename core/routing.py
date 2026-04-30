"""
WebSocket 路由定义。
"""
from django.urls import path

from .consumers import ExecutionConsumer

websocket_urlpatterns = [
    path('ws/execution/<int:execution_id>/', ExecutionConsumer.as_asgi()),
]
