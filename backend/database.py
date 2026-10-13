import os
import urllib.request
import json
from typing import Optional, Dict, Any
from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker, declarative_base

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

if os.environ.get("VERCEL") or not os.access(PROJECT_ROOT, os.W_OK):
    DATA_DIR = "/tmp/clubsync_data"
else:
    DATA_DIR = os.path.join(PROJECT_ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Supabase Configuration
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "club-tracker-assets").strip()

# Database URL priority: SUPABASE_DB_URL -> DATABASE_URL -> Local SQLite fallback
DEFAULT_SQLITE_URL = f"sqlite:///{os.path.join(DATA_DIR, 'msot_club_tracker.db')}"
RAW_DB_URL = (
    os.environ.get("SUPABASE_DB_URL", "").strip()
    or os.environ.get("DATABASE_URL", "").strip()
    or DEFAULT_SQLITE_URL
)

# Normalize postgres:// to postgresql+psycopg2:// for SQLAlchemy 2.0
if RAW_DB_URL.startswith("postgres://"):
    DATABASE_URL = RAW_DB_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif RAW_DB_URL.startswith("postgresql://"):
    DATABASE_URL = RAW_DB_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
else:
    DATABASE_URL = RAW_DB_URL

IS_SUPABASE_POSTGRES = DATABASE_URL.startswith("postgresql")

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": 60},
        pool_size=60,
        max_overflow=500,
        pool_pre_ping=False,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=30000;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()
else:
    # Supabase PostgreSQL connection pool (Transaction / Session pooler compatible)
    engine = create_engine(
        DATABASE_URL,
        pool_size=20,
        max_overflow=40,
        pool_pre_ping=True,
        connect_args={"sslmode": os.environ.get("PGSSLMODE", "require")},
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_database_info() -> Dict[str, Any]:
    return {
        "provider": "Supabase PostgreSQL" if IS_SUPABASE_POSTGRES else "Supabase-Compatible Local Engine (SQLite WAL)",
        "is_supabase_postgres": IS_SUPABASE_POSTGRES,
        "supabase_url_configured": bool(SUPABASE_URL),
        "supabase_storage_bucket": SUPABASE_STORAGE_BUCKET,
        "schema_sql_path": "supabase/schema.sql",
    }


def upload_to_supabase_storage(filepath: str, dest_path: str, content_type: str = "application/pdf") -> Optional[str]:
    """
    Uploads a file (e.g., PPT submission, event photo, or PDF certificate) to Supabase Storage
    when SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY / SUPABASE_ANON_KEY are configured.
    Returns the public Supabase Storage URL if configured, or None to use local file serving.
    """
    api_key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
    if not SUPABASE_URL or not api_key or not os.path.exists(filepath):
        return None
    try:
        url = f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/{SUPABASE_STORAGE_BUCKET}/{dest_path}"
        with open(filepath, "rb") as f:
            data = f.read()
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("apikey", api_key)
        req.add_header("Content-Type", content_type)
        req.add_header("x-upsert", "true")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status in (200, 201):
                return f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{SUPABASE_STORAGE_BUCKET}/{dest_path}"
    except Exception:
        return None
    return None
