DEDCODE — AI-Powered Learning Intelligence Platform

«Learn what you need. Close what you don't know.»

DEDCODE is an AI-powered Learning Intelligence Platform that adapts learning based on what a student knows, what they struggle with, and how they learn.

Instead of simply providing courses and quizzes, DEDCODE analyzes assessment performance, hints, answer changes, reasoning, learning behaviour, and concept-level gaps to calculate Learning Debt and generate a personalized learning path.

---

📌 Project Overview

DEDCODE follows an intelligent learning cycle:

ASSESS
   ↓
ANALYZE
   ↓
IDENTIFY KNOWLEDGE GAPS
   ↓
CALCULATE LEARNING DEBT
   ↓
PERSONALIZE LEARNING
   ↓
PRACTICE
   ↓
BUILD PROJECTS
   ↓
REASSESS
   ↓
MASTER

Key Features

- 🎯 Personalized course recommendations
- 🧠 Learning Debt calculation
- 📊 Concept-level learning analytics
- 🎥 Module-specific educational videos
- 💬 RAG-based AI Tutor
- 📝 Intelligent module assessments
- 💡 Progressive hints
- 🔍 Assessment behaviour analysis
- 🗣️ Answer justification analysis
- 📈 Personalized ordered learning paths
- 💻 Coding workspace
- 🔗 Interconnected projects
- 🧩 Code-to-visual representation
- 👨‍💼 Admin course and student management
- 📊 Student and enrollment analytics
- 🔐 Email/Password authentication
- 🔑 Google OAuth/OIDC authentication
- 🌐 Multilingual learning support
- 📚 Course, module, project and progress tracking

---

🛠️ Technologies Used

Frontend

- Next.js
- TypeScript
- React
- Tailwind CSS
- shadcn/ui
- Lucide Icons
- Framer Motion
- Recharts
- React Flow
- Monaco Editor

Backend

- FastAPI
- Python
- REST APIs
- WebSocket where required

Database & Infrastructure

- PostgreSQL
- Redis
- Vector Database
- Supabase where configured
- Vercel for frontend deployment

AI / Machine Learning

- Large Language Models
- RAG (Retrieval-Augmented Generation)
- Embeddings
- Vector Search
- Learning behaviour analysis
- Concept mastery analysis
- Learning Debt engine

Authentication

- Email / Password
- Google OAuth 2.0 / OpenID Connect
- Role-based authentication:
  - "STUDENT"
  - "ADMIN"

Learning Content

- Official educational YouTube/NPTEL/IIT sources
- Module-specific transcripts
- Module assessments
- Progressive projects

---

⚙️ Setup & Installation

1. Clone the Repository

git clone https://github.com/<your-username>/<your-repository>.git

cd <your-repository>

---

2. Install Frontend Dependencies

npm install

or:

pnpm install

---

3. Install Backend Dependencies

Navigate to the backend directory:

cd backend

Create a Python virtual environment:

python -m venv venv

Activate it.

Windows

venv\Scripts\activate

Linux / macOS

source venv/bin/activate

Install dependencies:

pip install -r requirements.txt

---

🔐 Environment Variables

Create a ".env.local" file for the frontend:

NEXT_PUBLIC_API_URL=http://localhost:8000

Create a ".env" file for the backend:

DATABASE_URL=your_postgresql_connection_string

REDIS_URL=your_redis_connection_string

GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback

OPENAI_API_KEY=your_openai_api_key

Add any additional AI/vector-database credentials required by the implementation.

Important

Never commit ".env", ".env.local", API keys, OAuth secrets, or database credentials.

Add them to ".gitignore":

.env
.env.local
.env.*.local
venv/
__pycache__/
node_modules/
.next/

---

🗄️ Database Setup

Make sure PostgreSQL is running.

Configure:

DATABASE_URL=your_database_url

Run the project's database migrations or initialization command.

For example:

alembic upgrade head

If the project uses another migration system, use the project's configured migration command.

---

🔑 Google Authentication Setup

DEDCODE supports Google OAuth/OIDC for students.

Create a Google OAuth application through Google Cloud Console.

Configure the authorized redirect URI to match:

