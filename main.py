import uvicorn
from app import app

if __name__ == "__main__":
    # Runs the main application defined in app/__init__.py
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
