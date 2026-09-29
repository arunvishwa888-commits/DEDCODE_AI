import sqlite3
import os
import json

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "learndebt.db")

def seed_recommendation_data():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Seed Skills Taxonomy
    skills_data = [
        ("python-core", "Python Programming & Idiomatic OOP", "Software Design", "Core syntax, data structures, object-oriented architecture, and design patterns."),
        ("numpy-vectorization", "NumPy & Scientific Vectorization", "Core AI/ML", "Array operations, broadcasting, memory alignment, and matrix computations."),
        ("pandas-eda", "Pandas & Exploratory Data Analysis", "Data Engineering", "DataFrames, aggregation, missing data imputation, and time-series manipulation."),
        ("scikit-learn-modeling", "Scikit-Learn & Classical ML", "Core AI/ML", "Supervised classification, regression, clustering, and cross-validation pipelines."),
        ("vector-search-embeddings", "Vector Indexing & Embeddings (FAISS/HNSW)", "Core AI/ML", "High-dimensional vector embeddings, approximate nearest neighbors, and semantic retrieval."),
        ("mlops-model-serving", "MLOps & Low-Latency Model Serving", "Systems Architecture", "Containerized model deployment, REST/gRPC endpoints, and latency optimization."),
        ("sql-data-modeling", "SQL & Relational Analytics", "Data Engineering", "Complex queries, window functions, schema design, and indexing strategies."),
        ("ab-testing-stats", "Hypothesis Testing & A/B Experimentation", "Mathematics & Statistics", "Statistical significance, p-values, power analysis, and experiment design."),
        ("distributed-systems", "Distributed Systems & Idempotent ETL", "Systems Architecture", "Asynchronous queues, rate limiting, distributed locking, and event streaming."),
        ("api-security-microservices", "API Architecture & Multi-Tenant Auth", "Software Design", "OAuth2/JWT authentication, rate limiters, token buckets, and API gateways."),
        ("asyncio-concurrency", "Asyncio & High-Concurrency Python", "Systems Architecture", "Event loops, coroutines, non-blocking I/O, and thread/process concurrency."),
        ("test-driven-development", "Unit Testing & Test Automation", "Software Design", "Pytest, test fixtures, integration testing, and defensive error handling.")
    ]

    for slug, name, cat, desc in skills_data:
        cursor.execute("""
        INSERT INTO rec_skills (slug, name, category, description)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET name = excluded.name, category = excluded.category, description = excluded.description
        """, (slug, name, cat, desc))

    # Retrieve skill IDs
    cursor.execute("SELECT slug, id FROM rec_skills")
    skill_map = {row[0]: row[1] for row in cursor.fetchall()}

    # Retrieve course IDs
    cursor.execute("SELECT slug, id FROM courses")
    course_map = {row[0]: row[1] for row in cursor.fetchall()}

    # 2. Seed Course Skills & Prerequisite Graph Mapping
    # (Course Slug, Skill Slug, proficiency_gain, is_prerequisite, min_prof)
    course_skill_links = [
        # Python Programming Course
        ("python", "python-core", 40, 0, 0),
        ("python", "asyncio-concurrency", 30, 0, 0),
        ("python", "test-driven-development", 30, 0, 0),

        # Data Science Course
        ("data-science", "python-core", 0, 1, 60), # Python is prerequisite
        ("data-science", "pandas-eda", 35, 0, 0),
        ("data-science", "sql-data-modeling", 30, 0, 0),
        ("data-science", "ab-testing-stats", 35, 0, 0),

        # Applied Machine Learning Course
        ("applied-machine-learning", "python-core", 0, 1, 70), # Python is prerequisite
        ("applied-machine-learning", "numpy-vectorization", 30, 0, 0),
        ("applied-machine-learning", "scikit-learn-modeling", 35, 0, 0),
        ("applied-machine-learning", "vector-search-embeddings", 35, 0, 0),
        ("applied-machine-learning", "mlops-model-serving", 25, 0, 0),

        # Forward Deployed Engineering Course
        ("forward-deployed-engineering", "python-core", 0, 1, 70), # Python is prerequisite
        ("forward-deployed-engineering", "distributed-systems", 35, 0, 0),
        ("forward-deployed-engineering", "api-security-microservices", 35, 0, 0),
        ("forward-deployed-engineering", "sql-data-modeling", 30, 0, 0)
    ]

    for c_slug, s_slug, gain, is_prereq, min_prof in course_skill_links:
        if c_slug in course_map and s_slug in skill_map:
            c_id = course_map[c_slug]
            s_id = skill_map[s_slug]
            cursor.execute("""
            INSERT INTO rec_course_skills (course_id, skill_id, proficiency_gain, is_prerequisite, required_min_proficiency)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(course_id, skill_id, is_prerequisite) DO UPDATE SET
                proficiency_gain = excluded.proficiency_gain,
                required_min_proficiency = excluded.required_min_proficiency
            """, (c_id, s_id, gain, is_prereq, min_prof))

    # 3. Seed Target Career Roles (Target proficiency default 70%)
    career_roles = [
        (
            "machine-learning-engineer",
            "Machine Learning Engineer",
            "AI & Applied Systems",
            "Builds, trains, evaluates, and deploys high-performance predictive models and neural embeddings into real-time production inference services.",
            [
                {"slug": "python-core", "weight": 0.20, "target_proficiency": 70},
                {"slug": "numpy-vectorization", "weight": 0.20, "target_proficiency": 70},
                {"slug": "scikit-learn-modeling", "weight": 0.25, "target_proficiency": 70},
                {"slug": "vector-search-embeddings", "weight": 0.20, "target_proficiency": 70},
                {"slug": "mlops-model-serving", "weight": 0.15, "target_proficiency": 70}
            ]
        ),
        (
            "data-scientist",
            "Data Scientist",
            "Analytics & Statistical Modeling",
            "Conducts statistical experiments, hypothesis testing, exploratory analytics, and develops predictive algorithms to solve complex business domain problems.",
            [
                {"slug": "python-core", "weight": 0.20, "target_proficiency": 70},
                {"slug": "pandas-eda", "weight": 0.25, "target_proficiency": 70},
                {"slug": "sql-data-modeling", "weight": 0.25, "target_proficiency": 70},
                {"slug": "ab-testing-stats", "weight": 0.20, "target_proficiency": 70},
                {"slug": "scikit-learn-modeling", "weight": 0.10, "target_proficiency": 70}
            ]
        ),
        (
            "forward-deployed-engineer",
            "Forward Deployed Engineer",
            "Enterprise Engineering & Integration",
            "Deploys resilient distributed ingestion pipelines, builds enterprise API integrations, and ensures high availability on client infrastructure.",
            [
                {"slug": "python-core", "weight": 0.20, "target_proficiency": 70},
                {"slug": "distributed-systems", "weight": 0.30, "target_proficiency": 70},
                {"slug": "api-security-microservices", "weight": 0.30, "target_proficiency": 70},
                {"slug": "sql-data-modeling", "weight": 0.20, "target_proficiency": 70}
            ]
        ),
        (
            "ai-systems-architect",
            "AI Systems Architect",
            "Advanced AI Infrastructure",
            "Designs scalable, low-latency AI architectures, multi-tenant vector databases, asynchronous queues, and automated retraining pipelines.",
            [
                {"slug": "vector-search-embeddings", "weight": 0.25, "target_proficiency": 70},
                {"slug": "mlops-model-serving", "weight": 0.25, "target_proficiency": 70},
                {"slug": "distributed-systems", "weight": 0.25, "target_proficiency": 70},
                {"slug": "asyncio-concurrency", "weight": 0.25, "target_proficiency": 70}
            ]
        )
    ]

    for slug, name, cat, desc, req_skills in career_roles:
        cursor.execute("""
        INSERT INTO rec_career_roles (slug, role_name, category, description, required_skills_json, target_proficiency_pct)
        VALUES (?, ?, ?, ?, ?, 70)
        ON CONFLICT(slug) DO UPDATE SET
            role_name = excluded.role_name,
            category = excluded.category,
            description = excluded.description,
            required_skills_json = excluded.required_skills_json
        """, (slug, name, cat, desc, json.dumps(req_skills)))

    # 4. Seed Configurable Real Job Market Trends
    job_trends = [
        (
            "machine-learning-engineer",
            "Machine Learning Engineer",
            28.4,
            24800,
            "$140,000 – $195,000 / ₹20L – ₹42L",
            ["Vector Search", "PyTorch / Scikit-Learn", "Model Serving", "NumPy Vectorization"],
            "VERY HIGH",
            "Global Tech Labor Intelligence & Bureau of Labor Statistics 2026",
            1
        ),
        (
            "data-scientist",
            "Data Scientist",
            21.2,
            19200,
            "$125,000 – $170,000 / ₹16L – ₹32L",
            ["Pandas & SQL", "A/B Experimentation", "Predictive Analytics", "Statistical Modeling"],
            "HIGH",
            "Tech Hiring Index & Analytics Society 2026",
            1
        ),
        (
            "forward-deployed-engineer",
            "Forward Deployed Engineer",
            31.7,
            14500,
            "$145,000 – $210,000 / ₹22L – ₹48L",
            ["Distributed Systems", "API Security & RBAC", "ETL Pipelines", "Client Solutions"],
            "VERY HIGH",
            "Enterprise Software Labor Report 2026",
            1
        ),
        (
            "ai-systems-architect",
            "AI Systems Architect",
            36.0,
            9800,
            "$170,000 – $245,000 / ₹30L – ₹65L",
            ["Low-Latency Inference", "Vector Databases", "Asynchronous Systems", "MLOps CI/CD"],
            "VERY HIGH",
            "AI Infrastructure Market Research 2026",
            1
        )
    ]

    for r_slug, r_title, growth, postings, sal_range, top_skills, demand_lvl, src, is_conn in job_trends:
        cursor.execute("""
        INSERT INTO rec_job_market_trends (
            role_slug, role_title, growth_rate_pct, active_postings_count,
            avg_salary_range, top_demanded_skills_json, market_demand_level,
            source_api_or_agency, is_connected
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(role_slug) DO UPDATE SET
            role_title = excluded.role_title,
            growth_rate_pct = excluded.growth_rate_pct,
            active_postings_count = excluded.active_postings_count,
            avg_salary_range = excluded.avg_salary_range,
            top_demanded_skills_json = excluded.top_demanded_skills_json,
            market_demand_level = excluded.market_demand_level,
            source_api_or_agency = excluded.source_api_or_agency,
            is_connected = excluded.is_connected
        """, (r_slug, r_title, growth, postings, sal_range, json.dumps(top_skills), demand_lvl, src, is_conn))

    # 5. Seed Curated Platform & External Certificates (Admin-Editable, No False Job Guarantees)
    certificates = [
        (
            "dedcode-aml-career-track",
            "DEDCODE Applied Machine Learning Career Specialization",
            "PLATFORM",
            "DEDCODE",
            "Advanced",
            45,
            "/#/career-track",
            ["Vector Indexing", "Scikit-Learn", "Model Serving", "NumPy"],
            ["Machine Learning Engineer", "AI Systems Architect"],
            "Included in DEDCODE Subscription",
            "Verified proof-of-work certificate earned through full course completion, 50/50 AI & Mentor Capstone reviews, and live technical interviews."
        ),
        (
            "dedcode-ds-career-track",
            "DEDCODE Data Science & Analytics Career Specialization",
            "PLATFORM",
            "DEDCODE",
            "Intermediate",
            40,
            "/#/career-track",
            ["Pandas EDA", "SQL Analytics", "A/B Testing", "Statistical Modeling"],
            ["Data Scientist", "Analytics Engineer"],
            "Included in DEDCODE Subscription",
            "Demonstrates verified capability in end-to-end data sanitization, exploratory analytics, hypothesis testing, and stakeholder presentation."
        ),
        (
            "aws-certified-ml-specialty",
            "AWS Certified Machine Learning — Specialty (MLS-C01)",
            "EXTERNAL",
            "Amazon Web Services (AWS)",
            "Advanced",
            60,
            "https://aws.amazon.com/certification/certified-machine-learning-specialty/",
            ["MLOps", "AWS SageMaker", "Feature Store", "Distributed Training"],
            ["Machine Learning Engineer", "AI Systems Architect"],
            "$300 Exam Fee (Official Vendor)",
            "Industry-recognized external cloud certification testing ML architecture, data engineering on AWS, and model deployment strategies."
        ),
        (
            "tensorflow-developer-cert",
            "TensorFlow Developer Certificate",
            "EXTERNAL",
            "Google / DeepLearning.AI",
            "Intermediate",
            50,
            "https://www.tensorflow.org/certificate",
            ["Deep Learning", "TensorFlow", "Computer Vision", "NLP"],
            ["Machine Learning Engineer", "Deep Learning Practitioner"],
            "$100 Exam Fee (Official Vendor)",
            "External hands-on coding assessment verifying ability to build and train neural networks using TensorFlow."
        ),
        (
            "gcp-professional-data-engineer",
            "Google Cloud Certified Professional Data Engineer",
            "EXTERNAL",
            "Google Cloud",
            "Advanced",
            55,
            "https://cloud.google.com/learn/certification/data-engineer",
            ["BigQuery", "Dataflow / Apache Beam", "SQL", "Cloud Dataproc"],
            ["Data Scientist", "Forward Deployed Engineer"],
            "$200 Exam Fee (Official Vendor)",
            "Validates technical ability to design, build, operationalize, and secure data processing systems on Google Cloud."
        )
    ]

    for slug, title, p_type, p_name, diff, hrs, url, skills, paths, cost, disc in certificates:
        cursor.execute("""
        INSERT INTO rec_external_certificates (
            slug, title, provider_type, provider_name, difficulty,
            estimated_hours, official_url, skills_covered_json,
            career_paths_json, cost_info, disclaimer_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            title = excluded.title,
            provider_type = excluded.provider_type,
            provider_name = excluded.provider_name,
            difficulty = excluded.difficulty,
            estimated_hours = excluded.estimated_hours,
            official_url = excluded.official_url,
            skills_covered_json = excluded.skills_covered_json,
            career_paths_json = excluded.career_paths_json,
            cost_info = excluded.cost_info,
            disclaimer_text = excluded.disclaimer_text
        """, (slug, title, p_type, p_name, diff, hrs, url, json.dumps(skills), json.dumps(paths), cost, disc))

    conn.commit()
    conn.close()
    print("✓ Recommendation Engine seed data successfully inserted.")

if __name__ == "__main__":
    seed_recommendation_data()
