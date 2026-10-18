from sqlalchemy.orm import Session
from .models import SystemConfig, Campus


def seed_database(db: Session) -> dict:
    """
    Initializes only the 3 official MSOT Campuses (HI-Tech, Rathinam, JUJ)
    and default system configuration rules. No mock users, clubs, or sessions are seeded.
    """
    if db.query(Campus).count() == 0:
        campuses_data = [
            ("HI-Tech", "MSOT HI-Tech City Campus", "Hyderabad", 17.4435, 78.3772, 500),
            ("Rathinam", "MSOT Rathinam Tech Valley Campus", "Coimbatore", 10.9366, 76.9667, 500),
            ("JUJ", "MSOT JUJ Knowledge Park Campus", "Jaipur", 26.9124, 75.7873, 500),
        ]
        for code, name, city, lat, lng, radius in campuses_data:
            db.add(
                Campus(
                    code=code,
                    name=name,
                    city=city,
                    lat=lat,
                    lng=lng,
                    geofence_radius_m=radius,
                )
            )

    if db.query(SystemConfig).count() == 0:
        configs = [
            SystemConfig(
                key="max_primary_clubs",
                value="1",
                description="Maximum Primary clubs a student can enrol in per semester",
            ),
            SystemConfig(
                key="max_secondary_clubs",
                value="1",
                description="Maximum Secondary clubs a student can enrol in per semester",
            ),
            SystemConfig(
                key="qr_rotation_seconds",
                value="15",
                description="Time-based QR rotation interval in seconds",
            ),
            SystemConfig(
                key="geofence_check_enabled",
                value="true",
                description="Require student GPS coordinates within campus geofence radius during check-in",
            ),
        ]
        db.add_all(configs)

    # Ensure official Campus Manager account exists with password 'sundaram'
    from .models import User
    from .database import hash_password
    mgr_email = "sundaram.mishra@msot.org"
    hi_tech = db.query(Campus).filter(Campus.code == "HI-Tech").first()
    existing_mgr = db.query(User).filter(User.email == mgr_email).first()
    if not existing_mgr:
        db.add(
            User(
                email=mgr_email,
                password_hash=hash_password("sundaram"),
                full_name="Sundaram Mishra",
                role="CAMPUS_MGR",
                account_status="APPROVED",
                campus_id=hi_tech.id if hi_tech else None,
                roll_number="MSOT-CM-01",
                batch="Staff",
                track="Administration",
            )
        )
    else:
        existing_mgr.password_hash = hash_password("sundaram")
        existing_mgr.role = "CAMPUS_MGR"
        existing_mgr.account_status = "APPROVED"
        if not existing_mgr.campus_id and hi_tech:
            existing_mgr.campus_id = hi_tech.id

    db.commit()
    return {"initialized": True}
