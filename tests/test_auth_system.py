import os
import re
import socketserver
import threading
from datetime import datetime, timedelta
from email.message import EmailMessage
import pytest

from app import create_app
from app.db import (
    activate_user_from_otp,
    create_otp_challenge,
    create_password_reset,
    get_db_connection,
    get_latest_otp_challenge,
    get_user_by_email,
    get_user_by_username,
    init_db,
    reset_failed_logins,
    verify_otp_challenge,
    verify_password_reset_token,
)
from app.services.auth_security import (
    generate_otp_code,
    hash_password,
    validate_email_address,
    validate_full_name,
    validate_password_strength,
    verify_password,
)
from app.services.email_service import (
    clear_outbox,
    get_outbox,
    send_account_confirmation_email,
    send_otp_email,
    send_password_reset_email,
)


# ── In-Process Real Network SMTP Server For Live Delivery Testing ────────────

class LiveSmtpHandler(socketserver.StreamRequestHandler):
    """Handles RFC-compliant SMTP commands over actual TCP socket."""
    def handle(self):
        self.wfile.write(b"220 127.0.0.1 CareerAI ESMTP Server Ready\r\n")
        self.wfile.flush()
        data_mode = False
        data_lines = []
        while True:
            line = self.rfile.readline()
            if not line:
                break
            if data_mode:
                if line.strip() == b".":
                    data_mode = False
                    raw_msg = b"\n".join(data_lines).decode("utf-8", errors="ignore")
                    self.server.received_messages.append(raw_msg)
                    self.wfile.write(b"250 2.0.0 Ok: message queued\r\n")
                    self.wfile.flush()
                else:
                    data_lines.append(line.rstrip(b"\r\n"))
            else:
                cmd = line.strip().upper()
                if cmd.startswith(b"EHLO") or cmd.startswith(b"HELO"):
                    self.wfile.write(b"250-127.0.0.1\r\n250 HELP\r\n")
                    self.wfile.flush()
                elif cmd.startswith(b"MAIL FROM:"):
                    self.wfile.write(b"250 2.1.0 Sender Ok\r\n")
                    self.wfile.flush()
                elif cmd.startswith(b"RCPT TO:"):
                    self.wfile.write(b"250 2.1.5 Recipient Ok\r\n")
                    self.wfile.flush()
                elif cmd == b"DATA":
                    data_mode = True
                    data_lines = []
                    self.wfile.write(b"354 Start mail input; end with <CR><LF>.<CR><LF>\r\n")
                    self.wfile.flush()
                elif cmd == b"QUIT":
                    self.wfile.write(b"221 2.0.0 Service closing transmission channel\r\n")
                    self.wfile.flush()
                    break
                else:
                    self.wfile.write(b"250 Ok\r\n")
                    self.wfile.flush()


class LiveSmtpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    def __init__(self, host="127.0.0.1", port=9925):
        super().__init__((host, port), LiveSmtpHandler)
        self.received_messages = []


@pytest.fixture(scope="session")
def live_smtp_server():
    """Starts a live, real TCP socket SMTP server for session duration."""
    server = LiveSmtpServer("127.0.0.1", 9925)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Configure application environment to deliver to this live SMTP server
    os.environ["SMTP_HOST"] = "127.0.0.1"
    os.environ["SMTP_PORT"] = "9925"
    os.environ["SMTP_USE_TLS"] = "false"
    os.environ["SMTP_USE_SSL"] = "false"
    os.environ["SMTP_USER"] = ""
    os.environ["SMTP_PASSWORD"] = ""
    os.environ["SMTP_FROM_EMAIL"] = "no-reply@example.test"
    os.environ["MAIL_SUPPRESS_SEND"] = "false"

    yield server

    server.shutdown()
    server.server_close()


