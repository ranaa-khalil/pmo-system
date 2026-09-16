"""Email service — sends emails via Resend API or SMTP fallback."""
import smtplib
import urllib.request
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings


def _send_via_resend(to_email: str, subject: str, html_body: str, text_body: str = "") -> bool:
    """Send email via Resend REST API."""
    if not settings.resend_api_key:
        return False
    payload = {
        "from": settings.email_from or "PMO System <onboarding@resend.dev>",
        "to": [to_email],
        "subject": subject,
        "html": html_body,
    }
    if text_body:
        payload["text"] = text_body
    try:
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 201)
    except Exception as e:
        print(f"[email] Resend failed: {e}")
        return False


def _send_via_smtp(to_email: str, subject: str, html_body: str, text_body: str = "") -> bool:
    """Send email via SMTP."""
    if not settings.smtp_host or not settings.smtp_user:
        return False
    msg = MIMEMultipart("alternative")
    msg["From"] = settings.email_from
    msg["To"] = to_email
    msg["Subject"] = subject
    if text_body:
        msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    try:
        if settings.smtp_port == 465:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
            server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.email_from, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"[email] SMTP failed: {e}")
        return False


def send_email(to_email: str, subject: str, html_body: str, text_body: str = "") -> bool:
    """Send an email. Tries Resend first, falls back to SMTP."""
    if _send_via_resend(to_email, subject, html_body, text_body):
        return True
    if _send_via_smtp(to_email, subject, html_body, text_body):
        return True
    return False


def send_password_reset_email(to_email: str, reset_token: str, user_name: str = "") -> bool:
    """Send a password reset email with a reset link."""
    reset_url = f"{settings.app_url}/?reset_token={reset_token}"

    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px;">
        <div style="text-align: center; margin-bottom: 32px;">
            <div style="display: inline-block; width: 48px; height: 48px; background: #7c3aed; border-radius: 12px; line-height: 48px; text-align: center; vertical-align: middle;">
                <span style="font-size: 24px; color: white; font-weight: bold;">P</span>
            </div>
            <h1 style="font-size: 20px; color: #1a1a2e; margin: 16px 0 0 0;">PMO System</h1>
        </div>

        <div style="background: white; border: 1px solid #e5e7eb; border-radius: 16px; padding: 32px;">
            <h2 style="font-size: 18px; color: #1a1a2e; margin: 0 0 8px 0;">Reset Your Password</h2>
            <p style="font-size: 14px; color: #6b7280; line-height: 1.6; margin: 0 0 24px 0;">
                {"Hi " + user_name + "," if user_name else "Hello,"}<br><br>
                We received a request to reset your password for your PMO System account.
                Click the button below to set a new password. This link will expire in 1 hour.
            </p>

            <div style="text-align: center; margin: 32px 0;">
                <a href="{reset_url}"
                   style="display: inline-block; background: #7c3aed; color: white; font-size: 14px; font-weight: 600;
                          text-decoration: none; padding: 12px 32px; border-radius: 10px;">
                    Reset Password
                </a>
            </div>

            <p style="font-size: 13px; color: #9ca3af; line-height: 1.6; margin: 0;">
                If the button doesn't work, copy and paste this link into your browser:<br>
                <a href="{reset_url}" style="color: #7c3aed; word-break: break-all;">{reset_url}</a>
            </p>

            <hr style="border: none; border-top: 1px solid #f3f4f6; margin: 24px 0;">

            <p style="font-size: 12px; color: #9ca3af; line-height: 1.6; margin: 0;">
                If you didn't request a password reset, you can safely ignore this email.
                Your password will not be changed.
            </p>
        </div>

        <p style="font-size: 11px; color: #d1d5db; text-align: center; margin-top: 24px;">
            PMO System &middot; This is an automated email, please do not reply.
        </p>
    </div>
    """

    text = f"""
PMO System - Reset Your Password

{"Hi " + user_name + "," if user_name else "Hello,"}

We received a request to reset your password for your PMO System account.
Click the link below to set a new password. This link will expire in 1 hour.

{reset_url}

If you didn't request a password reset, you can safely ignore this email.
Your password will not be changed.
"""

    return send_email(to_email, "PMO System - Reset Your Password", html, text)
