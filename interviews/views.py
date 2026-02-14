from .models import InterviewSession
from rest_framework.views import APIView
from rest_framework import generics
from rest_framework.response import Response
from .models import JobPosting, InterviewSession
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from interviews.models import InterviewSession, JobPosting
from .utils import generate_centrifugo_token
from django.shortcuts import get_object_or_404
from interviews.serializers import JobPostingSerializer, InterviewSessionSerializer


class JobPostingListCreateView(generics.ListCreateAPIView):
    """
    POST /api/jobs/ -> Company creates a new job & rubric
    GET /api/jobs/  -> List all active jobs
    """
    queryset = JobPosting.objects.all()
    serializer_class = JobPostingSerializer

class InterviewSessionCreateView(generics.CreateAPIView):
    """
    POST /api/sessions/ -> Company generates an interview link for a candidate
    Payload: {"job_id": "uuid-string", "candidate_name": "John Doe"}
    """
    queryset = InterviewSession.objects.all()
    serializer_class = InterviewSessionSerializer

class JoinInterviewSessionView(APIView):
    """
    GET /api/sessions/<session_id>/connect/
    The React frontend calls this right before the interview starts 
    to get the secure Centrifugo token and WebSocket URL.
    """
    def get(self, request, session_id):
        session = get_object_or_404(InterviewSession, id=session_id)
        
        # Create a unique Centrifugo user ID using the session & candidate name
        safe_name = session.candidate_name.replace(" ", "_").lower()
        user_id = f"cand_{safe_name}_{str(session.id)[:8]}"
        
        token = generate_centrifugo_token(user_id=user_id)
        
        return Response({
            "session_id": str(session.id),
            "candidate_name": session.candidate_name,
            "job_title": session.job.title,
            "token": token,
            "ws_url": "ws://192.168.0.97:8001/connection/websocket",
            "channel": f"interviews:interview:{session.id}",
            "status": "ready"
        })
@api_view(['POST'])
@permission_classes([AllowAny])
def bootstrap_interview(request):
    # 1. Use .filter().first() instead of get_or_create
    # This safely handles finding 0, 1, or 100 duplicates.
    job = JobPosting.objects.filter(title="Python Developer").first()
    
    if not job:
        job = JobPosting.objects.create(
            title="Python Developer", 
            stack=["Python", "Django"],
            rubric_template={"focus": "decorators and memory management"}
        )
    
    # 2. Create the unique interview session
    session = InterviewSession.objects.create(
        job=job,
        candidate_name="Web User"
    )
    
    # 3. Generate token
    token = generate_centrifugo_token(user_id="user_1")
    
    return Response({
        "session_id": str(session.id),
        "token": token,
        "channel": f"interviews:interview:{session.id}",
        "status": "ready"
    })