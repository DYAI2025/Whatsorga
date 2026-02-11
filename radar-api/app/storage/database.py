import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, Float, Boolean, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id = Column(String, nullable=False, index=True)
    chat_name = Column(String, nullable=True)
    sender = Column(String, nullable=False)
    text = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    audio_path = Column(String, nullable=True)
    is_transcribed = Column(Boolean, default=False)
    raw_payload = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Analysis(Base):
    __tablename__ = "analysis"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id"), nullable=False)
    sentiment_score = Column(Float, nullable=True)
    markers = Column(JSONB, nullable=True)
    marker_categories = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class DriftSnapshot(Base):
    __tablename__ = "drift_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id = Column(String, nullable=False)
    date = Column(DateTime, nullable=False)
    avg_sentiment = Column(Float, nullable=True)
    dominant_markers = Column(JSONB, nullable=True)
    message_count = Column(Integer, nullable=True)


class Thread(Base):
    __tablename__ = "threads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id = Column(String, nullable=False)
    theme = Column(String, nullable=True)
    message_ids = Column(JSONB, nullable=True)
    emotional_arc = Column(JSONB, nullable=True)
    status = Column(String, default="active")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Termin(Base):
    __tablename__ = "termine"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id"), nullable=True)
    title = Column(String, nullable=False)
    datetime_ = Column("datetime", DateTime(timezone=True), nullable=False)
    participants = Column(JSONB, nullable=True)
    confidence = Column(Float, nullable=True)
    caldav_uid = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class CaptureStats(Base):
    __tablename__ = "capture_stats"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id = Column(String, nullable=False, index=True, unique=True)
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)
    messages_captured_24h = Column(Integer, default=0)
    error_count_24h = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
