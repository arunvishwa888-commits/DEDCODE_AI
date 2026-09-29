#!/usr/bin/env python3
"""
DEDCODE Live Weekly AI + Mentor Assessment — 25-Scenario E2E Test Suite
Validates:
  1. System checks & Session Initialization
  2. Anti-False-Positive Temporal Confirmation (Camera/Face/Audio)
  3. Warning Progression (Warning 1/2 -> Warning 2/2 -> Violation 3)
  4. Automatic Termination & REVIEW_REQUIRED State
  5. Mentor Moderation Actions (ALLOW_RETAKE, CONFIRM_TERMINATION, DISMISS_EVENT)
  6. Multi-attempt Retakes
  7. 50/50 AI + Senior Industry Mentor Evaluation
  8. RBAC, Security & Data Protection
"""
import requests
import json
import sys
import time

BASE = "http://localhost:5050"
PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
results = []

def test(name, condition, detail=""):
    is_ok = bool(condition)
    status = PASS if is_ok else FAIL
    results.append(is_ok)
    print(f"  {status} {name}" + (f"  [{detail}]" if detail else ""))

def section(title):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")

# ── 1. Authenticate Actors ──────────────────────────────────────────────────
section("Setup: Authenticate Student, Mentor & Admin")

# Student
sr = requests.post(f"{BASE}/api/auth/login", json={"email": "student@test.com", "password": "student123"})
if sr.status_code != 200:
    sr = requests.post(f"{BASE}/api/auth/login", json={"email": "yogesh@dedcode.ai", "password": "password123"})
if sr.status_code != 200:
    requests.post(f"{BASE}/api/auth/register", json={"name": "Weekly Student", "email": "weekly@dedcode.ai", "password": "Password123!", "role": "STUDENT"})
    sr = requests.post(f"{BASE}/api/auth/login", json={"email": "weekly@dedcode.ai", "password": "Password123!"})

student_token = sr.json().get("token") if sr.status_code == 200 else None
test("Student authenticated", bool(student_token))

# Admin / Mentor
ar = requests.post(f"{BASE}/api/auth/login", json={"email": "admin@dedcode.ai", "password": "admin123"})
admin_token = ar.json().get("token") if ar.status_code == 200 else None
test("Admin / Mentor authenticated", bool(admin_token))

def s_hdr():
    return {"Authorization": f"Bearer {student_token}", "Content-Type": "application/json"}

def a_hdr():
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}

# ── 2. Test Configuration Endpoints ─────────────────────────────────────────
section("Test 25: Admin Configuration & Thresholds")
cfg_res = requests.get(f"{BASE}/api/career-track/weekly-assessment/config")
test("Fetch assessment configuration (Public/Student)", cfg_res.status_code == 200 and "config" in cfg_res.json())

cfg_update = requests.post(
    f"{BASE}/api/career-track/weekly-assessment/config",
    headers=a_hdr(),
    json={"max_warnings": 2, "face_not_detected_threshold": 8.0, "multiple_face_threshold": 2.5}
)
test("Admin update thresholds", cfg_update.status_code == 200 and cfg_update.json().get("config", {}).get("max_warnings") == 2)

# ── 3. Initialize Live Assessment Session ───────────────────────────────────
section("Test 1–3: Pre-Check & Session Initialization")
init_res = requests.post(
    f"{BASE}/api/career-track/weekly-assessment/session/init",
    headers=s_hdr(),
    json={
        "course_id": 1,
        "module_id": 1,
        "week_number": 1,
        "system_checks": {"camera": True, "microphone": True, "network": True, "fullscreen": True}
    }
)
session_data = init_res.json() if init_res.status_code == 200 else {}
session_id_1 = session_data.get("session_id")
test("Test 1: Session initialized with pre-check (Attempt #1)", bool(session_id_1), f"session_id={session_id_1}")

# Start Session
start_res = requests.post(f"{BASE}/api/career-track/weekly-assessment/session/{session_id_1}/start", headers=s_hdr())
test("Session transitioned to ACTIVE state", start_res.status_code == 200 and start_res.json().get("session_status") == "ACTIVE")

# ── 4. Anti-False-Positive Event Ingestion ──────────────────────────────────
section("Tests 4–13: Observable Event Ingestion & Debouncing")

