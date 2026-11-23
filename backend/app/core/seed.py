import hashlib
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.user import User
from app.models.account import Account
from app.models.transaction import Transaction
from app.models.alert import DetectionAlert
from app.models.risk_score import RiskScore
from app.models.case import InvestigationCase, CaseAccount, AuditLog


def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def seed_demo_data(db: Session) -> None:
    if db.query(User).count() > 0:
        return

    user = User(email="analyst@muletrace.io", full_name="Lead Investigator", hashed_password=_hash("MuleTrace@2026"), role="analyst")
    db.add(user)
    db.flush()

    accounts = []
    names = [
        ("ACC-ORIGIN-001", "Originator LLC", "BANK01", "business", "low", False),
        ("ACC-MULE-001", "Intermediary Mule 1", "BANK02", "personal", "high", True),
        ("ACC-MULE-002", "Intermediary Mule 2", "BANK02", "personal", "high", True),
        ("ACC-MULE-003", "Intermediary Mule 3", "BANK02", "personal", "high", True),
        ("ACC-HUB-001", "Central Mule Hub", "BANK03", "business", "critical", True),
        ("ACC-OFF-001", "Offshore Cash-Out 1", "BANK04", "business", "critical", True),
        ("ACC-OFF-002", "Offshore Cash-Out 2", "BANK04", "business", "critical", True),
        ("ACC-NORM-001", "Normal Retailer A", "BANK01", "business", "low", False),
        ("ACC-NORM-002", "Normal Retailer B", "BANK01", "business", "low", False),
        ("ACC-NORM-003", "Normal Customer", "BANK05", "personal", "low", False),
        ("ACC-NORM-004", "Normal Customer 2", "BANK05", "personal", "low", False),
        ("ACC-NORM-005", "Normal Customer 3", "BANK05", "personal", "low", False),
    ]
    for num, holder, bank, typ, tier, flagged in names:
        a = Account(account_number=num, holder_name=holder, bank_code=bank, account_type=typ, risk_tier=tier, is_flagged=flagged)
        db.add(a)
        accounts.append(a)
    db.flush()

    acc_map = {a.account_number: a for a in accounts}

    now = datetime.now(timezone.utc)
    txs = [
        ("TX-001", "ACC-ORIGIN-001", "ACC-MULE-001", 9500.00, "USD", "wire", now - timedelta(days=2)),
        ("TX-002", "ACC-ORIGIN-001", "ACC-MULE-002", 9200.00, "USD", "wire", now - timedelta(days=2, hours=1)),
        ("TX-003", "ACC-ORIGIN-001", "ACC-MULE-003", 9800.00, "USD", "wire", now - timedelta(days=2, hours=2)),
        ("TX-004", "ACC-MULE-001", "ACC-HUB-001", 9400.00, "USD", "wire", now - timedelta(days=1, hours=20)),
        ("TX-005", "ACC-MULE-002", "ACC-HUB-001", 9100.00, "USD", "wire", now - timedelta(days=1, hours=19)),
        ("TX-006", "ACC-MULE-003", "ACC-HUB-001", 9700.00, "USD", "wire", now - timedelta(days=1, hours=18)),
        ("TX-007", "ACC-HUB-001", "ACC-OFF-001", 27000.00, "USD", "wire", now - timedelta(days=1, hours=10)),
        ("TX-008", "ACC-HUB-001", "ACC-OFF-002", 12000.00, "USD", "wire", now - timedelta(days=1, hours=9)),
        ("TX-009", "ACC-OFF-001", "ACC-ORIGIN-001", 5000.00, "USD", "wire", now - timedelta(days=1)),
        ("TX-010", "ACC-NORM-001", "ACC-NORM-003", 120.50, "USD", "card", now - timedelta(days=5)),
        ("TX-011", "ACC-NORM-002", "ACC-NORM-004", 89.99, "USD", "card", now - timedelta(days=4)),
        ("TX-012", "ACC-NORM-003", "ACC-NORM-005", 45.00, "USD", "ach", now - timedelta(days=3)),
        ("TX-013", "ACC-NORM-001", "ACC-NORM-002", 200.00, "USD", "ach", now - timedelta(days=2)),
        ("TX-014", "ACC-NORM-004", "ACC-NORM-001", 15.00, "USD", "card", now - timedelta(days=1)),
        ("TX-015", "ACC-MULE-001", "ACC-MULE-002", 1000.00, "USD", "wire", now - timedelta(hours=5)),
        ("TX-016", "ACC-MULE-002", "ACC-MULE-003", 1000.00, "USD", "wire", now - timedelta(hours=4)),
        ("TX-017", "ACC-MULE-003", "ACC-MULE-001", 1000.00, "USD", "wire", now - timedelta(hours=3)),
        ("TX-018", "ACC-HUB-001", "ACC-OFF-001", 5000.00, "USD", "wire", now - timedelta(hours=2)),
    ]
    for ref, src, dst, amt, cur, ch, ts in txs:
        t = Transaction(transaction_ref=ref, source_account_id=acc_map[src].id, destination_account_id=acc_map[dst].id, amount=amt, currency=cur, channel=ch, timestamp=ts, status="completed")
        db.add(t)
    db.flush()

    # alerts for flagged
    for ref in ["TX-001", "TX-002", "TX-003", "TX-004", "TX-005", "TX-006", "TX-007", "TX-008", "TX-009", "TX-015", "TX-016", "TX-017", "TX-018"]:
        t = db.query(Transaction).filter_by(transaction_ref=ref).first()
        sev = "critical" if ref in ("TX-007", "TX-008") else "high"
        a = DetectionAlert(alert_ref=f"ALERT-{ref}", account_id=t.source_account_id, transaction_id=t.id, pattern_type="structuring", severity=sev, risk_score=85.0, status="new", description="Flagged by detection engine")
        db.add(a)

    # risk scores
    for acc in accounts:
        score = 90.0 if acc.is_flagged else 15.0
        rs = RiskScore(account_id=acc.id, score=score, velocity_score=score, network_centrality_score=score, model_version="v1", evaluated_at=now)
        db.add(rs)

    # case
    case = InvestigationCase(title="Mule Ring Alpha", status="open", priority="high", notes="Auto-seeded", created_by=user.id)
    db.add(case)
    db.flush()
    for num in ["ACC-MULE-001", "ACC-MULE-002", "ACC-MULE-003", "ACC-HUB-001"]:
        db.add(CaseAccount(case_id=case.id, account_id=acc_map[num].id))
    db.add(AuditLog(user_id=user.id, action="seed", entity_type="system", entity_id=None, details="Demo data seeded"))