# Reima

Reima is a real reimbursement and approval workflow product with a Python backend, vanilla JS frontend, PostgreSQL persistence, and SQLAlchemy-managed schema/models.

## Stack

- Frontend: HTML, CSS, vanilla JavaScript
- Backend: Python
- Database: PostgreSQL
- ORM / schema management: SQLAlchemy
- Security: salted `scrypt` password hashing, server-side sessions, `HttpOnly` cookies, `SameSite=Strict`, CSRF protection, RBAC, email verification, password reset tokens

## Files That Matter

- [server.py](C:\Users\LappySingh\Documents\New project\server.py): HTTP server and business logic
- [database.py](C:\Users\LappySingh\Documents\New project\database.py): SQLAlchemy engine, session, and database bootstrap
- [models.py](C:\Users\LappySingh\Documents\New project\models.py): SQLAlchemy models
- [schema.postgresql.sql](C:\Users\LappySingh\Documents\New project\schema.postgresql.sql): PostgreSQL DDL reference
- [migrate_sqlite_to_postgres.py](C:\Users\LappySingh\Documents\New project\migrate_sqlite_to_postgres.py): one-time migration from the old SQLite file
- [docker-compose.yml](C:\Users\LappySingh\Documents\New project\docker-compose.yml): local PostgreSQL container

## Setup

1. Install dependencies:

```powershell
pip install -r requirements.txt
```

2. Start PostgreSQL locally:

```powershell
docker compose up -d
```

3. Configure environment:

```powershell
Copy-Item .env.example .env
```

4. Run the server:

```powershell
python server.py
```

5. Open:

```text
http://127.0.0.1:8000
```

## Database Migration

If you already have data in the old SQLite file [reima.db](C:\Users\LappySingh\Documents\New project\reima.db), migrate it into PostgreSQL with:

```powershell
python migrate_sqlite_to_postgres.py
```

This preserves:

- companies
- users
- approval flows and steps
- rules
- expenses
- approval actions
- sessions
- verification/reset tokens
- notifications
- audit logs

## Environment Variables

```text
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/reima
HOST=127.0.0.1
PORT=8000
REIMA_PUBLIC_URL=http://127.0.0.1:8000
REIMA_SECURE_COOKIE=0
REIMA_SMTP_HOST=
REIMA_SMTP_PORT=587
REIMA_SMTP_USER=
REIMA_SMTP_PASSWORD=
REIMA_SMTP_FROM=noreply@reima.local
REIMA_SMTP_STARTTLS=1
```

## Email Delivery

If SMTP is configured, Reima sends real verification and password-reset emails.

If SMTP is not configured, emails are written to:

```text
mail_outbox.log
```

## Notes

- PostgreSQL is the primary database target for this project.
- SQLAlchemy creates and manages the live schema at startup.
- The old [schema.sql](C:\Users\LappySingh\Documents\New project\schema.sql) is the legacy SQLite version kept only for historical reference during migration.
