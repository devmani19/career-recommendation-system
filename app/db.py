import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

from .services.auth_security import (
    generate_otp_code,
    generate_reset_token,
    generate_user_id,
    hash_otp_code,
    hash_password,
    hash_reset_token,
    verify_otp_code,
    verify_password,
    verify_reset_token,
)

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "career_app.db"

# MySQL configuration from environment
MYSQL_HOST = os.environ.get("MYSQL_HOST")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD")
MYSQL_DB = os.environ.get("MYSQL_DB", os.environ.get("MYSQL_DATABASE"))
DATABASE_TYPE = os.environ.get("DATABASE_TYPE", "mysql" if MYSQL_HOST and MYSQL_DB else "sqlite").lower()


class DBConnectionWrapper:
    """
    Uniform wrapper around SQLite and MySQL connections.
    Translates '?' placeholders to '%s' for MySQL, and provides dictionary row access.
    """
    def __init__(self, raw_conn, is_mysql=False):
        self.raw_conn = raw_conn
        self.is_mysql = is_mysql

    def _format_query(self, query: str) -> str:
        if self.is_mysql:
            # Replace SQLite '?' with MySQL '%s'
            # (assuming ? are parameter placeholders and not literal inside strings)
            return query.replace("?", "%s")
        return query

    def execute(self, query: str, params: Union[Tuple, List] = ()):
        formatted_query = self._format_query(query)
        cursor = self.raw_conn.cursor()
        cursor.execute(formatted_query, params)
        return cursor

    def commit(self):
        self.raw_conn.commit()

    def rollback(self):
        self.raw_conn.rollback()

    def close(self):
        self.raw_conn.close()


def get_db_connection() -> DBConnectionWrapper:
    """
    Get active database connection.
    Connects to MySQL if DATABASE_TYPE is 'mysql' and credentials exist;
    otherwise falls back to SQLite.
    """
    global DATABASE_TYPE
    if DATABASE_TYPE == "mysql" and MYSQL_HOST and MYSQL_DB:
        try:
            import pymysql
            import pymysql.cursors

            conn = pymysql.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER or "root",
                password=MYSQL_PASSWORD or "",
                database=MYSQL_DB,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False,
            )
            return DBConnectionWrapper(conn, is_mysql=True)
        except Exception:
            # Fall back to SQLite if MySQL connection fails
            pass

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    sqlite_conn = sqlite3.connect(str(DB_PATH))
    sqlite_conn.row_factory = sqlite3.Row
    return DBConnectionWrapper(sqlite_conn, is_mysql=False)


