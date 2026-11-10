import os
import smtplib
from email.message import EmailMessage
from typing import Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()


class EmailDeliveryError(Exception):
    """Raised when email delivery fails."""
    pass


# Global in-memory outbox for test verification and audit
_outbox: List[Dict] = []


def get_outbox() -> List[Dict]:
    """Retrieve all delivered emails in current process (for test assertions)."""
    return _outbox


def clear_outbox():
    """Clear test outbox."""
    _outbox.clear()


def get_smtp_config():
    """Retrieve SMTP configuration from environment variables."""
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").replace(" ", "").strip()
    # Treat placeholder strings as unconfigured
    if any(value in password.lower() for value in ("replace_with", "your_gmail_app_password", "yourgmail", "your_email")):
        user = ""
        password = ""

    return {
        "host": os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": user,
        "password": password,
        "use_tls": os.environ.get("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes"),
        "use_ssl": os.environ.get("SMTP_USE_SSL", "false").lower() in ("1", "true", "yes"),
        "from_email": os.environ.get("SMTP_FROM_EMAIL", user or "no-reply@careerai.com"),
        "from_name": os.environ.get("SMTP_FROM_NAME", "Career Recommendation System Team"),
        "base_url": os.environ.get("APP_BASE_URL", "http://localhost:5000").rstrip("/"),
        "suppress_send": os.environ.get("MAIL_SUPPRESS_SEND", "false").lower() in ("1", "true", "yes"),
    }


def send_email(to_email: str, subject: str, text_content: str, html_content: Optional[str] = None) -> bool:
    """
    Send an email via SMTP using configured credentials.
    Also appends to the in-memory outbox for verification.
    """
    config = get_smtp_config()
    sender = f"{config['from_name']} <{config['from_email']}>"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content(text_content)

    if html_content:
        msg.add_alternative(html_content, subtype="html")

    # If send is suppressed (e.g. in test mode without local SMTP daemon running)
    if config["suppress_send"]:
        _outbox.append({
            "to": to_email,
            "from": sender,
            "subject": subject,
            "text": text_content,
            "html": html_content,
            "headers": dict(msg.items()),
        })
        return True

    is_gmail_smtp = config["host"].lower() == "smtp.gmail.com"
    if is_gmail_smtp and (not config["user"] or not config["password"]):
        raise EmailDeliveryError(
            "The app's Gmail sender is not configured. Set SMTP_USER to the sender Gmail "
            "address and SMTP_PASSWORD to its Google App Password."
        )

    try:
        if config["use_ssl"]:
            with smtplib.SMTP_SSL(config["host"], config["port"], timeout=10) as server:
                if config["user"] and config["password"]:
                    server.login(config["user"], config["password"])
                server.send_message(msg)
        else:
            with smtplib.SMTP(config["host"], config["port"], timeout=10) as server:
                if config["use_tls"]:
                    server.starttls()
                if config["user"] and config["password"]:
                    server.login(config["user"], config["password"])
                server.send_message(msg)
        _outbox.append({
            "to": to_email,
            "from": sender,
            "subject": subject,
            "text": text_content,
            "html": html_content,
            "headers": dict(msg.items()),
        })
        return True
    except Exception as exc:
        raise EmailDeliveryError(f"Failed to send email to {to_email}: {str(exc)}") from exc


