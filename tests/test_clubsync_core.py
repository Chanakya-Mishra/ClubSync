import time
import pytest
from fastapi.testclient import TestClient
from backend.main import app, create_access_token, cleanup_expired_sessions
from backend.database import SessionLocal
from backend.models import User, Club, ClubDaySession, Attendance
from backend.services.qr_engine import generate_qr_payload
from datetime import datetime, timedelta
import secrets


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_1_health_and_bootstrap(client: TestClient, db):
    """Verifies ultra-fast health check and single round-trip bootstrap."""
    h_resp = client.get("/api/health")
    assert h_resp.status_code == 200
    assert h_resp.json()["status"] == "ok"

    user = db.query(User).first()
    token = create_access_token(user)
    boot_resp = client.get("/api/bootstrap", headers={"Authorization": f"Bearer {token}"})
    assert boot_resp.status_code == 200
    data = boot_resp.json()
    assert "user" in data
    assert "campuses" in data
    assert len(data["campuses"]) >= 3


def test_2_session_30_minute_auto_cleanup(client: TestClient, db):
    """Verifies that demo sessions are purged automatically after 30 minutes."""
    club = db.query(Club).first()
    old_time = datetime.utcnow() - timedelta(minutes=35)
    demo_sess = ClubDaySession(
        club_id=club.id,
        week_number=1,
        scheduled_date="2026-10-20",
        topic="Automated Cleanup Demo Session",
        format="DEMO",
        deliverable_desc="Test description",
        submission_deadline="2026-10-22",
        checkin_secret=secrets.token_hex(16),
        created_at=old_time,
    )
    db.add(demo_sess)
    db.commit()
    demo_id = demo_sess.id

    # Run cleanup
    cleanup_expired_sessions(db)
    found = db.query(ClubDaySession).filter(ClubDaySession.id == demo_id).first()
    assert found is None, "Demo session older than 30 mins must be purged automatically."


def test_3_rotating_qr_checkin_and_db_persistence(client: TestClient, db):
    """Verifies rotating QR token check-in, database persistence, and duplicate rejection."""
    club = db.query(Club).first()
    student = db.query(User).filter(User.role == "STUDENT").first()

    sess = ClubDaySession(
        club_id=club.id,
        week_number=1,
        scheduled_date="2026-10-21",
        topic="Live Automated QR Checkin Session",
        format="WORKSHOP",
        deliverable_desc="Test deliverable",
        submission_deadline="2026-10-23",
        checkin_secret=secrets.token_hex(16),
        checkin_status="OPEN",
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)

    qr_data = generate_qr_payload(sess.checkin_secret, sess.id)
    st_token = create_access_token(student)
    st_headers = {"Authorization": f"Bearer {st_token}"}

    # Perform check-in
    checkin_resp = client.post(
        f"/api/sessions/{sess.id}/checkin",
        json={"qr_token": qr_data["qr_token"]},
        headers=st_headers,
    )
    assert checkin_resp.status_code == 200
    data = checkin_resp.json()
    assert data["status"] in ("PRESENT", "LATE")

    # Verify record in DB
    att = db.query(Attendance).filter(Attendance.session_id == sess.id, Attendance.student_id == student.id).first()
    assert att is not None
    assert att.status == data["status"]

    # Re-checking in must report already checked in
    dup_resp = client.post(
        f"/api/sessions/{sess.id}/checkin",
        json={"qr_token": qr_data["qr_token"]},
        headers=st_headers,
    )
    assert dup_resp.status_code == 200
    assert dup_resp.json()["already_checked_in"] is True

    # Cleanup
    db.delete(sess)
    db.commit()


def test_4_dashboard_attendance_percentages(client: TestClient, db):
    """Verifies student and president attendance percentage computation on dashboard."""
    student = db.query(User).filter(User.role == "STUDENT").first()
    pres = db.query(User).filter(User.role == "PRESIDENT").first()

    s_token = create_access_token(student)
    s_dash = client.get("/api/dashboard/overview", headers={"Authorization": f"Bearer {s_token}"})
    assert s_dash.status_code == 200
    s_data = s_dash.json()
    assert "my_attendance" in s_data
    assert "attendance_percentage" in s_data["my_attendance"]

    p_token = create_access_token(pres)
    p_dash = client.get("/api/dashboard/overview", headers={"Authorization": f"Bearer {p_token}"})
    assert p_dash.status_code == 200
    p_data = p_dash.json()
    assert "president_club_summary" in p_data


def test_5_president_exclusive_attendance_tab_and_csv(client: TestClient, db):
    """Verifies that only presidents can access the attendance tab and export CSV."""
    pres = db.query(User).filter(User.role == "PRESIDENT").first()
    student = db.query(User).filter(User.role == "STUDENT").first()

    p_token = create_access_token(pres)
    s_token = create_access_token(student)

    # 1. Student must be rejected with 403 Forbidden
    st_resp = client.get("/api/president/club-attendance", headers={"Authorization": f"Bearer {s_token}"})
    assert st_resp.status_code == 403

    # 2. President access must succeed with 200 OK
    p_resp = client.get("/api/president/club-attendance", headers={"Authorization": f"Bearer {p_token}"})
    assert p_resp.status_code == 200
    p_data = p_resp.json()
    assert "summary" in p_data
    assert "members" in p_data

    # 3. CSV Export must succeed with text/csv
    csv_resp = client.get("/api/president/club-attendance/export-csv", headers={"Authorization": f"Bearer {p_token}"})
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]


def test_6_gzip_compression_and_cache_control(client: TestClient, db):
    """Verifies response compression and static asset caching headers."""
    pres = db.query(User).filter(User.role == "PRESIDENT").first()
    p_token = create_access_token(pres)

    # GZip compression
    r_gzip = client.get(
        "/api/dashboard/overview",
        headers={"Authorization": f"Bearer {p_token}", "Accept-Encoding": "gzip"},
    )
    assert r_gzip.status_code == 200
    assert r_gzip.headers.get("content-encoding") == "gzip"

    # Static asset caching
    r_logo = client.get("/logo.png")
    assert r_logo.status_code == 200
    assert "max-age" in r_logo.headers.get("cache-control", "")
