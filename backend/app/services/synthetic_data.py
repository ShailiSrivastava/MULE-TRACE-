"""Deterministic synthetic records and atomic dataset generation workflow."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Account, Dataset, GroundTruthLabel, Transaction, User
from app.schemas.synthetic import (
    SyntheticGenerationRequest,
)
from app.services.dataset_access import (
    DatasetScopeNotFound,
    ResourceConflict,
    record_resource_audit,
)


@dataclass(frozen=True)
class SyntheticAccountRecord:
    id: UUID
    external_id: str
    account_type: str
    institution_code: str
    country_code: str


@dataclass(frozen=True)
class SyntheticTransactionRecord:
    id: UUID
    external_transaction_id: str
    sender_index: int
    receiver_index: int
    amount: Decimal
    currency: str
    occurred_at: datetime
    pattern: str | None


@dataclass(frozen=True)
class SyntheticRecords:
    accounts: tuple[SyntheticAccountRecord, ...]
    transactions: tuple[SyntheticTransactionRecord, ...]


def build_synthetic_records(
    dataset_id: UUID,
    request: SyntheticGenerationRequest,
) -> SyntheticRecords:
    """Generate the same record values and IDs for a dataset/seed pair."""

    rng = random.Random(request.seed)
    accounts = tuple(
        SyntheticAccountRecord(
            id=uuid5(dataset_id, f"synthetic:{request.seed}:account:{index}"),
            external_id=f"syn-{request.seed}-acct-{index:06d}",
            account_type=("business" if rng.random() < 0.2 else "personal"),
            institution_code=f"BANK-{rng.randrange(1, 25):02d}",
            country_code=rng.choice(("US", "GB", "DE", "SG", "CA", "AU")),
        )
        for index in range(request.account_count)
    )

    span = request.end_at - request.start_at
    events: list[tuple[int, int, Decimal, datetime, str | None]] = []

    def add_event(
        sender: int,
        receiver: int,
        amount: Decimal,
        offset_seconds: int,
        pattern: str | None,
    ) -> None:
        events.append(
            (
                sender,
                receiver,
                amount,
                request.start_at + timedelta(seconds=offset_seconds),
                pattern,
            )
        )

    patterns = set(request.patterns)
    if "rapid_successive" in patterns:
        for offset, (sender, receiver) in enumerate(((0, 1), (1, 0), (0, 1))):
            add_event(
                sender,
                receiver,
                Decimal("950.00"),
                offset * 60,
                "rapid_successive_transfer",
            )
    if "fan_in" in patterns:
        for index in range(1, 5):
            add_event(index, 0, Decimal(200 + index * 25), 240 + index * 60, "fan_in")
    if "fan_out" in patterns:
        for index in range(1, 5):
            add_event(0, index, Decimal(175 + index * 30), 600 + index * 60, "fan_out")
    if "circular" in patterns:
        for index in range(3):
            add_event(
                index,
                (index + 1) % 3,
                Decimal("410.00"),
                900 + index * 60,
                "circular_transfer",
            )
    if "multi_hop" in patterns:
        for index in range(4):
            add_event(
                index,
                index + 1,
                Decimal(300 + index * 50),
                1_200 + index * 60,
                "multi_hop_transfer",
            )
    if "unusual_amount" in patterns:
        add_event(0, 1, Decimal("9876543.21"), 1_500, "unusual_amount")
    if "unusual_frequency" in patterns:
        for index in range(3):
            add_event(2, 3, Decimal("85.00"), 1_560 + index, "unusual_frequency")

    while len(events) < request.transaction_count:
        sender = rng.randrange(request.account_count)
        receiver = rng.randrange(request.account_count - 1)
        if receiver >= sender:
            receiver += 1
        amount_cents = 500 + int((rng.random() ** 2) * 500_000)
        offset_seconds = rng.randrange(int(span.total_seconds()) + 1)
        events.append(
            (
                sender,
                receiver,
                Decimal(amount_cents) / Decimal(100),
                request.start_at + timedelta(seconds=offset_seconds),
                None,
            )
        )

    transactions = tuple(
        SyntheticTransactionRecord(
            id=uuid5(dataset_id, f"synthetic:{request.seed}:transaction:{index}"),
            external_transaction_id=f"syn-{request.seed}-txn-{index:08d}",
            sender_index=sender,
            receiver_index=receiver,
            amount=amount,
            currency=rng.choice(request.currencies),
            occurred_at=occurred_at,
            pattern=pattern,
        )
        for index, (sender, receiver, amount, occurred_at, pattern) in enumerate(events)
    )
    return SyntheticRecords(accounts=accounts, transactions=transactions)


def generate_dataset_data(
    db: Session,
    *,
    dataset_id: UUID,
    actor: User,
    request: SyntheticGenerationRequest,
) -> dict[str, int | UUID | bool | list[str]]:
    """Persist a complete generation atomically into an empty owned dataset."""

    dataset = db.scalar(
        select(Dataset).where(
            Dataset.id == dataset_id,
            Dataset.owner_id == actor.id,
        )
    )
    if dataset is None:
        raise DatasetScopeNotFound

    existing_accounts = (
        db.scalar(
            select(func.count(Account.id)).where(Account.dataset_id == dataset_id)
        )
        or 0
    )
    existing_transactions = (
        db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.dataset_id == dataset_id
            )
        )
        or 0
    )
    if existing_accounts or existing_transactions:
        raise ResourceConflict("Synthetic generation requires an empty dataset.")

    records = build_synthetic_records(dataset_id, request)
    accounts = [
        Account(
            id=record.id,
            dataset_id=dataset_id,
            external_id=record.external_id,
            account_type=record.account_type,
            institution_code=record.institution_code,
            country_code=record.country_code,
            metadata_json={"synthetic": True, "seed": request.seed},
        )
        for record in records.accounts
    ]
    account_ids = [record.id for record in records.accounts]
    transactions = [
        Transaction(
            id=record.id,
            dataset_id=dataset_id,
            sender_account_id=account_ids[record.sender_index],
            receiver_account_id=account_ids[record.receiver_index],
            external_transaction_id=record.external_transaction_id,
            amount=record.amount,
            currency=record.currency,
            transaction_type="transfer",
            channel="online",
            status="settled",
            occurred_at=record.occurred_at,
            metadata_json={
                "synthetic": True,
                "seed": request.seed,
                "pattern": record.pattern or "normal",
            },
        )
        for record in records.transactions
    ]
    labels = [
        GroundTruthLabel(
            id=uuid5(dataset_id, f"synthetic:{request.seed}:label:{index}"),
            dataset_id=dataset_id,
            transaction_id=record.id,
            label_code=record.pattern,
            label_scheme="muletrace_synthetic_v1",
            source="synthetic",
            confidence=Decimal("1.0000"),
            labeled_by_id=actor.id,
            metadata_json={"seed": request.seed, "generator_pattern": record.pattern},
        )
        for index, record in enumerate(records.transactions)
        if record.pattern is not None
    ]

    dataset.is_synthetic = True
    db.add_all(accounts)
    db.add_all(transactions)
    db.add_all(labels)
    record_resource_audit(
        db,
        actor_id=actor.id,
        event_type="dataset.synthetic_data.generated",
        entity_type="dataset",
        entity_id=dataset.id,
        dataset_id=dataset.id,
        fields=["accounts", "transactions", "ground_truth_labels"],
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ResourceConflict from exc

    return {
        "dataset_id": dataset_id,
        "seed": request.seed,
        "account_count": len(accounts),
        "transaction_count": len(transactions),
        "normal_transaction_count": len(transactions) - len(labels),
        "ground_truth_label_count": len(labels),
        "patterns": list(request.patterns),
        "is_synthetic": True,
    }
