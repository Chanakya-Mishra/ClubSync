# ClubSync — Multi-Campus Club & Co-Curricular Synchronization Operating System

<div align="center">
  <img src="frontend/logo.png" alt="ClubSync Logo" width="460" />
  <p><strong>Synchronizing Every College Club, Saturday Session, Event, and Student Record in Real Time.</strong></p>
  <p><em>Production-grade multi-campus platform serving <strong>HI-Tech</strong>, <strong>Rathinam</strong>, and <strong>JUJ</strong> campuses.</em></p>
</div>

---

## 🌟 Overview

**ClubSync** is an all-in-one, mobile-responsive campus operating system engineered to govern club lifecycles, eliminate proxy attendance, streamline activity deliverables, and issue cryptographically verifiable student transcripts and achievement certificates.

Built with a high-performance **FastAPI** backend, **Supabase PostgreSQL** cloud persistence, and a modern **Vanilla JS + Tailwind CSS** frontend powered by a local **Stale-While-Revalidate (SWR)** caching engine for sub-50ms user interactions.

---

## ⚡ Main Usable Features (In Brief)

### 1. 🛡️ Anti-Proxy Rotating QR Check-In Engine
* **HMAC-SHA256 Time-Bucketed Rotation:** Check-in QR codes rotate automatically every 15 seconds with live countdown bars, preventing screenshot forwarding or remote sharing.
* **6-Digit Rolling Code:** Secondary offline/fallback verification method synchronized with the current time bucket.
* **Campus Geofencing:** Mathematical Haversine distance validation restricts check-ins within the physical campus radius.
* **Projector Fullscreen Mode:** High-contrast presentation view for club halls and auditoriums.
* **30-Minute Automatic Session Lifecycle:** Demo sessions and open check-in windows automatically expire and clean up 30 minutes after generation.

### 2. 📊 Real-Time Attendance Intelligence
* **Personal Student Dashboard:** Instant attendance KPI card showing personal attendance percentage (e.g. `100%`), sessions attended vs. conducted, present vs. late check-in breakdown, and academic standing badge (*Excellent*, *Good Standing*, or *Attendance Warning*).
* **President-Exclusive Attendance Portal (`/api/president/club-attendance`):**
  * Gated strictly to Club Presidents and leadership.
  * Complete member roster with session counts, missed sessions, and individual attendance percentages.
  * Real-time search by name, email, or roll number with tier filters (*Primary*, *Secondary*, *Coordinator*).
  * Recent session turnout history (present vs. expected headcount and turnout percentage).
  * **1-Click CSV Export:** Download full club attendance sheets formatted for academic records.

### 3. 🏛️ Multi-Campus Club Registry & Enrolment
* **Enrolment Rule Engine:** Enforces the institutional rule of maximum **1 Primary Club** and **1 Secondary Club** per student.
* **Role-Based Access Control (RBAC):** Distinct permission hierarchies for `STUDENT`, `PRESIDENT`, `COORDINATOR`, `ADVISOR`, `CAMPUS_MGR`, and `ADMIN`.
* **Campus Manager Permissioning:** Mandatory authorization workflow before newly registered accounts access the campus portal.

### 4. 📅 Weekly Saturday Club Day 7-Step Lifecycle
* **Pre-Session Planning:** 7-day advance activity proposal with topic, format (PPT, Workshop, Coding Sprint, Debate, Prototype Demo), venue, and deliverable descriptions.
* **Faculty Advisor Review:** In-app approval and constructive feedback loop before sessions are announced.
* **Deliverable Submissions:** Student submission portal for GitHub links, slide decks, prototypes, and drive files.
* **30-Point Standardized Rubric:** Built-in grading across 3 dimensions:
  1. *Relevance & Effort* (10 pts)
  2. *Technical / Creative Quality* (10 pts)
  3. *Presentation & Delivery* (10 pts)

### 5. 🏆 Inter-Campus Events & Team Registration
* **Multi-Campus Hackathons & Competitions:** Create and discover campus-wide and inter-campus events.
* **Dynamic Team Formations:** Flexible solo or multi-member team formation (2–5 members) with team codes.
* **Live Event Check-In:** Dedicated event attendance verification.
* **Podium & Results:** Publish 1st, 2nd, 3rd place winners and top presenters.

### 6. 📜 Tamper-Evident Transcripts & Certificates
* **Cryptographic SHA-256 Seals:** Every generated transcript and certificate carries a verifiable cryptographic digital hash and unique serial number.
* **Instant QR Verification URL:** Public `/verify/{serial_number}` endpoint verifies document authenticity in real time without authentication required.
* **On-Demand PDF Generation:** Vector-quality PDF engine with automated metadata, signatures, and campus branding.