def send_otp_email(to_email: str, full_name: str, otp_code: str) -> bool:
    """
    Send 6-digit email verification OTP.
    OTP validity: 5 minutes.
    """
    subject = "Your CareerAI Email Verification Code"

    text_content = f"""Hello {full_name},

Thank you for registering with the AI-Based Career Recommendation System!

Your 6-digit email verification code is:

    {otp_code}

This code is valid for 5 minutes.
For security, do not share this code with anyone.
If you did not request this verification, please disregard this message.

Regards,
Career Recommendation System Team
"""

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f2f5f3; color: #1c2e2a; padding: 24px; margin: 0; }}
    .container {{ max-width: 560px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #d6e3df; overflow: hidden; }}
    .header {{ background: #0f6b5e; color: #ffffff; padding: 24px; text-align: center; }}
    .header h1 {{ margin: 0; font-size: 20px; font-weight: 600; }}
    .body {{ padding: 32px 24px; }}
    .otp-badge {{ display: inline-block; background: #e4f2ef; color: #0f6b5e; font-size: 32px; font-weight: 700; letter-spacing: 6px; padding: 12px 24px; border-radius: 6px; margin: 20px 0; border: 1px solid #1a8572; }}
    .footer {{ font-size: 13px; color: #5a6f6a; border-top: 1px solid #e8f0ec; padding: 16px 24px; text-align: center; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>AI-Based Career Recommendation System</h1>
    </div>
    <div class="body">
      <p>Hello <strong>{full_name}</strong>,</p>
      <p>Thank you for registering. Please enter the following 6-digit verification code to verify your email address and activate your account:</p>
      <div style="text-align: center;">
        <span class="otp-badge">{otp_code}</span>
      </div>
      <p style="color: #c4614a; font-size: 14px;"><strong>Note:</strong> This verification code is valid for <strong>5 minutes</strong>. Maximum 5 verification attempts are allowed per code.</p>
      <p>If you did not attempt to register, please ignore this email.</p>
    </div>
    <div class="footer">
      Regards,<br><strong>Career Recommendation System Team</strong>
    </div>
  </div>
</body>
</html>"""

    return send_email(to_email, subject, text_content, html_content)


def send_account_confirmation_email(to_email: str, full_name: str, user_id: str, login_url: Optional[str] = None) -> bool:
    """
    Send official Account Confirmation Email With Login Details.
    Strictly adheres to Requirement Section 4 specification.
    """
    config = get_smtp_config()
    if not login_url:
        login_url = f"{config['base_url']}/login"

    subject = "Your Account Has Been Successfully Created"

    text_content = f"""Hello {full_name},

Welcome to the AI-Based Career Recommendation System!

Your registration and email verification have been completed successfully. Your account is now active.

Your Login Details:

Login ID: {to_email}

Account ID: {user_id}

Password: Use the password you created during registration.

You can now log in to your account using your registered email address and password.

Login Here: {login_url}

Keep your login credentials confidential and do not share your password with anyone.

Thank you for registering with us!

Regards,
Career Recommendation System Team
"""

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f2f5f3; color: #1c2e2a; padding: 24px; margin: 0; }}
    .container {{ max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #d6e3df; overflow: hidden; }}
    .header {{ background: #0f6b5e; color: #ffffff; padding: 24px; }}
    .header h1 {{ margin: 0; font-size: 20px; font-weight: 600; }}
    .body {{ padding: 32px 28px; line-height: 1.6; font-size: 15px; }}
    .card {{ background: #f0f7f5; border: 1px solid #d6e3df; border-radius: 6px; padding: 18px 20px; margin: 20px 0; }}
    .card p {{ margin: 6px 0; }}
    .btn {{ display: inline-block; background: #0f6b5e; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 6px; font-weight: 600; margin-top: 10px; }}
    .warning {{ background: #fdf5e4; border-left: 4px solid #b38b3e; padding: 12px 16px; margin: 20px 0; font-size: 13.5px; }}
    .footer {{ font-size: 13px; color: #5a6f6a; border-top: 1px solid #e8f0ec; padding: 16px 28px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>AI-Based Career Recommendation System</h1>
    </div>
    <div class="body">
      <p>Hello <strong>{full_name}</strong>,</p>
      <p>Welcome to the AI-Based Career Recommendation System!</p>
      <p>Your registration and email verification have been completed successfully. Your account is now active.</p>

      <div class="card">
        <h3 style="margin-top: 0; color: #094d43;">Your Login Details:</h3>
        <p><strong>Login ID:</strong> {to_email}</p>
        <p><strong>Account ID:</strong> {user_id}</p>
        <p><strong>Password:</strong> Use the password you created during registration.</p>
      </div>

      <p>You can now log in to your account using your registered email address and password.</p>
      <p style="text-align: center; margin: 24px 0;">
        <a href="{login_url}" class="btn" style="color: #ffffff;">Log In to Your Account &rarr;</a>
      </p>

      <div class="warning">
        Keep your login credentials confidential and do not share your password with anyone.
      </div>

      <p>Thank you for registering with us!</p>
    </div>
    <div class="footer">
      Regards,<br>
      <strong>Career Recommendation System Team</strong>
    </div>
  </div>
</body>
</html>"""

    return send_email(to_email, subject, text_content, html_content)


def send_password_reset_email(to_email: str, full_name: str, reset_url: str) -> bool:
    """
    Send single-use password reset link.
    Validity: 15 minutes.
    """
    subject = "Reset Your CareerAI Password"

    text_content = f"""Hello {full_name},

We received a request to reset the password for your CareerAI account associated with this email.

To set a new password, click or paste the following link into your browser:

{reset_url}

This link is valid for 15 minutes and can only be used once.

If you did not request a password reset, you can safely ignore this email. Your existing password will remain active and secure.

Regards,
Career Recommendation System Team
"""

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f2f5f3; color: #1c2e2a; padding: 24px; margin: 0; }}
    .container {{ max-width: 560px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #d6e3df; overflow: hidden; }}
    .header {{ background: #0f6b5e; color: #ffffff; padding: 24px; text-align: center; }}
    .header h1 {{ margin: 0; font-size: 20px; font-weight: 600; }}
    .body {{ padding: 32px 24px; }}
    .btn {{ display: inline-block; background: #0f6b5e; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 6px; font-weight: 600; margin: 16px 0; }}
    .footer {{ font-size: 13px; color: #5a6f6a; border-top: 1px solid #e8f0ec; padding: 16px 24px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>AI-Based Career Recommendation System</h1>
    </div>
    <div class="body">
      <p>Hello <strong>{full_name}</strong>,</p>
      <p>We received a request to reset your password. Click the button below to choose a new password:</p>
      <div style="text-align: center;">
        <a href="{reset_url}" class="btn" style="color: #ffffff;">Reset Password &rarr;</a>
      </div>
      <p style="font-size: 13px; color: #5a6f6a;">Or copy this URL into your browser:<br><span style="word-break: break-all;">{reset_url}</span></p>
      <p style="color: #c4614a; font-size: 13px;">This link will expire in <strong>15 minutes</strong> and can only be used once.</p>
      <p>If you did not request this change, please ignore this email.</p>
    </div>
    <div class="footer">
      Regards,<br><strong>Career Recommendation System Team</strong>
    </div>
  </div>
</body>
</html>"""

    return send_email(to_email, subject, text_content, html_content)
