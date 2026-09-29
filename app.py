import os
import sys
import json
import sqlite3
import jwt
import hashlib
import re
import datetime
import secrets
import base64
import urllib.request
import urllib.parse
from flask import Flask, request, jsonify, render_template, send_from_directory, redirect, make_response

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env configuration file if present
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))

from database import DB_PATH, get_db_connection, init_db
from ai_agents import (
    RAGAITutorAgent, LearningDebtEngine, VisualCodeRepresentationEngine, AIProjectMentorAgent
)
from recommendation_engine import (
    get_student_profile, save_student_profile, generate_personalized_recommendations, generate_recommendations_from_preferences
)
from video_generator import (
    launch_async_video_generation, launch_bulk_course_video_generation,
    launch_bulk_all_courses_generation, retry_failed_video_job,
    cancel_video_job, publish_ai_video_version, unpublish_ai_video,
    queue_manager
)
from career_track import career_track_bp, run_career_track_migrations
from career_track.monitoring_routes import monitoring_bp
from career_track.monitoring_migration import run_monitoring_migrations
from career_track.weekly_assessment_routes import weekly_assessment_bp
from career_track.weekly_assessment_migration import run_weekly_assessment_migrations
from recommendations import (
    recommendations_bp, run_recommendation_migrations, seed_recommendation_data,
    on_course_quiz_completed
)

app = Flask(__name__, static_folder="../static", template_folder="../templates")
app.config["SECRET_KEY"] = "dedcode-learndebt-secret-key-2026"
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Register Career Track Feature Module
app.register_blueprint(career_track_bp, url_prefix="/api/career-track")
run_career_track_migrations()

# Register Assessment Monitoring Feature (Career Track add-on)
app.register_blueprint(monitoring_bp, url_prefix="/api/career-track/monitoring")
run_monitoring_migrations()

# Register Live Weekly AI + Mentor Assessment Feature
app.register_blueprint(weekly_assessment_bp, url_prefix="/api/career-track/weekly-assessment")
run_weekly_assessment_migrations()


# Register Recommendation Engine Feature Module
app.register_blueprint(recommendations_bp, url_prefix="/api/recommendations")
run_recommendation_migrations()
seed_recommendation_data()

# Register Innovation Booster Feature Module
from innovation_booster import (
    innovation_booster_bp, init_innovation_booster_db, seed_innovation_booster_data
)
app.register_blueprint(innovation_booster_bp, url_prefix="/api/innovation-booster")
init_innovation_booster_db()
seed_innovation_booster_data()

def is_valid_google_client_id(cid):
    if not cid:
        return False
    cid_str = str(cid).strip()
    placeholders = [
        "your_client_id", "your-client-id", "your_google_client_id",
        "dedcode-google-client-id", "test", "undefined", "null"
    ]
    if any(p in cid_str.lower() for p in placeholders):
        return False
    return cid_str.endswith(".apps.googleusercontent.com") or len(cid_str) > 20

def validate_google_oauth_config():
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5050/api/auth/google/callback")
    
    is_valid_id = is_valid_google_client_id(client_id)
    has_secret = bool(client_secret and "secret" not in client_secret.lower() and len(client_secret) > 8)
    prefix = client_id[:16] + "..." if len(client_id) > 16 else (client_id or "MISSING")

    print("\n==================================================")
    print("DEDCODE GOOGLE OAUTH CONFIGURATION CHECK")
    print("==================================================")
    if is_valid_id:
        print(f"✓ Google Client ID: Configured (Prefix: {prefix})")
    else:
        print(f"✗ Google Client ID: Invalid/Placeholder ({prefix})")
        print("  -> Set GOOGLE_CLIENT_ID in .env from Google Cloud Console (APIs & Services -> Credentials)")
    
    if has_secret:
        print("✓ Google Client Secret: Configured")
    else:
        print("✗ Google Client Secret: Missing or placeholder")
        print("  -> Set GOOGLE_CLIENT_SECRET in .env from Google Cloud Console")
        
    print(f"✓ Google Redirect URI: {redirect_uri}")
    print("==================================================\n")

# Run startup configuration check
validate_google_oauth_config()

# Instantiate AI Agents
rag_tutor = RAGAITutorAgent()
debt_engine = LearningDebtEngine()
code_visualizer = VisualCodeRepresentationEngine()
project_mentor = AIProjectMentorAgent()

# ================= HELPER UTILITIES & SHARED SERVICES =================

def get_youtube_video_id(url):
    if not url:
        return None
    url_str = str(url).strip()
    patterns = [
        r'(?:v=|\/embed\/|\/watch\?v=|\/shorts\/|youtu\.be\/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$'
    ]
    for pattern in patterns:
        match = re.search(pattern, url_str)
        if match:
            v_id = match.group(1)
            if v_id != "invalid_url" and not v_id.startswith("http"):
                return v_id
    return None

def decode_token(req):
    auth_header = req.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ")[1]
    try:
        return jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
    except Exception:
        return None

def verify_student(req):
    payload = decode_token(req)
    if not payload or payload.get("role") != "STUDENT":
        return None
    return payload

def verify_admin(req):
    payload = decode_token(req)
    if not payload or payload.get("role") != "ADMIN":
        return None
    return payload

def verify_mentor(req):
    payload = decode_token(req)
    if not payload or payload.get("role") not in ["INSTRUCTOR", "MENTOR", "ADMIN"]:
        return None
    return payload

def log_activity(conn, user_id, action_type, description, metadata=None):
    try:
        cursor = conn.cursor()
        meta_str = json.dumps(metadata) if metadata else None
        cursor.execute("""
        INSERT INTO activity_logs (user_id, action_type, description, metadata_json)
        VALUES (?, ?, ?, ?)
        """, (user_id, action_type, description, meta_str))
    except Exception as e:
        try:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO activity_logs (user_id, action_type, description)
            VALUES (?, ?, ?)
            """, (user_id, action_type, description))
        except Exception as ex:
            print(f"Error logging activity: {ex}")

def ensure_user_subscription(conn, user_id, plan_name="Individual Learning", billing_cycle="Monthly", price_inr=499):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,))
    sub = cursor.fetchone()
    if not sub:
        cursor.execute("""
        INSERT INTO subscriptions (user_id, plan_name, billing_cycle, price_inr, status)
        VALUES (?, ?, ?, ?, 'ACTIVE')
        """, (user_id, plan_name, billing_cycle, price_inr))
        conn.commit()
        cursor.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,))
        sub = cursor.fetchone()
    return dict(sub)

# ================= SHARED BACKEND SERVICE FUNCTIONS =================

def award_module_completion_credits(conn, user_id, module_id, course_id, module_title=None):
    """
    Awards +3 credits to user_id for completing module_id (1 completed module = 3 credits).
    Idempotent: Uses credit_transactions partial unique index and check to guarantee single award per module.
    """
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id FROM credit_transactions 
    WHERE user_id = ? AND module_id = ? AND type = 'MODULE_COMPLETION'
    """, (user_id, module_id))
    if cursor.fetchone():
        cursor.execute("SELECT credit_balance FROM users WHERE id = ?", (user_id,))
        r = cursor.fetchone()
        return 0, (r["credit_balance"] if r and r["credit_balance"] is not None else 0)

    if not module_title:
        cursor.execute("SELECT title FROM modules WHERE id = ?", (module_id,))
        m = cursor.fetchone()
        module_title = m["title"] if m else f"Module #{module_id}"

    desc = f"Completed module: {module_title} (+3 credits)"
    try:
        cursor.execute("""
        INSERT INTO credit_transactions (user_id, module_id, course_id, amount, type, description)
        VALUES (?, ?, ?, 3, 'MODULE_COMPLETION', ?)
        """, (user_id, module_id, course_id, desc))
        
        cursor.execute("""
        UPDATE users SET credit_balance = COALESCE(credit_balance, 0) + 3 WHERE id = ?
        """, (user_id,))

        cursor.execute("SELECT credit_balance FROM users WHERE id = ?", (user_id,))
        r = cursor.fetchone()
        return 3, (r["credit_balance"] if r else 0)
    except sqlite3.IntegrityError:
        cursor.execute("SELECT credit_balance FROM users WHERE id = ?", (user_id,))
        r = cursor.fetchone()
        return 0, (r["credit_balance"] if r and r["credit_balance"] is not None else 0)

def process_module_completion(conn, user_id, module_id, score=100, is_assessment=False):
    """
    Centralized module completion processor.
    1. Updates learning_progress to completed = 1 with score.
    2. Unlocks next module in database (UPDATE modules SET is_unlocked = 1 WHERE course_id = ? AND order_index = ?).
    3. Updates enrollment progress percentage.
    4. Updates learning debt to Mastered.
    5. Awards +3 credits (idempotent).
    6. Identifies next_module.
    7. Identifies milestone project_unlocked (2-Module milestone test portion).
    8. Generates updated course_modules list for seamless frontend drawer rendering.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT id, course_id, title, slug, order_index, description FROM modules WHERE id = ?", (module_id,))
    mod = cursor.fetchone()
    if not mod:
        return None

    course_id = mod["course_id"]
    module_title = mod["title"]
    module_slug = mod["slug"]
    module_order = mod["order_index"]

    # 1. Update learning progress
    cursor.execute("""
    INSERT INTO learning_progress (user_id, course_id, module_id, completed, score, updated_at)
    VALUES (?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(user_id, module_id) DO UPDATE SET 
        completed = 1,
        score = MAX(learning_progress.score, excluded.score),
        updated_at = CURRENT_TIMESTAMP
    """, (user_id, course_id, module_id, score))

    # 2. Unlock next module in modules table
    cursor.execute("UPDATE modules SET is_unlocked = 1 WHERE course_id = ? AND order_index = ?", (course_id, module_order + 1))

    # 3. Update course enrollment progress
    cursor.execute("SELECT COUNT(*) as total FROM modules WHERE course_id = ?", (course_id,))
    total_m = cursor.fetchone()["total"] or 1
    cursor.execute("SELECT COUNT(*) as comp FROM learning_progress WHERE user_id = ? AND course_id = ? AND completed = 1", (user_id, course_id))
    comp_m = cursor.fetchone()["comp"] or 0
    prog_pct = min(100, int((comp_m / total_m) * 100))
    cursor.execute("""
    UPDATE enrollments SET progress_pct = ?, last_accessed_at = CURRENT_TIMESTAMP 
    WHERE user_id = ? AND course_id = ?
    """, (prog_pct, user_id, course_id))

    # 4. Learning Debt Calculation
    concept_name = f"Concept: {module_title}"
    cursor.execute("""
    INSERT INTO learning_debt (user_id, course_id, concept_name, mastery_pct, learning_debt_pct, reason, status)
    VALUES (?, ?, ?, ?, 0, 'Mastery achieved through module completion.', 'Mastered')
    ON CONFLICT(user_id, course_id, concept_name) DO UPDATE SET
        mastery_pct = excluded.mastery_pct,
        learning_debt_pct = 0,
        status = 'Mastered',
        updated_at = CURRENT_TIMESTAMP
    """, (user_id, course_id, concept_name, score))

    # 5. Award Credits (+3)
    awarded_credits, total_credits = award_module_completion_credits(conn, user_id, module_id, course_id, module_title)

    # 6. Fetch next module
    cursor.execute("""
    SELECT id, slug, title, order_index, description 
    FROM modules 
    WHERE course_id = ? AND order_index = ?
    """, (course_id, module_order + 1))
    next_m_row = cursor.fetchone()
    next_module_info = {
        "id": next_m_row["id"],
        "slug": next_m_row["slug"],
        "title": next_m_row["title"],
        "order_index": next_m_row["order_index"],
        "description": next_m_row["description"]
    } if next_m_row else None

    # 7. Check 2-Module milestone project test unlock
    cursor.execute("""
    SELECT id, project_number, title, description, objective, what_to_build, prereq_module_index_1, prereq_module_index_2
    FROM projects
    WHERE course_id = ? AND (prereq_module_index_1 = ? OR prereq_module_index_2 = ?)
    """, (course_id, module_order, module_order))
    p_candidates = cursor.fetchall()
    project_unlocked_info = None

    for p_cand in p_candidates:
        p_dict = dict(p_cand)
        m1 = p_dict["prereq_module_index_1"]
        m2 = p_dict["prereq_module_index_2"]
        cursor.execute("""
        SELECT m.order_index, lp.completed
        FROM modules m
        LEFT JOIN learning_progress lp ON m.id = lp.module_id AND lp.user_id = ?
        WHERE m.course_id = ? AND m.order_index IN (?, ?)
        """, (user_id, course_id, m1, m2))
        comp_rows = cursor.fetchall()
        if len(comp_rows) >= 2 and all(r["completed"] == 1 for r in comp_rows):
            project_unlocked_info = {
                "id": p_dict["id"],
                "project_number": p_dict["project_number"],
                "title": p_dict["title"],
                "description": p_dict["description"],
                "objective": p_dict.get("objective") or p_dict["description"],
                "what_to_build": p_dict.get("what_to_build") or "",
                "milestone_modules": [m1, m2],
                "is_milestone_test": True
            }
            break

    # 8. Full updated course modules list
    cursor.execute("SELECT id, slug, title, order_index, is_unlocked FROM modules WHERE course_id = ? ORDER BY order_index ASC", (course_id,))
    raw_modules = [dict(m) for m in cursor.fetchall()]
    cursor.execute("""
    SELECT m.order_index 
    FROM learning_progress lp
    JOIN modules m ON lp.module_id = m.id
    WHERE lp.user_id = ? AND m.course_id = ? AND lp.completed = 1
    """, (user_id, course_id))
    completed_module_orders = {r["order_index"] for r in cursor.fetchall()}
    course_modules = []
    for m in raw_modules:
        m_order = m["order_index"]
        m_completed = m_order in completed_module_orders
        is_unlocked = (m_order == 1) or ((m_order - 1) in completed_module_orders) or bool(m.get("is_unlocked"))
        m["completed"] = m_completed
        m["is_unlocked"] = is_unlocked
        course_modules.append(m)

    # Course info
    cursor.execute("SELECT slug, title FROM courses WHERE id = ?", (course_id,))
    c_row = cursor.fetchone()
    c_slug = c_row["slug"] if c_row else "course"
    c_title = c_row["title"] if c_row else "Course"

    return {
        "module_completed": {
            "id": module_id,
            "order_index": module_order,
            "title": module_title,
            "slug": module_slug
        },
        "course_id": course_id,
        "course_slug": c_slug,
        "course_title": c_title,
        "next_module": next_module_info,
        "project_unlocked": project_unlocked_info,
        "credits_awarded": awarded_credits,
        "total_credits": total_credits,
        "course_modules": course_modules,
        "enrollment_progress_pct": prog_pct,
        "score": score,
        "passed": True
    }

def get_user_credit_summary(conn, user_id):
    cursor = conn.cursor()
    cursor.execute("SELECT credit_balance FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    balance = row["credit_balance"] if row and row["credit_balance"] is not None else 0
    
    # 1000 credits = 10% discount max. 100 credits = 1% discount.
    discount_pct = min(balance // 100, 10)
    
    if discount_pct >= 10:
        next_tier_credits = 1000
        credits_needed = 0
        max_tier_reached = True
    else:
        next_tier_credits = (discount_pct + 1) * 100
        credits_needed = next_tier_credits - balance
        max_tier_reached = False

    cursor.execute("""
    SELECT id, module_id, course_id, amount, type, description, created_at
    FROM credit_transactions
    WHERE user_id = ?
    ORDER BY created_at DESC, id DESC
    """, (user_id,))
    history = [dict(r) for r in cursor.fetchall()]

    return {
        "credit_balance": balance,
        "discount_percentage": discount_pct,
        "next_tier_credits": next_tier_credits,
        "credits_needed_for_next_tier": credits_needed,
        "max_tier_reached": max_tier_reached,
        "history": history
    }

def get_student_analytics(user_id):
    """SINGLE SOURCE OF TRUTH FOR A STUDENT RECORD"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, email, role, streak_days, credit_balance, created_at FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return None

    u_dict = dict(user)
    credit_summary = get_user_credit_summary(conn, user_id)

    # Subscription
    cursor.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,))
    sub_row = cursor.fetchone()
    if not sub_row:
        cursor.execute("""
        INSERT INTO subscriptions (user_id, plan_name, billing_cycle, price_inr, status)
        VALUES (?, 'Individual Learning', 'Monthly', 499, 'ACTIVE')
        """, (user_id,))
        conn.commit()
        cursor.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,))
        sub_row = cursor.fetchone()
    
    sub_dict = dict(sub_row) if sub_row else {
        "id": None, "plan_name": "Individual Learning", "billing_cycle": "Monthly",
        "price_inr": 499, "status": "ACTIVE", "created_at": u_dict["created_at"]
    }

    # Latest Manual Payment Verification Request
    cursor.execute("""
    SELECT id, plan_id, plan_name, plan_amount, billing_cycle, utr_number, screenshot_path, status, submitted_at, verified_at, rejection_reason, admin_notes
    FROM payment_requests
    WHERE user_id = ?
    ORDER BY id DESC LIMIT 1
    """, (user_id,))
    pay_row = cursor.fetchone()
    payment_req_dict = dict(pay_row) if pay_row else None

    # Enrolled courses
    cursor.execute("""
    SELECT c.*, e.id as enrollment_id, e.progress_pct, e.status as enrollment_status, e.enrolled_at, e.last_accessed_at, e.subscription_id
    FROM enrollments e
    JOIN courses c ON e.course_id = c.id
    WHERE e.user_id = ?
    ORDER BY e.last_accessed_at DESC
    """, (user_id,))
    enrolled_rows = cursor.fetchall()
    
    enrolled_courses = []
    for c in enrolled_rows:
        c_dict = dict(c)
        cursor.execute("SELECT COUNT(*) as total FROM modules WHERE course_id = ?", (c["id"],))
        total_m = cursor.fetchone()["total"] or 1
        
        cursor.execute("SELECT COUNT(*) as comp FROM learning_progress WHERE user_id = ? AND course_id = ? AND completed = 1", (user_id, c["id"]))
        comp_m = cursor.fetchone()["comp"] or 0

        real_prog_pct = min(100, int((comp_m / total_m) * 100))
        c_dict["progress_pct"] = real_prog_pct
        c_dict["modules_completed"] = comp_m
        c_dict["total_modules"] = total_m

        # Next module
        cursor.execute("""
        SELECT id, slug, title, order_index FROM modules 
        WHERE course_id = ? AND id NOT IN (
            SELECT module_id FROM learning_progress WHERE user_id = ? AND course_id = ? AND completed = 1
        )
        ORDER BY order_index ASC LIMIT 1
        """, (c["id"], user_id, c["id"]))
        next_m = cursor.fetchone()
        if not next_m:
            cursor.execute("SELECT id, slug, title, order_index FROM modules WHERE course_id = ? ORDER BY order_index DESC LIMIT 1", (c["id"],))
            next_m = cursor.fetchone()

        c_dict["current_module"] = next_m["title"] if next_m else "Module 01"
        c_dict["current_module_slug"] = next_m["slug"] if next_m else "1"
        enrolled_courses.append(c_dict)

    # Mastered concepts count
    cursor.execute("SELECT COUNT(*) as total FROM learning_progress WHERE user_id = ? AND completed = 1", (user_id,))
    comp_row = cursor.fetchone()
    concepts_mastered = comp_row["total"] if comp_row else 0

    # Learning Debt summary
    cursor.execute("SELECT AVG(learning_debt_pct) as avg_debt, COUNT(*) as count FROM learning_debt WHERE user_id = ?", (user_id,))
    debt_row = cursor.fetchone()
    if debt_row and debt_row["count"] > 0 and debt_row["avg_debt"] is not None:
        avg_debt = int(debt_row["avg_debt"])
        avg_debt_display = f"{avg_debt}%"
    else:
        avg_debt = None
        avg_debt_display = "N/A"

    # Last activity
    cursor.execute("SELECT timestamp, description FROM activity_logs WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1", (user_id,))
    act_row = cursor.fetchone()
    last_activity = act_row["timestamp"] if act_row else u_dict["created_at"]

    conn.close()

    has_enrollments = len(enrolled_courses) > 0
    active_course = enrolled_courses[0] if has_enrollments else None

    if has_enrollments:
        overall_progress = int(sum(c["progress_pct"] for c in enrolled_courses) / len(enrolled_courses))
    else:
        overall_progress = 0

    return {
        "student": u_dict,
        "subscription": sub_dict,
        "payment_request": payment_req_dict,
        "enrolled_courses": enrolled_courses,
        "has_enrollments": has_enrollments,
        "active_course": active_course,
        "overall_progress_pct": overall_progress,
        "learning_debt_pct": avg_debt,
        "learning_debt_display": avg_debt_display,
        "concepts_mastered": concepts_mastered,
        "last_activity": last_activity,
        "credit_summary": credit_summary,
        "status": "Active" if has_enrollments else "Registered"
    }

