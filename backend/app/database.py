from sqlalchemy import create_engine
from backend.app.db.models import Base
from sqlalchemy.orm import sessionmaker



DATABASE_URL = "postgresql://admin:admin123@localhost:5432/model_platform"

engine = create_engine(DATABASE_URL)
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)