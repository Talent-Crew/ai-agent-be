from django.urls import path
from . import views

urlpatterns = [
    path('api/jobs/', views.JobPostingListCreateView.as_view(), name='job-list-create'),
    path('api/sessions/', views.InterviewSessionCreateView.as_view(), name='session-create'),
    path('api/sessions/<uuid:session_id>/connect/', views.JoinInterviewSessionView.as_view(), name='session-connect'),
    path('api/sessions/<uuid:session_id>/end/', views.EndInterviewSessionView.as_view(), name='session-end'),
    path('api/sessions/<uuid:session_id>/download-pdf/', views.DownloadPDFView.as_view(), name='download-pdf'),
    path('test/bootstrap/', views.bootstrap_interview, name='test-bootstrap'),
]