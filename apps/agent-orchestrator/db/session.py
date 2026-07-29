"""
db/session.py — Database engine creation and FastAPI dependency.

Handles:
  - SQLite (local dev)  vs  PostgreSQL (production)
  - Tenant schema isolation (schema-per-tenant + RLS SET LOCAL)
  - Default compliance rule seeding on first use
"""
import os
import uuid
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from db.models import Base

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./orchestrator.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Auto-create tables on import
Base.metadata.create_all(bind=engine)

_DEFAULT_RULES = [
    # Structural SQL injection — regex patterns only
    (r"(?i)\bSELECT\b.+\bFROM\b",           "SOC2-CC-6.1"),
    (r"(?i)\bDROP\s+TABLE\b",               "SOC2-CC-6.1"),
    (r"(?i)\bINSERT\s+INTO\b",              "SOC2-CC-6.1"),
    (r"(?i)\bDELETE\s+FROM\b",              "SOC2-CC-6.1"),
    (r"(?i)\bUNION\s+SELECT\b",             "SOC2-CC-6.1"),
    # Command injection
    (r";\s*rm\s+-rf",                        "GDPR-Art-32"),
    (r"&&\s*rm\s+-rf",                       "GDPR-Art-32"),
    (r"\|\s*bash",                           "GDPR-Art-32"),
    (r"(?i)\bexec\s*\(",                     "GDPR-Art-32"),
    # Credential/PII exfiltration patterns in input
    (r"(?i)BEGIN\s+(RSA\s+)?PRIVATE\s+KEY", "GDPR-Art-32"),
]


def _seed_default_rules(db: Session) -> None:
    """Insert default compliance rules if the table is empty."""
    try:
        count = db.execute(text("SELECT COUNT(*) FROM compliance_rules")).scalar()
        if count == 0:
            for pattern, ctrl_id in _DEFAULT_RULES:
                db.execute(
                    text("""
                        INSERT INTO compliance_rules (rule_id, pattern, is_active, control_id)
                        VALUES (:id, :pattern, TRUE, :ctrl)
                    """),
                    {"id": str(uuid.uuid4()), "pattern": pattern, "ctrl": ctrl_id},
                )
            db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[DB] Seeding default rules failed: {exc}")


_initialized_schemas = set()

def _setup_postgres_tenant_schema(db: Session, tenant_id: str) -> None:
    """Create per-tenant schema and tables in PostgreSQL."""
    schema = f"tenant_{tenant_id.replace('-', '_')}"
    
    if schema not in _initialized_schemas:
        try:
            db.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema};"))
            db.execute(text(f"SET search_path TO {schema}, public;"))
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_threads (
                    thread_id   VARCHAR(255) PRIMARY KEY,
                    tenant_id   VARCHAR(64)  NOT NULL,
                    agent_type  VARCHAR(100) NOT NULL,
                    created_at  TIMESTAMP WITHOUT TIME ZONE
                                DEFAULT timezone('utc'::text, now())
                );
            """))
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_checkpoints (
                    id             SERIAL PRIMARY KEY,
                    thread_id      VARCHAR(255)
                                   REFERENCES agent_threads(thread_id)
                                   ON DELETE CASCADE,
                    checkpoint_id  VARCHAR(255) NOT NULL,
                    timestamp      TIMESTAMP WITHOUT TIME ZONE
                                   DEFAULT timezone('utc'::text, now()),
                    step           VARCHAR(100) NOT NULL,
                    state_data     JSON NOT NULL
                );
            """))
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS compliance_rules (
                    rule_id    VARCHAR(36)  PRIMARY KEY,
                    pattern    VARCHAR(255) NOT NULL,
                    is_active  BOOLEAN      DEFAULT TRUE,
                    control_id VARCHAR(100) NOT NULL,
                    created_at TIMESTAMP WITHOUT TIME ZONE
                               DEFAULT timezone('utc'::text, now())
                );
            """))
            db.commit()
            _initialized_schemas.add(schema)
        except Exception as exc:
            db.rollback()
            print(f"[DB] Tenant schema setup failed or raced: {exc}")
            _initialized_schemas.add(schema) # Assume it was created by another worker
    
    # Always ensure search_path is set for this session's connection
    db.execute(text(f"SET search_path TO {schema}, public;"))


def get_db(principal: dict) -> Generator[Session, None, None]:
    """
    FastAPI dependency — yields a tenant-scoped SQLAlchemy session.
    NOTE: principal is injected by get_principal() in auth/principal.py.
          Call as:  db: Session = Depends(make_db_dep(principal))
    """
    db = SessionLocal()
    tenant_id = principal.get("tenant_id", "default")

    if not DATABASE_URL.startswith("sqlite") and tenant_id:
        _setup_postgres_tenant_schema(db, tenant_id)
        try:
            db.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": tenant_id},
            )
        except Exception:
            pass

    _seed_default_rules(db)

    try:
        yield db
    finally:
        db.close()
