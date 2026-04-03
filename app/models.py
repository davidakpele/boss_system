# app/models.py
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, ForeignKey,
    Float, JSON, Enum as SAEnum
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
import enum

Base = declarative_base()


class UserRole(str, enum.Enum):
    super_admin = "super_admin"
    admin = "admin"
    manager = "manager"
    staff = "staff"
    new_employee = "new_employee"


class AccessLevel(str, enum.Enum):
    all_staff = "all_staff"
    restricted = "restricted"
    confidential = "confidential"


class DocStatus(str, enum.Enum):
    draft = "draft"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    department = Column(String(100))
    role = Column(SAEnum(UserRole, name="userrole"), default=UserRole.staff)
    is_active = Column(Boolean, default=True)
    is_online = Column(Boolean, default=False)
    avatar_color = Column(String(20), default="#6366f1")
    onboarding_complete = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    sent_messages = relationship("Message", foreign_keys="Message.sender_id", back_populates="sender")
    documents = relationship("Document", back_populates="author", foreign_keys="Document.author_id")
    audit_logs = relationship("AuditLog", back_populates="user")
    onboarding_progress = relationship("OnboardingProgress", back_populates="user")


class Channel(Base):
    __tablename__ = "channels"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    channel_type = Column(String(50), default="department")
    department = Column(String(100))
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_activity_at = Column(DateTime(timezone=True), nullable=True)   # NEW: tracks last message time

    messages = relationship("Message", back_populates="channel")
    members = relationship("ChannelMember", back_populates="channel")


class ChannelMember(Base):
    __tablename__ = "channel_members"
    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    joined_at = Column(DateTime(timezone=True), server_default=func.now())

    channel = relationship("Channel", back_populates="members")
    user = relationship("User")


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"))
    sender_id = Column(Integer, ForeignKey("users.id"))
    content = Column(Text, nullable=True)
    message_type = Column(String(50), default="text")
    file_url = Column(String(500))
    file_name = Column(String(255))
    file_size = Column(Integer)
    reply_to_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    reply_to_sender = Column(String(255), nullable=True)
    reply_to_content = Column(Text, nullable=True)
    is_ai_extracted = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    edited_at = Column(DateTime(timezone=True), nullable=True)

    channel = relationship("Channel", back_populates="messages")
    sender = relationship("User", foreign_keys=[sender_id], back_populates="sent_messages")
    reply_to = relationship("Message", remote_side="Message.id")

class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    content = Column(Text)
    description = Column(Text)
    department = Column(String(100))
    access_level = Column(SAEnum(AccessLevel, name="accesslevel"), default=AccessLevel.all_staff)
    status = Column(SAEnum(DocStatus, name="docstatus"), default=DocStatus.draft)
    author_id = Column(Integer, ForeignKey("users.id"))
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    file_path = Column(String(500))
    file_type = Column(String(50))
    original_filename = Column(String(255))
    is_compliance = Column(Boolean, default=False)
    compliance_score = Column(Float, default=0.0)
    tags = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    author = relationship("User", foreign_keys=[author_id], back_populates="documents")
    approver = relationship("User", foreign_keys=[approved_by])
    knowledge_chunks = relationship("KnowledgeChunk", back_populates="document")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    source_type = Column(String(50))
    content = Column(Text, nullable=False)
    summary = Column(Text)
    keywords = Column(JSON, default=list)
    department = Column(String(100))
    embedding = Column(Text, nullable=True)   # NEW: JSON-encoded float list
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Document", back_populates="knowledge_chunks")


class MeetingSummary(Base):
    """NEW: Auto-generated channel conversation summaries."""
    __tablename__ = "meeting_summaries"
    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"))
    summary = Column(Text, nullable=False)
    message_count = Column(Integer, default=0)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    generated_for_date = Column(String(20))  # YYYY-MM-DD

    channel = relationship("Channel")


class OnboardingConversation(Base):
    """NEW: Tracks onboarding AI chat sessions per employee."""
    __tablename__ = "onboarding_conversations"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    role = Column(String(20))   # user | assistant
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")


class AIConversation(Base):
    __tablename__ = "ai_conversations"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    session_id = Column(String(100), index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    messages = relationship("AIMessage", back_populates="conversation")
    user = relationship("User")


class AIMessage(Base):
    __tablename__ = "ai_messages"
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("ai_conversations.id"))
    role = Column(String(20))
    content = Column(Text, nullable=False)
    sources = Column(JSON, default=list)          # list of chunk_ids used
    source_chunks = Column(JSON, default=list)    # NEW: full chunk metadata for citations
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    conversation = relationship("AIConversation", back_populates="messages")


class ComplianceRecord(Base):
    __tablename__ = "compliance_records"
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"))
    regulation_type = Column(String(100))
    requirement = Column(Text)
    status = Column(String(50), default="identified")
    risk_level = Column(String(20), default="medium")
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Document")


