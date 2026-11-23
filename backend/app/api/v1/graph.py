from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.account import Account
from app.models.transaction import Transaction
from app.models.risk_score import RiskScore

router = APIRouter()

@router.get("/graph/network")
def network(hops: int = Query(1), db: Session = Depends(get_db)):
    accounts = db.query(Account).all()
    txs = db.query(Transaction).all()
    nodes = [{"data": {"id": str(a.id), "label": a.account_number, "risk_tier": a.risk_tier, "is_flagged": a.is_flagged}} for a in accounts]
    edges = [{"data": {"source": str(t.source_account_id), "target": str(t.destination_account_id), "label": str(t.amount)}} for t in txs]
    return {"nodes": nodes, "edges": edges}
