import asyncio
import logging
from typing import Dict, Set, List, Optional
from datetime import datetime

from fastapi import WebSocket, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
# IMPORTANT: Ensure 'delete' and 'update' are imported here for group management
from sqlalchemy import select, update, delete 
from sqlalchemy.orm import selectinload

from app.database.models import (
    UserModel,
    OneToOneMessageModel,
    GroupModel,
    GroupMembershipModel, # Used for group members
    GroupMessageModel,
)
from app.core.security import SecurityService
from app.schemas.common import UserCreate


__all__ = ["UserService", "ChatService", "ConnectionManager", "manager"]

# module logger
logger = logging.getLogger(__name__)


# ======================================================
#            USER SERVICE
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
        logger.debug("get_user_by_username('%s') -> %s", username, user)
        return user

    async def get_user_by_id(self, user_id: int) -> Optional[UserModel]:
        """Retrieve a user by ID."""
        stmt = select(UserModel).where(UserModel.id == user_id)
        result = await self.db.execute(stmt)
        user = result.scalars().first()
        logger.debug("get_user_by_id(%s) -> %s", user_id, user)
        return user

    async def get_user_by_email(self, email: str) -> Optional[UserModel]:
        """Retrieve a user by email (for password reset)."""
        stmt = select(UserModel).where(UserModel.email == email)
        result = await self.db.execute(stmt)
        user = result.scalars().first()
        logger.debug("get_user_by_email('%s') -> %s", email, user)
        return user

    async def create_user(self, user: UserCreate) -> UserModel:
        """Create a new user with a hashed password."""
        try:
            existing_user = await self.get_user_by_username(user.username)
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username already registered",
                )

            if getattr(user, "email", None):
                existing_email_user = await self.get_user_by_email(user.email)
                if existing_email_user:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Email already registered",
                    )

            hashed_password = SecurityService.hash_password(user.password)
            db_user = UserModel(
                username=user.username,
                email=getattr(user, "email", None),
                hashed_password=hashed_password,
            )

            self.db.add(db_user)
            await self.db.commit() 
            await self.db.refresh(db_user)
            logger.info("Created new user: %s (%s)", db_user.username, db_user.email)
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

    async def update_password(self, user_id: int, hashed_password: str) -> None:
        """Update a user's hashed password directly in the database."""
        stmt = (
            update(UserModel)
            .where(UserModel.id == user_id)
            .values(hashed_password=hashed_password)
        )
        await self.db.execute(stmt)
        await self.db.commit()


