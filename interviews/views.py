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
from django.template.loader import render_to_string
from django.http import HttpResponse, FileResponse
from weasyprint import HTML, CSS
from django.conf import settings
from datetime import datetime
import os


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

        result_summary = "HIRE" if final_score >= 70 else "REJECT"
        
        # Generate PDF Report
        pdf_file = self._generate_pdf_report(
            session=session,
            overall_score=final_score,
            result_summary=result_summary,
            top_weaknesses=list(set(all_missed))[:5],
            timeline=timeline
        )
        
        # Save PDF path to session
        if pdf_file:
            session.summary_pdf = pdf_file
            session.overall_score = final_score
            session.save()

        return Response({
            "candidate": session.candidate_name,
            "overall_score": final_score,
            "result_summary": result_summary,
            "top_weaknesses": list(set(all_missed))[:5],
            "timeline": timeline,
            "pdf_url": f"/api/sessions/{session_id}/download-pdf/" if pdf_file else None
        })
    
    def _generate_pdf_report(self, session, overall_score, result_summary, top_weaknesses, timeline):
        """Generate a beautiful PDF report using WeasyPrint"""
        try:
            context = {
                'candidate_name': session.candidate_name,
                'job_title': session.job.title,
                'session_id': str(session.id)[:8],
                'date': datetime.now().strftime('%B %d, %Y'),
                'overall_score': overall_score,
                'result_summary': result_summary,
                'top_weaknesses': top_weaknesses,
                'timeline': timeline,
                'total_questions': len(timeline)
            }
            
            # Render HTML template
            html_string = render_to_string('interviews/scorecard.html', context)
            
            # Create media directory if it doesn't exist
            media_root = settings.MEDIA_ROOT
            reports_dir = os.path.join(media_root, 'reports')
            os.makedirs(reports_dir, exist_ok=True)
            
            # Generate PDF filename
            filename = f"scorecard_{session.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            filepath = os.path.join(reports_dir, filename)
            
            # Convert HTML to PDF
            HTML(string=html_string).write_pdf(filepath)
            
            # Return relative path for FileField
            return f"reports/{filename}"
            
        except Exception as e:
            print(f"❌ PDF Generation Error: {e}")
            return None


class DownloadPDFView(APIView):
    """
    GET /api/sessions/<session_id>/download-pdf/
    Download the generated PDF scorecard
    """
    def get(self, request, session_id):
        session = get_object_or_404(InterviewSession, id=session_id)
        
        if not session.summary_pdf:
            return Response({
                "error": "PDF not generated yet. Please complete the interview first."
            }, status=404)
        
        # Get the full file path
        pdf_path = os.path.join(settings.MEDIA_ROOT, str(session.summary_pdf))
        
        if not os.path.exists(pdf_path):
            return Response({
                "error": "PDF file not found on server."
            }, status=404)
        
        # Return PDF file
        response = FileResponse(open(pdf_path, 'rb'), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Interview_Scorecard_{session.candidate_name.replace(" ", "_")}.pdf"'
        return response
