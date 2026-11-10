"""Question Bank Seeding and Automated Validation Script.

Validates and seeds at least 250 genuine questions:
- Aptitude questions: >= 100
- Python technical questions: >= 50
- Python coding challenges: >= 25
- Java technical questions: >= 50
- Java coding challenges: >= 25

Validates all MCQs and runs reference solutions against test cases.
Outputs validated data to data/assessment_questions.json and seeds data/career_app.db.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.data_aptitude_questions import APTITUDE_QUESTIONS
from scripts.data_python_questions import PYTHON_CODING_CHALLENGES, PYTHON_TECHNICAL_QUESTIONS
from scripts.data_java_questions import JAVA_CODING_CHALLENGES, JAVA_TECHNICAL_QUESTIONS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_questions")


def validate_python_code(code: str, test_cases: list[dict]) -> tuple[bool, str]:
    """Runs a Python reference solution against test cases to verify validity."""
    with tempfile.TemporaryDirectory() as td:
        script_path = os.path.join(td, "solution.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        for i, tc in enumerate(test_cases):
            inp = tc["input"]
            expected = tc["expected_output"].strip()
            try:
                proc = subprocess.run(
                    [sys.executable, script_path],
                    input=inp,
                    capture_output=True,
                    text=True,
                    timeout=4.0,
                )
                actual = proc.stdout.strip()
                if proc.returncode != 0:
                    return False, f"Test case {i+1} failed with error: {proc.stderr}"
                if actual != expected:
                    # Allow trailing newline or whitespace differences
                    if actual.split() != expected.split():
                        return False, f"Test case {i+1} mismatch. Expected '{expected}', got '{actual}'"
            except subprocess.TimeoutExpired:
                return False, f"Test case {i+1} timed out"
    return True, "All tests passed"


def validate_java_code(code: str, test_cases: list[dict]) -> tuple[bool, str]:
    """Compiles and runs a Java reference solution against test cases to verify validity."""
    with tempfile.TemporaryDirectory() as td:
        java_path = os.path.join(td, "Solution.java")
        with open(java_path, "w", encoding="utf-8") as f:
            f.write(code)

        # Compile
        comp = subprocess.run(["javac", java_path], capture_output=True, text=True, timeout=6.0)
        if comp.returncode != 0:
            return False, f"Java compilation error: {comp.stderr}"

        for i, tc in enumerate(test_cases):
            inp = tc["input"]
            expected = tc["expected_output"].strip()
            try:
                proc = subprocess.run(
                    ["java", "-cp", td, "Solution"],
                    input=inp,
                    capture_output=True,
                    text=True,
                    timeout=5.0,
                )
                actual = proc.stdout.strip()
                if proc.returncode != 0:
                    return False, f"Test case {i+1} failed with error: {proc.stderr}"
                if actual != expected:
                    if actual.split() != expected.split():
                        return False, f"Test case {i+1} mismatch. Expected '{expected}', got '{actual}'"
            except subprocess.TimeoutExpired:
                return False, f"Test case {i+1} timed out"
    return True, "All tests passed"


def validate_all_questions() -> tuple[list[dict], dict[str, int]]:
    """Validates every question record against quality criteria."""
    all_questions = []
    seen_ids = set()

    counts = {
        "aptitude": 0,
        "python_technical": 0,
        "python_coding": 0,
        "java_technical": 0,
        "java_coding": 0,
    }

    # 1. Aptitude
    for q in APTITUDE_QUESTIONS:
        qid = q["id"]
        assert qid not in seen_ids, f"Duplicate ID {qid}"
        seen_ids.add(qid)
        assert q["correct_answer"] in q["options"], f"Correct answer not in options for {qid}"
        assert len(q["options"]) == 4, f"Options count != 4 for {qid}"
        assert q["explanation"].strip(), f"Missing explanation for {qid}"
        q["version"] = "1.0.0"
        q["validation_status"] = "validated"
        all_questions.append(q)
        counts["aptitude"] += 1

    # 2. Python Technical
    for q in PYTHON_TECHNICAL_QUESTIONS:
        qid = q["id"]
        assert qid not in seen_ids, f"Duplicate ID {qid}"
        seen_ids.add(qid)
        assert q["correct_answer"] in q["options"], f"Correct answer not in options for {qid}"
        assert len(q["options"]) == 4, f"Options count != 4 for {qid}"
        assert q["explanation"].strip(), f"Missing explanation for {qid}"
        q["version"] = "1.0.0"
        q["validation_status"] = "validated"
        all_questions.append(q)
        counts["python_technical"] += 1

    # 3. Python Coding Challenges (run code validation)
    logger.info("Validating %d Python coding challenge reference solutions...", len(PYTHON_CODING_CHALLENGES))
    for q in PYTHON_CODING_CHALLENGES:
        qid = q["id"]
        assert qid not in seen_ids, f"Duplicate ID {qid}"
        seen_ids.add(qid)
        assert len(q["test_cases"]) >= 3, f"Fewer than 3 test cases for {qid}"
        ok, msg = validate_python_code(q["reference_solution"], q["test_cases"])
        if not ok:
            raise RuntimeError(f"Python coding challenge {qid} failed validation: {msg}")
        q["version"] = "1.0.0"
        q["validation_status"] = "validated"
        all_questions.append(q)
        counts["python_coding"] += 1

    # 4. Java Technical
    for q in JAVA_TECHNICAL_QUESTIONS:
        qid = q["id"]
        assert qid not in seen_ids, f"Duplicate ID {qid}"
        seen_ids.add(qid)
        assert q["correct_answer"] in q["options"], f"Correct answer not in options for {qid}"
        assert len(q["options"]) == 4, f"Options count != 4 for {qid}"
        assert q["explanation"].strip(), f"Missing explanation for {qid}"
        q["version"] = "1.0.0"
        q["validation_status"] = "validated"
        all_questions.append(q)
        counts["java_technical"] += 1

    # 5. Java Coding Challenges (compile and run validation)
    logger.info("Validating %d Java coding challenge reference solutions...", len(JAVA_CODING_CHALLENGES))
    for q in JAVA_CODING_CHALLENGES:
        qid = q["id"]
        assert qid not in seen_ids, f"Duplicate ID {qid}"
        seen_ids.add(qid)
        assert len(q["test_cases"]) >= 3, f"Fewer than 3 test cases for {qid}"
        ok, msg = validate_java_code(q["reference_solution"], q["test_cases"])
        if not ok:
            raise RuntimeError(f"Java coding challenge {qid} failed validation: {msg}")
        q["version"] = "1.0.0"
        q["validation_status"] = "validated"
        all_questions.append(q)
        counts["java_coding"] += 1

    return all_questions, counts


def seed_database(questions: list[dict], db_path: Path) -> None:
    """Creates tables if not existing and seeds questions into sqlite database."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS assessment_questions (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            question_type TEXT NOT NULL,
            subtopic TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            question_text TEXT NOT NULL,
            code_snippet TEXT,
            options_json TEXT,
            correct_answer TEXT NOT NULL,
            explanation TEXT,
            test_cases_json TEXT,
            reference_solution TEXT,
            marks INTEGER DEFAULT 1,
            target_roles_json TEXT,
            version TEXT DEFAULT '1.0.0',
            validation_status TEXT DEFAULT 'validated',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS assessment_sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            assessment_type TEXT NOT NULL,
            programming_language TEXT,
            target_role TEXT,
            duration_minutes INTEGER NOT NULL,
            status TEXT DEFAULT 'in_progress',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            total_score REAL DEFAULT 0.0,
            max_score REAL DEFAULT 0.0,
            percentage REAL DEFAULT 0.0,
            readiness_level TEXT,
            topic_breakdown_json TEXT,
            skill_gap_analysis_json TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS assessment_session_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            question_id TEXT NOT NULL,
            order_index INTEGER NOT NULL,
            shuffled_options_json TEXT,
            FOREIGN KEY (session_id) REFERENCES assessment_sessions(id),
            FOREIGN KEY (question_id) REFERENCES assessment_questions(id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS assessment_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            question_id TEXT NOT NULL,
            selected_option TEXT,
            code_submission TEXT,
            is_correct INTEGER,
            score_awarded REAL DEFAULT 0.0,
            max_score REAL DEFAULT 0.0,
            test_cases_passed INTEGER DEFAULT 0,
            test_cases_total INTEGER DEFAULT 0,
            execution_output_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(session_id, question_id),
            FOREIGN KEY (session_id) REFERENCES assessment_sessions(id),
            FOREIGN KEY (question_id) REFERENCES assessment_questions(id)
        )
        """
    )

    # Insert or replace questions
    for q in questions:
        cur.execute(
            """
            INSERT OR REPLACE INTO assessment_questions (
                id, category, question_type, subtopic, difficulty,
                question_text, code_snippet, options_json, correct_answer,
                explanation, test_cases_json, reference_solution, marks,
                target_roles_json, version, validation_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                q["id"],
                q["category"],
                q["question_type"],
                q["subtopic"],
                q["difficulty"],
                q["question_text"],
                q.get("code_snippet") or q.get("starter_code") or "",
                json.dumps(q.get("options", [])),
                q.get("correct_answer", ""),
                q.get("explanation", ""),
                json.dumps(q.get("test_cases", [])),
                q.get("reference_solution", ""),
                q.get("marks", 1),
                json.dumps(q.get("target_roles", [])),
                q.get("version", "1.0.0"),
                q.get("validation_status", "validated"),
            ),
        )

    conn.commit()
    conn.close()
    logger.info("Successfully seeded %d questions into %s", len(questions), db_path)


