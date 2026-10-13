import os
import io
import hmac
import hashlib
from typing import Dict, Any, List, Optional
import qrcode
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
if os.environ.get("VERCEL") or not os.access(PROJECT_ROOT, os.W_OK):
    CERT_DIR = "/tmp/clubsync_data/certificates"
else:
    CERT_DIR = os.path.join(PROJECT_ROOT, "data", "certificates")
os.makedirs(CERT_DIR, exist_ok=True)

SIGNING_SECRET = os.environ.get("MSOT_CERT_SECRET", "msot-verified-cocurricular-ledger-secret-2026")


def compute_certificate_hmac(
    serial_number: str,
    student_id: str,
    cert_type: str,
    title: str,
    issued_by_name: str,
) -> str:
    payload = f"{serial_number}|{student_id}|{cert_type}|{title}|{issued_by_name}".encode("utf-8")
    return hmac.new(SIGNING_SECRET.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _make_qr_image_reader(verify_url: str) -> ImageReader:
    qr = qrcode.QRCode(version=1, box_size=5, border=1)
    qr.add_data(verify_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def generate_certificate_pdf(
    serial_number: str,
    student_name: str,
    roll_number: str,
    campus_name: str,
    student_id: str,
    cert_type: str,
    title: str,
    citation: str,
    verification_evidence: str,
    issued_by_name: str,
    issued_by_role: str,
    issued_date_str: str,
    base_verify_url: str = "http://localhost:8000/verify",
) -> Dict[str, str]:
    """
    Generates a landscape A4 PDF Certificate with an embedded QR code,
    deterministic HMAC signature, and computes the exact SHA-256 hash of the PDF file.
    """
    hmac_sig = compute_certificate_hmac(
        serial_number=serial_number,
        student_id=student_id,
        cert_type=cert_type,
        title=title,
        issued_by_name=issued_by_name,
    )
    verify_url = f"{base_verify_url}/{serial_number}"

    buf = io.BytesIO()
    width, height = landscape(A4)
    c = canvas.Canvas(buf, pagesize=landscape(A4), invariant=1)
    c.setTitle(f"MSOT Verified Certificate - {serial_number}")
    c.setAuthor("MSOT Co-Curricular Verification Ledger")
    c.setSubject(f"SERIAL:{serial_number}|HMAC:{hmac_sig}")

    # Background & Ornamental Border
    c.setFillColor(colors.HexColor("#f8fafc"))
    c.rect(0, 0, width, height, fill=1, stroke=0)

    c.setStrokeColor(colors.HexColor("#1e3a8a"))
    c.setLineWidth(4)
    c.rect(24, 24, width - 48, height - 48, fill=0, stroke=1)

    c.setStrokeColor(colors.HexColor("#d97706"))
    c.setLineWidth(1.5)
    c.rect(32, 32, width - 64, height - 64, fill=0, stroke=1)

    # Header Banner
    c.setFillColor(colors.HexColor("#0f172a"))
    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(width / 2, height - 85, "MIRAI SCHOOL OF TECHNOLOGY (MSOT)")

    c.setFillColor(colors.HexColor("#475569"))
    c.setFont("Helvetica", 12)
    c.drawCentredString(
        width / 2,
        height - 105,
        f"VERIFIED CO-CURRICULAR RECORD • {campus_name.upper()} CAMPUS",
    )

    # Certificate Type Pill
    badge_label = f"CERTIFICATE OF {cert_type.replace('_', ' ').upper()}"
    c.setFillColor(colors.HexColor("#1e40af"))
    c.roundRect(width / 2 - 150, height - 150, 300, 30, 8, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(width / 2, height - 139, badge_label)

    # Main Recipient
    c.setFillColor(colors.HexColor("#64748b"))
    c.setFont("Helvetica-Oblique", 13)
    c.drawCentredString(width / 2, height - 190, "This is proudly presented to")

    c.setFillColor(colors.HexColor("#0f172a"))
    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(width / 2, height - 228, student_name)

    c.setFillColor(colors.HexColor("#334155"))
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, height - 250, f"Roll No: {roll_number}  |  Campus: {campus_name}")

    # Activity / Event Title
    c.setFillColor(colors.HexColor("#b45309"))
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, height - 288, title)

    # Citation text (wrapped up to 2 lines)
    c.setFillColor(colors.HexColor("#1e293b"))
    c.setFont("Helvetica", 12)
    if len(citation) > 95:
        split_idx = citation.rfind(" ", 0, 95)
        line1 = citation[:split_idx]
        line2 = citation[split_idx + 1 :]
        c.drawCentredString(width / 2, height - 315, line1)
        c.drawCentredString(width / 2, height - 333, line2)
    else:
        c.drawCentredString(width / 2, height - 320, citation)

    # Verification Evidence Box
    c.setFillColor(colors.HexColor("#ecfdf5"))
    c.setStrokeColor(colors.HexColor("#10b981"))
    c.setLineWidth(1)
    c.roundRect(120, height - 385, width - 240, 32, 6, fill=1, stroke=1)
    c.setFillColor(colors.HexColor("#065f46"))
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(
        width / 2,
        height - 373,
        f"VERIFIED PARTICIPATION PROOF: {verification_evidence}",
    )

    # QR Code on Bottom Left
    qr_reader = _make_qr_image_reader(verify_url)
    c.drawImage(qr_reader, 55, 55, width=95, height=95)

    c.setFillColor(colors.HexColor("#334155"))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(160, 125, f"Serial No: {serial_number}")
    c.setFont("Helvetica", 8.5)
    c.drawString(160, 110, f"Issued Date: {issued_date_str}")
    c.drawString(160, 95, f"Verify URL: {verify_url}")
    c.setFillColor(colors.HexColor("#64748b"))
    c.setFont("Courier", 7.5)
    c.drawString(160, 80, f"HMAC-SHA256: {hmac_sig[:36]}...")
    c.drawString(160, 68, "Tamper-evident PDF: Modifying any byte invalidates SHA-256 signature.")

    # Signature Line on Bottom Right
    c.setStrokeColor(colors.HexColor("#475569"))
    c.setLineWidth(1)
    c.line(width - 250, 95, width - 65, 95)
    c.setFillColor(colors.HexColor("#0f172a"))
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(width - 157, 78, issued_by_name)
    c.setFillColor(colors.HexColor("#64748b"))
    c.setFont("Helvetica", 9.5)
    c.drawCentredString(width - 157, 63, f"{issued_by_role}, MSOT")

    c.showPage()
    c.save()

    pdf_bytes = buf.getvalue()
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()

    filename = f"{serial_number}.pdf"
    filepath = os.path.join(CERT_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(pdf_bytes)

    return {
        "filename": filename,
        "filepath": filepath,
        "pdf_sha256_hash": pdf_sha256,
        "hmac_signature": hmac_sig,
        "verify_url": verify_url,
    }


def generate_transcript_pdf(
    serial_number: str,
    student: Dict[str, Any],
    clubs_summary: List[Dict[str, Any]],
    sessions_history: List[Dict[str, Any]],
    events_history: List[Dict[str, Any]],
    certificates_list: List[Dict[str, Any]],
    base_verify_url: str = "http://localhost:8000/verify",
) -> Dict[str, str]:
    """
    Generates a Verified Co-Curricular Transcript PDF (Portrait A4) for a student's resume,
    backed by check-ins, rubric evaluations, event results, and a tamper-evident QR & SHA-256 hash.
    """
    hmac_sig = compute_certificate_hmac(
        serial_number=serial_number,
        student_id=student["id"],
        cert_type="TRANSCRIPT",
        title=f"Official Co-Curricular Transcript - {student['full_name']}",
        issued_by_name="MSOT Academic & Co-Curricular Registry",
    )
    verify_url = f"{base_verify_url}/{serial_number}"

    buf = io.BytesIO()
    width, height = A4
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    c.setTitle(f"MSOT Co-Curricular Transcript - {student['roll_number']}")
    c.setAuthor("MSOT Co-Curricular Verification Ledger")
    c.setSubject(f"SERIAL:{serial_number}|HMAC:{hmac_sig}")

    # Top Header Bar
    c.setFillColor(colors.HexColor("#0f172a"))
    c.rect(0, height - 85, width, 85, fill=1, stroke=0)

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(36, height - 38, "MIRAI SCHOOL OF TECHNOLOGY (MSOT)")
    c.setFont("Helvetica", 10.5)
    c.drawString(36, height - 56, "OFFICIAL VERIFIED CO-CURRICULAR TRANSCRIPT")
    c.setFont("Courier-Bold", 9)
    c.drawRightString(width - 36, height - 38, f"TRANSCRIPT ID: {serial_number}")
    c.drawRightString(width - 36, height - 54, "STATUS: CRYPTOGRAPHICALLY VERIFIED")

    y = height - 110

    # Student Identity Card
    c.setFillColor(colors.HexColor("#f1f5f9"))
    c.setStrokeColor(colors.HexColor("#cbd5e1"))
    c.roundRect(36, y - 56, width - 72, 56, 6, fill=1, stroke=1)

    c.setFillColor(colors.HexColor("#0f172a"))
    c.setFont("Helvetica-Bold", 12)
    c.drawString(48, y - 20, f"Student: {student['full_name']}")
    c.setFont("Helvetica", 10)
    c.drawString(48, y - 36, f"Roll No: {student.get('roll_number') or 'N/A'}   |   Campus: {student.get('campus_name', 'HI-Tech')}")
    c.drawString(48, y - 50, f"Track: {student.get('track', 'Mirai Track')}   |   Batch: {student.get('batch', '2025-2029')}")

    y -= 80

    # Section 1: Enrolled Clubs
    c.setFillColor(colors.HexColor("#1e3a8a"))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(36, y, "1. REGISTERED CLUB MEMBERSHIPS & ROLES")
    y -= 6
    c.setStrokeColor(colors.HexColor("#1e3a8a"))
    c.line(36, y, width - 36, y)
    y -= 16

    c.setFillColor(colors.HexColor("#1e293b"))
    c.setFont("Helvetica", 9.5)
    if not clubs_summary:
        c.drawString(44, y, "No active club memberships recorded.")
        y -= 16
    else:
        for cl in clubs_summary:
            c.drawString(
                44,
                y,
                f"• {cl['club_name']} ({cl['category']}) — Role/Tier: {cl['tier']} | Status: {cl['status']}",
            )
            y -= 14

    y -= 10

    # Section 2: Verified Club Day Sessions & Evaluations
    c.setFillColor(colors.HexColor("#1e3a8a"))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(36, y, "2. VERIFIED SATURDAY CLUB DAY PARTICIPATION & RUBRIC SCORES")
    y -= 6
    c.line(36, y, width - 36, y)
    y -= 16

    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(colors.HexColor("#475569"))
    c.drawString(40, y, "DATE")
    c.drawString(100, y, "CLUB & ACTIVITY TOPIC")
    c.drawString(330, y, "CHECK-IN")
    c.drawString(415, y, "ROLE")
    c.drawString(485, y, "RUBRIC SCORE")
    y -= 12

    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.HexColor("#0f172a"))
    for sess in sessions_history[:12]:
        c.drawString(40, y, str(sess.get("date", ""))[:10])
        topic_str = f"{sess.get('club_code', '')}: {sess.get('topic', '')}"
        c.drawString(100, y, topic_str[:42])
        c.drawString(330, y, f"{sess.get('attendance_status', 'PRESENT')} ({sess.get('method', 'QR')})")
        c.drawString(415, y, "Presenter" if sess.get("is_presenter") else "Member")
        score_txt = f"{sess['total_score']}/30" if sess.get("total_score") is not None else "Pending"
        c.drawString(485, y, score_txt)
        y -= 13
        if y < 180:
            break

    y -= 10

    # Section 3: Campus & Inter-Campus Events
    c.setFillColor(colors.HexColor("#1e3a8a"))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(36, y, "3. CAMPUS & INTER-CAMPUS EVENTS (GAMBADE / HACKATHON / CONF / CROSS ROAD)")
    y -= 6
    c.line(36, y, width - 36, y)
    y -= 16

    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#1e293b"))
    if not events_history:
        c.drawString(44, y, "No event registrations recorded.")
        y -= 14
    else:
        for ev in events_history[:6]:
            c.drawString(
                44,
                y,
                f"• {ev['title']} ({ev['category']}) — Team: {ev.get('team_name') or 'Individual'} | "
                f"Check-in: {'Verified' if ev.get('checked_in') else 'Registered'} | Result: {ev.get('result') or 'Participant'}",
            )
            y -= 14

    # Footer Verification Block with QR Code
    c.setStrokeColor(colors.HexColor("#cbd5e1"))
    c.line(36, 130, width - 36, 130)

    qr_reader = _make_qr_image_reader(verify_url)
    c.drawImage(qr_reader, 36, 32, width=85, height=85)

    c.setFillColor(colors.HexColor("#0f172a"))
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(132, 105, "STUDENT-OWNED VERIFIED CO-CURRICULAR RECORD")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.HexColor("#334155"))
    c.drawString(132, 91, "Every entry in this transcript is backed by a live QR/OTP check-in, deliverable submission,")
    c.drawString(132, 79, "or Coordinator/Faculty Advisor rubric evaluation in the MSOT Club Tracker platform.")
    c.drawString(132, 65, f"Public Verification Portal: {verify_url}")
    c.setFont("Courier", 7.5)
    c.setFillColor(colors.HexColor("#64748b"))
    c.drawString(132, 50, f"HMAC Signature: {hmac_sig}")
    c.drawString(132, 38, "Tamper Check: Upload this PDF at /verify to validate its SHA-256 cryptographic digest.")

    c.showPage()
    c.save()

    pdf_bytes = buf.getvalue()
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()

    filename = f"{serial_number}.pdf"
    filepath = os.path.join(CERT_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(pdf_bytes)

    return {
        "filename": filename,
        "filepath": filepath,
        "pdf_sha256_hash": pdf_sha256,
        "hmac_signature": hmac_sig,
        "verify_url": verify_url,
    }
