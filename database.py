import os
import re
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


ROOT = Path(__file__).resolve().parent


def load_env_file() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env_file()

DEFAULT_DATABASE_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/reima"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL).strip()


class Base(DeclarativeBase):
    pass


engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _convert_qmark_sql(query: str, params: tuple[Any, ...] | list[Any] | None = None) -> tuple[str, dict[str, Any]]:
    params = tuple(params or ())
    if "?" not in query:
        return query, {}
    parts = query.split("?")
    rebuilt: list[str] = []
    bound: dict[str, Any] = {}
    for index, part in enumerate(parts[:-1]):
        key = f"p{index}"
        rebuilt.append(part)
        rebuilt.append(f":{key}")
        bound[key] = params[index]
    rebuilt.append(parts[-1])
    return "".join(rebuilt), bound


class DBResult:
    def __init__(self, rows: list[dict[str, Any]] | None = None, lastrowid: Any = None):
        self._rows = rows or []
        self.lastrowid = lastrowid

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


class DatabaseSession(AbstractContextManager):
    def __init__(self) -> None:
        self.session: Session = SessionLocal()

    def __enter__(self) -> "DatabaseSession":
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        if exc_type:
            self.session.rollback()
        self.session.close()
        return False

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def close(self) -> None:
        self.session.close()

    def execute(self, query: str, params: tuple[Any, ...] | list[Any] | None = None) -> DBResult:
        sql = query.strip()
        converted_sql, bound = _convert_qmark_sql(sql, params)
        if sql.upper().startswith("INSERT INTO") and "RETURNING" not in sql.upper():
            converted_sql = converted_sql.rstrip().rstrip(";") + " RETURNING id"
            result = self.session.execute(text(converted_sql), bound)
            return DBResult(lastrowid=result.scalar_one())
        result = self.session.execute(text(converted_sql), bound)
        try:
            rows = [dict(row) for row in result.mappings().all()]
        except Exception:
            rows = []
        return DBResult(rows=rows)

    def executemany(self, query: str, param_sets: list[tuple[Any, ...]]) -> None:
        for params in param_sets:
            self.execute(query, params)


def connect_db() -> DatabaseSession:
    return DatabaseSession()


def fetch_one(connection: DatabaseSession, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    return connection.execute(query, params).fetchone()


def fetch_all(connection: DatabaseSession, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return connection.execute(query, params).fetchall()


def ensure_database() -> None:
    import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def database_backend_label() -> str:
    if DATABASE_URL.startswith("postgresql"):
        return "PostgreSQL"
    if DATABASE_URL.startswith("mysql"):
        return "MySQL"
    return "SQLAlchemy"