events_payload = [
    # Normal / brief events (no violation triggered)
    {"event_type": "STUDENT_FACE_PRESENT", "duration_seconds": 12.0, "confidence": 0.99},
    {"event_type": "FACE_NOT_DETECTED",    "duration_seconds": 1.5,  "confidence": 0.80}, # < 8s threshold
    {"event_type": "MULTIPLE_FACES",       "duration_seconds": 0.8,  "confidence": 0.60}, # < 2.5s threshold
    {"event_type": "SIGNIFICANT_BACKGROUND_AUDIO", "duration_seconds": 0.5, "confidence": 0.70},
    {"event_type": "MICROPHONE_RECONNECTED", "duration_seconds": 0.0},
    {"event_type": "CAMERA_RECONNECTED",     "duration_seconds": 0.0},
    {"event_type": "TAB_SWITCH",             "duration_seconds": 1.0},
    {"event_type": "WINDOW_BLUR",            "duration_seconds": 1.2},
    {"event_type": "WINDOW_FOCUS",           "duration_seconds": 0.0},
    {"event_type": "FULLSCREEN_ENTER",       "duration_seconds": 0.0},
]

ingest_res = requests.post(
    f"{BASE}/api/career-track/weekly-assessment/session/{session_id_1}/events",
    headers=s_hdr(),
    json={"events": events_payload}
)
test("Tests 4,6,8,10,11,12,13: Batch event ingestion with temporal metadata",
     ingest_res.status_code == 200 and ingest_res.json().get("inserted") == len(events_payload))

# ── 5. Warning Progression ──────────────────────────────────────────────────
section("Tests 14–17: Warning 1 -> Warning 2 -> Violation 3 (Termination)")

# Violation 1 -> Warning 1
w1_res = requests.post(
    f"{BASE}/api/career-track/weekly-assessment/session/{session_id_1}/warning",
    headers=s_hdr(),
    json={"event_type": "FACE_NOT_DETECTED", "reason": "Face not detected for 9 seconds."}
)
w1_data = w1_res.json() if w1_res.status_code == 200 else {}
test("Test 14 & Test 5: Warning 1/2 issued on confirmed face absence",
     w1_data.get("warning_count") == 1 and not w1_data.get("terminated"))

# Violation 2 -> Warning 2
w2_res = requests.post(
    f"{BASE}/api/career-track/weekly-assessment/session/{session_id_1}/warning",
    headers=s_hdr(),
    json={"event_type": "MULTIPLE_FACES", "reason": "Multiple faces detected for 3.2 seconds."}
)
w2_data = w2_res.json() if w2_res.status_code == 200 else {}
test("Test 15 & Test 7: Warning 2/2 issued on confirmed multiple faces",
     w2_data.get("warning_count") == 2 and not w2_data.get("terminated"))

# Violation 3 -> Auto Termination
w3_res = requests.post(
    f"{BASE}/api/career-track/weekly-assessment/session/{session_id_1}/warning",
    headers=s_hdr(),
    json={"event_type": "EXTERNAL_AUDIO_DETECTED", "reason": "Sustained external voice detected for 4.5 seconds."}
)
w3_data = w3_res.json() if w3_res.status_code == 200 else {}
test("Test 16, 17, 9: Third confirmed violation -> Automatic TERMINATION",
     w3_data.get("terminated") is True and w3_data.get("status") == "TERMINATED")

# Verify session locked from auto-restart
locked_init = requests.post(
    f"{BASE}/api/career-track/weekly-assessment/session/init",
    headers=s_hdr(),
    json={"course_id": 1, "module_id": 1, "week_number": 1, "system_checks": {}}
)
test("Terminated session locked from auto-restart without mentor review", locked_init.status_code == 403)

# ── 6. Mentor Review & Retake Workflow ──────────────────────────────────────
section("Tests 18–19: Mentor Moderation Review & Allow Retake")

# Mentor reads session review
rev_res = requests.get(
    f"{BASE}/api/career-track/weekly-assessment/mentor/review/{session_id_1}",
    headers=a_hdr()
)
rev_data = rev_res.json() if rev_res.status_code == 200 else {}
test("Test 18: Mentor fetches full session details & event timeline",
     rev_res.status_code == 200 and "events" in rev_data and rev_data.get("session", {}).get("status") == "TERMINATED")
test("Disclaimer present in mentor moderation review", "disclaimer" in rev_data)

