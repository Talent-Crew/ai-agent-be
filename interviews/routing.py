from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/interview/(?P<session_id>[^/]+)/$', consumers.GeminiInterviewConsumer.as_asgi()),
]