def main():
    logger.info("Starting question bank validation and seeding...")
    questions, counts = validate_all_questions()

    total = len(questions)
    logger.info("=== QUESTION BANK VALIDATION SUMMARY ===")
    logger.info("Aptitude Questions:          %d (Minimum required: 100)", counts["aptitude"])
    logger.info("Python Technical Questions:  %d (Minimum required: 50)", counts["python_technical"])
    logger.info("Python Coding Challenges:    %d (Minimum required: 25)", counts["python_coding"])
    logger.info("Java Technical Questions:    %d (Minimum required: 50)", counts["java_technical"])
    logger.info("Java Coding Challenges:      %d (Minimum required: 25)", counts["java_coding"])
    logger.info("TOTAL VALIDATED QUESTIONS:   %d (Minimum required: 250)", total)

    # Enforce minimum criteria
    assert counts["aptitude"] >= 100, f"Aptitude count {counts['aptitude']} < 100"
    assert counts["python_technical"] >= 50, f"Python technical count {counts['python_technical']} < 50"
    assert counts["python_coding"] >= 25, f"Python coding count {counts['python_coding']} < 25"
    assert counts["java_technical"] >= 50, f"Java technical count {counts['java_technical']} < 50"
    assert counts["java_coding"] >= 25, f"Java coding count {counts['java_coding']} < 25"
    assert total >= 250, f"Total count {total} < 250"

    # Export to JSON
    json_path = BASE_DIR / "data" / "assessment_questions.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(questions, f, indent=2)
    logger.info("Saved question bank JSON to %s", json_path)

    # Seed SQLite database
    db_path = BASE_DIR / "data" / "career_app.db"
    seed_database(questions, db_path)
    logger.info("Question bank seeding complete and validated.")


if __name__ == "__main__":
    main()
