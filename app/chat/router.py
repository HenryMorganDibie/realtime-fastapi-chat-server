import json
import asyncio
from typing import List, Optional
from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    WebSocket,
    WebSocketDisconnect,
    Query, # <-- Used for history endpoint fix
    Path,
)
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError
from pydantic import BaseModel

# --- LOCAL IMPORTS ---
from app import get_db
from app.core.security import SecurityService, get_current_user_id
from app.schemas.common import GroupCreate, GroupResponse, MessageResponse, UsernamesList
from app.services import UserService, ChatService, manager
from app.database.models import GroupModel # Assuming this is available

# ============================================================
# NEW SCHEMA FOR OWNERSHIP TRANSFER
# ============================================================
class NewOwnerSchema(BaseModel):
    new_owner_username: str

# ============================================================
# CHAT ROUTER
# ============================================================
router = APIRouter(tags=["Chat & Messaging"])


# ============================================================
# GROUP MANAGEMENT ENDPOINTS
# ============================================================

@router.post("/groups", response_model=GroupResponse)
async def create_new_group(
    group: GroupCreate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new chat group and include the creator and initial members."""
    user_service = UserService(db)
    chat_service = ChatService(db)

    existing_group = await chat_service.get_group_by_name(group.name)
    if existing_group:
        raise HTTPException(status_code=400, detail="Group name already exists.")

    member_ids = [user_id]
    for username in group.member_usernames:
        member = await user_service.get_user_by_username(username)
        if not member:
            raise HTTPException(status_code=404, detail=f"User '{username}' not found.")
        if member.id not in member_ids:
            member_ids.append(member.id)

    new_group = await chat_service.create_group(group.name, member_ids, creator_id=user_id)
    
    # 🔥 COMMIT FIX retained: Explicitly commit the transaction to save the group
    await db.commit()
    await db.refresh(new_group)

    return GroupResponse(id=new_group.id, name=new_group.name, member_count=len(member_ids))


# 🚀 NEW ENDPOINT: TRANSFER OWNERSHIP
@router.patch("/groups/{group_name}/owner", status_code=200)
async def transfer_group_ownership(
    group_name: str = Path(..., description="Name of the group to transfer ownership for"),
    new_owner_data: NewOwnerSchema = ...,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Allows the current owner to transfer ownership to another member."""
    user_service = UserService(db)
    chat_service = ChatService(db)

    # 1. Find group by name
    group = await chat_service.get_group_by_name(group_name)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found.")

    # 2. Check if the user is the current owner
    if group.creator_id != user_id:
        raise HTTPException(status_code=403, detail="Only the current owner can transfer ownership.")

    # 3. Find the prospective new owner
    new_owner_user = await user_service.get_user_by_username(new_owner_data.new_owner_username)
    if not new_owner_user:
        raise HTTPException(status_code=404, detail=f"User '{new_owner_data.new_owner_username}' not found.")

    new_owner_id = new_owner_user.id
    
    # 4. Check if the new owner is currently a member
    if not await chat_service.is_member(new_owner_id, group.id):
        raise HTTPException(status_code=400, detail="New owner must be an existing member of the group.")
    
    if new_owner_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot transfer ownership to yourself.")

    # 5. Perform the transfer (CORRECTION applied here)
    try:
        # The service method only expects group_id and new_owner_id
        await chat_service.transfer_ownership(group.id, new_owner_id) 
        await db.commit()
        
        return {"message": f"Ownership successfully transferred to {new_owner_data.new_owner_username}."}
    except Exception as e:
        await db.rollback()
        # Ensure you handle specific exceptions in the service layer if necessary
        raise HTTPException(status_code=500, detail=f"Failed to transfer ownership: {str(e)}")


@router.post("/groups/{group_name}/members", status_code=200)
async def add_group_members(
    group_name: str = Path(..., description="Name of the group"),
    members_data: UsernamesList = ...,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Add specified members to a group (only owner)."""
    user_service = UserService(db)
    chat_service = ChatService(db)

    # 1. Find group by name
    group = await chat_service.get_group_by_name(group_name)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found.")

    if group.creator_id != user_id:
        raise HTTPException(status_code=403, detail="Only the owner can add members.")

    new_member_ids = []
    for username in members_data.member_usernames:
        member = await user_service.get_user_by_username(username)
        if not member:
            raise HTTPException(status_code=404, detail=f"User '{username}' not found.")
        new_member_ids.append(member.id)

    await chat_service.add_members(group.id, new_member_ids)
    await db.commit()
    return {"message": "Members successfully added."}


@router.delete("/groups/{group_name}/members", status_code=200)
async def remove_group_members(
    group_name: str = Path(..., description="Name of the group"),
    members_data: UsernamesList = ...,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Remove members from a group (only owner)."""
    user_service = UserService(db)
    chat_service = ChatService(db)

    # 1. Find group by name
    group = await chat_service.get_group_by_name(group_name)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found.")

    if group.creator_id != user_id:
        raise HTTPException(status_code=403, detail="Only the owner can remove members.")

    remove_member_ids = []
    for username in members_data.member_usernames:
        member = await user_service.get_user_by_username(username)
        if not member:
            raise HTTPException(status_code=404, detail=f"User '{username}' not found.")
        
        # 🔥 FIX: Improved error message for removing owner
        if member.id == group.creator_id:
            raise HTTPException(status_code=400, detail="Cannot remove the group owner. Transfer ownership or delete the group instead.")
            
        remove_member_ids.append(member.id)

    await chat_service.remove_members(group.id, remove_member_ids)
    await db.commit()
    return {"message": "Members successfully removed."}


@router.delete("/groups/{group_name}/leave", status_code=204)
async def leave_group(
    group_name: str = Path(..., description="Group name to leave"),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Allows a non-owner member to leave a group."""
    chat_service = ChatService(db)
    
    # 1. Find group by name
    group = await chat_service.get_group_by_name(group_name)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found.")
        
    # 🔥 FIX: Improved error message for owner leaving
    if group.creator_id == user_id:
        raise HTTPException(status_code=403, detail="Owner cannot leave the group. Transfer ownership or delete the group.")
        
    if not await chat_service.is_member(user_id, group.id):
        raise HTTPException(status_code=400, detail="You are not a member.")

    await chat_service.remove_member(group.id, user_id)
    await db.commit()
    return

# 🚀 NEW ENDPOINT: DELETE GROUP
@router.delete("/groups/{group_name}", status_code=204)
async def delete_group(
    group_name: str = Path(..., description="Group name to delete"),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Allows the group owner to delete the group and all associated data."""
    chat_service = ChatService(db)

    # 1. Find group by name
    group = await chat_service.get_group_by_name(group_name)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found.")

    # 2. Check if the user is the owner
    if group.creator_id != user_id:
        raise HTTPException(status_code=403, detail="Only the owner can delete the group.")

    # 3. Delete the group (This relies on chat_service.delete_group)
    await chat_service.delete_group(group.id)
    await db.commit()

    return # 204 No Content response


# ============================================================
# CHAT HISTORY ENDPOINTS (MODIFIED)
# ============================================================

# 🔥 FIX retained: Changed from Path to Query and from ID to Username to resolve 422 error
@router.get("/chat/one_to_one/history", response_model=List[MessageResponse])
async def get_chat_history_by_username(
    target_username: str = Query(..., description="Username of the user to get history with"),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve direct message history between two users by target username."""
    user_service = UserService(db)
    chat_service = ChatService(db)
    
    # 1. Look up target user by username to get their ID
    target_user = await user_service.get_user_by_username(target_username)
    if not target_user:
        raise HTTPException(status_code=404, detail=f"User '{target_username}' not found.")
    
    # 2. Get history using the current user's ID and the target user's ID
    history = await chat_service.get_one_to_one_history(user_id, target_user.id)
    
    # 3. Format and return the response
    return [
        MessageResponse(
            # 🛑 FIX APPLIED HERE: Changed 'message_id' to 'id' to match Pydantic model
            id=msg.id,
            sender_username=msg.sender.username,
            content=msg.content,
            timestamp=msg.timestamp,
        )
        for msg in history
    ]


# 🔥 MODIFIED retained: Changed path to use group_name as a Query parameter instead of group_id as a Path parameter
@router.get("/chat/group/history", response_model=List[MessageResponse])
async def get_group_chat_history_by_name( 
    group_name: str = Query(..., description="Name of the group to get history for"),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve chat history for a group by name."""
    chat_service = ChatService(db)
    
    # 1. Look up group by name
    group = await chat_service.get_group_by_name(group_name)
    if not group:
        # This fixes the history loading error you were seeing
        raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found.")
        
    # 2. Check membership
    if not await chat_service.is_member(user_id, group.id):
        raise HTTPException(status_code=403, detail="Not a member of this group.")
    
    # 3. Get history
    history = await chat_service.get_group_history(group.id)
    return [
        MessageResponse(
            # 🛑 FIX APPLIED HERE: Changed 'message_id' to 'id' to match Pydantic model
            id=msg.id,
            sender_username=msg.sender.username,
            content=msg.content,
            timestamp=msg.timestamp,
        )
        for msg in history
    ]


# ============================================================
# CLASS-BASED WEBSOCKET CONSUMER (MODIFIED)
# ============================================================

class ChatConsumer:
    """Handles all real-time chat logic via WebSocket."""

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.user_id: Optional[int] = None
        self.username: Optional[str] = None

    async def connect(self, token: str) -> bool:
        """Authenticate user via token and initialize group memberships. (MODIFIED)"""
        try:
            payload = SecurityService.decode_token(token)
            self.user_id = int(payload.sub)

            # Iterates through the database session dependency
            async for db in get_db():
                user_service = UserService(db)
                chat_service = ChatService(db) # <--- ADDED: Need chat_service to find groups
                user = await user_service.get_user_by_id(self.user_id)
                
                if not user:
                    await self.websocket.close(code=1008, reason="User not found.")
                    return False
                self.username = user.username
                
                # 🔥 FIX retained: Find all groups user belongs to and register them with the manager
                try:
                    user_groups = await chat_service.get_user_groups(self.user_id)
                    for group in user_groups:
                        manager.join_group(self.user_id, group.id)
                except AttributeError:
                    # Fallback if get_user_groups is not yet implemented in services.py
                    print("[WARN] ChatService.get_user_groups not found. Group broadcasts may fail.")
                
                await manager.connect(self.user_id, self.websocket)
                await manager.send_personal_message(
                    json.dumps({"type": "system", "content": f"Welcome, {self.username}!"}),
                    self.user_id,
                )
                return True

        except (JWTError, ValueError):
            await self.websocket.close(code=1008, reason="Invalid token.")
            return False
        except Exception:
            await self.websocket.close(code=1006, reason="Internal error.")
            return False

    async def receive_messages(self):
        """Listen for new incoming messages."""
        while True:
            try:
                data = await self.websocket.receive_text()
                async for db in get_db():
                    await self.handle_message(data, db)
            except WebSocketDisconnect:
                raise
            except Exception as e:
                print(f"[WS-LOOP-ERROR] {e}")

    async def handle_message(self, data: str, db: AsyncSession):
        """
        Process incoming message, including regular chat and typing indicators. (MODIFIED)
        """
        try:
            message_json = json.loads(data)
        except json.JSONDecodeError:
            await manager.send_personal_message(
                json.dumps({"type": "error", "content": "Invalid JSON"}), self.user_id
            )
            return

        # ----------------------------------------------------
        # 🔥 CORE CHANGES FOR TYPING INDICATORS
        # ----------------------------------------------------
        msg_type = message_json.get("type") 
        content = message_json.get("content")
        
        user_service = UserService(db)
        chat_service = ChatService(db)

        if msg_type in ("typing", "stopped_typing"):
            # The client sends: {"type": "typing", "target": "group_name" or "recipient_username"}
            target_name = message_json.get("target")
            
            if not target_name:
                return # Ignore status messages without a target

            # Message structure to broadcast for status
            status_message = json.dumps({
                "type": msg_type,
                "sender_username": self.username,
                "target": target_name
            })
            
            # 1. Check for Group Status
            group = await chat_service.get_group_by_name(target_name)
            if group and await chat_service.is_member(self.user_id, group.id):
                await manager.broadcast_typing_status(
                    status_message, 
                    group_id=group.id, 
                    exclude_user_id=self.user_id
                )
                return
                
            # 2. Check for One-to-One Status
            target_user = await user_service.get_user_by_username(target_name)
            if target_user:
                # We need to ensure the sender is actively looking at the target.
                # Since we don't have active chat session tracking, we just send it if the target is connected.
                await manager.broadcast_typing_status(
                    status_message, 
                    target_user_id=target_user.id, 
                    exclude_user_id=self.user_id
                )
                return
                
            return # Target not found or sender not member of group, ignore status
        
        # ----------------------------------------------------
        # REGULAR CHAT MESSAGE LOGIC CONTINUES BELOW
        # ----------------------------------------------------
        
        recipient_username = message_json.get("recipient_username") 
        group_name = message_json.get("group_name") 
        
        is_one_to_one = msg_type == "one_to_one"
        is_group = msg_type == "group"

        # General required check
        if not all([msg_type, content]):
             await manager.send_personal_message(
                 json.dumps({"type": "error", "content": "Missing message type or content"}), self.user_id
               )
             return
        
        # Specific target check
        if is_one_to_one and not recipient_username:
            await manager.send_personal_message(
                json.dumps({"type": "error", "content": "Missing recipient_username for one_to_one chat"}), self.user_id
            )
            return
        
        if is_group and not group_name:
            await manager.send_personal_message(
                json.dumps({"type": "error", "content": "Missing group_name for group chat"}), self.user_id
            )
            return

        # Prepare response message structure for chat messages
        formatted_msg = {
            "type": msg_type,
            "sender": self.username, 
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            if is_one_to_one:
                # 1. Look up target user by username
                target_user = await user_service.get_user_by_username(recipient_username)
                if not target_user:
                    await manager.send_personal_message(
                        json.dumps({"type": "error", "content": f"User '{recipient_username}' not found"}),
                        self.user_id,
                    )
                    return

                target_user_id = target_user.id
                
                # 2. Save message to DB
                await chat_service.save_one_to_one_message(self.user_id, target_user_id, content)
                
                # 3. Send response
                response = json.dumps({**formatted_msg, "recipient_username": recipient_username})
                await manager.send_personal_message(response, self.user_id)
                if self.user_id != target_user_id:
                    await manager.send_personal_message(response, target_user_id)
                await db.commit()

            elif is_group:
                # 1. Look up group by name
                group = await chat_service.get_group_by_name(group_name)
                if not group:
                    # 🔥 FIX retained: Send error to user if group is not found
                    await manager.send_personal_message(
                        json.dumps({"type": "error", "content": f"Group '{group_name}' not found"}),
                        self.user_id,
                    )
                    return

                # 2. Check membership
                if not await chat_service.is_member(self.user_id, group.id):
                    await manager.send_personal_message(
                        json.dumps({"type": "error", "content": "Not a member of this group."}),
                        self.user_id,
                    )
                    return
                
                # 3. Save message to DB
                await chat_service.save_group_message(group.id, self.user_id, content)
                
                # 4. Broadcast response
                response = json.dumps({**formatted_msg, "group": group_name})
                # Exclude self from broadcast, then send to self for immediate display (cleaner UX)
                await manager.broadcast_group_message(response, group.id, exclude_user_id=self.user_id) 
                await manager.safe_send(self.user_id, response) # Send to self for confirmation
                await db.commit()

            else:
                await manager.send_personal_message(
                    json.dumps({"type": "error", "content": "Unsupported chat type"}), self.user_id
                )

        except Exception as e:
            await db.rollback()
            print(f"[WS-DB-ERROR] {type(e).__name__}: {e}")
            await manager.send_personal_message(
                json.dumps({"type": "error", "content": "Error saving message"}), self.user_id
            )


# ============================================================
# WEBSOCKET ROUTE
# ============================================================

@router.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = Query(None)):
    """Main WebSocket endpoint for chat."""
    token = token or websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008, reason="Token required.")
        return

    consumer = ChatConsumer(websocket)
    try:
        connected = await consumer.connect(token)
        if not connected:
            return
        await consumer.receive_messages()

    except WebSocketDisconnect:
        if consumer.user_id:
            manager.disconnect(consumer.user_id)
        print(f"[WS] User {consumer.user_id} disconnected.")

    except Exception as e:
        if consumer.user_id:
            manager.disconnect(consumer.user_id)
        print(f"[WS-ERROR] {type(e).__name__}: {e}")