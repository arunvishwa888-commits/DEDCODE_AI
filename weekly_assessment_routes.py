"""
DEDCODE Career Track — Live Weekly AI + Mentor Assessment API Routes

Endpoints (under /api/career-track/weekly-assessment/):
  POST  /session/init               — Initialize session with system checks (Student)
  POST  /session/<id>/start         — Start live assessment session (Student)
  POST  /session/<id>/events        — Ingest monitoring events (Student)
  POST  /session/<id>/warning       — Register confirmed warning (Student/System)
  POST  /session/<id>/terminate     — Terminate session on max warnings (System/Student)
  POST  /session/<id>/submit        — Submit answers and execute 50/50 AI + Mentor evaluation (Student)
  GET   /session/<id>/status        — Get session state & monitoring HUD info (Student)
  GET   /student/attempts           — Get student's assessment attempt history (Student)
  GET   /admin/sessions             — List all assessment sessions (Admin/Mentor)
  GET   /mentor/review/<id>         — Get full session & event timeline for review (Mentor/Admin)
  POST  /mentor/action/<id>         — Execute review action: ALLOW_RETAKE | CONFIRM_TERMINATION | DISMISS_EVENT (Mentor/Admin)
  GET   /config                     — Get assessment configuration & thresholds (Public/Student)
  POST  /config                     — Update assessment configuration (Admin)
"""

import json
import sqlite3
import os
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app
import jwt

from career_track.weekly_evaluator import WeeklyAssessmentEvaluator

weekly_assessment_bp = Blueprint("weekly_assessment", __name__)

ALLOWED_EVENT_TYPES = {
    "STUDENT_FACE_PRESENT",
    "FACE_NOT_DETECTED",
    "MULTIPLE_FACES",
    "EXTERNAL_AUDIO_DETECTED",
    "SIGNIFICANT_BACKGROUND_AUDIO",
    "MICROPHONE_DISABLED",
    "MICROPHONE_RECONNECTED",
    "CAMERA_DISABLED",
    "CAMERA_UNAVAILABLE",
    "CAMERA_RECONNECTED",
    "TAB_SWITCH",
    "PAGE_HIDDEN",
    "PAGE_VISIBLE",
    "WINDOW_BLUR",
    "WINDOW_FOCUS",
    "FULLSCREEN_EXIT",
    "FULLSCREEN_ENTER",
    "WARNING_ISSUED",
    "ASSESSMENT_TERMINATED",
    "OTHER_MONITORING_EVENT"
}


def _get_db():
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "learndebt.db"
    )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _decode_token(req):
    auth_header = req.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ")[1]
    try:
        secret = current_app.config.get("SECRET_KEY", "dedcode-learndebt-secret-key-2026")
        return jwt.decode(token, secret, algorithms=["HS256"])
    except Exception:
        return None


def _require_student(req):
    payload = _decode_token(req)
    if not payload or payload.get("role") != "STUDENT":
        return None, (jsonify({"error": "Unauthorized — Student access required"}), 401)
    return payload, None


def _require_mentor_or_admin(req):
    payload = _decode_token(req)
    if not payload or payload.get("role") not in ["INSTRUCTOR", "MENTOR", "ADMIN"]:
        return None, (jsonify({"error": "Unauthorized — Mentor/Admin access required"}), 401)
    return payload, None


def _require_admin(req):
    payload = _decode_token(req)
    if not payload or payload.get("role") != "ADMIN":
        return None, (jsonify({"error": "Unauthorized — Admin access required"}), 401)
    return payload, None


def _get_config():
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM weekly_assessment_config ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return {
        "max_warnings": 2,
        "face_not_detected_threshold": 8.0,
        "multiple_face_threshold": 2.5,
        "external_audio_threshold": 0.25,
        "external_audio_duration": 3.0,
        "camera_failure_threshold": 5.0,
        "tab_switch_policy": "WARNING"
    }


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@weekly_assessment_bp.route("/config", methods=["GET"])
def get_assessment_config():
    return jsonify({"status": "success", "config": _get_config()})


