from django.db import models
from django.contrib.auth.models import AbstractUser
import uuid

from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager # Add BaseUserManager
import uuid

# --- Add this Manager ---
class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        
        # This handles the username requirement internally
        if 'username' not in extra_fields or not extra_fields['username']:
            extra_fields['username'] = email.split('@')[0] + str(uuid.uuid4())[:8]
            
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)

# --- Update your User Model ---
class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    company_name = models.CharField(max_length=255, blank=True, null=True)
    username = models.CharField(max_length=150, unique=True, blank=True, null=True)
    
    objects = UserManager() # <--- Tell the model to use your custom manager

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']
    
    def save(self, *args, **kwargs):
        if not self.username:
            self.username = self.email.split('@')[0] + str(self.id)[:8]
        super().save(*args, **kwargs)
class JobPosting(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255) 
    stack = models.JSONField(default=list) 
    
    rubric_template = models.JSONField(default=dict)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='created_jobs', null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class InterviewSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(JobPosting, on_delete=models.CASCADE)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='created_sessions', null=True, blank=True)
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