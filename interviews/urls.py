from django.urls import path
from .views import get_interview_token, create_test_session

urlpatterns = [
    path('token/<uuid:session_id>/', get_interview_token, name='interview_token'),
    path('test/setup/', create_test_session, name='test_setup'), 
]