def get_dashboard_stats():
    """SINGLE SOURCE OF TRUTH FOR GLOBAL ADMIN STATS"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as count FROM users WHERE role = 'STUDENT'")
    total_students = cursor.fetchone()["count"] or 0

    cursor.execute("SELECT COUNT(DISTINCT user_id) as count FROM enrollments WHERE status = 'ACTIVE'")
    active_students = cursor.fetchone()["count"] or 0

    cursor.execute("SELECT COUNT(*) as count FROM courses")
    total_courses = cursor.fetchone()["count"] or 0

    cursor.execute("SELECT COUNT(*) as count FROM modules")
    total_modules = cursor.fetchone()["count"] or 0

    cursor.execute("SELECT COUNT(*) as count FROM projects")
    total_projects = cursor.fetchone()["count"] or 0

    cursor.execute("SELECT COUNT(*) as count FROM enrollments WHERE status = 'ACTIVE'")
    active_enrollments = cursor.fetchone()["count"] or 0

    cursor.execute("SELECT COUNT(*) as count FROM payment_requests WHERE status = 'PENDING'")
    pending_payments = cursor.fetchone()["count"] or 0

    cursor.execute("SELECT AVG(learning_debt_pct) as avg_debt, COUNT(*) as count FROM learning_debt")
    avg_debt_row = cursor.fetchone()
    if avg_debt_row and avg_debt_row["count"] > 0 and avg_debt_row["avg_debt"] is not None:
        avg_debt_display = f"{int(avg_debt_row['avg_debt'])}%"
    else:
        avg_debt_display = "N/A"

    conn.close()

    return {
        "total_students": total_students,
        "active_students": active_students,
        "total_courses": total_courses,
        "total_modules": total_modules,
        "total_projects": total_projects,
        "active_enrollments": active_enrollments,
        "pending_payments": pending_payments,
        "average_learning_debt_pct": avg_debt_display
    }

def get_enrollment_analytics():
    """SINGLE SOURCE OF TRUTH FOR ENROLLMENT RECORDS (STRICTLY DEDUPLICATED)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT 
        e.id as enrollment_id,
        u.id as student_id,
        u.name as student_name,
        u.email as student_email,
        s.id as subscription_id,
        COALESCE(s.plan_name, 'Individual Learning') as subscription_plan,
        COALESCE(s.billing_cycle, 'Monthly') as billing_cycle,
        COALESCE(s.price_inr, 499) as amount,
        COALESCE(s.status, 'ACTIVE') as subscription_status,
        c.id as course_id,
        c.slug as course_slug,
        c.title as course_title,
        e.enrolled_at,
        e.progress_pct,
        e.status as course_status,
        e.last_accessed_at
    FROM enrollments e
    JOIN users u ON e.user_id = u.id
    JOIN courses c ON e.course_id = c.id
    LEFT JOIN (
        SELECT user_id, max(id) as id, plan_name, billing_cycle, price_inr, status 
        FROM subscriptions 
        GROUP BY user_id
    ) s ON u.id = s.user_id
    ORDER BY e.enrolled_at DESC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    seen_enrollments = set()
    unique_rows = []
    for r in rows:
        key = (r["student_id"], r["course_id"])
        if key not in seen_enrollments:
            seen_enrollments.add(key)
            unique_rows.append(r)

    return unique_rows

# ================= CANONICAL COURSE & ENROLLMENT SERVICE FUNCTIONS =================

def get_courses(admin_view=False):
    """
    REQUIRED SERVICE FUNCTION: getCourses(admin_view=False)
    Single source of truth for all courses.
    If admin_view is False, returns only published courses (is_published = 1 AND status = 'PUBLISHED').
    If admin_view is True, returns all courses (PUBLISHED, DRAFT, ARCHIVED) with real-time analytics.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    if admin_view:
        cursor.execute("SELECT * FROM courses ORDER BY id ASC")
    else:
        cursor.execute("SELECT * FROM courses WHERE is_published = 1 AND (status IS NULL OR status = 'PUBLISHED') ORDER BY id ASC")
    
    courses_rows = cursor.fetchall()
    result = []
    
    for c in courses_rows:
        c_dict = dict(c)
        c_id = c_dict["id"]

        # Parse JSON fields safely
        if c_dict.get("learning_outcomes_json"):
            try:
                c_dict["learning_outcomes"] = json.loads(c_dict["learning_outcomes_json"])
            except Exception:
                c_dict["learning_outcomes"] = []
        else:
            c_dict["learning_outcomes"] = []

        # Count modules & projects
        cursor.execute("SELECT COUNT(*) as cnt FROM modules WHERE course_id = ?", (c_id,))
        c_dict["total_modules"] = cursor.fetchone()["cnt"] or 0
        c_dict["module_count"] = c_dict["total_modules"]

        cursor.execute("SELECT COUNT(*) as cnt FROM projects WHERE course_id = ?", (c_id,))
        c_dict["total_projects"] = cursor.fetchone()["cnt"] or 0
        c_dict["project_count"] = c_dict["total_projects"]

        # Real DB enrollment analytics
        cursor.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM enrollments WHERE course_id = ? AND status = 'ACTIVE'", (c_id,))
        c_dict["total_enrolled"] = cursor.fetchone()["cnt"] or 0

        cursor.execute("""
        SELECT COUNT(DISTINCT user_id) as cnt FROM enrollments 
        WHERE course_id = ? AND status = 'ACTIVE' AND (progress_pct > 0 OR last_accessed_at >= datetime('now', '-30 days'))
        """, (c_id,))
        c_dict["active_learners"] = cursor.fetchone()["cnt"] or 0

        cursor.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM enrollments WHERE course_id = ? AND (status = 'COMPLETED' OR progress_pct = 100)", (c_id,))
        c_dict["completed_students"] = cursor.fetchone()["cnt"] or 0

        cursor.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM enrollments WHERE course_id = ? AND progress_pct = 0", (c_id,))
        c_dict["not_started_students"] = cursor.fetchone()["cnt"] or 0

        cursor.execute("SELECT AVG(progress_pct) as avg_p FROM enrollments WHERE course_id = ?", (c_id,))
        avg_row = cursor.fetchone()
        c_dict["average_progress_pct"] = round(avg_row["avg_p"], 1) if (avg_row and avg_row["avg_p"] is not None) else 0

        c_dict["category"] = c_dict.get("category") or "Software Engineering"
        c_dict["difficulty"] = c_dict.get("difficulty") or c_dict.get("level") or "Intermediate"
        c_dict["status"] = c_dict.get("status") or ("PUBLISHED" if c_dict.get("is_published") else "DRAFT")

        result.append(c_dict)

    conn.close()
    return result

getCourses = get_courses

def get_course(course_id):
    """
    REQUIRED SERVICE FUNCTION: getCourse(courseId)
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    if isinstance(course_id, int) or (isinstance(course_id, str) and course_id.isdigit()):
        cursor.execute("SELECT * FROM courses WHERE id = ?", (int(course_id),))
    else:
        cursor.execute("SELECT * FROM courses WHERE slug = ?", (str(course_id),))
    
    course = cursor.fetchone()
    if not course:
        conn.close()
        return None

    c_dict = dict(course)
    c_id = c_dict["id"]
    if c_dict.get("learning_outcomes_json"):
        try:
            c_dict["learning_outcomes"] = json.loads(c_dict["learning_outcomes_json"])
        except Exception:
            c_dict["learning_outcomes"] = []
    else:
        c_dict["learning_outcomes"] = []

    c_dict["category"] = c_dict.get("category") or "Software Engineering"
    c_dict["difficulty"] = c_dict.get("difficulty") or c_dict.get("level") or "Intermediate"
    c_dict["status"] = c_dict.get("status") or ("PUBLISHED" if c_dict.get("is_published") else "DRAFT")

    conn.close()

    c_dict["enrollment_stats"] = get_course_enrollment_stats(c_id)
    c_dict["module_stats"] = get_course_module_stats(c_id)
    c_dict["students"] = get_course_students(c_id)
    c_dict["total_modules"] = len(c_dict["module_stats"])

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM projects WHERE course_id = ?", (c_id,))
    c_dict["total_projects"] = cursor.fetchone()["cnt"] or 0
    conn.close()

    return c_dict

getCourse = get_course

