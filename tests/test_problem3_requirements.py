import io
import time
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import Base, engine, SessionLocal
from backend.models import (
    User,
    Club,
    ClubDaySession,
    Attendance,
    Submission,
    Evaluation,
    Certificate,
    Event,
    EventRegistration,
)
from backend.seed import seed_database


@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()
    with TestClient(app) as c:
        yield c


def test_1_end_to_end_club_day_flow_for_3_clubs(client: TestClient):
    """
    Section 6 Test Area 1:
    'End-to-end Club Day: Full flow for 3 clubs: plan -> approve -> check-in -> submit -> evaluate -> report'
    """
    clubs_to_test = [
        ("club-ai-hitech", "user-coord-ai", "user-advisor-ai", 17.4435, 78.3772),
        ("club-robo-ratnam", "user-coord-robo", "user-advisor-robo", 14.4426, 79.9865),
        ("club-debate-rgib", "user-coord-debate", "user-advisor-debate", 12.9716, 77.5946),
    ]

    for club_id, coord_id, advisor_id, lat, lng in clubs_to_test:
        # 1. PLAN: Coordinator submits Saturday Club Day activity plan
        plan_resp = client.post(
            "/api/sessions",
            headers={"X-User-Id": coord_id},
            json={
                "club_id": club_id,
                "week_number": 8,
                "scheduled_date": "2026-11-07",
                "topic": f"E2E Automated Verification Session for {club_id}",
                "format": "PPT",
                "venue": "Main Seminar Hall",
                "deliverable_desc": "10-slide PPT + GitHub Prototype",
                "submission_deadline": "2026-11-09 23:59",
            },
        )
        assert plan_resp.status_code == 200
        session_id = plan_resp.json()["id"]
        assert plan_resp.json()["plan_status"] == "PENDING_APPROVAL"

        # 2. APPROVE: Faculty Advisor approves the activity plan
        app_resp = client.patch(
            f"/api/sessions/{session_id}/approval",
            headers={"X-User-Id": advisor_id},
            json={"plan_status": "APPROVED", "advisor_feedback": "Approved for Saturday Club Day."},
        )
        assert app_resp.status_code == 200
        assert app_resp.json()["plan_status"] == "APPROVED"

        # 3. CHECK-IN: Coordinator opens window -> Student scans live QR -> Coordinator marks presenter
        open_resp = client.post(
            f"/api/sessions/{session_id}/checkin-window",
            headers={"X-User-Id": coord_id},
            json={"action": "OPEN", "duration_minutes": 45, "late_after_minutes": 15},
        )
        assert open_resp.status_code == 200
        assert open_resp.json()["checkin_status"] == "OPEN"

        qr_resp = client.get(f"/api/sessions/{session_id}/qr")
        assert qr_resp.status_code == 200
        qr_token = qr_resp.json()["qr_token"]

        checkin_resp = client.post(
            f"/api/sessions/{session_id}/checkin",
            headers={"X-User-Id": "user-student-1"},
            json={
                "student_id": "user-student-1",
                "qr_token": qr_token,
                "lat": lat + 0.0001,
                "lng": lng + 0.0001,
            },
        )
        assert checkin_resp.status_code == 200
        assert checkin_resp.json()["status"] == "PRESENT"

        # 4. RUN: Coordinator marks student as presenter
        pres_resp = client.patch(
            f"/api/sessions/{session_id}/presenter",
            headers={"X-User-Id": coord_id},
            json={
                "student_id": "user-student-1",
                "is_presenter": True,
                "activity_result": "Top Presenter Award",
            },
        )
        assert pres_resp.status_code == 200
        assert pres_resp.json()["is_presenter"] is True

        # 5. SUBMIT: Student uploads deliverable
        sub_resp = client.post(
            f"/api/sessions/{session_id}/submissions",
            headers={"X-User-Id": "user-student-1"},
            json={
                "student_id": "user-student-1",
                "title": f"Slide Deck for {club_id}",
                "deliverable_type": "PPT",
                "external_link": f"https://github.com/msot/{club_id}-e2e",
            },
        )
        assert sub_resp.status_code == 200
        sub_id = sub_resp.json()["id"]

        # 6. EVALUATE: Advisor/Coordinator grades submission on 3-part rubric
        eval_resp = client.post(
            f"/api/submissions/{sub_id}/evaluate",
            headers={"X-User-Id": advisor_id},
            json={
                "content_score": 9.5,
                "presentation_score": 9.0,
                "participation_score": 10.0,
                "comments": "Excellent E2E presentation.",
            },
        )
        assert eval_resp.status_code == 200
        assert eval_resp.json()["total_score"] == 28.5

        # 7. REPORT: Monthly club report reflects updated attendance, submissions, and rubric average
        rep_resp = client.get(f"/api/reports/monthly?club_id={club_id}")
        assert rep_resp.status_code == 200
        club_rep = rep_resp.json()["club_reports"][0]
        assert club_rep["sessions_conducted"] >= 4
        assert club_rep["total_submissions"] >= 1
        assert club_rep["average_rubric_score"] > 0


