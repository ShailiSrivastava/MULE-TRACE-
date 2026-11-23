import csv, io
from fastapi import APIRouter, Depends, UploadFile, File, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.account import Account
from app.models.transaction import Transaction
from app.services.detection_engine import evaluate_transaction

router = APIRouter()

@router.get("/transactions")
def list_transactions(search: str = None, status: str = None, db: Session = Depends(get_db)):
    q = db.query(Transaction)
    if status:
        q = q.filter(Transaction.status == status)
    txs = q.all()
    if search:
        txs = [t for t in txs if search.lower() in (t.transaction_ref or "").lower()]
    return [{"id": t.id, "transaction_ref": t.transaction_ref, "amount": float(t.amount), "status": t.status, "timestamp": str(t.timestamp)} for t in txs]

@router.post("/transactions")
def create_transaction(payload: dict, db: Session = Depends(get_db)):
    tx = Transaction(
        transaction_ref=payload["transaction_ref"],
        source_account_id=payload["source_account_id"],
        destination_account_id=payload["destination_account_id"],
        amount=payload["amount"],
        currency=payload.get("currency", "USD"),
        channel=payload.get("channel", "wire"),
        timestamp=payload.get("timestamp") or __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        status=payload.get("status", "completed"),
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    evaluate_transaction(db, tx)
    db.commit()
    return {"id": tx.id, "transaction_ref": tx.transaction_ref}

@router.post("/transactions/upload-csv")
async def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode()))
    created = 0
    for row in reader:
        src = db.query(Account).filter_by(account_number=row["source_account"]).first()
        if not src:
            src = Account(account_number=row["source_account"], holder_name=row["source_account"], bank_code="BANK", account_type="personal")
            db.add(src); db.flush()
        dst = db.query(Account).filter_by(account_number=row["destination_account"]).first()
        if not dst:
            dst = Account(account_number=row["destination_account"], holder_name=row["destination_account"], bank_code="BANK", account_type="personal")
            db.add(dst); db.flush()
        tx = Transaction(
            transaction_ref=row.get("transaction_ref") or row.get("transaction_id"),
            source_account_id=src.id,
            destination_account_id=dst.id,
            amount=float(row["amount"]),
            currency=row.get("currency", "USD"),
            channel=row.get("channel", "wire"),
            timestamp=__import__("datetime").datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")),
            status="completed",
        )
        db.add(tx); db.flush()
        evaluate_transaction(db, tx)
        created += 1
    db.commit()
    return {"ingested": created}
