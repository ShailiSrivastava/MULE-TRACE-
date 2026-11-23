from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.alert import DetectionAlert
from app.models.case import AuditLog

router = APIRouter()

@router.get("/alerts")
def list_alerts(severity: str = None, db: Session = Depends(get_db)):
    q = db.query(DetectionAlert)
    if severity:
        q = q.filter(DetectionAlert.severity == severity)
    return [{"id": a.id, "alert_ref": a.alert_ref, "severity": a.severity, "status": a.status, "risk_score": a.risk_score} for a in q.all()]

@router.patch("/alerts/{alert_id}")
def update_alert(alert_id: int, payload: dict, db: Session = Depends(get_db)):
    a = db.query(DetectionAlert).get(alert_id)
    if not a:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="not found")
    a.status = payload.get("status", a.status)
    db.add(AuditLog(action="update_alert", entity_type="alert", entity_id=a.id, details=str(payload)))
    db.commit()
    return {"id": a.id, "status": a.status}
