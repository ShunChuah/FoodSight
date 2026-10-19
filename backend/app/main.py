import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routes.chat import router as chat_router
from .services.shared.neo4j import warm_up


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

# Warm Neo4j up in the background so the first question does not pay for a cold database.
threading.Thread(target=warm_up, daemon=True).start()


@app.get("/")
def health_check():
    return {"status": "ok", "service": "foodsight-api"}
