import hmac
import hashlib
import time
import math
import base64
import io
from typing import Optional, Dict, Any
import qrcode

ROTATION_INTERVAL_SEC = 15
_QR_IMAGE_CACHE: Dict[str, str] = {}


def get_time_bucket(timestamp: Optional[float] = None, interval: int = ROTATION_INTERVAL_SEC) -> int:
    ts = timestamp if timestamp is not None else time.time()
    return int(ts // interval)


def generate_totp_signature(secret: str, session_id: str, bucket: int) -> str:
    msg = f"{session_id}:{bucket}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:16]


def generate_otp_code(secret: str, session_id: str, bucket: int) -> str:
    sig = generate_totp_signature(secret, session_id, bucket)
    num = int(sig[:8], 16) % 1000000
    return f"{num:06d}"


def generate_qr_payload(secret: str, session_id: str, timestamp: Optional[float] = None) -> Dict[str, Any]:
    ts = timestamp if timestamp is not None else time.time()
    bucket = get_time_bucket(ts)
    sig = generate_totp_signature(secret, session_id, bucket)
    otp_code = generate_otp_code(secret, session_id, bucket)
    token = f"MSOT-QR:{session_id}:{bucket}:{sig}"
    expires_in = ROTATION_INTERVAL_SEC - int(ts % ROTATION_INTERVAL_SEC)

    cache_key = f"{session_id}:{bucket}"
    if cache_key not in _QR_IMAGE_CACHE:
        qr = qrcode.QRCode(version=1, box_size=6, border=2)
        qr.add_data(token)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#0f172a", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64_img = base64.b64encode(buf.getvalue()).decode("ascii")
        if len(_QR_IMAGE_CACHE) > 256:
            _QR_IMAGE_CACHE.clear()
        _QR_IMAGE_CACHE[cache_key] = f"data:image/png;base64,{b64_img}"

    return {
        "session_id": session_id,
        "qr_token": token,
        "otp_code": otp_code,
        "time_bucket": bucket,
        "rotation_interval_sec": ROTATION_INTERVAL_SEC,
        "expires_in_sec": expires_in,
        "qr_image_data_url": _QR_IMAGE_CACHE[cache_key],
    }


def haversine_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Compute distance in meters between two GPS coordinates."""
    r = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)

    a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def verify_checkin_token_or_otp(
    secret: str,
    session_id: str,
    qr_token: Optional[str] = None,
    otp_code: Optional[str] = None,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Verify either a rotating QR token or 6-digit OTP code.
    Allows current bucket and -1 bucket (15s grace window for network lag).
    Older valid buckets are explicitly detected as EXPIRED_SCREENSHOT!
    """
    ts = now_ts if now_ts is not None else time.time()
    current_bucket = get_time_bucket(ts)
    valid_buckets = {current_bucket, current_bucket - 1}

    if qr_token:
        parts = qr_token.strip().split(":")
        if len(parts) != 4 or parts[0] != "MSOT-QR":
            return {"valid": False, "code": "MALFORMED_QR_TOKEN", "message": "Invalid QR token format."}

        _, token_session_id, bucket_str, provided_sig = parts
        if token_session_id != session_id:
            return {"valid": False, "code": "WRONG_SESSION_QR", "message": "QR token belongs to a different session."}

        try:
            token_bucket = int(bucket_str)
        except ValueError:
            return {"valid": False, "code": "INVALID_BUCKET", "message": "Invalid QR timestamp bucket."}

        expected_sig = generate_totp_signature(secret, session_id, token_bucket)
        if not hmac.compare_digest(provided_sig, expected_sig):
            return {"valid": False, "code": "FORGED_QR_SIGNATURE", "message": "QR cryptographic signature is invalid."}

        if token_bucket not in valid_buckets:
            age_seconds = (current_bucket - token_bucket) * ROTATION_INTERVAL_SEC
            return {
                "valid": False,
                "code": "EXPIRED_QR_SCREENSHOT",
                "message": f"Anti-screenshot protection triggered: QR code expired {age_seconds}s ago. Please scan the live screen.",
            }

        return {"valid": True, "method": "QR_SCAN", "bucket": token_bucket}

    if otp_code:
        cleaned = otp_code.strip()
        for b in valid_buckets:
            if hmac.compare_digest(cleaned, generate_otp_code(secret, session_id, b)):
                return {"valid": True, "method": "OTP_CODE", "bucket": b}

        # Check recent 40 buckets (last 10 mins) to distinguish expired OTP screenshot vs wrong typo
        for old_b in range(current_bucket - 40, current_bucket - 1):
            if hmac.compare_digest(cleaned, generate_otp_code(secret, session_id, old_b)):
                age_s = (current_bucket - old_b) * ROTATION_INTERVAL_SEC
                return {
                    "valid": False,
                    "code": "EXPIRED_OTP_CODE",
                    "message": f"One-time code expired {age_s}s ago. Shared codes are blocked.",
                }

        return {"valid": False, "code": "INVALID_OTP_CODE", "message": "Invalid 6-digit check-in code."}

    return {"valid": False, "code": "MISSING_CREDENTIALS", "message": "Provide either qr_token or otp_code."}
