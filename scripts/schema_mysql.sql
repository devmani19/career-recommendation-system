-- =============================================================================
-- MySQL Schema Migration for AI-Based Career Recommendation System
-- Supports User Registration, Email OTP Verification, Credential Management
-- =============================================================================

CREATE DATABASE IF NOT EXISTS career_app CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE career_app;

-- 1. Users Table
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. OTP Verifications Table
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
    INDEX idx_otp_email (email),
    INDEX idx_otp_consumed (is_consumed)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Password Resets Table
CREATE TABLE IF NOT EXISTS password_resets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    email VARCHAR(255) NOT NULL,
    token_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    is_used TINYINT(1) DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_pwd_resets_token (token_hash),
    INDEX idx_pwd_resets_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. Recommendations Table
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. Assessment Question Bank
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. Assessment Sessions
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 7. Assessment Session Questions
CREATE TABLE IF NOT EXISTS assessment_session_questions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    question_id VARCHAR(64) NOT NULL,
    order_index INT NOT NULL,
    shuffled_options_json TEXT,
    FOREIGN KEY (session_id) REFERENCES assessment_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (question_id) REFERENCES assessment_questions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8. Assessment Submissions
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Initial Administrator Account
-- password is 'admin123'
INSERT IGNORE INTO users (user_id, username, email, full_name, password_hash, email_verified, email_verified_at, account_status)
VALUES (
    'USR-ADMIN001',
    'admin',
    'admin@careerai.com',
    'CareerAI Administrator',
    '$2b$12$e68Y2kFv2U6eLskTfZjDyeT1uYt6iWzJqA6X9lM0oAeqsX5fSOm3a',
    1,
    CURRENT_TIMESTAMP,
    'active'
);
