from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, JobPosting, InterviewSession, EvidenceSnippet, PerAnswerMetric


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['email', 'full_name', 'company_name', 'is_active', 'date_joined']
    list_filter = ['is_active', 'is_staff']
    search_fields = ['email', 'full_name', 'company_name']
    ordering = ['-date_joined']
    
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('full_name', 'username', 'company_name')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'full_name', 'company_name', 'password1', 'password2'),
        }),
    )


@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_display = ['title', 'created_by', 'created_at']
    list_filter = ['created_by', 'created_at']
    search_fields = ['title', 'created_by__email', 'created_by__full_name']
    readonly_fields = ['created_at']


@admin.register(InterviewSession)
class InterviewSessionAdmin(admin.ModelAdmin):
    list_display = ['candidate_name', 'job', 'created_by', 'current_stage', 'is_completed', 'started_at']
    list_filter = ['is_completed', 'current_stage', 'created_by']
    search_fields = ['candidate_name', 'created_by__email', 'created_by__full_name']
    readonly_fields = ['started_at']


@admin.register(EvidenceSnippet)
class EvidenceSnippetAdmin(admin.ModelAdmin):
    list_display = ['session', 'metric_name', 'confidence_score', 'timestamp']
    list_filter = ['metric_name']
    search_fields = ['session__candidate_name']
    readonly_fields = ['timestamp']


@admin.register(PerAnswerMetric)
class PerAnswerMetricAdmin(admin.ModelAdmin):
    list_display = ['session', 'confidence_score', 'is_cheating_suspected', 'timestamp']
    list_filter = ['is_cheating_suspected', 'bias_flag']
    search_fields = ['session__candidate_name', 'question_asked']
    readonly_fields = ['timestamp']
