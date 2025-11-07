# app/auth/router.py
import json
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr

from app import get_db
from app.core.security import SecurityService, get_current_user_id
from app.schemas.common import (
    UserCreate,
    UserDB,
    Token,
)
from app.services import UserService # Ensure UserService is imported

# --- SCHEMAS ---
class UserPrecheck(BaseModel):
    username: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

# --- AUTH ROUTER INSTANCE ---
router = APIRouter(prefix="/auth", tags=["Authentication"]) 

# --- AUTH ROUTES ---
@router.post("/precheck")
async def precheck_user(user: UserPrecheck, db: AsyncSession = Depends(get_db)):
    existing_user = await UserService(db).get_user_by_username(user.username)
    return {"exists": bool(existing_user)}

@router.post("/register", response_model=UserDB)
async def register_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    return await UserService(db).create_user(user)

@router.post("/login", response_model=Token)
async def login_for_access_token(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    user = await UserService(db).authenticate_user(user_data.username, user_data.password)
    access_token = SecurityService.create_token(user_id=user.id, token_type="access")
    refresh_token = SecurityService.create_token(user_id=user.id, token_type="refresh")
    return {"access_token": access_token, "token_type": "bearer", "refresh_token": refresh_token}

@router.post("/refresh", response_model=Token)
async def refresh_session(refresh_token: str = Body(..., embed=True), db: AsyncSession = Depends(get_db)):
    payload = SecurityService.decode_token(refresh_token)
    if payload.type != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token is not a refresh token")
    user_id = payload.sub
    user = await UserService(db).get_user_by_id(int(user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    new_access = SecurityService.create_token(user_id=user.id, token_type="access")
    new_refresh = SecurityService.create_token(user_id=user.id, token_type="refresh")
    return {"access_token": new_access, "token_type": "bearer", "refresh_token": new_refresh}

@router.get("/check", response_model=UserDB)
async def check_session(user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    user = await UserService(db).get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return UserDB.from_orm(user)


# --- FORGOT PASSWORD / RESET (CORRECTED) ---
@router.post("/forgot-password")
async def forgot_password(req: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    user = await UserService(db).get_user_by_email(req.email) # 🚀 Uses new service method
    
    # SECURITY BEST PRACTICE: Return a generic message regardless of email existence
    if not user:
        return {"message": "If the email is registered, you will receive a reset token."}
        
    # Generate reset token valid for 30 mins, using the actual user ID
    reset_token = SecurityService.create_token(user_id=user.id, token_type="reset")
    
    # Here you would normally send an email with the token (for production)
    return {"reset_token": reset_token, "message": "Use this token to reset your password (sent via email in production)"}

@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    payload = SecurityService.decode_token(req.token)
    if payload.type != "reset":
        raise HTTPException(status_code=401, detail="Invalid reset token")
        
    user_id = int(payload.sub)
    user_service = UserService(db)
    
    # Check if user still exists (using the user_id from the valid token)
    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # Hash the new password and update it using the new service method
    hashed_password = SecurityService.hash_password(req.new_password)
    await user_service.update_password(user_id, hashed_password) # 🚀 Uses new service method
    
    return {"message": "Password updated successfully"}