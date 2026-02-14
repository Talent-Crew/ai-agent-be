from django.contrib import admin
from .models import JobPosting, InterviewSession, EvidenceSnippet, PerAnswerMetric


@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_display = ['title', 'created_at', 'get_stack']
    search_fields = ['title']
    readonly_fields = ['id', 'created_at']
    list_filter = ['created_at']
    
    def get_stack(self, obj):
        return ', '.join(obj.stack) if obj.stack else 'N/A'
    get_stack.short_description = 'Tech Stack'


@admin.register(InterviewSession)
class InterviewSessionAdmin(admin.ModelAdmin):
    list_display = ['candidate_name', 'job', 'current_stage', 'is_completed', 'overall_score', 'started_at']
    search_fields = ['candidate_name', 'job__title']
    list_filter = ['is_completed', 'current_stage', 'started_at']
    readonly_fields = ['id', 'started_at']
    raw_id_fields = ['job']


@admin.register(EvidenceSnippet)
class EvidenceSnippetAdmin(admin.ModelAdmin):
    list_display = ['session', 'metric_name', 'confidence_score', 'timestamp']
    search_fields = ['metric_name', 'snippet', 'session__candidate_name']
    list_filter = ['confidence_score', 'timestamp', 'metric_name']
    readonly_fields = ['timestamp']
    raw_id_fields = ['session']


@admin.register(PerAnswerMetric)
class PerAnswerMetricAdmin(admin.ModelAdmin):
    list_display = ['session', 'get_question_preview', 'confidence_score', 'is_cheating_suspected', 'bias_flag', 'timestamp']
    search_fields = ['question_asked', 'candidate_answer', 'session__candidate_name']
    list_filter = ['confidence_score', 'is_cheating_suspected', 'bias_flag', 'timestamp']
    readonly_fields = ['timestamp']
    raw_id_fields = ['session']
    
    def get_question_preview(self, obj):
        return obj.question_asked[:50] + '...' if len(obj.question_asked) > 50 else obj.question_asked
    get_question_preview.short_description = 'Question'
