"""Assessment Core Service.

Handles:
- Dynamic question selection, randomization, and profile personalization
- Strict Python and Java separation enforcement
- Timed assessment session lifecycle
- Server-side answer validation and scoring
- Integration with career recommendations and resume skill-gap analysis
"""

from __future__ import annotations

import json
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..db import (
    create_assessment_session,
    finalize_assessment_session,
    get_all_assessment_questions,
    get_assessment_question,
    get_assessment_session,
    get_db_connection,
    get_session_questions,
    get_session_submissions,
    get_user_assessment_sessions,
    get_user_recommendations,
    save_or_update_submission,
    save_session_questions,
)
from .code_executor import evaluate_code_submission

logger = logging.getLogger(__name__)

# Minimum counts per assessment configuration
ASSESSMENT_CONFIGS = {
    "aptitude": {
        "title": "Aptitude Assessment",
        "duration_minutes": 30,
        "requires_language": False,
        "counts": {"aptitude": 20},
    },
    "python_coding": {
        "title": "Python Coding Assessment",
        "duration_minutes": 45,
        "requires_language": True,
        "forced_language": "python",
        "counts": {"python_technical": 15, "python_coding": 3},
    },
    "java_coding": {
        "title": "Java Coding Assessment",
        "duration_minutes": 45,
        "requires_language": True,
        "forced_language": "java",
        "counts": {"java_technical": 15, "java_coding": 3},
    },
    "full_assessment": {
        "title": "Full Career Readiness Assessment",
        "duration_minutes": 60,
        "requires_language": True,
        "counts_python": {"aptitude": 20, "python_technical": 10, "python_coding": 2},
        "counts_java": {"aptitude": 20, "java_technical": 10, "java_coding": 2},
    },
}


