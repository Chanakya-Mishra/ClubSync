import uuid
from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    Text,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship
from .database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class SystemConfig(Base):
    __tablename__ = "system_configs"

    key = Column(String(100), primary_key=True)
    value = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Campus(Base):
    __tablename__ = "campuses"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    code = Column(String(30), unique=True, nullable=False, index=True)  # HI-Tech, Rathinam, JUJ
    name = Column(String(120), nullable=False)
    city = Column(String(80), nullable=False)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    geofence_radius_m = Column(Integer, default=500)
    created_at = Column(DateTime, default=datetime.utcnow)

    users = relationship("User", back_populates="campus")
    clubs = relationship("Club", back_populates="campus")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("idx_users_campus_role", "campus_id", "role"),
        Index("idx_users_status_role", "account_status", "role"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    email = Column(String(150), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False, default="")
    full_name = Column(String(120), nullable=False)
    roll_number = Column(String(50), unique=True, nullable=True, index=True)
    role = Column(
        String(30), nullable=False, index=True
    )  # ADMIN | CAMPUS_MGR | ADVISOR | COORDINATOR | STUDENT
    account_status = Column(
        String(30), default="APPROVED", nullable=False, index=True
    )  # PENDING_APPROVAL | APPROVED | REJECTED
    campus_id = Column(String(36), ForeignKey("campuses.id"), nullable=True, index=True)
    batch = Column(String(50), nullable=True)  # e.g., 2025-2029 B.Tech CS
    track = Column(String(50), default="Mirai Track")  # Mirai Track | University Track
    phone = Column(String(30), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    campus = relationship("Campus", back_populates="users")
    memberships = relationship(
        "ClubMembership",
        foreign_keys="ClubMembership.student_id",
        back_populates="student",
        cascade="all, delete-orphan",
    )


class Club(Base):
    __tablename__ = "clubs"
    __table_args__ = (
        Index("idx_clubs_campus_status", "campus_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    campus_id = Column(String(36), ForeignKey("campuses.id"), nullable=False, index=True)
    code = Column(String(40), unique=True, nullable=False, index=True)
    name = Column(String(140), nullable=False)
    category = Column(String(60), nullable=False)
    description = Column(Text, nullable=False)
    advisor_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    capacity = Column(Integer, default=60)
    meeting_rules = Column(String(255), default="Every Saturday, 09:30 AM - 11:30 AM (Club Day)")
    status = Column(String(30), default="ACTIVE", index=True)  # PENDING | ACTIVE | INACTIVE
    created_at = Column(DateTime, default=datetime.utcnow)

    campus = relationship("Campus", back_populates="clubs")
    advisor = relationship("User", foreign_keys=[advisor_id])
    memberships = relationship("ClubMembership", back_populates="club", cascade="all, delete-orphan")
    sessions = relationship("ClubDaySession", back_populates="club", cascade="all, delete-orphan")


class ClubMembership(Base):
    __tablename__ = "club_memberships"
    __table_args__ = (
        UniqueConstraint("club_id", "student_id", name="uq_club_student_membership"),
        Index("idx_club_memberships_club_status", "club_id", "status"),
        Index("idx_club_memberships_student_status", "student_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    club_id = Column(String(36), ForeignKey("clubs.id"), nullable=False, index=True)
    student_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    tier = Column(String(30), default="PRIMARY", index=True)  # PRIMARY | SECONDARY | COORDINATOR
    status = Column(String(30), default="PENDING", index=True)  # PENDING | APPROVED | REJECTED
    approved_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    joined_at = Column(DateTime, default=datetime.utcnow)

    club = relationship("Club", back_populates="memberships")
    student = relationship("User", foreign_keys=[student_id], back_populates="memberships")


class ClubDaySession(Base):
    __tablename__ = "club_day_sessions"
    __table_args__ = (
        Index("idx_sessions_checkin_status", "checkin_status"),
        Index("idx_sessions_club_date", "club_id", "scheduled_date"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    club_id = Column(String(36), ForeignKey("clubs.id"), nullable=False, index=True)
    week_number = Column(Integer, default=1)
    scheduled_date = Column(String(20), nullable=False, index=True)  # YYYY-MM-DD (Saturday)
    topic = Column(String(200), nullable=False)
    format = Column(String(50), default="PPT")  # PPT | ASSIGNMENT | CODING_SPRINT | DEBATE | PROTOTYPE_DEMO
    venue = Column(String(120), default="Auditorium A")
    deliverable_desc = Column(Text, nullable=False)
    submission_deadline = Column(String(30), nullable=False)  # ISO timestamp (48h after session)
    plan_status = Column(
        String(30), default="PENDING_APPROVAL", index=True
    )  # DRAFT | PENDING_APPROVAL | APPROVED | CHANGES_REQUESTED
    advisor_feedback = Column(Text, nullable=True)
    planned_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    announced_at = Column(DateTime, nullable=True)

    # Check-in window & rotating QR seed
    checkin_secret = Column(String(64), nullable=False)
    checkin_status = Column(String(30), default="CLOSED", index=True)  # CLOSED | OPEN | COMPLETED
    checkin_opens_at = Column(DateTime, nullable=True)
    checkin_late_after = Column(DateTime, nullable=True)
    checkin_closes_at = Column(DateTime, nullable=True)

    # Run stage notes & highlights
    on_the_spot_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    club = relationship("Club", back_populates="sessions")
    attendances = relationship("Attendance", back_populates="session", cascade="all, delete-orphan")
    submissions = relationship("Submission", back_populates="session", cascade="all, delete-orphan")


class Attendance(Base):
    __tablename__ = "attendances"
    __table_args__ = (
        UniqueConstraint("session_id", "student_id", name="uq_session_student_attendance"),
        Index("idx_attendance_session_status", "session_id", "status"),
        Index("idx_attendances_student_status", "student_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("club_day_sessions.id"), nullable=False, index=True)
    student_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(30), default="PRESENT", index=True)  # PRESENT | LATE | ABSENT | EXCUSED
    method = Column(String(30), default="QR_SCAN")  # QR_SCAN | OTP_CODE | MANUAL_OVERRIDE
    is_presenter = Column(Boolean, default=False, index=True)
    activity_result = Column(String(120), nullable=True)  # e.g., "Best Presenter", "Top 3 Pitch"
    override_reason = Column(Text, nullable=True)
    overridden_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    checkin_lat = Column(Float, nullable=True)
    checkin_lng = Column(Float, nullable=True)
    distance_from_campus_m = Column(Float, nullable=True)
    checked_in_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("ClubDaySession", back_populates="attendances")
    student = relationship("User", foreign_keys=[student_id])


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("session_id", "student_id", name="uq_session_student_submission"),
        Index("idx_submissions_student_session", "student_id", "session_id"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("club_day_sessions.id"), nullable=False, index=True)
    student_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    deliverable_type = Column(String(40), default="PPT")  # PPT | ASSIGNMENT | GITHUB_LINK | PHOTO
    file_url = Column(String(350), nullable=True)
    external_link = Column(String(350), nullable=True)
    notes = Column(Text, nullable=True)
    is_late = Column(Boolean, default=False)
    submitted_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("ClubDaySession", back_populates="submissions")
    student = relationship("User", foreign_keys=[student_id])
    evaluation = relationship("Evaluation", back_populates="submission", uselist=False, cascade="all, delete-orphan")


class Evaluation(Base):
    __tablename__ = "evaluations"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    submission_id = Column(String(36), ForeignKey("submissions.id"), unique=True, nullable=False, index=True)
    evaluator_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    evaluator_role = Column(String(30), nullable=False)  # COORDINATOR | ADVISOR
    content_score = Column(Float, nullable=False)  # 0 to 10
    presentation_score = Column(Float, nullable=False)  # 0 to 10
    participation_score = Column(Float, nullable=False)  # 0 to 10
    total_score = Column(Float, nullable=False)  # 0 to 30
    comments = Column(Text, nullable=True)
    evaluated_at = Column(DateTime, default=datetime.utcnow)

    submission = relationship("Submission", back_populates="evaluation")
    evaluator = relationship("User", foreign_keys=[evaluator_id])


class Event(Base):
    __tablename__ = "events"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    campus_id = Column(String(36), ForeignKey("campuses.id"), nullable=True, index=True)  # NULL = Inter-Campus
    code = Column(String(50), unique=True, nullable=False, index=True)
    title = Column(String(160), nullable=False)  # Gambade, Hackathon, International Conference, Cross Road
    category = Column(String(50), nullable=False)  # GAMBADE | HACKATHON | CONFERENCE | CROSS_ROAD
    scope = Column(String(40), default="INTER_CAMPUS")  # CAMPUS | INTER_CAMPUS | INTER_COLLEGE
    description = Column(Text, nullable=False)
    venue = Column(String(150), nullable=False)
    start_date = Column(String(30), nullable=False, index=True)
    end_date = Column(String(30), nullable=False)
    max_team_size = Column(Integer, default=4)
    capacity = Column(Integer, default=500)
    duty_leave_eligible = Column(Boolean, default=True)
    checkin_secret = Column(String(64), nullable=False)
    status = Column(String(30), default="UPCOMING", index=True)  # UPCOMING | ONGOING | COMPLETED
    created_at = Column(DateTime, default=datetime.utcnow)

    teams = relationship("EventTeam", back_populates="event", cascade="all, delete-orphan")
    registrations = relationship("EventRegistration", back_populates="event", cascade="all, delete-orphan")


class EventTeam(Base):
    __tablename__ = "event_teams"
    __table_args__ = (
        UniqueConstraint("event_id", "team_name", name="uq_event_team_name"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    event_id = Column(String(36), ForeignKey("events.id"), nullable=False, index=True)
    team_name = Column(String(120), nullable=False)
    invite_code = Column(String(20), unique=True, nullable=False, index=True)
    leader_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    project_title = Column(String(200), nullable=True)
    result_position = Column(String(50), nullable=True)  # WINNER | RUNNER_UP | FINALIST | PARTICIPANT
    score = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    event = relationship("Event", back_populates="teams")
    members = relationship("EventRegistration", back_populates="team")


class EventRegistration(Base):
    __tablename__ = "event_registrations"
    __table_args__ = (
        UniqueConstraint("event_id", "student_id", name="uq_event_student_registration"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    event_id = Column(String(36), ForeignKey("events.id"), nullable=False, index=True)
    team_id = Column(String(36), ForeignKey("event_teams.id"), nullable=True, index=True)
    student_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    checked_in = Column(Boolean, default=False, index=True)
    checked_in_at = Column(DateTime, nullable=True)
    result_badge = Column(String(80), nullable=True)
    registered_at = Column(DateTime, default=datetime.utcnow)

    event = relationship("Event", back_populates="registrations")
    team = relationship("EventTeam", back_populates="members")
    student = relationship("User", foreign_keys=[student_id])


class Certificate(Base):
    __tablename__ = "certificates"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    serial_number = Column(String(60), unique=True, nullable=False, index=True)
    student_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    club_id = Column(String(36), ForeignKey("clubs.id"), nullable=True, index=True)
    event_id = Column(String(36), ForeignKey("events.id"), nullable=True, index=True)
    session_id = Column(String(36), ForeignKey("club_day_sessions.id"), nullable=True)
    cert_type = Column(
        String(40), nullable=False, index=True
    )  # PARTICIPATION | ACHIEVEMENT | EVENT_EXCELLENCE | TRANSCRIPT
    title = Column(String(200), nullable=False)
    citation = Column(Text, nullable=False)
    verification_evidence = Column(String(255), nullable=False)
    issued_by_name = Column(String(120), nullable=False)
    issued_by_role = Column(String(60), default="Faculty Advisor")
    pdf_filename = Column(String(200), nullable=False)
    pdf_sha256_hash = Column(String(64), nullable=False, index=True)
    hmac_signature = Column(String(64), nullable=False)
    issued_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("User", foreign_keys=[student_id])
    club = relationship("Club", foreign_keys=[club_id])
    event = relationship("Event", foreign_keys=[event_id])


# --- Selected Stretch Goal Models (Middle Three Only) ---

# Stretch Goal #2 (Middle 1): Club budget and expense requests with approval workflow
class BudgetRequest(Base):
    __tablename__ = "budget_requests"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    club_id = Column(String(36), ForeignKey("clubs.id"), nullable=False, index=True)
    requested_by_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(160), nullable=False)
    category = Column(String(60), default="Equipment & Kits")  # Equipment, Refreshments, Prizes, Guest Speaker
    amount_inr = Column(Float, nullable=False)
    description = Column(Text, nullable=False)
    status = Column(
        String(40), default="PENDING_ADVISOR", index=True
    )  # PENDING_ADVISOR | PENDING_CAMPUS_MGR | APPROVED | REJECTED
    approval_notes = Column(Text, nullable=True)
    approved_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# Stretch Goal #3 (Middle 2): Duty Leave request generated automatically for approved inter-college events, ready for Campus Manager approval
class DutyLeaveRequest(Base):
    __tablename__ = "duty_leave_requests"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    event_id = Column(String(36), ForeignKey("events.id"), nullable=False, index=True)
    student_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    campus_id = Column(String(36), ForeignKey("campuses.id"), nullable=False, index=True)
    leave_dates = Column(String(100), nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(40), default="PENDING_CM_APPROVAL", index=True)  # PENDING_CM_APPROVAL | APPROVED | REJECTED
    approved_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# Stretch Goal #4 (Middle 3): Photo / media gallery per event with consent controls
class MediaGalleryItem(Base):
    __tablename__ = "media_gallery_items"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    club_id = Column(String(36), ForeignKey("clubs.id"), nullable=True, index=True)
    event_id = Column(String(36), ForeignKey("events.id"), nullable=True, index=True)
    uploaded_by_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    caption = Column(String(250), nullable=False)
    media_url = Column(String(350), nullable=False)
    tagged_student_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    student_consent = Column(Boolean, default=True, index=True)  # Consent control: student can opt-in/revoke visibility
    created_at = Column(DateTime, default=datetime.utcnow)


# Club News / Announcements posted by Club Presidents and Campus Managers
class ClubNews(Base):
    __tablename__ = "club_news"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    club_id = Column(String(36), ForeignKey("clubs.id"), nullable=False, index=True)
    author_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    pinned = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    club = relationship("Club", foreign_keys=[club_id])
    author = relationship("User", foreign_keys=[author_id])


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(80), nullable=False, index=True)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(60), nullable=True)
    details = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class PasswordResetOTP(Base):
    __tablename__ = "password_reset_otps"
    __table_args__ = (
        Index("idx_pwd_reset_email_otp", "email", "otp"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    email = Column(String(150), nullable=False, index=True)
    otp = Column(String(10), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    used = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
