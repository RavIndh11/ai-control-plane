"""
db/models.py — SQLAlchemy ORM models for the Agent Orchestrator.
All tables live in this single module so they share one MetaData instance.
"""
from datetime import datetime
from sqlalchemy import (
    Column, String, DateTime, JSON, ForeignKey, Integer
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class DBAgentThread(Base):
    __tablename__ = "agent_threads"

    thread_id = Column(String(255), primary_key=True)
    tenant_id = Column(String(64), index=True, nullable=False)
    agent_type = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    checkpoints = relationship(
        "DBAgentCheckpoint",
        back_populates="thread",
        cascade="all, delete-orphan",
    )


class DBAgentCheckpoint(Base):
    __tablename__ = "agent_checkpoints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(
        String(255),
        ForeignKey("agent_threads.thread_id", ondelete="CASCADE"),
        nullable=False,
    )
    checkpoint_id = Column(String(255), index=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    step = Column(String(100), nullable=False)
    state_data = Column(JSON, nullable=False)

    thread = relationship("DBAgentThread", back_populates="checkpoints")


class DBComplianceRule(Base):
    __tablename__ = "compliance_rules"

    rule_id = Column(String(36), primary_key=True)
    pattern = Column(String(255), nullable=False)
    is_active = Column(Integer, default=1)  # 1 = active, 0 = inactive
    control_id = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
