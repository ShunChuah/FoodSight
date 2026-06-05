# FastAPI entry point: creates tables, enables frontend access, and registers API routes.
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routes.chat import router as chat_router


# Creates the database tables from SQLAlchemy models when the API starts.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="FoodSight API")

# Allows the Vite/React frontend to call this backend during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)


@app.get("/")
def health_check():
    # Simple endpoint to confirm the backend is running.
    return {"status": "ok", "service": "foodsight-api"}
