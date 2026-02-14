from django.db import models
import uuid

class JobPosting(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255) # e.g., "Full Stack Engineer"
    stack = models.JSONField(default=list) # e.g., ["Python", "React", "Docker"]
    
    rubric_template = models.JSONField(default=dict)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class InterviewSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(JobPosting, on_delete=models.CASCADE)
    candidate_name = models.CharField(max_length=255)
    
    current_stage = models.CharField(max_length=50, default='intro')
    is_completed = models.BooleanField(default=False)
    
    overall_score = models.FloatField(null=True, blank=True)
    summary_pdf = models.FileField(upload_to='reports/', null=True, blank=True)
    
    started_at = models.DateTimeField(auto_now_add=True)

class EvidenceSnippet(models.Model):
    session = models.ForeignKey(InterviewSession, related_name='evidence', on_delete=models.CASCADE)
    metric_name = models.CharField(max_length=100) # e.g., "Database Optimization"
    snippet = models.TextField() # The exact quote from Gemini
    confidence_score = models.IntegerField() # 1-10
    
    timestamp = models.DateTimeField(auto_now_add=True)