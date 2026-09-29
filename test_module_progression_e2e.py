import requests
import json
import sqlite3

BASE_URL = "http://localhost:5050"

def run_tests():
    print("=== STARTING MODULE UNLOCK & 2-MODULE MINI PROJECT PROGRESSION E2E TESTS ===")

    # 1. Reset progress for yogesh@dedcode.ai for clean testing
    conn = sqlite3.connect("backend/learndebt.db")
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE email = 'yogesh@dedcode.ai'")
    user_row = c.fetchone()
    assert user_row is not None, "Student user yogesh@dedcode.ai not found"
    user_id = user_row[0]
    
    # Reset learning_progress, project_progress, learning_debt, credit_transactions
    c.execute("DELETE FROM learning_progress WHERE user_id = ?", (user_id,))
    c.execute("DELETE FROM project_progress WHERE user_id = ?", (user_id,))
    c.execute("DELETE FROM learning_debt WHERE user_id = ?", (user_id,))
    c.execute("DELETE FROM credit_transactions WHERE user_id = ? AND type = 'MODULE_COMPLETION'", (user_id,))
    c.execute("UPDATE users SET credit_balance = 0 WHERE id = ?", (user_id,))
    c.execute("UPDATE modules SET is_unlocked = CASE WHEN order_index = 1 THEN 1 ELSE 0 END WHERE course_id = 1")
    conn.commit()
    conn.close()
    print("✓ Reset DB state for clean test run")

    # 2. Login as student
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "yogesh@dedcode.ai",
        "password": "password123"
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    print("✓ Student authenticated successfully")

    # 3. Verify initial state of Course 1 (Applied Machine Learning)
    resp = requests.get(f"{BASE_URL}/api/courses/applied-machine-learning/modules/m01", headers=headers)
    assert resp.status_code == 200, f"Get Module 1 failed: {resp.text}"
    data = resp.json()
    mod1 = next(m for m in data["course_modules"] if m["order_index"] == 1)
    mod2 = next(m for m in data["course_modules"] if m["order_index"] == 2)
    assert mod1["is_unlocked"] is True, "Module 1 should be unlocked"
    assert mod1["completed"] is False, "Module 1 should not be completed yet"
    assert mod2["is_unlocked"] is False, "Module 2 should initially be locked"
    print("✓ Initial state verified: Module 1 is unlocked, Module 2 is locked")

    # Verify Project 1 is initially locked
    resp = requests.get(f"{BASE_URL}/api/student/projects?course_id=1", headers=headers)
    assert resp.status_code == 200
    proj1 = next(p for p in resp.json()["projects"] if p["project_number"] == 1)
    assert proj1["is_unlocked"] is False, "Project 1 should initially be locked"
    assert proj1["status"] == "Locked", "Project 1 status should be Locked"
    print("✓ Initial project state verified: Mini Project 01 is Locked")

    # 4. Watch Module 1 Video to 85% completion
    resp = requests.post(f"{BASE_URL}/api/modules/1/video-progress", headers=headers, json={
        "progress_pct": 85,
        "watch_seconds": 120,
        "duration": 140
    })
    assert resp.status_code == 200, f"Module 1 video progress failed: {resp.text}"
    vdata = resp.json()
    assert vdata["completed"] is True, "Module 1 should be marked completed"
    assert vdata["passed"] is True, "Module 1 should be marked passed"
    assert vdata["next_module"]["order_index"] == 2, "Next module should be Module 2"
    assert vdata["next_module"]["slug"] == "m02", "Next module slug should be m02"
    assert vdata["project_unlocked"] is None, "Project should not be unlocked after only 1 module"
    assert vdata["credits_awarded"] == 3, f"Should award 3 credits, got {vdata['credits_awarded']}"
    
    # Check that course_modules returned has Module 2 unlocked
    c_mods = vdata["course_modules"]
    mod1_updated = next(m for m in c_mods if m["order_index"] == 1)
    mod2_updated = next(m for m in c_mods if m["order_index"] == 2)
    assert mod1_updated["completed"] is True, "Module 1 should be marked completed in course_modules"
    assert mod2_updated["is_unlocked"] is True, "Module 2 should now be unlocked in course_modules"
    print("✓ TEST 1 PASSED: Module 1 video completion (85%) immediately unlocked Module 2 and awarded +3 credits!")

    # 5. Verify GET Module 2 now reports is_unlocked = True
    resp = requests.get(f"{BASE_URL}/api/courses/applied-machine-learning/modules/m02", headers=headers)
    assert resp.status_code == 200, f"Get Module 2 failed: {resp.text}"
    m2_data = resp.json()
    mod2_check = next(m for m in m2_data["course_modules"] if m["order_index"] == 2)
    assert mod2_check["is_unlocked"] is True, "Module 2 must be unlocked"
    print("✓ TEST 2 PASSED: Module 2 page confirms is_unlocked = True")

    # 6. Complete Module 2 (Video Progress to 100% or direct complete)
    resp = requests.post(f"{BASE_URL}/api/modules/2/video-progress", headers=headers, json={
        "progress_pct": 100,
        "watch_seconds": 150,
        "duration": 150,
        "completed": True
    })
    assert resp.status_code == 200, f"Module 2 video progress failed: {resp.text}"
    vdata2 = resp.json()
    assert vdata2["completed"] is True, "Module 2 should be marked completed"
    assert vdata2["next_module"]["order_index"] == 3, "Next module should be Module 3"
    
    # Check 2-Module milestone test portion unlocked!
    proj_unlocked = vdata2["project_unlocked"]
    assert proj_unlocked is not None, "2-Module milestone Project 01 must be unlocked!"
    assert proj_unlocked["project_number"] == 1, f"Expected project 1, got {proj_unlocked['project_number']}"
    assert "Data Cleaning & Vectorization Tool" in proj_unlocked["title"]
    assert proj_unlocked["milestone_modules"] == [1, 2]
    print("✓ TEST 3 PASSED: Completing Module 2 immediately unlocked Mini Project 01 Milestone Test Portion!")

    # 7. Verify /api/student/projects and /api/student/projects/1
    resp = requests.get(f"{BASE_URL}/api/student/projects?course_id=1", headers=headers)
    assert resp.status_code == 200
    pdata = resp.json()
    p1 = next(p for p in pdata["projects"] if p["project_number"] == 1)
    p2 = next(p for p in pdata["projects"] if p["project_number"] == 2)
    assert p1["is_unlocked"] is True, "Mini Project 01 must be unlocked"
    assert p1["status"] in ["Unlocked", "In Progress"], f"Mini Project 01 status should be Unlocked, got {p1['status']}"
    assert p2["is_unlocked"] is False, "Mini Project 02 must still be locked until modules 3 & 4 are complete"
    print("✓ TEST 4 PASSED: Student Projects API reports Mini Project 01 is Unlocked and Project 02 is Locked")

    # 8. Verify /api/student/projects/1 detail endpoint
    resp = requests.get(f"{BASE_URL}/api/student/projects/1", headers=headers)
    assert resp.status_code == 200
    p1_detail = resp.json()
    assert p1_detail["project"]["is_unlocked"] is True
    assert len(p1_detail["prerequisites"]) == 2
    assert all(pr["completed"] is True for pr in p1_detail["prerequisites"])
    print("✓ TEST 5 PASSED: Mini Project 01 Code Lab workspace is fully accessible with completed prerequisites")

    # 9. Verify Credit Balance (2 modules completed = 6 credits)
    resp = requests.get(f"{BASE_URL}/api/student/credits", headers=headers)
    assert resp.status_code == 200
    cred_summary = resp.json()
    assert cred_summary["credit_balance"] == 6, f"Expected 6 credits, got {cred_summary['credit_balance']}"
    print(f"✓ TEST 6 PASSED: Student credit wallet balance is {cred_summary['credit_balance']} credits (3 per completed module)")

    # 10. Test direct completion endpoint on Module 3
    resp = requests.post(f"{BASE_URL}/api/modules/3/complete", headers=headers)
    assert resp.status_code == 200
    m3_res = resp.json()
    assert m3_res["completed"] is True
    assert m3_res["next_module"]["order_index"] == 4
    assert m3_res["project_unlocked"] is None, "Project 2 should only unlock after Module 4"
    print("✓ TEST 7 PASSED: Module 3 direct complete unlocks Module 4")

    # 11. Complete Module 4 assessment quiz
    resp = requests.post(f"{BASE_URL}/api/modules/m04/submit-assessment", headers=headers, json={
        "answers": {
            "1": "To prevent perfect multicollinearity (dummy variable trap)",
            "2": "Project data onto orthogonal axes maximizing variance",
            "3": "A * B"
        }
    })
    assert resp.status_code == 200
    m4_res = resp.json()
    assert m4_res["passed"] is True, f"Module 4 quiz failed: {m4_res}"
    assert m4_res["project_unlocked"] is not None
    assert m4_res["project_unlocked"]["project_number"] == 2
    print("✓ TEST 8 PASSED: Completing Module 4 assessment unlocked Mini Project 02 Milestone Test!")

    print("\n=======================================================")
    print("🎉 ALL 8 MODULE UNLOCK & MINI PROJECT PROGRESSION E2E TESTS PASSED!")
    print("=======================================================")

if __name__ == "__main__":
    run_tests()
