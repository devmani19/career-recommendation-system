import json

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import (
    create_user,
    get_user_by_email,
    get_user_by_username,
    get_user_recommendations,
    save_recommendation,
)
from ..recommender import (
    extract_skills_from_text,
    extract_resume_sections,
    looks_like_certificate_document,
    read_text_from_upload,
    recommend_careers,
    verify_secure_file,
)

main = Blueprint("main", __name__)


@main.route("/", methods=["GET"])
def home():
    return render_template(
        "index.html",
        logged_in="user_id" in session,
        username=session.get("username", ""),
    )


@main.route("/register", methods=["GET", "POST"])
def register():
    from .auth_routes import register as auth_register
    return auth_register()


@main.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    from .auth_routes import verify_otp as auth_verify_otp
    return auth_verify_otp()


@main.route("/registration-success", methods=["GET"])
def registration_success():
    from .auth_routes import registration_success as auth_registration_success
    return auth_registration_success()


@main.route("/login", methods=["GET", "POST"])
def login():
    from .auth_routes import login as auth_login
    return auth_login()


@main.route("/logout")
def logout():
    from .auth_routes import logout as auth_logout
    return auth_logout()


@main.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    from .auth_routes import forgot_password as auth_forgot_password
    return auth_forgot_password()


@main.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    from .auth_routes import reset_password as auth_reset_password
    return auth_reset_password()


@main.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("main.login"))

    result = None
    error = None
    verification = []
    skill_gap_message = None
    resume_sections = {"education": "", "experience": "", "projects": ""}
    candidate_skills = []
    candidate_name = "Candidate"
    user_id = session["user_id"]
    history = get_user_recommendations(user_id)

    if request.method == "POST":
        candidate_name = request.form.get("candidate_name", "Candidate").strip() or "Candidate"
        resume_file = request.files.get("resume")
        certificate_files = request.files.getlist("certificate")
        extra_skills = request.form.get("skills", "")

        try:
            # Validate and verify resume
            if not resume_file or not resume_file.filename:
                raise ValueError("Please upload a resume.")
            verify_secure_file(resume_file, "resume")
            resume_text = read_text_from_upload(resume_file)
            resume_sections = extract_resume_sections(resume_text)

            # Process certificates if provided
            valid_certificate_files = [f for f in certificate_files if f and f.filename]
            verification = []
            certificate_text = ""

            if valid_certificate_files:
                for certificate_file in valid_certificate_files:
                    verification.append(verify_secure_file(certificate_file, "certificate"))

                certificate_texts = []
                for f in valid_certificate_files:
                    t = read_text_from_upload(f)
                    if not t.strip():
                        t = f"Certificate credential {f.filename} attached."
                    certificate_texts.append(t)

                for text, f in zip(certificate_texts, valid_certificate_files):
                    if not looks_like_certificate_document(text, f.filename or ""):
                        raise ValueError(
                            f"File '{f.filename}' does not appear to be a relevant certificate or proof document. "
                            "Please upload a course completion certificate, credential, or achievement proof."
                        )

                certificate_text = " ".join(certificate_texts)

            # Extract and combine skills
            candidate_skills = set(extract_skills_from_text(resume_text + " " + certificate_text))
            if extra_skills:
                candidate_skills.update(extract_skills_from_text(extra_skills))

            # Run recommendation engine
            result = recommend_careers(
                candidate_skills,
                limit=5,
                education=resume_sections.get("education", ""),
                experience_text=resume_sections.get("experience", ""),
                projects=[resume_sections.get("projects", "")] if resume_sections.get("projects") else [],
                verified_certificates=verification,
            )

            if result:
                best_role = result[0]
                if best_role["score"] < 45 or len(best_role["match"]) < 2:
                    skill_gap_message = (
                        "Your current certificate and resume evidence is not strong enough for this role. "
                        "The main skill gaps are: "
                        + ", ".join(best_role["missing"][:5])
                        + ". Please add more relevant certificates or remove weak documents."
                    )
                elif best_role["missing"]:
                    skill_gap_message = (
                        "Skill gap detected: "
                        + ", ".join(best_role["missing"][:5])
                        + ". Improve these areas with targeted certificates or projects."
                    )

                # Persist result
                ranking_method = result[0].get("ranking_method", "weighted_fallback") if result else "weighted_fallback"
                save_recommendation(
                    user_id=user_id,
                    candidate_name=candidate_name,
                    certificate_name=", ".join(item["filename"] for item in verification) if verification else "Resume Profile",
                    score=json.dumps({item["role"]: item["score"] for item in result}),
                    result_json=json.dumps(result),
                    ranking_method=ranking_method,
                    model_version="1.0.0",
                )
                history = get_user_recommendations(user_id)
            else:
                skill_gap_message = (
                    "No career roles matched the skills identified in your documents. "
                    "Try providing a more detailed resume or adding additional skills."
                )

            return render_template(
                "dashboard.html",
                logged_in=True,
                username=session["username"],
                candidate_name=candidate_name,
                result=result,
                verification=verification,
                error=None,
                skills=sorted(candidate_skills),
                resume_sections=resume_sections,
                history=history,
                skill_gap_message=skill_gap_message,
                active_module="career",
            )

        except ValueError as exc:
            error = str(exc)

    return render_template(
        "dashboard.html",
        logged_in=True,
        username=session["username"],
        candidate_name=candidate_name,
        result=result,
        verification=verification,
        error=error,
        skills=[],
        resume_sections=resume_sections,
        history=history,
        skill_gap_message=skill_gap_message,
    )
