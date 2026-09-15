"""Email service — send transactional emails.

Uses SMTP for sending (synchronous for MVP, can be upgraded to async queue).
Templates are plain-text/HTML strings rendered with Python's string.Template.

Configure via env vars:
  PMO_SMTP_HOST, PMO_SMTP_PORT, PMO_SMTP_USER, PMO_SMTP_PASSWORD, PMO_EMAIL_FROM

If SMTP is not configured, emails are logged but not sent (dev mode).
"""
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from string import Template

from app.config import settings

logger = logging.getLogger("app.email")

# ─── Email Templates ─────────────────────────────────────────

WELCOME_TEMPLATE = """
Welcome to PMO System, $name!

Your account has been created successfully.
You are now the owner of the "$tenant_name" workspace.

Get started by:
1. Create your first project
2. Invite team members
3. Set up your backlog

If you have any questions, feel free to reach out.

— PMO System Team
"""

INVITATION_TEMPLATE = """
You've been invited to join "$tenant_name" on PMO System!

$name has invited you to join their workspace as a $role.

To accept the invitation, click the link below:
$url/accept-invite?token=$token

This invitation expires in 7 days.

— PMO System Team
"""

APPROVAL_NOTIFICATION_TEMPLATE = """
Approval Request: $title

$requester_name has requested approval for: $title

Project: $project_name
Phase: $phase

Please review and approve or reject this request in the PMO System.

— PMO System Team
"""


class EmailService:
    """Send transactional emails via SMTP."""

    def __init__(self):
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.user = settings.smtp_user
        self.password = settings.smtp_password
        self.from_addr = settings.email_from or "noreply@pmosystem.app"

    @property
    def is_configured(self) -> bool:
        return bool(self.host and self.user)

    def send(self, to: str, subject: str, body: str, html: str = None):
        """Send an email. Logs if SMTP is not configured."""
        if not self.is_configured:
            logger.info(f"[EMAIL-DEV] To: {to} | Subject: {subject} | Body: {body[:200]}")
            return False

        msg = MIMEMultipart("alternative")
        msg["From"] = self.from_addr
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        if html:
            msg.attach(MIMEText(html, "html"))

        try:
            with smtplib.SMTP(self.host, self.port) as server:
                server.starttls()
                server.login(self.user, self.password)
                server.sendmail(self.from_addr, [to], msg.as_string())
            logger.info(f"Email sent to {to}: {subject}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to}: {e}")
            return False

    def send_welcome(self, to: str, name: str, tenant_name: str):
        """Send a welcome email to a new user."""
        body = Template(WELCOME_TEMPLATE).safe_substitute(
            name=name, tenant_name=tenant_name
        )
        self.send(to, f"Welcome to PMO System — {tenant_name}", body)

    def send_invitation(self, to: str, inviter_name: str, tenant_name: str, role: str, token: str, base_url: str = ""):
        """Send an invitation email."""
        url = base_url or "http://localhost:8000"
        body = Template(INVITATION_TEMPLATE).safe_substitute(
            tenant_name=tenant_name,
            name=inviter_name,
            role=role,
            url=url,
            token=token,
        )
        self.send(to, f"You're invited to join {tenant_name} on PMO System", body)

    def send_approval_notification(self, to: str, requester_name: str, title: str, project_name: str, phase: str):
        """Send an approval request notification."""
        body = Template(APPROVAL_NOTIFICATION_TEMPLATE).safe_substitute(
            requester_name=requester_name,
            title=title,
            project_name=project_name,
            phase=phase,
        )
        self.send(to, f"Approval Request: {title}", body)


# Singleton
email_service = EmailService()
