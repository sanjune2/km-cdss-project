import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlencode, urlsplit


logger = logging.getLogger(__name__)


def invitation_link(token):
    public_url = os.getenv("HANUI_PUBLIC_URL", "").strip().rstrip("/")
    try:
        parts = urlsplit(public_url)
        if (parts.scheme not in ("https", "http") or not parts.hostname or parts.username
                or parts.password or parts.path or parts.query or parts.fragment):
            return None
    except ValueError:
        return None
    return f"{public_url}/staff/register?{urlencode({'token': token})}"


def send_staff_invitation(recipient, link):
    host = os.getenv("HANUI_SMTP_HOST", "").strip()
    if not host:
        return "not_configured"

    sender = os.getenv("HANUI_SMTP_FROM", "").strip()
    security = os.getenv("HANUI_SMTP_SECURITY", "starttls").strip().lower()
    username = os.getenv("HANUI_SMTP_USER", "")
    password = os.getenv("HANUI_SMTP_PASSWORD", "")
    if not link or not sender or security not in ("starttls", "ssl") or bool(username) != bool(password):
        logger.warning("Staff invitation email configuration is incomplete")
        return "failed"

    try:
        port = int(os.getenv("HANUI_SMTP_PORT", "465" if security == "ssl" else "587"))
        if not 1 <= port <= 65535:
            raise ValueError("Invalid SMTP port")
        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        message["Subject"] = "한의결 직원 가입 초대"
        message.set_content(
            "한의결 직원 계정 가입에 초대되었습니다.\n\n"
            f"가입 링크\n{link}\n\n"
            "초대 링크는 생성일로부터 7일간 유효합니다. "
            "가입 신청 후 원장 승인까지 완료되면 로그인할 수 있습니다.\n"
        )
        tls = ssl.create_default_context()
        client = (smtplib.SMTP_SSL(host, port, timeout=8, context=tls)
                  if security == "ssl" else smtplib.SMTP(host, port, timeout=8))
        with client:
            if security == "starttls":
                client.starttls(context=tls)
            if username:
                client.login(username, password)
            if client.send_message(message, to_addrs=[recipient]):
                return "failed"
    except (OSError, smtplib.SMTPException, ValueError) as error:
        logger.warning("Staff invitation email could not be sent (%s)", type(error).__name__)
        return "failed"
    return "sent"
