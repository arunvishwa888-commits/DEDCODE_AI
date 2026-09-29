import sqlite3
import os
import json
import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "learndebt.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

class RecommendationEngine:
    """
    AI-Powered Recommendation & Skill Graph Traversal Engine.
    Implements prerequisite filtering, skill-gap detection against 70% career benchmark,
    multi-factor ranking, and human-readable 'Why am I seeing this?' rationales.
    """

    @classmethod
    def sync_user_skills_from_platform_data(cls, user_id):
        """
        Aggregates quiz scores, capstone project 50/50 evaluations, and Career Track interview scores
        to update rec_user_skills. Read-only access to existing tables.
        """
        conn = get_db()
        cursor = conn.cursor()

        # 1. Fetch Course Module Quiz Mastery
        cursor.execute("""
        SELECT c.slug as course_slug, AVG(lp.score) as avg_score, COUNT(lp.id) as completed_count
        FROM learning_progress lp
        JOIN courses c ON lp.course_id = c.id
        WHERE lp.user_id = ? AND lp.completed = 1
        GROUP BY c.slug
        """, (user_id,))
        course_scores = {row["course_slug"]: {"score": float(row["avg_score"] or 0), "count": row["completed_count"]} for row in cursor.fetchall()}

        # 2. Fetch Career Track Project Submissions (50/50 AI + Mentor)
        cursor.execute("""
        SELECT c.slug as course_slug, ps.final_score, ps.ai_score, ps.mentor_score
        FROM career_track_project_submissions ps
        JOIN courses c ON ps.course_id = c.id
        WHERE ps.user_id = ? AND ps.passed = 1
        """, (user_id,))
        project_scores = {row["course_slug"]: float(row["final_score"] or 0) for row in cursor.fetchall()}

        # 3. Fetch Career Track Interview Scores
        cursor.execute("""
        SELECT c.slug as course_slug, i.overall_interview_score, i.technical_score, i.problem_solving_score, i.system_design_score
        FROM career_track_interviews i
        JOIN courses c ON i.course_id = c.id
        WHERE i.user_id = ? AND i.passed = 1
        """, (user_id,))
        interview_scores = {row["course_slug"]: float(row["overall_interview_score"] or 0) for row in cursor.fetchall()}

        # 4. Map back to skills
        cursor.execute("SELECT id, slug FROM rec_skills")
        all_skills = {row["slug"]: row["id"] for row in cursor.fetchall()}

        # Compute skill proficiencies based on multi-source evidence
        computed_skills = {}

        # Python Skills
        if "python" in course_scores:
            q = course_scores["python"]["score"]
            computed_skills["python-core"] = max(computed_skills.get("python-core", 0), q * 0.95)
            computed_skills["asyncio-concurrency"] = max(computed_skills.get("asyncio-concurrency", 0), q * 0.85)
            computed_skills["test-driven-development"] = max(computed_skills.get("test-driven-development", 0), q * 0.88)

        # Data Science Skills
        if "data-science" in course_scores:
            q = course_scores["data-science"]["score"]
            computed_skills["pandas-eda"] = max(computed_skills.get("pandas-eda", 0), q * 0.92)
            computed_skills["sql-data-modeling"] = max(computed_skills.get("sql-data-modeling", 0), q * 0.90)
            computed_skills["ab-testing-stats"] = max(computed_skills.get("ab-testing-stats", 0), q * 0.88)

        # Applied Machine Learning Skills
        if "applied-machine-learning" in course_scores:
            q = course_scores["applied-machine-learning"]["score"]
            computed_skills["numpy-vectorization"] = max(computed_skills.get("numpy-vectorization", 0), q * 0.95)
            computed_skills["scikit-learn-modeling"] = max(computed_skills.get("scikit-learn-modeling", 0), q * 0.92)
            computed_skills["vector-search-embeddings"] = max(computed_skills.get("vector-search-embeddings", 0), q * 0.90)
            computed_skills["mlops-model-serving"] = max(computed_skills.get("mlops-model-serving", 0), q * 0.85)

        # Boost from Project 50/50 Reviews
        for c_slug, p_score in project_scores.items():
            if c_slug == "applied-machine-learning":
                computed_skills["vector-search-embeddings"] = min(100.0, max(computed_skills.get("vector-search-embeddings", 0), p_score))
                computed_skills["mlops-model-serving"] = min(100.0, max(computed_skills.get("mlops-model-serving", 0), p_score * 0.95))
            elif c_slug == "forward-deployed-engineering":
                computed_skills["distributed-systems"] = min(100.0, max(computed_skills.get("distributed-systems", 0), p_score))
                computed_skills["api-security-microservices"] = min(100.0, max(computed_skills.get("api-security-microservices", 0), p_score))

        # Boost from Technical Interviews
        for c_slug, i_score in interview_scores.items():
            if c_slug == "applied-machine-learning":
                computed_skills["vector-search-embeddings"] = min(100.0, max(computed_skills.get("vector-search-embeddings", 0), i_score))
            elif c_slug == "data-science":
                computed_skills["ab-testing-stats"] = min(100.0, max(computed_skills.get("ab-testing-stats", 0), i_score))

        # Save to rec_user_skills
        for slug, prof in computed_skills.items():
            if slug in all_skills:
                skill_id = all_skills[slug]
                cursor.execute("""
                INSERT INTO rec_user_skills (user_id, skill_id, proficiency_pct, confidence_score, source, last_evaluated_at)
                VALUES (?, ?, ?, 0.9, 'PLATFORM_EVAL', CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, skill_id) DO UPDATE SET
                    proficiency_pct = excluded.proficiency_pct,
                    last_evaluated_at = CURRENT_TIMESTAMP
                """, (user_id, skill_id, round(prof, 1)))

        conn.commit()
        conn.close()

    @classmethod
    def get_user_target_career_role(cls, user_id):
        """
        Resolves target career role from student profile or default Machine Learning Engineer.
        """
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT primary_career FROM student_learning_profiles WHERE user_id = ?", (user_id,))
        profile = cursor.fetchone()
        role_slug = "machine-learning-engineer"

        if profile and profile["primary_career"]:
            p_str = profile["primary_career"].lower()
            if "data" in p_str:
                role_slug = "data-scientist"
            elif "forward" in p_str or "deploy" in p_str:
                role_slug = "forward-deployed-engineer"
            elif "architect" in p_str:
                role_slug = "ai-systems-architect"

        cursor.execute("SELECT * FROM rec_career_roles WHERE slug = ?", (role_slug,))
        role_row = cursor.fetchone()
        conn.close()

        if not role_row:
            return {
                "id": 1,
                "slug": "machine-learning-engineer",
                "role_name": "Machine Learning Engineer",
                "category": "AI & Applied Systems",
                "description": "Builds and deploys high-performance predictive systems.",
                "required_skills": [
                    {"slug": "python-core", "weight": 0.20, "target_proficiency": 70},
                    {"slug": "numpy-vectorization", "weight": 0.20, "target_proficiency": 70},
                    {"slug": "scikit-learn-modeling", "weight": 0.25, "target_proficiency": 70},
                    {"slug": "vector-search-embeddings", "weight": 0.20, "target_proficiency": 70},
                    {"slug": "mlops-model-serving", "weight": 0.15, "target_proficiency": 70}
                ]
            }

        role_data = dict(role_row)
        role_data["required_skills"] = json.loads(role_data["required_skills_json"])
        return role_data

    @classmethod
    def compute_and_save_recommendations(cls, user_id, trigger_event="MANUAL_REFRESH"):
        """
        Full recommendation computation pipeline:
        1. Synchronizes skill evidence from quizzes, projects, and interviews
        2. Evaluates prerequisite graph
        3. Identifies skill gaps against target role (70% benchmark)
        4. Ranks candidate next courses, active courses, projects, skills to develop, and certificates
        5. Saves to rec_recommendations and records immutable history snapshot
        """
        cls.sync_user_skills_from_platform_data(user_id)
        target_role = cls.get_user_target_career_role(user_id)

        conn = get_db()
        cursor = conn.cursor()

        # Fetch current user skill map
        cursor.execute("""
        SELECT s.slug, s.name, s.category, us.proficiency_pct
        FROM rec_skills s
        LEFT JOIN rec_user_skills us ON s.id = us.skill_id AND us.user_id = ?
        """, (user_id,))
        user_skills = {row["slug"]: {"name": row["name"], "category": row["category"], "proficiency": float(row["proficiency_pct"] or 0.0)} for row in cursor.fetchall()}

        # Fetch Career Track project submissions and interview scores
        cursor.execute("""
        SELECT c.slug as course_slug, ps.final_score
        FROM career_track_project_submissions ps
        JOIN courses c ON ps.course_id = c.id
        WHERE ps.user_id = ? AND ps.passed = 1
        """, (user_id,))
        project_scores = {row["course_slug"]: float(row["final_score"] or 0) for row in cursor.fetchall()}

        cursor.execute("""
        SELECT c.slug as course_slug, i.overall_interview_score
        FROM career_track_interviews i
        JOIN courses c ON i.course_id = c.id
        WHERE i.user_id = ? AND i.passed = 1
        """, (user_id,))
        interview_scores = {row["course_slug"]: float(row["overall_interview_score"] or 0) for row in cursor.fetchall()}

        # Fetch courses & modules completion
        cursor.execute("SELECT id, slug, title, description, category, level, duration FROM courses WHERE status = 'PUBLISHED'")
        courses = [dict(c) for c in cursor.fetchall()]

        # Course completion stats
        course_status = {}
        for c in courses:
            c_id = c["id"]
            cursor.execute("SELECT COUNT(*) as total FROM modules WHERE course_id = ?", (c_id,))
            total_m = cursor.fetchone()["total"] or 0

            cursor.execute("SELECT COUNT(*) as done, AVG(score) as avg_score FROM learning_progress WHERE user_id = ? AND course_id = ? AND completed = 1", (user_id, c_id))
            prog = cursor.fetchone()
            done_m = prog["done"] if prog else 0
            avg_score = float(prog["avg_score"] or 0.0) if prog else 0.0

            is_completed = (done_m >= total_m and total_m > 0)
            is_in_progress = (done_m > 0 and done_m < total_m)
            progress_pct = int((done_m / max(1, total_m)) * 100)

            # Check enrolled status
            cursor.execute("SELECT id FROM enrollments WHERE user_id = ? AND course_id = ?", (user_id, c_id))
            is_enrolled = cursor.fetchone() is not None

            # Check next module in progress
            cursor.execute("""
            SELECT m.title FROM modules m
            LEFT JOIN learning_progress lp ON m.id = lp.module_id AND lp.user_id = ? AND lp.completed = 1
            WHERE m.course_id = ? AND lp.id IS NULL
            ORDER BY m.order_index ASC LIMIT 1
            """, (user_id, c_id))
            next_mod = cursor.fetchone()
            next_mod_title = next_mod["title"] if next_mod else "Capstone Review"

            # Check prerequisites
            cursor.execute("""
            SELECT s.slug, cs.required_min_proficiency
            FROM rec_course_skills cs
            JOIN rec_skills s ON cs.skill_id = s.id
            WHERE cs.course_id = ? AND cs.is_prerequisite = 1
            """, (c_id,))
            prereqs = cursor.fetchall()
            prereq_satisfied = True
            missing_prereqs = []
            for p in prereqs:
                p_slug = p["slug"]
                min_p = p["required_min_proficiency"]
                user_p = user_skills.get(p_slug, {}).get("proficiency", 0.0)
                if user_p < min_p:
                    prereq_satisfied = False
                    missing_prereqs.append(p_slug)

            # Skills gained by this course
            cursor.execute("""
            SELECT s.name FROM rec_course_skills cs
            JOIN rec_skills s ON cs.skill_id = s.id
            WHERE cs.course_id = ? AND cs.is_prerequisite = 0
            """, (c_id,))
            skills_gained = [row["name"] for row in cursor.fetchall()]

            course_status[c_id] = {
                "course": c,
                "total_modules": total_m,
                "completed_modules": done_m,
                "progress_pct": progress_pct,
                "is_completed": is_completed,
                "is_in_progress": is_in_progress,
                "is_enrolled": is_enrolled,
                "next_module_title": next_mod_title,
                "avg_score": avg_score,
                "prereq_satisfied": prereq_satisfied,
                "missing_prereqs": missing_prereqs,
                "skills_gained": skills_gained
            }

        # -------------------------------------------------------------
        # 1. GENERATE RECOMMENDED NEXT COURSE
        # -------------------------------------------------------------
        candidate_courses = []
        for c_id, st in course_status.items():
            if st["is_completed"]:
                continue # Never recommend already completed courses as next new course
            if not st["prereq_satisfied"]:
                continue # Prerequisite graph enforcement: never recommend courses with incomplete prerequisites

            c = st["course"]
            # Compute match score based on target career role alignment and skill gains
            cursor.execute("""
            SELECT s.slug, cs.proficiency_gain
            FROM rec_course_skills cs
            JOIN rec_skills s ON cs.skill_id = s.id
            WHERE cs.course_id = ? AND cs.is_prerequisite = 0
            """, (c_id,))
            gains = cursor.fetchall()

            role_relevance_points = 0.0
            gap_closed_points = 0.0
            reasons = []

            for g in gains:
                s_slug = g["slug"]
                curr_prof = user_skills.get(s_slug, {}).get("proficiency", 0.0)
                gap = max(0.0, 70.0 - curr_prof)
                # Check if this skill is in target career role
                role_match = next((item for item in target_role["required_skills"] if item["slug"] == s_slug), None)
                if role_match:
                    role_relevance_points += (role_match["weight"] * 40.0)
                    if gap > 0:
                        gap_closed_points += min(30.0, gap * 0.5)
                        reasons.append(f"Closes your {int(gap)}% proficiency gap in {user_skills.get(s_slug, {}).get('name', s_slug)}")

            # Base readiness score
            base_readiness = 80.0 if st["prereq_satisfied"] else 40.0
            if st["is_in_progress"]:
                base_readiness += 10.0

            total_rec_score = round(min(99.0, max(60.0, base_readiness + role_relevance_points + gap_closed_points)), 1)
            
            headline = f"Optimal Next Step for {target_role['role_name']}"
            if reasons:
                explanation = f"Recommended because: (1) All prerequisites are 100% verified; (2) Directly {reasons[0]}; (3) Aligned with {target_role['role_name']} core competency."
            else:
                explanation = f"Recommended because you have unlocked all prerequisites and this builds foundational strength for {target_role['role_name']}."

            candidate_courses.append({
                "course_id": c_id,
                "title": c["title"],
                "slug": c["slug"],
                "description": c.get("description", ""),
                "score": total_rec_score,
                "match_score": int(round(total_rec_score)),
                "headline": headline,
                "explanation": explanation,
                "why_recommended": explanation,
                "progress_pct": st["progress_pct"],
                "is_in_progress": st["is_in_progress"],
                "is_enrolled": st["is_enrolled"],
                "category": c["category"],
                "duration": c["duration"],
                "estimated_hours": 16 if "16" in str(c["duration"]) else 14,
                "level": c["level"],
                "difficulty": c["level"],
                "prerequisites_met": st["prereq_satisfied"],
                "missing_prerequisites": st["missing_prereqs"],
                "skills_gained": st["skills_gained"]
            })

        candidate_courses.sort(key=lambda x: x["score"], reverse=True)

        # -------------------------------------------------------------
        # 2. GENERATE CONTINUE LEARNING
        # -------------------------------------------------------------
        continue_learning = []
        for c_id, st in course_status.items():
            if st["is_in_progress"]:
                c = st["course"]
                continue_learning.append({
                    "course_id": c_id,
                    "title": c["title"],
                    "slug": c["slug"],
                    "progress_pct": st["progress_pct"],
                    "completed_modules": st["completed_modules"],
                    "total_modules": st["total_modules"],
                    "next_module_title": st["next_module_title"],
                    "category": c["category"],
                    "difficulty": c["level"],
                    "headline": f"Resume {c['title']}",
                    "explanation": f"You're {st['progress_pct']}% complete ({st['completed_modules']}/{st['total_modules']} modules finished). Continue now to maintain your learning streak."
                })

        # -------------------------------------------------------------
        # 3. GENERATE SKILLS TO DEVELOP (vs 70% Target Benchmark)
        # -------------------------------------------------------------
        skills_to_develop = []
        for req in target_role["required_skills"]:
            s_slug = req["slug"]
            target_p = req.get("target_proficiency", 70)
            user_info = user_skills.get(s_slug, {"name": s_slug.replace('-', ' ').title(), "category": "Technical", "proficiency": 0.0})
            curr_p = user_info["proficiency"]
            gap = max(0.0, float(target_p) - curr_p)

            priority = "High" if gap >= 30 else ("Medium" if gap > 0 else "Mastered")
            
            # Find course that teaches this skill
            cursor.execute("""
            SELECT c.slug, c.title FROM rec_course_skills cs
            JOIN courses c ON cs.course_id = c.id
            JOIN rec_skills s ON cs.skill_id = s.id
            WHERE s.slug = ? AND cs.is_prerequisite = 0
            LIMIT 1
            """, (s_slug,))
            rec_c = cursor.fetchone()
            rec_course_slug = rec_c["slug"] if rec_c else "applied-machine-learning"
            rec_course_title = rec_c["title"] if rec_c else "Applied Machine Learning"

            skills_to_develop.append({
                "slug": s_slug,
                "name": user_info["name"],
                "skill_name": user_info["name"],
                "category": user_info["category"],
                "current_proficiency": curr_p,
                "current_mastery": curr_p,
                "target_proficiency": target_p,
                "target_benchmark": target_p,
                "gap_size": round(gap, 1),
                "gap": round(gap, 1),
                "priority": priority,
                "weight": req["weight"],
                "recommended_course_slug": rec_course_slug,
                "recommended_course_title": rec_course_title,
                "why_important": f"Required for {target_role['role_name']} competency benchmark.",
                "headline": f"Target Deficit: {round(gap, 1)}% in {user_info['name']}",
                "explanation": f"Required for {target_role['role_name']}. Target is {target_p}% mastery; current verified level is {curr_p}%."
            })

        skills_to_develop.sort(key=lambda x: x["gap_size"], reverse=True)

        # -------------------------------------------------------------
        # 4. GENERATE RECOMMENDED PROJECTS
        # -------------------------------------------------------------
        recommended_projects = [
            {
                "title": "Production Vector Indexing & Semantic Search Engine",
                "course_slug": "applied-machine-learning",
                "difficulty": "Advanced",
                "estimated_hours": 18,
                "description": "Design and benchmark a production-ready FAISS semantic search index with hybrid lexical retrieval.",
                "skills_practiced": ["Vector Search & Embeddings", "NumPy Vectorization", "MLOps Model Serving"],
                "target_skills": ["Vector Search & Embeddings", "NumPy Vectorization", "Model Serving"],
                "headline": "Capstone Engineering for AI Roles",
                "why_recommended": "Strengthens vector indexing and model latency optimization for senior engineering roles.",
                "explanation": "Builds verified proof-of-work in high-dimensional vector search, FAISS approximate indexing, and low-latency API deployment."
            },
            {
                "title": "Automated EDA & Statistical Risk Analytics Pipeline",
                "course_slug": "data-science",
                "difficulty": "Intermediate",
                "estimated_hours": 12,
                "description": "Construct automated anomaly detection pipelines and two-tailed hypothesis testing frameworks.",
                "skills_practiced": ["Pandas EDA", "SQL Analytics", "A/B Hypothesis Testing"],
                "target_skills": ["Pandas EDA", "SQL Analytics", "A/B Hypothesis Testing"],
                "headline": "Core Analytics Portfolio Piece",
                "why_recommended": "Closes statistical modeling and data preparation gaps with real-world dataset validation.",
                "explanation": "Reinforces data wrangling, missing data imputation, and statistical significance testing."
            },
            {
                "title": "Idempotent Distributed Ingestion Worker & API Proxy",
                "course_slug": "forward-deployed-engineering",
                "difficulty": "Advanced",
                "estimated_hours": 16,
                "description": "Architect an asynchronous queue worker with token bucket rate-limiting and redis idempotency cache.",
                "skills_practiced": ["Distributed Systems", "API Security", "Fault-Tolerant ETL"],
                "target_skills": ["Distributed Systems", "API Security", "Fault-Tolerant ETL"],
                "headline": "High-Availability Infrastructure",
                "why_recommended": "Validates enterprise systems architecture and resilient backend API design.",
                "explanation": "Validates async message queue processing, token-bucket rate limiters, and idempotency guarantees."
            }
        ]

        # -------------------------------------------------------------
        # 5. FETCH CERTIFICATES (Platform & External)
        # -------------------------------------------------------------
        cursor.execute("SELECT * FROM rec_external_certificates WHERE is_active = 1")
        certificates = []
        for r in cursor.fetchall():
            item = dict(r)
            item["skills_covered"] = json.loads(item["skills_covered_json"])
            item["career_paths"] = json.loads(item["career_paths_json"])
            certificates.append(item)

        # -------------------------------------------------------------
        # 6. FETCH REAL JOB MARKET TRENDS
        # -------------------------------------------------------------
        cursor.execute("SELECT * FROM rec_job_market_trends WHERE is_connected = 1")
        job_trends = []
        for r in cursor.fetchall():
            item = dict(r)
            item["top_demanded_skills"] = json.loads(item["top_demanded_skills_json"])
            job_trends.append(item)

        # -------------------------------------------------------------
        # 7. GENERATE PERSONALIZED ROADMAP (Sequenced Milestones)
        # -------------------------------------------------------------
        roadmap = [
            {
                "step_order": 1,
                "course_title": "Python Programming",
                "course_slug": "python",
                "difficulty": "Beginner",
                "estimated_hours": 14,
                "status": "COMPLETED" if user_skills.get("python-core", {}).get("proficiency", 0) >= 60 else "CURRENT",
                "rationale": "Foundational language runtime mastery, data structures, and procedural foundations.",
                "skills_covered": ["Python Core", "AsyncIO Concurrency", "Test-Driven Development"]
            },
            {
                "step_order": 2,
                "course_title": "Data Science & Exploratory Analytics",
                "course_slug": "data-science",
                "difficulty": "Intermediate",
                "estimated_hours": 16,
                "status": "COMPLETED" if user_skills.get("pandas-eda", {}).get("proficiency", 0) >= 60 else ("CURRENT" if user_skills.get("python-core", {}).get("proficiency", 0) >= 60 else "LOCKED"),
                "rationale": "High-throughput data wrangling, SQL joins, and statistical significance validation.",
                "skills_covered": ["Pandas EDA", "SQL Data Modeling", "A/B Testing & Statistics"]
            },
            {
                "step_order": 3,
                "course_title": "Applied Machine Learning",
                "course_slug": "applied-machine-learning",
                "difficulty": "Advanced",
                "estimated_hours": 18,
                "status": "COMPLETED" if user_skills.get("numpy-vectorization", {}).get("proficiency", 0) >= 60 else ("CURRENT" if user_skills.get("pandas-eda", {}).get("proficiency", 0) >= 60 else "LOCKED"),
                "rationale": "Vector embeddings, scikit-learn estimators, and scalable model serving pipelines.",
                "skills_covered": ["NumPy Vectorization", "Scikit-Learn Modeling", "Vector Search & Embeddings", "MLOps Model Serving"]
            },
            {
                "step_order": 4,
                "course_title": "Forward-Deployed Engineering & Distributed Systems",
                "course_slug": "forward-deployed-engineering",
                "difficulty": "Advanced",
                "estimated_hours": 20,
                "status": "COMPLETED" if project_scores.get("forward-deployed-engineering", 0) >= 70 else ("CURRENT" if user_skills.get("numpy-vectorization", {}).get("proficiency", 0) >= 60 else "LOCKED"),
                "rationale": "Distributed consensus, fault-tolerant microservices, and enterprise API deployment.",
                "skills_covered": ["Distributed Systems", "API Security & Microservices", "Containerization & Docker"]
            }
        ]

        # -------------------------------------------------------------
        # 8. SAVE ACTIVE RECOMMENDATIONS & SNAPSHOT HISTORY
        # -------------------------------------------------------------
        cursor.execute("DELETE FROM rec_recommendations WHERE user_id = ?", (user_id,))
        
        # Save Next Course
        for idx, nc in enumerate(candidate_courses[:3]):
            cursor.execute("""
            INSERT INTO rec_recommendations (
                user_id, rec_type, item_id, item_title, item_slug, score,
                rank_order, reason_headline, reason_explanation, metadata_json
            ) VALUES (?, 'NEXT_COURSE', ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id, str(nc["course_id"]), nc["title"], nc["slug"], nc["score"],
                idx + 1, nc["headline"], nc["explanation"], json.dumps(nc)
            ))

        # Save Skills to Develop
        for idx, sk in enumerate(skills_to_develop[:5]):
            cursor.execute("""
            INSERT INTO rec_recommendations (
                user_id, rec_type, item_id, item_title, item_slug, score,
                rank_order, reason_headline, reason_explanation, metadata_json
            ) VALUES (?, 'SKILL_DEVELOPMENT', ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id, sk["slug"], sk["name"], sk["slug"], round(100.0 - sk["gap_size"], 1),
                idx + 1, sk["headline"], sk["explanation"], json.dumps(sk)
            ))

        # Snapshot object for history audit
        snapshot = {
            "timestamp": datetime.datetime.now().isoformat(),
            "target_role": target_role["role_name"],
            "recommended_next_course": candidate_courses[0] if candidate_courses else None,
            "continue_learning_count": len(continue_learning),
            "critical_skill_gaps": [s["name"] for s in skills_to_develop if s["gap_size"] > 0],
            "trigger_event": trigger_event
        }

        cursor.execute("""
        INSERT INTO rec_recommendation_history (user_id, trigger_event, snapshot_json)
        VALUES (?, ?, ?)
        """, (user_id, trigger_event, json.dumps(snapshot)))

        conn.commit()
        conn.close()

        return {
            "target_role": target_role["role_name"],
            "target_role_data": target_role,
            "recommended_next_course": candidate_courses[0] if candidate_courses else None,
            "all_recommended_courses": candidate_courses,
            "continue_learning": continue_learning,
            "skills_to_develop": skills_to_develop,
            "all_user_skills": skills_to_develop,
            "recommended_projects": recommended_projects,
            "certificates": certificates,
            "job_trends": job_trends,
            "roadmap": roadmap
        }
