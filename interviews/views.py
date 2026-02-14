from django.http import JsonResponse
from .utils import generate_centrifugo_token
from .models import InterviewSession
import uuid
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import JobPosting, InterviewSession
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from interviews.models import InterviewSession, JobPosting
from .utils import generate_centrifugo_token

def get_interview_token(request, session_id):
    try:
        session = InterviewSession.objects.get(id=session_id)
        token = generate_centrifugo_token(session.id)
        
        return JsonResponse({
            "token": token,
            "ws_url": "ws://localhost:8001/connection/websocket", 
            "channel": f"interviews:interview:{session.id}" 
        })
    except InterviewSession.DoesNotExist:
        return JsonResponse({"error": "Session not found"}, status=404)
    
@api_view(['POST'])
def create_test_session(request):
    # 1. Create a Master Job with a Rubric
    job, _ = JobPosting.objects.get_or_create(
        title="Senior Python Developer",
        defaults={
            "stack": ["Python", "Django"],
            "rubric_template": {
                "metrics": [
                    {"name": "Python Mastery", "criteria": "Explain decorators.", "threshold": 7},
                    {"name": "Architecture", "criteria": "Explain Monoliths.", "threshold": 8}
                ]
            }
        }
    )
    
    # 2. Create the Session
    session = InterviewSession.objects.create(
        job=job,
        candidate_name="Test Bot"
    )
    
    return Response({"session_id": str(session.id)})


@api_view(['POST'])
@permission_classes([AllowAny])
def bootstrap_interview(request):
    # 1. Use 'JobPosting' instead of 'Job'
    job, _ = JobPosting.objects.get_or_create(
        title="Python Developer", 
        defaults={
            "stack": ["Python", "Django"],
            "rubric_template": {
                "focus": "Focus on decorators and memory management."
            }
        }
    )
    
    # 2. Create the session (Ensure field names match your model)
    session = InterviewSession.objects.create(
        job=job,
        candidate_name="Web User" # candidate_name is required in your model
    )
    
    # 3. Generate token
    token = generate_centrifugo_token(user_id="user_1")
    
    return Response({
        "session_id": str(session.id),
        "token": token,
        "channel": f"interviews:interview:{session.id}",
        "status": "ready"
    })