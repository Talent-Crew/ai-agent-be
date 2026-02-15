# TalentCrew - AI-Powered Technical Interview Platform

> **⚡ 24-Hour MVP** | This is a rapid prototype built in 24 hours with simplified authentication (no permission classes, no CSRF). Uses email-based filtration instead of token authorization. See [Security & Authentication Model](#️-important-security--authentication-model) for details.

## 📋 Table of Contents
- [Overview](#overview)
- [⚠️ Important: Security & Authentication Model](#️-important-security--authentication-model)
- [Core Features](#core-features)
- [Architecture](#architecture)
- [Detailed Feature Documentation](#detailed-feature-documentation)
  - [1. Role Selection & Question Bank Governance](#1-role-selection--question-bank-governance)
  - [2. Candidate Response System (Text & Voice)](#2-candidate-response-system-text--voice)
  - [3. Intelligent Follow-up System](#3-intelligent-follow-up-system)
  - [4. Anti-Cheating Detection System](#4-anti-cheating-detection-system)
  - [5. Confidence Tracking Per Answer](#5-confidence-tracking-per-answer)
  - [6. Scorecard Generation](#6-scorecard-generation)
  - [7. Bias/Drift Monitoring](#7-biasdrift-monitoring)
  - [8. Dashboard & Analytics](#8-dashboard--analytics)
- [Data Models](#data-models)
- [API Endpoints](#api-endpoints)
- [Real-Time Communication](#real-time-communication)
- [Setup & Installation](#setup--installation)

---

## Overview

TalentCrew is an advanced AI-powered interview platform that conducts real-time technical interviews using voice and text interactions. The system uses Google's Gemini AI for intelligent questioning, Deepgram for speech recognition and synthesis, and implements sophisticated anti-cheating mechanisms.

---

## ⚠️ Important: Security & Authentication Model

**🚀 Built in 24 Hours - MVP Architecture**

This platform was developed as a rapid prototype in **24 hours** and uses a **simplified authentication model** for quick deployment and testing:

### Authentication Approach
- **No `IsAuthenticated` permission classes** on most endpoints
- **No CSRF protection** enabled (for easier frontend integration during development)
- **Email-based filtration** instead of token-based authorization
- **Public access with data isolation** - anyone can access endpoints, but data is filtered by user email

### How Access Works

1. **Sign Up / Login** - Create an account and log in to get a session cookie:
   ```http
   POST /api/users/          # Sign up
   POST /api/auth/login/     # Login (establishes session)
   ```

2. **Access Your Data** - Use your email to filter your resources:
   ```http
   GET /api/jobs/?email=your@email.com           # Your jobs
   GET /api/results/?email=your@email.com        # Your interview results
   ```

3. **Create Resources** - Pass your email in the request body:
   ```json
   POST /api/jobs/
   {
     "title": "Python Developer",
     "user_email": "your@email.com",
     ...
   }
   ```

### Why This Architecture?

✅ **Speed**: No complex JWT/OAuth implementation needed for MVP  
✅ **Simplicity**: Frontend doesn't need token management  
✅ **Testability**: Easy to test with tools like Postman/curl  
✅ **Data Isolation**: Users only see their own data via email filtering  

### Production Recommendations

For production deployment, you should add:
- ✋ Proper `IsAuthenticated` permission classes
- ✋ CSRF protection enabled
- ✋ JWT/OAuth token authentication
- ✋ Rate limiting and API throttling
- ✋ Input validation and sanitization
- ✋ HTTPS enforcement

---

## Core Features

✅ **Dynamic Role Selection** with customizable evaluation rubrics  
✅ **Voice & Text Interview Mode** with real-time transcription  
✅ **Context-Aware Follow-ups** that adapt to candidate responses  
✅ **Multi-Layer Anti-Cheating System** with pause analysis & behavioral tracking  
✅ **Granular Confidence Scoring** for each answer (1-10 scale)  
✅ **Question Bank Governance** through structured rubric templates  
✅ **Bias Detection & Monitoring** with flagging mechanisms  
✅ **Automated PDF Scorecard Generation**  
✅ **Admin Dashboard** for session management and analytics  

---

## Architecture

### Tech Stack
- **Backend**: Django 6.0.2 + Django REST Framework
- **Real-Time**: Django Channels + Centrifugo (WebSocket broker)
- **AI Engine**: Google Gemini 2.5 Flash
- **Speech**: Deepgram (STT + TTS)
- **Database**: SQLite (development) / Postgres (production-ready)
- **PDF Generation**: WeasyPrint

### System Flow
```
Candidate Browser → WebSocket → Django Channels → Deepgram STT
                                      ↓
                              InterviewerBrain (Gemini AI)
                                      ↓
                      Anti-Cheating Analysis + Scoring
                                      ↓
                         Deepgram TTS → Centrifugo
                                      ↓
                            React Frontend (Audio Playback)
```

---

## Detailed Feature Documentation

### 1. Role Selection & Question Bank Governance

#### **Database Model**
File: [interviews/models.py](interviews/models.py)

```python
class JobPosting(models.Model):
    title = models.CharField(max_length=255)
    stack = models.JSONField(default=list)
    rubric_template = models.JSONField(default=dict)
    created_by = models.ForeignKey(User)
```

#### **Rubric Template Structure**
The system uses a structured JSON rubric that governs the entire interview:

```json
{
  "languages": ["Python", "JavaScript", "SQL"],
  "experience_level": "Mid-Level",
  "core_skills": [
    "Database Query Optimization",
    "RESTful API Design",
    "State Management",
    "Caching Strategies"
  ],
  "evaluation_focus": [
    "Problem Solving",
    "Technical Depth",
    "Code Quality"
  ]
}
```

#### **How It Works**
1. **Recruiter creates a job** via `/api/jobs/` with customized rubric
2. **InterviewerBrain reads rubric** on initialization:
   ```python
   # File: interviews/services.py
   def __init__(self, session_id):
       rubric = self.session.job.rubric_template
       self.languages = rubric.get('languages')
       self.core_skills = rubric.get('core_skills')
       self.level = rubric.get('experience_level')
   ```
3. **Questions are dynamically generated** based on rubric constraints
4. **Coverage tracking** ensures all languages/skills are tested

#### **Governance Features**
- **Skills must be covered**: AI pivots if candidate lacks knowledge in one area
- **Language mixing**: Questions span multiple technologies listed
- **Experience-appropriate**: Questions adapt to seniority level
- **Consistency**: All candidates for same role face similar coverage

#### **API Endpoint**
```http
POST /api/jobs/
Content-Type: application/json

{
  "title": "Senior Python Developer",
  "stack": ["Python", "Django", "Postgres"],
  "rubric_template": { ... },
  "user_email": "recruiter@company.com"
}
```

---

### 2. Candidate Response System (Text & Voice)

#### **Voice Pipeline Components**

##### **A. Real-Time Transcription**
File: [interviews/consumers.py](interviews/consumers.py)

```python
class UnifiedInterviewConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Initialize Deepgram Live Transcription
        self.dg_connection = self.dg_client.listen.live.v("1")
        
        def on_transcript(self_dg, result, **kwargs):
            sentence = result.channel.alternatives[0].transcript
            self.transcript_buffer += sentence + " "
            logger.info(f"📝 Captured: {sentence}")
```

**How it works:**
1. Candidate speaks into microphone
2. Browser captures audio chunks (PCM 16-bit)
3. WebSocket streams audio to Django Channels
4. Django relays to Deepgram Live API
5. Real-time transcription accumulates in buffer
6. Candidate clicks "Done Speaking" → triggers processing

##### **B. Text-to-Speech Response**
File: [interviews/consumers.py](interviews/consumers.py)

```python
async def speak_text(self, text):
    # Generate audio via Deepgram Aura TTS
    options = SpeakOptions(model="aura-asteria-en", encoding="mp3")
    response = await asyncio.to_thread(
        self.dg_client.speak.v("1").stream, 
        {"text": text}, 
        options
    )
    
    # Stream audio to frontend via Centrifugo
    audio_bytes = b"".join(response.stream)
    b64_audio = base64.b64encode(audio_bytes).decode('utf-8')
    
    await self.centrifugo.publish(
        f"interviews:interview:{self.session_id}",
        {"type": "tts_audio_complete", "audio": b64_audio}
    )
```

#### **WebSocket Communication**
File: [interviews/routing.py](interviews/routing.py)

```python
websocket_urlpatterns = [
    re_path(r'ws/interview/(?P<session_id>[^/]+)/?$', 
            UnifiedInterviewConsumer.as_asgi()),
]
```

#### **Session Initialization**
```javascript
// Frontend workflow:
1. Get token: GET /api/sessions/{session_id}/connect/
2. Connect WebSocket: ws://host/ws/interview/{session_id}
3. Send audio chunks continuously
4. Signal completion: {"type": "user_finished_speaking"}
```

---

### 3. Intelligent Follow-up System

#### **Single-Pass Brain Architecture**
File: [interviews/services.py](interviews/services.py)

The system uses a revolutionary **single LLM call** that evaluates the answer AND generates the next question simultaneously:

```python
async def get_answer(self, user_text, pause_duration=0):
    prompt = f"""
    Candidate: {self.session.candidate_name}
    Languages: {languages_str}
    Core Skills: {skills_str}
    Current Drill Depth: {self.current_topic_drill_depth}
    Pause Duration: {pause_duration}s
    
    --- PREVIOUS HISTORY ---
    {history_context}
    
    --- CURRENT EXCHANGE ---
    Last Question: {self.last_question_asked}
    Candidate Answer: {user_text}
    
    YOUR TASK: Evaluate AND generate next question in ONE response.
    
    STEP 1: GRADE THE ANSWER (1-10)
    STEP 2: DECIDE NEXT QUESTION BASED ON SCORE
    STEP 3: FORMAT JSON RESPONSE
    """
```

#### **Decision Logic**
The AI decides follow-up strategy based on answer quality:

| Score | Action | Pivot? | Drill Depth Change |
|-------|--------|--------|-------------------|
| 8-10 | Deep dive follow-up on same topic | No | +1 (up to 2) |
| 8-10 + depth ≥ 2 | Acknowledge, move to new skill | Yes | Reset to 0 |
| 5-7 | Acknowledge, next skill | Yes | Reset to 0 |
| 1-4 | Gentle pivot to different skill | Yes | Reset to 0 |
| Off-topic | Stern warning, force pivot | Yes | Reset to 0 |
| Needs clarification | Rephrase same question | No | No change |

#### **Context-Aware Questioning**
```python
def _get_history_context(self):
    # Retrieve last 3 Q&A pairs
    metrics = PerAnswerMetric.objects.filter(session=self.session) \
                                     .order_by('-timestamp')[:3]
    
    context = ""
    for metric in metrics:
        context += f"Previous Question: {metric.question_asked}\n"
        context += f"Candidate Answered: {metric.candidate_answer}\n"
        context += f"Score: {metric.confidence_score}/10\n\n"
    return context
```

**Benefits:**
- AI avoids repeating topics
- Follows natural conversation flow
- Adapts difficulty based on performance
- Ensures comprehensive skill coverage

#### **Turn Management**
```python
self.turn_count += 1

if self.turn_count >= self.max_turns:
    return "FINISH_INTERVIEW: It's been great chatting..."
```

Default: **6 turns** (configurable via `self.max_turns`)

---

### 4. Anti-Cheating Detection System

TalentCrew implements a **multi-layer anti-cheating system** that detects suspicious behavior in real-time.

#### **Detection Mechanisms**

##### **A. Pause Duration Analysis**
File: [interviews/consumers.py](interviews/consumers.py)

```python
class UnifiedInterviewConsumer:
    async def speak_text(self, text):
        # Mark when AI finishes speaking
        self.ai_finished_speaking_time = time.time()
        self.user_first_word_time = 0
    
    def on_transcript(self_dg, result, **kwargs):
        # Mark when candidate starts speaking
        if self.user_first_word_time == 0:
            self.user_first_word_time = time.time()
    
    async def receive(self, text_data=None):
        # Calculate delay
        pause_duration = round(
            self.user_first_word_time - self.ai_finished_speaking_time, 
            2
        )
```

**Scoring Logic:**
- **Pause > 8 seconds + robotic answer** → Flags as cheating
- Passed to Gemini for behavioral analysis

##### **B. LLM-Based Behavioral Analysis**
File: [interviews/services.py](interviews/services.py)

```python
prompt = f"""
Time taken before candidate started speaking: {pause_duration}s

STEP 1: GRADE THE ANSWER
- is_cheating: TRUE if pause_duration > 8s AND answer sounds 
  robotic/textbook, OR if massive unnatural spike in fluency 
  compared to history.
"""

# Gemini returns structured response:
{
  "is_cheating": true/false,
  "understanding_score": 1-10,
  "explainability_score": 1-10
}
```

**Behavioral Indicators:**
1. **Long pause + perfect answer** → Likely reading from ChatGPT
2. **Sudden fluency spike** → Comparing to conversation history
3. **Textbook language** → Generic, non-personalized responses
4. **Off-topic rambling** → Attempting to dodge question

##### **C. Data Persistence**
File: [interviews/models.py](interviews/models.py)

```python
class PerAnswerMetric(models.Model):
    is_cheating_suspected = models.BooleanField(default=False)
    cheating_reason = models.CharField(max_length=255, null=True)
```

Stored for post-interview review and appeals.

#### **Cheating Response Protocol**
```python
if is_cheating:
    logger.warning(f"""
    🚨 CHEATING SUSPECTED 
    Score: {score}/10 
    Pause: {pause_duration}s 
    Answer: "{user_text[:100]}..."
    """)
    
    # AI's next question gently confronts:
    # "Interesting answer. Can you explain that in your own words?"
```

#### **Logging & Audit Trail**
Every suspicious event is logged with:
- Timestamp
- Pause duration
- Full answer text
- Score given
- Question asked

---

### 5. Confidence Tracking Per Answer

#### **Dual Scoring System**
File: [interviews/services.py](interviews/services.py)

Each answer receives **TWO independent scores** from Gemini:

```json
{
  "understanding_score": 8,      // Technical correctness (1-10)
  "explainability_score": 7,     // Communication clarity (1-10)
  "confidence_score": 8          // Average stored in DB
}
```

#### **Scoring Rubric**
Provided to AI:

```python
"""
STEP 1: GRADE THE ANSWER (1-10 for understanding, 1-10 for explainability)

- Score 8-10 (EXCELLENT): 
  Specific architectural decisions, real-world tools, 
  clear problem-solving approach.

- Score 5-7 (AVERAGE): 
  Technically correct but shallow. Lacks depth or examples.

- Score 1-4 (POOR): 
  Incorrect, dodges question, or zero technical knowledge.
"""
```

#### **Database Storage**
File: [interviews/models.py](interviews/models.py)

```python
class PerAnswerMetric(models.Model):
    question_asked = models.TextField()
    candidate_answer = models.TextField()
    confidence_score = models.IntegerField()  # 1-10
    evidence_extracted = models.TextField()
    critique = models.TextField()
    ideal_answer = models.TextField()
    technical_concepts_missed = models.JSONField(default=list)
    timestamp = models.DateTimeField(auto_now_add=True)
```

#### **Evidence Extraction**
```python
# Gemini extracts exact quotes as evidence
{
  "evidence_extracted": "I use indexes and caching to optimize queries",
  "critique": "Didn't mention query plan analysis or N+1 problem",
  "ideal_answer": "Analyze execution plans with EXPLAIN, add indexes...",
  "technical_concepts_missed": [
    "Query Plan Analysis",
    "N+1 Query Detection",
    "Connection Pooling"
  ]
}
```

#### **Logging**
```python
logger.info(f"""
📊 GEMINI EVALUATION 
Understanding: {score}/10 
Explainability: {explainability}/10 
Cheating: {is_cheating} 
Off-Topic: {is_off_topic}
💬 Evidence: "{data.get('evidence_extracted')}"
""")
```

#### **Final Score Calculation**
File: [interviews/views.py](interviews/views.py)

```python
class EndInterviewSessionView:
    def post(self, request, session_id):
        metrics = PerAnswerMetric.objects.filter(session=session) \
                                         .order_by('timestamp')
        
        # Average score across all answers
        avg_score = metrics.aggregate(Avg('confidence_score')) \
                          ['confidence_score__avg']
        
        final_score = int(avg_score * 10)  # Scale to 0-100
        
        result_summary = "HIRE" if final_score >= 70 else "REJECT"
```

---

### 6. Scorecard Generation

#### **PDF Generation Workflow**
File: [interviews/views.py](interviews/views.py)

```python
class EndInterviewSessionView(APIView):
    def post(self, request, session_id):
        session = get_object_or_404(InterviewSession, id=session_id)
        
        # Mark interview complete
        session.is_completed = True
        session.current_stage = 'completed'
        
        # Calculate final score
        metrics = PerAnswerMetric.objects.filter(session=session)
        avg_score = metrics.aggregate(Avg('confidence_score'))
        final_score = int(avg_score['confidence_score__avg'] * 10)
        
        # Collect weaknesses
        all_missed = []
        for m in metrics:
            all_missed.extend(m.technical_concepts_missed or [])
        
        # Generate PDF
        pdf_file = self._generate_pdf_report(
            session=session,
            overall_score=final_score,
            result_summary="HIRE" if final_score >= 70 else "REJECT",
            top_weaknesses=list(set(all_missed))[:5],
            timeline=[...]
        )
        
        session.summary_pdf = pdf_file
        session.save()
```

#### **Template Structure**
File: [interviews/templates/interviews/scorecard.html](interviews/templates/interviews/scorecard.html)

```html
<!DOCTYPE html>
<html>
<head>
    <title>Interview Scorecard - {{ candidate_name }}</title>
    <style>
        /* Professional styling with gradients, score circles */
    </style>
</head>
<body>
    <!-- Header: Company branding -->
    <div class="header">
        <div class="company-logo">TalentCrew</div>
        <div class="report-title">Technical Interview Report</div>
    </div>
    
    <!-- Candidate Info -->
    <div class="candidate-section">
        <h1>{{ candidate_name }}</h1>
        <div class="job-title">{{ job_title }}</div>
        <div class="meta-info">
            <span>Session: {{ session_id }}</span>
            <span>Date: {{ date }}</span>
            <span>Questions: {{ total_questions }}</span>
        </div>
    </div>
    
    <!-- Score Overview -->
    <div class="score-overview">
        <div class="score-circle">
            <div class="score-value">{{ overall_score }}</div>
            <div class="score-label">Overall</div>
        </div>
        <div class="recommendation-badge {{ result_summary|lower }}">
            {{ result_summary }}
        </div>
    </div>
    
    <!-- Top Weaknesses -->
    <div class="weaknesses-section">
        {% for weakness in top_weaknesses %}
        <div class="weakness-item">{{ weakness }}</div>
        {% endfor %}
    </div>
    
    <!-- Q&A Timeline -->
    {% for qa in timeline %}
    <div class="qa-card">
        <div class="question">Q: {{ qa.question }}</div>
        <div class="answer">A: {{ qa.answer }}</div>
        <div class="score-badge">{{ qa.score }}/10</div>
        <div class="critique">{{ qa.critique }}</div>
        <div class="ideal">Ideal: {{ qa.ideal_answer }}</div>
        <div class="missed-concepts">
            {% for concept in qa.concepts_missed %}
            <span>{{ concept }}</span>
            {% endfor %}
        </div>
    </div>
    {% endfor %}
</body>
</html>
```

#### **PDF Generation Library**
```python
from weasyprint import HTML

def _generate_pdf_report(self, session, ...):
    context = { ... }
    html_string = render_to_string('interviews/scorecard.html', context)
    
    # Create reports directory
    reports_dir = os.path.join(settings.MEDIA_ROOT, 'reports')
    os.makedirs(reports_dir, exist_ok=True)
    
    # Generate PDF
    filename = f"scorecard_{session.id}_{datetime.now()}.pdf"
    filepath = os.path.join(reports_dir, filename)
    HTML(string=html_string).write_pdf(filepath)
    
    return f"reports/{filename}"
```

#### **Download Endpoint**
```http
GET /api/sessions/{session_id}/download-pdf/
```

```python
class DownloadPDFView(APIView):
    def get(self, request, session_id):
        session = get_object_or_404(InterviewSession, id=session_id)
        
        if not session.summary_pdf:
            return Response({"error": "PDF not generated yet"}, status=404)
        
        pdf_path = os.path.join(settings.MEDIA_ROOT, str(session.summary_pdf))
        
        response = FileResponse(open(pdf_path, 'rb'), 
                                content_type='application/pdf')
        response['Content-Disposition'] = \
            f'attachment; filename="Interview_Scorecard_{session.candidate_name}.pdf"'
        return response
```

---

### 7. Bias/Drift Monitoring

#### **Bias Detection**
File: [interviews/models.py](interviews/models.py)

```python
class PerAnswerMetric(models.Model):
    bias_flag = models.BooleanField(default=False)
```

#### **LLM Bias Analysis**
File: [interviews/services.py](interviews/services.py)

Gemini is instructed to detect bias in its own evaluation:

```python
response_schema = {
    "type": "OBJECT",
    "properties": {
        "bias_flag": {"type": "BOOLEAN"}  # Auto-flagged by AI
    }
}
```

The AI flags bias if:
- Question assumes gender/ethnicity/age
- Evaluation penalizes non-native speakers unfairly
- Cultural knowledge affects scoring

#### **Bias Monitoring Dashboard**
```python
# Query biased evaluations
biased_answers = PerAnswerMetric.objects.filter(bias_flag=True)

# Aggregate by session
bias_by_session = biased_answers.values('session__candidate_name') \
                                .annotate(bias_count=Count('id'))
```

#### **Drift Detection**
**Concept:** Over time, AI evaluation standards may "drift" (become stricter or more lenient).

**Implementation:**
```python
# Compare average scores over time
from django.db.models import Avg
from datetime import timedelta

def detect_score_drift():
    # Last 30 days
    recent = PerAnswerMetric.objects.filter(
        timestamp__gte=timezone.now() - timedelta(days=30)
    ).aggregate(Avg('confidence_score'))
    
    # Previous 30 days
    older = PerAnswerMetric.objects.filter(
        timestamp__gte=timezone.now() - timedelta(days=60),
        timestamp__lt=timezone.now() - timedelta(days=30)
    ).aggregate(Avg('confidence_score'))
    
    drift = recent['confidence_score__avg'] - older['confidence_score__avg']
    
    if abs(drift) > 1.5:  # More than 15% change
        logger.warning(f"⚠️ Score drift detected: {drift}")
```

#### **Audit Trail**
Every evaluation includes:
- Full conversation history
- AI's reasoning (stored in `critique`)
- Evidence quotes
- Bias flag
- Timestamp

Allows for **human review** of flagged cases.

---

### 8. Dashboard & Analytics

#### **Admin Session Management**
File: [interviews/views.py](interviews/views.py)

```python
class UserSessionsView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        # Get all sessions created by logged-in recruiter
        sessions = InterviewSession.objects.filter(
            created_by=request.user
        ).select_related('job').order_by('-started_at')
        
        return Response({
            'user': UserSerializer(request.user).data,
            'sessions': UserSessionSerializer(sessions, many=True).data,
            'total_sessions': sessions.count()
        })
```

**API Endpoint:**
```http
GET /api/auth/sessions/
Authorization: Session Cookie

Response:
{
  "user": {
    "id": "uuid",
    "email": "recruiter@company.com",
    "full_name": "Jane Doe",
    "company_name": "Acme Inc"
  },
  "sessions": [
    {
      "id": "session-uuid",
      "job_title": "Senior Python Developer",
      "candidate_name": "John Smith",
      "overall_score": 85,
      "is_completed": true,
      "started_at": "2026-02-15T10:30:00Z",
      "current_stage": "completed"
    }
  ],
  "total_sessions": 42
}
```

#### **Analytics Queries**

##### **Average Score by Job Title**
```python
from django.db.models import Avg

avg_scores = InterviewSession.objects.filter(
    is_completed=True
).values('job__title').annotate(
    avg_score=Avg('overall_score'),
    session_count=Count('id')
)

# Result:
# [
#   {'job__title': 'Python Developer', 'avg_score': 72.5, 'session_count': 15},
#   {'job__title': 'Full Stack Engineer', 'avg_score': 68.3, 'session_count': 23}
# ]
```

##### **Cheating Rate by Role**
```python
cheating_stats = PerAnswerMetric.objects.values(
    'session__job__title'
).annotate(
    total_answers=Count('id'),
    cheating_count=Count('id', filter=Q(is_cheating_suspected=True))
).annotate(
    cheating_rate=F('cheating_count') * 100.0 / F('total_answers')
)
```

##### **Concept Gap Analysis**
```python
# Most commonly missed concepts across all candidates
from collections import Counter

all_missed_concepts = []
for metric in PerAnswerMetric.objects.all():
    all_missed_concepts.extend(metric.technical_concepts_missed or [])

concept_gaps = Counter(all_missed_concepts).most_common(10)

# Result:
# [
#   ('Database Indexing', 42),
#   ('N+1 Query Problem', 38),
#   ('Connection Pooling', 31),
#   ...
# ]
```

#### **Session Detail View**
```python
@api_view(['GET'])
def session_detail(request, session_id):
    session = get_object_or_404(InterviewSession, id=session_id)
    
    answers = PerAnswerMetric.objects.filter(
        session=session
    ).order_by('timestamp')
    
    return Response({
        'session': InterviewSessionSerializer(session).data,
        'answers': [{
            'question': a.question_asked,
            'answer': a.candidate_answer,
            'score': a.confidence_score,
            'critique': a.critique,
            'ideal_answer': a.ideal_answer,
            'is_cheating_suspected': a.is_cheating_suspected,
            'bias_flag': a.bias_flag,
            'concepts_missed': a.technical_concepts_missed
        } for a in answers],
        'cheating_incidents': answers.filter(is_cheating_suspected=True).count(),
        'bias_incidents': answers.filter(bias_flag=True).count()
    })
```

---

## Data Models

### **User Model**
File: [interviews/models.py](interviews/models.py)

```python
class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    company_name = models.CharField(max_length=255, blank=True, null=True)
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']
```

### **JobPosting Model**
```python
class JobPosting(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    title = models.CharField(max_length=255)
    stack = models.JSONField(default=list)  # ["Python", "Django"]
    rubric_template = models.JSONField(default=dict)  # Evaluation criteria
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
```

### **InterviewSession Model**
```python
class InterviewSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    job = models.ForeignKey(JobPosting, on_delete=models.CASCADE)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL)
    candidate_name = models.CharField(max_length=255)
    
    current_stage = models.CharField(max_length=50, default='intro')
    is_completed = models.BooleanField(default=False)
    
    overall_score = models.FloatField(null=True, blank=True)
    summary_pdf = models.FileField(upload_to='reports/', null=True, blank=True)
    
    started_at = models.DateTimeField(auto_now_add=True)
```

### **PerAnswerMetric Model**
```python
class PerAnswerMetric(models.Model):
    session = models.ForeignKey(InterviewSession, related_name='answers')
    
    question_asked = models.TextField()
    candidate_answer = models.TextField()
    
    confidence_score = models.IntegerField(null=True, blank=True)  # 1-10
    evidence_extracted = models.TextField(null=True, blank=True)
    
    critique = models.TextField(null=True, blank=True)
    ideal_answer = models.TextField(null=True, blank=True)
    technical_concepts_missed = models.JSONField(default=list)
    
    is_cheating_suspected = models.BooleanField(default=False)
    cheating_reason = models.CharField(max_length=255, null=True, blank=True)
    bias_flag = models.BooleanField(default=False)
    
    timestamp = models.DateTimeField(auto_now_add=True)
```

### **EvidenceSnippet Model** (Currently unused, reserved for future)
```python
class EvidenceSnippet(models.Model):
    session = models.ForeignKey(InterviewSession, related_name='evidence')
    metric_name = models.CharField(max_length=100)
    snippet = models.TextField()
    confidence_score = models.IntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)
```

---

## API Endpoints

**Authentication Model**: Most endpoints use email-based filtration instead of token authorization. See [Security & Authentication Model](#️-important-security--authentication-model) section.

### **Job Management**
```http
POST   /api/jobs/               # Create job posting (requires user_email in body)
GET    /api/jobs/?email=...     # List jobs by recruiter email (no auth, filtered by email param)
```

### **Session Management**
```http
POST   /api/sessions/                          # Create interview session (requires user_email in body)
GET    /api/sessions/{uuid}/connect/           # Get WebSocket token (no auth)
POST   /api/sessions/{uuid}/end/               # End interview & generate PDF (no auth)
GET    /api/sessions/{uuid}/download-pdf/      # Download scorecard PDF (no auth)
```

### **Results**
```http
GET    /api/results/?email=...                 # List all interview results (no auth, filtered by email param)
```

### **Authentication** (Session-based, with CSRF disabled)
```http
POST   /api/users/              # Sign up (create recruiter account)
POST   /api/auth/login/         # Login (establishes session cookie)
POST   /api/auth/logout/        # Logout (requires session)
GET    /api/auth/me/            # Get current user details (requires session)
GET    /api/auth/sessions/      # Get all sessions for logged-in recruiter (requires session)
```

### **WebSocket**
```
WS     ws://host/ws/interview/{session_id}/    # Real-time interview connection (no auth)
```

---

## Real-Time Communication

### **Centrifugo Publishing**
File: [interviews/centrifugo_client.py](interviews/centrifugo_client.py)

```python
class CentrifugoPublisher:
    async def publish_text_message(self, session_id, message):
        channel = f"interviews:interview:{session_id}"
        payload = {
            "type": "text_message",
            "message": message,
            "sender": "interviewer"
        }
        await self.publish(channel, payload)
    
    async def publish_event(self, session_id, event_type):
        channel = f"interviews:interview:{session_id}"
        payload = {
            "type": "event",
            "event": event_type  # "speech_start", "speech_end", "interview_complete"
        }
        await self.publish(channel, payload)
```

### **Frontend Integration**
```javascript
// React frontend connects to Centrifugo
const client = new Centrifuge('ws://host:8001/connection/websocket');
client.setToken(tokenFromAPI);

const sub = client.newSubscription(`interviews:interview:${sessionId}`);

sub.on('publication', (ctx) => {
    if (ctx.data.type === 'text_message') {
        displayMessage(ctx.data.message);
    } else if (ctx.data.type === 'tts_audio_complete') {
        playAudio(ctx.data.audio);  // Base64 MP3
    } else if (ctx.data.type === 'interview_complete') {
        showScorecard();
    }
});

sub.subscribe();
client.connect();
```

---

## Setup & Installation

### **1. Clone Repository**
```bash
git clone <repository-url>
cd talentcrew
```

### **2. Environment Variables**
Create `.env` file:
```bash
GEMINI_API_KEY=your_gemini_api_key
DEEPGRAM_API_KEY=your_deepgram_api_key
CENTRIFUGO_SECRET=your_centrifugo_secret
CENTRIFUGO_API_KEY=your_centrifugo_api_key
CENTRIFUGO_HOST=http://localhost:8001
```

### **3. Docker Setup**
```bash
docker-compose up --build -d
```

### **4. Run Migrations**
```bash
docker compose exec web python manage.py makemigrations
docker compose exec web python manage.py migrate
```

### **5. Create Superuser**
```bash
docker compose exec web python manage.py createsuperuser
```

### **6. Seed Sample Data**
```bash
docker compose exec web python seed_data.py
```

### **7. Access Application**
- **Django Admin**: http://localhost:8000/admin/
- **API Root**: http://localhost:8000/api/
- **Centrifugo Admin**: http://localhost:8001/

---

## Key Design Decisions

### **Why Single-Pass Brain?**
**Problem**: Traditional multi-call approach caused latency (evaluate → decide → generate question = 3 API calls).

**Solution**: Single Gemini call with structured JSON schema does everything at once.

**Benefits:**
- 3x faster response time
- Consistent evaluation logic
- Reduced API costs
- Simplified state management

### **Why WebSocket + Centrifugo?**
**Problem**: HTTP polling can't handle real-time audio streaming.

**Solution**: Django Channels + Centrifugo for production-grade WebSocket orchestration.

**Benefits:**
- Sub-second latency
- Scalable (Centrifugo handles 100k+ connections)
- Decoupled architecture

### **Why Per-Answer Metrics?**
**Problem**: Single overall score doesn't show candidate journey.

**Solution**: Granular tracking of every Q&A exchange.

**Benefits:**
- Detailed feedback for candidates
- Identify specific knowledge gaps
- Appeal mechanism (review specific answers)
- Training data for AI improvement

### **Why Pause Duration for Cheating?**
**Problem**: Candidates can use ChatGPT mid-interview.

**Solution**: Measure time between AI finishing speaking and candidate starting.

**Insight**: Legitimate candidates start responding within 3-5 seconds. >8 seconds + perfect answer = suspicious.

---

## Future Enhancements

### **Planned Features**
- [ ] Multi-language interview support (Spanish, Mandarin, Hindi)
- [ ] Video recording with facial analysis
- [ ] Live coding challenges integration
- [ ] Peer comparison rankings
- [ ] Automated interview scheduling
- [ ] White-label custom branding
- [ ] Integration with ATS systems (Greenhouse, Lever)

### **AI Improvements**
- [ ] Fine-tune Gemini on domain-specific interviews
- [ ] Multi-modal evaluation (code + explanation)
- [ ] Adaptive difficulty (real-time adjustment)
- [ ] Personality/soft skills assessment

---

## License
Proprietary - All Rights Reserved

## Support
For questions or issues: support@talentcrew.ai
