import os
from datetime import timedelta
from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..db import (
    activate_user_from_otp,
    cleanup_expired_records,
    create_otp_challenge,
    create_password_reset,
    get_latest_otp_challenge,
    get_user_by_email,
    get_user_by_id,
    get_user_by_login_id,
    is_user_locked_out,
    record_failed_login,
    resend_otp_challenge,
    reset_failed_logins,
    reset_user_password,
    update_user_password,
    verify_otp_challenge,
    verify_password_reset_token,
)
from ..services.auth_security import (
    hash_password,
    login_rate_limiter,
    needs_password_rehash,
    otp_request_limiter,
    reset_request_limiter,
    validate_email_address,
    validate_full_name,
    validate_password_strength,
    verify_password,
)
from ..services.email_service import (
    send_account_confirmation_email,
    send_otp_email,
    send_password_reset_email,
)

auth_bp = Blueprint("auth", __name__)


# ── User Registration & Email Verification Routes ───────────────────────────

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """
    User Registration:
    - GET: Render professional registration view (React or HTML).
    - POST: Validate registration, generate OTP, send email, redirect to OTP verification.
    """
    if "user_id" in session:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        # 1. Validation
        valid_name, err = validate_full_name(full_name)
        if not valid_name:
            flash(err, "error")
            return render_template("register.html", full_name=full_name, email=email)

        valid_email, err = validate_email_address(email)
        if not valid_email:
            flash(err, "error")
            return render_template("register.html", full_name=full_name, email=email)

        valid_pwd, err = validate_password_strength(password)
        if not valid_pwd:
            flash(err, "error")
            return render_template("register.html", full_name=full_name, email=email)

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("register.html", full_name=full_name, email=email)

        # 2. Check existing user
        existing_user = get_user_by_email(email)
        if existing_user:
            flash("An account already exists with this email address. Please log in.", "error")
            return render_template("register.html", full_name=full_name, email=email)

        # 3. Rate limiting for OTP creation
        client_ip = request.remote_addr or "127.0.0.1"
        allowed, wait_sec = otp_request_limiter.is_allowed(f"reg_{client_ip}_{email}", max_attempts=5, window_seconds=300)
        if not allowed:
            flash(f"Too many registration attempts. Please wait {wait_sec} seconds.", "error")
            return render_template("register.html", full_name=full_name, email=email)

        # 4. Hash password with bcrypt and generate OTP challenge
        password_hash = hash_password(password)
        otp_code = create_otp_challenge(email, full_name, password_hash)

        # 5. Send real OTP to registered email
        try:
            send_otp_email(email, full_name, otp_code)
        except Exception:
            flash(
                "Unable to send the verification email. Configure Gmail SMTP with a Google App Password and try again.",
                "error",
            )
            return render_template("register.html", full_name=full_name, email=email)

        session["pending_verification_email"] = email
        flash("A verification code has been sent to your email address.", "success")
        return redirect(url_for("auth.verify_otp", email=email))

    return render_template("register.html")


@auth_bp.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    """
    Email OTP Verification:
    - GET: Display verification screen.
    - POST: Validate entered OTP, activate account in DB, send confirmation email.
    """
    if "user_id" in session:
        return redirect(url_for("main.dashboard"))

    email = request.args.get("email", "").strip().lower() or session.get("pending_verification_email", "")
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower() or email
        otp_code = request.form.get("otp", "").strip()

        if not email:
            flash("Missing registration email. Please register again.", "error")
            return redirect(url_for("auth.register"))

        if not otp_code or len(otp_code) != 6 or not otp_code.isdigit():
            flash("Please enter a valid 6-digit verification code.", "error")
            return render_template("verify_otp.html", email=email)

        is_valid, reason, challenge = verify_otp_challenge(email, otp_code)

        if not is_valid:
            if reason == "expired":
                flash("Your verification code has expired. Please request a new one.", "error")
            elif reason == "max_attempts_exceeded":
                flash("Maximum verification attempts exceeded. Please request a new verification code.", "error")
            elif reason == "not_found":
                flash("No pending verification found. Please register first.", "error")
            else:
                attempts_left = max(0, 5 - (challenge.get("attempts", 0) if challenge else 5))
                flash(f"Incorrect verification code. Attempts remaining: {attempts_left}", "error")
            return render_template("verify_otp.html", email=email)

        # OTP is valid: Activate user account transactionally
        try:
            user = activate_user_from_otp(challenge)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("auth.login"))

        session.pop("pending_verification_email", None)

        # Send official Account Confirmation Email With Login Details
        try:
            login_url = url_for("auth.login", _external=True)
            send_account_confirmation_email(
                to_email=user["email"],
                full_name=user["full_name"],
                user_id=user["user_id"],
                login_url=login_url,
            )
        except Exception:
            pass

        flash("Account created and activated successfully! Please log in.", "success")
        return redirect(url_for("auth.registration_success", email=user["email"], user_id=user["user_id"]))

    return render_template("verify_otp.html", email=email)


