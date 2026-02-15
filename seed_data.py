import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from interviews.models import JobPosting

def seed():
    # Example 1: Multiple programming languages
    JobPosting.objects.get_or_create(
        title="Full Stack Developer",
        stack=["Python", "JavaScript", "React", "Django", "Node.js"],
        rubric_template={
            "languages": ["Python", "JavaScript", "SQL"],
            "experience_level": "Mid-Level",
            "core_skills": [
                "Backend API Development",
                "Frontend State Management",
                "Database Query Optimization",
                "RESTful Design"
            ],
            "evaluation_focus": [
                "Problem Solving",
                "Code Quality",
                "System Design"
            ]
        }
    )
    
    # Example 2: Single language focus
    JobPosting.objects.get_or_create(
        title="Senior Django Developer",
        stack=["Python", "Django", "Postgres", "Redis"],
        rubric_template={
            "languages": ["Python"],
            "experience_level": "Senior",
            "core_skills": [
                "Database Optimization",
                "System Design",
                "Django ORM",
                "Caching Strategies"
            ],
            "evaluation_focus": [
                "Technical Depth",
                "Architecture Decisions",
                "Performance Optimization"
            ]
        }
    )
    
    print("✅ Rubric Seeded!")

if __name__ == "__main__":
    seed()