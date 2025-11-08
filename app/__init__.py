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
# Ensure you are loading .env variables correctly in main.py or top-level file
SQLALCHEMY_DATABASE_URL = os.getenv("DB_URL", "sqlite+aiosqlite:///./chat_db.sqlite")

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    echo=True,
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
# 🛑 FIX APPLIED HERE: Use an absolute path to ensure correct loading 
# regardless of where uvicorn is launched from.
# os.path.dirname(__file__) gets the directory of this file (app/)
# We join 'static' to it, resulting in 'app/static' as an absolute path.
# =====================================================
STATIC_FILES_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_FILES_DIR), name="static")


# =====================================================
# Root Endpoint (for sanity check)
# =====================================================
@app.get("/")
async def root():
    return {"message": "🚀 FastAPI Realtime Chat Server is running!"}

# =====================================================
# Include Routers 🏗️ UPDATED FOR MODULARIZATION
# =====================================================

from app.auth.router import router as auth_router
from app.chat.router import router as chat_router

app.include_router(auth_router)  # Routes are now accessible via /auth/...
app.include_router(chat_router) # Routes are accessible directly (e.g., /groups) or via their prefixes (/ws/chat)

# =====================================================
# Database Initialization on Startup
# =====================================================
@app.on_event("startup")
async def startup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database initialized.")