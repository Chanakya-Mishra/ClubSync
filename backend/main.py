import os
import io
import csv
import hmac
import time
import base64
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, Header, UploadFile, File, Form, Query, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from .database import engine, Base, get_db, SessionLocal, get_database_info, upload_to_supabase_storage, DATA_DIR, DATABASE_URL
from .models import (
    SystemConfig,
    Campus,
    User,
    Club,
    ClubMembership,
    ClubDaySession,
    Attendance,
    Submission,
    Evaluation,
    Event,
    EventTeam,
    EventRegistration,
    Certificate,
    BudgetRequest,
    DutyLeaveRequest,
    MediaGalleryItem,
    ClubNews,
    AuditLog,
    PasswordResetOTP,
)
from .services.qr_engine import (
    generate_qr_payload,
    verify_checkin_token_or_otp,
    haversine_distance_m,
)
from .services.pdf_engine import (
    CERT_DIR,
    generate_certificate_pdf,
    generate_transcript_pdf,
)
from .services.email_engine import (
    send_password_reset_otp_email,
    send_account_approved_email,
    send_session_announced_email,
    send_club_news_email,
)
from .seed import seed_database

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(CERT_DIR, exist_ok=True)

AUTH_SECRET = os.environ.get("MSOT_AUTH_SECRET", "msot-auth-token-secret-2026")

app = FastAPI(
    title="ClubSync — Multi-Campus Club Activities Tracker API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.middleware("http")
async def add_performance_and_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") or path in ("/logo.png", "/favicon.ico"):
        if path.endswith((".png", ".jpg", ".jpeg", ".svg", ".ico", ".woff2", ".ttf")):
            response.headers["Cache-Control"] = "public, max-age=86400, stale-while-revalidate=604800"
        elif path.endswith((".js", ".css")):
            response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=86400"
    elif path == "/" or path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


_db_initialized = False


def init_db_and_defaults():
    global _db_initialized
    if _db_initialized:
        return
    # Only run table creation & seeding on local SQLite. Supabase PostgreSQL is permanent and pre-seeded.
    # This prevents running 100,000 PBKDF2 hash cycles and redundant DB queries on every Vercel cold start!
    if DATABASE_URL.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            seed_database(db)
        finally:
            db.close()
    _db_initialized = True


@app.on_event("startup")
def on_startup():
    init_db_and_defaults()


@app.get("/api/health")
def api_health_check():
    """Ultra-fast, zero-query health check for keeping serverless containers warm."""
    return {"status": "ok", "time": int(time.time())}


# ============================================================================
# Password Hashing & Token Helpers
# ============================================================================

def hash_password(password: str, salt: Optional[str] = None) -> str:
    s = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), s.encode("utf-8"), 100_000)
    return f"{s}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash or "$" not in stored_hash:
        return False
    salt, _ = stored_hash.split("$", 1)
    return hmac.compare_digest(hash_password(password, salt), stored_hash)


import json as _json


