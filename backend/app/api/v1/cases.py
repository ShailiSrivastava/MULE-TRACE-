from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.case import InvestigationCase, CaseAccount, AuditLog

router = APIRouter()

@router.get("/cases")
def list_cases(db: Session = Depends(get_db)):
    return [{"id": c.id, "title": c.title, "status": c.status, "priority": c.priority} for c in db.query(InvestigationCase).all()]

@router.post("/cases")
def create_case(payload: dict, db: Session = Depends(get_db)):
    c = InvestigationCase(title=payload["title"], status=payload.get("status", "open"), priority=payload.get("priority", "medium"), notes=payload.get("notes", ""), created_by=payload.get("created_by"))
    db.add(c); db.flush()
    for aid in payload.get("account_ids", []):
        db.add(CaseAccount(case_id=c.id, account_id=aid))
    db.add(AuditLog(action="create_case", entity_type="case", entity_id=c.id, details=payload.get("title", "")))
    db.commit()
    return {"id": c.id, "title": c.title}

@router.patch("/cases/{case_id}")
def update_case(case_id: int, payload: dict, db: Session = Depends(get_db)):
    c = db.query(InvestigationCase).get(case_id)
    if not c:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="not found")
    if "status" in payload: c.status = payload["status"]
    if "notes" in payload: c.notes = payload["notes"]
    db.add(AuditLog(action="update_case", entity_type="case", entity_id=c.id, details=str(payload)))
    db.commit()
    return {"id": c.id, "status": c.status}
