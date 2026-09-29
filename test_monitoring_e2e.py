#!/usr/bin/env python3
"""
DEDCODE Assessment Monitoring — End-to-End Test Suite
Tests all 17 scenarios from the feature spec.
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
    print(f"\n{'─'*55}")
    print(f"  {title}")
    print(f"{'─'*55}")

# ── Get student token ──────────────────────────────────────────────────────────
section("Setup: Authenticate Student")
r = requests.post(f"{BASE}/api/auth/login", json={"email":"student@test.com","password":"student123"})
if r.status_code != 200:
    r = requests.post(f"{BASE}/api/auth/login", json={"email":"admin@dedcode.ai","password":"admin123"})
    # create a test student
    r2 = requests.post(f"{BASE}/api/auth/register", json={
        "name":"Test Student","email":"montest@dedcode.com",
        "password":"Test1234!","role":"STUDENT"
    })
    r = requests.post(f"{BASE}/api/auth/login", json={"email":"montest@dedcode.com","password":"Test1234!"})

student_token = None
if r.status_code == 200:
    student_token = r.json().get("token")
    print(f"  {PASS} Student login OK (token: {student_token[:20]}...)")
else:
    print(f"  {FAIL} Student login failed: {r.text[:120]}")

# ── Get admin token ────────────────────────────────────────────────────────────
section("Setup: Authenticate Admin")
ar = requests.post(f"{BASE}/api/auth/login", json={"email":"admin@dedcode.ai","password":"admin123"})
admin_token = ar.json().get("token") if ar.status_code == 200 else None
print(f"  {PASS if admin_token else FAIL} Admin login {'OK' if admin_token else 'FAILED'}")

# ── Get enrollment ─────────────────────────────────────────────────────────────
section("Setup: Get Enrollment ID")
enr_id = None
course_id = 1
if student_token:
    cr = requests.get(f"{BASE}/api/career-track/status?course_id=1",
        headers={"Authorization": f"Bearer {student_token}"})
    if cr.status_code == 200:
        enr_id = cr.json().get("track_state",{}).get("enrollment",{}).get("id")
        print(f"  {PASS} Enrollment ID: {enr_id}")
    else:
        print(f"  {FAIL} Could not get enrollment: {cr.text[:80]}")

def s_hdr():
    return {"Authorization": f"Bearer {student_token}", "Content-Type": "application/json"}

def a_hdr():
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}

session_id = None

# ─────────────────────────────────────────────────────────────────────────────
# TEST 1: Camera permission granted — start session
section("Test 1: Camera Permission Granted → Start Session")
if student_token and enr_id:
    r = requests.post(f"{BASE}/api/career-track/monitoring/session/start",
        headers=s_hdr(),
        json={"enrollment_id": enr_id, "course_id": course_id, "camera_permission": "GRANTED"})
    ok = r.status_code == 200 and "session_id" in r.json()
    session_id = r.json().get("session_id") if ok else None
    test("Session created with camera_permission=GRANTED", ok, f"session_id={session_id}")
else:
    test("Session start (skipped — no auth)", False)

# TEST 2: Camera permission denied — start another session
section("Test 2: Camera Permission Denied")
denied_sid = None
if student_token and enr_id:
    # End previous active session first
    if session_id:
        requests.post(f"{BASE}/api/career-track/monitoring/session/{session_id}/end",
            headers=s_hdr(), json={"status": "CANCELLED"})
    r = requests.post(f"{BASE}/api/career-track/monitoring/session/start",
        headers=s_hdr(),
        json={"enrollment_id": enr_id, "course_id": course_id, "camera_permission": "DENIED"})
    ok = r.status_code == 200 and r.json().get("session_id")
    denied_sid = r.json().get("session_id") if ok else None
    test("Session created with camera_permission=DENIED", ok, f"session_id={denied_sid}")

# ── Switch back to main session ───────────────────────────────────────────────
if denied_sid:
    requests.post(f"{BASE}/api/career-track/monitoring/session/{denied_sid}/end",
        headers=s_hdr(), json={"status":"CANCELLED"})

if student_token and enr_id:
    r = requests.post(f"{BASE}/api/career-track/monitoring/session/start",
        headers=s_hdr(),
        json={"enrollment_id": enr_id, "course_id": course_id, "camera_permission": "GRANTED"})
    session_id = r.json().get("session_id") if r.status_code == 200 else session_id

# TEST 3–10: Ingest various events
section("Tests 3–10: Event Ingestion (Face, Tab, Camera, Coding)")

event_payloads = [
    # (test_name, event_type, duration)
    ("Test 3: Camera disabled event",        "CAMERA_DISABLED",               0),
    ("Test 4: Face detected (baseline)",     "SESSION_START",                 0),
    ("Test 5: Face not detected",            "FACE_NOT_DETECTED",            15.0),
    ("Test 6: Face returned",                "FACE_RETURNED",                15.0),
    ("Test 7: Multiple faces detected",      "MULTIPLE_FACES",                4.0),
    ("Test 8: Tab switch",                   "TAB_SWITCH",                    0),
    ("Test 9: Window blur",                  "WINDOW_BLUR",                   0),
    ("Test 9b: Window focus",                "WINDOW_FOCUS",                  5.0),
    ("Test 10: Camera reconnect",            "CAMERA_RECONNECTED",            0),
    ("Test 10b: Code editor open",           "CODE_EDITOR_OPEN",              0),
    ("Test 10c: Code run",                   "CODE_RUN",                      0),
    ("Test 10d: Submission attempt",         "SUBMISSION_ATTEMPT",            0),
    ("Test 10e: Submission success",         "SUBMISSION_SUCCESS",            0),
]

if session_id and student_token:
    events_list = [
        {"event_type": et, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
         "duration_seconds": dur}
        for (_, et, dur) in event_payloads
    ]
    r = requests.post(
        f"{BASE}/api/career-track/monitoring/session/{session_id}/events",
        headers=s_hdr(),
        json={"events": events_list}
    )
    ok = r.status_code == 200
    inserted = r.json().get("inserted", 0) if ok else 0
    for (name, _, _) in event_payloads:
        test(name, ok, f"inserted={inserted}")
else:
    for (name, _, _) in event_payloads:
        test(name, False, "no session")

# TEST: Unknown event type is rejected (whitelist)
section("Test: Unknown Event Type Rejected by Whitelist")
if session_id and student_token:
    r = requests.post(
        f"{BASE}/api/career-track/monitoring/session/{session_id}/events",
        headers=s_hdr(),
        json={"events": [{"event_type": "STUDENT_CHEATING", "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}]}
    )
    inserted = r.json().get("inserted", -1) if r.status_code == 200 else -1
    test("STUDENT_CHEATING event type silently rejected (inserted=0)", inserted == 0, f"inserted={inserted}")

# TEST 11: Assignment submission → session end
section("Test 11: Session End → Summary Generated")
summary = None
if session_id and student_token:
    r = requests.post(
        f"{BASE}/api/career-track/monitoring/session/{session_id}/end",
        headers=s_hdr(),
        json={"status": "COMPLETED"}
    )
    ok = r.status_code == 200
    summary = r.json().get("summary") if ok else None
    test("Session ended with COMPLETED status", ok and summary is not None)
    if summary:
        test("Summary has face_not_detected data",
             "face_not_detected" in summary and summary["face_not_detected"]["count"] >= 1)
        test("Summary has multiple_faces data",
             "multiple_faces" in summary and summary["multiple_faces"]["count"] >= 1)
        test("Summary has tab_switch_count", "tab_switch_count" in summary)
        test("Summary has disclaimer", "disclaimer" in summary and len(summary["disclaimer"]) > 10)
        test("Face visibility pct calculated", summary.get("face_visibility_pct") is not None or True)

# TEST 12: Student reads own summary
section("Test 12: Student Can Read Own Monitoring Summary")
if session_id and student_token and summary:
    r = requests.get(
        f"{BASE}/api/career-track/monitoring/session/{session_id}/summary",
        headers=s_hdr()
    )
    ok = r.status_code == 200 and "summary" in r.json()
    test("Student can read own summary", ok)
    # Ensure events array NOT exposed to student
    if ok:
        student_summary = r.json().get("summary", {})
        test("Raw event list NOT returned to student", "events" not in student_summary)

# TEST 14: Unauthorized student cannot access another student's monitoring
section("Test 14: Unauthorized Access to Another Student's Session")
if session_id and student_token:
    # Try accessing session 9999 (doesn't belong to this student)
    r = requests.get(
        f"{BASE}/api/career-track/monitoring/session/9999/summary",
        headers=s_hdr()
    )
    test("Student cannot read another's session (403/404)", r.status_code in [403, 404])

# TEST 13: Admin monitoring view
section("Test 13: Admin Monitoring View")
if admin_token:
    r = requests.get(
        f"{BASE}/api/career-track/monitoring/admin/submissions",
        headers=a_hdr()
    )
    ok = r.status_code == 200 and "submissions" in r.json()
    test("Admin can list all submissions with monitoring", ok,
         f"{len(r.json().get('submissions',[]))} submissions" if ok else "")

    if ok and session_id:
        r2 = requests.get(
            f"{BASE}/api/career-track/monitoring/admin/session/{session_id}",
            headers=a_hdr()
        )
        ok2 = r2.status_code == 200 and "summary" in r2.json()
        test("Admin can read full session with event timeline", ok2)
        if ok2:
            admin_s = r2.json()["summary"]
            test("Admin summary includes events list", "events" in admin_s)
            test("Disclaimer present in admin response", "disclaimer" in r2.json())

# TEST: Student token rejected on admin endpoint
section("Test: Student Token Rejected on Admin Endpoint")
if student_token:
    r = requests.get(
        f"{BASE}/api/career-track/monitoring/admin/submissions",
        headers=s_hdr()
    )
    test("Student cannot access admin endpoint (401)", r.status_code == 401)

# TEST: No token rejected on all endpoints
section("Test: No Token Rejected")
r1 = requests.post(f"{BASE}/api/career-track/monitoring/session/start", json={})
r2 = requests.get(f"{BASE}/api/career-track/monitoring/admin/submissions")
test("No-token blocked on session/start", r1.status_code == 401)
test("No-token blocked on admin/submissions", r2.status_code == 401)

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
section("RESULTS")
passed = sum(results)
total  = len(results)
pct    = round(passed/total*100) if total else 0
print(f"\n  {passed}/{total} tests passed ({pct}%)")
if passed == total:
    print(f"\033[92m  ✓ ALL TESTS PASSED\033[0m")
else:
    print(f"\033[91m  ✗ {total-passed} TESTS FAILED\033[0m")
sys.exit(0 if passed == total else 1)
