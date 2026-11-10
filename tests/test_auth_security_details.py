from datetime import datetime, timedelta
import pytest

from app import create_app
from app.db import (
    activate_user_from_otp,
    create_otp_challenge,
    get_db_connection,
    get_latest_otp_challenge,
    init_db,
    resend_otp_challenge,
    verify_otp_challenge,
)
from app.services.auth_security import (
    generate_otp_code,
    hash_otp_code,
    hash_password,
    validate_email_address,
    validate_full_name,
    validate_password_strength,
    verify_otp_code,
    verify_password,
)


@pytest.fixture
def app():
    test_app = create_app()
    test_app.config.update({"TESTING": True, "WTF_CSRF_ENABLED": False})
    init_db()
    yield test_app


@pytest.fixture
def client(app):
    return app.test_client()


def test_password_policy_validation():
    """Verify strong password policy rules."""
    # Too short
    valid, err = validate_password_strength("Short1!")
    assert not valid
    assert "at least 8 characters" in err

    # No lowercase
    valid, err = validate_password_strength("NOLOWER123!@")
    assert not valid
    assert "lowercase" in err

    # No uppercase
    valid, err = validate_password_strength("noupper123!@")
    assert not valid
    assert "uppercase" in err

    # No digit
    valid, err = validate_password_strength("NoDigitsHere!@")
    assert not valid
    assert "number" in err

    # No special character
    valid, err = validate_password_strength("NoSpecialChar123")
    assert not valid
    assert "special character" in err

    # Valid password
    valid, err = validate_password_strength("SecurePassword2026!@")
    assert valid
    assert err is None


def test_email_validation():
    """Verify RFC email validation."""
    valid, err = validate_email_address("invalid-email")
    assert not valid

    valid, err = validate_email_address("student@domain.co")
    assert valid


def test_full_name_validation():
    """Verify full name validation."""
    valid, err = validate_full_name("A")
    assert not valid
    assert "at least 2 characters" in err

    valid, err = validate_full_name("Dr. Devmani Jada-Smith")
    assert valid


def test_otp_cooldown_60_seconds(client):
    """Verify that requesting resend OTP enforces 60-second cooldown."""
    email = "cooldown_test@example.com"
    create_otp_challenge(email, "Cooldown User", hash_password("ValidPass123!@"))

    # Immediate resend attempt should fail with cooldown remaining
    success, msg, new_otp, cooldown_left = resend_otp_challenge(email)
    assert not success
    assert cooldown_left > 0
    assert "wait" in msg.lower()

    # Fast forward last_sent_at by 65 seconds
    conn = get_db_connection()
    past_time = (datetime.now() - timedelta(seconds=65)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE otp_verifications SET last_sent_at = ? WHERE LOWER(email) = ?", (past_time, email.lower()))
    conn.commit()
    conn.close()

    # Now resend should succeed and issue a new OTP
    success2, msg2, new_otp2, cooldown_left2 = resend_otp_challenge(email)
    assert success2
    assert new_otp2 is not None
    assert len(new_otp2) == 6


def test_otp_max_five_attempts(client):
    """Verify challenge invalidation after 5 incorrect verification attempts."""
    email = "attempts_limit@example.com"
    create_otp_challenge(email, "Attempt User", hash_password("ValidPass123!@"))

    # Attempt 1 through 4 incorrect
    for i in range(1, 5):
        valid, reason, challenge = verify_otp_challenge(email, "000000")
        assert not valid
        assert reason == "invalid_otp"
        assert challenge["attempts"] == i

    # Attempt 5: triggers maximum exceeded
    valid5, reason5, challenge5 = verify_otp_challenge(email, "000000")
    assert not valid5
    assert challenge5["attempts"] == 5

    # Attempt 6: challenge is locked / max attempts exceeded
    valid6, reason6, challenge6 = verify_otp_challenge(email, "000000")
    assert not valid6
    assert reason6 == "max_attempts_exceeded"


def test_html_form_post_fallback(client, monkeypatch):
    """Verify traditional HTML form POST submissions for clients without JavaScript."""
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    email = "html_form_user@example.com"
    conn = get_db_connection()
    conn.execute("DELETE FROM users WHERE LOWER(email) = ?", (email.lower(),))
    conn.execute("DELETE FROM otp_verifications WHERE LOWER(email) = ?", (email.lower(),))
    conn.commit()
    conn.close()

    # 1. HTML Form Register POST
    res_reg = client.post(
        "/register",
        data={
            "full_name": "HTML Fallback",
            "email": email,
            "password": "Password123!@",
            "confirm_password": "Password123!@",
        },
        follow_redirects=False,
    )
    assert res_reg.status_code == 302
    assert "verify-otp" in res_reg.location

    # Get generated OTP
    challenge = get_latest_otp_challenge(email)
    assert challenge is not None
    # We can fetch the plaintext OTP from memory or verify with DB
    # Let's verify OTP form POST with an incorrect OTP first
    res_fail = client.post(
        "/verify-otp",
        data={"email": email, "otp": "999999"},
        follow_redirects=True,
    )
    assert b"Incorrect verification code" in res_fail.data

    # Generate a known OTP challenge
    correct_otp = create_otp_challenge(email, "HTML Fallback", hash_password("Password123!@"))
    res_ok = client.post(
        "/verify-otp",
        data={"email": email, "otp": correct_otp},
        follow_redirects=False,
    )
    assert res_ok.status_code == 302
    assert "registration-success" in res_ok.location

    # Verify HTML Login form POST
    res_login = client.post(
        "/login",
        data={"login_id": email, "password": "Password123!@"},
        follow_redirects=False,
    )
    assert res_login.status_code == 302
    assert "dashboard" in res_login.location
