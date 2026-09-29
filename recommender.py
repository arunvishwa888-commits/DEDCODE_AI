import sqlite3
import os
import json

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "learndebt.db")

class InnovationRecommender:
    """
    Recommends Innovation Challenges based on completed courses, verified skills,
    skill gaps, and difficulty progression, complete with transparent stored rationales.
    """

    @staticmethod
    def get_db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def get_recommended_problems(cls, user_id):
        conn = cls.get_db()
        cursor = conn.cursor()

        # 1. Fetch user skills from rec_user_skills
        cursor.execute("SELECT skill_id, proficiency_pct, confidence_score FROM rec_user_skills WHERE user_id = ?", (user_id,))
        user_skills_map = {r["skill_id"]: dict(r) for r in cursor.fetchall()}

        # 2. Fetch completed courses
        cursor.execute("""
        SELECT c.id, c.slug, c.title, e.progress_pct, e.status
        FROM enrollments e
        JOIN courses c ON e.course_id = c.id
        WHERE e.user_id = ? AND (e.progress_pct >= 80 OR e.status = 'COMPLETED')
        """, (user_id,))
        completed_courses = [dict(r) for r in cursor.fetchall()]

        # 3. Fetch user enrollments in innovation problems
        cursor.execute("SELECT problem_id, status, current_stage, why_recommended_reason FROM ib_enrollments WHERE user_id = ?", (user_id,))
        enrolled_problems_map = {r["problem_id"]: dict(r) for r in cursor.fetchall()}

        # 4. Fetch all active problems
        cursor.execute("""
        SELECT p.*, c.name as category_name, c.icon as category_icon
        FROM ib_problems p
        LEFT JOIN ib_categories c ON p.category_slug = c.slug
        WHERE p.status = 'ACTIVE'
        """)
        problems = [dict(r) for r in cursor.fetchall()]
        conn.close()

        ranked_problems = []
        for p in problems:
            p_id = p["id"]
            req_skills = json.loads(p.get("required_skills_json") or "[]")
            technologies = json.loads(p.get("technologies_json") or "[]")
            deliverables = json.loads(p.get("deliverables_json") or "[]")
            constraints = json.loads(p.get("constraints_json") or "[]")
            evaluation_criteria = json.loads(p.get("evaluation_criteria_json") or "[]")

            p["required_skills"] = req_skills
            p["technologies"] = technologies
            p["deliverables"] = deliverables
            p["constraints"] = constraints
            p["evaluation_criteria"] = evaluation_criteria

            # Calculate match score & rationale
            matched_skills = [s for s in req_skills if s in user_skills_map and user_skills_map[s]["proficiency_pct"] >= 50]
            gap_skills = [s for s in req_skills if s not in user_skills_map or user_skills_map[s]["proficiency_pct"] < 70]

            score = 60.0
            reasons = []

            if matched_skills:
                score += len(matched_skills) * 12.0
                reasons.append(f"Leverages your verified skills in {', '.join(matched_skills[:2])}")
            if gap_skills:
                score += 10.0
                reasons.append(f"Directly closes growth areas in {', '.join(gap_skills[:2])}")
            if completed_courses:
                score += 8.0
                reasons.append(f"Builds upon your foundation in {completed_courses[0]['title']}")

            if p["difficulty"] == "BEGINNER":
                score += 5.0
            elif p["difficulty"] == "INTERMEDIATE":
                score += 10.0
            elif p["difficulty"] == "ADVANCED" and len(matched_skills) >= 2:
                score += 15.0

            match_pct = min(99, max(65, int(score)))

            why_reason = " • ".join(reasons) if reasons else "Aligned with your current engineering track."
            p["match_score"] = match_pct
            p["why_recommended"] = why_reason
            p["is_enrolled"] = (p_id in enrolled_problems_map)
            p["enrollment_info"] = enrolled_problems_map.get(p_id)

            ranked_problems.append(p)

        # Sort by match_score descending
        ranked_problems.sort(key=lambda x: x["match_score"], reverse=True)
        return ranked_problems

    @classmethod
    def enroll_in_problem(cls, user_id, problem_id):
        conn = cls.get_db()
        cursor = conn.cursor()

        # Check problem exists
        cursor.execute("SELECT id, title FROM ib_problems WHERE id = ? AND status = 'ACTIVE'", (problem_id,))
        prob = cursor.fetchone()
        if not prob:
            conn.close()
            return False, "Innovation challenge not found or inactive.", None

        # Check existing enrollment
        cursor.execute("SELECT * FROM ib_enrollments WHERE user_id = ? AND problem_id = ?", (user_id, problem_id))
        existing = cursor.fetchone()
        if existing:
            conn.close()
            return True, f"Already enrolled in '{prob['title']}'.", dict(existing)

        # Compute recommendation reason
        recs = cls.get_recommended_problems(user_id)
        why_reason = next((r["why_recommended"] for r in recs if r["id"] == problem_id), "Student initiated enrollment.")

        cursor.execute("""
        INSERT INTO ib_enrollments (user_id, problem_id, why_recommended_reason, status, current_stage)
        VALUES (?, ?, ?, 'IN_PROGRESS', 'IDEA')
        """, (user_id, problem_id, why_reason))

        enr_id = cursor.lastrowid
        cursor.execute("SELECT * FROM ib_enrollments WHERE id = ?", (enr_id,))
        new_enr = dict(cursor.fetchone())

        conn.commit()
        conn.close()

        return True, f"Successfully enrolled in '{prob['title']}' workspace!", new_enr