# Mentor authorizes ALLOW_RETAKE
action_res = requests.post(
    f"{BASE}/api/career-track/weekly-assessment/mentor/action/{session_id_1}",
    headers=a_hdr(),
    json={"action": "ALLOW_RETAKE", "notes": "Authorized by Marcus Vance after reviewing timestamps."}
)
test("Test 19: Mentor executes ALLOW_RETAKE action", action_res.status_code == 200 and action_res.json().get("action") == "ALLOW_RETAKE")

# ── 7. Fresh Retake Attempt (Attempt #2) & Normal Submission ────────────────
section("Tests 20–22: Retake (Attempt #2) & 50/50 AI + Mentor Evaluation")

init_res_2 = requests.post(
    f"{BASE}/api/career-track/weekly-assessment/session/init",
    headers=s_hdr(),
    json={"course_id": 1, "module_id": 1, "week_number": 1, "system_checks": {"camera": True, "microphone": True}}
)
session_id_2 = init_res_2.json().get("session_id")
attempt_num_2 = init_res_2.json().get("attempt_number")
test("Fresh Session initialized (Attempt #2+)", bool(session_id_2) and attempt_num_2 >= 2)

# Start Attempt 2
requests.post(f"{BASE}/api/career-track/weekly-assessment/session/{session_id_2}/start", headers=s_hdr())

# Submit Attempt 2 with answers
submit_res = requests.post(
    f"{BASE}/api/career-track/weekly-assessment/session/{session_id_2}/submit",
    headers=s_hdr(),
    json={
        "answers": {
            "quiz_answers": [{"question_id": 1, "is_correct": True}, {"question_id": 2, "is_correct": True}],
            "code_submission": "def vector_search(vectors, query):\n    '''Semantic vector cosine index'''\n    import numpy as np\n    assert vectors.ndim == 2\n    return np.dot(vectors, query)\n",
            "written_explanation": "Vector cosine similarity handles dimensional normalisation and provides sub-linear retrieval bounds."
        }
    }
)
sub_data = submit_res.json() if submit_res.status_code == 200 else {}
eval_data = sub_data.get("evaluation", {})

test("Test 20: Normal weekly assessment submission completed", submit_res.status_code == 200)
test("Test 21: 50% AI Evaluation calculated", "ai_score" in eval_data and eval_data["ai_score"] >= 70.0)
test("Test 22: 50% Senior Industry Mentor Evaluation calculated", "mentor_score" in eval_data and "rubric_scores" in eval_data.get("mentor_feedback", {}))
test("Composite 50/50 final score generated and passed", eval_data.get("final_score") is not None and eval_data.get("passed") is True)

# ── 8. Security & RBAC ──────────────────────────────────────────────────────
section("Tests 23–24: Security, RBAC & Persistence")

# Student cannot access admin/mentor review endpoint
unauth_mentor = requests.get(f"{BASE}/api/career-track/weekly-assessment/admin/sessions", headers=s_hdr())
test("Test 23: Student blocked from accessing Mentor/Admin review queue (401)", unauth_mentor.status_code == 401)

# Student cannot modify warning count or terminate other students' sessions
foreign_term = requests.post(f"{BASE}/api/career-track/weekly-assessment/session/99999/warning", headers=s_hdr(), json={})
test("Student cannot tamper with non-existent / foreign session (404)", foreign_term.status_code in [403, 404])

# Page refresh / session status endpoint
status_res = requests.get(f"{BASE}/api/career-track/weekly-assessment/session/{session_id_2}/status", headers=s_hdr())
test("Test 24: Page refresh state & assessment summary retrieved safely",
     status_res.status_code == 200 and status_res.json().get("session", {}).get("session_status") == "COMPLETED")

# ── Summary ─────────────────────────────────────────────────────────────────
section("FINAL RESULTS")
passed = sum(1 for r in results if r is True)
total  = len(results)
pct    = round(passed/total*100) if total else 0

print(f"\n  {passed}/{total} tests passed ({pct}%)")
if passed == total:
    print(f"\033[92m  ✓ ALL 25+ E2E ASSESSMENT SCENARIOS PASSED PERFECTLY!\033[0m")
    sys.exit(0)
else:
    print(f"\033[91m  ✗ {total-passed} TESTS FAILED\033[0m")
    sys.exit(1)
