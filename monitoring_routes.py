"""
DEDCODE Career Track — Assessment Monitoring API Routes

Endpoints (all under /api/career-track/monitoring/):
  POST  /session/start          — create a new monitoring session
  POST  /session/<id>/events    — batch-ingest monitoring events (student only)
  POST  /session/<id>/end       — finalise monitoring session + compute summary
  GET   /session/<id>/summary   — get monitoring summary (student: own only)
  GET   /admin/submissions      — admin list of submissions with monitoring status
  GET   /admin/session/<id>     — admin full monitoring detail for a session

Design:
- Students can only create/write to their OWN sessions.
- Students can read only their OWN summaries.
- Admins can read all sessions and events.
- Raw camera frames are NEVER stored.
- All events are server-side validated; students cannot delete events.
"""

import json
import sqlite3
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app
import jwt

monitoring_bp = Blueprint("ct_monitoring", __name__)

DB_PATH = None  # set at registration time via app context

# ── Allowed event types (whitelist — reject any unknown type) ────────────────
ALLOWED_EVENT_TYPES = {
    "FACE_NOT_DETECTED",
    "FACE_RETURNED",
    "MULTIPLE_FACES",
    "CAMERA_DISABLED",
    "CAMERA_UNAVAILABLE",
    "CAMERA_RECONNECTED",
    "HEAD_ORIENTATION_OUTSIDE_VIEW",
    "HEAD_ORIENTATION_RETURNED",
    "TAB_SWITCH",
    "WINDOW_BLUR",
    "WINDOW_FOCUS",
    "PAGE_HIDDEN",
    "PAGE_VISIBLE",
    "CODE_EDITOR_OPEN",
    "CODE_RUN",
    "CODE_SAVE",
    "TEST_RUN",
    "SUBMISSION_ATTEMPT",
    "SUBMISSION_SUCCESS",
    "SUBMISSION_FAILURE",
    "SESSION_START",
    "SESSION_END",
}


def _get_db():
    import os
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
        return None, (jsonify({"error": "Unauthorized"}), 401)
    return payload, None


def _require_admin(req):
    payload = _decode_token(req)
    if not payload or payload.get("role") != "ADMIN":
        return None, (jsonify({"error": "Unauthorized — admin only"}), 401)
    return payload, None


def _compute_summary(session_id):
    """Build a neutral monitoring summary dict from stored events."""
    conn = _get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM monitoring_sessions WHERE id = ?", (session_id,))
    sess = cursor.fetchone()
    if not sess:
        conn.close()
        return None
    sess = dict(sess)

    cursor.execute(
        "SELECT * FROM monitoring_events WHERE session_id = ? ORDER BY timestamp ASC",
        (session_id,)
    )
    events = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Duration
    started = sess.get("started_at")
    ended = sess.get("ended_at")
    duration_min = None
    if started and ended:
        try:
            fmt = "%Y-%m-%d %H:%M:%S"
            t_start = datetime.strptime(started.split(".")[0], fmt)
            t_end = datetime.strptime(ended.split(".")[0], fmt)
            duration_min = round((t_end - t_start).total_seconds() / 60, 1)
        except Exception:
            duration_min = None

    def count_and_duration(evt_type):
        evts = [e for e in events if e["event_type"] == evt_type]
        total_dur = sum(e.get("duration_seconds") or 0 for e in evts)
        return len(evts), round(total_dur, 1)

    face_not_det_count, face_not_det_dur = count_and_duration("FACE_NOT_DETECTED")
    multi_face_count, multi_face_dur = count_and_duration("MULTIPLE_FACES")
    tab_switch_count, _ = count_and_duration("TAB_SWITCH")
    window_blur_count, _ = count_and_duration("WINDOW_BLUR")
    cam_disabled_count, _ = count_and_duration("CAMERA_DISABLED")
    cam_unavail_count, _ = count_and_duration("CAMERA_UNAVAILABLE")
    head_away_count, head_away_dur = count_and_duration("HEAD_ORIENTATION_OUTSIDE_VIEW")

    # Face visibility percentage (rough: 1 - total_face_not_detected / total_duration_seconds)
    face_visibility_pct = None
    if duration_min and duration_min > 0:
        total_sec = duration_min * 60
        face_not_det_sec = face_not_det_dur
        face_visibility_pct = round(max(0.0, (total_sec - face_not_det_sec) / total_sec * 100), 1)

    return {
        "session_id": session_id,
        "student_id": sess["student_id"],
        "enrollment_id": sess["enrollment_id"],
        "course_id": sess["course_id"],
        "status": sess["status"],
        "camera_permission": sess["camera_permission"],
        "started_at": sess["started_at"],
        "ended_at": sess["ended_at"],
        "duration_minutes": duration_min,
        "face_visibility_pct": face_visibility_pct,
        "face_not_detected": {
            "count": face_not_det_count,
            "total_duration_seconds": face_not_det_dur,
        },
        "multiple_faces": {
            "count": multi_face_count,
            "total_duration_seconds": multi_face_dur,
        },
        "head_orientation_outside_view": {
            "count": head_away_count,
            "total_duration_seconds": head_away_dur,
        },
        "tab_switch_count": tab_switch_count,
        "window_blur_count": window_blur_count,
        "camera_interruptions": cam_disabled_count + cam_unavail_count,
        "disclaimer": (
            "Monitoring events are indicators for review and are not by themselves "
            "proof of academic misconduct."
        ),
        "event_count": len(events),
        "events": events,  # full timeline (admin only — stripped for student)
    }