### 7. 💼 Operational & Governance Modules
* **Budget Requests:** Submit, track, and approve operational club funding with itemized allocations and status pipelines (*PENDING*, *APPROVED*, *REJECTED*).
* **Automated Duty Leave Letters:** Generates formal academic absence excuse letters with attendance proof for students attending approved weekend sessions and events.
* **Media Gallery with Privacy Consent:** Club photo showcase with explicit per-student photo consent toggles.
* **Official Club News Broadcast:** Presidents and Campus Managers can broadcast announcements and pinned updates directly to enrolled members.

### 8. ⚡ Ultra-Low Latency & High-Speed Architecture
* **0ms SWR Frontend Engine:** Instantaneous view switching and data hydration from `localStorage` SWR cache with non-blocking background revalidation.
* **GZip Payload Compression:** Automated gzip compression on all API responses >500B, cutting JSON payload size by 70–80%.
* **Smart HTTP Cache-Control:** Static assets (logos, icons, fonts) are cached for 24 hours (`max-age=86400, stale-while-revalidate`), loading in 0ms on return visits.
* **Optimized Batch Database Queries:** Consolidated $O(1)$ batch queries across the dashboard and reports, eliminating N+1 database round-trips to Supabase.

---

## 🚀 One-Command Quick Start

### Option A: Local Run (Zero External Dependencies)
```bash
chmod +x start.sh && ./start.sh
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.
Interactive API documentation: **[http://localhost:8000/docs](http://localhost:8000/docs)**.

### Option B: Docker Compose
```bash
docker compose up --build
```

---

## 🗄️ Supabase Cloud Database Configuration

ClubSync natively connects to **Supabase PostgreSQL** and **Supabase Storage**:
1. Run the database migration script [`supabase/schema.sql`](./supabase/schema.sql) in your **Supabase Dashboard $\rightarrow$ SQL Editor**.
2. Configure your `.env` file:
   ```env
   SUPABASE_DB_URL=postgresql://postgres.[PROJECT-REF]:[PASSWORD]@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
   SUPABASE_URL=https://[PROJECT-REF].supabase.co
   SUPABASE_ANON_KEY=your-anon-key
   SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
   ```
3. If `SUPABASE_DB_URL` is omitted, ClubSync automatically falls back to its high-speed local engine in WAL mode (`data/msot_club_tracker.db`).

---

## 🧪 Automated Test Suite & Load Testing

```bash
# 1. Run full automated verification suite
PYTHONPATH=. ./.venv/bin/pytest tests/test_problem3_requirements.py -v

# 2. Run the concurrent Saturday morning check-in load test
PYTHONPATH=. ./.venv/bin/python3 tests/load_test_checkin.py
```

### High-Concurrency Performance Summary
* **100 Concurrent Check-Ins:** `p95 = 93.20 ms` | Error Rate: `0.0%`
* **300 Concurrent Check-Ins:** `p95 = 214.65 ms` | Error Rate: `0.0%`
* **500 Concurrent Check-Ins:** `p95 = 354.21 ms` | Error Rate: `0.0%`

---

## 📁 Repository Structure

```text
├── backend/
│   ├── main.py              # FastAPI application, routing, auth & business logic
│   ├── database.py          # SQLAlchemy engine, connection pooling & Supabase storage
│   ├── models.py            # 17 Relational database models with indices
│   ├── seed.py              # System config & campus seed definitions
│   └── services/
│       ├── qr_engine.py     # Rotating HMAC-SHA256 anti-proxy QR & geofencing
│       ├── pdf_engine.py    # SHA-256 sealed certificate & transcript generator
│       └── email_engine.py  # SMTP notification & transactional email engine
├── frontend/
│   ├── index.html           # Single-page application UI with Tailwind CSS
│   ├── app.js               # SWR client-side caching & reactive UI controller
│   ├── logo.png             # Official ClubSync high-res brand logo
│   └── logo-icon.png        # Translucent favicon & navigation badge
├── docs/
│   ├── ARCHITECTURE_DESIGN.md # System architecture & design specifications
│   └── TEST_REPORT.md         # Load test execution records & benchmarks
├── supabase/
│   └── schema.sql           # PostgreSQL schema DDL migration
├── Dockerfile               # Container build configuration
├── docker-compose.yml       # Multi-container orchestration
├── requirements.txt         # Production Python dependencies
└── vercel.json              # Serverless Vercel deployment routing
```
