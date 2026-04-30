from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from django.views.static import serve
import os

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('core.urls')),
]

# 开发环境：serve media 文件
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# 生产环境：serve 前端静态文件
if not settings.DEBUG:
    dist_dir = os.path.join(settings.BASE_DIR, 'backend', 'static', 'dist')
    if os.path.isdir(dist_dir):
        urlpatterns += [
            re_path(r'^assets/(?P<path>.*)$', serve, {'document_root': os.path.join(dist_dir, 'assets')}),
            re_path(r'^(?!api/|admin/).*$', TemplateView.as_view(template_name='index.html')),
        ]
