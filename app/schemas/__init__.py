# app/schemas/__init__.py
from datetime import datetime
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


# ===== USER SCHEMAS =====
class UserBase(BaseModel):
    username: str


class UserCreate(UserBase):
    password: str
    email: EmailStr


class UserOut(UserBase):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        orm_mode = True


# ===== MESSAGE SCHEMAS =====
class MessageBase(BaseModel):
    content: str


class MessageCreate(MessageBase):
    receiver_id: int


class MessageOut(MessageBase):
    id: int
    sender_id: int
    receiver_id: int
    timestamp: datetime
    is_read: bool

    class Config:
        orm_mode = True
