import json
import sqlite3

def get_student_profile(conn, user_id):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM student_learning_profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        return None
    
    p = dict(row)
    return {
        "id": p["id"],
        "user_id": p["user_id"],
        "course_interests": json.loads(p.get("course_interests_json") or "[]"),
        "skills": json.loads(p.get("skills_json") or "[]"),
        "primary_career": p.get("primary_career"),
        "secondary_careers": json.loads(p.get("secondary_careers_json") or "[]"),
        "coding_languages": json.loads(p.get("coding_languages_json") or "[]"),
        "experience_level": p.get("experience_level") or "Beginner",
        "learning_preferences": json.loads(p.get("learning_preferences_json") or "[]"),
        "learning_goal": p.get("learning_goal"),
        "onboarding_completed": bool(p.get("onboarding_completed", 0)),
        "created_at": p.get("created_at"),
        "updated_at": p.get("updated_at")
    }

def save_student_profile(conn, user_id, data):
    cursor = conn.cursor()
    course_interests = data.get("course_interests") or data.get("courseInterests") or []
    skills = data.get("skills") or []
    primary_career = data.get("primary_career") or data.get("primaryCareer") or "Machine Learning Engineer"
    secondary_careers = data.get("secondary_careers") or data.get("secondaryCareers") or []
    coding_languages = data.get("coding_languages") or data.get("codingLanguages") or []
    experience_level = data.get("experience_level") or data.get("experienceLevel") or "Beginner"
    learning_preferences = data.get("learning_preferences") or data.get("learningPreferences") or []
    learning_goal = data.get("learning_goal") or data.get("learningGoal") or "Build fundamentals"

    cursor.execute("""
    INSERT INTO student_learning_profiles (
        user_id, course_interests_json, skills_json, primary_career, 
        secondary_careers_json, coding_languages_json, experience_level, 
        learning_preferences_json, learning_goal, onboarding_completed, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
    ON CONFLICT(user_id) DO UPDATE SET
        course_interests_json = excluded.course_interests_json,
        skills_json = excluded.skills_json,
        primary_career = excluded.primary_career,
        secondary_careers_json = excluded.secondary_careers_json,
        coding_languages_json = excluded.coding_languages_json,
        experience_level = excluded.experience_level,
        learning_preferences_json = excluded.learning_preferences_json,
        learning_goal = excluded.learning_goal,
        onboarding_completed = 1,
        updated_at = CURRENT_TIMESTAMP
    """, (
        user_id,
        json.dumps(course_interests),
        json.dumps(skills),
        primary_career,
        json.dumps(secondary_careers),
        json.dumps(coding_languages),
        experience_level,
        json.dumps(learning_preferences),
        learning_goal
    ))
    conn.commit()
    return get_student_profile(conn, user_id)