def test_2_checkin_integrity_screenshot_late_and_geofence(client: TestClient):
    """
    Section 6 Test Area 2:
    'Check-in integrity: Screenshot sharing, late check-in and check-in from outside campus (if geo-check used): what happens in each case'
    """
    session_id = "sess-msot-ai-club-wk4"

    # Ensure check-in window is open
    client.post(
        f"/api/sessions/{session_id}/checkin-window",
        headers={"X-User-Id": "user-coord-ai"},
        json={"action": "OPEN", "duration_minutes": 60, "late_after_minutes": 15},
    )

    # Case A: Screenshot Sharing (60-second-old expired QR token) -> Must be REJECTED (403 EXPIRED_QR_SCREENSHOT)
    exp_qr = client.get(f"/api/sessions/{session_id}/qr-expired-test").json()["qr_token"]
    screenshot_resp = client.post(
        f"/api/sessions/{session_id}/checkin",
        headers={"X-User-Id": "user-student-15"},
        json={
            "student_id": "user-student-15",
            "qr_token": exp_qr,
            "lat": 17.4435,
            "lng": 78.3772,
        },
    )
    assert screenshot_resp.status_code == 403
    assert screenshot_resp.json()["detail"]["code"] == "EXPIRED_QR_SCREENSHOT"

    # Case B: Outside Campus Geofence (4.5km away from HI-Tech Campus) -> Must be REJECTED (403 OUTSIDE_CAMPUS_GEOFENCE)
    live_qr = client.get(f"/api/sessions/{session_id}/qr").json()["qr_token"]
    offcampus_resp = client.post(
        f"/api/sessions/{session_id}/checkin",
        headers={"X-User-Id": "user-student-16"},
        json={
            "student_id": "user-student-16",
            "qr_token": live_qr,
            "lat": 17.4850,  # > 4.5 km away
            "lng": 78.4150,
        },
    )
    assert offcampus_resp.status_code == 403
    assert offcampus_resp.json()["detail"]["code"] == "OUTSIDE_CAMPUS_GEOFENCE"

    # Case C: Late Check-In (25 minutes after session start, after 15m grace window) -> Accepted & Flagged LATE
    late_resp = client.post(
        f"/api/sessions/{session_id}/checkin",
        headers={"X-User-Id": "user-student-17"},
        json={
            "student_id": "user-student-17",
            "qr_token": live_qr,
            "lat": 17.4436,
            "lng": 78.3773,
            "simulated_check_time_offset_min": 25,
        },
    )
    assert late_resp.status_code == 200
    assert late_resp.json()["status"] == "LATE"


