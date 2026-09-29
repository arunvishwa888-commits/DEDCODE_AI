"""
DEDCODE Career Track — Live Weekly AI + Mentor Assessment Database Migration
Creates weekly_assessment_sessions, weekly_assessment_events, and assessment_config tables.
Fully additive and idempotent.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "learndebt.db")


def run_weekly_assessment_migrations():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Weekly Assessment Live Sessions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS weekly_assessment_sessions (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id           INTEGER NOT NULL,
        course_id            INTEGER NOT NULL,
        module_id            INTEGER NOT NULL,
        week_number          INTEGER DEFAULT 1,
        status               TEXT DEFAULT 'READY', -- READY | ACTIVE | SUBMITTED | TERMINATED | COMPLETED | REVIEW_REQUIRED
        warning_count        INTEGER DEFAULT 0,
        max_warnings         INTEGER DEFAULT 2,
        termination_reason   TEXT,
        terminated_at        DATETIME,
        system_checks_json   TEXT,
        answers_json         TEXT,
        ai_score             REAL,
        ai_feedback_json     TEXT,
        mentor_score         REAL,
        mentor_feedback_json TEXT,
        final_score          REAL,
        passed               INTEGER DEFAULT 0,
        attempt_number       INTEGER DEFAULT 1,
        mentor_action        TEXT,                 -- ALLOW_RETAKE | CONFIRM_TERMINATION | DISMISS_EVENT | MANUAL_APPROVE
        mentor_review_notes  TEXT,
        started_at           DATETIME,
        ended_at             DATETIME,
        created_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (student_id) REFERENCES users(id),
        FOREIGN KEY (course_id)  REFERENCES courses(id),
        FOREIGN KEY (module_id)  REFERENCES modules(id)
    )
    """)

    # 2. Weekly Assessment Monitoring Events
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS weekly_assessment_events (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id           INTEGER NOT NULL,
        event_type           TEXT NOT NULL,
        timestamp            DATETIME NOT NULL,
        duration_seconds     REAL DEFAULT 0.0,
        confidence           REAL DEFAULT 1.0,
        warning_number       INTEGER DEFAULT 0,
        metadata_json        TEXT,
        created_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES weekly_assessment_sessions(id)
    )
    """)

    # 3. Assessment Configuration Settings (Admin configurable)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS weekly_assessment_config (
        id                             INTEGER PRIMARY KEY AUTOINCREMENT,
        max_warnings                   INTEGER DEFAULT 2,
        face_not_detected_threshold    REAL DEFAULT 8.0,
        multiple_face_threshold        REAL DEFAULT 2.5,
        external_audio_threshold       REAL DEFAULT 0.25,
        external_audio_duration        REAL DEFAULT 3.0,
        camera_failure_threshold       REAL DEFAULT 5.0,
        tab_switch_policy              TEXT DEFAULT 'WARNING', -- WARNING | LOG_ONLY
        updated_at                     DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Seed initial default config if not present
    cursor.execute("SELECT COUNT(*) FROM weekly_assessment_config")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO weekly_assessment_config (
            max_warnings, face_not_detected_threshold, multiple_face_threshold,
            external_audio_threshold, external_audio_duration, camera_failure_threshold, tab_switch_policy
        ) VALUES (2, 8.0, 2.5, 0.25, 3.0, 5.0, 'WARNING')
        """)

    # Indexes for fast lookup
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_weekly_assess_sessions_student
    ON weekly_assessment_sessions(student_id, module_id)
    """)
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_weekly_assess_sessions_course
    ON weekly_assessment_sessions(course_id, week_number)
    """)
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_weekly_assess_events_session
    ON weekly_assessment_events(session_id)
    """)

    conn.commit()
    conn.close()
    print("✓ Live Weekly Assessment migrations successfully applied.")


if __name__ == "__main__":
    run_weekly_assessment_migrations()
