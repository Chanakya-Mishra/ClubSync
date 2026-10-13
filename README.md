# MSOT Club Activities Tracker (Problem 3)

A unified, mobile-first platform to run every MSOT club across **HI-Tech**, **Ratnam**, **RGIB**, and **JUJ** campuses—covering **student enrolment, 7-step Saturday Club Day planning, 15s rotating QR check-in, deliverable submissions, rubric evaluation, inter-campus events, and tamper-evident PDF certificates & co-curricular transcripts**.

---

## 🚀 One-Command Quick Start

### Option A: Local One-Command Startup (Zero External Dependencies Needed)
```bash
chmod +x start.sh && ./start.sh
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser (or **[http://localhost:8000/docs](http://localhost:8000/docs)** for the interactive OpenAPI Swagger documentation).

### Option B: Docker Compose One-Command Startup
```bash
docker compose up --build
```

---

## 🗄️ Supabase PostgreSQL & Storage Configuration

The backend natively supports **Supabase PostgreSQL** and **Supabase Storage**:
1. Run the SQL migration [`supabase/schema.sql`](./supabase/schema.sql) in your **Supabase Dashboard $\rightarrow$ SQL Editor** (creates all 17 relational tables, composite unique constraints, indexes, and the `club-tracker-assets` storage bucket).
2. Copy `.env.example` to `.env` and set your Supabase connection variables:
   ```env
   SUPABASE_DB_URL=postgresql://postgres.[PROJECT-REF]:[PASSWORD]@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
   SUPABASE_URL=https://[PROJECT-REF].supabase.co
   SUPABASE_ANON_KEY=your-anon-key
   SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
   ```
3. When `SUPABASE_DB_URL` is left empty, the platform automatically runs on its local Supabase-compatible engine (`data/msot_club_tracker.db` in WAL mode) with all sample data pre-seeded.

---

## ✅ Problem 3 Submission Checklist & Deliverables

| Deliverable | Location in Repo | Status |
| :--- | :--- | :--- |
| **1. One-Command Setup & README** | [`start.sh`](./start.sh), [`docker-compose.yml`](./docker-compose.yml), [`README.md`](./README.md) | ✅ Ready |
| **2. Architecture Diagram & Design Doc ($\le 3$ pages)** | [`docs/ARCHITECTURE_DESIGN.md`](./docs/ARCHITECTURE_DESIGN.md) | ✅ Ready |
| **3. Supabase PostgreSQL Schema** | [`supabase/schema.sql`](./supabase/schema.sql) | ✅ Ready |
| **4. Pre-Loaded Sample Data (4 Campuses, 30+ Clubs, 1 Month of Club Days, 4 Events)** | [`backend/seed.py`](./backend/seed.py) | ✅ Ready |
| **5. Sample PDF Certificates (22+) & Co-Curricular Transcript PDF** | [`data/certificates/MSOT-CERT-2026-0001.pdf`](./data/certificates/MSOT-CERT-2026-0001.pdf)<br>[`data/certificates/MSOT-TRANSCRIPT-2026-0101.pdf`](./data/certificates/MSOT-TRANSCRIPT-2026-0101.pdf) | ✅ Ready |
| **6. Test Report & 100 / 300 / 500 Concurrent Load Test Results** | [`docs/TEST_REPORT.md`](./docs/TEST_REPORT.md), [`data/load_test_results.json`](./data/load_test_results.json) | ✅ Ready |

---

## 🧪 Running the Automated Test Suite & 500-User Load Test

```bash
# 1. Run all 7 automated verification tests (6 mandatory Section 6 areas + Middle 3 Stretch Goals)
PYTHONPATH=. ./.venv/bin/pytest tests/test_problem3_requirements.py -v

# 2. Run the 100, 300, and 500 concurrent Saturday morning check-in load test
PYTHONPATH=. ./.venv/bin/python3 tests/load_test_checkin.py
```

### Load Test Summary (`p95 < 1 second` SLA)
* **100 Concurrent Check-Ins:** `p95 = 93.20 ms` | Error Rate: `0.0%`
* **300 Concurrent Check-Ins:** `p95 = 214.65 ms` | Error Rate: `0.0%`
* **500 Concurrent Check-Ins:** `p95 = 354.21 ms` | Error Rate: `0.0%`

---

## 👥 RBAC Demo Personas (Switchable in 1 Click in the Top Bar)

* **Student Coordinator:** `Rohan Gupta` (`rohan.coord@msot.org`) — Run Saturday Club Days, project live 15s rotating QR code, mark presenters, log manual overrides with mandatory reason, score rubric submissions, request club budgets.
* **Student:** `Aarav Patel` (`aarav.student@msot.org`, Roll No `MSOT-25-CS-101`) — Enrol in Primary/Secondary clubs, scan QR / enter OTP, upload deliverables, form event teams, toggle photo consent, download verified PDF Co-Curricular Transcript.
* **Faculty Advisor:** `Dr. Vikram Rao` (`vikram.rao@msot.org`) — Approve 7-day Club Day activity plans, grade submissions on the 3-part rubric, endorse club budgets, issue achievement certificates.
* **Campus Manager:** `Priya Nair` (`priya.nair@msot.org`, HI-Tech Campus) — View campus dashboards & monthly club reports, approve auto-generated Duty Leave requests, approve club budgets.
* **Admin / Program Manager:** `Arjun Mehta` (`arjun.mehta@msot.org`) — Create clubs & inter-campus events across all 4 campuses, monitor inactive clubs & zero-participation students, export CSV academic review reports.