def test_3_twenty_certificates_and_tampered_pdf_detection(client: TestClient):
    """
    Section 6 Test Area 3:
    'Certificates: 20 certificates generated; each verification link opens the correct record; tampered PDF fails verification'
    """
    certs_resp = client.get("/api/certificates")
    assert certs_resp.status_code == 200
    certs = certs_resp.json()
    assert len(certs) >= 20, f"Expected at least 20 certificates, found {len(certs)}"

    # Verify all 20 verification links open the exact matching student record
    for cert in certs[:20]:
        serial = cert["serial_number"]
        v_resp = client.get(f"/api/verify/{serial}")
        assert v_resp.status_code == 200
        v_data = v_resp.json()
        assert v_data["verified"] is True
        assert v_data["serial_number"] == serial
        assert v_data["recipient"]["full_name"] == cert["student_name"]
        assert v_data["cryptographic_proof"]["pdf_sha256_hash"] == cert["pdf_sha256_hash"]

    # Download genuine PDF #1 and verify it passes cryptographic SHA-256 verification
    dl_resp = client.get("/api/certificates/MSOT-CERT-2026-0001/download")
    assert dl_resp.status_code == 200
    genuine_pdf_bytes = dl_resp.content

    valid_upload = client.post(
        "/api/verify/pdf",
        files={"file": ("MSOT-CERT-2026-0001.pdf", io.BytesIO(genuine_pdf_bytes), "application/pdf")},
        data={"expected_serial": "MSOT-CERT-2026-0001"},
    )
    assert valid_upload.status_code == 200
    assert valid_upload.json()["verified"] is True
    assert valid_upload.json()["status"] == "AUTHENTIC_UNTAMPERED_PDF"

    # Tamper with the PDF bytes (simulate modifying text/metadata in the PDF) -> MUST FAIL VERIFICATION
    tampered_pdf_bytes = genuine_pdf_bytes + b"\n%UNAUTHORIZED_SCORE_MODIFICATION\n"
    tampered_upload = client.post(
        "/api/verify/pdf",
        files={"file": ("MSOT-CERT-2026-0001-tampered.pdf", io.BytesIO(tampered_pdf_bytes), "application/pdf")},
        data={"expected_serial": "MSOT-CERT-2026-0001"},
    )
    assert tampered_upload.status_code == 200
    t_json = tampered_upload.json()
    assert t_json["verified"] is False
    assert t_json["status"] == "TAMPERED_PDF_DETECTED"


