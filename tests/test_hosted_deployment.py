import json

from app.db import DBConnectionWrapper, _init_postgres_schema
from app.services import email_service


def test_postgres_connection_wrapper_converts_placeholders():
    connection = DBConnectionWrapper(None, is_postgres=True)

    assert connection._format_query("SELECT * FROM users WHERE email = ?") == (
        "SELECT * FROM users WHERE email = %s"
    )


def test_postgres_schema_uses_supported_schema_statements():
    class Cursor:
        def fetchone(self):
            return {"question_count": 1}

    class Connection:
        def __init__(self):
            self.statements = []

        def execute(self, query, params=()):
            self.statements.append(query)
            return Cursor()

        def commit(self):
            pass

    connection = Connection()
    _init_postgres_schema(connection)

    statements = "\n".join(connection.statements)
    assert "BIGSERIAL PRIMARY KEY" in statements
    assert "ON CONFLICT" not in statements
    assert "AUTOINCREMENT" not in statements
    assert "CREATE INDEX IF NOT EXISTS" in statements


def test_brevo_delivery_uses_https_api_and_configured_recipient(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "brevo")
    monkeypatch.setenv("EMAIL_API_KEY", "test-api-key")
    monkeypatch.setenv("EMAIL_FROM", "verified@example.test")
    monkeypatch.setenv("SMTP_FROM_NAME", "CareerAI Test")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "false")
    email_service.clear_outbox()
    captured = {}

    class Response:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["api_key"] = request.get_header("Api-key")
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(email_service.urllib.request, "urlopen", fake_urlopen)

    assert email_service.send_otp_email(
        "recipient@example.test", "Test User", "123456"
    )
    assert captured["url"] == "https://api.brevo.com/v3/smtp/email"
    assert captured["api_key"] == "test-api-key"
    assert captured["payload"]["to"] == [{"email": "recipient@example.test"}]
    assert "123456" in captured["payload"]["textContent"]
    assert len(email_service.get_outbox()) == 1