def init_db():
    """Initialize database tables and run backward-compatible migrations."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db_connection()

    if conn.is_mysql:
        _init_mysql_schema(conn)
    else:
        _init_sqlite_schema(conn)

    conn.close()


def _init_sqlite_schema(conn: DBConnectionWrapper):
    # 1. Base users table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()

    # Add extended columns to users if missing
    columns_to_add = [
        ("user_id", "TEXT"),
        ("full_name", "TEXT DEFAULT ''"),
        ("email_verified", "INTEGER DEFAULT 0"),
        ("email_verified_at", "TIMESTAMP"),
        ("account_status", "TEXT DEFAULT 'active'"),
        ("last_login_at", "TIMESTAMP"),
        ("failed_login_attempts", "INTEGER DEFAULT 0"),
        ("lockout_until", "TIMESTAMP"),
    ]
    for col_name, col_type in columns_to_add:
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
            conn.commit()
        except Exception:
            pass

    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id)")
        conn.commit()
    except Exception:
        pass

    # 2. Recommendations table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            candidate_name TEXT NOT NULL,
            certificate_name TEXT,
            score TEXT,
            result_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    conn.commit()

    try:
        conn.execute("ALTER TABLE recommendations ADD COLUMN ranking_method TEXT DEFAULT 'weighted_fallback'")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE recommendations ADD COLUMN model_version TEXT DEFAULT '1.0.0'")
    except sqlite3.OperationalError:
        pass
    conn.commit()

    # 3. Assessment tables
    conn.execute(
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
    conn.execute(
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
    conn.execute(
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
    conn.execute(
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
    conn.commit()

    # 4. OTP Verifications table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS otp_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            full_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            otp_hash TEXT NOT NULL,
            attempts INTEGER DEFAULT 0,
            resend_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            last_sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_consumed INTEGER DEFAULT 0
        )
        """
    )
    # Index for fast lookup
    conn.execute("CREATE INDEX IF NOT EXISTS idx_otp_email ON otp_verifications(email)")
    conn.commit()

    # 5. Password Resets table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            email TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            is_used INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pwd_resets_token ON password_resets(token_hash)")
    conn.commit()

    # Seed admin user if not exists
    cursor = conn.execute("SELECT id, user_id FROM users WHERE username = ?", ("admin",))
    admin_row = cursor.fetchone()
    if not admin_row:
        conn.execute(
            """
            INSERT INTO users (
                user_id, username, email, full_name, password_hash,
                email_verified, email_verified_at, account_status
            ) VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, 'active')
            """,
            (
                "USR-ADMIN001",
                "admin",
                "admin@careerai.com",
                "CareerAI Administrator",
                hash_password("admin123"),
            ),
        )
        conn.commit()
    else:
        # Upgrade admin fields if user_id was NULL
        if dict(admin_row).get("user_id") is None:
            conn.execute(
                """
                UPDATE users SET 
                    user_id = 'USR-ADMIN001',
                    full_name = 'CareerAI Administrator',
                    email_verified = 1,
                    account_status = 'active'
                WHERE username = 'admin'
                """
            )
            conn.commit()

    # Auto-seed question bank if empty
    q_count = conn.execute("SELECT count(*) FROM assessment_questions").fetchone()[0]
    if q_count == 0:
        json_path = BASE_DIR / "data" / "assessment_questions.json"
        if json_path.exists():
            import json
            with open(json_path, "r", encoding="utf-8") as f:
                qs = json.load(f)
            for q in qs:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO assessment_questions (
                        id, category, question_type, subtopic, difficulty,
                        question_text, code_snippet, options_json, correct_answer,
                        explanation, test_cases_json, reference_solution, marks,
                        target_roles_json, version, validation_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        q["id"], q["category"], q["question_type"], q["subtopic"], q["difficulty"],
                        q["question_text"], q.get("code_snippet") or q.get("starter_code") or "",
                        json.dumps(q.get("options", [])), q.get("correct_answer", ""),
                        q.get("explanation", ""), json.dumps(q.get("test_cases", [])),
                        q.get("reference_solution", ""), q.get("marks", 1),
                        json.dumps(q.get("target_roles", [])), q.get("version", "1.0.0"),
                        q.get("validation_status", "validated"),
                    ),
                )
            conn.commit()


