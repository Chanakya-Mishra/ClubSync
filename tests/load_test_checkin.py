import os
import time
import json
import asyncio
import statistics
from typing import List, Dict, Any
import httpx

from backend.main import app
from backend.database import Base, engine, SessionLocal
from backend.models import Campus, User, Club, ClubDaySession
from backend.seed import seed_database


def ensure_scale_dataset_1000_students_30_clubs():
    """
    Ensures the database meets Section 7 Scalability Requirement:
    4 campuses, 30+ clubs, and 1,000+ students.
    """
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_database(db)
        campuses = db.query(Campus).all()
        campus_ids = [c.id for c in campuses]

        # Ensure 32 Clubs across the 4 campuses
        existing_clubs = db.query(Club).count()
        if existing_clubs < 32:
            new_clubs = []
            for i in range(existing_clubs + 1, 33):
                cid = campus_ids[i % len(campus_ids)]
                new_clubs.append(
                    Club(
                        id=f"club-scale-{i}",
                        campus_id=cid,
                        code=f"MSOT-CLUB-{i:02d}",
                        name=f"MSOT Campus Innovation Club #{i}",
                        category="Technology & Innovation",
                        description=f"Scalability verified club #{i} for MSOT multi-campus deployment.",
                        capacity=60,
                        status="ACTIVE",
                    )
                )
            db.add_all(new_clubs)
            db.commit()

        # Ensure 1,050 Students across the 4 campuses
        existing_students = db.query(User).filter(User.role == "STUDENT").count()
        if existing_students < 1050:
            existing_ids = {u.id for u in db.query(User).all()}
            new_students = []
            for i in range(1, 1055):
                uid = f"user-load-st-{i}"
                if uid not in existing_ids:
                    cid = campus_ids[i % len(campus_ids)]
                    new_students.append(
                        User(
                            id=uid,
                            email=f"load.student.{i}@msot.org",
                            full_name=f"MSOT Student {i}",
                            roll_number=f"MSOT-26-LD-{i:04d}",
                            role="STUDENT",
                            campus_id=cid,
                            batch="2025-2029 B.Tech",
                            track="Mirai Track" if i % 2 == 0 else "University Track",
                        )
                    )
            if new_students:
                db.add_all(new_students)
                db.commit()

        return {
            "campuses": db.query(Campus).count(),
            "clubs": db.query(Club).count(),
            "students": db.query(User).filter(User.role == "STUDENT").count(),
        }
    finally:
        db.close()


async def run_concurrent_checkin_wave(concurrency: int, session_id: str) -> Dict[str, Any]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Open check-in window & fetch live rotating QR token
        await client.post(
            f"/api/sessions/{session_id}/checkin-window",
            headers={"X-User-Id": "user-coord-ai"},
            json={"action": "OPEN", "duration_minutes": 60, "late_after_minutes": 15},
        )
        qr_resp = await client.get(f"/api/sessions/{session_id}/qr")
        qr_token = qr_resp.json()["qr_token"]

        latencies_ms: List[float] = []
        errors = 0

        async def single_student_checkin(idx: int):
            nonlocal errors
            student_id = f"user-load-st-{idx}"
            t0 = time.perf_counter()
            resp = await client.post(
                f"/api/sessions/{session_id}/checkin",
                headers={"X-User-Id": student_id},
                json={
                    "student_id": student_id,
                    "qr_token": qr_token,
                    "lat": 17.4435 + (idx % 5) * 0.0001,
                    "lng": 78.3772 + (idx % 5) * 0.0001,
                },
            )
            dt_ms = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(dt_ms)
            if resp.status_code != 200:
                errors += 1

        wall_start = time.perf_counter()
        # Dispatch concurrent check-in wave
        await asyncio.gather(*(single_student_checkin(i) for i in range(1, concurrency + 1)))
        wall_elapsed_s = time.perf_counter() - wall_start

        latencies_ms.sort()
        p50 = round(latencies_ms[int(len(latencies_ms) * 0.50)], 2)
        p95 = round(latencies_ms[int(len(latencies_ms) * 0.95)], 2)
        p99 = round(latencies_ms[min(len(latencies_ms) - 1, int(len(latencies_ms) * 0.99))], 2)
        avg_ms = round(statistics.mean(latencies_ms), 2)
        error_rate_pct = round((errors / concurrency) * 100.0, 2)

        return {
            "concurrent_users": concurrency,
            "total_requests": concurrency,
            "successful_responses": concurrency - errors,
            "failed_responses": errors,
            "error_rate_pct": error_rate_pct,
            "p50_latency_ms": p50,
            "avg_latency_ms": avg_ms,
            "p95_latency_ms": p95,
            "p99_latency_ms": p99,
            "total_wall_time_sec": round(wall_elapsed_s, 3),
            "throughput_req_per_sec": round(concurrency / wall_elapsed_s, 1),
            "sla_p95_under_1000ms_passed": p95 < 1000.0 and error_rate_pct == 0.0,
        }


async def main():
    scale_counts = ensure_scale_dataset_1000_students_30_clubs()
    print("======================================================================")
    print("MSOT CLUB ACTIVITIES TRACKER — SCALABILITY & CONCURRENCY LOAD TEST")
    print(f"Dataset Scale: {scale_counts['campuses']} Campuses | {scale_counts['clubs']} Clubs | {scale_counts['students']} Students")
    print("======================================================================")

    sessions_for_waves = [
        (100, "sess-msot-ai-club-wk1"),
        (300, "sess-msot-ai-club-wk2"),
        (500, "sess-msot-ai-club-wk3"),
    ]

    results = []
    for concurrency, sess_id in sessions_for_waves:
        res = await run_concurrent_checkin_wave(concurrency, sess_id)
        results.append(res)
        print(
            f"[Wave: {concurrency:3d} Concurrent Check-Ins] "
            f"p50: {res['p50_latency_ms']:6.2f}ms | "
            f"p95: {res['p95_latency_ms']:6.2f}ms (<1000ms SLA) | "
            f"p99: {res['p99_latency_ms']:6.2f}ms | "
            f"Error Rate: {res['error_rate_pct']}% | "
            f"Throughput: {res['throughput_req_per_sec']} req/s"
        )

    out_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "load_test_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"scale": scale_counts, "waves": results}, f, indent=2)
    print("======================================================================")
    print(f"Saved load test report to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