def create_access_token(user_or_id: Any) -> str:
    exp = int(time.time()) + 86400 * 7
    if isinstance(user_or_id, str):
        claims = {"uid": user_or_id, "exp": exp}
    else:
        u = user_or_id
        claims = {
            "uid": u.id,
            "exp": exp,
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role,
            "account_status": getattr(u, "account_status", "APPROVED") or "APPROVED",
            "campus_id": u.campus_id,
            "roll_number": u.roll_number,
            "batch": u.batch,
            "track": u.track,
            "password_hash": u.password_hash,
        }
    payload_b64 = base64.urlsafe_b64encode(_json.dumps(claims, separators=(",", ":")).encode("utf-8")).decode("ascii")
    sig = hmac.new(AUTH_SECRET.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def decode_access_token_claims(token: str) -> Optional[Dict[str, Any]]:
    try:
        if "." in token:
            payload_b64, sig = token.split(".", 1)
            expected_sig = hmac.new(
                AUTH_SECRET.encode("utf-8"),
                payload_b64.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(sig, expected_sig):
                return None
            claims = _json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8"))
            if int(claims.get("exp", 0)) < int(time.time()):
                return None
            return claims
        else:
            decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
            user_id, exp_str, sig = decoded.split(":", 2)
            if int(exp_str) < int(time.time()):
                return None
            expected_sig = hmac.new(
                AUTH_SECRET.encode("utf-8"),
                f"{user_id}:{exp_str}".encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(sig, expected_sig):
                return None
            return {"uid": user_id, "exp": int(exp_str)}
    except Exception:
        return None


def decode_access_token(token: str) -> Optional[str]:
    claims = decode_access_token_claims(token)
    return claims.get("uid") if claims else None


def get_current_user(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
) -> User:
    user_id = None
    claims = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "", 1).strip()
        claims = decode_access_token_claims(token)
        if claims:
            user_id = claims.get("uid")
    if not user_id and x_user_id:
        user_id = x_user_id

    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required. Please log in.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user and claims and claims.get("email"):
        # Auto-rehydrate verified user if hitting a fresh serverless container with ephemeral SQLite
        existing_by_email = db.query(User).filter(User.email == claims["email"]).first()
        if existing_by_email:
            user = existing_by_email
        else:
            user = User(
                id=claims["uid"],
                email=claims["email"],
                full_name=claims.get("full_name", "User"),
                role=claims.get("role", "STUDENT"),
                account_status=claims.get("account_status", "APPROVED"),
                campus_id=claims.get("campus_id"),
                roll_number=claims.get("roll_number"),
                batch=claims.get("batch", "2025-2029 B.Tech"),
                track=claims.get("track", "Mirai Track"),
                password_hash=claims.get("password_hash"),
            )
            db.add(user)
            try:
                db.commit()
                db.refresh(user)
            except Exception:
                db.rollback()
                user = db.query(User).filter(User.email == claims["email"]).first()

    if not user:
        raise HTTPException(status_code=401, detail="User session not found. Please log in again.")
    if getattr(user, "account_status", "APPROVED") != "APPROVED":
        raise HTTPException(
            status_code=403,
            detail="Your account is pending Admin approval. You will be able to access ClubSync once permitted by the Admin.",
        )
    return user


def verify_coordinator_club_access(db: Session, user: User, club_id: str):
    """Enforces RBAC: Coordinators can only manage their own club."""
    if user.role == "ADMIN":
        return
    if user.role == "CAMPUS_MGR":
        club = db.query(Club).filter(Club.id == club_id).first()
        if club and (not user.campus_id or club.campus_id == user.campus_id):
            return
        raise HTTPException(status_code=403, detail="Campus Manager can only manage clubs in their own campus.")
    if user.role == "ADVISOR":
        club = db.query(Club).filter(Club.id == club_id).first()
        if club and (not club.advisor_id or club.advisor_id == user.id):
            return
        raise HTTPException(status_code=403, detail="Faculty Advisor can only manage their assigned club.")
    if user.role in ("COORDINATOR", "PRESIDENT"):
        coord_mem = (
            db.query(ClubMembership)
            .filter(
                ClubMembership.club_id == club_id,
                ClubMembership.student_id == user.id,
                ClubMembership.tier.in_(["COORDINATOR", "PRESIDENT"]),
                ClubMembership.status == "APPROVED",
            )
            .first()
        )
        if not coord_mem:
            raise HTTPException(
                status_code=403,
                detail="Club Presidents / Coordinators can only manage their own assigned club.",
            )
        return
    raise HTTPException(status_code=403, detail=f"Role '{user.role}' is not permitted to perform this action.")


# ============================================================================
# Pydantic Schemas
# ============================================================================

class RegisterRequest(BaseModel):
    full_name: str
    email: str
    password: str
    role: str = "STUDENT"  # STUDENT | COORDINATOR | ADVISOR | CAMPUS_MGR | ADMIN
    campus_id: Optional[str] = None
    roll_number: Optional[str] = None
    batch: Optional[str] = "2025-2029 B.Tech"
    track: Optional[str] = "Mirai Track"


class LoginRequest(BaseModel):
    email: str
    password: str


class ClubCreateRequest(BaseModel):
    campus_id: str
    code: str
    name: str
    category: str
    description: str
    advisor_id: Optional[str] = None
    coordinator_id: Optional[str] = None
    capacity: int = 60
    meeting_rules: str = "Every Saturday, 09:30 AM - 11:30 AM"


class EnrolRequest(BaseModel):
    tier: str = Field(default="PRIMARY", description="PRIMARY or SECONDARY")
    student_id: Optional[str] = None


class EnrolmentStatusUpdate(BaseModel):
    status: str = Field(..., description="APPROVED or REJECTED")


class SessionPlanCreate(BaseModel):
    club_id: str
    week_number: int = 1
    scheduled_date: str
    topic: str
    format: str = "PPT"
    venue: str = "Auditorium"
    deliverable_desc: str
    submission_deadline: str


class SessionApprovalUpdate(BaseModel):
    plan_status: str = Field(..., description="APPROVED or CHANGES_REQUESTED")
    advisor_feedback: str = ""


class CheckinWindowUpdate(BaseModel):
    action: str = Field(..., description="OPEN or CLOSE")
    duration_minutes: int = 30
    late_after_minutes: int = 15


class StudentCheckinRequest(BaseModel):
    student_id: Optional[str] = None
    qr_token: Optional[str] = None
    otp_code: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    simulated_check_time_offset_min: Optional[int] = 0


class ManualAttendanceOverrideRequest(BaseModel):
    student_id: str
    status: str = Field(default="PRESENT", description="PRESENT, LATE, EXCUSED, ABSENT")
    reason: str = Field(..., description="Mandatory reason for coordinator override")


class PresenterUpdateRequest(BaseModel):
    student_id: str
    is_presenter: bool = True
    activity_result: Optional[str] = None
    on_the_spot_notes: Optional[str] = None


class SubmissionCreateRequest(BaseModel):
    student_id: Optional[str] = None
    title: str
    deliverable_type: str = "PPT"
    file_url: Optional[str] = None
    external_link: Optional[str] = None
    notes: Optional[str] = None


class EvaluationCreateRequest(BaseModel):
    content_score: float = Field(..., ge=0, le=10)
    presentation_score: float = Field(..., ge=0, le=10)
    participation_score: float = Field(..., ge=0, le=10)
    comments: str = ""


class EventCreateRequest(BaseModel):
    campus_id: Optional[str] = None
    code: str
    title: str
    category: str = "HACKATHON"
    scope: str = "INTER_CAMPUS"
    description: str
    venue: str
    start_date: str
    end_date: str
    max_team_size: int = 4
    capacity: int = 500
    duty_leave_eligible: bool = True


class EventRegisterRequest(BaseModel):
    student_id: Optional[str] = None
    mode: str = Field(default="INDIVIDUAL", description="INDIVIDUAL, CREATE_TEAM, JOIN_TEAM")
    team_name: Optional[str] = None
    project_title: Optional[str] = None
    invite_code: Optional[str] = None


class TeamResultUpdateRequest(BaseModel):
    result_position: str = Field(..., description="WINNER, RUNNER_UP, FINALIST, PARTICIPANT")
    score: Optional[float] = None


class CertificateIssueRequest(BaseModel):
    student_id: str
    club_id: Optional[str] = None
    event_id: Optional[str] = None
    cert_type: str = "ACHIEVEMENT"
    title: str
    citation: str
    verification_evidence: str = "Verified Club / Event Record"


class BudgetCreateRequest(BaseModel):
    club_id: str
    title: str
    category: str = "Equipment & Kits"
    amount_inr: float
    description: str


class BudgetApprovalRequest(BaseModel):
    decision: str = Field(..., description="APPROVE or REJECT")
    notes: str = ""


class DutyLeaveCreateRequest(BaseModel):
    event_id: str
    student_id: Optional[str] = None
    leave_dates: str
    reason: str


class DutyLeaveDecisionRequest(BaseModel):
    status: str = Field(..., description="APPROVED or REJECTED")


class MediaCreateRequest(BaseModel):
    club_id: Optional[str] = None
    event_id: Optional[str] = None
    caption: str
    media_url: str
    tagged_student_id: Optional[str] = None
    student_consent: bool = True


class ConsentToggleRequest(BaseModel):
    student_consent: bool


class ClubNewsCreateRequest(BaseModel):
    club_id: str
    title: str
    content: str
    pinned: bool = False


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    email: str
    otp: str
    new_password: str


# ============================================================================
# Authentication & User Management Endpoints
# ============================================================================

def serialize_user(u: User, campuses_map: Dict[str, str]) -> Dict[str, Any]:
    return {
        "id": u.id,
        "full_name": u.full_name,
        "email": u.email,
        "role": u.role,
        "account_status": getattr(u, "account_status", "APPROVED") or "APPROVED",
        "campus_id": u.campus_id,
        "campus_code": campuses_map.get(u.campus_id, "HI-Tech") if u.campus_id else "All",
        "roll_number": u.roll_number,
        "batch": u.batch,
        "track": u.track,
    }


@app.post("/api/auth/register")
def register_user(req: RegisterRequest, db: Session = Depends(get_db)):
    email_clean = req.email.strip().lower()
    if not email_clean or not req.password or len(req.password) < 4:
        raise HTTPException(status_code=400, detail="Valid email and password (min 4 characters) are required.")

    existing = db.query(User).filter(User.email == email_clean).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    roll_clean = req.roll_number.strip() if req.roll_number and req.roll_number.strip() else None
    if roll_clean:
        dup_roll = db.query(User).filter(User.roll_number == roll_clean).first()
        if dup_roll:
            raise HTTPException(status_code=400, detail="This Roll / ID Number is already registered.")

    default_campus = db.query(Campus).first()
    campus_id = req.campus_id or (default_campus.id if default_campus else None)

    role_upper = req.role.upper()
    # Mandatory requirement: Every account type (Student, President, Faculty Advisor) requires Campus Manager permission
    initial_account_status = "PENDING_APPROVAL"

    user = User(
        email=email_clean,
        password_hash=hash_password(req.password),
        full_name=req.full_name.strip(),
        role=role_upper,
        account_status=initial_account_status,
        campus_id=campus_id,
        roll_number=roll_clean,
        batch=req.batch,
        track=req.track or "Mirai Track",
    )
    db.add(user)
    db.flush()

    db.add(
        AuditLog(
            actor_id=user.id,
            action="ACCOUNT_REQUESTED",
            entity_type="USER",
            entity_id=user.id,
            details=f"{user.role} account requested by {user.full_name} ({user.email}). Awaiting Campus Manager approval.",
        )
    )

    db.commit()
    db.refresh(user)

    campuses_map = {c.id: c.code for c in db.query(Campus).all()}
    return {
        "pending_approval": True,
        "token": None,
        "user": serialize_user(user, campuses_map),
        "message": "Your account request has been submitted! Every account requires verification and permission from the Campus Manager before access is granted. You will receive an email once approved.",
    }


@app.post("/api/auth/login")
def login_user(req: LoginRequest, db: Session = Depends(get_db)):
    email_clean = req.email.strip().lower()
    user = db.query(User).filter(User.email == email_clean).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    acc_status = getattr(user, "account_status", "APPROVED") or "APPROVED"
    if acc_status == "PENDING_APPROVAL":
        raise HTTPException(
            status_code=403,
            detail="Your account is awaiting approval from the Campus Manager. You will receive an email notification once your access is permitted.",
        )
    if acc_status == "REJECTED":
        raise HTTPException(
            status_code=403,
            detail="Your account request was declined by the Campus Manager.",
        )

    campuses_map = {c.id: c.code for c in db.query(Campus).all()}
    token = create_access_token(user)
    return {
        "token": token,
        "user": serialize_user(user, campuses_map),
    }


@app.post("/api/auth/forgot-password")
def request_password_reset(req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    email_clean = req.email.strip().lower()
    if not email_clean or "@" not in email_clean:
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")

    user = db.query(User).filter(User.email.ilike(email_clean)).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail=f"No registered account found with email '{email_clean}'. Please check for typos or submit an account request.",
        )

    # Invalidate previous unused OTPs for this email
    db.query(PasswordResetOTP).filter(
        PasswordResetOTP.email == email_clean,
        PasswordResetOTP.used == False
    ).update({"used": True})

    # Generate cryptographically secure 6-digit OTP
    otp_code = f"{secrets.randbelow(900000) + 100000}"
    expires_at = datetime.utcnow() + timedelta(minutes=15)

    otp_record = PasswordResetOTP(
        email=email_clean,
        otp=otp_code,
        expires_at=expires_at,
        used=False,
    )
    db.add(otp_record)
    db.commit()

    # Dispatch email in background thread
    send_password_reset_otp_email(email_clean, user.full_name, otp_code)

    return {
        "success": True,
        "message": f"A 6-digit verification code has been sent to {email_clean}. It is valid for 15 minutes.",
    }


@app.post("/api/auth/reset-password")
def complete_password_reset(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    email_clean = req.email.strip().lower()
    otp_clean = req.otp.strip()
    if not email_clean or not otp_clean:
        raise HTTPException(status_code=400, detail="Email and verification code are required.")

    if not req.new_password or len(req.new_password) < 4:
        raise HTTPException(status_code=400, detail="New password must be at least 4 characters.")

    now = datetime.utcnow()
    record = (
        db.query(PasswordResetOTP)
        .filter(
            PasswordResetOTP.email == email_clean,
            PasswordResetOTP.otp == otp_clean,
            PasswordResetOTP.used == False,
            PasswordResetOTP.expires_at >= now,
        )
        .order_by(PasswordResetOTP.created_at.desc())
        .first()
    )

    if not record:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired verification code. Please request a new code.",
        )

    user = db.query(User).filter(User.email == email_clean).first()
    if not user:
        raise HTTPException(status_code=404, detail="Account not found.")

    user.password_hash = hash_password(req.new_password)
    record.used = True
    db.commit()

    return {
        "success": True,
        "message": "Password reset successfully! You can now sign in with your new password.",
    }


@app.get("/api/auth/me")
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campuses_map = {c.id: c.code for c in db.query(Campus).all()}
    return serialize_user(current_user, campuses_map)


@app.get("/api/users")
def list_users(
    role: Optional[str] = None,
    campus_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(User)
    if role:
        q = q.filter(User.role == role.upper())
    if campus_id:
        q = q.filter(User.campus_id == campus_id)
    users = q.order_by(User.created_at.desc()).all()
    campuses_map = {c.id: c.code for c in db.query(Campus).all()}
    return [serialize_user(u, campuses_map) for u in users]


# ============================================================================
# File Upload Endpoint (Deliverables & Gallery Photos)
# ============================================================================

@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    ext = os.path.splitext(file.filename or "file")[1].lower()
    safe_name = f"{int(time.time())}_{secrets.token_hex(4)}{ext}"
    dest_path = os.path.join(UPLOADS_DIR, safe_name)
    content = await file.read()
    with open(dest_path, "wb") as f:
        f.write(content)

    supabase_url = upload_to_supabase_storage(
        dest_path,
        f"uploads/{safe_name}",
        content_type=file.content_type or "application/octet-stream",
    )
    return {
        "filename": file.filename,
        "file_url": supabase_url or f"/uploads/{safe_name}",
    }


# ============================================================================
# System & Campuses Endpoints
# ============================================================================

@app.get("/api/system/status")
def get_system_status(db: Session = Depends(get_db)):
    configs = {c.key: c.value for c in db.query(SystemConfig).all()}
    return {
        "status": "healthy",
        "database": get_database_info(),
        "configs": configs,
        "counts": {
            "campuses": db.query(Campus).count(),
            "users": db.query(User).count(),
            "clubs": db.query(Club).count(),
            "sessions": db.query(ClubDaySession).count(),
            "attendances": db.query(Attendance).count(),
            "submissions": db.query(Submission).count(),
            "evaluations": db.query(Evaluation).count(),
            "events": db.query(Event).count(),
            "certificates": db.query(Certificate).count(),
            "budget_requests": db.query(BudgetRequest).count(),
            "duty_leaves": db.query(DutyLeaveRequest).count(),
            "gallery_items": db.query(MediaGalleryItem).count(),
        },
    }


@app.get("/api/campuses")
def list_campuses(db: Session = Depends(get_db)):
    campuses = db.query(Campus).all()
    return [
        {
            "id": c.id,
            "code": c.code,
            "name": c.name,
            "city": c.city,
            "lat": c.lat,
            "lng": c.lng,
            "geofence_radius_m": c.geofence_radius_m,
        }
        for c in campuses
    ]


@app.get("/api/bootstrap")
def get_bootstrap_payload(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    High-performance single round-trip bootstrap endpoint.
    Bundles user profile, campuses, and pending counters in one shot to eliminate network waterfalls.
    """
    campuses = db.query(Campus).all()
    campuses_map = {c.id: c.code for c in campuses}
    serialized_user = serialize_user(current_user, campuses_map)

    campuses_list = [
        {
            "id": c.id,
            "code": c.code,
            "name": c.name,
            "city": c.city,
            "lat": c.lat,
            "lng": c.lng,
            "geofence_radius_m": c.geofence_radius_m,
        }
        for c in campuses
    ]

    total_pending = 0
    if current_user.role in ("ADMIN", "CAMPUS_MGR", "ADVISOR"):
        total_pending = db.query(User).filter(User.account_status == "PENDING_APPROVAL").count()

    return {
        "user": serialized_user,
        "campuses": campuses_list,
        "total_pending": total_pending,
        "timestamp": int(time.time()),
    }


# ============================================================================
# 1. Club Registry & 2. Student Enrolment
# ============================================================================

@app.get("/api/clubs")
def list_clubs(
    campus_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Club)
    if campus_id:
        q = q.filter(Club.campus_id == campus_id)
    clubs = q.order_by(Club.created_at.desc()).all()

    campuses_map = {row[0]: row[1] for row in db.query(Campus.id, Campus.code).all()}
    users_map = {row[0]: row[1] for row in db.query(User.id, User.full_name).all()}

    # Single-query batch fetch for all memberships of retrieved clubs
    club_ids = [cl.id for cl in clubs]
    all_memberships = db.query(ClubMembership).filter(ClubMembership.club_id.in_(club_ids)).all() if club_ids else []
    memberships_by_club: Dict[str, list] = {}
    for m in all_memberships:
        memberships_by_club.setdefault(m.club_id, []).append(m)

    out = []
    for cl in clubs:
        memberships = memberships_by_club.get(cl.id, [])
        approved_count = sum(1 for m in memberships if m.status == "APPROVED")
        pending_count = sum(1 for m in memberships if m.status == "PENDING")
        coordinators = [
            {"id": m.student_id, "name": users_map.get(m.student_id, "President")}
            for m in memberships
            if m.tier in ("COORDINATOR", "PRESIDENT") and m.status == "APPROVED"
        ]
        my_membership = next((m for m in memberships if m.student_id == current_user.id), None)

        out.append(
            {
                "id": cl.id,
                "campus_id": cl.campus_id,
                "campus_code": campuses_map.get(cl.campus_id, "HI-Tech"),
                "code": cl.code,
                "name": cl.name,
                "category": cl.category,
                "description": cl.description,
                "advisor_id": cl.advisor_id,
                "advisor_name": users_map.get(cl.advisor_id, "Not Assigned") if cl.advisor_id else "Not Assigned",
                "coordinators": coordinators,
                "capacity": cl.capacity,
                "approved_members": approved_count,
                "pending_requests": pending_count,
                "meeting_rules": cl.meeting_rules,
                "status": cl.status,
                "my_membership": (
                    {"id": my_membership.id, "tier": my_membership.tier, "status": my_membership.status}
                    if my_membership
                    else None
                ),
            }
        )
    return out


@app.post("/api/clubs")
def create_club(
    req: ClubCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("ADMIN", "CAMPUS_MGR"):
        raise HTTPException(status_code=403, detail="Only Admin or Campus Manager can create clubs.")

    code_clean = req.code.strip().upper()
    if db.query(Club).filter(Club.code == code_clean).first():
        raise HTTPException(status_code=400, detail=f"Club code '{code_clean}' already exists.")

    initial_status = "ACTIVE" if current_user.role == "ADMIN" else "PENDING"
    new_club = Club(
        campus_id=req.campus_id,
        code=code_clean,
        name=req.name.strip(),
        category=req.category.strip(),
        description=req.description.strip(),
        advisor_id=req.advisor_id or None,
        capacity=req.capacity,
        meeting_rules=req.meeting_rules,
        status=initial_status,
    )
    db.add(new_club)
    db.flush()

    if req.coordinator_id:
        db.add(
            ClubMembership(
                club_id=new_club.id,
                student_id=req.coordinator_id,
                tier="COORDINATOR",
                status="APPROVED",
                approved_by_id=current_user.id,
            )
        )

    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="CLUB_CREATED",
            entity_type="CLUB",
            entity_id=new_club.id,
            details=f"Created club {new_club.name} ({new_club.code}) with status {initial_status}.",
        )
    )
    db.commit()
    return {"id": new_club.id, "code": new_club.code, "status": new_club.status, "message": "Club created successfully."}


@app.patch("/api/clubs/{club_id}/status")
def update_club_status(
    club_id: str,
    status: str = Query(..., description="ACTIVE or INACTIVE"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("ADMIN", "CAMPUS_MGR"):
        raise HTTPException(status_code=403, detail="Only Admin or Campus Manager can update club status.")
    club = db.query(Club).filter(Club.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
    club.status = status.upper()
    db.commit()
    return {"id": club.id, "status": club.status, "message": f"Club marked as {club.status}."}


@app.post("/api/clubs/{club_id}/assign-coordinator")
def assign_club_coordinator(
    club_id: str,
    student_id: str = Query(...),
    tier: str = Query(default="PRESIDENT"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("ADMIN", "CAMPUS_MGR", "ADVISOR"):
        raise HTTPException(status_code=403, detail="Only Admin, Campus Manager, or Advisor can assign club leadership.")
    assign_tier = "PRESIDENT" if tier.upper() in ("PRESIDENT", "COORDINATOR") else tier.upper()
    existing = (
        db.query(ClubMembership)
        .filter(ClubMembership.club_id == club_id, ClubMembership.student_id == student_id)
        .first()
    )
    if existing:
        existing.tier = assign_tier
        existing.status = "APPROVED"
        existing.approved_by_id = current_user.id
    else:
        db.add(
            ClubMembership(
                club_id=club_id,
                student_id=student_id,
                tier=assign_tier,
                status="APPROVED",
                approved_by_id=current_user.id,
            )
        )
    user_obj = db.query(User).filter(User.id == student_id).first()
    if user_obj and user_obj.role in ("STUDENT", "COORDINATOR"):
        user_obj.role = "PRESIDENT"
    db.commit()
    return {"message": f"Club President assigned successfully."}


@app.post("/api/clubs/{club_id}/enrol")
def request_club_enrolment(
    club_id: str,
    req: EnrolRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target_student_id = req.student_id or current_user.id
    club = db.query(Club).filter(Club.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    existing = (
        db.query(ClubMembership)
        .filter(ClubMembership.club_id == club_id, ClubMembership.student_id == target_student_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail=f"Already enrolled or pending in {club.name} ({existing.status}).")

    tier = req.tier.upper()
    if tier in ("PRIMARY", "SECONDARY"):
        max_key = "max_primary_clubs" if tier == "PRIMARY" else "max_secondary_clubs"
        cfg = db.query(SystemConfig).filter(SystemConfig.key == max_key).first()
        limit_val = int(cfg.value) if cfg else 1

        current_tier_count = (
            db.query(ClubMembership)
            .filter(
                ClubMembership.student_id == target_student_id,
                ClubMembership.tier == tier,
                ClubMembership.status.in_(["PENDING", "APPROVED"]),
            )
            .count()
        )
        if current_tier_count >= limit_val:
            raise HTTPException(
                status_code=400,
                detail=f"Limit reached: You can join at most {limit_val} {tier} club(s).",
            )

    mem = ClubMembership(
        club_id=club_id,
        student_id=target_student_id,
        tier=tier,
        status="PENDING",
    )
    db.add(mem)
    db.commit()
    return {"id": mem.id, "club_id": club_id, "tier": tier, "status": "PENDING", "message": "Enrolment request sent."}


@app.get("/api/enrolments")
def list_enrolments(
    club_id: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(ClubMembership)
    if club_id:
        if current_user.role == "COORDINATOR":
            verify_coordinator_club_access(db, current_user, club_id)
        q = q.filter(ClubMembership.club_id == club_id)
    elif current_user.role == "COORDINATOR":
        my_coord_clubs = [
            m.club_id
            for m in db.query(ClubMembership)
            .filter(ClubMembership.student_id == current_user.id, ClubMembership.tier == "COORDINATOR")
            .all()
        ]
        q = q.filter(ClubMembership.club_id.in_(my_coord_clubs)) if my_coord_clubs else q.filter(False)
    if status:
        q = q.filter(ClubMembership.status == status)

    student_ids = [r.student_id for r in rows]
    users_tuple = db.query(User.id, User.full_name, User.roll_number).filter(User.id.in_(student_ids)).all() if student_ids else []
    user_names = {u[0]: u[1] for u in users_tuple}
    user_rolls = {u[0]: u[2] for u in users_tuple}
    club_ids = [r.club_id for r in rows]
    clubs_map = {row[0]: row[1] for row in db.query(Club.id, Club.name).filter(Club.id.in_(club_ids)).all()} if club_ids else {}

    return [
        {
            "id": r.id,
            "club_id": r.club_id,
            "club_name": clubs_map.get(r.club_id, ""),
            "student_id": r.student_id,
            "student_name": user_names.get(r.student_id, ""),
            "roll_number": user_rolls.get(r.student_id, ""),
            "tier": r.tier,
            "status": r.status,
            "joined_at": r.joined_at.isoformat() if r.joined_at else None,
        }
        for r in rows
    ]


@app.patch("/api/enrolments/{membership_id}")
def approve_or_reject_enrolment(
    membership_id: str,
    req: EnrolmentStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mem = db.query(ClubMembership).filter(ClubMembership.id == membership_id).first()
    if not mem:
        raise HTTPException(status_code=404, detail="Enrolment request not found")

    verify_coordinator_club_access(db, current_user, mem.club_id)
    mem.status = req.status.upper()
    mem.approved_by_id = current_user.id
    db.commit()
    return {"id": mem.id, "status": mem.status, "message": f"Membership {mem.status.lower()}."}


# ============================================================================
# 3. Club Day Calendar & 7-Step Flow
# ============================================================================

def cleanup_expired_sessions(db: Session):
    """
    Automatic cleanup 30 minutes after generation:
    1. Removes all DEMO sessions (format == 'DEMO' or topic contains 'demo') created > 30 mins ago.
    2. Closes / completes any open check-in windows older than 30 minutes.
    """
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=30)
        # 1. Purge expired demo sessions
        expired_demos = (
            db.query(ClubDaySession)
            .filter(
                ClubDaySession.created_at < cutoff,
                (ClubDaySession.format == "DEMO") | (ClubDaySession.topic.ilike("%demo%"))
            )
            .all()
        )
        for s in expired_demos:
            db.delete(s)

        # 2. Mark any open sessions created > 30 minutes ago as COMPLETED
        open_expired = (
            db.query(ClubDaySession)
            .filter(
                ClubDaySession.created_at < cutoff,
                ClubDaySession.checkin_status == "OPEN",
            )
            .all()
        )
        for s in open_expired:
            s.checkin_status = "COMPLETED"
            if not s.checkin_closes_at or s.checkin_closes_at > cutoff:
                s.checkin_closes_at = s.created_at + timedelta(minutes=30)

        if expired_demos or open_expired:
            db.commit()
    except Exception as e:
        db.rollback()


@app.get("/api/sessions")
def list_club_day_sessions(
    club_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cleanup_expired_sessions(db)
    q = db.query(ClubDaySession)
    if club_id:
        q = q.filter(ClubDaySession.club_id == club_id)
    sessions = q.order_by(ClubDaySession.scheduled_date.desc(), ClubDaySession.week_number.desc()).all()

    clubs_map = {
        row[0]: {"name": row[1], "code": row[2], "campus_id": row[3]}
        for row in db.query(Club.id, Club.name, Club.code, Club.campus_id).all()
    }
    campuses_map = {
        row[0]: {"code": row[1], "lat": row[2], "lng": row[3]}
        for row in db.query(Campus.id, Campus.code, Campus.lat, Campus.lng).all()
    }

    session_ids = [s.id for s in sessions]
    if session_ids:
        from sqlalchemy import func
        att_counts = dict(
            db.query(Attendance.session_id, func.count(Attendance.id))
            .filter(Attendance.session_id.in_(session_ids))
            .group_by(Attendance.session_id)
            .all()
        )
        sub_counts = dict(
            db.query(Submission.session_id, func.count(Submission.id))
            .filter(Submission.session_id.in_(session_ids))
            .group_by(Submission.session_id)
            .all()
        )
        my_atts = {
            a.session_id: a
            for a in db.query(Attendance)
            .filter(Attendance.session_id.in_(session_ids), Attendance.student_id == current_user.id)
            .all()
        }
        my_subs = {
            s.session_id: s
            for s in db.query(Submission)
            .filter(Submission.session_id.in_(session_ids), Submission.student_id == current_user.id)
            .all()
        }
    else:
        att_counts, sub_counts, my_atts, my_subs = {}, {}, {}, {}

    out = []
    for s in sessions:
        cl = clubs_map.get(s.club_id)
        camp = campuses_map.get(cl["campus_id"]) if cl else None
        att_count = att_counts.get(s.id, 0)
        sub_count = sub_counts.get(s.id, 0)
        my_att = my_atts.get(s.id)
        my_sub = my_subs.get(s.id)

        out.append(
            {
                "id": s.id,
                "club_id": s.club_id,
                "club_name": cl["name"] if cl else "",
                "club_code": cl["code"] if cl else "",
                "campus_code": camp["code"] if camp else "HI-Tech",
                "campus_lat": camp["lat"] if camp else 17.4435,
                "campus_lng": camp["lng"] if camp else 78.3772,
                "week_number": s.week_number,
                "scheduled_date": s.scheduled_date,
                "topic": s.topic,
                "format": s.format,
                "venue": s.venue,
                "deliverable_desc": s.deliverable_desc,
                "submission_deadline": s.submission_deadline,
                "plan_status": s.plan_status,
                "advisor_feedback": s.advisor_feedback,
                "announced": s.announced_at is not None,
                "checkin_status": s.checkin_status,
                "attendance_count": att_count,
                "submission_count": sub_count,
                "on_the_spot_notes": s.on_the_spot_notes,
                "my_attendance": (
                    {"status": my_att.status, "method": my_att.method, "is_presenter": my_att.is_presenter}
                    if my_att
                    else None
                ),
                "my_submission": (
                    {
                        "id": my_sub.id,
                        "title": my_sub.title,
                        "score": my_sub.evaluation.total_score if my_sub.evaluation else None,
                    }
                    if my_sub
                    else None
                ),
            }
        )
    return out


@app.post("/api/sessions")
def plan_club_day_session(
    req: SessionPlanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    verify_coordinator_club_access(db, current_user, req.club_id)

    sess = ClubDaySession(
        club_id=req.club_id,
        week_number=req.week_number,
        scheduled_date=req.scheduled_date,
        topic=req.topic.strip(),
        format=req.format,
        venue=req.venue.strip(),
        deliverable_desc=req.deliverable_desc.strip(),
        submission_deadline=req.submission_deadline,
        plan_status="PENDING_APPROVAL",
        planned_by_id=current_user.id,
        checkin_secret=secrets.token_hex(16),
        checkin_status="CLOSED",
    )
    db.add(sess)
    db.commit()
    return {
        "id": sess.id,
        "plan_status": sess.plan_status,
        "message": "Activity plan created and sent for Advisor approval.",
    }


@app.post("/api/sessions/quick-start")
def quick_start_session(
    payload: Dict[str, Any] = Body(default={}),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    1-Click Live Session & Rotating QR Launcher for Campus Managers, Presidents, and Advisors.
    Immediately creates an approved session and opens the check-in window.
    """
    if current_user.role not in ("CAMPUS_MGR", "ADMIN", "PRESIDENT", "COORDINATOR", "ADVISOR"):
        raise HTTPException(status_code=403, detail="Only Campus Managers, Club Presidents, and Faculty Advisors can launch live sessions.")

    club_id = payload.get("club_id")
    if not club_id:
        # Default to first club for user campus
        q = db.query(Club)
        if current_user.campus_id:
            q = q.filter(Club.campus_id == current_user.campus_id)
        club = q.first() or db.query(Club).first()
        if not club:
            raise HTTPException(status_code=400, detail="No club registered yet. Create a club first.")
        club_id = club.id
    else:
        verify_coordinator_club_access(db, current_user, club_id)
        club = db.query(Club).filter(Club.id == club_id).first()

    cleanup_expired_sessions(db)
    now = datetime.utcnow()
    scheduled_date = datetime.now().strftime("%Y-%m-%d")
    topic = payload.get("topic") or f"{club.name} Club Day Hands-On Workshop"
    
    sess = ClubDaySession(
        club_id=club_id,
        week_number=int(time.time() // 604800 % 52) + 1,
        scheduled_date=scheduled_date,
        topic=topic,
        format=payload.get("format") or "DEMO",
        venue=payload.get("venue") or "Campus Seminar Hall",
        deliverable_desc="Project / Prototype Link & GitHub Repository",
        submission_deadline=(datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d 23:59"),
        plan_status="APPROVED",
        planned_by_id=current_user.id,
        approved_by_id=current_user.id,
        checkin_secret=secrets.token_hex(16),
        checkin_status="OPEN",
        checkin_opens_at=now,
        checkin_late_after=now + timedelta(minutes=15),
        checkin_closes_at=now + timedelta(minutes=30),
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return {
        "id": sess.id,
        "topic": sess.topic,
        "club_name": club.name,
        "checkin_status": sess.checkin_status,
        "message": f"Live session started for {club.name}! Rotating QR is now live.",
    }


@app.patch("/api/sessions/{session_id}/approval")
def review_session_plan(
    session_id: str,
    req: SessionApprovalUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("ADVISOR", "ADMIN", "CAMPUS_MGR"):
        raise HTTPException(status_code=403, detail="Only Faculty Advisor, Campus Manager, or Admin can approve plans.")
    sess = db.query(ClubDaySession).filter(ClubDaySession.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    sess.plan_status = req.plan_status.upper()
    sess.advisor_feedback = req.advisor_feedback
    sess.approved_by_id = current_user.id
    if sess.plan_status == "APPROVED":
        sess.announced_at = datetime.utcnow()
    db.commit()
    return {"id": sess.id, "plan_status": sess.plan_status, "advisor_feedback": sess.advisor_feedback}


@app.post("/api/sessions/{session_id}/announce")
def announce_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sess = db.query(ClubDaySession).filter(ClubDaySession.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    verify_coordinator_club_access(db, current_user, sess.club_id)
    sess.announced_at = datetime.utcnow()
    db.commit()

    # Dispatch email notification to all approved club members
    club = db.query(Club).filter(Club.id == sess.club_id).first()
    memberships = db.query(ClubMembership).filter(
        ClubMembership.club_id == sess.club_id,
        ClubMembership.status == "APPROVED"
    ).all()
    st_ids = [m.student_id for m in memberships]
    if st_ids:
        member_emails = [
            row[0]
            for row in db.query(User.email).filter(User.id.in_(st_ids), User.email != "").all()
        ]
        send_session_announced_email(
            member_emails,
            club.name if club else "Club",
            sess.topic,
            sess.scheduled_date,
            sess.venue,
            sess.format,
            sess.deliverable_desc or "Saturday Club Day Session Activity",
        )

    return {"id": sess.id, "announced": True, "message": "Session announced and email notifications dispatched to club members."}


@app.post("/api/sessions/{session_id}/checkin-window")
def toggle_checkin_window(
    session_id: str,
    req: CheckinWindowUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sess = db.query(ClubDaySession).filter(ClubDaySession.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    verify_coordinator_club_access(db, current_user, sess.club_id)
    if sess.plan_status != "APPROVED":
        raise HTTPException(status_code=400, detail="Activity plan must be approved before opening check-in.")

    now = datetime.utcnow()
    if req.action.upper() == "OPEN":
        sess.checkin_status = "OPEN"
        sess.checkin_opens_at = now
        sess.checkin_late_after = now + timedelta(minutes=req.late_after_minutes)
        sess.checkin_closes_at = now + timedelta(minutes=req.duration_minutes)
    else:
        sess.checkin_status = "COMPLETED"
        sess.checkin_closes_at = now

    db.commit()
    return {
        "id": sess.id,
        "checkin_status": sess.checkin_status,
        "checkin_opens_at": sess.checkin_opens_at.isoformat() if sess.checkin_opens_at else None,
        "checkin_late_after": sess.checkin_late_after.isoformat() if sess.checkin_late_after else None,
        "checkin_closes_at": sess.checkin_closes_at.isoformat() if sess.checkin_closes_at else None,
    }


@app.get("/api/sessions/{session_id}/qr")
def get_live_session_qr(session_id: str, db: Session = Depends(get_db)):
    cleanup_expired_sessions(db)
    sess = db.query(ClubDaySession).filter(ClubDaySession.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found or has expired after 30 minutes.")

    now = datetime.utcnow()
    if sess.checkin_closes_at and now > sess.checkin_closes_at:
        sess.checkin_status = "COMPLETED"
        db.commit()

    payload = generate_qr_payload(sess.checkin_secret, sess.id)
    payload["checkin_status"] = sess.checkin_status
    payload["topic"] = sess.topic
    return payload


@app.get("/api/sessions/{session_id}/qr-expired-test")
def get_expired_screenshot_qr_for_test(session_id: str, db: Session = Depends(get_db)):
    sess = db.query(ClubDaySession).filter(ClubDaySession.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    return generate_qr_payload(sess.checkin_secret, sess.id, timestamp=time.time() - 60)


_CLUB_GEOFENCE_CACHE: Dict[str, Dict[str, Any]] = {}


@app.post("/api/sessions/{session_id}/checkin")
def student_checkin(
    session_id: str,
    req: StudentCheckinRequest,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
):
    cleanup_expired_sessions(db)
    sess = db.query(ClubDaySession).filter(ClubDaySession.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found or has expired after 30 minutes.")

    if sess.checkin_status != "OPEN":
        raise HTTPException(status_code=400, detail="Check-in window is currently closed for this session.")

    token_user_id = None
    if authorization and authorization.startswith("Bearer "):
        token_user_id = decode_access_token(authorization.replace("Bearer ", "", 1).strip())

    target_student_id = req.student_id or token_user_id or x_user_id
    if not target_student_id:
        raise HTTPException(status_code=401, detail="Student identity required to check in.")

    ver = verify_checkin_token_or_otp(
        secret=sess.checkin_secret,
        session_id=sess.id,
        qr_token=req.qr_token,
        otp_code=req.otp_code,
    )
    if not ver["valid"]:
        db.add(
            AuditLog(
                actor_id=target_student_id,
                action=f"CHECKIN_REJECTED_{ver['code']}",
                entity_type="SESSION",
                entity_id=sess.id,
                details=ver["message"],
            )
        )
        db.commit()
        raise HTTPException(status_code=403, detail={"code": ver["code"], "message": ver["message"]})

    if sess.club_id not in _CLUB_GEOFENCE_CACHE:
        club = db.query(Club).filter(Club.id == sess.club_id).first()
        campus = db.query(Campus).filter(Campus.id == club.campus_id).first() if club else None
        if campus:
            _CLUB_GEOFENCE_CACHE[sess.club_id] = {
                "name": campus.name,
                "lat": campus.lat,
                "lng": campus.lng,
                "geofence_radius_m": campus.geofence_radius_m,
            }
    camp_meta = _CLUB_GEOFENCE_CACHE.get(sess.club_id)

    geofence_cfg = db.query(SystemConfig).filter(SystemConfig.key == "geofence_check_enabled").first()
    geofence_enabled = (geofence_cfg.value.lower() == "true") if geofence_cfg else True

    dist_m = 15.0
    if camp_meta and req.lat is not None and req.lng is not None:
        dist_m = round(haversine_distance_m(req.lat, req.lng, camp_meta["lat"], camp_meta["lng"]), 1)
        if geofence_enabled and dist_m > camp_meta["geofence_radius_m"]:
            msg = f"Outside campus geofence: {dist_m}m away from {camp_meta['name']} (max {camp_meta['geofence_radius_m']}m)."
            db.add(
                AuditLog(
                    actor_id=target_student_id,
                    action="CHECKIN_REJECTED_OUTSIDE_CAMPUS",
                    entity_type="SESSION",
                    entity_id=sess.id,
                    details=msg,
                )
            )
            db.commit()
            raise HTTPException(
                status_code=403,
                detail={"code": "OUTSIDE_CAMPUS_GEOFENCE", "message": msg, "distance_m": dist_m},
            )

    now = datetime.utcnow() + timedelta(minutes=req.simulated_check_time_offset_min or 0)
    if sess.checkin_closes_at and now > sess.checkin_closes_at:
        raise HTTPException(
            status_code=403,
            detail={"code": "CHECKIN_WINDOW_EXPIRED", "message": "Check-in window has closed."},
        )

    att_status = "PRESENT"
    if sess.checkin_late_after and now > sess.checkin_late_after:
        att_status = "LATE"

    existing = (
        db.query(Attendance)
        .filter(Attendance.session_id == sess.id, Attendance.student_id == target_student_id)
        .first()
    )
    if existing:
        return {
            "id": existing.id,
            "session_id": sess.id,
            "student_id": target_student_id,
            "status": existing.status,
            "method": existing.method,
            "distance_from_campus_m": existing.distance_from_campus_m,
            "already_checked_in": True,
            "message": f"Already checked in ({existing.status}).",
        }

    att = Attendance(
        session_id=sess.id,
        student_id=target_student_id,
        status=att_status,
        method=ver["method"],
        checkin_lat=req.lat if req.lat is not None else (camp_meta["lat"] if camp_meta else 17.4435),
        checkin_lng=req.lng if req.lng is not None else (camp_meta["lng"] if camp_meta else 78.3772),
        distance_from_campus_m=dist_m,
        checked_in_at=now,
    )
    db.add(att)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(Attendance)
            .filter(Attendance.session_id == sess.id, Attendance.student_id == target_student_id)
            .first()
        )
        return {
            "id": existing.id if existing else "concurrent",
            "session_id": sess.id,
            "student_id": target_student_id,
            "status": existing.status if existing else att_status,
            "method": ver["method"],
            "already_checked_in": True,
            "message": "Checked in.",
        }

    return {
        "id": att.id,
        "session_id": sess.id,
        "student_id": target_student_id,
        "status": att.status,
        "method": att.method,
        "distance_from_campus_m": dist_m,
        "already_checked_in": False,
        "message": f"Checked in ({att.status}) via {att.method}.",
    }


@app.post("/api/sessions/{session_id}/attendance/override")
def coordinator_manual_override(
    session_id: str,
    req: ManualAttendanceOverrideRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "STUDENT":
        raise HTTPException(status_code=403, detail="Students cannot edit attendance records.")

    sess = db.query(ClubDaySession).filter(ClubDaySession.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    verify_coordinator_club_access(db, current_user, sess.club_id)

    if not req.reason or len(req.reason.strip()) < 5:
        raise HTTPException(
            status_code=400,
            detail="A valid reason (minimum 5 characters) is mandatory for manual attendance corrections.",
        )

    att = (
        db.query(Attendance)
        .filter(Attendance.session_id == session_id, Attendance.student_id == req.student_id)
        .first()
    )
    if att:
        att.status = req.status.upper()
        att.method = "MANUAL_OVERRIDE"
        att.override_reason = req.reason.strip()
        att.overridden_by_id = current_user.id
    else:
        att = Attendance(
            session_id=session_id,
            student_id=req.student_id,
            status=req.status.upper(),
            method="MANUAL_OVERRIDE",
            override_reason=req.reason.strip(),
            overridden_by_id=current_user.id,
        )
        db.add(att)

    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="ATTENDANCE_MANUAL_OVERRIDE",
            entity_type="ATTENDANCE",
            entity_id=session_id,
            details=f"Student {req.student_id} marked {req.status} by {current_user.full_name}. Reason: {req.reason}",
        )
    )
    db.commit()
    return {
        "id": att.id,
        "student_id": att.student_id,
        "status": att.status,
        "method": att.method,
        "override_reason": att.override_reason,
    }


@app.patch("/api/sessions/{session_id}/presenter")
def mark_session_presenter(
    session_id: str,
    req: PresenterUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sess = db.query(ClubDaySession).filter(ClubDaySession.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    verify_coordinator_club_access(db, current_user, sess.club_id)

    if req.on_the_spot_notes:
        sess.on_the_spot_notes = req.on_the_spot_notes

    att = (
        db.query(Attendance)
        .filter(Attendance.session_id == session_id, Attendance.student_id == req.student_id)
        .first()
    )
    if not att:
        raise HTTPException(status_code=404, detail="Student must be checked into the session first.")

    att.is_presenter = req.is_presenter
    if req.activity_result is not None:
        att.activity_result = req.activity_result
    db.commit()
    return {
        "student_id": att.student_id,
        "is_presenter": att.is_presenter,
        "activity_result": att.activity_result,
    }


@app.get("/api/sessions/{session_id}/details")
def get_session_roster_and_submissions(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sess = db.query(ClubDaySession).filter(ClubDaySession.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    attendances = db.query(Attendance).filter(Attendance.session_id == session_id).all()
    submissions = db.query(Submission).filter(Submission.session_id == session_id).all()
    st_ids = list({a.student_id for a in attendances} | {s.student_id for s in submissions})
    users_tuple = db.query(User.id, User.full_name, User.roll_number).filter(User.id.in_(st_ids)).all() if st_ids else []
    user_names = {u[0]: u[1] for u in users_tuple}
    user_rolls = {u[0]: u[2] for u in users_tuple}

    att_list = [
        {
            "id": a.id,
            "student_id": a.student_id,
            "student_name": user_names.get(a.student_id, a.student_id),
            "roll_number": user_rolls.get(a.student_id, ""),
            "status": a.status,
            "method": a.method,
            "is_presenter": a.is_presenter,
            "activity_result": a.activity_result,
            "override_reason": a.override_reason,
            "distance_from_campus_m": a.distance_from_campus_m,
            "checked_in_at": a.checked_in_at.isoformat() if a.checked_in_at else None,
        }
        for a in attendances
    ]

    sub_list = []
    for sub in submissions:
        ev = sub.evaluation
        sub_list.append(
            {
                "id": sub.id,
                "student_id": sub.student_id,
                "student_name": user_names.get(sub.student_id, sub.student_id),
                "roll_number": user_rolls.get(sub.student_id, ""),
                "title": sub.title,
                "deliverable_type": sub.deliverable_type,
                "file_url": sub.file_url,
                "external_link": sub.external_link,
                "notes": sub.notes,
                "is_late": sub.is_late,
                "submitted_at": sub.submitted_at.isoformat() if sub.submitted_at else None,
                "evaluation": (
                    {
                        "id": ev.id,
                        "evaluator_role": ev.evaluator_role,
                        "content_score": ev.content_score,
                        "presentation_score": ev.presentation_score,
                        "participation_score": ev.participation_score,
                        "total_score": ev.total_score,
                        "comments": ev.comments,
                    }
                    if ev
                    else None
                ),
            }
        )

    return {
        "session": {
            "id": sess.id,
            "club_id": sess.club_id,
            "week_number": sess.week_number,
            "scheduled_date": sess.scheduled_date,
            "topic": sess.topic,
            "format": sess.format,
            "venue": sess.venue,
            "deliverable_desc": sess.deliverable_desc,
            "submission_deadline": sess.submission_deadline,
            "plan_status": sess.plan_status,
            "advisor_feedback": sess.advisor_feedback,
            "announced": sess.announced_at is not None,
            "checkin_status": sess.checkin_status,
            "on_the_spot_notes": sess.on_the_spot_notes,
        },
        "attendances": att_list,
        "submissions": sub_list,
    }


# ============================================================================
# 5. Submissions & 6. Rubric Evaluations
# ============================================================================

@app.post("/api/sessions/{session_id}/submissions")
def submit_session_deliverable(
    session_id: str,
    req: SubmissionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sess = db.query(ClubDaySession).filter(ClubDaySession.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    target_student_id = req.student_id or current_user.id
    now = datetime.utcnow()
    is_late = False
    try:
        deadline_dt = datetime.strptime(sess.submission_deadline[:16], "%Y-%m-%d %H:%M")
        if now > deadline_dt:
            is_late = True
    except Exception:
        is_late = False

    existing = (
        db.query(Submission)
        .filter(Submission.session_id == session_id, Submission.student_id == target_student_id)
        .first()
    )
    if existing:
        existing.title = req.title
        existing.deliverable_type = req.deliverable_type
        existing.file_url = req.file_url or existing.file_url
        existing.external_link = req.external_link
        existing.notes = req.notes
        existing.submitted_at = now
        db.commit()
        return {"id": existing.id, "is_late": existing.is_late, "message": "Submission updated."}

    sub = Submission(
        session_id=session_id,
        student_id=target_student_id,
        title=req.title,
        deliverable_type=req.deliverable_type,
        file_url=req.file_url,
        external_link=req.external_link,
        notes=req.notes,
        is_late=is_late,
        submitted_at=now,
    )
    db.add(sub)
    db.commit()
    return {"id": sub.id, "is_late": sub.is_late, "message": "Deliverable submitted."}


@app.post("/api/submissions/{submission_id}/evaluate")
def evaluate_submission_rubric(
    submission_id: str,
    req: EvaluationCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "STUDENT":
        raise HTTPException(status_code=403, detail="Students cannot score or evaluate submissions.")

    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    sess = db.query(ClubDaySession).filter(ClubDaySession.id == sub.session_id).first()
    if sess:
        verify_coordinator_club_access(db, current_user, sess.club_id)

    total = round(req.content_score + req.presentation_score + req.participation_score, 2)
    ev = db.query(Evaluation).filter(Evaluation.submission_id == submission_id).first()
    if ev:
        ev.evaluator_id = current_user.id
        ev.evaluator_role = current_user.role
        ev.content_score = req.content_score
        ev.presentation_score = req.presentation_score
        ev.participation_score = req.participation_score
        ev.total_score = total
        ev.comments = req.comments
        ev.evaluated_at = datetime.utcnow()
    else:
        ev = Evaluation(
            submission_id=submission_id,
            evaluator_id=current_user.id,
            evaluator_role=current_user.role,
            content_score=req.content_score,
            presentation_score=req.presentation_score,
            participation_score=req.participation_score,
            total_score=total,
            comments=req.comments,
        )
        db.add(ev)

    db.commit()
    return {
        "id": ev.id,
        "submission_id": submission_id,
        "total_score": ev.total_score,
        "content_score": ev.content_score,
        "presentation_score": ev.presentation_score,
        "participation_score": ev.participation_score,
        "comments": ev.comments,
    }


# ============================================================================
# 7. Events & Team Registrations (+ Auto Duty Leave Generation)
# ============================================================================

@app.get("/api/events")
def list_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    events = db.query(Event).order_by(Event.start_date.asc()).all()
    event_ids = [ev.id for ev in events]
    all_teams = db.query(EventTeam).filter(EventTeam.event_id.in_(event_ids)).all() if event_ids else []
    all_regs = db.query(EventRegistration).filter(EventRegistration.event_id.in_(event_ids)).all() if event_ids else []

    teams_by_event: Dict[str, list] = {}
    for t in all_teams:
        teams_by_event.setdefault(t.event_id, []).append(t)

    regs_by_event: Dict[str, list] = {}
    for r in all_regs:
        regs_by_event.setdefault(r.event_id, []).append(r)

    user_ids = list({t.leader_id for t in all_teams} | {r.student_id for r in all_regs})
    users_map = {row[0]: row[1] for row in db.query(User.id, User.full_name).filter(User.id.in_(user_ids)).all()} if user_ids else {}

    out = []
    for ev in events:
        teams = teams_by_event.get(ev.id, [])
        regs = regs_by_event.get(ev.id, [])
        my_reg = next((r for r in regs if r.student_id == current_user.id), None)

        out.append(
            {
                "id": ev.id,
                "code": ev.code,
                "title": ev.title,
                "category": ev.category,
                "scope": ev.scope,
                "description": ev.description,
                "venue": ev.venue,
                "start_date": ev.start_date,
                "end_date": ev.end_date,
                "max_team_size": ev.max_team_size,
                "capacity": ev.capacity,
                "duty_leave_eligible": ev.duty_leave_eligible,
                "status": ev.status,
                "total_registrations": len(regs),
                "checked_in_count": sum(1 for r in regs if r.checked_in),
                "teams": [
                    {
                        "id": t.id,
                        "team_name": t.team_name,
                        "invite_code": t.invite_code,
                        "leader_name": users_map.get(t.leader_id, "Leader"),
                        "project_title": t.project_title,
                        "result_position": t.result_position,
                        "score": t.score,
                        "member_count": sum(1 for r in regs if r.team_id == t.id),
                    }
                    for t in teams
                ],
                "registrations": [
                    {
                        "id": r.id,
                        "student_id": r.student_id,
                        "student_name": users_map.get(r.student_id, r.student_id),
                        "team_id": r.team_id,
                        "checked_in": r.checked_in,
                    }
                    for r in regs[:50]
                ],
                "my_registration": (
                    {
                        "id": my_reg.id,
                        "team_id": my_reg.team_id,
                        "checked_in": my_reg.checked_in,
                        "result_badge": my_reg.result_badge,
                    }
                    if my_reg
                    else None
                ),
            }
        )
    return out


@app.post("/api/events")
def create_event(
    req: EventCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("ADMIN", "CAMPUS_MGR"):
        raise HTTPException(status_code=403, detail="Only Admin or Campus Manager can create events.")

    ev = Event(
        campus_id=req.campus_id or None,
        code=req.code.strip().upper(),
        title=req.title.strip(),
        category=req.category,
        scope=req.scope,
        description=req.description.strip(),
        venue=req.venue.strip(),
        start_date=req.start_date,
        end_date=req.end_date,
        max_team_size=req.max_team_size,
        capacity=req.capacity,
        duty_leave_eligible=req.duty_leave_eligible,
        checkin_secret=secrets.token_hex(16),
        status="UPCOMING",
    )
    db.add(ev)
    db.commit()
    return {"id": ev.id, "code": ev.code, "title": ev.title, "message": "Event created."}


@app.post("/api/events/{event_id}/register")
def register_for_event(
    event_id: str,
    req: EventRegisterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")

    target_student_id = req.student_id or current_user.id
    student_obj = db.query(User).filter(User.id == target_student_id).first() or current_user

    existing = (
        db.query(EventRegistration)
        .filter(EventRegistration.event_id == event_id, EventRegistration.student_id == target_student_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Already registered for this event.")

    team_id = None
    invite_code_created = None
    mode = req.mode.upper()

    if mode == "CREATE_TEAM":
        if not req.team_name:
            raise HTTPException(status_code=400, detail="Team name is required.")
        invite_code_created = f"TM-{secrets.token_hex(3).upper()}"
        team = EventTeam(
            event_id=event_id,
            team_name=req.team_name.strip(),
            invite_code=invite_code_created,
            leader_id=target_student_id,
            project_title=req.project_title,
        )
        db.add(team)
        db.flush()
        team_id = team.id

    elif mode == "JOIN_TEAM":
        if not req.invite_code:
            raise HTTPException(status_code=400, detail="Invite code is required to join a team.")
        team = (
            db.query(EventTeam)
            .filter(EventTeam.event_id == event_id, EventTeam.invite_code == req.invite_code.strip().upper())
            .first()
        )
        if not team:
            raise HTTPException(status_code=404, detail="Invalid team invite code.")
        current_members = db.query(EventRegistration).filter(EventRegistration.team_id == team.id).count()
        if current_members >= ev.max_team_size:
            raise HTTPException(status_code=400, detail=f"Team '{team.team_name}' is full (max {ev.max_team_size}).")
        team_id = team.id

    reg = EventRegistration(
        event_id=event_id,
        team_id=team_id,
        student_id=target_student_id,
        checked_in=False,
    )
    db.add(reg)

    duty_leave_created = False
    if ev.duty_leave_eligible and student_obj.campus_id:
        existing_dl = (
            db.query(DutyLeaveRequest)
            .filter(DutyLeaveRequest.event_id == event_id, DutyLeaveRequest.student_id == target_student_id)
            .first()
        )
        if not existing_dl:
            dl = DutyLeaveRequest(
                event_id=event_id,
                student_id=target_student_id,
                campus_id=student_obj.campus_id,
                leave_dates=f"{ev.start_date} to {ev.end_date}",
                reason=f"Auto-generated Duty Leave for event registration: {ev.title} ({ev.scope}).",
                status="PENDING_CM_APPROVAL",
            )
            db.add(dl)
            duty_leave_created = True

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Duplicate registration or team name conflict.")

    return {
        "registration_id": reg.id,
        "event_id": event_id,
        "student_id": target_student_id,
        "team_id": team_id,
        "invite_code": invite_code_created,
        "duty_leave_auto_generated": duty_leave_created,
        "message": "Registered for event." + (" Duty Leave request auto-generated." if duty_leave_created else ""),
    }


@app.post("/api/events/{event_id}/checkin")
def checkin_to_event(
    event_id: str,
    student_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target_id = student_id or current_user.id
    reg = (
        db.query(EventRegistration)
        .filter(EventRegistration.event_id == event_id, EventRegistration.student_id == target_id)
        .first()
    )
    if not reg:
        raise HTTPException(status_code=404, detail="Student is not registered for this event.")
    reg.checked_in = True
    reg.checked_in_at = datetime.utcnow()
    db.commit()
    return {"id": reg.id, "checked_in": True, "checked_in_at": reg.checked_in_at.isoformat()}


@app.patch("/api/teams/{team_id}/result")
def update_team_result(
    team_id: str,
    req: TeamResultUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "STUDENT":
        raise HTTPException(status_code=403, detail="Students cannot set event results.")
    team = db.query(EventTeam).filter(EventTeam.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    team.result_position = req.result_position.upper()
    team.score = req.score
    db.commit()
    return {"id": team.id, "result_position": team.result_position, "score": team.score}


# ============================================================================
# 8. Certificates, Co-Curricular Transcripts & Public Tamper Verification
# ============================================================================

@app.get("/api/certificates")
def list_certificates(
    student_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Certificate)
    if student_id:
        q = q.filter(Certificate.student_id == student_id)
    certs = q.order_by(Certificate.issued_at.desc()).all()
    users_map = {u.id: u for u in db.query(User).all()}

    return [
        {
            "id": c.id,
            "serial_number": c.serial_number,
            "student_id": c.student_id,
            "student_name": users_map[c.student_id].full_name if c.student_id in users_map else "",
            "roll_number": users_map[c.student_id].roll_number if c.student_id in users_map else "",
            "cert_type": c.cert_type,
            "title": c.title,
            "citation": c.citation,
            "verification_evidence": c.verification_evidence,
            "issued_by_name": c.issued_by_name,
            "pdf_sha256_hash": c.pdf_sha256_hash,
            "hmac_signature": c.hmac_signature,
            "download_url": f"/api/certificates/{c.serial_number}/download",
            "verify_url": f"/api/verify/{c.serial_number}",
            "issued_at": c.issued_at.isoformat() if c.issued_at else None,
        }
        for c in certs
    ]


@app.post("/api/certificates/issue")
def issue_new_certificate(
    req: CertificateIssueRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("ADVISOR", "ADMIN", "CAMPUS_MGR", "COORDINATOR"):
        raise HTTPException(status_code=403, detail="Students cannot issue certificates.")

    st = db.query(User).filter(User.id == req.student_id).first()
    if not st:
        raise HTTPException(status_code=404, detail="Recipient student not found")
    campus = db.query(Campus).filter(Campus.id == st.campus_id).first()

    count = db.query(Certificate).count() + 1
    serial = f"MSOT-CERT-2026-{count:04d}"
    while db.query(Certificate).filter(Certificate.serial_number == serial).first():
        serial = f"MSOT-CERT-2026-{count:04d}-{secrets.token_hex(2).upper()}"

    pdf_info = generate_certificate_pdf(
        serial_number=serial,
        student_name=st.full_name,
        roll_number=st.roll_number or "MSOT-STUDENT",
        campus_name=campus.name if campus else "MSOT Campus",
        student_id=st.id,
        cert_type=req.cert_type,
        title=req.title,
        citation=req.citation,
        verification_evidence=req.verification_evidence,
        issued_by_name=current_user.full_name,
        issued_by_role=current_user.role.replace("_", " ").title(),
        issued_date_str=datetime.utcnow().strftime("%Y-%m-%d"),
    )

    upload_to_supabase_storage(pdf_info["filepath"], f"certificates/{pdf_info['filename']}")

    cert = Certificate(
        serial_number=serial,
        student_id=st.id,
        club_id=req.club_id or None,
        event_id=req.event_id or None,
        cert_type=req.cert_type,
        title=req.title,
        citation=req.citation,
        verification_evidence=req.verification_evidence,
        issued_by_name=current_user.full_name,
        issued_by_role=current_user.role,
        pdf_filename=pdf_info["filename"],
        pdf_sha256_hash=pdf_info["pdf_sha256_hash"],
        hmac_signature=pdf_info["hmac_signature"],
    )
    db.add(cert)
    db.commit()
    return {
        "serial_number": cert.serial_number,
        "pdf_sha256_hash": cert.pdf_sha256_hash,
        "download_url": f"/api/certificates/{cert.serial_number}/download",
    }


@app.post("/api/transcripts/generate/{student_id}")
def generate_student_verified_transcript(
    student_id: str,
    db: Session = Depends(get_db),
):
    st = db.query(User).filter(User.id == student_id).first()
    if not st:
        raise HTTPException(status_code=404, detail="Student not found")

    campus = db.query(Campus).filter(Campus.id == st.campus_id).first()
    clubs_map = {c.id: c for c in db.query(Club).all()}

    memberships = db.query(ClubMembership).filter(ClubMembership.student_id == student_id).all()
    clubs_summary = [
        {
            "club_name": clubs_map[m.club_id].name if m.club_id in clubs_map else m.club_id,
            "category": clubs_map[m.club_id].category if m.club_id in clubs_map else "Club",
            "tier": m.tier,
            "status": m.status,
        }
        for m in memberships
    ]

    attendances = db.query(Attendance).filter(Attendance.student_id == student_id).all()
    sessions_history = []
    for a in attendances:
        sess = db.query(ClubDaySession).filter(ClubDaySession.id == a.session_id).first()
        if not sess:
            continue
        cl = clubs_map.get(sess.club_id)
        sub = (
            db.query(Submission)
            .filter(Submission.session_id == sess.id, Submission.student_id == student_id)
            .first()
        )
        score_val = sub.evaluation.total_score if (sub and sub.evaluation) else None
        sessions_history.append(
            {
                "date": sess.scheduled_date,
                "club_code": cl.code if cl else "CLUB",
                "topic": sess.topic,
                "attendance_status": a.status,
                "method": a.method,
                "is_presenter": a.is_presenter,
                "total_score": score_val,
            }
        )

    event_regs = db.query(EventRegistration).filter(EventRegistration.student_id == student_id).all()
    events_history = []
    for r in event_regs:
        ev = db.query(Event).filter(Event.id == r.event_id).first()
        tm = db.query(EventTeam).filter(EventTeam.id == r.team_id).first() if r.team_id else None
        if ev:
            events_history.append(
                {
                    "title": ev.title,
                    "category": ev.category,
                    "team_name": tm.team_name if tm else "Individual",
                    "checked_in": r.checked_in,
                    "result": r.result_badge or (tm.result_position if tm else "Participant"),
                }
            )

    certs = db.query(Certificate).filter(Certificate.student_id == student_id).all()
    serial = f"MSOT-TRANSCRIPT-{st.roll_number or student_id[-6:]}"

    pdf_info = generate_transcript_pdf(
        serial_number=serial,
        student={
            "id": st.id,
            "full_name": st.full_name,
            "roll_number": st.roll_number,
            "campus_name": campus.name if campus else "MSOT Campus",
            "track": st.track,
            "batch": st.batch,
        },
        clubs_summary=clubs_summary,
        sessions_history=sessions_history,
        events_history=events_history,
        certificates_list=[{"serial_number": c.serial_number} for c in certs],
    )

    existing_cert = db.query(Certificate).filter(Certificate.serial_number == serial).first()
    if existing_cert:
        existing_cert.pdf_sha256_hash = pdf_info["pdf_sha256_hash"]
        existing_cert.hmac_signature = pdf_info["hmac_signature"]
        existing_cert.issued_at = datetime.utcnow()
    else:
        db.add(
            Certificate(
                serial_number=serial,
                student_id=st.id,
                cert_type="TRANSCRIPT",
                title=f"Official Co-Curricular Transcript — {st.full_name}",
                citation="Verified student co-curricular record.",
                verification_evidence=f"{len(sessions_history)} Club Days & {len(events_history)} Events",
                issued_by_name="MSOT Co-Curricular Registry",
                issued_by_role="Registrar",
                pdf_filename=pdf_info["filename"],
                pdf_sha256_hash=pdf_info["pdf_sha256_hash"],
                hmac_signature=pdf_info["hmac_signature"],
            )
        )
    db.commit()

    return {
        "serial_number": serial,
        "student_name": st.full_name,
        "pdf_sha256_hash": pdf_info["pdf_sha256_hash"],
        "download_url": f"/api/certificates/{serial}/download",
        "verify_url": f"/api/verify/{serial}",
    }


@app.get("/api/certificates/{serial_number}/download")
def download_certificate_pdf(serial_number: str, db: Session = Depends(get_db)):
    cert = db.query(Certificate).filter(Certificate.serial_number == serial_number).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate or Transcript not found")
    filepath = os.path.join(CERT_DIR, cert.pdf_filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="PDF file not found")
    return FileResponse(filepath, media_type="application/pdf", filename=cert.pdf_filename)


@app.get("/api/verify/{serial_number}")
def verify_certificate_by_serial(serial_number: str, db: Session = Depends(get_db)):
    cert = db.query(Certificate).filter(Certificate.serial_number == serial_number).first()
    if not cert:
        return {
            "verified": False,
            "status": "RECORD_NOT_FOUND",
            "message": f"No certificate or transcript found for serial '{serial_number}'.",
        }

    st = db.query(User).filter(User.id == cert.student_id).first()
    campus = db.query(Campus).filter(Campus.id == st.campus_id).first() if st else None
    return {
        "verified": True,
        "status": "AUTHENTIC_VERIFIED_RECORD",
        "serial_number": cert.serial_number,
        "cert_type": cert.cert_type,
        "recipient": {
            "full_name": st.full_name if st else "Unknown",
            "roll_number": st.roll_number if st else "",
            "campus": campus.name if campus else "MSOT",
            "track": st.track if st else "Mirai Track",
        },
        "title": cert.title,
        "citation": cert.citation,
        "verification_evidence": cert.verification_evidence,
        "issued_by": f"{cert.issued_by_name} ({cert.issued_by_role})",
        "issued_at": cert.issued_at.isoformat() if cert.issued_at else None,
        "cryptographic_proof": {
            "pdf_sha256_hash": cert.pdf_sha256_hash,
            "hmac_signature": cert.hmac_signature,
        },
    }


@app.post("/api/verify/pdf")
async def verify_uploaded_pdf_tamper_check(
    file: UploadFile = File(...),
    expected_serial: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
):
    pdf_bytes = await file.read()
    computed_sha256 = hashlib.sha256(pdf_bytes).hexdigest()

    matching_cert = db.query(Certificate).filter(Certificate.pdf_sha256_hash == computed_sha256).first()
    if matching_cert:
        if expected_serial and matching_cert.serial_number != expected_serial:
            return {
                "verified": False,
                "status": "SERIAL_MISMATCH",
                "computed_sha256": computed_sha256,
                "message": "PDF belongs to a different certificate serial number.",
            }
        st = db.query(User).filter(User.id == matching_cert.student_id).first()
        return {
            "verified": True,
            "status": "AUTHENTIC_UNTAMPERED_PDF",
            "serial_number": matching_cert.serial_number,
            "student_name": st.full_name if st else "",
            "cert_type": matching_cert.cert_type,
            "title": matching_cert.title,
            "computed_sha256": computed_sha256,
            "expected_sha256": matching_cert.pdf_sha256_hash,
            "message": "PDF is authentic and untampered.",
        }

    claimed_serial = expected_serial
    if not claimed_serial and b"SERIAL:" in pdf_bytes:
        try:
            idx = pdf_bytes.index(b"SERIAL:")
            snippet = pdf_bytes[idx + 7 : idx + 60].decode("latin-1", errors="ignore")
            claimed_serial = snippet.split("|")[0].split(")")[0].strip()
        except Exception:
            claimed_serial = None

    target_cert = (
        db.query(Certificate).filter(Certificate.serial_number == claimed_serial).first()
        if claimed_serial
        else None
    )

    db.add(
        AuditLog(
            action="TAMPERED_PDF_REJECTED",
            entity_type="CERTIFICATE",
            entity_id=claimed_serial or "UNKNOWN",
            details=f"Tampered PDF upload detected! Computed SHA256={computed_sha256[:16]}... did not match ledger.",
        )
    )
    db.commit()

    return {
        "verified": False,
        "status": "TAMPERED_PDF_DETECTED",
        "claimed_serial": claimed_serial,
        "computed_sha256": computed_sha256,
        "expected_sha256": target_cert.pdf_sha256_hash if target_cert else None,
        "message": "Verification failed: The uploaded PDF has been modified or is not an official MSOT certificate.",
    }


# ============================================================================
# 9. Dashboards, Monthly Reports & Academic Review CSV Exports
# ============================================================================

@app.get("/api/reports/monthly")
def get_monthly_club_reports(
    campus_id: Optional[str] = None,
    club_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    from sqlalchemy import func
    q = db.query(Club)
    if campus_id:
        q = q.filter(Club.campus_id == campus_id)
    if club_id:
        q = q.filter(Club.id == club_id)
    clubs = q.all()
    campuses_map = {c.id: c.code for c in db.query(Campus).all()}

    club_ids = [cl.id for cl in clubs]
    if not club_ids:
        return {"generated_at": datetime.utcnow().isoformat(), "club_reports": []}

    # 1. Batch approved membership counts in 1 query
    approved_mems_by_club = dict(
        db.query(ClubMembership.club_id, func.count(ClubMembership.id))
        .filter(ClubMembership.club_id.in_(club_ids), ClubMembership.status == "APPROVED")
        .group_by(ClubMembership.club_id)
        .all()
    )

    # 2. Batch all sessions for these clubs in 1 query
    sessions = (
        db.query(ClubDaySession)
        .filter(ClubDaySession.club_id.in_(club_ids))
        .all()
    )
    sessions_by_club: Dict[str, list] = {}
    completed_session_ids = []
    for s in sessions:
        if s.checkin_status in ("OPEN", "COMPLETED"):
            sessions_by_club.setdefault(s.club_id, []).append(s)
            completed_session_ids.append(s.id)

    # 3. Batch attendances & submissions in single queries
    attendances_by_session: Dict[str, list] = {}
    if completed_session_ids:
        raw_atts = (
            db.query(Attendance)
            .filter(
                Attendance.session_id.in_(completed_session_ids),
                Attendance.status.in_(["PRESENT", "LATE"]),
            )
            .all()
        )
        for a in raw_atts:
            attendances_by_session.setdefault(a.session_id, []).append(a)

    submissions_by_session: Dict[str, list] = {}
    if completed_session_ids:
        raw_subs = db.query(Submission).filter(Submission.session_id.in_(completed_session_ids)).all()
        for sub in raw_subs:
            submissions_by_session.setdefault(sub.session_id, []).append(sub)

    reports = []
    for cl in clubs:
        approved_members = approved_mems_by_club.get(cl.id, 0)
        completed_sessions = sessions_by_club.get(cl.id, [])
        session_ids = [s.id for s in completed_sessions]

        raw_attendances = []
        raw_submissions = []
        for sid in session_ids:
            raw_attendances.extend(attendances_by_session.get(sid, []))
            raw_submissions.extend(submissions_by_session.get(sid, []))

        expected_total_checkins = approved_members * len(completed_sessions)
        attendance_pct = (
            round((len(raw_attendances) / expected_total_checkins) * 100.0, 2)
            if expected_total_checkins > 0
            else 0.0
        )

        eval_scores = [
            sub.evaluation.total_score
            for sub in raw_submissions
            if sub.evaluation is not None
        ]
        avg_score = round(sum(eval_scores) / len(eval_scores), 2) if eval_scores else 0.0
        presenter_count = sum(1 for a in raw_attendances if a.is_presenter)
        late_checkins = sum(1 for a in raw_attendances if a.status == "LATE")
        manual_overrides = sum(1 for a in raw_attendances if a.method == "MANUAL_OVERRIDE")

        reports.append(
            {
                "club_id": cl.id,
                "club_code": cl.code,
                "club_name": cl.name,
                "campus_code": campuses_map.get(cl.campus_id, "HI-Tech"),
                "status": cl.status,
                "approved_members": approved_members,
                "sessions_conducted": len(completed_sessions),
                "expected_checkins": expected_total_checkins,
                "actual_verified_checkins": len(raw_attendances),
                "attendance_percentage": attendance_pct,
                "total_submissions": len(raw_submissions),
                "evaluated_submissions": len(eval_scores),
                "average_rubric_score": avg_score,
                "presenters_count": presenter_count,
                "late_checkins_flagged": late_checkins,
                "manual_overrides_logged": manual_overrides,
                "highlights": (
                    f"{len(completed_sessions)} sessions; {presenter_count} presenters; avg score {avg_score}/30."
                    if completed_sessions
                    else "No sessions conducted yet."
                ),
            }
        )
    return {"generated_at": datetime.utcnow().isoformat(), "club_reports": reports}


@app.get("/api/dashboard/overview")
def get_dashboard_analytics(
    campus_id: Optional[str] = None,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
):
    cleanup_expired_sessions(db)
    campuses = db.query(Campus).all()
    clubs = db.query(Club).all()
    students = db.query(User).filter(User.role == "STUDENT").all()
    attendances = db.query(Attendance).filter(Attendance.status.in_(["PRESENT", "LATE"])).all()
    submissions = db.query(Submission).all()
    event_regs = db.query(EventRegistration).all()

    campus_stats = []
    for c in campuses:
        c_clubs = [cl for cl in clubs if cl.campus_id == c.id]
        c_students = [s for s in students if s.campus_id == c.id]
        c_student_ids = {s.id for s in c_students}
        c_att = [a for a in attendances if a.student_id in c_student_ids]
        c_sub = [s for s in submissions if s.student_id in c_student_ids]
        active_st_ids = {a.student_id for a in c_att} | {r.student_id for r in event_regs if r.student_id in c_student_ids}

        campus_stats.append(
            {
                "campus_id": c.id,
                "campus_code": c.code,
                "campus_name": c.name,
                "total_clubs": len(c_clubs),
                "active_clubs": sum(1 for cl in c_clubs if cl.status == "ACTIVE"),
                "total_students": len(c_students),
                "participating_students": len(active_st_ids),
                "participation_rate_pct": round((len(active_st_ids) / len(c_students)) * 100.0, 1) if c_students else 0.0,
                "verified_checkins": len(c_att),
                "deliverables_submitted": len(c_sub),
            }
        )

    from sqlalchemy import func
    sess_counts = dict(
        db.query(ClubDaySession.club_id, func.count(ClubDaySession.id))
        .group_by(ClubDaySession.club_id)
        .all()
    )
    inactive_clubs = []
    campuses_map = {c.id: c.code for c in campuses}
    for cl in clubs:
        sess_count = sess_counts.get(cl.id, 0)
        if cl.status == "INACTIVE" or sess_count == 0:
            inactive_clubs.append(
                {
                    "club_id": cl.id,
                    "code": cl.code,
                    "name": cl.name,
                    "campus_code": campuses_map.get(cl.campus_id, ""),
                    "status": cl.status,
                    "sessions_count": sess_count,
                    "reason": "Inactive or 0 sessions conducted",
                }
            )

    att_by_student: Dict[str, int] = {}
    pres_by_student: Dict[str, int] = {}
    for a in attendances:
        att_by_student[a.student_id] = att_by_student.get(a.student_id, 0) + 1
        if a.is_presenter:
            pres_by_student[a.student_id] = pres_by_student.get(a.student_id, 0) + 1

    eval_by_submission = {
        row[0]: row[1]
        for row in db.query(Evaluation.submission_id, Evaluation.total_score).all()
    }
    sub_by_student: Dict[str, int] = {}
    score_by_student: Dict[str, float] = {}
    for s in submissions:
        sub_by_student[s.student_id] = sub_by_student.get(s.student_id, 0) + 1
        eval_score = eval_by_submission.get(s.id)
        if eval_score is not None:
            score_by_student[s.student_id] = round(score_by_student.get(s.student_id, 0.0) + eval_score, 2)

    ev_by_student: Dict[str, int] = {}
    for r in event_regs:
        ev_by_student[r.student_id] = ev_by_student.get(r.student_id, 0) + 1

    zero_participation_students = []
    student_rankings = []

    for st in students:
        if campus_id and st.campus_id != campus_id:
            continue
        c_att = att_by_student.get(st.id, 0)
        c_sub = sub_by_student.get(st.id, 0)
        c_ev = ev_by_student.get(st.id, 0)
        c_pres = pres_by_student.get(st.id, 0)
        c_score = score_by_student.get(st.id, 0.0)

        if c_att == 0 and c_sub == 0 and c_ev == 0:
            zero_participation_students.append(
                {
                    "student_id": st.id,
                    "full_name": st.full_name,
                    "roll_number": st.roll_number,
                    "campus_code": campuses_map.get(st.campus_id, ""),
                    "batch": st.batch,
                    "track": st.track,
                }
            )
        else:
            student_rankings.append(
                {
                    "student_id": st.id,
                    "full_name": st.full_name,
                    "roll_number": st.roll_number,
                    "campus_code": campuses_map.get(st.campus_id, ""),
                    "track": st.track,
                    "sessions_attended": c_att,
                    "presentations_given": c_pres,
                    "submissions_count": c_sub,
                    "events_count": c_ev,
                    "cumulative_rubric_score": c_score,
                }
            )

    student_rankings.sort(key=lambda x: (x["cumulative_rubric_score"], x["sessions_attended"]), reverse=True)

    # Attendance percentage for currently logged-in user & president club summary
    my_attendance = None
    president_club_summary = None

    token_user_id = None
    if authorization and authorization.startswith("Bearer "):
        token_user_id = decode_access_token(authorization.replace("Bearer ", "", 1).strip())
    current_uid = token_user_id or x_user_id

    if current_uid:
        cur_u = db.query(User).filter(User.id == current_uid).first()
        if cur_u:
            # 1. User's personal attendance metrics
            user_mems = db.query(ClubMembership).filter(
                ClubMembership.student_id == cur_u.id,
                ClubMembership.status == "APPROVED"
            ).all()
            user_club_ids = [m.club_id for m in user_mems]
            
            if user_club_ids:
                u_sessions = db.query(ClubDaySession).filter(ClubDaySession.club_id.in_(user_club_ids)).all()
            elif cur_u.campus_id:
                campus_club_ids = [c.id for c in clubs if c.campus_id == cur_u.campus_id]
                u_sessions = db.query(ClubDaySession).filter(ClubDaySession.club_id.in_(campus_club_ids)).all() if campus_club_ids else []
            else:
                u_sessions = db.query(ClubDaySession).all()

            u_session_ids = [s.id for s in u_sessions]
            total_sessions_count = len(u_sessions)

            user_atts = (
                db.query(Attendance)
                .filter(
                    Attendance.student_id == cur_u.id,
                    Attendance.status.in_(["PRESENT", "LATE"])
                )
                .all()
            )
            if u_session_ids:
                user_atts = [a for a in user_atts if a.session_id in u_session_ids]
            
            attended_count = len(user_atts)
            late_count = sum(1 for a in user_atts if a.status == "LATE")
            present_count = attended_count - late_count
            missed_count = max(0, total_sessions_count - attended_count)
            att_pct = round((attended_count / total_sessions_count) * 100.0, 1) if total_sessions_count > 0 else (100.0 if attended_count > 0 else 0.0)

            standing = "GOOD_STANDING" if att_pct >= 75.0 else "NEEDS_IMPROVEMENT"
            if att_pct >= 90.0:
                standing = "EXCELLENT"

            my_attendance = {
                "student_id": cur_u.id,
                "full_name": cur_u.full_name,
                "role": cur_u.role,
                "total_sessions": total_sessions_count,
                "attended_sessions": attended_count,
                "present_count": present_count,
                "late_count": late_count,
                "missed_sessions": missed_count,
                "attendance_percentage": att_pct,
                "standing": standing,
            }

            # 2. If user is PRESIDENT or COORDINATOR, compute their club attendance overview
            if cur_u.role in ("PRESIDENT", "COORDINATOR", "ADMIN", "CAMPUS_MGR"):
                pres_club = None
                if cur_u.role in ("PRESIDENT", "COORDINATOR"):
                    p_mem = db.query(ClubMembership).filter(
                        ClubMembership.student_id == cur_u.id,
                        ClubMembership.tier.in_(["PRESIDENT", "COORDINATOR"]),
                        ClubMembership.status == "APPROVED"
                    ).first()
                    if p_mem:
                        pres_club = db.query(Club).filter(Club.id == p_mem.club_id).first()
                if not pres_club and cur_u.campus_id:
                    pres_club = db.query(Club).filter(Club.campus_id == cur_u.campus_id).first()
                if not pres_club:
                    pres_club = db.query(Club).first()

                if pres_club:
                    p_sessions = db.query(ClubDaySession).filter(ClubDaySession.club_id == pres_club.id).all()
                    p_mems = db.query(ClubMembership).filter(ClubMembership.club_id == pres_club.id, ClubMembership.status == "APPROVED").all()
                    p_sess_ids = [s.id for s in p_sessions]
                    p_atts = db.query(Attendance).filter(Attendance.session_id.in_(p_sess_ids), Attendance.status.in_(["PRESENT", "LATE"])).all() if p_sess_ids else []
                    
                    expected_checkins = len(p_mems) * len(p_sessions)
                    club_rate = round((len(p_atts) / expected_checkins) * 100.0, 1) if expected_checkins > 0 else 0.0

                    president_club_summary = {
                        "club_id": pres_club.id,
                        "club_name": pres_club.name,
                        "club_code": pres_club.code,
                        "total_members": len(p_mems),
                        "total_sessions": len(p_sessions),
                        "verified_checkins": len(p_atts),
                        "overall_attendance_pct": club_rate,
                    }

    return {
        "campus_breakdown": campus_stats,
        "inactive_clubs": inactive_clubs,
        "zero_participation_students": zero_participation_students,
        "top_contributors": student_rankings[:15],
        "monthly_club_reports": get_monthly_club_reports(campus_id=campus_id, db=db)["club_reports"],
        "my_attendance": my_attendance,
        "president_club_summary": president_club_summary,
    }


@app.get("/api/reports/export-csv")
def export_academic_review_csv(db: Session = Depends(get_db)):
    from sqlalchemy import func
    students = db.query(User).filter(User.role == "STUDENT").all()
    campuses_map = {c.id: c.code for c in db.query(Campus).all()}

    student_ids = [st.id for st in students]
    if not student_ids:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["No student records found"])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=msot_cocurricular_report.csv"},
        )

    # 1. Batch counts in single queries
    mem_counts = dict(
        db.query(ClubMembership.student_id, func.count(ClubMembership.id))
        .filter(ClubMembership.student_id.in_(student_ids), ClubMembership.status == "APPROVED")
        .group_by(ClubMembership.student_id)
        .all()
    )
    ev_counts = dict(
        db.query(EventRegistration.student_id, func.count(EventRegistration.id))
        .filter(EventRegistration.student_id.in_(student_ids))
        .group_by(EventRegistration.student_id)
        .all()
    )
    cert_counts = dict(
        db.query(Certificate.student_id, func.count(Certificate.id))
        .filter(Certificate.student_id.in_(student_ids))
        .group_by(Certificate.student_id)
        .all()
    )

    # 2. Batch fetch attendances
    atts_by_student: Dict[str, list] = {}
    for a in db.query(Attendance).filter(Attendance.student_id.in_(student_ids), Attendance.status.in_(["PRESENT", "LATE"])).all():
        atts_by_student.setdefault(a.student_id, []).append(a)

    # 3. Batch fetch submissions
    subs_by_student: Dict[str, list] = {}
    for s in db.query(Submission).filter(Submission.student_id.in_(student_ids)).all():
        subs_by_student.setdefault(s.student_id, []).append(s)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Roll Number",
            "Student Name",
            "Campus",
            "Track",
            "Clubs Enrolled",
            "Club Days Attended",
            "Presentations",
            "Submissions",
            "Avg Rubric Score (/30)",
            "Events Participated",
            "Certificates Issued",
        ]
    )

    for st in students:
        mems = mem_counts.get(st.id, 0)
        atts = atts_by_student.get(st.id, [])
        pres = sum(1 for a in atts if a.is_presenter)
        subs = subs_by_student.get(st.id, [])
        scores = [s.evaluation.total_score for s in subs if s.evaluation]
        avg_sc = round(sum(scores) / len(scores), 2) if scores else 0.0
        evs = ev_counts.get(st.id, 0)
        certs = cert_counts.get(st.id, 0)

        writer.writerow(
            [
                st.roll_number or "",
                st.full_name,
                campuses_map.get(st.campus_id, "HI-Tech"),
                st.track,
                mems,
                len(atts),
                pres,
                len(subs),
                avg_sc,
                evs,
                certs,
            ]
        )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=msot_cocurricular_report.csv"},
    )


# ============================================================================
# President Exclusive: Member Attendance Roster & Tracking
# ============================================================================

@app.get("/api/president/club-attendance")
def get_president_club_attendance(
    club_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    President Exclusive: Track individual attendance percentage and session
    history for each club member. Accessible only to PRESIDENT, COORDINATOR, CAMPUS_MGR, ADMIN.
    """
    if current_user.role not in ("PRESIDENT", "COORDINATOR", "ADMIN", "CAMPUS_MGR", "ADVISOR"):
        raise HTTPException(
            status_code=403,
            detail="Access restricted: Only Club Presidents and Club Leadership can access the Member Attendance Roster.",
        )

    cleanup_expired_sessions(db)

    # 1. Determine available clubs for this user
    available_clubs = []
    if current_user.role in ("ADMIN", "CAMPUS_MGR"):
        q = db.query(Club)
        if current_user.role == "CAMPUS_MGR" and current_user.campus_id:
            q = q.filter(Club.campus_id == current_user.campus_id)
        available_clubs = q.all()
    else:
        # President / Coordinator: find their assigned clubs
        coord_mems = db.query(ClubMembership).filter(
            ClubMembership.student_id == current_user.id,
            ClubMembership.tier.in_(["PRESIDENT", "COORDINATOR"]),
            ClubMembership.status == "APPROVED"
        ).all()
        club_ids = [m.club_id for m in coord_mems]
        if club_ids:
            available_clubs = db.query(Club).filter(Club.id.in_(club_ids)).all()
        elif current_user.campus_id:
            available_clubs = db.query(Club).filter(Club.campus_id == current_user.campus_id).all()
        else:
            available_clubs = db.query(Club).all()

    if not available_clubs:
        return {
            "club": None,
            "available_clubs": [],
            "summary": {
                "total_members": 0,
                "total_sessions": 0,
                "average_attendance_pct": 0.0,
                "perfect_attendance_count": 0,
                "low_attendance_count": 0,
            },
            "sessions": [],
            "members": [],
        }

    # Selected club
    target_club = None
    if club_id:
        target_club = next((c for c in available_clubs if c.id == club_id), None)
        if not target_club:
            target_club = db.query(Club).filter(Club.id == club_id).first()
    if not target_club:
        target_club = available_clubs[0]

    # If the user is PRESIDENT and has no membership in target_club yet, auto-add as PRESIDENT
    if current_user.role in ("PRESIDENT", "COORDINATOR"):
        existing_mem = db.query(ClubMembership).filter(
            ClubMembership.club_id == target_club.id,
            ClubMembership.student_id == current_user.id
        ).first()
        if not existing_mem:
            db.add(ClubMembership(
                club_id=target_club.id,
                student_id=current_user.id,
                tier="PRESIDENT",
                status="APPROVED",
                approved_by_id=current_user.id,
            ))
            try:
                db.commit()
            except Exception:
                db.rollback()

    campuses_map = {c.id: c.code for c in db.query(Campus).all()}

    # Query all sessions of this club
    sessions = (
        db.query(ClubDaySession)
        .filter(ClubDaySession.club_id == target_club.id)
        .order_by(ClubDaySession.scheduled_date.desc(), ClubDaySession.week_number.desc())
        .all()
    )

    session_ids = [s.id for s in sessions]
    total_sessions_count = len(sessions)

    # Query all approved members of this club
    memberships = (
        db.query(ClubMembership)
        .filter(ClubMembership.club_id == target_club.id, ClubMembership.status == "APPROVED")
        .all()
    )

    member_user_ids = [m.student_id for m in memberships]
    users_dict = {
        u.id: u
        for u in db.query(User).filter(User.id.in_(member_user_ids)).all()
    } if member_user_ids else {}

    # Query attendances for all members across these sessions
    attendances = (
        db.query(Attendance)
        .filter(Attendance.session_id.in_(session_ids))
        .all()
        if session_ids else []
    )

    # Group attendances by student_id and by session_id
    att_by_student: Dict[str, List[Attendance]] = {}
    att_by_session: Dict[str, int] = {}
    for a in attendances:
        if a.status in ("PRESENT", "LATE"):
            att_by_student.setdefault(a.student_id, []).append(a)
            att_by_session[a.session_id] = att_by_session.get(a.session_id, 0) + 1

    # Build member roster
    member_roster = []
    perfect_count = 0
    low_count = 0

    for m in memberships:
        u = users_dict.get(m.student_id)
        if not u:
            continue
        mem_atts = att_by_student.get(u.id, [])
        attended_count = len(mem_atts)
        late_count = sum(1 for a in mem_atts if a.status == "LATE")
        missed_count = max(0, total_sessions_count - attended_count)
        pct = (
            round((attended_count / total_sessions_count) * 100.0, 1)
            if total_sessions_count > 0
            else 100.0
        )

        if pct >= 100.0 and total_sessions_count > 0:
            perfect_count += 1
        elif pct < 75.0 and total_sessions_count > 0:
            low_count += 1

        last_att = None
        last_topic = None
        if mem_atts:
            sorted_atts = sorted(mem_atts, key=lambda x: x.checked_in_at or datetime.min, reverse=True)
            last_att = sorted_atts[0].checked_in_at.strftime("%Y-%m-%d %H:%M") if sorted_atts[0].checked_in_at else None
            last_sess = next((s for s in sessions if s.id == sorted_atts[0].session_id), None)
            if last_sess:
                last_topic = last_sess.topic

        member_roster.append({
            "student_id": u.id,
            "full_name": u.full_name,
            "email": u.email,
            "roll_number": u.roll_number or "N/A",
            "tier": m.tier,
            "status": m.status,
            "joined_at": m.joined_at.strftime("%Y-%m-%d") if m.joined_at else None,
            "total_sessions": total_sessions_count,
            "attended_sessions": attended_count,
            "late_sessions": late_count,
            "missed_sessions": missed_count,
            "attendance_percentage": pct,
            "last_attended_date": last_att,
            "last_session_topic": last_topic,
        })

    # Sort roster: highest attendance first, then alphabetically
    member_roster.sort(key=lambda x: (-x["attendance_percentage"], x["full_name"]))

    # Sessions list with attendance counts
    sessions_list = []
    for s in sessions:
        present = att_by_session.get(s.id, 0)
        sessions_list.append({
            "id": s.id,
            "topic": s.topic,
            "scheduled_date": s.scheduled_date,
            "format": s.format,
            "checkin_status": s.checkin_status,
            "present_count": present,
            "total_expected": len(memberships),
            "attendance_pct": round((present / len(memberships)) * 100.0, 1) if memberships else 0.0,
        })

    total_expected_checkins = len(memberships) * total_sessions_count
    total_actual_checkins = sum(len(atts) for atts in att_by_student.values())
    avg_pct = round((total_actual_checkins / total_expected_checkins) * 100.0, 1) if total_expected_checkins > 0 else 0.0

    return {
        "club": {
            "id": target_club.id,
            "name": target_club.name,
            "code": target_club.code,
            "campus_code": campuses_map.get(target_club.campus_id, "HI-Tech"),
            "category": target_club.category,
        },
        "available_clubs": [
            {"id": c.id, "name": c.name, "code": c.code, "campus_code": campuses_map.get(c.campus_id, "")}
            for c in available_clubs
        ],
        "summary": {
            "total_members": len(memberships),
            "total_sessions": total_sessions_count,
            "average_attendance_pct": avg_pct,
            "perfect_attendance_count": perfect_count,
            "low_attendance_count": low_count,
        },
        "sessions": sessions_list,
        "members": member_roster,
    }


@app.get("/api/president/club-attendance/export-csv")
def export_president_attendance_csv(
    club_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    President Exclusive: Export member attendance roster as CSV.
    """
    data = get_president_club_attendance(club_id=club_id, db=db, current_user=current_user)
    club = data.get("club")
    club_name = club["name"] if club else "Club"
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([f"Member Attendance Roster - {club_name} ({club['code'] if club else ''})"])
    writer.writerow(["Generated At", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")])
    writer.writerow([])
    writer.writerow([
        "Roll Number",
        "Student Name",
        "Email",
        "Membership Tier",
        "Total Sessions Held",
        "Sessions Attended",
        "Late Check-ins",
        "Missed Sessions",
        "Attendance %",
        "Last Check-in Date",
        "Last Session Topic"
    ])
    for m in data.get("members", []):
        writer.writerow([
            m["roll_number"],
            m["full_name"],
            m["email"],
            m["tier"],
            m["total_sessions"],
            m["attended_sessions"],
            m["late_sessions"],
            m["missed_sessions"],
            f"{m['attendance_percentage']}%",
            m["last_attended_date"] or "Never",
            m["last_session_topic"] or "N/A",
        ])
    output.seek(0)
    filename = f"attendance_{club['code'] if club else 'club'}_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ============================================================================
# Middle 3 Stretch Goals Endpoints
# ============================================================================

@app.get("/api/budgets")
def list_budget_requests(club_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(BudgetRequest)
    if club_id:
        q = q.filter(BudgetRequest.club_id == club_id)
    rows = q.order_by(BudgetRequest.created_at.desc()).all()
    clubs_map = {c.id: c.name for c in db.query(Club).all()}
    users_map = {u.id: u.full_name for u in db.query(User).all()}

    return [
        {
            "id": r.id,
            "club_id": r.club_id,
            "club_name": clubs_map.get(r.club_id, ""),
            "requested_by": users_map.get(r.requested_by_id, "Coordinator"),
            "title": r.title,
            "category": r.category,
            "amount_inr": r.amount_inr,
            "description": r.description,
            "status": r.status,
            "approval_notes": r.approval_notes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@app.post("/api/budgets")
def create_budget_request(
    req: BudgetCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    verify_coordinator_club_access(db, current_user, req.club_id)
    b = BudgetRequest(
        club_id=req.club_id,
        requested_by_id=current_user.id,
        title=req.title,
        category=req.category,
        amount_inr=req.amount_inr,
        description=req.description,
        status="PENDING_ADVISOR",
    )
    db.add(b)
    db.commit()
    return {"id": b.id, "status": b.status, "message": "Budget request submitted."}


@app.patch("/api/budgets/{budget_id}/approve")
def review_budget_request(
    budget_id: str,
    req: BudgetApprovalRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("ADVISOR", "CAMPUS_MGR", "ADMIN"):
        raise HTTPException(status_code=403, detail="Only Faculty Advisor, Campus Manager, or Admin can review budgets.")

    b = db.query(BudgetRequest).filter(BudgetRequest.id == budget_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Budget request not found")

    if req.decision.upper() == "REJECT":
        b.status = "REJECTED"
    else:
        if current_user.role == "ADVISOR" and b.status == "PENDING_ADVISOR":
            b.status = "PENDING_CAMPUS_MGR"
        else:
            b.status = "APPROVED"

    b.approval_notes = req.notes or f"Reviewed by {current_user.full_name}"
    b.approved_by_id = current_user.id
    db.commit()
    return {"id": b.id, "status": b.status, "approval_notes": b.approval_notes}


@app.get("/api/duty-leaves")
def list_duty_leave_requests(campus_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(DutyLeaveRequest)
    if campus_id:
        q = q.filter(DutyLeaveRequest.campus_id == campus_id)
    rows = q.order_by(DutyLeaveRequest.created_at.desc()).all()

    users_map = {u.id: u for u in db.query(User).all()}
    events_map = {e.id: e for e in db.query(Event).all()}
    campuses_map = {c.id: c.code for c in db.query(Campus).all()}

    return [
        {
            "id": r.id,
            "event_id": r.event_id,
            "event_title": events_map[r.event_id].title if r.event_id in events_map else "",
            "event_scope": events_map[r.event_id].scope if r.event_id in events_map else "",
            "student_id": r.student_id,
            "student_name": users_map[r.student_id].full_name if r.student_id in users_map else "",
            "roll_number": users_map[r.student_id].roll_number if r.student_id in users_map else "",
            "campus_code": campuses_map.get(r.campus_id, "HI-Tech"),
            "leave_dates": r.leave_dates,
            "reason": r.reason,
            "status": r.status,
            "approved_at": r.approved_at.isoformat() if r.approved_at else None,
        }
        for r in rows
    ]


@app.post("/api/duty-leaves")
def create_duty_leave_request(
    req: DutyLeaveCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target_student_id = req.student_id or current_user.id
    student_obj = db.query(User).filter(User.id == target_student_id).first() or current_user
    default_campus = db.query(Campus).first()
    dl = DutyLeaveRequest(
        event_id=req.event_id,
        student_id=target_student_id,
        campus_id=student_obj.campus_id or (default_campus.id if default_campus else ""),
        leave_dates=req.leave_dates,
        reason=req.reason,
        status="PENDING_CM_APPROVAL",
    )
    db.add(dl)
    db.commit()
    return {"id": dl.id, "status": dl.status, "message": "Duty Leave request submitted."}


@app.patch("/api/duty-leaves/{leave_id}/approve")
def approve_duty_leave(
    leave_id: str,
    req: DutyLeaveDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("CAMPUS_MGR", "ADMIN"):
        raise HTTPException(status_code=403, detail="Only Campus Manager or Admin can approve Duty Leave requests.")
    dl = db.query(DutyLeaveRequest).filter(DutyLeaveRequest.id == leave_id).first()
    if not dl:
        raise HTTPException(status_code=404, detail="Duty Leave request not found")

    dl.status = req.status.upper()
    dl.approved_by_id = current_user.id
    dl.approved_at = datetime.utcnow()
    db.commit()
    return {"id": dl.id, "status": dl.status}


@app.get("/api/gallery")
def list_media_gallery(
    include_hidden: bool = False,
    db: Session = Depends(get_db),
):
    q = db.query(MediaGalleryItem)
    if not include_hidden:
        q = q.filter(MediaGalleryItem.student_consent.is_(True))
    items = q.order_by(MediaGalleryItem.created_at.desc()).all()

    events_map = {e.id: e.title for e in db.query(Event).all()}
    clubs_map = {c.id: c.name for c in db.query(Club).all()}
    users_map = {u.id: u.full_name for u in db.query(User).all()}

    return [
        {
            "id": item.id,
            "club_id": item.club_id,
            "club_name": clubs_map.get(item.club_id, ""),
            "event_id": item.event_id,
            "event_title": events_map.get(item.event_id, ""),
            "caption": item.caption,
            "media_url": item.media_url,
            "tagged_student_id": item.tagged_student_id,
            "tagged_student_name": users_map.get(item.tagged_student_id, "") if item.tagged_student_id else "",
            "student_consent": item.student_consent,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in items
    ]


@app.post("/api/gallery")
def upload_gallery_photo(
    req: MediaCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = MediaGalleryItem(
        club_id=req.club_id or None,
        event_id=req.event_id or None,
        uploaded_by_id=current_user.id,
        caption=req.caption,
        media_url=req.media_url,
        tagged_student_id=req.tagged_student_id or None,
        student_consent=req.student_consent,
    )
    db.add(item)
    db.commit()
    return {"id": item.id, "student_consent": item.student_consent, "message": "Photo added to gallery."}


@app.patch("/api/gallery/{item_id}/consent")
def update_photo_consent(
    item_id: str,
    req: ConsentToggleRequest,
    db: Session = Depends(get_db),
):
    item = db.query(MediaGalleryItem).filter(MediaGalleryItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Gallery item not found")
    item.student_consent = req.student_consent
    db.commit()
    return {
        "id": item.id,
        "student_consent": item.student_consent,
        "message": "Photo visibility updated.",
    }


# ============================================================================
# Club News & Announcements (Scoped by Membership; Authored by Presidents & CM)
# ============================================================================

@app.get("/api/club-news")
def list_club_news(
    club_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns club news.
    - If user is a STUDENT: Only sees news from clubs they are an APPROVED member of.
    - If user is a PRESIDENT or COORDINATOR: Sees news from their assigned club.
    - If user is a CAMPUS_MGR or ADMIN or ADVISOR: Can see news across their campus / all clubs.
    """
    q = db.query(ClubNews)
    if club_id:
        q = q.filter(ClubNews.club_id == club_id)

    # Student scoping: restricted strictly to approved club memberships
    if current_user.role == "STUDENT":
        approved_club_ids = [
            m.club_id
            for m in db.query(ClubMembership)
            .filter(ClubMembership.student_id == current_user.id, ClubMembership.status == "APPROVED")
            .all()
        ]
        q = q.filter(ClubNews.club_id.in_(approved_club_ids))
    elif current_user.role in ("PRESIDENT", "COORDINATOR"):
        # Sees news for their own assigned club
        pres_club_ids = [
            m.club_id
            for m in db.query(ClubMembership)
            .filter(
                ClubMembership.student_id == current_user.id,
                ClubMembership.tier.in_(["PRESIDENT", "COORDINATOR"]),
                ClubMembership.status == "APPROVED",
            )
            .all()
        ]
        if pres_club_ids:
            q = q.filter(ClubNews.club_id.in_(pres_club_ids))
    elif current_user.role == "CAMPUS_MGR" and current_user.campus_id:
        campus_club_ids = [c.id for c in db.query(Club).filter(Club.campus_id == current_user.campus_id).all()]
        q = q.filter(ClubNews.club_id.in_(campus_club_ids))

    news_items = q.order_by(ClubNews.pinned.desc(), ClubNews.created_at.desc()).all()
    clubs_map = {c.id: c for c in db.query(Club).all()}
    users_map = {u.id: u.full_name for u in db.query(User).all()}

    return [
        {
            "id": n.id,
            "club_id": n.club_id,
            "club_name": clubs_map[n.club_id].name if n.club_id in clubs_map else "",
            "club_code": clubs_map[n.club_id].code if n.club_id in clubs_map else "",
            "title": n.title,
            "content": n.content,
            "pinned": n.pinned,
            "author_id": n.author_id,
            "author_name": users_map.get(n.author_id, "Club President"),
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in news_items
    ]


@app.post("/api/club-news")
def create_club_news(
    req: ClubNewsCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Creates an official club news announcement.
    Allowed for:
    - Club President / Coordinator of this club
    - Campus Manager
    - System Admin
    - Faculty Advisor assigned to this club
    """
    club = db.query(Club).filter(Club.id == req.club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    # Permission check
    can_post = False
    if current_user.role == "ADMIN":
        can_post = True
    elif current_user.role == "CAMPUS_MGR":
        if not current_user.campus_id or club.campus_id == current_user.campus_id:
            can_post = True
    elif current_user.role == "ADVISOR":
        if club.advisor_id == current_user.id:
            can_post = True
    elif current_user.role in ("PRESIDENT", "COORDINATOR"):
        coord_mem = (
            db.query(ClubMembership)
            .filter(
                ClubMembership.club_id == req.club_id,
                ClubMembership.student_id == current_user.id,
                ClubMembership.tier.in_(["PRESIDENT", "COORDINATOR"]),
                ClubMembership.status == "APPROVED",
            )
            .first()
        )
        if coord_mem:
            can_post = True

    if not can_post:
        raise HTTPException(
            status_code=403,
            detail="Only the Club President, Campus Manager, or assigned Advisor can post news for this club.",
        )

    news = ClubNews(
        club_id=req.club_id,
        author_id=current_user.id,
        title=req.title.strip(),
        content=req.content.strip(),
        pinned=req.pinned,
    )
    db.add(news)
    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="CLUB_NEWS_POSTED",
            entity_type="CLUB_NEWS",
            entity_id=news.id,
            details=f"Posted news '{news.title}' for club {club.name} ({club.code})",
        )
    )
    db.commit()
    db.refresh(news)

    # Dispatch email notification to all approved club members
    memberships = db.query(ClubMembership).filter(
        ClubMembership.club_id == req.club_id,
        ClubMembership.status == "APPROVED"
    ).all()
    st_ids = [m.student_id for m in memberships]
    if st_ids:
        member_emails = [
            row[0]
            for row in db.query(User.email).filter(User.id.in_(st_ids), User.email != "").all()
        ]
        send_club_news_email(member_emails, club.name, news.title, news.content, current_user.full_name)

    return {
        "id": news.id,
        "title": news.title,
        "message": f"News broadcasted and emailed to members of {club.name}!",
    }


@app.delete("/api/club-news/{news_id}")
def delete_club_news(
    news_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    news = db.query(ClubNews).filter(ClubNews.id == news_id).first()
    if not news:
        raise HTTPException(status_code=404, detail="News item not found")

    can_delete = (
        current_user.role in ("ADMIN", "CAMPUS_MGR")
        or news.author_id == current_user.id
    )
    if not can_delete:
        raise HTTPException(status_code=403, detail="Not authorized to delete this news post.")

    db.delete(news)
    db.commit()
    return {"message": "News post deleted."}


@app.get("/api/audit-logs")
def list_audit_logs(limit: int = 40, db: Session = Depends(get_db)):
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()
    users_map = {u.id: u.full_name for u in db.query(User).all()}
    return [
        {
            "id": l.id,
            "actor_id": l.actor_id,
            "actor_name": users_map.get(l.actor_id, "System") if l.actor_id else "System",
            "action": l.action,
            "entity_type": l.entity_type,
            "entity_id": l.entity_id,
            "details": l.details,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]


# ============================================================================
# Admin Command Center & Multi-Campus Governance Power Tools
# ============================================================================

class AdminUserUpdateRequest(BaseModel):
    role: Optional[str] = None
    account_status: Optional[str] = None
    campus_id: Optional[str] = None
    roll_number: Optional[str] = None
    track: Optional[str] = None
    password: Optional[str] = None


class BulkUserOnboardingRequest(BaseModel):
    csv_text: str = Field(..., description="One user per line: Full Name, Email, Role, CampusCode, RollNumber, Password")


class SystemConfigUpdateRequest(BaseModel):
    max_primary_clubs: Optional[str] = None
    max_secondary_clubs: Optional[str] = None
    qr_rotation_seconds: Optional[str] = None
    geofence_check_enabled: Optional[str] = None


class CampusUpsertRequest(BaseModel):
    code: str
    name: str
    city: str = "Hyderabad"
    lat: float = 17.4435
    lng: float = 78.3772
    geofence_radius_m: float = 350.0


class BatchCertificateRequest(BaseModel):
    target_type: str = Field(..., description="EVENT or CLUB")
    target_id: str
    cert_type: str = "PARTICIPATION"
    title: str
    citation: str


@app.post("/api/admin/users/create")
def admin_create_user(
    req: RegisterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Allows Admin or Campus Manager to directly add a Student or Staff account (auto-approved)."""
    if current_user.role not in ("ADMIN", "CAMPUS_MGR"):
        raise HTTPException(status_code=403, detail="Only Admin or Campus Manager can directly add accounts.")

    email_clean = req.email.strip().lower()
    if not email_clean or not req.password or len(req.password) < 4:
        raise HTTPException(status_code=400, detail="Valid email and password (min 4 characters) are required.")
    if db.query(User).filter(User.email == email_clean).first():
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    roll_clean = req.roll_number.strip() if req.roll_number and req.roll_number.strip() else None
    if roll_clean and db.query(User).filter(User.roll_number == roll_clean).first():
        raise HTTPException(status_code=400, detail="This Roll / ID Number is already registered.")

    default_campus = db.query(Campus).first()
    campus_id = req.campus_id or current_user.campus_id or (default_campus.id if default_campus else None)

    user = User(
        email=email_clean,
        password_hash=hash_password(req.password),
        full_name=req.full_name.strip(),
        role=req.role.upper(),
        account_status="APPROVED",
        campus_id=campus_id,
        roll_number=roll_clean,
        batch=req.batch or "2025-2029 B.Tech",
        track=req.track or "Mirai Track",
    )
    db.add(user)
    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="USER_CREATED_BY_ADMIN",
            entity_type="USER",
            entity_id=user.id,
            details=f"Admin {current_user.full_name} added {user.role} account for {user.full_name} ({user.email}).",
        )
    )
    db.commit()
    db.refresh(user)
    campuses_map = {c.id: c.code for c in db.query(Campus).all()}
    return {"user": serialize_user(user, campuses_map), "message": f"Added {user.full_name} ({user.role}) with immediate access."}


@app.get("/api/admin/pending-queue")
def get_admin_pending_queue(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Unified inbox of every pending item across all campuses so Admins can act from one screen."""
    campuses_map = {row[0]: row[1] for row in db.query(Campus.id, Campus.code).all()}
    clubs_map = {row[0]: row[1] for row in db.query(Club.id, Club.name).all()}
    events_map = {row[0]: row[1] for row in db.query(Event.id, Event.title).all()}
    users_tuple = db.query(User.id, User.full_name, User.roll_number).all()
    user_names = {u[0]: u[1] for u in users_tuple}
    user_rolls = {u[0]: u[2] for u in users_tuple}

    pending_accounts = [
        {
            "id": u.id,
            "full_name": u.full_name,
            "email": u.email,
            "role": u.role,
            "roll_number": u.roll_number,
            "campus_code": campuses_map.get(u.campus_id, "HI-Tech"),
        }
        for u in db.query(User).filter(User.account_status == "PENDING_APPROVAL").all()
    ]

    pending_clubs = [
        {
            "id": c.id,
            "code": c.code,
            "name": c.name,
            "category": c.category,
            "campus_code": campuses_map.get(c.campus_id, "HI-Tech"),
        }
        for c in db.query(Club).filter(Club.status == "PENDING").all()
    ]

    pending_enrolments = [
        {
            "id": m.id,
            "club_id": m.club_id,
            "club_name": clubs_map.get(m.club_id, ""),
            "student_name": user_names.get(m.student_id, ""),
            "roll_number": user_rolls.get(m.student_id, ""),
            "tier": m.tier,
        }
        for m in db.query(ClubMembership).filter(ClubMembership.status == "PENDING").all()
    ]

    pending_sessions = [
        {
            "id": s.id,
            "club_name": clubs_map.get(s.club_id, ""),
            "week_number": s.week_number,
            "scheduled_date": s.scheduled_date,
            "topic": s.topic,
            "format": s.format,
        }
        for s in db.query(ClubDaySession).filter(ClubDaySession.plan_status == "PENDING_APPROVAL").all()
    ]

    pending_budgets = [
        {
            "id": b.id,
            "club_name": clubs_map.get(b.club_id, ""),
            "title": b.title,
            "amount_inr": b.amount_inr,
            "status": b.status,
        }
        for b in db.query(BudgetRequest)
        .filter(BudgetRequest.status.in_(["PENDING_ADVISOR", "PENDING_CAMPUS_MGR"]))
        .all()
    ]

    pending_duty_leaves = [
        {
            "id": d.id,
            "student_name": user_names.get(d.student_id, ""),
            "event_title": events_map.get(d.event_id, ""),
            "leave_dates": d.leave_dates,
            "campus_code": campuses_map.get(d.campus_id, "HI-Tech"),
        }
        for d in db.query(DutyLeaveRequest).filter(DutyLeaveRequest.status == "PENDING_CM_APPROVAL").all()
    ]

    return {
        "total_pending": (
            len(pending_accounts)
            + len(pending_clubs)
            + len(pending_enrolments)
            + len(pending_sessions)
            + len(pending_budgets)
            + len(pending_duty_leaves)
        ),
        "pending_accounts": pending_accounts,
        "pending_clubs": pending_clubs,
        "pending_enrolments": pending_enrolments,
        "pending_sessions": pending_sessions,
        "pending_budgets": pending_budgets,
        "pending_duty_leaves": pending_duty_leaves,
    }


@app.post("/api/admin/approve-all")
def admin_bulk_approve(
    category: str = Query(default="ALL", description="ALL, ACCOUNTS, CLUBS, ENROLMENTS, SESSIONS, BUDGETS, DUTY_LEAVES"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("ADMIN", "CAMPUS_MGR", "ADVISOR"):
        raise HTTPException(status_code=403, detail="Only Admin, Campus Manager, or Advisor can run bulk approvals.")

    cat = category.upper()
    counts = {"accounts": 0, "clubs": 0, "enrolments": 0, "sessions": 0, "budgets": 0, "duty_leaves": 0}
    now = datetime.utcnow()
    approved_users_for_email = []

    if cat in ("ALL", "ACCOUNTS") and current_user.role in ("ADMIN", "CAMPUS_MGR"):
        for u in db.query(User).filter(User.account_status == "PENDING_APPROVAL").all():
            u.account_status = "APPROVED"
            counts["accounts"] += 1
            approved_users_for_email.append((u.email, u.full_name, u.role, u.campus_id))

    if cat in ("ALL", "CLUBS") and current_user.role in ("ADMIN", "CAMPUS_MGR"):
        for c in db.query(Club).filter(Club.status == "PENDING").all():
            c.status = "ACTIVE"
            counts["clubs"] += 1

    if cat in ("ALL", "ENROLMENTS"):
        for m in db.query(ClubMembership).filter(ClubMembership.status == "PENDING").all():
            m.status = "APPROVED"
            m.approved_by_id = current_user.id
            counts["enrolments"] += 1

    if cat in ("ALL", "SESSIONS"):
        for s in db.query(ClubDaySession).filter(ClubDaySession.plan_status == "PENDING_APPROVAL").all():
            s.plan_status = "APPROVED"
            s.approved_by_id = current_user.id
            s.announced_at = now
            counts["sessions"] += 1

    if cat in ("ALL", "BUDGETS"):
        for b in db.query(BudgetRequest).filter(BudgetRequest.status.in_(["PENDING_ADVISOR", "PENDING_CAMPUS_MGR"])).all():
            b.status = "APPROVED"
            b.approved_by_id = current_user.id
            b.approval_notes = f"Bulk approved by {current_user.full_name}"
            counts["budgets"] += 1

    if cat in ("ALL", "DUTY_LEAVES") and current_user.role in ("ADMIN", "CAMPUS_MGR"):
        for d in db.query(DutyLeaveRequest).filter(DutyLeaveRequest.status == "PENDING_CM_APPROVAL").all():
            d.status = "APPROVED"
            d.approved_by_id = current_user.id
            d.approved_at = now
            counts["duty_leaves"] += 1

    total_approved = sum(counts.values())
    if total_approved > 0:
        db.add(
            AuditLog(
                actor_id=current_user.id,
                action="ADMIN_BULK_APPROVE",
                entity_type=cat,
                entity_id="BULK",
                details=f"Bulk approved {total_approved} items ({counts}) by {current_user.full_name}.",
            )
        )
    db.commit()

    if approved_users_for_email:
        campuses_dict = {c.id: c.name for c in db.query(Campus).all()}
        for email, full_name, role, cid in approved_users_for_email:
            cname = campuses_dict.get(cid, "Your Campus")
            send_account_approved_email(
                to_email=email,
                full_name=full_name,
                role=role,
                campus_name=cname,
            )

    return {"approved_counts": counts, "total_approved": total_approved, "message": f"Approved {total_approved} pending item(s)."}


@app.patch("/api/admin/users/{user_id}")
def admin_update_user(
    user_id: str,
    req: AdminUserUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("ADMIN", "CAMPUS_MGR"):
        raise HTTPException(status_code=403, detail="Only Admin or Campus Manager can modify user roles and profiles.")

    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    status_changed_to_approved = False
    if req.role:
        u.role = req.role.upper()
    if req.account_status:
        new_status = req.account_status.upper()
        if new_status == "APPROVED" and u.account_status != "APPROVED":
            status_changed_to_approved = True
        u.account_status = new_status
    if req.campus_id is not None:
        u.campus_id = req.campus_id or None
    if req.roll_number is not None:
        u.roll_number = req.roll_number.strip() or None
    if req.track:
        u.track = req.track
    if req.password and len(req.password) >= 4:
        u.password_hash = hash_password(req.password)

    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="USER_UPDATED_BY_ADMIN",
            entity_type="USER",
            entity_id=u.id,
            details=f"Updated {u.full_name} ({u.email}) role={u.role} status={u.account_status}",
        )
    )
    db.commit()

    if status_changed_to_approved:
        campus = db.query(Campus).filter(Campus.id == u.campus_id).first() if u.campus_id else None
        campus_name = campus.name if campus else "Your Campus"
        send_account_approved_email(
            to_email=u.email,
            full_name=u.full_name,
            role=u.role,
            campus_name=campus_name,
        )

    campuses_map = {c.id: c.code for c in db.query(Campus).all()}
    return serialize_user(u, campuses_map)


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("ADMIN", "CAMPUS_MGR"):
        raise HTTPException(status_code=403, detail="Only Admin or Campus Manager can remove accounts.")

    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")

    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")

    if current_user.role == "CAMPUS_MGR" and target_user.role == "ADMIN":
        raise HTTPException(status_code=403, detail="Campus Managers cannot remove System Admin accounts.")

    user_full_name = target_user.full_name
    user_email = target_user.email
    user_role = target_user.role

    # 1. Nullify references where target_user was an approver / advisor / planner / actor
    db.query(Club).filter(Club.advisor_id == user_id).update({Club.advisor_id: None})
    db.query(ClubMembership).filter(ClubMembership.approved_by_id == user_id).update({ClubMembership.approved_by_id: None})
    db.query(ClubDaySession).filter(ClubDaySession.planned_by_id == user_id).update({ClubDaySession.planned_by_id: None})
    db.query(ClubDaySession).filter(ClubDaySession.approved_by_id == user_id).update({ClubDaySession.approved_by_id: None})
    db.query(Attendance).filter(Attendance.overridden_by_id == user_id).update({Attendance.overridden_by_id: None})
    db.query(BudgetRequest).filter(BudgetRequest.approved_by_id == user_id).update({BudgetRequest.approved_by_id: None})
    db.query(DutyLeaveRequest).filter(DutyLeaveRequest.approved_by_id == user_id).update({DutyLeaveRequest.approved_by_id: None})
    db.query(MediaGalleryItem).filter(MediaGalleryItem.tagged_student_id == user_id).update({MediaGalleryItem.tagged_student_id: None})
    db.query(AuditLog).filter(AuditLog.actor_id == user_id).update({AuditLog.actor_id: None})

    # 2. Delete evaluations written by target_user
    db.query(Evaluation).filter(Evaluation.evaluator_id == user_id).delete(synchronize_session=False)

    # 3. Delete evaluations on submissions made by target_user, then delete submissions
    sub_ids = [s.id for s in db.query(Submission.id).filter(Submission.student_id == user_id).all()]
    if sub_ids:
        db.query(Evaluation).filter(Evaluation.submission_id.in_(sub_ids)).delete(synchronize_session=False)
        db.query(Submission).filter(Submission.id.in_(sub_ids)).delete(synchronize_session=False)

    # 4. Delete attendance, certificates, duty leaves, club memberships, and password reset OTPs
    db.query(Attendance).filter(Attendance.student_id == user_id).delete(synchronize_session=False)
    db.query(Certificate).filter(Certificate.student_id == user_id).delete(synchronize_session=False)
    db.query(DutyLeaveRequest).filter(DutyLeaveRequest.student_id == user_id).delete(synchronize_session=False)
    db.query(ClubMembership).filter(ClubMembership.student_id == user_id).delete(synchronize_session=False)
    db.query(BudgetRequest).filter(BudgetRequest.requested_by_id == user_id).delete(synchronize_session=False)
    db.query(MediaGalleryItem).filter(MediaGalleryItem.uploaded_by_id == user_id).delete(synchronize_session=False)
    db.query(ClubNews).filter(ClubNews.author_id == user_id).delete(synchronize_session=False)
    db.query(PasswordResetOTP).filter(PasswordResetOTP.email.ilike(user_email)).delete(synchronize_session=False)

    # 5. Delete event registrations and event teams led by target_user
    db.query(EventRegistration).filter(EventRegistration.student_id == user_id).delete(synchronize_session=False)
    teams_led = db.query(EventTeam).filter(EventTeam.leader_id == user_id).all()
    for team in teams_led:
        db.query(EventRegistration).filter(EventRegistration.team_id == team.id).delete(synchronize_session=False)
        db.delete(team)

    # 6. Delete target user
    db.delete(target_user)

    # 7. Record Audit Log
    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="USER_DELETED_BY_ADMIN",
            entity_type="USER",
            entity_id=user_id,
            details=f"Account '{user_full_name}' ({user_email}, role={user_role}) was permanently removed by {current_user.full_name} ({current_user.role}).",
        )
    )
    db.commit()
    return {"success": True, "message": f"Account '{user_full_name}' ({user_email}) has been permanently removed."}


@app.post("/api/admin/users/bulk")
def admin_bulk_onboard_users(
    req: BulkUserOnboardingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("ADMIN", "CAMPUS_MGR"):
        raise HTTPException(status_code=403, detail="Only Admin or Campus Manager can bulk-import users.")

    campuses = db.query(Campus).all()
    campus_by_code = {c.code.upper(): c.id for c in campuses}
    default_campus_id = campuses[0].id if campuses else None

    created = 0
    skipped = 0
    lines = [line.strip() for line in req.csv_text.splitlines() if line.strip()]
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2 or "@" not in parts[1]:
            skipped += 1
            continue
        full_name = parts[0]
        email = parts[1].lower()
        role = parts[2].upper() if len(parts) >= 3 and parts[2] else "STUDENT"
        if role not in ("STUDENT", "PRESIDENT", "COORDINATOR", "ADVISOR", "CAMPUS_MGR", "ADMIN"):
            role = "STUDENT"
        campus_code = parts[3].upper() if len(parts) >= 4 and parts[3] else ""
        roll_num = parts[4] if len(parts) >= 5 and parts[4] else None
        raw_pass = parts[5] if len(parts) >= 6 and parts[5] else "clubsync123"

        if db.query(User).filter(User.email == email).first():
            skipped += 1
            continue
        if roll_num and db.query(User).filter(User.roll_number == roll_num).first():
            roll_num = None

        c_id = campus_by_code.get(campus_code, current_user.campus_id or default_campus_id)
        db.add(
            User(
                full_name=full_name,
                email=email,
                password_hash=hash_password(raw_pass),
                role=role,
                account_status="APPROVED",
                campus_id=c_id,
                roll_number=roll_num,
                batch="2025-2029 B.Tech",
                track="Mirai Track",
            )
        )
        created += 1

    if created > 0:
        db.add(
            AuditLog(
                actor_id=current_user.id,
                action="BULK_USERS_ONBOARDED",
                entity_type="USER",
                entity_id="BULK",
                details=f"Onboarded {created} users via bulk CSV import ({skipped} skipped).",
            )
        )
    db.commit()
    return {"created": created, "skipped": skipped, "message": f"Onboarded {created} user(s) ({skipped} skipped)."}


@app.patch("/api/clubs/{club_id}/assign-advisor")
def assign_club_advisor(
    club_id: str,
    advisor_id: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("ADMIN", "CAMPUS_MGR"):
        raise HTTPException(status_code=403, detail="Only Admin or Campus Manager can assign a Faculty Advisor.")
    club = db.query(Club).filter(Club.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
    club.advisor_id = advisor_id or None
    adv = db.query(User).filter(User.id == advisor_id).first()
    if adv and adv.role == "STUDENT":
        adv.role = "ADVISOR"
    db.commit()
    return {"message": f"Assigned {adv.full_name if adv else 'Advisor'} as Faculty Advisor for {club.name}."}


@app.put("/api/admin/config")
def update_system_config(
    req: SystemConfigUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("ADMIN", "CAMPUS_MGR"):
        raise HTTPException(status_code=403, detail="Only Admin or Campus Manager can update system configuration.")

    updates = {
        "max_primary_clubs": req.max_primary_clubs,
        "max_secondary_clubs": req.max_secondary_clubs,
        "qr_rotation_seconds": req.qr_rotation_seconds,
        "geofence_check_enabled": req.geofence_check_enabled,
    }
    for k, val in updates.items():
        if val is not None:
            row = db.query(SystemConfig).filter(SystemConfig.key == k).first()
            if row:
                row.value = str(val)
            else:
                db.add(SystemConfig(key=k, value=str(val)))

    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="SYSTEM_CONFIG_UPDATED",
            entity_type="CONFIG",
            entity_id="GLOBAL",
            details=f"Updated system policies by {current_user.full_name}.",
        )
    )
    db.commit()
    return {"configs": {c.key: c.value for c in db.query(SystemConfig).all()}, "message": "System policies updated."}


@app.post("/api/admin/campuses")
def upsert_campus(
    req: CampusUpsertRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Only System Admin can add or update campuses.")
    existing = db.query(Campus).filter(Campus.code == req.code.strip()).first()
    if existing:
        existing.name = req.name.strip()
        existing.city = req.city.strip()
        existing.lat = req.lat
        existing.lng = req.lng
        existing.geofence_radius_m = req.geofence_radius_m
        _CLUB_GEOFENCE_CACHE.clear()
        db.commit()
        return {"id": existing.id, "code": existing.code, "message": f"Updated campus {existing.code}."}

    new_c = Campus(
        id=f"campus-{req.code.strip().lower().replace(' ', '-')}",
        code=req.code.strip(),
        name=req.name.strip(),
        city=req.city.strip(),
        lat=req.lat,
        lng=req.lng,
        geofence_radius_m=req.geofence_radius_m,
    )
    db.add(new_c)
    db.commit()
    return {"id": new_c.id, "code": new_c.code, "message": f"Created campus {new_c.code}."}


@app.post("/api/admin/certificates/batch")
def batch_issue_certificates(
    req: BatchCertificateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("ADMIN", "CAMPUS_MGR", "ADVISOR"):
        raise HTTPException(status_code=403, detail="Only Admin, Campus Manager, or Advisor can batch-issue certificates.")

    student_ids = []
    club_id_val = None
    event_id_val = None
    evidence_str = "Verified ClubSync Record"

    if req.target_type.upper() == "EVENT":
        ev = db.query(Event).filter(Event.id == req.target_id).first()
        if not ev:
            raise HTTPException(status_code=404, detail="Event not found")
        event_id_val = ev.id
        evidence_str = f"Event: {ev.title} ({ev.code})"
        regs = db.query(EventRegistration).filter(EventRegistration.event_id == ev.id).all()
        checked_in_regs = [r.student_id for r in regs if r.checked_in]
        student_ids = checked_in_regs if checked_in_regs else [r.student_id for r in regs]
    else:
        cl = db.query(Club).filter(Club.id == req.target_id).first()
        if not cl:
            raise HTTPException(status_code=404, detail="Club not found")
        club_id_val = cl.id
        evidence_str = f"Club: {cl.name} ({cl.code})"
        mems = (
            db.query(ClubMembership)
            .filter(ClubMembership.club_id == cl.id, ClubMembership.status == "APPROVED")
            .all()
        )
        student_ids = [m.student_id for m in mems]

    if not student_ids:
        raise HTTPException(status_code=400, detail="No eligible students found in the selected Club or Event.")

    issued_count = 0
    campuses_map = {c.id: c.name for c in db.query(Campus).all()}

    for sid in set(student_ids):
        st = db.query(User).filter(User.id == sid).first()
        if not st:
            continue
        count = db.query(Certificate).count() + 1 + issued_count
        serial = f"MSOT-CERT-2026-{count:04d}-{secrets.token_hex(2).upper()}"
        pdf_info = generate_certificate_pdf(
            serial_number=serial,
            student_name=st.full_name,
            roll_number=st.roll_number or "MSOT-STUDENT",
            campus_name=campuses_map.get(st.campus_id, "MSOT Campus"),
            student_id=st.id,
            cert_type=req.cert_type,
            title=req.title,
            citation=req.citation,
            verification_evidence=evidence_str,
            issued_by_name=current_user.full_name,
            issued_by_role=current_user.role.replace("_", " ").title(),
            issued_date_str=datetime.utcnow().strftime("%Y-%m-%d"),
        )
        db.add(
            Certificate(
                serial_number=serial,
                student_id=st.id,
                club_id=club_id_val,
                event_id=event_id_val,
                cert_type=req.cert_type,
                title=req.title,
                citation=req.citation,
                verification_evidence=evidence_str,
                issued_by_name=current_user.full_name,
                issued_by_role=current_user.role,
                pdf_filename=pdf_info["filename"],
                pdf_sha256_hash=pdf_info["pdf_sha256_hash"],
                hmac_signature=pdf_info["hmac_signature"],
            )
        )
        issued_count += 1

    db.add(
        AuditLog(
            actor_id=current_user.id,
            action="BATCH_CERTIFICATES_ISSUED",
            entity_type=req.target_type.upper(),
            entity_id=req.target_id,
            details=f"Batch-issued {issued_count} certificates ('{req.title}') by {current_user.full_name}.",
        )
    )
    db.commit()
    return {"issued_count": issued_count, "message": f"Successfully issued {issued_count} verified PDF certificate(s)."}


# ============================================================================
# Serve Uploaded Files & Frontend App
# ============================================================================

@app.post("/api/admin/smtp-test")
def admin_smtp_test(
    recipient: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("ADMIN", "CAMPUS_MGR"):
        raise HTTPException(status_code=403, detail="Only Admin or Campus Manager can perform SMTP testing.")
    from .services.email_engine import send_email_sync, _get_credentials
    target = recipient.strip() if recipient else current_user.email
    user, pwd = _get_credentials()
    success = send_email_sync(
        to_emails=[target],
        subject="[ClubSync] Admin SMTP Diagnostic Test",
        html_content=f"<p>This diagnostic test verifies that the ClubSync email engine is successfully connected via Google SMTP (User: {user}).</p>",
    )
    return {
        "success": success,
        "sender": user,
        "target": target,
        "message": f"SMTP test {'delivered successfully' if success else 'failed to send'} to {target}."
    }


app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/favicon.ico")
def serve_favicon():
    favicon_path = os.path.join(FRONTEND_DIR, "logo-icon.png")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path, media_type="image/png")
    return HTMLResponse("", status_code=204)


@app.get("/logo.png")
def serve_logo_root():
    logo_path = os.path.join(FRONTEND_DIR, "logo.png")
    if os.path.exists(logo_path):
        return FileResponse(logo_path, media_type="image/png")
    return HTMLResponse("", status_code=204)


@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>ClubSync Running</h1>"


@app.get("/verify/{serial_number}", response_class=HTMLResponse)
def serve_public_verify_page(serial_number: str):
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return f"<h1>Verify {serial_number}</h1>"

