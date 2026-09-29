from recommendations.engine import RecommendationEngine

def on_course_quiz_completed(user_id, course_id, module_id, score):
    """Event hook: Recalculates recommendations when a student submits or completes a quiz."""
    try:
        RecommendationEngine.compute_and_save_recommendations(user_id, trigger_event=f"QUIZ_COMPLETED_M{module_id}_C{course_id}")
    except Exception as e:
        print(f"Warning: Failed to trigger recommendation update on quiz completion: {e}")

def on_project_evaluated(user_id, course_id, final_score):
    """Event hook: Recalculates recommendations when a capstone project is evaluated (50% AI + 50% Mentor)."""
    try:
        RecommendationEngine.compute_and_save_recommendations(user_id, trigger_event=f"PROJECT_EVALUATED_C{course_id}_SCORE_{final_score}")
    except Exception as e:
        print(f"Warning: Failed to trigger recommendation update on project evaluation: {e}")

def on_interview_completed(user_id, course_id, overall_score):
    """Event hook: Recalculates recommendations when a Career Track AI interview is completed."""
    try:
        RecommendationEngine.compute_and_save_recommendations(user_id, trigger_event=f"INTERVIEW_COMPLETED_C{course_id}_SCORE_{overall_score}")
    except Exception as e:
        print(f"Warning: Failed to trigger recommendation update on interview completion: {e}")

def on_profile_updated(user_id):
    """Event hook: Recalculates recommendations when student target career role or preferences change."""
    try:
        RecommendationEngine.compute_and_save_recommendations(user_id, trigger_event="PROFILE_UPDATED")
    except Exception as e:
        print(f"Warning: Failed to trigger recommendation update on profile update: {e}")
