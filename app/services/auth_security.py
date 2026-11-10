import hashlib
import hmac
import os
import re
import secrets
import time
from typing import Optional, Tuple
import bcrypt
from werkzeug.security import check_password_hash as werkzeug_check_hash


# Secret pepper used for HMAC-SHA256 of OTPs and reset tokens to prevent rainbow table attacks
SECRET_PEPPER = os.environ.get("AUTH_SECRET_PEPPER") or secrets.token_hex(32)
SECRET_PEPPER = SECRET_PEPPER.encode("utf-8")


def hash_password(password: str) -> str:
    """Hash password using bcrypt with salt."""
    if not password or not isinstance(password, str):
        raise ValueError("Password must be a non-empty string.")
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(password: str, stored_hash: str) -> bool:
    """
    Verify password against stored hash.
    Supports both bcrypt hashes ($2b$, $2a$, $2y$) and legacy Werkzeug hashes (scrypt/pbkdf2).
    """
    if not password or not stored_hash:
        return False

    # Check bcrypt hash format
    if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
        except Exception:
            return False

    # Fallback for existing legacy werkzeug hashes (e.g. existing admin user)
    try:
        return werkzeug_check_hash(stored_hash, password)
    except Exception:
        return False


def needs_password_rehash(stored_hash: str) -> bool:
    """Check if legacy password hash should be upgraded to bcrypt."""
    return not stored_hash.startswith(("$2a$", "$2b$", "$2y$"))


def validate_password_strength(password: str) -> Tuple[bool, Optional[str]]:
    """
    Enforce strong password policy:
    - At least 8 characters
    - At least 1 lowercase letter
    - At least 1 uppercase letter
    - At least 1 numeric digit
    - At least 1 special character
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if len(password) > 128:
        return False, "Password cannot exceed 128 characters."
    if not re.search(r"[a-z]", password):
        return False, "Password must include at least one lowercase letter."
    if not re.search(r"[A-Z]", password):
        return False, "Password must include at least one uppercase letter."
    if not re.search(r"\d", password):
        return False, "Password must include at least one number."
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{}|;:'\",.<>/?`~]", password):
        return False, "Password must include at least one special character."
    return True, None


def validate_email_address(email: str) -> Tuple[bool, Optional[str]]:
    """Validate email address format and length."""
    if not email or not isinstance(email, str):
        return False, "Email address is required."
    email = email.strip()
    if len(email) > 255:
        return False, "Email address cannot exceed 255 characters."
    # RFC 5322 simplified pattern
    email_regex = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    if not re.match(email_regex, email):
        return False, "Please provide a valid email address."
    return True, None


def validate_full_name(name: str) -> Tuple[bool, Optional[str]]:
    """Validate full name."""
    if not name or not isinstance(name, str):
        return False, "Full name is required."
    name = name.strip()
    if len(name) < 2:
        return False, "Full name must be at least 2 characters long."
    if len(name) > 100:
        return False, "Full name cannot exceed 100 characters."
    if not re.match(r"^[a-zA-Z\s'.\-]+$", name):
        return False, "Full name contains invalid characters."
    return True, None


def generate_otp_code() -> str:
    """Generate a cryptographically secure 6-digit numeric OTP."""
    # secrets.randbelow(900000) generates integer in [0, 899999]
    return f"{100000 + secrets.randbelow(900000)}"


def hash_otp_code(otp_code: str) -> str:
    """
    Hash OTP code using HMAC-SHA256 with server pepper.
    Never store OTP in plaintext in the database.
    """
    return hmac.new(SECRET_PEPPER, otp_code.strip().encode("utf-8"), hashlib.sha256).hexdigest()


def verify_otp_code(entered_otp: str, stored_hash: str) -> bool:
    """Verify an entered OTP against stored HMAC-SHA256 hash using constant-time comparison."""
    if not entered_otp or not stored_hash:
        return False
    computed_hash = hash_otp_code(entered_otp)
    return hmac.compare_digest(computed_hash, stored_hash)


def generate_reset_token() -> str:
    """Generate a cryptographically secure, URL-safe single-use reset token."""
    return secrets.token_urlsafe(32)


def hash_reset_token(token: str) -> str:
    """Hash password reset token using HMAC-SHA256."""
    return hmac.new(SECRET_PEPPER, token.strip().encode("utf-8"), hashlib.sha256).hexdigest()


def verify_reset_token(token: str, stored_hash: str) -> bool:
    """Verify reset token against stored hash using constant-time comparison."""
    if not token or not stored_hash:
        return False
    computed_hash = hash_reset_token(token)
    return hmac.compare_digest(computed_hash, stored_hash)


def generate_user_id() -> str:
    """
    Generate unique internal User ID.
    Format: USR-XXXXXXXX (8 uppercase alphanumeric characters)
    """
    random_part = secrets.token_hex(4).upper()
    return f"USR-{random_part}"


class SimpleRateLimiter:
    """
    Thread-safe in-memory rate limiter for brute-force protection and cooldowns.
    """
    def __init__(self):
        self._records = {}

    def is_allowed(self, key: str, max_attempts: int, window_seconds: int) -> Tuple[bool, int]:
        """
        Check if an action is allowed for the given key.
        Returns (is_allowed, seconds_remaining).
        """
        now = time.time()
        record = self._records.get(key, [])
        # Prune expired timestamps
        valid_timestamps = [t for t in record if now - t < window_seconds]
        if len(valid_timestamps) >= max_attempts:
            oldest = valid_timestamps[0]
            remaining = int(window_seconds - (now - oldest))
            return False, max(1, remaining)
        
        valid_timestamps.append(now)
        self._records[key] = valid_timestamps
        return True, 0

    def reset(self, key: str):
        if key in self._records:
            del self._records[key]


# Global rate limiters
login_rate_limiter = SimpleRateLimiter()
otp_request_limiter = SimpleRateLimiter()
reset_request_limiter = SimpleRateLimiter()
