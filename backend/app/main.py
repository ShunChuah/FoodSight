import asyncio
import logging
import threading
from contextlib import asynccontextmanager, suppress

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import config
from app.admin.routes import router as admin_router
from app.auth.cleanup import run_token_cleanup
from app.auth.routes import router as auth_router
from app.business.admin_routes import router as business_admin_router
from app.business.routes import router as business_router
from app.database import auth_engine
from app.errors import handle_unexpected_errors
from app.routes.chat import router as chat_router
from app.routes.narration import router as narration_router
from app.routes.preferences import router as preferences_router
from app.services.shared.neo4j import warm_up

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("foodsight")


@asynccontextmanager
async def lifespan(app):
    # Runs beside the app, so a slow database never delays startup.
    cleanup = asyncio.create_task(run_token_cleanup())
    yield
    cleanup.cancel()
    with suppress(asyncio.CancelledError):
        await cleanup


app = FastAPI(title="FoodSight API", lifespan=lifespan)
handle_unexpected_errors(app)

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
router.include_router(chat_router)
router.include_router(narration_router)
router.include_router(preferences_router)
router.include_router(admin_router)
router.include_router(business_router)
router.include_router(business_admin_router)
app.include_router(router)

threading.Thread(target=warm_up, daemon=True).start()


@app.get("/")
def health_check():
    return {"status": "ok", "service": "foodsight-api"}
