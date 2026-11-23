import app.core.database  # noqa: F401  (WDAC MetaPathFinder guard)
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
import app.models  # noqa: F401
from app.core.database import Base, engine
Base.metadata.create_all(bind=engine)
from sqlalchemy.orm import Session
_db = Session(bind=engine)
try:
    from app.core.seed import seed_demo_data
    seed_demo_data(_db)
    _db.commit()
finally:
    _db.close()
from app.api.v1 import router as v1_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    from sqlalchemy.orm import Session
    db = Session(bind=engine)
    try:
        from app.core.seed import seed_demo_data
        seed_demo_data(db)
        db.commit()
    finally:
        db.close()
    yield

app = FastAPI(title=settings.PROJECT_NAME, version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(v1_router, prefix="/api/v1")

@app.get("/")
def read_root():
    return {"project": settings.PROJECT_NAME, "status": "online", "docs_url": "/docs"}

@app.get("/health")
def health():
    return {"status": "healthy", "service": "muletrace-backend", "version": "0.1.0"}

