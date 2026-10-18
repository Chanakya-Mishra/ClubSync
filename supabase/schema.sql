-- ============================================================================
-- MSOT Club Activities Tracker (Problem 3) — Supabase PostgreSQL Schema
-- Run this script in your Supabase Dashboard -> SQL Editor
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. System Configs
CREATE TABLE IF NOT EXISTS public.system_configs (
    key VARCHAR(100) PRIMARY KEY,
    value VARCHAR(500) NOT NULL,
    description TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Campuses (HI-Tech, Rathinam, JUJ)
CREATE TABLE IF NOT EXISTS public.campuses (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    code VARCHAR(30) UNIQUE NOT NULL,
    name VARCHAR(120) NOT NULL,
    city VARCHAR(80) NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lng DOUBLE PRECISION NOT NULL,
    geofence_radius_m INTEGER DEFAULT 500,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Users (ADMIN, CAMPUS_MGR, ADVISOR, COORDINATOR, STUDENT)
CREATE TABLE IF NOT EXISTS public.users (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    email VARCHAR(150) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL DEFAULT '',
    full_name VARCHAR(120) NOT NULL,
    roll_number VARCHAR(50) UNIQUE,
    role VARCHAR(30) NOT NULL,
    account_status VARCHAR(30) NOT NULL DEFAULT 'APPROVED',
    campus_id VARCHAR(36) REFERENCES public.campuses(id) ON DELETE SET NULL,
    batch VARCHAR(50),
    track VARCHAR(50) DEFAULT 'Mirai Track',
    phone VARCHAR(30),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Clubs
CREATE TABLE IF NOT EXISTS public.clubs (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    campus_id VARCHAR(36) NOT NULL REFERENCES public.campuses(id) ON DELETE CASCADE,
    code VARCHAR(40) UNIQUE NOT NULL,
    name VARCHAR(140) NOT NULL,
    category VARCHAR(60) NOT NULL,
    description TEXT NOT NULL,
    advisor_id VARCHAR(36) REFERENCES public.users(id) ON DELETE SET NULL,
    capacity INTEGER DEFAULT 60,
    meeting_rules VARCHAR(255) DEFAULT 'Every Saturday, 09:30 AM - 11:30 AM (Club Day)',
    status VARCHAR(30) DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. Club Memberships (Primary / Secondary / Coordinator)
CREATE TABLE IF NOT EXISTS public.club_memberships (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    club_id VARCHAR(36) NOT NULL REFERENCES public.clubs(id) ON DELETE CASCADE,
    student_id VARCHAR(36) NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    tier VARCHAR(30) DEFAULT 'PRIMARY',
    status VARCHAR(30) DEFAULT 'PENDING',
    approved_by_id VARCHAR(36) REFERENCES public.users(id) ON DELETE SET NULL,
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_club_student_membership UNIQUE (club_id, student_id)
);

-- 6. Club Day Sessions (Saturday Flow: Plan -> Approve -> Announce -> Check-in -> Run -> Submit -> Evaluate)
CREATE TABLE IF NOT EXISTS public.club_day_sessions (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    club_id VARCHAR(36) NOT NULL REFERENCES public.clubs(id) ON DELETE CASCADE,
    week_number INTEGER DEFAULT 1,
    scheduled_date VARCHAR(20) NOT NULL,
    topic VARCHAR(200) NOT NULL,
    format VARCHAR(50) DEFAULT 'PPT',
    venue VARCHAR(120) DEFAULT 'Auditorium A',
    deliverable_desc TEXT NOT NULL,
    submission_deadline VARCHAR(30) NOT NULL,
    plan_status VARCHAR(30) DEFAULT 'PENDING_APPROVAL',
    advisor_feedback TEXT,
    planned_by_id VARCHAR(36) REFERENCES public.users(id) ON DELETE SET NULL,
    approved_by_id VARCHAR(36) REFERENCES public.users(id) ON DELETE SET NULL,
    announced_at TIMESTAMPTZ,
    checkin_secret VARCHAR(64) NOT NULL,
    checkin_status VARCHAR(30) DEFAULT 'CLOSED',
    checkin_opens_at TIMESTAMPTZ,
    checkin_late_after TIMESTAMPTZ,
    checkin_closes_at TIMESTAMPTZ,
    on_the_spot_notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 7. Attendances (QR Scan / OTP / Manual Override with Reason)
CREATE TABLE IF NOT EXISTS public.attendances (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    session_id VARCHAR(36) NOT NULL REFERENCES public.club_day_sessions(id) ON DELETE CASCADE,
    student_id VARCHAR(36) NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    status VARCHAR(30) DEFAULT 'PRESENT',
    method VARCHAR(30) DEFAULT 'QR_SCAN',
    is_presenter BOOLEAN DEFAULT FALSE,
    activity_result VARCHAR(120),
    override_reason TEXT,
    overridden_by_id VARCHAR(36) REFERENCES public.users(id) ON DELETE SET NULL,
    checkin_lat DOUBLE PRECISION,
    checkin_lng DOUBLE PRECISION,
    distance_from_campus_m DOUBLE PRECISION,
    checked_in_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_session_student_attendance UNIQUE (session_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_attendance_session_status ON public.attendances (session_id, status);

-- 8. Submissions (PPTs, Assignments, Links, Photos)
CREATE TABLE IF NOT EXISTS public.submissions (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    session_id VARCHAR(36) NOT NULL REFERENCES public.club_day_sessions(id) ON DELETE CASCADE,
    student_id VARCHAR(36) NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    deliverable_type VARCHAR(40) DEFAULT 'PPT',
    file_url VARCHAR(350),
    external_link VARCHAR(350),
    notes TEXT,
    is_late BOOLEAN DEFAULT FALSE,
    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_session_student_submission UNIQUE (session_id, student_id)
);

-- 9. Rubric Evaluations (Content 0-10, Presentation 0-10, Participation 0-10)
CREATE TABLE IF NOT EXISTS public.evaluations (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    submission_id VARCHAR(36) UNIQUE NOT NULL REFERENCES public.submissions(id) ON DELETE CASCADE,
    evaluator_id VARCHAR(36) NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    evaluator_role VARCHAR(30) NOT NULL,
    content_score DOUBLE PRECISION NOT NULL,
    presentation_score DOUBLE PRECISION NOT NULL,
    participation_score DOUBLE PRECISION NOT NULL,
    total_score DOUBLE PRECISION NOT NULL,
    comments TEXT,
    evaluated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 10. Events (Gambade, Hackathon, International Conference, Cross Road)
CREATE TABLE IF NOT EXISTS public.events (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    campus_id VARCHAR(36) REFERENCES public.campuses(id) ON DELETE SET NULL,
    code VARCHAR(50) UNIQUE NOT NULL,
    title VARCHAR(160) NOT NULL,
    category VARCHAR(50) NOT NULL,
    scope VARCHAR(40) DEFAULT 'INTER_CAMPUS',
    description TEXT NOT NULL,
    venue VARCHAR(150) NOT NULL,
    start_date VARCHAR(30) NOT NULL,
    end_date VARCHAR(30) NOT NULL,
    max_team_size INTEGER DEFAULT 4,
    capacity INTEGER DEFAULT 500,
    duty_leave_eligible BOOLEAN DEFAULT TRUE,
    checkin_secret VARCHAR(64) NOT NULL,
    status VARCHAR(30) DEFAULT 'UPCOMING',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 11. Event Teams
CREATE TABLE IF NOT EXISTS public.event_teams (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    event_id VARCHAR(36) NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    team_name VARCHAR(120) NOT NULL,
    invite_code VARCHAR(20) UNIQUE NOT NULL,
    leader_id VARCHAR(36) NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    project_title VARCHAR(200),
    result_position VARCHAR(50),
    score DOUBLE PRECISION,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_event_team_name UNIQUE (event_id, team_name)
);

-- 12. Event Registrations
CREATE TABLE IF NOT EXISTS public.event_registrations (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    event_id VARCHAR(36) NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    team_id VARCHAR(36) REFERENCES public.event_teams(id) ON DELETE SET NULL,
    student_id VARCHAR(36) NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    checked_in BOOLEAN DEFAULT FALSE,
    checked_in_at TIMESTAMPTZ,
    result_badge VARCHAR(80),
    registered_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_event_student_registration UNIQUE (event_id, student_id)
);

-- 13. Certificates & Verified Transcripts (with SHA-256 + HMAC Tamper Detection)
CREATE TABLE IF NOT EXISTS public.certificates (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    serial_number VARCHAR(60) UNIQUE NOT NULL,
    student_id VARCHAR(36) NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    club_id VARCHAR(36) REFERENCES public.clubs(id) ON DELETE SET NULL,
    event_id VARCHAR(36) REFERENCES public.events(id) ON DELETE SET NULL,
    session_id VARCHAR(36) REFERENCES public.club_day_sessions(id) ON DELETE SET NULL,
    cert_type VARCHAR(40) NOT NULL,
    title VARCHAR(200) NOT NULL,
    citation TEXT NOT NULL,
    verification_evidence VARCHAR(255) NOT NULL,
    issued_by_name VARCHAR(120) NOT NULL,
    issued_by_role VARCHAR(60) DEFAULT 'Faculty Advisor',
    pdf_filename VARCHAR(200) NOT NULL,
    pdf_sha256_hash VARCHAR(64) NOT NULL,
    hmac_signature VARCHAR(64) NOT NULL,
    issued_at TIMESTAMPTZ DEFAULT NOW()
);

-- 14. Stretch Goal 1 (Middle): Club Budget & Expense Requests
CREATE TABLE IF NOT EXISTS public.budget_requests (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    club_id VARCHAR(36) NOT NULL REFERENCES public.clubs(id) ON DELETE CASCADE,
    requested_by_id VARCHAR(36) NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    title VARCHAR(160) NOT NULL,
    category VARCHAR(60) DEFAULT 'Equipment & Kits',
    amount_inr DOUBLE PRECISION NOT NULL,
    description TEXT NOT NULL,
    status VARCHAR(40) DEFAULT 'PENDING_ADVISOR',
    approval_notes TEXT,
    approved_by_id VARCHAR(36) REFERENCES public.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 15. Stretch Goal 2 (Middle): Automated Duty Leave Requests for Inter-College Events
CREATE TABLE IF NOT EXISTS public.duty_leave_requests (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    event_id VARCHAR(36) NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    student_id VARCHAR(36) NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    campus_id VARCHAR(36) NOT NULL REFERENCES public.campuses(id) ON DELETE CASCADE,
    leave_dates VARCHAR(100) NOT NULL,
    reason TEXT NOT NULL,
    status VARCHAR(40) DEFAULT 'PENDING_CM_APPROVAL',
    approved_by_id VARCHAR(36) REFERENCES public.users(id) ON DELETE SET NULL,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 16. Stretch Goal 3 (Middle): Event Photo / Media Gallery with Consent Controls
CREATE TABLE IF NOT EXISTS public.media_gallery_items (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    club_id VARCHAR(36) REFERENCES public.clubs(id) ON DELETE SET NULL,
    event_id VARCHAR(36) REFERENCES public.events(id) ON DELETE SET NULL,
    uploaded_by_id VARCHAR(36) NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    caption VARCHAR(250) NOT NULL,
    media_url VARCHAR(350) NOT NULL,
    tagged_student_id VARCHAR(36) REFERENCES public.users(id) ON DELETE SET NULL,
    student_consent BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 17. Club News & Announcements
CREATE TABLE IF NOT EXISTS public.club_news (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    club_id VARCHAR(36) NOT NULL REFERENCES public.clubs(id) ON DELETE CASCADE,
    author_id VARCHAR(36) NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    pinned BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 18. Security & Integrity Audit Logs
CREATE TABLE IF NOT EXISTS public.audit_logs (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    actor_id VARCHAR(36) REFERENCES public.users(id) ON DELETE SET NULL,
    action VARCHAR(80) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id VARCHAR(60),
    details TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Optional: Supabase Storage Bucket creation for deliverables, certificates, and gallery
INSERT INTO storage.buckets (id, name, public)
VALUES ('club-tracker-assets', 'club-tracker-assets', true)
ON CONFLICT (id) DO NOTHING;
