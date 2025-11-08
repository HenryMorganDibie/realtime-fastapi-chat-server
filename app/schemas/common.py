from pydantic import BaseModel, Field, validator, EmailStr
from typing import Optional, List
from datetime import datetime

# --- Token Schemas ---

class Token(BaseModel):
    """Schema for JWT tokens."""
    access_token: str
    token_type: str
    refresh_token: Optional[str] = None

class TokenPayload(BaseModel):
    """Schema for JWT payload."""
    sub: Optional[int] = None  # User ID
    exp: int
    type: str  # Token type (access or refresh)

# --- User Schemas ---

MAX_PASSWORD_LENGTH = 72  # bcrypt max bytes

class UserBase(BaseModel):
    """Base schema for user data."""
    username: str

class UserCreate(UserBase):
    """Schema for user registration / login."""
    password: str = Field(..., min_length=6, max_length=MAX_PASSWORD_LENGTH)
    email: EmailStr

    @validator("password")
    def password_length(cls, v):
        if len(v) > MAX_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at most {MAX_PASSWORD_LENGTH} characters")
        return v

class UserDB(UserBase):
    """Schema for user data retrieved from DB."""
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        orm_mode = True

# --- Message Schemas ---

class MessageBase(BaseModel):
    """Base schema for messages."""
    content: str

class MessageOneToOneCreate(MessageBase):
    """Schema for creating a one-to-one message."""
    receiver_username: str

class MessageResponse(MessageBase):
    """Schema for message response."""
    id: int
    sender_username: str
    timestamp: datetime

    class Config:
        # Note: In Pydantic V2, 'orm_mode' is deprecated, use 'from_attributes = True'
        orm_mode = True

# --- Group Schemas ---

# 🟢 NEW: Schema to handle list of usernames in request body (for adding/removing members)
class UsernamesList(BaseModel):
    """Schema for passing a list of usernames in a request body."""
    member_usernames: List[str]

class GroupCreate(BaseModel):
    """Schema for creating a group."""
    name: str
    member_usernames: List[str] = Field(default_factory=list)

class GroupResponse(BaseModel):
    """Schema for group details."""
    id: int
    name: str
    member_count: int