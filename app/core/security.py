import os
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from jose import jwt, JWTError
from dotenv import load_dotenv

from app.schemas.common import TokenPayload

# --- LOAD ENV VARIABLES ---
load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY", "dev-fallback-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))

# --- PASSWORD HASHING (Argon2) ---
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# --- OAUTH2 CONFIGURATION ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class SecurityService:
    """Handles password hashing, verification, and JWT encoding/decoding."""

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using Argon2."""
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a password against an Argon2 hash."""
        return pwd_context.verify(plain_password, hashed_password)

    @staticmethod
    def create_token(user_id: int, token_type: str = "access") -> str:
        """Create a JWT token (access or refresh)."""
        if token_type == "access":
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        elif token_type == "refresh":
            expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        else:
            raise ValueError("Invalid token type. Must be 'access' or 'refresh'.")

        to_encode = {
            "exp": expire,
            "sub": str(user_id),
            "type": token_type,
        }
        return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    @staticmethod
    def decode_token(token: str) -> TokenPayload:
        """Decode a JWT token and return a TokenPayload."""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return TokenPayload(**payload)
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )


# --- DEPENDENCY INJECTION ---
async def get_current_user_id(token: str = Depends(oauth2_scheme)) -> int:
    """
    FastAPI dependency to get the current authenticated user's ID from the access token.
    """
    payload = SecurityService.decode_token(token)
    sub = payload.sub
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload missing subject",
        )
    try:
        return int(sub)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid subject in token",
        )
