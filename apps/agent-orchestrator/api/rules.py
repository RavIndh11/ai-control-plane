"""
api/rules.py — Compliance rules CRUD routes.

Endpoints:
  GET    /rules
  POST   /rules
  DELETE /rules/{rule_id}
  PUT    /rules/{rule_id}/toggle
"""
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from auth.principal import get_principal
from db.session     import get_db

router = APIRouter(tags=["rules"])


class RuleCreate(BaseModel):
    pattern:    str
    control_id: str = "SOC2-CC-6.1"


def _db_dep(principal: Dict[str, Any] = Depends(get_principal)):
    yield from get_db(principal)


@router.get("/rules")
def get_rules(
    principal: Dict[str, Any] = Depends(get_principal),
    db: Session              = Depends(_db_dep),
):
    rows = db.execute(
        text("SELECT rule_id, pattern, is_active, control_id FROM compliance_rules")
    ).fetchall()
    return [
        {"rule_id": r[0], "pattern": r[1], "is_active": bool(r[2]), "control_id": r[3]}
        for r in rows
    ]


@router.post("/rules", status_code=201)
def create_rule(
    req: RuleCreate,
    principal: Dict[str, Any] = Depends(get_principal),
    db: Session              = Depends(_db_dep),
):
    rule_id = str(uuid.uuid4())
    db.execute(
        text("""
            INSERT INTO compliance_rules (rule_id, pattern, is_active, control_id)
            VALUES (:id, :pattern, 1, :ctrl)
        """),
        {"id": rule_id, "pattern": req.pattern, "ctrl": req.control_id},
    )
    db.commit()
    return {"rule_id": rule_id, "pattern": req.pattern, "is_active": True, "control_id": req.control_id}


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: str,
    principal: Dict[str, Any] = Depends(get_principal),
    db: Session              = Depends(_db_dep),
):
    db.execute(text("DELETE FROM compliance_rules WHERE rule_id = :id"), {"id": rule_id})
    db.commit()
    return {"status": "deleted", "rule_id": rule_id}


@router.put("/rules/{rule_id}/toggle")
def toggle_rule(
    rule_id: str,
    principal: Dict[str, Any] = Depends(get_principal),
    db: Session              = Depends(_db_dep),
):
    row = db.execute(
        text("SELECT is_active FROM compliance_rules WHERE rule_id = :id"), {"id": rule_id}
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    new_status = 0 if row[0] else 1
    db.execute(
        text("UPDATE compliance_rules SET is_active = :s WHERE rule_id = :id"),
        {"s": new_status, "id": rule_id},
    )
    db.commit()
    return {"rule_id": rule_id, "is_active": bool(new_status)}
