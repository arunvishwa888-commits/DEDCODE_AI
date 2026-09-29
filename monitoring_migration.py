"""
DEDCODE Career Track — Assessment Monitoring Tables Migration
Creates monitoring_sessions and monitoring_events tables.
Fully additive — no existing tables are modified.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "learndebt.db")


def run_monitoring_migrations():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # ── 1. Monitoring Sessions ──────────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS monitoring_sessions (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id          INTEGER NOT NULL,
        enrollment_id       INTEGER NOT NULL,
        course_id           INTEGER NOT NULL,
        camera_permission   TEXT    DEFAULT 'UNKNOWN',   -- GRANTED | DENIED | UNKNOWN
        status              TEXT    DEFAULT 'ACTIVE',    -- ACTIVE | COMPLETED | INTERRUPTED | CANCELLED
        started_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
        ended_at            DATETIME,
        summary_json        TEXT,                        -- cached MonitoringSummary after completion
        created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (student_id)   REFERENCES users(id),
        FOREIGN KEY (enrollment_id) REFERENCES career_track_enrollments(id),
        FOREIGN KEY (course_id)    REFERENCES courses(id)
    )
    """)

    # ── 2. Monitoring Events ────────────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS monitoring_events (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id       INTEGER NOT NULL,
        event_type       TEXT    NOT NULL,
        timestamp        DATETIME NOT NULL,
        duration_seconds REAL    DEFAULT 0.0,
        metadata_json    TEXT,
        created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES monitoring_sessions(id)
    )
    """)

    # Index for fast session lookup
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_monitoring_events_session
    ON monitoring_events(session_id)
    """)
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_monitoring_sessions_student
    ON monitoring_sessions(student_id)
    """)

    conn.commit()
    conn.close()
    print("✓ Monitoring migrations successfully applied.")


if __name__ == "__main__":
    run_monitoring_migrations()
