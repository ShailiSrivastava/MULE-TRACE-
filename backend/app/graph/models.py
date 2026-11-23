"""Data contracts and bounds for the pure graph engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID


def normalize_utc(value: datetime, *, field_name: str = "timestamp") -> datetime:
    """Return an aware UTC datetime or reject an ambiguous timestamp."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset.")
    return value.astimezone(UTC)


def decimal_value(value: Decimal | int | str) -> Decimal:
    """Convert a monetary value without introducing binary float rounding."""

    if isinstance(value, bool | float):
        raise TypeError("Monetary values must be finite decimals.")
    try:
        amount = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Monetary values must be finite decimals.") from exc
    if not amount.is_finite():
        raise ValueError("Monetary values must be finite decimals.")
    return amount


@dataclass(frozen=True, slots=True)
class AccountRecord:
    """Minimal safe account fields needed to construct a graph node."""

    id: UUID
    dataset_id: UUID
    account_type: str | None = None
    institution_code: str | None = None
    country_code: str | None = None


@dataclass(frozen=True, slots=True)
class TransactionRecord:
    """Transaction fields needed to construct one independently keyed edge."""

    id: UUID
    dataset_id: UUID
    sender_account_id: UUID
    receiver_account_id: UUID
    amount: Decimal
    currency: str
    occurred_at: datetime
    transaction_type: str | None = None
    channel: str | None = None
    status: str | None = None


@dataclass(frozen=True, slots=True)
class GraphLimits:
    """Hard bounds preventing accidental unbounded graph or path work."""

    max_accounts: int = 100_000
    max_transactions: int = 500_000
    max_path_hops: int = 8
    max_paths: int = 100
    max_path_expansions: int = 100_000
    max_neighborhood_depth: int = 5

    def __post_init__(self) -> None:
        for name in (
            "max_accounts",
            "max_transactions",
            "max_path_hops",
            "max_paths",
            "max_path_expansions",
            "max_neighborhood_depth",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive.")


DEFAULT_GRAPH_LIMITS = GraphLimits()


class GraphLimitExceeded(ValueError):
    """Raised when the requested graph exceeds a configured construction bound."""


class GraphRecordError(ValueError):
    """Raised when source rows violate invariants needed for stable graph identity."""


@dataclass(frozen=True, slots=True)
class GraphFilters:
    """Graph filters; time ranges are half-open and amount bounds inclusive."""

    start_at: datetime | None = None
    end_at: datetime | None = None
    currency: str | None = None
    minimum_amount: Decimal | int | str | None = None
    maximum_amount: Decimal | int | str | None = None
    account_ids: frozenset[UUID] | None = None

    def __post_init__(self) -> None:
        start_at = (
            normalize_utc(self.start_at, field_name="start_at")
            if self.start_at is not None
            else None
        )
        end_at = (
            normalize_utc(self.end_at, field_name="end_at")
            if self.end_at is not None
            else None
        )
        if start_at is not None and end_at is not None and start_at >= end_at:
            raise ValueError("start_at must be earlier than end_at.")

        currency = self.currency
        if currency is not None:
            currency = currency.strip().upper()
            if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
                raise ValueError("currency must be a three-letter code.")

        minimum = (
            decimal_value(self.minimum_amount)
            if self.minimum_amount is not None
            else None
        )
        maximum = (
            decimal_value(self.maximum_amount)
            if self.maximum_amount is not None
            else None
        )
        if minimum is not None and minimum < 0:
            raise ValueError("minimum_amount cannot be negative.")
        if maximum is not None and maximum < 0:
            raise ValueError("maximum_amount cannot be negative.")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError("minimum_amount cannot exceed maximum_amount.")

        account_ids = (
            frozenset(self.account_ids) if self.account_ids is not None else None
        )
        if (
            account_ids is not None
            and len(account_ids) > DEFAULT_GRAPH_LIMITS.max_accounts
        ):
            raise GraphLimitExceeded(
                f"Account filters cannot exceed {DEFAULT_GRAPH_LIMITS.max_accounts} IDs."
            )

        object.__setattr__(self, "start_at", start_at)
        object.__setattr__(self, "end_at", end_at)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "minimum_amount", minimum)
        object.__setattr__(self, "maximum_amount", maximum)
        object.__setattr__(self, "account_ids", account_ids)

    def metadata(self) -> dict[str, str | bool | None]:
        """Return safe, JSON-ready filter metadata without account identifiers."""

        return {
            "start_at": self.start_at.isoformat().replace("+00:00", "Z")
            if self.start_at
            else None,
            "end_at": self.end_at.isoformat().replace("+00:00", "Z")
            if self.end_at
            else None,
            "currency": self.currency,
            "minimum_amount": format(self.minimum_amount, "f")
            if self.minimum_amount is not None
            else None,
            "maximum_amount": format(self.maximum_amount, "f")
            if self.maximum_amount is not None
            else None,
            "account_filter_applied": self.account_ids is not None,
        }


@dataclass(frozen=True, slots=True)
class AccountMetrics:
    account_id: UUID
    in_degree: int
    out_degree: int
    total_degree: int
    incoming_transaction_count: int
    outgoing_transaction_count: int
    total_transaction_count: int
    unique_incoming_counterparty_count: int
    unique_outgoing_counterparty_count: int
    total_unique_counterparty_count: int
    incoming_amount_by_currency: dict[str, Decimal]
    outgoing_amount_by_currency: dict[str, Decimal]


@dataclass(frozen=True, slots=True)
class TransactionActivity:
    account_id: UUID
    start_at: datetime
    end_at: datetime
    incoming_transaction_count: int
    outgoing_transaction_count: int
    total_transaction_count: int


@dataclass(frozen=True, slots=True)
class ComponentSummary:
    accounts: tuple[UUID, ...]

    @property
    def size(self) -> int:
        return len(self.accounts)


@dataclass(frozen=True, slots=True)
class NetworkMetrics:
    node_count: int
    edge_count: int
    directed_density: float


@dataclass(frozen=True, slots=True)
class PathTransaction:
    transaction_id: UUID
    source: UUID
    target: UUID
    amount: Decimal
    currency: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class GraphPath:
    accounts: tuple[UUID, ...]
    transactions: tuple[PathTransaction, ...]


@dataclass(frozen=True, slots=True)
class PathSearchResult:
    source_found: bool
    target_found: bool
    paths: tuple[GraphPath, ...]
    truncated: bool
    expanded_edges: int