http://localhost:8000/auth/google/callback

For production, replace this with the deployed HTTPS callback URL.

Configure:

GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=...

The Google authentication flow is:

DEDCODE Login
      ↓
Continue with Google
      ↓
Google Account Selector
      ↓
Google Authentication
      ↓
OAuth Callback
      ↓
Backend Verification
      ↓
DEDCODE Session
      ↓
Student Dashboard

---

▶️ How to Run the Project

Start Backend

From the backend directory:

uvicorn main:app --reload --port 8000

Backend will be available at:

http://localhost:8000

---

Start Frontend

Open another terminal in the project root:

npm run dev

Frontend will be available at:

http://localhost:3000

Open:

http://localhost:3000

---

👤 Authentication

Student

Students can authenticate using:

- Email + Password
- Google OAuth/OIDC

After successful authentication:

Student → Student Dashboard

Admin

Admin access is available through the Admin Portal.

Admin Portal
     ↓
Admin Email + Password
     ↓
Backend Role Verification
     ↓
Admin Dashboard

Roles are enforced by the backend:

STUDENT
ADMIN

---

📚 Learning Flow

Register
   ↓
Learning Profile
   ↓
Course Interests
   ↓
Skills + Skill Level
   ↓
Career Interests
   ↓
Programming Language Interests
   ↓
Learning Goal
   ↓
Personalized Recommendations
   ↓
Ordered Learning Path
   ↓
Course
   ↓
Module
   ↓
Video + Transcript
   ↓
RAG AI Tutor
   ↓
Assessment
   ↓
Behaviour Analysis
   ↓
Learning Debt
   ↓
Recovery
   ↓
Project
   ↓
Reassessment

---

🚀 Project Structure

dedcode/
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── pages/
│   ├── services/
│   └── ...
│
├── backend/
│   ├── api/
│   ├── models/
│   ├── services/
│   ├── repositories/
│   ├── auth/
│   ├── rag/
│   ├── assessment/
│   └── ...
│
├── database/
│   ├── migrations/
│   └── ...
│
├── public/
│
├── .env.example
├── package.json
├── requirements.txt
└── README.md

«Update the structure above to match the actual repository structure.»

---

📊 Core DEDCODE Intelligence

The platform analyzes multiple learning signals instead of relying only on assessment marks.

Answer Accuracy
      +
Hint Usage
      +
Answer Changes
      +
Time Spent
      +
Question Revisits
      +
Justification
      +
Repeated Mistakes
      +
Previous Mastery
      ↓
Learning Intelligence
      ↓
Concept Mastery
      ↓
Learning Debt
      ↓
Recovery Recommendation

The goal is to understand why a learner is struggling, not just whether an answer is correct.

---

💻 Progressive Project System

Students build projects throughout the course.

For a 10-module course:

Modules 1–2
     ↓
Project 01
     ↓
Modules 3–4
     ↓
Project 02
     ↓
Modules 5–6
     ↓
Project 03
     ↓
Modules 7–8
     ↓
Project 04
     ↓
Modules 9–10
     ↓
Final Integrated Project

Each project builds on previous knowledge and contributes toward the final project.

---

👨‍💼 Admin Portal

Administrators can:

- Create courses
- Edit courses
- Publish/unpublish courses
- Add modules
- Reorder modules
- Add module videos
- Add transcripts
- Create assessments
- Configure projects
- Manage students
- View enrollments
- View course enrollment counts
- View student progress
- View Learning Debt analytics
- View course-level analytics

All analytics are connected to the same database used by students.

---

🔒 Security

DEDCODE follows role-based access control.

STUDENT
 ├── Student Dashboard
 ├── My Courses
 ├── Learning Debt
 ├── Projects
 └── Assessments

ADMIN
 ├── Admin Dashboard
 ├── Course Management
 ├── Student Management
 ├── Enrollment Analytics
 └── Platform Analytics

Students cannot access administrative APIs or data.

---

📄 License

Add your project's selected license here.

Example:

MIT License

---

👥 Team

DEDCODE — Street Coders

Built as an AI-powered learning intelligence platform focused on personalized, measurable and practical learning.

«Learn what you need. Close what you don't know.»
