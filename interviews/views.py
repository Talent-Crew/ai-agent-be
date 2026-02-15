from .models import InterviewSession
from rest_framework.views import APIView
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from .models import JobPosting, InterviewSession, User
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from interviews.models import InterviewSession, JobPosting
from .utils import generate_centrifugo_token
from django.shortcuts import get_object_or_404
from interviews.serializers import (
    JobPostingSerializer, InterviewSessionSerializer,
    UserSerializer, UserCreateSerializer, LoginSerializer, UserSessionSerializer
)
from interviews.models import PerAnswerMetric
from django.db.models import Avg
from django.template.loader import render_to_string
from django.http import HttpResponse, FileResponse
from weasyprint import HTML, CSS
from django.conf import settings
from datetime import datetime
from django.contrib.auth import login, logout
import os


from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.shortcuts import get_object_or_404
from .models import JobPosting, InterviewSession, User
from .serializers import JobPostingSerializer, InterviewSessionSerializer

# --- JOB VIEW: NO SECURITY / EXPLICIT EMAIL LINKING ---
class JobPostingListCreateView(generics.ListCreateAPIView):
    """
    POST /api/jobs/ -> Creates a job linked by user_email in body
    GET /api/jobs/  -> Lists jobs filtered by ?email=...
    """
    queryset = JobPosting.objects.all()
    serializer_class = JobPostingSerializer
    permission_classes = [AllowAny]
    authentication_classes = [] # Bypasses Session/CSRF checks

    def get_queryset(self):
        # 1. Look for explicit email in URL parameters (?email=k@mail.com)
        email = self.request.query_params.get('email')
        if email:
            return JobPosting.objects.filter(created_by__email=email).order_by('-created_at')
        
        # 2. Fallback: If no email param, return nothing to keep data private
        return JobPosting.objects.none()
    
    def perform_create(self, serializer):
        # Manually link the user by the email passed in the JSON body
        user_email = self.request.data.get('user_email')
        user = User.objects.filter(email=user_email).first()
        serializer.save(created_by=user)


# --- SESSION VIEW: NO SECURITY / EXPLICIT EMAIL LINKING ---
class InterviewSessionCreateView(generics.CreateAPIView):
    queryset = InterviewSession.objects.all()
    serializer_class = InterviewSessionSerializer
    permission_classes = [AllowAny]
    authentication_classes = [] 
    
    def perform_create(self, serializer):
        # Link the recruiter manually via the email passed in the JSON body
        user_email = self.request.data.get('user_email')
        
        if not user_email:
            raise ValidationError({"user_email": "This field is required to link the session to a user."})
        
        user = User.objects.filter(email=user_email).first()
        
        if not user:
            raise ValidationError({"user_email": f"No user found with email: {user_email}"})
        
        # This user is passed into the serializer's validated_data
        serializer.save(created_by=user)
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


class InterviewResultsListView(APIView):
    """
    GET /api/results/?email=recruiter@company.com
    List all interview results for sessions created by the specified user.
    Returns the exact same data structure as EndInterviewSessionView.
    No authentication required - uses email parameter for filtering.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    
    def get(self, request):
        email = self.request.query_params.get('email')
        
        if not email:
            return Response({"error": "email parameter required"}, status=400)
        
        # Get completed sessions created by this user
        sessions = InterviewSession.objects.filter(
            created_by__email=email,
            is_completed=True
        ).select_related('job').order_by('-started_at')
        
        results = []
        
        for session in sessions:
            # Calculate results the same way as EndInterviewSessionView
            metrics = PerAnswerMetric.objects.filter(session=session).order_by('timestamp')
            
            if not metrics.exists():
                results.append({
                    "session_id": str(session.id),
                    "candidate": session.candidate_name,
                    "job_title": session.job.title,
                    "overall_score": 0,
                    "result_summary": "INCOMPLETE",
                    "top_weaknesses": [],
                    "timeline": [],
                    "pdf_url": None,
                    "started_at": session.started_at
                })
                continue
            
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
            
            results.append({
                "session_id": str(session.id),
                "candidate": session.candidate_name,
                "job_title": session.job.title,
                "overall_score": final_score,
                "result_summary": result_summary,
                "top_weaknesses": list(set(all_missed))[:5],
                "timeline": timeline,
                "pdf_url": f"/api/sessions/{session.id}/download-pdf/" if session.summary_pdf else None,
                "started_at": session.started_at
            })
        
        return Response({
            "email": email,
            "total_results": len(results),
            "results": results
        })


# ====== Authentication & User Management Views ======

class UserCreateView(generics.CreateAPIView):
    """
    POST /api/users/
    Create a new company admin user
    Payload: {"email": "admin@company.com", "full_name": "Admin Name", "password": "secure123", "company_name": "Acme Inc"}
    """
    queryset = User.objects.all()
    serializer_class = UserCreateSerializer
    permission_classes = [AllowAny]  # In production, restrict this or remove after first admin
    authentication_classes = []  # Bypass CSRF for Signup


class LoginView(APIView):
    """
    POST /api/auth/login/
    """
    permission_classes = [AllowAny]
    authentication_classes = []  # Bypass CSRF for Login

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            login(request, user)
            
            return Response({
                'message': 'Login successful',
                'user': UserSerializer(user).data
            })
        
        return Response(serializer.errors, status=400)
class LogoutView(APIView):
    """
    POST /api/auth/logout/
    Admin logout endpoint
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        logout(request)
        return Response({'message': 'Logout successful'})


class CurrentUserView(APIView):
    """
    GET /api/auth/me/
    Get current logged-in admin details
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


class UserSessionsView(APIView):
    """
    GET /api/auth/sessions/
    Get all interview sessions created by the logged-in admin
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        sessions = InterviewSession.objects.filter(
            created_by=request.user
        ).select_related('job').order_by('-started_at')
        
        serializer = UserSessionSerializer(sessions, many=True)
        return Response({
            'user': UserSerializer(request.user).data,
            'sessions': serializer.data,
            'total_sessions': sessions.count()
        })
