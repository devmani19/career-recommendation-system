"""Comprehensive test suite for Career Readiness Assessment Module.

Validates:
- Functional assessment workflow from navigation to results review
- Question bank counts: >= 250 validated questions (100+ apt, 50+ py tech, 25+ py code, 50+ java tech, 25+ java code)
- Mandatory Python and Java strict separation (Tests 1-11 from prompt specification)
- Answer validation, scoring, and partial credit evaluation
- Code execution security and isolation
- User authorization and privacy guards
"""

import json
import pytest
from app import create_app
from app.db import (
    get_all_assessment_questions,
    get_assessment_question_counts,
    get_assessment_session,
    get_db_connection,
    get_session_questions,
)
from app.services.assessment_service import AssessmentService
from app.services.code_executor import evaluate_code_submission, run_python_test


@pytest.fixture
def app_client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def auth_user1():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "demo"
        yield client


@pytest.fixture
def auth_user2():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 2
            sess["username"] = "admin"
        yield client


# ── 1. Minimum Question Bank Size Requirements ─────────────────────────────


def test_question_bank_minimum_counts():
    """Confirms at least 250 actual unique validated question records exist in database."""
    counts_rows = get_assessment_question_counts()
    category_totals = {}
    for r in counts_rows:
        cat = r["category"]
        qtype = r["question_type"]
        category_totals.setdefault(cat, {"total": 0, "types": {}})
        category_totals[cat]["total"] += r["count"]
        category_totals[cat]["types"][qtype] = r["count"]

    # 1. Aptitude: at least 100
    apt_count = category_totals.get("aptitude", {}).get("total", 0)
    assert apt_count >= 100, f"Expected >= 100 aptitude questions, found {apt_count}"

    # 2. Python technical: at least 50
    py_tech = (
        category_totals.get("python", {}).get("types", {}).get("multiple_choice", 0)
        + category_totals.get("python", {}).get("types", {}).get("output_prediction", 0)
    )
    assert py_tech >= 50, f"Expected >= 50 Python technical questions, found {py_tech}"

    # 3. Python coding challenges: at least 25
    py_code = category_totals.get("python", {}).get("types", {}).get("coding_challenge", 0)
    assert py_code >= 25, f"Expected >= 25 Python coding challenges, found {py_code}"

    # 4. Java technical: at least 50
    java_tech = (
        category_totals.get("java", {}).get("types", {}).get("multiple_choice", 0)
        + category_totals.get("java", {}).get("types", {}).get("output_prediction", 0)
    )
    assert java_tech >= 50, f"Expected >= 50 Java technical questions, found {java_tech}"

    # 5. Java coding challenges: at least 25
    java_code = category_totals.get("java", {}).get("types", {}).get("coding_challenge", 0)
    assert java_code >= 25, f"Expected >= 25 Java coding challenges, found {java_code}"

    # 6. Overall total: >= 250
    total_questions = sum(c["total"] for c in category_totals.values())
    assert total_questions >= 250, f"Expected >= 250 total questions, found {total_questions}"


# ── 2. Mandatory Programming Language Separation Tests (Tests 1-11) ────────


def test_mandatory_separation_test_1_python_coding():
    """Test 1: Select Python Coding Assessment. Confirm that only Python technical questions and Python coding challenges appear."""
    session_id = AssessmentService.create_session(
        user_id=1,
        assessment_type="python_coding",
        programming_language="python",
    )
    sess = get_assessment_session(session_id)
    assert sess["assessment_type"] == "python_coding"
    assert sess["programming_language"] == "python"

    questions = get_session_questions(session_id)
    assert len(questions) == 18, f"Expected 18 questions (15 tech + 3 coding), got {len(questions)}"

    # Confirm strict Python exclusivity
    for q in questions:
        assert q["category"] == "python", f"Found non-Python question {q['id']} in Python test!"
        assert q["category"] != "java", "Java question leaked into Python session!"

    coding_challenges = [q for q in questions if q["question_type"] == "coding_challenge"]
    assert len(coding_challenges) == 3


def test_mandatory_separation_test_2_java_coding():
    """Test 2: Select Java Coding Assessment. Confirm that only Java technical questions and Java coding challenges appear."""
    session_id = AssessmentService.create_session(
        user_id=1,
        assessment_type="java_coding",
        programming_language="java",
    )
    sess = get_assessment_session(session_id)
    assert sess["assessment_type"] == "java_coding"
    assert sess["programming_language"] == "java"

    questions = get_session_questions(session_id)
    assert len(questions) == 18, f"Expected 18 questions (15 tech + 3 coding), got {len(questions)}"

    # Confirm strict Java exclusivity
    for q in questions:
        assert q["category"] == "java", f"Found non-Java question {q['id']} in Java test!"
        assert q["category"] != "python", "Python question leaked into Java session!"

    coding_challenges = [q for q in questions if q["question_type"] == "coding_challenge"]
    assert len(coding_challenges) == 3


