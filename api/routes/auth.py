"""
Auth routes — passwordless email-based authentication.

  POST /auth/register   — create account (sends verification email)
  POST /auth/login      — request magic link (sends login email)
  GET  /auth/verify     — verify token from email link
  GET  /auth/me         — get current logged-in user (from cookie)
  POST /auth/logout     — clear session cookie
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from core.auth_service import (
    generate_session_token,
    get_user_from_session_token,
    invalidate_session_token,
    register_user,
    request_login,
    resend_verification,
    verify_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_COOKIE = "smw_session"


def _get_current_user(request: Request) -> dict | None:
    """Extract current user from session cookie."""
    token = request.cookies.get(SESSION_COOKIE)
    return get_user_from_session_token(token)


@router.post("/register")
async def auth_register(request: Request):
    """Register a new account. Sends verification email."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    username = (body.get("username") or "").strip().lower()
    email = (body.get("email") or "").strip().lower()
    display_name = body.get("display_name")

    try:
        result = register_user(username, email, display_name)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    # Send verification email
    from core.email_service import is_configured, send_verification_email
    if is_configured():
        sent = send_verification_email(result["email"], result["username"], result["token"])
        if not sent:
            return JSONResponse({
                "error": "Account created but verification email failed to send. Contact the admin."
            }, status_code=500)
        return {"ok": True, "message": "Check your email for a verification link."}
    else:
        # SMTP not configured — return the token directly (dev mode)
        return {
            "ok": True,
            "message": "SMTP not configured — verify manually.",
            "dev_verify_url": f"/auth/verify?token={result['token']}",
        }


@router.post("/login")
async def auth_login(request: Request):
    """Request a magic login link via email."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    email = (body.get("email") or "").strip().lower()
    if not email:
        return JSONResponse({"error": "Email is required"}, status_code=400)

    result = request_login(email)
    if not result:
        # Don't reveal whether the email exists
        return {"ok": True, "message": "If an account exists with that email, a login link has been sent."}

    from core.email_service import is_configured, send_login_email
    if is_configured():
        sent = send_login_email(result["email"], result["username"], result["token"])
        if sent:
            return {"ok": True, "message": "Check your email for a login link."}
        else:
            return JSONResponse({"error": "Failed to send email. Check server logs."}, status_code=500)
    else:
        return {
            "ok": True,
            "message": "Email not configured — use link directly.",
            "dev_verify_url": f"/auth/verify?token={result['token']}",
        }


@router.post("/resend")
async def auth_resend(request: Request):
    """Resend verification email for an unverified account."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    email = (body.get("email") or "").strip().lower()
    if not email:
        return JSONResponse({"error": "Email is required"}, status_code=400)

    result = resend_verification(email)
    if not result:
        # Don't reveal whether the email exists or is already verified
        return {"ok": True, "message": "If an unverified account exists with that email, a new verification link has been sent."}

    from core.email_service import is_configured, send_verification_email
    if is_configured():
        send_verification_email(result["email"], result["username"], result["token"])
        return {"ok": True, "message": "A new verification link has been sent to your email."}
    else:
        return {
            "ok": True,
            "message": "SMTP not configured — use link directly.",
            "dev_verify_url": f"/auth/verify?token={result['token']}",
        }


@router.get("/verify")
async def auth_verify(request: Request, token: str = Query(...)):
    """Verify a token from a registration or login email.

    On success: sets session cookie and shows the welcome/API key page.
    """
    user = verify_token(token)
    if not user:
        return HTMLResponse(_error_page("Invalid or expired link",
            "This verification link has expired or was already used. "
            "Try logging in again to get a new link."), status_code=400)

    # Set session cookie
    session_token = generate_session_token(user["id"])
    response = HTMLResponse(_welcome_page(user))
    response.set_cookie(
        SESSION_COOKIE, session_token,
        httponly=True, samesite="lax", max_age=30 * 86400,  # 30 days
    )
    return response


@router.get("/me")
async def auth_me(request: Request):
    """Get current logged-in user info."""
    user = _get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user.get("display_name"),
        "email": user.get("email"),
    }


