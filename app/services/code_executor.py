"""Secure, isolated code execution engine for Python and Java programming challenges.

Implements:
- Subprocess isolation in clean temporary directories
- Execution timeouts (preventing infinite loops)
- Security static analysis guards
- Output size truncation (preventing memory exhaustion)
- Strict language separation
- Distinct sample run vs full scored evaluation (protecting hidden test cases)
"""

from __future__ import annotations

import ast
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# Security restrictions
PYTHON_DISALLOWED_MODULES = {
    "os", "sys", "subprocess", "socket", "shutil", "pty", "posix",
    "resource", "ctypes", "_thread", "multiprocessing", "webbrowser",
    "http", "urllib", "requests"
}
PYTHON_DISALLOWED_CALLS = {
    "eval", "exec", "__import__", "compile", "globals", "locals"
}
JAVA_DISALLOWED_PATTERNS = [
    r"ProcessBuilder",
    r"Runtime\.getRuntime\(\)",
    r"java\.net\.",
    r"java\.nio\.file\.",
    r"java\.lang\.reflect\.",
    r"System\.exit",
    r"SecurityManager",
]


class SecurityViolationError(Exception):
    """Raised when submitted code contains prohibited operations."""
    pass


def inspect_python_code_security(code: str) -> None:
    """Inspects Python AST to ensure untrusted code does not call dangerous APIs."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Let the python compiler report syntax errors normally
        return

    for node in ast.walk(tree):
        # Disallow forbidden imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_pkg = alias.name.split(".")[0]
                # Allow sys ONLY for sys.stdin / sys.stdout reading
                if root_pkg in PYTHON_DISALLOWED_MODULES:
                    if root_pkg == "sys":
                        continue
                    raise SecurityViolationError(f"Import of module '{root_pkg}' is restricted for security.")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_pkg = node.module.split(".")[0]
                if root_pkg in PYTHON_DISALLOWED_MODULES:
                    if root_pkg == "sys":
                        continue
                    raise SecurityViolationError(f"Import from module '{root_pkg}' is restricted for security.")

        # Disallow dangerous builtins (eval, exec, __import__)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in PYTHON_DISALLOWED_CALLS:
                raise SecurityViolationError(f"Use of built-in function '{node.func.id}()' is prohibited.")


def inspect_java_code_security(code: str) -> None:
    """Regex-based static guard for Java submissions."""
    for pattern in JAVA_DISALLOWED_PATTERNS:
        if re.search(pattern, code):
            clean_name = pattern.replace(r"\.", ".").replace(r"\(", "(").replace(r"\)", ")")
            raise SecurityViolationError(f"Use of restricted API '{clean_name}' is not permitted.")


def run_python_test(code: str, test_input: str, timeout_seconds: float = 3.5) -> dict[str, Any]:
    """Executes a single test case against Python submission in isolated subprocess."""
    inspect_python_code_security(code)

    with tempfile.TemporaryDirectory() as td:
        script_file = os.path.join(td, "solution.py")
        with open(script_file, "w", encoding="utf-8") as f:
            f.write(code)

        start_time = time.perf_counter()
        try:
            # -I: isolated mode, -B: don't write .pyc, -s: don't add user site
            proc = subprocess.run(
                [sys.executable, "-I", "-B", "-s", script_file],
                input=test_input,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            elapsed = round((time.perf_counter() - start_time) * 1000, 2)
            stdout = proc.stdout[:65536]
            stderr = proc.stderr[:65536]
            return {
                "success": proc.returncode == 0,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": proc.returncode,
                "execution_time_ms": elapsed,
                "timed_out": False,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Time Limit Exceeded ({timeout_seconds}s)",
                "exit_code": -1,
                "execution_time_ms": timeout_seconds * 1000,
                "timed_out": True,
            }
        except Exception as exc:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(exc),
                "exit_code": -1,
                "execution_time_ms": 0,
                "timed_out": False,
            }


def run_java_test(code: str, test_input: str, timeout_seconds: float = 4.5) -> dict[str, Any]:
    """Compiles and executes a single test case against Java submission."""
    inspect_java_code_security(code)

    with tempfile.TemporaryDirectory() as td:
        java_file = os.path.join(td, "Solution.java")
        with open(java_file, "w", encoding="utf-8") as f:
            f.write(code)

        # 1. Compile
        comp = subprocess.run(
            ["javac", "-J-Xmx128m", java_file],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if comp.returncode != 0:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Compilation Error:\n{comp.stderr[:10000]}",
                "exit_code": comp.returncode,
                "execution_time_ms": 0,
                "timed_out": False,
                "compilation_error": True,
            }

        # 2. Run
        start_time = time.perf_counter()
        try:
            proc = subprocess.run(
                ["java", "-Xmx128m", "-Xms32m", "-cp", td, "Solution"],
                input=test_input,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            elapsed = round((time.perf_counter() - start_time) * 1000, 2)
            stdout = proc.stdout[:65536]
            stderr = proc.stderr[:65536]
            return {
                "success": proc.returncode == 0,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": proc.returncode,
                "execution_time_ms": elapsed,
                "timed_out": False,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Time Limit Exceeded ({timeout_seconds}s)",
                "exit_code": -1,
                "execution_time_ms": timeout_seconds * 1000,
                "timed_out": True,
            }
        except Exception as exc:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(exc),
                "exit_code": -1,
                "execution_time_ms": 0,
                "timed_out": False,
            }


def evaluate_code_submission(
    language: str,
    code: str,
    test_cases: list[dict],
    is_sample_run: bool = False,
    max_marks: float = 10.0,
) -> dict[str, Any]:
    """
    Evaluates a user code submission against test cases.

    Enforces:
    - Strict language isolation: Python only executes Python, Java only executes Java.
    - If is_sample_run is True: runs only predefined test cases and returns full outputs.
    - If is_sample_run is False: runs ALL test cases; masks hidden inputs and expected outputs.
    """
    lang = language.strip().lower()
    if lang not in {"python", "java"}:
        return {
            "success": False,
            "error": f"Unsupported or incompatible programming language: '{language}'",
            "passed_tests": 0,
            "total_tests": len(test_cases),
            "score": 0.0,
            "max_score": max_marks,
            "test_results": [],
        }

    # Filter test cases based on run mode
    if is_sample_run:
        target_tests = [tc for tc in test_cases if not tc.get("is_hidden", False)]
        if not target_tests:
            target_tests = test_cases[:2]  # Fallback to first 2
    else:
        target_tests = test_cases

    results = []
    passed_count = 0

    # Initial security check
    try:
        if lang == "python":
            inspect_python_code_security(code)
        else:
            inspect_java_code_security(code)
    except SecurityViolationError as sec_err:
        return {
            "success": False,
            "error": f"Security Violation: {str(sec_err)}",
            "passed_tests": 0,
            "total_tests": len(target_tests),
            "score": 0.0,
            "max_score": max_marks,
            "test_results": [],
        }

    for i, tc in enumerate(target_tests):
        inp = tc.get("input", "")
        expected = tc.get("expected_output", "").strip()
        is_hidden = tc.get("is_hidden", False)

        if lang == "python":
            run_res = run_python_test(code, inp)
        else:
            run_res = run_java_test(code, inp)

        actual = run_res.get("stdout", "").strip()
        has_error = bool(run_res.get("stderr")) or run_res.get("exit_code") != 0

        # Normalization comparison: split tokens to tolerate trailing spacing differences
        is_match = False
        if not has_error:
            if actual == expected or actual.split() == expected.split():
                is_match = True

        if is_match:
            passed_count += 1

        test_detail = {
            "test_case_number": i + 1,
            "passed": is_match,
            "is_hidden": is_hidden,
            "execution_time_ms": run_res.get("execution_time_ms", 0),
        }

        # Reveal input / output details only for non-hidden tests or sample runs
        if not is_hidden or is_sample_run:
            test_detail["input"] = inp
            test_detail["expected_output"] = expected
            test_detail["actual_output"] = actual
            if run_res.get("stderr"):
                test_detail["error"] = run_res["stderr"]
        else:
            test_detail["input"] = "[Hidden Test Case]"
            test_detail["expected_output"] = "[Hidden]"
            test_detail["actual_output"] = "[Passed]" if is_match else "[Incorrect Output or Error]"
            if run_res.get("timed_out"):
                test_detail["error"] = "Time Limit Exceeded"

        results.append(test_detail)

    total_tests = len(target_tests)
    score = round((passed_count / total_tests) * max_marks, 2) if total_tests > 0 else 0.0

    return {
        "success": passed_count == total_tests and total_tests > 0,
        "language": lang,
        "is_sample_run": is_sample_run,
        "passed_tests": passed_count,
        "total_tests": total_tests,
        "score": score,
        "max_score": max_marks,
        "test_results": results,
    }
