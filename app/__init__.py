import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.database.models import Base

# =====================================================
# Database Configuration
# =====================================================
SQLALCHEMY_DATABASE_URL = os.getenv("DB_URL", "sqlite+aiosqlite:///./chat_db.sqlite")

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    echo=False,
)

AsyncSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=AsyncSession,
)

# =====================================================
# Dependency for Database Session
# =====================================================
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# =====================================================
# FastAPI App Initialization
# =====================================================
app = FastAPI(
    title="FastAPI Realtime Chat Server",
    description="A class-based, JWT-authenticated, and WebSocket-enabled chat API.",
    version="1.0.0",
)

# =====================================================
# CORS Middleware (for Swagger & Frontend Access)
# =====================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all for testing; restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================
# Serve Static Files
# =====================================================
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# =====================================================
# Root Endpoint (for sanity check)
# =====================================================
@app.get("/")
async def root():
    return {"message": "🚀 FastAPI Realtime Chat Server is running!"}

# =====================================================
# Include Routers
# =====================================================
from app import routers
app.include_router(routers.router)

# =====================================================
# Database Initialization on Startup
# =====================================================
@app.on_event("startup")
async def startup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database initialized.")
