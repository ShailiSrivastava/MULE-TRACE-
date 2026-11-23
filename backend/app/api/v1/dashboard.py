from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.transaction import Transaction
from app.models.alert import DetectionAlert
from app.models.case import InvestigationCase
from app.models.account import Account

router = APIRouter()

@router.get("/dashboard/overview")
def overview(db: Session = Depends(get_db)):
    total_volume = sum(float(t.amount) for t in db.query(Transaction).all())
    active_alerts = db.query(DetectionAlert).filter(DetectionAlert.status == "new").count()
    open_cases = db.query(InvestigationCase).filter(InvestigationCase.status == "open").count()
    flagged = db.query(Account).filter(Account.is_flagged == True).count()
    recent = db.query(DetectionAlert).order_by(DetectionAlert.created_at.desc()).limit(5).all()
    return {
        "total_monitored_volume": total_volume,
        "active_high_risk_alerts": active_alerts,
        "open_investigations": open_cases,
        "flagged_mule_networks": flagged,
        "recent_alerts": [{"id": a.id, "alert_ref": a.alert_ref, "severity": a.severity, "status": a.status} for a in recent],
    }
