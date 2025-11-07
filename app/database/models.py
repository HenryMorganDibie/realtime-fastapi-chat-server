from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, select
from sqlalchemy.orm import relationship, declarative_base

# Base class for all ORM models
Base = declarative_base()

class UserModel(Base):
    """Database model for users."""
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    # 🌟 FIX: Added the required 'email' column 🌟
    email = Column(String, unique=True, index=True)
    # ---------------------------------------------
    hashed_password = Column(String)
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    sent_messages = relationship("OneToOneMessageModel", foreign_keys="OneToOneMessageModel.sender_id", back_populates="sender", cascade="all, delete-orphan")
    received_messages = relationship("OneToOneMessageModel", foreign_keys="OneToOneMessageModel.receiver_id", back_populates="receiver", cascade="all, delete-orphan")
    group_memberships = relationship("GroupMembershipModel", back_populates="user", cascade="all, delete-orphan")
    group_messages = relationship("GroupMessageModel", back_populates="sender", cascade="all, delete-orphan")

class GroupModel(Base):
    """Database model for chat groups."""
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    is_private = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    members = relationship("GroupMembershipModel", back_populates="group", cascade="all, delete-orphan")
    messages = relationship("GroupMessageModel", back_populates="group", cascade="all, delete-orphan")

class GroupMembershipModel(Base):
    """Database model for many-to-many relationship between users and groups."""
    __tablename__ = "group_memberships"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    group_id = Column(Integer, ForeignKey("groups.id"), primary_key=True)

    user = relationship("UserModel", back_populates="group_memberships")
    group = relationship("GroupModel", back_populates="members")
    joined_at = Column(DateTime, default=datetime.utcnow)

class OneToOneMessageModel(Base):
    """Database model for one-to-one messages."""
    __tablename__ = "one_to_one_messages"
    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"))
    receiver_id = Column(Integer, ForeignKey("users.id"))
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    is_read = Column(Integer, default=0)

    sender = relationship("UserModel", foreign_keys=[sender_id], back_populates="sent_messages")
    receiver = relationship("UserModel", foreign_keys=[receiver_id], back_populates="received_messages")

class GroupMessageModel(Base):
    """Database model for group messages."""
    __tablename__ = "group_messages"
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"))
    sender_id = Column(Integer, ForeignKey("users.id"))
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    group = relationship("GroupModel", back_populates="messages")
    sender = relationship("UserModel", foreign_keys=[sender_id], back_populates="group_messages")