def _init_mysql_schema(conn: DBConnectionWrapper):
    """Initialize MySQL tables."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id VARCHAR(64) UNIQUE,
            username VARCHAR(150) UNIQUE NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            full_name VARCHAR(255) DEFAULT '',
            password_hash VARCHAR(255) NOT NULL,
            email_verified TINYINT(1) DEFAULT 0,
            email_verified_at TIMESTAMP NULL,
            account_status VARCHAR(32) DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login_at TIMESTAMP NULL,
            failed_login_attempts INT DEFAULT 0,
            lockout_until TIMESTAMP NULL,
            INDEX idx_user_email (email),
            INDEX idx_user_id (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    conn.commit()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recommendations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            candidate_name VARCHAR(255) NOT NULL,
            certificate_name TEXT,
            score TEXT,
            result_json LONGTEXT,
            ranking_method VARCHAR(64) DEFAULT 'weighted_fallback',
            model_version VARCHAR(32) DEFAULT '1.0.0',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    conn.commit()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS assessment_questions (
            id VARCHAR(64) PRIMARY KEY,
            category VARCHAR(64) NOT NULL,
            question_type VARCHAR(32) NOT NULL,
            subtopic VARCHAR(128) NOT NULL,
            difficulty VARCHAR(32) NOT NULL,
            question_text TEXT NOT NULL,
            code_snippet TEXT,
            options_json TEXT,
            correct_answer TEXT NOT NULL,
            explanation TEXT,
            test_cases_json TEXT,
            reference_solution TEXT,
            marks INT DEFAULT 1,
            target_roles_json TEXT,
            version VARCHAR(32) DEFAULT '1.0.0',
            validation_status VARCHAR(32) DEFAULT 'validated',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    conn.commit()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS assessment_sessions (
            id VARCHAR(64) PRIMARY KEY,
            user_id INT NOT NULL,
            assessment_type VARCHAR(64) NOT NULL,
            programming_language VARCHAR(64),
            target_role VARCHAR(128),
            duration_minutes INT NOT NULL,
            status VARCHAR(32) DEFAULT 'in_progress',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP NULL,
            total_score DOUBLE DEFAULT 0.0,
            max_score DOUBLE DEFAULT 0.0,
            percentage DOUBLE DEFAULT 0.0,
            readiness_level VARCHAR(64),
            topic_breakdown_json LONGTEXT,
            skill_gap_analysis_json LONGTEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    conn.commit()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS assessment_session_questions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            session_id VARCHAR(64) NOT NULL,
            question_id VARCHAR(64) NOT NULL,
            order_index INT NOT NULL,
            shuffled_options_json TEXT,
            FOREIGN KEY (session_id) REFERENCES assessment_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (question_id) REFERENCES assessment_questions(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    conn.commit()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS assessment_submissions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            session_id VARCHAR(64) NOT NULL,
            question_id VARCHAR(64) NOT NULL,
            selected_option TEXT,
            code_submission LONGTEXT,
            is_correct TINYINT(1),
            score_awarded DOUBLE DEFAULT 0.0,
            max_score DOUBLE DEFAULT 0.0,
            test_cases_passed INT DEFAULT 0,
            test_cases_total INT DEFAULT 0,
            execution_output_json LONGTEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY unq_session_q (session_id, question_id),
            FOREIGN KEY (session_id) REFERENCES assessment_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (question_id) REFERENCES assessment_questions(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    conn.commit()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS otp_verifications (
            id INT AUTO_INCREMENT PRIMARY KEY,
            email VARCHAR(255) NOT NULL,
            full_name VARCHAR(255) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            otp_hash VARCHAR(255) NOT NULL,
            attempts INT DEFAULT 0,
            resend_count INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            last_sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_consumed TINYINT(1) DEFAULT 0,
            INDEX idx_otp_email (email)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    conn.commit()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS password_resets (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            email VARCHAR(255) NOT NULL,
            token_hash VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            is_used TINYINT(1) DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            INDEX idx_pwd_resets_token (token_hash)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    conn.commit()


# ── User Account Operations ─────────────────────────────────────────────────

def create_user(
    username: str,
    email: str,
    password_hash: str,
    full_name: str = "",
    user_id: Optional[str] = None,
    email_verified: int = 1,
    account_status: str = "active",
) -> int:
    """Create a user account in the database."""
    conn = get_db_connection()
    if not user_id:
        user_id = generate_user_id()
    if not full_name:
        full_name = username

    cursor = conn.execute(
        """
        INSERT INTO users (
            user_id, username, email, full_name, password_hash,
            email_verified, email_verified_at, account_status
        ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
        """,
        (user_id, username, email.lower().strip(), full_name.strip(), password_hash, email_verified, account_status),
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id


def get_user_by_email(email: str) -> Optional[Dict]:
    """Retrieve user record by email address (case-insensitive)."""
    if not email:
        return None
    conn = get_db_connection()
    cursor = conn.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(?)", (email.strip(),))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None


def get_user_by_username(username: str) -> Optional[Dict]:
    """Retrieve user record by username."""
    if not username:
        return None
    conn = get_db_connection()
    cursor = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None


def get_user_by_id(user_id: Union[int, str]) -> Optional[Dict]:
    """Retrieve user record by database ID or internal user_id."""
    conn = get_db_connection()
    if isinstance(user_id, int) or (isinstance(user_id, str) and user_id.isdigit()):
        cursor = conn.execute("SELECT * FROM users WHERE id = ?", (int(user_id),))
    else:
        cursor = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None


def get_user_by_login_id(login_id: str) -> Optional[Dict]:
    """
    Retrieve user by Login ID (email) or username.
    """
    if not login_id:
        return None
    user = get_user_by_email(login_id)
    if not user:
        user = get_user_by_username(login_id)
    return user


def update_user_password(user_id: int, new_password_hash: str) -> bool:
    """Update stored password hash for a user."""
    conn = get_db_connection()
    conn.execute(
        "UPDATE users SET password_hash = ?, failed_login_attempts = 0, lockout_until = NULL WHERE id = ?",
        (new_password_hash, user_id),
    )
    conn.commit()
    conn.close()
    return True


def record_failed_login(user_id: int) -> int:
    """
    Increment failed login attempts.
    Lock account for 15 minutes if attempts reach 5.
    Returns new attempt count.
    """
    conn = get_db_connection()
    cursor = conn.execute("SELECT failed_login_attempts FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    current_attempts = (dict(row).get("failed_login_attempts") or 0) if row else 0
    new_attempts = current_attempts + 1

    lockout_time = None
    if new_attempts >= 5:
        # Lockout for 15 minutes
        lockout_time = (datetime.now() + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        "UPDATE users SET failed_login_attempts = ?, lockout_until = ? WHERE id = ?",
        (new_attempts, lockout_time, user_id),
    )
    conn.commit()
    conn.close()
    return new_attempts


def reset_failed_logins(user_id: int):
    """Reset failed login count and update last_login_at timestamp."""
    conn = get_db_connection()
    conn.execute(
        "UPDATE users SET failed_login_attempts = 0, lockout_until = NULL, last_login_at = CURRENT_TIMESTAMP WHERE id = ?",
        (user_id,),
    )
    conn.commit()
    conn.close()


def is_user_locked_out(user: Dict) -> Tuple[bool, int]:
    """
    Check if user account is currently locked out.
    Returns (is_locked, minutes_remaining).
    """
    lockout_until = user.get("lockout_until")
    if not lockout_until:
        return False, 0

    if isinstance(lockout_until, str):
        try:
            lock_dt = datetime.fromisoformat(lockout_until.replace("Z", "+00:00"))
        except Exception:
            try:
                lock_dt = datetime.strptime(lockout_until, "%Y-%m-%d %H:%M:%S")
            except Exception:
                return False, 0
    elif isinstance(lockout_until, datetime):
        lock_dt = lockout_until
    else:
        return False, 0

    now = datetime.now()
    if lock_dt > now:
        diff_mins = max(1, int((lock_dt - now).total_seconds() / 60))
        return True, diff_mins

    return False, 0


# ── OTP Verification Operations ─────────────────────────────────────────────

def create_otp_challenge(email: str, full_name: str, password_hash: str) -> str:
    """
    Create a new OTP verification challenge.
    1. Generates 6-digit OTP code.
    2. Hashes OTP with HMAC-SHA256.
    3. Inactive/consumes any older challenges for this email.
    4. Sets 5-minute validity window.
    Returns the plaintext 6-digit OTP code (to be emailed to the user).
    """
    conn = get_db_connection()
    email_clean = email.strip().lower()

    # Invalidate older unconsumed challenges for this email
    conn.execute("UPDATE otp_verifications SET is_consumed = 1 WHERE LOWER(email) = ?", (email_clean,))

    otp_code = generate_otp_code()
    otp_hash = hash_otp_code(otp_code)
    expires_at = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        """
        INSERT INTO otp_verifications (
            email, full_name, password_hash, otp_hash,
            attempts, resend_count, created_at, expires_at, last_sent_at, is_consumed
        ) VALUES (?, ?, ?, ?, 0, 0, ?, ?, ?, 0)
        """,
        (email_clean, full_name.strip(), password_hash, otp_hash, now_str, expires_at, now_str),
    )
    conn.commit()
    conn.close()

    return otp_code


def get_latest_otp_challenge(email: str) -> Optional[Dict]:
    """Retrieve the latest unconsumed OTP challenge for an email."""
    conn = get_db_connection()
    cursor = conn.execute(
        """
        SELECT * FROM otp_verifications 
        WHERE LOWER(email) = ? AND is_consumed = 0 
        ORDER BY id DESC LIMIT 1
        """,
        (email.strip().lower(),),
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def verify_otp_challenge(email: str, entered_otp: str) -> Tuple[bool, str, Optional[Dict]]:
    """
    Validate entered OTP for an email.
    Returns (success, reason_code, challenge_dict).
    Reason codes: 'valid', 'not_found', 'expired', 'max_attempts_exceeded', 'invalid_otp'
    """
    conn = get_db_connection()
    email_clean = email.strip().lower()

    cursor = conn.execute(
        """
        SELECT * FROM otp_verifications 
        WHERE LOWER(email) = ? AND is_consumed = 0 
        ORDER BY id DESC LIMIT 1
        """,
        (email_clean,),
    )
    row = cursor.fetchone()

    if not row:
        conn.close()
        return False, "not_found", None

    challenge = dict(row)
    now = datetime.now()

    # Parse expiration
    expires_at_val = challenge["expires_at"]
    if isinstance(expires_at_val, str):
        try:
            exp_dt = datetime.fromisoformat(expires_at_val.replace("Z", "+00:00"))
        except Exception:
            exp_dt = datetime.strptime(expires_at_val, "%Y-%m-%d %H:%M:%S")
    else:
        exp_dt = expires_at_val

    if exp_dt < now:
        conn.execute("UPDATE otp_verifications SET is_consumed = 1 WHERE id = ?", (challenge["id"],))
        conn.commit()
        conn.close()
        return False, "expired", challenge

    # Check attempt threshold (max 5)
    current_attempts = challenge.get("attempts", 0)
    if current_attempts >= 5:
        conn.close()
        return False, "max_attempts_exceeded", challenge

    # Verify OTP hash
    if not verify_otp_code(entered_otp, challenge["otp_hash"]):
        new_attempts = current_attempts + 1
        conn.execute(
            "UPDATE otp_verifications SET attempts = ? WHERE id = ?",
            (new_attempts, challenge["id"]),
        )
        conn.commit()
        conn.close()
        challenge["attempts"] = new_attempts
        if new_attempts >= 5:
            return False, "max_attempts_exceeded", challenge
        return False, "invalid_otp", challenge

    conn.close()
    return True, "valid", challenge


def resend_otp_challenge(email: str) -> Tuple[bool, str, Optional[str], int]:
    """
    Resend OTP for an active challenge with 60-second cooldown enforcement.
    Returns (success, message, new_otp_code, cooldown_remaining_seconds).
    """
    conn = get_db_connection()
    email_clean = email.strip().lower()

    cursor = conn.execute(
        """
        SELECT * FROM otp_verifications 
        WHERE LOWER(email) = ? AND is_consumed = 0 
        ORDER BY id DESC LIMIT 1
        """,
        (email_clean,),
    )
    row = cursor.fetchone()

    if not row:
        conn.close()
        return False, "No active registration found. Please register first.", None, 0

    challenge = dict(row)
    now = datetime.now()

    # Check 60-second cooldown since last_sent_at
    last_sent_val = challenge["last_sent_at"]
    if isinstance(last_sent_val, str):
        try:
            last_dt = datetime.fromisoformat(last_sent_val.replace("Z", "+00:00"))
        except Exception:
            last_dt = datetime.strptime(last_sent_val, "%Y-%m-%d %H:%M:%S")
    else:
        last_dt = last_sent_val

    diff_seconds = (now - last_dt).total_seconds()
    if diff_seconds < 60:
        remaining = int(60 - diff_seconds)
        conn.close()
        return False, f"Please wait {remaining} seconds before requesting a new OTP.", None, remaining

    # Generate new OTP, refresh 5-minute window, reset attempts, increment resend count
    new_otp = generate_otp_code()
    new_hash = hash_otp_code(new_otp)
    new_expires_at = (now + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        """
        UPDATE otp_verifications SET 
            otp_hash = ?, 
            expires_at = ?, 
            last_sent_at = ?, 
            attempts = 0, 
            resend_count = resend_count + 1 
        WHERE id = ?
        """,
        (new_hash, new_expires_at, now_str, challenge["id"]),
    )
    conn.commit()
    conn.close()

    return True, "A new verification code has been sent to your email.", new_otp, 0


def activate_user_from_otp(challenge: Dict) -> Dict:
    """
    Transactional creation and activation of verified user account:
    1. Ensures atomic insert into users table.
    2. Marks OTP challenge consumed.
    3. Assigns unique internal User ID.
    4. Sets Login ID as verified email.
    Returns created user dict.
    """
    conn = get_db_connection()
    email = challenge["email"].strip().lower()
    full_name = challenge["full_name"].strip()
    password_hash = challenge["password_hash"]
    challenge_id = challenge["id"]

    try:
        # Check if already registered
        existing = conn.execute("SELECT id FROM users WHERE LOWER(email) = ?", (email,)).fetchone()
        if existing:
            # Mark OTP consumed
            conn.execute("UPDATE otp_verifications SET is_consumed = 1 WHERE id = ?", (challenge_id,))
            conn.commit()
            conn.close()
            raise ValueError("An account with this email address already exists.")

        # Generate unique internal User ID
        user_id = generate_user_id()
        # Verify uniqueness of generated user_id
        while conn.execute("SELECT id FROM users WHERE user_id = ?", (user_id,)).fetchone() is not None:
            user_id = generate_user_id()

        username = email.split("@")[0]
        # Ensure username uniqueness
        idx = 1
        base_username = username
        while conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone() is not None:
            username = f"{base_username}{idx}"
            idx += 1

        cursor = conn.execute(
            """
            INSERT INTO users (
                user_id, username, email, full_name, password_hash,
                email_verified, email_verified_at, account_status, created_at
            ) VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, 'active', CURRENT_TIMESTAMP)
            """,
            (user_id, username, email, full_name, password_hash),
        )

        # Mark OTP challenge consumed
        conn.execute("UPDATE otp_verifications SET is_consumed = 1 WHERE id = ?", (challenge_id,))
        conn.commit()

        user_db_id = cursor.lastrowid
        cursor_u = conn.execute("SELECT * FROM users WHERE id = ?", (user_db_id,))
        created_user = dict(cursor_u.fetchone())
        conn.close()
        return created_user

    except Exception:
        conn.rollback()
        conn.close()
        raise


# ── Password Reset Operations ───────────────────────────────────────────────

def create_password_reset(email: str) -> Optional[str]:
    """
    Create a single-use password reset token with 15-minute expiration.
    Invalidates any previous unused tokens for this user.
    Returns plaintext token (to be sent via email), or None if user not found.
    """
    user = get_user_by_email(email)
    if not user:
        return None

    conn = get_db_connection()
    user_id = user["id"]
    email_clean = user["email"].strip().lower()

    # Invalidate older tokens for this user
    conn.execute("UPDATE password_resets SET is_used = 1 WHERE user_id = ?", (user_id,))

    token = generate_reset_token()
    token_hash = hash_reset_token(token)
    expires_at = (datetime.now() + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        """
        INSERT INTO password_resets (user_id, email, token_hash, expires_at, is_used)
        VALUES (?, ?, ?, ?, 0)
        """,
        (user_id, email_clean, token_hash, expires_at),
    )
    conn.commit()
    conn.close()

    return token


def verify_password_reset_token(token: str) -> Tuple[bool, str, Optional[Dict]]:
    """
    Verify reset token.
    Returns (is_valid, reason, reset_record).
    Reasons: 'valid', 'invalid_token', 'expired', 'already_used'
    """
    if not token or not isinstance(token, str):
        return False, "invalid_token", None

    token_hash = hash_reset_token(token)
    conn = get_db_connection()
    cursor = conn.execute("SELECT * FROM password_resets WHERE token_hash = ?", (token_hash,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return False, "invalid_token", None

    record = dict(row)
    if record.get("is_used"):
        return False, "already_used", record

    now = datetime.now()
    expires_at_val = record["expires_at"]
    if isinstance(expires_at_val, str):
        try:
            exp_dt = datetime.fromisoformat(expires_at_val.replace("Z", "+00:00"))
        except Exception:
            exp_dt = datetime.strptime(expires_at_val, "%Y-%m-%d %H:%M:%S")
    else:
        exp_dt = expires_at_val

    if exp_dt < now:
        return False, "expired", record

    return True, "valid", record


def reset_user_password(token: str, new_password_hash: str) -> bool:
    """
    Update password and invalidate token in a single atomic transaction.
    Also clears failed login attempts and lockouts.
    """
    is_valid, reason, record = verify_password_reset_token(token)
    if not is_valid or not record:
        return False

    conn = get_db_connection()
    try:
        user_id = record["user_id"]
        # Update user's password hash and unlock account
        conn.execute(
            """
            UPDATE users SET 
                password_hash = ?, 
                failed_login_attempts = 0, 
                lockout_until = NULL 
            WHERE id = ?
            """,
            (new_password_hash, user_id),
        )
        # Mark token as used
        conn.execute("UPDATE password_resets SET is_used = 1 WHERE id = ?", (record["id"],))
        conn.commit()
        conn.close()
        return True
    except Exception:
        conn.rollback()
        conn.close()
        return False


def cleanup_expired_records():
    """Clean up expired OTPs and reset tokens older than 24 hours."""
    cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    conn.execute("DELETE FROM otp_verifications WHERE expires_at < ? OR is_consumed = 1", (cutoff,))
    conn.execute("DELETE FROM password_resets WHERE expires_at < ? OR is_used = 1", (cutoff,))
    conn.commit()
    conn.close()


# ── Existing Career AI Database Operations (Preserved Unaltered) ─────────────

def save_recommendation(
    user_id,
    candidate_name,
    certificate_name,
    score,
    result_json,
    ranking_method="weighted_fallback",
    model_version="1.0.0",
):
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO recommendations (
            user_id, candidate_name, certificate_name, score, result_json, ranking_method, model_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, candidate_name, certificate_name, score, result_json, ranking_method, model_version),
    )
    conn.commit()
    conn.close()


def get_user_recommendations(user_id):
    conn = get_db_connection()
    cursor = conn.execute(
        "SELECT * FROM recommendations WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_assessment_question(question_id: str):
    conn = get_db_connection()
    cursor = conn.execute("SELECT * FROM assessment_questions WHERE id = ?", (question_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_assessment_questions(category: str = None, question_type: str = None):
    conn = get_db_connection()
    query = "SELECT * FROM assessment_questions WHERE 1=1"
    params = []
    if category:
        query += " AND category = ?"
        params.append(category)
    if question_type:
        query += " AND question_type = ?"
        params.append(question_type)
    cursor = conn.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_assessment_question_counts():
    conn = get_db_connection()
    cursor = conn.execute(
        "SELECT category, question_type, count(*) as count FROM assessment_questions GROUP BY category, question_type"
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_assessment_session(
    session_id: str,
    user_id: int,
    assessment_type: str,
    programming_language: str | None,
    target_role: str | None,
    duration_minutes: int,
):
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO assessment_sessions (
            id, user_id, assessment_type, programming_language, target_role, duration_minutes, status
        ) VALUES (?, ?, ?, ?, ?, ?, 'in_progress')
        """,
        (session_id, user_id, assessment_type, programming_language, target_role, duration_minutes),
    )
    conn.commit()
    conn.close()


