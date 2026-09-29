"""
Recommendations Engine Package
"""
from recommendations.routes import recommendations_bp
from recommendations.migration import run_recommendation_migrations
from recommendations.seed import seed_recommendation_data
from recommendations.triggers import (
    on_course_quiz_completed,
    on_project_evaluated,
    on_interview_completed,
    on_profile_updated
)

__all__ = [
    'recommendations_bp',
    'run_recommendation_migrations',
    'seed_recommendation_data',
    'on_course_quiz_completed',
    'on_project_evaluated',
    'on_interview_completed',
    'on_profile_updated'
]