def test_mandatory_separation_test_3_full_assessment_python():
    """Test 3: Select Full Career Readiness Assessment and choose Python. Confirm test includes 20 aptitude, 10 Python tech, 2 Python coding."""
    session_id = AssessmentService.create_session(
        user_id=1,
        assessment_type="full_assessment",
        programming_language="python",
    )
    sess = get_assessment_session(session_id)
    assert sess["programming_language"] == "python"

    questions = get_session_questions(session_id)
    assert len(questions) == 32, f"Expected 32 questions (20 apt + 10 py tech + 2 py code), got {len(questions)}"

    apt_qs = [q for q in questions if q["category"] == "aptitude"]
    py_tech = [q for q in questions if q["category"] == "python" and q["question_type"] != "coding_challenge"]
    py_code = [q for q in questions if q["category"] == "python" and q["question_type"] == "coding_challenge"]
    java_qs = [q for q in questions if q["category"] == "java"]

    assert len(apt_qs) == 20
    assert len(py_tech) == 10
    assert len(py_code) == 2
    assert len(java_qs) == 0, "No Java questions may appear in Python Full Assessment!"


def test_mandatory_separation_test_4_full_assessment_java():
    """Test 4: Select Full Career Readiness Assessment and choose Java. Confirm test includes 20 aptitude, 10 Java tech, 2 Java coding."""
    session_id = AssessmentService.create_session(
        user_id=1,
        assessment_type="full_assessment",
        programming_language="java",
    )
    sess = get_assessment_session(session_id)
    assert sess["programming_language"] == "java"

    questions = get_session_questions(session_id)
    assert len(questions) == 32, f"Expected 32 questions (20 apt + 10 java tech + 2 java code), got {len(questions)}"

    apt_qs = [q for q in questions if q["category"] == "aptitude"]
    java_tech = [q for q in questions if q["category"] == "java" and q["question_type"] != "coding_challenge"]
    java_code = [q for q in questions if q["category"] == "java" and q["question_type"] == "coding_challenge"]
    py_qs = [q for q in questions if q["category"] == "python"]

    assert len(apt_qs) == 20
    assert len(java_tech) == 10
    assert len(java_code) == 2
    assert len(py_qs) == 0, "No Python questions may appear in Java Full Assessment!"


