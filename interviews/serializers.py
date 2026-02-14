from rest_framework import serializers
from .models import JobPosting, InterviewSession

class JobPostingSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobPosting
        fields = ['id', 'title', 'stack', 'rubric_template', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate_rubric_template(self, value):
        """Ensure the frontend sends the fixed fields we expect."""
        required_keys = ['primary_language', 'experience_level', 'core_skills']
        
        for key in required_keys:
            if key not in value:
                raise serializers.ValidationError(f"Missing required fixed field: {key}")
        
        if not isinstance(value.get('core_skills'), list):
            raise serializers.ValidationError("core_skills must be a list of strings.")
        
        if not isinstance(value.get('evaluation_focus'), list):
            raise serializers.ValidationError("evaluation_focus must be a list of strings.")
        
        return value

class InterviewSessionSerializer(serializers.ModelSerializer):
    # We accept a job_id from the frontend to link the session to the job
    job_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = InterviewSession
        fields = [
            'id', 'job_id', 'candidate_name', 'current_stage', 
            'is_completed', 'overall_score', 'started_at'
        ]
        read_only_fields = [
            'id', 'current_stage', 'is_completed', 
            'overall_score', 'started_at'
        ]

    def create(self, validated_data):
        # Pop the job_id, find the actual Job object, and create the session
        job_id = validated_data.pop('job_id')
        try:
            job = JobPosting.objects.get(id=job_id)
        except JobPosting.DoesNotExist:
            raise serializers.ValidationError({"job_id": "Invalid Job ID."})
            
        return InterviewSession.objects.create(job=job, **validated_data)