# MSOT Club Activities Tracker — Official Test Report & Load Test Results

**Test Suite Location:** [`tests/test_problem3_requirements.py`](../tests/test_problem3_requirements.py)  
**Load Test Script:** [`tests/load_test_checkin.py`](../tests/load_test_checkin.py)  
**Raw Load Test Artifact:** [`data/load_test_results.json`](../data/load_test_results.json)  

---

## 1. Automated Verification Summary (Section 6 Mandatory Test Areas)

Run command:
```bash
PYTHONPATH=. ./.venv/bin/pytest tests/test_problem3_requirements.py -v
```

| # | Test Area (Section 6 Brief) | Minimum Evidence Required | Automated Test Case | Result & Verified Evidence |
| :--- | :--- | :--- | :--- | :--- |
| **1** | **End-to-end Club Day** | Full flow for 3 clubs: `plan -> approve -> check-in -> submit -> evaluate -> report` | `test_1_end_to_end_club_day_flow_for_3_clubs` | **PASSED** — Executed complete 7-step lifecycle across 3 clubs (`Mirai AI Club @ HI-Tech`, `AutonomeX Robotics @ Rathinam`, `PitchCraft Debate @ JUJ`). Verified advisor approval, QR check-in, presenter tagging, deliverable upload, rubric grading (`28.5/30`), and monthly report reflection. |
| **2** | **Check-in Integrity** | Screenshot sharing, late check-in, and check-in from outside campus (geo-check): what happens in each case | `test_2_checkin_integrity_screenshot_late_and_geofence` | **PASSED** — <br>1. **Screenshot Sharing (60s old QR):** Rejected with `403 EXPIRED_QR_SCREENSHOT` and logged in `audit_logs`.<br>2. **Outside Campus GPS (4.5km away):** Rejected with `403 OUTSIDE_CAMPUS_GEOFENCE` (>500m radius).<br>3. **Late Check-in (+25m after start):** Accepted & automatically flagged `status = "LATE"`. |
| **3** | **Certificates** | 20 certificates generated; each verification link opens the correct record; tampered PDF fails verification | `test_3_twenty_certificates_and_tampered_pdf_detection` | **PASSED** — 23 PDFs (22 Certificates + 1 Official Transcript) generated in `data/certificates/`. Verified all 20 `/api/verify/{serial}` links return exact student/hash records. Uploaded genuine PDF (`AUTHENTIC_UNTAMPERED_PDF`) and byte-modified PDF (`TAMPERED_PDF_DETECTED` — failed verification as required). |
| **4** | **Events** | Event with 200 registrations and team formation runs without duplicates or lost entries | `test_4_event_with_200_registrations_and_team_formation` | **PASSED** — Registered 200 students into Gambade event across 50 teams of 4 (50 team creations + 150 team joins via invite code). Verified `total_registrations == 200`, `50 teams`, `0 lost entries`, and verified duplicate registration attempt is blocked (`400 Bad Request`). |
| **5** | **Permissions (RBAC)** | Coordinators see/edit only their own club; students cannot edit attendance or scores | `test_5_rbac_permissions_enforcement` | **PASSED** — Verified Student attempting attendance override (`403 Forbidden`) and rubric grading (`403 Forbidden`). Verified AI Club Coordinator attempting to plan a session or override attendance in Robotics Club is blocked (`403 Forbidden`). |
| **6** | **Reports** | Monthly report figures match the raw attendance and submission data | `test_6_monthly_report_matches_raw_attendance_and_submission_data` | **PASSED** — Cross-checked `/api/reports/monthly` output for every club against direct SQL counts on `attendances`, `submissions`, and `evaluations` (`average_rubric_score` matches to 2 decimal places). |
| **7** | **Middle 3 Stretch Goals** | 1. Club Budgets<br>2. Auto Duty Leave<br>3. Consent Media Gallery | `test_7_middle_three_stretch_goals` | **PASSED** — Verified `Coordinator -> Advisor -> Campus Manager` budget approval workflow, auto-generated Duty Leave approval, and student photo consent revocation hiding photos from the public gallery. |

---

## 2. Scalability & High-Concurrency Load Test Results (Section 7)

### Dataset Scale Provisioned
* **Campuses:** `3` (`HI-Tech`, `Rathinam`, `JUJ`)
* **Clubs:** `32` Active Clubs (`> 30` requirement)
* **Students:** `1,298` Students (`> 1,000` requirement)

### Saturday Morning Concurrent Check-In Benchmark (`100`, `300`, `500` Concurrent Users)
Run command:
```bash
PYTHONPATH=. ./.venv/bin/python3 tests/load_test_checkin.py
```

| Concurrent Check-Ins | Total Requests | Successful | Error Rate | Median (`p50`) Latency | **`p95` Latency (SLA < 1000ms)** | `p99` Latency | Throughput | SLA Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **100 Users** | 100 | 100 | **0.0%** | `78.71 ms` | **`93.20 ms`** | `98.14 ms` | `940.2 req/s` | **PASS (< 0.10s)** |
| **300 Users** | 300 | 300 | **0.0%** | `168.50 ms` | **`214.65 ms`** | `230.82 ms` | `1,105.2 req/s` | **PASS (< 0.22s)** |
| **500 Users** | 500 | 500 | **0.0%** | `259.08 ms` | **`354.21 ms`** | `359.76 ms` | `1,126.7 req/s` | **PASS (< 0.36s)** |

---

## 3. Detailed Behavior Matrix for Check-In Integrity Cases

| Scenario | Input Sent to `POST /api/sessions/{id}/checkin` | HTTP Status | System Action & Database State |
| :--- | :--- | :--- | :--- |
| **1. Valid On-Time QR / OTP** | Current 15s HMAC token + GPS within 500m of campus | `200 OK` | Inserts `Attendance(status="PRESENT", method="QR_SCAN")` with exact distance in meters. |
| **2. Late Arrival Check-In** | Current 15s token submitted after `checkin_late_after` (+15m) | `200 OK` | Inserts `Attendance(status="LATE", method="QR_SCAN")`; counted in Monthly Report's `late_checkins_flagged`. |
| **3. Shared WhatsApp Screenshot** | Cryptographically valid QR token from 60 seconds ago (expired bucket) | `403 Forbidden` | Returns `EXPIRED_QR_SCREENSHOT`; blocks check-in; writes `CHECKIN_REJECTED_EXPIRED_QR_SCREENSHOT` to `audit_logs`. |
| **4. Outside Campus Geo-Check** | Valid QR token + GPS coordinates 4.5 km away from campus | `403 Forbidden` | Returns `OUTSIDE_CAMPUS_GEOFENCE` with distance in meters; writes `CHECKIN_REJECTED_OUTSIDE_CAMPUS` to `audit_logs`. |
| **5. Coordinator Manual Override** | `POST /attendance/override` with `reason="Student phone camera broken"` | `200 OK` | Upserts `Attendance(method="MANUAL_OVERRIDE", override_reason=...)` and logs actor in `audit_logs`. Rejects with `400` if reason is missing. |
