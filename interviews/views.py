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
class EndInterviewSessionView(APIView):
    """
    POST /api/sessions/<session_id>/end/
    Generates a comprehensive interview report with line-by-line analysis.
    """
    def post(self, request, session_id):
        session = get_object_or_404(InterviewSession, id=session_id)
        
        # Pull all answers in chronological order
        metrics = PerAnswerMetric.objects.filter(session=session).order_by('timestamp')
        
        if not metrics.exists():
            return Response({
                "session_id": str(session.id),
                "candidate": session.candidate_name,
                "overall_score": 0,
                "result_summary": "INCOMPLETE",
                "top_weaknesses": [],
                "timeline": []
            })
        
        # Calculate scores
        avg_score = metrics.aggregate(Avg('confidence_score'))['confidence_score__avg'] or 0
        final_score = int(avg_score * 10)
        
        # Check for Cheating Flags
        cheating_count = metrics.filter(is_cheating_suspected=True).count()
        if cheating_count > 0:
            final_score = min(final_score, 30)

        # Build the Line-by-Line Report
        detailed_report = []
        for m in metrics:
            detailed_report.append({
                "id": m.id,
                "question": m.question_asked,
                "answer": m.candidate_answer,
                "score": m.confidence_score,
                "critique": m.critique,
                "ideal_answer": m.ideal_answer,
                "concepts_missed": m.technical_concepts_missed,
                "status": "PASS" if m.confidence_score and m.confidence_score >= 6 else "FAIL"
            })

        # Summary of the entire session
        all_missed_concepts = []
        for m in metrics:
            all_missed_concepts.extend(m.technical_concepts_missed)

        # Generate final recommendation
        if cheating_count > 0:
            result_summary = "REJECT - CHEATING SUSPECTED"
        elif final_score >= 70:
            result_summary = "HIRE"
        elif final_score >= 50:
            result_summary = "NEEDS REVIEW"
        else:
            result_summary = "REJECT"

        response_data = {
            "session_id": str(session.id),
            "candidate": session.candidate_name,
            "overall_score": final_score,
            "result_summary": result_summary,
            "top_weaknesses": list(set(all_missed_concepts))[:5],
            "timeline": detailed_report,  # 🚀 This is the line-by-line report
            "total_questions_answered": metrics.count(),
            "cheating_flags_triggered": cheating_count
        }

        # Mark session as completed and save overall score
        session.is_completed = True
        session.overall_score = final_score
        session.current_stage = 'completed'
        session.save()

        return Response(response_data)