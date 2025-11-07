# app/services.py
import asyncio
from typing import Dict, Set, List, Optional
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.database.models import (
    UserModel,
    OneToOneMessageModel,
    GroupModel,
    GroupMembershipModel,
    GroupMessageModel,
)
from app.core.security import SecurityService
from app.schemas.common import UserCreate  # Pydantic schemas


__all__ = ["UserService", "ChatService", "ConnectionManager", "manager"]


# ======================================================
#                      USER SERVICE (Updated)
# ======================================================
class UserService:
    """Handles all user database and authentication logic."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_by_username(self, username: str) -> Optional[UserModel]:
        """Retrieve a user by username (case-insensitive)."""
        stmt = select(UserModel).where(UserModel.username.ilike(username))
        result = await self.db.execute(stmt)
        user = result.scalars().first()
        print(f"[DEBUG] get_user_by_username('{username}') -> {user}")
        return user

    async def get_user_by_id(self, user_id: int) -> Optional[UserModel]:
        """Retrieve a user by ID."""
        stmt = select(UserModel).where(UserModel.id == user_id)
        result = await self.db.execute(stmt)
        user = result.scalars().first()
        print(f"[DEBUG] get_user_by_id({user_id}) -> {user}")
        return user

    # NEW METHOD 1: Retrieve user by email for forgot password
    async def get_user_by_email(self, email: str) -> Optional[UserModel]:
        """Retrieve a user by email."""
        # NOTE: Assumes UserModel has an 'email' field.
        stmt = select(UserModel).where(UserModel.email == email)
        result = await self.db.execute(stmt)
        user = result.scalars().first()
        print(f"[DEBUG] get_user_by_email('{email}') -> {user}")
        return user

    async def create_user(self, user: UserCreate) -> UserModel:
        """Create a new user with a hashed password and proper error handling."""
        try:
            existing_user = await self.get_user_by_username(user.username)
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username already registered",
                )

            # Prevent duplicate email registration (assumes schema includes email)
            if getattr(user, "email", None):
                existing_email_user = await self.get_user_by_email(user.email)
                if existing_email_user:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Email already registered",
                    )

            hashed_password = SecurityService.hash_password(user.password)

            # Create DB model instance
            db_user = UserModel(
                username=user.username,
                email=getattr(user, "email", None),
                hashed_password=hashed_password,
            )

            self.db.add(db_user)
            await self.db.commit()
            await self.db.refresh(db_user)
            print(f"[DEBUG] Created new user: {db_user.username} with email: {db_user.email}")
            return db_user

        except HTTPException:
            raise
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to register user: {str(e)}",
            )

    async def authenticate_user(self, username: str, password: str) -> UserModel:
        """Authenticate a user and verify password."""
        user = await self.get_user_by_username(username)
        if not user or not SecurityService.verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
            )
        return user

    # NEW METHOD 2: Update user password for reset
    async def update_password(self, user_id: int, hashed_password: str) -> None:
        """Update a user's hashed password directly in the database."""
        stmt = (
            update(UserModel)
            .where(UserModel.id == user_id)
            .values(hashed_password=hashed_password)
        )
        await self.db.execute(stmt)
        await self.db.commit()
        print(f"[DEBUG] User {user_id} password updated.")


# ======================================================
#                 CHAT SERVICE (N+1 Fix Applied)
# ======================================================
class ChatService:
    """Handles chat message persistence and group management."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def save_one_to_one_message(
        self, sender_id: int, receiver_id: int, content: str
    ) -> OneToOneMessageModel:
        """Save a one-to-one message."""
        db_msg = OneToOneMessageModel(
            sender_id=sender_id,
            receiver_id=receiver_id,
            content=content,
        )
        self.db.add(db_msg)
        await self.db.commit()
        await self.db.refresh(db_msg)
        return db_msg

    async def get_one_to_one_history(
        self, user_a_id: int, user_b_id: int, limit: int = 50
    ) -> List[OneToOneMessageModel]:
        """
        Retrieve conversation history between two users, eager loading the sender.
        (N+1 Fix is included here)
        """
        stmt = (
            select(OneToOneMessageModel)
            .where(
                ((OneToOneMessageModel.sender_id == user_a_id) & (OneToOneMessageModel.receiver_id == user_b_id))
                | ((OneToOneMessageModel.sender_id == user_b_id) & (OneToOneMessageModel.receiver_id == user_a_id))
            )
            .order_by(OneToOneMessageModel.timestamp.desc())
            .limit(limit)
            .options(selectinload(OneToOneMessageModel.sender))
        )
        result = await self.db.execute(stmt)
        return result.scalars().unique().all()[::-1]

    async def create_group(self, name: str, member_ids: List[int]) -> GroupModel:
        """Create a new group and add initial members."""
        db_group = GroupModel(name=name)
        self.db.add(db_group)
        await self.db.flush()

        memberships = [
            GroupMembershipModel(group_id=db_group.id, user_id=user_id)
            for user_id in member_ids
        ]
        self.db.add_all(memberships)
        await self.db.commit()
        await self.db.refresh(db_group)
        return db_group

    async def get_group_by_name(self, name: str) -> Optional[GroupModel]:
        """Retrieve a group by name."""
        stmt = select(GroupModel).where(GroupModel.name == name)
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def is_member(self, user_id: int, group_id: int) -> bool:
        """Check if a user is a member of a group."""
        stmt = select(GroupMembershipModel).where(
            (GroupMembershipModel.user_id == user_id)
            & (GroupMembershipModel.group_id == group_id)
        )
        result = await self.db.execute(stmt)
        return result.scalars().first() is not None

    async def save_group_message(
        self, group_id: int, sender_id: int, content: str
    ) -> GroupMessageModel:
        """Save a group message if sender is a valid member."""
        if not await self.is_member(sender_id, group_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of this group.",
            )

        db_msg = GroupMessageModel(
            group_id=group_id,
            sender_id=sender_id,
            content=content,
        )
        self.db.add(db_msg)
        await self.db.commit()
        await self.db.refresh(db_msg)
        return db_msg


# ======================================================
#      CONNECTION MANAGER (WebSocket)
# ======================================================
class ConnectionManager:
    """Manages active WebSocket connections and group memberships."""

    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}
        self.group_members: Dict[int, Set[int]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        print(f"[DEBUG] User {user_id} connected via WebSocket")

    def disconnect(self, user_id: int):
        self.active_connections.pop(user_id, None)
        for group_id in list(self.group_members.keys()):
            self.group_members[group_id].discard(user_id)
            if not self.group_members[group_id]:
                self.group_members.pop(group_id)
        print(f"[DEBUG] User {user_id} disconnected")

    async def safe_send(self, user_id: int, message: str):
        try:
            if user_id in self.active_connections:
                await self.active_connections[user_id].send_text(message)
        except Exception:
            self.disconnect(user_id)

    async def send_personal_message(self, message: str, user_id: int):
        await self.safe_send(user_id, message)

    async def broadcast_group_message(
        self, message: str, group_id: int, exclude_user_id: Optional[int] = None
    ):
        if group_id not in self.group_members:
            return
        tasks = []
        for uid in self.group_members[group_id]:
            if uid != exclude_user_id and uid in self.active_connections:
                tasks.append(self.safe_send(uid, message))
        await asyncio.gather(*tasks, return_exceptions=True)

    def join_group(self, user_id: int, group_id: int):
        if group_id not in self.group_members:
            self.group_members[group_id] = set()
        self.group_members[group_id].add(user_id)


# --- Global WebSocket connection manager ---
manager: ConnectionManager = ConnectionManager()