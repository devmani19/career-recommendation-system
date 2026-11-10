# career-recommendation-system
An AI-powered career guidance platform for resume analysis, skill-gap assessment, career-readiness evaluation, and personalized career recommendations

## Deploy to Google Cloud Run with Cloud SQL

The project includes a Dockerfile for Cloud Run. Use Cloud SQL for MySQL in production;
Cloud Run's local filesystem is temporary and SQLite data will not persist across instances.

### 1. Create Google Cloud resources

In the Google Cloud Console:

1. Create or select a project and enable billing.
2. Enable Cloud Run, Cloud Build, Artifact Registry, Cloud SQL Admin, and Secret Manager APIs.
3. Create a Cloud SQL for MySQL 8 instance in the same region you plan to use for Cloud Run.
4. Create a database named `career_app` and a dedicated database user (for example `careerai_app`).
   Save the user's password securely.
   Grant that user permission to create and update tables in this database, for example by
   connecting as the database administrator and running
   `GRANT ALL PRIVILEGES ON career_app.* TO 'careerai_app'@'%'`.
5. Create a runtime service account for the Cloud Run service and grant it **Cloud SQL Client**
   and **Secret Manager Secret Accessor** roles.
6. Create these Secret Manager secrets and add their values:
   - `careerai-secret-key`: a long random value used as the Flask session key.
   - `careerai-auth-pepper`: a different long random value used for OTP/reset-token hashing.
   - `careerai-db-password`: the Cloud SQL user's password.
   - `careerai-smtp-password`: the sender Gmail's Google App Password.

Generate random application secrets locally with:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Run it separately for each application secret. Do not commit the generated values.

### 2. Deploy from this GitHub repository

In the Google Cloud Console, open **Cloud Run → Create service → Continuously deploy from a
repository**, connect the GitHub repository, and select the `main` branch. Choose Dockerfile
builds and the same region as Cloud SQL.

Configure the service:

- Allow unauthenticated invocations if the website should be public.
- Use the runtime service account created above.
- Attach the Cloud SQL instance in the service's **Connections** settings.
- Start with 2 CPUs and 4 GiB memory; the resume/NLP/model dependencies are resource-intensive.
- Set minimum instances to 0 to reduce idle cost.
- Cloud SQL has ongoing charges even when the app is idle; review Google Cloud pricing and set a
  billing budget alert before creating the instance.

Set these environment variables on the Cloud Run service:

| Name | Value |
| --- | --- |
| `DATABASE_TYPE` | `mysql` |
| `CLOUD_SQL_CONNECTION_NAME` | Cloud SQL instance connection name: `project:region:instance` |
| `MYSQL_DB` | `career_app` |
| `MYSQL_USER` | The dedicated Cloud SQL database user |
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USE_TLS` | `true` |
| `SMTP_USE_SSL` | `false` |
| `SMTP_USER` | The app owner's sender Gmail address |
| `SMTP_FROM_EMAIL` | The same sender Gmail address |
| `SMTP_FROM_NAME` | `Career Recommendation System Team` |
| `MAIL_SUPPRESS_SEND` | `false` |

Map the following environment variables to the corresponding Secret Manager secrets:

| Environment variable | Secret |
| --- | --- |
| `SECRET_KEY` | `careerai-secret-key` |
| `AUTH_SECRET_PEPPER` | `careerai-auth-pepper` |
| `MYSQL_PASSWORD` | `careerai-db-password` |
| `SMTP_PASSWORD` | `careerai-smtp-password` |

Deploy the service. On startup, the app creates the MySQL schema and seeds the assessment
question bank. Users can then register through the public service URL. The sender Gmail is
configured once by the app owner; registrants only enter their own email address.

### 3. Verify delivery and data persistence

Register with an email address you can access, then check its inbox and spam folder for the OTP.
Create a test account, deploy a new revision, and confirm the account can still log in; this
checks that the service is using Cloud SQL rather than local SQLite.

Cloud Run may not retain uploaded files after an instance stops. The app processes resume
uploads during requests; use Cloud Storage if uploaded files need durable retention.

Never commit `.env`, database passwords, SMTP credentials, or generated application secrets.