# ======================================================
#            CHAT SERVICE (FIXED/UPDATED)
# ======================================================
class ChatService:
    """Handles chat message persistence and group management."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # --- Messaging Methods ---

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
        await self.db.flush()
        return db_msg

    async def get_one_to_one_history(
        self, user_a_id: int, user_b_id: int, limit: int = 50
    ) -> List[OneToOneMessageModel]:
        """Retrieve conversation history between two users."""
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
        await self.db.flush()
        return db_msg

    async def get_group_history(
        self, group_id: int, limit: int = 100
    ) -> List[GroupMessageModel]:
        """Retrieve group chat history with sender preloaded."""
        stmt = (
            select(GroupMessageModel)
            .where(GroupMessageModel.group_id == group_id)
            .order_by(GroupMessageModel.timestamp.desc())
            .limit(limit)
            .options(selectinload(GroupMessageModel.sender))
        )
        result = await self.db.execute(stmt)
        return result.scalars().unique().all()[::-1]


    # --- Group Management Methods ---

    # Method to retrieve group by ID (needed by router.py)
    async def get_group_by_id(self, group_id: int) -> Optional[GroupModel]:
        """Retrieve a group by ID."""
        stmt = select(GroupModel).where(GroupModel.id == group_id)
        result = await self.db.execute(stmt)
        return result.scalars().first()

    # Added 'creator_id: int' to accept the owner ID
    async def create_group(self, name: str, member_ids: List[int], creator_id: int) -> GroupModel:
        """Create a new group and add initial members."""
        # Initialize GroupModel with creator_id
        db_group = GroupModel(name=name, creator_id=creator_id)
        self.db.add(db_group)
        await self.db.flush() # Flush needed to get db_group.id

        memberships = [
            GroupMembershipModel(group_id=db_group.id, user_id=user_id)
            for user_id in member_ids
        ]
        self.db.add_all(memberships)
        # Note: router.py handles the commit/refresh outside of this method now
        return db_group
    
    # Method to get all groups a user belongs to (needed by ChatConsumer.connect)
    async def get_user_groups(self, user_id: int) -> List[GroupModel]:
        """Retrieve all groups a specific user is a member of."""
        stmt = (
            select(GroupModel)
            .join(GroupMembershipModel)
            .where(GroupMembershipModel.user_id == user_id)
        )
        result = await self.db.execute(stmt)
        return result.scalars().unique().all()


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
    
    # Add members to a group (used by POST /groups/{group_name}/members)
    async def add_members(self, group_id: int, user_ids: List[int]):
        """Adds multiple users to a group, skipping existing members."""
        # 1. Check current members to avoid duplicates
        current_members_stmt = select(GroupMembershipModel.user_id).where(
            GroupMembershipModel.group_id == group_id
        )
        result = await self.db.execute(current_members_stmt)
        current_member_ids = set(result.scalars().all())

        new_memberships = [
            GroupMembershipModel(group_id=group_id, user_id=user_id)
            for user_id in user_ids
            if user_id not in current_member_ids
        ]
        
        if new_memberships:
            self.db.add_all(new_memberships)
            await self.db.flush()
            logger.info("Added %d members to group %s", len(new_memberships), group_id)
        return

    # Remove the current user from a group (used by DELETE /groups/{group_name}/leave)
    async def remove_member(self, group_id: int, user_id: int):
        """Removes a single user from a group."""
        stmt = delete(GroupMembershipModel).where(
            (GroupMembershipModel.group_id == group_id) 
            & (GroupMembershipModel.user_id == user_id)
        )
        result = await self.db.execute(stmt)
        if result.rowcount > 0:
            logger.info("User %s left group %s", user_id, group_id)
        return

    # Remove specific members from a group (used by DELETE /groups/{group_name}/members)
    async def remove_members(self, group_id: int, user_ids: List[int]):
        """Removes multiple specified users from a group."""
        stmt = delete(GroupMembershipModel).where(
            (GroupMembershipModel.group_id == group_id)
            & (GroupMembershipModel.user_id.in_(user_ids))
        )
        result = await self.db.execute(stmt)
        logger.info("Removed %d members from group %s", result.rowcount, group_id)
        return

    
    # --- NEW: Owner Actions ---

    async def transfer_ownership(self, group_id: int, new_owner_id: int):
        """Transfers group ownership by updating the creator_id."""
        
        stmt = (
            update(GroupModel)
            .where(GroupModel.id == group_id)
            .values(creator_id=new_owner_id)
        )
        
        result = await self.db.execute(stmt)
        
        if result.rowcount == 0:
            # Note: This usually indicates an internal logic error if group was found by the router,
            # but raising 404 is safe.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, 
                                detail="Group not found for ownership transfer.")
            
        await self.db.flush() # Stage the change
        return


    async def delete_group(self, group_id: int):
        """Deletes a group and all associated messages and memberships."""
        
        # 1. Delete all group messages first
        await self.db.execute(
            delete(GroupMessageModel).where(GroupMessageModel.group_id == group_id)
        )
        
        # 2. Delete all group memberships
        await self.db.execute(
            delete(GroupMembershipModel).where(GroupMembershipModel.group_id == group_id)
        )
        
        # 3. Delete the Group itself
        result = await self.db.execute(
            delete(GroupModel).where(GroupModel.id == group_id)
        )
        
        if result.rowcount == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, 
                                detail="Group not found for deletion.")
            
        await self.db.flush() # Stage the deletion changes
        return


# ======================================================
#         CONNECTION MANAGER (WebSocket)
# ======================================================
class ConnectionManager:
    """Manages active WebSocket connections and group memberships."""

    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}
        self.group_members: Dict[int, Set[int]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        """Accept and register a WebSocket connection."""
        await websocket.accept()
        self.active_connections[user_id] = websocket
        logger.debug("User %s connected via WebSocket", user_id)

    def disconnect(self, user_id: int):
        """Remove user from active connections and group memberships."""
        self.active_connections.pop(user_id, None)
        for group_id in list(self.group_members.keys()):
            self.group_members[group_id].discard(user_id)
            if not self.group_members[group_id]:
                self.group_members.pop(group_id)
        logger.debug("User %s disconnected", user_id)

    async def safe_send(self, user_id: int, message: str):
        """Safely send a message to a user, handling disconnections."""
        try:
            if user_id in self.active_connections:
                await self.active_connections[user_id].send_text(message)
        except Exception:
            self.disconnect(user_id)

    async def send_personal_message(self, message: str, user_id: int):
        """Send a direct message to a specific user."""
        await self.safe_send(user_id, message)

    async def broadcast_group_message(
        self, message: str, group_id: int, exclude_user_id: Optional[int] = None
    ):
        """Broadcast a message to all members of a group."""
        if group_id not in self.group_members:
            return
        tasks = [
            self.safe_send(uid, message)
            for uid in self.group_members[group_id]
            if uid != exclude_user_id and uid in self.active_connections
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    def join_group(self, user_id: int, group_id: int):
        """Add a user to a group."""
        if group_id not in self.group_members:
            self.group_members[group_id] = set()
        self.group_members[group_id].add(user_id)

    # 🚀 NEW: Typing Status Broadcasting
    async def broadcast_typing_status(
        self, 
        message: str, 
        group_id: Optional[int] = None, 
        target_user_id: Optional[int] = None,
        exclude_user_id: Optional[int] = None
    ):
        """
        Broadcasts typing status to group members or a single target user.
        """
        if group_id is not None:
            # Broadcast to all members in a group (excluding self)
            if group_id not in self.group_members:
                return
            tasks = [
                self.safe_send(uid, message)
                for uid in self.group_members[group_id]
                if uid != exclude_user_id and uid in self.active_connections
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
            
        elif target_user_id is not None and target_user_id in self.active_connections:
            # Send to a single user in a one-to-one chat
            if target_user_id != exclude_user_id:
                await self.safe_send(target_user_id, message)


# --- Global WebSocket connection manager instance ---
manager: ConnectionManager = ConnectionManager()