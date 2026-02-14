from django.db import models
import uuid

class JobPosting(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255) 
    stack = models.JSONField(default=list) 
    
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
    metric_name = models.CharField(max_length=100) 
    snippet = models.TextField() 
    confidence_score = models.IntegerField() 
    
    timestamp = models.DateTimeField(auto_now_add=True)

class PerAnswerMetric(models.Model):
    session = models.ForeignKey(InterviewSession, related_name='answers', on_delete=models.CASCADE)
    
    question_asked = models.TextField()
    candidate_answer = models.TextField()
    
    confidence_score = models.IntegerField(null=True, blank=True) 
    evidence_extracted = models.TextField(null=True, blank=True)
    
    critique = models.TextField(null=True, blank=True)  
    ideal_answer = models.TextField(null=True, blank=True)  
    technical_concepts_missed = models.JSONField(default=list)  
    
    is_cheating_suspected = models.BooleanField(default=False)
    cheating_reason = models.CharField(max_length=255, null=True, blank=True)
    bias_flag = models.BooleanField(default=False) 
    
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Q&A for Session {self.session.id} - Score: {self.confidence_score}"