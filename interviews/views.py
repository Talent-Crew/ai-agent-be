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
from interviews.models import PerAnswerMetric
from django.db.models import Avg


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
    job = JobPosting.objects.filter(title="Python Developer").first()
    
    if not job:
        job = JobPosting.objects.create(
            title="Python Developer", 
            stack=["Python", "Django"],
            rubric_template={
                "languages": ["Python", "JavaScript"],
                "experience_level": "Mid-Level",
                "core_skills": ["Decorators", "Memory Management", "Async Programming"],
                "evaluation_focus": ["Technical Depth", "Problem Solving"]
            }
        )
    
    session = InterviewSession.objects.create(
        job=job,
        candidate_name="Web User"
    )
    
    token = generate_centrifugo_token(user_id="user_1")
    
    return Response({
        "session_id": str(session.id),
        "token": token,
        "channel": f"interviews:interview:{session.id}",
        "status": "ready"
    })
class EndInterviewSessionView(APIView):
    def post(self, request, session_id):
        session = get_object_or_404(InterviewSession, id=session_id)
        
        session.is_completed = True
        session.current_stage = 'completed'
        session.save()
        
        metrics = PerAnswerMetric.objects.filter(session=session).order_by('timestamp')
        
        if not metrics.exists():
            return Response({
                "candidate": session.candidate_name,
                "overall_score": 0,
                "result_summary": "INCOMPLETE",
                "top_weaknesses": [],
                "timeline": []
            })

        avg_score = metrics.aggregate(Avg('confidence_score'))['confidence_score__avg'] or 0
        final_score = int(avg_score * 10)

        timeline = []
        all_missed = []
        for m in metrics:
            missed = m.technical_concepts_missed or []
            all_missed.extend(missed)
            timeline.append({
                "id": m.id,
                "question": m.question_asked,
                "answer": m.candidate_answer,
                "score": m.confidence_score,
                "critique": m.critique or "No specific critique available.",
                "ideal_answer": m.ideal_answer or "No ideal answer provided.",
                "concepts_missed": missed
            })

        return Response({
            "candidate": session.candidate_name,
            "overall_score": final_score,
            "result_summary": "HIRE" if final_score >= 70 else "REJECT",
            "top_weaknesses": list(set(all_missed))[:5],
            "timeline": timeline
        })