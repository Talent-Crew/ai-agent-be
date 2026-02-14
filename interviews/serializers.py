from rest_framework import serializers
from .models import JobPosting, InterviewSession, User
from django.contrib.auth import authenticate

class JobPostingSerializer(serializers.ModelSerializer):
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)
    
    class Meta:
        model = JobPosting
        fields = ['id', 'title', 'stack', 'rubric_template', 'created_at', 'created_by_email', 'created_by_name']
        read_only_fields = ['id', 'created_at', 'created_by_email', 'created_by_name']

    def validate_rubric_template(self, value):
        """Ensure the frontend sends the fixed fields we expect."""
        required_keys = ['languages', 'experience_level', 'core_skills']
        
        for key in required_keys:
            if key not in value:
                raise serializers.ValidationError(f"Missing required fixed field: {key}")
        
        if not isinstance(value.get('languages'), list):
            raise serializers.ValidationError("languages must be a list of strings.")
        
        if not value.get('languages'):
            raise serializers.ValidationError("languages list cannot be empty.")
        
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
            'id', 'job_id', 'candidate_name',
            'current_stage', 'is_completed', 'overall_score', 'started_at'
        ]
        read_only_fields = [
            'id', 'current_stage', 'is_completed', 
            'overall_score', 'started_at'
        ]

    def create(self, validated_data):
        job_id = validated_data.pop('job_id')
        
        try:
            job = JobPosting.objects.get(id=job_id)
        except JobPosting.DoesNotExist:
            raise serializers.ValidationError({"job_id": "Invalid Job ID."})
        
        # Get the current user from the request context if available
        request = self.context.get('request')
        created_by = request.user if request and request.user.is_authenticated else None
        
        return InterviewSession.objects.create(
            job=job, 
            created_by=created_by,
            **validated_data
        )


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User details"""
    class Meta:
        model = User
        fields = ['id', 'email', 'full_name', 'company_name']
        read_only_fields = ['id']


class UserCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating company admin users"""
    password = serializers.CharField(write_only=True, required=True, min_length=6)
    
    class Meta:
        model = User
        fields = ['id', 'email', 'full_name', 'company_name', 'password']
        read_only_fields = ['id']
    
    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data['email'],
            full_name=validated_data['full_name'],
            password=validated_data['password'],
            company_name=validated_data.get('company_name', ''),
            is_staff=True  # Company admins are staff
        )
        return user


class LoginSerializer(serializers.Serializer):
    """Serializer for user login"""
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    
    def validate(self, data):
        email = data.get('email')
        password = data.get('password')
        
        if email and password:
            # Django's authenticate expects username field, but we're using email
            try:
                user_obj = User.objects.get(email=email)
                user = authenticate(username=user_obj.username, password=password)
            except User.DoesNotExist:
                raise serializers.ValidationError('Invalid email or password.')
            
            if not user:
                raise serializers.ValidationError('Invalid email or password.')
            
            if not user.is_active:
                raise serializers.ValidationError('User account is disabled.')
        else:
            raise serializers.ValidationError('Must include "email" and "password".')
        
        data['user'] = user
        return data


class UserSessionSerializer(serializers.ModelSerializer):
    """Serializer for interview sessions with job details - for admin dashboard"""
    job_title = serializers.CharField(source='job.title', read_only=True)
    job_stack = serializers.JSONField(source='job.stack', read_only=True)
    job_id = serializers.UUIDField(source='job.id', read_only=True)
    
    class Meta:
        model = InterviewSession
        fields = [
            'id', 'job_id', 'job_title', 'job_stack', 'candidate_name',
            'current_stage', 'is_completed', 'overall_score', 'started_at'
        ]
        read_only_fields = fields