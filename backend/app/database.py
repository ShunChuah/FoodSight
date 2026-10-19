import os
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import URL, create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, declarative_base, sessionmaker


load_dotenv()

from app import config  # noqa: E402  (reads the settings loaded above)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/foodsight",
)

# Accept common PostgreSQL URL formats and convert them for psycopg2.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Login tables (async, from main). Separate names so they do not clash with the chat engine and Base above.
auth_engine = create_async_engine(
    URL.create(
        "postgresql+asyncpg",
        username=config.DB_USER,
        password=config.DB_PASSWORD,
        host=config.DB_HOST,
        port=config.DB_PORT,
        database=config.DB_NAME,
    )
)
async_session_maker = async_sessionmaker(auth_engine, expire_on_commit=False)


class AuthBase(DeclarativeBase):
    pass


async def get_async_session():
    async with async_session_maker() as session:
        yield session
