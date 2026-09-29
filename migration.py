import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "learndebt.db")

def run_recommendation_migrations():
    """
    Creates all Section 18 recommendation engine tables safely.
    Guaranteed not to modify, rename, or drop any existing tables.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Master Skills Taxonomy
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rec_skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        category TEXT NOT NULL, -- 'Core AI/ML', 'Data Engineering', 'Systems Architecture', 'Software Design', 'Mathematics & Statistics'
        description TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 2. Course Skills & Prerequisite Graph Mapping
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rec_course_skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        skill_id INTEGER NOT NULL,
        proficiency_gain INTEGER DEFAULT 25, -- Proficiency points added upon course mastery (0-100)
        is_prerequisite INTEGER DEFAULT 0, -- 1 if this skill is required BEFORE taking the course
        required_min_proficiency INTEGER DEFAULT 50,
        FOREIGN KEY (course_id) REFERENCES courses(id),
        FOREIGN KEY (skill_id) REFERENCES rec_skills(id),
        UNIQUE(course_id, skill_id, is_prerequisite)
    )
    """)

    # 3. Student Verified Skills Matrix
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rec_user_skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        skill_id INTEGER NOT NULL,
        proficiency_pct REAL DEFAULT 0.0, -- 0 to 100
        confidence_score REAL DEFAULT 0.8,
        source TEXT DEFAULT 'COURSE_QUIZ', -- 'COURSE_QUIZ', 'PROJECT_EVAL', 'INTERVIEW', 'ONBOARDING'
        last_evaluated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (skill_id) REFERENCES rec_skills(id),
        UNIQUE(user_id, skill_id)
    )
    """)

    # 4. Target Career Role Profiles & Requirements
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rec_career_roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT UNIQUE NOT NULL,
        role_name TEXT NOT NULL,
        category TEXT NOT NULL,
        description TEXT NOT NULL,
        required_skills_json TEXT NOT NULL, -- List of {skill_slug, target_proficiency (default 70%), weight}
        target_proficiency_pct INTEGER DEFAULT 70,
        is_active INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 5. Configurable Real Job Market Trends
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rec_job_market_trends (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role_slug TEXT UNIQUE NOT NULL,
        role_title TEXT NOT NULL,
        growth_rate_pct REAL DEFAULT 24.5,
        active_postings_count INTEGER DEFAULT 18450,
        avg_salary_range TEXT DEFAULT '$135,000 – $185,000 / ₹18L – ₹35L',
        top_demanded_skills_json TEXT DEFAULT '[]',
        market_demand_level TEXT DEFAULT 'VERY HIGH', -- 'VERY HIGH', 'HIGH', 'MODERATE', 'STABLE'
        source_api_or_agency TEXT DEFAULT 'National Labor Analytics & Tech Hiring Index 2026',
        last_updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        is_connected INTEGER DEFAULT 1 -- 1 if active telemetry is connected, 0 for disconnected state
    )
    """)

    # 6. Curated External & Platform Certificate Options (Admin-Editable)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rec_external_certificates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        provider_type TEXT NOT NULL, -- 'PLATFORM' (Career Track) or 'EXTERNAL'
        provider_name TEXT NOT NULL, -- 'DEDCODE', 'AWS', 'Google Cloud', 'DeepLearning.AI', 'Linux Foundation'
        difficulty TEXT DEFAULT 'Intermediate',
        estimated_hours INTEGER DEFAULT 40,
        official_url TEXT NOT NULL,
        badge_image_url TEXT,
        skills_covered_json TEXT DEFAULT '[]',
        career_paths_json TEXT DEFAULT '[]',
        cost_info TEXT DEFAULT 'Included with Subscription / Free to Audit',
        disclaimer_text TEXT DEFAULT 'Certifications validate specialized technical competency. Employment outcomes depend on overall portfolio and interview performance.',
        is_active INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 7. Computed Active Recommendations
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rec_recommendations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        rec_type TEXT NOT NULL, -- 'NEXT_COURSE', 'CONTINUE_LEARNING', 'SKILL_DEVELOPMENT', 'PROJECT', 'CERTIFICATE'
        item_id TEXT NOT NULL,
        item_title TEXT NOT NULL,
        item_slug TEXT,
        score REAL NOT NULL, -- 0 to 100 ranking score
        rank_order INTEGER DEFAULT 1,
        reason_headline TEXT NOT NULL,
        reason_explanation TEXT NOT NULL,
        metadata_json TEXT DEFAULT '{}',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    # 8. Recommendation History Snapshots Audit Log
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rec_recommendation_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        trigger_event TEXT NOT NULL, -- 'COURSE_COMPLETED', 'QUIZ_SUBMITTED', 'PROJECT_EVALUATED', 'INTERVIEW_COMPLETED', 'PROFILE_UPDATED', 'MANUAL_REFRESH'
        snapshot_json TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    conn.commit()
    conn.close()
    print("✓ Section 18 Recommendation Engine migrations successfully applied.")

if __name__ == "__main__":
    run_recommendation_migrations()