def get_assessment_session(session_id: str):
    conn = get_db_connection()
    cursor = conn.execute("SELECT * FROM assessment_sessions WHERE id = ?", (session_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def save_session_questions(session_id: str, question_records: list[dict]):
    conn = get_db_connection()
    for q in question_records:
        conn.execute(
            """
            INSERT INTO assessment_session_questions (
                session_id, question_id, order_index, shuffled_options_json
            ) VALUES (?, ?, ?, ?)
            """,
            (session_id, q["question_id"], q["order_index"], q.get("shuffled_options_json", "[]")),
        )
    conn.commit()
    conn.close()


def get_session_questions(session_id: str):
    conn = get_db_connection()
    cursor = conn.execute(
        """
        SELECT 
            asq.order_index,
            asq.shuffled_options_json,
            q.*
        FROM assessment_session_questions asq
        JOIN assessment_questions q ON asq.question_id = q.id
        WHERE asq.session_id = ?
        ORDER BY asq.order_index ASC
        """,
        (session_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_or_update_submission(
    session_id: str,
    question_id: str,
    selected_option: str | None,
    code_submission: str | None,
    is_correct: int | None,
    score_awarded: float,
    max_score: float,
    test_cases_passed: int = 0,
    test_cases_total: int = 0,
    execution_output_json: str = "{}",
):
    conn = get_db_connection()
    # Check if submission exists
    existing = conn.execute(
        "SELECT id FROM assessment_submissions WHERE session_id = ? AND question_id = ?",
        (session_id, question_id),
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE assessment_submissions SET 
                selected_option = ?, code_submission = ?, is_correct = ?,
                score_awarded = ?, max_score = ?, test_cases_passed = ?,
                test_cases_total = ?, execution_output_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE session_id = ? AND question_id = ?
            """,
            (
                selected_option, code_submission, is_correct, score_awarded,
                max_score, test_cases_passed, test_cases_total, execution_output_json,
                session_id, question_id,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO assessment_submissions (
                session_id, question_id, selected_option, code_submission,
                is_correct, score_awarded, max_score, test_cases_passed,
                test_cases_total, execution_output_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                session_id, question_id, selected_option, code_submission,
                is_correct, score_awarded, max_score, test_cases_passed,
                test_cases_total, execution_output_json,
            ),
        )
    conn.commit()
    conn.close()


def get_session_submissions(session_id: str):
    conn = get_db_connection()
    cursor = conn.execute(
        "SELECT * FROM assessment_submissions WHERE session_id = ?",
        (session_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return {r["question_id"]: dict(r) for r in rows}


def finalize_assessment_session(
    session_id: str,
    total_score: float,
    max_score: float,
    percentage: float,
    readiness_level: str,
    topic_breakdown_json: str,
    skill_gap_analysis_json: str,
):
    conn = get_db_connection()
    conn.execute(
        """
        UPDATE assessment_sessions
        SET status = 'completed',
            completed_at = CURRENT_TIMESTAMP,
            total_score = ?,
            max_score = ?,
            percentage = ?,
            readiness_level = ?,
            topic_breakdown_json = ?,
            skill_gap_analysis_json = ?
        WHERE id = ?
        """,
        (
            total_score,
            max_score,
            percentage,
            readiness_level,
            topic_breakdown_json,
            skill_gap_analysis_json,
            session_id,
        ),
    )
    conn.commit()
    conn.close()


def get_user_assessment_sessions(user_id: int):
    conn = get_db_connection()
    cursor = conn.execute(
        """
        SELECT * FROM assessment_sessions
        WHERE user_id = ?
        ORDER BY started_at DESC
        """,
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]
