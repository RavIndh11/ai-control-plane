import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON
from database import Base, engine

class DBComplianceEvidence(Base):
    __tablename__ = "compliance_evidence"

    evidence_id      = Column(String(36),  primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id        = Column(String(64),  index=True,  nullable=False)
    control_id       = Column(String(100), index=True,  nullable=False)
    source_component = Column(String(100), nullable=False)
    event_type       = Column(String(100), nullable=False)
    severity         = Column(String(20),  index=True,  nullable=False)
    payload          = Column(JSON,        nullable=False)
    minio_object_path= Column(String(512), nullable=True)
    evidence_hmac    = Column(String(64),  nullable=True)
    created_at       = Column(DateTime,    default=datetime.utcnow)

Base.metadata.create_all(bind=engine)