@weekly_assessment_bp.route("/config", methods=["POST"])
def update_assessment_config():
    payload, err = _require_admin(request)
    if err:
        return err

    data = request.get_json() or {}
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE weekly_assessment_config
    SET max_warnings = ?, face_not_detected_threshold = ?, multiple_face_threshold = ?,
        external_audio_threshold = ?, external_audio_duration = ?, camera_failure_threshold = ?,
        tab_switch_policy = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = 1
    """, (
        data.get("max_warnings", 2),
        data.get("face_not_detected_threshold", 8.0),
        data.get("multiple_face_threshold", 2.5),
        data.get("external_audio_threshold", 0.25),
        data.get("external_audio_duration", 3.0),
        data.get("camera_failure_threshold", 5.0),
        data.get("tab_switch_policy", "WARNING")
    ))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "config": _get_config()})


# ─────────────────────────────────────────────────────────────────────────────
# STUDENT LIVE ASSESSMENT SESSION LIFECYCLE
# ─────────────────────────────────────────────────────────────────────────────

@weekly_assessment_bp.route("/session/init", methods=["POST"])
def init_assessment_session():
    """Initializes a new assessment session after pre-check passes."""
    payload, err = _require_student(request)
    if err:
        return err

    student_id = payload["user_id"]
    data = request.get_json() or {}
    course_id = data.get("course_id")
    module_id = data.get("module_id")
    week_number = data.get("week_number", 1)
    system_checks = data.get("system_checks", {})

    if not course_id or not module_id:
        return jsonify({"error": "course_id and module_id are required"}), 400

    conn = _get_db()
    cursor = conn.cursor()

    # Check if student has a currently TERMINATED or REVIEW_REQUIRED session that has not been reviewed
    cursor.execute("""
    SELECT id, status, mentor_action FROM weekly_assessment_sessions
    WHERE student_id = ? AND module_id = ?
    ORDER BY id DESC LIMIT 1
    """, (student_id, module_id))
    last_session = cursor.fetchone()

    if last_session:
        l_status = last_session["status"]
        l_action = last_session["mentor_action"]
        if l_status in ["TERMINATED", "REVIEW_REQUIRED"] and l_action != "ALLOW_RETAKE":
            conn.close()
            return jsonify({
                "error": "Previous assessment attempt was terminated and requires mentor review before a retake can begin.",
                "status": "REVIEW_REQUIRED",
                "session_id": last_session["id"]
            }), 403

    # Calculate attempt number
    cursor.execute("""
    SELECT COUNT(*) as count FROM weekly_assessment_sessions
    WHERE student_id = ? AND module_id = ?
    """, (student_id, module_id))
    attempt_num = cursor.fetchone()["count"] + 1

    config = _get_config()

    cursor.execute("""
    INSERT INTO weekly_assessment_sessions (
        student_id, course_id, module_id, week_number, status,
        warning_count, max_warnings, system_checks_json, attempt_number
    ) VALUES (?, ?, ?, ?, 'READY', 0, ?, ?, ?)
    """, (
        student_id, course_id, module_id, week_number,
        config["max_warnings"], json.dumps(system_checks), attempt_num
    ))
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        "status": "success",
        "session_id": session_id,
        "attempt_number": attempt_num,
        "max_warnings": config["max_warnings"],
        "message": "Assessment session initialized. Ready to begin."
    })


@weekly_assessment_bp.route("/session/<int:session_id>/start", methods=["POST"])
def start_live_assessment(session_id):
    """Marks session as ACTIVE and records started_at timestamp."""
    payload, err = _require_student(request)
    if err:
        return err

    student_id = payload["user_id"]
    conn = _get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, status FROM weekly_assessment_sessions
    WHERE id = ? AND student_id = ?
    """, (session_id, student_id))
    sess = cursor.fetchone()

    if not sess:
        conn.close()
        return jsonify({"error": "Session not found or not yours"}), 404

    if sess["status"] == "TERMINATED":
        conn.close()
        return jsonify({"error": "Cannot start a terminated session."}), 403

    cursor.execute("""
    UPDATE weekly_assessment_sessions
    SET status = 'ACTIVE', started_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (session_id,))
    conn.commit()
    conn.close()

    return jsonify({
        "status": "success",
        "session_id": session_id,
        "session_status": "ACTIVE",
        "message": "Live assessment session is now active."
    })


@weekly_assessment_bp.route("/session/<int:session_id>/events", methods=["POST"])
def ingest_assessment_events(session_id):
    """Batch-ingest monitoring events for the active weekly assessment session."""
    payload, err = _require_student(request)
    if err:
        return err

    student_id = payload["user_id"]
    conn = _get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, status, warning_count, max_warnings FROM weekly_assessment_sessions
    WHERE id = ? AND student_id = ?
    """, (session_id, student_id))
    sess = cursor.fetchone()

    if not sess:
        conn.close()
        return jsonify({"error": "Session not found or not yours"}), 404

    if sess["status"] != "ACTIVE":
        conn.close()
        return jsonify({"error": f"Session is not active (status: {sess['status']})"}), 409

    data = request.get_json() or {}
    events = data.get("events", [])
    inserted = 0

    for evt in events:
        evt_type = evt.get("event_type", "")
        if evt_type not in ALLOWED_EVENT_TYPES:
            continue

        ts = evt.get("timestamp") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        dur = float(evt.get("duration_seconds") or 0.0)
        conf = float(evt.get("confidence") or 1.0)
        warn_num = int(evt.get("warning_number") or 0)
        meta = json.dumps(evt.get("metadata")) if evt.get("metadata") else None

        cursor.execute("""
        INSERT INTO weekly_assessment_events (
            session_id, event_type, timestamp, duration_seconds, confidence, warning_number, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session_id, evt_type, ts, dur, conf, warn_num, meta))
        inserted += 1

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "inserted": inserted})


@weekly_assessment_bp.route("/session/<int:session_id>/warning", methods=["POST"])
def issue_assessment_warning(session_id):
    """
    Registers a confirmed violation warning.
    Warning 1 -> warning_count = 1
    Warning 2 -> warning_count = 2
    Violation 3 -> Automatically terminates session (status: TERMINATED / REVIEW_REQUIRED)
    """
    payload, err = _require_student(request)
    if err:
        return err

    student_id = payload["user_id"]
    data = request.get_json() or {}
    reason = data.get("reason", "Assessment monitoring event detected.")
    trigger_type = data.get("event_type", "OTHER_MONITORING_EVENT")

    conn = _get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, status, warning_count, max_warnings FROM weekly_assessment_sessions
    WHERE id = ? AND student_id = ?
    """, (session_id, student_id))
    sess = cursor.fetchone()

    if not sess:
        conn.close()
        return jsonify({"error": "Session not found or not yours"}), 404

    if sess["status"] != "ACTIVE":
        conn.close()
        return jsonify({"error": "Session is not active"}), 409

    current_warn = sess["warning_count"]
    new_warn = current_warn + 1
    max_warn = sess["max_warnings"]

    # Log the warning event
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    INSERT INTO weekly_assessment_events (
        session_id, event_type, timestamp, duration_seconds, warning_number, metadata_json
    ) VALUES (?, 'WARNING_ISSUED', ?, 0, ?, ?)
    """, (session_id, ts, new_warn, json.dumps({"reason": reason, "trigger_type": trigger_type})))

    if new_warn > max_warn:
        # Third confirmed violation -> Immediate Termination
        cursor.execute("""
        UPDATE weekly_assessment_sessions
        SET status = 'TERMINATED', warning_count = ?, termination_reason = ?,
            terminated_at = CURRENT_TIMESTAMP, ended_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """, (new_warn, f"Max monitoring warnings reached: {reason}", session_id))

        cursor.execute("""
        INSERT INTO weekly_assessment_events (
            session_id, event_type, timestamp, duration_seconds, warning_number, metadata_json
        ) VALUES (?, 'ASSESSMENT_TERMINATED', ?, 0, ?, ?)
        """, (session_id, ts, new_warn, json.dumps({"final_reason": reason})))

        conn.commit()
        conn.close()

        return jsonify({
            "status": "TERMINATED",
            "terminated": True,
            "warning_count": new_warn,
            "max_warnings": max_warn,
            "reason": reason,
            "message": "Assessment terminated. Your assessment was ended because the maximum number of monitoring warnings was reached."
        })

    # Within warning limits
    cursor.execute("""
    UPDATE weekly_assessment_sessions
    SET warning_count = ?
    WHERE id = ?
    """, (new_warn, session_id))
    conn.commit()
    conn.close()

    return jsonify({
        "status": "WARNING_RECORDED",
        "terminated": False,
        "warning_count": new_warn,
        "max_warnings": max_warn,
        "reason": reason,
        "message": f"Assessment Monitoring Warning {new_warn}/{max_warn}: {reason}"
    })


@weekly_assessment_bp.route("/session/<int:session_id>/terminate", methods=["POST"])
def terminate_session(session_id):
    """Directly terminates session (e.g. from repeated disconnect or manual cancel)."""
    payload, err = _require_student(request)
    if err:
        return err

    student_id = payload["user_id"]
    data = request.get_json() or {}
    reason = data.get("reason", "Assessment terminated by monitoring policy.")

    conn = _get_db()
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE weekly_assessment_sessions
    SET status = 'TERMINATED', termination_reason = ?,
        terminated_at = CURRENT_TIMESTAMP, ended_at = CURRENT_TIMESTAMP
    WHERE id = ? AND student_id = ?
    """, (reason, session_id, student_id))

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    INSERT INTO weekly_assessment_events (
        session_id, event_type, timestamp, duration_seconds, metadata_json
    ) VALUES (?, 'ASSESSMENT_TERMINATED', ?, 0, ?)
    """, (session_id, ts, json.dumps({"reason": reason})))

    conn.commit()
    conn.close()

    return jsonify({
        "status": "TERMINATED",
        "message": "Assessment session terminated."
    })


@weekly_assessment_bp.route("/session/<int:session_id>/submit", methods=["POST"])
def submit_weekly_assessment(session_id):
    """
    Submits weekly assessment answers and triggers 50/50 AI + Mentor evaluation.
    Monitoring events are kept strictly separate from technical scores.
    """
    payload, err = _require_student(request)
    if err:
        return err

    student_id = payload["user_id"]
    data = request.get_json() or {}
    answers = data.get("answers", {})

    conn = _get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT * FROM weekly_assessment_sessions
    WHERE id = ? AND student_id = ?
    """, (session_id, student_id))
    sess = cursor.fetchone()

    if not sess:
        conn.close()
        return jsonify({"error": "Session not found or not yours"}), 404

    if sess["status"] == "TERMINATED":
        conn.close()
        return jsonify({"error": "Cannot submit a terminated assessment session."}), 403

    # Run 50/50 AI + Mentor evaluation
    eval_result = WeeklyAssessmentEvaluator.evaluate_weekly_submission(
        module_id=sess["module_id"],
        week_number=sess["week_number"],
        answers_payload=answers
    )

    cursor.execute("""
    UPDATE weekly_assessment_sessions
    SET status = 'COMPLETED',
        answers_json = ?,
        ai_score = ?,
        ai_feedback_json = ?,
        mentor_score = ?,
        mentor_feedback_json = ?,
        final_score = ?,
        passed = ?,
        ended_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (
        json.dumps(answers),
        eval_result["ai_score"],
        json.dumps(eval_result["ai_feedback"]),
        eval_result["mentor_score"],
        json.dumps(eval_result["mentor_feedback"]),
        eval_result["final_score"],
        1 if eval_result["passed"] else 0,
        session_id
    ))

    # Update module progress in learning_progress
    cursor.execute("""
    INSERT INTO learning_progress (user_id, course_id, module_id, completed, score, updated_at)
    VALUES (?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(user_id, module_id) DO UPDATE SET
        completed = 1,
        score = MAX(score, ?),
        updated_at = CURRENT_TIMESTAMP
    """, (
        student_id, sess["course_id"], sess["module_id"],
        int(eval_result["final_score"]), int(eval_result["final_score"])
    ))

    conn.commit()
    conn.close()

    return jsonify({
        "status": "success",
        "session_id": session_id,
        "evaluation": eval_result,
        "message": "Weekly assessment submitted and evaluated successfully."
    })


@weekly_assessment_bp.route("/session/<int:session_id>/status", methods=["GET"])
def get_session_status(session_id):
    """Returns the current state and neutral monitoring summary for student."""
    payload, err = _require_student(request)
    if err:
        return err

    student_id = payload["user_id"]
    conn = _get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT s.*, m.title as module_title, c.title as course_title
    FROM weekly_assessment_sessions s
    JOIN modules m ON s.module_id = m.id
    JOIN courses c ON s.course_id = c.id
    WHERE s.id = ? AND s.student_id = ?
    """, (session_id, student_id))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return jsonify({"error": "Session not found"}), 404

    sess = dict(row)

    # Fetch event counts for student summary
    cursor.execute("""
    SELECT event_type, COUNT(*) as count, SUM(duration_seconds) as total_dur
    FROM weekly_assessment_events
    WHERE session_id = ?
    GROUP BY event_type
    """, (session_id,))
    event_counts = {r["event_type"]: {"count": r["count"], "total_duration": r["total_dur"] or 0.0} for r in cursor.fetchall()}

    conn.close()

    return jsonify({
        "status": "success",
        "session": {
            "id": sess["id"],
            "course_title": sess["course_title"],
            "module_title": sess["module_title"],
            "week_number": sess["week_number"],
            "session_status": sess["status"],
            "warning_count": sess["warning_count"],
            "max_warnings": sess["max_warnings"],
            "termination_reason": sess["termination_reason"],
            "attempt_number": sess["attempt_number"],
            "final_score": sess["final_score"],
            "passed": bool(sess["passed"]),
            "ai_score": sess["ai_score"],
            "mentor_score": sess["mentor_score"],
            "event_summary": event_counts,
            "disclaimer": "Monitoring events are indicators for review and are not by themselves proof of academic misconduct."
        }
    })


@weekly_assessment_bp.route("/student/attempts", methods=["GET"])
def get_student_attempts():
    """Gets attempt history for a specific module or course."""
    payload, err = _require_student(request)
    if err:
        return err

    student_id = payload["user_id"]
    module_id = request.args.get("module_id", type=int)

    conn = _get_db()
    cursor = conn.cursor()

    if module_id:
        cursor.execute("""
        SELECT * FROM weekly_assessment_sessions
        WHERE student_id = ? AND module_id = ?
        ORDER BY attempt_number DESC
        """, (student_id, module_id))
    else:
        cursor.execute("""
        SELECT * FROM weekly_assessment_sessions
        WHERE student_id = ?
        ORDER BY id DESC LIMIT 10
        """, (student_id,))

    attempts = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return jsonify({"status": "success", "attempts": attempts})


# ─────────────────────────────────────────────────────────────────────────────
# MENTOR & ADMIN REVIEW ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@weekly_assessment_bp.route("/admin/sessions", methods=["GET"])
def admin_list_sessions():
    """Admin/Mentor: list weekly assessment sessions with filtering."""
    payload, err = _require_mentor_or_admin(request)
    if err:
        return err

    status_filter = request.args.get("status")
    course_id = request.args.get("course_id", type=int)

    conn = _get_db()
    cursor = conn.cursor()

    query = """
    SELECT s.id, s.student_id, u.name as student_name, u.email as student_email,
           s.course_id, c.title as course_title, s.module_id, m.title as module_title,
           s.week_number, s.status, s.warning_count, s.max_warnings, s.termination_reason,
           s.final_score, s.passed, s.attempt_number, s.started_at, s.ended_at, s.mentor_action
    FROM weekly_assessment_sessions s
    JOIN users u ON s.student_id = u.id
    JOIN courses c ON s.course_id = c.id
    JOIN modules m ON s.module_id = m.id
    WHERE 1=1
    """
    params = []

    if status_filter:
        query += " AND s.status = ?"
        params.append(status_filter)
    if course_id:
        query += " AND s.course_id = ?"
        params.append(course_id)

    query += " ORDER BY s.id DESC LIMIT 50"

    cursor.execute(query, tuple(params))
    sessions = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return jsonify({"status": "success", "sessions": sessions})


@weekly_assessment_bp.route("/mentor/review/<int:session_id>", methods=["GET"])
def mentor_get_session_review(session_id):
    """Mentor/Admin: get complete session details and full event timeline for review."""
    payload, err = _require_mentor_or_admin(request)
    if err:
        return err

    conn = _get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT s.*, u.name as student_name, u.email as student_email,
           c.title as course_title, m.title as module_title
    FROM weekly_assessment_sessions s
    JOIN users u ON s.student_id = u.id
    JOIN courses c ON s.course_id = c.id
    JOIN modules m ON s.module_id = m.id
    WHERE s.id = ?
    """, (session_id,))
    sess = cursor.fetchone()

    if not sess:
        conn.close()
        return jsonify({"error": "Session not found"}), 404

    session_data = dict(sess)

    # Fetch full event timeline
    cursor.execute("""
    SELECT * FROM weekly_assessment_events
    WHERE session_id = ?
    ORDER BY timestamp ASC
    """, (session_id,))
    events = [dict(e) for e in cursor.fetchall()]

    conn.close()

    return jsonify({
        "status": "success",
        "session": session_data,
        "events": events,
        "disclaimer": "Monitoring events are indicators for review and are not by themselves proof of academic misconduct."
    })


@weekly_assessment_bp.route("/mentor/action/<int:session_id>", methods=["POST"])
def mentor_review_action(session_id):
    """
    Mentor/Admin review actions on terminated or flagged assessments:
    - ALLOW_RETAKE: Allows student to initialize a fresh AssessmentSession.
    - CONFIRM_TERMINATION: Finalizes the termination record.
    - DISMISS_EVENT: Clears flags and acknowledges as non-misconduct.
    - MANUAL_APPROVE: Manually approves the technical submission.
    """
    payload, err = _require_mentor_or_admin(request)
    if err:
        return err

    data = request.get_json() or {}
    action = data.get("action")
    notes = data.get("notes", "")

    if action not in ["ALLOW_RETAKE", "CONFIRM_TERMINATION", "DISMISS_EVENT", "MANUAL_APPROVE"]:
        return jsonify({"error": "Invalid action"}), 400

    conn = _get_db()
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE weekly_assessment_sessions
    SET mentor_action = ?,
        mentor_review_notes = ?,
        status = CASE 
            WHEN ? = 'ALLOW_RETAKE' THEN 'COMPLETED'
            WHEN ? = 'MANUAL_APPROVE' THEN 'COMPLETED'
            WHEN ? = 'CONFIRM_TERMINATION' THEN 'TERMINATED'
            ELSE status
        END
    WHERE id = ?
    """, (action, notes, action, action, action, session_id))

    conn.commit()
    conn.close()

    return jsonify({
        "status": "success",
        "session_id": session_id,
        "action": action,
        "message": f"Mentor action '{action}' recorded successfully."
    })
