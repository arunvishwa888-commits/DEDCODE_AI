import sqlite3
import os
import json

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "learndebt.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_or_create_enrollment(user_id, course_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT * FROM career_track_enrollments
    WHERE user_id = ? AND course_id = ?
    """, (user_id, course_id))
    row = cursor.fetchone()

    if not row:
        cursor.execute("""
        INSERT INTO career_track_enrollments (user_id, course_id, current_step, status)
        VALUES (?, ?, 1, 'IN_PROGRESS')
        """, (user_id, course_id))
        conn.commit()
        cursor.execute("SELECT * FROM career_track_enrollments WHERE id = ?", (cursor.lastrowid,))
        row = cursor.fetchone()

    conn.close()
    return dict(row)

def check_course_completion(user_id, course_id):
    """
    Checks if student has completed all modules in the course.
    Returns (is_completed, total_modules, completed_modules, avg_score)
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as count FROM modules WHERE course_id = ?", (course_id,))
    total_mod = cursor.fetchone()["count"]

    if total_mod == 0:
        conn.close()
        return False, 0, 0, 0.0

    cursor.execute("""
    SELECT COUNT(*) as count, AVG(score) as avg_score
    FROM learning_progress
    WHERE user_id = ? AND course_id = ? AND completed = 1
    """, (user_id, course_id))
    prog = cursor.fetchone()
    completed_mod = prog["count"] if prog else 0
    avg_score = prog["avg_score"] if (prog and prog["avg_score"] is not None) else 0.0

    conn.close()
    is_completed = (completed_mod >= total_mod and total_mod > 0)
    return is_completed, total_mod, completed_mod, round(float(avg_score), 1)

