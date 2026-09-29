import json
import sqlite3
from flask import Blueprint, request, jsonify, current_app
import jwt

from recommendations.engine import RecommendationEngine, get_db

recommendations_bp = Blueprint("recommendations", __name__)

def decode_token(req):
    auth_header = req.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ")[1]
    try:
        secret = current_app.config.get("SECRET_KEY", "dedcode-learndebt-secret-key-2026")
        return jwt.decode(token, secret, algorithms=["HS256"])
    except Exception:
        return None

def verify_student(req):
    payload = decode_token(req)
    if not payload:
        return None
    return payload

# ================= 1. COMPREHENSIVE DASHBOARD ENDPOINT =================

@recommendations_bp.route("/dashboard", methods=["GET"])
def get_recommendations_dashboard():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["user_id"]
    force_refresh = request.args.get("refresh", "false").lower() == "true"

    try:
        data = RecommendationEngine.compute_and_save_recommendations(
            user_id,
            trigger_event="MANUAL_REFRESH" if force_refresh else "DASHBOARD_VIEW"
        )
        return jsonify({
            "status": "success",
            "data": data
        })
    except Exception as e:
        return jsonify({"error": f"Failed to compute recommendations: {str(e)}"}), 500

# ================= 2. RECOMMENDED NEXT COURSE =================

@recommendations_bp.route("/next-course", methods=["GET"])
def get_next_course():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["user_id"]
    data = RecommendationEngine.compute_and_save_recommendations(user_id, trigger_event="NEXT_COURSE_QUERY")
    return jsonify({
        "status": "success",
        "recommended_next_course": data["recommended_next_course"],
        "all_ranked_courses": data["all_recommended_courses"]
    })

# ================= 3. CONTINUE LEARNING =================

@recommendations_bp.route("/continue-learning", methods=["GET"])
def get_continue_learning():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["user_id"]
    data = RecommendationEngine.compute_and_save_recommendations(user_id, trigger_event="CONTINUE_LEARNING_QUERY")
    return jsonify({
        "status": "success",
        "continue_learning": data["continue_learning"]
    })

# ================= 4. SKILLS & GAPS =================

@recommendations_bp.route("/skills", methods=["GET"])
def get_skills_and_gaps():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["user_id"]
    data = RecommendationEngine.compute_and_save_recommendations(user_id, trigger_event="SKILLS_QUERY")
    return jsonify({
        "status": "success",
        "target_role": data["target_role"],
        "skills_to_develop": data["skills_to_develop"]
    })

# ================= 5. RECOMMENDED PROJECTS =================

@recommendations_bp.route("/projects", methods=["GET"])
def get_recommended_projects():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["user_id"]
    data = RecommendationEngine.compute_and_save_recommendations(user_id, trigger_event="PROJECTS_QUERY")
    return jsonify({
        "status": "success",
        "recommended_projects": data["recommended_projects"]
    })

# ================= 6. CERTIFICATES =================

@recommendations_bp.route("/certificates", methods=["GET"])
def get_certificates():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rec_external_certificates WHERE is_active = 1 ORDER BY provider_type ASC, id ASC")
    certs = []
    for r in cursor.fetchall():
        item = dict(r)
        item["skills_covered"] = json.loads(item["skills_covered_json"])
        item["career_paths"] = json.loads(item["career_paths_json"])
        item["issuer"] = item["provider_name"]
        item["external_url"] = item["official_url"]
        item["exam_format"] = "50/50 AI + Senior Mentor Review" if item["provider_type"] == "PLATFORM" else "Third-Party Proctored Exam"
        certs.append(item)
    conn.close()

    return jsonify({
        "status": "success",
        "certificates": certs
    })

# ================= 7. JOB MARKET TRENDS =================

@recommendations_bp.route("/job-trends", methods=["GET"])
def get_job_trends():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rec_job_market_trends ORDER BY growth_rate_pct DESC")
    trends = []
    for r in cursor.fetchall():
        item = dict(r)
        item["top_demanded_skills"] = json.loads(item["top_demanded_skills_json"])
        item["role_name"] = item["role_title"]
        item["salary_range_usd"] = item["avg_salary_range"]
        item["category"] = "AI & Platform Engineering"
        item["demand_score"] = 95 if item["market_demand_level"] == "VERY HIGH" else 88
        trends.append(item)
    conn.close()

    return jsonify({
        "status": "success",
        "data_source": "Configured Benchmark Labor Data (Q3 2026 Reference Model)",
        "job_trends": trends
    })

# ================= 8. PERSONALIZED ROADMAP =================

@recommendations_bp.route("/roadmap", methods=["GET"])
def get_roadmap():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["user_id"]
    data = RecommendationEngine.compute_and_save_recommendations(user_id, trigger_event="ROADMAP_QUERY")
    return jsonify({
        "status": "success",
        "roadmap": data["roadmap"]
    })

# ================= 9. RECALCULATE ON DEMAND =================

@recommendations_bp.route("/recalculate", methods=["POST"])
def recalculate_recommendations():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["user_id"]
    data = RecommendationEngine.compute_and_save_recommendations(user_id, trigger_event="USER_REQUESTED_RECALCULATION")
    return jsonify({
        "status": "success",
        "message": "Recommendations successfully recalculated.",
        "data": data
    })

# ================= 10. RECOMMENDATION HISTORY SNAPSHOTS =================

@recommendations_bp.route("/history", methods=["GET"])
def get_history():
    payload = verify_student(request)
    if not payload:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = payload["user_id"]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, trigger_event, snapshot_json, created_at
    FROM rec_recommendation_history
    WHERE user_id = ?
    ORDER BY id DESC LIMIT 20
    """, (user_id,))
    history = []
    for r in cursor.fetchall():
        history.append({
            "id": r["id"],
            "trigger_event": r["trigger_event"],
            "snapshot": json.loads(r["snapshot_json"]),
            "created_at": r["created_at"]
        })
    conn.close()

    return jsonify({
        "status": "success",
        "history": history
    })