def test_4_event_with_200_registrations_and_team_formation(client: TestClient):
    """
    Section 6 Test Area 4:
    'Events: Event with 200 registrations and team formation runs without duplicates or lost entries'
    """
    # Create a dedicated stress-test event for 200 students forming 50 teams of 4
    ev_resp = client.post(
        "/api/events",
        headers={"X-User-Id": "user-admin-1"},
        json={
            "code": f"MSOT-GAMBADE-200-{int(time.time())}",
            "title": "Gambade 200-Student Team Formation Stress Event",
            "category": "GAMBADE",
            "scope": "INTER_CAMPUS",
            "description": "Automated verification of 200 student registrations across 50 teams of 4.",
            "venue": "HI-Tech Stadium",
            "start_date": "2026-11-15",
            "end_date": "2026-11-16",
            "max_team_size": 4,
            "capacity": 500,
            "duty_leave_eligible": True,
        },
    )
    assert ev_resp.status_code == 200
    event_id = ev_resp.json()["id"]

    # Ensure 200 student users exist in DB
    db = SessionLocal()
    try:
        existing_ids = {u.id for u in db.query(User).all()}
        new_users = []
        for i in range(1, 205):
            uid = f"user-ev200-{i}"
            if uid not in existing_ids:
                new_users.append(
                    User(
                        id=uid,
                        email=f"ev200.{i}@msot.org",
                        full_name=f"Event Student {i}",
                        roll_number=f"MSOT-EV200-{i:03d}",
                        role="STUDENT",
                    )
                )
        if new_users:
            db.add_all(new_users)
            db.commit()
    finally:
        db.close()

    # Register 200 students: 50 team leaders create a team, and 150 members join those 50 teams (3 per team)
    invite_codes = []
    for t_idx in range(1, 51):
        leader_id = f"user-ev200-{t_idx}"
        r = client.post(
            f"/api/events/{event_id}/register",
            headers={"X-User-Id": leader_id},
            json={
                "student_id": leader_id,
                "mode": "CREATE_TEAM",
                "team_name": f"Gambade Squad {t_idx}",
                "project_title": f"Autonomous Bot #{t_idx}",
            },
        )
        assert r.status_code == 200
        invite_codes.append(r.json()["invite_code"])

    # Remaining 150 students join the 50 teams (3 members per team -> total 4 per team = 200 registrations)
    student_cursor = 51
    for code in invite_codes:
        for _ in range(3):
            st_id = f"user-ev200-{student_cursor}"
            student_cursor += 1
            jr = client.post(
                f"/api/events/{event_id}/register",
                headers={"X-User-Id": st_id},
                json={"student_id": st_id, "mode": "JOIN_TEAM", "invite_code": code},
            )
            assert jr.status_code == 200

    # Attempt duplicate registration for user-ev200-1 -> MUST be rejected (400)
    dup_resp = client.post(
        f"/api/events/{event_id}/register",
        headers={"X-User-Id": "user-ev200-1"},
        json={"student_id": "user-ev200-1", "mode": "INDIVIDUAL"},
    )
    assert dup_resp.status_code == 400

    # Verify exact count in DB: 200 registrations, 0 duplicates, 0 lost entries, 50 teams
    events_list = client.get("/api/events").json()
    target_ev = next(e for e in events_list if e["id"] == event_id)
    assert target_ev["total_registrations"] == 200
    assert len(target_ev["teams"]) == 50
    assert all(t["member_count"] == 4 for t in target_ev["teams"])


def test_5_rbac_permissions_enforcement(client: TestClient):
    """
    Section 6 Test Area 5:
    'Permissions: Coordinators see only their own club; students cannot edit attendance or scores'
    """
    # 1. Student attempting to override attendance -> 403 Forbidden
    st_att = client.post(
        "/api/sessions/sess-msot-ai-club-wk4/attendance/override",
        headers={"X-User-Id": "user-student-1"},
        json={"student_id": "user-student-1", "status": "PRESENT", "reason": "Trying to self-approve"},
    )
    assert st_att.status_code == 403

    # 2. Student attempting to score a submission -> 403 Forbidden
    details = client.get("/api/sessions/sess-msot-ai-club-wk1/details").json()
    sub_id = details["submissions"][0]["id"]
    st_eval = client.post(
        f"/api/submissions/{sub_id}/evaluate",
        headers={"X-User-Id": "user-student-1"},
        json={"content_score": 10, "presentation_score": 10, "participation_score": 10, "comments": "Self grade"},
    )
    assert st_eval.status_code == 403

    # 3. Coordinator of AI Club (user-coord-ai) attempting to override attendance or plan session in Robotics Club (club-robo-ratnam) -> 403 Forbidden
    cross_club_plan = client.post(
        "/api/sessions",
        headers={"X-User-Id": "user-coord-ai"},
        json={
            "club_id": "club-robo-ratnam",
            "week_number": 9,
            "scheduled_date": "2026-11-14",
            "topic": "Unauthorized Cross-Club Plan",
            "deliverable_desc": "None",
            "submission_deadline": "2026-11-16 23:59",
        },
    )
    assert cross_club_plan.status_code == 403

    cross_club_override = client.post(
        "/api/sessions/sess-msot-robo-club-wk1/attendance/override",
        headers={"X-User-Id": "user-coord-ai"},
        json={"student_id": "user-student-2", "status": "PRESENT", "reason": "Cross club attempt"},
    )
    assert cross_club_override.status_code == 403


