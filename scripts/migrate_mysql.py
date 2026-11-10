"""
Database migration utility for AI-Based Career Recommendation System.
Safely migrates SQLite schema & data to MySQL when configured.
Usage:
    python scripts/migrate_mysql.py
"""

import os
import sqlite3
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
SQLITE_DB_PATH = BASE_DIR / "data" / "career_app.db"
SQL_SCHEMA_PATH = BASE_DIR / "scripts" / "schema_mysql.sql"


def run_migration():
    host = os.environ.get("MYSQL_HOST", "localhost")
    port = int(os.environ.get("MYSQL_PORT", "3306"))
    user = os.environ.get("MYSQL_USER", "root")
    password = os.environ.get("MYSQL_PASSWORD", "")
    database = os.environ.get("MYSQL_DB", os.environ.get("MYSQL_DATABASE", "career_app"))

    print(f"Connecting to MySQL at {host}:{port}...")
    try:
        import pymysql
    except ImportError:
        print("ERROR: pymysql is not installed. Please run `pip install pymysql`.")
        sys.exit(1)

    try:
        # First connect without database to ensure database exists
        server_conn = pymysql.connect(host=host, port=port, user=user, password=password, autocommit=True)
        with server_conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
        server_conn.close()

        # Connect to the target database
        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset="utf8mb4",
            autocommit=True,
        )
        print(f"Connected to MySQL database '{database}'.")

        # Execute schema SQL statements
        with open(SQL_SCHEMA_PATH, "r", encoding="utf-8") as f:
            sql_statements = f.read().split(";")

        with conn.cursor() as cur:
            for stmt in sql_statements:
                stmt_clean = stmt.strip()
                if stmt_clean and not stmt_clean.lower().startswith("use "):
                    cur.execute(stmt_clean)
        print("MySQL schema migration applied successfully.")

        # Migrate existing users from SQLite if available
        if SQLITE_DB_PATH.exists():
            print("Importing records from local SQLite database...")
            s_conn = sqlite3.connect(SQLITE_DB_PATH)
            s_conn.row_factory = sqlite3.Row
            s_cur = s_conn.cursor()

            try:
                users = s_cur.execute("SELECT * FROM users").fetchall()
                with conn.cursor() as cur:
                    for u in users:
                        u_dict = dict(u)
                        cur.execute(
                            """
                            INSERT IGNORE INTO users (
                                id, user_id, username, email, full_name, password_hash,
                                email_verified, email_verified_at, account_status, created_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                u_dict["id"],
                                u_dict.get("user_id") or f"USR-{u_dict['id']:04d}",
                                u_dict["username"],
                                u_dict["email"],
                                u_dict.get("full_name") or u_dict["username"],
                                u_dict["password_hash"],
                                u_dict.get("email_verified", 1),
                                u_dict.get("email_verified_at") or u_dict["created_at"],
                                u_dict.get("account_status", "active"),
                                u_dict["created_at"],
                            ),
                        )
                print(f"Migrated {len(users)} user(s) from SQLite.")
            except Exception as e:
                print(f"Notice during user import: {e}")
            finally:
                s_conn.close()

        conn.close()
        print("Migration completed successfully.")

    except Exception as e:
        print(f"MySQL Migration failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_migration()