class RiskItem(Base):
    __tablename__ = "risk_items"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    category = Column(String(100))
    likelihood = Column(Integer, default=3)
    impact = Column(Integer, default=3)
    risk_score = Column(Float, default=0.0)
    status = Column(String(50), default="open")
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    mitigation_plan = Column(Text)
    auto_detected = Column(Boolean, default=False)   # NEW: flagged if AI-detected
    source_type = Column(String(50), nullable=True)  # NEW: 'document' | 'message'
    source_id = Column(Integer, nullable=True)        # NEW: doc/channel id
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User")


class OnboardingStep(Base):
    __tablename__ = "onboarding_steps"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    step_order = Column(Integer, default=0)
    is_required = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Document")


class OnboardingProgress(Base):
    __tablename__ = "onboarding_progress"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    step_id = Column(Integer, ForeignKey("onboarding_steps.id"))
    completed = Column(Boolean, default=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="onboarding_progress")
    step = relationship("OnboardingStep")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String(100), nullable=False)
    resource_type = Column(String(100))
    resource_id = Column(Integer, nullable=True)
    details = Column(JSON, default=dict)
    ip_address = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="audit_logs")


class AppSettings(Base):
    __tablename__ = "app_settings"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text)
    description = Column(Text)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    department = Column(String(100))
    status = Column(String(50), default="todo")  # todo | in_progress | done
    priority = Column(String(20), default="medium")  # low | medium | high | urgent
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"))
    due_date = Column(DateTime(timezone=True), nullable=True)
    ai_priority_reason = Column(Text, nullable=True)
    position = Column(Integer, default=0)  # order within column
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    assignee = relationship("User", foreign_keys=[assigned_to])
    creator = relationship("User", foreign_keys=[created_by])


class MeetingRoom(Base):
    __tablename__ = "meeting_rooms"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    organizer_id = Column(Integer, ForeignKey("users.id"))
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    location = Column(String(255))
    agenda = Column(Text)
    ai_agenda_generated = Column(Boolean, default=False)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organizer = relationship("User")
    attendees = relationship("MeetingAttendee", back_populates="meeting")


class MeetingAttendee(Base):
    __tablename__ = "meeting_attendees"
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meeting_rooms.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    status = Column(String(20), default="invited")  # invited | accepted | declined

    meeting = relationship("MeetingRoom", back_populates="attendees")
    user = relationship("User")


class Announcement(Base):
    __tablename__ = "announcements"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    priority = Column(String(20), default="normal")  # normal | important | urgent
    created_by = Column(Integer, ForeignKey("users.id"))
    expires_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    author = relationship("User")
    reads = relationship("AnnouncementRead", back_populates="announcement")


class AnnouncementRead(Base):
    __tablename__ = "announcement_reads"
    id = Column(Integer, primary_key=True, index=True)
    announcement_id = Column(Integer, ForeignKey("announcements.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    read_at = Column(DateTime(timezone=True), server_default=func.now())

    announcement = relationship("Announcement", back_populates="reads")
    user = relationship("User")


class LeaveRequest(Base):
    __tablename__ = "leave_requests"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    leave_type = Column(String(50))  # annual | sick | maternity | paternity | unpaid | other
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    days_count = Column(Float, default=0)
    reason = Column(Text)
    status = Column(String(20), default="pending")  # pending | approved | rejected
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    review_note = Column(Text)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    employee = relationship("User", foreign_keys=[user_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by])


class ReportingLine(Base):
    """Who reports to whom."""
    __tablename__ = "reporting_lines"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("users.id"), unique=True)
    manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    employee = relationship("User", foreign_keys=[employee_id])
    manager = relationship("User", foreign_keys=[manager_id])
    
class IPAllowlist(Base):
    """Office IP ranges/addresses that are allowed to access the system."""
    __tablename__ = "ip_allowlist"
    id         = Column(Integer, primary_key=True, index=True)
    label      = Column(String(100), nullable=False)   # "Head Office", "VPN"
    ip_range   = Column(String(50),  nullable=False)   # "192.168.1.0/24" | "203.0.113.5"
    is_active  = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
 
    creator = relationship("User", foreign_keys=[created_by])
 
 
class OAuthAccount(Base):
    """Links a Google / Microsoft account to a local BOSS user."""
    __tablename__ = "oauth_accounts"
    id               = Column(Integer, primary_key=True, index=True)
    user_id          = Column(Integer, ForeignKey("users.id"))
    provider         = Column(String(50),  nullable=False)   # "google" | "microsoft"
    provider_user_id = Column(String(255), nullable=False)
    email            = Column(String(255))
    access_token     = Column(Text, nullable=True)
    refresh_token    = Column(Text, nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
 
    user = relationship("User")
 
 
class PushSubscription(Base):
    """One row per browser/device that has enabled push notifications."""
    __tablename__ = "push_subscriptions"
    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"))
    endpoint   = Column(Text, nullable=False)
    p256dh     = Column(Text, nullable=False)
    auth       = Column(Text, nullable=False)
    user_agent = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
 
    user = relationship("User")
 