class AssessmentService:
    """Service providing assessment session orchestration and scoring."""

    @staticmethod
    def get_user_profile_context(user_id: int) -> dict[str, Any]:
        """Extracts candidate profile, resume skills, and target role from existing recommendations."""
        recs = get_user_recommendations(user_id)
        if not recs:
            return {
                "candidate_name": "Candidate",
                "target_role": "Software Engineer",
                "resume_skills": [],
                "education": "",
            }

        latest = recs[0]
        target_role = "Software Engineer"
        try:
            result_list = json.loads(latest["result_json"])
            if result_list and isinstance(result_list, list):
                target_role = result_list[0].get("role", "Software Engineer")
        except Exception:
            pass

        return {
            "candidate_name": latest.get("candidate_name", "Candidate"),
            "target_role": target_role,
            "resume_skills": [],
            "education": "",
        }

    @staticmethod
    def get_past_seen_question_ids(user_id: int) -> set[str]:
        """Finds question IDs assigned to the user in their last 3 assessment attempts."""
        conn = get_db_connection()
        rows = conn.execute(
            """
            SELECT asq.question_id
            FROM assessment_sessions s
            JOIN assessment_session_questions asq ON s.id = asq.session_id
            WHERE s.user_id = ?
            ORDER BY s.started_at DESC
            LIMIT 150
            """,
            (user_id,),
        ).fetchall()
        conn.close()
        return {r["question_id"] for r in rows}

    @classmethod
    def select_questions_for_pool(
        cls,
        available: list[dict],
        count: int,
        seen_ids: set[str],
        target_role: str,
    ) -> list[dict]:
        """Selects questions balancing difficulty, role relevance, and minimizing repetition."""
        if len(available) <= count:
            return available

        # Partition into unseen vs seen
        unseen = [q for q in available if q["id"] not in seen_ids]
        seen = [q for q in available if q["id"] in seen_ids]

        # Role-relevant priority
        def role_score(q: dict) -> int:
            try:
                roles = json.loads(q.get("target_roles_json", "[]"))
                return 1 if any(target_role.lower() in r.lower() for r in roles) else 0
            except Exception:
                return 0

        # Sort unseen first, then by role relevance and randomized tie-break
        pool = sorted(unseen, key=lambda q: (role_score(q), random.random()), reverse=True)
        if len(pool) < count:
            pool += sorted(seen, key=lambda q: (role_score(q), random.random()), reverse=True)

        # Ensure difficulty distribution: roughly 40% easy, 40% medium, 20% hard
        easy = [q for q in pool if q["difficulty"] == "easy"]
        medium = [q for q in pool if q["difficulty"] == "medium"]
        hard = [q for q in pool if q["difficulty"] == "hard"]

        n_easy = max(1, int(count * 0.4))
        n_med = max(1, int(count * 0.4))
        n_hard = count - (n_easy + n_med)

        selected = easy[:n_easy] + medium[:n_med] + hard[:n_hard]

        # If shortfall due to pool bucket size, backfill from remaining pool
        if len(selected) < count:
            chosen_ids = {q["id"] for q in selected}
            for q in pool:
                if q["id"] not in chosen_ids:
                    selected.append(q)
                    chosen_ids.add(q["id"])
                    if len(selected) == count:
                        break

        return selected[:count]

    @classmethod
    def create_session(
        cls,
        user_id: int,
        assessment_type: str,
        programming_language: str | None = None,
        target_role: str | None = None,
    ) -> str:
        """
        Generates and initializes a new assessment session with dynamic question selection.
        Enforces strict Python/Java separation and question counts.
        """
        if assessment_type not in ASSESSMENT_CONFIGS:
            raise ValueError(f"Invalid assessment type: '{assessment_type}'")

        config = ASSESSMENT_CONFIGS[assessment_type]

        # Enforce language rules
        lang = None
        if config["requires_language"]:
            if "forced_language" in config:
                lang = config["forced_language"]
            else:
                lang = (programming_language or "").strip().lower()
                if lang not in {"python", "java"}:
                    raise ValueError("A valid programming language ('python' or 'java') must be explicitly selected.")
        else:
            lang = None  # Aptitude assessment has no programming language

        # Retrieve profile context and seen questions
        profile = cls.get_user_profile_context(user_id)
        effective_target_role = target_role or profile.get("target_role", "Software Engineer")
        seen_ids = cls.get_past_seen_question_ids(user_id)

        # Determine question quotas
        if assessment_type == "aptitude":
            quotas = {"aptitude": 20}
        elif assessment_type == "python_coding":
            quotas = {"python_technical": 15, "python_coding": 3}
        elif assessment_type == "java_coding":
            quotas = {"java_technical": 15, "java_coding": 3}
        elif assessment_type == "full_assessment":
            quotas = config["counts_python"] if lang == "python" else config["counts_java"]

        selected_questions: list[dict] = []

        # 1. Aptitude selection
        if "aptitude" in quotas:
            apt_all = get_all_assessment_questions(category="aptitude")
            apt_selected = cls.select_questions_for_pool(
                apt_all, quotas["aptitude"], seen_ids, effective_target_role
            )
            selected_questions.extend(apt_selected)

        # 2. Python technical selection
        if "python_technical" in quotas:
            py_tech_all = [
                q for q in get_all_assessment_questions(category="python")
                if q["question_type"] != "coding_challenge"
            ]
            py_tech_sel = cls.select_questions_for_pool(
                py_tech_all, quotas["python_technical"], seen_ids, effective_target_role
            )
            selected_questions.extend(py_tech_sel)

        # 3. Python coding selection
        if "python_coding" in quotas:
            py_code_all = get_all_assessment_questions(category="python", question_type="coding_challenge")
            py_code_sel = cls.select_questions_for_pool(
                py_code_all, quotas["python_coding"], seen_ids, effective_target_role
            )
            selected_questions.extend(py_code_sel)

        # 4. Java technical selection
        if "java_technical" in quotas:
            java_tech_all = [
                q for q in get_all_assessment_questions(category="java")
                if q["question_type"] != "coding_challenge"
            ]
            java_tech_sel = cls.select_questions_for_pool(
                java_tech_all, quotas["java_technical"], seen_ids, effective_target_role
            )
            selected_questions.extend(java_tech_sel)

        # 5. Java coding selection
        if "java_coding" in quotas:
            java_code_all = get_all_assessment_questions(category="java", question_type="coding_challenge")
            java_code_sel = cls.select_questions_for_pool(
                java_code_all, quotas["java_coding"], seen_ids, effective_target_role
            )
            selected_questions.extend(java_code_sel)

        # Strict language verification: never mix languages
        for q in selected_questions:
            if lang == "python" and q["category"] == "java":
                raise RuntimeError("Critical error: Java question leaked into Python session!")
            if lang == "java" and q["category"] == "python":
                raise RuntimeError("Critical error: Python question leaked into Java session!")

        # Shuffle presentation order (keeping coding challenges grouped at the end for clean test UX)
        non_coding = [q for q in selected_questions if q["question_type"] != "coding_challenge"]
        coding = [q for q in selected_questions if q["question_type"] == "coding_challenge"]
        random.shuffle(non_coding)
        random.shuffle(coding)
        final_ordered = non_coding + coding

        # Create session record
        session_id = uuid.uuid4().hex
        duration = config["duration_minutes"]
        create_assessment_session(
            session_id=session_id,
            user_id=user_id,
            assessment_type=assessment_type,
            programming_language=lang,
            target_role=effective_target_role,
            duration_minutes=duration,
        )

        # Build session question records with shuffled multiple choice options
        session_questions_data = []
        for idx, q in enumerate(final_ordered):
            shuffled_options = []
            if q["question_type"] != "coding_challenge":
                try:
                    opts = json.loads(q.get("options_json", "[]"))
                    shuffled_options = list(opts)
                    random.shuffle(shuffled_options)
                except Exception:
                    shuffled_options = []

            session_questions_data.append({
                "question_id": q["id"],
                "order_index": idx + 1,
                "shuffled_options_json": json.dumps(shuffled_options),
            })

        save_session_questions(session_id, session_questions_data)
        logger.info(
            "Created assessment session %s: type=%s, lang=%s, questions=%d",
            session_id, assessment_type, lang, len(final_ordered)
        )
        return session_id

    @classmethod
    def get_active_session_data(cls, session_id: str, user_id: int) -> dict[str, Any]:
        """
        Retrieves session details and assigned questions for test-taking.
        CRITICAL: Never exposes correct_answer, explanation, or hidden test cases!
        """
        sess = get_assessment_session(session_id)
        if not sess:
            raise KeyError("Assessment session not found.")
        if sess["user_id"] != user_id:
            raise PermissionError("Access denied: You are not authorized to view this assessment session.")

        raw_questions = get_session_questions(session_id)
        submissions = get_session_submissions(session_id)

        sanitized_questions = []
        for q in raw_questions:
            # Parse test cases: expose ONLY predefined non-hidden test cases for the user's sample run
            raw_tests = json.loads(q.get("test_cases_json") or "[]")
            sample_tests = [
                {"input": tc["input"], "expected_output": tc["expected_output"], "is_hidden": False}
                for tc in raw_tests if not tc.get("is_hidden", False)
            ]

            # Parse shuffled options
            shuffled_opts = json.loads(q.get("shuffled_options_json") or "[]")
            if not shuffled_opts and q.get("options_json"):
                shuffled_opts = json.loads(q["options_json"])

            sub = submissions.get(q["id"], {})

            sanitized_questions.append({
                "order_index": q["order_index"],
                "id": q["id"],
                "category": q["category"],
                "question_type": q["question_type"],
                "subtopic": q["subtopic"],
                "difficulty": q["difficulty"],
                "question_text": q["question_text"],
                "code_snippet": q["code_snippet"],
                "options": shuffled_opts,
                "marks": q["marks"],
                "sample_test_cases": sample_tests,
                # User's current saved answer
                "saved_selected_option": sub.get("selected_option"),
                "saved_code_submission": sub.get("code_submission") or q["code_snippet"],
                "is_answered": bool(sub.get("selected_option") or sub.get("code_submission")),
            })

        # Calculate time remaining
        started = datetime.strptime(sess["started_at"][:19], "%Y-%m-%d %H:%M:%S")
        elapsed_seconds = (datetime.now(timezone.utc).replace(tzinfo=None) - started).total_seconds()
        total_seconds = sess["duration_minutes"] * 60
        remaining_seconds = max(0, int(total_seconds - elapsed_seconds))

        return {
            "session": sess,
            "questions": sanitized_questions,
            "submissions": submissions,
            "remaining_seconds": remaining_seconds,
            "total_questions": len(sanitized_questions),
            "is_completed": sess["status"] == "completed",
        }

    @classmethod
    def save_answer(
        cls,
        session_id: str,
        user_id: int,
        question_id: str,
        selected_option: str | None = None,
        code_submission: str | None = None,
    ) -> dict[str, Any]:
        """Saves a candidate's answer during the active test."""
        sess = get_assessment_session(session_id)
        if not sess:
            raise KeyError("Session not found.")
        if sess["user_id"] != user_id:
            raise PermissionError("Unauthorized.")
        if sess["status"] == "completed":
            raise ValueError("Assessment session is already completed.")

        question = get_assessment_question(question_id)
        if not question:
            raise KeyError(f"Question {question_id} not found.")

        # Backend strict language validation
        if sess["programming_language"]:
            if question["category"] not in {"aptitude", sess["programming_language"]}:
                raise ValueError(
                    f"Question category '{question['category']}' does not match session language '{sess['programming_language']}'."
                )

        save_or_update_submission(
            session_id=session_id,
            question_id=question_id,
            selected_option=selected_option,
            code_submission=code_submission,
            is_correct=None,
            score_awarded=0.0,
            max_score=float(question["marks"]),
        )

        return {"success": True, "saved_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat()}

    @classmethod
    def run_sample_code(
        cls,
        session_id: str,
        user_id: int,
        question_id: str,
        code: str,
        submitted_language: str,
    ) -> dict[str, Any]:
        """Runs the user's code against predefined sample test cases only."""
        sess = get_assessment_session(session_id)
        if not sess or sess["user_id"] != user_id:
            raise PermissionError("Unauthorized.")

        session_lang = sess.get("programming_language")
        if not session_lang:
            raise ValueError("Active assessment does not support programming challenges.")

        # Backend enforcement: reject cross-language execution requests
        if submitted_language.strip().lower() != session_lang.lower():
            raise ValueError(
                f"Language mismatch: Submission requested '{submitted_language}' but assessment session is locked to '{session_lang}'."
            )

        q = get_assessment_question(question_id)
        if not q or q["category"] != session_lang:
            raise ValueError("Incompatible question for session language.")

        test_cases = json.loads(q.get("test_cases_json") or "[]")
        return evaluate_code_submission(
            language=session_lang,
            code=code,
            test_cases=test_cases,
            is_sample_run=True,
            max_marks=float(q["marks"]),
        )

    @classmethod
    def finalize_and_score_session(cls, session_id: str, user_id: int) -> dict[str, Any]:
        """
        Evaluates all answers, scores coding challenges against hidden test cases,
        computes readiness tiers, and links to career recommendation skill gaps.
        """
        sess = get_assessment_session(session_id)
        if not sess:
            raise KeyError("Session not found.")
        if sess["user_id"] != user_id:
            raise PermissionError("Unauthorized.")

        raw_questions = get_session_questions(session_id)
        submissions = get_session_submissions(session_id)
        session_lang = sess.get("programming_language")

        total_score = 0.0
        max_score = 0.0
        topic_stats: dict[str, dict[str, float]] = {}
        category_stats: dict[str, dict[str, float]] = {}

        for q in raw_questions:
            qid = q["id"]
            sub = submissions.get(qid, {})
            marks = float(q["marks"])
            max_score += marks

            subtopic = q["subtopic"]
            cat = q["category"]

            topic_stats.setdefault(subtopic, {"score": 0.0, "max": 0.0, "correct": 0, "total": 0})
            topic_stats[subtopic]["max"] += marks
            topic_stats[subtopic]["total"] += 1

            category_stats.setdefault(cat, {"score": 0.0, "max": 0.0})
            category_stats[cat]["max"] += marks

            if q["question_type"] != "coding_challenge":
                # Multiple choice / Output prediction evaluation
                selected = (sub.get("selected_option") or "").strip()
                correct_ans = (q.get("correct_answer") or "").strip()
                is_correct = 1 if (selected and selected.lower() == correct_ans.lower()) else 0
                awarded = marks if is_correct else 0.0
                total_score += awarded

                topic_stats[subtopic]["score"] += awarded
                if is_correct:
                    topic_stats[subtopic]["correct"] += 1
                category_stats[cat]["score"] += awarded

                save_or_update_submission(
                    session_id=session_id,
                    question_id=qid,
                    selected_option=selected,
                    code_submission=None,
                    is_correct=is_correct,
                    score_awarded=awarded,
                    max_score=marks,
                    test_cases_passed=1 if is_correct else 0,
                    test_cases_total=1,
                    execution_output_json=json.dumps({"is_correct": bool(is_correct)}),
                )
            else:
                # Coding Challenge evaluation against full test suite (predefined + hidden)
                user_code = sub.get("code_submission") or ""
                test_cases = json.loads(q.get("test_cases_json") or "[]")

                if user_code.strip():
                    eval_res = evaluate_code_submission(
                        language=session_lang,
                        code=user_code,
                        test_cases=test_cases,
                        is_sample_run=False,
                        max_marks=marks,
                    )
                    awarded = float(eval_res.get("score", 0.0))
                    passed_tc = eval_res.get("passed_tests", 0)
                    total_tc = eval_res.get("total_tests", len(test_cases))
                    is_correct = 1 if (passed_tc == total_tc and total_tc > 0) else 0
                else:
                    eval_res = {"error": "No code submitted", "test_results": []}
                    awarded = 0.0
                    passed_tc = 0
                    total_tc = len(test_cases)
                    is_correct = 0

                total_score += awarded
                topic_stats[subtopic]["score"] += awarded
                if is_correct:
                    topic_stats[subtopic]["correct"] += 1
                category_stats[cat]["score"] += awarded

                save_or_update_submission(
                    session_id=session_id,
                    question_id=qid,
                    selected_option=None,
                    code_submission=user_code,
                    is_correct=is_correct,
                    score_awarded=awarded,
                    max_score=marks,
                    test_cases_passed=passed_tc,
                    test_cases_total=total_tc,
                    execution_output_json=json.dumps(eval_res),
                )

        percentage = round((total_score / max_score) * 100, 1) if max_score > 0 else 0.0

        # Career Readiness Level determination
        if percentage >= 75.0:
            readiness_level = "Strong"
        elif percentage >= 50.0:
            readiness_level = "Developing"
        else:
            readiness_level = "Needs Improvement"

        # Topic Breakdown formatting
        breakdown = []
        for topic, data in topic_stats.items():
            acc = round((data["score"] / data["max"]) * 100, 1) if data["max"] > 0 else 0.0
            breakdown.append({
                "topic": topic,
                "score": data["score"],
                "max_score": data["max"],
                "accuracy": acc,
                "correct": data["correct"],
                "total": data["total"],
            })
        breakdown.sort(key=lambda x: x["accuracy"], reverse=True)

        strongest_skills = [b["topic"] for b in breakdown if b["accuracy"] >= 70.0][:3]
        weakest_skills = [b["topic"] for b in reversed(breakdown) if b["accuracy"] < 60.0][:3]

        # Skill-Gap Analysis and Recommendations Connection
        skill_gap_analysis = cls.build_skill_gap_analysis(
            user_id=user_id,
            target_role=sess["target_role"],
            programming_language=session_lang,
            weakest_topics=weakest_skills,
            strongest_topics=strongest_skills,
            percentage=percentage,
        )

        finalize_assessment_session(
            session_id=session_id,
            total_score=round(total_score, 1),
            max_score=round(max_score, 1),
            percentage=percentage,
            readiness_level=readiness_level,
            topic_breakdown_json=json.dumps(breakdown),
            skill_gap_analysis_json=json.dumps(skill_gap_analysis),
        )

        return {
            "session_id": session_id,
            "total_score": round(total_score, 1),
            "max_score": round(max_score, 1),
            "percentage": percentage,
            "readiness_level": readiness_level,
            "breakdown": breakdown,
            "strongest_skills": strongest_skills,
            "weakest_skills": weakest_skills,
            "skill_gap_analysis": skill_gap_analysis,
        }

    @staticmethod
    def build_skill_gap_analysis(
        user_id: int,
        target_role: str,
        programming_language: str | None,
        weakest_topics: list[str],
        strongest_topics: list[str],
        percentage: float,
    ) -> dict[str, Any]:
        """
        Synthesizes assessment performance with existing ESCO career recommendations.
        Identifies verified skills vs demonstrated skill gaps.
        """
        recs = get_user_recommendations(user_id)
        resume_skills = []
        if recs:
            try:
                res_data = json.loads(recs[0]["result_json"])
                if res_data and isinstance(res_data, list):
                    resume_skills = res_data[0].get("match", [])
            except Exception:
                pass

        actionable_recommendations = []
        if programming_language == "python":
            if any("Comprehensions" in t or "Generators" in t or "Collections" in t for t in weakest_topics):
                actionable_recommendations.append(
                    "Reinforce Python standard libraries (itertools, collections.deque, Counter) and generator expressions."
                )
            if any("OOP" in t or "Dunder" in t for t in weakest_topics):
                actionable_recommendations.append(
                    "Practice Python Object-Oriented patterns, dunder methods (__str__, __call__), and class inheritance."
                )
            if any("Arrays" in t or "Dynamic Programming" in t or "Kadane" in t for t in weakest_topics):
                actionable_recommendations.append(
                    "Solve medium-level algorithmic challenges on two-pointers, hash tables, and Kadane's algorithm."
                )
        elif programming_language == "java":
            if any("Collections" in t or "HashMap" in t or "List" in t for t in weakest_topics):
                actionable_recommendations.append(
                    "Deepen understanding of Java Collections Framework internals (HashMap red-black trees, ArrayList vs LinkedList)."
                )
            if any("OOP" in t or "Polymorphism" in t or "Interface" in t for t in weakest_topics):
                actionable_recommendations.append(
                    "Review Java OOP fundamentals: dynamic method dispatch, interface default methods, and constructor chaining."
                )
            if any("Concurrency" in t or "Memory" in t for t in weakest_topics):
                actionable_recommendations.append(
                    "Study JVM memory architecture (Stack vs Heap, garbage collection) and multithreading synchronization."
                )

        if any("Quantitative" in t for t in weakest_topics):
            actionable_recommendations.append(
                "Revise speed-distance-time, percentages, and profit & loss calculation shortcuts for campus placements."
            )
        if any("Logical" in t or "Analytical" in t for t in weakest_topics):
            actionable_recommendations.append(
                "Practice seating arrangement puzzles, syllogisms, and direction sense reasoning tests."
            )

        if not actionable_recommendations:
            actionable_recommendations.append(
                f"Maintain your strong score with continuous practice on advanced placement challenges for {target_role}."
            )

        return {
            "target_role": target_role,
            "programming_language": programming_language,
            "resume_skills": resume_skills,
            "demonstrated_strengths": strongest_topics,
            "identified_lagging_skills": weakest_topics,
            "learning_recommendations": actionable_recommendations,
            "career_readiness_advice": (
                f"Your performance indicates a {percentage}% readiness index for entry-level {target_role} recruitment rounds. "
                "Target the recommended practice areas to maximize your technical interview success."
            ),
        }

    @classmethod
    def get_review_data(cls, session_id: str, user_id: int) -> dict[str, Any]:
        """
        Retrieves full answer review: submitted answer, correct answer,
        explanation, test case outputs, and language-specific reference solutions.
        """
        sess = get_assessment_session(session_id)
        if not sess:
            raise KeyError("Session not found.")
        if sess["user_id"] != user_id:
            raise PermissionError("Unauthorized.")

        questions = get_session_questions(session_id)
        submissions = get_session_submissions(session_id)
        session_lang = sess.get("programming_language")

        review_items = []
        for q in questions:
            qid = q["id"]
            sub = submissions.get(qid, {})
            is_coding = q["question_type"] == "coding_challenge"

            # Parse execution outputs if coding challenge
            exec_out = {}
            if is_coding and sub.get("execution_output_json"):
                try:
                    exec_out = json.loads(sub["execution_output_json"])
                except Exception:
                    pass

            shuffled_opts = json.loads(q.get("shuffled_options_json") or "[]")
            if not shuffled_opts and q.get("options_json"):
                shuffled_opts = json.loads(q["options_json"])

            review_items.append({
                "order_index": q["order_index"],
                "id": q["id"],
                "category": q["category"],
                "question_type": q["question_type"],
                "subtopic": q["subtopic"],
                "difficulty": q["difficulty"],
                "question_text": q["question_text"],
                "code_snippet": q["code_snippet"],
                "options": shuffled_opts,
                "user_selected_option": sub.get("selected_option"),
                "user_code_submission": sub.get("code_submission"),
                "correct_answer": q["correct_answer"],
                "explanation": q["explanation"],
                "reference_solution": q["reference_solution"] if is_coding else None,
                "is_correct": bool(sub.get("is_correct")),
                "score_awarded": sub.get("score_awarded", 0.0),
                "max_score": q["marks"],
                "test_cases_passed": sub.get("test_cases_passed", 0),
                "test_cases_total": sub.get("test_cases_total", 0),
                "execution_output": exec_out,
            })

        return {
            "session": sess,
            "review_items": review_items,
            "items": review_items,
        }
