from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.account import Account
from app.models.transaction import Transaction
from app.models.alert import DetectionAlert
from app.models.risk_score import RiskScore

def evaluate_transaction(db: Session, tx: Transaction):
    alerts = []
    # structuring
    if 8500 <= float(tx.amount) <= 9999.99:
        alerts.append(("structuring", "high", 80.0))
    # velocity: count recent tx from source in 1h
    recent = db.query(Transaction).filter(
        Transaction.source_account_id == tx.source_account_id,
        Transaction.timestamp >= tx.timestamp - timedelta(hours=1),
    ).count()
    if recent >= 3:
        alerts.append(("rapid_pass_through", "high", 75.0))
    # circular: destination sent to source within 3 hops? simplified: check if source appears as destination in recent tx from dst
    loop = db.query(Transaction).filter(
        Transaction.source_account_id == tx.destination_account_id,
        Transaction.destination_account_id == tx.source_account_id,
    ).first()
    if loop:
        alerts.append(("circular_loop", "critical", 95.0))
    for pattern, sev, score in alerts:
        db.add(DetectionAlert(alert_ref=f"ALERT-TX-{tx.id}-{pattern}", account_id=tx.source_account_id, transaction_id=tx.id, pattern_type=pattern, severity=sev, risk_score=score, status="new", description=pattern))
    db.flush()
    recalculate_account_risk(db, tx.source_account_id)
    recalculate_account_risk(db, tx.destination_account_id)

def recalculate_account_risk(db: Session, account_id: int):
    alerts = db.query(DetectionAlert).filter_by(account_id=account_id).all()
    score = min(100.0, 10.0 * len(alerts) + (5.0 if alerts else 0))
    rs = db.query(RiskScore).filter_by(account_id=account_id).first()
    if rs:
        rs.score = score
    else:
        db.add(RiskScore(account_id=account_id, score=score, evaluated_at=datetime.utcnow()))
    acc = db.query(Account).get(account_id)
    if acc:
        acc.is_flagged = score >= 50
        acc.risk_tier = "critical" if score >= 80 else ("high" if score >= 50 else ("medium" if score >= 25 else "low"))
    db.flush()