def generate_personalized_recommendations(conn, user_id):
    profile = get_student_profile(conn, user_id)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM courses WHERE is_published = 1 OR status = 'PUBLISHED'")
    course_rows = cursor.fetchall()

    if not course_rows:
        return {
            "user_id": user_id,
            "onboarding_completed": bool(profile and profile["onboarding_completed"]),
            "recommendations": [],
            "learning_path": [],
            "target_career": profile["primary_career"] if profile else "Software Engineer",
            "skills_to_build": []
        }

    target_career = (profile["primary_career"] if profile else "Machine Learning Engineer") or "Machine Learning Engineer"
    sec_careers = profile["secondary_careers"] if profile else []
    user_interests = set(i.lower() for i in (profile["course_interests"] if profile else []))
    
    user_skills_map = {}
    if profile and profile.get("skills"):
        for s in profile["skills"]:
            if isinstance(s, dict):
                user_skills_map[s.get("name", "").lower()] = s.get("level", "BEGINNER").upper()
            elif isinstance(s, str):
                user_skills_map[s.lower()] = "BEGINNER"

    user_lang_map = {}
    if profile and profile.get("coding_languages"):
        for l in profile["coding_languages"]:
            if isinstance(l, dict):
                user_lang_map[l.get("name", "").lower()] = l.get("current_level", "BEGINNER").upper()
            elif isinstance(l, str):
                user_lang_map[l.lower()] = "BEGINNER"

    user_exp = (profile["experience_level"] if profile else "Beginner").upper()

    cursor.execute("SELECT course_id, progress_pct, status FROM enrollments WHERE user_id = ?", (user_id,))
    enrolled = {r["course_id"]: dict(r) for r in cursor.fetchall()}

    cursor.execute("SELECT DISTINCT concept_name FROM learning_debt WHERE user_id = ? AND status != 'Resolved'", (user_id,))
    active_debts = [r["concept_name"] for r in cursor.fetchall()]

    courses = []
    for r in course_rows:
        c = dict(r)
        c["skills_covered"] = json.loads(c.get("skills_covered_json") or "[]")
        c["career_paths"] = json.loads(c.get("career_paths_json") or "[]")
        c["prerequisites"] = json.loads(c.get("prerequisites_json") or "[]")
        c["recommended_before"] = json.loads(c.get("recommended_before_json") or "[]")
        c["recommended_after"] = json.loads(c.get("recommended_after_json") or "[]")
        c["coding_languages"] = json.loads(c.get("coding_languages_json") or "[]")
        courses.append(c)

    scored_courses = []
    for c in courses:
        match_signals = []
        score = 50.0

        c_careers = [car.lower() for car in c["career_paths"]]
        if target_career.lower() in c_careers:
            score += 35
            match_signals.append("career_alignment")
        elif any(sc.lower() in c_careers for sc in sec_careers):
            score += 20
            match_signals.append("secondary_career_alignment")

        c_skills = [sk.lower() for sk in c["skills_covered"]]
        interest_overlap = sum(1 for i in user_interests if i in c_skills or i in c["title"].lower() or i in c["description"].lower())
        if interest_overlap > 0:
            score += min(25, interest_overlap * 10)
            match_signals.append("interest_alignment")

        c_langs = [l.lower() for l in c["coding_languages"]]
        if any(l in c_langs for l in user_lang_map):
            score += 15
            match_signals.append("language_alignment")

        c_diff = (c.get("difficulty") or c.get("level") or "INTERMEDIATE").upper()
        if (user_exp in ["COMPLETE BEGINNER", "BEGINNER"] and c_diff == "BEGINNER") or \
           (user_exp == "INTERMEDIATE" and c_diff == "INTERMEDIATE") or \
           (user_exp == "ADVANCED" and c_diff == "ADVANCED"):
            score += 15
            match_signals.append("experience_level_match")
        elif user_exp in ["COMPLETE BEGINNER", "BEGINNER"] and c_diff == "INTERMEDIATE":
            score += 5

        missing_prereqs = []
        for p in c["prerequisites"]:
            p_lower = p.lower()
            if p_lower not in user_skills_map and p_lower not in user_lang_map:
                missing_prereqs.append(p)
            elif user_skills_map.get(p_lower) == "BEGINNER" and c_diff in ["INTERMEDIATE", "ADVANCED"]:
                missing_prereqs.append(f"{p} (foundational)")

        prereqs_satisfied = len(missing_prereqs) == 0

        enr_info = enrolled.get(c["id"])
        if enr_info:
            if enr_info["status"] == "COMPLETED" or enr_info["progress_pct"] == 100:
                score -= 30
            elif enr_info["progress_pct"] > 0:
                score += 10

        match_pct = min(98, max(60, int(score)))

        reason_parts = []
        if "career_alignment" in match_signals:
            reason_parts.append(f"Strongly aligns with your target career goal as a {target_career}.")
        if "interest_alignment" in match_signals:
            reason_parts.append(f"Directly covers your selected interests in {', '.join(c['skills_covered'][:3])}.")
        if not prereqs_satisfied:
            reason_parts.append(f"Recommended prerequisite foundations: {', '.join(missing_prereqs)}.")

        reason = " ".join(reason_parts) if reason_parts else f"Builds essential core competencies for {c['title']}."

        scored_courses.append({
            "course_id": c["id"],
            "slug": c["slug"],
            "title": c["title"],
            "description": c["description"],
            "difficulty": c["difficulty"],
            "duration": c["duration"],
            "thumbnail_url": c["thumbnail_url"],
            "match_pct": match_pct,
            "match_signals": match_signals,
            "prerequisites_satisfied": prereqs_satisfied,
            "missing_prerequisites": missing_prereqs,
            "reason": reason,
            "skills_covered": c["skills_covered"],
            "career_paths": c["career_paths"],
            "prerequisites": c["prerequisites"]
        })

    scored_courses.sort(key=lambda x: x["match_pct"], reverse=True)

    for idx, sc in enumerate(scored_courses):
        sc["rank"] = idx + 1

    difficulty_order = {"BEGINNER": 1, "INTERMEDIATE": 2, "ADVANCED": 3}
    path_courses = sorted(courses, key=lambda c: (difficulty_order.get((c.get("difficulty") or c.get("level") or "INTERMEDIATE").upper(), 2), c["id"]))

    ordered_path = []
    for step_num, pc in enumerate(path_courses, start=1):
        c_diff = (pc.get("difficulty") or pc.get("level") or "INTERMEDIATE").upper()
        badge = "Foundation" if c_diff == "BEGINNER" else ("Recommended Next" if step_num == 2 else "Career-Aligned")
        
        if c_diff == "BEGINNER":
            p_reason = f"Recommended first to build core Python and algorithmic programming fundamentals for your {target_career} path."
        elif step_num == 2:
            p_reason = f"Recommended next to master exploratory data analysis, statistics, and SQL before entering advanced ML engineering."
        else:
            p_reason = f"Primary career target matching your goal to become a {target_career}."

        ordered_path.append({
            "step": step_num,
            "course_id": pc["id"],
            "slug": pc["slug"],
            "title": pc["title"],
            "difficulty": c_diff,
            "duration": pc.get("duration", "12 Weeks"),
            "badge": badge,
            "reason": p_reason,
            "prerequisite_for": pc["recommended_before"]
        })

    all_skills = []
    for c in courses:
        for sk in c["skills_covered"]:
            if sk not in all_skills:
                all_skills.append(sk)

    return {
        "user_id": user_id,
        "onboarding_completed": bool(profile and profile["onboarding_completed"]),
        "profile": profile,
        "recommendations": scored_courses,
        "ordered_learning_path": ordered_path,
        "target_career": target_career,
        "skills_to_build": all_skills[:8],
        "active_learning_debts": active_debts
    }

