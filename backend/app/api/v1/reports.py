import csv, io
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.transaction import Transaction
from app.models.alert import DetectionAlert
from app.models.account import Account

router = APIRouter()

@router.get("/reports/export")
def export(report_type: str = Query("transactions"), format: str = Query("json"), db: Session = Depends(get_db)):
    if report_type == "transactions":
        rows = [{"transaction_ref": t.transaction_ref, "amount": float(t.amount), "status": t.status} for t in db.query(Transaction).all()]
    elif report_type == "sar":
        rows = [{"alert_ref": a.alert_ref, "severity": a.severity, "status": a.status, "risk_score": a.risk_score} for a in db.query(DetectionAlert).all()]
    else:
        rows = [{"account_number": a.account_number, "risk_tier": a.risk_tier, "is_flagged": a.is_flagged} for a in db.query(Account).all()]
    if format == "csv":
        buf = io.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=report.csv"})
    return JSONResponse(content=rows)
