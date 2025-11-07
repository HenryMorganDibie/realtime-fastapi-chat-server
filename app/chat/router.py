# app/chat/router.py
import json
import asyncio
from typing import List, Optional, Dict, Set
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app import get_db
from app.core.security import SecurityService, get_current_user_id
from app.schemas.common import GroupCreate, GroupResponse, MessageResponse
from app.services import UserService, ChatService, ConnectionManager, manager # Import ConnectionManager/manager

# --- CHAT ROUTER INSTANCE ---
router = APIRouter(tags=["Chat & Messaging"]) # No prefix needed here, we'll add it in __init__.py

# --- GROUP & HISTORY ROUTES ---
@router.post("/groups", response_model=GroupResponse)
async def create_new_group(group: GroupCreate, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    user_service = UserService(db)
    chat_service = ChatService(db)

    member_ids = [user_id]
    for username in group.member_usernames:
        member = await user_service.get_user_by_username(username)
        if member and member.id not in member_ids:
            member_ids.append(member.id)
        elif not member:
            raise HTTPException(status_code=404, detail=f"User '{username}' not found.")

    new_group = await chat_service.create_group(group.name, member_ids)
    return GroupResponse(id=new_group.id, name=new_group.name, member_count=len(member_ids))

@router.get("/chat/one_to_one/history/{target_username}", response_model=List[MessageResponse])
async def get_chat_history(
    target_username: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    user_service = UserService(db)
    target_user = await user_service.get_user_by_username(target_username)
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")
    
    # 🚀 Using the optimized service method (Step 1 fix)
    history = await ChatService(db).get_one_to_one_history(user_id, target_user.id)
    
    out = []
    for msg in history:
        # 🚀 Using the optimized object access (Step 2 fix)
        out.append(MessageResponse(
            id=msg.id,
            sender_username=msg.sender.username,
            content=msg.content,
            timestamp=msg.timestamp
        ))
    return out


# --- CLASS-BASED WEBSOCKET CONSUMER ---
class ChatConsumer:
    def __init__(self, websocket: WebSocket, db: AsyncSession):
        self.websocket = websocket
        self.db = db
        self.user_service = UserService(db)
        self.chat_service = ChatService(db)
        self.user_id: Optional[int] = None
        self.username: Optional[str] = None

    async def connect(self, token: str) -> bool:
        # ... (Connect logic, same as before) ...
        payload = SecurityService.decode_token(token)
        self.user_id = int(payload.sub)
        user = await self.user_service.get_user_by_id(self.user_id)
        if not user:
            await self.websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return False
        self.username = user.username
        await manager.connect(self.user_id, self.websocket)
        await manager.send_personal_message(json.dumps({"type": "system", "content": f"Welcome, {self.username}!"}), self.user_id)
        return True

    async def receive_messages(self):
        # ... (Receive logic, same as before) ...
        while True:
            data = await self.websocket.receive_text()
            await self.handle_message(data)

    async def handle_message(self, data: str):
        # ... (Handle message logic, same as before) ...
        try:
            message_json = json.loads(data)
        except json.JSONDecodeError:
            await manager.send_personal_message(json.dumps({"type": "error", "content": "Invalid JSON"}), self.user_id)
            return

        msg_type = message_json.get("type")
        target = message_json.get("target")
        content = message_json.get("content")

        if not all([msg_type, target, content]):
            await manager.send_personal_message(json.dumps({"type": "error", "content": "Missing type, target, or content"}), self.user_id)
            return

        formatted_msg = {"sender": self.username, "content": content, "timestamp": datetime.utcnow().isoformat(), "type": msg_type}
        
        # Use a consistent response format for broadcast/send
        if msg_type == "one_to_one":
            receiver = await self.user_service.get_user_by_username(target)
            if not receiver:
                await manager.send_personal_message(json.dumps({"type": "error", "content": f"User '{target}' not found"}), self.user_id)
                return
            # Save message (Persistence)
            await self.chat_service.save_one_to_one_message(self.user_id, receiver.id, content)
            
            # Realtime Delivery: Send to self and receiver
            response_msg = json.dumps({**formatted_msg, "target": target})
            await manager.send_personal_message(response_msg, self.user_id)
            await manager.send_personal_message(response_msg, receiver.id)

        elif msg_type == "group":
            group = await self.chat_service.get_group_by_name(target)
            if not group:
                await manager.send_personal_message(json.dumps({"type": "error", "content": f"Group '{target}' not found"}), self.user_id)
                return
            if not await self.chat_service.is_member(self.user_id, group.id):
                await manager.send_personal_message(json.dumps({"type": "error", "content": "Not a member"}), self.user_id)
                return
            
            # Add user to in-memory group tracking (for immediate broadcast)
            manager.join_group(self.user_id, group.id)
            
            # Save message (Persistence)
            await self.chat_service.save_group_message(group.id, self.user_id, content)
            
            # Realtime Delivery: Broadcast
            response_msg = json.dumps({**formatted_msg, "group": target})
            await manager.broadcast_group_message(response_msg, group.id)
        
        else:
            await manager.send_personal_message(json.dumps({"type": "error", "content": "Unsupported message type"}), self.user_id)


@router.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = Query(None), db: AsyncSession = Depends(get_db)):
    if token is None:
        token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Pass the database session to the consumer instance
    consumer = ChatConsumer(websocket, db)
    try:
        connected = await consumer.connect(token)
        if not connected:
            return
        await consumer.receive_messages()
    except WebSocketDisconnect:
        manager.disconnect(consumer.user_id)
    except Exception:
        manager.disconnect(consumer.user_id)