def test_6_monthly_report_matches_raw_attendance_and_submission_data(client: TestClient):
    """
    Section 6 Test Area 6:
    'Reports: Monthly report figures match the raw attendance and submission data'
    """
    rep_data = client.get("/api/reports/monthly").json()["club_reports"]
    db = SessionLocal()
    try:
        for club_rep in rep_data:
            cid = club_rep["club_id"]
            sessions = db.query(ClubDaySession).filter(ClubDaySession.club_id == cid).all()
            active_sids = [s.id for s in sessions if s.checkin_status in ("OPEN", "COMPLETED")]

            raw_att_count = (
                db.query(Attendance)
                .filter(Attendance.session_id.in_(active_sids), Attendance.status.in_(["PRESENT", "LATE"]))
                .count()
                if active_sids
                else 0
            )
            raw_subs = (
                db.query(Submission).filter(Submission.session_id.in_(active_sids)).all()
                if active_sids
                else []
            )
            raw_scores = [s.evaluation.total_score for s in raw_subs if s.evaluation is not None]
            expected_avg = round(sum(raw_scores) / len(raw_scores), 2) if raw_scores else 0.0

            assert club_rep["actual_verified_checkins"] == raw_att_count
            assert club_rep["total_submissions"] == len(raw_subs)
            assert club_rep["average_rubric_score"] == expected_avg
    finally:
        db.close()


def test_7_middle_three_stretch_goals(client: TestClient):
    """
    Verifies the Middle 3 Stretch Goals:
    1. Club budget & expense requests with approval workflow
    2. Duty Leave request generated automatically for approved inter-college events, ready for CM approval
    3. Photo / media gallery per event with student consent controls
    """
    # Stretch 1: Budget Request -> Advisor Endorses -> Campus Manager Approves
    b_resp = client.post(
        "/api/budgets",
        headers={"X-User-Id": "user-coord-ai"},
        json={
            "club_id": "club-ai-hitech",
            "title": "Microcontroller & Edge Camera Array",
            "amount_inr": 12000.0,
            "description": "For Saturday AI Vision build sprint",
        },
    )
    assert b_resp.status_code == 200
    bid = b_resp.json()["id"]
    assert b_resp.json()["status"] == "PENDING_ADVISOR"

    adv_b = client.patch(
        f"/api/budgets/{bid}/approve",
        headers={"X-User-Id": "user-advisor-ai"},
        json={"decision": "APPROVE", "notes": "Endorsed by Advisor"},
    )
    assert adv_b.status_code == 200
    assert adv_b.json()["status"] == "PENDING_CAMPUS_MGR"

    cm_b = client.patch(
        f"/api/budgets/{bid}/approve",
        headers={"X-User-Id": "user-cm-hitech"},
        json={"decision": "APPROVE", "notes": "Final Campus Manager approval granted"},
    )
    assert cm_b.status_code == 200
    assert cm_b.json()["status"] == "APPROVED"

    # Stretch 2: Registering for Inter-College Conference auto-generates Duty Leave -> CM approves
    dl_list = client.get("/api/duty-leaves").json()
    assert len(dl_list) >= 1
    pending_dl = next((d for d in dl_list if d["status"] == "PENDING_CM_APPROVAL"), dl_list[0])
    dl_app = client.patch(
        f"/api/duty-leaves/{pending_dl['id']}/approve",
        headers={"X-User-Id": "user-cm-hitech"},
        json={"status": "APPROVED"},
    )
    assert dl_app.status_code == 200
    assert dl_app.json()["status"] == "APPROVED"

    # Stretch 3: Media Gallery Consent Control hides non-consented photos from public feed
    public_gal_before = client.get("/api/gallery?include_hidden=false").json()
    target_media_id = public_gal_before[0]["id"]

    revoke_resp = client.patch(
        f"/api/gallery/{target_media_id}/consent",
        json={"student_consent": False},
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["student_consent"] is False

    public_gal_after = client.get("/api/gallery?include_hidden=false").json()
    assert all(item["id"] != target_media_id for item in public_gal_after)

    # Restore consent
    client.patch(f"/api/gallery/{target_media_id}/consent", json={"student_consent": True})