@auth_bp.route("/registration-success", methods=["GET"])
def registration_success():
    """
    Registration Success view:
    Shows confirmed Login ID, generated Account ID, and login link.
    """
    email = request.args.get("email", "")
    user_id = request.args.get("user_id", "")
    return render_template("registration_success.html", email=email, user_id=user_id)


# ── User Login & Logout Routes ───────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    User Login:
    - GET: Render login page with show/hide password, remember me, forgot password link.
    - POST: Validate credentials, verify email is verified and active, create session.
    """
    if "user_id" in session:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        login_id = request.form.get("login_id", "").strip() or request.form.get("username_or_email", "").strip()
        password = request.form.get("password", "")
        remember_me = bool(request.form.get("remember_me"))

        if not login_id or not password:
            flash("Please enter both Login ID and password.", "error")
            return render_template("login.html", login_id=login_id)

        client_ip = request.remote_addr or "127.0.0.1"
        allowed, wait_sec = login_rate_limiter.is_allowed(f"login_{client_ip}", max_attempts=10, window_seconds=60)
        if not allowed:
            flash(f"Too many login attempts. Please wait {wait_sec} seconds before trying again.", "error")
            return render_template("login.html", login_id=login_id)

        user = get_user_by_login_id(login_id)

        if not user:
            # Generic error to prevent email enumeration
            flash("Invalid login credentials.", "error")
            return render_template("login.html", login_id=login_id)

        # Check account lockout
        is_locked, mins_left = is_user_locked_out(user)
        if is_locked:
            flash(f"Account temporarily locked due to multiple failed login attempts. Try again in {mins_left} minute(s).", "error")
            return render_template("login.html", login_id=login_id)

        # Verify password
        if not verify_password(password, user["password_hash"]):
            failed_count = record_failed_login(user["id"])
            if failed_count >= 5:
                flash("Account locked for 15 minutes due to 5 consecutive failed login attempts.", "error")
            else:
                flash("Invalid login credentials.", "error")
            return render_template("login.html", login_id=login_id)

        # Verify account status
        if user.get("account_status") != "active":
            flash("Your account is currently disabled or suspended. Please contact support.", "error")
            return render_template("login.html", login_id=login_id)

        # Verify email verification status
        if not user.get("email_verified"):
            flash("Your email address is not verified. Please complete email verification to log in.", "error")
            return redirect(url_for("auth.verify_otp", email=user["email"]))

        # Successful login: Reset failed attempts
        reset_failed_logins(user["id"])

        # Auto-upgrade legacy hash to bcrypt if needed
        if needs_password_rehash(user["password_hash"]):
            try:
                update_user_password(user["id"], hash_password(password))
            except Exception:
                pass

        # Establish authenticated session
        session.clear()
        session["user_id"] = user["id"]
        session["account_id"] = user.get("user_id", f"USR-{user['id']:04d}")
        session["username"] = user.get("full_name") or user.get("username")
        session["email"] = user["email"]

        if remember_me:
            session.permanent = True
            session.modified = True

        return redirect(url_for("main.dashboard"))

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    """Clear session and log user out."""
    session.clear()
    flash("You have been successfully logged out.", "success")
    return redirect(url_for("auth.login"))


# ── Forgot Password & Reset Password Routes ─────────────────────────────────

@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """
    Forgot Password:
    - GET: Render forgot password page.
    - POST: Send single-use reset link to registered email (without revealing if email exists).
    """
    if "user_id" in session:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        valid_email, _ = validate_email_address(email)

        if valid_email:
            # Enforce rate limiting on reset requests
            client_ip = request.remote_addr or "127.0.0.1"
            allowed, _ = reset_request_limiter.is_allowed(f"reset_{client_ip}_{email}", max_attempts=3, window_seconds=300)
            if allowed:
                token = create_password_reset(email)
                if token:
                    user = get_user_by_email(email)
                    reset_url = url_for("auth.reset_password", token=token, _external=True)
                    try:
                        send_password_reset_email(email, user.get("full_name") or "User", reset_url)
                    except Exception:
                        pass

        # Always show consistent, secure confirmation message
        flash(
            "If your email address is registered in our system, you will receive a password reset link shortly.",
            "success",
        )
        return render_template("forgot_password.html")

    return render_template("forgot_password.html")


@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    """
    Reset Password:
    - GET: Validate token and show password reset form.
    - POST: Validate token and new password, hash new password, invalidate token.
    """
    token = request.args.get("token", "").strip() or request.form.get("token", "").strip()

    if not token:
        flash("Password reset token is missing.", "error")
        return redirect(url_for("auth.login"))

    is_valid, reason, record = verify_password_reset_token(token)
    if not is_valid:
        if reason == "expired":
            flash("This password reset link has expired. Please request a new one.", "error")
        elif reason == "already_used":
            flash("This password reset link has already been used. Please request a new one.", "error")
        else:
            flash("Invalid password reset link.", "error")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        valid_pwd, err = validate_password_strength(new_password)
        if not valid_pwd:
            flash(err, "error")
            return render_template("reset_password.html", token=token)

        if new_password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("reset_password.html", token=token)

        new_hash = hash_password(new_password)
        success = reset_user_password(token, new_hash)

        if success:
            session.clear()
            flash("Your password has been successfully reset! You can now log in with your new password.", "success")
            return redirect(url_for("auth.login"))
        else:
            flash("Failed to reset password. The link may have expired or already been used.", "error")
            return redirect(url_for("auth.forgot_password"))

    return render_template("reset_password.html", token=token)


# ── JSON APIs For React Frontend Integration ────────────────────────────────

@auth_bp.route("/api/auth/register", methods=["POST"])
def api_register():
    """JSON API for React registration."""
    data = request.get_json(silent=True) or request.form.to_dict()
    full_name = data.get("full_name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    confirm_password = data.get("confirm_password", "")

    valid_name, err = validate_full_name(full_name)
    if not valid_name:
        return jsonify({"success": False, "message": err}), 400

    valid_email, err = validate_email_address(email)
    if not valid_email:
        return jsonify({"success": False, "message": err}), 400

    valid_pwd, err = validate_password_strength(password)
    if not valid_pwd:
        return jsonify({"success": False, "message": err}), 400

    if password != confirm_password:
        return jsonify({"success": False, "message": "Passwords do not match."}), 400

    existing_user = get_user_by_email(email)
    if existing_user:
        return jsonify({"success": False, "message": "An account already exists with this email address. Please log in."}), 409

    client_ip = request.remote_addr or "127.0.0.1"
    allowed, wait_sec = otp_request_limiter.is_allowed(f"reg_{client_ip}_{email}", max_attempts=5, window_seconds=300)
    if not allowed:
        return jsonify({"success": False, "message": f"Too many registration attempts. Please wait {wait_sec} seconds."}), 429

    password_hash = hash_password(password)
    otp_code = create_otp_challenge(email, full_name, password_hash)

    try:
        send_otp_email(email, full_name, otp_code)
    except Exception:
        return jsonify({
            "success": False,
            "message": "Unable to send the verification email. Configure Gmail SMTP with a Google App Password and try again.",
        }), 500

    session["pending_verification_email"] = email
    return jsonify({
        "success": True,
        "message": "A 6-digit verification code has been sent to your email address.",
        "email": email,
    }), 200


@auth_bp.route("/api/auth/verify-otp", methods=["POST"])
def api_verify_otp():
    """JSON API for React OTP verification."""
    data = request.get_json(silent=True) or request.form.to_dict()
    email = data.get("email", "").strip().lower() or session.get("pending_verification_email", "")
    otp_code = data.get("otp", "").strip()

    if not email:
        return jsonify({"success": False, "message": "Email is required for OTP verification."}), 400

    if not otp_code or len(otp_code) != 6 or not otp_code.isdigit():
        return jsonify({"success": False, "message": "Please enter a valid 6-digit numeric verification code."}), 400

    is_valid, reason, challenge = verify_otp_challenge(email, otp_code)
    if not is_valid:
        messages = {
            "expired": "Your verification code has expired. Please request a new one.",
            "max_attempts_exceeded": "Maximum verification attempts exceeded. Please request a new code.",
            "not_found": "No active verification challenge found. Please register first.",
        }
        attempts_left = max(0, 5 - (challenge.get("attempts", 0) if challenge else 5))
        msg = messages.get(reason, f"Incorrect verification code. Attempts remaining: {attempts_left}")
        return jsonify({"success": False, "reason": reason, "message": msg, "attempts_remaining": attempts_left}), 400

    try:
        user = activate_user_from_otp(challenge)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400

    session.pop("pending_verification_email", None)
    # Send account confirmation email
    try:
        login_url = url_for("auth.login", _external=True)
        send_account_confirmation_email(
            to_email=user["email"],
            full_name=user["full_name"],
            user_id=user["user_id"],
            login_url=login_url,
        )
    except Exception:
        pass

    return jsonify({
        "success": True,
        "message": "Your account has been successfully verified and created.",
        "user_id": user["user_id"],
        "login_id": user["email"],
        "full_name": user["full_name"],
    }), 200


@auth_bp.route("/api/auth/resend-otp", methods=["POST"])
def api_resend_otp():
    """JSON API to resend OTP with 60-second cooldown."""
    data = request.get_json(silent=True) or request.form.to_dict()
    email = data.get("email", "").strip().lower() or session.get("pending_verification_email", "")

    if not email:
        return jsonify({"success": False, "message": "Email is required."}), 400

    success, msg, new_otp, cooldown_left = resend_otp_challenge(email)
    if not success:
        return jsonify({"success": False, "message": msg, "cooldown_seconds": cooldown_left}), 429

    challenge = get_latest_otp_challenge(email)
    full_name = challenge.get("full_name", "User") if challenge else "User"

    try:
        send_otp_email(email, full_name, new_otp)
    except Exception:
        return jsonify({
            "success": False,
            "message": "Unable to send the verification email. Please check the Gmail SMTP configuration.",
        }), 500

    return jsonify({
        "success": True,
        "message": "A new verification code has been sent to your email address.",
        "cooldown_seconds": 60,
    }), 200


@auth_bp.route("/api/auth/login", methods=["POST"])
def api_login():
    """JSON API for React login."""
    data = request.get_json(silent=True) or request.form.to_dict()
    login_id = data.get("login_id", "").strip() or data.get("username_or_email", "").strip()
    password = data.get("password", "")
    remember_me = bool(data.get("remember_me"))

    if not login_id or not password:
        return jsonify({"success": False, "message": "Please enter both Login ID and password."}), 400

    client_ip = request.remote_addr or "127.0.0.1"
    allowed, wait_sec = login_rate_limiter.is_allowed(f"login_{client_ip}", max_attempts=10, window_seconds=60)
    if not allowed:
        return jsonify({"success": False, "message": f"Too many attempts. Please wait {wait_sec} seconds."}), 429

    user = get_user_by_login_id(login_id)
    if not user:
        return jsonify({"success": False, "message": "Invalid login credentials."}), 401

    is_locked, mins_left = is_user_locked_out(user)
    if is_locked:
        return jsonify({"success": False, "message": f"Account temporarily locked. Please try again in {mins_left} minute(s)."}), 403

    if not verify_password(password, user["password_hash"]):
        failed_count = record_failed_login(user["id"])
        if failed_count >= 5:
            return jsonify({"success": False, "message": "Account locked for 15 minutes due to 5 consecutive failed attempts."}), 403
        return jsonify({"success": False, "message": "Invalid login credentials."}), 401

    if user.get("account_status") != "active":
        return jsonify({"success": False, "message": "Your account is not active. Please contact support."}), 403

    if not user.get("email_verified"):
        return jsonify({
            "success": False,
            "requires_verification": True,
            "email": user["email"],
            "message": "Your email address is not verified. Please complete email verification.",
        }), 403

    reset_failed_logins(user["id"])

    if needs_password_rehash(user["password_hash"]):
        try:
            update_user_password(user["id"], hash_password(password))
        except Exception:
            pass

    session.clear()
    session["user_id"] = user["id"]
    session["account_id"] = user.get("user_id", f"USR-{user['id']:04d}")
    session["username"] = user.get("full_name") or user.get("username")
    session["email"] = user["email"]

    if remember_me:
        session.permanent = True

    return jsonify({
        "success": True,
        "message": "Login successful.",
        "redirect": url_for("main.dashboard"),
        "user": {
            "id": user["id"],
            "user_id": user.get("user_id", f"USR-{user['id']:04d}"),
            "email": user["email"],
            "full_name": user.get("full_name", user.get("username")),
        },
    }), 200


@auth_bp.route("/api/auth/forgot-password", methods=["POST"])
def api_forgot_password():
    """JSON API for Forgot Password."""
    data = request.get_json(silent=True) or request.form.to_dict()
    email = data.get("email", "").strip().lower()

    reset_url = None
    valid_email, _ = validate_email_address(email)
    if valid_email:
        client_ip = request.remote_addr or "127.0.0.1"
        allowed, _ = reset_request_limiter.is_allowed(f"reset_{client_ip}_{email}", max_attempts=3, window_seconds=300)
        if allowed:
            token = create_password_reset(email)
            if token:
                user = get_user_by_email(email)
                reset_url = url_for("auth.reset_password", token=token, _external=True)
                try:
                    send_password_reset_email(email, user.get("full_name") or "User", reset_url)
                except Exception:
                    pass

    return jsonify({
        "success": True,
        "message": "If an account with that email exists, password reset instructions have been sent.",
        "instant_reset_link": reset_url,
    }), 200


@auth_bp.route("/api/auth/reset-password", methods=["POST"])
def api_reset_password():
    """JSON API for Reset Password."""
    data = request.get_json(silent=True) or request.form.to_dict()
    token = data.get("token", "").strip()
    new_password = data.get("password", "")
    confirm_password = data.get("confirm_password", "")

    if not token:
        return jsonify({"success": False, "message": "Reset token is missing."}), 400

    is_valid, reason, _ = verify_password_reset_token(token)
    if not is_valid:
        msg = "Password reset link is invalid, expired, or has already been used."
        return jsonify({"success": False, "message": msg}), 400

    valid_pwd, err = validate_password_strength(new_password)
    if not valid_pwd:
        return jsonify({"success": False, "message": err}), 400

    if new_password != confirm_password:
        return jsonify({"success": False, "message": "Passwords do not match."}), 400

    new_hash = hash_password(new_password)
    success = reset_user_password(token, new_hash)

    if not success:
        return jsonify({"success": False, "message": "Failed to reset password. Link may have expired."}), 400

    session.clear()
    return jsonify({
        "success": True,
        "message": "Your password has been successfully reset. You can now log in.",
        "redirect": url_for("auth.login"),
    }), 200


@auth_bp.route("/api/auth/status", methods=["GET"])
def api_status():
    """Check current authentication status."""
    logged_in = "user_id" in session
    user_info = None
    if logged_in:
        user = get_user_by_id(session["user_id"])
        if user:
            user_info = {
                "id": user["id"],
                "user_id": user.get("user_id"),
                "email": user["email"],
                "full_name": user.get("full_name", user.get("username")),
                "email_verified": bool(user.get("email_verified")),
            }
    return jsonify({"logged_in": logged_in, "user": user_info})
