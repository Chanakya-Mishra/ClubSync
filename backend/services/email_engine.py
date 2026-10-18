import os
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional

try:
    from dotenv import load_dotenv
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(os.path.dirname(BASE_DIR), ".env"))
    load_dotenv()
except Exception:
    pass

DEFAULT_GMAIL_USER = "info.clubsync@gmail.com"
DEFAULT_GMAIL_APP_PWD = "weftjnainoemxtrj"

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))


def _get_credentials():
    user = (
        os.environ.get("GMAIL_USER", "").strip()
        or os.environ.get("SMTP_USER", "").strip()
        or os.environ.get("SMTP_EMAIL", "").strip()
        or DEFAULT_GMAIL_USER
    )
    pwd = (
        os.environ.get("GMAIL_APP_PASSWORD", "").strip()
        or os.environ.get("SMTP_PASSWORD", "").strip()
        or DEFAULT_GMAIL_APP_PWD
    )
    if pwd:
        pwd = pwd.replace(" ", "")
    return user, pwd


def send_email_sync(
    to_emails: List[str],
    subject: str,
    html_content: str,
    text_content: Optional[str] = None,
    is_bulk: bool = False,
    club_name_header: Optional[str] = None,
) -> bool:
    """
    Sends an email to one or multiple recipients using Google SMTP.
    Uses direct SSL (port 465) with automatic fallback to STARTTLS (port 587).
    Works reliably in both local and serverless (Vercel) environments.
    """
    if not to_emails:
        return False

    valid_recipients = [e.strip() for e in to_emails if e and "@" in e]
    if not valid_recipients:
        return False

    user, pwd = _get_credentials()
    if not user or not pwd:
        print(f"[EmailEngine - Dry Run] No SMTP credentials configured.")
        return False

    sender_name = os.environ.get("EMAIL_SENDER_NAME", "ClubSync Multi-Campus Platform")
    from_header = f"{sender_name} <{user}>"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_header

    if is_bulk or len(valid_recipients) > 1:
        # Protect recipient privacy (Bcc mode for club announcements)
        recipient_label = f"{club_name_header} Members" if club_name_header else "Club Members"
        msg["To"] = f"{recipient_label} <{user}>"
    else:
        msg["To"] = valid_recipients[0]

    if text_content:
        msg.attach(MIMEText(text_content, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))
    msg_str = msg.as_string()

    # Try Port 465 (SSL) first — fastest and works through firewalls/serverless
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=12) as server:
            server.login(user, pwd)
            server.sendmail(user, valid_recipients, msg_str)
        print(f"[EmailEngine - SSL 465] Dispatched email to {len(valid_recipients)} recipient(s): '{subject}'")
        return True
    except Exception as exc_ssl:
        print(f"[EmailEngine] Port 465 attempt encountered ({exc_ssl}), trying Port 587 STARTTLS...")

    # Fallback to Port 587 (STARTTLS)
    try:
        with smtplib.SMTP(SMTP_HOST, 587, timeout=12) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, pwd)
            server.sendmail(user, valid_recipients, msg_str)
        print(f"[EmailEngine - STARTTLS 587] Dispatched email to {len(valid_recipients)} recipient(s): '{subject}'")
        return True
    except Exception as exc_tls:
        print(f"[EmailEngine Error] Both 465 and 587 failed for '{subject}' to {valid_recipients}: {exc_tls}")
        return False


def send_email_in_background(
    to_emails: List[str],
    subject: str,
    html_content: str,
    text_content: Optional[str] = None,
    is_bulk: bool = False,
    club_name_header: Optional[str] = None,
):
    """
    In serverless environments (Vercel), background threads are terminated when HTTP response finishes.
    In Vercel, we dispatch synchronously (taking ~1.5s).
    In local/persistent server environments, we run with a short thread join so responses aren't blocked.
    """
    if os.environ.get("VERCEL"):
        send_email_sync(to_emails, subject, html_content, text_content, is_bulk, club_name_header)
    else:
        t = threading.Thread(
            target=send_email_sync,
            args=(to_emails, subject, html_content, text_content, is_bulk, club_name_header),
            daemon=True,
        )
        t.start()
        # Wait up to 3.5s so delivery usually completes before response without blocking indefinitely
        t.join(timeout=3.5)


# ============================================================================
# Reusable HTML Templates with Modern ClubSync Branding
# ============================================================================

