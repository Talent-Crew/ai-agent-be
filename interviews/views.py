from django.http import JsonResponse
from .utils import generate_centrifugo_token
from .models import InterviewSession
import uuid
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import JobPosting, InterviewSession

def get_interview_token(request, session_id):
    """
    Endpoint for the candidate to get their Centrifugo connection token.
    """
    try:
        session = InterviewSession.objects.get(id=session_id)
        token = generate_centrifugo_token(session.id)
        
        return JsonResponse({
            "token": token,
            "ws_url": "ws://localhost:8001/connection/websocket", 
            "channel": f"interview:{session.id}"
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