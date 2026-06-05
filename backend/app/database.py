# Database setup: connects SQLAlchemy to PostgreSQL and provides one session per request.
import os
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker


load_dotenv()

# PostgreSQL connection string loaded from .env, with a local fallback.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/foodsight",
)

# Accept common PostgreSQL URL formats and convert them for psycopg2.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

# engine manages DB connections; SessionLocal creates request-level sessions.
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    # FastAPI injects this session into routes, then closes it after the request.
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