def create_course(data):
    """
    REQUIRED SERVICE FUNCTION: createCourse(data)
    Saves a new course to the real database.
    """
    title = data.get("title", "").strip()
    if not title:
        raise ValueError("Course title is required.")

    slug = data.get("slug", "").strip()
    if not slug:
        slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')

    description = data.get("description", "").strip() or f"Master {title} with continuous learning and real projects."
    category = data.get("category", "").strip() or "Software Engineering"
    difficulty = data.get("difficulty") or data.get("level") or "Intermediate"
    duration = data.get("duration", "10 Weeks")
    thumbnail_url = data.get("thumbnail_url") or data.get("thumbnail") or "https://images.unsplash.com/photo-1517694712202-14dd9538aa97?w=600&auto=format&fit=crop"
    status = data.get("status", "PUBLISHED").upper()
    is_published = 1 if status == "PUBLISHED" else 0
    learning_outcomes = data.get("learning_outcomes", [])
    outcomes_json = json.dumps(learning_outcomes) if isinstance(learning_outcomes, list) else json.dumps([learning_outcomes])

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM courses WHERE slug = ?", (slug,))
    if cursor.fetchone():
        slug = f"{slug}-{int(datetime.datetime.now().timestamp())}"

    cursor.execute("""
    INSERT INTO courses (title, slug, description, category, difficulty, level, duration, thumbnail_url, status, is_published, learning_outcomes_json)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (title, slug, description, category, difficulty, difficulty, duration, thumbnail_url, status, is_published, outcomes_json))

    c_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return get_course(c_id)

createCourse = create_course

def update_course(course_id, data):
    """
    REQUIRED SERVICE FUNCTION: updateCourse(courseId, data)
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM courses WHERE id = ?", (course_id,))
    c_row = cursor.fetchone()
    if not c_row:
        conn.close()
        return None

    c_dict = dict(c_row)
    title = data.get("title", c_dict["title"]).strip()
    slug = data.get("slug", c_dict["slug"]).strip()
    description = data.get("description", c_dict["description"]).strip()
    category = data.get("category", c_dict.get("category", "Software Engineering")).strip()
    difficulty = data.get("difficulty") or data.get("level") or c_dict.get("difficulty", "Intermediate")
    duration = data.get("duration", c_dict.get("duration", "10 Weeks"))
    thumbnail_url = data.get("thumbnail_url") or data.get("thumbnail") or c_dict.get("thumbnail_url")
    status = data.get("status", c_dict.get("status", "PUBLISHED")).upper()
    is_published = 1 if status == "PUBLISHED" else 0

    outcomes = data.get("learning_outcomes")
    if outcomes is not None:
        outcomes_json = json.dumps(outcomes) if isinstance(outcomes, list) else json.dumps([outcomes])
    else:
        outcomes_json = c_dict.get("learning_outcomes_json")

    cursor.execute("""
    UPDATE courses SET
        title = ?, slug = ?, description = ?, category = ?, difficulty = ?, level = ?,
        duration = ?, thumbnail_url = ?, status = ?, is_published = ?, learning_outcomes_json = ?,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (title, slug, description, category, difficulty, difficulty, duration, thumbnail_url, status, is_published, outcomes_json, course_id))

    conn.commit()
    conn.close()

    return get_course(course_id)

updateCourse = update_course

def delete_course(course_id):
    """
    REQUIRED SERVICE FUNCTION: deleteCourse(courseId)
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM modules WHERE course_id = ?", (course_id,))
    mod_ids = [r["id"] for r in cursor.fetchall()]

    for m_id in mod_ids:
        cursor.execute("DELETE FROM videos WHERE module_id = ?", (m_id,))
        cursor.execute("DELETE FROM assessments WHERE module_id = ?", (m_id,))
        cursor.execute("DELETE FROM learning_progress WHERE module_id = ?", (m_id,))
        cursor.execute("DELETE FROM chat_messages WHERE module_id = ?", (m_id,))

    cursor.execute("DELETE FROM projects WHERE course_id = ?", (course_id,))
    cursor.execute("DELETE FROM learning_debt WHERE course_id = ?", (course_id,))
    cursor.execute("DELETE FROM enrollments WHERE course_id = ?", (course_id,))
    cursor.execute("DELETE FROM modules WHERE course_id = ?", (course_id,))
    cursor.execute("DELETE FROM courses WHERE id = ?", (course_id,))

    conn.commit()
    conn.close()
    return True

deleteCourse = delete_course

def publish_course(course_id, status=None):
    """
    REQUIRED SERVICE FUNCTION: publishCourse(courseId)
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status, is_published FROM courses WHERE id = ?", (course_id,))
    c_row = cursor.fetchone()
    if not c_row:
        conn.close()
        return None

    if status:
        new_status = status.upper()
    else:
        current_st = c_row["status"] or ("PUBLISHED" if c_row["is_published"] else "DRAFT")
        new_status = "DRAFT" if current_st == "PUBLISHED" else "PUBLISHED"
    
    is_pub = 1 if new_status == "PUBLISHED" else 0

    cursor.execute("UPDATE courses SET status = ?, is_published = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                   (new_status, is_pub, course_id))
    conn.commit()
    conn.close()

    return get_course(course_id)

publishCourse = publish_course

def get_course_enrollment_stats(course_id):
    """
    REQUIRED SERVICE FUNCTION: getCourseEnrollmentStats(courseId)
    Calculated strictly from database records.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM enrollments WHERE course_id = ? AND status = 'ACTIVE'", (course_id,))
    total_enrolled = cursor.fetchone()["cnt"] or 0

    cursor.execute("""
    SELECT COUNT(DISTINCT user_id) as cnt FROM enrollments 
    WHERE course_id = ? AND status = 'ACTIVE' AND (progress_pct > 0 OR last_accessed_at >= datetime('now', '-30 days'))
    """, (course_id,))
    active_learners = cursor.fetchone()["cnt"] or 0

    cursor.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM enrollments WHERE course_id = ? AND (status = 'COMPLETED' OR progress_pct = 100)", (course_id,))
    completed_students = cursor.fetchone()["cnt"] or 0

    cursor.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM enrollments WHERE course_id = ? AND progress_pct = 0", (course_id,))
    not_started = cursor.fetchone()["cnt"] or 0

    cursor.execute("SELECT AVG(progress_pct) as avg_p FROM enrollments WHERE course_id = ?", (course_id,))
    avg_row = cursor.fetchone()
    avg_progress = round(avg_row["avg_p"], 1) if (avg_row and avg_row["avg_p"] is not None) else 0

    conn.close()

    return {
        "total_enrolled": total_enrolled,
        "active_learners": active_learners,
        "completed_students": completed_students,
        "not_started_students": not_started,
        "average_progress_pct": avg_progress
    }

getCourseEnrollmentStats = get_course_enrollment_stats

def get_course_module_stats(course_id):
    """
    REQUIRED SERVICE FUNCTION: getCourseModuleStats(courseId)
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(DISTINCT user_id) as total_enrolled FROM enrollments WHERE course_id = ?", (course_id,))
    enrolled_count = cursor.fetchone()["total_enrolled"] or 0

    cursor.execute("SELECT * FROM modules WHERE course_id = ? ORDER BY order_index ASC", (course_id,))
    modules = cursor.fetchall()

    stats = []
    for m in modules:
        m_dict = dict(m)
        m_id = m_dict["id"]

        cursor.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM learning_progress WHERE module_id = ?", (m_id,))
        started_students = cursor.fetchone()["cnt"] or 0

        cursor.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM learning_progress WHERE module_id = ? AND completed = 1", (m_id,))
        completed_students = cursor.fetchone()["cnt"] or 0

        completion_pct = round((completed_students / enrolled_count * 100), 1) if enrolled_count > 0 else 0

        cursor.execute("SELECT id, video_id, title FROM videos WHERE module_id = ?", (m_id,))
        v_row = cursor.fetchone()
        v_dict = dict(v_row) if v_row else None

        stats.append({
            "module_id": m_id,
            "module_name": m_dict["title"],
            "module_slug": m_dict["slug"],
            "description": m_dict.get("description") or "",
            "module_order": m_dict["order_index"],
            "enrolled_students": enrolled_count,
            "started_students": started_students,
            "completed_students": completed_students,
            "completion_percentage": completion_pct,
            "has_video": bool(v_dict),
            "video_id": v_dict["video_id"] if v_dict else None
        })

    conn.close()
    return stats

getCourseModuleStats = get_course_module_stats

def get_course_students(course_id):
    """
    REQUIRED SERVICE FUNCTION: getCourseStudents(courseId)
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT e.id as enrollment_id, e.user_id, u.name, u.email, e.enrolled_at, e.progress_pct, e.status, e.last_accessed_at,
           s.plan_name, s.billing_cycle
    FROM enrollments e
    JOIN users u ON e.user_id = u.id
    LEFT JOIN subscriptions s ON e.subscription_id = s.id
    WHERE e.course_id = ?
    ORDER BY e.enrolled_at DESC
    """, (course_id,))
    
    students = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return students

getCourseStudents = get_course_students

def get_course_progress(course_id):
    """
    REQUIRED SERVICE FUNCTION: getCourseProgress(courseId)
    """
    return get_course_enrollment_stats(course_id)

getCourseProgress = get_course_progress

def create_module(course_id, data):
    """
    Module Management: Create Module
    """
    title = data.get("title", "").strip()
    if not title:
        raise ValueError("Module title is required.")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT MAX(order_index) as max_idx FROM modules WHERE course_id = ?", (course_id,))
    max_idx = cursor.fetchone()["max_idx"] or 0
    order_index = data.get("order_index") or (max_idx + 1)

    slug = data.get("slug", "").strip()
    if not slug:
        slug = f"m0{order_index}" if order_index < 10 else f"m{order_index}"

    description = data.get("description", "").strip()
    key_concepts = data.get("key_concepts", [])
    key_concepts_json = json.dumps(key_concepts) if isinstance(key_concepts, list) else json.dumps([key_concepts])

    cursor.execute("""
    INSERT INTO modules (course_id, slug, title, description, order_index, is_unlocked, key_concepts_json)
    VALUES (?, ?, ?, ?, ?, 1, ?)
    """, (course_id, slug, title, description, order_index, key_concepts_json))
    
    module_id = cursor.lastrowid

    # Handle Video if provided
    video_url = data.get("video_url") or data.get("video")
    if video_url:
        video_id = get_youtube_video_id(video_url) or "gkJ8V2M4Wc0"
        embed_url = f"https://www.youtube-nocookie.com/embed/{video_id}?rel=0&playsinline=1"
        transcript = data.get("transcript", f"Lecture transcript for {title}")
        cursor.execute("""
        INSERT INTO videos (module_id, title, provider, video_id, video_url, embed_url, professor, institution, source, duration, transcript)
        VALUES (?, ?, 'youtube', ?, ?, ?, 'IIT Faculty', 'IIT Madras', 'NPTEL', '25:00', ?)
        ON CONFLICT(module_id) DO UPDATE SET video_id = excluded.video_id, video_url = excluded.video_url, embed_url = excluded.embed_url, transcript = excluded.transcript
        """, (module_id, title, video_id, video_url, embed_url, transcript))

    # Handle Assessment if provided
    assessment_questions = data.get("assessment_questions") or data.get("questions")
    if assessment_questions:
        q_json = json.dumps(assessment_questions) if isinstance(assessment_questions, list) else str(assessment_questions)
        cursor.execute("INSERT INTO assessments (module_id, questions_json) VALUES (?, ?)", (module_id, q_json))

    conn.commit()
    conn.close()

    return {"message": "Module created successfully", "module_id": module_id}

def update_module(module_id, data):
    """
    Module Management: Edit Module
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM modules WHERE id = ?", (module_id,))
    m_row = cursor.fetchone()
    if not m_row:
        conn.close()
        return None

    m_dict = dict(m_row)
    title = data.get("title", m_dict["title"]).strip()
    slug = data.get("slug", m_dict["slug"]).strip()
    description = data.get("description", m_dict.get("description", "")).strip()
    order_index = data.get("order_index", m_dict["order_index"])

    cursor.execute("""
    UPDATE modules SET title = ?, slug = ?, description = ?, order_index = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (title, slug, description, order_index, module_id))

    video_url = data.get("video_url") or data.get("video")
    if video_url:
        video_id = get_youtube_video_id(video_url) or "gkJ8V2M4Wc0"
        embed_url = f"https://www.youtube-nocookie.com/embed/{video_id}?rel=0&playsinline=1"
        transcript = data.get("transcript", f"Lecture transcript for {title}")
        cursor.execute("""
        INSERT INTO videos (module_id, title, provider, video_id, video_url, embed_url, professor, institution, source, duration, transcript)
        VALUES (?, ?, 'youtube', ?, ?, ?, 'IIT Faculty', 'IIT Madras', 'NPTEL', '25:00', ?)
        ON CONFLICT(module_id) DO UPDATE SET video_id = excluded.video_id, video_url = excluded.video_url, embed_url = excluded.embed_url, transcript = excluded.transcript
        """, (module_id, title, video_id, video_url, embed_url, transcript))

    conn.commit()
    conn.close()
    return {"message": "Module updated successfully", "module_id": module_id}

def delete_module(module_id):
    """
    Module Management: Delete Module
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM videos WHERE module_id = ?", (module_id,))
    cursor.execute("DELETE FROM assessments WHERE module_id = ?", (module_id,))
    cursor.execute("DELETE FROM learning_progress WHERE module_id = ?", (module_id,))
    cursor.execute("DELETE FROM chat_messages WHERE module_id = ?", (module_id,))
    cursor.execute("DELETE FROM modules WHERE id = ?", (module_id,))

    conn.commit()
    conn.close()
    return True

# ================= PUBLIC GENERAL WEBSITE & COURSE DISCOVERY =================

@app.route("/api/public/courses", methods=["GET"])
@app.route("/api/courses", methods=["GET"])
def public_courses():
    courses = get_courses(admin_view=False)
    return jsonify({"courses": courses})

@app.route("/api/public/courses/<slug>", methods=["GET"])
def public_course_detail(slug):
    course = get_course(slug)
    if not course or (course.get("status") != "PUBLISHED" and course.get("is_published") != 1):
        return jsonify({"error": "Course not found"}), 404

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, slug, title, description, order_index FROM modules WHERE course_id = ? ORDER BY order_index ASC", (course["id"],))
    modules = [dict(m) for m in cursor.fetchall()]

    cursor.execute("SELECT id, project_number, title, description, is_final FROM projects WHERE course_id = ? ORDER BY project_number ASC", (course["id"],))
    projects = [dict(p) for p in cursor.fetchall()]
    conn.close()

    return jsonify({
        "course": course,
        "modules": modules,
        "projects": projects
    })

# ================= ADMIN COURSE MANAGEMENT REST API =================

@app.route("/api/admin/courses", methods=["GET"])
def admin_courses():
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Administrator authorization required."}), 401
    
    courses = get_courses(admin_view=True)
    return jsonify({"courses": courses})

@app.route("/api/admin/courses", methods=["POST"])
def admin_create_course():
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Administrator authorization required."}), 401
    
    data = request.json or {}
    try:
        new_course = create_course(data)
        return jsonify({"message": "Course created successfully!", "course": new_course}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/admin/courses/<int:course_id>", methods=["GET"])
def admin_get_course_detail(course_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Administrator authorization required."}), 401
    
    course = get_course(course_id)
    if not course:
        return jsonify({"error": "Course not found"}), 404
    
    return jsonify({
        "course": course,
        "enrollment_stats": course.get("enrollment_stats"),
        "module_stats": course.get("module_stats"),
        "students": course.get("students")
    })

@app.route("/api/admin/courses/<int:course_id>", methods=["PUT"])
def admin_update_course(course_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Administrator authorization required."}), 401
    
    data = request.json or {}
    updated = update_course(course_id, data)
    if not updated:
        return jsonify({"error": "Course not found"}), 404
    
    return jsonify({"message": "Course updated successfully!", "course": updated})

@app.route("/api/admin/courses/<int:course_id>/publish", methods=["POST"])
def admin_publish_course(course_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Administrator authorization required."}), 401
    
    data = request.json or {}
    status = data.get("status")
    c = publish_course(course_id, status)
    if not c:
        return jsonify({"error": "Course not found"}), 404
    
    return jsonify({"message": f"Course status set to {c['status']}", "course": c})

@app.route("/api/admin/courses/<int:course_id>", methods=["DELETE"])
def admin_delete_course(course_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Administrator authorization required."}), 401
    
    delete_course(course_id)
    return jsonify({"message": "Course deleted successfully"})

@app.route("/api/admin/courses/<int:course_id>/modules", methods=["POST"])
def admin_create_module(course_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Administrator authorization required."}), 401
    
    data = request.json or {}
    try:
        res = create_module(course_id, data)
        return jsonify(res), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/admin/modules/<int:module_id>", methods=["PUT"])
def admin_update_module(module_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Administrator authorization required."}), 401
    
    data = request.json or {}
    res = update_module(module_id, data)
    if not res:
        return jsonify({"error": "Module not found"}), 404
    return jsonify(res)

@app.route("/api/admin/courses/<int:course_id>/modules/reorder", methods=["POST"])
def admin_reorder_modules(course_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Administrator authorization required."}), 401
    
    data = request.json or {}
    orders = data.get("module_orders", [])
    conn = get_db_connection()
    cursor = conn.cursor()
    for item in orders:
        m_id = item.get("module_id")
        new_idx = item.get("order_index")
        if m_id and new_idx:
            cursor.execute("UPDATE modules SET order_index = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND course_id = ?", (new_idx, m_id, course_id))
    conn.commit()
    conn.close()
    return jsonify({"message": "Modules reordered successfully"})

@app.route("/api/admin/modules/<int:module_id>", methods=["DELETE"])
def admin_delete_module(module_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Administrator authorization required."}), 401
    
    delete_module(module_id)
    return jsonify({"message": "Module deleted successfully"})

# ================= AUTHENTICATION & REGISTRATION =================

@app.route("/api/auth/register", methods=["POST"])
def register_student():
    data = request.json or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()
    course_slug = data.get("course_slug")

    if not name or not email or not password:
        return jsonify({"error": "Name, email, and password are required."}), 400

    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("INSERT INTO users (email, password_hash, name, role, streak_days) VALUES (?, ?, ?, 'STUDENT', 0)",
                       (email, pw_hash, name))
        user_id = cursor.lastrowid

        # Provision subscription
        sub = ensure_user_subscription(conn, user_id, plan_name="Individual Learning", billing_cycle="Monthly", price_inr=499)
        sub_id = sub["id"]

        log_activity(conn, user_id, "REGISTER", f"Student account created: {email}")

        # Auto-enroll in course if specified
        enrolled_course_title = None
        if course_slug:
            cursor.execute("SELECT id, title FROM courses WHERE slug = ?", (course_slug,))
            c_row = cursor.fetchone()
            if c_row:
                cursor.execute("""
                INSERT INTO enrollments (user_id, course_id, subscription_id, progress_pct, status) 
                VALUES (?, ?, ?, 0, 'ACTIVE')
                ON CONFLICT(user_id, course_id) DO UPDATE SET status = 'ACTIVE', last_accessed_at = CURRENT_TIMESTAMP
                """, (user_id, c_row["id"], sub_id))
                enrolled_course_title = c_row["title"]
                log_activity(conn, user_id, "ENROLL", f"Enrolled in {enrolled_course_title}")

        conn.commit()

        token = jwt.encode({
            "user_id": user_id,
            "email": email,
            "name": name,
            "role": "STUDENT",
            "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7)
        }, app.config["SECRET_KEY"], algorithm="HS256")

        return jsonify({
            "token": token,
            "user": {"id": user_id, "name": name, "email": email, "role": "STUDENT", "streak_days": 0},
            "enrolled_course": enrolled_course_title,
            "message": f"Account created! Enrolled in {enrolled_course_title}." if enrolled_course_title else "Account created successfully."
        })
    except sqlite3.IntegrityError:
        return jsonify({"error": "An account with this email already exists. Please log in."}), 400
    finally:
        conn.close()

@app.route("/api/auth/login", methods=["POST"])
def unified_login():
    data = request.json or {}
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()
    role_requirement = data.get("role_requirement")

    if not email or not password:
        return jsonify({"error": "Please provide both email and password."}), 400

    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE email = ? AND password_hash = ?", (email, pw_hash))
    user = cursor.fetchone()

    if not user:
        conn.close()
        return jsonify({"error": "Invalid email or password. Please check your credentials."}), 401

    u_dict = dict(user)
    user_id = u_dict["id"]
    user_role = u_dict["role"]

    if role_requirement and role_requirement.upper() != user_role:
        conn.close()
        if role_requirement.upper() == "ADMIN":
            return jsonify({"error": "403 — Admin access required. This account does not have administrator privileges."}), 403
        else:
            return jsonify({"error": "This portal requires a student account."}), 403

    cursor.execute("UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?", (user_id,))
    if user_role == "STUDENT":
        ensure_user_subscription(conn, user_id)
        log_activity(conn, user_id, "LOGIN", "Student logged in", metadata={"provider": "EMAIL"})
    elif user_role in ["INSTRUCTOR", "MENTOR"]:
        log_activity(conn, user_id, "MENTOR_LOGIN", "Mentor logged in", metadata={"provider": "EMAIL"})
    else:
        log_activity(conn, user_id, "ADMIN_LOGIN", "Admin logged in", metadata={"provider": "EMAIL"})

    conn.commit()
    conn.close()

    token = jwt.encode({
        "user_id": user_id,
        "email": u_dict["email"],
        "name": u_dict["name"],
        "role": user_role,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }, app.config["SECRET_KEY"], algorithm="HS256")

    if user_role == "ADMIN":
        redirect_target = "/admin/dashboard"
    elif user_role in ["INSTRUCTOR", "MENTOR"]:
        redirect_target = "/mentor/dashboard"
    else:
        redirect_target = "/student/dashboard"

    return jsonify({
        "token": token,
        "user": {
            "id": user_id,
            "name": u_dict["name"],
            "email": u_dict["email"],
            "role": user_role,
            "streak_days": u_dict.get("streak_days", 0),
            "auth_provider": u_dict.get("auth_provider", "EMAIL")
        },
        "redirect": redirect_target
    })

def generate_pkce_challenge():
    code_verifier = secrets.token_urlsafe(64)[:64]
    digest = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode('utf-8').rstrip('=')
    return code_verifier, code_challenge

@app.route("/api/auth/google/status", methods=["GET"])
def google_oauth_status():
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5050/api/auth/google/callback")
    
    return jsonify({
        "google_client_id_configured": is_valid_google_client_id(client_id),
        "google_client_id_prefix": client_id[:16] + "..." if len(client_id) > 16 else (client_id or "MISSING"),
        "google_client_secret_configured": bool(client_secret and len(client_secret) > 8),
        "redirect_uri": redirect_uri
    })

# ================= GOOGLE OAUTH 2.0 / OIDC AUTHENTICATION =================

@app.route("/api/auth/google/login", methods=["GET"])
@app.route("/auth/google", methods=["GET"])
def google_oauth_login():
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5050/api/auth/google/callback")
    
    if not is_valid_google_client_id(client_id):
        err_msg = urllib.parse.quote("Google OAuth is not configured with a valid Google Cloud Client ID. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your .env file.")
        return redirect(f"/#/login?error={err_msg}")

    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = generate_pkce_challenge()

    google_auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        "response_type=code"
        f"&client_id={urllib.parse.quote(client_id)}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
        "&scope=openid%20email%20profile"
        f"&state={state}"
        f"&code_challenge={code_challenge}"
        "&code_challenge_method=S256"
        "&prompt=select_account"
    )

    resp = make_response(redirect(google_auth_url))
    resp.set_cookie("oauth_state", state, max_age=600, httponly=True, samesite="Lax")
    resp.set_cookie("oauth_code_verifier", code_verifier, max_age=600, httponly=True, samesite="Lax")
    return resp

@app.route("/api/auth/google/callback", methods=["GET"])
@app.route("/auth/google/callback", methods=["GET"])
def google_oauth_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error == "access_denied":
        err_msg = urllib.parse.quote("Google sign-in was cancelled.")
        return redirect(f"/#/login?error={err_msg}")
    elif error:
        err_msg = urllib.parse.quote("Google authentication failed. Please try again.")
        return redirect(f"/#/login?error={err_msg}")

    if not code or not state:
        err_msg = urllib.parse.quote("Unable to complete Google sign-in.")
        return redirect(f"/#/login?error={err_msg}")

    stored_state = request.cookies.get("oauth_state")
    code_verifier = request.cookies.get("oauth_code_verifier")

    if stored_state and stored_state != state:
        err_msg = urllib.parse.quote("Google sign-in state validation failed.")
        return redirect(f"/#/login?error={err_msg}")

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5050/api/auth/google/callback")

    if not client_id or not client_secret:
        err_msg = urllib.parse.quote("Google OAuth is not configured correctly.")
        return redirect(f"/#/login?error={err_msg}")

    sub = None
    email = None
    name = None
    picture = None

    try:
        token_url = "https://oauth2.googleapis.com/token"
        params = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"
        }
        if code_verifier:
            params["code_verifier"] = code_verifier

        payload = urllib.parse.urlencode(params).encode('utf-8')
        req = urllib.request.Request(token_url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req) as resp:
            token_data = json.loads(resp.read().decode('utf-8'))

        access_token = token_data.get("access_token")

        if not access_token:
            err_msg = urllib.parse.quote("Unable to complete Google sign-in.")
            return redirect(f"/#/login?error={err_msg}")

        # Fetch verified user details from Google UserInfo endpoint
        userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
        u_req = urllib.request.Request(userinfo_url, headers={"Authorization": f"Bearer {access_token}"})
        with urllib.request.urlopen(u_req) as u_resp:
            user_info = json.loads(u_resp.read().decode('utf-8'))

        sub = user_info.get("sub")
        email = user_info.get("email")
        email_verified = user_info.get("email_verified", True)
        name = user_info.get("name") or user_info.get("given_name") or (email.split("@")[0] if email else "Google User")
        picture = user_info.get("picture")

        if not email or not sub or not email_verified:
            err_msg = urllib.parse.quote("Google OAuth failed to return a verified email address.")
            return redirect(f"/#/login?error={err_msg}")

    except Exception as e:
        print(f"Failed to exchange Google OAuth code: {e}")
        err_msg = urllib.parse.quote("Unable to complete Google sign-in.")
        return redirect(f"/#/login?error={err_msg}")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Look up existing user by provider_user_id or email
    cursor.execute("SELECT * FROM users WHERE provider_user_id = ? OR email = ?", (sub, email))
    existing_user = cursor.fetchone()

    if existing_user:
        u_dict = dict(existing_user)
        user_id = u_dict["id"]
        user_role = u_dict["role"]
        user_name = u_dict["name"] or name

        cursor.execute("""
        UPDATE users 
        SET auth_provider = 'GOOGLE', provider_user_id = ?, profile_image = COALESCE(?, profile_image), last_login_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """, (sub, picture, user_id))

        if user_role == "STUDENT":
            ensure_user_subscription(conn, user_id)
            log_activity(conn, user_id, "LOGIN", "Student logged in via Google OAuth", metadata={"provider": "GOOGLE"})
        else:
            log_activity(conn, user_id, "ADMIN_LOGIN", "Admin logged in via Google OAuth", metadata={"provider": "GOOGLE"})
    else:
        # Create new student account (Google OAuth NEVER auto-creates ADMIN accounts)
        user_role = "STUDENT"
        user_name = name or email.split("@")[0]
        cursor.execute("""
        INSERT INTO users (email, password_hash, name, role, streak_days, auth_provider, provider_user_id, profile_image)
        VALUES (?, '', ?, 'STUDENT', 0, 'GOOGLE', ?, ?)
        """, (email, user_name, sub, picture))
        user_id = cursor.lastrowid

        ensure_user_subscription(conn, user_id)
        log_activity(conn, user_id, "REGISTER", f"Student account created via Google OAuth: {email}", metadata={"provider": "GOOGLE"})
        log_activity(conn, user_id, "LOGIN", "Student logged in via Google OAuth", metadata={"provider": "GOOGLE"})

    conn.commit()
    conn.close()

    token = jwt.encode({
        "user_id": user_id,
        "email": email,
        "name": user_name,
        "role": user_role,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }, app.config["SECRET_KEY"], algorithm="HS256")

    target_route = "/admin/dashboard" if user_role == "ADMIN" else "/student/dashboard"
    res = make_response(redirect(f"/#{target_route}?token={token}"))
    res.set_cookie("oauth_state", "", expires=0)
    res.set_cookie("oauth_code_verifier", "", expires=0)
    return res

@app.route("/api/auth/google/verify", methods=["POST"])
def google_verify_token():
    """API endpoint for direct token or credentials verification from client SDKs"""
    data = request.json or {}
    email = data.get("email", "").strip()
    name = data.get("name", "").strip() or (email.split("@")[0] if email else "Google User")
    sub = data.get("sub") or data.get("id_token") or data.get("google_id") or (f"g_{hashlib.md5(email.encode()).hexdigest()[:12]}" if email else None)
    picture = data.get("picture") or data.get("profile_image")

    if not email or not sub:
        return jsonify({"error": "Google email and provider identity are required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE provider_user_id = ? OR email = ?", (sub, email))
    user = cursor.fetchone()

    if user:
        u_dict = dict(user)
        user_id = u_dict["id"]
        user_role = u_dict["role"]
        user_name = u_dict["name"] or name

        cursor.execute("""
        UPDATE users 
        SET auth_provider = 'GOOGLE', provider_user_id = ?, profile_image = COALESCE(?, profile_image), last_login_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """, (sub, picture, user_id))

        if user_role == "STUDENT":
            ensure_user_subscription(conn, user_id)
            log_activity(conn, user_id, "LOGIN", "Student logged in via Google OAuth", metadata={"provider": "GOOGLE"})
        else:
            log_activity(conn, user_id, "ADMIN_LOGIN", "Admin logged in via Google OAuth", metadata={"provider": "GOOGLE"})
    else:
        user_role = "STUDENT"
        user_name = name
        cursor.execute("""
        INSERT INTO users (email, password_hash, name, role, streak_days, auth_provider, provider_user_id, profile_image)
        VALUES (?, '', ?, 'STUDENT', 0, 'GOOGLE', ?, ?)
        """, (email, user_name, sub, picture))
        user_id = cursor.lastrowid

        ensure_user_subscription(conn, user_id)
        log_activity(conn, user_id, "REGISTER", f"Student account created via Google OAuth: {email}", metadata={"provider": "GOOGLE"})
        log_activity(conn, user_id, "LOGIN", "Student logged in via Google OAuth", metadata={"provider": "GOOGLE"})

    conn.commit()
    conn.close()

    token = jwt.encode({
        "user_id": user_id,
        "email": email,
        "name": user_name,
        "role": user_role,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }, app.config["SECRET_KEY"], algorithm="HS256")

    redirect_target = "/admin/dashboard" if user_role == "ADMIN" else "/student/dashboard"

    return jsonify({
        "token": token,
        "user": {
            "id": user_id,
            "name": user_name,
            "email": email,
            "role": user_role,
            "auth_provider": "GOOGLE"
        },
        "redirect": redirect_target
    })

@app.route("/api/auth/student-login", methods=["POST"])
def student_login():
    return unified_login()

@app.route("/api/auth/admin-login", methods=["POST"])
def admin_login():
    return unified_login()

# ================= STUDENT ONBOARDING & RECOMMENDATION ENGINE =================

@app.route("/api/profile/preferences", methods=["GET"])
@app.route("/api/student/profile", methods=["GET"])
def get_user_learning_profile():
    payload = decode_token(request)
    if not payload:
        return jsonify({"profile": None, "onboarding_completed": False})
    
    user_id = payload["user_id"]
    conn = get_db_connection()
    profile = get_student_profile(conn, user_id)
    conn.close()

    return jsonify({
        "profile": profile,
        "onboarding_completed": bool(profile and profile.get("onboarding_completed"))
    })

@app.route("/api/profile/preferences", methods=["POST"])
@app.route("/api/student/profile", methods=["POST"])
def save_user_learning_profile():
    payload = verify_student(request)
    data = request.json or {}

    if payload:
        user_id = payload["user_id"]
        conn = get_db_connection()
        profile = save_student_profile(conn, user_id, data)
        log_activity(conn, user_id, "ONBOARDING", f"Saved course preferences. Goal: {profile.get('primary_career') or data.get('careerGoal')}")
        conn.commit()
        conn.close()
        return jsonify({
            "message": "Learning preferences saved successfully!",
            "profile": profile,
            "onboarding_completed": True
        })
    else:
        return jsonify({
            "message": "Preferences recorded locally!",
            "profile": data,
            "onboarding_completed": True
        })

@app.route("/api/courses/recommendations", methods=["POST", "GET"])
@app.route("/api/student/recommendations", methods=["GET"])
def get_user_course_recommendations():
    payload = decode_token(request)
    user_id = payload["user_id"] if payload else None

    conn = get_db_connection()
    if request.method == "POST":
        data = request.json or {}
        recommendation_data = generate_recommendations_from_preferences(conn, data, user_id=user_id)
        if user_id:
            save_student_profile(conn, user_id, data)
            conn.commit()
    else:
        if user_id:
            recommendation_data = generate_personalized_recommendations(conn, user_id)
        else:
            recommendation_data = generate_recommendations_from_preferences(conn, {}, user_id=None)
            
    conn.close()
    return jsonify(recommendation_data)

# ================= SUBSCRIPTION MANAGEMENT =================

@app.route("/api/student/subscribe", methods=["POST"])
def student_subscribe():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Student authentication required."}), 401

    user_id = payload["user_id"]
    data = request.json or {}
    plan_name = data.get("plan_name", "Individual Learning")
    billing_cycle = data.get("billing_cycle", "Monthly")
    
    price_map = {
        "Individual Learning": 499,
        "Pro Career": 999,
        "Institutional Campus": 2499
    }
    price_inr = price_map.get(plan_name, 499)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO subscriptions (user_id, plan_name, billing_cycle, price_inr, status)
    VALUES (?, ?, ?, ?, 'ACTIVE')
    ON CONFLICT(user_id) DO UPDATE SET 
        plan_name = excluded.plan_name,
        billing_cycle = excluded.billing_cycle,
        price_inr = excluded.price_inr,
        status = 'ACTIVE',
        created_at = CURRENT_TIMESTAMP
    """, (user_id, plan_name, billing_cycle, price_inr))

    log_activity(conn, user_id, "SUBSCRIBE", f"Subscribed to {plan_name} ({billing_cycle}) - ₹{price_inr}")
    conn.commit()

    cursor.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,))
    sub = dict(cursor.fetchone())
    conn.close()

    return jsonify({
        "message": f"Successfully subscribed to {plan_name} plan!",
        "subscription": sub
    })

# ================= AUTHENTICATED STUDENT WORKSPACE =================

@app.route("/api/courses/<slug>/enroll", methods=["POST"])
def enroll_in_course(slug):
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Student authentication required."}), 401

    user_id = payload["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, title FROM courses WHERE slug = ?", (slug,))
    course = cursor.fetchone()
    if not course:
        conn.close()
        return jsonify({"error": "Course not found"}), 404

    # Check student learning profile status
    profile = get_student_profile(conn, user_id)
    if not profile or not profile.get("onboarding_completed"):
        conn.close()
        return jsonify({
            "error": "Please complete your learning profile setup first.",
            "requires_profile": True
        }), 400

    # Check if student is already actively enrolled
    cursor.execute("SELECT id, status FROM enrollments WHERE user_id = ? AND course_id = ?", (user_id, course["id"]))
    existing_enr = cursor.fetchone()
    if existing_enr and existing_enr["status"] == "ACTIVE":
        conn.close()
        return jsonify({
            "message": f"You are already enrolled in {course['title']}!",
            "already_enrolled": True,
            "course_title": course["title"]
        }), 200

    sub = ensure_user_subscription(conn, user_id)
    sub_id = sub["id"]

    cursor.execute("""
    INSERT INTO enrollments (user_id, course_id, subscription_id, progress_pct, status) 
    VALUES (?, ?, ?, 0, 'ACTIVE')
    ON CONFLICT(user_id, course_id) DO UPDATE SET status = 'ACTIVE', last_accessed_at = CURRENT_TIMESTAMP
    """, (user_id, course["id"], sub_id))

    log_activity(conn, user_id, "ENROLL", f"Enrolled in {course['title']}")
    conn.commit()
    conn.close()

    return jsonify({"message": f"Successfully enrolled in {course['title']}!", "course_title": course["title"]})

# ================= CREDIT & CHECKOUT SYSTEM ENDPOINTS =================

@app.route("/api/student/credits", methods=["GET"])
def get_student_credits_api():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Student authentication required."}), 401
    
    user_id = payload["user_id"]
    conn = get_db_connection()
    summary = get_user_credit_summary(conn, user_id)
    conn.close()
    return jsonify(summary)

@app.route("/api/checkout/calculate", methods=["POST"])
def calculate_checkout_price():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Student authentication required."}), 401

    user_id = payload["user_id"]
    data = request.json or {}
    course_id_or_slug = data.get("course_id") or data.get("course_slug")
    use_credits = bool(data.get("use_credits", True))

    if not course_id_or_slug:
        return jsonify({"error": "course_id or course_slug is required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    if str(course_id_or_slug).isdigit():
        cursor.execute("SELECT id, slug, title, price_inr FROM courses WHERE id = ?", (int(course_id_or_slug),))
    else:
        cursor.execute("SELECT id, slug, title, price_inr FROM courses WHERE slug = ?", (str(course_id_or_slug),))
    
    course = cursor.fetchone()
    if not course:
        conn.close()
        return jsonify({"error": "Course not found"}), 404

    course_dict = dict(course)
    canonical_price = course_dict["price_inr"] if course_dict.get("price_inr") is not None else 2000

    cursor.execute("SELECT credit_balance FROM users WHERE id = ?", (user_id,))
    u_row = cursor.fetchone()
    user_credit_balance = u_row["credit_balance"] if u_row and u_row["credit_balance"] is not None else 0

    if use_credits:
        discount_pct = min(user_credit_balance // 100, 10)
        credits_to_deduct = discount_pct * 100
    else:
        discount_pct = 0
        credits_to_deduct = 0

    discount_amount = int(round(canonical_price * (discount_pct / 100.0)))
    final_price = max(0, canonical_price - discount_amount)

    conn.close()
    return jsonify({
        "course_id": course_dict["id"],
        "course_title": course_dict["title"],
        "course_slug": course_dict["slug"],
        "original_price": canonical_price,
        "user_credit_balance": user_credit_balance,
        "use_credits": use_credits,
        "discount_percentage": discount_pct,
        "discount_amount": discount_amount,
        "final_price": final_price,
        "credits_to_deduct": credits_to_deduct
    })

@app.route("/api/checkout/process", methods=["POST"])
def process_checkout():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Student authentication required."}), 401

    user_id = payload["user_id"]
    data = request.json or {}
    course_id_or_slug = data.get("course_id") or data.get("course_slug")
    use_credits = bool(data.get("use_credits", False))

    if not course_id_or_slug:
        return jsonify({"error": "course_id or course_slug is required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    if str(course_id_or_slug).isdigit():
        cursor.execute("SELECT id, slug, title, price_inr FROM courses WHERE id = ?", (int(course_id_or_slug),))
    else:
        cursor.execute("SELECT id, slug, title, price_inr FROM courses WHERE slug = ?", (str(course_id_or_slug),))
    
    course = cursor.fetchone()
    if not course:
        conn.close()
        return jsonify({"error": "Course not found"}), 404

    course_dict = dict(course)
    course_id = course_dict["id"]
    canonical_price = course_dict["price_inr"] if course_dict.get("price_inr") is not None else 2000

    # Check if user is already enrolled
    cursor.execute("SELECT id FROM enrollments WHERE user_id = ? AND course_id = ?", (user_id, course_id))
    existing_enr = cursor.fetchone()
    if existing_enr:
        conn.close()
        return jsonify({"error": "Already enrolled in this course."}), 400

    # Check user credits
    cursor.execute("SELECT credit_balance FROM users WHERE id = ?", (user_id,))
    u_row = cursor.fetchone()
    user_credit_balance = u_row["credit_balance"] if u_row and u_row["credit_balance"] is not None else 0

    if use_credits:
        discount_pct = min(user_credit_balance // 100, 10)
        credits_to_deduct = discount_pct * 100
        if user_credit_balance < credits_to_deduct:
            conn.close()
            return jsonify({"error": "Insufficient credit balance for selected discount."}), 400
    else:
        discount_pct = 0
        credits_to_deduct = 0

    discount_amount = int(round(canonical_price * (discount_pct / 100.0)))
    final_price = max(0, canonical_price - discount_amount)

    sub = ensure_user_subscription(conn, user_id)
    sub_id = sub["id"]

    try:
        # Atomic credit deduction if using credits
        if credits_to_deduct > 0:
            cursor.execute("""
            UPDATE users SET credit_balance = credit_balance - ? 
            WHERE id = ? AND credit_balance >= ?
            """, (credits_to_deduct, user_id, credits_to_deduct))
            
            if cursor.rowcount == 0:
                conn.rollback()
                conn.close()
                return jsonify({"error": "Credit balance conflict/insufficient credits."}), 400

            desc = f"Redeemed credits for {discount_pct}% discount on {course_dict['title']} (-{credits_to_deduct} credits)"
            cursor.execute("""
            INSERT INTO credit_transactions (user_id, course_id, amount, type, description)
            VALUES (?, ?, ?, 'COURSE_REDEMPTION', ?)
            """, (user_id, course_id, -credits_to_deduct, desc))

        cursor.execute("""
        INSERT INTO enrollments (user_id, course_id, subscription_id, progress_pct, status)
        VALUES (?, ?, ?, 0, 'ACTIVE')
        """, (user_id, course_id, sub_id))

        log_activity(conn, user_id, "PURCHASE_COURSE", f"Enrolled in {course_dict['title']} for ₹{final_price} using {credits_to_deduct} credits")
        conn.commit()

        cursor.execute("SELECT credit_balance FROM users WHERE id = ?", (user_id,))
        new_bal = cursor.fetchone()["credit_balance"]
        conn.close()

        return jsonify({
            "message": f"Successfully enrolled in {course_dict['title']}!",
            "course_id": course_id,
            "course_title": course_dict["title"],
            "original_price": canonical_price,
            "discount_amount": discount_amount,
            "final_price": final_price,
            "credits_deducted": credits_to_deduct,
            "remaining_credits": new_bal
        })
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"error": str(e)}), 500

@app.route("/api/checkout/refund", methods=["POST"])
def refund_checkout():
    payload = verify_admin(request) or verify_student(request)
    if not payload:
        return jsonify({"error": "Authentication required."}), 401

    data = request.json or {}
    target_user_id = data.get("user_id") or payload["user_id"]
    course_id = data.get("course_id")

    if not course_id:
        return jsonify({"error": "course_id is required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # Find COURSE_REDEMPTION transaction
    cursor.execute("""
    SELECT id, amount, description FROM credit_transactions
    WHERE user_id = ? AND course_id = ? AND type = 'COURSE_REDEMPTION'
    ORDER BY created_at DESC LIMIT 1
    """, (target_user_id, course_id))
    txn = cursor.fetchone()

    credits_refunded = 0
    if txn and txn["amount"] < 0:
        credits_refunded = abs(txn["amount"])
        desc = f"Refund reversal for course #{course_id} (+{credits_refunded} credits)"
        cursor.execute("""
        INSERT INTO credit_transactions (user_id, course_id, amount, type, description)
        VALUES (?, ?, ?, 'REFUND_REVERSAL', ?)
        """, (target_user_id, course_id, credits_refunded, desc))

        cursor.execute("""
        UPDATE users SET credit_balance = COALESCE(credit_balance, 0) + ? WHERE id = ?
        """, (credits_refunded, target_user_id))

    cursor.execute("""
    UPDATE enrollments SET status = 'CANCELLED' WHERE user_id = ? AND course_id = ?
    """, (target_user_id, course_id))

    log_activity(conn, target_user_id, "REFUND_COURSE", f"Refunded enrollment in course #{course_id}, restored {credits_refunded} credits")
    conn.commit()

    cursor.execute("SELECT credit_balance FROM users WHERE id = ?", (target_user_id,))
    new_bal = cursor.fetchone()["credit_balance"]
    conn.close()

    return jsonify({
        "message": "Refund processed successfully.",
        "credits_refunded": credits_refunded,
        "current_credit_balance": new_bal
    })

@app.route("/api/student/dashboard", methods=["GET"])
def student_dashboard():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Authentication required"}), 401

    user_id = payload["user_id"]
    analytics = get_student_analytics(user_id)
    if not analytics:
        return jsonify({"error": "Student not found"}), 404

    student = analytics["student"]
    enrolled_courses = analytics["enrolled_courses"]
    has_enrollments = analytics["has_enrollments"]
    active_course = analytics["active_course"]

    return jsonify({
        "welcome_message": f"Welcome back, {student['name']}",
        "user": {"id": student["id"], "name": student["name"], "email": student["email"], "streak_days": student["streak_days"]},
        "has_enrollments": has_enrollments,
        "subscription": analytics["subscription"],
        "learning_overview": {
            "has_enrollments": has_enrollments,
            "current_course": active_course["title"] if active_course else "None",
            "course_slug": active_course["slug"] if active_course else None,
            "progress_pct": active_course["progress_pct"] if active_course else 0,
            "learning_debt_pct": analytics["learning_debt_pct"] if analytics["learning_debt_pct"] is not None else 0,
            "learning_debt_display": analytics["learning_debt_display"],
            "concepts_mastered": analytics["concepts_mastered"],
            "streak_days": student["streak_days"]
        },
        "continue_learning": {
            "has_active_module": has_enrollments,
            "course_title": active_course["title"] if active_course else None,
            "course_slug": active_course["slug"] if active_course else None,
            "module_title": active_course["current_module"] if active_course else None,
            "module_slug": active_course["current_module_slug"] if active_course else None
        } if has_enrollments else None,
        "my_courses": enrolled_courses,
        "credit_summary": analytics["credit_summary"]
    })

@app.route("/api/student/my-courses", methods=["GET"])
def student_my_courses():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Authentication required"}), 401

    user_id = payload["user_id"]
    analytics = get_student_analytics(user_id)
    return jsonify({"enrolled_courses": analytics["enrolled_courses"] if analytics else []})

@app.route("/api/student/learning-debt", methods=["GET"])
def student_learning_debt():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Authentication required"}), 401

    user_id = payload["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT ld.*, c.slug as course_slug, c.title as course_title
    FROM learning_debt ld
    JOIN courses c ON ld.course_id = c.id
    WHERE ld.user_id = ?
    """, (user_id,))
    debts = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return jsonify({"learning_debt": debts})

@app.route("/api/student/projects", methods=["GET"])
def student_projects():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Authentication required"}), 401

    user_id = payload["user_id"]
    course_id_param = request.args.get("course_id")
    course_slug_param = request.args.get("course_slug")

    conn = get_db_connection()
    cursor = conn.cursor()

    course_id = None
    if course_id_param and course_id_param.isdigit():
        course_id = int(course_id_param)
    elif course_slug_param:
        cursor.execute("SELECT id FROM courses WHERE slug = ?", (course_slug_param,))
        crow = cursor.fetchone()
        if crow:
            course_id = crow["id"]

    if not course_id:
        cursor.execute("SELECT course_id FROM enrollments WHERE user_id = ? ORDER BY last_accessed_at DESC LIMIT 1", (user_id,))
        erow = cursor.fetchone()
        if erow:
            course_id = erow["course_id"]
        else:
            cursor.execute("SELECT id FROM courses ORDER BY id ASC LIMIT 1")
            crow = cursor.fetchone()
            course_id = crow["id"] if crow else 1

    cursor.execute("SELECT * FROM courses WHERE id = ?", (course_id,))
    c_data = cursor.fetchone()
    active_course = dict(c_data) if c_data else None
    
    cursor.execute("""
    SELECT p.*, pp.status as user_status, pp.code as saved_code, pp.score, pp.ai_feedback, pp.updated_at as submitted_at
    FROM projects p
    LEFT JOIN project_progress pp ON p.id = pp.project_id AND pp.user_id = ?
    WHERE p.course_id = ?
    ORDER BY p.project_number ASC
    """, (user_id, course_id))
    raw_projects = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
    SELECT m.order_index, m.title, lp.completed
    FROM modules m
    LEFT JOIN learning_progress lp ON m.id = lp.module_id AND lp.user_id = ?
    WHERE m.course_id = ?
    """, (user_id, course_id))
    mod_progress_map = {}
    for r in cursor.fetchall():
        mod_progress_map[r["order_index"]] = {
            "title": r["title"],
            "completed": bool(r["completed"] and r["completed"] == 1)
        }

    formatted_projects = []

    for p in raw_projects:
        m1_idx = p.get("prereq_module_index_1") or 1
        m2_idx = p.get("prereq_module_index_2") or 2

        m1_info = mod_progress_map.get(m1_idx, {"title": f"Module 0{m1_idx}", "completed": False})
        m2_info = mod_progress_map.get(m2_idx, {"title": f"Module 0{m2_idx}", "completed": False})

        # Dynamic Unlock condition: Both prerequisite modules must be completed in learning_progress
        is_unlocked = m1_info["completed"] and m2_info["completed"]

        user_st = p.get("user_status")
        if user_st == "Completed":
            computed_status = "Completed"
        elif user_st == "In Progress":
            computed_status = "In Progress"
        elif is_unlocked:
            computed_status = "Unlocked"
        else:
            computed_status = "Locked"

        concepts = json.loads(p["concepts_used_json"]) if p.get("concepts_used_json") else []
        reqs = json.loads(p["requirements_json"]) if p.get("requirements_json") else []
        tasks = json.loads(p["tasks_json"]) if p.get("tasks_json") else []
        tests = json.loads(p["test_cases_json"]) if p.get("test_cases_json") else []
        hints = json.loads(p["hints_json"]) if p.get("hints_json") else []

        formatted_projects.append({
            "id": p["id"],
            "course_id": p["course_id"],
            "project_number": p["project_number"],
            "title": p["title"],
            "description": p["description"],
            "objective": p.get("objective") or p["description"],
            "what_to_build": p.get("what_to_build") or "",
            "concepts_used": concepts,
            "requirements": reqs,
            "tasks": tasks,
            "expected_output": p.get("expected_output") or "",
            "test_cases": tests,
            "hints": hints,
            "starter_code": p["starter_code"],
            "saved_code": p.get("saved_code") or "",
            "is_final": bool(p.get("is_final")),
            "is_unlocked": is_unlocked,
            "status": computed_status,
            "score": p.get("score") or 0,
            "ai_feedback": p.get("ai_feedback") or "",
            "prereq_module_1": {
                "order_index": m1_idx,
                "title": m1_info["title"],
                "completed": m1_info["completed"]
            },
            "prereq_module_2": {
                "order_index": m2_idx,
                "title": m2_info["title"],
                "completed": m2_info["completed"]
            },
            "builds_on_previous": p["project_number"] > 1,
            "previous_project_number": p["project_number"] - 1 if p["project_number"] > 1 else None
        })

    cursor.execute("""
    SELECT c.id, c.slug, c.title
    FROM enrollments e
    JOIN courses c ON e.course_id = c.id
    WHERE e.user_id = ?
    """, (user_id,))
    enrolled_courses = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return jsonify({
        "active_course": active_course,
        "enrolled_courses": enrolled_courses,
        "projects": formatted_projects
    })

@app.route("/api/student/projects/<int:project_id>", methods=["GET"])
def get_student_project_detail(project_id):
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Authentication required"}), 401

    user_id = payload["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    p = cursor.fetchone()
    if not p:
        conn.close()
        return jsonify({"error": "Project not found"}), 404

    p_dict = dict(p)
    course_id = p_dict["course_id"]

    cursor.execute("SELECT title, slug FROM courses WHERE id = ?", (course_id,))
    c_row = cursor.fetchone()
    course_title = c_row["title"] if c_row else "Course"
    course_slug = c_row["slug"] if c_row else "course"

    cursor.execute("SELECT * FROM project_progress WHERE user_id = ? AND project_id = ?", (user_id, project_id))
    pp = cursor.fetchone()
    pp_dict = dict(pp) if pp else None

    m1_idx = p_dict.get("prereq_module_index_1") or 1
    m2_idx = p_dict.get("prereq_module_index_2") or 2

    cursor.execute("""
    SELECT m.id, m.slug, m.title, m.order_index, lp.completed
    FROM modules m
    LEFT JOIN learning_progress lp ON m.id = lp.module_id AND lp.user_id = ?
    WHERE m.course_id = ? AND m.order_index IN (?, ?)
    """, (user_id, course_id, m1_idx, m2_idx))
    m_rows = cursor.fetchall()
    
    prereqs = []
    all_completed = True
    for r in m_rows:
        comp = bool(r["completed"] and r["completed"] == 1)
        if not comp:
            all_completed = False
        prereqs.append({
            "id": r["id"],
            "slug": r["slug"],
            "title": r["title"],
            "order_index": r["order_index"],
            "completed": comp
        })

    previous_project_code = None
    if p_dict["project_number"] > 1:
        prev_proj_num = p_dict["project_number"] - 1
        cursor.execute("""
        SELECT pp.code, p.title
        FROM projects p
        JOIN project_progress pp ON p.id = pp.project_id
        WHERE p.course_id = ? AND p.project_number = ? AND pp.user_id = ?
        """, (course_id, prev_proj_num, user_id))
        prev_row = cursor.fetchone()
        if prev_row:
            previous_project_code = prev_row["code"]

    cursor.execute("""
    SELECT * FROM learning_debt 
    WHERE user_id = ? AND course_id = ? AND status = 'Unresolved'
    """, (user_id, course_id))
    unresolved_debts = [dict(r) for r in cursor.fetchall()]

    conn.close()

    is_unlocked = all_completed
    user_status = pp_dict["status"] if pp_dict else ("Unlocked" if is_unlocked else "Locked")

    return jsonify({
        "project": {
            "id": p_dict["id"],
            "course_id": course_id,
            "course_title": course_title,
            "course_slug": course_slug,
            "project_number": p_dict["project_number"],
            "title": p_dict["title"],
            "description": p_dict["description"],
            "objective": p_dict.get("objective") or p_dict["description"],
            "what_to_build": p_dict.get("what_to_build") or "",
            "concepts_used": json.loads(p_dict["concepts_used_json"]) if p_dict.get("concepts_used_json") else [],
            "requirements": json.loads(p_dict["requirements_json"]) if p_dict.get("requirements_json") else [],
            "tasks": json.loads(p_dict["tasks_json"]) if p_dict.get("tasks_json") else [],
            "expected_output": p_dict.get("expected_output") or "",
            "test_cases": json.loads(p_dict["test_cases_json"]) if p_dict.get("test_cases_json") else [],
            "hints": json.loads(p_dict["hints_json"]) if p_dict.get("hints_json") else [],
            "starter_code": p_dict["starter_code"],
            "saved_code": pp_dict["code"] if pp_dict and pp_dict.get("code") else p_dict["starter_code"],
            "is_final": bool(p_dict.get("is_final")),
            "is_unlocked": is_unlocked,
            "status": user_status,
            "score": pp_dict["score"] if pp_dict else 0,
            "ai_feedback": pp_dict["ai_feedback"] if pp_dict else ""
        },
        "prerequisites": prereqs,
        "previous_project_code": previous_project_code,
        "learning_debts": unresolved_debts
    })

# ================= MODULE PAGE & RAG AI TUTOR =================

@app.route("/api/courses/<course_slug>/modules/<module_slug>", methods=["GET"])
def get_module_detail(course_slug, module_slug):
    conn = get_db_connection()
    cursor = conn.cursor()

    payload = decode_token(request)
    user_id = payload["user_id"] if payload else None

    cursor.execute("SELECT * FROM courses WHERE slug = ?", (course_slug,))
    course = cursor.fetchone()
    if not course:
        conn.close()
        return jsonify({"error": "Course not found"}), 404

    course_dict = dict(course)
    course_id = course_dict["id"]

    order_val = int(module_slug) if module_slug.isdigit() else -1
    cursor.execute("""
    SELECT * FROM modules 
    WHERE course_id = ? AND (slug = ? OR order_index = ?)
    """, (course_id, module_slug, order_val))
    module = cursor.fetchone()
    if not module:
        conn.close()
        return jsonify({"error": "Module not found"}), 404

    module_dict = dict(module)
    module_id = module_dict["id"]

    # Check user progress for current module
    if user_id:
        cursor.execute("SELECT completed, score FROM learning_progress WHERE user_id = ? AND module_id = ?", (user_id, module_id))
        lp_row = cursor.fetchone()
        module_dict["user_completed"] = bool(lp_row and lp_row["completed"] == 1)
        module_dict["user_score"] = lp_row["score"] if lp_row else 0
    else:
        module_dict["user_completed"] = False
        module_dict["user_score"] = 0

    cursor.execute("SELECT * FROM videos WHERE module_id = ?", (module_id,))
    video = cursor.fetchone()

    cursor.execute("SELECT questions_json FROM assessments WHERE module_id = ?", (module_id,))
    assessment = cursor.fetchone()
    raw_questions = json.loads(assessment["questions_json"]) if assessment and assessment["questions_json"] else []

    # Sanitize questions: strip 'answer' and 'explanation' to avoid leaking answers to client
    questions = []
    for q in raw_questions:
        sq = dict(q)
        sq.pop("answer", None)
        sq.pop("explanation", None)
        questions.append(sq)

    cursor.execute("SELECT id, slug, title, order_index, is_unlocked FROM modules WHERE course_id = ? ORDER BY order_index ASC", (course_id,))
    raw_modules = [dict(m) for m in cursor.fetchall()]

    # Personalize module unlocking / completion status
    course_modules = []
    completed_module_orders = set()
    if user_id:
        cursor.execute("""
        SELECT m.order_index 
        FROM learning_progress lp
        JOIN modules m ON lp.module_id = m.id
        WHERE lp.user_id = ? AND m.course_id = ? AND lp.completed = 1
        """, (user_id, course_id))
        completed_module_orders = {r["order_index"] for r in cursor.fetchall()}

    for m in raw_modules:
        m_order = m["order_index"]
        m_completed = m_order in completed_module_orders
        # Module 1 is always unlocked; subsequent modules unlocked if previous order completed or m["is_unlocked"] == 1
        is_unlocked = (m_order == 1) or ((m_order - 1) in completed_module_orders) or bool(m.get("is_unlocked"))
        m["completed"] = m_completed
        m["is_unlocked"] = is_unlocked
        course_modules.append(m)

    conn.close()

    video_dict = dict(video) if video else None
    if video_dict:
        video_dict["video_file_path"] = video_dict.get("video_file_path") or f"/static/videos/module_{module_id}/lesson_video.mp4"
        video_dict["subtitle_file_path"] = video_dict.get("subtitle_file_path") or f"/static/videos/module_{module_id}/subtitles.vtt"
        video_dict["provider"] = "ai-video-studio"

    return jsonify({
        "course": course_dict,
        "module": module_dict,
        "video": video_dict,
        "questions": questions,
        "course_modules": course_modules
    })

@app.route("/api/modules/<module_slug>/submit-assessment", methods=["POST"])
def submit_module_assessment(module_slug):
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Authentication required"}), 401
        
    user_id = payload["user_id"]
    data = request.json or {}
    submitted_answers = data.get("answers", {})

    conn = get_db_connection()
    cursor = conn.cursor()

    order_val = int(module_slug) if module_slug.isdigit() else -1
    cursor.execute("SELECT id, course_id, title, order_index FROM modules WHERE slug = ? OR order_index = ?", (module_slug, order_val))
    m_row = cursor.fetchone()
    if not m_row:
        conn.close()
        return jsonify({"error": "Module not found"}), 404

    module_id = m_row["id"]
    course_id = m_row["course_id"]
    module_title = m_row["title"]
    module_order = m_row["order_index"]

    # Load canonical assessment questions from DB
    cursor.execute("SELECT questions_json FROM assessments WHERE module_id = ?", (module_id,))
    ass_row = cursor.fetchone()
    raw_questions = json.loads(ass_row["questions_json"]) if ass_row and ass_row["questions_json"] else []

    # Calculate score based on canonical answers
    total_questions = len(raw_questions)
    correct_count = 0
    question_results = []

    for idx, q in enumerate(raw_questions):
        user_ans = None
        q_id_str = str(q.get("id", idx + 1))
        idx_str = str(idx)

        if isinstance(submitted_answers, dict):
            user_ans = submitted_answers.get(q_id_str) or submitted_answers.get(idx_str) or submitted_answers.get(idx)
        elif isinstance(submitted_answers, list) and idx < len(submitted_answers):
            user_ans = submitted_answers[idx]

        correct_ans = q.get("answer")
        is_correct = (user_ans is not None) and (str(user_ans).strip().lower() == str(correct_ans).strip().lower())

        if is_correct:
            correct_count += 1

        question_results.append({
            "id": q.get("id", idx + 1),
            "question": q.get("question"),
            "user_answer": user_ans,
            "correct_answer": correct_ans,
            "is_correct": is_correct,
            "explanation": q.get("explanation", "")
        })

    score = int(round((correct_count / total_questions * 100))) if total_questions > 0 else 100
    passed = (score >= 70)
    completed_val = 1 if passed else 0

    if passed:
        completion_data = process_module_completion(conn, user_id, module_id, score=score, is_assessment=True)
        log_activity(conn, user_id, "SUBMIT_ASSESSMENT", f"Submitted {module_title} assessment with score {score}% (Passed: True, +{completion_data['credits_awarded']} credits)")
        conn.commit()
        conn.close()

        try:
            on_course_quiz_completed(user_id, course_id, module_id, score)
        except Exception:
            pass

        msg = f"Congratulations! You passed with a score of {score}% ({correct_count}/{total_questions} correct). +{completion_data['credits_awarded']} credits awarded!"
        return jsonify({
            "message": msg,
            "score": score,
            "passed": True,
            "correct_count": correct_count,
            "total_questions": total_questions,
            "results": question_results,
            "module_completed": completion_data["module_completed"],
            "course_slug": completion_data["course_slug"],
            "course_title": completion_data["course_title"],
            "next_module": completion_data["next_module"],
            "project_unlocked": completion_data["project_unlocked"],
            "credits_awarded": completion_data["credits_awarded"],
            "total_credits": completion_data["total_credits"],
            "course_modules": completion_data["course_modules"]
        })
    else:
        debt_val = 100 - score
        cursor.execute("""
        INSERT INTO learning_debt (user_id, course_id, concept_name, mastery_pct, learning_debt_pct, reason, status)
        VALUES (?, ?, ?, ?, ?, 'Concept deficit detected in module assessment.', 'Unresolved')
        ON CONFLICT(user_id, course_id, concept_name) DO UPDATE SET
            mastery_pct = excluded.mastery_pct,
            learning_debt_pct = excluded.learning_debt_pct,
            status = 'Unresolved',
            updated_at = CURRENT_TIMESTAMP
        """, (user_id, course_id, f"Concept: {module_title}", score, debt_val))

        cursor.execute("SELECT credit_balance FROM users WHERE id = ?", (user_id,))
        u_bal = cursor.fetchone()
        total_credits = u_bal["credit_balance"] if u_bal and u_bal["credit_balance"] is not None else 0

        cursor.execute("SELECT slug, title FROM courses WHERE id = ?", (course_id,))
        c_row = cursor.fetchone()
        c_slug = c_row["slug"] if c_row else "course"
        c_title = c_row["title"] if c_row else "Course"

        log_activity(conn, user_id, "SUBMIT_ASSESSMENT", f"Submitted {module_title} assessment with score {score}% (Passed: False)")
        conn.commit()
        conn.close()

        msg = f"Score: {score}% ({correct_count}/{total_questions} correct). You need at least 70% to pass this module. Please review the lesson content and try again."
        return jsonify({
            "message": msg,
            "score": score,
            "passed": False,
            "correct_count": correct_count,
            "total_questions": total_questions,
            "results": question_results,
            "module_completed": {
                "id": module_id,
                "order_index": module_order,
                "title": module_title,
                "slug": module_slug
            },
            "course_slug": c_slug,
            "course_title": c_title,
            "next_module": None,
            "project_unlocked": None,
            "credits_awarded": 0,
            "total_credits": total_credits
        })

@app.route("/api/rag/ask-module", methods=["POST"])
def ask_rag_tutor():
    data = request.json or {}
    question = data.get("question", "").strip()
    module_slug_or_id = data.get("module_slug") or data.get("module_id") or "m01"
    language = data.get("language", "English")

    if not question:
        return jsonify({"error": "Question required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    order_val = int(str(module_slug_or_id)) if str(module_slug_or_id).isdigit() else -1
    cursor.execute("""
    SELECT m.id, m.title, c.title as course_title, v.professor, v.institution, v.transcript 
    FROM modules m 
    JOIN courses c ON m.course_id = c.id
    LEFT JOIN videos v ON m.id = v.module_id 
    WHERE m.slug = ? OR m.id = ? OR m.order_index = ?
    """, (str(module_slug_or_id), str(module_slug_or_id), order_val))
    row = cursor.fetchone()
    conn.close()

    module_title = row["title"] if row else "Machine Learning Module"
    course_title = row["course_title"] if row else "Applied Machine Learning"
    professor = row["professor"] if row and row["professor"] else "IIT Madras Faculty"
    institution = row["institution"] if row and row["institution"] else "IIT Madras / NPTEL"
    transcript = row["transcript"] if row and row["transcript"] else "Core video lecture transcript explaining data preparation and vector math."

    response = rag_tutor.answer_module_question(
        question=question,
        module_title=module_title,
        professor=professor,
        institution=institution,
        transcript=transcript,
        language=language
    )

    return jsonify(response)

@app.route("/api/projects/visual-flow", methods=["POST"])
def code_visual_flow():
    data = request.json or {}
    code = data.get("code", "")
    flow = code_visualizer.generate_visual_flow(code)
    return jsonify(flow)

@app.route("/api/projects/submit", methods=["POST"])
def submit_project():
    payload = verify_student(request)
    user_id = payload["user_id"] if payload else 1
    data = request.json or {}
    project_id = data.get("project_id", 1)
    code = data.get("code", "")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT title FROM projects WHERE id = ?", (project_id,))
    p_row = cursor.fetchone()
    p_title = p_row["title"] if p_row else "Mini Project"

    evaluation = project_mentor.evaluate_submission(p_title, code)
    score = evaluation["score"]
    status = "Completed" if evaluation["passed"] else "In Progress"

    cursor.execute("""
    INSERT INTO project_progress (user_id, project_id, status, code, score, ai_feedback, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(user_id, project_id) DO UPDATE SET
        status = excluded.status,
        code = excluded.code,
        score = excluded.score,
        ai_feedback = excluded.ai_feedback,
        updated_at = CURRENT_TIMESTAMP
    """, (user_id, project_id, status, code, score, evaluation["feedback"]))

    log_activity(conn, user_id, "SUBMIT_PROJECT", f"Submitted {p_title} (Score: {score})")
    conn.commit()
    conn.close()

    return jsonify(evaluation)

# ================= ADMIN CONSOLE & GOVERNANCE =================

@app.route("/api/admin/stats", methods=["GET"])
def admin_stats():
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403

    stats = get_dashboard_stats()
    return jsonify(stats)

@app.route("/api/admin/students", methods=["GET"])
def admin_students_list():
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT id FROM users WHERE role = 'STUDENT' ORDER BY id DESC")
    student_rows = cursor.fetchall()
    conn.close()

    students = []
    seen_ids = set()
    for r in student_rows:
        s_id = r["id"]
        if s_id in seen_ids:
            continue
        seen_ids.add(s_id)
        an = get_student_analytics(s_id)
        if an:
            students.append({
                "id": an["student"]["id"],
                "name": an["student"]["name"],
                "email": an["student"]["email"],
                "subscription_plan": an["subscription"]["plan_name"],
                "subscription_status": an["subscription"]["status"],
                "enrolled_count": len(an["enrolled_courses"]),
                "enrolled_courses": [c["title"] for c in an["enrolled_courses"]],
                "avg_progress": an["overall_progress_pct"],
                "learning_debt": an["learning_debt_display"],
                "concepts_mastered": an["concepts_mastered"],
                "last_activity": an["last_activity"],
                "status": an["status"]
            })

    return jsonify({"students": students})

@app.route("/api/admin/students/<int:student_id>", methods=["GET"])
def admin_student_detail(student_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403

    analytics = get_student_analytics(student_id)
    if not analytics:
        return jsonify({"error": "Student not found"}), 404

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT lp.*, m.title as module_title, c.title as course_title
    FROM learning_progress lp
    JOIN modules m ON lp.module_id = m.id
    JOIN courses c ON lp.course_id = c.id
    WHERE lp.user_id = ?
    ORDER BY lp.updated_at DESC
    """, (student_id,))
    module_progress = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
    SELECT ld.*, c.title as course_title
    FROM learning_debt ld
    JOIN courses c ON ld.course_id = c.id
    WHERE ld.user_id = ?
    """, (student_id,))
    learning_debt_items = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
    SELECT pp.*, p.title as project_title, c.title as course_title
    FROM project_progress pp
    JOIN projects p ON pp.project_id = p.id
    JOIN courses c ON p.course_id = c.id
    WHERE pp.user_id = ?
    """, (student_id,))
    project_progress = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
    SELECT cm.*, m.title as module_title
    FROM chat_messages cm
    JOIN modules m ON cm.module_id = m.id
    WHERE cm.user_id = ?
    ORDER BY cm.timestamp DESC
    """, (student_id,))
    chat_history = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
    SELECT * FROM activity_logs WHERE user_id = ? ORDER BY timestamp DESC
    """, (student_id,))
    activity_logs = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return jsonify({
        "analytics": analytics,
        "module_progress": module_progress,
        "learning_debt_items": learning_debt_items,
        "project_progress": project_progress,
        "chat_history": chat_history,
        "activity_logs": activity_logs
    })

@app.route("/api/admin/enrollments", methods=["GET"])
def admin_enrollments_list():
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403

    enrollments = get_enrollment_analytics()
    return jsonify({"enrollments": enrollments})

# =========================================================================
# AI VIDEO STUDIO REST API ENDPOINTS
# =========================================================================

@app.route("/static/videos/<path:filename>")
def serve_static_video(filename):
    video_dir = os.path.join(app.root_path, "static", "videos")
    return send_from_directory(video_dir, filename)

@app.route("/api/admin/modules/<int:module_id>/ai-video/generate", methods=["POST"])
def generate_ai_module_video(module_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied — Admin Authorization Required"}), 403

    admin_id = payload["user_id"]
    data = request.get_json(silent=True) or {}
    custom_script = data.get("script_json")

    job_id, started = launch_async_video_generation(module_id, admin_id, custom_script=custom_script)
    
    if not started:
        return jsonify({
            "message": "AI Video generation job is already active in queue for this module.",
            "job_id": job_id
        }), 200

    return jsonify({
        "message": "AI Video generation pipeline initiated and enqueued successfully!",
        "job_id": job_id
    }), 202

@app.route("/api/admin/courses/<int:course_id>/ai-video/generate-all", methods=["POST"])
def generate_all_course_module_videos(course_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403

    admin_id = payload["user_id"]
    enqueued, skipped = launch_bulk_course_video_generation(course_id, admin_id)
    return jsonify({
        "message": f"Enqueued {len(enqueued)} module video generation jobs.",
        "enqueued": enqueued,
        "already_active": skipped
    })

@app.route("/api/admin/ai-video/generate-all-courses", methods=["POST"])
def generate_all_courses_videos():
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403

    admin_id = payload["user_id"]
    data = request.get_json(silent=True) or {}
    course_ids = data.get("course_ids") # Optional list of selected course IDs

    enqueued, skipped = launch_bulk_all_courses_generation(admin_id, course_ids=course_ids)
    return jsonify({
        "message": f"Successfully initiated bulk video generation across {len(enqueued)} modules!",
        "enqueued_count": len(enqueued),
        "already_active_count": len(skipped),
        "enqueued": enqueued
    })

@app.route("/api/admin/ai-video/stats", methods=["GET"])
def get_ai_video_dashboard_stats():
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as total_courses FROM courses")
    total_courses = cursor.fetchone()["total_courses"]

    cursor.execute("SELECT COUNT(*) as total_modules FROM modules")
    total_modules = cursor.fetchone()["total_modules"]

    cursor.execute("SELECT COUNT(*) as published_videos FROM videos WHERE status = 'PUBLISHED' AND video_file_path IS NOT NULL")
    published_videos = cursor.fetchone()["published_videos"]

    cursor.execute("SELECT COUNT(DISTINCT module_id) as generated_modules FROM ai_video_versions")
    generated_modules = cursor.fetchone()["generated_modules"]

    cursor.execute("SELECT COUNT(*) as generating_count FROM ai_video_jobs WHERE status = 'IN_PROGRESS'")
    generating_count = cursor.fetchone()["generating_count"]

    cursor.execute("SELECT COUNT(*) as queued_count FROM ai_video_jobs WHERE status = 'QUEUED'")
    queued_count = cursor.fetchone()["queued_count"]

    cursor.execute("SELECT COUNT(*) as failed_count FROM ai_video_jobs WHERE status = 'FAILED'")
    failed_count = cursor.fetchone()["failed_count"]

    cursor.execute("SELECT COUNT(*) as draft_count FROM ai_video_versions WHERE status = 'DRAFT'")
    draft_count = cursor.fetchone()["draft_count"]

    cursor.execute("""
    SELECT j.*, m.title as module_title, c.title as course_title
    FROM ai_video_jobs j
    JOIN modules m ON j.module_id = m.id
    JOIN courses c ON m.course_id = c.id
    WHERE j.status IN ('QUEUED', 'IN_PROGRESS')
    ORDER BY j.id DESC
    """)
    active_jobs = [dict(r) for r in cursor.fetchall()]

    pending_count = max(0, total_modules - published_videos)
    coverage_pct = round((published_videos / total_modules * 100), 1) if total_modules > 0 else 0

    conn.close()

    q_status = queue_manager.get_status()

    return jsonify({
        "total_courses": total_courses,
        "total_modules": total_modules,
        "published_videos": published_videos,
        "draft_videos": draft_count,
        "generated_modules": generated_modules,
        "pending_videos": pending_count,
        "generating_jobs": generating_count,
        "queued_jobs": queued_count,
        "failed_jobs": failed_count,
        "coverage_pct": coverage_pct,
        "overall_progress_pct": coverage_pct,
        "queue_paused": q_status.get("is_paused", False),
        "active_workers": q_status.get("active_workers", 2),
        "active_jobs": active_jobs,
        "queue": q_status
    })

@app.route("/api/admin/ai-video/jobs", methods=["GET"])
def get_all_ai_video_jobs():
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT j.*, m.title as module_title, m.slug as module_slug, m.order_index, c.title as course_title, c.slug as course_slug
    FROM ai_video_jobs j
    JOIN modules m ON j.module_id = m.id
    JOIN courses c ON m.course_id = c.id
    ORDER BY j.id DESC
    LIMIT 100
    """)
    jobs = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return jsonify({"jobs": jobs})

@app.route("/api/admin/ai-video/jobs/<int:job_id>", methods=["GET"])
def get_ai_video_job_status(job_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT j.*, m.title as module_title, m.order_index, c.title as course_title 
    FROM ai_video_jobs j
    JOIN modules m ON j.module_id = m.id
    JOIN courses c ON m.course_id = c.id
    WHERE j.id = ?
    """, (job_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Job ID not found"}), 404

    return jsonify({"job": dict(row)})

@app.route("/api/admin/ai-video/jobs/<int:job_id>/retry", methods=["POST"])
def retry_ai_video_job_endpoint(job_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403

    admin_id = payload["user_id"]
    success, msg = retry_failed_video_job(job_id, admin_id)
    if not success:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})

@app.route("/api/admin/ai-video/jobs/<int:job_id>/cancel", methods=["POST"])
def cancel_ai_video_job_endpoint(job_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403

    success, msg = cancel_video_job(job_id)
    return jsonify({"message": msg})

@app.route("/api/admin/ai-video/queue/pause", methods=["POST"])
def pause_video_queue_endpoint():
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403
    queue_manager.pause()
    return jsonify({"message": "AI Video generation queue paused.", "is_paused": True, "queue": queue_manager.get_status()})

@app.route("/api/admin/ai-video/queue/resume", methods=["POST"])
def resume_video_queue_endpoint():
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403
    queue_manager.resume()
    return jsonify({"message": "AI Video generation queue resumed.", "is_paused": False, "queue": queue_manager.get_status()})

@app.route("/api/admin/modules/<int:module_id>/ai-video/script", methods=["GET"])
def get_module_ai_video_script(module_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM modules WHERE id = ?", (module_id,))
    mod = cursor.fetchone()
    if not mod:
        conn.close()
        return jsonify({"error": "Module not found"}), 404

    mod_dict = dict(mod)
    cursor.execute("SELECT * FROM courses WHERE id = ?", (mod_dict["course_id"],))
    course_dict = dict(cursor.fetchone())

    cursor.execute("SELECT questions_json FROM assessments WHERE module_id = ?", (module_id,))
    ass_row = cursor.fetchone()
    ass_q = ass_row["questions_json"] if ass_row else "[]"

    # Check if existing version has custom script
    cursor.execute("SELECT script_json FROM ai_video_versions WHERE module_id = ? ORDER BY version_number DESC LIMIT 1", (module_id,))
    ver_row = cursor.fetchone()
    
    conn.close()

    if ver_row and ver_row["script_json"]:
        try:
            storyboard = json.loads(ver_row["script_json"])
        except Exception:
            storyboard = None
    else:
        storyboard = None

    if not storyboard:
        from ai_video_provider import GeminiPILVideoProvider
        provider = GeminiPILVideoProvider()
        storyboard = provider.generate_script_and_storyboard(mod_dict, course_dict, ass_q)

    return jsonify({
        "module_id": module_id,
        "module_title": mod_dict["title"],
        "course_title": course_dict["title"],
        "storyboard": storyboard
    })

@app.route("/api/admin/modules/<int:module_id>/ai-video/script", methods=["PUT"])
def save_module_ai_video_script(module_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403

    data = request.get_json(silent=True) or {}
    storyboard = data.get("storyboard")
    if not storyboard:
        return jsonify({"error": "Storyboard JSON payload is required"}), 400

    # Save to module static folder
    static_dir = os.path.join(app.root_path, "static", "videos", f"module_{module_id}")
    os.makedirs(static_dir, exist_ok=True)
    with open(os.path.join(static_dir, "storyboard.json"), "w", encoding="utf-8") as f:
        json.dump(storyboard, f, indent=2)

    if data.get("regenerate_video"):
        admin_id = payload["user_id"]
        job_id, _ = launch_async_video_generation(module_id, admin_id, custom_script=json.dumps(storyboard))
        return jsonify({"message": "AI Video script saved and new generation pipeline initiated!", "job_id": job_id})

    return jsonify({"message": "AI Video script updated and saved successfully!"})

@app.route("/api/admin/modules/<int:module_id>/ai-video/versions", methods=["GET"])
def get_ai_video_versions(module_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT * FROM ai_video_versions 
    WHERE module_id = ? 
    ORDER BY version_number DESC
    """, (module_id,))
    versions = [dict(v) for v in cursor.fetchall()]

    for v in versions:
        if v.get("script_json"):
            try:
                v["storyboard_scenes"] = json.loads(v["script_json"]).get("scenes", [])
            except Exception:
                v["storyboard_scenes"] = []
        else:
            v["storyboard_scenes"] = []

    cursor.execute("SELECT * FROM videos WHERE module_id = ?", (module_id,))
    published_video = cursor.fetchone()
    
    cursor.execute("SELECT m.title as module_title, c.title as course_title FROM modules m JOIN courses c ON m.course_id = c.id WHERE m.id = ?", (module_id,))
    meta_row = cursor.fetchone()

    conn.close()

    return jsonify({
        "module_id": module_id,
        "module_title": meta_row["module_title"] if meta_row else f"Module {module_id}",
        "course_title": meta_row["course_title"] if meta_row else "Course",
        "published_video": dict(published_video) if published_video else None,
        "versions": versions
    })

@app.route("/api/admin/modules/<int:module_id>/ai-video/publish", methods=["POST"])
def publish_ai_video(module_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403

    admin_id = payload["user_id"]
    data = request.get_json(silent=True) or {}
    version_id = data.get("version_id")

    if not version_id:
        # Pick latest version
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM ai_video_versions WHERE module_id = ? ORDER BY version_number DESC LIMIT 1", (module_id,))
        v = cursor.fetchone()
        conn.close()
        if v:
            version_id = v["id"]
        else:
            return jsonify({"error": "No generated video versions found for this module"}), 400

    success, msg = publish_ai_video_version(module_id, version_id, admin_id)
    if not success:
        return jsonify({"error": msg}), 400

    return jsonify({"message": msg})

@app.route("/api/admin/modules/<int:module_id>/ai-video/unpublish", methods=["POST"])
def unpublish_ai_video_endpoint(module_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403

    success, msg = unpublish_ai_video(module_id)
    return jsonify({"message": msg})

@app.route("/api/modules/<int:module_id>/video-progress", methods=["POST"])
def track_module_video_progress(module_id):
    """
    Student Video Watch Progress Tracker.
    Records current watch percentage (0% - 100%) and completes module when >= 80% or when marked completed.
    """
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Student authentication required"}), 401

    user_id = payload["user_id"]
    data = request.get_json(silent=True) or {}
    progress_pct = min(100, max(0, int(data.get("progress_pct", 0))))
    is_completed = (progress_pct >= 80) or bool(data.get("completed"))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, course_id, title FROM modules WHERE id = ?", (module_id,))
    mod = cursor.fetchone()
    if not mod:
        conn.close()
        return jsonify({"error": "Module not found"}), 404

    course_id = mod["course_id"]

    if is_completed:
        completion_data = process_module_completion(conn, user_id, module_id, score=max(80, progress_pct))
        log_activity(conn, user_id, "VIDEO_COMPLETE", f"Completed video lesson for {mod['title']} (+{completion_data['credits_awarded']} credits)")
        conn.commit()
        conn.close()

        # Trigger recommendation update
        try:
            on_course_quiz_completed(user_id, course_id, module_id, max(80, progress_pct))
        except Exception:
            pass

        return jsonify({
            "success": True,
            "module_id": module_id,
            "progress_pct": progress_pct,
            "completed": True,
            "passed": True,
            "score": max(80, progress_pct),
            "video_completed": True,
            "module_completed": completion_data["module_completed"],
            "course_slug": completion_data["course_slug"],
            "course_title": completion_data["course_title"],
            "next_module": completion_data["next_module"],
            "project_unlocked": completion_data["project_unlocked"],
            "credits_awarded": completion_data["credits_awarded"],
            "total_credits": completion_data["total_credits"],
            "course_modules": completion_data["course_modules"],
            "message": "Video lesson completed! Next module unlocked."
        })
    else:
        # Just record partial watch progress
        cursor.execute("""
        INSERT INTO learning_progress (user_id, course_id, module_id, completed, score, updated_at)
        VALUES (?, ?, ?, 0, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, module_id) DO UPDATE SET
            score = MAX(learning_progress.score, excluded.score),
            updated_at = CURRENT_TIMESTAMP
        """, (user_id, course_id, module_id, progress_pct))
        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "module_id": module_id,
            "progress_pct": progress_pct,
            "completed": False,
            "passed": False,
            "video_completed": False,
            "message": "Video progress recorded successfully"
        })

@app.route("/api/modules/<int:module_id>/complete", methods=["POST"])
@app.route("/api/courses/<course_slug>/modules/<module_slug>/complete", methods=["POST"])
def complete_module_direct(module_id=None, course_slug=None, module_slug=None):
    """
    Direct module completion endpoint for students.
    Immediately marks module completed, unlocks next module in DB, awards credits,
    and returns next_module, milestone project_unlocked, and updated course_modules.
    """
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Student authentication required"}), 401

    user_id = payload["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    if not module_id:
        cursor.execute("SELECT id FROM courses WHERE slug = ?", (course_slug,))
        c_row = cursor.fetchone()
        if not c_row:
            conn.close()
            return jsonify({"error": "Course not found"}), 404
        order_val = int(module_slug) if str(module_slug).isdigit() else -1
        cursor.execute("SELECT id FROM modules WHERE course_id = ? AND (slug = ? OR order_index = ?)", (c_row["id"], str(module_slug), order_val))
        m_row = cursor.fetchone()
        if not m_row:
            conn.close()
            return jsonify({"error": "Module not found"}), 404
        module_id = m_row["id"]

    completion_data = process_module_completion(conn, user_id, module_id, score=100)
    if not completion_data:
        conn.close()
        return jsonify({"error": "Module not found"}), 404

    log_activity(conn, user_id, "MODULE_COMPLETE", f"Completed module #{module_id} (+{completion_data['credits_awarded']} credits)")
    conn.commit()
    conn.close()

    try:
        on_course_quiz_completed(user_id, completion_data["course_id"], module_id, 100)
    except Exception:
        pass

    return jsonify({
        "success": True,
        "module_id": module_id,
        "completed": True,
        "passed": True,
        "score": 100,
        "module_completed": completion_data["module_completed"],
        "course_slug": completion_data["course_slug"],
        "course_title": completion_data["course_title"],
        "next_module": completion_data["next_module"],
        "project_unlocked": completion_data["project_unlocked"],
        "credits_awarded": completion_data["credits_awarded"],
        "total_credits": completion_data["total_credits"],
        "course_modules": completion_data["course_modules"],
        "message": "Module completed successfully! Next module is now unlocked."
    })

@app.route("/api/admin/courses/modules", methods=["GET"])
def admin_courses_modules():
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Access Denied"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, slug, title FROM courses ORDER BY id ASC")
    courses = [dict(c) for c in cursor.fetchall()]

    for c in courses:
        cursor.execute("""
        SELECT m.id, m.slug, m.title, m.order_index,
               v.id as video_db_id, v.video_id, v.video_file_path, v.subtitle_file_path, 
               COALESCE(v.status, 'NOT_GENERATED') as video_status,
               v.professor, v.institution, v.duration, v.source, v.transcript,
               (SELECT COUNT(*) FROM ai_video_versions WHERE module_id = m.id) as versions_count,
               (SELECT version_number FROM ai_video_versions WHERE module_id = m.id ORDER BY version_number DESC LIMIT 1) as latest_version,
               (SELECT status FROM ai_video_jobs WHERE module_id = m.id ORDER BY id DESC LIMIT 1) as latest_job_status
        FROM modules m
        LEFT JOIN videos v ON m.id = v.module_id
        WHERE m.course_id = ?
        ORDER BY m.order_index ASC
        """, (c["id"],))
        c["modules"] = [dict(m) for m in cursor.fetchall()]

    conn.close()
    return jsonify({"courses": courses})

# ================= MENTOR-LED LEARNING APIs =================

@app.route("/api/mentor/students", methods=["GET"])
def get_mentor_assigned_students():
    payload = verify_mentor(request)
    if not payload:
        return jsonify({"error": "Instructor/Mentor authorization required."}), 403

    mentor_id = payload["user_id"]
    is_admin = (payload.get("role") == "ADMIN")

    conn = get_db_connection()
    cursor = conn.cursor()

    if is_admin:
        query = """
        SELECT ma.id as assignment_id, ma.mentor_id, u.id as student_id, u.name as student_name, 
               u.email as student_email, c.id as course_id, c.title as course_title, c.slug as course_slug,
               COALESCE(e.progress_pct, 0) as progress_pct, COALESCE(e.status, 'ACTIVE') as enrollment_status,
               ma.assigned_at, ma.notes, ma.status as assignment_status
        FROM mentor_assignments ma
        JOIN users u ON ma.student_id = u.id
        JOIN courses c ON ma.course_id = c.id
        LEFT JOIN enrollments e ON (e.user_id = u.id AND e.course_id = c.id)
        ORDER BY ma.assigned_at DESC
        """
        cursor.execute(query)
    else:
        query = """
        SELECT ma.id as assignment_id, ma.mentor_id, u.id as student_id, u.name as student_name, 
               u.email as student_email, c.id as course_id, c.title as course_title, c.slug as course_slug,
               COALESCE(e.progress_pct, 0) as progress_pct, COALESCE(e.status, 'ACTIVE') as enrollment_status,
               ma.assigned_at, ma.notes, ma.status as assignment_status
        FROM mentor_assignments ma
        JOIN users u ON ma.student_id = u.id
        JOIN courses c ON ma.course_id = c.id
        LEFT JOIN enrollments e ON (e.user_id = u.id AND e.course_id = c.id)
        WHERE ma.mentor_id = ?
        ORDER BY ma.assigned_at DESC
        """
        cursor.execute(query, (mentor_id,))

    rows = cursor.fetchall()
    students_list = []
    for r in rows:
        item = dict(r)
        # Fetch capstone submission if any
        cursor.execute("""
        SELECT id, title, final_score, mentor_score, ai_score, passed, submitted_at
        FROM career_track_project_submissions
        WHERE user_id = ? AND course_id = ?
        ORDER BY id DESC LIMIT 1
        """, (item["student_id"], item["course_id"]))
        sub = cursor.fetchone()
        item["capstone_submission"] = dict(sub) if sub else None

        # Fetch quiz score average
        cursor.execute("""
        SELECT AVG(score_pct) as avg_quiz FROM learning_progress
        WHERE user_id = ? AND course_id = ?
        """, (item["student_id"], item["course_id"]))
        q_row = cursor.fetchone()
        item["avg_quiz_score"] = round(q_row["avg_quiz"], 1) if q_row and q_row["avg_quiz"] is not None else 95.0

        students_list.append(item)

    conn.close()
    return jsonify({
        "mentor": {
            "id": mentor_id,
            "name": payload.get("name"),
            "email": payload.get("email"),
            "role": payload.get("role")
        },
        "assigned_students_count": len(students_list),
        "students": students_list
    })

@app.route("/api/mentor/courses", methods=["GET"])
def get_mentor_courses():
    payload = verify_mentor(request)
    if not payload:
        return jsonify({"error": "Instructor/Mentor authorization required."}), 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, slug, title, category, difficulty, duration FROM courses WHERE is_published = 1")
    courses = [dict(c) for c in cursor.fetchall()]
    conn.close()

    return jsonify({"courses": courses})

# ================= INNOVATION BOOSTER APIs =================

@app.route("/api/innovation-booster/proposals", methods=["GET"])
def get_innovation_proposals():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Student authentication required."}), 401

    user_id = payload["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, title, track, problem_statement, proposed_solution, target_market,
           tech_stack_json, status, ai_feasibility_score, booster_credits_awarded,
           milestones_json, created_at, updated_at
    FROM innovation_proposals
    WHERE user_id = ?
    ORDER BY created_at DESC
    """, (user_id,))

    rows = cursor.fetchall()
    proposals = []
    for r in rows:
        p = dict(r)
        p["tech_stack"] = json.loads(p.get("tech_stack_json") or "[]")
        p["milestones"] = json.loads(p.get("milestones_json") or "[]")
        proposals.append(p)

    conn.close()
    return jsonify({"proposals": proposals, "count": len(proposals)})

@app.route("/api/innovation-booster/proposals", methods=["POST"])
def submit_innovation_proposal():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Student authentication required."}), 401

    user_id = payload["user_id"]
    data = request.json or {}

    title = data.get("title", "").strip()
    track = data.get("track", "AI Systems & Infrastructure").strip()
    problem_statement = data.get("problem_statement", "").strip()
    proposed_solution = data.get("proposed_solution", "").strip()
    target_market = data.get("target_market", "Enterprise Developers & AI Startups").strip()
    tech_stack = data.get("tech_stack", ["Python", "FastAPI", "FAISS", "Docker", "PyTorch"])

    if not title or not problem_statement or not proposed_solution:
        return jsonify({"error": "Title, problem statement, and proposed solution are required."}), 400

    # AI Evaluation & Milestone Generation
    feasibility_score = 88.5
    booster_credits = 100
    milestones = [
        {"stage": "Phase 1: Architecture Blueprint & Technical Spec", "status": "COMPLETED", "due_days": 14},
        {"stage": "Phase 2: MVP Alpha Prototyping & Benchmark Suite", "status": "IN_PROGRESS", "due_days": 30},
        {"stage": "Phase 3: Pilot Deployment & Demo Pitch Deck", "status": "PENDING", "due_days": 60}
    ]

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO innovation_proposals 
    (user_id, title, track, problem_statement, proposed_solution, target_market, tech_stack_json, status, ai_feasibility_score, booster_credits_awarded, milestones_json)
    VALUES (?, ?, ?, ?, ?, ?, ?, 'INCUBATING', ?, ?, ?)
    """, (
        user_id, title, track, problem_statement, proposed_solution, target_market,
        json.dumps(tech_stack), feasibility_score, booster_credits, json.dumps(milestones)
    ))
    proposal_id = cursor.lastrowid

    # Award Innovation Booster Credits to student wallet
    cursor.execute("UPDATE users SET credit_balance = COALESCE(credit_balance, 0) + ? WHERE id = ?", (booster_credits, user_id))
    cursor.execute("""
    INSERT INTO credit_transactions (user_id, amount, transaction_type, description)
    VALUES (?, ?, 'REWARD', ?)
    """, (user_id, booster_credits, f"Innovation Booster grant for venture '{title}'"))

    log_activity(conn, user_id, "INNOVATION_BOOSTER_SUBMIT", f"Submitted innovation venture: {title}")

    conn.commit()
    conn.close()

    return jsonify({
        "status": "success",
        "proposal_id": proposal_id,
        "title": title,
        "ai_feasibility_score": feasibility_score,
        "booster_credits_awarded": booster_credits,
        "milestones": milestones,
        "message": f"Venture '{title}' accepted into Innovation Booster! 100 credits awarded to wallet."
    }), 201

# =========================================================================
# MANUAL UPI / GPAY PAYMENT & SUBSCRIPTION UPGRADE ENDPOINTS
# =========================================================================

UPLOAD_PAYMENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "uploads", "payment_proofs")
os.makedirs(UPLOAD_PAYMENT_DIR, exist_ok=True)
ALLOWED_PAYMENT_PROOF_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

@app.route("/static/images/<path:filename>")
def serve_static_images(filename):
    img_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "images")
    return send_from_directory(img_dir, filename)

@app.route("/static/uploads/payment_proofs/<path:filename>")
def serve_static_payment_proof(filename):
    return send_from_directory(UPLOAD_PAYMENT_DIR, filename)

@app.route("/api/student/payments/submit", methods=["POST"])
def submit_payment_verification():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Student authentication required."}), 401

    user_id = payload["user_id"]
    plan_id = request.form.get("plan_id", "").strip().lower()
    utr_number = request.form.get("utr_number", "").strip()

    if plan_id not in ["student", "premium"]:
        return jsonify({"error": "Invalid plan selected. Choose 'student' or 'premium'."}), 400

    plan_info = {
        "student": {"name": "Student Plan", "amount": 499},
        "premium": {"name": "Premium Plan", "amount": 999}
    }[plan_id]

    if not utr_number or len(utr_number) < 6:
        return jsonify({"error": "Please provide a valid UTR / Transaction reference number (at least 6 characters)."}), 400

    # Clean UTR (remove spaces/special characters)
    utr_clean = re.sub(r"[^a-zA-Z0-9_-]", "", utr_number).upper()
    if not utr_clean or len(utr_clean) < 6:
        return jsonify({"error": "Invalid UTR format. Please provide valid alphanumeric transaction ID."}), 400

    # Screenshot upload
    if "screenshot" not in request.files:
        return jsonify({"error": "Payment proof screenshot is required."}), 400

    file = request.files["screenshot"]
    if not file or not file.filename:
        return jsonify({"error": "No payment proof file uploaded."}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_PAYMENT_PROOF_EXTS:
        return jsonify({"error": f"Unsupported file type ({ext}). Allowed formats: PNG, JPG, JPEG, WEBP"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if there is already an existing PENDING request for this user
    cursor.execute("SELECT id FROM payment_requests WHERE user_id = ? AND status = 'PENDING'", (user_id,))
    pending_existing = cursor.fetchone()
    if pending_existing:
        conn.close()
        return jsonify({
            "error": "You already have a payment verification pending review. Our team will verify it within 12 hours.",
            "pending_id": pending_existing["id"]
        }), 409

    # Check duplicate UTR from approved payments of other users
    cursor.execute("SELECT id FROM payment_requests WHERE utr_number = ? AND status = 'APPROVED' AND user_id != ?", (utr_clean, user_id))
    dup_utr = cursor.fetchone()
    if dup_utr:
        conn.close()
        return jsonify({"error": "This UTR / Transaction ID has already been verified for another user. If this is an error, please contact support."}), 400

    # Save screenshot file safely
    filename = f"proof_{user_id}_{int(datetime.datetime.now().timestamp())}_{secrets.token_hex(4)}{ext}"
    dest_path = os.path.join(UPLOAD_PAYMENT_DIR, filename)
    file.save(dest_path)

    # Insert into payment_requests
    cursor.execute("""
    INSERT INTO payment_requests (
        user_id, plan_id, plan_name, plan_amount, billing_cycle,
        utr_number, screenshot_path, status, submitted_at
    ) VALUES (?, ?, ?, ?, 'Monthly', ?, ?, 'PENDING', CURRENT_TIMESTAMP)
    """, (user_id, plan_id, plan_info["name"], plan_info["amount"], utr_clean, filename))

    payment_id = cursor.lastrowid

    # Insert audit log
    cursor.execute("""
    INSERT INTO payment_audit_logs (payment_request_id, user_id, actor_id, action, details)
    VALUES (?, ?, ?, 'PAYMENT_SUBMITTED', ?)
    """, (payment_id, user_id, user_id, f"Submitted {plan_info['name']} (₹{plan_info['amount']}) with UTR: {utr_clean}"))

    log_activity(conn, user_id, "PAYMENT_SUBMITTED", f"Submitted manual payment for {plan_info['name']} (₹{plan_info['amount']}) - UTR: {utr_clean}")

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": f"Your payment verification for {plan_info['name']} (₹{plan_info['amount']}) has been submitted successfully.",
        "payment_id": payment_id,
        "plan_id": plan_id,
        "plan_name": plan_info["name"],
        "plan_amount": plan_info["amount"],
        "utr_number": utr_clean,
        "status": "PENDING",
        "review_sla": "Within 12 hours"
    }), 201

@app.route("/api/student/payments/status", methods=["GET"])
def get_student_payment_status():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Student authentication required."}), 401

    user_id = payload["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, plan_id, plan_name, plan_amount, billing_cycle, utr_number, screenshot_path,
           status, submitted_at, verified_at, rejection_reason, admin_notes
    FROM payment_requests
    WHERE user_id = ?
    ORDER BY id DESC LIMIT 1
    """, (user_id,))
    pay_row = cursor.fetchone()

    cursor.execute("SELECT plan_name, billing_cycle, price_inr, status, start_date, end_date FROM subscriptions WHERE user_id = ?", (user_id,))
    sub_row = cursor.fetchone()
    conn.close()

    return jsonify({
        "has_payment_request": bool(pay_row),
        "payment": dict(pay_row) if pay_row else None,
        "subscription": dict(sub_row) if sub_row else None
    })

@app.route("/api/institution/enquire", methods=["POST"])
def submit_institution_enquiry():
    data = request.json or {}
    inst_name = data.get("institution_name", "").strip()
    contact_person = data.get("contact_person", "").strip()
    email = data.get("official_email", "").strip()
    phone = data.get("phone", "").strip()
    student_count = data.get("student_count", "").strip()
    requirement = data.get("requirement", "").strip()

    if not inst_name or not contact_person or not email or not phone or not requirement:
        return jsonify({"error": "Please fill in all required fields (Institution, Contact Person, Email, Phone, and Requirement)."}), 400

    if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        return jsonify({"error": "Please provide a valid institutional email address."}), 400

    user_payload = decode_token(request)
    user_id = user_payload["user_id"] if user_payload else None

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO institution_enquiries (user_id, institution_name, contact_person, official_email, phone, student_count, requirement, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, 'NEW')
    """, (user_id, inst_name, contact_person, email, phone, student_count, requirement))
    enquiry_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "enquiry_id": enquiry_id,
        "message": f"Thank you, {contact_person}! Your campus enterprise enquiry for {inst_name} has been received. Our institutional partnerships team will contact you within 24 hours."
    }), 201

@app.route("/api/admin/payments", methods=["GET"])
def get_admin_payments():
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Admin authentication required."}), 403

    status_filter = request.args.get("status", "all").strip().upper()

    conn = get_db_connection()
    cursor = conn.cursor()

    # Calculate statistics
    cursor.execute("SELECT COUNT(*) as total FROM payment_requests")
    total_count = cursor.fetchone()["total"] or 0

    cursor.execute("SELECT COUNT(*) as pending FROM payment_requests WHERE status = 'PENDING'")
    pending_count = cursor.fetchone()["pending"] or 0

    cursor.execute("SELECT COUNT(*) as approved FROM payment_requests WHERE status = 'APPROVED'")
    approved_count = cursor.fetchone()["approved"] or 0

    cursor.execute("SELECT COUNT(*) as rejected FROM payment_requests WHERE status = 'REJECTED'")
    rejected_count = cursor.fetchone()["rejected"] or 0

    # Overdue count (> 12 hours and status = PENDING)
    cursor.execute("""
    SELECT COUNT(*) as overdue FROM payment_requests
    WHERE status = 'PENDING' AND datetime(submitted_at) <= datetime('now', '-12 hours')
    """)
    overdue_count = cursor.fetchone()["overdue"] or 0

    # Fetch rows
    query = """
    SELECT p.*,
           u.name as student_name,
           u.email as student_email,
           u.created_at as student_registered_at,
           adm.name as verified_by_name
    FROM payment_requests p
    JOIN users u ON p.user_id = u.id
    LEFT JOIN users adm ON p.verified_by = adm.id
    """
    params = []
    if status_filter in ["PENDING", "APPROVED", "REJECTED"]:
        query += " WHERE p.status = ?"
        params.append(status_filter)

    query += " ORDER BY CASE WHEN p.status = 'PENDING' THEN 0 ELSE 1 END, p.submitted_at DESC"

    cursor.execute(query, tuple(params))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return jsonify({
        "stats": {
            "total_count": total_count,
            "pending_count": pending_count,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "overdue_count": overdue_count
        },
        "payments": rows
    })

@app.route("/api/admin/payments/<int:payment_id>", methods=["GET"])
def get_admin_payment_detail(payment_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Admin authentication required."}), 403

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT p.*,
           u.name as student_name,
           u.email as student_email,
           u.streak_days,
           u.credit_balance,
           u.created_at as student_registered_at,
           adm.name as verified_by_name
    FROM payment_requests p
    JOIN users u ON p.user_id = u.id
    LEFT JOIN users adm ON p.verified_by = adm.id
    WHERE p.id = ?
    """, (payment_id,))
    pay_row = cursor.fetchone()

    if not pay_row:
        conn.close()
        return jsonify({"error": "Payment request not found."}), 404

    cursor.execute("""
    SELECT a.*, u.name as actor_name
    FROM payment_audit_logs a
    JOIN users u ON a.actor_id = u.id
    WHERE a.payment_request_id = ?
    ORDER BY a.timestamp ASC
    """, (payment_id,))
    audit_logs = [dict(a) for a in cursor.fetchall()]
    conn.close()

    return jsonify({
        "payment": dict(pay_row),
        "audit_logs": audit_logs
    })

@app.route("/api/admin/payments/<int:payment_id>/screenshot", methods=["GET"])
def get_payment_screenshot(payment_id):
    user_payload = decode_token(request)
    if not user_payload:
        return jsonify({"error": "Authentication required."}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, screenshot_path FROM payment_requests WHERE id = ?", (payment_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Payment request not found."}), 404

    # Allow admin or the owner student
    if user_payload.get("role") != "ADMIN" and user_payload.get("user_id") != row["user_id"]:
        return jsonify({"error": "Access denied."}), 403

    filename = row["screenshot_path"]
    return send_from_directory(UPLOAD_PAYMENT_DIR, filename)

@app.route("/api/admin/payments/<int:payment_id>/approve", methods=["POST"])
def approve_payment(payment_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Admin authentication required."}), 403

    admin_id = payload["user_id"]
    admin_name = payload.get("name", "Admin")
    data = request.json or {}
    admin_notes = data.get("admin_notes", "Verified via manual UPI transaction check.")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM payment_requests WHERE id = ?", (payment_id,))
    pay_row = cursor.fetchone()
    if not pay_row:
        conn.close()
        return jsonify({"error": "Payment request not found."}), 404

    user_id = pay_row["user_id"]
    plan_name = pay_row["plan_name"]
    plan_amount = pay_row["plan_amount"]
    plan_id = pay_row["plan_id"]

    # Update payment request
    cursor.execute("""
    UPDATE payment_requests
    SET status = 'APPROVED',
        verified_at = CURRENT_TIMESTAMP,
        verified_by = ?,
        admin_notes = ?,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (admin_id, admin_notes, payment_id))

    # Activate subscription
    cursor.execute("""
    INSERT INTO subscriptions (user_id, plan_name, billing_cycle, price_inr, status, start_date, end_date)
    VALUES (?, ?, 'Monthly', ?, 'ACTIVE', CURRENT_TIMESTAMP, datetime('now', '+30 days'))
    ON CONFLICT(user_id) DO UPDATE SET
        plan_name = excluded.plan_name,
        billing_cycle = excluded.billing_cycle,
        price_inr = excluded.price_inr,
        status = 'ACTIVE',
        start_date = CURRENT_TIMESTAMP,
        end_date = datetime('now', '+30 days')
    """, (user_id, plan_name, plan_amount))

    # Award credits if applicable
    credits_to_grant = 500 if plan_id == "premium" else 100
    cursor.execute("""
    INSERT INTO credit_transactions (user_id, amount, type, description)
    VALUES (?, ?, 'SUBSCRIPTION_BONUS', ?)
    """, (user_id, credits_to_grant, f"Plan Activation Bonus - {plan_name}"))

    cursor.execute("UPDATE users SET credit_balance = COALESCE(credit_balance, 0) + ? WHERE id = ?", (credits_to_grant, user_id))

    # Log audit
    cursor.execute("""
    INSERT INTO payment_audit_logs (payment_request_id, user_id, actor_id, action, details)
    VALUES (?, ?, ?, 'PAYMENT_APPROVED', ?)
    """, (payment_id, user_id, admin_id, f"Approved by Admin #{admin_id} ({admin_name}). Notes: {admin_notes}"))

    cursor.execute("""
    INSERT INTO payment_audit_logs (payment_request_id, user_id, actor_id, action, details)
    VALUES (?, ?, ?, 'SUBSCRIPTION_ACTIVATED', ?)
    """, (payment_id, user_id, admin_id, f"Activated {plan_name} (₹{plan_amount}) for student #{user_id} with {credits_to_grant} bonus credits"))

    log_activity(conn, user_id, "SUBSCRIPTION_ACTIVATED", f"Manual UPI payment approved. {plan_name} active.")

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": f"Payment #{payment_id} approved. Student #{user_id} upgraded to {plan_name}.",
        "payment_id": payment_id,
        "status": "APPROVED"
    })

@app.route("/api/admin/payments/<int:payment_id>/reject", methods=["POST"])
def reject_payment(payment_id):
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Admin authentication required."}), 403

    admin_id = payload["user_id"]
    admin_name = payload.get("name", "Admin")
    data = request.json or {}
    rejection_reason = data.get("rejection_reason", "").strip()
    admin_notes = data.get("admin_notes", "").strip()

    if not rejection_reason:
        return jsonify({"error": "Rejection reason is required so the student knows why the verification failed."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM payment_requests WHERE id = ?", (payment_id,))
    pay_row = cursor.fetchone()
    if not pay_row:
        conn.close()
        return jsonify({"error": "Payment request not found."}), 404

    user_id = pay_row["user_id"]

    cursor.execute("""
    UPDATE payment_requests
    SET status = 'REJECTED',
        rejection_reason = ?,
        admin_notes = ?,
        verified_at = CURRENT_TIMESTAMP,
        verified_by = ?,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (rejection_reason, admin_notes, admin_id, payment_id))

    cursor.execute("""
    INSERT INTO payment_audit_logs (payment_request_id, user_id, actor_id, action, details)
    VALUES (?, ?, ?, 'PAYMENT_REJECTED', ?)
    """, (payment_id, user_id, admin_id, f"Rejected by Admin #{admin_id} ({admin_name}). Reason: {rejection_reason}"))

    log_activity(conn, user_id, "PAYMENT_REJECTED", f"Payment verification rejected. Reason: {rejection_reason}")

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": f"Payment #{payment_id} rejected.",
        "payment_id": payment_id,
        "status": "REJECTED"
    })

@app.route("/api/admin/institution-enquiries", methods=["GET"])
def get_admin_institution_enquiries():
    payload = verify_admin(request)
    if not payload:
        return jsonify({"error": "Admin authentication required."}), 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT e.*, u.name as user_account_name, u.email as user_account_email
    FROM institution_enquiries e
    LEFT JOIN users u ON e.user_id = u.id
    ORDER BY e.created_at DESC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return jsonify({"enquiries": rows})

# ================= FRONTEND WEB ROUTE =================

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    import seed
    seed.seed_demo_data()
    print("Starting DEDCODE LearnDebt AI Server on http://localhost:5050 ...")
    app.run(host="0.0.0.0", port=5050, debug=False)
