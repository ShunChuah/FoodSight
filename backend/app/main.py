import logging
import threading

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .database import Base, auth_engine, engine
from . import config
from .auth.routes import router as auth_router
from .routes.chat import router as chat_router
from .routes.preferences import router as preferences_router
from .services.shared.neo4j import warm_up


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("foodsight")

Base.metadata.create_all(bind=engine)

app = FastAPI(title="FoodSight API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys([
        *config.CORS_ORIGINS,
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ])),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(preferences_router)

router = APIRouter(prefix="/api/v1")


@router.get("/health")
async def health():
    try:
        async with auth_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        logger.exception("Database health check failed")
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "unreachable"},
        )
    return {"status": "ok", "database": "ok"}


router.include_router(auth_router)
app.include_router(router)

threading.Thread(target=warm_up, daemon=True).start()


@app.get("/")
def health_check():
    return {"status": "ok", "service": "foodsight-api"}
