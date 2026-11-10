# Career Recommendation System

An AI-powered career guidance platform for resume analysis, skill-gap assessment,
career-readiness evaluation, and personalized career recommendations.

## Free demo hosting: Render + Neon

This setup keeps the database outside the web container, so app restarts or redeploys
do not erase registered users or assessment results. Free plans have quotas and can
change; export database backups regularly. Render's free web service can sleep while
idle, so the first visit after inactivity may take time.

### 1. Create a persistent PostgreSQL database

1. Create a free Neon account and a PostgreSQL project.
2. Copy the **pooled** connection string from the Neon dashboard. It should include
   SSL settings such as `sslmode=require`.
3. Keep the connection string private; add it to the app host as `DATABASE_URL`.

The app creates its tables and assessment question bank on first startup when
`DATABASE_TYPE=postgresql`.

### 2. Create the web service

1. Create a Render account and choose **New → Web Service**.
2. Connect `devmani19/career-recommendation-system`, select the `main` branch, and
   choose the repository's Dockerfile.
3. Select the free instance type. The service may sleep when idle and has limited
   CPU/RAM; model-heavy requests may exceed the free instance's resources.
4. Add the environment variables below in Render's service settings. Add secret values
   there, not to GitHub.

| Variable | Value |
| --- | --- |
| `DATABASE_TYPE` | `postgresql` |
| `DATABASE_URL` | Neon pooled PostgreSQL connection string |
| `SECRET_KEY` | Long random secret used to sign Flask sessions |
| `AUTH_SECRET_PEPPER` | A different long random secret for OTP/reset-token hashes |
| `ADMIN_PASSWORD` | Strong admin password; omit to disable automatic admin creation |
| `EMAIL_PROVIDER` | `brevo` (HTTPS API, avoids SMTP port restrictions) |
| `EMAIL_API_KEY` | Brevo API key |
| `EMAIL_FROM` | Verified sender email address in Brevo |
| `SMTP_FROM_NAME` | `Career Recommendation System Team` |
| `MAIL_SUPPRESS_SEND` | `false` |

Generate each application secret locally in PowerShell:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Generate two different values. Store them in Render's environment settings and keep
them stable across deploys. Do not commit them.

### 3. Configure OTP email

Render free services may not be able to connect to external SMTP servers. Use Brevo's
HTTPS transactional email API instead:

1. Create a Brevo account and an API key.
2. Register and verify the sender email address with Brevo.
3. Set `EMAIL_PROVIDER=brevo`, `EMAIL_API_KEY`, and `EMAIL_FROM` in Render.
4. Register using an email address you can access and check Inbox and Spam/Junk.

Brevo warns that free email domains such as Gmail cannot be authenticated with DKIM/
DMARC in the same way as a custom domain. Delivery may be less reliable or be classified
as spam. For reliable production email, use a domain you control and authenticate it.
Never ask registrants for their Gmail passwords or App Passwords.

### 4. Protect and back up user data

- User accounts and assessment records live in Neon, not in the container filesystem.
- Check Neon plan limits and export a database backup regularly; a free database is not
  a substitute for backups or an availability guarantee.
- Uploaded files are stored on the app container and can disappear on redeploy/restart.
  Do not treat local uploads as durable. Add object storage before relying on long-term
  resume-file retention.
- Set a strong, unique admin password before allowing public use. Never deploy with the
  default demo admin credentials. The app creates its initial admin account only if
  `ADMIN_PASSWORD` is configured; configure it before the first database startup if needed.
- Keep `.env`, API keys, database URLs, and generated secrets out of GitHub.

## Local development

Install dependencies and run the test suite:

```powershell
python -m pip install -r requirements.txt
pytest -q
```

To use PostgreSQL locally, set `DATABASE_TYPE=postgresql` and `DATABASE_URL`. Otherwise
the app uses the local SQLite database.