def test_mandatory_separation_test_5_reject_python_in_java_session(auth_user1):
    """Test 5: Send a Python submission to a Java assessment endpoint. Confirm backend rejects."""
    session_id = AssessmentService.create_session(
        user_id=1,
        assessment_type="java_coding",
        programming_language="java",
    )
    res = auth_user1.post(
        "/assessment/api/run-code",
        json={
            "session_id": session_id,
            "question_id": "java_code_001",
            "code": "print('hello')",
            "language": "python",  # Mismatched language!
        },
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert "Language mismatch" in data["error"]


def test_mandatory_separation_test_6_reject_java_in_python_session(auth_user1):
    """Test 6: Send a Java submission to a Python assessment endpoint. Confirm backend rejects."""
    session_id = AssessmentService.create_session(
        user_id=1,
        assessment_type="python_coding",
        programming_language="python",
    )
    res = auth_user1.post(
        "/assessment/api/run-code",
        json={
            "session_id": session_id,
            "question_id": "py_code_001",
            "code": "public class Solution { public static void main(String[] args) {} }",
            "language": "java",  # Mismatched language!
        },
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert "Language mismatch" in data["error"]


def test_mandatory_separation_test_7_refresh_resumes_cleanly(auth_user1):
    """Test 7: Refresh or resume an assessment. Confirm original language and assigned questions remain unchanged."""
    session_id = AssessmentService.create_session(
        user_id=1,
        assessment_type="full_assessment",
        programming_language="python",
    )
    # Fetch questions initially
    data1 = AssessmentService.get_active_session_data(session_id, user_id=1)
    q_ids_1 = [q["id"] for q in data1["questions"]]

    # Save an answer
    AssessmentService.save_answer(session_id, user_id=1, question_id=q_ids_1[0], selected_option="Sample Option")

    # Resume / fetch again
    data2 = AssessmentService.get_active_session_data(session_id, user_id=1)
    q_ids_2 = [q["id"] for q in data2["questions"]]

    assert q_ids_1 == q_ids_2, "Assigned questions changed upon resume!"
    assert data2["session"]["programming_language"] == "python"
    assert data2["questions"][0]["saved_selected_option"] == "Sample Option"


def test_mandatory_separation_test_8_review_python_no_java():
    """Test 8: Review a completed Python assessment. Confirm Java questions and reference solutions are not displayed."""
    session_id = AssessmentService.create_session(
        user_id=1,
        assessment_type="python_coding",
        programming_language="python",
    )
    AssessmentService.finalize_and_score_session(session_id, user_id=1)
    review = AssessmentService.get_review_data(session_id, user_id=1)

    for item in review["items"]:
        assert item["category"] == "python"
        if item["reference_solution"]:
            assert "class Solution" not in item["reference_solution"]
            assert "import sys" in item["reference_solution"] or "def " in item["reference_solution"]


def test_mandatory_separation_test_9_review_java_no_python():
    """Test 9: Review a completed Java assessment. Confirm Python questions and reference solutions are not displayed."""
    session_id = AssessmentService.create_session(
        user_id=1,
        assessment_type="java_coding",
        programming_language="java",
    )
    AssessmentService.finalize_and_score_session(session_id, user_id=1)
    review = AssessmentService.get_review_data(session_id, user_id=1)

    for item in review["items"]:
        assert item["category"] == "java"
        if item["reference_solution"]:
            assert "def solve()" not in item["reference_solution"]
            assert "public class Solution" in item["reference_solution"]


def test_mandatory_separation_test_10_randomization_preserves_separation():
    """Test 10: Randomize questions across 3 sessions; confirm counts and strict separation are preserved."""
    for _ in range(3):
        sid_py = AssessmentService.create_session(user_id=1, assessment_type="python_coding", programming_language="python")
        qs_py = get_session_questions(sid_py)
        assert len(qs_py) == 18
        assert all(q["category"] == "python" for q in qs_py)

        sid_java = AssessmentService.create_session(user_id=1, assessment_type="java_coding", programming_language="java")
        qs_java = get_session_questions(sid_java)
        assert len(qs_java) == 18
        assert all(q["category"] == "java" for q in qs_java)


def test_mandatory_separation_test_11_security_and_hidden_answers(auth_user1, auth_user2):
    """Test 11: Verify correct answers remain hidden during active test, and users cannot access another user's session."""
    session_id = AssessmentService.create_session(user_id=1, assessment_type="aptitude")

    # 1. Active test data must NOT reveal correct answers or explanations
    active_data = AssessmentService.get_active_session_data(session_id, user_id=1)
    for q in active_data["questions"]:
        assert "correct_answer" not in q
        assert "explanation" not in q

    # 2. User 2 cannot access User 1's active session
    with pytest.raises(PermissionError):
        AssessmentService.get_active_session_data(session_id, user_id=2)

    # 3. HTTP endpoint rejects User 2 from accessing User 1's session
    res = auth_user2.get(f"/assessment/session/{session_id}")
    assert res.status_code == 403


# ── 3. Code Execution & Security Tests ─────────────────────────────────────


def test_python_code_execution_sample_pass():
    """Executes a valid Python solution against sample test cases."""
    code = (
        "import sys\n"
        "def solve():\n"
        "    nums = [int(x) for x in sys.stdin.read().split()]\n"
        "    if nums:\n"
        "        print(sum(nums))\n"
        "solve()\n"
    )
    test_cases = [
        {"input": "2 3 5", "expected_output": "10", "is_hidden": False},
        {"input": "1 1", "expected_output": "2", "is_hidden": False},
    ]
    res = evaluate_code_submission("python", code, test_cases, is_sample_run=True)
    assert res["success"] is True
    assert res["passed_tests"] == 2


def test_python_code_security_sandbox():
    """Verifies that malicious Python code attempting restricted module import is blocked."""
    bad_code = "import os\nos.system('echo hacked')\n"
    test_cases = [{"input": "", "expected_output": "", "is_hidden": False}]
    res = evaluate_code_submission("python", bad_code, test_cases)
    assert res["success"] is False
    assert "Security Violation" in res.get("error", "")


def test_java_code_execution_sample_pass():
    """Executes a valid Java solution against sample test cases using javac and java."""
    code = (
        "import java.util.*;\n"
        "public class Solution {\n"
        "    public static void main(String[] args) {\n"
        "        Scanner sc = new Scanner(System.in);\n"
        "        int sum = 0;\n"
        "        while (sc.hasNextInt()) sum += sc.nextInt();\n"
        "        System.out.println(sum);\n"
        "    }\n"
        "}\n"
    )
    test_cases = [
        {"input": "10 20 30", "expected_output": "60", "is_hidden": False},
        {"input": "5", "expected_output": "5", "is_hidden": False},
    ]
    res = evaluate_code_submission("java", code, test_cases, is_sample_run=True)
    assert res["success"] is True
    assert res["passed_tests"] == 2


# ── 4. End-to-End Scoring and Result Workflow ──────────────────────────────


def test_scoring_and_skill_gap_generation():
    """Simulates answering an assessment, scoring it, and validating skill gap output."""
    session_id = AssessmentService.create_session(
        user_id=1,
        assessment_type="python_coding",
        programming_language="python",
    )
    questions = get_session_questions(session_id)

    # Submit correct answer for first question
    q0 = questions[0]
    AssessmentService.save_answer(
        session_id=session_id,
        user_id=1,
        question_id=q0["id"],
        selected_option=q0["correct_answer"],
    )

    # Finalize and score
    result = AssessmentService.finalize_and_score_session(session_id, user_id=1)
    assert "percentage" in result
    assert "readiness_level" in result
    assert result["readiness_level"] in {"Strong", "Developing", "Needs Improvement"}
    assert "skill_gap_analysis" in result

    # Check skill gap analysis structure
    sg = result["skill_gap_analysis"]
    assert sg["programming_language"] == "python"
    assert "learning_recommendations" in sg
    assert len(sg["learning_recommendations"]) > 0
