"""
Email service — sends emails via Resend API (HTTPS).

Environment variables:
  RESEND_API_KEY  — API key from resend.com (required)
  EMAIL_FROM      — From address (default: SMW Tracker <noreply@smwtracker.com>)
  BASE_URL        — Public URL of the site (default: https://smwtracker.com)
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
DEFAULT_FROM = "SMW Tracker <noreply@smwtracker.com>"


def _cfg():
    """Read config from environment at call time."""
    return {
        "api_key": os.environ.get("RESEND_API_KEY", ""),
        "email_from": os.environ.get("EMAIL_FROM", "") or DEFAULT_FROM,
        "base_url": os.environ.get("BASE_URL", "https://smwtracker.com").rstrip("/"),
    }


def is_configured() -> bool:
    """Check if Resend is configured."""
    return bool(_cfg()["api_key"])


def send_email(to: str, subject: str, html_body: str) -> bool:
    """Send an HTML email via Resend API. Returns True on success."""
    c = _cfg()
    if not c["api_key"]:
        log.warning("RESEND_API_KEY not set — cannot send email to %s", to)
        return False

    try:
        resp = requests.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {c['api_key']}",
                "Content-Type": "application/json",
            },
            json={
                "from": c["email_from"],
                "to": [to],
                "subject": subject,
                "html": html_body,
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            log.info("Email sent to %s: %s", to, subject)
            return True
        else:
            log.error("Resend API error %s: %s", resp.status_code, resp.text[:300])
            return False
    except Exception as exc:
        log.error("Resend request failed for %s: %s", to, exc)
        return False


# ── Email templates ──

def send_verification_email(to: str, username: str, token: str) -> bool:
    """Send account verification email."""
    base_url = _cfg()["base_url"]
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
    base_url = _cfg()["base_url"]
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
