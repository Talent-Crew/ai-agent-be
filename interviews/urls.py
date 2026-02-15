from django.urls import path
from . import views

urlpatterns = [
    # Job & Session Management
    path('api/jobs/', views.JobPostingListCreateView.as_view(), name='job-list-create'),
    path('api/sessions/', views.InterviewSessionCreateView.as_view(), name='session-create'),
    path('api/sessions/<uuid:session_id>/connect/', views.JoinInterviewSessionView.as_view(), name='session-connect'),
    path('api/sessions/<uuid:session_id>/end/', views.EndInterviewSessionView.as_view(), name='session-end'),
    path('api/sessions/<uuid:session_id>/download-pdf/', views.DownloadPDFView.as_view(), name='download-pdf'),
    
    # User Management
    path('api/users/', views.UserCreateView.as_view(), name='user-create'),
    
    # Authentication
    path('api/auth/login/', views.LoginView.as_view(), name='login'),
    path('api/auth/logout/', views.LogoutView.as_view(), name='logout'),
    path('api/auth/me/', views.CurrentUserView.as_view(), name='current-user'),
    path('api/auth/sessions/', views.UserSessionsView.as_view(), name='user-sessions'),
    
    # Testing
    path('test/bootstrap/', views.bootstrap_interview, name='test-bootstrap'),
]