def get_track_status(user_id, course_id):
    """
    Returns the comprehensive state of the career track for the given student and course.
    Server enforces the locked step-by-step flow:
    Step 1 -> Step 2 -> Step 3 -> Step 4 -> Step 5 -> Step 6 (Certificate)
    """
    conn = get_db()
    cursor = conn.cursor()

    # Get course details
    cursor.execute("SELECT id, title, slug, description, category FROM courses WHERE id = ?", (course_id,))
    course = cursor.fetchone()
    if not course:
        conn.close()
        return None

    # Get track enrollment
    cursor.execute("SELECT * FROM career_track_enrollments WHERE user_id = ? AND course_id = ?", (user_id, course_id))
    enr = cursor.fetchone()
    if not enr:
        cursor.execute("""
        INSERT INTO career_track_enrollments (user_id, course_id, current_step, status)
        VALUES (?, ?, 1, 'IN_PROGRESS')
        """, (user_id, course_id))
        conn.commit()
        cursor.execute("SELECT * FROM career_track_enrollments WHERE id = ?", (cursor.lastrowid,))
        enr = cursor.fetchone()

    enrollment = dict(enr)
    enrollment_id = enrollment["id"]

    # 1. Course Completion Check
    is_course_done, total_modules, completed_modules, avg_score = check_course_completion(user_id, course_id)

    # 2. Mini Project Status
    cursor.execute("SELECT * FROM career_track_project_submissions WHERE enrollment_id = ?", (enrollment_id,))
    project_row = cursor.fetchone()
    project = dict(project_row) if project_row else None

    # 3. AI + Mentor Eval Status
    eval_passed = False
    if project and project.get("submitted_at") and project.get("final_score") is not None:
        eval_passed = (project["final_score"] >= 70.0)

    # 4. AI Interview Status
    cursor.execute("SELECT * FROM career_track_interviews WHERE enrollment_id = ?", (enrollment_id,))
    interview_row = cursor.fetchone()
    interview = dict(interview_row) if interview_row else None
    interview_passed = False
    if interview and interview.get("status") == "COMPLETED" and interview.get("overall_interview_score", 0) >= 70.0:
        interview_passed = True

    # 5. Skill Gaps & Roadmap Status
    cursor.execute("SELECT * FROM career_track_skill_gaps WHERE enrollment_id = ?", (enrollment_id,))
    skill_gap_row = cursor.fetchone()
    skill_gap = dict(skill_gap_row) if skill_gap_row else None
    roadmap_unlocked = interview_passed

    # 6. Certificate Status
    cursor.execute("SELECT * FROM career_track_certificates WHERE enrollment_id = ?", (enrollment_id,))
    cert_row = cursor.fetchone()
    certificate = dict(cert_row) if cert_row else None

    # Compute step unlock flags strictly
    step1_unlocked = True
    step1_completed = is_course_done

    step2_unlocked = step1_completed
    step2_completed = bool(project and project.get("submitted_at"))

    step3_unlocked = step2_completed
    step3_completed = eval_passed

    step4_unlocked = step3_completed
    step4_completed = interview_passed

    step5_unlocked = step4_completed
    step5_completed = bool(skill_gap and skill_gap.get("acknowledged"))

    step6_unlocked = (step1_completed and step3_completed and step4_completed and step5_unlocked)
    step6_completed = bool(certificate)

    # Update current_step in DB if progression moved forward
    calculated_step = 1
    if step6_completed:
        calculated_step = 6
    elif step5_unlocked:
        calculated_step = 5
    elif step4_unlocked:
        calculated_step = 4
    elif step3_unlocked:
        calculated_step = 3
    elif step2_unlocked:
        calculated_step = 2
    else:
        calculated_step = 1

    cursor.execute("""
    UPDATE career_track_enrollments
    SET current_step = ?, status = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (calculated_step, 'CERTIFIED' if certificate else 'IN_PROGRESS', enrollment_id))
    conn.commit()
    conn.close()

    return {
        "course": dict(course),
        "enrollment": enrollment,
        "steps": {
            "step1_course_check": {
                "step_number": 1,
                "title": "Course Completion Check",
                "unlocked": step1_unlocked,
                "completed": step1_completed,
                "total_modules": total_modules,
                "completed_modules": completed_modules,
                "average_quiz_score": avg_score
            },
            "step2_mini_project": {
                "step_number": 2,
                "title": "Capstone Mini Project",
                "unlocked": step2_unlocked,
                "completed": step2_completed,
                "project": project
            },
            "step3_evaluation": {
                "step_number": 3,
                "title": "AI + Mentor Evaluation (50/50)",
                "unlocked": step3_unlocked,
                "completed": step3_completed,
                "ai_score": project["ai_score"] if project else None,
                "mentor_score": project["mentor_score"] if project else None,
                "final_score": project["final_score"] if project else None,
                "ai_feedback": json.loads(project["ai_feedback_json"]) if (project and project.get("ai_feedback_json")) else None,
                "mentor_feedback": json.loads(project["mentor_feedback_json"]) if (project and project.get("mentor_feedback_json")) else None,
                "passed": eval_passed
            },
            "step4_ai_interview": {
                "step_number": 4,
                "title": "AI Technical Interview",
                "unlocked": step4_unlocked,
                "completed": step4_completed,
                "interview": {
                    "id": interview["id"] if interview else None,
                    "status": interview["status"] if interview else "NOT_STARTED",
                    "overall_score": interview["overall_interview_score"] if interview else None,
                    "technical_score": interview["technical_score"] if interview else None,
                    "problem_solving_score": interview["problem_solving_score"] if interview else None,
                    "system_design_score": interview["system_design_score"] if interview else None,
                    "passed": interview_passed,
                    "feedback": interview["feedback"] if interview else None
                } if interview else None
            },
            "step5_skill_gaps": {
                "step_number": 5,
                "title": "Skill Gaps & Career Roadmap",
                "unlocked": step5_unlocked,
                "completed": step5_completed,
                "data": {
                    "strong_skills": json.loads(skill_gap["strong_skills_json"]) if (skill_gap and skill_gap.get("strong_skills_json")) else [],
                    "gap_skills": json.loads(skill_gap["gap_skills_json"]) if (skill_gap and skill_gap.get("gap_skills_json")) else [],
                    "roadmap": json.loads(skill_gap["personalized_roadmap_json"]) if (skill_gap and skill_gap.get("personalized_roadmap_json")) else [],
                    "readiness_score": skill_gap["readiness_score"] if skill_gap else 0.0,
                    "acknowledged": bool(skill_gap and skill_gap.get("acknowledged"))
                } if skill_gap else None
            },
            "step6_certificate": {
                "step_number": 6,
                "title": "Verified Career Certificate",
                "unlocked": step6_unlocked,
                "completed": step6_completed,
                "certificate": {
                    "certificate_id": certificate["certificate_id"],
                    "student_name": certificate["student_name"],
                    "course_title": certificate["course_title"],
                    "project_score": certificate["project_score"],
                    "interview_score": certificate["interview_score"],
                    "overall_score": certificate["overall_score"],
                    "issue_date": certificate["issue_date"],
                    "verification_url": f"/api/career-track/verify/{certificate['certificate_id']}"
                } if certificate else None
            }
        }
    }