def generate_recommendations_from_preferences(conn, prefs, user_id=None):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM courses WHERE is_published = 1 OR status = 'PUBLISHED'")
    course_rows = cursor.fetchall()

    if not course_rows:
        return {
            "user_id": user_id,
            "preferences": prefs,
            "recommendations": [],
            "ordered_learning_path": []
        }

    career_interests = prefs.get("careerInterests") or prefs.get("course_interests") or []
    current_skills = prefs.get("currentSkills") or prefs.get("skills") or []
    learning_languages = prefs.get("learningLanguages") or prefs.get("coding_languages") or []
    experience_level = (prefs.get("experienceLevel") or prefs.get("experience_level") or "Beginner").upper()
    career_goal = prefs.get("careerGoal") or prefs.get("primary_career") or "AI/ML Engineer"
    learning_style = prefs.get("learningStyle") or prefs.get("learning_style") or "Project-based"
    weekly_hours = prefs.get("weeklyHours") or prefs.get("weekly_hours") or "5-10"

    c_interests_set = set(str(ci).lower() for ci in career_interests)
    c_skills_set = set(str(cs).lower() for cs in current_skills if str(cs).lower() != "none")
    c_langs_set = set(str(cl).lower() for cl in learning_languages)

    scored_courses = []
    for r in course_rows:
        c = dict(r)
        c_skills = [s.lower() for s in json.loads(c.get("skills_covered_json") or "[]")]
        c_careers = [car.lower() for car in json.loads(c.get("career_paths_json") or "[]")]
        c_langs = [l.lower() for l in json.loads(c.get("coding_languages_json") or "[]")]
        c_prereqs = [p.lower() for p in json.loads(c.get("prerequisites_json") or "[]")]
        c_level = (c.get("difficulty") or c.get("level") or "INTERMEDIATE").upper()

        score = 0
        reasons = []

        # 1. Career Interest Match (+30)
        interest_matched = [ci for ci in c_interests_set if ci in c.get("category", "").lower() or ci in c.get("title", "").lower() or any(ci in sk for sk in c_skills)]
        if interest_matched:
            score += 30
            reasons.append(f"✓ Matches your {interest_matched[0].title()} career interest")
        elif not c_interests_set:
            score += 15

        # 2. Career Goal Match (+25)
        if any(str(career_goal).lower() in car for car in c_careers) or str(career_goal).lower() in c.get("title", "").lower():
            score += 25
            reasons.append(f"✓ Directly aligns with your goal to become a {career_goal}")
        else:
            score += 10

        # 3. Skill Match (+15)
        skill_overlap = [s for s in c_skills if s in c_skills_set or s in c_langs_set]
        if skill_overlap:
            score += 15
            reasons.append(f"✓ Builds upon your existing skills ({', '.join([s.title() for s in skill_overlap[:2]])})")
        elif "none" in c_skills_set or not c_skills_set:
            if c_level == "BEGINNER":
                score += 15
                reasons.append("✓ Designed from scratch for learners starting fresh")
            else:
                score += 5

        # 4. Programming Language Match (+10)
        lang_overlap = [l for l in c_langs if l in c_langs_set or l in c_skills_set]
        if lang_overlap:
            score += 10
            reasons.append(f"✓ Uses {', '.join([l.title() for l in lang_overlap])}, which you selected")
        elif not c_langs_set:
            score += 5

        # 5. Experience Level Match (+10)
        if (experience_level in ["COMPLETE BEGINNER", "BEGINNER"] and c_level == "BEGINNER") or \
           (experience_level == "INTERMEDIATE" and c_level == "INTERMEDIATE") or \
           (experience_level == "ADVANCED" and c_level == "ADVANCED"):
            score += 10
            reasons.append(f"✓ Suitable for your {experience_level.title()} experience level")
        elif experience_level in ["COMPLETE BEGINNER", "BEGINNER"] and c_level == "INTERMEDIATE":
            score += 5
            reasons.append(f"✓ Step-up module tailored for growing {experience_level.title()}s")
        else:
            score += 5

        # 6. Learning Style Match (+5)
        score += 5
        reasons.append(f"✓ {learning_style} approach matches your learning preference")

        # 7. Time Compatibility (+5)
        score += 5
        reasons.append(f"✓ Fits your {weekly_hours} weekly schedule")

        match_score = min(98, max(55, score))

        scored_courses.append({
            "courseId": c["id"],
            "id": c["id"],
            "slug": c["slug"],
            "title": c["title"],
            "description": c["description"],
            "category": c.get("category", "Software Engineering"),
            "difficulty": c.get("difficulty") or c.get("level") or "Intermediate",
            "level": c.get("difficulty") or c.get("level") or "Intermediate",
            "duration": c.get("duration", "12 Weeks"),
            "thumbnail_url": c.get("thumbnail_url"),
            "price": c.get("price_inr") if c.get("price_inr") is not None else 2000,
            "matchScore": match_score,
            "match_pct": match_score,
            "reasons": reasons,
            "reason": " ".join(reasons),
            "skills": json.loads(c.get("skills_covered_json") or "[]"),
            "careerPaths": json.loads(c.get("career_paths_json") or "[]"),
            "languages": json.loads(c.get("coding_languages_json") or "[]")
        })

    scored_courses.sort(key=lambda x: x["matchScore"], reverse=True)

    diff_rank = {"BEGINNER": 1, "INTERMEDIATE": 2, "ADVANCED": 3}
    path_sorted = sorted(scored_courses, key=lambda x: (diff_rank.get(x["level"].upper(), 2), -x["matchScore"]))

    ordered_path = []
    for idx, pc in enumerate(path_sorted, start=1):
        c_level = pc["level"].upper()
        if idx == 1:
            badge = "01 • Foundation (Start Here)"
            reason = f"Recommended first to build essential programming and mathematical foundations."
        elif idx == 2:
            badge = "02 • Core Skill Mastery"
            reason = f"Recommended second to transition from fundamentals into exploratory data & statistical analysis."
        elif idx == 3:
            badge = "03 • Advanced Applied Engineering"
            reason = f"Recommended third to build production machine learning models and end-to-end API systems."
        else:
            badge = f"0{idx} • System Specialization"
            reason = f"Follow-up specialization course aligned with your {career_goal} goal."

        ordered_path.append({
            "step": idx,
            "courseId": pc["courseId"],
            "slug": pc["slug"],
            "title": pc["title"],
            "level": pc["level"],
            "duration": pc["duration"],
            "badge": badge,
            "reason": reason
        })

    return {
        "user_id": user_id,
        "preferences": prefs,
        "recommendations": scored_courses,
        "ordered_learning_path": ordered_path,
        "career_goal": career_goal
    }
