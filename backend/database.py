import os
import urllib.request
import json
from typing import Optional, Dict, Any
from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker, declarative_base

import hashlib
import secrets
import hmac

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

if os.environ.get("VERCEL") or not os.access(PROJECT_ROOT, os.W_OK):
    DATA_DIR = "/tmp/clubsync_data"
else:
    DATA_DIR = os.path.join(PROJECT_ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Supabase Configuration
_env_supabase_url = os.environ.get("SUPABASE_URL", "").strip()
if not _env_supabase_url or "rpskgbyrpfyszpyfwebp" in _env_supabase_url:
    _alt_url = os.environ.get("NEXT_PUBLIC_clubsync_SUPABASE_URL", "").strip()
    if _alt_url and "rpskgbyrpfyszpyfwebp" not in _alt_url:
        SUPABASE_URL = _alt_url
    else:
        SUPABASE_URL = "https://jmesfffyyzlhyjtdbipa.supabase.co"
else:
    SUPABASE_URL = _env_supabase_url

_env_anon_key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
if not _env_anon_key:
    _alt_anon = os.environ.get("clubsync_SUPABASE_ANON_KEY", "").strip()
    SUPABASE_ANON_KEY = _alt_anon if "rpskgbyrpfyszpyfwebp" not in _alt_anon else ""
else:
    SUPABASE_ANON_KEY = _env_anon_key

_env_service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
if not _env_service_key:
    _alt_service = os.environ.get("clubsync_SUPABASE_SERVICE_ROLE_KEY", "").strip()
    SUPABASE_SERVICE_ROLE_KEY = _alt_service if "rpskgbyrpfyszpyfwebp" not in _alt_service else ""
else:
    SUPABASE_SERVICE_ROLE_KEY = _env_service_key

SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "club-tracker-assets").strip()

from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

# Cloud Supabase Database Pooler URL (Configured for project jmesfffyyzlhyjtdbipa in region ap-south-1)
SUPABASE_CLOUD_DB_URL = "postgresql://postgres.jmesfffyyzlhyjtdbipa:cognix%40902008@aws-0-ap-south-1.pooler.supabase.com:6543/postgres?sslmode=require"
DEFAULT_SQLITE_URL = f"sqlite:///{os.path.join(DATA_DIR, 'msot_club_tracker.db')}"


def _get_valid_env_db_url() -> str:
    for key in (
        "SUPABASE_DB_URL",
        "DATABASE_URL",
        "POSTGRES_URL_NON_POOLING",
        "POSTGRES_URL",
        "POSTGRES_PRISMA_URL",
        "clubsync_POSTGRES_URL",
        "clubsync_POSTGRES_PRISMA_URL",
        "clubsync_POSTGRES_URL_NON_POOLING",
    ):
        val = os.environ.get(key, "").strip()
        if (
            val
            and "[PASSWORD]" not in val
            and "[PROJECT-REF]" not in val
            and "YOUR_PASSWORD" not in val
            and "rpskgbyrpfyszpyfwebp" not in val
        ):
            return val
    # If running on Vercel or cloud mode, use the verified Supabase Cloud URL directly
    if os.environ.get("VERCEL") or os.environ.get("USE_SUPABASE"):
        return SUPABASE_CLOUD_DB_URL
    return SUPABASE_CLOUD_DB_URL


RAW_DB_URL = _get_valid_env_db_url()


def _clean_postgres_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql"):
        parsed = urlparse(url)
        # Strip pgbouncer / supa params injected by Vercel integrations that psycopg2 rejects
        allowed_q = [
            (k, v)
            for k, v in parse_qsl(parsed.query)
            if k.lower() not in ("pgbouncer", "supa", "schema", "connection_limit", "pool_timeout")
        ]
        url = urlunparse(parsed._replace(query=urlencode(allowed_q)))
    return url


DATABASE_URL = _clean_postgres_url(RAW_DB_URL)
IS_SUPABASE_POSTGRES = DATABASE_URL.startswith("postgresql")
IS_EPHEMERAL_VERCEL_SQLITE = bool(os.environ.get("VERCEL")) and not IS_SUPABASE_POSTGRES

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
    # Supabase PostgreSQL connection pool with connection reuse and health checks
    engine = create_engine(
        DATABASE_URL,
        pool_size=5,
        max_overflow=10,
        pool_recycle=300,
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
        "provider": (
            "Supabase PostgreSQL"
            if IS_SUPABASE_POSTGRES
            else (
                "Ephemeral /tmp SQLite (Connect Supabase/Postgres on Vercel to persist data!)"
                if IS_EPHEMERAL_VERCEL_SQLITE
                else "Local SQLite Engine (data/msot_club_tracker.db)"
            )
        ),
        "is_supabase_postgres": IS_SUPABASE_POSTGRES,
        "is_ephemeral_vercel_sqlite": IS_EPHEMERAL_VERCEL_SQLITE,
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


def hash_password(password: str, salt: Optional[str] = None) -> str:
    s = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), s.encode("utf-8"), 100_000)
    return f"{s}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash or "$" not in stored_hash:
        return False
    salt, _ = stored_hash.split("$", 1)
    return hmac.compare_digest(hash_password(password, salt), stored_hash)

