import sqlite3
import os
import hashlib

DB_PATH = os.path.join(os.path.dirname(__file__), "learndebt.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Users (STUDENT and ADMIN roles)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT,
        name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'STUDENT', -- STUDENT or ADMIN
        streak_days INTEGER DEFAULT 0,
        last_login_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        auth_provider TEXT DEFAULT 'EMAIL',
        provider_user_id TEXT,
        profile_image TEXT
    )
    """)

    # Ensure missing columns in users table are added safely for existing SQLite DBs
    cursor.execute("PRAGMA table_info(users)")
    usr_cols = [row[1] for row in cursor.fetchall()]
    if "auth_provider" not in usr_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN auth_provider TEXT DEFAULT 'EMAIL'")
    if "provider_user_id" not in usr_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN provider_user_id TEXT")
    if "profile_image" not in usr_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN profile_image TEXT")
    if "credit_balance" not in usr_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN credit_balance INTEGER DEFAULT 0")

    # 2. Subscriptions (One primary active subscription per user)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE NOT NULL,
        plan_name TEXT NOT NULL DEFAULT 'Individual Learning',
        billing_cycle TEXT NOT NULL DEFAULT 'Monthly',
        price_inr INTEGER DEFAULT 499,
        status TEXT DEFAULT 'ACTIVE', -- ACTIVE, EXPIRED, CANCELLED
        start_date DATETIME DEFAULT CURRENT_TIMESTAMP,
        end_date DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    # 2b. Student Learning Profile (Personalized Onboarding & Recommendation Engine)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS student_learning_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE NOT NULL,
        course_interests_json TEXT DEFAULT '[]',
        skills_json TEXT DEFAULT '[]',
        primary_career TEXT,
        secondary_careers_json TEXT DEFAULT '[]',
        coding_languages_json TEXT DEFAULT '[]',
        experience_level TEXT DEFAULT 'Beginner',
        learning_preferences_json TEXT DEFAULT '[]',
        learning_goal TEXT,
        onboarding_completed INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    # 3. Courses (Applied ML, Data Science, FDE, Python)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        category TEXT DEFAULT 'Software Engineering',
        difficulty TEXT DEFAULT 'Intermediate',
        level TEXT DEFAULT 'Intermediate',
        duration TEXT DEFAULT '12 Weeks',
        thumbnail_url TEXT,
        status TEXT DEFAULT 'PUBLISHED',
        is_published INTEGER DEFAULT 1,
        learning_outcomes_json TEXT,
        skills_covered_json TEXT DEFAULT '[]',
        career_paths_json TEXT DEFAULT '[]',
        prerequisites_json TEXT DEFAULT '[]',
        recommended_before_json TEXT DEFAULT '[]',
        recommended_after_json TEXT DEFAULT '[]',
        coding_languages_json TEXT DEFAULT '[]',
        estimated_duration TEXT DEFAULT '12 Weeks',
        price_inr INTEGER DEFAULT 2000,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Ensure missing columns in courses table are added safely for existing SQLite DBs
    cursor.execute("PRAGMA table_info(courses)")
    existing_cols = [row[1] for row in cursor.fetchall()]
    if "category" not in existing_cols:
        cursor.execute("ALTER TABLE courses ADD COLUMN category TEXT DEFAULT 'Software Engineering'")
    if "difficulty" not in existing_cols:
        cursor.execute("ALTER TABLE courses ADD COLUMN difficulty TEXT DEFAULT 'Intermediate'")
    if "status" not in existing_cols:
        cursor.execute("ALTER TABLE courses ADD COLUMN status TEXT DEFAULT 'PUBLISHED'")
    if "created_at" not in existing_cols:
        cursor.execute("ALTER TABLE courses ADD COLUMN created_at DATETIME")
    if "updated_at" not in existing_cols:
        cursor.execute("ALTER TABLE courses ADD COLUMN updated_at DATETIME")
    if "skills_covered_json" not in existing_cols:
        cursor.execute("ALTER TABLE courses ADD COLUMN skills_covered_json TEXT DEFAULT '[]'")
    if "career_paths_json" not in existing_cols:
        cursor.execute("ALTER TABLE courses ADD COLUMN career_paths_json TEXT DEFAULT '[]'")
    if "prerequisites_json" not in existing_cols:
        cursor.execute("ALTER TABLE courses ADD COLUMN prerequisites_json TEXT DEFAULT '[]'")
    if "recommended_before_json" not in existing_cols:
        cursor.execute("ALTER TABLE courses ADD COLUMN recommended_before_json TEXT DEFAULT '[]'")
    if "recommended_after_json" not in existing_cols:
        cursor.execute("ALTER TABLE courses ADD COLUMN recommended_after_json TEXT DEFAULT '[]'")
    if "coding_languages_json" not in existing_cols:
        cursor.execute("ALTER TABLE courses ADD COLUMN coding_languages_json TEXT DEFAULT '[]'")
    if "estimated_duration" not in existing_cols:
        cursor.execute("ALTER TABLE courses ADD COLUMN estimated_duration TEXT DEFAULT '12 Weeks'")
    if "price_inr" not in existing_cols:
        cursor.execute("ALTER TABLE courses ADD COLUMN price_inr INTEGER DEFAULT 2000")

    # 3b. Credit Transactions Ledger
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS credit_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        module_id INTEGER,
        course_id INTEGER,
        amount INTEGER NOT NULL,
        type TEXT NOT NULL, -- 'MODULE_COMPLETION', 'COURSE_REDEMPTION', 'ADMIN_ADJUSTMENT', 'REFUND_REVERSAL'
        description TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (module_id) REFERENCES modules(id),
        FOREIGN KEY (course_id) REFERENCES courses(id)
    )
    """)

    cursor.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_credit_module_reward
    ON credit_transactions(user_id, module_id)
    WHERE type = 'MODULE_COMPLETION'
    """)

    # 4. Enrollments (Links Students to Courses & Subscription)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS enrollments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL,
        subscription_id INTEGER,
        enrolled_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        progress_pct INTEGER DEFAULT 0,
        status TEXT DEFAULT 'ACTIVE', -- ACTIVE, COMPLETED, CANCELLED
        last_accessed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        completed_at DATETIME,
        UNIQUE(user_id, course_id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (course_id) REFERENCES courses(id),
        FOREIGN KEY (subscription_id) REFERENCES subscriptions(id)
    )
    """)

    # Ensure completed_at column exists in enrollments
    cursor.execute("PRAGMA table_info(enrollments)")
    enr_cols = [row[1] for row in cursor.fetchall()]
    if "completed_at" not in enr_cols:
        cursor.execute("ALTER TABLE enrollments ADD COLUMN completed_at DATETIME")

    # 5. Modules
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS modules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        slug TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        order_index INTEGER DEFAULT 1,
        is_unlocked INTEGER DEFAULT 0,
        key_concepts_json TEXT DEFAULT '[]',
        content TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(course_id, order_index),
        FOREIGN KEY (course_id) REFERENCES courses(id)
    )
    """)

    cursor.execute("PRAGMA table_info(modules)")
    mod_cols = [row[1] for row in cursor.fetchall()]
    if "key_concepts_json" not in mod_cols:
        cursor.execute("ALTER TABLE modules ADD COLUMN key_concepts_json TEXT DEFAULT '[]'")
    if "content" not in mod_cols:
        cursor.execute("ALTER TABLE modules ADD COLUMN content TEXT")
    if "created_at" not in mod_cols:
        cursor.execute("ALTER TABLE modules ADD COLUMN created_at DATETIME")
    if "updated_at" not in mod_cols:
        cursor.execute("ALTER TABLE modules ADD COLUMN updated_at DATETIME")

    # 6. Videos (AI-Generated Educational Videos — Strictly 1 Active Published Video per Module)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        module_id INTEGER UNIQUE NOT NULL,
        title TEXT NOT NULL,
        provider TEXT DEFAULT 'ai-video-studio',
        video_id TEXT NOT NULL,
        video_url TEXT NOT NULL,
        embed_url TEXT NOT NULL,
        professor TEXT DEFAULT 'AI Learning Tutor',
        institution TEXT DEFAULT 'DEDCODE Platform',
        source TEXT DEFAULT 'AI Video Studio',
        duration TEXT DEFAULT '05:00',
        transcript TEXT NOT NULL,
        is_embeddable INTEGER DEFAULT 1,
        video_file_path TEXT,
        subtitle_file_path TEXT,
        status TEXT DEFAULT 'PUBLISHED',
        generation_provider TEXT DEFAULT 'ai-video-studio',
        script_json TEXT,
        published_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (module_id) REFERENCES modules(id)
    )
    """)

    # Ensure missing AI video columns are added safely for existing SQLite DBs
    cursor.execute("PRAGMA table_info(videos)")
    vid_cols = [row[1] for row in cursor.fetchall()]
    if "video_file_path" not in vid_cols:
        cursor.execute("ALTER TABLE videos ADD COLUMN video_file_path TEXT")
    if "subtitle_file_path" not in vid_cols:
        cursor.execute("ALTER TABLE videos ADD COLUMN subtitle_file_path TEXT")
    if "status" not in vid_cols:
        cursor.execute("ALTER TABLE videos ADD COLUMN status TEXT DEFAULT 'PUBLISHED'")
    if "generation_provider" not in vid_cols:
        cursor.execute("ALTER TABLE videos ADD COLUMN generation_provider TEXT DEFAULT 'ai-video-studio'")
    if "script_json" not in vid_cols:
        cursor.execute("ALTER TABLE videos ADD COLUMN script_json TEXT")
    if "published_at" not in vid_cols:
        cursor.execute("ALTER TABLE videos ADD COLUMN published_at DATETIME")

    # 6b. AI Video Jobs (Track asynchronous generation status and stage progress)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_video_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        module_id INTEGER NOT NULL,
        version_id INTEGER,
        status TEXT DEFAULT 'PENDING', -- PENDING, IN_PROGRESS, COMPLETED, FAILED
        current_stage TEXT DEFAULT 'Preparing module...',
        progress_pct INTEGER DEFAULT 0,
        error_message TEXT,
        created_by_user_id INTEGER NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (module_id) REFERENCES modules(id),
        FOREIGN KEY (created_by_user_id) REFERENCES users(id)
    )
    """)

    # 6c. AI Video Versions (Stores generated draft and historical versions)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_video_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        module_id INTEGER NOT NULL,
        version_number INTEGER DEFAULT 1,
        video_file_path TEXT NOT NULL,
        subtitle_file_path TEXT,
        duration_seconds INTEGER DEFAULT 0,
        script_json TEXT NOT NULL,
        status TEXT DEFAULT 'DRAFT', -- DRAFT, PUBLISHED, SUPERSEDED
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (module_id) REFERENCES modules(id)
    )
    """)

    # 7. Assessments
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS assessments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        module_id INTEGER NOT NULL,
        questions_json TEXT NOT NULL,
        FOREIGN KEY (module_id) REFERENCES modules(id)
    )
    """)

    # 8. Learning Progress (Module-level completion & scores)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS learning_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL,
        module_id INTEGER NOT NULL,
        completed INTEGER DEFAULT 0,
        score INTEGER DEFAULT 0,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, module_id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (course_id) REFERENCES courses(id),
        FOREIGN KEY (module_id) REFERENCES modules(id)
    )
    """)

    # 9. Learning Debt
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS learning_debt (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL,
        concept_name TEXT NOT NULL,
        mastery_pct INTEGER DEFAULT 50,
        learning_debt_pct INTEGER DEFAULT 50,
        reason TEXT NOT NULL,
        status TEXT DEFAULT 'Unresolved',
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, course_id, concept_name),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (course_id) REFERENCES courses(id)
    )
    """)

    # 10. Projects (Project-based progression mapped to 2-module pairs)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        project_number INTEGER DEFAULT 1,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        objective TEXT,
        what_to_build TEXT,
        concepts_used_json TEXT,
        requirements_json TEXT NOT NULL,
        tasks_json TEXT,
        expected_output TEXT,
        test_cases_json TEXT,
        hints_json TEXT,
        starter_code TEXT NOT NULL,
        is_final INTEGER DEFAULT 0,
        prereq_module_index_1 INTEGER DEFAULT 1,
        prereq_module_index_2 INTEGER DEFAULT 2,
        builds_on_project_id INTEGER,
        unlocked_after_module_index INTEGER DEFAULT 2,
        FOREIGN KEY (course_id) REFERENCES courses(id),
        FOREIGN KEY (builds_on_project_id) REFERENCES projects(id)
    )
    """)

    # 11. Project Progress
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS project_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        project_id INTEGER NOT NULL,
        status TEXT DEFAULT 'Unlocked',
        code TEXT,
        score INTEGER DEFAULT 0,
        ai_feedback TEXT,
        test_results_json TEXT,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, project_id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )
    """)

    # 12. Chat Messages
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        module_id INTEGER NOT NULL,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        sources_json TEXT,
        language TEXT DEFAULT 'English',
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (module_id) REFERENCES modules(id)
    )
    """)

    # 13. Behavior Events
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS behavior_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        module_id INTEGER,
        event_type TEXT NOT NULL,
        metadata_json TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 14. Activity Logs (Real Activity Log for Students)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS activity_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        action_type TEXT NOT NULL,
        description TEXT NOT NULL,
        metadata_json TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    cursor.execute("PRAGMA table_info(activity_logs)")
    act_cols = [row[1] for row in cursor.fetchall()]
    if "metadata_json" not in act_cols:
        cursor.execute("ALTER TABLE activity_logs ADD COLUMN metadata_json TEXT")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS mentor_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mentor_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL,
        status TEXT DEFAULT 'ACTIVE',
        assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        notes TEXT,
        FOREIGN KEY (mentor_id) REFERENCES users(id),
        FOREIGN KEY (student_id) REFERENCES users(id),
        FOREIGN KEY (course_id) REFERENCES courses(id),
        UNIQUE(mentor_id, student_id, course_id)
    )
    """)

    # 15. Innovation Booster Proposals
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS innovation_proposals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        track TEXT NOT NULL,
        problem_statement TEXT NOT NULL,
        proposed_solution TEXT NOT NULL,
        target_market TEXT,
        tech_stack_json TEXT DEFAULT '[]',
        status TEXT DEFAULT 'SUBMITTED', -- SUBMITTED, INCUBATING, ACCELERATED, FUNDED
        ai_feasibility_score REAL DEFAULT 85.0,
        booster_credits_awarded INTEGER DEFAULT 100,
        milestones_json TEXT DEFAULT '[]',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    # 16. Manual UPI / GPay Payment Requests
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payment_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        plan_id TEXT NOT NULL,
        plan_name TEXT NOT NULL,
        plan_amount INTEGER NOT NULL,
        billing_cycle TEXT DEFAULT 'Monthly',
        utr_number TEXT NOT NULL,
        screenshot_path TEXT NOT NULL,
        status TEXT DEFAULT 'PENDING', -- PENDING, APPROVED, REJECTED
        submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        verified_at DATETIME,
        verified_by INTEGER,
        rejection_reason TEXT,
        admin_notes TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (verified_by) REFERENCES users(id)
    )
    """)

    # 17. Institution / Campus Enquiries
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS institution_enquiries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        institution_name TEXT NOT NULL,
        contact_person TEXT NOT NULL,
        official_email TEXT NOT NULL,
        phone TEXT NOT NULL,
        student_count TEXT,
        requirement TEXT NOT NULL,
        status TEXT DEFAULT 'NEW', -- NEW, CONTACTED, CLOSED
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    # 18. Payment Audit Logs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payment_audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_request_id INTEGER,
        user_id INTEGER NOT NULL,
        actor_id INTEGER NOT NULL,
        action TEXT NOT NULL, -- PAYMENT_SUBMITTED, PAYMENT_APPROVED, PAYMENT_REJECTED, PAYMENT_RESUBMITTED, SUBSCRIPTION_ACTIVATED
        details TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (payment_request_id) REFERENCES payment_requests(id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (actor_id) REFERENCES users(id)
    )
    """)

    # Seed default Admin, Student, and Mentor users if not present
    cursor.execute("SELECT id FROM users WHERE email = 'admin@dedcode.ai'")
    if not cursor.fetchone():
        admin_pw_hash = hashlib.sha256("admin123".encode()).hexdigest()
        cursor.execute("""
        INSERT INTO users (email, password_hash, name, role, streak_days, auth_provider)
        VALUES ('admin@dedcode.ai', ?, 'DEDCODE Admin', 'ADMIN', 0, 'EMAIL')
        """, (admin_pw_hash,))

    cursor.execute("SELECT id FROM users WHERE email = 'yogesh@dedcode.ai'")
    if not cursor.fetchone():
        student_pw_hash = hashlib.sha256("password123".encode()).hexdigest()
        cursor.execute("""
        INSERT INTO users (email, password_hash, name, role, streak_days, auth_provider)
        VALUES ('yogesh@dedcode.ai', ?, 'Yogesh Kumar', 'STUDENT', 5, 'EMAIL')
        """, (student_pw_hash,))
        y_id = cursor.lastrowid
        cursor.execute("""
        INSERT INTO subscriptions (user_id, plan_name, billing_cycle, price_inr, status)
        VALUES (?, 'Individual Learning', 'Monthly', 499, 'ACTIVE')
        ON CONFLICT(user_id) DO NOTHING
        """, (y_id,))

    cursor.execute("SELECT id FROM users WHERE email = 'mentor@dedcode.ai'")
    mentor_row = cursor.fetchone()
    if not mentor_row:
        mentor_pw_hash = hashlib.sha256("mentor123".encode()).hexdigest()
        cursor.execute("""
        INSERT INTO users (email, password_hash, name, role, streak_days, auth_provider)
        VALUES ('mentor@dedcode.ai', ?, 'Marcus Vance (Lead Mentor)', 'INSTRUCTOR', 12, 'EMAIL')
        """, (mentor_pw_hash,))
        m_id = cursor.lastrowid
    else:
        m_id = mentor_row[0]

    # Assign mentor to student Yogesh in course 1
    cursor.execute("SELECT id FROM users WHERE email = 'yogesh@dedcode.ai'")
    y_row = cursor.fetchone()
    if y_row and m_id:
        cursor.execute("""
        INSERT INTO mentor_assignments (mentor_id, student_id, course_id, status, notes)
        VALUES (?, ?, 1, 'ACTIVE', 'Primary mentor assigned for Applied Machine Learning capstone track.')
        ON CONFLICT(mentor_id, student_id, course_id) DO NOTHING
        """, (m_id, y_row[0]))

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized with strict relational constraints and subscriptions table.")

