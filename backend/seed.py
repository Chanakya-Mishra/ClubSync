from sqlalchemy.orm import Session
from .models import SystemConfig, Campus


def seed_database(db: Session) -> dict:
    """
    Initializes only the 4 official MSOT Campuses (HI-Tech, Ratnam, RGIB, JUJ)
    and default system configuration rules. No mock users, clubs, or sessions are seeded.
    """
    if db.query(Campus).count() == 0:
        campuses_data = [
            ("HI-Tech", "MSOT HI-Tech City Campus", "Hyderabad", 17.4435, 78.3772, 500),
            ("Ratnam", "MSOT Ratnam Tech Valley Campus", "Nellore", 14.4426, 79.9865, 500),
            ("RGIB", "MSOT RGIB Innovation Campus", "Bengaluru", 12.9716, 77.5946, 500),
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

    db.commit()
    return {"initialized": True}