# ─────────────────────────────────────────────────────────────────────────────
# STUDENT ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@monitoring_bp.route("/session/start", methods=["POST"])
def start_session():
    """Student: create a new monitoring session when mini project begins."""
    payload, err = _require_student(request)
    if err:
        return err

    student_id = payload["user_id"]
    data = request.get_json() or {}
    enrollment_id = data.get("enrollment_id")
    course_id = data.get("course_id")
    camera_permission = data.get("camera_permission", "GRANTED")

    if not enrollment_id or not course_id:
        return jsonify({"error": "enrollment_id and course_id are required"}), 400

    # Verify the enrollment belongs to this student
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM career_track_enrollments WHERE id = ? AND user_id = ?",
        (enrollment_id, student_id)
    )
    if not cursor.fetchone():
        conn.close()
        return jsonify({"error": "Enrollment not found or not yours"}), 403

    # Mark any existing ACTIVE session for this enrollment as INTERRUPTED
    cursor.execute(
        """UPDATE monitoring_sessions
           SET status = 'INTERRUPTED', ended_at = CURRENT_TIMESTAMP
           WHERE enrollment_id = ? AND status = 'ACTIVE'""",
        (enrollment_id,)
    )

    cursor.execute(
        """INSERT INTO monitoring_sessions
           (student_id, enrollment_id, course_id, camera_permission, status)
           VALUES (?, ?, ?, ?, 'ACTIVE')""",
        (student_id, enrollment_id, course_id, camera_permission)
    )
    conn.commit()
    session_id = cursor.lastrowid
    conn.close()

    return jsonify({
        "status": "success",
        "session_id": session_id,
        "message": "Monitoring session started."
    })


