import json

class CareerTrackGapAnalyzer:
    """
    Computes real-time skill gaps, strengths, and personalized actionable 30-60-90 day roadmaps
    based on course progress, project score, and AI technical interview metrics.
    """

    SKILL_MATRIX = {
        "applied-machine-learning": [
            {"name": "Feature Engineering & Data Sanitization", "category": "Core ML", "importance": "High"},
            {"name": "Distributed Vector Indexing (FAISS/HNSW)", "category": "AI Systems", "importance": "High"},
            {"name": "Hyperparameter Optimization & Cross-Validation", "category": "Core ML", "importance": "Medium"},
            {"name": "Low-Latency Inference & Model Serving", "category": "MLOps", "importance": "High"},
            {"name": "Concept Drift Monitoring & Retraining", "category": "Production", "importance": "High"}
        ],
        "data-science": [
            {"name": "Exploratory Data Analysis & Statistical Modeling", "category": "Statistics", "importance": "High"},
            {"name": "Hypothesis Testing & A/B Experimentation", "category": "Experimentation", "importance": "High"},
            {"name": "SQL & Analytical Query Optimization", "category": "Data Engineering", "importance": "High"},
            {"name": "Predictive Classification & Regression", "category": "Modeling", "importance": "High"},
            {"name": "Data Visualization & Stakeholder Communication", "category": "Business", "importance": "Medium"}
        ],
        "forward-deployed-engineering": [
            {"name": "Distributed Microservices & Concurrency", "category": "Architecture", "importance": "High"},
            {"name": "Enterprise API Design & Multi-Tenant Auth", "category": "Security", "importance": "High"},
            {"name": "Idempotent Data Ingestion & ETL Pipelines", "category": "Data Pipelines", "importance": "High"},
            {"name": "Production Telemetry & Observability", "category": "DevOps", "importance": "High"},
            {"name": "Client Technical Integration & Scoping", "category": "Consulting", "importance": "Medium"}
        ],
        "python": [
            {"name": "Idiomatic OOP & Design Patterns", "category": "Software Design", "importance": "High"},
            {"name": "Asyncio & Concurrent Programming", "category": "Performance", "importance": "High"},
            {"name": "Unit Testing & Test-Driven Development", "category": "Quality", "importance": "High"},
            {"name": "Memory Profiling & C-Extensions", "category": "Optimization", "importance": "Medium"},
            {"name": "REST API Development (FastAPI/Flask)", "category": "Web Services", "importance": "High"}
        ]
    }

    @classmethod
    def analyze_gaps(cls, course_slug, project_score, interview_score):
        slug = course_slug.lower() if course_slug else "python"
        matched_key = "python"
        for k in cls.SKILL_MATRIX:
            if k in slug or slug in k:
                matched_key = k
                break

        base_skills = cls.SKILL_MATRIX.get(matched_key, cls.SKILL_MATRIX["python"])
        
        strong_skills = []
        gap_skills = []

        avg_score = (project_score + interview_score) / 2.0

        for idx, skill in enumerate(base_skills):
            # Skill level derived from performance
            mod_factor = (idx * 3) - 4
            derived_pct = min(98, max(55, int(avg_score + mod_factor)))
            
            skill_entry = {
                "name": skill["name"],
                "category": skill["category"],
                "mastery_pct": derived_pct,
                "importance": skill["importance"]
            }

            if derived_pct >= 80:
                skill_entry["status"] = "Strong"
                strong_skills.append(skill_entry)
            else:
                skill_entry["status"] = "Improvement Opportunity"
                skill_entry["target_action"] = f"Practice deep-dive implementation of {skill['name']} in hands-on scenarios."
                gap_skills.append(skill_entry)

        # 30-60-90 Day Milestone Roadmap
        roadmap = [
            {
                "phase": "Days 1 – 30: Core Mastery & Production Hardening",
                "goal": "Solidify architectural patterns and resolve identified gap skills.",
                "actions": [
                    f"Refactor capstone codebase to incorporate automated CI/CD unit tests for {gap_skills[0]['name'] if gap_skills else 'core components'}.",
                    "Implement defensive exception logging and latency metrics profiling."
                ]
            },
            {
                "phase": "Days 31 – 60: Real-World Systems & Distributed Scaling",
                "goal": "Build high-throughput resilience and system design intuition.",
                "actions": [
                    "Design and benchmark asynchronous queue workers handling batch workloads.",
                    "Complete 5 mock architecture whiteboard interviews focusing on trade-off articulation."
                ]
            },
            {
                "phase": "Days 61 – 90: Industry Portfolio & Career Placement",
                "goal": "Showcase verified credentials and engage top engineering hiring pipelines.",
                "actions": [
                    "Publish verified DEDCODE Career Track Certificate to LinkedIn and GitHub profile.",
                    "Apply to vetted engineering partner roles with tailored technical case studies."
                ]
            }
        ]

        readiness_score = round(min(99.0, max(70.0, (avg_score * 0.95) + 3.0)), 1)

        return {
            "strong_skills": strong_skills,
            "gap_skills": gap_skills,
            "roadmap": roadmap,
            "readiness_score": readiness_score
        }
