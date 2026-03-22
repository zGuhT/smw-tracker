"""
Email service — sends verification and magic link emails via SMTP.

Configure via environment variables:
  SMTP_HOST     — SMTP server (e.g. smtp.gmail.com)
  SMTP_PORT     — SMTP port (default 587 for TLS)
  SMTP_USER     — SMTP username (usually your email)
  SMTP_PASS     — SMTP password or app password
  SMTP_FROM     — From address (defaults to SMTP_USER)
  BASE_URL      — Public URL of the site (e.g. https://smwtracker.com)
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger(__name__)


def _cfg():
    """Read SMTP config from environment at call time (not import time)."""
    host = os.environ.get("SMTP_HOST", "")
    user = os.environ.get("SMTP_USER", "")
    pwd = os.environ.get("SMTP_PASS", "")
    port = int(os.environ.get("SMTP_PORT", "587"))
    from_addr = os.environ.get("SMTP_FROM", "") or user
    base_url = os.environ.get("BASE_URL", "https://smwtracker.com").rstrip("/")
    return host, port, user, pwd, from_addr, base_url


def is_configured() -> bool:
    """Check if SMTP is configured."""
    host, _, user, pwd, _, _ = _cfg()
    return bool(host and user and pwd)


def send_email(to: str, subject: str, html_body: str) -> bool:
    """Send an HTML email. Returns True on success."""
    host, port, user, pwd, from_addr, _ = _cfg()
    if not (host and user and pwd):
        log.warning("SMTP not configured — cannot send email to %s (SMTP_HOST=%r, SMTP_USER=%r, SMTP_PASS=%s)",
                     to, host, user, "set" if pwd else "empty")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls()
            server.login(user, pwd)
            server.send_message(msg)
        log.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as exc:
        log.error("Failed to send email to %s: %s", to, exc)
        return False


def send_verification_email(to: str, username: str, token: str) -> bool:
    """Send account verification email with a link."""
    _, _, _, _, _, base_url = _cfg()
    verify_url = f"{base_url}/auth/verify?token={token}"
    subject = "SMW Tracker — Verify your account"
    html = f"""
    <div style="font-family: system-ui, sans-serif; max-width: 480px; margin: 0 auto; padding: 2rem;">
      <h2 style="color: #6dd5fa;">SMW://TRACKER</h2>
      <p>Hey <strong>{username}</strong>,</p>
      <p>Click below to verify your account and get your API key:</p>
      <p style="text-align: center; margin: 2rem 0;">
        <a href="{verify_url}"
           style="background: #6dd5fa; color: #0d1117; padding: 12px 32px;
                  text-decoration: none; border-radius: 6px; font-weight: 600;
                  display: inline-block;">
          Verify Account
        </a>
      </p>
      <p style="color: #7a8ba0; font-size: 0.85rem;">
        Or copy this link: <a href="{verify_url}" style="color: #6dd5fa;">{verify_url}</a>
      </p>
      <p style="color: #7a8ba0; font-size: 0.85rem;">This link expires in 24 hours.</p>
    </div>
    """
    return send_email(to, subject, html)


def send_login_email(to: str, username: str, token: str) -> bool:
    """Send magic login link email."""
    _, _, _, _, _, base_url = _cfg()
    login_url = f"{base_url}/auth/verify?token={token}"
    subject = "SMW Tracker — Your login link"
    html = f"""
    <div style="font-family: system-ui, sans-serif; max-width: 480px; margin: 0 auto; padding: 2rem;">
      <h2 style="color: #6dd5fa;">SMW://TRACKER</h2>
      <p>Hey <strong>{username}</strong>,</p>
      <p>Click below to log in and view your API key:</p>
      <p style="text-align: center; margin: 2rem 0;">
        <a href="{login_url}"
           style="background: #6dd5fa; color: #0d1117; padding: 12px 32px;
                  text-decoration: none; border-radius: 6px; font-weight: 600;
                  display: inline-block;">
          Log In
        </a>
      </p>
      <p style="color: #7a8ba0; font-size: 0.85rem;">
        Or copy this link: <a href="{login_url}" style="color: #6dd5fa;">{login_url}</a>
      </p>
      <p style="color: #7a8ba0; font-size: 0.85rem;">This link expires in 1 hour.</p>
    </div>
    """
    return send_email(to, subject, html)