@monitoring_bp.route("/session/<int:session_id>/events", methods=["POST"])
def ingest_events(session_id):
    """Student: batch-ingest monitoring events. Students can ONLY write to own sessions."""
    payload, err = _require_student(request)
    if err:
        return err

    student_id = payload["user_id"]

    conn = _get_db()
    cursor = conn.cursor()

    # Ownership check
    cursor.execute(
        "SELECT id, status FROM monitoring_sessions WHERE id = ? AND student_id = ?",
        (session_id, student_id)
    )
    sess = cursor.fetchone()
    if not sess:
        conn.close()
        return jsonify({"error": "Session not found or not yours"}), 403
    if sess["status"] != "ACTIVE":
        conn.close()
        return jsonify({"error": "Session is not active"}), 409

    data = request.get_json() or {}
    events = data.get("events", [])
    if not isinstance(events, list):
        conn.close()
        return jsonify({"error": "events must be a list"}), 400

    inserted = 0
    for evt in events:
        evt_type = evt.get("event_type", "")
        if evt_type not in ALLOWED_EVENT_TYPES:
            continue  # silently skip unknown event types
        ts = evt.get("timestamp") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        duration = float(evt.get("duration_seconds") or 0)
        meta = evt.get("metadata")
        meta_json = json.dumps(meta) if meta else None
        cursor.execute(
            """INSERT INTO monitoring_events
               (session_id, event_type, timestamp, duration_seconds, metadata_json)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, evt_type, ts, duration, meta_json)
        )
        inserted += 1

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "inserted": inserted})


@monitoring_bp.route("/session/<int:session_id>/end", methods=["POST"])
def end_session(session_id):
    """Student: end a monitoring session and compute summary."""
    payload, err = _require_student(request)
    if err:
        return err

    student_id = payload["user_id"]
    data = request.get_json() or {}
    status = data.get("status", "COMPLETED")
    if status not in ("COMPLETED", "INTERRUPTED", "CANCELLED"):
        status = "COMPLETED"

    conn = _get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM monitoring_sessions WHERE id = ? AND student_id = ?",
        (session_id, student_id)
    )
    if not cursor.fetchone():
        conn.close()
        return jsonify({"error": "Session not found or not yours"}), 403

    cursor.execute(
        """UPDATE monitoring_sessions
           SET status = ?, ended_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (status, session_id)
    )
    conn.commit()
    conn.close()

    # Compute and cache summary
    summary = _compute_summary(session_id)
    if summary:
        # cache summary (strip event detail for cache)
        summary_cache = {k: v for k, v in summary.items() if k != "events"}
        conn2 = _get_db()
        conn2.execute(
            "UPDATE monitoring_sessions SET summary_json = ? WHERE id = ?",
            (json.dumps(summary_cache), session_id)
        )
        conn2.commit()
        conn2.close()

    # Return student-facing summary (no raw events)
    if summary:
        del summary["events"]
    return jsonify({"status": "success", "summary": summary})


@monitoring_bp.route("/session/<int:session_id>/summary", methods=["GET"])
def get_session_summary(session_id):
    """Student: get own monitoring summary (no raw events returned)."""
    payload, err = _require_student(request)
    if err:
        return err

    student_id = payload["user_id"]
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM monitoring_sessions WHERE id = ? AND student_id = ?",
        (session_id, student_id)
    )
    if not cursor.fetchone():
        conn.close()
        return jsonify({"error": "Session not found or not yours"}), 403
    conn.close()

    summary = _compute_summary(session_id)
    if not summary:
        return jsonify({"error": "Session not found"}), 404
    del summary["events"]  # never expose raw timeline to student
    return jsonify({"status": "success", "summary": summary})


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@monitoring_bp.route("/admin/submissions", methods=["GET"])
def admin_list_submissions():
    """Admin: list all mini-project submissions with their monitoring session status."""
    payload, err = _require_admin(request)
    if err:
        return err

    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            s.id             AS submission_id,
            s.user_id        AS student_id,
            u.name           AS student_name,
            u.email          AS student_email,
            c.title          AS course_title,
            s.final_score,
            s.passed,
            s.submitted_at,
            ms.id            AS session_id,
            ms.status        AS monitoring_status,
            ms.camera_permission,
            ms.started_at,
            ms.ended_at,
            ms.summary_json
        FROM career_track_project_submissions s
        JOIN users     u  ON s.user_id = u.id
        JOIN courses   c  ON s.course_id = c.id
        LEFT JOIN monitoring_sessions ms ON ms.enrollment_id = s.enrollment_id
        ORDER BY s.submitted_at DESC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    for row in rows:
        if row.get("summary_json"):
            try:
                row["monitoring_summary"] = json.loads(row.pop("summary_json"))
            except Exception:
                row["monitoring_summary"] = None
                row.pop("summary_json", None)
        else:
            row.pop("summary_json", None)
            row["monitoring_summary"] = None

    return jsonify({"status": "success", "submissions": rows})


@monitoring_bp.route("/admin/session/<int:session_id>", methods=["GET"])
def admin_get_session(session_id):
    """Admin: full monitoring session detail including event timeline."""
    payload, err = _require_admin(request)
    if err:
        return err

    summary = _compute_summary(session_id)
    if not summary:
        return jsonify({"error": "Session not found"}), 404

    return jsonify({
        "status": "success",
        "summary": summary,
        "disclaimer": (
            "Monitoring events are indicators for review and are not by themselves "
            "proof of academic misconduct."
        )
    })
