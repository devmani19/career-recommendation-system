"""Career Readiness Assessment Blueprint and Routes.

Implements:
- Assessment Hub (4 assessment cards + previous attempts)
- Instructions page with language selection confirmation
- Interactive test-taking screen with timer, question palette, and code editor
- Results dashboard with readiness tier, topic breakdown, and skill gaps
- Answer review screen with explanations and reference solutions
- Secure AJAX APIs for auto-saving and isolated sample code execution
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..db import (
    get_assessment_question_counts,
    get_assessment_session,
    get_user_assessment_sessions,
    get_user_recommendations,
)
from ..services.assessment_service import ASSESSMENT_CONFIGS, AssessmentService

logger = logging.getLogger(__name__)

assessment_bp = Blueprint("assessment", __name__, url_prefix="/assessment")


def get_current_user_id() -> Optional[int]:
    """Retrieves user_id from session or X-User-Id header for testing."""
    user_id = session.get("user_id")
    if user_id:
        return int(user_id)
    auth_header = request.headers.get("X-User-Id")
    if auth_header and auth_header.isdigit():
        return int(auth_header)
    return None


@assessment_bp.before_request
def require_authentication():
    """Protects all assessment endpoints requiring authentication."""
    user_id = get_current_user_id()
    if not user_id:
        if request.is_json:
            return jsonify({"success": False, "error": "Authentication required"}), 401
        flash("Please log in to access the Career Readiness Assessment.", "warning")
        return redirect(url_for("main.login"))


# ── Assessment Hub ─────────────────────────────────────────────────────────


@assessment_bp.route("/", methods=["GET"])
def assessment_home():
    """Assessment dashboard displaying the 4 cards and attempt history."""
    user_id = get_current_user_id()
    username = session.get("username", "Candidate")
    history = get_user_assessment_sessions(user_id)
    profile_ctx = AssessmentService.get_user_profile_context(user_id)

    # Question bank counts
    counts_rows = get_assessment_question_counts()
    counts_map = {}
    for r in counts_rows:
        key = f"{r['category']}_{r['question_type']}"
        counts_map[key] = r["count"]

    return render_template(
        "assessment/index.html",
        username=username,
        candidate_name=profile_ctx["candidate_name"],
        target_role=profile_ctx["target_role"],
        history=history,
        counts=counts_map,
        active_nav="assessment",
    )


# ── Instructions Page ──────────────────────────────────────────────────────


@assessment_bp.route("/instructions/<assessment_type>", methods=["GET"])
def instructions(assessment_type: str):
    """Pre-test review displaying rules, duration, question breakdown, and language."""
    if assessment_type not in ASSESSMENT_CONFIGS:
        flash("Invalid assessment type selected.", "error")
        return redirect(url_for("assessment.assessment_home"))

    config = ASSESSMENT_CONFIGS[assessment_type]
    user_id = get_current_user_id()
    username = session.get("username", "Candidate")
    profile_ctx = AssessmentService.get_user_profile_context(user_id)

    preselected_lang = request.args.get("lang", "").strip().lower()
    if preselected_lang not in {"python", "java"}:
        preselected_lang = config.get("forced_language", "python")

    return render_template(
        "assessment/instructions.html",
        username=username,
        assessment_type=assessment_type,
        config=config,
        selected_language=preselected_lang,
        target_role=profile_ctx["target_role"],
        active_nav="assessment",
    )


# ── Start Assessment Session ───────────────────────────────────────────────


@assessment_bp.route("/start", methods=["POST"])
def start_assessment():
    """Creates a new session and redirects to the active test screen."""
    user_id = get_current_user_id()
    assessment_type = request.form.get("assessment_type", "").strip()
    programming_language = request.form.get("programming_language", "").strip().lower()
    target_role = request.form.get("target_role", "").strip()

    if assessment_type not in ASSESSMENT_CONFIGS:
        flash("Invalid assessment configuration.", "error")
        return redirect(url_for("assessment.assessment_home"))

    config = ASSESSMENT_CONFIGS[assessment_type]
    if config["requires_language"]:
        if "forced_language" in config:
            programming_language = config["forced_language"]
        elif programming_language not in {"python", "java"}:
            flash("Please explicitly select either Python or Java for the coding assessment.", "error")
            return redirect(url_for("assessment.instructions", assessment_type=assessment_type))
    else:
        programming_language = None

    try:
        session_id = AssessmentService.create_session(
            user_id=user_id,
            assessment_type=assessment_type,
            programming_language=programming_language,
            target_role=target_role or None,
        )
        return redirect(url_for("assessment.take_test", session_id=session_id))
    except Exception as exc:
        logger.exception("Failed to initialize assessment session:")
        flash(f"Could not generate assessment: {str(exc)}", "error")
        return redirect(url_for("assessment.assessment_home"))


# ── Active Test-Taking Screen ──────────────────────────────────────────────


@assessment_bp.route("/session/<session_id>", methods=["GET"])
def take_test(session_id: str):
    """The timed assessment screen with question palette and isolated editor."""
    user_id = get_current_user_id()
    username = session.get("username", "Candidate")

    try:
        data = AssessmentService.get_active_session_data(session_id, user_id)
    except PermissionError:
        abort(403)
    except KeyError:
        abort(404)

    # If already finalized, redirect to result screen
    if data["is_completed"]:
        return redirect(url_for("assessment.view_result", session_id=session_id))

    return render_template(
        "assessment/session.html",
        username=username,
        session_id=session_id,
        session_data=data["session"],
        questions=data["questions"],
        remaining_seconds=data["remaining_seconds"],
        total_questions=data["total_questions"],
        active_nav="assessment",
    )


# ── AJAX Answer Save API ───────────────────────────────────────────────────


@assessment_bp.route("/api/save-answer", methods=["POST"])
def api_save_answer():
    """AJAX endpoint to auto-save candidate answers without page reload."""
    user_id = get_current_user_id()
    payload = request.get_json(silent=True) or {}

    session_id = payload.get("session_id", "").strip()
    question_id = payload.get("question_id", "").strip()
    selected_option = payload.get("selected_option")
    code_submission = payload.get("code_submission")

    if not session_id or not question_id:
        return jsonify({"success": False, "error": "Missing session_id or question_id"}), 400

    try:
        res = AssessmentService.save_answer(
            session_id=session_id,
            user_id=user_id,
            question_id=question_id,
            selected_option=selected_option,
            code_submission=code_submission,
        )
        return jsonify(res), 200
    except PermissionError:
        return jsonify({"success": False, "error": "Unauthorized session access"}), 403
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


# ── AJAX Sample Code Execution API ─────────────────────────────────────────


@assessment_bp.route("/api/run-code", methods=["POST"])
def api_run_code():
    """AJAX endpoint to execute code against predefined sample test cases only."""
    user_id = get_current_user_id()
    payload = request.get_json(silent=True) or {}

    session_id = payload.get("session_id", "").strip()
    question_id = payload.get("question_id", "").strip()
    code = payload.get("code", "")
    language = payload.get("language", "").strip().lower()

    if not session_id or not question_id or not language:
        return jsonify({"success": False, "error": "Missing required execution parameters"}), 400

    try:
        eval_result = AssessmentService.run_sample_code(
            session_id=session_id,
            user_id=user_id,
            question_id=question_id,
            code=code,
            submitted_language=language,
        )
        return jsonify(eval_result), 200
    except PermissionError:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    except ValueError as ve:
        # Rejection of mismatched language (e.g. submitting Java to Python test)
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


# ── Assessment Submission & Finalization ───────────────────────────────────


@assessment_bp.route("/session/<session_id>/submit", methods=["POST"])
def submit_test(session_id: str):
    """Scores all answers, tests hidden coding cases, and finalizes session."""
    user_id = get_current_user_id()
    try:
        AssessmentService.finalize_and_score_session(session_id, user_id)
        return redirect(url_for("assessment.view_result", session_id=session_id))
    except PermissionError:
        abort(403)
    except KeyError:
        abort(404)
    except Exception as exc:
        logger.exception("Error scoring assessment:")
        flash(f"Error finalizing assessment: {str(exc)}", "error")
        return redirect(url_for("assessment.assessment_home"))


# ── Results Dashboard ──────────────────────────────────────────────────────


@assessment_bp.route("/result/<session_id>", methods=["GET"])
def view_result(session_id: str):
    """Results dashboard with score, percentage, readiness tier, and skill-gap links."""
    user_id = get_current_user_id()
    username = session.get("username", "Candidate")
    sess = get_assessment_session(session_id)

    if not sess:
        abort(404)
    if sess["user_id"] != user_id:
        abort(403)

    # If test is not completed yet, finalize now
    if sess["status"] != "completed":
        AssessmentService.finalize_and_score_session(session_id, user_id)
        sess = get_assessment_session(session_id)

    breakdown = json.loads(sess.get("topic_breakdown_json") or "[]")
    skill_gaps = json.loads(sess.get("skill_gap_analysis_json") or "{}")

    # Counts of answered, unanswered, correct
    conn = get_assessment_session(session_id)  # fetch fresh
    submissions = get_user_assessment_sessions(user_id)

    return render_template(
        "assessment/result.html",
        username=username,
        session=sess,
        breakdown=breakdown,
        skill_gaps=skill_gaps,
        active_nav="assessment",
    )


# ── Detailed Answer Review ─────────────────────────────────────────────────


@assessment_bp.route("/review/<session_id>", methods=["GET"])
def review_answers(session_id: str):
    """Displays question-by-question review with correct answers, explanations, and code solutions."""
    user_id = get_current_user_id()
    username = session.get("username", "Candidate")

    try:
        review_data = AssessmentService.get_review_data(session_id, user_id)
    except PermissionError:
        abort(403)
    except KeyError:
        abort(404)

    return render_template(
        "assessment/review.html",
        username=username,
        session=review_data["session"],
        items=review_data["review_items"],
        active_nav="assessment",
    )