@router.get("/debug-smtp")
async def auth_debug_email(request: Request):
    """Debug endpoint — shows email config and user status. Admin only."""
    import os
    is_local = getattr(request.state, "is_local", False)
    admin_key = os.environ.get("SMW_ADMIN_KEY", "")
    if not is_local and request.query_params.get("admin_key") != admin_key:
        return JSONResponse({"error": "Admin only"}, status_code=403)

    from core.email_service import is_configured, _cfg
    from core import db
    c = _cfg()

    users = db.fetchall(
        "SELECT id, username, email, email_verified, verification_token IS NOT NULL AS has_token, created_at FROM users ORDER BY id"
    )

    return {
        "is_configured": is_configured(),
        "RESEND_API_KEY": "set" if c["api_key"] else "(empty)",
        "EMAIL_FROM": c["email_from"],
        "BASE_URL": c["base_url"],
        "users": users,
    }


@router.post("/logout")
async def auth_logout(request: Request):
    """Clear session cookie."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        invalidate_session_token(token)
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE)
    return response


# ── HTML page builders ──

def _welcome_page(user: dict) -> str:
    """Render the post-verification welcome page with API key."""
    return f"""<!DOCTYPE html>
<html lang="en"><head>
  <meta charset="utf-8">
  <title>Welcome — SMW Tracker</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="/static/css/app.css?v=2" rel="stylesheet">
</head><body>
  <div class="page">
    <header class="page-header">
      <h1>SMW://TRACKER</h1>
      <nav>
        <a href="/u/{user['username']}">My Profile</a>
        <a href="/live?user={user['id']}">Live</a>
      </nav>
    </header>
    <main>
      <section class="card" style="max-width:540px;margin:2rem auto;">
        <div class="card-title">Welcome, {user.get('display_name', user['username'])}!</div>
        <p>Your account is verified. Here's your API key — you'll need it to connect your SNES tracker.</p>

        <div style="background:#0d1117;border:1px solid #2a3544;border-radius:8px;padding:1rem;margin:1.5rem 0;position:relative;">
          <code id="api-key" style="color:#6dd5fa;font-size:0.95rem;word-break:break-all;">{user['api_key']}</code>
          <button onclick="navigator.clipboard.writeText(document.getElementById('api-key').textContent).then(()=>this.textContent='Copied!')"
                  style="position:absolute;top:0.5rem;right:0.5rem;background:#2a3544;color:#e2e8f0;border:none;border-radius:4px;padding:4px 10px;cursor:pointer;font-size:0.8rem;">
            Copy
          </button>
        </div>

        <p style="color:#7a8ba0;font-size:0.85rem;">Save this key somewhere safe. You'll use it to start the tracker:</p>
        <pre style="background:#0d1117;border:1px solid #2a3544;border-radius:8px;padding:1rem;overflow-x:auto;color:#e2e8f0;font-size:0.85rem;">python run_tracker.py --cloud --api-key {user['api_key']}</pre>

        <div style="margin-top:2rem;text-align:center;">
          <a href="/u/{user['username']}" class="btn" style="display:inline-block;background:#6dd5fa;color:#0d1117;padding:10px 28px;border-radius:6px;text-decoration:none;font-weight:600;">
            Go to your profile →
          </a>
        </div>
      </section>
    </main>
  </div>
</body></html>"""


def _error_page(title: str, message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head>
  <meta charset="utf-8">
  <title>{title} — SMW Tracker</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="/static/css/app.css?v=2" rel="stylesheet">
</head><body>
  <div class="page">
    <header class="page-header">
      <h1>SMW://TRACKER</h1>
      <nav><a href="/">Home</a></nav>
    </header>
    <main>
      <section class="card" style="max-width:480px;margin:2rem auto;text-align:center;">
        <div class="card-title" style="color:#f87171;">{title}</div>
        <p>{message}</p>
        <div style="margin-top:1.5rem;">
          <a href="/auth/page" class="btn" style="display:inline-block;background:#2a3544;color:#e2e8f0;padding:8px 20px;border-radius:6px;text-decoration:none;">
            Try again
          </a>
        </div>
      </section>
    </main>
  </div>
</body></html>"""
