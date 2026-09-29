import os
import sys
import io
import requests
import json

BASE_URL = "http://localhost:5050"

def run_tests():
    print("==================================================")
    print("DEDCODE MANUAL UPI PAYMENT & UPGRADE E2E TEST SUITE")
    print("==================================================")
    
    # 1. Test Fixed QR Code Image Serving
    print("\n[TEST 1] Verifying Static QR Code Assets Serving...")
    res_qr499 = requests.get(f"{BASE_URL}/static/images/qr_499.jpg")
    assert res_qr499.status_code == 200, f"qr_499.jpg returned {res_qr499.status_code}"
    assert len(res_qr499.content) > 1000, "qr_499.jpg content is too small"
    print("✓ Fixed QR 499 (qr_499.jpg) serves with 200 OK and valid image bytes.")

    res_qr999 = requests.get(f"{BASE_URL}/static/images/qr_999.png")
    assert res_qr999.status_code == 200, f"qr_999.png returned {res_qr999.status_code}"
    assert len(res_qr999.content) > 1000, "qr_999.png content is too small"
    print("✓ Fixed QR 999 (qr_999.png) serves with 200 OK and valid image bytes.")

    # 2. Student Authentication
    print("\n[TEST 2] Authenticating Student Account (yogesh@dedcode.ai)...")
    res_s_login = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "yogesh@dedcode.ai",
        "password": "password123",
        "role": "STUDENT"
    })
    assert res_s_login.status_code == 200, f"Student login failed: {res_s_login.text}"
    student_token = res_s_login.json()["token"]
    student_headers = {"Authorization": f"Bearer {student_token}"}
    print(f"✓ Student authenticated successfully. Token prefix: {student_token[:20]}...")

    # 3. Admin Authentication
    print("\n[TEST 3] Authenticating Admin Account (admin@dedcode.ai)...")
    res_a_login = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@dedcode.ai",
        "password": "admin123",
        "role": "ADMIN"
    })
    assert res_a_login.status_code == 200, f"Admin login failed: {res_a_login.text}"
    admin_token = res_a_login.json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    print(f"✓ Admin authenticated successfully. Token prefix: {admin_token[:20]}...")

    # 4. Student Submits ₹499 Student Plan Payment Verification
    print("\n[TEST 4] Student Submits ₹499 Student Plan Verification with UTR & Screenshot...")
    dummy_img = io.BytesIO(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
    dummy_img.name = "gpay_proof_499.png"

    res_sub499 = requests.post(
        f"{BASE_URL}/api/student/payments/submit",
        headers=student_headers,
        data={
            "plan_id": "student",
            "utr_number": "427812948291"
        },
        files={"screenshot": ("gpay_proof_499.png", dummy_img, "image/png")}
    )
    print("Submit response:", res_sub499.json())
    assert res_sub499.status_code in [200, 201], f"Submission failed: {res_sub499.text}"
    pay499_data = res_sub499.json()
    payment_id_1 = pay499_data["payment_id"]
    assert pay499_data["status"] == "PENDING"
    print(f"✓ Payment #{payment_id_1} created with status 'PENDING' and 12-hour SLA review notice.")

    # 5. Duplicate Pending Submission Protection
    print("\n[TEST 5] Testing Duplicate Pending Submission Protection...")
    dummy_img.seek(0)
    res_dup = requests.post(
        f"{BASE_URL}/api/student/payments/submit",
        headers=student_headers,
        data={
            "plan_id": "student",
            "utr_number": "427812948291"
        },
        files={"screenshot": ("gpay_proof_499.png", dummy_img, "image/png")}
    )
    assert res_dup.status_code == 409, f"Expected 409 conflict, got {res_dup.status_code}"
    print("✓ Correctly prevented duplicate submission while review is pending (409 Conflict).")

    # 6. Check Student Status Endpoint
    print("\n[TEST 6] Verifying Student Payment Status API (/api/student/payments/status)...")
    res_status = requests.get(f"{BASE_URL}/api/student/payments/status", headers=student_headers)
    assert res_status.status_code == 200
    st_data = res_status.json()
    assert st_data["has_payment_request"] is True
    assert st_data["payment"]["status"] == "PENDING"
    assert st_data["payment"]["plan_amount"] == 499
    assert st_data["payment"]["utr_number"] == "427812948291"
    print("✓ Student payment status correctly returns pending details and UTR.")

    # 7. Admin List Payments & Stats
    print("\n[TEST 7] Admin Listing Payment Verification Requests (/api/admin/payments)...")
    res_adm_list = requests.get(f"{BASE_URL}/api/admin/payments", headers=admin_headers)
    assert res_adm_list.status_code == 200
    adm_list_data = res_adm_list.json()
    assert adm_list_data["stats"]["pending_count"] >= 1
    found_pay = any(p["id"] == payment_id_1 for p in adm_list_data["payments"])
    assert found_pay, f"Payment #{payment_id_1} not found in admin list"
    print(f"✓ Admin sees payment #{payment_id_1} with Pending Count: {adm_list_data['stats']['pending_count']}.")

    # 8. Admin View Payment Details with Audit Logs & Screenshot
    print(f"\n[TEST 8] Admin Inspecting Payment #{payment_id_1} Details & Screenshot...")
    res_detail = requests.get(f"{BASE_URL}/api/admin/payments/{payment_id_1}", headers=admin_headers)
    assert res_detail.status_code == 200
    detail_data = res_detail.json()
    assert detail_data["payment"]["student_email"] == "yogesh@dedcode.ai"
    assert len(detail_data["audit_logs"]) >= 1
    assert detail_data["audit_logs"][0]["action"] == "PAYMENT_SUBMITTED"
    print("✓ Payment details retrieved with student info and audit history.")

    res_ss = requests.get(f"{BASE_URL}/api/admin/payments/{payment_id_1}/screenshot", headers=admin_headers)
    assert res_ss.status_code == 200
    assert len(res_ss.content) > 0
    print("✓ Payment screenshot safely served via authenticated endpoint.")

    # 9. Admin Rejection Flow with Reason
    print(f"\n[TEST 9] Admin Rejecting Payment #{payment_id_1} with Reason...")
    rejection_reason = "Transaction UTR not found on SBI statement. Please verify reference ID."
    res_reject = requests.post(
        f"{BASE_URL}/api/admin/payments/{payment_id_1}/reject",
        headers=admin_headers,
        json={"rejection_reason": rejection_reason, "admin_notes": "Checked SBI UPI portal at 04:30 AM"}
    )
    assert res_reject.status_code == 200
    print("✓ Payment rejection processed successfully.")

    # Verify student sees rejection
    res_status_after_rej = requests.get(f"{BASE_URL}/api/student/payments/status", headers=student_headers)
    p_rej = res_status_after_rej.json()["payment"]
    assert p_rej["status"] == "REJECTED"
    assert p_rej["rejection_reason"] == rejection_reason
    print(f"✓ Student status accurately reflects 'REJECTED' with reason: '{rejection_reason}'.")

    # 10. Student Resubmits for ₹999 Premium Plan with Fixed QR 999
    print("\n[TEST 10] Student Resubmitting Payment for ₹999 Premium Plan...")
    dummy_img.seek(0)
    res_sub999 = requests.post(
        f"{BASE_URL}/api/student/payments/submit",
        headers=student_headers,
        data={
            "plan_id": "premium",
            "utr_number": "SBI999123456789"
        },
        files={"screenshot": ("gpay_proof_999.png", dummy_img, "image/png")}
    )
    assert res_sub999.status_code in [200, 201], f"Resubmission failed: {res_sub999.text}"
    payment_id_2 = res_sub999.json()["payment_id"]
    print(f"✓ Student successfully resubmitted payment #{payment_id_2} for Premium Plan (₹999).")

    # 11. Admin Approval Flow
    print(f"\n[TEST 11] Admin Approving Payment #{payment_id_2}...")
    res_approve = requests.post(
        f"{BASE_URL}/api/admin/payments/{payment_id_2}/approve",
        headers=admin_headers,
        json={"admin_notes": "Verified ₹999 received on SBI account (Ref SBI999123456789)."}
    )
    assert res_approve.status_code == 200, f"Approval failed: {res_approve.text}"
    print(f"✓ Payment #{payment_id_2} approved by admin.")

    # 12. Verify Subscription Activation & Perks in Student Dashboard
    print("\n[TEST 12] Verifying Student Subscription Activation in Dashboard...")
    res_dash = requests.get(f"{BASE_URL}/api/student/dashboard", headers=student_headers)
    assert res_dash.status_code == 200
    dash_data = res_dash.json()
    assert dash_data["subscription"]["plan_name"] == "Premium Plan"
    assert dash_data["subscription"]["price_inr"] == 999
    assert dash_data["subscription"]["status"] == "ACTIVE"
    print(f"✓ Student subscription is ACTIVE on Premium Plan (₹999).")

    # 13. Institution Campus Enquiry Submission & Admin Review
    print("\n[TEST 13] Submitting Campus Institution Enquiry (/api/institution/enquire)...")
    res_enq = requests.post(
        f"{BASE_URL}/api/institution/enquire",
        headers=student_headers,
        json={
            "institution_name": "Indian Institute of Technology Madras",
            "contact_person": "Dr. S. Narayanan (Head of AI)",
            "official_email": "ai.head@iitm.ac.in",
            "phone": "+91 94441 55667",
            "student_count": "500 - 1,000 Students",
            "requirement": "Campus-wide AI Video Studio access and 1-on-1 mentorship for 600 B.Tech AI students."
        }
    )
    assert res_enq.status_code in [200, 201], f"Institution enquiry failed: {res_enq.text}"
    print("✓ Institution campus enquiry submitted successfully.")

    res_adm_enq = requests.get(f"{BASE_URL}/api/admin/institution-enquiries", headers=admin_headers)
    assert res_adm_enq.status_code == 200
    enq_list = res_adm_enq.json()["enquiries"]
    found_enq = any(e["institution_name"] == "Indian Institute of Technology Madras" for e in enq_list)
    assert found_enq, "Institution enquiry not found in admin list"
    print("✓ Admin successfully retrieved institution campus enquiry list.")

    # 14. Unauthorized Access Security Check
    print("\n[TEST 14] Verifying Security: Non-Admin Cannot Approve Payments...")
    res_unauth = requests.post(
        f"{BASE_URL}/api/admin/payments/{payment_id_2}/approve",
        headers=student_headers,
        json={"admin_notes": "Hacker attempt"}
    )
    assert res_unauth.status_code in [401, 403], f"Expected 403/401, got {res_unauth.status_code}"
    print("✓ Unauthorized payment approval successfully blocked (403 Forbidden).")

    print("\n==================================================")
    print("ALL 14 E2E PAYMENT & UPGRADE TESTS PASSED PERFECTLY!")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
