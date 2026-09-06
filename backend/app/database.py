from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:///./app.db"
)

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def run_migrations():
    """Run Alembic migrations on startup."""
    try:
        from alembic.config import Config
        from alembic import command
        import os
        alembic_cfg = Config("/app/backend/alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
        command.upgrade(alembic_cfg, "head")
        print("[db] migrations applied successfully", flush=True)
    except Exception as e:
        print(f"[db] migration warning: {e}", flush=True)

# Run migrations and create tables
from backend.app.db.models import Base
if DATABASE_URL.startswith("postgresql"):
    run_migrations()
    # Ensure default admin account exists
    try:
        from backend.app.services.auth import ensure_admin_exists
        _db = SessionLocal()
        ensure_admin_exists(_db)
        _db.close()
    except Exception as e:
        print(f"[auth] admin check warning: {e}", flush=True)
else:
    Base.metadata.create_all(bind=engine)