def _base_template(title: str, body_html: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 0; background-color: #f1f5f9; color: #1e293b; }}
    .container {{ max-width: 600px; margin: 28px auto; background: #ffffff; border-radius: 16px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 4px 20px rgba(0,0,0,0.04); }}
    .header {{ background: linear-gradient(135deg, #1e1b4b 0%, #312e81 60%, #4338ca 100%); padding: 28px 24px; text-align: center; color: #ffffff; }}
    .logo {{ font-size: 24px; font-weight: 800; letter-spacing: -0.5px; margin: 0; }}
    .logo-accent {{ color: #38bdf8; }}
    .tagline {{ font-size: 12px; color: #cbd5e1; margin-top: 4px; font-weight: 500; text-transform: uppercase; letter-spacing: 1px; }}
    .content {{ padding: 32px 28px; line-height: 1.6; font-size: 14px; }}
    .card {{ background: #f8fafc; border-radius: 12px; padding: 18px 20px; border: 1px solid #e2e8f0; margin: 20px 0; }}
    .otp-code {{ font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #4338ca; background: #e0e7ff; padding: 12px 20px; border-radius: 10px; display: inline-block; font-family: Courier, monospace; margin: 12px 0; border: 1px solid #c7d2fe; }}
    .btn {{ display: inline-block; background: linear-gradient(135deg, #2563eb 0%, #4f46e5 100%); color: #ffffff !important; font-weight: 700; font-size: 14px; text-decoration: none; padding: 12px 28px; border-radius: 10px; margin-top: 16px; }}
    .footer {{ background: #f8fafc; padding: 20px; text-align: center; font-size: 11px; color: #64748b; border-top: 1px solid #e2e8f0; }}
    .badge {{ display: inline-block; padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; background: #e0f2fe; color: #0369a1; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1 class="logo">Club<span class="logo-accent">Sync</span></h1>
      <div class="tagline">Multi-Campus Co-Curricular Platform</div>
    </div>
    <div class="content">
      {body_html}
    </div>
    <div class="footer">
      <p style="margin: 0 0 6px;">This is an automated notification from ClubSync (HI-Tech, Rathinam & JUJ Campuses).</p>
      <p style="margin: 0;">Please do not reply directly to this email.</p>
    </div>
  </div>
</body>
</html>"""


def send_password_reset_otp_email(to_email: str, full_name: str, otp: str):
    """Dispatches a 6-digit verification code to the user for resetting their password."""
    subject = f"[ClubSync] Your Password Reset OTP: {otp}"
    body_html = f"""
      <h2 style="font-size: 18px; margin-top: 0; color: #0f172a;">Password Reset Verification</h2>
      <p>Hello <strong>{full_name}</strong>,</p>
      <p>We received a request to reset the password for your ClubSync account associated with <strong>{to_email}</strong>.</p>
      
      <div style="text-align: center; margin: 24px 0;">
        <div style="font-size: 12px; font-weight: 600; color: #64748b; text-transform: uppercase;">Your 6-Digit Verification Code</div>
        <div class="otp-code">{otp}</div>
        <div style="font-size: 12px; color: #dc2626; font-weight: 600;">⏱️ Valid for 15 minutes</div>
      </div>

      <p>Enter this code in the password reset window on ClubSync to choose a new password.</p>
      
      <div class="card" style="border-left: 4px solid #f59e0b; background: #fffbeb;">
        <strong style="color: #92400e; font-size: 12px;">Security Notice:</strong>
        <p style="font-size: 12px; color: #78350f; margin: 4px 0 0;">
          If you did not request this verification code, please ignore this email. Your current password remains secure and untouched.
        </p>
      </div>
    """
    text_content = f"Your ClubSync Password Reset OTP code is: {otp}\nThis code is valid for 15 minutes.\nIf you did not request this, please ignore."
    send_email_in_background([to_email], subject, _base_template("Password Reset Verification", body_html), text_content)


def send_account_approved_email(to_email: str, full_name: str, role: str, campus_name: str):
    """Dispatches an approval confirmation email when Campus Manager grants access."""
    subject = f"[ClubSync] Account Approved — Welcome to the Platform!"
    body_html = f"""
      <h2 style="font-size: 18px; margin-top: 0; color: #0f172a;">Account Approved! 🎉</h2>
      <p>Hello <strong>{full_name}</strong>,</p>
      <p>Great news! Your ClubSync account has been officially verified and <strong>approved by the Campus Manager</strong>.</p>
      
      <div class="card">
        <div style="margin-bottom: 8px;"><strong>Role:</strong> <span class="badge">{role}</span></div>
        <div style="margin-bottom: 8px;"><strong>Campus:</strong> {campus_name}</div>
        <div><strong>Login Email:</strong> {to_email}</div>
      </div>

      <p>You can now sign in to your workspace, join official college clubs, participate in Saturday Club Day activities, submit deliverables, and track your verified co-curricular achievements.</p>
      
      <div style="text-align: center; margin-top: 24px;">
        <a href="https://clubsync.vercel.app" class="btn">Sign In to ClubSync Workspace →</a>
      </div>
    """
    text_content = f"Hello {full_name},\nYour ClubSync account has been approved by the Campus Manager! You can now log in to the workspace at https://clubsync.vercel.app"
    send_email_in_background([to_email], subject, _base_template("Account Approved", body_html), text_content)


def send_session_announced_email(
    to_emails: List[str],
    club_name: str,
    topic: str,
    scheduled_date: str,
    venue: str,
    format_type: str,
    deliverable_desc: str,
):
    """Dispatches a meeting invitation and session instructions to all approved club members."""
    if not to_emails:
        return

    subject = f"[ClubSync] New Saturday Session: {topic} ({club_name})"
    body_html = f"""
      <div style="margin-bottom: 12px;">
        <span class="badge">{club_name}</span>
        <span class="badge" style="background: #fef3c7; color: #92400e; margin-left: 6px;">Club Day Session</span>
      </div>
      
      <h2 style="font-size: 20px; margin-top: 0; color: #0f172a; line-height: 1.3;">{topic}</h2>
      
      <p>Your Club President has scheduled and announced an upcoming Saturday Club Day session. Here are the session details:</p>
      
      <div class="card">
        <table style="width: 100%; font-size: 13px; border-collapse: collapse;">
          <tr>
            <td style="padding: 6px 0; color: #64748b; width: 120px;"><strong>Date:</strong></td>
            <td style="padding: 6px 0; font-weight: 700; color: #0f172a;">📅 {scheduled_date}</td>
          </tr>
          <tr>
            <td style="padding: 6px 0; color: #64748b;"><strong>Venue:</strong></td>
            <td style="padding: 6px 0; font-weight: 700; color: #0f172a;">📍 {venue}</td>
          </tr>
          <tr>
            <td style="padding: 6px 0; color: #64748b;"><strong>Format:</strong></td>
            <td style="padding: 6px 0; font-weight: 600; color: #4338ca;">⚡ {format_type}</td>
          </tr>
        </table>
      </div>

      <h3 style="font-size: 14px; color: #334155; margin-bottom: 6px;">Deliverable & Task Requirements:</h3>
      <div style="background: #ffffff; border-left: 3px solid #6366f1; padding: 8px 14px; font-size: 13px; color: #475569; margin-bottom: 16px;">
        {deliverable_desc}
      </div>

      <p style="font-size: 13px; color: #64748b;">
        <strong>Important:</strong> Bring your laptop / materials. Be present in the venue to scan the rotating QR code for attendance.
      </p>

      <div style="text-align: center; margin-top: 24px;">
        <a href="https://clubsync.vercel.app" class="btn">View Session in ClubSync →</a>
      </div>
    """
    text_content = f"New Saturday Session announced for {club_name}!\nTopic: {topic}\nDate: {scheduled_date}\nVenue: {venue}\nFormat: {format_type}\nDeliverable: {deliverable_desc}"
    send_email_in_background(
        to_emails,
        subject,
        _base_template("New Saturday Club Session", body_html),
        text_content,
        is_bulk=True,
        club_name_header=club_name,
    )


def send_club_news_email(
    to_emails: List[str],
    club_name: str,
    title: str,
    content: str,
    author_name: str,
):
    """Dispatches a news announcement broadcast to all approved club members."""
    if not to_emails:
        return

    subject = f"[ClubSync Announcement] {title} ({club_name})"
    formatted_content = "<br />".join(content.strip().split("\n"))
    body_html = f"""
      <div style="margin-bottom: 12px;">
        <span class="badge">{club_name}</span>
        <span class="badge" style="background: #fef08a; color: #854d0e; margin-left: 6px;">Announcement</span>
      </div>
      
      <h2 style="font-size: 20px; margin-top: 0; color: #0f172a; line-height: 1.3;">{title}</h2>
      
      <div style="font-size: 12px; color: #64748b; margin-bottom: 16px;">
        Posted by <strong>{author_name}</strong>
      </div>
      
      <div class="card" style="background: #ffffff; border: 1px solid #e2e8f0; line-height: 1.7; font-size: 14px; color: #334155;">
        {formatted_content}
      </div>

      <div style="text-align: center; margin-top: 20px;">
        <a href="https://clubsync.vercel.app" class="btn">Open Club Feed →</a>
      </div>
    """
    text_content = f"Club Announcement for {club_name}:\n{title}\nBy: {author_name}\n\n{content}"
    send_email_in_background(
        to_emails,
        subject,
        _base_template("Club Announcement", body_html),
        text_content,
        is_bulk=True,
        club_name_header=club_name,
    )
