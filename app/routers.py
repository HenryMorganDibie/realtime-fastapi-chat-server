# app/routers.py
import json
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr

from app import get_db
from app.core.security import SecurityService, get_current_user_id
from app.schemas.common import (
    UserCreate,
    UserDB,
    Token,
    GroupCreate,
    GroupResponse,
    MessageResponse,
)
from app.services import UserService, ChatService

# --- SCHEMAS ---
class UserPrecheck(BaseModel):
    username: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

# --- CONNECTION MANAGER ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, WebSocket] = {}  # user_id -> websocket
        self.group_members: dict[int, set[int]] = {}        # group_id -> set(user_ids)

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: int):
        self.active_connections.pop(user_id, None)
        for members in self.group_members.values():
            members.discard(user_id)

    async def send_personal_message(self, message: str, user_id: int):
        ws = self.active_connections.get(user_id)
        if ws:
            await ws.send_text(message)

    def join_group(self, user_id: int, group_id: int):
        if group_id not in self.group_members:
            self.group_members[group_id] = set()
        self.group_members[group_id].add(user_id)

    async def broadcast_group_message(self, message: str, group_id: int, exclude_user_id: int = None):
        members = self.group_members.get(group_id, set())
        for uid in members:
            if uid != exclude_user_id:
                await self.send_personal_message(message, uid)

manager = ConnectionManager()
router = APIRouter()


# --- AUTH ROUTES ---
@router.post("/auth/precheck", tags=["Auth"])
async def precheck_user(user: UserPrecheck, db: AsyncSession = Depends(get_db)):
    existing_user = await UserService(db).get_user_by_username(user.username)
    return {"exists": bool(existing_user)}

@router.post("/auth/register", response_model=UserDB, tags=["Auth"])
async def register_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    return await UserService(db).create_user(user)

@router.post("/auth/login", response_model=Token, tags=["Auth"])
async def login_for_access_token(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    user = await UserService(db).authenticate_user(user_data.username, user_data.password)
    access_token = SecurityService.create_token(user_id=user.id, token_type="access")
    refresh_token = SecurityService.create_token(user_id=user.id, token_type="refresh")
    return {"access_token": access_token, "token_type": "bearer", "refresh_token": refresh_token}

@router.post("/auth/refresh", response_model=Token, tags=["Auth"])
async def refresh_session(refresh_token: str = Body(...), db: AsyncSession = Depends(get_db)):
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

@router.get("/auth/check", response_model=UserDB, tags=["Auth"])
async def check_session(user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    user = await UserService(db).get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return UserDB.from_orm(user)


# --- FORGOT PASSWORD / RESET ---
@router.post("/auth/forgot-password", tags=["Auth"])
async def forgot_password(req: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    user = await UserService(db).get_user_by_email(req.email)
    if not user:
        raise HTTPException(status_code=404, detail="Email not registered")
    # Generate reset token valid for 30 mins
    reset_token = SecurityService.create_token(user_id=user.id, token_type="reset")
    # Here you would normally send an email with the token
    return {"reset_token": reset_token, "message": "Use this token to reset your password (send via email in production)"}

@router.post("/auth/reset-password", tags=["Auth"])
async def reset_password(req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    payload = SecurityService.decode_token(req.token)
    if payload.type != "reset":
        raise HTTPException(status_code=401, detail="Invalid reset token")
    user_id = int(payload.sub)
    user_service = UserService(db)
    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    hashed_password = SecurityService.hash_password(req.new_password)
    await user_service.update_password(user_id, hashed_password)
    return {"message": "Password updated successfully"}


# --- GROUP & HISTORY ROUTES ---
@router.post("/groups", response_model=GroupResponse, tags=["Groups"])
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

@router.get("/chat/one_to_one/history/{target_username}", response_model=List[MessageResponse], tags=["Chat History"])
async def get_chat_history(
    target_username: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    user_service = UserService(db)
    target_user = await user_service.get_user_by_username(target_username)
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")
    history = await ChatService(db).get_one_to_one_history(user_id, target_user.id)
    out = []
    for msg in history:
        sender = await user_service.get_user_by_id(msg.sender_id)
        out.append(MessageResponse(
            id=msg.id,
            sender_username=sender.username if sender else "unknown",
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
        while True:
            data = await self.websocket.receive_text()
            await self.handle_message(data)

    async def handle_message(self, data: str):
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
        response_msg = json.dumps(formatted_msg)

        if msg_type == "one_to_one":
            receiver = await self.user_service.get_user_by_username(target)
            if not receiver:
                await manager.send_personal_message(json.dumps({"type": "error", "content": f"User '{target}' not found"}), self.user_id)
                return
            await self.chat_service.save_one_to_one_message(self.user_id, receiver.id, content)
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
            manager.join_group(self.user_id, group.id)
            await self.chat_service.save_group_message(group.id, self.user_id, content)
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
