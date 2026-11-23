import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
import app.models  # noqa: F401


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_models_crud_and_constraints(db_session):
    from app.models.user import User
    from app.models.account import Account
    from app.models.transaction import Transaction
    from app.models.alert import DetectionAlert
    from app.models.risk_score import RiskScore
    from app.models.case import InvestigationCase, CaseAccount, AuditLog
    from sqlalchemy.exc import IntegrityError

    u = User(email="a@b.com", full_name="Alice", hashed_password="x")
    db_session.add(u)
    db_session.commit()

    acc = Account(account_number="ACC1", holder_name="H", bank_code="BC", account_type="checking")
    db_session.add(acc)
    db_session.commit()

    tx = Transaction(
        transaction_ref="TX1",
        source_account_id=acc.id,
        destination_account_id=acc.id,
        amount=10.5,
        channel="wire",
        timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    db_session.add(tx)
    db_session.commit()

    alert = DetectionAlert(
        alert_ref="AL1", account_id=acc.id, transaction_id=tx.id,
        pattern_type="structuring", severity="high", risk_score=80.0,
    )
    db_session.add(alert)
    db_session.commit()

    rs = RiskScore(account_id=acc.id, score=75.0, evaluated_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    db_session.add(rs)
    db_session.commit()

    case = InvestigationCase(title="Case1", created_by=u.id)
    db_session.add(case)
    db_session.commit()
    ca = CaseAccount(case_id=case.id, account_id=acc.id)
    db_session.add(ca)
    db_session.commit()

    log = AuditLog(user_id=u.id, action="create", entity_type="case", entity_id=case.id)
    db_session.add(log)
    db_session.commit()

    assert db_session.query(User).count() == 1
    assert db_session.query(Account).count() == 1
    assert db_session.query(Transaction).count() == 1
    assert db_session.query(DetectionAlert).count() == 1
    assert db_session.query(RiskScore).count() == 1
    assert db_session.query(InvestigationCase).count() == 1
    assert db_session.query(CaseAccount).count() == 1
    assert db_session.query(AuditLog).count() == 1

    # unique constraint
    db_session.add(User(email="a@b.com", full_name="B", hashed_password="y"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # check constraint amount
    bad_tx = Transaction(
        transaction_ref="TX2", source_account_id=acc.id, destination_account_id=acc.id,
        amount=0, channel="wire", timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    db_session.add(bad_tx)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # risk score range
    bad_rs = RiskScore(account_id=acc.id, score=150.0, evaluated_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    db_session.add(bad_rs)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
