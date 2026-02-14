import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from interviews.models import JobPosting

def seed():
    JobPosting.objects.get_or_create(
        title="Senior Django Developer",
        stack=["Python", "Django", "Postgres", "Redis"],
        rubric_template={
            "metrics": [
                {
                    "name": "Database Optimization",
                    "criteria": "Knowledge of N+1 issues, indexing, and QuerySet optimization.",
                    "weight": 0.4,
                    "target_signals": ["select_related", "prefetch_related", "explain analyze"]
                },
                {
                    "name": "System Design",
                    "criteria": "Ability to design scalable architectures and handle concurrency.",
                    "weight": 0.4,
                    "target_signals": ["horizontal scaling", "load balancer", "caching"]
                }
            ]
        }
    )
    print("✅ Rubric Seeded!")

if __name__ == "__main__":
    seed()