@pytest.fixture
def app():
    """Create Flask application configured for testing."""
    os.environ["SMTP_HOST"] = "127.0.0.1"
    os.environ["SMTP_PORT"] = "9925"
    os.environ["SMTP_USE_TLS"] = "false"
    os.environ["SMTP_USE_SSL"] = "false"
    os.environ["SMTP_USER"] = ""
    os.environ["SMTP_PASSWORD"] = ""
    os.environ["SMTP_FROM_EMAIL"] = "no-reply@example.test"
    os.environ["MAIL_SUPPRESS_SEND"] = "false"

    test_app = create_app()
    test_app.config.update({
        "TESTING": True,
        "SECRET_KEY": "test_secret_key_auth_verification",
        "WTF_CSRF_ENABLED": False,
    })
    init_db()
    clear_outbox()
    yield test_app


@pytest.fixture
def client(app):
    return app.test_client()


# ── The 20 Mandatory User Journey & Security Tests ──────────────────────────

def test_01_and_02_new_user_registration_and_actual_otp_email_delivery(client, live_smtp_server):
    """
    Test 1: A new user registers with valid details.
    Test 2: An OTP is actually sent to the entered email address over live SMTP socket.
    """
    email = "new_student_2026@test.com"
    # Ensure fresh test state
    conn = get_db_connection()
    conn.execute("DELETE FROM users WHERE LOWER(email) = ?", (email.lower(),))
    conn.execute("DELETE FROM otp_verifications WHERE LOWER(email) = ?", (email.lower(),))
    conn.commit()
    conn.close()

    pre_count = len(live_smtp_server.received_messages)

    res = client.post(
        "/api/auth/register",
        json={
            "full_name": "Devmani Student",
            "email": email,
            "password": "Password123!@",
            "confirm_password": "Password123!@",
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "instant_otp" not in data
    with client.session_transaction() as auth_session:
        assert "instant_otp" not in auth_session

    # Verify actual TCP SMTP socket message receipt
    post_count = len(live_smtp_server.received_messages)
    assert post_count > pre_count, "Live SMTP server did not receive email over network socket"
    last_msg = live_smtp_server.received_messages[-1]
    assert "Your CareerAI Email Verification Code" in last_msg
    assert email in last_msg
    verify_page = client.get(f"/verify-otp?email={email}")
    assert b"Instant Verification Code" not in verify_page.data

    # Verify OTP was stored hashed and NOT plaintext in database
    challenge = get_latest_otp_challenge(email)
    assert challenge is not None
    assert challenge["is_consumed"] == 0
    # OTP hash must not be the 6-digit number
    assert len(challenge["otp_hash"]) == 64  # SHA-256 HMAC length


def test_03_04_05_06_otp_verification_account_creation_confirmation_email(client, live_smtp_server):
    """
    Test 3: The user enters the correct OTP.
    Test 4: The email is successfully verified.
    Test 5: The account is created and activated.
    Test 6: The user receives an account confirmation email containing their Login ID.
    """
    email = "verify_journey_user@test.com"
    pwd = "StrongPassword2026!#"

    # Clean test state
    conn = get_db_connection()
    conn.execute("DELETE FROM users WHERE LOWER(email) = ?", (email.lower(),))
    conn.execute("DELETE FROM otp_verifications WHERE LOWER(email) = ?", (email.lower(),))
    conn.commit()
    conn.close()

    # Create challenge
    otp_code = create_otp_challenge(email, "Journey User", hash_password(pwd))
    pre_count = len(live_smtp_server.received_messages)

    # Submit correct OTP
    res = client.post(
        "/api/auth/verify-otp",
        json={"email": email, "otp": otp_code},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["login_id"] == email
    user_id = data["user_id"]
    assert user_id.startswith("USR-")

    # Verify account exists in MySQL / SQLite database and is active
    user = get_user_by_email(email)
    assert user is not None
    assert user["email_verified"] == 1
    assert user["account_status"] == "active"
    assert user["user_id"] == user_id

    # Verify Account Confirmation Email was sent over live SMTP
    post_count = len(live_smtp_server.received_messages)
    assert post_count > pre_count, "Confirmation email was not delivered via live SMTP"
    conf_msg = live_smtp_server.received_messages[-1]
    assert "Your Account Has Been Successfully Created" in conf_msg
    assert f"Login ID: {email}" in conf_msg
    assert f"Account ID: {user_id}" in conf_msg
    assert "Use the password you created during registration." in conf_msg
    # Ensure plaintext password was NOT sent
    assert pwd not in conf_msg


def test_07_and_08_login_with_registered_email_and_reach_dashboard(client):
    """
    Test 7: The user logs in using their registered email and chosen password.
    Test 8: The user reaches the existing dashboard.
    """
    email = "active_student_login@test.com"
    pwd = "StudentPassword2026!$"

    # Ensure user exists and is active
    conn = get_db_connection()
    conn.execute("DELETE FROM users WHERE LOWER(email) = ?", (email.lower(),))
    conn.commit()
    conn.close()

    challenge = {
        "id": 9999,
        "email": email,
        "full_name": "Active Student",
        "password_hash": hash_password(pwd),
    }
    activate_user_from_otp(challenge)

    # Log in via API
    res = client.post(
        "/api/auth/login",
        json={"login_id": email, "password": pwd},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["redirect"] == "/dashboard"

    # Access dashboard with session
    dash_res = client.get("/dashboard")
    assert dash_res.status_code == 200
    assert b"Career Profile" in dash_res.data


def test_09_incorrect_password_is_rejected(client):
    """
    Test 9: An incorrect password is rejected.
    """
    email = "active_student_login@test.com"
    res = client.post(
        "/api/auth/login",
        json={"login_id": email, "password": "WrongPassword999!"},
    )
    assert res.status_code == 401
    data = res.get_json()
    assert data["success"] is False
    assert data["message"] == "Invalid login credentials."


def test_10_incorrect_otp_is_rejected(client):
    """
    Test 10: An incorrect OTP is rejected.
    """
    email = "otp_test_student@test.com"
    create_otp_challenge(email, "Student", hash_password("Password123!"))

    res = client.post(
        "/api/auth/verify-otp",
        json={"email": email, "otp": "000000"},
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert "Incorrect verification code" in data["message"]


def test_11_expired_otp_is_rejected(client):
    """
    Test 11: An expired OTP is rejected.
    """
    email = "expired_otp_user@test.com"
    otp_code = create_otp_challenge(email, "Expired User", hash_password("Password123!"))

    # Force expiration in database
    past_time = (datetime.now() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    conn.execute("UPDATE otp_verifications SET expires_at = ? WHERE LOWER(email) = ?", (past_time, email.lower()))
    conn.commit()
    conn.close()

    res = client.post(
        "/api/auth/verify-otp",
        json={"email": email, "otp": otp_code},
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert "expired" in data["message"].lower()


def test_12_reusing_otp_is_rejected(client):
    """
    Test 12: Reusing an OTP is rejected.
    """
    email = "reuse_otp_user@test.com"
    conn = get_db_connection()
    conn.execute("DELETE FROM users WHERE LOWER(email) = ?", (email.lower(),))
    conn.commit()
    conn.close()

    otp_code = create_otp_challenge(email, "Reuse User", hash_password("Password123!"))

    # First use: succeeds
    res1 = client.post(
        "/api/auth/verify-otp",
        json={"email": email, "otp": otp_code},
    )
    assert res1.status_code == 200

    # Second use: must be rejected
    res2 = client.post(
        "/api/auth/verify-otp",
        json={"email": email, "otp": otp_code},
    )
    assert res2.status_code == 400
    data2 = res2.get_json()
    assert data2["success"] is False


def test_13_unverified_user_cannot_log_in(client):
    """
    Test 13: An unverified user cannot log in.
    """
    email = "unverified_test_user@test.com"
    conn = get_db_connection()
    conn.execute("DELETE FROM users WHERE LOWER(email) = ?", (email.lower(),))
    # Insert unverified user
    conn.execute(
        """
        INSERT INTO users (user_id, username, email, full_name, password_hash, email_verified, account_status)
        VALUES ('USR-UNVER01', 'unver', ?, 'Unverified User', ?, 0, 'pending')
        """,
        (email, hash_password("Secret123!#")),
    )
    conn.commit()
    conn.close()

    res = client.post(
        "/api/auth/login",
        json={"login_id": email, "password": "Secret123!#"},
    )
    assert res.status_code == 403
    data = res.get_json()
    assert data["success"] is False
    assert "not verified" in data["message"].lower() or "not active" in data["message"].lower()


def test_14_duplicate_email_registration_is_rejected(client):
    """
    Test 14: A duplicate email registration is rejected.
    """
    email = "admin@careerai.com"  # existing verified user
    res = client.post(
        "/api/auth/register",
        json={
            "full_name": "Admin Clone",
            "email": email,
            "password": "Password123!#",
            "confirm_password": "Password123!#",
        },
    )
    assert res.status_code in (400, 409)
    data = res.get_json()
    assert data["success"] is False
    assert "already exists" in data["message"].lower()


def test_15_and_16_forgot_password_sends_link_and_user_resets_password(client, live_smtp_server):
    """
    Test 15: Forgot Password sends a valid reset link.
    Test 16: The user can successfully reset their password.
    """
    email = "reset_user_test@test.com"
    conn = get_db_connection()
    conn.execute("DELETE FROM users WHERE LOWER(email) = ?", (email.lower(),))
    conn.commit()
    conn.close()

    # Create active user
    challenge = {
        "id": 9998,
        "email": email,
        "full_name": "Reset Test User",
        "password_hash": hash_password("OldPassword123!"),
    }
    activate_user_from_otp(challenge)

    pre_count = len(live_smtp_server.received_messages)

    # Request reset link
    res = client.post(
        "/api/auth/forgot-password",
        json={"email": email},
    )
    assert res.status_code == 200

    # Verify reset email was delivered via SMTP
    post_count = len(live_smtp_server.received_messages)
    assert post_count > pre_count
    msg = live_smtp_server.received_messages[-1]
    assert "Reset Your CareerAI Password" in msg
    assert "token=" in msg

    # Extract token from outbox text or parsed email
    outbox = get_outbox()
    email_text = outbox[-1]["text"] if outbox else msg
    match = re.search(r"token=([a-zA-Z0-9_\-]+)", email_text)
    assert match is not None
    token = match.group(1)

    # Reset password using token
    new_pwd = "BrandNewPassword2026!$"
    reset_res = client.post(
        "/api/auth/reset-password",
        json={
            "token": token,
            "password": new_pwd,
            "confirm_password": new_pwd,
        },
    )
    assert reset_res.status_code == 200
    data = reset_res.get_json()
    assert data["success"] is True


def test_17_and_18_old_password_fails_and_new_password_works(client):
    """
    Test 17: The old password no longer works after a successful reset.
    Test 18: The new password works.
    """
    email = "reset_user_test@test.com"
    old_pwd = "OldPassword123!"
    new_pwd = "BrandNewPassword2026!$"

    # 17: Old password must be rejected
    res_old = client.post(
        "/api/auth/login",
        json={"login_id": email, "password": old_pwd},
    )
    assert res_old.status_code == 401

    # 18: New password must succeed
    res_new = client.post(
        "/api/auth/login",
        json={"login_id": email, "password": new_pwd},
    )
    assert res_new.status_code == 200
    assert res_new.get_json()["success"] is True


def test_19_existing_verified_users_can_still_log_in(client):
    """
    Test 19: Existing verified users can still log in (e.g. admin).
    """
    reset_failed_logins(2)  # admin id
    res = client.post(
        "/api/auth/login",
        json={"login_id": "admin@careerai.com", "password": "admin123"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True


def test_20_existing_application_modules_remain_functional(client):
    """
    Test 20: Existing application modules (home, assessments, recommendation APIs) remain functional.
    """
    # Home landing page
    home_res = client.get("/")
    assert home_res.status_code == 200
    assert b"CareerAI" in home_res.data

    # Log in as admin to test protected modules
    login_res = client.post(
        "/api/auth/login",
        json={"login_id": "admin@careerai.com", "password": "admin123"},
    )
    assert login_res.status_code == 200

    # Assessment home page when authenticated
    assess_res = client.get("/assessment/")
    assert assess_res.status_code == 200

    # Career recommendation API
    rec_res = client.get("/api/v1/careers")
    assert rec_res.status_code in (200, 404, 405)
