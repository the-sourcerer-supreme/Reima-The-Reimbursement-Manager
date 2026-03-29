import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import smtplib
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from database import connect_db as orm_connect_db
from database import database_backend_label, ensure_database as orm_ensure_database
from sqlalchemy.exc import IntegrityError as SAIntegrityError


ROOT = Path(__file__).resolve().parent
SESSION_COOKIE = "reima_session"
SESSION_TTL_HOURS = 12
EMAIL_VERIFICATION_TTL_HOURS = 24
PASSWORD_RESET_TTL_MINUTES = 30
SECURE_COOKIE = os.getenv("REIMA_SECURE_COOKIE", "0") == "1"
SMTP_HOST = os.getenv("REIMA_SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("REIMA_SMTP_PORT", "587") or 587)
SMTP_USERNAME = os.getenv("REIMA_SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("REIMA_SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("REIMA_SMTP_FROM", "noreply@reima.local").strip()
SMTP_USE_TLS = os.getenv("REIMA_SMTP_STARTTLS", "1") != "0"
PUBLIC_URL = os.getenv("REIMA_PUBLIC_URL", "").strip().rstrip("/")
MAIL_OUTBOX_PATH = ROOT / "mail_outbox.log"
FALLBACK_COUNTRY_CURRENCY = {
    "India": "INR",
    "United States": "USD",
    "United Kingdom": "GBP",
    "United Arab Emirates": "AED",
    "Germany": "EUR",
    "Singapore": "SGD",
    "Australia": "AUD",
}
COUNTRY_API_URL = "https://restcountries.com/v3.1/all?fields=name,currencies"
RATE_API_URL = "https://api.exchangerate-api.com/v4/latest/{base_currency}"
CACHE_LOCK = threading.Lock()
REFERENCE_CACHE = {
    "countries": {"value": None, "fetched_at": None},
    "rates": {}
}
ROLE_LABELS = {
    "ADMIN": "Admin",
    "MANAGER": "Manager",
    "EMPLOYEE": "Employee",
    "FINANCE": "Finance",
    "DIRECTOR": "Director",
}
CURRENCY_IN_INR = {
    "INR": 1.0,
    "USD": 83.0,
    "EUR": 90.0,
    "GBP": 105.0,
    "AED": 22.6,
    "SGD": 62.0,
    "AUD": 55.0,
}
STATIC_FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/styles.css": "styles.css",
}


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    return now_utc().isoformat()


def connect_db() -> sqlite3.Connection:
    return orm_connect_db()


def ensure_database() -> None:
    orm_ensure_database()


def fetch_one(connection, query: str, params: tuple = ()) -> dict | None:
    return connection.execute(query, params).fetchone()


def fetch_all(connection, query: str, params: tuple = ()) -> list[dict]:
    return connection.execute(query, params).fetchall()


def row_to_dict(row: dict | None) -> dict | None:
    return dict(row) if row is not None else None


def json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw:
      return {}
    return json.loads(raw.decode("utf-8"))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    hashed = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${hashed.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    salt_hex, digest_hex = stored_hash.split("$", 1)
    fresh = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
    return hmac.compare_digest(fresh.hex(), digest_hex)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_one_time_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(value: str) -> str:
    return value.strip().lower()


def create_one_time_token(connection: sqlite3.Connection, table: str, user_id: int, lifetime: timedelta) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hash_one_time_token(token)
    connection.execute(f"DELETE FROM {table} WHERE user_id = ? AND consumed_at IS NULL", (user_id,))
    connection.execute(
        f"""
        INSERT INTO {table} (user_id, token_hash, expires_at, consumed_at, created_at)
        VALUES (?, ?, ?, NULL, ?)
        """,
        (user_id, token_hash, (now_utc() + lifetime).isoformat(), iso_now()),
    )
    return token


def consume_one_time_token(connection: sqlite3.Connection, table: str, token: str, invalid_message: str, expired_message: str) -> sqlite3.Row:
    token_hash = hash_one_time_token(token)
    row = fetch_one(
        connection,
        f"SELECT * FROM {table} WHERE token_hash = ? AND consumed_at IS NULL ORDER BY id DESC LIMIT 1",
        (token_hash,),
    )
    if not row:
        raise ValueError(invalid_message)
    if datetime.fromisoformat(row["expires_at"]) <= now_utc():
        raise ValueError(expired_message)
    connection.execute(f"UPDATE {table} SET consumed_at = ? WHERE id = ?", (iso_now(), row["id"]))
    return row


def send_email_message(to_email: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = SMTP_FROM
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)
    if SMTP_HOST:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
            if SMTP_USE_TLS:
                smtp.starttls()
            if SMTP_USERNAME:
                smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(message)
        return
    with MAIL_OUTBOX_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"[{iso_now()}] TO: {to_email}\nSUBJECT: {subject}\n{body}\n{'-' * 72}\n")


def currency_for_country(country: str) -> str:
    countries = get_country_reference_data()
    return next((item["currency"] for item in countries if item["name"] == country), FALLBACK_COUNTRY_CURRENCY.get(country, "USD"))


def convert_currency(amount: float, from_currency: str, to_currency: str) -> float:
    if from_currency == to_currency:
        return round(amount, 2)
    rates = get_exchange_rates(from_currency)
    target_rate = rates.get(to_currency)
    if target_rate:
        return round(amount * float(target_rate), 2)
    from_in_inr = CURRENCY_IN_INR.get(from_currency, 1.0)
    to_in_inr = CURRENCY_IN_INR.get(to_currency, 1.0)
    return round((amount * from_in_inr) / to_in_inr, 2)


def fetch_json(url: str) -> dict | list:
    with urlopen(url, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def get_country_reference_data() -> list[dict]:
    with CACHE_LOCK:
        cached = REFERENCE_CACHE["countries"]["value"]
    if cached:
        return cached
    try:
        payload = fetch_json(COUNTRY_API_URL)
        countries = []
        for item in payload:
            name = item.get("name", {}).get("common")
            currencies = item.get("currencies") or {}
            currency_code = next(iter(currencies.keys()), None)
            if name and currency_code:
                countries.append({"name": name, "currency": currency_code})
        countries.sort(key=lambda item: item["name"])
        if countries:
            with CACHE_LOCK:
                REFERENCE_CACHE["countries"] = {"value": countries, "fetched_at": iso_now()}
            return countries
    except Exception:
        pass
    fallback = [{"name": name, "currency": currency} for name, currency in sorted(FALLBACK_COUNTRY_CURRENCY.items())]
    with CACHE_LOCK:
        REFERENCE_CACHE["countries"] = {"value": fallback, "fetched_at": iso_now()}
    return fallback


def get_exchange_rates(base_currency: str) -> dict:
    base = base_currency.upper()
    with CACHE_LOCK:
        cached = REFERENCE_CACHE["rates"].get(base)
    if cached and (now_utc() - cached["fetched_at"]) < timedelta(hours=6):
        return cached["rates"]
    try:
        payload = fetch_json(RATE_API_URL.format(base_currency=base))
        rates = payload.get("rates") or {}
        if rates:
            with CACHE_LOCK:
                REFERENCE_CACHE["rates"][base] = {"rates": rates, "fetched_at": now_utc()}
            return rates
    except Exception:
        pass
    fallback_rates = {}
    for currency, inr_value in CURRENCY_IN_INR.items():
        if currency == base:
            fallback_rates[currency] = 1.0
        else:
            fallback_rates[currency] = round((CURRENCY_IN_INR.get(currency, 1.0) / CURRENCY_IN_INR.get(base, 1.0)), 6)
    with CACHE_LOCK:
        REFERENCE_CACHE["rates"][base] = {"rates": fallback_rates, "fetched_at": now_utc()}
    return fallback_rates


def require_fields(payload: dict, fields: list[str]) -> None:
    missing = [field for field in fields if not str(payload.get(field, "")).strip()]
    if missing:
        raise ValueError(f"Missing required field(s): {', '.join(missing)}")


def validate_password_strength(password: str) -> None:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")


def get_cookie_token(handler: BaseHTTPRequestHandler) -> str | None:
    cookie_header = handler.headers.get("Cookie")
    if not cookie_header:
        return None
    jar = cookies.SimpleCookie()
    jar.load(cookie_header)
    morsel = jar.get(SESSION_COOKIE)
    return morsel.value if morsel else None


def session_payload(connection: sqlite3.Connection, token: str | None) -> dict | None:
    if not token:
        return None
    session = fetch_one(
        connection,
        """
        SELECT us.id, us.user_id, us.csrf_token, us.expires_at,
               u.name, u.email, u.email_verified, u.role, u.company_id, u.manager_id, u.department, u.status,
               c.name AS company_name, c.country, c.base_currency
        FROM user_session us
        JOIN app_user u ON u.id = us.user_id
        JOIN company c ON c.id = u.company_id
        WHERE us.token_hash = ?
        """,
        (hash_session_token(token),),
    )
    if not session:
        return None
    expires_at = datetime.fromisoformat(session["expires_at"])
    if expires_at <= now_utc():
        connection.execute("DELETE FROM user_session WHERE id = ?", (session["id"],))
        connection.commit()
        return None
    if session["status"] != "ACTIVE":
        return None
    return {
        "session_id": session["id"],
        "user": {
            "id": session["user_id"],
            "name": session["name"],
            "email": session["email"],
            "email_verified": bool(session["email_verified"]),
            "role": session["role"],
            "company_id": session["company_id"],
            "manager_id": session["manager_id"],
            "department": session["department"],
            "status": session["status"],
        },
        "company": {
            "id": session["company_id"],
            "name": session["company_name"],
            "country": session["country"],
            "base_currency": session["base_currency"],
        },
        "csrf_token": session["csrf_token"],
    }


def create_session(connection: sqlite3.Connection, user_id: int) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    expires_at = (now_utc() + timedelta(hours=SESSION_TTL_HOURS)).isoformat()
    connection.execute(
        """
        INSERT INTO user_session (user_id, token_hash, csrf_token, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, hash_session_token(token), csrf_token, expires_at, iso_now()),
    )
    connection.commit()
    return token, csrf_token


def destroy_session(connection: sqlite3.Connection, token: str | None) -> None:
    if not token:
        return
    connection.execute("DELETE FROM user_session WHERE token_hash = ?", (hash_session_token(token),))
    connection.commit()


def add_audit_log(connection: sqlite3.Connection, company_id: int, actor_id: int | None, action: str, target_type: str, target_id: int | None, description: str) -> None:
    connection.execute(
        """
        INSERT INTO audit_log (company_id, actor_id, action, target_type, target_id, description, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (company_id, actor_id, action, target_type, target_id, description, iso_now()),
    )


def add_notification(connection: sqlite3.Connection, user_id: int, message: str) -> None:
    connection.execute(
        "INSERT INTO notification (user_id, message, is_read, created_at) VALUES (?, ?, 0, ?)",
        (user_id, message, iso_now()),
    )


def active_user_by_role(connection: sqlite3.Connection, company_id: int, role: str) -> sqlite3.Row | None:
    return fetch_one(
        connection,
        "SELECT * FROM app_user WHERE company_id = ? AND role = ? AND status = 'ACTIVE' ORDER BY id LIMIT 1",
        (company_id, role),
    )


def flow_for_company(connection: sqlite3.Connection, company_id: int) -> sqlite3.Row:
    flow = fetch_one(connection, "SELECT * FROM approval_flow WHERE company_id = ? ORDER BY id LIMIT 1", (company_id,))
    if not flow:
        raise ValueError("Approval flow is not configured for this company.")
    return flow


def steps_for_flow(connection: sqlite3.Connection, flow_id: int) -> list[sqlite3.Row]:
    return fetch_all(connection, "SELECT * FROM approval_step WHERE flow_id = ? ORDER BY step_order", (flow_id,))


def rule_for_flow(connection: sqlite3.Connection, flow_id: int) -> sqlite3.Row:
    rule = fetch_one(connection, "SELECT * FROM approval_rule WHERE flow_id = ? ORDER BY id LIMIT 1", (flow_id,))
    if not rule:
        raise ValueError("Approval rule is not configured for this company.")
    return rule


def company_stats(connection: sqlite3.Connection, company_id: int) -> dict:
    expenses = fetch_all(connection, "SELECT * FROM expense WHERE company_id = ?", (company_id,))
    total_employees = fetch_one(connection, "SELECT COUNT(*) AS total FROM app_user WHERE company_id = ? AND role = 'EMPLOYEE'", (company_id,))["total"]
    approved_total = sum(float(row["converted_amount"]) for row in expenses if row["status"] == "APPROVED")
    return {
        "total_employees": total_employees,
        "total_expenses": len(expenses),
        "pending_approvals": len([row for row in expenses if row["status"] == "PENDING"]),
        "approved_expenses": len([row for row in expenses if row["status"] == "APPROVED"]),
        "rejected_expenses": len([row for row in expenses if row["status"] == "REJECTED"]),
        "approved_total": approved_total,
    }


class ReimaHandler(BaseHTTPRequestHandler):
    server_version = "ReimaHTTP/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in STATIC_FILES:
            self.serve_static(STATIC_FILES[parsed.path])
            return

        if parsed.path.startswith("/api/"):
            self.handle_api("GET", parsed.path, parse_qs(parsed.query))
            return

        self.serve_static("index.html")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        self.handle_api("POST", parsed.path, parse_qs(parsed.query))

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        self.handle_api("PATCH", parsed.path, parse_qs(parsed.query))

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        self.handle_api("DELETE", parsed.path, parse_qs(parsed.query))

    def log_message(self, format: str, *args) -> None:
        return

    def security_headers(self) -> list[tuple[str, str]]:
        return [
            ("X-Content-Type-Options", "nosniff"),
            ("X-Frame-Options", "DENY"),
            ("Referrer-Policy", "no-referrer"),
            ("Cache-Control", "no-store"),
            ("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"),
        ]

    def send_json(self, status: int, payload: dict, set_cookie: str | None = None, clear_cookie: bool = False) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        for key, value in self.security_headers():
            self.send_header(key, value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        if clear_cookie:
            self.send_header("Set-Cookie", self.cookie_header("", expired=True))
        self.end_headers()
        self.wfile.write(body)

    def serve_static(self, filename: str) -> None:
        path = ROOT / filename
        if not path.exists():
            self.send_error(404)
            return
        body = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        for key, value in self.security_headers():
            self.send_header(key, value)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def cookie_header(self, token: str, expired: bool = False) -> str:
        parts = [f"{SESSION_COOKIE}={token}", "Path=/", "HttpOnly", "SameSite=Strict"]
        if SECURE_COOKIE:
            parts.append("Secure")
        if expired:
            parts.append("Max-Age=0")
        else:
            parts.append(f"Max-Age={SESSION_TTL_HOURS * 3600}")
        return "; ".join(parts)

    def current_session(self, connection: sqlite3.Connection) -> dict | None:
        return session_payload(connection, get_cookie_token(self))

    def public_base_url(self) -> str:
        if PUBLIC_URL:
            return PUBLIC_URL
        forwarded_proto = self.headers.get("X-Forwarded-Proto", "").strip().lower()
        scheme = forwarded_proto if forwarded_proto in {"http", "https"} else ("https" if SECURE_COOKIE else "http")
        host = self.headers.get("Host", "127.0.0.1:8000").strip()
        return f"{scheme}://{host}"

    def send_verification_email(self, connection: sqlite3.Connection, user_id: int) -> None:
        user = fetch_one(
            connection,
            """
            SELECT u.id, u.name, u.email, u.company_id, c.name AS company_name
            FROM app_user u
            JOIN company c ON c.id = u.company_id
            WHERE u.id = ?
            """,
            (user_id,),
        )
        if not user:
            raise ValueError("User not found.")
        token = create_one_time_token(connection, "email_verification_token", user_id, timedelta(hours=EMAIL_VERIFICATION_TTL_HOURS))
        link = f"{self.public_base_url()}/#/verify-email?token={token}"
        body = (
            f"Hello {user['name']},\n\n"
            f"Verify your Reima email for {user['company_name']} by opening the link below:\n{link}\n\n"
            f"This link expires in {EMAIL_VERIFICATION_TTL_HOURS} hours."
        )
        send_email_message(user["email"], "Verify your Reima email", body)

    def send_password_reset_email(self, connection: sqlite3.Connection, user_id: int) -> None:
        user = fetch_one(
            connection,
            """
            SELECT u.id, u.name, u.email, c.name AS company_name
            FROM app_user u
            JOIN company c ON c.id = u.company_id
            WHERE u.id = ?
            """,
            (user_id,),
        )
        if not user:
            raise ValueError("User not found.")
        token = create_one_time_token(connection, "password_reset_token", user_id, timedelta(minutes=PASSWORD_RESET_TTL_MINUTES))
        link = f"{self.public_base_url()}/#/reset-password?token={token}"
        body = (
            f"Hello {user['name']},\n\n"
            f"We received a request to reset your Reima password for {user['company_name']}.\n"
            f"Open this link to choose a new password:\n{link}\n\n"
            f"This link expires in {PASSWORD_RESET_TTL_MINUTES} minutes."
        )
        send_email_message(user["email"], "Reset your Reima password", body)

    def require_auth(self, connection: sqlite3.Connection) -> dict:
        session = self.current_session(connection)
        if not session:
            raise PermissionError("Authentication required.")
        return session

    def require_role(self, session: dict, allowed_roles: set[str]) -> None:
        if session["user"]["role"] not in allowed_roles:
            raise PermissionError("You do not have permission to access this resource.")

    def require_csrf(self, session: dict) -> None:
        header_token = self.headers.get("X-CSRF-Token", "")
        if not header_token or not hmac.compare_digest(header_token, session["csrf_token"]):
            raise PermissionError("Invalid CSRF token.")

    def handle_api(self, method: str, path: str, query: dict) -> None:
        try:
            with connect_db() as connection:
                session = self.current_session(connection)
                if path == "/api/bootstrap" and method == "GET":
                    self.handle_bootstrap(connection, session)
                    return
                if path == "/api/auth/signup" and method == "POST":
                    self.handle_signup(connection)
                    return
                if path == "/api/auth/login-admin" and method == "POST":
                    self.handle_login(connection, {"ADMIN"})
                    return
                if path == "/api/auth/login-staff" and method == "POST":
                    self.handle_login(connection, {"MANAGER", "EMPLOYEE", "FINANCE", "DIRECTOR"})
                    return
                if path == "/api/auth/request-verification" and method == "POST":
                    self.handle_request_verification(connection)
                    return
                if path == "/api/auth/verify-email" and method == "POST":
                    self.handle_verify_email(connection)
                    return
                if path == "/api/auth/forgot-password" and method == "POST":
                    self.handle_forgot_password(connection)
                    return
                if path == "/api/auth/reset-password" and method == "POST":
                    self.handle_reset_password(connection)
                    return
                if path == "/api/auth/logout" and method == "POST":
                    self.handle_logout(connection, session)
                    return

                session = self.require_auth(connection)
                if method in {"POST", "PATCH", "DELETE"}:
                    self.require_csrf(session)

                if path == "/api/dashboard" and method == "GET":
                    self.handle_dashboard(connection, session)
                    return

                self.route_authenticated_api(connection, session, method, path, query)
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except PermissionError as error:
            self.send_json(403 if get_cookie_token(self) else 401, {"error": str(error)})
        except (sqlite3.IntegrityError, SAIntegrityError):
            self.send_json(400, {"error": "The requested change violates a database constraint."})
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Request body must be valid JSON."})
        except FileNotFoundError:
            self.send_json(500, {"error": "Server configuration is incomplete."})
        except Exception as error:
            self.send_json(500, {"error": "Internal server error.", "detail": str(error)})

    def handle_bootstrap(self, connection: sqlite3.Connection, session: dict | None) -> None:
        company_exists = fetch_one(connection, "SELECT COUNT(*) AS total FROM company")["total"] > 0
        countries = get_country_reference_data()
        currencies = sorted({item["currency"] for item in countries} | set(CURRENCY_IN_INR.keys()))
        payload = {
            "authenticated": bool(session),
            "can_signup_company": True,
            "countries": countries,
            "currencies": currencies,
            "database_backend": database_backend_label(),
        }
        if session:
            payload["auth"] = {
                "user": session["user"],
                "company": session["company"],
                "csrf_token": session["csrf_token"],
            }
        payload["company_exists"] = company_exists
        self.send_json(200, payload)

    def handle_signup(self, connection: sqlite3.Connection) -> None:
        payload = json_body(self)
        require_fields(payload, ["company_name", "country", "admin_name", "admin_email", "password", "confirm_password"])
        validate_password_strength(payload["password"])
        if payload["password"] != payload["confirm_password"]:
            raise ValueError("Password and confirm password must match.")

        admin_email = normalize_email(payload["admin_email"])
        existing = fetch_one(connection, "SELECT id FROM app_user WHERE email = ?", (admin_email,))
        if existing:
            raise ValueError("That admin email is already in use.")

        base_currency = currency_for_country(payload["country"])
        company_cursor = connection.execute(
            "INSERT INTO company (name, country, base_currency, created_at) VALUES (?, ?, ?, ?)",
            (payload["company_name"].strip(), payload["country"].strip(), base_currency, iso_now()),
        )
        company_id = company_cursor.lastrowid
        user_cursor = connection.execute(
            """
            INSERT INTO app_user (company_id, manager_id, name, email, password_hash, email_verified, email_verified_at, role, department, status, created_at)
            VALUES (?, NULL, ?, ?, ?, 0, NULL, 'ADMIN', 'Leadership', 'ACTIVE', ?)
            """,
            (company_id, payload["admin_name"].strip(), admin_email, hash_password(payload["password"]), iso_now()),
        )
        admin_id = user_cursor.lastrowid

        flow_cursor = connection.execute(
            "INSERT INTO approval_flow (company_id, name, created_at) VALUES (?, 'Default Expense Approval', ?)",
            (company_id, iso_now()),
        )
        flow_id = flow_cursor.lastrowid
        connection.executemany(
            "INSERT INTO approval_step (flow_id, step_order, approver_role, is_mandatory) VALUES (?, ?, ?, ?)",
            [(flow_id, 1, "MANAGER", 1), (flow_id, 2, "FINANCE", 1), (flow_id, 3, "DIRECTOR", 0)],
        )
        connection.execute(
            "INSERT INTO approval_rule (flow_id, type, threshold_percentage, specific_user_id) VALUES (?, 'HYBRID', 60, ?)",
            (flow_id, admin_id),
        )
        add_audit_log(connection, company_id, admin_id, "created_company", "Company", company_id, f"Created {payload['company_name'].strip()} and provisioned the first admin account.")
        self.send_verification_email(connection, admin_id)
        connection.commit()
        self.send_json(
            201,
            {
                "message": "Company account created. Verify the admin email before logging in.",
            },
        )

    def handle_login(self, connection: sqlite3.Connection, allowed_roles: set[str]) -> None:
        payload = json_body(self)
        require_fields(payload, ["email", "password"])
        user = fetch_one(
            connection,
            """
            SELECT u.*, c.name AS company_name, c.country, c.base_currency
            FROM app_user u
            JOIN company c ON c.id = u.company_id
            WHERE u.email = ?
            """,
            (normalize_email(payload["email"]),),
        )
        if not user or not verify_password(payload["password"], user["password_hash"]):
            raise ValueError("Invalid email or password.")
        if user["role"] not in allowed_roles:
            raise PermissionError("This login form is not valid for your role.")
        if user["status"] != "ACTIVE":
            raise PermissionError("This account is inactive.")
        if not user["email_verified"]:
            raise PermissionError("Please verify your email before logging in.")

        token, csrf_token = create_session(connection, user["id"])
        self.send_json(
            200,
            {
                "message": "Login successful.",
                "auth": {
                    "user": self.user_payload(connection, user["id"]),
                    "company": self.company_payload(connection, user["company_id"]),
                    "csrf_token": csrf_token,
                },
            },
            set_cookie=self.cookie_header(token),
        )

    def handle_request_verification(self, connection: sqlite3.Connection) -> None:
        payload = json_body(self)
        require_fields(payload, ["email"])
        email = normalize_email(payload["email"])
        user = fetch_one(connection, "SELECT id, company_id, email_verified FROM app_user WHERE email = ? AND status = 'ACTIVE'", (email,))
        if user and not user["email_verified"]:
            self.send_verification_email(connection, user["id"])
            add_audit_log(connection, user["company_id"], None, "sent_verification_email", "User", user["id"], f"Sent verification email to {email}.")
            connection.commit()
        self.send_json(200, {"message": "If the account exists and is pending verification, a verification email has been sent."})

    def handle_verify_email(self, connection: sqlite3.Connection) -> None:
        payload = json_body(self)
        require_fields(payload, ["token"])
        token_row = consume_one_time_token(
            connection,
            "email_verification_token",
            str(payload["token"]).strip(),
            "Verification link is invalid.",
            "Verification link has expired.",
        )
        user = fetch_one(connection, "SELECT id, company_id FROM app_user WHERE id = ?", (token_row["user_id"],))
        if not user:
            raise ValueError("User not found.")
        connection.execute(
            "UPDATE app_user SET email_verified = 1, email_verified_at = ? WHERE id = ?",
            (iso_now(), user["id"]),
        )
        add_audit_log(connection, user["company_id"], user["id"], "verified_email", "User", user["id"], "Verified account email.")
        connection.commit()
        self.send_json(200, {"message": "Email verified successfully. You can now log in."})

    def handle_forgot_password(self, connection: sqlite3.Connection) -> None:
        payload = json_body(self)
        require_fields(payload, ["email"])
        email = normalize_email(payload["email"])
        user = fetch_one(connection, "SELECT id, company_id FROM app_user WHERE email = ? AND status = 'ACTIVE'", (email,))
        if user:
            self.send_password_reset_email(connection, user["id"])
            add_audit_log(connection, user["company_id"], None, "sent_password_reset", "User", user["id"], f"Sent password reset email to {email}.")
            connection.commit()
        self.send_json(200, {"message": "If the account exists, a password reset link has been sent."})

    def handle_reset_password(self, connection: sqlite3.Connection) -> None:
        payload = json_body(self)
        require_fields(payload, ["token", "password", "confirm_password"])
        validate_password_strength(payload["password"])
        if payload["password"] != payload["confirm_password"]:
            raise ValueError("Password and confirm password must match.")
        token_row = consume_one_time_token(
            connection,
            "password_reset_token",
            str(payload["token"]).strip(),
            "Password reset link is invalid.",
            "Password reset link has expired.",
        )
        user = fetch_one(connection, "SELECT id, company_id FROM app_user WHERE id = ?", (token_row["user_id"],))
        if not user:
            raise ValueError("User not found.")
        connection.execute("UPDATE app_user SET password_hash = ? WHERE id = ?", (hash_password(payload["password"]), user["id"]))
        connection.execute("DELETE FROM user_session WHERE user_id = ?", (user["id"],))
        add_audit_log(connection, user["company_id"], user["id"], "reset_password", "User", user["id"], "Reset account password.")
        connection.commit()
        self.send_json(200, {"message": "Password reset successful. Please log in with the new password."})

    def handle_logout(self, connection: sqlite3.Connection, session: dict | None) -> None:
        destroy_session(connection, get_cookie_token(self))
        self.send_json(200, {"message": "Logged out successfully."}, clear_cookie=True)

    def handle_dashboard(self, connection: sqlite3.Connection, session: dict) -> None:
        role = session["user"]["role"]
        if role == "ADMIN":
            self.send_json(200, self.admin_dashboard(connection, session))
            return
        if role == "EMPLOYEE":
            self.send_json(200, self.employee_dashboard(connection, session))
            return
        self.send_json(200, self.approver_dashboard(connection, session))

    def route_authenticated_api(self, connection: sqlite3.Connection, session: dict, method: str, path: str, query: dict) -> None:
        if path == "/api/users" and method == "GET":
            self.require_role(session, {"ADMIN"})
            self.send_json(200, {"users": self.company_users(connection, session["company"]["id"])})
            return
        if path == "/api/users" and method == "POST":
            self.require_role(session, {"ADMIN"})
            self.handle_create_user(connection, session)
            return
        if path.startswith("/api/users/") and path.endswith("/status") and method == "PATCH":
            self.require_role(session, {"ADMIN"})
            user_id = int(path.split("/")[3])
            self.handle_toggle_user_status(connection, session, user_id)
            return

        if path == "/api/expenses" and method == "POST":
            self.require_role(session, {"EMPLOYEE"})
            self.handle_create_expense(connection, session)
            return
        if path == "/api/expenses/my" and method == "GET":
            self.require_role(session, {"EMPLOYEE"})
            self.send_json(200, {"expenses": self.my_expenses(connection, session)})
            return
        if path == "/api/expenses/team" and method == "GET":
            self.require_role(session, {"ADMIN", "MANAGER", "FINANCE", "DIRECTOR"})
            self.send_json(200, {"expenses": self.team_expenses(connection, session)})
            return
        if path == "/api/expenses/company" and method == "GET":
            self.require_role(session, {"ADMIN", "FINANCE", "DIRECTOR"})
            self.send_json(200, {"expenses": self.company_expenses(connection, session)})
            return
        if path.startswith("/api/expenses/") and method == "GET":
            expense_id = int(path.split("/")[3])
            self.send_json(200, {"expense": self.expense_details(connection, session, expense_id)})
            return
        if path.startswith("/api/expenses/") and method == "PATCH":
            self.require_role(session, {"EMPLOYEE"})
            expense_id = int(path.split("/")[3])
            self.handle_update_expense(connection, session, expense_id)
            return
        if path.startswith("/api/expenses/") and method == "DELETE":
            self.require_role(session, {"EMPLOYEE"})
            expense_id = int(path.split("/")[3])
            self.handle_delete_expense(connection, session, expense_id)
            return

        if path == "/api/approvals/pending" and method == "GET":
            self.require_role(session, {"ADMIN", "MANAGER", "FINANCE", "DIRECTOR"})
            self.send_json(200, {"approvals": self.pending_approvals(connection, session)})
            return
        if path == "/api/approvals/history" and method == "GET":
            self.require_role(session, {"ADMIN", "MANAGER", "FINANCE", "DIRECTOR"})
            self.send_json(200, {"approvals": self.approval_history(connection, session)})
            return
        if path.startswith("/api/approvals/") and path.endswith("/approve") and method == "POST":
            self.require_role(session, {"ADMIN", "MANAGER", "FINANCE", "DIRECTOR"})
            approval_id = int(path.split("/")[3])
            self.handle_approval_action(connection, session, approval_id, "APPROVED")
            return
        if path.startswith("/api/approvals/") and path.endswith("/reject") and method == "POST":
            self.require_role(session, {"ADMIN", "MANAGER", "FINANCE", "DIRECTOR"})
            approval_id = int(path.split("/")[3])
            self.handle_approval_action(connection, session, approval_id, "REJECTED")
            return

        if path == "/api/workflow" and method == "GET":
            self.require_role(session, {"ADMIN"})
            self.send_json(200, self.workflow_payload(connection, session["company"]["id"]))
            return
        if path == "/api/workflow/steps" and method == "POST":
            self.require_role(session, {"ADMIN"})
            self.handle_add_step(connection, session)
            return
        if path.startswith("/api/workflow/steps/") and path.endswith("/move") and method == "POST":
            self.require_role(session, {"ADMIN"})
            step_id = int(path.split("/")[4])
            self.handle_move_step(connection, session, step_id)
            return
        if path.startswith("/api/workflow/steps/") and method == "PATCH":
            self.require_role(session, {"ADMIN"})
            step_id = int(path.split("/")[4])
            self.handle_update_step(connection, session, step_id)
            return
        if path.startswith("/api/workflow/steps/") and method == "DELETE":
            self.require_role(session, {"ADMIN"})
            step_id = int(path.split("/")[4])
            self.handle_delete_step(connection, session, step_id)
            return
        if path == "/api/workflow/rule" and method == "PATCH":
            self.require_role(session, {"ADMIN"})
            self.handle_update_rule(connection, session)
            return

        if path == "/api/company/currency" and method == "PATCH":
            self.require_role(session, {"ADMIN"})
            self.handle_update_company_currency(connection, session)
            return

        if path == "/api/reports" and method == "GET":
            self.require_role(session, {"ADMIN", "FINANCE", "DIRECTOR"})
            self.send_json(200, self.reports_payload(connection, session))
            return
        if path == "/api/audit-logs" and method == "GET":
            self.require_role(session, {"ADMIN"})
            self.send_json(200, {"logs": self.audit_logs_payload(connection, session["company"]["id"])})
            return
        if path == "/api/notifications" and method == "GET":
            self.send_json(200, {"notifications": self.notifications_payload(connection, session["user"]["id"])})
            return
        if path == "/api/notifications/read-all" and method == "POST":
            connection.execute("UPDATE notification SET is_read = 1 WHERE user_id = ?", (session["user"]["id"],))
            connection.commit()
            self.send_json(200, {"message": "Notifications marked as read."})
            return

        if path == "/api/profile" and method == "GET":
            self.send_json(200, {"profile": self.user_payload(connection, session["user"]["id"]), "company": self.company_payload(connection, session["company"]["id"])})
            return
        if path == "/api/profile" and method == "PATCH":
            self.handle_update_profile(connection, session)
            return

        raise ValueError("Unknown endpoint.")

    def user_payload(self, connection: sqlite3.Connection, user_id: int) -> dict:
        user = fetch_one(
            connection,
            "SELECT id, company_id, manager_id, name, email, email_verified, email_verified_at, role, department, status, created_at FROM app_user WHERE id = ?",
            (user_id,),
        )
        if not user:
            raise ValueError("User not found.")
        return dict(user)

    def company_payload(self, connection: sqlite3.Connection, company_id: int) -> dict:
        company = fetch_one(connection, "SELECT id, name, country, base_currency, created_at FROM company WHERE id = ?", (company_id,))
        if not company:
            raise ValueError("Company not found.")
        return dict(company)

    def notifications_payload(self, connection: sqlite3.Connection, user_id: int) -> list[dict]:
        rows = fetch_all(connection, "SELECT * FROM notification WHERE user_id = ? ORDER BY created_at DESC LIMIT 10", (user_id,))
        return [dict(row) for row in rows]

    def company_users(self, connection: sqlite3.Connection, company_id: int) -> list[dict]:
        users = fetch_all(
            connection,
            """
            SELECT u.id, u.name, u.email, u.email_verified, u.role, u.department, u.status, u.created_at, m.name AS manager_name
            FROM app_user u
            LEFT JOIN app_user m ON m.id = u.manager_id
            WHERE u.company_id = ?
            ORDER BY u.role, u.name
            """,
            (company_id,),
        )
        return [dict(row) for row in users]

    def expense_base_query(self) -> str:
        return """
            SELECT e.*,
                   u.name AS employee_name,
                   u.role AS employee_role,
                   c.base_currency,
                   c.name AS company_name
            FROM expense e
            JOIN app_user u ON u.id = e.user_id
            JOIN company c ON c.id = e.company_id
        """

    def serialize_expense(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict:
        expense = dict(row)
        approvals = fetch_all(
            connection,
            """
            SELECT ea.*, u.name AS approver_name
            FROM expense_approval ea
            LEFT JOIN app_user u ON u.id = ea.approver_id
            WHERE ea.expense_id = ?
            ORDER BY ea.step_order
            """,
            (row["id"],),
        )
        expense["approvals"] = [dict(item) for item in approvals]
        expense["is_draft"] = expense["status"] == "PENDING" and len(expense["approvals"]) == 0
        expense["display_status"] = "DRAFT" if expense["is_draft"] else expense["status"]
        return expense

    def my_expenses(self, connection: sqlite3.Connection, session: dict) -> list[dict]:
        rows = fetch_all(connection, self.expense_base_query() + " WHERE e.user_id = ? ORDER BY e.created_at DESC", (session["user"]["id"],))
        return [self.serialize_expense(connection, row) for row in rows]

    def team_expenses(self, connection: sqlite3.Connection, session: dict) -> list[dict]:
        if session["user"]["role"] == "MANAGER":
            rows = fetch_all(
                connection,
                self.expense_base_query() + " WHERE u.manager_id = ? ORDER BY e.created_at DESC",
                (session["user"]["id"],),
            )
        else:
            rows = fetch_all(
                connection,
                self.expense_base_query() + " WHERE e.company_id = ? ORDER BY e.created_at DESC",
                (session["company"]["id"],),
            )
        return [self.serialize_expense(connection, row) for row in rows]

    def company_expenses(self, connection: sqlite3.Connection, session: dict) -> list[dict]:
        rows = fetch_all(
            connection,
            self.expense_base_query() + " WHERE e.company_id = ? ORDER BY e.created_at DESC",
            (session["company"]["id"],),
        )
        return [self.serialize_expense(connection, row) for row in rows]

    def expense_details(self, connection: sqlite3.Connection, session: dict, expense_id: int) -> dict:
        row = fetch_one(connection, self.expense_base_query() + " WHERE e.id = ?", (expense_id,))
        if not row:
            raise ValueError("Expense not found.")
        if session["user"]["role"] == "EMPLOYEE" and row["user_id"] != session["user"]["id"]:
            raise PermissionError("You may only view your own expenses.")
        if session["user"]["role"] == "MANAGER" and row["employee_role"] == "EMPLOYEE":
            employee = fetch_one(connection, "SELECT manager_id FROM app_user WHERE id = ?", (row["user_id"],))
            if employee["manager_id"] != session["user"]["id"]:
                raise PermissionError("This expense is outside your team.")
        return self.serialize_expense(connection, row)

    def pending_approvals(self, connection: sqlite3.Connection, session: dict) -> list[dict]:
        rows = fetch_all(
            connection,
            """
            SELECT ea.*, e.amount, e.currency, e.expense_date, e.description, e.category, e.status AS expense_status, e.id AS expense_id,
                   u.name AS employee_name
            FROM expense_approval ea
            JOIN expense e ON e.id = ea.expense_id
            JOIN app_user u ON u.id = e.user_id
            WHERE ea.approver_id = ? AND ea.status = 'PENDING'
            ORDER BY e.created_at ASC
            """,
            (session["user"]["id"],),
        )
        actionable = [dict(row) for row in rows if self.approval_actionable(connection, row["id"])]
        return actionable

    def approval_history(self, connection: sqlite3.Connection, session: dict) -> list[dict]:
        rows = fetch_all(
            connection,
            """
            SELECT ea.*, e.id AS expense_id, e.amount, e.currency, e.expense_date, e.category, e.status AS expense_status, u.name AS employee_name
            FROM expense_approval ea
            JOIN expense e ON e.id = ea.expense_id
            JOIN app_user u ON u.id = e.user_id
            WHERE ea.approver_id = ? AND ea.status != 'PENDING'
            ORDER BY ea.action_date DESC
            """,
            (session["user"]["id"],),
        )
        return [dict(row) for row in rows]

    def workflow_payload(self, connection: sqlite3.Connection, company_id: int) -> dict:
        flow = flow_for_company(connection, company_id)
        steps = [dict(row) for row in steps_for_flow(connection, flow["id"])]
        rule = dict(rule_for_flow(connection, flow["id"]))
        approvers = [
            dict(row)
            for row in fetch_all(
                connection,
                "SELECT id, name, role FROM app_user WHERE company_id = ? AND role IN ('ADMIN', 'MANAGER', 'FINANCE', 'DIRECTOR') AND status = 'ACTIVE' ORDER BY role, name",
                (company_id,),
            )
        ]
        return {"flow": dict(flow), "steps": steps, "rule": rule, "approvers": approvers}

    def reports_payload(self, connection: sqlite3.Connection, session: dict) -> dict:
        expenses = self.company_expenses(connection, session)
        monthly: dict[str, float] = {}
        categories: dict[str, float] = {}
        employees: dict[str, float] = {}
        for expense in expenses:
            month = expense["expense_date"][:7]
            monthly[month] = monthly.get(month, 0.0) + float(expense["converted_amount"])
            categories[expense["category"]] = categories.get(expense["category"], 0.0) + float(expense["converted_amount"])
            employees[expense["employee_name"]] = employees.get(expense["employee_name"], 0.0) + float(expense["converted_amount"])
        approved = [expense for expense in expenses if expense["status"] == "APPROVED"]
        pending = [expense for expense in expenses if expense["status"] == "PENDING"]
        return {
            "monthly": monthly,
            "categories": categories,
            "employees": employees,
            "summary": {
                "approved_total": sum(float(item["converted_amount"]) for item in approved),
                "pending_total": sum(float(item["converted_amount"]) for item in pending),
                "approved_count": len(approved),
                "pending_count": len(pending),
            },
        }

    def audit_logs_payload(self, connection: sqlite3.Connection, company_id: int) -> list[dict]:
        rows = fetch_all(
            connection,
            """
            SELECT al.*, u.name AS actor_name
            FROM audit_log al
            LEFT JOIN app_user u ON u.id = al.actor_id
            WHERE al.company_id = ?
            ORDER BY al.created_at DESC
            LIMIT 100
            """,
            (company_id,),
        )
        return [dict(row) for row in rows]

    def admin_dashboard(self, connection: sqlite3.Connection, session: dict) -> dict:
        stats = company_stats(connection, session["company"]["id"])
        recent_expenses = self.company_expenses(connection, session)[:6]
        logs = self.audit_logs_payload(connection, session["company"]["id"])[:6]
        return {"role": "ADMIN", "stats": stats, "expenses": recent_expenses, "logs": logs, "notifications": self.notifications_payload(connection, session["user"]["id"])}

    def employee_dashboard(self, connection: sqlite3.Connection, session: dict) -> dict:
        expenses = self.my_expenses(connection, session)
        approved = [row for row in expenses if row["status"] == "APPROVED"]
        drafts = [row for row in expenses if row["display_status"] == "DRAFT"]
        waiting = [row for row in expenses if row["display_status"] == "PENDING"]
        return {
            "role": "EMPLOYEE",
            "stats": {
                "submitted": len(expenses),
                "drafts": len(drafts),
                "waiting_approval": len(waiting),
                "approved": len(approved),
                "rejected": len([row for row in expenses if row["status"] == "REJECTED"]),
                "reimbursed_total": sum(float(row["converted_amount"]) for row in approved),
            },
            "expenses": expenses[:6],
            "notifications": self.notifications_payload(connection, session["user"]["id"]),
        }

    def approver_dashboard(self, connection: sqlite3.Connection, session: dict) -> dict:
        pending = self.pending_approvals(connection, session)
        history = self.approval_history(connection, session)
        team = self.team_expenses(connection, session)
        return {
            "role": "ADMIN" if session["user"]["role"] == "ADMIN" else session["user"]["role"],
            "stats": {
                "pending": len(pending),
                "approved_by_me": len([row for row in history if row["status"] == "APPROVED"]),
                "rejected_by_me": len([row for row in history if row["status"] == "REJECTED"]),
                "team_expenses": len(team),
            },
            "pending": pending[:6],
            "history": history[:6],
            "notifications": self.notifications_payload(connection, session["user"]["id"]),
        }

    def resolve_approvers(self, connection: sqlite3.Connection, company_id: int, employee_id: int, role: str, is_mandatory: bool = True) -> list[sqlite3.Row]:
        if role == "MANAGER":
            manager = fetch_one(
                connection,
                """
                SELECT m.*
                FROM app_user e
                JOIN app_user m ON m.id = e.manager_id
                WHERE e.id = ? AND m.status = 'ACTIVE'
                """,
                (employee_id,),
            )
            if not manager:
                if is_mandatory:
                    raise ValueError("A manager must be assigned before this expense can be submitted.")
                return []
            return [manager]
        if role == "DIRECTOR":
            approvers = fetch_all(
                connection,
                "SELECT * FROM app_user WHERE company_id = ? AND role IN ('ADMIN', 'DIRECTOR') AND status = 'ACTIVE' ORDER BY role, name",
                (company_id,),
            )
        else:
            approvers = fetch_all(
                connection,
                "SELECT * FROM app_user WHERE company_id = ? AND role = ? AND status = 'ACTIVE' ORDER BY name",
                (company_id, role),
            )
        if not approvers:
            if is_mandatory:
                raise ValueError(f"No active {ROLE_LABELS[role].lower()} is configured for the approval flow.")
            return []
        return approvers

    def create_expense_approvals(self, connection: sqlite3.Connection, expense_id: int, company_id: int, employee_id: int) -> None:
        flow = flow_for_company(connection, company_id)
        steps = steps_for_flow(connection, flow["id"])
        for step in steps:
            approvers = self.resolve_approvers(connection, company_id, employee_id, step["approver_role"], bool(step["is_mandatory"]))
            for approver in approvers:
                connection.execute(
                    """
                    INSERT INTO expense_approval (expense_id, approver_id, step_order, approver_role, is_mandatory, status, comment, action_date)
                    VALUES (?, ?, ?, ?, ?, 'PENDING', '', NULL)
                    """,
                    (expense_id, approver["id"], step["step_order"], step["approver_role"], step["is_mandatory"]),
                )

    def approval_actionable(self, connection: sqlite3.Connection, approval_id: int) -> bool:
        approval = fetch_one(connection, "SELECT * FROM expense_approval WHERE id = ?", (approval_id,))
        if not approval or approval["status"] != "PENDING":
            return False
        expense = fetch_one(connection, "SELECT status FROM expense WHERE id = ?", (approval["expense_id"],))
        if not expense or expense["status"] != "PENDING":
            return False
        prior_steps = fetch_all(
            connection,
            "SELECT status FROM expense_approval WHERE expense_id = ? AND step_order < ?",
            (approval["expense_id"], approval["step_order"]),
        )
        return all(step["status"] != "PENDING" for step in prior_steps)

    def refresh_expense_status(self, connection: sqlite3.Connection, expense_id: int) -> None:
        expense = fetch_one(connection, "SELECT * FROM expense WHERE id = ?", (expense_id,))
        if not expense:
            raise ValueError("Expense not found.")
        flow = flow_for_company(connection, expense["company_id"])
        rule = rule_for_flow(connection, flow["id"])
        approvals = fetch_all(connection, "SELECT * FROM expense_approval WHERE expense_id = ? ORDER BY step_order", (expense_id,))

        if not approvals:
            connection.execute("UPDATE expense SET status = 'PENDING' WHERE id = ?", (expense_id,))
            return

        approved_count = len([row for row in approvals if row["status"] == "APPROVED"])
        total_count = max(len(approvals), 1)
        threshold_met = (approved_count / total_count) * 100 >= float(rule["threshold_percentage"] or 0)
        specific_approved = bool(rule["specific_user_id"]) and any(
            row["approver_id"] == rule["specific_user_id"] and row["status"] == "APPROVED" for row in approvals
        )
        all_resolved = all(row["status"] != "PENDING" for row in approvals)

        approved = False
        if rule["type"] == "PERCENTAGE":
            approved = threshold_met
        elif rule["type"] == "SPECIFIC":
            approved = specific_approved
        elif rule["type"] == "HYBRID":
            approved = threshold_met or specific_approved

        if all_resolved:
            connection.execute("UPDATE expense SET status = ? WHERE id = ?", ("APPROVED" if approved else "REJECTED", expense_id))
        else:
            connection.execute("UPDATE expense SET status = 'PENDING' WHERE id = ?", (expense_id,))

    def handle_create_user(self, connection: sqlite3.Connection, session: dict) -> None:
        payload = json_body(self)
        require_fields(payload, ["name", "email", "password", "role", "department"])
        validate_password_strength(payload["password"])
        role = payload["role"].strip().upper()
        if role not in {"MANAGER", "EMPLOYEE", "FINANCE", "DIRECTOR"}:
            raise ValueError("Invalid role.")
        email = normalize_email(payload["email"])
        if fetch_one(connection, "SELECT id FROM app_user WHERE email = ?", (email,)):
            raise ValueError("That email address is already registered.")

        manager_id = payload.get("manager_id") or None
        if role == "EMPLOYEE" and not manager_id:
            raise ValueError("Employees must be assigned to a manager.")

        cursor = connection.execute(
            """
            INSERT INTO app_user (company_id, manager_id, name, email, password_hash, role, department, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
            """,
            (
                session["company"]["id"],
                manager_id,
                payload["name"].strip(),
                email,
                hash_password(payload["password"]),
                role,
                payload["department"].strip(),
                iso_now(),
            ),
        )
        user_id = cursor.lastrowid
        self.send_verification_email(connection, user_id)
        add_audit_log(connection, session["company"]["id"], session["user"]["id"], "created_user", "User", user_id, f"Created {payload['name'].strip()} as {ROLE_LABELS[role]}.")
        connection.commit()
        self.send_json(201, {"message": "User created successfully. Verification email sent.", "user": self.user_payload(connection, user_id)})

    def handle_toggle_user_status(self, connection: sqlite3.Connection, session: dict, user_id: int) -> None:
        target = fetch_one(connection, "SELECT * FROM app_user WHERE id = ? AND company_id = ?", (user_id, session["company"]["id"]))
        if not target:
            raise ValueError("User not found.")
        if target["role"] == "ADMIN":
            raise ValueError("The primary admin cannot be deactivated from this screen.")
        new_status = "INACTIVE" if target["status"] == "ACTIVE" else "ACTIVE"
        connection.execute("UPDATE app_user SET status = ? WHERE id = ?", (new_status, user_id))
        add_audit_log(connection, session["company"]["id"], session["user"]["id"], "updated_user_status", "User", user_id, f"Changed {target['name']} to {new_status}.")
        connection.commit()
        self.send_json(200, {"message": f"User marked as {new_status.lower()}."})

    def handle_create_expense(self, connection: sqlite3.Connection, session: dict) -> None:
        payload = json_body(self)
        require_fields(payload, ["amount", "currency", "category", "description", "vendor", "expense_date"])
        amount = float(payload["amount"])
        if amount <= 0:
            raise ValueError("Amount must be greater than zero.")
        workflow_action = str(payload.get("workflow_action", "submit")).lower()
        if workflow_action not in {"draft", "submit"}:
            workflow_action = "submit"

        converted_amount = convert_currency(amount, payload["currency"], session["company"]["base_currency"])
        cursor = connection.execute(
            """
            INSERT INTO expense (
                company_id, user_id, amount, currency, converted_amount, category, description, vendor,
                expense_date, status, receipt_name, receipt_data, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)
            """,
            (
                session["company"]["id"],
                session["user"]["id"],
                amount,
                payload["currency"],
                converted_amount,
                payload["category"].strip(),
                payload["description"].strip(),
                payload["vendor"].strip(),
                payload["expense_date"],
                payload.get("receipt_name", ""),
                payload.get("receipt_data", ""),
                iso_now(),
            ),
        )
        expense_id = cursor.lastrowid
        if workflow_action == "submit":
            self.create_expense_approvals(connection, expense_id, session["company"]["id"], session["user"]["id"])
            add_audit_log(connection, session["company"]["id"], session["user"]["id"], "submitted_expense", "Expense", expense_id, f"Submitted a {payload['category'].strip().lower()} expense.")
            self.notify_next_approvers(connection, expense_id)
            message = "Expense submitted successfully."
        else:
            add_audit_log(connection, session["company"]["id"], session["user"]["id"], "saved_draft_expense", "Expense", expense_id, "Saved an expense as draft.")
            message = "Draft saved successfully."
        connection.commit()
        self.send_json(201, {"message": message, "expense": self.expense_details(connection, session, expense_id)})

    def handle_update_expense(self, connection: sqlite3.Connection, session: dict, expense_id: int) -> None:
        expense = fetch_one(connection, "SELECT * FROM expense WHERE id = ? AND user_id = ?", (expense_id, session["user"]["id"]))
        if not expense:
            raise ValueError("Expense not found.")
        approval_count = fetch_one(connection, "SELECT COUNT(*) AS total FROM expense_approval WHERE expense_id = ?", (expense_id,))["total"]
        if expense["status"] != "PENDING" or approval_count > 0:
            raise ValueError("Only draft expenses can be edited.")
        payload = json_body(self)
        require_fields(payload, ["amount", "currency", "category", "description", "vendor", "expense_date"])
        amount = float(payload["amount"])
        if amount <= 0:
            raise ValueError("Amount must be greater than zero.")
        workflow_action = str(payload.get("workflow_action", "submit")).lower()
        converted_amount = convert_currency(amount, payload["currency"], session["company"]["base_currency"])
        connection.execute(
            """
            UPDATE expense
            SET amount = ?, currency = ?, converted_amount = ?, category = ?, description = ?, vendor = ?,
                expense_date = ?, receipt_name = ?, receipt_data = ?
            WHERE id = ?
            """,
            (
                amount,
                payload["currency"],
                converted_amount,
                payload["category"].strip(),
                payload["description"].strip(),
                payload["vendor"].strip(),
                payload["expense_date"],
                payload.get("receipt_name", expense["receipt_name"]),
                payload.get("receipt_data", expense["receipt_data"]),
                expense_id,
            ),
        )
        if workflow_action == "submit":
            self.create_expense_approvals(connection, expense_id, session["company"]["id"], session["user"]["id"])
            add_audit_log(connection, session["company"]["id"], session["user"]["id"], "submitted_expense", "Expense", expense_id, "Submitted a draft expense for approval.")
            self.notify_next_approvers(connection, expense_id)
            message = "Draft submitted for approval."
        else:
            add_audit_log(connection, session["company"]["id"], session["user"]["id"], "updated_expense", "Expense", expense_id, "Updated a draft expense.")
            message = "Draft updated successfully."
        connection.commit()
        self.send_json(200, {"message": message})

    def handle_delete_expense(self, connection: sqlite3.Connection, session: dict, expense_id: int) -> None:
        expense = fetch_one(connection, "SELECT * FROM expense WHERE id = ? AND user_id = ?", (expense_id, session["user"]["id"]))
        if not expense:
            raise ValueError("Expense not found.")
        approval_count = fetch_one(connection, "SELECT COUNT(*) AS total FROM expense_approval WHERE expense_id = ?", (expense_id,))["total"]
        if expense["status"] != "PENDING" or approval_count > 0:
            raise ValueError("Only draft expenses can be deleted.")
        connection.execute("DELETE FROM expense WHERE id = ?", (expense_id,))
        add_audit_log(connection, session["company"]["id"], session["user"]["id"], "deleted_expense", "Expense", expense_id, "Deleted a draft expense.")
        connection.commit()
        self.send_json(200, {"message": "Expense deleted successfully."})

    def notify_next_approvers(self, connection: sqlite3.Connection, expense_id: int) -> None:
        approvals = fetch_all(connection, "SELECT id, approver_id FROM expense_approval WHERE expense_id = ? AND status = 'PENDING'", (expense_id,))
        for approval in approvals:
            if self.approval_actionable(connection, approval["id"]):
                add_notification(connection, approval["approver_id"], f"Expense #{expense_id} is ready for your approval.")

    def handle_approval_action(self, connection: sqlite3.Connection, session: dict, approval_id: int, action_status: str) -> None:
        approval = fetch_one(connection, "SELECT * FROM expense_approval WHERE id = ? AND approver_id = ?", (approval_id, session["user"]["id"]))
        if not approval:
            raise ValueError("Approval not found.")
        if approval["status"] != "PENDING":
            raise ValueError("This approval has already been processed.")
        if not self.approval_actionable(connection, approval_id):
            raise ValueError("This approval step is not actionable yet.")

        payload = json_body(self)
        comment = str(payload.get("comment", "")).strip()
        if action_status == "REJECTED" and not comment:
            raise ValueError("A rejection comment is required.")

        connection.execute(
            "UPDATE expense_approval SET status = ?, comment = ?, action_date = ? WHERE id = ?",
            (action_status, comment, iso_now(), approval_id),
        )
        self.refresh_expense_status(connection, approval["expense_id"])
        expense = fetch_one(connection, "SELECT * FROM expense WHERE id = ?", (approval["expense_id"],))
        add_audit_log(
            connection,
            session["company"]["id"],
            session["user"]["id"],
            "approved_expense" if action_status == "APPROVED" else "rejected_expense",
            "Expense",
            approval["expense_id"],
            f"{session['user']['name']} {action_status.lower()} expense #{approval['expense_id']}.",
        )
        if expense["status"] == "PENDING":
            add_notification(connection, expense["user_id"], f"Expense #{approval['expense_id']} moved to the next approval stage.")
        else:
            add_notification(connection, expense["user_id"], f"Expense #{approval['expense_id']} was {expense['status'].lower()}.")
        if expense["status"] == "PENDING":
            self.notify_next_approvers(connection, approval["expense_id"])
        connection.commit()
        self.send_json(200, {"message": f"Expense {action_status.lower()} successfully."})

    def handle_add_step(self, connection: sqlite3.Connection, session: dict) -> None:
        payload = json_body(self)
        require_fields(payload, ["approver_role"])
        role = payload["approver_role"].strip().upper()
        if role not in {"MANAGER", "FINANCE", "DIRECTOR"}:
            raise ValueError("Invalid step role.")
        flow = flow_for_company(connection, session["company"]["id"])
        current_steps = steps_for_flow(connection, flow["id"])
        connection.execute(
            "INSERT INTO approval_step (flow_id, step_order, approver_role, is_mandatory) VALUES (?, ?, ?, ?)",
            (flow["id"], len(current_steps) + 1, role, 1 if payload.get("is_mandatory", True) else 0),
        )
        add_audit_log(connection, session["company"]["id"], session["user"]["id"], "added_approval_step", "ApprovalStep", flow["id"], f"Added {ROLE_LABELS[role]} to the approval flow.")
        connection.commit()
        self.send_json(201, {"message": "Approval step added."})

    def handle_move_step(self, connection: sqlite3.Connection, session: dict, step_id: int) -> None:
        payload = json_body(self)
        direction = payload.get("direction")
        if direction not in {"up", "down"}:
            raise ValueError("Direction must be 'up' or 'down'.")
        step = fetch_one(connection, "SELECT * FROM approval_step WHERE id = ?", (step_id,))
        if not step:
            raise ValueError("Approval step not found.")
        target_order = step["step_order"] - 1 if direction == "up" else step["step_order"] + 1
        swap = fetch_one(connection, "SELECT * FROM approval_step WHERE flow_id = ? AND step_order = ?", (step["flow_id"], target_order))
        if not swap:
            self.send_json(200, {"message": "Step order unchanged."})
            return
        connection.execute("UPDATE approval_step SET step_order = -1 WHERE id = ?", (step_id,))
        connection.execute("UPDATE approval_step SET step_order = ? WHERE id = ?", (step["step_order"], swap["id"]))
        connection.execute("UPDATE approval_step SET step_order = ? WHERE id = ?", (target_order, step_id))
        connection.commit()
        self.send_json(200, {"message": "Step order updated."})

    def handle_update_step(self, connection: sqlite3.Connection, session: dict, step_id: int) -> None:
        payload = json_body(self)
        step = fetch_one(connection, "SELECT * FROM approval_step WHERE id = ?", (step_id,))
        if not step:
            raise ValueError("Approval step not found.")
        role = payload.get("approver_role", step["approver_role"]).strip().upper()
        if role not in {"MANAGER", "FINANCE", "DIRECTOR"}:
            raise ValueError("Invalid step role.")
        is_mandatory = 1 if payload.get("is_mandatory", bool(step["is_mandatory"])) else 0
        connection.execute(
            "UPDATE approval_step SET approver_role = ?, is_mandatory = ? WHERE id = ?",
            (role, is_mandatory, step_id),
        )
        connection.commit()
        self.send_json(200, {"message": "Approval step updated."})

    def handle_delete_step(self, connection: sqlite3.Connection, session: dict, step_id: int) -> None:
        step = fetch_one(connection, "SELECT * FROM approval_step WHERE id = ?", (step_id,))
        if not step:
            raise ValueError("Approval step not found.")
        count = fetch_one(connection, "SELECT COUNT(*) AS total FROM approval_step WHERE flow_id = ?", (step["flow_id"],))["total"]
        if count <= 1:
            raise ValueError("At least one approval step must remain.")
        connection.execute("DELETE FROM approval_step WHERE id = ?", (step_id,))
        remaining = fetch_all(connection, "SELECT id FROM approval_step WHERE flow_id = ? ORDER BY step_order", (step["flow_id"],))
        for index, row in enumerate(remaining, start=1):
            connection.execute("UPDATE approval_step SET step_order = ? WHERE id = ?", (index, row["id"]))
        connection.commit()
        self.send_json(200, {"message": "Approval step deleted."})

    def handle_update_rule(self, connection: sqlite3.Connection, session: dict) -> None:
        payload = json_body(self)
        flow = flow_for_company(connection, session["company"]["id"])
        rule = rule_for_flow(connection, flow["id"])
        rule_type = payload.get("type", rule["type"]).strip().upper()
        if rule_type not in {"PERCENTAGE", "SPECIFIC", "HYBRID"}:
            raise ValueError("Invalid rule type.")
        threshold_value = payload.get("threshold_percentage", rule["threshold_percentage"] or 60)
        threshold = None
        if rule_type in {"PERCENTAGE", "HYBRID"}:
            threshold = float(threshold_value)
            if threshold <= 0 or threshold > 100:
                raise ValueError("Threshold percentage must be between 1 and 100.")
        specific_user_id = payload.get("specific_user_id") or None
        if rule_type in {"SPECIFIC", "HYBRID"} and not specific_user_id:
            raise ValueError("Specific approver is required for specific and hybrid rules.")
        if specific_user_id:
            approver = fetch_one(
                connection,
                "SELECT id FROM app_user WHERE id = ? AND company_id = ? AND role IN ('ADMIN', 'MANAGER', 'FINANCE', 'DIRECTOR')",
                (specific_user_id, session["company"]["id"]),
            )
            if not approver:
                raise ValueError("Specific approver must be an admin/director, manager, or finance approver in this company.")
        connection.execute(
            "UPDATE approval_rule SET type = ?, threshold_percentage = ?, specific_user_id = ? WHERE id = ?",
            (rule_type, threshold, specific_user_id, rule["id"]),
        )
        add_audit_log(connection, session["company"]["id"], session["user"]["id"], "updated_approval_rule", "ApprovalRule", rule["id"], "Updated approval rule configuration.")
        connection.commit()
        self.send_json(200, {"message": "Approval rule updated."})

    def handle_update_company_currency(self, connection: sqlite3.Connection, session: dict) -> None:
        payload = json_body(self)
        require_fields(payload, ["country", "base_currency"])
        base_currency = payload["base_currency"].strip().upper()
        if len(base_currency) != 3 or not base_currency.isalpha():
            raise ValueError("Unsupported base currency.")
        connection.execute(
            "UPDATE company SET country = ?, base_currency = ? WHERE id = ?",
            (payload["country"].strip(), base_currency, session["company"]["id"]),
        )
        expenses = fetch_all(connection, "SELECT id, amount, currency FROM expense WHERE company_id = ?", (session["company"]["id"],))
        for expense in expenses:
            converted_amount = convert_currency(float(expense["amount"]), expense["currency"], base_currency)
            connection.execute("UPDATE expense SET converted_amount = ? WHERE id = ?", (converted_amount, expense["id"]))
        add_audit_log(connection, session["company"]["id"], session["user"]["id"], "updated_currency", "Company", session["company"]["id"], f"Updated base currency to {base_currency}.")
        connection.commit()
        self.send_json(200, {"message": "Company currency updated."})

    def handle_update_profile(self, connection: sqlite3.Connection, session: dict) -> None:
        payload = json_body(self)
        require_fields(payload, ["name", "email", "department"])
        email = normalize_email(payload["email"])
        existing = fetch_one(connection, "SELECT id FROM app_user WHERE email = ? AND id != ?", (email, session["user"]["id"]))
        if existing:
            raise ValueError("That email is already in use.")
        password_hash = None
        if payload.get("password"):
            validate_password_strength(payload["password"])
            password_hash = hash_password(payload["password"])
        current_user = fetch_one(connection, "SELECT email, company_id FROM app_user WHERE id = ?", (session["user"]["id"],))
        email_changed = email != current_user["email"]
        connection.execute(
            """
            UPDATE app_user
            SET name = ?, email = ?, department = ?, password_hash = COALESCE(?, password_hash),
                email_verified = CASE WHEN ? THEN 0 ELSE email_verified END,
                email_verified_at = CASE WHEN ? THEN NULL ELSE email_verified_at END
            WHERE id = ?
            """,
            (payload["name"].strip(), email, payload["department"].strip(), password_hash, 1 if email_changed else 0, 1 if email_changed else 0, session["user"]["id"]),
        )
        if email_changed:
            self.send_verification_email(connection, session["user"]["id"])
            add_audit_log(connection, current_user["company_id"], session["user"]["id"], "changed_email", "User", session["user"]["id"], f"Changed account email to {email}.")
        connection.commit()
        self.send_json(200, {"message": "Profile updated successfully." if not email_changed else "Profile updated. Please verify the new email address."})


def run() -> None:
    ensure_database()
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), ReimaHandler)
    print(f"Reima running on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
